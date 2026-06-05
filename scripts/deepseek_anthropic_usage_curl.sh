#!/usr/bin/env bash
set -euo pipefail

# Debug DeepSeek's Anthropic-compatible Messages API response.
#
# Usage:
#   ANTHROPIC_API_KEY=sk-... ./scripts/deepseek_anthropic_usage_curl.sh
#   ANTHROPIC_API_KEY=sk-... MODEL_ID=deepseek-v4-pro ./scripts/deepseek_anthropic_usage_curl.sh
#
# The response JSON should contain a `usage` object. For cache accounting,
# check fields such as:
#   - input_tokens
#   - output_tokens
#   - cache_creation_input_tokens
#   - cache_read_input_tokens

BASE_URL="${ANTHROPIC_BASE_URL:-https://api.deepseek.com/anthropic}"
MODEL_ID="${MODEL_ID:-deepseek-v4-flash}"
API_KEY="${ANTHROPIC_API_KEY:-${DEEPSEEK_API_KEY:-}}"

if [[ -z "${API_KEY}" ]]; then
  echo "Error: set ANTHROPIC_API_KEY or DEEPSEEK_API_KEY first." >&2
  exit 1
fi

curl -sS "${BASE_URL%/}/v1/messages" \
  -H "x-api-key: ${API_KEY}" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d @- <<JSON
{
  "model": "${MODEL_ID}",
  "max_tokens": 16,
  "system": "Reply with a short plain text answer.",
  "messages": [
    {
      "role": "user",
      "content": "Say pong. This is a token usage debug request."
    }
  ]
}
JSON
echo
