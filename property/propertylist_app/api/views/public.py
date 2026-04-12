import random

import json

from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


from django.conf import settings
from django.utils import timezone


from datetime import timedelta


from rest_framework import generics
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.permissions import AllowAny
from drf_spectacular.utils import (
    extend_schema,
    OpenApiParameter,
    OpenApiResponse,
    inline_serializer,
)
from drf_spectacular.types import OpenApiTypes



 
from propertylist_app.services.captcha import verify_captcha
from propertylist_app.services.geo import geocode_postcode_cached
from propertylist_app.api.schema_serializers import ErrorResponseSerializer
from propertylist_app.api.schema_helpers import (
    standard_response_serializer,
    standard_paginated_response_serializer,
)
from propertylist_app.api.serializers import (
    CitySummarySerializer,
    FindAddressSerializer,
    HomeSummarySerializer,
    PhoneOTPStartSerializer,
    PhoneOTPVerifySerializer,
    RoomSerializer,
    EmailOTPVerifySerializer,
    DetailResponseSerializer,
    EmailOTPResendSerializer,
)
from propertylist_app.models import Room, UserProfile, PhoneOTP, EmailOTP
from .common import ok_response, _wrap_response_success


from propertylist_app.api.pagination import StandardLimitOffsetPagination






class HomePageView(APIView):
    """
    GET /api/home/

    Returns everything the mobile/web home screen needs:
    - featured_rooms: top-rated, active listings
    - latest_rooms: newest active listings
    - popular_cities: cities with most listings (for the slider strip)
    - stats: high-level counters
    - app_links: iOS / Android URLs (from settings, if defined)
    """
    permission_classes = [AllowAny]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="HomePageOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "data": HomeSummarySerializer(),
                },
            )
        },
        description="Return homepage summary data including featured rooms, latest rooms, popular cities, stats, and app links.",
    )
    def get(self, request):
        today = timezone.now().date()

        base_rooms = (
            Room.objects.alive()
            .filter(status="active")
            .filter(Q(paid_until__isnull=True) | Q(paid_until__gte=today))
            .select_related("category", "property_owner")
        )

        # 1) Featured rooms – highest rating first
        featured_rooms_qs = base_rooms.order_by("-avg_rating", "-number_rating", "-created_at")[:6]

        # 2) Latest rooms – newest first
        latest_rooms_qs = base_rooms.order_by("-created_at")[:6]

        # 3) Popular cities for the “Explore the Most Popular Shared Homes” strip
        city_rows = (
            base_rooms
            .exclude(location__isnull=True)
            .exclude(location__exact="")
            .values("location")
            .annotate(room_count=Count("id"))
            .order_by("-room_count", "location")[:12]
        )
        popular_cities = [
            {"name": r["location"], "room_count": r["room_count"]}
            for r in city_rows
        ]

        # 4) High-level stats for the page (can be shown or hidden in UI)
        stats = {
            "total_active_rooms": base_rooms.count(),
            "total_landlords": UserProfile.objects.filter(role="landlord").count(),
            "total_seekers": UserProfile.objects.filter(role="seeker").count(),
        }

        # 5) Mobile app links – pulled from settings if you configure them
        app_links = {
            "ios": getattr(settings, "MOBILE_APP_IOS_URL", ""),
            "android": getattr(settings, "MOBILE_APP_ANDROID_URL", ""),
        }

        payload = {
            "featured_rooms": featured_rooms_qs,
            "latest_rooms": latest_rooms_qs,
            "popular_cities": popular_cities,
            "stats": stats,
            "app_links": app_links,
        }

        ser = HomeSummarySerializer(payload, context={"request": request})
        return ok_response(ser.data, status_code=status.HTTP_200_OK)




class CityListView(APIView):
    """
    GET /api/cities/

    Returns all distinct Room.location values (all cities / towns with listings)
    so the front-end can show a scrollable list and call search on click.

    Query params:
      ?q=Lon    -> filters by case-insensitive substring
    """
    permission_classes = [AllowAny]
    pagination_class = StandardLimitOffsetPagination

    @extend_schema(
        request=None,
        parameters=[
            OpenApiParameter(
                name="q",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter cities by case-insensitive substring.",
            ),
        ],
        responses={
            200: inline_serializer(
                name="CityListOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "data": CitySummarySerializer(many=True),
                },
            )
        },
        description="List cities. Returns ok_response envelope. Supports optional filtering with the 'q' query parameter.",
    )
    def get(self, request):
        q = (request.query_params.get("q") or "").strip()

        base_qs = (
            Room.objects.alive()
            .exclude(location__isnull=True)
            .exclude(location__exact="")
        )

        if q:
            base_qs = base_qs.filter(location__icontains=q)

        rows = (
            base_qs.values("location")
            .annotate(room_count=Count("id"))
            .order_by("location")
        )

        data = [
            {"name": r["location"], "room_count": r["room_count"]}
            for r in rows
        ]

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(data, request, view=self)
        ser = CitySummarySerializer(page, many=True)

        return _wrap_response_success(
            paginator.get_paginated_response(ser.data)
        )

    


class FindAddressResponseDataSerializer(serializers.Serializer):
    addresses = serializers.ListField(
        child=inline_serializer(
            name="FindAddressItem",
            fields={
                "id": serializers.CharField(),
                "label": serializers.CharField(),
            },
        )
    )


  
    
    
class FindAddressView(APIView):
    permission_classes = [permissions.AllowAny]
    versioning_class = None

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="postcode",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
                description="UK postcode to look up addresses for.",
            )
        ],
        responses={
            200: standard_response_serializer(
                "FindAddressResponse",
                FindAddressResponseDataSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            429: OpenApiResponse(response=ErrorResponseSerializer),
            502: OpenApiResponse(response=ErrorResponseSerializer),
            503: OpenApiResponse(response=ErrorResponseSerializer),
        },
        auth=[],
        description="Return real address suggestions for a UK postcode via getAddress.",
    )
    def get(self, request):
        postcode = (request.query_params.get("postcode") or "").strip().upper()

        if not postcode:
            return Response(
                {
                    "ok": False,
                    "message": "Query param 'postcode' is required.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            addresses = _fetch_ideal_postcodes_suggestions(postcode)
        except RuntimeError:
            return Response(
                {
                    "ok": False,
                    "message": "Address lookup is not configured.",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except HTTPError as exc:
            if exc.code == 400:
                return Response(
                    {
                        "ok": False,
                        "message": "Invalid postcode.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if exc.code == 404:
                return ok_response(
                    {"addresses": []},
                    message="Address suggestions retrieved successfully.",
                    status_code=status.HTTP_200_OK,
                )
            if exc.code == 401:
                return Response(
                    {
                        "ok": False,
                        "message": "Address provider authentication failed.",
                    },
                    status=status.HTTP_502_BAD_GATEWAY,
                )
            if exc.code == 402:
                return Response(
                    {
                        "ok": False,
                        "message": "Address lookup credits exhausted.",
                    },
                    status=status.HTTP_502_BAD_GATEWAY,
                )
            if exc.code == 429:
                return Response(
                    {
                        "ok": False,
                        "message": "Address lookup rate limited.",
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )

            return Response(
                {
                    "ok": False,
                    "message": "Address provider error.",
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except URLError:
            return Response(
                {
                    "ok": False,
                    "message": "Address provider unavailable.",
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except Exception:
            return Response(
                {
                    "ok": False,
                    "message": "Address lookup failed.",
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return ok_response(
            {"addresses": addresses},
            message="Address suggestions retrieved successfully.",
            status_code=status.HTTP_200_OK,
        )





class SearchRoomsView(generics.ListAPIView):

    """
    GET /api/search/rooms/

    Supports:
    - q                : free-text search
    - min_price        : minimum monthly price
    - max_price        : maximum monthly price
    - postcode         : UK postcode centre
    - radius_miles     : search radius around postcode
    - ordering         : default/newest/last_updated/price_asc/price_desc/distance_miles
    - property_types   : flat / house / studio (Advanced Search)
    - rooms_min/max    : minimum / maximum number_of_bedrooms (Advanced Search)
    - move_in_date     : earliest acceptable move-in date (Advanced Search)
    - min_rating       : minimum average rating (1–5)
    - max_rating       : maximum average rating (1–5)

    """
    serializer_class = RoomSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = StandardLimitOffsetPagination

    _ordered_ids = None
    _distance_by_id = None

    def get_queryset(self):
        params = self.request.query_params

        # Enforce postcode when radius is used (raises DRF ValidationError)
        if params.get("radius_miles") is not None and not (params.get("postcode") or "").strip():
            raise ValidationError({"postcode": "Postcode is required when using radius search."})

        q_text = (params.get("q") or "").strip()
        min_price = params.get("min_price")
        max_price = params.get("max_price")
        postcode = (params.get("postcode") or "").strip()
        raw_radius = params.get("radius_miles", 10)

        # ===== Advanced filters from query =====
        # “Rooms in existing shares”
        include_shared = params.get("include_shared")

        # “Rooms suitable for ages”
        min_age = params.get("min_age")
        max_age = params.get("max_age")

        # “Length of stay”
        min_stay = params.get("min_stay_months")
        max_stay = params.get("max_stay_months")

        # “Rooms for” and “Room sizes”
        room_for = (params.get("room_for") or "").strip()
        room_size = (params.get("room_size") or "").strip()

       

        qs = (
            Room.objects.alive()
            .select_related("category", "property_owner", "property_owner__profile")
            .prefetch_related(
                Prefetch(
                    "roomimage_set",
                    queryset=RoomImage.objects.filter(status="approved").order_by("id"),
                    to_attr="prefetched_approved_images",
                )
            )
        )

        today = timezone.now().date()
        qs = qs.filter(status="active").filter(
            Q(paid_until__isnull=True) | Q(paid_until__gte=today)
        )

        # ----- keyword search -----
        if q_text:
            qs = qs.filter(
                Q(title__icontains=q_text)
                | Q(description__icontains=q_text)
                | Q(location__icontains=q_text)
            )

        
        # ----- manual address filters (street / city) -----
        street = (params.get("street") or "").strip()
        if street:
            qs = qs.filter(location__icontains=street)

        city = (params.get("city") or "").strip()
        if city:
            qs = qs.filter(location__icontains=city)



        # ----- price filters -----
        if min_price is not None:
            try:
                qs = qs.filter(price_per_month__gte=int(min_price))
            except Exception:
                raise ValidationError({"min_price": "Must be an integer."})

        if max_price is not None:
            try:
                qs = qs.filter(price_per_month__lte=int(max_price))
            except Exception:
                raise ValidationError({"max_price": "Must be an integer."})



                # ----- bedroom count filters -----
        rooms_min_raw = params.get("rooms_min")
        rooms_max_raw = params.get("rooms_max")

        rooms_min_val = None
        rooms_max_val = None

        if rooms_min_raw is not None and str(rooms_min_raw).strip() != "":
            try:
                rooms_min_val = int(rooms_min_raw)
            except ValueError:
                raise ValidationError({"rooms_min": "Must be an integer."})

        if rooms_max_raw is not None and str(rooms_max_raw).strip() != "":
            try:
                rooms_max_val = int(rooms_max_raw)
            except ValueError:
                raise ValidationError({"rooms_max": "Must be an integer."})

        if rooms_min_val is not None and rooms_max_val is not None and rooms_min_val > rooms_max_val:
            raise ValidationError({"rooms_min": "rooms_min cannot be greater than rooms_max."})

        if rooms_min_val is not None:
            qs = qs.filter(number_of_bedrooms__gte=rooms_min_val)

        if rooms_max_val is not None:
            qs = qs.filter(number_of_bedrooms__lte=rooms_max_val)
        
        
        

        # ----- rating filters -----
        min_rating = params.get("min_rating")
        max_rating = params.get("max_rating")

        def _parse_rating(value, field_name):
            if value is None or str(value).strip() == "":
                return None
            try:
                r = float(value)
            except Exception:
                raise ValidationError({field_name: "Must be a number between 1 and 5."})
            if r < 1 or r > 5:
                raise ValidationError({field_name: "Must be between 1 and 5."})
            return r

        min_rating_val = _parse_rating(min_rating, "min_rating")
        max_rating_val = _parse_rating(max_rating, "max_rating")

        if min_rating_val is not None and max_rating_val is not None and min_rating_val > max_rating_val:
            raise ValidationError({"min_rating": "min_rating cannot be greater than max_rating."})

        if min_rating_val is not None:
            qs = qs.filter(avg_rating__gte=min_rating_val)

        if max_rating_val is not None:
            qs = qs.filter(avg_rating__lte=max_rating_val)

        
        user = getattr(self.request, "user", None)
        if user and user.is_authenticated:
            qs = qs.annotate(
                _is_saved=Exists(
                    SavedRoom.objects.filter(user=user, room_id=OuterRef("pk"))
                )
            )

        



        # Property preferences – boolean filters (support true and false)
        def parse_bool(v):
            if v is None:
                return None
            v = str(v).strip().lower()
            if v in {"true", "1", "yes"}:
                return True
            if v in {"false", "0", "no"}:
                return False
            return None

        furnished_b = parse_bool(params.get("furnished"))
        if furnished_b is not None:
            qs = qs.filter(furnished=furnished_b)

        bills_b = parse_bool(params.get("bills_included"))
        if bills_b is not None:
            qs = qs.filter(bills_included=bills_b)

        parking_b = parse_bool(params.get("parking_available"))
        if parking_b is not None:
            qs = qs.filter(parking_available=parking_b)


        # Property types (advanced search chips)
        property_types = params.getlist("property_types") or params.getlist("property_type")
        if property_types:
            qs = qs.filter(property_type__in=property_types)

        # ---- Advanced Search II (Option A) filters ----
        # move_in_date (UI) maps to Room.available_from:
        # seeker wants a room they can move into by selected date
        move_in_date = params.get("move_in_date")
        if move_in_date:
            try:
                qs = qs.filter(available_from__lte=move_in_date)
            except Exception:
                raise ValidationError({"move_in_date": "Invalid date format. Use YYYY-MM-DD."})

        bathroom_type = (params.get("bathroom_type") or "").strip()
        if bathroom_type and bathroom_type != "no_preference":
            qs = qs.filter(bathroom_type=bathroom_type)

        shared_living_space = (params.get("shared_living_space") or "").strip()
        if shared_living_space and shared_living_space != "no_preference":
            qs = qs.filter(shared_living_space=shared_living_space)

        smoking_allowed_in_property = (params.get("smoking_allowed_in_property") or "").strip()
        if smoking_allowed_in_property and smoking_allowed_in_property != "no_preference":
            qs = qs.filter(smoking_allowed_in_property=smoking_allowed_in_property)


        suitable_for = (params.get("suitable_for") or "").strip()
        if suitable_for and suitable_for != "no_preference":
            qs = qs.filter(suitable_for=suitable_for)

        max_occupants = params.get("max_occupants")
        if max_occupants:
            try:
                max_occ_int = int(max_occupants)
            except ValueError:
                raise ValidationError({"max_occupants": "Must be an integer."})
            qs = qs.filter(Q(max_occupants__isnull=True) | Q(max_occupants__gte=max_occ_int))

        hb_min = params.get("household_bedrooms_min")
        if hb_min:
            try:
                hb_min_int = int(hb_min)
            except ValueError:
                raise ValidationError({"household_bedrooms_min": "Must be an integer."})
            qs = qs.filter(Q(household_bedrooms_min__isnull=True) | Q(household_bedrooms_min__gte=hb_min_int))

        hb_max = params.get("household_bedrooms_max")
        if hb_max:
            try:
                hb_max_int = int(hb_max)
            except ValueError:
                raise ValidationError({"household_bedrooms_max": "Must be an integer."})
            qs = qs.filter(Q(household_bedrooms_max__isnull=True) | Q(household_bedrooms_max__lte=hb_max_int))

        household_type = (params.get("household_type") or "").strip()
        if household_type and household_type != "no_preference":
            qs = qs.filter(household_type=household_type)

        household_environment = (params.get("household_environment") or "").strip()
        if household_environment and household_environment != "no_preference":
            qs = qs.filter(household_environment=household_environment)

        pets_allowed = (params.get("pets_allowed") or "").strip()
        if pets_allowed and pets_allowed != "no_preference":
            qs = qs.filter(pets_allowed=pets_allowed)

        inclusive_household = (params.get("inclusive_household") or "").strip()
        if inclusive_household and inclusive_household != "no_preference":
            qs = qs.filter(inclusive_household=inclusive_household)

        accessible_entry = (params.get("accessible_entry") or "").strip()
        if accessible_entry and accessible_entry != "no_preference":
            qs = qs.filter(accessible_entry=accessible_entry)

        free_to_contact = parse_bool(params.get("free_to_contact"))
        if free_to_contact is not None:
            qs = qs.filter(free_to_contact=free_to_contact)
        

        photos_only = parse_bool(params.get("photos_only"))
        if photos_only:
            approved_photo_exists = RoomImage.objects.filter(
                room_id=OuterRef("pk"),
                status="approved",
            )
            qs = qs.annotate(
                _has_approved_photo=Exists(approved_photo_exists)
            ).filter(
                Q(_has_approved_photo=True) | (Q(image__isnull=False) & ~Q(image=""))
            )


        verified_only = parse_bool(params.get("verified_advertisers_only"))
        if verified_only:
            qs = qs.filter(property_owner__profile__advertiser_verified=True)
            
            
        # Advert by household (UserProfile.role_detail)
        advert_by_household = (params.get("advert_by_household") or "").strip()
        if advert_by_household and advert_by_household != "no_preference":
            qs = qs.filter(property_owner__profile__role_detail__iexact=advert_by_household)
            

        posted_within_days = params.get("posted_within_days")
        if posted_within_days:
            try:
                days_int = int(posted_within_days)
            except ValueError:
                raise ValidationError({"posted_within_days": "Must be an integer."})
            cutoff = timezone.now() - timedelta(days=days_int)
            qs = qs.filter(created_at__gte=cutoff)

            


        # ----- “Rooms in existing shares” -----
        if include_shared in {"1", "true", "True", "yes"}:
            qs = qs.filter(is_shared_room=True)

        # ----- “Rooms suitable for ages” -----
        # If user sends min_age, keep rooms whose max_age is blank OR >= min_age
        if min_age is not None and str(min_age).strip() != "":
            try:
                min_age_val = int(min_age)
            except ValueError:
                raise ValidationError({"min_age": "Must be an integer."})
            qs = qs.filter(Q(max_age__isnull=True) | Q(max_age__gte=min_age_val))

        # If user sends max_age, keep rooms whose min_age is blank OR <= max_age
        if max_age is not None and str(max_age).strip() != "":
            try:
                max_age_val = int(max_age)
            except ValueError:
                raise ValidationError({"max_age": "Must be an integer."})
            qs = qs.filter(Q(min_age__isnull=True) | Q(min_age__lte=max_age_val))

        # ----- “Length of stay” (months) -----
        if min_stay is not None and str(min_stay).strip() != "":
            try:
                min_stay_val = int(min_stay)
            except ValueError:
                raise ValidationError({"min_stay_months": "Must be an integer."})
            qs = qs.filter(Q(max_stay_months__isnull=True) | Q(max_stay_months__gte=min_stay_val))

        if max_stay is not None and str(max_stay).strip() != "":
            try:
                max_stay_val = int(max_stay)
            except ValueError:
                raise ValidationError({"max_stay_months": "Must be an integer."})
            qs = qs.filter(Q(min_stay_months__isnull=True) | Q(min_stay_months__lte=max_stay_val))

        # ----- “Rooms for” -----
        # Only filter when user picks a specific option (not 'any')
        if room_for and room_for != "any":
            qs = qs.filter(room_for=room_for)

        # ----- “Room sizes” -----
        if room_size and room_size != "dont_mind":
            qs = qs.filter(room_size=room_size)

        # Reset any prior state for distance ordering
        self._ordered_ids = None
        self._distance_by_id = None

        # ----- distance / radius handling -----
        if postcode:
            try:
                radius_miles = validate_radius_miles(raw_radius, max_miles=500)
            except ValidationError:
                radius_miles = 10

            lat, lon = geocode_postcode_cached(postcode)

            base_qs = qs.exclude(latitude__isnull=True).exclude(longitude__isnull=True)

            distances = []
            for r in base_qs.select_related(None).only("id", "latitude", "longitude"):
                d = haversine_miles(lat, lon, r.latitude, r.longitude)
                if d <= radius_miles:
                    distances.append((r.id, d))

            distances.sort(key=lambda t: t[1])
            ids_in_radius = [rid for rid, _ in distances]
            self._ordered_ids = ids_in_radius
            self._distance_by_id = {rid: d for rid, d in distances}
            qs = qs.filter(id__in=ids_in_radius)

        ordering_param = (params.get("ordering") or "").strip()

        # Map friendly front-end sort keys to real fields
        # Frontend options:
        #   default       -> lets backend decide
        #   newest        -> -created_at
        #   last_updated  -> -updated_at
        #   price_asc     -> price_per_month
        #   price_desc    -> -price_per_month
        ui_sort_map = {
            # Frontend "Default viewing order" → newest first
            "default": "-created_at",
            "newest": "-created_at",
            "last_updated": "-updated_at",
            "price_asc": "price_per_month",
            "price_desc": "-price_per_month",
            # optional: if FE ever sends this explicitly
            "distance": "distance_miles",
        }
        if ordering_param in ui_sort_map:
            ordering_param = ui_sort_map[ordering_param]

        if not ordering_param:
            # Backend default when no ordering is provided:
            # - If postcode search: by distance
            # - Otherwise: newest first
            ordering_param = "distance_miles" if postcode else "-created_at"


        # Defer distance ordering to list() when we have computed distances
        if ordering_param in {"distance_miles", "-distance_miles"} and self._ordered_ids is not None:
            pass
        else:
            allowed = {
                "price_per_month": "price_per_month",
                "-price_per_month": "-price_per_month",
                "avg_rating": "avg_rating",
                "-avg_rating": "-avg_rating",
                "created_at": "created_at",
                "-created_at": "-created_at",
                "updated_at": "updated_at",
                "-updated_at": "-updated_at",
            }
            mapped = allowed.get(ordering_param)
            if mapped:
                qs = qs.order_by(mapped)

        return qs
    
    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="q",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Free-text search across title, description, and location.",
            ),
            OpenApiParameter(
                name="min_price",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Minimum monthly price.",
            ),
            OpenApiParameter(
                name="max_price",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Maximum monthly price.",
            ),
            OpenApiParameter(
                name="postcode",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="UK postcode centre for radius search.",
            ),
            OpenApiParameter(
                name="radius_miles",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Search radius in miles around postcode.",
            ),
            OpenApiParameter(
                name="ordering",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Sort order. Supported values include default, newest, last_updated, price_asc, price_desc, distance.",
            ),
            OpenApiParameter(
                name="property_types",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                many=True,
                description="Property types filter.",
            ),
            OpenApiParameter(
                name="rooms_min",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Minimum number of bedrooms.",
            ),
            OpenApiParameter(
                name="rooms_max",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Maximum number of bedrooms.",
            ),
            OpenApiParameter(
                name="move_in_date",
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Earliest acceptable move-in date in YYYY-MM-DD format.",
            ),
            OpenApiParameter(
                name="min_rating",
                type=float,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Minimum average rating from 1 to 5.",
            ),
            OpenApiParameter(
                name="max_rating",
                type=float,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Maximum average rating from 1 to 5.",
            ),
            OpenApiParameter(
                name="street",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Street filter.",
            ),
            OpenApiParameter(
                name="city",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="City filter.",
            ),
            OpenApiParameter(
                name="furnished",
                type=bool,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by furnished true/false.",
            ),
            OpenApiParameter(
                name="bills_included",
                type=bool,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by bills included true/false.",
            ),
            OpenApiParameter(
                name="parking_available",
                type=bool,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by parking available true/false.",
            ),
            OpenApiParameter(
                name="bathroom_type",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Bathroom type filter.",
            ),
            OpenApiParameter(
                name="shared_living_space",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Shared living space filter.",
            ),
            OpenApiParameter(
                name="smoking_allowed_in_property",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Smoking allowed filter.",
            ),
            OpenApiParameter(
                name="suitable_for",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Suitable for filter.",
            ),
            OpenApiParameter(
                name="max_occupants",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Maximum occupants filter.",
            ),
            OpenApiParameter(
                name="household_bedrooms_min",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Minimum household bedrooms filter.",
            ),
            OpenApiParameter(
                name="household_bedrooms_max",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Maximum household bedrooms filter.",
            ),
            OpenApiParameter(
                name="household_type",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Household type filter.",
            ),
            OpenApiParameter(
                name="household_environment",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Household environment filter.",
            ),
            OpenApiParameter(
                name="pets_allowed",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Pets allowed filter.",
            ),
            OpenApiParameter(
                name="inclusive_household",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Inclusive household filter.",
            ),
            OpenApiParameter(
                name="accessible_entry",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Accessible entry filter.",
            ),
            OpenApiParameter(
                name="free_to_contact",
                type=bool,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by free to contact true/false.",
            ),
            OpenApiParameter(
                name="photos_only",
                type=bool,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Only return rooms with photos.",
            ),
            OpenApiParameter(
                name="verified_advertisers_only",
                type=bool,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Only return verified advertisers.",
            ),
            OpenApiParameter(
                name="advert_by_household",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Advert by household filter.",
            ),
            OpenApiParameter(
                name="posted_within_days",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Only return rooms posted within the given number of days.",
            ),
            OpenApiParameter(
                name="include_shared",
                type=bool,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Only include shared rooms.",
            ),
            OpenApiParameter(
                name="min_age",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Minimum suitable age.",
            ),
            OpenApiParameter(
                name="max_age",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Maximum suitable age.",
            ),
            OpenApiParameter(
                name="min_stay_months",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Minimum stay in months.",
            ),
            OpenApiParameter(
                name="max_stay_months",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Maximum stay in months.",
            ),
            OpenApiParameter(
                name="room_for",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Room for filter.",
            ),
            OpenApiParameter(
                name="room_size",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Room size filter.",
            ),
            OpenApiParameter(
                name="limit",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Maximum number of rooms to return.",
            ),
            OpenApiParameter(
                name="offset",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Number of rooms to skip before starting the result set.",
            ),
        ],
        responses={
            200: standard_paginated_response_serializer(
                "SearchRoomsResponse",
                RoomSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
        },
        description="Search rooms with filters, sorting, postcode radius search, and limit/offset pagination.",
    )
    def list(self, request, *args, **kwargs):
        """
        Preserve distance ordering (when postcode/radius search is used)
        and return wrapped success responses with backwards-compatible
        pagination keys: count, next, previous, results.
        """
        queryset = self.get_queryset()

        # Build ordered list if distance ordering is active
        if self._ordered_ids is not None and self._distance_by_id is not None:
            room_by_id = {obj.id: obj for obj in queryset}

            ordering_raw = (request.query_params.get("ordering") or "").strip()
            ui_sort_map = {
                "default": "-created_at",
                "newest": "-created_at",
                "last_updated": "-updated_at",
                "price_asc": "price_per_month",
                "price_desc": "-price_per_month",
                "distance": "distance_miles",
            }
            ordering = ui_sort_map.get(ordering_raw, ordering_raw)

            rid_list = self._ordered_ids
            if ordering == "-distance_miles":
                rid_list = list(reversed(rid_list))

            ordered_objs = []
            for rid in rid_list:
                obj = room_by_id.get(rid)
                if obj is not None:
                    obj.distance_miles = self._distance_by_id.get(rid)
                    ordered_objs.append(obj)
        else:
            ordered_objs = list(queryset)

        # DRF pagination
        page = self.paginate_queryset(ordered_objs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return _wrap_response_success(
                self.get_paginated_response(serializer.data)
            )

        # If pagination is disabled for some reason, return wrapped list
        serializer = self.get_serializer(ordered_objs, many=True)
        return ok_response(serializer.data, status_code=status.HTTP_200_OK)




class NearbyRoomsView(generics.ListAPIView):
    """
    GET /api/v1/rooms/nearby/?postcode=<UK_postcode>&radius_miles=<int>
    Miles only; attaches .distance_miles to each room.
    """
    serializer_class = RoomSerializer
    permission_classes = [AllowAny]
    pagination_class = StandardLimitOffsetPagination

    _ordered_ids = None
    _distance_by_id = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Room.objects.none()
        postcode_raw = (self.request.query_params.get("postcode") or "").strip()
        if not postcode_raw:
            raise ValidationError({"postcode": "Postcode is required."})

        radius_miles = validate_radius_miles(self.request.query_params.get("radius_miles", 10), max_miles=500)

        lat, lon = geocode_postcode_cached(postcode_raw)

        base_qs = Room.objects.alive().exclude(latitude__isnull=True).exclude(longitude__isnull=True)

        distances = []
        for r in base_qs.only("id", "latitude", "longitude"):
            d = haversine_miles(lat, lon, r.latitude, r.longitude)
            if d <= radius_miles:
                distances.append((r.id, d))

        distances.sort(key=lambda t: t[1])
        self._ordered_ids = [rid for rid, _ in distances]
        self._distance_by_id = {rid: d for rid, d in distances}

        return Room.objects.alive().filter(id__in=self._ordered_ids or [])
    
    
    
    
    @extend_schema(
            parameters=[
                OpenApiParameter(
                    name="postcode",
                    type=str,
                    location=OpenApiParameter.QUERY,
                    required=True,
                    description="UK postcode used as the search centre.",
                ),
                OpenApiParameter(
                    name="radius_miles",
                    type=int,
                    location=OpenApiParameter.QUERY,
                    required=False,
                    description="Search radius in miles. Defaults to 10.",
                ),
                OpenApiParameter(
                    name="limit",
                    type=int,
                    location=OpenApiParameter.QUERY,
                    required=False,
                    description="Maximum number of rooms to return.",
                ),
                OpenApiParameter(
                    name="offset",
                    type=int,
                    location=OpenApiParameter.QUERY,
                    required=False,
                    description="Number of rooms to skip before starting the result set.",
                ),
            ],
            responses={
                200: inline_serializer(
                    name="NearbyRoomsResponse",
                    fields={
                        "ok": serializers.BooleanField(),
                        "message": serializers.CharField(required=False, allow_null=True),
                        "data": inline_serializer(
                            name="NearbyRoomsPaginatedData",
                            fields={
                                "count": serializers.IntegerField(),
                                "next": serializers.CharField(allow_null=True),
                                "previous": serializers.CharField(allow_null=True),
                                "results": RoomSerializer(many=True),
                            },
                        ),
                    },
                ),
                400: inline_serializer(
                    name="NearbyRoomsBadRequestResponse",
                    fields={
                        "postcode": serializers.CharField(required=False),
                        "radius_miles": serializers.CharField(required=False),
                        "detail": serializers.CharField(required=False),
                    },
                ),
            },
            description="List nearby rooms for a UK postcode using mile-based radius search, with limit/offset pagination.",
        )
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        room_by_id = {obj.id: obj for obj in queryset}
        ordered_objs = []

        for rid in (self._ordered_ids or []):
            obj = room_by_id.get(rid)
            if obj is not None:
                obj.distance_miles = self._distance_by_id.get(rid)
                ordered_objs.append(obj)

        page = self.paginate_queryset(ordered_objs)
        if page is not None:
            ser = self.get_serializer(page, many=True)
            return _wrap_response_success(self.get_paginated_response(ser.data))

        ser = self.get_serializer(ordered_objs, many=True)
        return ok_response(ser.data, status_code=status.HTTP_200_OK)



class HealthCheckView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="HealthCheckResponse",
                fields={
                    "status": serializers.CharField(),
                    "db": serializers.BooleanField(),
                },
            )
        },
        auth=[],
        description="Health check endpoint.",
    )
    def get(self, request):
        # Minimal DB ping (read-only, fast)
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT 1")
            db_ok = True
        except Exception:
            db_ok = False
        return Response({"status": "ok", "db": db_ok}, status=status.HTTP_200_OK)




class EmailOTPVerifyView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "otp-verify"
    versioning_class = None

    @extend_schema(
        request=EmailOTPVerifySerializer,
        responses={
            200: inline_serializer(
                name="EmailOTPVerifyOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="EmailOTPVerifyData",
                        fields={"detail": serializers.CharField()},
                    ),
                },
            ),
            400: DetailResponseSerializer,
            429: DetailResponseSerializer,
        },
        auth=[],
        description="Verify a 6-digit email OTP code and mark the user's email as verified.",
    )
    def post(self, request):
        # 1) Validate input (user_id + 6-digit code)
        ser = EmailOTPVerifySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user_id = ser.validated_data["user_id"]
        code = ser.validated_data["code"]

        # 2) Load user or 404
        UserModel = get_user_model()
        user = get_object_or_404(UserModel, pk=user_id)

        # 3) Get latest active OTP for this user
        otp = (
            EmailOTP.objects
            .filter(
                user=user,
                purpose=EmailOTP.PURPOSE_EMAIL_VERIFY,
                used_at__isnull=True,
            )
            .order_by("-created_at")
            .first()
        )

        if not otp:
            return Response(
                {"detail": "No active code. Please resend."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 4) Expired?
        if otp.is_expired:
            return Response(
                {"detail": "Code expired. Please resend."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 5) Too many attempts?
        if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            return Response(
                {"detail": "Too many attempts. Resend a new code."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # 6) Wrong code → increment attempts and return 400
        if not otp.matches(code):
            otp.attempts = (otp.attempts or 0) + 1
            otp.save(update_fields=["attempts"])
            return Response(
                {"detail": "Invalid code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 7) Correct code → mark used + mark profile email_verified
        otp.mark_used()

        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.email_verified = True
        profile.email_verified_at = timezone.now()
        profile.save(update_fields=["email_verified", "email_verified_at"])

        return ok_response(
            {"detail": "Email verified."},
            status_code=status.HTTP_200_OK,
        )






class EmailOTPResendView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "otp-resend"
    versioning_class = None

    @extend_schema(
        request=EmailOTPResendSerializer,
        responses={
            200: inline_serializer(
                name="EmailOTPResendOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="EmailOTPResendData",
                        fields={"detail": serializers.CharField()},
                    ),
                },
            ),
            400: DetailResponseSerializer,
            429: DetailResponseSerializer,
        },
        auth=[],
        description="Resend a new email verification OTP code.",
    )
    def post(self, request):
        ser = EmailOTPResendSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        if getattr(settings, "ENABLE_CAPTCHA", False):
            token = (request.data.get("captcha_token") or "").strip()
            if not verify_captcha(token, request.META.get("REMOTE_ADDR", "")):
                return Response(
                    {"detail": "CAPTCHA verification failed."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        generic_response = ok_response(
            {"detail": "If the account exists, a new verification code has been sent."},
            status_code=status.HTTP_200_OK,
        )

        user = get_user_model().objects.filter(pk=ser.validated_data["user_id"]).first()
        if not user:
            return generic_response

        cache_key = f"otp_resend_{user.id}"
        if cache.get(cache_key):
            return generic_response

        cache.set(cache_key, 1, timeout=settings.OTP_RESEND_COOLDOWN_SECONDS)

        EmailOTP.objects.filter(
            user=user,
            purpose=EmailOTP.PURPOSE_EMAIL_VERIFY,
            used_at__isnull=True,
        ).update(used_at=timezone.now())

        from django.core import mail

        code = get_random_string(6, allowed_chars="0123456789")
        EmailOTP.create_for(
            user,
            code,
            ttl_minutes=settings.OTP_EXPIRY_MINUTES,
            purpose=EmailOTP.PURPOSE_EMAIL_VERIFY,
        )

        mail.send_mail(
            subject="Your new verification code",
            message=f"Your verification code is: {code}",
            from_email=None,
            recipient_list=[user.email],
            fail_silently=True,
        )

        return ok_response(
            {"detail": "If the account exists, a new verification code has been sent."},
            status_code=status.HTTP_200_OK,
        )
        
        
        
class PhoneOTPStartView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    versioning_class = None
    throttle_scope = "otp-resend"

    @extend_schema(
        request=PhoneOTPStartSerializer,
        responses={
            200: inline_serializer(
                name="PhoneOTPStartOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="PhoneOTPStartData",
                        fields={"detail": serializers.CharField()},
                    ),
                },
            ),
            400: DetailResponseSerializer,
            401: OpenApiResponse(description="Authentication required."),
            429: DetailResponseSerializer,
        },
        auth=[],
        description="Start phone OTP verification by sending a 6-digit code.",
    )
    def post(self, request):
        serializer = PhoneOTPStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if getattr(settings, "ENABLE_CAPTCHA", False):
            token = (request.data.get("captcha_token") or "").strip()
            if not verify_captcha(token, request.META.get("REMOTE_ADDR", "")):
                return Response(
                    {"detail": "CAPTCHA verification failed."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        phone = serializer.validated_data["phone"]

        from django.core.cache import cache

        cache_key = f"phone_otp_resend_{request.user.id}"
        if cache.get(cache_key):
            return Response(
                {"detail": "Too many requests. Please wait before requesting another code."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        cache.set(cache_key, 1, timeout=settings.OTP_RESEND_COOLDOWN_SECONDS)

        PhoneOTP.objects.filter(
            user=request.user,
            used_at__isnull=True,
        ).update(used_at=timezone.now())

        code = f"{random.randint(0, 999999):06d}"

        PhoneOTP.objects.create(
            user=request.user,
            phone=phone,
            code=code,
            expires_at=timezone.now() + timedelta(minutes=settings.OTP_EXPIRY_MINUTES),
        )

        return ok_response(
            {"detail": "OTP sent to phone."},
            status_code=status.HTTP_200_OK,
        )



class PhoneOTPVerifyView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    versioning_class = None
    throttle_scope = "otp-verify"

    @extend_schema(
        request=PhoneOTPVerifySerializer,
        responses={
            200: inline_serializer(
                name="PhoneOTPVerifyOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="PhoneOTPVerifyData",
                        fields={"detail": serializers.CharField()},
                    ),
                },
            ),
            400: DetailResponseSerializer,
            401: OpenApiResponse(description="Authentication required."),
        },
        auth=[],
        description="Verify a phone OTP code and mark the current user's phone number as verified.",
    )
    def post(self, request):
        serializer = PhoneOTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data["phone"]
        code = serializer.validated_data["code"]

        otp = (
            PhoneOTP.objects.filter(user=request.user, phone=phone, used_at__isnull=True)
            .order_by("-created_at")
            .first()
        )

        if not otp:
            return Response({"detail": "Invalid or expired OTP."}, status=status.HTTP_400_BAD_REQUEST)

        if otp.is_expired:
            return Response({"detail": "Invalid or expired OTP."}, status=status.HTTP_400_BAD_REQUEST)
        
        
        if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            return Response(
                {"detail": "Invalid or expired OTP."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        otp.attempts = int(otp.attempts or 0) + 1
        otp.save(update_fields=["attempts"])

        if otp.code != code:
            return Response({"detail": "Invalid or expired OTP."}, status=status.HTTP_400_BAD_REQUEST)

        otp.used_at = timezone.now()
        otp.save(update_fields=["used_at"])

        # update profile
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile.phone = phone
        profile.phone_verified = True
        profile.phone_verified_at = timezone.now()
        profile.save(update_fields=["phone", "phone_verified", "phone_verified_at"])

        return ok_response(
            {"detail": "Phone number verification complete."},
            status_code=status.HTTP_200_OK,
        )
        
        
                



    
