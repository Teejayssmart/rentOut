from rest_framework import serializers


class SuccessResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField(default=True)
    message = serializers.CharField()
    data = serializers.JSONField()


class ErrorResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField(default=False)
    message = serializers.CharField()
    errors = serializers.JSONField(required=False)