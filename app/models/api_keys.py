"""API keys -- the non-browser way in.

They exist so that a script, a cron job, a CI pipeline, or another service can
call the same API a signed-in person calls, without inventing a second
permission model for them.

A key carries a role from the same set users do -- admin, user or viewer -- so
whatever an admin may do in the UI an admin-scoped key may do over HTTP, and a
user-scoped key is limited to exactly what a non-admin account is. There is no
separate scope language to keep in step with the role checks.

Keys are minted from a browser session, with one exception: a key the owner
let mint keys (may_mint_keys, switched on from the owner's session) may mint
and revoke keys for other accounts through /api/admin/users/{id}/keys. Every
key minted that way records the key that minted it (minted_by_key), and
revoking or deleting a key revokes every key below it, however deep
(revoke_minted_tx), so pulling one credential still pulls everything it led
to. A minted key can never mint keys itself, nor make sign-in links.

A key can never outrank its owner. The role stored on a key is a *request*,
and it is bounded twice: issue_api_key refuses to mint an admin key for a
non-admin account, and narrow_role re-applies the ceiling on every request.
The second check is what covers an account that is demoted after the key was
minted: the stored role still says admin, and the effective role does not.

Same "<id>.<secret>" shape as sessions, and the same hash. The id is the
record key, so authenticating a key is one fetch and one hash comparison.
sha256 rather than bcrypt because this runs on every request against a
256-bit random secret, exactly like a session; bcrypt here would be a latency
tax that buys nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core import encryption
from app.core.db import BUCKET_API_KEYS, BUCKET_USERS, Record, Store, Transaction
from app.models import RestoreGoneError, deleted_long_ago, from_iso, mark_deleted, to_iso, unmark_deleted, utc_now
from app.models import login_tokens
from app.models.sessions import split_credential
from app.models.users import (
    KIND_SERVICE,
    ROLE_ADMIN,
    ROLE_USER,
    ServiceAccountError,
    OwnerProtectedError,
    OwnerRequiredError,
    RenameConflictError,
    User,
    get_user,
    lower_role,
    may_act_on_id_tx,
    owner_id_tx,
    may_act_on_tx,
    role_rank,
    valid_role,
)

# How many live keys one account can hold. Any signed-in user can mint keys,
# so without a cap a single account can grow the bucket without limit. 25 is
# far past what a person needs and low enough to stay a bound; revoking or
# deleting one frees a slot.
API_KEY_MAX_PER_USER = 25

# How many rows one account keeps, dead keys included. The live cap alone
# does not bound anything: mint, revoke, repeat, and the retained history
# grows by one row each time, and every listing and quota check decrypts all
# of it. When an account reaches this, issuing a key drops its oldest dead
# rows to make room.
API_KEY_MAX_ROWS_PER_USER = 100

# How stale last_used_at is allowed to get. "When was this key last used" is
# the question an operator asks before revoking something, so it is worth
# recording -- but a write per authenticated request would put every handler
# that needs to write behind it. At most once per interval keeps the answer
# useful (to within 15 minutes) and the cost negligible.
API_KEY_TOUCH_INTERVAL = timedelta(minutes=15)

# How long a dead key's row is kept before the purge drops it. A revoked key
# that vanished immediately would make the listing lie about what existed last
# week; keeping it forever is the other wrong trade.
API_KEY_RETENTION = timedelta(days=30)

# Bounds an explicit expiry. Zero still means "never expires", asked for
# deliberately; this only stops a typo from producing a date so far out that
# it is the same thing by accident.
API_KEY_MAX_DAYS = 3650


class APIKeyError(Exception):
    """A key that cannot be issued. The message is safe to show."""


class APIKeyLimitError(APIKeyError):
    def __init__(self) -> None:
        super().__init__("this account already holds the maximum number of live API keys")


class APIKeyRoleError(APIKeyError):
    def __init__(self) -> None:
        super().__init__("an API key cannot be given a role its owner does not have")


class APIKeyDisabledError(APIKeyError):
    def __init__(self) -> None:
        super().__init__("cannot issue an API key for a disabled account")


class APIKeyDeadError(APIKeyError):
    def __init__(self) -> None:
        super().__init__("only a live API key can have its expiry changed")


class APIKeyNotYoursError(APIKeyError):
    def __init__(self) -> None:
        super().__init__("only the account a key acts as may let it make sign-in links")


class APIKeyOwnerError(APIKeyError):
    def __init__(self, user_id: int) -> None:
        super().__init__(f"no user with id {user_id}")


class APIKeyForOwnerError(APIKeyError):
    """Nobody mints a key that acts as the owner from the web."""

    def __init__(self) -> None:
        super().__init__("a key for the owner can only be made by the owner, or from a shell")


class APIKeyExpiryOwnerError(APIKeyError):
    """Nobody else changes when the owner's keys expire."""

    def __init__(self) -> None:
        super().__init__("only the owner can change when the owner's keys expire")


class APIKeyExpiryAdminError(APIKeyError):
    """Only the owner changes when another admin's keys expire."""

    def __init__(self) -> None:
        super().__init__("only the owner can change when an admin's keys expire")


class APIKeyMintedError(APIKeyError):
    """A minted key asking for a right a minted key never gets."""

    def __init__(self, what: str) -> None:
        super().__init__(f"a minted key can never {what}")


class APIKeyMintRoleError(APIKeyError):
    def __init__(self) -> None:
        super().__init__("only an admin key can mint keys")


class APIKeyNotOwnerError(APIKeyError):
    def __init__(self) -> None:
        super().__init__("only the owner can let a key mint keys")


class APIKeyForAdminError(APIKeyError):
    """Only the owner mints a key that acts as another admin."""

    def __init__(self) -> None:
        super().__init__("only the owner can create a key for an admin")


@dataclass
class APIKey:
    id: str
    user_id: int
    name: str
    role: str
    secret_hash: str
    created_at: datetime
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    # Set by delete_api_key. A deleted key is dead and out of every listing,
    # but restore_api_key can bring it back for RESTORE_WINDOW.
    deleted_at: datetime | None = None
    deleted_by: int | None = None
    # The admin who minted this key as its owner, through issue_api_key_for.
    # None means the owner made it, or it came from a shell, and rows from
    # before this field read as None too. It is what lets the person a key
    # acts as see that someone else made it.
    created_by: int | None = None
    # Whether this key may ask for a login link for its own account (POST
    # /api/account/login-link). Off by default: the link becomes an ordinary
    # browser session, so a key that may make one is as good as a session to
    # whoever holds it. Only the key's own account turns it on, and only from
    # a browser session (set_api_key_sign_in). Its links work once and for at
    # most KEY_LOGIN_LINK_TTL_SECONDS.
    may_sign_in: bool = False
    # Whether this key may mint and revoke keys for other accounts (POST
    # /api/admin/users/{user_id}/keys). Only the owner turns it on, from a
    # browser session, on one of the owner's own admin keys
    # (set_api_key_mint_keys). A minted key never has it.
    may_mint_keys: bool = False
    # The key that minted this one, "" when a person or a shell did. Revoking
    # or deleting that key revokes this one too (revoke_minted_tx).
    minted_by_key: str = ""

    @property
    def revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def expired(self) -> bool:
        return self.expires_at is not None and utc_now() > self.expires_at

    @property
    def live(self) -> bool:
        """Whether the key would authenticate right now, as far as the key
        itself is concerned. Whether its owner is still enabled is a separate
        question, asked in load_api_key."""
        return not self.revoked and not self.expired and not self.deleted

    def to_record(self) -> Record:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "role": self.role,
            "secret_hash": self.secret_hash,
            "created_at": to_iso(self.created_at),
            "expires_at": to_iso(self.expires_at),
            "last_used_at": to_iso(self.last_used_at),
            "revoked_at": to_iso(self.revoked_at),
            "deleted_at": to_iso(self.deleted_at),
            "deleted_by": self.deleted_by,
            "created_by": self.created_by,
            "may_sign_in": self.may_sign_in,
            "may_mint_keys": self.may_mint_keys,
            "minted_by_key": self.minted_by_key,
        }

    @classmethod
    def from_record(cls, record: Record) -> "APIKey":
        return cls(
            id=record["id"],
            user_id=record["user_id"],
            name=record["name"],
            role=record["role"],
            secret_hash=record["secret_hash"],
            created_at=from_iso(record["created_at"]),
            expires_at=from_iso(record.get("expires_at")),
            last_used_at=from_iso(record.get("last_used_at")),
            revoked_at=from_iso(record.get("revoked_at")),
            deleted_at=from_iso(record.get("deleted_at")),
            deleted_by=record.get("deleted_by"),
            created_by=record.get("created_by"),
            may_sign_in=bool(record.get("may_sign_in", False)),
            may_mint_keys=bool(record.get("may_mint_keys", False)),
            minted_by_key=record.get("minted_by_key") or "",
        )


def ttl_from_days(days: int | None, fallback_seconds: int) -> int | None:
    """Turn a requested lifetime in days into seconds. It lives here rather
    than in a handler so the HTTP API and the CLI cannot end up disagreeing
    about what "0 days" means.

    None means "use the configured default", 0 means "never expires" (returned
    as 0), and a number means that many days. Returns None for a value that is
    out of range."""
    if days is None:
        return fallback_seconds
    if isinstance(days, bool) or not isinstance(days, int) or days < 0 or days > API_KEY_MAX_DAYS:
        return None
    return days * 24 * 60 * 60


def valid_name(name: str) -> bool:
    """Bounds the label a key is given. It is free text a user controls, same
    as a display name, and exists only so a list of keys is readable --
    "deploy bot", "grafana", "my laptop"."""
    return isinstance(name, str) and 1 <= len(name.strip()) <= 80


def narrow_role(account_role: str, key_role: str) -> str:
    """The permission ceiling, applied on every request that authenticates
    with a key: the effective role is the *lower* of the account's role and
    the key's.

    Storing the key's role and then re-deriving the effective one, rather than
    trusting what was stored, is what makes demotion work. If an admin mints
    an admin key and later becomes an ordinary user, the row still says admin
    -- and every request it authenticates is treated as a user. A viewer
    account's admin key acts as a viewer."""
    if not valid_role(key_role):
        key_role = ROLE_USER
    return lower_role(account_role, key_role)


def issue_api_key_for(store: Store, actor_id: int, user_id: int, name: str, role: str, ttl_seconds: int) -> tuple[str, APIKey]:
    """An admin minting a key that acts as someone else, so it follows the
    ladder deleting an account does, for the same reason -- acting as an
    account is as much power over it as removing it:

    - nobody mints for the owner (APIKeyForOwnerError) -- a shell still can,
      through issue_api_key;
    - only the owner mints for another admin (APIKeyForAdminError).

    Your own account is simply your own key. The rules are checked inside the
    issuing transaction, so ownership cannot move between the check and the
    key."""
    if actor_id == user_id:
        return issue_api_key(store, user_id, name, role, ttl_seconds)
    return issue_api_key(store, user_id, name, role, ttl_seconds, created_by=actor_id)


def issue_api_key(store: Store, user_id: int, name: str, role: str, ttl_seconds: int, created_by: int | None = None, minted_by_key: str = "", minting: bool = False) -> tuple[str, APIKey]:
    """Returns (credential, key). The credential exists exactly once, here: it
    is never stored and cannot be recovered -- if it is lost, revoke the key
    and mint another.

    ttl_seconds of zero means the key never expires. That is a deliberate
    option rather than an oversight: a CI job nobody will remember to re-key is
    worse served by a credential that dies silently at 3am. It has to be asked
    for explicitly; the default comes from configuration.

    minting is mint_api_key's: the owner's account is refused outright and a
    role above the account's is capped to it rather than refused."""
    # The owner is loaded inside the transaction below rather than taking the
    # caller's word for the role. Every route into this function -- the HTTP
    # API and the CLI -- then gets the same ceiling without each having to
    # remember it.
    if not valid_role(role):
        role = ROLE_USER

    key_id = encryption.url_token(12)
    secret = encryption.url_token(32)
    now = utc_now()
    key = APIKey(
        id=key_id,
        user_id=user_id,
        name=name.strip(),
        role=role,
        secret_hash=encryption.sha256_hex(secret),
        created_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds) if ttl_seconds > 0 else None,
        created_by=created_by,
        minted_by_key=minted_by_key,
    )

    # The owner check, the quota check, and the insert share one transaction.
    # Counted in one transaction and inserted in another, sixteen concurrent
    # requests can all see 24 live keys and all insert, which is how a "max
    # 25" turns into 40.
    with store.transaction() as tx:
        owner_record = tx.get(BUCKET_USERS, user_id)
        if owner_record is None:
            raise APIKeyOwnerError(user_id)
        owner = User.from_record(owner_record)
        if minting:
            if owner_id_tx(tx) == user_id:
                raise APIKeyForOwnerError()
            key.role = role = lower_role(role, owner.role)
        try:
            may_act_on_tx(tx, created_by, owner)
        except OwnerProtectedError:
            raise APIKeyForOwnerError() from None
        except OwnerRequiredError:
            raise APIKeyForAdminError() from None
        if owner.disabled:
            raise APIKeyDisabledError()
        if role_rank(role) > role_rank(owner.role):
            raise APIKeyRoleError()

        owned = [APIKey.from_record(record) for _, record in tx.all(BUCKET_API_KEYS) if record["user_id"] == user_id]
        if sum(1 for existing in owned if existing.live) >= API_KEY_MAX_PER_USER:
            raise APIKeyLimitError()
        # Oldest dead rows first. Live keys are capped well below the row
        # limit, so there is always a dead row to drop when the limit is hit.
        dead = sorted((existing for existing in owned if not existing.live), key=lambda existing: existing.created_at)
        for existing in dead[: max(0, len(owned) + 1 - API_KEY_MAX_ROWS_PER_USER)]:
            tx.delete(BUCKET_API_KEYS, existing.id)

        tx.put(BUCKET_API_KEYS, key_id, key.to_record())
    return f"{key_id}.{secret}", key


def load_api_key(store: Store, credential: str) -> tuple[APIKey, User] | None:
    """None for anything that is not a usable key -- wrong shape, unknown id,
    bad secret, expired, revoked, or belonging to a disabled account. Callers
    only ever need "is this request authenticated", and folding every failure
    into one answer avoids leaking which check failed.

    Note what is *not* here: a disabled account does not have its keys
    revoked, the way it has its sessions destroyed. A session is a browser
    artifact and destroying it costs nothing; a key is a configured
    integration, and tearing every integration's credential down because
    someone was disabled for an afternoon is a footgun with no security gain
    -- the check below already refuses the request either way."""
    parts = split_credential(credential)
    if parts is None:
        return None
    key_id, secret = parts

    record = store.get(BUCKET_API_KEYS, key_id)
    if record is None:
        return None
    key = APIKey.from_record(record)

    if not encryption.constant_time_equal(key.secret_hash, encryption.sha256_hex(secret)):
        return None
    if not key.live:
        return None

    user = get_user(store, key.user_id)
    if user is None or user.disabled:
        return None

    _touch(store, key)
    return key, user


def _touch(store: Store, key: APIKey) -> None:
    """Record use at most once per API_KEY_TOUCH_INTERVAL. Failures are
    ignored on purpose: this is bookkeeping, and a request that authenticated
    correctly should not fail because a timestamp could not be written."""
    now = utc_now()
    if key.last_used_at is not None and now - key.last_used_at < API_KEY_TOUCH_INTERVAL:
        return

    def mutate(record: Record) -> None:
        record["last_used_at"] = to_iso(now)

    try:
        store.update_value(BUCKET_API_KEYS, key.id, mutate)
    except Exception:  # noqa: BLE001 -- bookkeeping only, see above
        return
    key.last_used_at = now


def get_api_key(store: Store, key_id: str) -> APIKey | None:
    record = store.get(BUCKET_API_KEYS, key_id)
    return None if record is None else APIKey.from_record(record)


def list_api_keys(store: Store) -> list[APIKey]:
    """Every key, newest first, leaving out deleted ones. Only the admin
    endpoint and the CLI use it; a user asking for "my keys" goes through
    list_api_keys_for_user."""
    keys = [APIKey.from_record(record) for _, record in store.all(BUCKET_API_KEYS)]
    keys = [key for key in keys if not key.deleted]
    return sorted(keys, key=lambda key: key.created_at, reverse=True)


def list_api_keys_for_user(store: Store, user_id: int) -> list[APIKey]:
    return [key for key in list_api_keys(store) if key.user_id == user_id]


def void_what_keys_made_tx(tx: Transaction, user_id: int) -> int:
    """login_tokens.void_links_minted_by_key for every API key an account
    holds, live or not, inside the caller's transaction. Disabling an
    account, or taking its admin role away, calls it: a login link its key
    made, and a browser that link signed in, carry the right the account had
    then, so they end with that right instead of outliving it. So do the keys
    they minted, down the whole chain (revoke_minted_tx)."""
    key_ids = [key_id for key_id, record in tx.all(BUCKET_API_KEYS) if record["user_id"] == user_id]
    voided = sum(login_tokens.void_links_minted_by_key(tx, key_id) for key_id in key_ids)
    return voided + sum(revoke_minted_tx(tx, key_id) for key_id in key_ids)


def count_live_api_keys_for_user(store: Store, user_id: int) -> int:
    return sum(1 for key in list_api_keys_for_user(store, user_id) if key.live)


def revoke_api_key(store: Store, key_id: str, actor_id: int | None = None) -> APIKey | None:
    """Mark a key dead and return it, or None if there is no such key. It is
    idempotent -- revoking twice keeps the first timestamp -- and goes through
    update_value so two concurrent revocations cannot have one overwrite the
    other with a stale copy of the row.

    The row is marked rather than deleted so a listing can still show the key
    existed and when it died. The purge removes it later.

    In the same transaction it voids the login links and invite links the key
    made that could still be used (login_tokens.void_links_minted_by_key), so a
    leaked key cannot leave a way in behind it.

    actor_id, when given, is the account asking through the web, held to
    users.may_act_on_tx for the key's account: only the owner revokes another
    admin's key, and nobody else revokes the owner's. None is the operator."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_API_KEYS, key_id)
        if record is None:
            return None
        may_act_on_id_tx(tx, actor_id, record["user_id"])
        if record.get("revoked_at") is None:
            record["revoked_at"] = to_iso(utc_now())
            tx.put(BUCKET_API_KEYS, key_id, record)
        login_tokens.void_links_minted_by_key(tx, key_id)
        revoke_minted_tx(tx, key_id)
    return APIKey.from_record(record)


def revoke_minted_tx(tx: Transaction, key_id: str) -> int:
    """Revoke every key key_id minted, and every key those minted, down the
    whole chain, inside the caller's transaction, and void what each of them
    made (login_tokens.void_links_minted_by_key). Returns how many keys it
    revoked. Revoking, deleting, revoke-access, deleting an account and an
    account expiring all call it, so no way of ending a key leaves its
    descendants working.

    Walked breadth first over the whole bucket, with a seen set: a chain is
    short in practice, and the set keeps a damaged row pointing in a circle
    from looping."""
    if not key_id:
        return 0
    children: dict[str, list[tuple[str, Record]]] = {}
    for other_id, record in tx.all(BUCKET_API_KEYS):
        parent = record.get("minted_by_key") or ""
        if parent:
            children.setdefault(parent, []).append((other_id, record))
    now = to_iso(utc_now())
    revoked, seen, queue = 0, {key_id}, [key_id]
    while queue:
        for child_id, record in children.get(queue.pop(0), []):
            if child_id in seen:
                continue
            seen.add(child_id)
            queue.append(child_id)
            if record.get("revoked_at") is None and record.get("deleted_at") is None:
                record["revoked_at"] = now
                tx.put(BUCKET_API_KEYS, child_id, record)
                revoked += 1
            login_tokens.void_links_minted_by_key(tx, child_id)
    return revoked


def rename_api_key(store: Store, key_id: str, actor_id: int | None, name: str, expect: str | None = None) -> bool:
    """Change a key's label, which is all a name is: nothing about what the
    key may do hangs off it, so a dead key can be renamed too. False if there
    is no such key or it is deleted.

    expect, when given, is the name the caller believes is stored, as in
    users.rename_user: RenameConflictError if it is not, which keeps an undo
    from overwriting a rename made somewhere else.

    actor_id is who is asking (None for none, as from a shell). A name is what
    the owner goes by when deciding which key to revoke, so renaming someone
    else's key follows the same ladder as everything else done to it (S14):
    nobody renames the owner's keys (OwnerProtectedError), and only the owner
    renames another admin's (OwnerRequiredError)."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_API_KEYS, key_id)
        if record is None or record.get("deleted_at") is not None:
            return False
        if actor_id is not None:
            may_act_on_id_tx(tx, actor_id, record["user_id"])
        if expect is not None and record["name"] != expect.strip():
            raise RenameConflictError(record["name"])
        record["name"] = name.strip()
        tx.put(BUCKET_API_KEYS, key_id, record)
    return True


def set_api_key_expiry(store: Store, key_id: str, actor_id: int, ttl_seconds: int) -> APIKey | None:
    """Give a live key a new expiry, counted from now; a ttl of zero means it
    never expires, as when issuing one. None if there is no such key or it is
    deleted.

    A dead key stays dead (APIKeyDeadError). Reviving an expired key here
    would turn an edit into a way round the expiry, and a revoked one would
    break the promise that revoking is final: a new key is the way back.

    actor_id is who is asking. Keeping someone else's key alive is as much
    power over that account as minting one for it, so it follows the same
    ladder as issue_api_key_for: nobody touches the owner's keys, and only the
    owner touches another admin's. Otherwise an admin holding a stolen key
    could keep it going."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_API_KEYS, key_id)
        if record is None:
            return None
        key = APIKey.from_record(record)
        if key.deleted:
            return None
        if not key.live:
            raise APIKeyDeadError()
        try:
            may_act_on_id_tx(tx, actor_id, key.user_id)
        except OwnerProtectedError:
            raise APIKeyExpiryOwnerError() from None
        except OwnerRequiredError:
            raise APIKeyExpiryAdminError() from None
        key.expires_at = utc_now() + timedelta(seconds=ttl_seconds) if ttl_seconds > 0 else None
        tx.put(BUCKET_API_KEYS, key_id, key.to_record())
    return key


# The longest a login link made by an API key works for. Such a link always
# works once, whatever the request asked.
KEY_LOGIN_LINK_TTL_SECONDS = 15 * 60


def set_api_key_sign_in(store: Store, key_id: str, user_id: int, on: bool) -> APIKey | None:
    """Turn may_sign_in on or off. Only the account the key acts as may change
    it, not an admin, not even the owner: it decides whether that key is as
    good as a browser session to that account, which is the account's own
    call. A dead key cannot be turned on (APIKeyDeadError); turning it off
    always works, and voids any link the key made that is still unused.
    Browsers those links already signed in stay signed in: the switch off is
    "no more links", and revoking the key is "sign them out too". None when
    there is no such key or it is deleted."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_API_KEYS, key_id)
        if record is None:
            return None
        key = APIKey.from_record(record)
        if key.deleted:
            return None
        if key.user_id != user_id:
            raise APIKeyNotYoursError()
        if on and not key.live:
            raise APIKeyDeadError()
        if on and key.minted_by_key:
            raise APIKeyMintedError("make sign-in links")
        if on and (tx.get(BUCKET_USERS, key.user_id) or {}).get("kind") == KIND_SERVICE:
            raise ServiceAccountError()
        key.may_sign_in = on
        tx.put(BUCKET_API_KEYS, key_id, key.to_record())
        if not on:
            login_tokens.void_unused_links_minted_by_key(tx, key_id)
    return key


def set_api_key_mint_keys(store: Store, key_id: str, user_id: int, on: bool) -> APIKey | None:
    """Turn may_mint_keys on or off for one of the owner's own keys. Only the
    owner may (APIKeyNotOwnerError), on its own key (anyone else's is None,
    "no such key"), and only on a live admin key that was not itself minted:
    a key that mints keys is as good as an admin session for every account
    but the owner's, so the right starts at the owner and goes no further.
    Turning it off always works and leaves the keys it already minted alone;
    revoking the key is what ends those. None when there is no such key or
    it is deleted."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_API_KEYS, key_id)
        if record is None:
            return None
        key = APIKey.from_record(record)
        if key.deleted:
            return None
        # The owner's own keys, or a service account's (ProjectPortal's,
        # whose keys only the owner runs).
        account = tx.get(BUCKET_USERS, key.user_id) or {}
        if key.user_id != user_id and account.get("kind") != KIND_SERVICE:
            return None
        if owner_id_tx(tx) != user_id:
            raise APIKeyNotOwnerError()
        if on:
            if not key.live:
                raise APIKeyDeadError()
            if key.minted_by_key:
                raise APIKeyMintedError("mint keys")
            if key.role != ROLE_ADMIN:
                raise APIKeyMintRoleError()
        key.may_mint_keys = on
        tx.put(BUCKET_API_KEYS, key_id, key.to_record())
    return key


def mint_api_key(store: Store, actor_id: int, minted_by_key: str, user_id: int, name: str, role: str, ttl_seconds: int) -> tuple[str, APIKey]:
    """A key minted for another account through /api/admin/users/{id}/keys,
    by a minting key (minted_by_key its id) or an admin session (""). The
    role is capped at the account's own; the owner's keys are never minted
    this way (APIKeyForOwnerError); the ladder for everyone else is
    issue_api_key's (only the owner mints for another admin)."""
    created_by = None if actor_id == user_id else actor_id
    return issue_api_key(store, user_id, name, role, ttl_seconds, created_by=created_by, minted_by_key=minted_by_key, minting=True)


def delete_api_key(store: Store, key_id: str, actor_id: int | None) -> bool:
    """Take a key off every listing and stop it working, now; False if there
    is no such key or it is already deleted.

    Unlike revoking, this can be undone: the row is only marked, and
    restore_api_key brings it back -- working again -- for RESTORE_WINDOW,
    after which the purge removes it. Revoke is the one-way switch for a key
    that may have leaked; delete is tidying up, and tidying up the wrong row
    is the mistake an undo exists for. The routes decide who may ask, and
    actor_id is held to users.may_act_on_tx for the key's account: only the
    owner deletes another admin's key, and nobody else deletes the owner's.

    Like revoking, it voids the links the key made
    (login_tokens.void_links_minted_by_key); restoring the key does not bring
    them back."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_API_KEYS, key_id)
        if record is None or record.get("deleted_at") is not None:
            return False
        may_act_on_id_tx(tx, actor_id, record["user_id"])
        mark_deleted(record, actor_id)
        tx.put(BUCKET_API_KEYS, key_id, record)
        login_tokens.void_links_minted_by_key(tx, key_id)
        revoke_minted_tx(tx, key_id)
    return True


def restore_api_key(store: Store, key_id: str, actor_id: int, actor_is_admin: bool) -> APIKey:
    """Undo delete_api_key. Raises a RestoreError when the window has passed
    or the actor is neither whoever deleted it nor an admin, and
    APIKeyLimitError when bringing it back would put its owner over the live
    key cap -- the same cap issue_api_key keeps, checked in the same
    transaction for the same reason."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_API_KEYS, key_id)
        if record is None:
            raise RestoreGoneError()
        # Bringing a key back is as much power over its account as minting
        # one, so the rule is the key's account's, not the deleter's.
        may_act_on_id_tx(tx, actor_id, record["user_id"])
        unmark_deleted(record, actor_id, actor_is_admin, owner_id_tx(tx))
        key = APIKey.from_record(record)
        if key.live:
            owned = (APIKey.from_record(other) for _, other in tx.all(BUCKET_API_KEYS) if other["user_id"] == key.user_id)
            if sum(1 for other in owned if other.live) >= API_KEY_MAX_PER_USER:
                raise APIKeyLimitError()
        tx.put(BUCKET_API_KEYS, key_id, record)
    return key


def purge_api_key(store: Store, key_id: str) -> bool:
    """Remove a key's row outright, with no way back; False if there is no
    such key. Only the CLI uses it: an operator at a shell has no Undo
    button, so a soft delete there would only leave the row lying around."""
    with store.transaction() as tx:
        if tx.get(BUCKET_API_KEYS, key_id) is None:
            return False
        tx.delete(BUCKET_API_KEYS, key_id)
    return True


def purge_dead_api_keys(store: Store) -> int:
    """Drop rows for keys revoked or expired longer than API_KEY_RETENTION
    ago, and deleted ones past their RESTORE_WINDOW. Dead keys are already
    refused by load_api_key, so this is only housekeeping."""
    cutoff = utc_now() - API_KEY_RETENTION

    def dead(_key: object, record: Record) -> bool:
        revoked_at = from_iso(record.get("revoked_at"))
        expires_at = from_iso(record.get("expires_at"))
        return (
            (revoked_at is not None and revoked_at < cutoff)
            or (expires_at is not None and expires_at < cutoff)
            or deleted_long_ago(record)
        )

    return store.delete_where(BUCKET_API_KEYS, dead)


class APIKeyRotateDeadError(APIKeyError):
    def __init__(self) -> None:
        super().__init__("only a live API key can be rotated")


def rotate_api_key(store: Store, key_id: str) -> tuple[str, APIKey]:
    """Give a key a new secret and return (its new credential, the key). The
    old secret stops working at once. Everything else stays -- id, name,
    role, grants, lineage, and expires_at, which rotation never extends -- so
    the keys and links it made keep working, and a leaked key that rotates
    itself still dies on schedule. APIKeyRotateDeadError for a key that is not
    live."""
    secret = encryption.url_token(32)
    with store.transaction() as tx:
        record = tx.get(BUCKET_API_KEYS, key_id)
        key = APIKey.from_record(record) if record is not None else None
        if key is None or key.deleted or not key.live:
            raise APIKeyRotateDeadError()
        key.secret_hash = encryption.sha256_hex(secret)
        tx.put(BUCKET_API_KEYS, key_id, key.to_record())
    return f"{key_id}.{secret}", key
