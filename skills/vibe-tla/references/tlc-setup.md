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
5. **Download** a pinned release into `$WORKSPACE/tools/tla2tools.jar` from the TLA+
   GitHub releases (`https://github.com/tlaplus/tlaplus/releases`), using `curl` or
   `wget`. If the machine is offline, the script prints the URL and the target path so
   the user can drop the jar in manually.

It then runs a smoke spec (`scripts/smoke/Smoke.tla`) to confirm TLC actually executes,
and writes `TLA_TOOLS_JAR=<path>` into `$WORKSPACE/config.env`.

## The canonical invocation

Use `scripts/run_tlc.sh <module>.tla <module>.cfg` — it sources `config.env`, runs the
module-named `.tla` (never a symlink), captures timing, and cleans scratch. By hand it is:

```sh
# from inside the level directory; MODULE name must equal the .tla basename
java -XX:+UseParallelGC -cp "$TLA_TOOLS_JAR" tlc2.TLC \
     -workers auto -config L2_Foo.cfg L2_Foo.tla
```

- `-workers auto` (or `-workers N`) for speed while exploring.
- For a **violating** run, re-run with `-workers 1` — that gives deterministic distinct/
  generated state counts and a stable trace depth, which are the numbers you cite.
- `-deadlock` to disable deadlock detection when termination is legitimate.
- `-dump dot states.dot` to visualize a small state graph when debugging a trace.
- For timing the way the run log records it: `/usr/bin/time -p java … -workers 1 …` and
  record the `real` seconds per cfg plus the whole-level aggregate.

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
VIBE_TLA_EFFORT=medium                     # default effort: low | medium | high (set by /vibe-tla effort)
```

`REPO_MODE`/`REPO_URL` come from the **standalone** install flow: `scripts/get_repo.sh`
(`use` / `refresh` / `active`) clones the target repo from a URL and records the active repo
in `${VIBE_TLA_HOME:-$HOME/.vibe-tla}/active.env`, which is the source of truth for
`REPO_ROOT`/`REPO_MODE` there; `config.env` mirrors it (both written at `init`). In an
embedded install these stay `embedded`/empty. See `references/workspace.md` for the two
install shapes.
