"""`python -m app config ...` -- create, check, change, or read config.yaml.

These exist so that nothing else has to parse YAML. The scripts in scripts/
and docker/ eval the output of `config shell server|docker`, which means they
get the same defaults, the same strict decoding, the same validation and the
same resolved paths as the server -- a typo fails the deploy before anything
starts, instead of being ignored by a second, looser parser, and what a
script prints is what the server will do.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from app.core import config

USAGE = f"""config -- create, check, change, or read config.yaml

Usage:
  init  [--file ./config/config.yaml | --dir DIR]
                                     write a new config.yaml, and a secret.key
                                     beside it unless one is there (--file -
                                     prints config.yaml instead)
  example [--file ./config/config.example.yaml]
                                     write the committed example: every
                                     default (--file - prints it)
  secret [--file ./config/secret.key]
                                     write a new secret.key; never replaces
                                     one (--file - prints a fresh key)
  migrate [--file path | --dir DIR]  move server.secret_key out of an older
                                     config.yaml into secret.key; silent when
                                     there is nothing to do
  check [--file path]                validate the config in use and its
                                     secret.key, and say which files they are
  set [--file path] section.key value
                                     change one setting in place, keeping
                                     every comment; a running server applies
                                     it within seconds. Lists: [a, b] or a,b
  shell [--file path] [--format sh|bat] server|docker
                                     print one section as assignments for the
                                     scripts to read: sh (quoted, for eval) or
                                     bat (plain key=value, for for /f).
                                     server is every resolved path and the URL

Without --file, the file is found the way the server finds it:
  ./config/config.yaml, then ~/.config/{config.APP_SLUG}/config.yaml
"""


def run(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="python -m app config", description=USAGE,
                                     formatter_class=argparse.RawDescriptionHelpFormatter, add_help=True)
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="write a new config.yaml, and a secret.key beside it")
    init.add_argument("--file", default=str(Path(config.CONFIG_DIR_NAME) / config.CONFIG_FILE_NAME), help="where to write it; - for stdout")
    init.add_argument("--dir", default="", help="folder for config.yaml and secret.key")

    example = commands.add_parser("example", help="write config.example.yaml: every default")
    example.add_argument("--file", default=str(Path(config.CONFIG_DIR_NAME) / config.EXAMPLE_FILE_NAME), help="where to write it; - for stdout")

    secret = commands.add_parser("secret", help="write a new secret.key")
    secret.add_argument("--file", default=str(Path(config.CONFIG_DIR_NAME) / config.SECRET_FILE_NAME), help="where to write it; - prints a fresh key")

    migrate = commands.add_parser("migrate", help="move server.secret_key out of config.yaml into secret.key")
    migrate.add_argument("--file", default="", help="config file to migrate (default: the one in use)")
    migrate.add_argument("--dir", default="", help="folder holding config.yaml")

    check = commands.add_parser("check", help="validate the config in use")
    check.add_argument("--file", default="", help="config file to check (default: the one in use)")

    set_parser = commands.add_parser("set", help="change one setting in place")
    set_parser.add_argument("--file", default="", help="config file to change (default: the one in use)")
    set_parser.add_argument("key", help="section.key, e.g. server.public_url")
    set_parser.add_argument("value", help="the new value")

    shell = commands.add_parser("shell", help="print one section as shell assignments")
    shell.add_argument("--file", default="", help="config file to read (default: the one in use)")
    shell.add_argument("--format", choices=["sh", "bat"], default="sh", help="sh (single-quoted, for eval) or bat (plain key=value)")
    shell.add_argument("section", choices=["server", "docker"])

    args = parser.parse_args(arguments)
    {
        "init": command_init,
        "example": command_example,
        "secret": command_secret,
        "migrate": command_migrate,
        "check": command_check,
        "set": command_set,
        "shell": command_shell,
    }[args.command](args)


def _config_path(args: argparse.Namespace) -> str:
    """--file, or --dir DIR meaning DIR/config.yaml (and so DIR/secret.key).
    docker/lib.sh uses --dir with the project's config/ folder mounted, which
    lets the files be created as the invoking user."""
    if getattr(args, "dir", ""):
        return str(Path(args.dir) / config.CONFIG_FILE_NAME)
    return args.file


def command_init(args: argparse.Namespace) -> None:
    from app.core import config_secret

    path = _config_path(args)
    if path == "-":
        sys.stdout.write(config.new_file_content())
        return
    secret_created = config.write_new(Path(path))
    print(f"wrote {path} (mode 0600)")
    if secret_created:
        print(f"wrote {config_secret.secret_path_for(Path(path))} (mode 0600, fresh secret key)")
    else:
        print(f"kept  {config_secret.secret_path_for(Path(path))} (already there)")
    print("Keep both out of version control, and back secret.key up with the app's data.")


def command_secret(args: argparse.Namespace) -> None:
    """secret.key on its own: for a config.yaml copied from
    config.example.yaml, or a fresh install whose config came from
    elsewhere."""
    from app.core import config_secret

    if args.file == "-":
        print(config_secret.generate_secret())
        return
    try:
        config_secret.write_secret(Path(args.file), config_secret.generate_secret())
    except FileExistsError:
        raise config.ConfigError(f"{args.file} already exists -- an existing key is never replaced") from None
    print(f"wrote {args.file} (mode 0600, fresh secret key -- back it up with the app's data)")


def command_migrate(args: argparse.Namespace) -> None:
    """migrate_legacy_secret from the command line. scripts/run.sh and
    docker/run.sh run it before every start, so it says nothing unless it did
    something."""
    from app.core import config_secret

    path = Path(_config_path(args)) if (args.file or args.dir) else config.locate()[0]
    if not path.is_file():
        return
    result = config_secret.migrate_legacy_secret(path)
    if result.moved:
        print(f"MOVED server.secret_key out of {path} into {result.secret_file} (mode 0600).")
        print("  config.yaml holds no secret now; back secret.key up with the app's data.")
    elif result.removed:
        print(f"Removed server.secret_key from {path}; {result.secret_file} already held the same key.")


def command_set(args: argparse.Namespace) -> None:
    """Change one setting the way the Settings screen does: the value is
    checked against the schema, written in place, and the whole file
    validated before anything is written."""
    from app.core import config_live, config_schema
    from app.core.layout import PINNED, in_container

    path = Path(args.file) if args.file else config.locate()[0]
    key = config_schema.schema_key(args.key)
    if key is None:
        raise config_live.UnknownSettingError(args.key)
    value = config_schema.parse_value(key, args.value)
    try:
        raw = config_live.read_raw(path)
    except OSError as error:
        raise config.ConfigError(f"could not read {path}: {error.strerror}") from None
    edited, unchanged = config_live.edit_changes(raw, {key.path: value}, str(path), False)
    if unchanged:
        print(f"{key.path} is already {args.value} in {path}")
        return
    in_place = in_container() and str(path) == PINNED.config_file
    backup = Path(PINNED.app_dir) / config.BACKUP_FILE_NAME if in_place else None
    config_live.write_config_file(path, edited, in_place, backup)
    when = {
        config_schema.MODE_LIVE: "a running server applies it within seconds",
        config_schema.MODE_SCRIPTS: "used the next time the scripts run",
    }.get(key.mode, "takes effect when the server restarts")
    print(f"set {key.path} in {path} -- {when}")


def command_example(args: argparse.Namespace) -> None:
    """Regenerate config.example.yaml from the defaults, so after changing a
    default the example can be brought back in step with one command instead
    of by hand."""
    if args.file == "-":
        sys.stdout.write(config.example_file_content())
        return
    config.write_example(Path(args.file))
    print(f"wrote {args.file} (no secret key -- safe to commit)")


def pick_file(explicit: str) -> tuple[config.File, Path, bool]:
    """The --file given, or the file the server would use. found is False when
    there is no file, in which case the defaults apply."""
    if explicit == "":
        return config.current()
    path = Path(explicit)
    if not path.is_file():
        return config.defaults(), path, False
    return config.read_file(path), path, True


def command_check(args: argparse.Namespace) -> None:
    file, path, found = pick_file(args.file)
    if not found:
        if args.file:
            raise config.ConfigError(f"{path} does not exist")
        print(f"no config.yaml yet -- the server will create {path} on first run (scripts/run.sh writes ./config/config.yaml instead)")
        return
    from app.core import config_secret

    secret_path = config_secret.secret_path_for(path)
    if file.server.secret_key:
        print(f"warning: {path} still holds server.secret_key -- `config migrate` moves it into {secret_path}")
    else:
        config_secret.read_secret(secret_path)
    print(f"ok  {path}")
    if secret_path.is_file():
        print(f"ok  {secret_path}")
    warning = config.permission_warning(path, secret_path)
    if warning:
        print(f"warning: {warning}")
    try:
        if os.stat(path).st_nlink == 0:
            print("warning: config.yaml was replaced on the host since this container started; restart it to see the new file")
    except OSError:
        pass


def shell_quote(value: str) -> str:
    """Single-quote a value for POSIX sh, which makes any content inert under
    eval -- on top of validate() having already rejected anything unusual."""
    return "'" + value.replace("'", "'\\''") + "'"


def _flag(value: bool) -> str:
    return "true" if value else "false"


def command_shell(args: argparse.Namespace) -> None:
    file, path, found = pick_file(args.file)
    path = path.absolute()
    if args.section == "server":
        # What the server would use, resolved exactly as load() resolves it,
        # without creating anything. The scripts print these instead of
        # guessing, so what they say is what will happen.
        paths = config.resolve_paths(file, path)
        url, url_source = config.server_url(file)
        lines = [
            ("config_file", str(path)),
            ("config_exists", _flag(found)),
            ("secret_file", str(path.parent / config.SECRET_FILE_NAME)),
            ("secret_exists", _flag((path.parent / config.SECRET_FILE_NAME).is_file())),
            ("project_dir", str(paths.project_dir)),
            ("app_dir", str(paths.app_dir)),
            ("database", str(paths.database_path)),
            ("database_exists", _flag(paths.database_path.is_file())),
            ("static_dir", paths.static_dir),
            ("static_on_disk", _flag(bool(paths.static_dir) and Path(paths.static_dir).is_dir())),
            ("language_file", paths.language_file),
            ("language_on_disk", _flag(bool(paths.language_file) and Path(paths.language_file).is_file())),
            ("host", file.server.host),
            ("port", str(file.server.port)),
            ("url", url),
            ("url_source", url_source),
            ("public_url", file.server.public_url),
            ("secure_cookies", _flag(file.server.secure_cookies)),
            ("trust_proxy", _flag(file.server.trust_proxy)),
        ]
    else:
        docker = file.docker
        # The full -p value is assembled here so the script does not have to
        # know that an IPv6 address needs brackets.
        bind = f"[{docker.bind_address}]" if ":" in docker.bind_address else docker.bind_address
        url, url_source = config.docker_url(file)
        lines = [
            ("docker_image", docker.image),
            ("docker_container", docker.container),
            ("docker_bind_address", docker.bind_address),
            ("docker_host_port", str(docker.host_port)),
            ("docker_publish", f"{bind}:{docker.host_port}:{file.server.port}"),
            ("docker_data_dir", docker.data_dir),
            ("docker_restart", docker.restart),
            ("docker_memory", docker.memory),
            ("docker_cpus", docker.cpus),
            ("docker_pids_limit", str(docker.pids_limit)),
            ("docker_tmpfs_size", docker.tmpfs_size),
            ("server_port", str(file.server.port)),
            ("server_secure_cookies", _flag(file.server.secure_cookies)),
            ("server_trust_proxy", _flag(file.server.trust_proxy)),
            ("docker_url", url),
            ("docker_url_source", url_source),
        ]
    # Never the secret key, only where it is: nothing a script does needs it, and this output
    # tends to end up in terminal scrollback and CI logs.
    for name, value in lines:
        if args.format == "bat":
            # cmd has no quoting to undo; for /f "tokens=1,* delims==" splits
            # on the first = and keeps the rest of the line as the value.
            sys.stdout.write(f"{name}={value.replace(chr(13), ' ').replace(chr(10), ' ')}\r\n")
        else:
            print(f"{name}={shell_quote(value)}")
