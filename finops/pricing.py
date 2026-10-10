"""Approximate on-demand prices used to estimate monthly waste.

These are rough ap-south-1 (Mumbai) Linux on-demand list prices. They are only
used to rank findings by how much money they waste, not for billing, so being
a few percent off is fine. Unknown types fall back to a conservative default.
"""

HOURS_PER_MONTH = 730

# USD per hour
EC2_HOURLY_USD = {
    "t2.micro": 0.0124,
    "t3.nano": 0.0056,
    "t3.micro": 0.0112,
    "t3.small": 0.0224,
    "t3.medium": 0.0448,
    "t3.large": 0.0896,
    "t3.xlarge": 0.1792,
    "m5.large": 0.101,
    "m5.xlarge": 0.202,
    "c5.large": 0.085,
    "r5.large": 0.128,
}
EC2_DEFAULT_HOURLY_USD = 0.10

# USD per GB-month
EBS_GB_MONTH_USD = {
    "gp2": 0.114,
    "gp3": 0.0912,
    "io1": 0.142,
    "io2": 0.142,
    "st1": 0.051,
    "sc1": 0.0174,
    "standard": 0.08,
}
EBS_DEFAULT_GB_MONTH_USD = 0.10

# An Elastic IP that is allocated but not attached is billed per hour
ELASTIC_IP_HOURLY_USD = 0.005


def ec2_monthly_cost(instance_type: str) -> float:
    return round(EC2_HOURLY_USD.get(instance_type, EC2_DEFAULT_HOURLY_USD) * HOURS_PER_MONTH, 2)


def ebs_monthly_cost(volume_type: str, size_gb: int) -> float:
    return round(EBS_GB_MONTH_USD.get(volume_type, EBS_DEFAULT_GB_MONTH_USD) * size_gb, 2)


def elastic_ip_monthly_cost() -> float:
    return round(ELASTIC_IP_HOURLY_USD * HOURS_PER_MONTH, 2)
