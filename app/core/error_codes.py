"""Every 4xx answer is {"error": "<sentence for a person>", "code": "<code>"}
(portal contract v3): a caller shows error and branches on code, never on the
words. The list is closed: a new code is a contract change, made in the
python-webserver and go-webserver skills together."""
from __future__ import annotations

from typing import Any

CODE_NOT_AUTHENTICATED = "not_authenticated"  # 401: no credential, or a bad one
CODE_NOT_ADMIN = "not_admin"  # the route needs an admin
CODE_VIEW_ONLY = "view_only"  # a viewer writing
CODE_SESSION_ONLY = "session_only"  # an API key on a browser-only route
CODE_OWNER_REQUIRED = "owner_required"  # the ladder: only the owner does this (to an admin)
CODE_OWNER_PROTECTED = "owner_protected"  # the ladder: nobody does this to the owner
CODE_KEY_MINTING_OFF = "key_minting_off"  # the calling key may not make keys
CODE_SERVICE_ACCOUNT = "service_account"  # a sign-in action on a service account
CODE_NOT_FOUND = "not_found"  # no such account, key, link or route
CODE_INVALID = "invalid"  # a bad request; field names the field when it is one
CODE_CONFLICT = "conflict"  # a 409
CODE_RATE_LIMITED = "rate_limited"  # a 429
CODE_FORBIDDEN = "forbidden"  # any other 403: a bad csrf token, a cross-origin call

# The whole list, in the contract's order.
ERROR_CODES = (
    CODE_NOT_AUTHENTICATED, CODE_NOT_ADMIN, CODE_VIEW_ONLY, CODE_SESSION_ONLY, CODE_OWNER_REQUIRED,
    CODE_OWNER_PROTECTED, CODE_KEY_MINTING_OFF, CODE_SERVICE_ACCOUNT, CODE_NOT_FOUND, CODE_INVALID,
    CODE_CONFLICT, CODE_RATE_LIMITED, CODE_FORBIDDEN,
)

_BY_STATUS = {401: CODE_NOT_AUTHENTICATED, 403: CODE_FORBIDDEN, 404: CODE_NOT_FOUND, 409: CODE_CONFLICT, 429: CODE_RATE_LIMITED}


def status_code(status: int) -> str:
    """The code a refusal gets when nothing more exact was said: what its
    status alone tells. Empty for a status that is not a 4xx."""
    if not 400 <= status < 500:
        return ""
    return _BY_STATUS.get(status, CODE_INVALID)


def error_body(status: int, message: str, code: str = "", **extra: Any) -> dict[str, Any]:
    """The body of a refusal: the sentence, and the code (code, or
    status_code's when it is empty), then anything more for the caller."""
    body: dict[str, Any] = {"error": message}
    code = code or status_code(status)
    if code:
        body["code"] = code
    body.update(extra)
    return body
