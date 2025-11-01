import hashlib
import json
from typing import Any, Dict, Optional
from django.core.cache import cache
from django.conf import settings
from django.utils.encoding import force_bytes

BUSTER_KEY = f"{getattr(settings, 'CACHE_KEY_PREFIX', 'rentout')}:rooms:buster"

def get_buster() -> str:
    """
    A monotonically increasing 'version' for room/search caches.
    Whenever room data changes, we 'bump' this value so new keys are used.
    Old entries die naturally when TTL expires; no need to iterate and delete.
    """
    val = cache.get(BUSTER_KEY)
    if val is None:
        val = "1"
        cache.set(BUSTER_KEY, val, None)
    return str(val)

def bump_buster() -> None:
    try:
        # simple int increment; if absent, start at 1
        cur = cache.get(BUSTER_KEY)
        nxt = str(int(cur) + 1) if cur and cur.isdigit() else "1"
        cache.set(BUSTER_KEY, nxt, None)
    except Exception:
        # worst case, just overwrite
        cache.set(BUSTER_KEY, "1", None)

def _canonical_querydict(querydict) -> Dict[str, Any]:
    """
    Convert QueryDict to a normalized dict (sorted keys, single or list values).
    Ensures stable cache keys for same logical queries.
    """
    items = {}
    for k in sorted(querydict.keys()):
        vals = querydict.getlist(k)
        if len(vals) == 1:
            items[k] = vals[0]
        else:
            items[k] = sorted(vals)
    return items

def make_cache_key(prefix: str, path: str, request=None, extra: Optional[Dict[str, Any]] = None) -> str:
    """
    Build a stable cache key: prefix + path + normalized query + optional extras + buster.
    We DO NOT include user id, because we only cache for anonymous GETs.
    """
    base: Dict[str, Any] = {"path": path, "buster": get_buster()}
    if request is not None:
        base["q"] = _canonical_querydict(request.GET)
        # include pagination headers that affect output (DRF LimitOffsetPagination)
        # (We already include 'limit'/'offset' via request.GET if present.)
    if extra:
        base.update(extra)

    raw = json.dumps(base, separators=(",", ":"), sort_keys=True)
    digest = hashlib.sha256(force_bytes(raw)).hexdigest()
    key_prefix = getattr(settings, "CACHE_KEY_PREFIX", "rentout")
    return f"{key_prefix}:{prefix}:{digest}"

def get_cached_json(key: str):
    data = cache.get(key)
    return data

def set_cached_json(key: str, data, ttl: Optional[int] = None):
    cache.set(key, data, ttl or getattr(settings, "CACHE_DEFAULT_TTL", 60))
