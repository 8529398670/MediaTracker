"""Operations on everything an account can sign in with at once -- its
sessions, its live login links, its password, and its API keys -- and on the
account as a whole: disabling it, and deleting it. They live here, rather than in
users.py, because each one spans several buckets in one transaction and so
needs all three models.

The owner rules (see app/models/users.py) are checked here, inside each
operation's own transaction, so ownership cannot move between a check and the
change it guards.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from app.core.db import BUCKET_USERS, Store, Transaction
from app.core.db import BUCKET_API_KEYS
from app.models import from_iso, to_iso, utc_now
from app.models.api_keys import APIKey, void_what_keys_made_tx
from app.models.login_tokens import delete_login_tokens_for_user, delete_pending_login_tokens
from app.models.sessions import destroy_sessions_for_user
from app.models.users import User, owner_id_tx
from app.models import playlists, prefs, suggestions, user_state, verdicts, views
from app.models.revision import bump
from app.models.sign_in import delete_challenges_for_user
from app.models.two_factor import clear_record
from app.models.users import (  # noqa: F401 -- the errors are re-exported for the routes
    ROLE_ADMIN,
    OwnerProtectedError,
    OwnerRequiredError,
    RenameConflictError,
    User,
    may_act_on_tx,
    owner_id_tx,
)


class SelfDeleteError(Exception):
    """Refusal for deleting your own account, which would sign you out with
    no record left to sign back in to."""

    def __init__(self) -> None:
        super().__init__("you cannot delete your own account")


class SelfRoleError(Exception):
    """Refusal for changing your own role: it could only take your own admin
    rights away, or sign you out."""

    def __init__(self) -> None:
        super().__init__("you cannot change your own role")


class SelfResetError(Exception):
    """Refusal for resetting your own 2FA: that would skip the code turning
    it off asks for."""

    def __init__(self) -> None:
        super().__init__("you cannot reset your own two-factor sign-in")


def _refuse_owner(tx: Transaction, user_id: int) -> None:
    if owner_id_tx(tx) == user_id:
        raise OwnerProtectedError()


@dataclass
class Revoked:
    """What revoke_all_credentials took away, or what delete_user removed
    along with the account -- the same things either way."""

    sessions: int = 0
    login_links: int = 0
    api_keys: int = 0
    passwords: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def set_user_disabled(store: Store, user_id: int, disabled: bool, actor_id: int | None = None) -> bool:
    """Disable or re-enable an account; False if there is no such account.

    Disabling also deletes every session the account holds and every login
    link it has not used yet, in the same transaction as the change itself: a
    session or a link that survived would come back to life the moment the
    account was re-enabled. API keys are deliberately left alone -- see
    load_api_key -- and revoke_all_credentials is for when they should die
    too. What the keys made is not: their unused login links, and every
    browser one of those signed in, in any account, end here too
    (api_keys.void_what_keys_made_tx). They used to stay.

    The owner cannot be disabled by any route, the CLI included: the owner is
    always an enabled admin. Raises OwnerProtectedError; transfer ownership
    first.

    actor_id is the admin asking through the web, held to may_act_on_tx both
    ways: only the owner switches another admin off, or back on. None is the
    operator."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_USERS, user_id)
        if record is None:
            return False
        may_act_on_tx(tx, actor_id, record)
        if disabled:
            _refuse_owner(tx, user_id)
        record["disabled_at"] = to_iso(utc_now()) if disabled else None
        tx.put(BUCKET_USERS, user_id, record)
        if disabled:
            destroy_sessions_for_user(tx, user_id)
            delete_pending_login_tokens(tx, user_id)
            delete_challenges_for_user(tx, user_id)
            void_what_keys_made_tx(tx, user_id)
    return True


def rename_user_as(store: Store, user_id: int, actor_id: int, display_name: str, expect: str | None = None) -> bool:
    """users.rename_user for one account acting on another: any admin may
    rename an ordinary user, and only the owner may rename an admin
    (OwnerRequiredError), because a name is how people tell who they are
    dealing with. Your own name goes through rename_user, from the Account
    screen. False if there is no such account."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_USERS, user_id)
        if record is None:
            return False
        if User.from_record(record).is_admin and actor_id != owner_id_tx(tx):
            raise OwnerRequiredError()
        if expect is not None and record["display_name"] != expect.strip():
            raise RenameConflictError(record["display_name"])
        record["display_name"] = display_name.strip()
        tx.put(BUCKET_USERS, user_id, record)
    return True


def set_user_role(store: Store, user_id: int, actor_id: int, role: str) -> bool | None:
    """Make an account an admin or an ordinary user, and say whether that
    changed anything; None if there is no such account. The rules follow
    deleting: nobody changes their own role (SelfRoleError), the owner is
    always an admin (OwnerProtectedError, transfer ownership first), and only
    the owner takes an admin's rights away (OwnerRequiredError). Any admin may
    make one, as any admin can create one.

    Becoming an admin ends the account's sessions and live login links in
    the same transaction. Whoever holds an invite link can sign in as an
    account that joined through it, so a session already open may not be the
    person being promoted. An admin cannot sign in through an invite link, so
    a new login link is the way back in.

    Losing admin rights ends nothing of the account's own: the role is read
    on every request, so it applies at once, and API keys narrow to it. Invite
    links the account made stop working while it is not an admin. What its API
    keys made as an admin does end: their unused login links, and the browsers
    those signed in (api_keys.void_what_keys_made_tx). A link an admin's key
    made outlived the demotion."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_USERS, user_id)
        if record is None:
            return None
        if user_id == actor_id:
            raise SelfRoleError()
        _refuse_owner(tx, user_id)
        if record["role"] == role:
            return False
        may_act_on_tx(tx, actor_id, record)
        record["role"] = role
        tx.put(BUCKET_USERS, user_id, record)
        if role == ROLE_ADMIN:
            destroy_sessions_for_user(tx, user_id)
            delete_pending_login_tokens(tx, user_id)
            delete_challenges_for_user(tx, user_id)
        else:
            void_what_keys_made_tx(tx, user_id)
    return True


def revoke_all_credentials(store: Store, user_id: int, allow_owner: bool = False, actor_id: int | None = None) -> Revoked | None:
    """The "this account may be compromised" operation: every session is
    deleted, the live login link is deleted, the password is removed, and
    every live API key is revoked, in one transaction. Afterwards nothing
    issued before this moment can act as the account; the way back in is a new
    login link from an admin. None if there is no such account. The login
    links those keys made for other accounts, and the browsers those signed
    in, end too (api_keys.void_what_keys_made_tx).

    2FA stays. It is not something that can be used to get in, and a person
    whose password leaked should not lose it; if it is what went wrong (they
    lost the phone, or someone enrolled their own), reset_two_factor is the
    separate step.

    It is deliberately separate from the two operations it is easy to mistake
    it for. Issuing a new login link replaces the old link but leaves
    existing sessions alone (someone adding a second device should not be
    signed out of the first), and disabling leaves API keys alone (an account
    disabled for an afternoon should not need every integration re-keyed).
    Neither is a reset.

    allow_owner is False for the web route, so no admin can cut the owner off
    (OwnerProtectedError), and True for the CLI: when it is the owner's own
    credentials that leaked, an operator with shell access still needs this.

    actor_id is the admin asking through the web: only the owner revokes
    another admin (may_act_on_tx). None is the operator."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_USERS, user_id)
        if record is None:
            return None
        if not allow_owner:
            _refuse_owner(tx, user_id)
        may_act_on_tx(tx, actor_id, record)
        return _revoke_all_tx(tx, user_id, record)


def _revoke_all_tx(tx: Transaction, user_id: int, record: dict) -> Revoked:
    """revoke_all_credentials' work, inside the caller's transaction, for it
    and for an account expiring (expire_due_accounts). record is the
    account's row, written back when the password goes."""
    revoked = Revoked(
        sessions=destroy_sessions_for_user(tx, user_id),
        login_links=delete_pending_login_tokens(tx, user_id),
        passwords=1 if record.get("password_hash", "") != "" else 0,
    )
    delete_challenges_for_user(tx, user_id)
    record["password_hash"] = ""
    tx.put(BUCKET_USERS, user_id, record)
    now = to_iso(utc_now())
    for key_id, key_record in tx.all(BUCKET_API_KEYS):
        if key_record["user_id"] == user_id and APIKey.from_record(key_record).live:
            key_record["revoked_at"] = now
            tx.put(BUCKET_API_KEYS, key_id, key_record)
            revoked.api_keys += 1
    # What those keys made in other accounts -- links not yet used, the
    # browsers those signed in, and the keys they minted, all the way
    # down -- ends with them (S22).
    void_what_keys_made_tx(tx, user_id)
    return revoked


def delete_user(store: Store, user_id: int, actor_id: int | None) -> Revoked | None:
    """Remove an account and everything it could sign in with -- every
    session, every login link (used or not), every API key row -- in one
    transaction; None if there is no such account. Unlike disabling, it cannot
    be undone: the id is never reused (see users.create_user), so the account
    cannot come back even by accident. The login links its API keys made for
    other accounts, and the browsers those signed in, end too
    (api_keys.void_what_keys_made_tx).

    actor_id is who is asking. None means the operator, through the CLI, who
    may delete any account but the owner. Anyone else is an admin acting
    through the web, and the rules are:

    - nobody deletes themselves (SelfDeleteError);
    - nobody deletes the owner (OwnerProtectedError) -- transfer it first;
    - only the owner deletes another admin (OwnerRequiredError).

    Records an app adds that point at a user id are not touched here. When
    you add one, decide whether it should go with the account (delete it in
    this transaction) or outlive it (render a missing user as "#<id>")."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_USERS, user_id)
        if record is None:
            return None
        if actor_id is not None and actor_id == user_id:
            raise SelfDeleteError()
        # The operator may delete anyone but the owner; an admin goes by the
        # rule every account action does.
        _refuse_owner(tx, user_id)
        may_act_on_tx(tx, actor_id, record)

        # Before the key rows go: void_what_keys_made_tx finds the keys by
        # account, and what they made in other accounts ends with them (S22).
        void_what_keys_made_tx(tx, user_id)
        removed = Revoked(
            sessions=destroy_sessions_for_user(tx, user_id),
            login_links=delete_login_tokens_for_user(tx, user_id),
            api_keys=tx.delete_where(BUCKET_API_KEYS, lambda _key, key_record: key_record["user_id"] == user_id),
            passwords=1 if record.get("password_hash", "") != "" else 0,
        )
        # A person's own corner of the library goes with them: their queue,
        # ratings and hearts, their prefs, saved views, playlists and
        # Discover verdicts. The titles they added stay -- those are the
        # family's -- and show "#<id>" as who added them.
        user_state.delete_for_user_tx(tx, user_id)
        prefs.delete_for_user_tx(tx, user_id)
        views.delete_for_user_tx(tx, user_id)
        playlists.delete_for_user_tx(tx, user_id)
        suggestions.delete_for_user_tx(tx, user_id)
        verdicts.delete_for_user_tx(tx, user_id)
        bump(tx)
        delete_challenges_for_user(tx, user_id)
        tx.delete(BUCKET_USERS, user_id)
    return removed


class ExpiryPastError(Exception):
    """An expiry that is not in the future."""

    def __init__(self) -> None:
        super().__init__("expires_at must be in the future")


class OwnerExpiryError(Exception):
    """The owner is always an enabled admin, so it never expires."""

    def __init__(self) -> None:
        super().__init__("the owner's account cannot expire")


def set_user_expiry(store: Store, user_id: int, actor_id: int | None, expires_at: datetime | None) -> bool:
    """Set when an account stops working, or None for never; False if there
    is no such account. The owner never expires (OwnerExpiryError), and
    otherwise the ladder is may_act_on_tx's: only the owner sets an admin's.
    A time not in the future is ExpiryPastError: switching an account off now
    is what disabling is for.

    Clearing or moving the expiry of an account housekeeping already
    disabled for expiring does not switch it back on: that is the separate,
    deliberate POST /api/admin/users/{id}/disabled."""
    if expires_at is not None and expires_at <= utc_now():
        raise ExpiryPastError()
    with store.transaction() as tx:
        record = tx.get(BUCKET_USERS, user_id)
        if record is None:
            return False
        if owner_id_tx(tx) == user_id:
            raise OwnerExpiryError()
        may_act_on_tx(tx, actor_id, record)
        record["expires_at"] = to_iso(expires_at)
        tx.put(BUCKET_USERS, user_id, record)
    return True


def expire_due_accounts(store: Store) -> int:
    """Housekeeping for account expiry: every account past its expiry that is
    not disabled yet is disabled and has its access revoked, as
    revoke_all_credentials does, each in its own transaction. Such an
    account was already refused everywhere (User.disabled reads the expiry);
    this makes it final, so the record no longer depends on the clock and
    nothing it held lingers. The owner is skipped: it never expires (see
    users.transfer_owner). Returns how many accounts it disabled."""
    now = utc_now()
    due = [
        user.id for user in (User.from_record(record) for _, record in store.all(BUCKET_USERS))
        if user.disabled_at is None and user.expires_at is not None and user.expires_at <= now
    ]
    expired = 0
    for user_id in due:
        with store.transaction() as tx:
            record = tx.get(BUCKET_USERS, user_id)
            if record is None or record.get("disabled_at") is not None or owner_id_tx(tx) == user_id:
                continue
            ends = from_iso(record.get("expires_at"))
            if ends is None or ends > utc_now():
                continue
            record["disabled_at"] = to_iso(utc_now())
            tx.put(BUCKET_USERS, user_id, record)
            _revoke_all_tx(tx, user_id, record)
            expired += 1
    return expired


def reset_two_factor(store: Store, user_id: int, actor_id: int | None) -> bool:
    """Take 2FA off an account whose person lost both the phone and the
    recovery codes; False if there is no such account. Sign-ins waiting on a
    code end with it, and so does every session the account holds (S15): a
    reset is the way back in for someone who lost their device, and the device
    may be in someone else's hands.

    actor_id is who is asking. None means the operator, through the CLI, who
    may reset anyone: that is the way back for an owner locked out. Through
    the web the rules are delete_user's, because this lets someone in who
    could not get in before:

    - nobody resets themselves (SelfResetError);
    - nobody resets the owner (OwnerProtectedError);
    - only the owner resets another admin (OwnerRequiredError)."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_USERS, user_id)
        if record is None:
            return False
        if actor_id is not None and actor_id == user_id:
            raise SelfResetError()
        may_act_on_tx(tx, actor_id, record)
        clear_record(record)
        tx.put(BUCKET_USERS, user_id, record)
        delete_challenges_for_user(tx, user_id)
        destroy_sessions_for_user(tx, user_id)
    return True
