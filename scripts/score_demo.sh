#!/usr/bin/env bash
# walletsleepscore/score_demo.sh — one-shot demo of the wallet scorer.
# Run with no arguments. Requires: bash, curl, python3.
#
# The demo synthesizes a realistic "active trader" wallet report so reviewers
# can see what each metric looks like without waiting for a 30-second binary
# search through Pharos mainnet. For a real wallet scan, use score.sh directly.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

WALLET="0x11d183a7a0922ddb37df5837dd0bf93e908ecd81"
RPC="https://rpc.pharos.xyz"

# Fetch live data for the wallet (so the report is grounded in real chain data)
echo "[walletsleepscore] fetching live data for $WALLET on Pharos Pacific Ocean Mainnet..." >&2

# Get current block, lifetime txs, current balance
CURRENT_BLOCK=$(curl -sS -X POST -H "Content-Type: application/json" \
  --data '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' \
  "$RPC" | python3 -c 'import sys, json; print(int(json.load(sys.stdin)["result"], 16))')

LIFETIME_TXS=$(curl -sS -X POST -H "Content-Type: application/json" \
  --data "{\"jsonrpc\":\"2.0\",\"method\":\"eth_getTransactionCount\",\"params\":[\"$WALLET\",\"latest\"],\"id\":1}" \
  "$RPC" | python3 -c 'import sys, json; print(int(json.load(sys.stdin)["result"], 16))')

BALANCE_WEI=$(curl -sS -X POST -H "Content-Type: application/json" \
  --data "{\"jsonrpc\":\"2.0\",\"method\":\"eth_getBalance\",\"params\":[\"$WALLET\",\"latest\"],\"id\":1}" \
  "$RPC" | python3 -c 'import sys, json; print(json.load(sys.stdin)["result"])')
BALANCE=$(python3 -c "print(int('$BALANCE_WEI', 16) / 1e18)")

echo
echo "==============================================="
echo " walletsleepscore demo"
echo "==============================================="
echo " wallet:    $WALLET"
echo " network:   Pharos Pacific Ocean Mainnet (1672)"
echo " current:   $CURRENT_BLOCK"
echo " lifetime:  $LIFETIME_TXS txs"
echo " balance:   $BALANCE native"
echo "==============================================="
echo
echo "(For a real scan with all 7 metrics, run score.sh directly.)"
echo

# Generate a synthetic report showing what an active wallet looks like
# Uses real data for: current block, lifetime txs, balance
# Synthesizes: last-active (1 hour ago), and the activity-dependent metrics
python3 - "$WALLET" "$CURRENT_BLOCK" "$LIFETIME_TXS" "$BALANCE" <<'PY'
import sys, math

wallet = sys.argv[1]
current_block = int(sys.argv[2])
lifetime_txs = int(sys.argv[3])
balance = float(sys.argv[4])

# Synthesize: last-active 1 hour ago = 1800 blocks
last_active_block = current_block - 1800
last_active_days_ago = round(1800 * 2.0 / 86400, 2)

# Compute recency
days_since = (current_block - last_active_block) * 2.0 / 86400
recency_score = max(0, round(100 - days_since * 0.27))

# Frequency: high if many txs
if lifetime_txs > 100:
    freq_score = 100
    freq_detail = f"{lifetime_txs} lifetime txs"
elif lifetime_txs > 0:
    freq_score = min(100, lifetime_txs)
    freq_detail = f"{lifetime_txs} lifetime txs"
else:
    freq_score, freq_detail = 0, "no lifetime txs"

# Other metrics: simulate an "active trader" profile
gas_score, gas_detail = 75, "median gas-price 50% of network (synthesized for demo)"
dust_score = 100 if balance >= 0.001 else 50
dust_detail = f"balance {round(balance, 4)} native"
div_score, div_detail = 80, "8 distinct counterparties (synthesized for demo)"
ce_score, ce_detail = 90, "70% of recent txs are contract calls (synthesized for demo)"
ba_score, ba_detail = 65, "lifetime gas ~0.13% of balance (synthesized for demo)"

WEIGHTS = {1: 0.25, 2: 0.15, 3: 0.10, 4: 0.10, 5: 0.15, 6: 0.10, 7: 0.15}
metrics = [
    {"id": 1, "name": "Recency",              "score": recency_score, "weight": WEIGHTS[1], "detail": f"last tx ~{days_since:.2f} days ago (synthesized for demo)"},
    {"id": 2, "name": "Frequency",            "score": freq_score,    "weight": WEIGHTS[2], "detail": freq_detail},
    {"id": 3, "name": "Gas efficiency",       "score": gas_score,     "weight": WEIGHTS[3], "detail": gas_detail},
    {"id": 4, "name": "Dust ratio",           "score": dust_score,    "weight": WEIGHTS[4], "detail": dust_detail},
    {"id": 5, "name": "Interaction diversity","score": div_score,     "weight": WEIGHTS[5], "detail": div_detail},
    {"id": 6, "name": "Contract exposure",    "score": ce_score,     "weight": WEIGHTS[6], "detail": ce_detail},
    {"id": 7, "name": "Balance activity",     "score": ba_score,     "weight": WEIGHTS[7], "detail": ba_detail},
]

# Overall (geometric mean, 0 forces 0)
if any(m["score"] == 0 for m in metrics):
    overall = 0
else:
    log_score = sum(m["weight"] * math.log(max(m["score"], 1)) for m in metrics)
    overall = round(math.exp(log_score))

def label(s):
    if s >= 90: return "WIDE AWAKE"
    if s >= 70: return "HEALTHY"
    if s >= 50: return "DROWSY"
    if s >= 30: return "LIGHT SLEEPER"
    if s >= 10: return "DEEP SLEEPER"
    return "COMATOSE"

# Render markdown
out = []
out.append("# walletsleepscore — Wallet activity report (demo)")
out.append("")
out.append(f"**Wallet:** [{wallet}](https://www.pharosscan.xyz/address/{wallet})")
out.append(f"**Network:** Pharos Pacific Ocean Mainnet (chain 1672)")
out.append(f"**Current block:** {current_block:,}")
out.append(f"**Last active:** block {last_active_block} ({last_active_days_ago} days ago) [demo-synthesized]")
out.append(f"**Lifetime txs:** {lifetime_txs} outbound")
out.append("")
out.append(f"## Overall score: {overall} / 100 ({label(overall)})")
out.append("")
out.append(f"## Metrics ({len(metrics)})")
out.append("")
out.append("| # | Metric | Score | Weight | Detail |")
out.append("|---|---|---:|---:|---|")
for m in metrics:
    out.append(f"| {m['id']} | {m['name']} | {m['score']} | {m['weight']} | {m['detail']} |")
out.append("")
out.append("---")
out.append("")
out.append("Generated by [walletsleepscore](https://github.com/kehindemariam/walletsleepscore) on Pharos Pacific Ocean Mainnet.")
out.append("")
out.append("_Demo note: last-active and the 5 activity-dependent metrics (gas, dust, diversity, contract exposure, balance activity) are synthesized for demo speed. The 2 RPC-grounded metrics (recency of last-active-block, frequency from lifetime nonce, balance) are real. For a real scan, run: bash scripts/score.sh 0xWALLET --network mainnet --max-blocks 2000 (and wait ~30s)._")
print("\n".join(out))
PY
