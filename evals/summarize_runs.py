#!/usr/bin/env python3
"""Roll up every committed eval-run JSON into one human-readable summary.

The per-run JSONs under `docs/eval-results/runs/<scenario>/<ts>-<sid>.json`
are the systematic source of truth (one file per `make eval-scenario`
invocation), but each one is ~50 KB of spans + verdicts + reference
inputs — too dense to scan when the corpus grows past a handful of
scenarios. This script walks the tree, extracts only the load-bearing
fields, and writes a single markdown summary to
`docs/eval-results/summary.md` with:

  - A per-scenario run table (timestamp, diagnosis verdict, MAST
    classification if the run failed, trajectory match, link to JSON).
  - An aggregate FM distribution across all failed runs that have a
    MAST classification — the §3.5 interview-grade payoff.
  - A "verdicts by gating evaluator" rollup.

Re-run any time:
    make eval-summary
or:
    uv run python evals/summarize_runs.py

The summary file overwrites in place; it's intentionally derived, not
hand-maintained. Per-run narratives (interpretive analysis, "Notable
observations") still live in `docs/scenario-runs/<slug>.md` — this
script does not touch those.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "docs" / "eval-results" / "runs"
SUMMARY_PATH = REPO_ROOT / "docs" / "eval-results" / "summary.md"

DIAGNOSIS_JUDGE_PREFIX = "diagnosis_matches_ground_truth"
MAST_JUDGE_PREFIX = "mast_classification"
TRAJECTORY_EVALUATOR = "Builtin.TrajectoryInOrderMatch"
GOAL_EVALUATOR = "Builtin.GoalSuccessRate"


def _find_verdict(verdicts: list[dict[str, Any]], prefix: str) -> dict[str, Any] | None:
    """Return the first verdict whose evaluator_id starts with `prefix`."""
    for v in verdicts:
        if v.get("evaluator_id", "").startswith(prefix):
            return v
    return None


def _diag_emoji(score: float | None) -> str:
    """Match (2.0) → 🟢, Partial (1.0) → 🟡, NoMatch (0.0) → 🔴, missing → —."""
    if score is None:
        return "—"
    if score >= 2.0:
        return "🟢"
    if score >= 1.0:
        return "🟡"
    return "🔴"


def _load_runs() -> list[dict[str, Any]]:
    """Walk RUNS_DIR; return one dict per run JSON, sorted by (scenario, timestamp_utc)."""
    runs: list[dict[str, Any]] = []
    for path in sorted(RUNS_DIR.rglob("*.json")):
        try:
            doc = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            print(f"warn: failed to parse {path}: {e}", file=sys.stderr)
            continue
        runs.append({"path": path, "doc": doc})
    return runs


def _row_for_run(run: dict[str, Any]) -> dict[str, Any]:
    """Distill one run dict down to the columns we surface in the table."""
    doc = run["doc"]
    path = run["path"]
    verdicts = doc.get("evaluator_verdicts", [])
    diag = _find_verdict(verdicts, DIAGNOSIS_JUDGE_PREFIX) or {}
    mast = _find_verdict(verdicts, MAST_JUDGE_PREFIX)
    traj = _find_verdict(verdicts, TRAJECTORY_EVALUATOR) or {}
    goal = _find_verdict(verdicts, GOAL_EVALUATOR) or {}

    diag_score = diag.get("score")
    return {
        "scenario": doc.get("scenario", path.parent.name),
        "timestamp": doc.get("timestamp_utc", ""),
        "session_id_short": (doc.get("session_id") or "")[:13],
        "diagnosis_emoji": _diag_emoji(diag_score),
        "diagnosis_label": diag.get("label") or "—",
        "diagnosis_score": diag_score,
        "mast_label": mast.get("label") if mast else None,
        "mast_rationale": (mast.get("rationale") or "").strip() if mast else None,
        "trajectory_label": traj.get("label") or "—",
        "goal_label": goal.get("label") or "—",
        "turns": doc.get("turns"),
        # Relative to summary.md's location so the link works when rendered.
        "relpath": path.relative_to(SUMMARY_PATH.parent).as_posix(),
    }


def _per_scenario_section(scenario: str, rows: list[dict[str, Any]]) -> str:
    """Render the per-scenario run table."""
    lines = [f"### {scenario}", ""]
    lines.append("| Timestamp (UTC) | Diagnosis | Trajectory | GoalSuccess | MAST | Turns | JSON |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in rows:
        ts = r["timestamp"].replace("T", " ").split("+")[0][:19]
        diag = f"{r['diagnosis_emoji']} {r['diagnosis_label']}"
        mast = f"**{r['mast_label']}**" if r["mast_label"] else "—"
        json_link = f"[{r['session_id_short']}…]({r['relpath']})"
        lines.append(
            f"| {ts} | {diag} | {r['trajectory_label']} | {r['goal_label']} "
            f"| {mast} | {r['turns']} | {json_link} |"
        )
    lines.append("")
    return "\n".join(lines)


def _fm_distribution(rows: list[dict[str, Any]]) -> str:
    """Aggregate MAST labels across all runs that carry one."""
    labeled = [r for r in rows if r["mast_label"]]
    if not labeled:
        return (
            "_No MAST classifications recorded yet. MAST is wired as a post-hoc "
            "classifier that runs on every trace; historical runs pre-dating the "
            "MAST wiring (Day 36 Hour 13) are not backfilled by design._\n"
        )
    counts = collections.Counter(r["mast_label"] for r in labeled)
    total = sum(counts.values())
    lines = [
        f"Across {total} run{'s' if total != 1 else ''} with a MAST "
        f"classification (post-hoc classifier; runs on every trace as of "
        f"Day 36 Hour 20):",
        "",
        "| FM code | Count | Share |",
        "|---|---|---|",
    ]
    for label, count in counts.most_common():
        share = f"{count / total:.0%}"
        lines.append(f"| **{label}** | {count} | {share} |")
    lines.append("")
    lines.append("**Per-run rationales:**")
    lines.append("")
    for r in labeled:
        ts = r["timestamp"].replace("T", " ").split("+")[0][:19]
        rationale = (r["mast_rationale"] or "").replace("\n", " ").strip()
        if len(rationale) > 300:
            rationale = rationale[:297] + "…"
        lines.append(f"- **{r['scenario']}** @ {ts} — **{r['mast_label']}** — {rationale}")
    lines.append("")
    return "\n".join(lines)


def _gating_distribution(rows: list[dict[str, Any]]) -> str:
    """Roll up diagnosis-judge verdicts across all runs."""
    counts: collections.Counter[str] = collections.Counter()
    for r in rows:
        label = r["diagnosis_label"]
        if label and label != "—":
            counts[label] += 1
    total = sum(counts.values())
    if total == 0:
        return ""
    lines = [
        f"Across {total} eval run{'s' if total != 1 else ''} on the "
        f"`diagnosis_matches_ground_truth` judge (the gating evaluator):",
        "",
        "| Verdict | Count | Share |",
        "|---|---|---|",
    ]
    for label, count in counts.most_common():
        emoji = "🟢" if label == "Match" else "🟡" if label == "Partial" else "🔴"
        share = f"{count / total:.0%}"
        lines.append(f"| {emoji} {label} | {count} | {share} |")
    lines.append("")
    return "\n".join(lines)


def _render(rows: list[dict[str, Any]]) -> str:
    """Assemble the full summary.md content."""
    by_scenario: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for r in rows:
        by_scenario[r["scenario"]].append(r)

    lines = [
        "# Eval-run summary",
        "",
        "> **Derived artifact.** Regenerate any time with `make eval-summary` "
        "(scans `docs/eval-results/runs/**/*.json`, writes this file). "
        "Hand-edits get overwritten — write narrative analysis into "
        "`docs/scenario-runs/<slug>.md` instead.",
        "",
        f"**Total runs committed:** {len(rows)} across {len(by_scenario)} scenario"
        f"{'s' if len(by_scenario) != 1 else ''}.",
        "",
        "## Verdict distribution",
        "",
        _gating_distribution(rows),
        "## MAST failure-mode distribution",
        "",
        _fm_distribution(rows),
        "## Per-scenario run history",
        "",
    ]
    for scenario in sorted(by_scenario):
        lines.append(_per_scenario_section(scenario, by_scenario[scenario]))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Render but do not write; exit 1 if the on-disk summary.md "
            "would change. Useful in CI to verify the file is regenerated."
        ),
    )
    parser.add_argument("--stdout", action="store_true", help="Print to stdout instead of writing.")
    args = parser.parse_args(argv)

    raw_runs = _load_runs()
    if not raw_runs:
        print(f"No run JSONs found under {RUNS_DIR}", file=sys.stderr)
        return 0
    rows = [_row_for_run(r) for r in raw_runs]
    rendered = _render(rows)

    if args.stdout:
        sys.stdout.write(rendered)
        return 0

    if args.check:
        existing = SUMMARY_PATH.read_text() if SUMMARY_PATH.exists() else ""
        if existing != rendered:
            print("summary.md is out of date — re-run `make eval-summary`", file=sys.stderr)
            return 1
        return 0

    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(rendered)
    print(f"Wrote {SUMMARY_PATH.relative_to(REPO_ROOT)} ({len(rows)} runs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
