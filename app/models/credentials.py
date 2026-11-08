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

from app.core.db import BUCKET_USERS, Store, Transaction
from app.core.db import BUCKET_API_KEYS
from app.models import to_iso, utc_now
from app.models.api_keys import APIKey
from app.models.login_tokens import delete_login_tokens_for_user, delete_pending_login_tokens
from app.models.sessions import destroy_sessions_for_user
from app.models.users import User, owner_id_tx
from app.models import playlists, prefs, user_state, verdicts, views
from app.models.revision import bump
from app.models.sign_in import delete_challenges_for_user
from app.models.two_factor import clear_record
from app.models.users import ROLE_ADMIN, RenameConflictError, User, owner_id_tx


class OwnerProtectedError(Exception):
    """Refusal for deleting, disabling, or (from the web) revoking the owner.
    Move ownership first: manage transfer-owner."""

    def __init__(self) -> None:
        super().__init__(
            "the owner account cannot be deleted, disabled, or have its access revoked "
            "-- transfer ownership first (manage transfer-owner)"
        )


class OwnerRequiredError(Exception):
    """Refusal for an admin who is not the owner deleting another admin."""

    def __init__(self) -> None:
        super().__init__("only the owner can delete an admin account")


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


def set_user_disabled(store: Store, user_id: int, disabled: bool) -> bool:
    """Disable or re-enable an account; False if there is no such account.

    Disabling also deletes every session the account holds and every login
    link it has not used yet, in the same transaction as the change itself: a
    session or a link that survived would come back to life the moment the
    account was re-enabled. API keys are deliberately left alone -- see
    load_api_key -- and revoke_all_credentials is for when they should die
    too.

    The owner cannot be disabled by any route, the CLI included: the owner is
    always an enabled admin. Raises OwnerProtectedError; transfer ownership
    first."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_USERS, user_id)
        if record is None:
            return False
        if disabled:
            _refuse_owner(tx, user_id)
        record["disabled_at"] = to_iso(utc_now()) if disabled else None
        tx.put(BUCKET_USERS, user_id, record)
        if disabled:
            destroy_sessions_for_user(tx, user_id)
            delete_pending_login_tokens(tx, user_id)
            delete_challenges_for_user(tx, user_id)
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

    Losing admin rights ends nothing: the role is read on every request, so it
    applies at once, and API keys narrow to it. Invite links the account made
    stop working while it is not an admin."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_USERS, user_id)
        if record is None:
            return None
        if user_id == actor_id:
            raise SelfRoleError()
        owner_id = owner_id_tx(tx)
        if user_id == owner_id:
            raise OwnerProtectedError()
        if record["role"] == role:
            return False
        if User.from_record(record).is_admin and actor_id != owner_id:
            raise OwnerRequiredError()
        record["role"] = role
        tx.put(BUCKET_USERS, user_id, record)
        if role == ROLE_ADMIN:
            destroy_sessions_for_user(tx, user_id)
            delete_pending_login_tokens(tx, user_id)
            delete_challenges_for_user(tx, user_id)
    return True


def revoke_all_credentials(store: Store, user_id: int, allow_owner: bool = False) -> Revoked | None:
    """The "this account may be compromised" operation: every session is
    deleted, the live login link is deleted, the password is removed, and
    every live API key is revoked, in one transaction. Afterwards nothing
    issued before this moment can act as the account; the way back in is a new
    login link from an admin. None if there is no such account.

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
    credentials that leaked, an operator with shell access still needs this."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_USERS, user_id)
        if record is None:
            return None
        if not allow_owner:
            _refuse_owner(tx, user_id)
        revoked = Revoked(
            sessions=destroy_sessions_for_user(tx, user_id),
            login_links=delete_pending_login_tokens(tx, user_id),
            passwords=1 if record.get("password_hash", "") != "" else 0,
        )
        delete_challenges_for_user(tx, user_id)
        record["password_hash"] = ""
        tx.put(BUCKET_USERS, user_id, record)
        now = to_iso(utc_now())
        for key_id, record in tx.all(BUCKET_API_KEYS):
            if record["user_id"] == user_id and APIKey.from_record(record).live:
                record["revoked_at"] = now
                tx.put(BUCKET_API_KEYS, key_id, record)
                revoked.api_keys += 1
    return revoked


def delete_user(store: Store, user_id: int, actor_id: int | None) -> Revoked | None:
    """Remove an account and everything it could sign in with -- every
    session, every login link (used or not), every API key row -- in one
    transaction; None if there is no such account. Unlike disabling, it cannot
    be undone: the id is never reused (see users.create_user), so the account
    cannot come back even by accident.

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
        owner_id = owner_id_tx(tx)
        if owner_id == user_id:
            raise OwnerProtectedError()
        if actor_id is not None and User.from_record(record).is_admin and actor_id != owner_id:
            raise OwnerRequiredError()

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
        verdicts.delete_for_user_tx(tx, user_id)
        bump(tx)
        delete_challenges_for_user(tx, user_id)
        tx.delete(BUCKET_USERS, user_id)
    return removed


def reset_two_factor(store: Store, user_id: int, actor_id: int | None) -> bool:
    """Take 2FA off an account whose person lost both the phone and the
    recovery codes; False if there is no such account. Sign-ins waiting on a
    code end with it.

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
        if actor_id is not None:
            if actor_id == user_id:
                raise SelfResetError()
            owner_id = owner_id_tx(tx)
            if owner_id == user_id:
                raise OwnerProtectedError()
            if User.from_record(record).is_admin and actor_id != owner_id:
                raise OwnerRequiredError()
        clear_record(record)
        tx.put(BUCKET_USERS, user_id, record)
        delete_challenges_for_user(tx, user_id)
    return True
