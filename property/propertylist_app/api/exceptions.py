from typing import Any, Dict, Optional
from django.http import Http404
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import Throttled, ValidationError, APIException

def _extract_field_errors(data: Any) -> Optional[Dict[str, list]]:
    """
    Turn DRF's error structure into {field: [messages]} or None.
    Accepts dicts or lists and normalises them.
    """
    if isinstance(data, dict):
        normalised = {}
        for key, value in data.items():
            if isinstance(value, (list, tuple)):
                normalised[key] = [str(v) for v in value]
            else:
                normalised[key] = [str(value)]
        return normalised
    return None

def custom_exception_handler(exc, context):
    """
    Wrap DRF's default exception_handler to return a consistent JSON shape.
    """
    response = exception_handler(exc, context)
    request = context.get("request")
    path = request.get_full_path() if request else None

    if response is not None:
        status_code = response.status_code
        data = response.data

        if isinstance(exc, ValidationError):
            code = "validation_error"
            message = "Invalid input."
        elif isinstance(exc, Throttled):
            code = "rate_limited"
            message = "Too many requests. Please wait before retrying."
            data = {"retry_after": getattr(exc, "wait", None)}
        elif status_code == status.HTTP_401_UNAUTHORIZED:
            code = "unauthorised"
            message = "Authentication credentials were not provided or are invalid."
        elif status_code == status.HTTP_403_FORBIDDEN:
            code = "forbidden"
            message = "You do not have permission to perform this action."
        elif status_code == status.HTTP_404_NOT_FOUND or isinstance(exc, Http404):
            code = "not_found"
            message = "The requested resource was not found."
        else:
            code = "error"
            message = "An error occurred."

        body = {
            "ok": False,
            "code": code,
            "message": message,
            "field_errors": _extract_field_errors(response.data),
            "details": data if isinstance(data, dict) else None,
            "status": status_code,
            "path": path,
        }
        return Response(body, status=status_code)

    # Unhandled exceptions → generic 500 without leaking internals
    body = {
        "ok": False,
        "code": "server_error",
        "message": "Something went wrong on our side.",
        "field_errors": None,
        "details": None,
        "status": 500,
        "path": path,
    }
    return Response(body, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class APIError(APIException):
    """
    Optional helper to raise consistent, typed API errors.

    Example:
        raise APIError(detail={"reason": "payment_failed"},
                       code="payment_failed",
                       status_code=402)
    """
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = {"reason": "bad_request"}
    default_code = "error"

    def __init__(self, detail=None, code=None, status_code=None):
        super().__init__(detail=detail or self.default_detail, code=code or self.default_code)
        if status_code is not None:
            self.status_code = status_code
