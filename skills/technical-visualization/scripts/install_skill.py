#!/usr/bin/env python3
"""Copy this entire skill into Codex; refuse to replace a different installation."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile

IGNORE = shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store', 'tests', 'install_skill.py')


def inventory(root):
    result = {}
    for path in sorted(root.rglob('*')):
        rel_parts = path.relative_to(root).parts
        if (
            '__pycache__' in rel_parts
            or 'tests' in rel_parts
            or path.suffix == '.pyc'
            or path.name in {'.DS_Store', 'install_skill.py'}
        ):
            continue
        if path.is_symlink():
            raise ValueError(f'Symlinked package content is unsupported: {path}')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def install(source, destination, check=False):
    source, destination = source.resolve(), destination.absolute()
    if source == destination.resolve():
        return 'Source is the installed directory; no copy needed.'
    if source in destination.resolve().parents:
        raise ValueError('Destination cannot be inside the source skill.')
    expected = inventory(source)
    if 'SKILL.md' not in expected or 'name: technical-visualization' not in (source / 'SKILL.md').read_text(encoding='utf-8'):
        raise ValueError('Source is not the technical-visualization skill.')
    if destination.exists() or destination.is_symlink():
        if destination.is_dir() and inventory(destination) == expected:
            return f'Installation verified: {destination}'
        raise ValueError('Destination exists with different content. Choose a new destination or move your existing installation to a backup first.')
    if check:
        raise ValueError(f'Not installed: {destination}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.technical-visualization-', dir=destination.parent) as temp:
        staging = Path(temp) / 'technical-visualization'
        shutil.copytree(source, staging, ignore=IGNORE)
        if inventory(staging) != expected:
            raise ValueError('Copied files failed verification.')
        if destination.exists() or destination.is_symlink():
            raise ValueError('Destination appeared during installation; no replacement performed.')
        staging.rename(destination)
    if inventory(destination) != expected:
        raise ValueError('Installed files failed verification.')
    return f'Installed and verified: {destination}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    if 'CODEX_HOME' in os.environ:
        default_root = Path(os.environ['CODEX_HOME']) / 'skills'
    else:
        default_root = Path.home() / '.agents' / 'skills'
    parser.add_argument('--dest', type=Path, default=default_root / 'technical-visualization',
                        help='Full destination skill directory, not its parent.')
    parser.add_argument('--check', action='store_true', help='Compare installed bytes without writing.')
    args = parser.parse_args()
    try:
        print(install(Path(__file__).resolve().parents[1], args.dest, args.check))
        return 0
    except (OSError, ValueError) as exc:
        print(f'Installation error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
