#!/usr/bin/env bash
# Re-record real per-source fixtures to catch field drift.
# Usage: scripts/refresh_source_fixtures.sh [CA]   (default: a small live token)
# Note: Helius getTokenLargestAccounts overloads on huge tokens (e.g. BONK) — use a small/new token.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; [ -f .env ] && . ./.env 2>/dev/null; set +a
CA="${1:-2kDX2fm3Tqtv6zycg3tcD4E8ySadwh3Nz4QpgQmTbonk}"
DIR=tests/memedogV2/fixtures/sources; mkdir -p "$DIR"

echo "RugCheck…"; curl -s --max-time 60 "https://api.rugcheck.xyz/v1/tokens/$CA/report" -o "$DIR/rugcheck.json"
echo "Helius… (retries; transient http=000 is common)"
for i in 1 2 3 4; do
  c=$(curl -s --max-time 30 -w "%{http_code}" "https://mainnet.helius-rpc.com/?api-key=$HELIUS_API_KEY" \
      -X POST -H 'Content-Type: application/json' \
      -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"getTokenLargestAccounts\",\"params\":[\"$CA\"]}" \
      -o "$DIR/helius.json"); [ "$c" = "200" ] && break; sleep 4
done
echo "gmgn…"; gmgn-cli token info --chain sol --address "$CA" --raw > "$DIR/gmgn_info.json"; sleep 2
gmgn-cli token security --chain sol --address "$CA" --raw > "$DIR/gmgn_security.json"
echo "done."; wc -c "$DIR"/*.json
