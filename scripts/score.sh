#!/usr/bin/env bash
# walletsleepscore/score.sh — zero-dep bash scorer for Pharos wallets.
# Usage:
#   bash scripts/score.sh 0xWALLET --network mainnet
#   bash scripts/score.sh 0xWALLET --network testnet --format json
#   bash scripts/score.sh 0xWALLET --network mainnet --max-blocks 5000 --txs 200
#
# Requires: bash 4+, curl, python3
# Read-only: never asks for a private key, never sends a transaction.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# -------------------- args --------------------
if [[ $# -lt 1 ]] || [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
  cat <<EOF
Usage: bash scripts/score.sh 0xWALLET [--network mainnet|atlantic-testnet] [--format md|json|txt] [--max-blocks 10000] [--txs 200]

Networks:
  atlantic-testnet  (default) — Pharos Atlantic Testnet, chain 688689
  mainnet                       — Pharos Pacific Ocean Mainnet, chain 1672

Examples:
  bash scripts/score.sh 0xWALLET --network mainnet
  bash scripts/score.sh 0xWALLET --network testnet --format json
  bash scripts/score.sh 0xWALLET --network mainnet --max-blocks 5000 --txs 200
EOF
  exit 0
fi

WALLET="${1,,}"
NETWORK="atlantic-testnet"
FORMAT="md"
MAX_BLOCKS=10000
TXS=200

shift
while [[ $# -gt 0 ]]; do
  case "$1" in
    --network)     NETWORK="$2"; shift 2 ;;
    --format)      FORMAT="$2"; shift 2 ;;
    --max-blocks)  MAX_BLOCKS="$2"; shift 2 ;;
    --txs)         TXS="$2"; shift 2 ;;
    *) echo "Unknown flag: $1" >&2; exit 2 ;;
  esac
done

# validate
if [[ ! "$WALLET" =~ ^0x[0-9a-f]{40}$ ]]; then
  echo "ERROR: wallet must look like 0x + 40 hex chars" >&2; exit 2
fi

case "$NETWORK" in
  mainnet)
    CHAIN_ID=1672
    RPC="https://rpc.pharos.xyz"
    EXPLORER="https://www.pharosscan.xyz"
    NET_LABEL="Pharos Pacific Ocean Mainnet (chain 1672)"
    ;;
  atlantic-testnet|testnet)
    CHAIN_ID=688689
    RPC="https://atlantic.dplabs-internal.com"
    EXPLORER="https://atlantic.pharosscan.xyz"
    NET_LABEL="Pharos Atlantic Testnet (chain 688689)"
    ;;
  *) echo "ERROR: unknown network: $NETWORK" >&2; exit 2 ;;
esac

case "$FORMAT" in md|json|txt) ;; *) echo "ERROR: format must be md|json|txt" >&2; exit 2 ;; esac

echo "[walletsleepscore] fetching data for $WALLET on $NET_LABEL" >&2

# -------------------- run scorer --------------------
export SCORER_NETWORK="$NETWORK"
export SCORER_RPC="$RPC"
export SCORER_MAX_BLOCKS="$MAX_BLOCKS"
export SCORER_TXS="$TXS"
export SCORER_WALLET="$WALLET"

REPORT_JSON=$(export SCORER_NETWORK SCORER_RPC SCORER_MAX_BLOCKS SCORER_TXS SCORER_WALLET && python3 <<'PYEOF'
import os, json, urllib.request

NETWORK = os.environ["SCORER_NETWORK"]
RPC = os.environ["SCORER_RPC"]
WALLET = os.environ["SCORER_WALLET"]
MAX_BLOCKS = int(os.environ["SCORER_MAX_BLOCKS"])
TXS = int(os.environ["SCORER_TXS"])

DUST_THRESHOLD = 0.001
BLOCK_TIME_SEC = 2.0
WEIGHTS = {1: 0.25, 2: 0.15, 3: 0.10, 4: 0.10, 5: 0.15, 6: 0.10, 7: 0.15}

_id = [0]
def rpc(method, params):
    _id[0] += 1
    payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": _id[0]}).encode()
    req = urllib.request.Request(RPC, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read())
    if "error" in data:
        raise RuntimeError(f"RPC {method}: {data['error']}")
    return data.get("result")

def int_or_zero(s, base=16):
    if s is None: return 0
    return int(s, base)

current_block = int_or_zero(rpc("eth_blockNumber", []))
lifetime_txs = int_or_zero(rpc("eth_getTransactionCount", [WALLET, "latest"]))

# Find last-active block (bounded scan)
last_active_block = None
if lifetime_txs > 0 and MAX_BLOCKS > 0:
    block = current_block
    for i in range(MAX_BLOCKS):
        if block <= 0: break
        n = int_or_zero(rpc("eth_getBlockTransactionCountByNumber", [hex(block)]))
        if n > 0:
            blk = rpc("eth_getBlockByNumber", [hex(block), True])
            for tx in blk.get("transactions", []):
                if tx.get("from", "").lower() == WALLET.lower():
                    last_active_block = block
                    break
            if last_active_block: break
        block -= 1

# Sample recent blocks
sample = []
for b in range(current_block, max(0, current_block - TXS), -1):
    try:
        sample.append(rpc("eth_getBlockByNumber", [hex(b), True]))
    except Exception:
        continue

# Compute metrics
metrics = []

# 1. Recency
if last_active_block is None or last_active_block == 0:
    recency_score = 0
    recency_detail = "wallet has never sent a tx"
else:
    days = (current_block - last_active_block) * BLOCK_TIME_SEC / 86400
    recency_score = max(0, round(100 - days * 0.27))
    recency_detail = f"last tx {round(days, 1)} days ago (block {last_active_block})"
metrics.append({"id": 1, "name": "Recency", "score": recency_score, "weight": WEIGHTS[1], "detail": recency_detail})

# 2. Frequency
if lifetime_txs == 0:
    freq_score = 0
    freq_detail = "no lifetime txs"
elif last_active_block is None or last_active_block == current_block:
    freq_score = 100
    freq_detail = "new wallet"
else:
    age_days = max(1, (current_block - last_active_block) * BLOCK_TIME_SEC / 86400)
    txs_per_week = lifetime_txs * 7 / age_days
    freq_score = min(100, round(txs_per_week * 20))
    freq_detail = f"{round(txs_per_week, 2)} txs/week (lifetime)"
metrics.append({"id": 2, "name": "Frequency", "score": freq_score, "weight": WEIGHTS[2], "detail": freq_detail})

# 3. Gas efficiency
net_gp = []
wal_gp = []
for blk in sample:
    for tx in blk.get("transactions", []):
        gp = int_or_zero(tx.get("gasPrice"))
        if gp == 0: continue
        net_gp.append(gp)
        if tx.get("from", "").lower() == WALLET.lower():
            wal_gp.append(gp)
if not wal_gp or not net_gp:
    gas_score, gas_detail = 50, "no recent txs to evaluate"
else:
    net_med = sorted(net_gp)[len(net_gp) // 2]
    wal_med = sorted(wal_gp)[len(wal_gp) // 2]
    pct = wal_med / max(net_med, 1)
    gas_score = max(0, round(100 - max(0, pct - 0.25) * 200))
    gas_detail = f"median gas-price {round(pct * 100)}% of network median"
metrics.append({"id": 3, "name": "Gas efficiency", "score": gas_score, "weight": WEIGHTS[3], "detail": gas_detail})

# 4. Dust ratio
balance = int_or_zero(rpc("eth_getBalance", [WALLET, "latest"]))
balance_native = balance / 1e18
if lifetime_txs > 50 and balance_native < DUST_THRESHOLD:
    dust_score = 50
    dust_detail = f"low balance ({round(balance_native, 4)} native) + {lifetime_txs} lifetime txs"
else:
    dust_score = 100
    dust_detail = f"balance {round(balance_native, 4)} native"
metrics.append({"id": 4, "name": "Dust ratio", "score": dust_score, "weight": WEIGHTS[4], "detail": dust_detail})

# 5. Diversity
counterparties = set()
for blk in sample:
    for tx in blk.get("transactions", []):
        if tx.get("from", "").lower() == WALLET.lower():
            to = tx.get("to", "")
            if to and to != "0x" + "0" * 40:
                counterparties.add(to.lower())
if not counterparties:
    div_score, div_detail = 0, "no recent txs to evaluate"
else:
    div_score = min(100, round(len(counterparties) * 10))
    div_detail = f"{len(counterparties)} distinct counterparties in last {len(sample)} blocks"
metrics.append({"id": 5, "name": "Interaction diversity", "score": div_score, "weight": WEIGHTS[5], "detail": div_detail})

# 6. Contract exposure
total_w = 0
contract_w = 0
for blk in sample:
    for tx in blk.get("transactions", []):
        if tx.get("from", "").lower() == WALLET.lower():
            total_w += 1
            to = tx.get("to", "")
            if to and to != "0x" + "0" * 40:
                code = rpc("eth_getCode", [to, "latest"])
                if code and code != "0x" and len(code) > 2:
                    contract_w += 1
if total_w == 0:
    ce_score, ce_detail = 50, "no recent txs to evaluate"
else:
    ratio = contract_w / total_w
    ce_score = max(0, round(100 - 4 * abs(ratio - 0.7) * 100))
    ce_detail = f"{round(ratio * 100)}% of {total_w} recent txs are contract calls"
metrics.append({"id": 6, "name": "Contract exposure", "score": ce_score, "weight": WEIGHTS[6], "detail": ce_detail})

# 7. Balance activity (rough)
sample_gas = 0
for blk in sample:
    for tx in blk.get("transactions", []):
        if tx.get("from", "").lower() == WALLET.lower():
            gp = int_or_zero(tx.get("gasPrice"))
            gl = int_or_zero(tx.get("gas"))
            sample_gas += gp * (gl // 2)
ratio = sample_gas / max(balance, 1)
ba_score = min(100, max(0, round(ratio * 500)))
ba_detail = f"sample gas ~{round(ratio * 100, 2)}% of balance (rough)"
metrics.append({"id": 7, "name": "Balance activity", "score": ba_score, "weight": WEIGHTS[7], "detail": ba_detail})

# Overall (geometric mean, 0 forces 0)
import math
if any(m["score"] == 0 for m in metrics):
    overall = 0
else:
    overall = round(math.exp(sum(m["weight"] * math.log(max(m["score"], 1)) for m in metrics)))

def label(s):
    if s >= 90: return "WIDE AWAKE"
    if s >= 70: return "HEALTHY"
    if s >= 50: return "DROWSY"
    if s >= 30: return "LIGHT SLEEPER"
    if s >= 10: return "DEEP SLEEPER"
    return "COMATOSE"

last_active_days_ago = None
if last_active_block is not None:
    last_active_days_ago = round((current_block - last_active_block) * BLOCK_TIME_SEC / 86400, 1)

result = {
    "wallet": WALLET,
    "current_block": current_block,
    "last_active_block": last_active_block,
    "last_active_days_ago": last_active_days_ago,
    "lifetime_txs": lifetime_txs,
    "overall_score": overall,
    "label": label(overall),
    "metrics": metrics,
}
print(json.dumps(result))
PYEOF
)

# -------------------- render --------------------
EXPLORER_LINK="$EXPLORER/address/$WALLET"
echo "$REPORT_JSON" | python3 "$SCRIPT_DIR/_render.py" \
  "wallet=$WALLET" \
  "network=$NETWORK" \
  "chain_id=$CHAIN_ID" \
  "net_label=$NET_LABEL" \
  "explorer_link=$EXPLORER_LINK" \
  "format=$FORMAT"
