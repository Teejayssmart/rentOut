from typing import Optional
from django.conf import settings
from rest_framework.response import Response

from .cache import make_cache_key, get_cached_json, set_cached_json


class CachedAnonymousGETMixin:
    """
    Drop-in mixin for DRF views:
    - Caches ONLY anonymous GET responses
    - Uses per-view prefix to isolate keys
    - Stores/returns 'data' payload (JSON-serializable)
    - Uses the global cache buster so when data changes,
      new keys are automatically used.
    """

    cache_prefix: str = "v1"
    cache_ttl: Optional[int] = None  # override per-view
    cache_timeout: int = 60  # fallback default

    def _cache_should_use(self, request) -> bool:
        """Only use cache for anonymous GETs."""
        return request.method == "GET" and not request.user.is_authenticated

    def _cache_ttl(self) -> int:
        """Get TTL (seconds) for this view."""
        if self.cache_ttl is not None:
            return self.cache_ttl
        return getattr(settings, "CACHE_DEFAULT_TTL", self.cache_timeout)

    def _make_key(self, request):
        return make_cache_key(self.cache_prefix, request.path, request=request)

    # For ListAPIView
    def list(self, request, *args, **kwargs):
        if self._cache_should_use(request):
            key = self._make_key(request)
            cached = get_cached_json(key)
            if cached is not None:
                return Response(cached)
            resp = super().list(request, *args, **kwargs)
            if getattr(resp, "status_code", None) == 200:
                set_cached_json(key, resp.data, ttl=self._cache_ttl())
            return resp
        return super().list(request, *args, **kwargs)

    # For RetrieveAPIView / APIView.get
    def get(self, request, *args, **kwargs):
        if self._cache_should_use(request):
            key = self._make_key(request)
            cached = get_cached_json(key)
            if cached is not None:
                return Response(cached)
            resp = super().get(request, *args, **kwargs)
            if getattr(resp, "status_code", None) == 200:
                set_cached_json(key, resp.data, ttl=self._cache_ttl())
            return resp
        return super().get(request, *args, **kwargs)
