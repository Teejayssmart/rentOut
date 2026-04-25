from rest_framework.renderers import JSONRenderer


class EnvelopeJSONRenderer(JSONRenderer):
    """
    Wrap successful API responses into:

    {
        "ok": true,
        "message": null,
        "data": ...
    }

    Non-2xx responses are left alone because they are handled by
    the custom exception handler.
    """

    def render(self, data, accepted_media_type=None, renderer_context=None):
        renderer_context = renderer_context or {}
        response = renderer_context.get("response")

        if response is None:
            return super().render(data, accepted_media_type, renderer_context)

        status_code = getattr(response, "status_code", 200)

        # Only wrap successful responses
        if 200 <= status_code < 300:
            # No body (e.g. old 204 style)
            if data is None:
                data = {}

            # Already enveloped
            if isinstance(data, dict) and "ok" in data and "data" in data:
                if "message" not in data:
                    data = {**data, "message": None}
                return super().render(data, accepted_media_type, renderer_context)

            wrapped = {
                "ok": True,
                "message": None,
                "data": data,
            }
            return super().render(wrapped, accepted_media_type, renderer_context)

        return super().render(data, accepted_media_type, renderer_context)