#!/usr/bin/env python3
"""Resolve Scribe's vault and manage its session registries.

The vault is resolved from $MEMORY_VAULT, then ~/.scribe/config.json, then by
walking up from this script to an enclosing directory that contains .scribe/.
All command output is JSON.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

TAGS_STUB = "# Tag vocabulary: a flat, sorted list with one `- tag` per line.\n"


def config_path(override: str | None = None) -> Path:
    if override:
        return Path(override).expanduser()
    return Path("~/.scribe/config.json").expanduser()


def read_vault(path: Path) -> str | None:
    """Read the vault path from a config file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data, dict) and isinstance(data.get("vault"), str) and data["vault"]:
        return data["vault"]
    return None


def write_config(path: Path, vault: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"vault": str(vault)}, indent=2) + "\n")


def enclosing_vault() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".scribe").is_dir():
            return parent
    return None


def resolve_vault(path: Path) -> dict:
    """Locate the vault from the environment, the config file, or an enclosing directory."""
    override = os.environ.get("MEMORY_VAULT")
    if override:
        return found(override, "MEMORY_VAULT")

    configured = read_vault(path)
    if configured:
        return found(configured, str(path))

    nearby = enclosing_vault()
    if nearby:
        return found(nearby, "enclosing directory")

    return {"configured": False, "vault": None, "source": None}


def found(vault: str | Path, source: str) -> dict:
    return {
        "configured": True,
        "vault": str(Path(vault).expanduser().resolve()),
        "source": source,
    }


def init_vault(root: Path, path: Path) -> dict:
    existed = root.is_dir()
    (root / ".scribe" / "state").mkdir(parents=True, exist_ok=True)
    (root / "journal").mkdir(exist_ok=True)
    tags = root / "tags.yaml"
    if not tags.exists():
        tags.write_text(TAGS_STUB)
    write_config(path, root)
    return {"vault": str(root), "existed": existed, "config": str(path)}


def registries_for_sessions(vault: Path, session_uuids: set[str]) -> list[dict]:
    """Return active registries containing every supplied working-session UUID."""
    if not session_uuids:
        raise ValueError("At least one working-session UUID is required")
    matches = []
    for path in sorted((vault / ".scribe" / "state").glob("*.json")):
        try:
            registry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        sessions = registry.get("sessions")
        if isinstance(sessions, dict) and session_uuids.issubset(sessions):
            matches.append({"registry": str(path), "data": registry})
    return matches


def emit(value: object) -> None:
    print(json.dumps(value, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Override the config file path")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--resolve-vault", action="store_true")
    group.add_argument("--init-vault", action="store_true")
    group.add_argument("--find-by-sessions", action="store_true")
    parser.add_argument("--path", help="Vault path for --init-vault")
    parser.add_argument(
        "--session-uuids",
        help="Comma-separated working-session UUIDs for --find-by-sessions",
    )
    args = parser.parse_args()
    path = config_path(args.config)

    try:
        if args.init_vault:
            if not args.path:
                raise ValueError("--init-vault requires --path")
            emit(init_vault(Path(args.path).expanduser().resolve(), path))
            return

        resolved = resolve_vault(path)
        if args.resolve_vault:
            emit(resolved)
            return

        if not resolved["configured"]:
            raise ValueError("No vault is configured; run --init-vault first")
        session_uuids = {
            value.strip() for value in (args.session_uuids or "").split(",") if value.strip()
        }
        if not session_uuids:
            raise ValueError("--find-by-sessions requires --session-uuids")
        emit(registries_for_sessions(Path(resolved["vault"]), session_uuids))
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc), "config": str(path)}), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
