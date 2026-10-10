"""Read daily spend from AWS Cost Explorer and compare it with a baseline.

Cost Explorer data for the current day is incomplete, so the "latest" day is
always yesterday. The baseline is the mean of the N complete days before it.

Note: every Cost Explorer API call costs USD 0.01, which is why the exporter
refreshes every few hours instead of on every Prometheus scrape.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import mean


@dataclass(frozen=True)
class DailyCost:
    day: date
    total_usd: float
    by_service: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class CostSummary:
    latest: DailyCost
    baseline_usd: float
    change_pct: float
    month_to_date_usd: float
    projected_month_usd: float


def fetch_daily_costs(ce, days: int = 14, today: date | None = None) -> list[DailyCost]:
    """Daily unblended cost per service, oldest first.

    Covers at least the last `days` complete days, and always reaches back to the
    1st of the month so that month-to-date spend can be calculated.
    """
    today = today or date.today()
    yesterday = today - timedelta(days=1)
    start = min(today - timedelta(days=days), yesterday.replace(day=1))

    response = ce.get_cost_and_usage(
        TimePeriod={"Start": start.isoformat(), "End": today.isoformat()},  # End is exclusive
        Granularity="DAILY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )

    results: list[DailyCost] = []
    for period in response["ResultsByTime"]:
        by_service = {
            group["Keys"][0]: round(float(group["Metrics"]["UnblendedCost"]["Amount"]), 4)
            for group in period.get("Groups", [])
        }
        results.append(
            DailyCost(
                day=date.fromisoformat(period["TimePeriod"]["Start"]),
                total_usd=round(sum(by_service.values()), 4),
                by_service=by_service,
            )
        )
    return sorted(results, key=lambda d: d.day)


def summarise(daily: list[DailyCost], baseline_days: int = 7) -> CostSummary:
    """Compare the most recent day with the average of the days before it."""
    if not daily:
        raise ValueError("no cost data")

    latest = daily[-1]
    history = [d.total_usd for d in daily[-1 - baseline_days : -1]]
    baseline = mean(history) if history else latest.total_usd

    if baseline > 0:
        change_pct = (latest.total_usd - baseline) / baseline * 100
    else:
        change_pct = 0.0 if latest.total_usd == 0 else 100.0

    same_month = (latest.day.year, latest.day.month)
    month_to_date = sum(d.total_usd for d in daily if (d.day.year, d.day.month) == same_month)

    # Straight-line projection: average daily spend so far x days in the month
    days_in_month = calendar.monthrange(latest.day.year, latest.day.month)[1]
    projected_month = month_to_date / latest.day.day * days_in_month

    return CostSummary(
        latest=latest,
        baseline_usd=round(baseline, 4),
        change_pct=round(change_pct, 2),
        month_to_date_usd=round(month_to_date, 4),
        projected_month_usd=round(projected_month, 2),
    )
