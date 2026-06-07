#!/usr/bin/env python3
"""
walletsleepscore/score.py — Wallet sleep-score for Pharos.
Run on Pharos Atlantic Testnet or Pacific Mainnet.

Usage:
  python3 scripts/score.py 0xWALLET [--network mainnet|atlantic-testnet] [--format md|json|txt]
                              [--max-blocks 5000] [--txs 200] [--demo]
  python3 scripts/score.py --help

Requires: pip install web3 (not actually used; we use urllib for portability)
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.request
from collections import Counter

NETWORKS = {
    "mainnet": {
        "chainId": 1672,
        "rpcUrl": "https://rpc.pharos.xyz",
        "displayName": "Pharos Pacific Ocean Mainnet",
        "explorer": "https://www.pharosscan.xyz",
        "blockTimeSec": 2.0,
    },
    "atlantic-testnet": {
        "chainId": 688689,
        "rpcUrl": "https://atlantic.dplabs-internal.com",
        "displayName": "Pharos Atlantic Testnet",
        "explorer": "https://atlantic.pharosscan.xyz",
        "blockTimeSec": 2.0,
    },
}

# Metric weights
WEIGHTS = {
    1: 0.25,  # Recency
    2: 0.15,  # Frequency
    3: 0.10,  # Gas efficiency
    4: 0.10,  # Dust ratio
    5: 0.15,  # Interaction diversity
    6: 0.10,  # Contract exposure
    7: 0.15,  # Balance activity
}

DUST_THRESHOLD = 0.001  # native tokens


def rpc(url, method, params, _id=[1], retries=3):
    """Make a JSON-RPC call to the Pharos RPC."""
    _id[0] += 1
    payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": _id[0]}).encode()
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
            if "error" in data:
                raise RuntimeError(f"RPC error: {data['error']}")
            return data.get("result")
        except Exception as e:
            last_err = e
    raise RuntimeError(f"RPC {method} failed after {retries} attempts: {last_err}")


def get_block_number(network):
    h = rpc(NETWORKS[network]["rpcUrl"], "eth_blockNumber", [])
    return int(h, 16)


def get_tx_count(network, address, tag="latest"):
    n = rpc(NETWORKS[network]["rpcUrl"], "eth_getTransactionCount", [address, tag])
    return int(n, 16)


def get_balance(network, address):
    b = rpc(NETWORKS[network]["rpcUrl"], "eth_getBalance", [address, "latest"])
    return int(b, 16)


def get_block(network, block_num, full_txs=False):
    h = hex(block_num)
    return rpc(NETWORKS[network]["rpcUrl"], "eth_getBlockByNumber", [h, full_txs])


def get_tx_count_in_block(network, block_num):
    h = hex(block_num)
    n = rpc(NETWORKS[network]["rpcUrl"], "eth_getBlockTransactionCountByNumber", [h])
    return int(n, 16)


def get_logs_for_address(network, address, from_block, to_block):
    """Use eth_getLogs to find all txs FROM the given address in a block range.
    Much faster than per-block scan for the last-active-block lookup.
    """
    # Topic: keccak256("TransactionExecuted(address,uint256,uint256)") is NOT a real topic.
    # Instead, we use the from-address field of the filter object.
    # The filter format: {"fromBlock": "0x...", "toBlock": "0x...", "address": null, "topics": null, "from": [address]}
    # But standard JSON-RPC doesn't support `from` filter directly. We use the `address` field with the wallet itself.
    # However, we want txs where `from == wallet`, not `to == wallet`.
    # Workaround: query logs for all txs in the range, then filter.
    # That's too expensive. Instead, we use the standard approach:
    # `from` filter is supported in some RPCs (EIP-234), not all.
    # We use a hybrid: query the most recent blocks via getLogs, then for each log, fetch the receipt and check `from`.
    # Actually the simplest fast approach: use the wallet's nonce to binary-search for the last-active block.
    return []  # Not used; binary search below is the fallback.


def find_last_active_block_binary(network, address, current_block, max_scan_blocks=10000):
    """Find the most recent block where the address sent a tx using a binary-search-like approach.
    Strategy: nonce at 'latest' = N. nonce at block B = M means there are M txs from the wallet up to and including block B.
    We want the highest block where nonce = current_nonce (i.e. the most recent tx).
    """
    nonce_latest = get_tx_count(network, address, "latest")
    if nonce_latest == 0:
        return None
    if nonce_latest == 1:
        # Only one tx ever — binary search
        return _binary_search_single_tx(network, address, current_block, max_scan_blocks)

    # Multi-tx: find the highest block where nonce_at_block == nonce_latest
    # Use getTransactionByBlockNonceAndIndex (no, that doesn't exist). Instead, walk backward
    # with getBlockTransactionCountByNumber but skip empty blocks.
    # Optimization: get a recent range of blocks in parallel (sequential is fine for the demo).
    block = current_block
    for _ in range(max_scan_blocks):
        if block <= 0: break
        # Use a single getBlockByNumber call (with full_txs=False) to check tx count efficiently
        try:
            h = hex(block)
            data = rpc(NETWORKS[network]["rpcUrl"], "eth_getBlockByNumber", [h, False])
            txs_in_block = int(data.get("transactions", []).__len__() if isinstance(data.get("transactions"), list) else int(data.get("transactions", "0x0"), 16), 16) if data.get("transactions") else 0
        except Exception:
            block -= 1
            continue
        if txs_in_block > 0:
            # Get the full block to check `from`
            try:
                full = rpc(NETWORKS[network]["rpcUrl"], "eth_getBlockByNumber", [h, True])
                for tx in full.get("transactions", []):
                    if tx.get("from", "").lower() == address.lower():
                        return block
            except Exception:
                pass
        block -= 1
    return None


def _binary_search_single_tx(network, address, current_block, max_scan_blocks):
    """Binary search for the single-tx case: find the only block containing a tx from this address."""
    lo, hi = 0, current_block
    nonce_target = 1
    for _ in range(max_scan_blocks // 2):
        if lo >= hi: break
        mid = (lo + hi) // 2
        try:
            nonce_at = get_tx_count(network, address, hex(mid))
        except Exception:
            hi = mid - 1
            continue
        if nonce_at >= nonce_target:
            hi = mid
        else:
            lo = mid + 1
    return lo if lo <= current_block else None


# Backwards-compat alias
find_last_active_block = find_last_active_block_binary


def sample_recent_blocks(network, current_block, num_blocks=200):
    """Return a list of recent blocks (up to num_blocks) with full tx data."""
    blocks = []
    start = max(0, current_block - num_blocks + 1)
    for b in range(current_block, start - 1, -1):
        try:
            blocks.append(get_block(network, b, full_txs=True))
        except Exception:
            continue
    return blocks


def compute_metrics(network, address, current_block, last_active_block, lifetime_txs, sample_blocks, balance=None):
    """Compute the 7 metrics. Returns a list of dicts: {id, name, score, weight, detail}."""
    block_time_sec = NETWORKS[network]["blockTimeSec"]
    metrics = []

    # ---- 1. Recency ----
    if last_active_block is None or last_active_block == 0:
        recency_score = 0
        recency_detail = "wallet has never sent a tx"
    else:
        blocks_since = current_block - last_active_block
        days_since = blocks_since * block_time_sec / 86400
        recency_score = max(0, round(100 - days_since * 0.27))
        recency_detail = f"last tx {round(days_since, 1)} days ago (block {last_active_block})"
    metrics.append({
        "id": 1, "name": "Recency", "score": recency_score, "weight": WEIGHTS[1],
        "detail": recency_detail,
    })

    # ---- 2. Frequency ----
    if lifetime_txs == 0:
        freq_score = 0
        freq_detail = "no lifetime txs"
    elif last_active_block is None or last_active_block == current_block:
        # New wallet
        freq_score = 100
        freq_detail = "new wallet (created this block)"
    else:
        wallet_age_days = (current_block - last_active_block) * block_time_sec / 86400
        # We don't know the FIRST block exactly, so use last_active_block as a lower bound
        wallet_age_days = max(wallet_age_days, 1)  # at least 1 day
        txs_per_week = lifetime_txs * 7 / max(wallet_age_days, 1)
        freq_score = min(100, round(txs_per_week * 20))
        freq_detail = f"{round(txs_per_week, 2)} txs/week (lifetime average)"
    metrics.append({
        "id": 2, "name": "Frequency", "score": freq_score, "weight": WEIGHTS[2],
        "detail": freq_detail,
    })

    # ---- 3. Gas efficiency ----
    network_gas_prices = []
    wallet_gas_prices = []
    for blk in sample_blocks:
        for tx in blk.get("transactions", []):
            gp = int(tx.get("gasPrice", "0x0"), 16)
            if gp == 0: continue
            network_gas_prices.append(gp)
            if tx.get("from", "").lower() == address.lower():
                wallet_gas_prices.append(gp)
    if not wallet_gas_prices:
        gas_score = 50
        gas_detail = "no recent txs to evaluate"
    elif not network_gas_prices:
        gas_score = 50
        gas_detail = "no network txs in sample"
    else:
        net_med = sorted(network_gas_prices)[len(network_gas_prices) // 2]
        wal_med = sorted(wallet_gas_prices)[len(wallet_gas_prices) // 2]
        pct = wal_med / max(net_med, 1)
        gas_score = max(0, round(100 - max(0, pct - 0.25) * 200))
        gas_detail = f"median gas-price {round(pct * 100)}% of network median"
    metrics.append({
        "id": 3, "name": "Gas efficiency", "score": gas_score, "weight": WEIGHTS[3],
        "detail": gas_detail,
    })

    # ---- 4. Dust ratio (simplified for RPC-only) ----
    if balance is None:
        balance = get_balance(network, address)
    balance_native = balance / 1e18
    if lifetime_txs > 50 and balance_native < DUST_THRESHOLD:
        dust_score = 50
        dust_detail = f"low balance ({round(balance_native, 4)} native) + {lifetime_txs} lifetime txs"
    else:
        dust_score = 100
        dust_detail = f"balance {round(balance_native, 4)} native, no dust detected"
    metrics.append({
        "id": 4, "name": "Dust ratio", "score": dust_score, "weight": WEIGHTS[4],
        "detail": dust_detail,
    })

    # ---- 5. Interaction diversity ----
    counterparties = set()
    for blk in sample_blocks:
        for tx in blk.get("transactions", []):
            if tx.get("from", "").lower() == address.lower():
                to = tx.get("to", "")
                if to and to != "0x" + "0" * 40:
                    counterparties.add(to.lower())
    if not counterparties:
        div_score = 0
        div_detail = "no recent txs to evaluate"
    else:
        div_score = min(100, round(len(counterparties) * 10))
        div_detail = f"{len(counterparties)} distinct counterparties in last {len(sample_blocks)} blocks"
    metrics.append({
        "id": 5, "name": "Interaction diversity", "score": div_score, "weight": WEIGHTS[5],
        "detail": div_detail,
    })

    # ---- 6. Contract exposure ----
    total_wallet_txs = 0
    contract_txs = 0
    for blk in sample_blocks:
        for tx in blk.get("transactions", []):
            if tx.get("from", "").lower() == address.lower():
                total_wallet_txs += 1
                to = tx.get("to", "")
                if to and to != "0x" + "0" * 40:
                    try:
                        code = rpc(NETWORKS[network]["rpcUrl"], "eth_getCode", [to, "latest"])
                        if code and code != "0x" and len(code) > 2:
                            contract_txs += 1
                    except Exception:
                        pass
    if total_wallet_txs == 0:
        ce_score = 50
        ce_detail = "no recent txs to evaluate"
    else:
        ratio = contract_txs / total_wallet_txs
        ce_score = max(0, round(100 - 4 * abs(ratio - 0.7) * 100))
        ce_detail = f"{round(ratio * 100)}% of {total_wallet_txs} recent txs are contract calls"
    metrics.append({
        "id": 6, "name": "Contract exposure", "score": ce_score, "weight": WEIGHTS[6],
        "detail": ce_detail,
    })

    # ---- 7. Balance activity (RPC-friendly approximation) ----
    # Without archive-node access, estimate lifetime gas-spent by sampling recent receipts.
    # This is a rough proxy; full accuracy requires an indexer.
    sample_gas_spent = 0
    for blk in sample_blocks:
        for tx in blk.get("transactions", []):
            if tx.get("from", "").lower() == address.lower():
                gp = int(tx.get("gasPrice", "0x0"), 16)
                # We don't have gasUsed without a receipt fetch; estimate with tx gas limit
                gas_limit = int(tx.get("gas", "0x0"), 16)
                sample_gas_spent += gp * (gas_limit // 2)  # rough estimate
    balance_activity_ratio = sample_gas_spent / max(balance, 1)
    ba_score = min(100, max(0, round(balance_activity_ratio * 500)))
    ba_detail = f"sample gas ~{round(balance_activity_ratio * 100, 2)}% of balance (rough)"
    metrics.append({
        "id": 7, "name": "Balance activity", "score": ba_score, "weight": WEIGHTS[7],
        "detail": ba_detail,
    })

    return metrics


def compute_overall(metrics):
    """Weighted geometric mean. Any 0 forces overall = 0."""
    if any(m["score"] == 0 for m in metrics):
        return 0
    log_score = sum(m["weight"] * math.log(max(m["score"], 1)) for m in metrics)
    return round(math.exp(log_score))


def score_label(s):
    if s >= 90: return "WIDE AWAKE"
    if s >= 70: return "HEALTHY"
    if s >= 50: return "DROWSY"
    if s >= 30: return "LIGHT SLEEPER"
    if s >= 10: return "DEEP SLEEPER"
    return "COMATOSE"


def render(data, fmt):
    if fmt == "json":
        return json.dumps(data, indent=2)
    if fmt == "txt":
        out = []
        out.append("walletsleepscore — Wallet activity report")
        out.append(f"  Wallet:        {data['wallet']}")
        out.append(f"  Network:       {data.get('net_label', '?')}")
        out.append(f"  Current block: {data['current_block']:,}")
        out.append(f"  Last active:   block {data.get('last_active_block', 'none')}")
        out.append(f"  Lifetime txs:  {data['lifetime_txs']}")
        out.append("")
        out.append(f"  Overall:       {data['overall_score']} / 100 ({data['label']})")
        out.append("")
        for m in data["metrics"]:
            out.append(f"  #{m['id']} {m['name']:24s} {m['score']:3d}/100  (w={m['weight']})  {m['detail']}")
        out.append("")
        out.append(f"  generated: {data.get('generated_at', '?')}")
        return "\n".join(out)
    # md
    out = []
    out.append("# walletsleepscore — Wallet activity report")
    out.append("")
    out.append(f"**Wallet:** [{data['wallet']}]({data.get('explorer_link', '#')})")
    out.append(f"**Network:** {data.get('net_label', '?')}")
    out.append(f"**Current block:** {data['current_block']:,}")
    out.append(f"**Last active:** {'block ' + str(data['last_active_block']) + ' (' + str(data.get('last_active_days_ago', '?')) + ' days ago)' if data.get('last_active_block') else 'never'}")
    out.append(f"**Lifetime txs:** {data['lifetime_txs']} outbound")
    out.append("")
    out.append(f"## Overall score: {data['overall_score']} / 100 ({data['label']})")
    out.append("")
    out.append(f"## Metrics ({len(data['metrics'])})")
    out.append("")
    out.append("| # | Metric | Score | Weight | Detail |")
    out.append("|---|---|---:|---:|---|")
    for m in data["metrics"]:
        out.append(f"| {m['id']} | {m['name']} | {m['score']} | {m['weight']} | {m['detail']} |")
    out.append("")
    out.append("---")
    out.append("")
    out.append(f"Generated by [walletsleepscore](https://github.com/kehindemariam/walletsleepscore) on {data.get('net_label', 'Pharos')}.")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="walletsleepscore — Pharos wallet activity scorer")
    ap.add_argument("wallet", nargs="?", help="wallet address (0x...)")
    ap.add_argument("--network", default="atlantic-testnet", choices=list(NETWORKS.keys()))
    ap.add_argument("--format", default="md", choices=["md", "json", "txt"])
    ap.add_argument("--max-blocks", type=int, default=10000, help="max blocks to scan for last-active")
    ap.add_argument("--txs", type=int, default=200, help="recent blocks to sample for metrics")
    ap.add_argument("--demo", action="store_true", help="score a real public mainnet address")
    args = ap.parse_args()

    wallet = args.wallet
    if args.demo:
        # Use a known active Pharos mainnet address (very active, recent tx)
        wallet = "0x11d183a7a0922ddb37df5837dd0bf93e908ecd81"

    if not wallet:
        ap.print_help()
        sys.exit(1)

    wallet = wallet.lower()
    if not (wallet.startswith("0x") and len(wallet) == 42):
        print(f"ERROR: wallet must look like 0x + 40 hex chars, got: {wallet}", file=sys.stderr)
        sys.exit(2)

    net = NETWORKS[args.network]
    print(f"[walletsleepscore] fetching data for {wallet} on {net['displayName']}...", file=sys.stderr)

    current_block = get_block_number(args.network)
    print(f"[walletsleepscore] current block: {current_block}", file=sys.stderr)

    lifetime_txs = get_tx_count(args.network, wallet, "latest")
    print(f"[walletsleepscore] lifetime outbound txs: {lifetime_txs}", file=sys.stderr)

    if lifetime_txs > 0 and args.max_blocks > 0:
        print(f"[walletsleepscore] finding last-active block (max scan: {args.max_blocks})...", file=sys.stderr)
        last_active_block = find_last_active_block(args.network, wallet, current_block, max_scan_blocks=args.max_blocks)
        if last_active_block is None:
            print(f"[walletsleepscore] last-active block not found within {args.max_blocks} blocks (use --max-blocks N to scan more)", file=sys.stderr)
    else:
        last_active_block = None
        if args.max_blocks == 0:
            print(f"[walletsleepscore] --max-blocks 0: skipping last-active-block scan", file=sys.stderr)

    print(f"[walletsleepscore] sampling last {args.txs} blocks for metrics...", file=sys.stderr)
    sample = sample_recent_blocks(args.network, current_block, num_blocks=args.txs)

    metrics = compute_metrics(args.network, wallet, current_block, last_active_block, lifetime_txs, sample)
    overall = compute_overall(metrics)
    label = score_label(overall)

    # Days since last active
    last_active_days_ago = None
    if last_active_block is not None:
        last_active_days_ago = round((current_block - last_active_block) * net["blockTimeSec"] / 86400, 1)

    result = {
        "wallet": wallet,
        "network": args.network,
        "chain_id": net["chainId"],
        "net_label": net["displayName"],
        "explorer_link": f"{net['explorer']}/address/{wallet}",
        "current_block": current_block,
        "last_active_block": last_active_block,
        "last_active_days_ago": last_active_days_ago,
        "lifetime_txs": lifetime_txs,
        "overall_score": overall,
        "label": label,
        "metrics": metrics,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    print(render(result, args.format))


if __name__ == "__main__":
    main()
