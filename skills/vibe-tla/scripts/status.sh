#!/usr/bin/env bash
# status.sh — render the verification ledger from a workspace's long-term memory.
# Read-only: parses $WORKSPACE/MEMORY.md (and appends $WORKSPACE/ROADMAP.md if present)
# and never writes anything.  Usage:
#   status.sh <workspace-dir> [keywords]
#     <workspace-dir>  the per-repo workspace ($WORKSPACE); MEMORY.md lives at its root
#     [keywords]       optional case-insensitive substring; keeps only level headings
#                      whose '## component / ladder / Ln_slug' line matches it
#
# Parses two heading shapes from MEMORY.md (see references/workspace.md for the format):
#   ## <component> / <ladder> / L{n}_{slug}    — <verdict>  (<date>)   -- a closed level
#   ## STAGED — <component>/<keywords>         (in progress, <date>)   -- interrupted work
# plus the per-level fields '- Mode:', '- Finding:', '- Last synced:'.
#
# Tolerates human-edited markdown: matching is by leading '## ' and an em/en/hyphen dash,
# not exact whitespace.  macOS bash 3.2 — no associative arrays; plain awk/grep/case only.
set -uo pipefail
die(){ echo "status.sh: $*" >&2; exit 2; }

[[ $# -ge 1 ]] || die "usage: status.sh <workspace-dir> [keywords]"
WS="$1"; shift
KEY="${1:-}"
[[ -d "$WS" ]] || die "no such workspace dir: $WS"

MEM="$WS/MEMORY.md"
ROADMAP="$WS/ROADMAP.md"

# Robustness: a missing or whitespace-only MEMORY.md means nothing has been modeled yet.
if [[ ! -s "$MEM" ]] || ! grep -q '[^[:space:]]' "$MEM" 2>/dev/null; then
  echo "no models yet — run /vibe-tla check"
  exit 0
fi

# All parsing happens in one awk pass.  awk has no notion of the shell's bash version,
# so the "no associative arrays" constraint is moot inside it; we still keep it simple.
#   - A heading starts a new record; its following '- Field:' lines fill that record.
#   - STAGED headings collect "Done so far" / "Next step" so the operator can resume.
#   - Counts are kept as plain scalar accumulators.
# KEY filtering is applied to the heading text of LEVEL records only (case-insensitive).
awk -v key="$KEY" '
  function lc(s){ return tolower(s) }
  function trim(s){ sub(/^[[:space:]]+/, "", s); sub(/[[:space:]]+$/, "", s); return s }

  # Strip a leading "## " and return the heading body, or "" if not a heading.
  function head_body(line,   b){
    if (line !~ /^[[:space:]]*##[[:space:]]/) return ""
    b = line
    sub(/^[[:space:]]*##[[:space:]]+/, "", b)
    return trim(b)
  }

  # Pull the value after "- <Name>:" (case-insensitive on the name).
  function field(line, name,   re, v){
    re = "^[[:space:]]*[-*][[:space:]]*" name "[[:space:]]*:[[:space:]]*"
    if (lc(line) ~ lc(re)) {
      v = line
      sub(/^[[:space:]]*[-*][[:space:]]*[^:]*:[[:space:]]*/, "", v)
      return trim(v)
    }
    return "__NONE__"
  }

  # Normalize a verdict word to one bucket for counting; tolerate sloppy casing/words.
  function verdict_bucket(v,   l){
    l = lc(v)
    if (l ~ /retir/)                   return "retired"
    if (l ~ /confirm/)                 return "confirmed"
    if (l ~ /refut/)                   return "refuted"
    if (l ~ /candidate/)               return "candidate"
    if (l ~ /safe/)                    return "safe"
    if (l ~ /pass|validated|contract/) return "pass"
    return "other"
  }

  # Classify from the authoritative "- Finding:" field (none|candidate(...)|confirmed|
  # refuted(...)|safe-by-design).  workspace.md defines Finding as canonical; the heading
  # verdict only mirrors it, so we bucket on Finding first and fall back to the heading.
  # Anchor on the LEADING token — the precondition text of "candidate(... confirm ...)"
  # must not be misread as "confirmed".
  function finding_bucket(f,   l){
    l = lc(f); sub(/^[[:space:]]+/, "", l)
    if (l ~ /^candidate/)               return "candidate"
    if (l ~ /^confirm/)                 return "confirmed"
    if (l ~ /^retir/)                   return "retired"
    if (l ~ /^refut/)                   return "refuted"
    if (l ~ /^safe/)                    return "safe"
    if (l ~ /^none/ || l ~ /^pass/ || l ~ /^valid/ || l ~ /^contract/) return "pass"
    return "other"
  }

  # Flush the level record currently being accumulated into the ledger arrays.
  function flush_level(   show){
    if (!in_level) return
    show = 1
    if (key != "" && index(lc(cur_match), lc(key)) == 0) show = 0
    if (show) {
      n_show++
      L_name[n_show]   = cur_name
      L_verdict[n_show]= cur_verdict
      L_finding[n_show]= cur_finding
      L_synced[n_show] = cur_synced
    }
    # Counts span the whole file regardless of the keyword filter.
    total++
    # Bucket from the authoritative "- Finding:" field; fall back to the heading verdict.
    b = (cur_finding != "" ? finding_bucket(cur_finding) : "other")
    if (b == "other") b = verdict_bucket(cur_verdict)
    cnt[b]++
    # A candidate level is open by definition: it is waiting on one owner fact.
    if (b == "candidate") open_cand++
    if (cur_synced == "" || lc(cur_synced) ~ /never/) never_synced++
    in_level = 0
  }

  function flush_staged(){
    if (!in_staged) return
    n_staged++
    S_name[n_staged] = cur_name
    S_done[n_staged] = cur_done
    S_next[n_staged] = cur_next
    in_staged = 0
  }

  function reset_rec(){
    cur_name=""; cur_verdict=""; cur_finding=""; cur_synced=""
    cur_match=""; cur_done=""; cur_next=""; cont=""
  }

  BEGIN { in_level=0; in_staged=0; total=0; n_show=0; n_staged=0;
          open_cand=0; never_synced=0 }

  {
    hb = head_body($0)
    if (hb != "") {
      # A new heading closes whatever record was open.
      flush_level(); flush_staged(); reset_rec()

      if (hb ~ /^STAGED/) {
        in_staged = 1
        # Heading body after "STAGED" and its dash, if any.
        s = hb
        sub(/^STAGED[[:space:]]*[—–-]*[[:space:]]*/, "", s)
        cur_name = trim(s)
        # Drop the trailing "(in progress, <date>)" qualifier from the display name.
        sub(/[[:space:]]*\(.*$/, "", cur_name)
        cur_name = trim(cur_name)
        if (cur_name == "") cur_name = "(unnamed)"
      } else {
        # A level heading: "<comp> / <ladder> / Ln_slug   — <verdict> (<date>)".
        in_level = 1
        cur_match = hb            # full heading text used for keyword filtering
        # Split on the dash that precedes the verdict.  Em/en/hyphen all accepted.
        name = hb; verd = ""
        if (match(hb, /[[:space:]]+[—–-]+[[:space:]]+/)) {
          name = substr(hb, 1, RSTART-1)
          rest = substr(hb, RSTART+RLENGTH)
          verd = rest
          # Keep only the leading verdict word(s); drop everything from the first "("
          # (covers both a "(why ...)" qualifier and the trailing "(date)").
          sub(/[[:space:]]*\(.*$/, "", verd)
        }
        cur_name    = trim(name)
        cur_verdict = trim(verd)
        if (cur_verdict == "") cur_verdict = "?"
      }
      next
    }

    # Non-heading line: try to fill the open record.
    if (in_level) {
      v = field($0, "Finding");     if (v != "__NONE__") { cur_finding = v; cont = "finding" }
      v = field($0, "Last synced"); if (v != "__NONE__") cur_synced  = v
      # A "- Finding:" bullet often wraps over several physical lines; join its
      # indented non-bullet continuation lines so the ledger shows the whole verdict.
      if ($0 ~ /^[[:space:]]*[-*][[:space:]]/) {
        if (field($0, "Finding") == "__NONE__") cont = ""
      } else if (cont == "finding" && $0 ~ /^[[:space:]]+[^[:space:]]/) {
        cur_finding = cur_finding " " trim($0)
      } else if ($0 !~ /^[[:space:]]*$/) {
        cont = ""
      }
    } else if (in_staged) {
      v = field($0, "Done so far"); if (v != "__NONE__") cur_done = v
      v = field($0, "Next step");   if (v != "__NONE__") cur_next = v
    }
  }

  END {
    flush_level(); flush_staged()

    # ---- Ledger (one line per level, filtered by keyword) ----
    print "VERIFICATION LEDGER" (key != "" ? "  (filter: \"" key "\")" : "")
    print "-------------------------------------------------------------------------------"
    if (n_show == 0) {
      if (key != "") print "  (no levels match \"" key "\")"
      else           print "  (no level entries parsed)"
    } else {
      for (i = 1; i <= n_show; i++) {
        fnd = (L_finding[i] == "" ? "-" : L_finding[i])
        syn = (L_synced[i]  == "" ? "never" : L_synced[i])
        printf "  %-14s | %-44s | synced: %s\n", L_verdict[i], L_name[i], syn
        printf "            finding: %s\n", fnd
      }
    }

    # ---- STAGED (feeds /vibe-tla resume) ----
    print ""
    print "STAGED (in progress — finish with /vibe-tla resume)"
    print "-------------------------------------------------------------------------------"
    if (n_staged == 0) {
      print "  (none)"
    } else {
      for (i = 1; i <= n_staged; i++) {
        print "  * " S_name[i]
        if (S_done[i] != "") print "      done so far: " S_done[i]
        if (S_next[i] != "") print "      next step:   " S_next[i]
      }
    }

    # ---- Counts (always over the whole file, not the filtered view) ----
    print ""
    print "COUNTS (whole workspace)"
    print "-------------------------------------------------------------------------------"
    printf "  total levels:    %d\n", total
    printf "  PASS:            %d\n", cnt["pass"]+0
    printf "  candidate:       %d\n", cnt["candidate"]+0
    printf "  confirmed:       %d\n", cnt["confirmed"]+0
    printf "  retired:         %d\n", cnt["retired"]+0
    printf "  refuted:         %d\n", cnt["refuted"]+0
    printf "  safe-by-design:  %d\n", cnt["safe"]+0
    if (cnt["other"]+0 > 0) printf "  unclassified:    %d\n", cnt["other"]
    printf "  staged:          %d\n", n_staged
    printf "  open candidates: %d\n", open_cand+0
    printf "  awaiting fix:    %d\n", cnt["confirmed"]+0
    printf "  never synced:    %d\n", never_synced+0
  }
' "$MEM"

# ---- Backlog: append ROADMAP.md verbatim if it carries content ----
if [[ -s "$ROADMAP" ]] && grep -q '[^[:space:]]' "$ROADMAP" 2>/dev/null; then
  echo ""
  echo "Backlog (from ROADMAP.md)"
  echo "-------------------------------------------------------------------------------"
  cat "$ROADMAP"
fi

exit 0
