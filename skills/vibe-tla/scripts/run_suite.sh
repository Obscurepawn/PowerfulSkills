#!/usr/bin/env bash
# run_suite.sh — Core-budgeted LPT multi-config / multi-level TLC runner with
# Coverage-Basis Deduplication and workload-tiered JVM tuning.
#
# Why use run_suite.sh instead of serial run_tlc.sh loops?
#   1. LPT (Longest-Processing-Time) Head-of-Line Scheduling: Estimates per-cfg state
#      weight from prior 03_run_log.md / *.log / PAUSED.txt entries and starts heavy
#      multi-worker scaling configs at t=0 so no multi-million-state run sits stranded
#      at the tail behind 1-core tasks.
#   2. Coverage-Basis Deduplication (100% sound): Runs primary / <2M-state configs with
#      `-coverage 60` (`1..4` workers) to verify every action fires (`generated > 0`).
#      Heavy `>=2M`-state scaling configs on the same module run coverage-free with
#      `4..12` workers + `OffHeapDiskFPSet` + C2 inlining (honoring optional
#      `\* @vibe-view: ViewIdent` comments in `.cfg` inside an isolated scratch copy).
#      Failsafe: if any action remains `0` across the small configs, scaling configs are
#      automatically re-run with `-coverage 60` before flagging a dead action.
#   3. Tiered JVM Startup & Off-Heap Memory Budgeting: Uses C1 fast-JIT (`-XX:TieredStopAtLevel=1`)
#      below 25k states (~45% faster startup) and bounds `-Xmx` + `MaxDirectMemorySize`
#      against available host RAM.
#
# Usage:
#   run_suite.sh <workspace-or-level-or-Module.tla ...> [--jobs N] [--classpath CP]
#                [--no-dedup-coverage] [--det]
set -uo pipefail
die(){ echo "run_suite.sh: $*" >&2; exit 2; }

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ $# -ge 1 ]] || die "usage: run_suite.sh <target-dir-or-Module.tla ...> [--jobs N] [--classpath CP] [--no-dedup-coverage] [--det]"

JOBS="${TLC_SUITE_JOBS:-}"
EXTRA_CP="${TLC_CLASSPATH:-}"
DEDUP_COV=1
DET=0
TARGETS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --jobs=*)            JOBS="${1#*=}" ;;
    --jobs)              shift; JOBS="${1:-}" ;;
    --classpath=*)       EXTRA_CP="${1#*=}" ;;
    --classpath)         shift; EXTRA_CP="${1:-}" ;;
    --no-dedup-coverage) DEDUP_COV=0 ;;
    --det)               DET=1 ;;
    -*)                  die "unknown flag: $1" ;;
    *)                   TARGETS+=("$1") ;;
  esac
  shift
done

[[ ${#TARGETS[@]} -gt 0 ]] || die "at least one target directory or .tla file is required"

if ! command -v python3 >/dev/null 2>&1; then
  # Minimal POSIX fallback when python3 is absent.
  rc_all=0
  for t in "${TARGETS[@]}"; do
    if [[ -f "$t" && "$t" == *.tla ]]; then
      bash "$SELF_DIR/coverage.sh" "$t" --all-cfgs || rc_all=$?
    elif [[ -d "$t" ]]; then
      while IFS= read -r mf; do
        [[ -n "$mf" ]] || continue
        bash "$SELF_DIR/coverage.sh" "$mf" --all-cfgs || rc_all=$?
      done < <(find "$t" -type f -path '*/02_models/*.tla' ! -name '*_TTrace_*' ! -name '*_Unsafe.tla' | sort)
    fi
  done
  exit "$rc_all"
fi

exec python3 - "$JOBS" "$EXTRA_CP" "$DEDUP_COV" "$DET" "${TARGETS[@]}" <<'PY'
from __future__ import annotations

from pathlib import Path
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

jobs_arg = sys.argv[1].strip()
extra_cp_arg = sys.argv[2].strip()
dedup_cov = sys.argv[3] == "1"
det_mode = sys.argv[4] == "1"
raw_targets = [Path(p).resolve() for p in sys.argv[5:]]

SUMMARY_RE = re.compile(
    r"([0-9,]+) states generated, ([0-9,]+) distinct states found, 0 states left on queue\."
)
DEPTH_RE = re.compile(r"The depth of the complete state graph search is ([0-9]+)\.")
PROGRESS_RE = re.compile(
    r"Progress\(([0-9]+)\).*?: ([0-9,]+) states generated(?: \(([0-9,]+) s/min\))?"
)
ACTION_COV_RE = re.compile(r"^<([A-Za-z_][A-Za-z0-9_]*)\b[^>]*>: ([0-9]+):([0-9]+)\s*$", re.M)
RUNLOG_ROW_RE = re.compile(
    r"^\|\s*`?([A-Za-z0-9_.-]+\.cfg)`?\s*\|\s*`?([0-9,]+)`?\s*\|\s*`?([0-9,]+)`?\s*\|",
    re.M,
)
VIBE_VIEW_RE = re.compile(r"^\s*\\\*\s*@vibe-view:\s*([A-Za-z_][A-Za-z0-9_]*)\s*$", re.M)
VIEW_CFG_RE = re.compile(r"^\s*VIEW\b", re.M)

SCALING_THRESHOLD = 2_000_000
MEGA_THRESHOLD = 50_000_000
ULTRA_THRESHOLD = 300_000_000
FAST_JIT_THRESHOLD = 25_000
MULTI_COV_2W = 50_000
MULTI_COV_4W = 150_000
OFFHEAP_COV_THRESHOLD = 500_000


def parse_config_env(start: Path) -> dict[str, str]:
    env_path = os.environ.get("VIBE_TLA_CONFIG", "").strip()
    cand = Path(env_path) if env_path else None
    if cand is None or not cand.is_file():
        d = start if start.is_dir() else start.parent
        while True:
            p = d / "config.env"
            if p.is_file():
                cand = p
                break
            if d.parent == d:
                break
            d = d.parent
    out: dict[str, str] = {}
    if cand and cand.is_file():
        out["__CONFIG_DIR__"] = str(cand.parent)
        for ln in cand.read_text(errors="ignore").splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def detect_host_budget(explicit_jobs: str) -> tuple[int, int]:
    cpus = os.cpu_count() or 4
    avail_mb = 8192
    try:
        meminfo = Path("/proc/meminfo")
        if meminfo.is_file():
            for ln in meminfo.read_text(errors="ignore").splitlines():
                if ln.startswith("MemAvailable:"):
                    avail_mb = int(ln.split()[1]) // 1024
                    break
        elif sys.platform == "darwin":
            r = subprocess.run(
                ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, check=False
            )
            if r.returncode == 0 and r.stdout.strip().isdigit():
                avail_mb = max(2048, (int(r.stdout.strip()) // (1024 * 1024)) * 3 // 4)
    except OSError:
        pass

    if det_mode:
        return 1, avail_mb
    if explicit_jobs.isdigit() and int(explicit_jobs) >= 1:
        return int(explicit_jobs), avail_mb
    mem_cores = max(1, avail_mb // 1024)
    return max(1, min(cpus, mem_cores, 16)), avail_mb


def discover_modules(targets: list[Path]) -> list[tuple[Path, list[Path]]]:
    """Return sorted `(tla_path, [cfg_paths...])` pairs."""
    explicit_tlas: list[Path] = []
    model_dirs: set[Path] = set()
    for t in targets:
        if not t.exists():
            raise SystemExit(f"run_suite.sh: target not found: {t}")
        if t.is_file():
            if t.suffix != ".tla":
                raise SystemExit(f"run_suite.sh: expected .tla file or directory, got: {t}")
            explicit_tlas.append(t)
        else:
            if t.name == "02_models":
                model_dirs.add(t)
            elif (t / "02_models").is_dir():
                model_dirs.add(t / "02_models")
            else:
                for p in t.glob("**/02_models/*.tla"):
                    if p.is_file():
                        model_dirs.add(p.parent)

    pairs: list[tuple[Path, list[Path]]] = []
    seen_tlas: set[Path] = set()

    for tla in explicit_tlas:
        if tla in seen_tlas:
            continue
        seen_tlas.add(tla)
        d = tla.parent
        stem = tla.stem
        cfgs = sorted(
            c
            for c in d.glob("*.cfg")
            if c.is_file() and (c.stem == stem or c.stem.startswith(stem + "_") or len(list(d.glob("*.tla"))) == 1)
        )
        if cfgs:
            pairs.append((tla, cfgs))

    for d in sorted(model_dirs):
        tlas = sorted(
            p
            for p in d.glob("*.tla")
            if p.is_file() and not p.is_symlink() and "_TTrace_" not in p.name and not p.stem.endswith("_Unsafe")
        )
        all_cfgs = sorted(c for c in d.glob("*.cfg") if c.is_file() and not c.is_symlink())
        if not tlas or not all_cfgs:
            continue
        if len(tlas) == 1:
            if tlas[0] not in seen_tlas:
                seen_tlas.add(tlas[0])
                pairs.append((tlas[0], all_cfgs))
        else:
            # Match each cfg to the longest matching module stem (e.g. L0_Foo_v2 before L0_Foo).
            by_tla: dict[Path, list[Path]] = {t: [] for t in tlas}
            sorted_by_len = sorted(tlas, key=lambda p: len(p.stem), reverse=True)
            for c in all_cfgs:
                if c.stem.endswith("_Unsafe"):
                    continue
                for t in sorted_by_len:
                    if c.stem == t.stem or c.stem.startswith(t.stem + "_"):
                        by_tla[t].append(c)
                        break
            for t in tlas:
                if t not in seen_tlas and by_tla[t]:
                    seen_tlas.add(t)
                    pairs.append((t, by_tla[t]))

    return pairs


def extract_final_coverage(log_text: str) -> dict[str, int] | None:
    marker = "coverage statistics at"
    pos = log_text.rfind(marker)
    if pos < 0:
        return None
    tail = log_text[pos:]
    counts: dict[str, int] = {}
    for m in ACTION_COV_RE.finditer(tail):
        name, _dist, gen = m.group(1), int(m.group(2)), int(m.group(3))
        if name != "Init":
            counts[name] = max(counts.get(name, 0), gen)
    return counts if counts else None


def estimate_module_plan(
    tla_file: Path, cfg_files: list[Path]
) -> tuple[list[tuple[int, int]], set[int]]:
    lvl = tla_file.parent.parent
    n = len(cfg_files)
    cfg_names = [c.name for c in cfg_files]
    cfg_stems = [c.stem for c in cfg_files]
    best_gen: list[int | None] = [None] * n
    is_paused: list[bool] = [False] * n
    cov_hist: dict[int, dict[str, int]] = {}

    # 1. Check 03_run_log.md table rows (`| cfg.cfg | dist | gen |`).
    run_log = lvl / "03_run_log.md"
    if run_log.is_file():
        txt = run_log.read_text(errors="ignore")
        for m in RUNLOG_ROW_RE.finditer(txt):
            cname, dist_s, gen_s = m.group(1), m.group(2), m.group(3)
            if cname in cfg_names:
                idx = cfg_names.index(cname)
                val = max(int(dist_s.replace(",", "")), int(gen_s.replace(",", "")))
                best_gen[idx] = max(best_gen[idx] or 0, val)

    # 2. Check evidence / run logs under the level folder.
    for lp in sorted(lvl.glob("**/*.log")):
        if not lp.is_file():
            continue
        c_idx = None
        for idx, st in enumerate(cfg_stems):
            if lp.stem == st or lp.stem == f"tlc-{st}" or lp.stem.endswith(f"_{st}"):
                c_idx = idx
                break
        if c_idx is None:
            continue
        try:
            raw = lp.read_text(errors="ignore")
        except OSError:
            continue
        sm = SUMMARY_RE.findall(raw[-16384:])
        if sm:
            gen = int(sm[-1][0].replace(",", ""))
            best_gen[c_idx] = max(best_gen[c_idx] or 0, gen)
            cov = extract_final_coverage(raw)
            if cov:
                cov_hist[c_idx] = cov
        else:
            pm = PROGRESS_RE.findall(raw[-16384:])
            if pm and best_gen[c_idx] is None:
                best_gen[c_idx] = int(pm[-1][1].replace(",", "")) * 2
                is_paused[c_idx] = True

    weights: list[tuple[int, int]] = []
    for idx, c in enumerate(cfg_files):
        st = best_gen[idx]
        if st is not None:
            weights.append((3 if is_paused[idx] else 2, st))
        else:
            sz = tla_file.stat().st_size + c.stat().st_size
            weights.append((1, sz))

    if not dedup_cov or det_mode or n <= 1:
        return weights, set(range(n))

    cov_indices: set[int] = {
        idx for idx in range(n) if best_gen[idx] is None or best_gen[idx] < SCALING_THRESHOLD
    }
    if not cov_indices:
        lightest = min(range(n), key=lambda i: best_gen[i] or 0)
        cov_indices.add(lightest)

    if cov_hist:
        all_acts: set[str] = set()
        for mp in cov_hist.values():
            all_acts.update(mp.keys())
        covered = {
            act for idx in cov_indices for act, cnt in cov_hist.get(idx, {}).items() if cnt > 0
        }
        if not all_acts.issubset(covered):
            return weights, set(range(n))

    return weights, cov_indices


def main() -> int:
    t0 = time.monotonic()
    total_cores, avail_mb = detect_host_budget(jobs_arg)
    pairs = discover_modules(raw_targets)
    if not pairs:
        print("run_suite.sh: no checkable 02_models/*.tla + *.cfg pairs found.")
        return 0

    cfg_env = parse_config_env(pairs[0][0])
    jar_str = os.environ.get("TLA_TOOLS_JAR", "").strip() or cfg_env.get("TLA_TOOLS_JAR", "")
    if not jar_str or not Path(jar_str).is_file():
        print(
            "run_suite.sh: TLA_TOOLS_JAR not set/found — run '/vibe-tla init' first",
            file=sys.stderr,
        )
        return 2
    jar_path = Path(jar_str).resolve()

    extra_cp = extra_cp_arg or cfg_env.get("TLC_CLASSPATH", "")
    if not extra_cp and "__CONFIG_DIR__" in cfg_env:
        cand_ovr = Path(cfg_env["__CONFIG_DIR__"]) / "tools" / "overrides"
        if cand_ovr.is_dir() and any(cand_ovr.iterdir()):
            extra_cp = str(cand_ovr)
    explicit_heap = os.environ.get("TLC_MAX_HEAP", "").strip() or cfg_env.get("TLC_MAX_HEAP", "")
    timeout_s = int(os.environ.get("TLC_TIMEOUT", cfg_env.get("TLC_TIMEOUT", "1800")) or "0")

    with tempfile.TemporaryDirectory(prefix="vibe_suite.") as scratch_s:
        scratch = Path(scratch_s)
        models: list[dict] = []
        pending: list[dict] = []

        for m_idx, (tla_src, cfg_srcs) in enumerate(pairs):
            gdir = Path(tempfile.mkdtemp(prefix=f"m{m_idx}.", dir=scratch))
            # Stage all non-symlink .tla and .cfg files in 02_models/ (supports EXTENDS local helpers).
            for sib in tla_src.parent.iterdir():
                if sib.is_file() and not sib.is_symlink() and sib.suffix in (".tla", ".cfg"):
                    shutil.copyfile(sib, gdir / sib.name)

            weights, cov_indices = estimate_module_plan(tla_src, cfg_srcs)
            models.append(
                {
                    "idx": m_idx,
                    "tla_src": tla_src,
                    "tla_name": tla_src.name,
                    "mod_name": tla_src.stem,
                    "group_dir": gdir,
                    "cfg_names": [c.name for c in cfg_srcs],
                    "cov_indices": cov_indices,
                    "results": [None] * len(cfg_srcs),
                    "done_count": 0,
                    "verdict": None,
                    "emitted": False,
                }
            )
            for c_idx, c_src in enumerate(cfg_srcs):
                tier, score = weights[c_idx]
                est_states = score if tier >= 2 else 0
                use_cov = c_idx in cov_indices
                pending.append(
                    {
                        "priority": (-tier, -score, m_idx, c_idx),
                        "m_idx": m_idx,
                        "c_idx": c_idx,
                        "cfg_name": c_src.name,
                        "use_cov": use_cov,
                        "est_states": est_states,
                        "req_cores": 1,
                    }
                )

        for task in pending:
            est = task["est_states"]
            if det_mode:
                task["req_cores"] = 1
            elif task["use_cov"]:
                if est >= MULTI_COV_4W:
                    task["req_cores"] = max(1, min(4, total_cores))
                elif est >= MULTI_COV_2W:
                    task["req_cores"] = max(1, min(2, total_cores))
                else:
                    task["req_cores"] = 1
            elif est >= ULTRA_THRESHOLD:
                task["req_cores"] = max(1, min(12 if total_cores >= 16 else 8, total_cores))
            elif est >= MEGA_THRESHOLD:
                task["req_cores"] = max(1, min(8, total_cores))
            else:
                task["req_cores"] = max(1, min(4, total_cores))

        pending.sort(key=lambda t: t["priority"])

        cond = threading.Condition()
        stop_event = threading.Event()
        active_procs: set[subprocess.Popen] = set()
        avail_cores = total_cores
        next_emit = 0
        overall_rc = 0

        def kill_all(procs: list[subprocess.Popen]) -> None:
            for p in procs:
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except OSError:
                    try:
                        p.terminate()
                    except OSError:
                        pass

        def on_sig(signum, _frame) -> None:
            nonlocal overall_rc
            overall_rc = 128 + signum
            stop_event.set()
            with cond:
                procs = list(active_procs)
                pending.clear()
                cond.notify_all()
            kill_all(procs)

        signal.signal(signal.SIGINT, on_sig)
        signal.signal(signal.SIGTERM, on_sig)

        def invoke_one(
            gdir: Path, tla_name: str, cfg_name: str, workers: int, use_cov: bool, est: int
        ) -> tuple[int, str, float]:
            rdir = Path(tempfile.mkdtemp(prefix="run.", dir=gdir))
            wdir = rdir / "work"
            sdir = rdir / "states"
            jdir = rdir / "java"
            wdir.mkdir(parents=True, exist_ok=True)
            sdir.mkdir(parents=True, exist_ok=True)
            jdir.mkdir(parents=True, exist_ok=True)

            for f in gdir.iterdir():
                if f.is_file() and f.suffix in (".tla", ".cfg"):
                    try:
                        os.link(f, wdir / f.name)
                    except OSError:
                        shutil.copyfile(f, wdir / f.name)

            # Honor optional `\* @vibe-view: ViewIdent` in scaling (coverage-free) mode.
            cfg_work = wdir / cfg_name
            cfg_txt = cfg_work.read_text(errors="ignore")
            if not use_cov and not VIEW_CFG_RE.search(cfg_txt):
                vm = VIBE_VIEW_RE.search(cfg_txt)
                if vm:
                    cfg_work.unlink()
                    shutil.copyfile(gdir / cfg_name, cfg_work)
                    cfg_work.write_text(cfg_txt.rstrip() + f"\nVIEW {vm.group(1)}\n")

            if explicit_heap:
                heap = explicit_heap
            elif not use_cov and est >= MEGA_THRESHOLD:
                heap = "3072m" if avail_mb >= 16384 else "2048m"
            elif est >= SCALING_THRESHOLD:
                heap = "2560m"
            else:
                heap = "1536m"

            cmd = ["java", f"-Djava.io.tmpdir={jdir}", f"-Xmx{heap}", "-XX:+UseParallelGC"]
            if workers == 1:
                cmd.extend(["-XX:ParallelGCThreads=2", "-XX:ConcGCThreads=1"])
                if est < FAST_JIT_THRESHOLD:
                    cmd.extend(["-XX:+TieredCompilation", "-XX:TieredStopAtLevel=1"])
            else:
                cmd.extend(
                    [
                        f"-XX:ParallelGCThreads={min(4, workers)}",
                        "-XX:ConcGCThreads=1",
                        "-XX:MaxInlineLevel=24",
                        "-XX:FreqInlineSize=512",
                    ]
                )
                if not use_cov or est >= OFFHEAP_COV_THRESHOLD:
                    offheap = (
                        "3072m"
                        if (not use_cov and est >= MEGA_THRESHOLD and avail_mb >= 16384)
                        else "1536m"
                    )
                    cmd.extend(
                        [
                            f"-XX:MaxDirectMemorySize={offheap}",
                            "-Dtlc2.tool.fp.FPSet.impl=tlc2.tool.fp.OffHeapDiskFPSet",
                        ]
                    )

            cp_val = f"{extra_cp}{os.pathsep}{jar_path}" if extra_cp else str(jar_path)
            cmd.extend(
                ["-cp", cp_val, "tlc2.TLC", "-checkpoint", "0", "-workers", str(workers)]
            )
            if use_cov:
                cmd.extend(["-coverage", "60"])
            cmd.extend(["-metadir", str(sdir), "-config", cfg_name, tla_name])

            log_p = rdir / "tlc.log"
            start_t = time.monotonic()
            timed_out = False
            with open(log_p, "wb") as lf:
                proc = subprocess.Popen(
                    cmd, cwd=wdir, stdout=lf, stderr=subprocess.STDOUT, start_new_session=True
                )
                with cond:
                    if stop_event.is_set():
                        kill_all([proc])
                    else:
                        active_procs.add(proc)
                try:
                    rc = proc.wait(timeout=timeout_s if timeout_s > 0 else None)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    kill_all([proc])
                    rc = 124
                    proc.wait()
                finally:
                    with cond:
                        active_procs.discard(proc)

            elapsed = time.monotonic() - start_t
            out_txt = log_p.read_text(errors="replace")
            if timed_out:
                out_txt += f"\n>>> hit TLC_TIMEOUT={timeout_s}s (exit 124)\n"
            shutil.rmtree(rdir, ignore_errors=True)
            return rc, out_txt, elapsed

        def flush_ready_locked() -> None:
            nonlocal next_emit
            while next_emit < len(models) and models[next_emit]["verdict"] is not None:
                m = models[next_emit]
                v = m["verdict"]
                print(f"=== {m['mod_name']} ({m['tla_src'].parent}) -> {v['status']} ===")
                for row in v["rows"]:
                    print(
                        f"  cfg={row['cfg']:<30} dist={row['dist']:>10} gen={row['gen']:>11} "
                        f"depth={row['depth']:>3} workers={row['workers']:>2} cov={row['cov']} "
                        f"time={row['elapsed']:.1f}s rc={row['rc']}"
                    )
                if v["cov_summary"]:
                    print(f"  coverage: {v['cov_summary']}")
                if v["tail"]:
                    print("  failure tail:")
                    for ln in v["tail"]:
                        print(f"    {ln}")
                print(flush=True)
                shutil.rmtree(m["group_dir"], ignore_errors=True)
                next_emit += 1

        def finalize_model(m_idx: int) -> None:
            nonlocal avail_cores, overall_rc
            m = models[m_idx]
            merged_cov: dict[str, int] = {}
            scale_idxs: list[int] = []
            failed_rc = 0
            fail_tail: list[str] = []

            for c_idx, res in enumerate(m["results"]):
                rc, txt, _elapsed, _w, has_cov = res
                if rc != 0 and failed_rc == 0:
                    failed_rc = rc
                    fail_tail = txt.strip().splitlines()[-12:]
                if has_cov:
                    cdict = extract_final_coverage(txt) or {}
                    for k, v in cdict.items():
                        merged_cov[k] = max(merged_cov.get(k, 0), v)
                else:
                    scale_idxs.append(c_idx)

            # Failsafe: if any action has generated == 0 and scaling cfgs ran coverage-free,
            # re-run those scaling cfgs with `-coverage 60` before reporting DEAD.
            dead_acts = sorted(k for k, v in merged_cov.items() if v == 0)
            if failed_rc == 0 and dead_acts and scale_idxs:
                for c_idx in scale_idxs:
                    if stop_event.is_set():
                        return
                    with cond:
                        while not stop_event.is_set() and avail_cores < 1:
                            cond.wait()
                        if stop_event.is_set():
                            return
                        avail_cores -= 1
                    try:
                        rc2, txt2, el2 = invoke_one(
                            m["group_dir"],
                            m["tla_name"],
                            m["cfg_names"][c_idx],
                            1,
                            True,
                            SCALING_THRESHOLD,
                        )
                    finally:
                        with cond:
                            avail_cores += 1
                            cond.notify_all()
                    m["results"][c_idx] = (rc2, txt2, el2, 1, True)
                    if rc2 != 0 and failed_rc == 0:
                        failed_rc = rc2
                        fail_tail = txt2.strip().splitlines()[-12:]
                    cdict2 = extract_final_coverage(txt2) or {}
                    for k, v in cdict2.items():
                        merged_cov[k] = max(merged_cov.get(k, 0), v)
                dead_acts = sorted(k for k, v in merged_cov.items() if v == 0)

            rows = []
            for c_idx, (rc, txt, el, w, has_cov) in enumerate(m["results"]):
                sm = SUMMARY_RE.findall(txt[-16384:])
                dm = DEPTH_RE.findall(txt[-16384:])
                gen_s, dist_s = sm[-1] if sm else ("?", "?")
                dep_s = dm[-1] if dm else "?"
                rows.append(
                    {
                        "cfg": m["cfg_names"][c_idx],
                        "gen": gen_s,
                        "dist": dist_s,
                        "depth": dep_s,
                        "workers": w,
                        "cov": "yes" if has_cov else "dedup",
                        "elapsed": el,
                        "rc": rc,
                    }
                )

            if failed_rc != 0:
                status = f"FAIL (rc={failed_rc})"
                cov_sum = ""
                final_bad = failed_rc
            elif dead_acts:
                status = "DEAD-ACTION"
                cov_sum = (
                    f"{len(merged_cov) - len(dead_acts)}/{len(merged_cov)} actions fired; "
                    f"DEAD (generated=0): {', '.join(dead_acts)}"
                )
                final_bad = 1
            else:
                status = "PASS"
                cov_sum = (
                    f"{len(merged_cov)}/{len(merged_cov)} actions fired"
                    if merged_cov
                    else "no action lines parsed"
                )
                final_bad = 0

            with cond:
                if final_bad != 0 and overall_rc == 0:
                    overall_rc = final_bad
                m["verdict"] = {
                    "status": status,
                    "rows": rows,
                    "cov_summary": cov_sum,
                    "tail": fail_tail,
                }
                flush_ready_locked()

        def acquire_task() -> dict | None:
            nonlocal avail_cores
            with cond:
                while True:
                    if stop_event.is_set() or not pending:
                        return None
                    head = pending[0]
                    if head["req_cores"] <= avail_cores:
                        pending.pop(0)
                        if (
                            not det_mode
                            and not head["use_cov"]
                            and head["est_states"] >= MEGA_THRESHOLD
                            and avail_cores == total_cores
                            and not any(
                                not t["use_cov"] and t["est_states"] >= SCALING_THRESHOLD
                                for t in pending
                            )
                        ):
                            head["req_cores"] = total_cores
                        avail_cores -= head["req_cores"]
                        return head
                    cond.wait()

        def worker_fn() -> None:
            nonlocal avail_cores
            while True:
                task = acquire_task()
                if task is None:
                    return
                m = models[task["m_idx"]]
                w = task["req_cores"]
                try:
                    rc, txt, el = invoke_one(
                        m["group_dir"],
                        m["tla_name"],
                        task["cfg_name"],
                        w,
                        task["use_cov"],
                        task["est_states"],
                    )
                finally:
                    with cond:
                        avail_cores += w
                        cond.notify_all()

                ready = False
                with cond:
                    m["results"][task["c_idx"]] = (rc, txt, el, w, task["use_cov"])
                    m["done_count"] += 1
                    if m["done_count"] == len(m["cfg_names"]):
                        ready = True
                if ready:
                    finalize_model(task["m_idx"])

        threads = [threading.Thread(target=worker_fn, daemon=True) for _ in range(total_cores)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        wall = time.monotonic() - t0
        passed = sum(1 for m in models if (m["verdict"] or {}).get("status") == "PASS")
        print(
            f"SUMMARY: {passed}/{len(models)} module(s) PASS in {wall:.1f}s "
            f"(budget={total_cores} core(s), exit={overall_rc})"
        )
        return 0 if overall_rc == 0 else (1 if overall_rc < 128 else overall_rc)


if __name__ == "__main__":
    sys.exit(main())
PY

