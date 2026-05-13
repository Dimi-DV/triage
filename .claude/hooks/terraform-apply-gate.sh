#!/bin/bash
# PreToolUse hook for Bash tool calls.
# Purpose: gate `terraform apply` behind a recent `terraform plan` in the same directory.
# Behavior:
#   - If command is `terraform plan ...` → touch .last-tf-plan in the working dir, allow
#   - If command is `terraform apply ...` → check .last-tf-plan freshness (≤30 min), allow or block
#   - All other commands → pass through
# Exit codes: 0 = allow, 2 = block

set -uo pipefail

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')

# If jq couldn't parse or command is empty, don't block
if [[ -z "$COMMAND" ]]; then
  exit 0
fi

# Try to detect the working dir from `cd <dir> && terraform ...` patterns;
# fall back to current dir
TF_DIR=$(echo "$COMMAND" | grep -oE '(^|[[:space:]])cd[[:space:]]+[^[:space:]&]+' | head -1 | awk '{print $NF}')
TF_DIR="${TF_DIR:-.}"
MARKER="${TF_DIR}/.last-tf-plan"

# Case 1: terraform plan → record timestamp
if echo "$COMMAND" | grep -qE '\bterraform[[:space:]]+plan\b'; then
  mkdir -p "$TF_DIR" 2>/dev/null
  touch "$MARKER" 2>/dev/null
  exit 0
fi

# Case 2: terraform apply → require recent plan
if echo "$COMMAND" | grep -qE '\bterraform[[:space:]]+apply\b'; then
  if [[ ! -f "$MARKER" ]]; then
    echo "BLOCKED: no terraform plan recorded in $TF_DIR." >&2
    echo "Run 'terraform plan' first, then retry the apply." >&2
    exit 2
  fi

  # Cross-platform mtime: GNU stat (Linux) uses -c %Y; BSD/macOS uses -f %m
  PLAN_TS=$(stat -c %Y "$MARKER" 2>/dev/null || stat -f %m "$MARKER" 2>/dev/null)
  NOW=$(date +%s)
  AGE=$((NOW - PLAN_TS))

  if [[ $AGE -gt 1800 ]]; then
    echo "BLOCKED: terraform plan in $TF_DIR is $((AGE / 60)) min old (limit: 30)." >&2
    echo "Re-run 'terraform plan' before applying — state may have drifted." >&2
    exit 2
  fi
fi

# Everything else passes
exit 0
