#!/bin/bash
# PostToolUse hook for Edit, Write, MultiEdit tool calls.
# Purpose: auto-format Terraform files after they're edited.
# Always exits 0 — PostToolUse runs after the tool action and cannot undo it;
# formatting failure should never block the agent.

set -uo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // ""')

# Skip if no file path
if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

# Only act on Terraform files
case "$FILE_PATH" in
  *.tf|*.tfvars|*.tftest.hcl)
    # Only run if terraform binary is on PATH; silent fail if not
    if command -v terraform >/dev/null 2>&1; then
      terraform fmt "$FILE_PATH" >/dev/null 2>&1 || true
    fi
    ;;
esac

exit 0
