"""User authentication, driven by ServerConfig.xml identity tokens.

quasar's ServerConfig enables token *types* (anonymous, user/password); the
credential store on a C++ server is backend-internal. kilonova takes the
credentials programmatically: ``Server(..., users={"operator": "secret"})``.
"""

from __future__ import annotations

import hmac
import logging

from asyncua.crypto.permission_rules import User, UserRole

_log = logging.getLogger(__name__)


class QuasarUserManager:
    """Grants sessions per the ServerConfig identity-token settings."""

    def __init__(self, allow_anonymous: bool = True,
                 users: dict[str, str] | None = None) -> None:
        self._allow_anonymous = allow_anonymous
        self._users = users or {}

    def get_user(self, iserver, username=None, password=None, certificate=None):
        if username:
            expected = self._users.get(username)
            if expected is not None and hmac.compare_digest(expected, password or ""):
                return User(role=UserRole.User)
            _log.warning("rejected user/password logon for %r", username)
            return None
        if self._allow_anonymous:
            return User(role=UserRole.User)
        _log.warning("rejected anonymous logon (EnableAnonymous is false)")
        return None
