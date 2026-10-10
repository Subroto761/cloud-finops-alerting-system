"""Prometheus exporter.

Exposes FinOps numbers as metrics on :9108/metrics. Prometheus scrapes them,
evaluates the alert rules in monitoring/alert_rules.yml, and sends firing
alerts to Alertmanager. Grafana only visualises; it does not alert.

Environment variables:
    FINOPS_DEMO=1            use synthetic data instead of AWS
    AWS_REGION               region to scan (default ap-south-1)
    REFRESH_SECONDS          how often to call AWS (default 21600 = 6 hours)
    CPU_THRESHOLD_PCT        idle EC2 threshold (default 5)
    LOOKBACK_DAYS            idle EC2 look-back window (default 7)
    MONTHLY_BUDGET_USD       budget the projected spend is compared with (default 50)
    EXPORTER_PORT            default 9108
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict

from prometheus_client import Gauge, start_http_server

from finops.sources import AwsSource, DemoSource, Snapshot

log = logging.getLogger("finops.exporter")

DAILY_COST = Gauge("finops_daily_cost_usd", "Total spend for the latest complete day")
DAILY_COST_BASELINE = Gauge("finops_daily_cost_baseline_usd", "Mean daily spend over the previous 7 days")
DAILY_COST_BY_SERVICE = Gauge("finops_daily_cost_by_service_usd", "Latest day spend per AWS service", ["service"])
MONTH_TO_DATE = Gauge("finops_month_to_date_cost_usd", "Spend so far this month")
PROJECTED_MONTH = Gauge("finops_projected_month_cost_usd", "Month-to-date spend projected to the end of the month")
MONTHLY_BUDGET = Gauge("finops_monthly_budget_usd", "Monthly budget from MONTHLY_BUDGET_USD, used by alert rules")
IDLE_COUNT = Gauge("finops_idle_resources", "Number of idle resources found", ["resource_type"])
IDLE_WASTE = Gauge("finops_idle_monthly_waste_usd", "Estimated monthly cost of idle resources", ["resource_type"])
LAST_SUCCESS = Gauge("finops_last_refresh_success", "1 if the last refresh worked, 0 if it failed")
LAST_REFRESH = Gauge("finops_last_refresh_timestamp_seconds", "Unix time of the last successful refresh")

RESOURCE_TYPES = ("ec2_instance", "ebs_volume", "elastic_ip")


def publish(snapshot: Snapshot) -> None:
    costs = snapshot.costs
    DAILY_COST.set(costs.latest.total_usd)
    DAILY_COST_BASELINE.set(costs.baseline_usd)
    MONTH_TO_DATE.set(costs.month_to_date_usd)
    PROJECTED_MONTH.set(costs.projected_month_usd)

    DAILY_COST_BY_SERVICE.clear()
    for service, amount in costs.latest.by_service.items():
        DAILY_COST_BY_SERVICE.labels(service=service).set(amount)

    counts: dict[str, int] = defaultdict(int)
    waste: dict[str, float] = defaultdict(float)
    for finding in snapshot.findings:
        counts[finding.resource_type] += 1
        waste[finding.resource_type] += finding.monthly_cost_usd
    for resource_type in RESOURCE_TYPES:  # always publish every type so "0" is visible
        IDLE_COUNT.labels(resource_type=resource_type).set(counts[resource_type])
        IDLE_WASTE.labels(resource_type=resource_type).set(round(waste[resource_type], 2))

    LAST_SUCCESS.set(1)
    LAST_REFRESH.set(time.time())


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if os.getenv("FINOPS_DEMO") == "1":
        source = DemoSource()
        log.info("Running in demo mode with synthetic data")
    else:
        source = AwsSource(
            region=os.getenv("AWS_REGION", "ap-south-1"),
            cpu_threshold_pct=float(os.getenv("CPU_THRESHOLD_PCT", "5")),
            lookback_days=int(os.getenv("LOOKBACK_DAYS", "7")),
        )

    MONTHLY_BUDGET.set(float(os.getenv("MONTHLY_BUDGET_USD", "50")))
    port = int(os.getenv("EXPORTER_PORT", "9108"))
    refresh = int(os.getenv("REFRESH_SECONDS", "21600"))
    start_http_server(port)
    log.info("Serving metrics on :%d/metrics, refreshing every %ds", port, refresh)

    while True:
        try:
            snapshot = source.snapshot()
            publish(snapshot)
            log.info(
                "Refreshed: latest day $%.2f (baseline $%.2f, %+.1f%%), %d idle resources",
                snapshot.costs.latest.total_usd,
                snapshot.costs.baseline_usd,
                snapshot.costs.change_pct,
                len(snapshot.findings),
            )
        except Exception:  # keep serving the last good values; the alert rule catches stale data
            LAST_SUCCESS.set(0)
            log.exception("Refresh failed")
        time.sleep(refresh)


if __name__ == "__main__":
    main()
