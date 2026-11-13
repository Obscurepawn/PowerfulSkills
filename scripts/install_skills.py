#!/usr/bin/env python3
"""Install and verify skills from this repository without copying test suites."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile

SKIP_DIRS = {"__pycache__", "tests"}
SKIP_FILES = {".DS_Store", "install_skill.py"}
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "tests", "install_skill.py")


def inventory(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel_parts = path.relative_to(root).parts
        if (
            any(part in SKIP_DIRS for part in rel_parts)
            or path.suffix == ".pyc"
            or path.name in SKIP_FILES
        ):
            continue
        if path.is_symlink():
            raise ValueError(f"Symlinked package content is unsupported: {path}")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def install_one(source: Path, destination: Path, check: bool = False, force: bool = False) -> str:
    source = source.resolve()
    destination = destination.absolute()
    if source == destination.resolve():
        return f"skip (same directory): {destination}"
    if source in destination.resolve().parents:
        raise ValueError(f"Destination cannot be inside source skill: {destination}")
    expected = inventory(source)
    if "SKILL.md" not in expected:
        raise ValueError(f"Missing SKILL.md in {source}")

    if destination.exists() or destination.is_symlink():
        if destination.is_dir() and not destination.is_symlink() and inventory(destination) == expected:
            return f"verified: {destination}"
        if check or not force:
            raise ValueError(
                f"Destination differs from source: {destination} "
                "(pass --force to replace, or back up your local changes first)"
            )

    if check:
        raise ValueError(f"Not installed: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{source.name}-", dir=destination.parent) as tmp:
        staging = Path(tmp) / source.name
        shutil.copytree(source, staging, ignore=IGNORE)
        if inventory(staging) != expected:
            raise ValueError(f"Staging verification failed for {source.name}")
        backup = None
        if destination.exists() or destination.is_symlink():
            backup = Path(tmp) / f"{source.name}.old"
            destination.rename(backup)
        try:
            staging.rename(destination)
        except Exception:
            if backup is not None and not destination.exists():
                backup.rename(destination)
            raise
    if inventory(destination) != expected:
        raise ValueError(f"Installed verification failed for {destination}")
    return f"installed: {destination}"


def default_dest_root() -> Path:
    if "CODEX_HOME" in os.environ:
        return Path(os.environ["CODEX_HOME"]) / "skills"
    return Path.home() / ".agents" / "skills"


def main(argv=None) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    skills_dir = repo_root / "skills"
    available = sorted(p.name for p in skills_dir.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dest-root",
        type=Path,
        default=default_dest_root(),
        help="Target skills parent directory (e.g. ~/.agents/skills, ~/.claude/skills, ~/.gemini/config/skills).",
    )
    parser.add_argument(
        "--skill",
        action="append",
        choices=available,
        help="Install or check only selected skill(s); omit to process all skills.",
    )
    parser.add_argument("--check", action="store_true", help="Verify installed copies without modifying files.")
    parser.add_argument("--force", action="store_true", help="Atomically replace differing existing installations.")
    args = parser.parse_args(argv)

    selected = args.skill or available
    errors = 0
    for name in selected:
        try:
            msg = install_one(skills_dir / name, args.dest_root / name, check=args.check, force=args.force)
            print(f"[{name}] {msg}")
        except (OSError, ValueError) as exc:
            print(f"[{name}] error: {exc}", file=sys.stderr)
            errors += 1
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
