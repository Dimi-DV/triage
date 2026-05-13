#!/bin/bash
# PreToolUse hook for Edit, Write, MultiEdit tool calls.
# Purpose: block writes containing AWS credential patterns.
# Exit codes: 0 = allow, 2 = block

set -uo pipefail

INPUT=$(cat)

# Extract content being written. Different tools structure their input differently:
#   - Write: tool_input.content
#   - Edit:  tool_input.new_string
#   - MultiEdit: tool_input.edits[].new_string
#   - Some variants use file_text
CONTENT=$(echo "$INPUT" | jq -r '
  .tool_input.content //
  .tool_input.new_string //
  .tool_input.file_text //
  ([.tool_input.edits[]?.new_string] | join("\n")) //
  ""
')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // "unknown"')

# Skip empty content
if [[ -z "$CONTENT" ]]; then
  exit 0
fi

# Pattern 1: AWS Access Key ID (high-confidence — AKIA prefix is reserved)
if echo "$CONTENT" | grep -qE 'AKIA[0-9A-Z]{16}'; then
  echo "BLOCKED: AWS Access Key ID pattern (AKIA...) detected in $FILE_PATH." >&2
  echo "Use environment variables, IAM roles, or AWS profiles instead." >&2
  exit 2
fi

# Pattern 2: AWS Secret Access Key assigned to a key-named variable
if echo "$CONTENT" | grep -qiE 'aws[_-]?secret[_-]?access[_-]?key[[:space:]]*[:=][[:space:]]*["\x27]?[a-zA-Z0-9/+=]{40}'; then
  echo "BLOCKED: AWS secret access key pattern detected in $FILE_PATH." >&2
  echo "Move the secret to AWS Secrets Manager, SSM Parameter Store, or env vars." >&2
  exit 2
fi

# Pattern 3: AWS Session Token pattern (long base64-like)
if echo "$CONTENT" | grep -qiE 'aws[_-]?session[_-]?token[[:space:]]*[:=][[:space:]]*["\x27]?[a-zA-Z0-9/+=]{100,}'; then
  echo "BLOCKED: AWS session token pattern detected in $FILE_PATH." >&2
  exit 2
fi

# Pattern 4 (warn only — high false-positive rate): generic API key / bearer token assignments
# Doesn't block — too many test fixtures, .env.example files, etc. trigger this
if echo "$CONTENT" | grep -qiE '(api[_-]?key|bearer|secret[_-]?token)[[:space:]]*[:=][[:space:]]*["\x27][a-zA-Z0-9_\-]{32,}["\x27]'; then
  echo "WARN: looks like a hardcoded API key/token in $FILE_PATH — verify it's not a real secret." >&2
fi

# All clear
exit 0
