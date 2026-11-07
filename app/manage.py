"""`python -m app manage ...` -- the handful of account operations that cannot
happen through the web UI, because they are needed before anyone can log in or
at the point when nobody can.

It opens the database directly, whether or not the server is running. SQLite
in WAL mode allows that: readers never block, and a write here waits its turn
behind the server's (up to the busy timeout) rather than failing. That is why
this template has no control socket, unlike the Go one -- bolt hands its file
to a single process, SQLite does not.

Every command goes through the same model functions the web routes use, so the
rules hold whichever door a change comes through: disabling an account kills
its sessions and unused login links, and an API key can never outrank the
account that owns it.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from app.core import bootstrap, config, db
from app.legacy.import_legacy import LegacyError, import_legacy
from app.models import api_keys, credentials, invite_links, login_tokens, users
from app.reference import paths as reference_paths

USAGE = """manage -- account administration for Media Tracker

Usage:
  bootstrap-admin --name "Ada"          create the first admin + login link
  create-login    --name "Grace" [--role user]
  reissue-login   --user-id 3           fresh link for an existing user
  list-users                            id, name, role, status
  set-disabled    --user-id 3 [--enable]
  revoke-access   --user-id 3           end every session, login link and API key
  delete-user     --user-id 3 --yes     remove the account and everything it held
  transfer-owner  --user-id 3           make another enabled admin the owner
  list-keys       [--user-id 3]         API keys, whose they are, when last used
  create-key      --user-id 3 --name "CI" [--role user] [--days 90]
  revoke-key      --key-id abc123       kill one API key now, keep its record
  delete-key      --key-id abc123       kill one API key now and remove its record
  create-invite   --user-id 1 --label "Book club" [--uses 10] [--days 30]
                                        one link a group can join through
  paths                                 where this app keeps its state
  import-legacy   <old data dir> [--dry-run] [--force] [--no-files] [--no-links]
                                        bring the old MediaTracker's data across

The owner is the first admin, and the one account that can delete other
admins from the web UI. Nothing deletes or disables the owner -- move it with
transfer-owner first. delete-user cannot be undone, hence --yes.

An API key carries a role from the same set users do, so an admin-scoped key
can do what an admin can and a user-scoped one cannot. A key never outranks
the account it belongs to. --days 0 means it never expires; omit --days to use
the server's configured default.

These work whether or not the server is running: the database is opened
directly, which SQLite's WAL mode makes safe alongside a live server.

Every command reads the same config.yaml as the server (see "paths" for which
one). Its server.secret_key in particular must be the one the data was written
with, or the stored records cannot be decrypted.
"""


class ManageError(Exception):
    """A command that cannot do what was asked. Shown as `error: <message>`."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app manage", description=USAGE,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")

    p = commands.add_parser("bootstrap-admin", help="create the first admin + login link")
    p.add_argument("--name", required=True, help="display name for the first admin")
    p.add_argument("--force", action="store_true", help="create another admin even if one exists")

    p = commands.add_parser("create-login", help="create a user and print a login link")
    p.add_argument("--name", required=True, help="display name")
    p.add_argument("--role", choices=[users.ROLE_USER, users.ROLE_ADMIN], default=users.ROLE_USER)

    p = commands.add_parser("reissue-login", help="fresh login link for an existing user")
    p.add_argument("--user-id", type=int, required=True)

    commands.add_parser("list-users", help="id, name, role, status")

    p = commands.add_parser("set-disabled", help="disable (or re-enable) an account")
    p.add_argument("--user-id", type=int, required=True)
    p.add_argument("--enable", action="store_true", help="re-enable instead of disabling")

    p = commands.add_parser("revoke-access", help="end every session, login link and API key")
    p.add_argument("--user-id", type=int, required=True)

    p = commands.add_parser("delete-user", help="remove an account and everything it held")
    p.add_argument("--user-id", type=int, required=True)
    p.add_argument("--yes", action="store_true", help="confirm: this cannot be undone")

    p = commands.add_parser("transfer-owner", help="make another enabled admin the owner")
    p.add_argument("--user-id", type=int, required=True)

    p = commands.add_parser("list-keys", help="API keys, whose they are, when last used")
    p.add_argument("--user-id", type=int, default=None, help="only this user's keys (default: everyone's)")

    p = commands.add_parser("create-key", help="mint an API key for an account")
    p.add_argument("--user-id", type=int, required=True, help="id of the account the key belongs to")
    p.add_argument("--name", required=True, help='what this key is for, e.g. "deploy bot"')
    p.add_argument("--role", choices=[users.ROLE_USER, users.ROLE_ADMIN], default=users.ROLE_USER,
                   help="never more than the account has")
    p.add_argument("--days", type=int, default=None,
                   help="lifetime in days; 0 never expires; omit for the server default")

    p = commands.add_parser("revoke-key", help="kill one API key now, keep its record")
    p.add_argument("--key-id", required=True, help="id of the key to revoke (from list-keys)")

    p = commands.add_parser("delete-key", help="kill one API key now and remove its record")
    p.add_argument("--key-id", required=True, help="id of the key to delete (from list-keys)")

    p = commands.add_parser("create-invite", help="one link a whole group can join through")
    p.add_argument("--user-id", type=int, required=True, help="id of the admin the link is made as")
    p.add_argument("--label", required=True, help='what the link is for, e.g. "Book club"')
    p.add_argument("--uses", type=int, default=10, help="how many people can join through it (1-1000)")
    p.add_argument("--days", type=int, default=30, help="days until it stops working (1-365)")

    commands.add_parser("paths", help="where this app keeps its state")

    p = commands.add_parser("import-legacy", help="bring the old MediaTracker's data across")
    p.add_argument("old_dir", help="the old app's data directory (holding library.json)")
    p.add_argument("--dry-run", action="store_true", help="report what would be imported, write nothing")
    p.add_argument("--force", action="store_true", help="merge into a library that already has other titles")
    p.add_argument("--no-files", action="store_true", help="skip copying the catalogue, IMDb table and posters")
    p.add_argument("--no-links", action="store_true", help="do not print login links for the imported people")
    return parser


def run(arguments: list[str]) -> None:
    args = build_parser().parse_args(arguments)
    try:
        cfg = config.load()
    except config.ConfigError as error:
        raise ManageError(f"config error: {error}") from None

    # "paths" reports configuration only, so it never needs the database and
    # stays useful when everything else is failing.
    if args.command == "paths":
        command_paths(cfg)
        return

    store = db.open_store(cfg.database_path, cfg.secret_key, cfg.encrypt_at_rest)
    # A database written before the owner marker existed gets one here too,
    # so the owner rules hold for commands run before the server's first boot
    # on the new version.
    users.ensure_owner(store)
    # Say where this went. stderr, so piping list-users stays clean.
    print(f"[manage] database at {cfg.database_path}", file=sys.stderr)

    handlers = {
        "bootstrap-admin": command_bootstrap_admin,
        "create-login": command_create_login,
        "reissue-login": command_reissue_login,
        "list-users": command_list_users,
        "set-disabled": command_set_disabled,
        "revoke-access": command_revoke_access,
        "delete-user": command_delete_user,
        "transfer-owner": command_transfer_owner,
        "list-keys": command_list_keys,
        "create-key": command_create_key,
        "revoke-key": command_revoke_key,
        "delete-key": command_delete_key,
        "create-invite": command_create_invite,
        "import-legacy": command_import_legacy,
    }
    try:
        handlers[args.command](store, cfg, args)
    except (
        db.DecodeError,
        credentials.OwnerProtectedError,
        users.NotAdminError,
        invite_links.BadInviteLinkError,
        invite_links.InviteNotAdminError,
        LegacyError,
    ) as error:
        raise ManageError(str(error)) from None


def require_user(store: db.Store, user_id: int) -> users.User:
    user = users.get_user(store, user_id)
    if user is None:
        raise ManageError(f"no user with id {user_id}")
    return user


def command_bootstrap_admin(store: db.Store, cfg: config.Config, args: argparse.Namespace) -> None:
    if not users.valid_display_name(args.name):
        raise ManageError("--name must be 1-80 characters")
    if users.any_admin_exists(store) and not args.force:
        print("An admin already exists. Re-run with --force to create another.")
        return
    user = users.create_user(store, args.name, users.ROLE_ADMIN)
    credential = login_tokens.issue_login_token(store, user.id, cfg.login_token_ttl_seconds)
    bootstrap.print_login_link(cfg, f"admin #{user.id} {user.display_name!r}", credential)


def command_create_login(store: db.Store, cfg: config.Config, args: argparse.Namespace) -> None:
    if not users.valid_display_name(args.name):
        raise ManageError("--name must be 1-80 characters")
    user = users.create_user(store, args.name, args.role)
    credential = login_tokens.issue_login_token(store, user.id, cfg.login_token_ttl_seconds)
    bootstrap.print_login_link(cfg, f"{user.role} #{user.id} {user.display_name!r}", credential)


def command_reissue_login(store: db.Store, cfg: config.Config, args: argparse.Namespace) -> None:
    user = require_user(store, args.user_id)
    credential = login_tokens.issue_login_token(store, user.id, cfg.login_token_ttl_seconds)
    bootstrap.print_login_link(cfg, f"{user.role} #{user.id} {user.display_name!r}", credential)


def command_list_users(store: db.Store, cfg: config.Config, args: argparse.Namespace) -> None:
    rows = users.list_users(store)
    if not rows:
        print('No users yet. Create the first admin with: python -m app manage bootstrap-admin --name "Your Name"')
        return
    owner_id = users.get_owner_id(store)
    print(f"{'ID':<6} {'NAME':<30} {'ROLE':<8} STATUS")
    for user in rows:
        status = "disabled" if user.disabled else "active"
        if user.id == owner_id:
            status += ", owner"
        print(f"{user.id:<6} {user.display_name:<30} {user.role:<8} {status}")


def command_set_disabled(store: db.Store, cfg: config.Config, args: argparse.Namespace) -> None:
    user = require_user(store, args.user_id)
    disabled = not args.enable
    # Disabling deletes the account's sessions and unused login links in the
    # same transaction -- see credentials.set_user_disabled.
    credentials.set_user_disabled(store, user.id, disabled)
    print(f"user #{user.id} ({user.display_name}) disabled={str(disabled).lower()}")


def command_revoke_access(store: db.Store, cfg: config.Config, args: argparse.Namespace) -> None:
    """The incident-response command: run it when an account's credentials
    may be in someone else's hands. The account stays enabled; follow it with
    reissue-login to let its owner back in."""
    user = require_user(store, args.user_id)
    # The operator may revoke the owner's access too -- see
    # credentials.revoke_all_credentials.
    revoked = credentials.revoke_all_credentials(store, user.id, allow_owner=True)
    if revoked is None:
        raise ManageError(f"no user with id {user.id}")
    print(
        f"user #{user.id} ({user.display_name}): ended {revoked.sessions} sessions, deleted "
        f"{revoked.login_links} unused login links, revoked {revoked.api_keys} API keys"
    )
    print(f"To let them back in: python -m app manage reissue-login --user-id {user.id}")


def command_delete_user(store: db.Store, cfg: config.Config, args: argparse.Namespace) -> None:
    """Asks for --yes because nothing brings the account back: the id is never
    reused and its keys and links are gone with it. Disabling is the
    reversible option, and the error says so. Acts as the operator (actor
    None): any account but the owner."""
    if not args.yes:
        raise ManageError(
            f"delete-user cannot be undone; re-run with --yes "
            f"(or use set-disabled --user-id {args.user_id} to keep the account)"
        )
    user = require_user(store, args.user_id)
    removed = credentials.delete_user(store, user.id, None)
    if removed is None:
        raise ManageError(f"no user with id {user.id}")
    print(
        f"user #{user.id} ({user.display_name}) deleted, with {removed.sessions} sessions, "
        f"{removed.login_links} login links and {removed.api_keys} API keys"
    )


def command_transfer_owner(store: db.Store, cfg: config.Config, args: argparse.Namespace) -> None:
    user = users.transfer_owner(store, args.user_id)
    if user is None:
        raise ManageError(f"no user with id {args.user_id}")
    print(f"user #{user.id} ({user.display_name}) is now the owner")


def command_create_invite(store: db.Store, cfg: config.Config, args: argparse.Namespace) -> None:
    """A link a whole group can join through, made as the admin --user-id: it
    stops working if that admin is disabled or demoted."""
    issued = invite_links.issue_invite_link_as(store, args.user_id, args.label, args.uses, args.days)
    if issued is None:
        raise ManageError(f"no user with id {args.user_id}")
    credential, link = issued
    bootstrap.print_invite_link(cfg, f"{link.label!r}, {link.max_uses} places", credential, format_time(link.expires_at))


def format_time(value: datetime | None, absent: str = "never") -> str:
    """Minute precision keeps the listings narrow -- enough for "when was this
    last used", and a full timestamp per column would wrap any normal
    terminal."""
    return absent if value is None else value.astimezone().strftime("%Y-%m-%d %H:%M")


def key_status(key: api_keys.APIKey) -> str:
    if key.revoked:
        return "revoked"
    if key.expired:
        return "expired"
    return "active"


def command_list_keys(store: db.Store, cfg: config.Config, args: argparse.Namespace) -> None:
    keys = (
        api_keys.list_api_keys(store)
        if args.user_id is None
        else api_keys.list_api_keys_for_user(store, args.user_id)
    )
    if not keys:
        print('No API keys. Create one with: python -m app manage create-key --user-id <id> --name "CI"')
        return
    names = {user.id: user.display_name for user in users.list_users(store)}
    row = "{:<18} {:<22} {:<6} {:<20} {:<8} {:<16} {}"
    print(row.format("KEY ID", "NAME", "ROLE", "OWNER", "STATUS", "LAST USED", "EXPIRES"))
    for key in keys:
        print(row.format(
            key.id, key.name, key.role, names.get(key.user_id, f"#{key.user_id}"), key_status(key),
            format_time(key.last_used_at), format_time(key.expires_at),
        ))


def command_create_key(store: db.Store, cfg: config.Config, args: argparse.Namespace) -> None:
    """How a CI system or a cron job gets a credential without anyone signing
    in. --role is what "mirroring admin and non-admin permissions" means in
    practice: --role admin produces a key that can do what an admin can, and
    the default produces one that cannot."""
    # Refuse rather than mint something that cannot be used: with the feature
    # off the server ignores the Authorization header entirely.
    if not cfg.api_keys_enabled:
        raise ManageError("api keys are disabled on this server (auth.api_keys: false)")
    if not api_keys.valid_name(args.name):
        raise ManageError("--name must be 1-80 characters")
    owner = require_user(store, args.user_id)
    ttl_seconds = api_keys.ttl_from_days(args.days, cfg.api_key_ttl_seconds)
    if ttl_seconds is None:
        raise ManageError(f"--days must be 0 (never) or up to {api_keys.API_KEY_MAX_DAYS}")
    try:
        credential, key = api_keys.issue_api_key(store, owner.id, args.name, args.role, ttl_seconds)
    except api_keys.APIKeyError as error:
        raise ManageError(str(error)) from None
    bootstrap.print_api_key(
        cfg,
        f"{key.role}-scoped {key.name!r} for #{owner.id} {owner.display_name!r}",
        credential,
        format_time(key.expires_at),
    )


def command_revoke_key(store: db.Store, cfg: config.Config, args: argparse.Namespace) -> None:
    key = api_keys.revoke_api_key(store, args.key_id)
    if key is None:
        raise ManageError(f"no api key with id {args.key_id}")
    print(f"api key {key.id} ({key.name!r}, owner #{key.user_id}) revoked -- it stops working immediately")


def command_delete_key(store: db.Store, cfg: config.Config, args: argparse.Namespace) -> None:
    """revoke-key without the record left behind. Unlike deleting in the web
    UI there is no undo here, so the row goes at once (purge_api_key)."""
    key = api_keys.get_api_key(store, args.key_id)
    if key is None or not api_keys.purge_api_key(store, key.id):
        raise ManageError(f"no api key with id {args.key_id}")
    print(f"api key {key.id} ({key.name!r}, owner #{key.user_id}) deleted -- it stops working immediately")


def command_paths(cfg: config.Config) -> None:
    """Answers "where did it put my data", which is otherwise a question you
    can only settle by reading the source or the startup log."""

    def note(path: str) -> str:
        return "" if Path(path).exists() else "  (absent -- the bundled copy is used)"

    print(f"{'config':<14} {cfg.config_file}  (holds the secret key)")
    print(f"{'project dir':<14} {cfg.project_dir}  (relative paths in the config start here)")
    print(f"{'url':<14} {cfg.url}  (from {cfg.url_source})")
    print(f"{'app dir':<14} {cfg.app_dir}")
    print(f"{'database':<14} {cfg.database_path}  (plus -wal and -shm files while in use)")
    print(f"{'storage':<14} {cfg.storage_dir}")
    print(f"{'static':<14} {cfg.static_dir}{note(cfg.static_dir)}")
    print(f"{'language':<14} {cfg.language_file}{note(cfg.language_file)}")
    if cfg.config_warning:
        print(f"{'warning':<14} {cfg.config_warning}")

    # Whether the key sits inside the app dir decides what a backup has to
    # cover, so say which case this is rather than leaving it to be worked out
    # from the paths above.
    print("")
    print(f"Change any of these in {cfg.config_file} (server.app_dir moves the app dir).")
    if cfg.config_file.parent == cfg.app_dir:
        print("Back up the app dir as a unit -- app.db is unreadable without the key in config.yaml.")
    else:
        print("config.yaml is NOT in the app dir. Back up both; app.db is unreadable without")
        print("the key in config.yaml, and either one alone is useless.")
    print("Stop the server before copying app.db, or the copy can miss writes still in app.db-wal.")


def command_import_legacy(store: db.Store, cfg: config.Config, args: argparse.Namespace) -> None:
    old_dir = Path(args.old_dir).expanduser().resolve()
    if not (old_dir / "library.json").is_file():
        raise ManageError(f"no library.json in {old_dir}")
    report, user_map = import_legacy(
        store, reference_paths.configure(cfg.storage_dir), old_dir, force=args.force, dry_run=args.dry_run, copy_files=not args.no_files
    )
    prefix = "would import" if args.dry_run else "imported"
    print(f"{prefix} {report.titles} titles: " + ", ".join(f"{count} {name}" for name, count in sorted(report.by_type.items())))
    print("  status: " + ", ".join(f"{count} {name}" for name, count in sorted(report.by_status.items())))
    if report.types_created:
        print("  new types: " + ", ".join(report.types_created))
    print(f"  people created: {', '.join(report.users_created) or 'none'}")
    if report.users_matched:
        print(f"  people already here: {', '.join(report.users_matched)}")
    if not args.dry_run:
        print(f"  sources: {report.sources}, Discover verdicts: {report.verdicts}")
        if report.files:
            print("  files copied: " + ", ".join(f"{count} {name}" for name, count in report.files.items()))
        if report.skipped:
            print(f"  skipped (no title): {len(report.skipped)}")
    if args.dry_run or args.no_links:
        return
    for user_id in dict.fromkeys(user_map.values()):
        user = users.get_user(store, user_id)
        if user is None or user.disabled:
            continue
        credential = login_tokens.issue_login_token(store, user.id, cfg.login_token_ttl_seconds)
        bootstrap.print_login_link(cfg, f"{user.role} #{user.id} {user.display_name!r}", credential)
