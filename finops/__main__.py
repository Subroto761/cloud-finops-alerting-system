"""Command-line report.

python -m finops report --demo           # synthetic data, no AWS needed
python -m finops report --region ap-south-1
python -m finops report --json           # machine-readable output
python -m finops exporter                # start the Prometheus exporter
"""

from __future__ import annotations

import argparse
import json
import sys

from finops.sources import AwsSource, DemoSource, Snapshot


def render_text(snapshot: Snapshot) -> str:
    c = snapshot.costs
    lines = [
        f"Spend on {c.latest.day}: ${c.latest.total_usd:.2f}  "
        f"(7-day average ${c.baseline_usd:.2f}, change {c.change_pct:+.1f}%)",
        f"Month to date: ${c.month_to_date_usd:.2f}  (projected month end ${c.projected_month_usd:.2f})",
        "",
        "Top services yesterday:",
    ]
    for service, amount in sorted(c.latest.by_service.items(), key=lambda kv: kv[1], reverse=True)[:5]:
        lines.append(f"  {amount:>8.2f}  {service}")

    total_waste = sum(f.monthly_cost_usd for f in snapshot.findings)
    lines += ["", f"Idle resources: {len(snapshot.findings)}  (about ${total_waste:.2f}/month)"]
    for f in snapshot.findings:
        lines.append(f"  ${f.monthly_cost_usd:>7.2f}/mo  {f.resource_type:<13} {f.resource_id:<24} {f.reason}")
    return "\n".join(lines)


def render_json(snapshot: Snapshot) -> str:
    c = snapshot.costs
    return json.dumps(
        {
            "latest_day": c.latest.day.isoformat(),
            "latest_day_cost_usd": c.latest.total_usd,
            "baseline_usd": c.baseline_usd,
            "change_pct": c.change_pct,
            "month_to_date_usd": c.month_to_date_usd,
            "projected_month_usd": c.projected_month_usd,
            "cost_by_service_usd": c.latest.by_service,
            "idle_resources": [f.to_dict() for f in snapshot.findings],
        },
        indent=2,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="finops", description="Cloud FinOps cost and idle-resource report")
    sub = parser.add_subparsers(dest="command", required=True)

    report = sub.add_parser("report", help="print a one-off report")
    report.add_argument("--demo", action="store_true", help="use synthetic data")
    report.add_argument("--region", default="ap-south-1")
    report.add_argument("--cpu-threshold", type=float, default=5.0)
    report.add_argument("--lookback-days", type=int, default=7)
    report.add_argument("--json", action="store_true")

    sub.add_parser("exporter", help="run the Prometheus exporter")

    args = parser.parse_args(argv)

    if args.command == "exporter":
        from finops.exporter import main as run_exporter

        run_exporter()
        return 0

    source = DemoSource() if args.demo else AwsSource(args.region, args.cpu_threshold, args.lookback_days)
    snapshot = source.snapshot()
    print(render_json(snapshot) if args.json else render_text(snapshot))
    return 0


if __name__ == "__main__":
    sys.exit(main())
