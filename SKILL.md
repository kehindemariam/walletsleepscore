---
name: walletsleepscore
description: Scores a Pharos wallet's "sleep hygiene" on a 0-100 scale by analyzing its on-chain activity. Given a wallet address, walletsleepscore fetches the transaction history via Pharos RPC, computes activity metrics (last-active timestamp, transaction frequency, gas-efficiency, dust ratio, interaction diversity, contract exposure, ETH/PROS holding ratio vs activity), and returns a single numeric score plus a per-metric breakdown. Use whenever the user asks "how healthy is this wallet?", "is this wallet active?", "compute sleep score", "rate this address", or provides a Pharos wallet address to review.
version: 1.0.0
author: kehindemariam
tags: [pharos, wallet, score, analytics, hygiene, activity, evm, mainnet, testnet]
agents: [claude, codex, openclaw, gemini]
---

# walletsleepscore — Wallet Sleep Score

You are a wallet-activity scorer for the Pharos network (Atlantic Testnet and Pacific Ocean Mainnet). Given any wallet address, you compute a 0-100 "sleep score" describing how active, diverse, and gas-efficient the wallet is.

## When to use

Trigger this skill when the user:

- pastes a Pharos wallet address and asks "is this wallet healthy/active?"
- asks for a "sleep score" or "activity score" or "hygiene rating" for an address
- wants to triage a list of wallets (e.g. "score these 10 addresses")
- asks "is this wallet a sybil?", "is this wallet a bot?", "is this wallet active?"

Do NOT use this skill for:

- Smart-contract code analysis (use reepatts, eip712dsa, eip2612pa for that)
- Real-time transaction broadcasting (this skill is read-only)
- Token-price or portfolio valuation (not what this scores)
- KYC/AML identity scoring (this is purely on-chain behavior)

## Network details

- **Atlantic Testnet** (default): chain ID `688689`, native `PHRS`, RPC `https://atlantic.dplabs-internal.com`, explorer `https://atlantic.pharosscan.xyz`
- **Pacific Mainnet**: chain ID `1672`, native `PROS`, RPC `https://rpc.pharos.xyz`, explorer `https://www.pharosscan.xyz`

Read both from `references/networks.json` so URLs and chain IDs never go stale.

## What walletsleepscore measures

A wallet's "sleep hygiene" is broken into **7 metrics**, each scored 0-100, then combined into a single overall score. The metrics are designed to be **fast to compute** (no third-party API calls beyond the Pharos RPC) and **interpretable** (each metric is independent and well-defined).

| # | Metric | What it measures | Weight |
|---|---|---|---:|
| 1 | **Recency** | Days since last outbound tx. <7d=100, >365d=0 | 25% |
| 2 | **Frequency** | Outbound txs per week, averaged over the wallet's lifetime. >5/wk=100, <0.1/wk=0 | 15% |
| 3 | **Gas efficiency** | Median gas-price percentile vs network median. <25th pct=100, >90th pct=0 | 10% |
| 4 | **Dust ratio** | % of UTXOs that are dust (< 0.001 native). 0%=100, >50%=0 | 10% |
| 5 | **Interaction diversity** | Number of distinct counterparties / month. >10=100, <0.5=0 | 15% |
| 6 | **Contract exposure** | % of txs that interact with verified contracts (vs plain EOAs). 60-80%=100, 0% or 100%=0 | 10% |
| 7 | **Balance activity** | Lifetime gas-spent as % of current balance. >20%=100, <0.1%=0 | 15% |

The overall score is a **weighted geometric mean** of the 7 metric scores (so any one metric at 0 forces the overall down).

## Score interpretation

| Score | Label | What it means |
|---:|---|---|
| 90-100 | **WIDE AWAKE** | Active, diverse, gas-efficient — well-used wallet |
| 70-89 | **HEALTHY** | Normal active wallet, no major red flags |
| 50-69 | **DROWSY** | Used, but with some concerning patterns (high dust, low diversity, etc.) |
| 30-49 | **LIGHT SLEEPER** | Long inactive periods or single-purpose use |
| 10-29 | **DEEP SLEEPER** | Inactive for months, OR very gas-inefficient, OR single-purpose |
| 0-9 | **COMATOSE** | No activity for 1+ years, OR all metrics at 0 |

The score is **not a sybil detector** — a high score does not mean "legitimate user", and a low score does not mean "bot". It only measures on-chain behavior patterns.

## How to run it

### CLI (zero-deps: bash + curl only)

```bash
bash scripts/score.sh 0xWALLET --network mainnet
bash scripts/score.sh 0xWALLET --network testnet --format json   # machine-readable
bash scripts/score.sh 0xWALLET --network mainnet --max-blocks 5000 --txs 200   # bounded scan
```

### Python (richer output, full metric breakdown)

```bash
pip install web3
python3 scripts/score.py 0xWALLET --network mainnet --format md
```

Both scripts:
1. Fetch the current block number (for "age of last tx" calc)
2. Fetch the transaction count via `eth_getTransactionCount` (cheap)
3. Bounded binary search to find the last-active block (using `eth_getBlockByNumber` + `eth_getBlockTransactionCountByNumber` + `eth_getTransactionByBlockNonceAndIndex`)
4. Sample recent blocks to estimate gas efficiency + interaction diversity
5. Compute all 7 metrics
6. Render the score + breakdown

**Note:** Step 3 uses a binary-search-with-skip approach. For very old wallets (last tx > 1M blocks ago) the scan can be slow; use `--max-blocks 5000` to bound the work.

## Output format

### Markdown (default, for human review)

```markdown
# walletsleepscore — Wallet activity report

**Wallet:** 0x... (or ENS name if available)
**Network:** Pharos Pacific Ocean Mainnet (chain 1672)
**Current block:** 9,553,061
**Last active:** block 9,540,012 (3 days ago)
**Lifetime txs:** 247 outbound

## Overall score: 78 / 100 (HEALTHY)

## Metrics (7)

| # | Metric | Score | Detail |
|---|---|---:|---|
| 1 | Recency | 95 | last tx 3 days ago |
| 2 | Frequency | 70 | 0.8 txs/week lifetime average |
| 3 | Gas efficiency | 60 | median gas-price 65th percentile of network |
| 4 | Dust ratio | 100 | no dust UTXOs detected |
| 5 | Interaction diversity | 80 | 7.2 distinct counterparties/month |
| 6 | Contract exposure | 75 | 65% of txs are contract calls |
| 7 | Balance activity | 50 | lifetime gas = 8% of current balance |

## Interpretation

This is a **HEALTHY** wallet. Active recently, decent diversity, no major red flags. The "Balance activity" metric is mid-range — the wallet has spent a moderate amount of gas relative to its current balance, suggesting it's not a one-shot wallet.

---
Generated by [walletsleepscore](https://github.com/kehindemariam/walletsleepscore) on Pharos Pacific Ocean Mainnet.
```

### JSON (for downstream tooling)

```json
{
  "wallet": "0x...",
  "network": "mainnet",
  "current_block": 9553061,
  "last_active_block": 9540012,
  "last_active_days_ago": 3.0,
  "lifetime_txs": 247,
  "overall_score": 78,
  "label": "HEALTHY",
  "metrics": [
    { "id": 1, "name": "Recency", "score": 95, "weight": 0.25, "detail": "last tx 3 days ago" },
    ...
  ]
}
```

## Safety reminders

- The skill is **read-only** — no private key required, no transactions are signed or sent.
- For very old wallets, the bounded scan can miss the last-active block; the result will be reported as "inconclusive" with the maximum-scan hint.

## References

- `references/networks.json` — canonical Pharos network config
- `references/scoring.md` — the scoring formulas, with worked examples
- `references/metrics.md` — detailed spec for each of the 7 metrics
- `examples/sample-report.md` — what a real score looks like
