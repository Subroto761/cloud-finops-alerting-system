# Cloud FinOps Alerting System

[![CI](https://github.com/Subroto761/cloud-finops-alerting-system/actions/workflows/ci.yml/badge.svg)](https://github.com/Subroto761/cloud-finops-alerting-system/actions/workflows/ci.yml)

This project finds AWS resources that cost money but do nothing useful, tracks daily spend, and alerts when costs spike or the monthly budget is at risk.

**Stack:** Python (boto3) · Prometheus · Alertmanager · Grafana · Docker Compose · Terraform · GitHub Actions

```
            ┌───────────────────────── AWS account ─────────────────────────┐
            │  EC2 · EBS · Elastic IPs · CloudWatch (CPU) · Cost Explorer   │
            └───────────────────────────────┬───────────────────────────────┘
                                            │ read-only IAM (Terraform)
                                            ▼
┌──────────────────────┐  scrape   ┌──────────────┐  alerts  ┌──────────────┐
│ finops-exporter      │ ◀──────── │ Prometheus   │ ───────▶ │ Alertmanager │ ──▶ Slack / email
│ Python, :9108        │  :9108    │ evaluates    │          │ groups and   │
│ refreshes every 6 h  │           │ alert rules  │          │ routes       │
└──────────────────────┘           └──────┬───────┘          └──────────────┘
                                          │ query
                                          ▼
                                   ┌──────────────┐
                                   │ Grafana      │  dashboards only (no alerting)
                                   └──────────────┘

   AWS Budgets ──▶ SNS ──▶ email      (independent safety net, also from Terraform)
```

## What it detects

| Check | How | Why it matters |
|---|---|---|
| **Idle EC2 instances** | Running for at least 7 days, with the daily average CPU under 5% on every one of those days (CloudWatch) | The most common source of waste |
| **Unattached EBS volumes** | Volume state is `available` | Still billed per GB after the instance is gone |
| **Unused Elastic IPs** | Allocated but not associated | Billed hourly while sitting idle |
| **Cost spike** | Yesterday's spend is more than 30% above the 7-day average, and the jump is at least $1 | Catches runaway resources within a day |
| **Budget at risk** | Month-to-date spend, projected to month end, exceeds the budget | Warns before the bill arrives |

Every finding comes with an estimated monthly cost (see `finops/pricing.py`), so the most expensive waste is listed first.

## Quick start (no AWS account needed)

Demo mode generates realistic synthetic data, including a cost spike, so the full pipeline can be seen working:

```bash
docker compose up --build
```

| URL | What you'll see |
|---|---|
| http://localhost:3000 | Grafana, **FinOps → Cloud FinOps Overview** dashboard |
| http://localhost:9090/alerts | Prometheus: `CostSpike`, `MonthlyBudgetAtRisk` and `IdleResourcesWastingMoney` pending, then firing |
| http://localhost:9093 | Alertmanager with the grouped alerts |
| http://localhost:9108/metrics | Raw exporter metrics |

Or just print a report:

```bash
pip install -r requirements.txt
python -m finops report --demo
```

```
Spend on 2026-10-09: $10.89  (7-day average $6.25, change +74.2%)
Month to date: $60.60  (projected month end $208.73)

Idle resources: 5  (about $114.30/month)
  $  65.41/mo  ec2_instance  i-0demo1a2b3c4d5e6   t3.large: daily average CPU peaked at 1.8% over 7 days
  $  32.70/mo  ec2_instance  i-0demo7f8e9d0c1b2   t3.medium: daily average CPU peaked at 3.2% over 7 days
  $   9.12/mo  ebs_volume    vol-0demo11223344    100 GiB gp3 volume not attached to any instance
  ...
```

## Running against a real AWS account

1. **Create the read-only permissions and budget with Terraform**

   ```bash
   cd terraform
   cp terraform.tfvars.example terraform.tfvars   # set your budget and email
   terraform init
   terraform apply
   ```

   This creates:
   - a least-privilege IAM policy (`ec2:Describe*` for three resource types, `cloudwatch:GetMetricStatistics`, `ce:GetCostAndUsage`)
   - an EC2 role and instance profile
   - an AWS Budget that emails through SNS at 80% of actual spend and 100% of forecast spend

   Optionally, set `create_monitoring_host = true` to run the whole stack on a t3.small. It uses IMDSv2, an encrypted disk, Grafana open only to your IP, and credentials from the instance role, so no access keys are stored on the server.

2. **Run locally with your AWS credentials** (attach the `readonly_policy_arn` output to your IAM user):

   ```bash
   python -m finops report --region ap-south-1
   # or the full stack
   FINOPS_DEMO=0 MONTHLY_BUDGET_USD=25 docker compose up --build
   ```

   Cost Explorer must be enabled on the account once (Billing console → Cost Explorer).

## Design decisions

- **Prometheus does the alerting; Grafana only visualises.** Alert rules live in version control (`monitoring/alert_rules.yml`) and have unit tests (`alert_rules_test.yml`, run with `promtool`). Alertmanager handles grouping, de-duplication and routing.
- **The exporter refreshes every 6 hours, not on every scrape.** Each Cost Explorer API call costs $0.01, and AWS only updates billing data a few times a day. Prometheus scrapes every minute but reads cached values.
- **Spikes need both a percentage and an absolute threshold.** Going from $0.50 to $1.20 is +140% but not worth waking anyone up. Requiring a jump of at least $1 removes that noise.
- **Instances need evidence before they're called idle.** An instance must have run for the whole 7-day window, and a single busy day disqualifies it, so a weekly batch job won't be flagged.
- **The pipeline watches itself.** `FinOpsExporterDown` and `FinOpsDataStale` fire if the exporter dies or AWS calls start failing (for example, after credentials expire).
- **AWS Budgets is a separate safety net.** It keeps alerting even if the monitoring stack is down.

## Project structure

```
finops/
  idle_resources.py   idle EC2, unattached EBS, unused Elastic IP checks
  cost_report.py      Cost Explorer parsing, baseline, spike %, month-end projection
  pricing.py          approximate ap-south-1 prices for estimating waste
  sources.py          AwsSource (real) and DemoSource (synthetic)
  exporter.py         Prometheus exporter
  __main__.py         CLI: `python -m finops report | exporter`
tests/                pytest + moto (mocked AWS), botocore Stubber for Cost Explorer
monitoring/
  prometheus.yml, alert_rules.yml, alert_rules_test.yml, alertmanager.yml
  grafana/            provisioned datasource and dashboard
terraform/            IAM, AWS Budget + SNS, optional monitoring EC2 host
.github/workflows/    CI: lint, tests, terraform validate, promtool, end-to-end stack test
```

## Testing

```bash
pip install -r requirements-dev.txt
pytest                      # 20 tests, AWS is mocked with moto
ruff check . && ruff format --check .
promtool test rules monitoring/alert_rules_test.yml
```

CI runs all of the above. It also runs `terraform validate` and starts the full Docker Compose stack, then checks four things: Prometheus scrapes the exporter, the `CostSpike` alert triggers on demo data, and Grafana loads the dashboard.

## Limitations and next steps

- Scans one region at a time. Next step: loop over regions, or use AWS Organizations for multiple accounts.
- Prices are approximate list prices. They don't account for Savings Plans or Reserved Instances.
- Next step: an optional `--fix` mode that snapshots and deletes unattached volumes after approval.

## Author

**Subroto Mondal** · [GitHub](https://github.com/Subroto761) · [LinkedIn](https://www.linkedin.com/in/cnctsubroto)
