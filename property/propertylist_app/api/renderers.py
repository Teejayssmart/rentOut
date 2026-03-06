from rest_framework.renderers import JSONRenderer


class EnvelopeJSONRenderer(JSONRenderer):
    """
    Wrap successful (2xx) responses into:
      { "ok": true, "message": null, "data": ... }

    - Leaves non-2xx responses untouched
    - Avoids double-wrapping if the response already contains an envelope
    - Preserves special response shapes that tests/clients expect directly
    """

    def render(self, data, accepted_media_type=None, renderer_context=None):
        renderer_context = renderer_context or {}
        response = renderer_context.get("response")

        # If no Response context, render as-is.
        if response is None:
            return super().render(data, accepted_media_type, renderer_context)

        status_code = getattr(response, "status_code", 200)

        # Only wrap successful responses
        if 200 <= status_code < 300:
            # Already enveloped
            if isinstance(data, dict) and "ok" in data and "data" in data:
                if "message" not in data:
                    data = {**data, "message": None}
                return super().render(data, accepted_media_type, renderer_context)

            # Keep room preview payload unwrapped:
            # {"room": {...}, "photos": [...]}
            if isinstance(data, dict) and "room" in data and "photos" in data:
                return super().render(data, accepted_media_type, renderer_context)

            wrapped = {"ok": True, "message": None, "data": data}
            return super().render(wrapped, accepted_media_type, renderer_context)

        return super().render(data, accepted_media_type, renderer_context)