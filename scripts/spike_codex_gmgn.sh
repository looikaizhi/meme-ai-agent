#!/usr/bin/env bash
# Phase 0 spike (memedogV2): proves `codex exec` can drive `gmgn-cli` non-interactively
# and return schema-constrained JSON. Confirmed GREEN 2026-06-25.
#
# Prereqs:
#   - npm install -g gmgn-cli           (binary on PATH; confirmed v1.4.7)
#   - GMGN_API_KEY in ~/.config/gmgn/.env   (NOT the project .env — CLI reads this path)
#   - codex login valid                  (ChatGPT subscription; model gpt-5.5)
#   - IPv4 egress (gmgn 401/403 over IPv6)
#
# Key learnings baked in:
#   - stdin MUST be closed (< /dev/null) or `codex exec` hangs "Reading additional input from stdin..."
#   - --output-schema MUST be strict: top-level "additionalProperties": false AND every
#     property listed in "required", else the API rejects with 400 invalid_json_schema.
set -euo pipefail

CA="${1:-EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v}"   # default: USDC (safe known token)
SCHEMA="$(mktemp)"; OUT="$(mktemp)"
trap 'rm -f "$SCHEMA" "$OUT"' EXIT

cat > "$SCHEMA" <<'JSON'
{"type":"object","additionalProperties":false,
 "properties":{"address":{"type":"string"},"renounced_mint":{"type":"boolean"},"raw_ok":{"type":"boolean"}},
 "required":["address","renounced_mint","raw_ok"]}
JSON

codex exec \
  --dangerously-bypass-approvals-and-sandbox \
  --skip-git-repo-check \
  --output-schema "$SCHEMA" \
  -o "$OUT" \
  "Run this exact shell command: gmgn-cli token security --chain sol --address ${CA} --raw — then return JSON with: address, renounced_mint (boolean from output), and raw_ok=true if the command returned JSON data." \
  < /dev/null

echo "----- codex schema output -----"
cat "$OUT"; echo
