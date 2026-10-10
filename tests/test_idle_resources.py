"""Idle-resource checks against a fake AWS account provided by moto."""

from datetime import timedelta

import boto3
import pytest
from moto import mock_aws

from finops import idle_resources, pricing

REGION = "ap-south-1"


@pytest.fixture
def aws(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    with mock_aws():
        yield boto3.client("ec2", region_name=REGION), boto3.client("cloudwatch", region_name=REGION)


def _launch(ec2, instance_type="t3.medium"):
    ami = ec2.describe_images(Owners=["amazon"])["Images"][0]["ImageId"]
    return ec2.run_instances(ImageId=ami, InstanceType=instance_type, MinCount=1, MaxCount=1)["Instances"][0]


def _put_daily_cpu(cloudwatch, instance_id, values, now):
    for days_ago, value in enumerate(values, start=1):
        cloudwatch.put_metric_data(
            Namespace="AWS/EC2",
            MetricData=[
                {
                    "MetricName": "CPUUtilization",
                    "Dimensions": [{"Name": "InstanceId", "Value": instance_id}],
                    "Timestamp": now - timedelta(days=days_ago, hours=-1),
                    "Value": value,
                    "Unit": "Percent",
                }
            ],
        )


def test_instance_with_low_cpu_is_idle(aws):
    ec2, cloudwatch = aws
    instance = _launch(ec2, "t3.medium")
    # Pretend "now" is 10 days after launch so the instance is old enough to judge
    now = instance["LaunchTime"] + timedelta(days=10)
    _put_daily_cpu(cloudwatch, instance["InstanceId"], [1.2, 0.8, 2.5, 1.1, 0.9, 1.4, 2.0], now)

    findings = idle_resources.find_idle_instances(ec2, cloudwatch, cpu_threshold_pct=5, lookback_days=7, now=now)

    assert [f.resource_id for f in findings] == [instance["InstanceId"]]
    assert findings[0].monthly_cost_usd == pricing.ec2_monthly_cost("t3.medium")
    assert "2.5%" in findings[0].reason


def test_busy_instance_is_not_idle(aws):
    ec2, cloudwatch = aws
    instance = _launch(ec2)
    now = instance["LaunchTime"] + timedelta(days=10)
    _put_daily_cpu(cloudwatch, instance["InstanceId"], [1.0, 1.0, 40.0, 1.0, 1.0, 1.0, 1.0], now)

    assert idle_resources.find_idle_instances(ec2, cloudwatch, 5, 7, now=now) == []


def test_new_instance_is_skipped(aws):
    ec2, cloudwatch = aws
    instance = _launch(ec2)
    now = instance["LaunchTime"] + timedelta(days=2)
    _put_daily_cpu(cloudwatch, instance["InstanceId"], [0.5, 0.5], now)

    assert idle_resources.find_idle_instances(ec2, cloudwatch, 5, 7, now=now) == []


def test_instance_without_metrics_is_skipped(aws):
    ec2, cloudwatch = aws
    instance = _launch(ec2)
    now = instance["LaunchTime"] + timedelta(days=10)

    assert idle_resources.find_idle_instances(ec2, cloudwatch, 5, 7, now=now) == []


def test_unattached_volume_is_found_and_attached_one_is_not(aws):
    ec2, _ = aws
    instance = _launch(ec2)
    zone = instance["Placement"]["AvailabilityZone"]
    loose = ec2.create_volume(AvailabilityZone=zone, Size=100, VolumeType="gp3")
    used = ec2.create_volume(AvailabilityZone=zone, Size=50, VolumeType="gp3")
    ec2.attach_volume(VolumeId=used["VolumeId"], InstanceId=instance["InstanceId"], Device="/dev/sdf")

    findings = idle_resources.find_unattached_volumes(ec2)

    assert [f.resource_id for f in findings] == [loose["VolumeId"]]
    assert findings[0].monthly_cost_usd == pytest.approx(9.12)


def test_unassociated_elastic_ip_is_found(aws):
    ec2, _ = aws
    instance = _launch(ec2)
    free = ec2.allocate_address(Domain="vpc")
    used = ec2.allocate_address(Domain="vpc")
    ec2.associate_address(AllocationId=used["AllocationId"], InstanceId=instance["InstanceId"])

    findings = idle_resources.find_unused_elastic_ips(ec2)

    assert [f.resource_id for f in findings] == [free["AllocationId"]]
    assert findings[0].monthly_cost_usd == pytest.approx(3.65)


def test_find_all_sorts_by_cost(aws):
    ec2, cloudwatch = aws
    zone = ec2.describe_availability_zones()["AvailabilityZones"][0]["ZoneName"]
    ec2.create_volume(AvailabilityZone=zone, Size=500, VolumeType="gp2")
    ec2.allocate_address(Domain="vpc")

    findings = idle_resources.find_all(ec2, cloudwatch)

    assert [f.resource_type for f in findings] == ["ebs_volume", "elastic_ip"]
    assert findings[0].monthly_cost_usd > findings[1].monthly_cost_usd
