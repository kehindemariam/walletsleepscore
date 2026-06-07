#!/usr/bin/env python3
"""
walletsleepscore/test_score.py — unit tests for the wallet scorer.
Run: python3 tests/test_score.py
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
from score import (
    score_label, compute_overall, compute_metrics, find_last_active_block,
    WEIGHTS, NETWORKS, DUST_THRESHOLD,
)  # noqa


# ============== tests ==============

def test_score_label_thresholds():
    """Score labels at exact threshold values."""
    assert score_label(100) == "WIDE AWAKE"
    assert score_label(95)  == "WIDE AWAKE"
    assert score_label(90)  == "WIDE AWAKE"
    assert score_label(89)  == "HEALTHY"
    assert score_label(70)  == "HEALTHY"
    assert score_label(69)  == "DROWSY"
    assert score_label(50)  == "DROWSY"
    assert score_label(49)  == "LIGHT SLEEPER"
    assert score_label(30)  == "LIGHT SLEEPER"
    assert score_label(29)  == "DEEP SLEEPER"
    assert score_label(10)  == "DEEP SLEEPER"
    assert score_label(9)   == "COMATOSE"
    assert score_label(0)   == "COMATOSE"
    print("  ✓ test_score_label_thresholds")


def test_overall_geometric_mean_all_100():
    """When all metrics are 100, the geometric mean is 100."""
    metrics = [{"id": i, "name": f"m{i}", "score": 100, "weight": WEIGHTS[i], "detail": ""} for i in range(1, 8)]
    assert compute_overall(metrics) == 100
    print("  ✓ test_overall_geometric_mean_all_100")


def test_overall_zero_metric_forces_zero():
    """If any metric is 0, the overall is 0 (geometric mean property)."""
    metrics = [{"id": i, "name": f"m{i}", "score": 100, "weight": WEIGHTS[i], "detail": ""} for i in range(1, 8)]
    metrics[3]["score"] = 0  # dust ratio = 0
    assert compute_overall(metrics) == 0
    print("  ✓ test_overall_zero_metric_forces_zero")


def test_overall_weights_sum_to_one():
    """The weights should sum to 1.0."""
    total = sum(WEIGHTS.values())
    assert abs(total - 1.0) < 1e-9, f"weights sum to {total}, expected 1.0"
    print("  ✓ test_overall_weights_sum_to_one")


def test_overall_realistic_mix():
    """A realistic mix of metric scores should produce a sensible overall."""
    metrics = [
        {"id": 1, "name": "Recency",       "score": 95, "weight": 0.25, "detail": ""},
        {"id": 2, "name": "Frequency",     "score": 70, "weight": 0.15, "detail": ""},
        {"id": 3, "name": "Gas efficiency","score": 60, "weight": 0.10, "detail": ""},
        {"id": 4, "name": "Dust ratio",    "score": 100,"weight": 0.10, "detail": ""},
        {"id": 5, "name": "Diversity",     "score": 80, "weight": 0.15, "detail": ""},
        {"id": 6, "name": "Contract exp",  "score": 75, "weight": 0.10, "detail": ""},
        {"id": 7, "name": "Balance act",   "score": 50, "weight": 0.15, "detail": ""},
    ]
    # Hand-computed: weighted log sum
    import math
    log_sum = sum(m["weight"] * math.log(m["score"]) for m in metrics)
    expected = round(math.exp(log_sum))
    actual = compute_overall(metrics)
    assert actual == expected
    # Should land in the "DROWSY" or "HEALTHY" range
    assert 50 <= actual <= 90, f"expected 50-90, got {actual}"
    print("  ✓ test_overall_realistic_mix")


def test_compute_metrics_never_sent_tx():
    """If the wallet has no lifetime txs, all metrics should be computable (some at 0)."""
    # We can't actually call RPCs in a unit test, so we mock the inputs
    metrics = compute_metrics(
        network="mainnet",
        address="0xtest",
        current_block=1000000,
        last_active_block=None,
        lifetime_txs=0,
        sample_blocks=[],
        balance=int(10 * 1e18),  # 10 PROS, no dust
    )
    assert len(metrics) == 7
    # Recency should be 0 (no txs)
    recency = next(m for m in metrics if m["id"] == 1)
    assert recency["score"] == 0
    # Frequency should be 0
    freq = next(m for m in metrics if m["id"] == 2)
    assert freq["score"] == 0
    print("  ✓ test_compute_metrics_never_sent_tx")


def test_compute_metrics_active_recently():
    """A wallet with a recent tx and high activity should score high on recency + frequency."""
    metrics = compute_metrics(
        network="mainnet",
        address="0xtest",
        current_block=1000000,
        last_active_block=999000,  # 1000 blocks ago
        lifetime_txs=100,
        sample_blocks=[],
        balance=int(10 * 1e18),  # 10 PROS
    )
    recency = next(m for m in metrics if m["id"] == 1)
    # 1000 blocks * 2s = 2000s = 0.023 days. Recency = 100 - 0.023*0.27 = ~99.99 -> round to 100
    assert recency["score"] >= 99
    freq = next(m for m in metrics if m["id"] == 2)
    # 100 txs / (1000 blocks * 2s / 86400) = 432 txs/day = ~3024 txs/week -> score = 100 (saturates)
    assert freq["score"] == 100
    print("  ✓ test_compute_metrics_active_recently")


def test_compute_metrics_old_wallet():
    """A wallet whose last tx is years ago should score low on recency."""
    # 365 days = 365 * 86400 / 2 = 15,768,000 blocks
    blocks_per_year = 365 * 86400 / 2
    metrics = compute_metrics(
        network="mainnet",
        address="0xtest",
        current_block=int(blocks_per_year * 2),  # current block
        last_active_block=int(blocks_per_year),  # 1 year ago
        lifetime_txs=10,
        sample_blocks=[],
        balance=int(10 * 1e18),  # 10 PROS
    )
    recency = next(m for m in metrics if m["id"] == 1)
    # 365 days * 0.27 = 98.55, so score ~ 1
    assert recency["score"] <= 5
    print("  ✓ test_compute_metrics_old_wallet")


def test_dust_ratio_logic():
    """Dust ratio: high lifetime txs + low balance = penalty; otherwise OK."""
    # We can test by calling compute_metrics with no sample blocks (so diversity etc. are neutral)
    # but lifetime_txs > 50 + balance < 0.001 (we'd need to mock get_balance)
    # For now, just test the constants and label logic
    assert DUST_THRESHOLD == 0.001
    print("  ✓ test_dust_ratio_logic")


def test_score_label_progression():
    """As score increases, label should progress from COMATOSE -> WIDE AWAKE."""
    labels = [score_label(s) for s in [0, 10, 30, 50, 70, 90, 100]]
    assert labels == ["COMATOSE", "DEEP SLEEPER", "LIGHT SLEEPER", "DROWSY", "HEALTHY", "WIDE AWAKE", "WIDE AWAKE"]
    print("  ✓ test_score_label_progression")


def test_score_label_boundaries():
    """Test exact boundary values for the score labels."""
    assert score_label(89) == "HEALTHY"  # 89 is the highest "HEALTHY"
    assert score_label(90) == "WIDE AWAKE"  # 90 is the lowest "WIDE AWAKE"
    assert score_label(69) == "DROWSY"  # 69 is the highest "DROWSY"
    assert score_label(70) == "HEALTHY"  # 70 is the lowest "HEALTHY"
    assert score_label(49) == "LIGHT SLEEPER"
    assert score_label(50) == "DROWSY"
    print("  ✓ test_score_label_boundaries")


# ----- runner -----

if __name__ == "__main__":
    tests = [
        test_score_label_thresholds,
        test_overall_geometric_mean_all_100,
        test_overall_zero_metric_forces_zero,
        test_overall_weights_sum_to_one,
        test_overall_realistic_mix,
        test_compute_metrics_never_sent_tx,
        test_compute_metrics_active_recently,
        test_compute_metrics_old_wallet,
        test_dust_ratio_logic,
        test_score_label_progression,
        test_score_label_boundaries,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {t.__name__} — {e}")
        except Exception as e:
            failed += 1
            print(f"  ✗ {t.__name__} — EXCEPTION: {e}")
    print(f"\n{len(tests) - failed} test(s) passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
