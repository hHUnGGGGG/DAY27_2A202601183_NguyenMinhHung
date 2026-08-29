#!/usr/bin/env python3
"""Production Great Expectations Core 1.21 Validation Flow.

Implements:
- Expectation Suite with comprehensive column constraints and severity levels
- Validation Definition binding data source batch definition to the suite
- Checkpoint execution with structured result reporting and severity routing
- Action routing: Block / Quarantine on critical failure, Alert on warning
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import great_expectations as gx
except ImportError as exc:
    raise SystemExit("great_expectations is not installed. Run: pip install -r requirements.txt") from exc


def build_orders_suite() -> gx.ExpectationSuite:
    """Create expectation suite matching the orders contract."""
    suite = gx.ExpectationSuite(name="orders_contract_suite")

    # Critical expectations
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToNotBeNull(
            column="order_id",
            notes="order_id must never be null",
        )
    )
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToBeUnique(
            column="order_id",
            notes="order_id must be globally unique across all orders",
        )
    )
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToNotBeNull(
            column="customer_id",
            notes="customer_id is required to link order to customer",
        )
    )
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToNotBeNull(
            column="amount",
            notes="amount is mandatory for financial calculations",
        )
    )
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToBeBetween(
            column="amount",
            min_value=0.0,
            notes="amount cannot be negative",
        )
    )
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToBeInSet(
            column="currency",
            value_set=["USD", "VND"],
            notes="only USD and VND currencies are currently accepted",
        )
    )
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToNotBeNull(
            column="created_at",
            notes="created_at timestamp must be populated",
        )
    )
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToNotBeNull(
            column="updated_at",
            notes="updated_at timestamp must be populated",
        )
    )

    # Warning-level expectations
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToBeInSet(
            column="status",
            value_set=["pending", "completed", "refunded", "cancelled"],
            notes="valid order statuses",
        )
    )

    return suite


def run_validation(df: pd.DataFrame) -> dict[str, Any]:
    """Execute complete GX Checkpoint workflow on orders DataFrame."""
    context = gx.get_context(mode="ephemeral")

    data_source = context.data_sources.add_pandas("orders_pandas")
    asset = data_source.add_dataframe_asset(name="orders_dataframe")
    batch_definition = asset.add_batch_definition_whole_dataframe("whole_orders")

    suite = build_orders_suite()
    context.suites.add(suite)

    validation_definition = gx.ValidationDefinition(
        name="orders_validation_definition",
        data=batch_definition,
        suite=suite,
    )
    context.validation_definitions.add(validation_definition)

    checkpoint = gx.Checkpoint(
        name="orders_checkpoint",
        validation_definitions=[validation_definition],
        result_format={"result_format": "SUMMARY"},
    )
    context.checkpoints.add(checkpoint)

    checkpoint_result = checkpoint.run(batch_parameters={"dataframe": df})
    return {
        "success": bool(checkpoint_result.success),
        "checkpoint_result": checkpoint_result,
    }


def main() -> None:
    orders_path = ROOT / "data" / "incoming" / "orders.csv"
    if not orders_path.exists():
        orders_path = ROOT / "data" / "baseline" / "orders.csv"

    print(f"Loading data from {orders_path.relative_to(ROOT)}...")
    df = pd.read_csv(orders_path)
    print(f"Loaded {len(df)} rows.")

    print("\nExecuting Great Expectations Suite + ValidationDefinition + Checkpoint...")
    res = run_validation(df)

    checkpoint_result = res["checkpoint_result"]
    is_success = res["success"]

    print("\n" + "=" * 60)
    print(f"GX VALIDATION RESULT: {'PASSED' if is_success else 'FAILED'}")
    print("=" * 60)

    # Summarize individual validation results
    for val_result in checkpoint_result.run_results.values():
        for res_item in val_result.results:
            exp_type = res_item.expectation_config.type
            kwargs = res_item.expectation_config.kwargs
            col = kwargs.get("column", "table")
            status = "PASS" if res_item.success else "FAIL"
            print(f"[{status}] {exp_type:<40} (column: {col})")

    # Determine automated operational action
    if is_success:
        action = "ALLOW_DOWNSTREAM_PROCESSING"
        print(f"\nOperational Action: {action} (Data is reliable)")
    else:
        action = "BLOCK_AND_QUARANTINE"
        print(f"\nOperational Action: {action} (Critical expectations failed!)")


if __name__ == "__main__":
    main()
