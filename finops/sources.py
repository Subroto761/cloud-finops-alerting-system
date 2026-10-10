"""Where the numbers come from.

`AwsSource` calls the real AWS APIs. `DemoSource` returns realistic made-up data
(including a cost spike) so the whole stack, including dashboards and alerts,
can be run and demonstrated without an AWS account.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

from finops import cost_report, idle_resources, pricing
from finops.cost_report import CostSummary, DailyCost
from finops.idle_resources import Finding


@dataclass(frozen=True)
class Snapshot:
    findings: list[Finding]
    costs: CostSummary


class AwsSource:
    def __init__(self, region: str, cpu_threshold_pct: float = 5.0, lookback_days: int = 7):
        import boto3  # imported here so demo mode works without AWS credentials

        session = boto3.Session(region_name=region)
        self.ec2 = session.client("ec2")
        self.cloudwatch = session.client("cloudwatch")
        self.ce = session.client("ce", region_name="us-east-1")  # Cost Explorer is global, served from us-east-1
        self.cpu_threshold_pct = cpu_threshold_pct
        self.lookback_days = lookback_days

    def snapshot(self) -> Snapshot:
        findings = idle_resources.find_all(self.ec2, self.cloudwatch, self.cpu_threshold_pct, self.lookback_days)
        daily = cost_report.fetch_daily_costs(self.ce)
        return Snapshot(findings=findings, costs=cost_report.summarise(daily))


class DemoSource:
    """Fourteen days of steady spend, then a spike on the latest day."""

    SERVICES = {
        "Amazon Elastic Compute Cloud - Compute": 3.20,
        "Amazon Simple Storage Service": 0.45,
        "Amazon Relational Database Service": 1.60,
        "AmazonCloudWatch": 0.25,
        "EC2 - Other": 0.70,
    }

    def __init__(self, seed: int = 42, spike_multiplier: float = 1.6):
        self.rng = random.Random(seed)
        self.spike_multiplier = spike_multiplier

    def snapshot(self) -> Snapshot:
        today = date.today()
        daily: list[DailyCost] = []
        for offset in range(14, 0, -1):
            day = today - timedelta(days=offset)
            is_latest = offset == 1
            by_service = {}
            for service, base in self.SERVICES.items():
                value = base * self.rng.uniform(0.9, 1.1)
                if is_latest and service.startswith("Amazon Elastic Compute"):
                    value *= self.spike_multiplier * 1.5
                by_service[service] = round(value, 4)
            daily.append(DailyCost(day=day, total_usd=round(sum(by_service.values()), 4), by_service=by_service))

        findings = [
            Finding(
                "ec2_instance",
                "i-0demo1a2b3c4d5e6",
                "t3.large: daily average CPU peaked at 1.8% over 7 days (threshold 5.0%)",
                pricing.ec2_monthly_cost("t3.large"),
            ),
            Finding(
                "ec2_instance",
                "i-0demo7f8e9d0c1b2",
                "t3.medium: daily average CPU peaked at 3.2% over 7 days (threshold 5.0%)",
                pricing.ec2_monthly_cost("t3.medium"),
            ),
            Finding(
                "ebs_volume",
                "vol-0demo11223344",
                "100 GiB gp3 volume not attached to any instance",
                pricing.ebs_monthly_cost("gp3", 100),
            ),
            Finding(
                "ebs_volume",
                "vol-0demo55667788",
                "30 GiB gp2 volume not attached to any instance",
                pricing.ebs_monthly_cost("gp2", 30),
            ),
            Finding(
                "elastic_ip",
                "eipalloc-0demo9900",
                "Elastic IP 203.0.113.10 is allocated but not associated",
                pricing.elastic_ip_monthly_cost(),
            ),
        ]
        findings.sort(key=lambda f: f.monthly_cost_usd, reverse=True)
        return Snapshot(findings=findings, costs=cost_report.summarise(daily))
