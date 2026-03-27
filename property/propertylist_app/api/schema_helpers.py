from drf_spectacular.utils import inline_serializer
from rest_framework import serializers


def standard_response_serializer(name: str, data_serializer):
    return inline_serializer(
        name=name,
        fields={
            "ok": serializers.BooleanField(default=True),
            "message": serializers.CharField(),
            "data": data_serializer,
        },
    )


def standard_list_response_serializer(name: str, item_serializer):
    return inline_serializer(
        name=name,
        fields={
            "ok": serializers.BooleanField(default=True),
            "message": serializers.CharField(),
            "data": item_serializer(many=True),
        },
    )


def paginated_data_serializer(name: str, item_serializer):
    return inline_serializer(
        name=name,
        fields={
            "count": serializers.IntegerField(),
            "next": serializers.CharField(allow_null=True, required=False),
            "previous": serializers.CharField(allow_null=True, required=False),
            "results": item_serializer(many=True),
        },
    )


def standard_paginated_response_serializer(name: str, item_serializer):
    return inline_serializer(
        name=name,
        fields={
            "ok": serializers.BooleanField(default=True),
            "message": serializers.CharField(),
            "data": paginated_data_serializer(f"{name}Data", item_serializer),
        },
    )