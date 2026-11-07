"""Operations on everything an account can sign in with at once -- its
sessions, its unused login links, and its API keys -- and on the account as a
whole: disabling it, and deleting it. They live here, rather than in
users.py, because each one spans several buckets in one transaction and so
needs all three models.

The owner rules (see app/models/users.py) are checked here, inside each
operation's own transaction, so ownership cannot move between a check and the
change it guards.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from app.core.db import BUCKET_API_KEYS, BUCKET_USERS, Store, Transaction
from app.models import to_iso, utc_now
from app.models.api_keys import APIKey
from app.models.login_tokens import delete_login_tokens_for_user, delete_pending_login_tokens
from app.models.sessions import destroy_sessions_for_user
from app.models.users import User, owner_id_tx
from app.models import playlists, prefs, user_state, verdicts, views
from app.models.revision import bump


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


def _refuse_owner(tx: Transaction, user_id: int) -> None:
    if owner_id_tx(tx) == user_id:
        raise OwnerProtectedError()


@dataclass
class Revoked:
    """What revoke_all_credentials took away, or what delete_user removed
    along with the account -- the same three things either way."""

    sessions: int = 0
    login_links: int = 0
    api_keys: int = 0

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
    return True


def revoke_all_credentials(store: Store, user_id: int, allow_owner: bool = False) -> Revoked | None:
    """The "this account may be compromised" operation: every session is
    deleted, every unused login link is deleted, and every live API key is
    revoked, in one transaction. Afterwards nothing issued before this moment
    can act as the account; the way back in is a new login link from an
    admin. None if there is no such account.

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
        if tx.get(BUCKET_USERS, user_id) is None:
            return None
        if not allow_owner:
            _refuse_owner(tx, user_id)
        revoked = Revoked(
            sessions=destroy_sessions_for_user(tx, user_id),
            login_links=delete_pending_login_tokens(tx, user_id),
        )
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
        tx.delete(BUCKET_USERS, user_id)
    return removed
