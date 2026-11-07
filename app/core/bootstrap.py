"""Solves the chicken-and-egg problem this auth model creates: only an admin
can mint a login link, and on a fresh database there is no admin to do it.

So on first boot -- and only when no enabled admin exists -- the server
creates one and prints a one-time login link to its own logs. Whoever can read
the container logs is already trusted with the deployment, so this grants
nothing they did not already have, and it means a fresh deploy is usable
without a separate setup command.

Every path that reveals a credential prints through this module, so they all
have one shape and one warning.
"""
from __future__ import annotations

from app.core.config import Config
from app.core.db import Store
from app.models import login_tokens, users

RULE = "-" * 72


def describe_seconds(seconds: int) -> str:
    if seconds % 86400 == 0:
        count, unit = seconds // 86400, "day"
    elif seconds % 3600 == 0:
        count, unit = seconds // 3600, "hour"
    elif seconds % 60 == 0:
        count, unit = seconds // 60, "minute"
    else:
        count, unit = seconds, "second"
    return f"{count} {unit}{'' if count == 1 else 's'}"


def ensure_first_admin(store: Store, cfg: Config, display_name: str = "Admin") -> None:
    """A no-op once any enabled admin exists, so restarting the container does
    not keep minting new admin accounts.

    It also adopts an owner for a database written before the owner marker
    existed (see users.ensure_owner). A fresh database needs no adoption: the
    admin created below becomes the owner as it is created."""
    users.ensure_owner(store)
    if users.any_admin_exists(store):
        return
    user = users.create_user(store, display_name, users.ROLE_ADMIN)
    credential = login_tokens.issue_login_token(store, user.id, cfg.login_token_ttl_seconds)
    print_login_link(cfg, f"first-run admin {display_name!r}", credential)


def print_login_link(cfg: Config, label: str, credential: str) -> None:
    """The one moment a login credential is ever visible, as one full URL you
    can click. The address is server.public_url when set; without it the
    server only knows its own listen address, which the note under it says
    rather than leaving a confidently wrong host unexplained."""
    lines = [
        RULE,
        f"  ONE-TIME LOGIN LINK -- {label}",
        RULE,
        f"  {cfg.url}/login/{credential}",
        RULE,
        f"  Valid once, for {describe_seconds(cfg.login_token_ttl_seconds)}.",
        _link_note(cfg),
        "  It is not stored anywhere and cannot be shown again -- if you lose",
        "  it, mint another with scripts/login.sh (or: python -m app manage",
        "  reissue-login --user-id <id>).",
        RULE,
    ]
    print("\n".join(lines), flush=True)


def print_invite_link(cfg: Config, label: str, credential: str, expires: str) -> None:
    """Show a new invite link once. Like a login link it is stored only as a
    hash, so this is the only time it can be copied."""
    lines = [
        RULE,
        f"  INVITE LINK -- {label}",
        RULE,
        f"  {cfg.url}/join/{credential}",
        RULE,
        f"  Works until {expires}.",
        _link_note(cfg),
        "  Anyone holding it can join, so share it only where you mean to.",
        "  It cannot be shown again; switch it off in the admin panel.",
        RULE,
    ]
    print("\n".join(lines), flush=True)


def print_api_key(cfg: Config, label: str, credential: str, expires: str) -> None:
    """The one moment an API key is ever visible. Unlike a login link this is
    a complete credential, not a URL; the example request uses the same
    address the links do."""
    lines = [
        RULE,
        f"  API KEY -- {label}",
        RULE,
        f"  {credential}",
        RULE,
        f"  Expires: {expires}",
        "  Send it as a header:",
        f'    curl -H "Authorization: Bearer {credential}" {cfg.url}/api/me',
        _link_note(cfg),
        "  It is not stored anywhere and cannot be shown again. If it leaks,",
        "  revoke it: python -m app manage revoke-key --key-id <id>",
        RULE,
    ]
    print("\n".join(lines), flush=True)


def _link_note(cfg: Config) -> str:
    """Where the address in a printed link came from, so a link built from
    127.0.0.1 is not mistaken for one other people can open."""
    return f"  Address from {cfg.url_source}."
