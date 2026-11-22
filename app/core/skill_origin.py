"""Which webserver skill, at which commit, this app was scaffolded from (or
last upgraded to): /api/me reports it as skill and skill_commit, so
ProjectPortal can say when an app is behind its template."""
from __future__ import annotations

from pathlib import Path

import yaml

from app.core.config import CODE_ROOT

ORIGIN_PATH = CODE_ROOT / ".skill-origin.yaml"


def skill_origin(path: Path = ORIGIN_PATH) -> tuple[str, str]:
    """(skill, commit). The Docker image has no .skill-origin.yaml, so the
    Dockerfile writes both into app/build_info.py (docker/lib.sh reads the
    file on the host); anywhere else the file beside app/ is read. ("", "")
    when neither says."""
    try:
        from app import build_info  # type: ignore[attr-defined]

        stamped = getattr(build_info, "SKILL", ""), getattr(build_info, "SKILL_COMMIT", "")
        if path == ORIGIN_PATH and stamped[0]:
            return stamped
    except ImportError:
        pass
    try:
        origin = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return "", ""
    if not isinstance(origin, dict):
        return "", ""
    return str(origin.get("skill") or ""), str(origin.get("commit") or "")
