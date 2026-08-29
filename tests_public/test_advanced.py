"""Comprehensive tests for advanced data reliability features.

Covers:
- Strict type drift detection in data contracts
- Robust MAD edge cases (zero-MAD handling)
- Context-aware anomaly detection (segment history & known events)
- Transitive column lineage traversal
- Google SRE Multi-Window Multi-Burn-Rate alerting
- Embedding vector drift and collapse detection
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pandas as pd
import pytest

from student_api import (
    column_downstream,
    detect_distribution,
    detect_metric,
    downstream_assets,
    multiwindow_burn,
    rag_embedding_shift,
    slo_status,
    validate_orders,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "orders_contract.yaml"


def test_type_drift_is_detected():
    """String 'invalid_amount' in numeric amount column must be caught by contract validator."""
    df = pd.DataFrame([
        {
            "order_id": 101,
            "customer_id": "C0001",
            "amount": "not_a_number",
            "currency": "USD",
            "status": "completed",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ])
    issues = validate_orders(df, CONTRACT)
    failed = [i for i in issues if not i["passed"]]
    assert any(i["check"] in {"type", "range"} and i["column"] == "amount" for i in failed)


def test_mad_zero_variance_handling():
    """When history has zero MAD, exact match should not alarm, while deviation should."""
    history = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0]
    
    # Exact match
    res_match = detect_metric(100.0, history, method="mad")
    assert res_match["is_anomaly"] is False
    assert res_match["score"] == 0.0

    # Deviation from constant
    res_dev = detect_metric(150.0, history, method="mad")
    assert res_dev["is_anomaly"] is True


def test_context_aware_segment_history():
    """Auto detector should use same_segment_history from context when provided."""
    global_history = [600, 610, 590, 605, 600, 615]  # Weekday traffic
    saturday_history = [250, 255, 248, 252, 260]     # Weekend traffic

    # Current value is 250 (normal for Saturday, anomaly for global)
    context = {"same_segment_history": saturday_history, "day_of_week": 5}
    res = detect_metric(250, global_history, method="auto", context=context)
    assert res["is_anomaly"] is False


def test_multiwindow_burn_rate_policies():
    """Test sustained fast burn, sustained medium burn, and transient spikes."""
    # 1. Sustained Fast Burn (both short and long high -> PAGE)
    res_fast = multiwindow_burn(short_window_burn=15.0, long_window_burn=15.0)
    assert res_fast["page"] is True
    assert res_fast["severity"] == "critical"

    # 2. Transient Spike (short high, but long low -> NO PAGE)
    res_transient = multiwindow_burn(short_window_burn=18.0, long_window_burn=1.5)
    assert res_transient["page"] is False
    assert res_transient["severity"] in {"warning", "info"}

    # 3. Healthy (both within budget -> OK)
    res_ok = multiwindow_burn(short_window_burn=0.5, long_window_burn=0.4)
    assert res_ok["page"] is False
    assert res_ok["severity"] == "ok"


def test_transitive_column_lineage():
    """Column lineage graph traversal must return all transitive downstream columns in BFS order."""
    col_graph = {
        "raw_orders.amount": ["stg_orders.amount_usd"],
        "stg_orders.amount_usd": ["fct_daily_revenue.daily_revenue"],
        "fct_daily_revenue.daily_revenue": ["ceo_revenue_dashboard.revenue"],
    }
    result = column_downstream(col_graph, "raw_orders.amount")
    assert result == [
        "stg_orders.amount_usd",
        "fct_daily_revenue.daily_revenue",
        "ceo_revenue_dashboard.revenue",
    ]


def test_rag_embedding_norm_collapse():
    """Zero or collapsed embedding norms should trigger an anomaly."""
    baseline = [0.95, 0.98, 0.96, 0.97, 0.99]
    collapsed_current = [0.0, 0.00001, 0.0]
    res = rag_embedding_shift(collapsed_current, baseline)
    assert res["is_anomaly"] is True
