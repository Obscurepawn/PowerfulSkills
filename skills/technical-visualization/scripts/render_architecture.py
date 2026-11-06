#!/usr/bin/env python3
"""Render a checked architecture specification into a portable vector bundle.

Python 3.10+ and the Graphviz `dot` executable are required. No network access.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile

KINDS = {
    "sync": {"style": "solid", "color": "#1F4E79", "arrowhead": "normal"},
    "async": {"style": "dashed", "color": "#007C78", "arrowhead": "normal"},
    "data": {"style": "solid", "color": "#6A4C93", "arrowhead": "vee"},
    "control": {"style": "dotted", "color": "#5B6066", "arrowhead": "open"},
}
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    if any(ord(c) < 32 and c != "\n" for c in value):
        raise ValueError(f"{name} contains unsupported control characters")
    return value


def _identifier(value, name):
    _text(value, name)
    if not ID_RE.fullmatch(value):
        raise ValueError(f"{name} must start with a letter and use letters, digits, dot, underscore or hyphen")
    return value


def _object(value, allowed, required, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    missing, extra = required - value.keys(), value.keys() - allowed
    if missing:
        raise ValueError(f"{name} missing fields: {', '.join(sorted(missing))}")
    if extra:
        raise ValueError(f"{name} unsupported fields: {', '.join(sorted(extra))}")


def validate_spec(spec):
    """Validate meaning-bearing inputs; return the same specification."""
    required = {"title", "data_kind", "source", "nodes", "edges"}
    _object(spec, required | {"rankdir", "font_family", "font_size", "boundaries"}, required, "spec")
    _text(spec["title"], "title")
    _text(spec["source"], "source")
    if spec["data_kind"] not in ("observed", "proposed", "synthetic"):
        raise ValueError("data_kind must be observed, proposed or synthetic")
    if spec.get("rankdir", "LR") not in ("LR", "TB"):
        raise ValueError("rankdir must be LR or TB")
    _text(spec.get("font_family", "DejaVu Sans"), "font_family")
    size = spec.get("font_size", 11)
    if isinstance(size, bool) or not isinstance(size, (int, float)) or not math.isfinite(size) or not 9 <= size <= 48:
        raise ValueError("font_size must be a finite number between 9 and 48 points")
    boundaries = spec.get("boundaries", [])
    if not isinstance(boundaries, list):
        raise ValueError("boundaries must be a list")
    boundary_ids = set()
    for i, boundary in enumerate(boundaries):
        name = f"boundaries[{i}]"
        _object(boundary, {"id", "label"}, {"id", "label"}, name)
        bid = _identifier(boundary["id"], name + ".id")
        _text(boundary["label"], name + ".label")
        if bid in boundary_ids:
            raise ValueError(f"duplicate boundary id: {bid}")
        boundary_ids.add(bid)
    if not isinstance(spec["nodes"], list) or not spec["nodes"]:
        raise ValueError("nodes must be a nonempty list")
    node_ids = set()
    for i, node in enumerate(spec["nodes"]):
        name = f"nodes[{i}]"
        _object(node, {"id", "label", "boundary", "evidence"}, {"id", "label"}, name)
        nid = _identifier(node["id"], name + ".id")
        _text(node["label"], name + ".label")
        if nid in node_ids:
            raise ValueError(f"duplicate node id: {nid}")
        node_ids.add(nid)
        if "boundary" in node:
            _identifier(node["boundary"], name + ".boundary")
            if node["boundary"] not in boundary_ids:
                raise ValueError(f"{name} references an unknown boundary")
        if "evidence" in node or spec["data_kind"] == "observed":
            _text(node.get("evidence"), name + ".evidence")
    if not isinstance(spec["edges"], list):
        raise ValueError("edges must be a list")
    seen_edges = set()
    for i, edge in enumerate(spec["edges"]):
        name = f"edges[{i}]"
        _object(edge, {"from", "to", "label", "kind", "evidence"}, {"from", "to", "label", "kind"}, name)
        _identifier(edge["from"], name + ".from")
        _identifier(edge["to"], name + ".to")
        if edge["from"] not in node_ids or edge["to"] not in node_ids:
            raise ValueError(f"{name} has an unknown endpoint")
        _text(edge["label"], name + ".label")
        _text(edge["kind"], name + ".kind")
        if edge["kind"] not in KINDS:
            raise ValueError(f"{name}.kind must be one of {', '.join(KINDS)}")
        key = (edge["from"], edge["to"], edge["label"], edge["kind"])
        if key in seen_edges:
            raise ValueError(f"duplicate edge: {key}")
        seen_edges.add(key)
        if "evidence" in edge or spec["data_kind"] == "observed":
            _text(edge.get("evidence"), name + ".evidence")
    return spec


def quote(value):
    """Quote DOT literal text, preserving user backslashes without substitutions."""
    return json.dumps(str(value), ensure_ascii=False)


def attributes(values):
    return ", ".join(f"{key}={quote(value)}" for key, value in values.items())


def make_dot(spec):
    validate_spec(spec)
    font = spec.get("font_family", "DejaVu Sans")
    size = spec.get("font_size", 11)
    banner = {"observed": "OBSERVED — evidence references in specification",
              "proposed": "PROPOSED — design, not verified deployment",
              "synthetic": "SYNTHETIC EXAMPLE — not a real system"}[spec["data_kind"]]
    used = [kind for kind in KINDS if any(edge["kind"] == kind for edge in spec["edges"])]
    legend = {"sync": "[sync] synchronous call; solid / filled arrow",
              "async": "[async] asynchronous message; dashed / filled arrow",
              "data": "[data] data movement; solid / V arrow",
              "control": "[control] control signal; dotted / open arrow"}
    # A graph label is outside the network so it cannot be mistaken for a component.
    title = spec["title"] + "\n" + banner
    if used:
        title += "\n" + "\n".join(legend[k] for k in used)
    lines = ["digraph architecture {",
             "  graph [" + attributes({"rankdir": spec.get("rankdir", "LR"), "bgcolor": "white",
                "fontname": font, "fontsize": size, "pad": 0.25, "nodesep": 0.45, "ranksep": 0.7,
                "labelloc": "t", "labeljust": "l", "label": title}) + "];",
             "  node [" + attributes({"shape": "box", "style": "rounded,filled", "fillcolor": "#F2F5F7",
                "color": "#52616B", "fontcolor": "#17212B", "fontname": font, "fontsize": size,
                "margin": "0.17,0.12", "penwidth": 1.1}) + "];",
             "  edge [" + attributes({"fontname": font, "fontsize": size, "penwidth": 1.4,
                "arrowsize": 0.8}) + "];"]
    def node_line(node, indent="  "):
        return indent + quote(node["id"]) + " [" + attributes({"label": node["label"], "id": "node-" + node["id"]}) + "];"
    for node in spec["nodes"]:
        if "boundary" not in node:
            lines.append(node_line(node))
    for boundary in spec.get("boundaries", []):
        lines.append("  subgraph " + quote("cluster_" + boundary["id"]) + " {")
        lines.append("    graph [" + attributes({"label": boundary["label"], "style": "rounded,dashed",
            "color": "#8B959E", "fontname": font, "fontsize": size, "margin": 18, "labeljust": "l"}) + "];")
        lines.extend(node_line(node, "    ") for node in spec["nodes"] if node.get("boundary") == boundary["id"])
        lines.append("  }")
    for i, edge in enumerate(spec["edges"]):
        attrs = dict(KINDS[edge["kind"]], label=f"[{edge['kind']}] {edge['label']}", id=f"edge-{i + 1}")
        lines.append("  " + quote(edge["from"]) + " -> " + quote(edge["to"]) + " [" + attributes(attrs) + "];")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _strict_json(path):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError(f"duplicate JSON key: {key}")
            out[key] = value
        return out
    def invalid_constant(value):
        raise ValueError(f"nonfinite JSON number: {value}")
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=pairs, parse_constant=invalid_constant)


def _hash_entry(root, relative, role=None):
    result = {"path": relative, "sha256": hashlib.sha256((root / relative).read_bytes()).hexdigest()}
    if role:
        result["role"] = role
    return result


def render(input_path, output_path):
    input_path, output_path = Path(input_path).resolve(), Path(output_path).absolute()
    if output_path.is_symlink():
        raise ValueError("output must not be a symbolic link")
    if output_path.exists() and (not output_path.is_dir() or any(output_path.iterdir())):
        raise ValueError("output directory is nonempty or is not a directory; choose a new path")
    spec = validate_spec(_strict_json(input_path))
    dot = shutil.which("dot")
    if not dot:
        raise ValueError("Graphviz dot is required; install Graphviz and put dot on PATH")
    dot_version = subprocess.run([dot, "-V"], capture_output=True, text=True, check=True).stderr.strip()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Work in a sibling staging directory. Rendering failures leave the target untouched.
    with tempfile.TemporaryDirectory(prefix=".architecture-", dir=output_path.parent) as tmp:
        stage = Path(tmp)
        (stage / "inputs").mkdir()
        (stage / "code").mkdir()
        shutil.copyfile(input_path, stage / "inputs" / "architecture.json")
        shutil.copyfile(Path(__file__).resolve(), stage / "code" / "render_architecture.py")
        (stage / "architecture.dot").write_text(make_dot(spec), encoding="utf-8")
        warnings = []
        for fmt in ("svg", "pdf", "png"):
            result = subprocess.run([dot, f"-T{fmt}", "architecture.dot", "-o", f"architecture.{fmt}"],
                                    cwd=stage, capture_output=True, text=True)
            if result.returncode:
                raise ValueError(f"Graphviz {fmt} rendering failed: {result.stderr.strip()}")
            if result.stderr.strip():
                warnings.append(f"Graphviz {fmt}: {result.stderr.strip()}")
        caption = (f"{spec['title']}. {spec['data_kind'].upper()} architecture. Source: {spec['source']}. "
                   "Arrows are directed from sender to receiver; bracketed labels identify flow kind. "
                   "Boundaries have the meaning written in their labels. Node size does not encode capacity. "
                   "Evidence references in the JSON are user-supplied and require review.\n")
        (stage / "caption.txt").write_text(caption, encoding="utf-8")
        (stage / "reproduce.txt").write_text(
            "From this bundle directory, with Python 3.10+ and Graphviz on PATH:\n"
            "python3 code/render_architecture.py --input inputs/architecture.json --output replay\n"
            "Use a fresh output directory for each render. Graphviz and font versions affect geometry.\n",
            encoding="utf-8")
        manifest = {
            "schema_version": 1, "kind": "architecture", "data_kind": spec["data_kind"],
            "inputs": [_hash_entry(stage, "inputs/architecture.json", "specification"),
                       _hash_entry(stage, "code/render_architecture.py", "renderer")],
            "outputs": [_hash_entry(stage, name) for name in
                        ("architecture.dot", "architecture.svg", "architecture.pdf", "architecture.png", "caption.txt", "reproduce.txt")],
            "parameters": spec,
            "environment": {"python": platform.python_version(), "platform": platform.platform(),
                            "graphviz": dot_version, "font_requested": spec.get("font_family", "DejaVu Sans")},
            "command": ["python3", "code/render_architecture.py", "--input", "inputs/architecture.json", "--output", "replay"],
            "warnings": warnings,
            "checks": {"schema": "passed", "unique_nodes": "passed", "edge_endpoints": "passed",
                       "observed_evidence_presence": "passed" if spec["data_kind"] == "observed" else "not_applicable",
                       "semantic_evidence_review": "pending", "visual_review": "pending"},
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if output_path.exists():
            output_path.rmdir()  # It was empty and stays protected if changed during rendering.
        stage.rename(output_path)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Architecture JSON specification")
    parser.add_argument("--output", required=True, type=Path, help="New or empty bundle directory")
    args = parser.parse_args(argv)
    try:
        render(args.input, args.output)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(f"Rendered architecture bundle: {args.output}")


if __name__ == "__main__":
    main()
