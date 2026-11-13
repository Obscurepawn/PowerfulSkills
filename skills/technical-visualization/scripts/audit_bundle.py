#!/usr/bin/env python3
"""Audit bundle integrity and exported geometry; never certify data truth."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def svg_text_candidates(svg):
    """Return live text after obvious hiding rules, not a complete CSS render."""
    excluded, hidden_count, definition_text_count = {}, 0, 0
    nonrendered = {'defs', 'clipPath', 'mask'}

    def walk(node, blocked=False, visibility='visible', in_definition=False):
        nonlocal hidden_count, definition_text_count
        tag = node.tag.split('}')[-1]
        properties = {key: node.get(key, '').strip().lower()
                      for key in ('display', 'visibility', 'opacity')}
        for declaration in node.get('style', '').split(';'):
            if ':' in declaration:
                key, value = declaration.split(':', 1)
                key = key.strip().lower()
                if key in properties:
                    properties[key] = value.strip().lower().replace('!important', '').strip()
        opacity = properties['opacity']
        try:
            transparent = bool(opacity) and float(opacity.rstrip('%')) <= 0
        except ValueError:
            transparent = False
        blocked = blocked or properties['display'] == 'none' or transparent
        visibility = properties['visibility'] or visibility
        hidden = blocked or visibility in ('hidden', 'collapse')
        in_definition = in_definition or tag in nonrendered
        excluded[node] = hidden or in_definition
        hidden_count += int(hidden)
        definition_text_count += int(in_definition and tag == 'text')
        for child in node:
            walk(child, blocked, visibility, in_definition)

    def content(node):
        if excluded[node]:
            return ''
        pieces = [node.text or '']
        for child in node:
            pieces.extend((content(child), child.tail or ''))
        return ''.join(pieces)

    walk(svg)
    texts = [content(node).strip() for node in svg.iter()
             if node.tag.split('}')[-1] == 'text' and not excluded[node]]
    return texts, hidden_count, definition_text_count


def audit_bundle(bundle, min_pt=8.0, tolerance_pt=1.5):
    root = Path(bundle).resolve()
    issues, measurements = [], {}

    def issue(level, check, message, **context):
        issues.append(dict(level=level, check=check, message=message, **context))

    def finish():
        status = 'fail' if any(x['level'] == 'fail' for x in issues) else (
            'review' if issues else 'pass')
        return {'schema_version': 1, 'automatic_status': status,
                'human_review': 'required', 'issues': issues, 'measurements': measurements,
                'scope': 'Hashes, formats and supported text/panel geometry only; no proof of data authenticity, inference, complete collision freedom or semantic correctness.'}

    try:
        manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        issue('fail', 'manifest', str(exc))
        return finish()
    if not isinstance(manifest, dict) or manifest.get('schema_version') != 1:
        issue('fail', 'manifest', 'Expected schema_version 1 object.')
        return finish()
    for field, typ in [('inputs', list), ('outputs', list), ('parameters', dict),
                       ('environment', dict), ('command', list), ('warnings', list), ('checks', dict)]:
        if not isinstance(manifest.get(field), typ):
            issue('fail', 'manifest', f'{field} must be {typ.__name__}.')
    if issues:
        return finish()
    if manifest.get('kind') not in ('benchmark', 'quant', 'architecture'):
        issue('fail', 'manifest', 'Unknown bundle kind.')
    if manifest.get('data_kind') not in ('observed', 'synthetic', 'proposed'):
        issue('fail', 'manifest', 'Unknown data_kind.')
    if not manifest['command'] or not all(isinstance(x, str) for x in manifest['command']):
        issue('fail', 'manifest', 'Replay command must be a nonempty argument list.')
    if not manifest['inputs'] or not manifest['outputs']:
        issue('fail', 'manifest', 'Inputs and outputs must be nonempty.')
    for warning in manifest['warnings']:
        issue('warn', 'producer-warning', str(warning))

    valid_outputs, seen = [], set()
    for group in ('inputs', 'outputs'):
        for entry in manifest[group]:
            if not isinstance(entry, dict) or not isinstance(entry.get('path'), str):
                issue('fail', 'manifest', 'File entries require path and sha256.')
                continue
            relative = entry['path']
            path = root / relative
            if not relative or Path(relative).is_absolute() or '..' in Path(relative).parts or '\\' in relative:
                issue('fail', 'path', 'File path must be a portable relative path.', file=relative)
                continue
            try:
                path.resolve().relative_to(root)
            except ValueError:
                issue('fail', 'path', 'Symlink escapes bundle.', file=relative)
                continue
            if relative in seen:
                issue('fail', 'manifest', 'Duplicate file entry.', file=relative)
            seen.add(relative)
            if not path.is_file():
                issue('fail', 'file', 'Missing file.', file=relative)
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != entry.get('sha256'):
                issue('fail', 'sha256', 'File differs from recorded digest.', file=relative)
            if group == 'outputs':
                valid_outputs.append(path)

    suffixes = {p.suffix.lower() for p in valid_outputs}
    for suffix in ('.svg', '.pdf', '.png'):
        if suffix not in suffixes:
            issue('fail', 'formats', f'Missing {suffix} output.')
    if manifest.get('kind') in ('benchmark', 'quant') and not any(p.name == 'layout.json' for p in valid_outputs):
        issue('fail', 'missing-layout', 'Data plot bundles require a listed layout.json output for panel geometry checks.')
    if not any(str(x.get('path', '')).endswith('.py') for x in manifest['inputs'] if isinstance(x, dict)):
        issue('fail', 'source', 'No replayable Python source in inputs.')

    for path in valid_outputs:
        relative = path.relative_to(root).as_posix()
        if path.suffix.lower() == '.svg':
            try:
                svg = ET.parse(path).getroot()
                if svg.tag.split('}')[-1] != 'svg':
                    raise ValueError('Root element is not svg.')
                box = [float(x) for x in svg.get('viewBox', '').replace(',', ' ').split()]
                if len(box) != 4 or not all(math.isfinite(x) for x in box) or box[2] <= 0 or box[3] <= 0:
                    raise ValueError('Missing or invalid positive viewBox.')
                nodes = list(svg.iter())
                texts, hidden_count, definition_text_count = svg_text_candidates(svg)
                measurements[relative] = {'text_elements': len(texts), 'viewBox': box,
                                          'obviously_hidden_elements': hidden_count,
                                          'definition_text_elements': definition_text_count}
                if hidden_count or definition_text_count:
                    issue('warn', 'svg-visibility', 'Hidden or definition-only elements were excluded from text checks; review actual visibility and CSS.', file=relative)
                if not any(texts):
                    issue('fail', 'svg-text', 'No live text; text may be outlined or rasterized.', file=relative)
                if any(n.tag.split('}')[-1] == 'image' for n in nodes):
                    issue('warn', 'svg-raster', 'Contains raster images; review whether data marks remain editable.', file=relative)
                if manifest['data_kind'] in ('synthetic', 'proposed'):
                    label = manifest['data_kind'].upper()
                    if label not in ' '.join(texts).upper():
                        issue('fail', 'data-label', f'Missing {label} label among text candidates after basic visibility checks.', file=relative)
            except (OSError, ValueError, ET.ParseError) as exc:
                issue('fail', 'svg', str(exc), file=relative)
        elif path.suffix.lower() == '.pdf':
            audit_pdf(path, relative, issue, measurements, min_pt)
        elif path.suffix.lower() == '.png':
            if path.read_bytes()[:8] != b'\x89PNG\r\n\x1a\n':
                issue('fail', 'png', 'Invalid PNG signature.', file=relative)
        elif path.name == 'layout.json':
            audit_layout(path, issue, measurements, tolerance_pt)
    return finish()


def audit_pdf(path, relative, issue, measurements, min_pt):
    if not path.read_bytes().startswith(b'%PDF-'):
        issue('fail', 'pdf', 'Invalid PDF signature.', file=relative)
        return
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz  # Compatibility with early PyMuPDF 1.24 releases.
    except ImportError:
        issue('warn', 'pdf-audit-unavailable', 'Install PyMuPDF to inspect actual PDF text geometry.', file=relative)
        return
    try:
        with fitz.open(path) as document:
            if len(document) == 0:
                raise ValueError('No PDF pages.')
            sizes, line_count, collisions = [], 0, []
            for page_index, page in enumerate(document):
                lines = []
                for block in page.get_text('dict')['blocks']:
                    for line in block.get('lines', []):
                        spans = [s for s in line['spans'] if s['text'].strip()]
                        if not spans:
                            continue
                        sizes.extend(float(s['size']) for s in spans)
                        text = ''.join(s['text'] for s in spans)
                        box = fitz.Rect(line['bbox'])
                        lines.append((box, text))
                        expanded = fitz.Rect(page.rect.x0 - 1, page.rect.y0 - 1, page.rect.x1 + 1, page.rect.y1 + 1)
                        if not expanded.contains(box):
                            issue('warn', 'pdf-clipping', 'Text bounds cross page boundary.', file=relative, page=page_index + 1, text=text)
                line_count += len(lines)
                for i, (box, label) in enumerate(lines):
                    for other, other_label in lines[i + 1:]:
                        overlap = box & other
                        area = min(box.get_area(), other.get_area())
                        if area > 0 and overlap.get_area() / area > 0.12:
                            collisions.append({'page': page_index + 1, 'text': label, 'other': other_label})
            measurements[relative] = {'pages': len(document), 'text_lines': line_count,
                                      'minimum_font_pt': min(sizes) if sizes else None,
                                      'possible_collisions': len(collisions)}
            if not sizes:
                issue('fail', 'pdf-text', 'No extractable text; inspect font encoding/editability.', file=relative)
            elif min(sizes) < min_pt - 0.05:
                issue('warn', 'pdf-font', f'Minimum rendered font {min(sizes):.2f} pt below {min_pt:g} pt.', file=relative)
            for collision in collisions[:25]:
                issue('warn', 'pdf-text-overlap', 'Text bounding boxes overlap; visually review.', file=relative, **collision)
            if len(collisions) > 25:
                issue('warn', 'pdf-text-overlap', f'{len(collisions)-25} additional overlap candidates.', file=relative)
    except Exception as exc:
        issue('fail', 'pdf', f'Cannot inspect PDF: {exc}', file=relative)


def audit_layout(path, issue, measurements, tolerance):
    try:
        layout = json.loads(path.read_text(encoding='utf-8'))
        if layout['units'] != 'pt':
            raise ValueError('Panel layout requires physical points.')
        width, height = float(layout['figure']['width']), float(layout['figure']['height'])
        if not all(math.isfinite(v) and v > 0 for v in (width, height)):
            raise ValueError('Invalid figure dimensions.')
        panels = {}
        for panel in layout['panels']:
            box = list(map(float, panel['bounds']))
            if len(box) != 4 or not all(math.isfinite(x) for x in box):
                raise ValueError('Invalid panel bounds.')
            if panel['id'] in panels or not (0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height):
                raise ValueError('Duplicate, inverted or out-of-figure panel bounds.')
            panels[panel['id']] = box
        if not panels:
            raise ValueError('No panels.')
        for group in layout['comparison_groups']:
            indices = (0, 2) if group['axis'] == 'x' else (1, 3) if group['axis'] == 'y' else None
            if indices is None or len(group['panels']) < 2:
                raise ValueError('Invalid comparison group.')
            for index in indices:
                values = [panels[p][index] for p in group['panels']]
                if max(values) - min(values) > tolerance:
                    issue('warn', 'panel-alignment', f'Comparable panel edges differ by more than {tolerance:g} pt.', panels=group['panels'], axis=group['axis'])
        for i, (pid, box) in enumerate(panels.items()):
            for qid, other in list(panels.items())[i+1:]:
                if min(box[2], other[2]) > max(box[0], other[0]) + tolerance and min(box[3], other[3]) > max(box[1], other[1]) + tolerance:
                    issue('warn', 'panel-overlap', 'Panel plot areas overlap.', panels=[pid, qid])
        measurements['layout'] = {'panels': len(panels), 'comparison_groups': len(layout['comparison_groups'])}
        if len(panels) > 1 and not layout['comparison_groups']:
            issue('warn', 'panel-alignment', 'Multiple panels without comparison groups; alignment unassessed.')
    except (OSError, ValueError, TypeError, KeyError) as exc:
        issue('fail', 'layout', f'Invalid layout manifest: {exc}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--json', dest='report', type=Path, help='Write report; do not replace a bundled artifact.')
    parser.add_argument('--min-pt', type=float, default=8)
    parser.add_argument('--tolerance-pt', type=float, default=1.5)
    parser.add_argument('--strict', action='store_true', help='Exit 2 for warnings requiring review.')
    args = parser.parse_args()
    if not all(math.isfinite(v) and v > 0 for v in (args.min_pt, args.tolerance_pt)):
        parser.error('Font floor and tolerance must be finite and positive.')
    result = audit_bundle(args.bundle, args.min_pt, args.tolerance_pt)
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.report:
        if args.report.exists():
            parser.error('Report already exists; choose a new path.')
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded, encoding='utf-8')
    print(encoded, end='')
    return 1 if result['automatic_status'] == 'fail' else 2 if args.strict and result['automatic_status'] == 'review' else 0


if __name__ == '__main__':
    sys.exit(main())
