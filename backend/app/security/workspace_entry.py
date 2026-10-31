"""Explicit shared workspace entry for a configured public authority.

The ASGI server must not trust forwarded headers from arbitrary clients. This
policy uses the actual request scheme and Host; it never reads X-Forwarded-*.
"""

from app.core.config import settings
from app.security.errors import Denied
from app.security.primitives import check_origin


def check_shared_workspace(request):
    hosts = request.headers.getlist('host')
    if len(hosts) != 1 or request.headers.get('sec-fetch-site') == 'cross-site':
        raise Denied('ACCESS_DENIED')
    authority = f'{request.scope["scheme"]}://{hosts[0]}'
    if not check_origin(authority, settings.allowed_origins):
        raise Denied('ACCESS_DENIED')
    origins = request.headers.getlist('origin')
    if origins and (len(origins) != 1 or origins[0] != authority):
        raise Denied('CSRF_INVALID')
