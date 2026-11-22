"""ProjectPortal's own account (portal contract v3): a service account the
owner connects from the API keys screen (or `manage portal-connect`), so the
portal never holds the owner's key. It is an admin, and never the owner. It
cannot be signed into (sign_in.start_sign_in_tx, login_tokens.issue_login_link);
it has keys only, each one an admin key that may make keys (may_mint_keys)
and never sign-in links. The ladder treats it as an admin, so only the owner
acts on it: no other admin can cut the portal off. Revoking its keys
(disconnect_portal) revokes everything they made, down the chain."""
from __future__ import annotations

from dataclasses import dataclass

from app.core.db import BUCKET_API_KEYS, BUCKET_USERS, Store
from app.models import api_keys
from app.models.users import KIND_SERVICE, ROLE_ADMIN, OwnerRequiredError, User, create_user_tx, get_user, list_users, may_act_on, owner_id_tx, valid_display_name

# The account Connect makes when no name is given.
DEFAULT_PORTAL_NAME = "ProjectPortal"


class NotServiceError(Exception):
    def __init__(self) -> None:
        super().__init__("that account is not a service account")


class BadPortalNameError(Exception):
    def __init__(self) -> None:
        super().__init__("name must be 1-80 characters")


def connect_portal(store: Store, actor_id: int | None, name: str, ttl_seconds: int) -> tuple[str, api_keys.APIKey, User]:
    """Find the service account named name (making it when there is none),
    and give it one more admin key that may make keys, lasting ttl_seconds.
    Only the owner may (OwnerRequiredError); actor None is a shell. Returns
    (credential, key, account); the credential is shown once, by the caller."""
    if not valid_display_name(name):
        raise BadPortalNameError()
    with store.transaction() as tx:
        owner_id = owner_id_tx(tx)
        # With no owner yet, the first admin made would become it.
        if owner_id is None or (actor_id is not None and actor_id != owner_id):
            raise OwnerRequiredError()
        found = [User.from_record(record) for _, record in tx.all(BUCKET_USERS)]
        user = next((each for each in found if each.is_service and each.display_name == name), None)
        if user is None:
            user = create_user_tx(tx, name, ROLE_ADMIN)
            user.kind = KIND_SERVICE
            tx.put(BUCKET_USERS, user.id, user.to_record())
    credential, key = api_keys.issue_api_key(store, user.id, name, ROLE_ADMIN, ttl_seconds)
    with store.transaction() as tx:
        record = tx.get(BUCKET_API_KEYS, key.id)
        record["may_mint_keys"] = True
        tx.put(BUCKET_API_KEYS, key.id, record)
    key.may_mint_keys = True
    return credential, key, user


@dataclass
class PortalAccount:
    user: User
    keys: list[api_keys.APIKey]


def portal_accounts(store: Store) -> list[PortalAccount]:
    """Every service account, oldest first, with its live keys."""
    return [
        PortalAccount(user, [key for key in api_keys.list_api_keys_for_user(store, user.id) if key.live])
        for user in list_users(store)
        if user.is_service
    ]


def disconnect_portal(store: Store, actor_id: int | None, user_id: int) -> int | None:
    """Revoke every live key of the service account user_id, which revokes
    the keys and voids the links they made. Returns how many of its own keys
    it revoked, or None when there is no such account. NotServiceError for an
    account that is not one."""
    user = get_user(store, user_id)
    if user is None:
        return None
    if not user.is_service:
        raise NotServiceError()
    may_act_on(store, actor_id, user_id)
    revoked = 0
    for key in api_keys.list_api_keys_for_user(store, user_id):
        if key.live:
            api_keys.revoke_api_key(store, key.id)
            revoked += 1
    return revoked
