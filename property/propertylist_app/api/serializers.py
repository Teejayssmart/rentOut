from django.contrib.auth.models import User

from rest_framework import serializers

from propertylist_app.models import (
    Room,
    RoomCategorie,
    Review,
    UserProfile,
    RoomImage,
    SavedRoom,
    MessageThread,
    Message,
)

from propertylist_app.validators import (
    validate_person_name,
    validate_age_18_plus,
    validate_avatar_image,
    normalize_uk_postcode,
    validate_listing_title,
    sanitize_html_description,
    validate_price,
    validate_available_from,
    validate_choice,
    validate_listing_photos,
    sanitize_search_text,
    validate_numeric_range,
    validate_radius_miles,
    validate_pagination,
    validate_ordering,
    normalise_price,
    normalise_phone,
    normalise_name,
    assert_not_duplicate_listing,
    assert_no_duplicate_files,
    enforce_user_caps,
)






class ReviewSerializer(serializers.ModelSerializer):
    review_user = serializers.StringRelatedField(read_only=True)
  
    class Meta:
        model = Review
        #exclude = ('review_user',)
        fields = "__all__"  
      

class RoomSerializer(serializers.ModelSerializer):
    # expose category name (read-only)
    category = serializers.CharField(source='category.name', read_only=True)
    distance_miles = serializers.SerializerMethodField(read_only=True)
    

    # ---- Field validators you already wrote ----
    def validate_title(self, value):
        return validate_listing_title(value)

    def validate_description(self, value):
        return sanitize_html_description(value)

    def validate_price_per_month(self, value):
        value = normalise_price(value)
        return validate_price(value, min_val=50.0, max_val=20000.0)

    def validate_location(self, value):
        parts = str(value or "").strip().split()
        if not parts:
            raise serializers.ValidationError("Location is required.")
        postcode_guess = parts[-1]
        normalize_uk_postcode(postcode_guess)  # raises if invalid
        return value

    def validate_available_from(self, value):
        return validate_available_from(value)

    def validate_property_type(self, value):
        allowed = {c[0] for c in Room._meta.get_field("property_type").choices}
        return validate_choice(value, allowed, label="property_type")

    def validate_image(self, value):
        validate_listing_photos([value])
        assert_no_duplicate_files([value])
        return value

    # ---- Object-level validation (merged) ----
    def validate(self, attrs):
        price = attrs.get("price_per_month")
        bills_included = attrs.get("bills_included")
        available_from = attrs.get("available_from")

        # price sanity (if present in partial updates)
        if price is not None:
            validate_price(price, min_val=50.0, max_val=20000.0)

        # bills_included guard
        if bills_included and price is not None and float(price) < 100.0:
            raise serializers.ValidationError({
                "bills_included": "Bills cannot be included for such a low price."
            })

        # non-negative integers
        for field in ("number_of_bedrooms", "number_of_bathrooms"):
            val = attrs.get(field)
            if val is not None and int(val) < 0:
                raise serializers.ValidationError({field: "Must be zero or a positive integer."})

        # availability guard
        if available_from is not None:
            validate_available_from(available_from)

        # duplicate listing detection (title + postcode from location)
        title = attrs.get("title") or getattr(self.instance, "title", "")
        location = attrs.get("location") or getattr(self.instance, "location", "")
        if title and location:
            parts = str(location).strip().split()
            if parts:
                pc_norm = normalize_uk_postcode(parts[-1])
                assert_not_duplicate_listing(
                    title=title,
                    postcode_normalised=pc_norm,
                    room_qs=Room.objects.all(),
                    exclude_room_id=getattr(self.instance, "pk", None),
                )

        # caps (on create only)
        if self.instance is None and self.context.get("request"):
            user = self.context["request"].user
            enforce_user_caps(
                user,
                listings_qs=Room.objects,
                max_listings=5
            )

        return attrs

    # keep your explicit field declarations (these just mirror the model types)
    property_type = serializers.ChoiceField(
        choices=[('flat','Flat'), ('house','House'), ('studio','Studio')],
        required=True
    )
    price_per_month = serializers.DecimalField(max_digits=10, decimal_places=2, required=True)
    available_from  = serializers.DateField(required=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Room
        fields = "__all__"
        
    def get_is_saved(self, obj):
        request = self.context.get("request")
        if not request or not request.user or not request.user.is_authenticated:
            return False
        return SavedRoom.objects.filter(user=request.user, room=obj.id).exists()    
        
    def get_distance_miles(self, obj):
        # Populated by the view; None if not provided
        val = getattr(obj, "distance_miles", None)
        return round(val, 2) if isinstance(val, (int, float)) else val   

    

class RoomCategorieSerializer(serializers.ModelSerializer):
        room_info = RoomSerializer(many=True, read_only=True)
        class Meta:
            model = RoomCategorie
            fields = "__all__"
            

            

class SearchFiltersSerializer(serializers.Serializer):
    # free-text
    q = serializers.CharField(required=False, allow_blank=True)

    # numeric ranges
    min_price = serializers.DecimalField(required=False, max_digits=10, decimal_places=2)
    max_price = serializers.DecimalField(required=False, max_digits=10, decimal_places=2)

    # geography
    postcode = serializers.CharField(required=False)
    radius_km = serializers.FloatField(required=False)

    # pagination / ordering
    limit = serializers.IntegerField(required=False)
    page = serializers.IntegerField(required=False)
    offset = serializers.IntegerField(required=False)
    ordering = serializers.CharField(required=False)  # e.g. "price_per_month,-available_from"

    # whitelist of fields the API allows clients to sort by
    ALLOWED_ORDER_FIELDS = {"price_per_month", "available_from", "created_at"}

    def validate_q(self, value):
        return sanitize_search_text(value)

    def validate_min_price(self, value):
        return validate_price(value, min_val=0.0, max_val=20000.0)

    def validate_max_price(self, value):
        return validate_price(value, min_val=0.0, max_val=20000.0)

    def validate_postcode(self, value):
        # normalise if provided
        return normalize_uk_postcode(value) if value else value

    def validate_radius_km(self, value):
        return validate_radius_km(value, max_km=100)

    def validate_ordering(self, value):
        return validate_ordering(value, self.ALLOWED_ORDER_FIELDS)

    def validate(self, attrs):
        # price range consistency
        validate_numeric_range(attrs.get("min_price"), attrs.get("max_price"),
                               label_min="min_price", label_max="max_price")

        # pagination rules
        validate_pagination(attrs.get("limit"), attrs.get("page"), attrs.get("offset"),
                            max_limit=50)

        # postcode requires radius if doing geo search (optional rule)
        if attrs.get("radius_km") and not attrs.get("postcode"):
            raise serializers.ValidationError({"postcode": "Postcode is required when using radius search."})

        return attrs   
    



# Registration
class RegistrationSerializer(serializers.ModelSerializer):
    password2 = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ["username", "email", "password", "password2"]
        extra_kwargs = {"password": {"write_only": True}}

    def validate(self, data):
        if data["password"] != data["password2"]:
            raise serializers.ValidationError("Passwords must match.")
        return data


# Login
class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


# Password reset request
class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


# Password reset confirm
class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True)


# User core
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name"]


# User profile extension
class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ["phone"]  # extend with dob, avatar later
        
        
class RoomImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoomImage
        fields = ["id", "room", "image"]
        read_only_fields = ["room"]
        
        
class MessageSerializer(serializers.ModelSerializer):
    sender = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Message
        fields = ["id", "thread", "sender", "body", "created_at"]
        read_only_fields = ["thread", "sender", "created_at"] 


class MessageThreadSerializer(serializers.ModelSerializer):
    participants = serializers.SlugRelatedField(
        slug_field="username",
        many=True,
        queryset=User.objects.all()
    )
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = MessageThread
        fields = ["id", "participants", "created_at", "last_message"]

    def get_last_message(self, obj):
        msg = obj.messages.order_by("-created_at").first()
        return MessageSerializer(msg).data if msg else None         
      



      
      
      
      
      
      
      
          
    



















