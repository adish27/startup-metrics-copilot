"""Agent tools, tested without an LLM: each story must be findable through the tools alone."""

import json

import pytest

import agent as A


def dumps(x):
    return json.dumps(x)  # no default=: outputs must be plain JSON types


def test_all_tool_outputs_are_plain_json():
    for out in [A.list_metrics(), A.get_metric("cac", breakdown="channel"), A.get_mrr_bridge("2026-03", "plan"),
                A.top_account_changes("2026-08"), A.compare_periods("nrr", "2025-10", "2026-01", "2026-02", "2026-05"),
                A.detect_anomalies(), A.runway_scenario(-85000)]:
        dumps(out)


def test_bad_arguments_return_errors_not_exceptions():
    assert "error" in A.get_metric("not_a_metric")
    assert "error" in A.get_metric("cac", breakdown="plan")


def test_anomalies_surface_all_three_stories():
    flagged = {(f["month"], f["series"]) for f in A.detect_anomalies()["anomalies"]}
    assert ("2026-03", "bridge:expansion") in flagged          # story 1
    assert ("2026-06", "marketing_spend:paid_social") in flagged  # story 2
    assert ("2026-08", "bridge:churned") in flagged            # story 3
    assert ("2026-05", "bridge:contraction") in flagged        # story 3 early warning


def test_expansion_spike_is_pro_accounts_without_plan_change():
    top = A.top_account_changes("2026-03", "expansion")["plan_transitions"][0]
    assert (top["plan_before"], top["plan_after"]) == ("pro", "pro")
    assert top["median_change"] == 150


def test_august_churn_is_one_whale():
    out = A.top_account_changes("2026-08", "churned", n=1)["top_accounts"][0]
    assert out["account_id"] == "A00042" and out["share_of_prior_mrr_pct"] > 4


def test_cac_rise_is_isolated_to_paid_social():
    rows = {r["channel"]: r for r in A.compare_periods("cac", "2025-10", "2026-05", "2026-06", "2026-09", "channel")["rows"]}
    assert rows["paid_social"]["change_pct"] > 100
    assert all(abs(r["change_pct"]) < 20 for ch, r in rows.items() if ch != "paid_social")


def test_runway_scenario_cut_extends_runway():
    out = A.runway_scenario(-85000)
    assert out["static_runway_scenario"] > out["static_runway_current"]


def test_tool_budget_caps_calls():
    budget = A.ToolBudget(limit=2)
    assert [budget.take() for _ in range(3)] == [True, True, False]


def test_agent_graph_builds(monkeypatch):
    pytest.importorskip("langgraph")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    A.build_agent.cache_clear()
    graph = A.build_agent()
    assert {"agent", "tools"} <= set(graph.get_graph().nodes)
    A.build_agent.cache_clear()
