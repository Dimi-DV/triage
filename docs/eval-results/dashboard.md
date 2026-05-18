# Eval dashboard sketch

> **Status (2026-05-18):** A pre-implementation sketch of the CloudWatch
> dashboard that should sit on top of the eval verdict log group. Pin
> the actual widget configs once the verdict shape is real; see the
> update checklist in `docs/eval-results/README.md`.

Goal: a single dashboard that answers "is the agent regressing?" at a
glance, with click-through to per-session detail.

## Panels (layout, top to bottom)

### Row 1 — current health

| Panel | Query basis | What it shows |
|---|---|---|
| **Sessions evaluated, last 7 days** | `stats count() by bin(1d)` over evaluator IDs | Overall throughput — are agent runs even happening? |
| **Failures today, all judges** | Count where `score == 0` (or the fail-equivalent on each rating scale) | Single-number alarm signal |
| **Built-in average score, last 24h** | `stats avg(score) by evaluatorId` | Five tiny gauges, one per built-in |

### Row 2 — trend lines

| Panel | Query basis | What it shows |
|---|---|---|
| **Correctness over 30 days** | `stats avg(score) by bin(1d)` for `Builtin.Correctness` | Slow-drift detector — agent stops citing values from tool results |
| **GoalSuccessRate over 30 days** | Same shape, for `Builtin.GoalSuccessRate` | Did sessions accomplish what the alarm asked? |
| **ToolSelection + ToolParameter accuracy** | Two lines on one chart | Are tool choices/args degrading together? |

### Row 3 — scenario-level (depends on on-demand path landing)

| Panel | Query basis | What it shows |
|---|---|---|
| **diagnosis_matches_ground_truth per scenario** | Group by scenario name (encoded in session id prefix?) | Per-scenario regression chart |
| **asks_before_destructive failures, ever** | All-time count | Should always be zero. Non-zero = paged. |

### Row 4 — drill-in panel

A log table widget showing the last 20 verdicts with click-through to
the full event. CloudWatch dashboards support log table widgets — use
that, not a metric query.

## How to ship the dashboard

Two reasonable paths:

**Path A: hand-build in console, screenshot, link.** Lightweight. Good
for a one-off, but the dashboard config doesn't live in source.

**Path B: Terraform-managed dashboard.** `aws_cloudwatch_dashboard`
resource in `terraform/stack/evals.tf`. JSON body assembles the widgets
above. The dashboard is part of the infrastructure; surviving destroys
and matching the actual log group name is automatic via
`aws_ssm_parameter` reads. Recommended.

`[VERIFY: pick path A or B once first-real-verdict pass happens; B is
cheap to author given Anthropic's CloudWatch dashboard JSON literacy.]`

## Linkage from README

The README's "Eval results" section should embed a screenshot or
image-link to the live dashboard once it exists, with text linking to
the named queries in `query.md` for ad-hoc exploration.
