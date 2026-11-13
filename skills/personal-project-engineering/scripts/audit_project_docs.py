#!/usr/bin/env python3
"""Audit project Markdown docs (README, SPECS, AGENTS.md) against repository reality.

Checks:
  1. Relative Markdown links/images resolve to existing files or directories.
  2. Heading fragments (#anchor) resolve in target local Markdown files.
  3. Unfilled template placeholders ({{...}}) are not left behind in prose/headings.
  4. `npm run <script>` commands match scripts declared in package.json (when present).

Exit codes: 0 = clean, 1 = issues found, 2 = invalid arguments.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote

FENCE_RE = re.compile(r"^(`{3,}|~{3,})")
INLINE_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
REF_DEF_RE = re.compile(r"^\s*\[[^\]]+\]:\s*(\S+)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
EXPLICIT_ID_RE = re.compile(r"\{#([A-Za-z0-9_.-]+)\}\s*$")
PLACEHOLDER_RE = re.compile(r"\{\{[^{}\n]+\}\}")
NPM_RUN_RE = re.compile(r"\bnpm\s+run\s+([A-Za-z0-9_:.-]+)")
EXTERNAL_SCHEMES = ("http://", "https://", "mailto:", "tel:", "data:", "file://", "customization://", "conversation://")


def github_slug(heading_text: str) -> str:
    text = EXPLICIT_ID_RE.sub("", heading_text).strip()
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.lower()
    # Keep letters/digits/word chars (including CJK), hyphens, and spaces.
    cleaned = []
    for ch in text:
        if ch.isalnum() or ch in (" ", "-", "_"):
            cleaned.append(ch)
    return re.sub(r"\s+", "-", "".join(cleaned).strip())


def collect_headings(md_path: Path) -> set[str]:
    slugs: set[str] = set()
    counts: dict[str, int] = {}
    in_code = False
    fence_char, fence_len = "", 0
    for raw in md_path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = raw.strip()
        if in_code:
            if re.match(rf"^{re.escape(fence_char)}{{{fence_len},}}\s*$", s):
                in_code = False
            continue
        m_fence = FENCE_RE.match(s)
        if m_fence:
            in_code, fence_char, fence_len = True, m_fence.group(1)[0], len(m_fence.group(1))
            continue
        m_head = HEADING_RE.match(s)
        if m_head:
            body = m_head.group(2)
            m_id = EXPLICIT_ID_RE.search(body)
            if m_id:
                slugs.add(m_id.group(1))
            base = github_slug(body)
            if base:
                idx = counts.get(base, 0)
                counts[base] = idx + 1
                slugs.add(base if idx == 0 else f"{base}-{idx}")
    return slugs


def default_docs(repo_root: Path) -> list[Path]:
    patterns = [
        "README*.md", "AGENTS*.md", "CLAUDE.md", "GEMINI.md", "SPECS*.md",
        "docs/**/*.md", "specs/**/*.md",
    ]
    found: set[Path] = set()
    for pat in patterns:
        for p in repo_root.glob(pat):
            if p.is_file() and ".git" not in p.parts and "node_modules" not in p.parts:
                found.add(p.resolve())
    return sorted(found)


def load_npm_scripts(repo_root: Path) -> set[str] | None:
    pkg = repo_root / "package.json"
    if not pkg.is_file():
        return None
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    scripts = data.get("scripts")
    return set(scripts.keys()) if isinstance(scripts, dict) else set()


def audit_repo(repo_root: Path, docs: list[Path] | None = None) -> dict:
    repo_root = repo_root.resolve()
    targets = [p.resolve() for p in docs] if docs else default_docs(repo_root)
    npm_scripts = load_npm_scripts(repo_root)
    heading_cache: dict[Path, set[str]] = {}
    issues: list[dict] = []

    def get_slugs(path: Path) -> set[str]:
        if path not in heading_cache:
            heading_cache[path] = collect_headings(path)
        return heading_cache[path]

    def record(kind: str, doc: Path, line: int, message: str, target: str = ""):
        try:
            rel = doc.relative_to(repo_root).as_posix()
        except ValueError:
            rel = str(doc)
        issues.append({"check": kind, "file": rel, "line": line, "target": target, "message": message})

    for doc in targets:
        if not doc.is_file():
            record("missing-doc", doc, 0, "Document to audit does not exist.")
            continue
        is_template = doc.name.endswith(".template.md")
        in_code = False
        fence_char, fence_len = "", 0
        lines = doc.read_text(encoding="utf-8", errors="replace").splitlines()
        for lineno, raw in enumerate(lines, 1):
            s = raw.strip()
            if in_code:
                if re.match(rf"^{re.escape(fence_char)}{{{fence_len},}}\s*$", s):
                    in_code = False
                    continue
                if npm_scripts is not None and not is_template:
                    for m_npm in NPM_RUN_RE.finditer(raw):
                        script_name = m_npm.group(1)
                        if script_name not in npm_scripts:
                            record("npm-script", doc, lineno,
                                   f"`npm run {script_name}` is not defined in package.json scripts.", script_name)
                continue
            m_fence = FENCE_RE.match(s)
            if m_fence:
                in_code, fence_char, fence_len = True, m_fence.group(1)[0], len(m_fence.group(1))
                continue

            no_code = re.sub(r"`[^`]*`", "", raw)
            if not is_template and PLACEHOLDER_RE.search(no_code):
                for m_ph in PLACEHOLDER_RE.finditer(no_code):
                    record("placeholder", doc, lineno, "Unreplaced template placeholder.", m_ph.group(0))

            if npm_scripts is not None and not is_template:
                for m_npm in NPM_RUN_RE.finditer(raw):
                    script_name = m_npm.group(1)
                    if script_name not in npm_scripts:
                        record("npm-script", doc, lineno,
                               f"`npm run {script_name}` is not defined in package.json scripts.", script_name)

            raw_targets = [m.group(1) for m in INLINE_LINK_RE.finditer(no_code)]
            m_ref = REF_DEF_RE.match(no_code)
            if m_ref:
                raw_targets.append(m_ref.group(1))

            for raw_target in raw_targets:
                target = raw_target.strip("<>")
                if not target or target.startswith(EXTERNAL_SCHEMES) or "{{" in target:
                    continue
                path_part, sep, frag = target.partition("#")
                path_part = unquote(path_part.split("?", 1)[0])
                frag = unquote(frag)
                resolved = doc if not path_part else (
                    (repo_root / path_part.lstrip("/")).resolve()
                    if path_part.startswith("/")
                    else (doc.parent / path_part).resolve()
                )
                if not resolved.exists():
                    record("dead-link", doc, lineno, f"Target does not exist: {raw_target}", raw_target)
                    continue
                if sep and frag and resolved.is_file() and resolved.suffix.lower() == ".md":
                    if frag.lower() not in get_slugs(resolved) and frag not in get_slugs(resolved):
                        record("dead-anchor", doc, lineno,
                               f"Heading anchor #{frag} not found in {resolved.name}.", raw_target)

    return {"checked_files": len(targets), "issue_count": len(issues), "issues": issues}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repo_root", type=Path, help="Repository root directory")
    parser.add_argument("docs", nargs="*", type=Path, help="Optional explicit Markdown files to check")
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    args = parser.parse_args(argv)
    if not args.repo_root.is_dir():
        print(f"error: not a directory: {args.repo_root}", file=sys.stderr)
        return 2
    report = audit_repo(args.repo_root, args.docs or None)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Checked {report['checked_files']} Markdown file(s); {report['issue_count']} issue(s).")
        for item in report["issues"]:
            print(f"  [{item['check']}] {item['file']}:{item['line']}: {item['message']}")
    return 1 if report["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
