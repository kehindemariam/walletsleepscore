# Scoring formulas

This document specifies the exact formulas for each of the 7 metrics used by `walletsleepscore`. All scores are 0-100 (integer, no decimals).

## 1. Recency (weight 25%)

```
days_since_last_tx = (current_block - last_active_block) * BLOCK_TIME_SECONDS / 86400
score = max(0, 100 - days_since_last_tx * 0.27)        # linear decay
       # <7 days  -> 100
       # 30 days  -> 92
       # 90 days  -> 76
       # 180 days -> 51
       # 365 days -> 1
       # 730 days -> 0
```

If the wallet has **never sent a transaction** (lifetime nonce = 0), recency = 0.

## 2. Frequency (weight 15%)

```
txs_per_week = lifetime_txs * 7 / wallet_age_days
score = min(100, txs_per_week * 20)                    # linear ramp
       # 0.1 tx/wk -> 2
       # 0.5 tx/wk -> 10
       # 1 tx/wk   -> 20
       # 5 tx/wk   -> 100 (saturates)
```

If wallet_age_days = 0 (created this block), frequency = 100.

## 3. Gas efficiency (weight 10%)

```
sample recent 200 blocks, collect gas-price percentiles
network_median_gas = median over all txs in the sample
wallet_median_gas  = median over the wallet's outbound txs in the sample
percentile = wallet_median_gas / network_median_gas       # 0.5 = cheap, 2.0 = expensive
score = max(0, 100 - max(0, percentile - 0.25) * 200)    # anything <= 25th pct = 100
       # 0.25 -> 100
       # 0.5  -> 80
       # 0.75 -> 60
       # 1.0  -> 40
       # 1.5  -> 10
       # 2.0+ -> 0
```

If the wallet has no recent txs, gas efficiency = 50 (neutral).

## 4. Dust ratio (weight 10%)

```
dust_utxos = count of UTXOs with value < 0.001 native token (PROS on mainnet, PHRS on testnet)
total_utxos = total UTXO count
ratio = dust_utxos / total_utxos
score = max(0, 100 - ratio * 200)                         # linear penalty
       # 0%   -> 100
       # 25%  -> 50
       # 50%+ -> 0
```

If total_utxos = 0, dust ratio = 100 (no UTXOs is technically "no dust" — score = 100).

## 5. Interaction diversity (weight 15%)

```
distinct_counterparties = number of unique addresses this wallet has sent txs to (or received from) in the last 30 days
counterparties_per_month = distinct_counterparties
score = min(100, counterparties_per_month * 10)           # linear ramp
       # 1    -> 10
       # 5    -> 50
       # 10+  -> 100 (saturates)
```

If the wallet has no recent txs, diversity = 0.

## 6. Contract exposure (weight 10%)

```
contract_txs = count of txs where `to` is an address with non-empty bytecode at the time of the tx
total_txs    = total txs in the sample
ratio = contract_txs / total_txs
# U-shaped scoring: 0% (pure EOA) and 100% (pure contract) are both suspicious
# Sweet spot: 60-80% (mixes E2E and contract interactions)
score = 100 - 4 * |ratio - 0.7| * 100                     # peak at 70%
       # 0%   -> 28
       # 50%  -> 80
       # 70%  -> 100
       # 80%  -> 80
       # 100% -> 28
```

If total_txs = 0, contract exposure = 50 (neutral).

## 7. Balance activity (weight 15%)

```
lifetime_gas_spent = sum of (gas_used * gas_price) over all lifetime outbound txs
current_balance    = current native token balance
ratio = lifetime_gas_spent / max(current_balance, 1e-9)
score = min(100, max(0, ratio * 500))                     # 0.2% balance = 100
       # 0.05% -> 25
       # 0.1%  -> 50
       # 0.2%+ -> 100
```

If lifetime_gas_spent = 0, balance activity = 0.

## Overall score (weighted geometric mean)

```
weights = [0.25, 0.15, 0.10, 0.10, 0.15, 0.10, 0.15]    # sum = 1.0
log_score = sum(w * log(max(score_i, 1)) for w, score_i in zip(weights, scores))
overall = round(exp(log_score))
```

**Why geometric mean, not arithmetic?** A wallet with 6/7 perfect metrics but 1 metric at 0 should NOT get a "passing" score. Geometric mean makes any 0 metric tank the overall.

If a metric score is 0, the overall is forced to 0 (mathematically).

## Worked example

Wallet:
- Last tx: 3 days ago
- Lifetime txs: 247
- Wallet age: 580 days
- Median gas: 0.5× network median
- Dust UTXOs: 0 of 23
- Distinct counterparties (last 30d): 7
- Contract txs: 65% of 247
- Lifetime gas spent: 0.8 PROS
- Current balance: 10 PROS

| Metric | Raw | Score | Weight | Contribution |
|---|---:|---:|---:|---:|
| Recency | 3 days | 99 | 0.25 | 0.25 × log(99) = 1.144 |
| Frequency | 0.30 txs/wk | 6 | 0.15 | 0.15 × log(6) = 0.269 |
| Gas efficiency | 0.5× | 80 | 0.10 | 0.10 × log(80) = 0.447 |
| Dust ratio | 0% | 100 | 0.10 | 0.10 × log(100) = 0.461 |
| Diversity | 7 | 70 | 0.15 | 0.15 × log(70) = 0.643 |
| Contract exposure | 65% | 100 | 0.10 | 0.10 × log(100) = 0.461 |
| Balance activity | 8% | 40 | 0.15 | 0.15 × log(40) = 0.591 |

`log_score = 4.016` → `overall = exp(4.016) = 55.5 ≈ 56` → **DROWSY**

(The "DROWSY" label is driven by the low frequency — only 0.3 txs/week, which is normal for a "set and forget" wallet but suggests limited active engagement.)
