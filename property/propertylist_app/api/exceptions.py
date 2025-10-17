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
    Wrap DRF's default exception_handler to return a consistent JSON shape,
    while preserving a human-readable top-level 'detail' string.
    """
    response = exception_handler(exc, context)
    request = context.get("request")
    path = request.get_full_path() if request else None

    # Defaults
    detail_text = None
    field_errors = None
    details_block = None
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    if response is not None:
        status_code = response.status_code

        # Try to preserve DRF's 'detail' (string), or non_field_errors[0], etc.
        if isinstance(response.data, dict):
            data = response.data

            # 1) Direct detail
            if "detail" in data:
                val = data["detail"]
                if isinstance(val, (list, tuple)) and val:
                    detail_text = str(val[0])
                else:
                    detail_text = str(val)

            # 2) Serializer non_field_errors
            if not detail_text and "non_field_errors" in data:
                nfe = data.get("non_field_errors")
                if isinstance(nfe, (list, tuple)) and nfe:
                    detail_text = str(nfe[0])
                elif isinstance(nfe, str):
                    detail_text = nfe

            # 3) Fallback: if only one key and it's a list, surface the first message
            if not detail_text and len(data.keys()) == 1:
                only_val = next(iter(data.values()))
                if isinstance(only_val, (list, tuple)) and only_val:
                    detail_text = str(only_val[0])

            # Keep structured error shapes too
            field_errors = _extract_field_errors(data)
            details_block = data if isinstance(data, dict) else None

    # Map high-level code/message
    if isinstance(exc, ValidationError):
        code = "validation_error"
        message = "Invalid input."
    elif isinstance(exc, Throttled):
        code = "rate_limited"
        message = "Too many requests. Please wait before retrying."
        # Show retry information under details
        details_block = {"retry_after": getattr(exc, "wait", None)}
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
        "detail": detail_text,          # ← preserve the human-friendly detail
        "field_errors": field_errors,   # normalized field-level errors
        "details": details_block,       # raw details (if dict)
        "status": status_code,
        "path": path,
    }
    return Response(body, status=status_code)


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
