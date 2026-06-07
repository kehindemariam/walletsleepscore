# Metrics spec

Detailed specification for each of the 7 metrics. If you've read `scoring.md`, you have the formulas. This document covers the **implementation details**: what data to fetch, how to handle edge cases, and what the metric does and does NOT tell you.

## 1. Recency

**Data needed:** current block height, last-active block of the wallet.

**How to find last-active block (in order of preference):**

1. `eth_getTransactionCount(wallet, "latest")` — if 0, recency = 0.
2. `eth_getTransactionCount(wallet, "earliest")` — if 0, recency = 0.
3. Bounded binary search: starting at the latest block, halve the search range until the last-active block is found. Use `eth_getBlockTransactionCountByNumber` to skip empty blocks quickly. Bound the search with `--max-blocks`.

**Edge cases:**
- Wallet created this block and already has a tx: recency = 100.
- Wallet exists but has never sent a tx (only received): recency = 0.
- Last-active block is before the chain's genesis (shouldn't happen but defensive): recency = 0.

**What it does NOT tell you:** the *type* of recent activity. A wallet that just bridged 10 PROS in is not the same as a wallet that just made 50 contract calls. Use Frequency + Diversity for that.

## 2. Frequency

**Data needed:** lifetime outbound tx count, wallet age in days.

**How to compute wallet age:**
- Best: timestamp of the wallet's first outbound tx.
- Approximation: `current_block - first_outbound_block`.

**Edge cases:**
- New wallet (created in the last hour): frequency = 100.
- Wallet with 0 lifetime txs: frequency = 0.
- Wallet with 1 tx in 365 days: frequency = 0.019, score = 0 (saturates low).

**What it does NOT tell you:** the bursty vs steady nature of activity. A wallet that made 100 txs in one day and then went silent looks the same as a wallet making 1 tx per day for 100 days. Both score 100 on frequency.

## 3. Gas efficiency

**Data needed:** recent gas-price distribution + the wallet's own gas-price usage.

**How to sample:**
- Look at the last N blocks (default 200).
- For each block, get all txs via `eth_getBlockByNumber(block, true)`.
- Collect `(gasPrice, from)` tuples.
- Compute network median gas-price (all txs) and wallet median gas-price (wallet's txs only).

**Edge cases:**
- Wallet has no txs in the last N blocks: gas efficiency = 50 (neutral).
- Network is empty (no recent txs): gas efficiency = 50.
- Wallet's only recent txs are type-0 (legacy) and the network is type-2 (EIP-1559): comparison still valid (we use the effective gas-price which is comparable).

**What it does NOT tell you:** whether the wallet is OVER-paying due to slippage on a DEX (you'd need trade-decoding for that).

## 4. Dust ratio

**Data needed:** the wallet's UTXO set and current native balance.

**How to get UTXOs:** this is the hard part. Pharos is EVM, so there are no UTXOs in the Bitcoin sense. **Approximation:** use `eth_getBalance` for native balance + scan recent inbound txs to estimate UTXO count. Or: just call this metric a "dust penalty" that triggers on:
- `native_balance < 0.001` AND `lifetime_txs > 50` → dust ratio = 50.
- `native_balance >= 0.001` → dust ratio = 0.

This is a **simplification**. A real implementation would require an indexer (Blockscout, TheGraph, etc.) to enumerate all ERC-20 balances per wallet. For an RPC-only tool, this approximation is good enough.

**What it does NOT tell you:** ERC-20 dust (a wallet with 50 empty ERC-20 token positions will not show as "dusty" under this metric).

## 5. Interaction diversity

**Data needed:** the wallet's last 30 days of outbound txs.

**How to get them:** sample the last 7200 blocks (~1 day on Pharos, which has ~2s blocks) and collect all txs FROM the wallet. For the 30-day window, scan the last 216,000 blocks.

**Edge cases:**
- Wallet has 0 txs in the last 30 days: diversity = 0.
- Wallet has only 1 unique counterparty in 30 days: diversity = 10.

**What it does NOT tell you:** the *type* of counterparties. A wallet sending to 100 different addresses once each looks the same as a wallet sending to 5 different contracts 20 times each.

## 6. Contract exposure

**Data needed:** the wallet's lifetime txs, with `to` address + bytecode size of the `to` address at the time of the tx.

**How to detect contract calls:** `eth_getCode(to, "latest")` returns non-empty bytecode → it's a contract. (For historical accuracy you'd need archive-node access, but for the score we use latest — this is a minor approximation.)

**Edge cases:**
- All txs are to a single contract (e.g. an L2 bridge): exposure = 100 → 28 (suspicious for being 100%).
- All txs are to EOAs: exposure = 0% → 28 (suspicious for being 0%).
- Sweet spot: 60-80% contract txs, with 20-40% P2P.

**What it does NOT tell you:** whether the contracts are well-known and trusted. A wallet that interacts only with phishing contracts scores the same as one that interacts only with Uniswap.

## 7. Balance activity

**Data needed:** sum of `(gas_used * gas_price)` over all lifetime outbound txs, current native balance.

**How to compute lifetime gas-spent:** for each outbound tx, fetch the receipt via `eth_getTransactionReceipt` and multiply `gasUsed` by the tx's `gasPrice` (or effective gas price for type-2 txs). Sum.

**Edge cases:**
- Wallet has 0 outbound txs: balance activity = 0.
- Wallet has current balance of 0: balance activity = 100 (they've spent everything).
- Wallet has lifetime gas > current balance: balance activity = 100.

**What it does NOT tell you:** the *source* of the wallet's funds. A wallet that received 100 PROS from a CEX and spent 5 PROS in gas scores the same as a wallet that earned 5 PROS in mining rewards and spent all of it.

## What the score does NOT do

- **Not a sybil detector.** A bot wallet can have a high score; a legitimate user with cold storage can have a low score.
- **Not a credit score.** No valuation, no risk of default, no payment history.
- **Not an identity check.** No ENS resolution, no KYC, no social signals.
- **Not a security audit.** This scores the wallet's *behavior*, not the *security* of the contracts it interacts with.
- **Not a portfolio analyzer.** No token balances, no NFT holdings, no LP positions.

The score is one number. Use it as a triage signal, not a verdict.
