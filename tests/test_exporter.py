"""The exporter publishes what Prometheus alert rules expect."""

from prometheus_client import REGISTRY

from finops import exporter
from finops.__main__ import main as cli
from finops.sources import DemoSource


def _value(name, **labels):
    return REGISTRY.get_sample_value(name, labels)


def test_demo_snapshot_has_a_cost_spike():
    snapshot = DemoSource().snapshot()
    assert snapshot.costs.change_pct > 30, "demo data should trigger the CostSpike alert"
    assert len(snapshot.findings) == 5


def test_publish_sets_all_metrics():
    snapshot = DemoSource().snapshot()
    exporter.publish(snapshot)

    assert _value("finops_daily_cost_usd") == snapshot.costs.latest.total_usd
    assert _value("finops_daily_cost_baseline_usd") == snapshot.costs.baseline_usd
    assert _value("finops_idle_resources", resource_type="ec2_instance") == 2
    assert _value("finops_idle_resources", resource_type="ebs_volume") == 2
    assert _value("finops_idle_resources", resource_type="elastic_ip") == 1
    assert _value("finops_last_refresh_success") == 1
    expected_waste = round(sum(f.monthly_cost_usd for f in snapshot.findings if f.resource_type == "ebs_volume"), 2)
    assert _value("finops_idle_monthly_waste_usd", resource_type="ebs_volume") == expected_waste


def test_cli_report_runs_in_demo_mode(capsys):
    assert cli(["report", "--demo"]) == 0
    out = capsys.readouterr().out
    assert "Idle resources: 5" in out
    assert "Month to date" in out


def test_cli_json_output(capsys):
    import json

    cli(["report", "--demo", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert len(data["idle_resources"]) == 5
    assert data["change_pct"] > 30
