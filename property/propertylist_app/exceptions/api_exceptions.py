from rest_framework.exceptions import APIException


class BadRequest(APIException):
    status_code = 400
    default_detail = "Bad request."
    default_code = "bad_request"


class Forbidden(APIException):
    status_code = 403
    default_detail = "Forbidden."
    default_code = "forbidden"


class NotFound(APIException):
    status_code = 404
    default_detail = "Not found."
    default_code = "not_found"


class Conflict(APIException):
    status_code = 409
    default_detail = "Conflict."
    default_code = "conflict"