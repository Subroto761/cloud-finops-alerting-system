"""Find AWS resources that cost money but do nothing useful.

Three checks, each a common source of silent waste:

1. Running EC2 instances whose average CPU stayed under a threshold every day
   for the whole look-back window.
2. EBS volumes in the "available" state, meaning they are not attached to any
   instance but are still billed per GB.
3. Elastic IPs that are allocated but not associated with anything.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from finops import pricing


@dataclass(frozen=True)
class Finding:
    resource_type: str  # "ec2_instance" | "ebs_volume" | "elastic_ip"
    resource_id: str
    reason: str
    monthly_cost_usd: float

    def to_dict(self) -> dict:
        return asdict(self)


def find_idle_instances(
    ec2,
    cloudwatch,
    cpu_threshold_pct: float = 5.0,
    lookback_days: int = 7,
    now: datetime | None = None,
) -> list[Finding]:
    """Running instances whose daily average CPU never rose above the threshold.

    Instances younger than the look-back window, or with no CloudWatch data yet,
    are skipped: there is not enough evidence to call them idle.
    """
    now = now or datetime.now(UTC)
    start = now - timedelta(days=lookback_days)
    findings: list[Finding] = []

    paginator = ec2.get_paginator("describe_instances")
    pages = paginator.paginate(Filters=[{"Name": "instance-state-name", "Values": ["running"]}])
    for page in pages:
        for reservation in page["Reservations"]:
            for instance in reservation["Instances"]:
                if instance["LaunchTime"] > start:
                    continue

                stats = cloudwatch.get_metric_statistics(
                    Namespace="AWS/EC2",
                    MetricName="CPUUtilization",
                    Dimensions=[{"Name": "InstanceId", "Value": instance["InstanceId"]}],
                    StartTime=start,
                    EndTime=now,
                    Period=86400,
                    Statistics=["Average"],
                )
                daily_averages = [point["Average"] for point in stats["Datapoints"]]
                if not daily_averages:
                    continue

                peak = max(daily_averages)
                if peak < cpu_threshold_pct:
                    findings.append(
                        Finding(
                            resource_type="ec2_instance",
                            resource_id=instance["InstanceId"],
                            reason=(
                                f"{instance['InstanceType']}: daily average CPU peaked at "
                                f"{peak:.1f}% over {lookback_days} days "
                                f"(threshold {cpu_threshold_pct}%)"
                            ),
                            monthly_cost_usd=pricing.ec2_monthly_cost(instance["InstanceType"]),
                        )
                    )
    return findings


def find_unattached_volumes(ec2) -> list[Finding]:
    findings: list[Finding] = []
    paginator = ec2.get_paginator("describe_volumes")
    for page in paginator.paginate(Filters=[{"Name": "status", "Values": ["available"]}]):
        for volume in page["Volumes"]:
            findings.append(
                Finding(
                    resource_type="ebs_volume",
                    resource_id=volume["VolumeId"],
                    reason=f"{volume['Size']} GiB {volume['VolumeType']} volume not attached to any instance",
                    monthly_cost_usd=pricing.ebs_monthly_cost(volume["VolumeType"], volume["Size"]),
                )
            )
    return findings


def find_unused_elastic_ips(ec2) -> list[Finding]:
    findings: list[Finding] = []
    for address in ec2.describe_addresses()["Addresses"]:
        if "AssociationId" in address:
            continue
        findings.append(
            Finding(
                resource_type="elastic_ip",
                resource_id=address.get("AllocationId", address["PublicIp"]),
                reason=f"Elastic IP {address['PublicIp']} is allocated but not associated",
                monthly_cost_usd=pricing.elastic_ip_monthly_cost(),
            )
        )
    return findings


def find_all(ec2, cloudwatch, cpu_threshold_pct: float = 5.0, lookback_days: int = 7) -> list[Finding]:
    findings = (
        find_idle_instances(ec2, cloudwatch, cpu_threshold_pct, lookback_days)
        + find_unattached_volumes(ec2)
        + find_unused_elastic_ips(ec2)
    )
    return sorted(findings, key=lambda f: f.monthly_cost_usd, reverse=True)
