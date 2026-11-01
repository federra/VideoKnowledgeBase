"""Administrator is an explicit current organization capability, never a role name."""

from app.security.errors import Denied
from app.security.sessions import active_grants


def is_administrator(c, p):
    return any(
        g["action_code"] == "member.manage" and g["scope_kind"] == "org"
        for g in active_grants(c, p)
    )


def require_administrator(c, p):
    if not is_administrator(c, p):
        raise Denied("ACCESS_DENIED")
