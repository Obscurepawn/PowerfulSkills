# tlc-setup.md — the TLC toolchain, invocation, and cleanup

`init` runs `scripts/install_tlc.sh` to set this up automatically and record the result
in `$WORKSPACE/config.env`. This file is the reference for when the script can't resolve
something, or you need to invoke TLC by hand.

## What TLC needs

- **Java 11+ (17+ preferred).** `java -version` must work. If it doesn't, install a JRE
  (`brew install openjdk` on macOS; the distro JDK package on Linux) — TLC is a Java
  tool and cannot run without it. This is the one dependency the skill cannot install
  silently; tell the user and stop if it's missing.
- **`tla2tools.jar`** — the TLA+ tools (TLC model checker + SANY parser) in one jar.

## How `install_tlc.sh` resolves the jar (in order)

1. `$TLA_TOOLS_JAR` if it points to an existing file.
2. A jar already recorded in `$WORKSPACE/config.env`.
3. A VSCode TLA+ extension install: `~/.vscode*/extensions/tlaplus.vscode-ide-*/tools/tla2tools.jar`.
4. Common system locations (`/usr/local/lib`, `/opt/tlaplus`, `$HOME/.tlaplus`).
5. **Download** a pinned release (`v1.8.0` by default; override with `TLA_TOOLS_VERSION`
   or `TLA_TOOLS_URL`) into `$WORKSPACE/tools/tla2tools.jar` from the TLA+ GitHub
   releases (`https://github.com/tlaplus/tlaplus/releases`), using `curl` or `wget`. If
   the machine is offline, the script prints the URL and the target path so the user can
   drop the jar in manually.

It then runs a smoke spec (`scripts/smoke/Smoke.tla`) to confirm TLC actually executes,
and writes `TLA_TOOLS_JAR=<path>` into `$WORKSPACE/config.env`.

## The canonical invocation

Use `scripts/run_tlc.sh <module>.tla [module.cfg]` for single runs and
`scripts/run_suite.sh <level-or-workspace-dir>` for multi-cfg or multi-level sweeps — both
source `config.env`, stage real `.tla`/`.cfg` files into an isolated `/tmp` workdir (so
concurrent runs never collide or dirty `02_models/`), capture timing, and clean scratch.
See **`references/performance.md`** for the full acceleration guide.

```sh
# Single config (fast C1 JIT for <25k states; --coverage uses -coverage 60)
scripts/run_tlc.sh 02_models/L2_Foo.tla --fast-jit
scripts/run_tlc.sh 02_models/L2_Foo.tla --coverage

# Scaling config with scratch-only congruent VIEW + @TLAPlusOperator overrides
scripts/run_tlc.sh 02_models/L2_Foo.tla 02_models/L2_Foo_scale.cfg \
    --view FooView --view-def 'FooView == <<core, obs>>' \
    --classpath "$WORKSPACE/tools/overrides"

# Multi-cfg level or full workspace (Core-budgeted LPT + Coverage-Basis Deduplication)
scripts/run_suite.sh "$WORKSPACE"
```

- `-workers auto` (or `-workers N`) for speed while exploring; `run_suite.sh` automatically
  enables `OffHeapDiskFPSet` and C2 aggressive inlining on multi-worker scaling runs.
- For a **violating** run, re-run with `--det` (`-workers 1`) — that gives deterministic
  distinct/generated state counts and a stable trace depth, which are the numbers you cite.
- `-deadlock` to disable deadlock detection when termination is legitimate.
- `-dump dot states.dot` to visualize a small state graph when debugging a trace.
- For hot pure-operator bottlenecks in explicit TLC (even on headless JRE-only hosts without
  `javac`), emit `@TLAPlusOperator` bytecode into `$WORKSPACE/tools/overrides` via
  `scripts/tlc_bytecode.py` (`references/performance.md` §3.3).

## TLC gotchas worth knowing

- **Module name ≠ filename → parse error.** Always invoke the module-named `.tla`.
- **`Naturals`/`Integers`/`Sequences`/`FiniteSets`/`TLC` must be `EXTENDS`-ed** for the
  usual operators; a missing extend reads as an "unknown operator" parse error.
- **Unbounded state → never terminates.** Add a `CONSTRAINT` bounding any growing value
  (sequence length, counter range) and document the bound.
- **`SYMMETRY` only over truly interchangeable values**, and never combine symmetry with
  a property that distinguishes those values (it gives wrong results silently).
- **A reported "deadlock" may be expected termination** — decide which, and either allow
  it in the cfg or treat the stuck state as a finding.

## Cleanup (every run)

TLC writes scratch you should not commit: `states/`, `*.out`, `*_TTrace_*.tla`,
`*_trace_*.tlc`, `MC_*` files. `run_tlc.sh` removes these after capturing the result.
Keep only the committed `.tla` + `.cfg` + the markdown record.

## Config keys (`$WORKSPACE/config.env`)

```
TLA_TOOLS_JAR=/abs/path/to/tla2tools.jar   # resolved by install_tlc.sh
REPO_ROOT=/abs/path/to/repo                # the repo being modeled: the owning project (embedded), a clone (remote), or a named local path
REPO_MODE=embedded                         # embedded | remote (cloned from a URL) | local (a named local path)
REPO_URL=                                  # the git URL, in remote mode (empty otherwise)
WORKSPACE_DIR=tla                          # workspace folder name (relative to REPO_ROOT)
TLC_WORKERS=auto                           # default worker count for exploration
TLC_TIMEOUT=1800                           # per-cfg wall-clock bound (seconds), 0 = none; run_tlc.sh enforces it when a timeout/gtimeout binary exists
TLC_MAX_HEAP=                              # optional: explicit JVM -Xmx (e.g. 3072m); auto-sized by run_suite.sh
TLC_CLASSPATH=                             # optional: @TLAPlusOperator override dir/jar (defaults to $WORKSPACE/tools/overrides if non-empty)
VIBE_TLA_EFFORT=medium                     # default effort: low | medium | high (set by /vibe-tla effort)
APALACHE_BIN=/abs/path/to/apalache-mc      # optional: resolved on demand by scripts/install_apalache.sh
APALACHE_TIMEOUT=1800                      # optional: per-step timeout for scripts/run_apalache.sh
```

## On-demand symbolic solver (`Apalache` + bundled Z3)

`init` keeps setup fast by installing only `tla2tools.jar`. When a level encounters
Cartesian-product state explosion and switches to symbolic BMC or inductive invariants
(`references/symbolic.md`), run:

```sh
scripts/install_apalache.sh "$WORKSPACE"
```

It resolves an existing `apalache-mc` (`$APALACHE_BIN`, `config.env`, `$WORKSPACE/tools/apalache/`,
`PATH`) or downloads a pinned release (`v0.63.0` by default; override with `APALACHE_VERSION`
or `APALACHE_URL`), smoke-tests Snowcat + Z3 on `scripts/smoke/SmokeSymbolic.tla`, and
records `APALACHE_BIN` in `$WORKSPACE/config.env` without clobbering existing keys. Invoke
symbolic checks through `scripts/run_apalache.sh` (`typecheck` / `bmc` / `inductive`).

`REPO_MODE`/`REPO_URL` come from the **standalone** install flow: `scripts/get_repo.sh`
(`use` / `refresh` / `active`) clones the target repo from a URL and records the active repo
in `${VIBE_TLA_HOME:-$HOME/.vibe-tla}/active.env`, which is the source of truth for
`REPO_ROOT`/`REPO_MODE` there; `config.env` mirrors it (both written at `init`). In an
embedded install these stay `embedded`/empty. See `references/workspace.md` for the two
install shapes.
