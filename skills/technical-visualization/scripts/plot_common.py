"""Shared local-only validation, style, and reproducible bundle export."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from importlib.metadata import version, PackageNotFoundError
import platform
import shlex
from pathlib import Path
import shutil
import sys
import tempfile
import warnings

COLORS = ['#0072B2', '#D55E00', '#009E73', '#CC79A7', '#E69F00', '#56B4E9', '#000000']
STYLES = ['-', '--', '-.', ':']
MARKERS = ['o', 's', '^', 'D', 'v', 'P', 'X']
SHARED_KEYS = {'title', 'source', 'data_kind', 'width', 'height', 'font_size', 'font_family'}

class DataError(ValueError):
    """Invalid data/configuration with a user-readable message."""


def load_plotting_deps():
    """Import numpy and matplotlib on demand; fail cleanly with install instructions if absent."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        import numpy as np
    except ModuleNotFoundError as exc:
        root = Path(__file__).resolve().parents[1]
        req = root / 'requirements.txt' if (root / 'requirements.txt').is_file() else root / 'requirements-lock.txt'
        raise DataError(
            f'missing plotting dependency {exc.name!r}; install with: python3 -m pip install -r {req}'
        ) from None
    return np, matplotlib, plt, font_manager


def finite_number(value, label):
    if isinstance(value, bool):
        raise DataError(f'{label} must be a finite number, not a boolean')
    try:
        number = float(value)
    except (ValueError, TypeError):
        raise DataError(f'{label} must be a finite number') from None
    if not math.isfinite(number):
        raise DataError(f'{label} must be finite; missing/NaN/infinity values are not imputed')
    return number


def integer(value, label, minimum, maximum):
    number = finite_number(value, label)
    if number != int(number) or not minimum <= number <= maximum:
        raise DataError(f'{label} must be an integer in [{minimum}, {maximum}]')
    return int(number)


def nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise DataError(f'{label} must be a nonempty string')
    if any(ord(char) < 32 and char not in '\n\t' for char in value):
        raise DataError(f'{label} contains control characters')
    return value.strip()


def load_config(path, extra_keys):
    def reject_constant(value):
        raise DataError(f'JSON contains nonfinite constant {value}')
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise DataError(f'duplicate config key: {key}')
            result[key] = value
        return result
    config = json.loads(Path(path).read_text(encoding='utf-8'), parse_constant=reject_constant, object_pairs_hook=unique_keys)
    if not isinstance(config, dict):
        raise DataError('config must be a JSON object')
    unknown = set(config) - SHARED_KEYS - extra_keys
    if unknown:
        raise DataError(f'unknown config keys: {", ".join(sorted(unknown))}')
    for key in ('title', 'source', 'data_kind'):
        config[key] = nonempty(config.get(key), key)
    if config['data_kind'] not in {'observed', 'synthetic'}:
        raise DataError('data_kind must be observed or synthetic')
    for key, default, low, high in [('width', 8, 4, 24), ('height', 5, 3, 24), ('font_size', 10, 8, 24)]:
        config[key] = finite_number(config.get(key, default), key)
        if not low <= config[key] <= high:
            raise DataError(f'{key} must be between {low} and {high}')
    config['font_family'] = nonempty(config.get('font_family', 'DejaVu Sans'), 'font_family')
    _, _, _, font_manager = load_plotting_deps()
    try:
        font_manager.findfont(font_manager.FontProperties(family=config['font_family']), fallback_to_default=False)
    except ValueError as exc:
        raise DataError(f'font_family {config["font_family"]!r} is unavailable; install or select a local font') from exc
    return config


def read_csv(path, fields):
    with Path(path).open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != fields:
            raise DataError(f'CSV columns must be exactly: {",".join(fields)}')
        rows = []
        for line, row in enumerate(reader, 2):
            if None in row or any(value is None or not value.strip() for value in row.values()):
                raise DataError(f'CSV row {line} has missing or extra fields')
            rows.append((line, {key: value.strip() for key, value in row.items()}))
    if not rows:
        raise DataError('CSV has no observations')
    return rows


def apply_style(config):
    _, _, plt, _ = load_plotting_deps()
    plt.rcParams.update({
        'font.family': config['font_family'], 'font.size': config['font_size'],
        'axes.titlesize': config['font_size'] + 1, 'axes.labelsize': config['font_size'],
        'legend.fontsize': config['font_size'], 'xtick.labelsize': config['font_size'],
        'ytick.labelsize': config['font_size'], 'svg.fonttype': 'none', 'pdf.fonttype': 42,
        'svg.hashsalt': 'technical-visualization-v1', 'axes.spines.top': False,
        'axes.spines.right': False, 'axes.grid': True, 'grid.alpha': 0.2,
        'figure.facecolor': 'white', 'savefig.facecolor': 'white', 'text.usetex': False,
        'axes.formatter.useoffset': False,
    })


def decorate(fig, config, subtitle):
    title = config['title']
    if config['data_kind'] == 'synthetic':
        title = 'SYNTHETIC EXAMPLE — ' + title
    fig.suptitle(title, fontsize=config['font_size'] + 2, fontweight='bold')
    fig.supxlabel(subtitle, fontsize=config['font_size'])


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_csv(path, fields, rows):
    with Path(path).open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: '' if isinstance(row[key], float) and math.isnan(row[key]) else row[key] for key in fields})


def export_bundle(args, config, kind, fig, rows, fields, caption, notes, groups):
    """Validate output, write to a staging directory, then commit the bundle."""
    np, matplotlib, plt, font_manager = load_plotting_deps()
    destination = Path(args.output).resolve()
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise DataError(f'output exists and is not empty: {destination}; choose a new directory')
    destination.parent.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).with_name(f'plot_{kind}.py')
    with tempfile.TemporaryDirectory(prefix='.technical-vis-', dir=destination.parent) as staging:
        bundle = Path(staging) / 'bundle'
        (bundle / 'inputs').mkdir(parents=True)
        (bundle / 'code').mkdir()
        for source, target in [(Path(args.input), bundle / 'inputs/data.csv'), (Path(args.config), bundle / 'inputs/config.json'), (script, bundle / 'code' / script.name), (Path(__file__), bundle / 'code/plot_common.py')]:
            shutil.copyfile(source, target)
        packages = {}
        for package in ['numpy', 'matplotlib', 'contourpy', 'cycler', 'fonttools', 'kiwisolver', 'packaging', 'pillow', 'pyparsing', 'python-dateutil', 'six']:
            try:
                packages[package] = version(package)
            except PackageNotFoundError:
                pass
        (bundle / 'requirements-lock.txt').write_text(''.join(f'{name}=={release}\n' for name, release in packages.items()), encoding='utf-8')
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            fig.canvas.draw()
            layout = {
                'units': 'pt',
                'figure': {'width': fig.get_figwidth() * 72, 'height': fig.get_figheight() * 72},
                'panels': [], 'comparison_groups': groups,
            }
            for index, ax in enumerate(fig.axes):
                box = ax.get_position()
                layout['panels'].append({'id': chr(ord('a') + index), 'bounds': [box.x0 * fig.get_figwidth() * 72, box.y0 * fig.get_figheight() * 72, box.x1 * fig.get_figwidth() * 72, box.y1 * fig.get_figheight() * 72]})
            fig.savefig(bundle / 'figure.svg', metadata={'Date': None, 'Creator': 'technical-visualization'})
            fig.savefig(bundle / 'figure.pdf', metadata={'CreationDate': None, 'ModDate': None, 'Creator': 'technical-visualization'})
            fig.savefig(bundle / 'figure.png', dpi=180, metadata={'Software': 'technical-visualization'})
        render_warnings = sorted({str(w.message) for w in caught})
        missing_glyphs = [message for message in render_warnings if 'Glyph' in message and 'missing' in message]
        if missing_glyphs:
            raise DataError('selected font lacks required characters; choose font_family with glyph coverage: ' + missing_glyphs[0])
        notes = list(notes) + render_warnings
        (bundle / 'layout.json').write_text(json.dumps(layout, indent=2) + '\n', encoding='utf-8')
        write_csv(bundle / 'derived.csv', fields, rows)
        (bundle / 'caption.txt').write_text(caption + '\n', encoding='utf-8')
        command = ['python3', f'code/{script.name}', '--input', 'inputs/data.csv', '--config', 'inputs/config.json', '--output', '../replayed-' + destination.name]
        readme = 'Run from this directory with the recorded Python/package versions.\nInstall dependencies: python3 -m pip install -r requirements-lock.txt\nReplay: ' + shlex.join(command) + '\n\nUse a different --output path if it already exists. Input files are never modified.\nFont: ' + config['font_family'] + '\nRender equality is expected only with the same OS, fonts and dependency stack.\nThe lock file records the installed plotting dependency stack; the manifest records Python and platform.\nInspect SVG/PDF at final size and resolve QA findings before presenting conclusions.\n'
        (bundle / 'REPRODUCE.txt').write_text(readme, encoding='utf-8')
        input_paths = [('inputs/data.csv', 'data'), ('inputs/config.json', 'configuration'), (f'code/{script.name}', 'code'), ('code/plot_common.py', 'code'), ('requirements-lock.txt', 'dependencies')]
        manifest = {
            'schema_version': 1, 'kind': kind, 'data_kind': config['data_kind'],
            'inputs': [{'path': name, 'sha256': sha256(bundle / name), 'role': role} for name, role in input_paths],
            'outputs': [{'path': name, 'sha256': sha256(bundle / name)} for name in ['figure.svg', 'figure.pdf', 'figure.png', 'derived.csv', 'caption.txt', 'layout.json', 'REPRODUCE.txt']],
            'parameters': config,
            'environment': {'python': platform.python_version(), 'platform': platform.platform(), 'numpy': np.__version__, 'matplotlib': matplotlib.__version__, 'font_family': config['font_family'], 'font_sha256': sha256(font_manager.findfont(font_manager.FontProperties(family=config['font_family']), fallback_to_default=False)), 'packages': packages},
            'command': command, 'warnings': notes,
            'checks': {'input_validation': 'passed', 'nonfinite_values': 'rejected', 'visual_review': 'required', 'statistics_review': 'required', 'source_declaration': 'user-supplied, not independently verified'},
        }
        (bundle / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
        if destination.exists():
            destination.rmdir()  # Only an empty directory can be removed.
        bundle.rename(destination)
    plt.close(fig)
    print(f'Wrote {destination}; visual and semantic review remain required.')


def cli(run):
    parser = argparse.ArgumentParser(description=run.__doc__)
    parser.add_argument('--input', required=True, help='UTF-8 CSV matching the documented schema')
    parser.add_argument('--config', required=True, help='JSON figure and provenance configuration')
    parser.add_argument('--output', required=True, help='New or empty bundle directory')
    args = parser.parse_args()
    try:
        run(args)
    except (DataError, OSError, json.JSONDecodeError, csv.Error) as exc:
        parser.exit(2, f'error: {exc}\n')
