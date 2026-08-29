"""RAG and Generative AI Data Quality & Drift Signals.

Monitors:
- Token and character length distribution shifts
- Embedding vector norm shifts, dimension collapse, and scale drift
"""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np

from observability.anomaly import mad_detector, zscore_detector


def approximate_token_lengths(texts: Iterable[str]) -> list[int]:
    """Token count proxy based on whitespace splitting."""
    return [len(str(t).split()) for t in texts]


def detect_text_length_shift(
    current_texts: Iterable[str],
    baseline_batch_means: Iterable[float],
    *,
    threshold: float = 3.0,
) -> dict[str, Any]:
    lengths = approximate_token_lengths(current_texts)
    current_mean = float(np.mean(lengths)) if lengths else 0.0
    result = zscore_detector(current_mean, baseline_batch_means, threshold=threshold)
    result["metric"] = "mean_text_length"
    result["current_mean"] = current_mean
    return result


def detect_embedding_norm_shift(
    current_norms: Iterable[float],
    baseline_norms: Iterable[float],
    *,
    threshold: float = 3.0,
) -> dict[str, Any]:
    """Detect anomalies in embedding vector norms (norm collapse, scaling drift).

    Identifies:
    1. Zero-norm or NaN vector collapses
    2. Significant mean/median magnitude shift compared to baseline norms
    """
    cur = np.asarray(list(current_norms), dtype=float)
    base = np.asarray(list(baseline_norms), dtype=float)

    if cur.size == 0 or base.size == 0:
        return {
            "is_anomaly": False,
            "score": 0.0,
            "method": "embedding_norm",
            "reason": "empty_norms_input",
        }

    # 1. Critical Collapse: check for zero or near-zero norms
    zero_or_nan_count = int(np.sum(np.isnan(cur) | (cur < 1e-6)))
    if zero_or_nan_count > 0:
        return {
            "is_anomaly": True,
            "score": float("inf"),
            "method": "embedding_norm:collapse",
            "reason": f"detected {zero_or_nan_count} zero or collapsed embedding vectors",
        }

    cur_mean = float(np.mean(cur))
    base_mean = float(np.mean(base))
    base_std = float(np.std(base))

    # 2. Statistical shift test
    if base_std > 0:
        z_res = zscore_detector(cur_mean, base, threshold=threshold)
        score = z_res["score"]
        is_anomaly = z_res["is_anomaly"]
    else:
        # Fallback to relative ratio
        ratio = max(cur_mean / base_mean, base_mean / cur_mean) if base_mean > 0 and cur_mean > 0 else float("inf")
        score = float(ratio)
        is_anomaly = bool(ratio >= 2.0)

    return {
        "is_anomaly": is_anomaly,
        "score": float(score),
        "method": "embedding_norm_shift",
        "reason": f"current_norm_mean={cur_mean:.4f}, baseline_norm_mean={base_mean:.4f}, std={base_std:.4f}",
    }
