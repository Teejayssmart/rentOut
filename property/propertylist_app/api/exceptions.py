from typing import Any, Dict, Optional

from django.db import IntegrityError
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException, Throttled, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler


def _extract_field_errors(data: Any) -> Optional[Dict[str, list]]:
    """
    Normalise DRF serializer errors into:
    {
        "field_name": ["message 1", "message 2"],
        "non_field_errors": ["message"]
    }
    """
    if isinstance(data, dict):
        normalised = {}
        for key, value in data.items():
            if isinstance(value, dict):
                nested = _extract_field_errors(value)
                normalised[key] = nested if nested is not None else [str(value)]
            elif isinstance(value, (list, tuple)):
                normalised[key] = [str(v) for v in value]
            else:
                normalised[key] = [str(value)]
        return normalised

    if isinstance(data, (list, tuple)):
        return {"non_field_errors": [str(v) for v in data]}

    return None


def custom_exception_handler(exc, context):
    """
    Return a consistent API error envelope:

    {
        "ok": false,
        "code": "validation_error",
        "message": "Invalid input.",
        "detail": "This field is required.",
        "status": 400,
        "field_errors": {...},
        "details": {...},
        "path": "/api/v1/..."
    }
    """
    response = exception_handler(exc, context)
    request = context.get("request")
    path = request.get_full_path() if request else None

    # Handle exceptions DRF doesn't convert automatically
    if response is None:
        if isinstance(exc, Http404):
            response = Response(
                {"detail": "Not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        elif isinstance(exc, IntegrityError):
            response = Response(
                {"detail": "Conflict."},
                status=status.HTTP_409_CONFLICT,
            )
        elif isinstance(exc, APIException):
            detail = exc.detail
            response = Response(
                {"detail": detail},
                status=getattr(exc, "status_code", status.HTTP_500_INTERNAL_SERVER_ERROR),
            )
        else:
            response = Response(
                {"detail": "Internal server error."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    status_code = response.status_code
    response_data = response.data

    detail_text = None
    field_errors = None
    details_block = None

    if isinstance(response_data, dict):
        details_block = response_data
        field_errors = _extract_field_errors(response_data)

        if "detail" in response_data:
            value = response_data["detail"]
            if isinstance(value, (list, tuple)) and value:
                detail_text = str(value[0])
            else:
                detail_text = str(value)

        if not detail_text and "non_field_errors" in response_data:
            value = response_data["non_field_errors"]
            if isinstance(value, (list, tuple)) and value:
                detail_text = str(value[0])
            else:
                detail_text = str(value)

        if not detail_text and len(response_data) == 1:
            only_value = next(iter(response_data.values()))
            if isinstance(only_value, (list, tuple)) and only_value:
                detail_text = str(only_value[0])
            elif isinstance(only_value, str):
                detail_text = only_value

    elif isinstance(response_data, (list, tuple)):
        details_block = {"non_field_errors": [str(v) for v in response_data]}
        field_errors = {"non_field_errors": [str(v) for v in response_data]}
        if response_data:
            detail_text = str(response_data[0])

    elif response_data is not None:
        detail_text = str(response_data)
        details_block = {"detail": detail_text}

    if isinstance(exc, ValidationError):
        code = "validation_error"
        message = "Invalid input."
    elif isinstance(exc, Throttled) or status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        code = "rate_limited"
        message = "Too many requests. Please wait before retrying."
        retry_after = getattr(exc, "wait", None)
        if not isinstance(details_block, dict):
            details_block = {}
        details_block = {**details_block, "retry_after": retry_after}
    elif status_code == status.HTTP_400_BAD_REQUEST:
        code = "bad_request"
        message = detail_text or "Bad request."
    elif status_code == status.HTTP_401_UNAUTHORIZED:
        code = "unauthorised"
        message = "Authentication credentials were not provided or are invalid."
    elif status_code == status.HTTP_403_FORBIDDEN:
        code = "forbidden"
        message = "You do not have permission to perform this action."
    elif status_code == status.HTTP_404_NOT_FOUND:
        code = "not_found"
        message = "The requested resource was not found."
    elif status_code == status.HTTP_409_CONFLICT:
        code = "conflict"
        message = "Conflict."
    else:
        code = "error"
        message = detail_text or "An error occurred."

    envelope = {
        "ok": False,
        "code": code,
        "message": message,
        "detail": detail_text,
        "status": status_code,
    }

    if field_errors:
        envelope["field_errors"] = field_errors

    if details_block is not None:
        envelope["details"] = details_block

    if path:
        envelope["path"] = path

    response.data = envelope
    return response