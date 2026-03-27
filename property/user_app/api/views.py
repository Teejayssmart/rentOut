from rest_framework.decorators import api_view  #,  permission_classes
# from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from rest_framework import status
# #from rest_framework_simplejwt.tokens import RefreshToken

from user_app.api.serializers import RegistrationSerializer
from user_app import models
from drf_spectacular.utils import extend_schema, OpenApiResponse
from propertylist_app.api.schema_serializers import StandardErrorResponseSerializer
from propertylist_app.api.schema_helpers import (
    standard_response_serializer,
    standard_list_response_serializer,
    standard_paginated_response_serializer,
)

from rest_framework import filters  # if not already imported
from propertylist_app.api.pagination import RoomPagination, RoomCPagination, RoomLOPagination

@api_view(["POST"])
def logout_view(request):
    if hasattr(request.user, "auth_token"):
        request.user.auth_token.delete()

    return Response(
        {"detail": "Logged out successfully."},
        status=status.HTTP_200_OK,
    )



@api_view(["POST"])
def registration_view(request):
    serializer = RegistrationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    account = serializer.save()
    token = Token.objects.get(user=account).key

    data = {
        "response": "Registration successful.",
        "username": account.username,
        "email": account.email,
        "token": token,
    }

    return Response(data, status=status.HTTP_201_CREATED)
                      