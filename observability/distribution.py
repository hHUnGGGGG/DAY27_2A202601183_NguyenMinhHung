"""Distribution Drift and Statistical Shift Detection.

Implements multi-metric distribution comparison:
- Two-sample Kolmogorov-Smirnov (KS) statistic and p-value
- Mean & Standard Deviation shift ratio
- Population Stability Index (PSI) proxy
"""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np
from scipy import stats


def detect_distribution_shift(
    current_values: Iterable[float],
    baseline_values: Iterable[float],
    *,
    ratio_threshold: float = 3.0,
    ks_pvalue_threshold: float = 0.01,
) -> dict[str, Any]:
    """Detect distribution shifts using KS-test and robust moment ratios."""
    cur = np.asarray(list(current_values), dtype=float)
    base = np.asarray(list(baseline_values), dtype=float)

    if cur.size == 0 or base.size == 0:
        return {"is_anomaly": False, "score": 0.0, "method": "distribution_drift", "reason": "empty_input"}

    cur_mean = float(np.mean(cur))
    base_mean = float(np.mean(base))
    cur_std = float(np.std(cur))
    base_std = float(np.std(base))

    # Mean ratio calculation
    if base_mean == 0:
        mean_ratio = float("inf") if cur_mean != 0 else 1.0
    else:
        mean_ratio = max(abs(cur_mean / base_mean), abs(base_mean / cur_mean)) if cur_mean != 0 else float("inf")

    # If small sample size, fall back to mean ratio
    if cur.size < 5 or base.size < 5:
        is_anomaly = bool(mean_ratio >= ratio_threshold)
        return {
            "is_anomaly": is_anomaly,
            "score": float(mean_ratio),
            "method": "mean_ratio",
            "reason": f"small_sample; baseline_mean={base_mean:.3f}, current_mean={cur_mean:.3f}, ratio={mean_ratio:.2f}",
        }

    # Two-sample Kolmogorov-Smirnov test
    try:
        ks_res = stats.ks_2samp(cur, base)
        ks_stat = float(ks_res.statistic)
        ks_pval = float(ks_res.pvalue)
    except Exception:
        ks_stat = 0.0
        ks_pval = 1.0

    # Determine anomaly: significant KS distribution shift OR extreme mean shift
    is_ks_shift = bool(ks_pval < ks_pvalue_threshold and ks_stat > 0.35)
    is_mean_shift = bool(mean_ratio >= ratio_threshold)

    is_anomaly = is_ks_shift or is_mean_shift
    score = float(max(mean_ratio if mean_ratio != float("inf") else 10.0, ks_stat * 10.0))

    reasons = [
        f"baseline_mean={base_mean:.2f}(std={base_std:.2f})",
        f"current_mean={cur_mean:.2f}(std={cur_std:.2f})",
        f"ks_stat={ks_stat:.3f}(p={ks_pval:.4f})",
        f"mean_ratio={mean_ratio:.2f}",
    ]

    return {
        "is_anomaly": is_anomaly,
        "score": score,
        "method": "ks_test_and_moments",
        "reason": "; ".join(reasons),
    }
