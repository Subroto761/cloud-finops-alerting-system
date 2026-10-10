"""Cost Explorer parsing and spike maths."""

from datetime import date

import boto3
import pytest
from botocore.stub import Stubber

from finops.cost_report import DailyCost, fetch_daily_costs, summarise


def _days(values, start=date(2026, 3, 1)):
    return [DailyCost(day=start.replace(day=start.day + i), total_usd=v) for i, v in enumerate(values)]


def test_spike_is_measured_against_previous_seven_days():
    summary = summarise(_days([10, 10, 10, 10, 10, 10, 10, 15]))
    assert summary.baseline_usd == 10
    assert summary.change_pct == 50
    assert summary.latest.total_usd == 15


def test_only_last_seven_days_count_towards_baseline():
    # The expensive first day is outside the 7-day window and must be ignored
    summary = summarise(_days([100, 10, 10, 10, 10, 10, 10, 10, 10]))
    assert summary.baseline_usd == 10
    assert summary.change_pct == 0


def test_drop_in_spend_is_negative():
    assert summarise(_days([10] * 7 + [5])).change_pct == -50


def test_zero_baseline_does_not_divide_by_zero():
    assert summarise(_days([0, 0, 0, 2])).change_pct == 100
    assert summarise(_days([0, 0, 0, 0])).change_pct == 0


def test_month_to_date_only_counts_latest_month():
    daily = [
        DailyCost(day=date(2026, 2, 27), total_usd=50),
        DailyCost(day=date(2026, 2, 28), total_usd=50),
        DailyCost(day=date(2026, 3, 1), total_usd=4),
        DailyCost(day=date(2026, 3, 2), total_usd=6),
    ]
    assert summarise(daily).month_to_date_usd == 10


def test_projection_scales_month_to_date_to_full_month():
    # 2 days into a 31-day month at $5/day -> $155 projected
    daily = [DailyCost(day=date(2026, 3, 1), total_usd=5), DailyCost(day=date(2026, 3, 2), total_usd=5)]
    assert summarise(daily).projected_month_usd == 155


def test_empty_input_raises():
    with pytest.raises(ValueError):
        summarise([])


def test_fetch_parses_cost_explorer_response():
    ce = boto3.client("ce", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
    response = {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": "2026-03-02", "End": "2026-03-03"},
                "Groups": [
                    {"Keys": ["Amazon EC2"], "Metrics": {"UnblendedCost": {"Amount": "3.5", "Unit": "USD"}}},
                    {"Keys": ["Amazon S3"], "Metrics": {"UnblendedCost": {"Amount": "0.25", "Unit": "USD"}}},
                ],
                "Total": {},
                "Estimated": False,
            },
            {
                "TimePeriod": {"Start": "2026-03-01", "End": "2026-03-02"},
                "Groups": [
                    {"Keys": ["Amazon EC2"], "Metrics": {"UnblendedCost": {"Amount": "3.0", "Unit": "USD"}}},
                ],
                "Total": {},
                "Estimated": False,
            },
        ],
        "DimensionValueAttributes": [],
    }
    with Stubber(ce) as stub:
        stub.add_response(
            "get_cost_and_usage",
            response,
            {
                # today = 3 March: 14 days back (17 Feb) is earlier than the 1st of the month, so it wins
                "TimePeriod": {"Start": "2026-02-17", "End": "2026-03-03"},
                "Granularity": "DAILY",
                "Metrics": ["UnblendedCost"],
                "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
            },
        )
        daily = fetch_daily_costs(ce, days=14, today=date(2026, 3, 3))

    assert [d.day for d in daily] == [date(2026, 3, 1), date(2026, 3, 2)]  # sorted oldest first
    assert daily[1].total_usd == 3.75
    assert daily[1].by_service == {"Amazon EC2": 3.5, "Amazon S3": 0.25}


def test_fetch_reaches_back_to_start_of_month():
    ce = boto3.client("ce", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
    with Stubber(ce) as stub:
        stub.add_response(
            "get_cost_and_usage",
            {"ResultsByTime": [], "DimensionValueAttributes": []},
            {
                # 14 days before 28 March is 14 March, but the month began on 1 March
                "TimePeriod": {"Start": "2026-03-01", "End": "2026-03-28"},
                "Granularity": "DAILY",
                "Metrics": ["UnblendedCost"],
                "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
            },
        )
        fetch_daily_costs(ce, days=14, today=date(2026, 3, 28))
