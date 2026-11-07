"""`python -m app config ...` -- create, check, or read config.yaml.

These exist so that nothing else has to parse YAML. The scripts in scripts/
and docker/ eval the output of `config shell server|docker`, which means they
get the same defaults, the same strict decoding, the same validation and the
same resolved paths as the server -- a typo fails the deploy before anything
starts, instead of being ignored by a second, looser parser, and what a
script prints is what the server will do.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.core import config

USAGE = f"""config -- create, check, or read config.yaml

Usage:
  init  [--file ./config/config.yaml]
                                     write a new config.yaml with a fresh
                                     secret key (--file - prints it instead)
  example [--file ./config/config.example.yaml]
                                     write the committed example: every
                                     default, no secret key (--file - prints it)
  check [--file path]                validate the config in use and say which
                                     file it is
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

    init = commands.add_parser("init", help="write a new config.yaml with a fresh secret key")
    init.add_argument("--file", default=str(Path(config.CONFIG_DIR_NAME) / config.CONFIG_FILE_NAME), help="where to write it; - for stdout")

    example = commands.add_parser("example", help="write config.example.yaml: every default, no secret key")
    example.add_argument("--file", default=str(Path(config.CONFIG_DIR_NAME) / config.EXAMPLE_FILE_NAME), help="where to write it; - for stdout")

    check = commands.add_parser("check", help="validate the config in use")
    check.add_argument("--file", default="", help="config file to check (default: the one in use)")

    shell = commands.add_parser("shell", help="print one section as shell assignments")
    shell.add_argument("--file", default="", help="config file to read (default: the one in use)")
    shell.add_argument("--format", choices=["sh", "bat"], default="sh", help="sh (single-quoted, for eval) or bat (plain key=value)")
    shell.add_argument("section", choices=["server", "docker"])

    args = parser.parse_args(arguments)
    {"init": command_init, "example": command_example, "check": command_check, "shell": command_shell}[args.command](args)


def command_init(args: argparse.Namespace) -> None:
    if args.file == "-":
        sys.stdout.write(config.new_file_content())
        return
    config.write_new(Path(args.file))
    print(f"wrote {args.file} (mode 0600, fresh secret key)")
    print("Review it, then keep it out of version control and back it up with the app's data.")


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
    config.check_secret_key(file, path)
    print(f"ok  {path}")
    warning = config.permission_warning(path)
    if warning:
        print(f"warning: {warning}")


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
    # Never the secret key: nothing a script does needs it, and this output
    # tends to end up in terminal scrollback and CI logs.
    for name, value in lines:
        if args.format == "bat":
            # cmd has no quoting to undo; for /f "tokens=1,* delims==" splits
            # on the first = and keeps the rest of the line as the value.
            sys.stdout.write(f"{name}={value.replace(chr(13), ' ').replace(chr(10), ' ')}\r\n")
        else:
            print(f"{name}={shell_quote(value)}")
