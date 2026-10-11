"""Metric correctness: a hand-built fixture with known answers, plus integrity checks on generated data."""

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import metrics as M

ROOT = Path(__file__).resolve().parent.parent


# --- hand-built fixture: 4 paying accounts (+1 failed trial), Sep (opening) to Nov 2025 ---
#
#           Sep    Oct    Nov
#   A1      100    100    150   starter -> pro in Nov (expansion)
#   A2      200    200      0   churned in Nov
#   A3     1000    800    800   contraction in Oct
#   A4        0      0    300   new in Nov (paid_search)
#   A5      failed Nov trial (paid_search)

@pytest.fixture
def tiny():
    accounts = pd.DataFrame([
        ["A1", "One", "broker", "organic_search", "2025-01-05", True, "2025-01-10", "starter", None],
        ["A2", "Two", "broker", "paid_search", "2025-02-05", True, "2025-02-10", "pro", "2025-10-31"],
        ["A3", "Three", "community_lender", "outbound", "2025-03-05", True, "2025-03-10", "business", None],
        ["A4", "Four", "broker", "paid_search", "2025-11-01", True, "2025-11-05", "pro", None],
        ["A5", "Five", "broker", "paid_search", "2025-11-02", False, None, None, None],
    ], columns=["account_id", "account_name", "segment", "acquisition_channel", "trial_start_date",
                "converted", "conversion_date", "first_plan", "churn_date"])
    subs = pd.DataFrame([
        ["2025-09", "A1", "starter", 100], ["2025-09", "A2", "pro", 200], ["2025-09", "A3", "business", 1000],
        ["2025-10", "A1", "starter", 100], ["2025-10", "A2", "pro", 200], ["2025-10", "A3", "business", 800],
        ["2025-11", "A1", "pro", 150], ["2025-11", "A3", "business", 800], ["2025-11", "A4", "pro", 300],
    ], columns=["month", "account_id", "plan", "mrr"])
    spend = pd.DataFrame([
        ["2025-10", "organic_search", 500],
        ["2025-11", "organic_search", 400], ["2025-11", "paid_search", 600],
    ], columns=["month", "channel", "spend"])
    expenses = pd.DataFrame([
        ["2025-10", "hosting", 100, True], ["2025-10", "qc_ops", 100, True],
        ["2025-10", "payroll", 2000, False], ["2025-10", "marketing", 500, False],
        ["2025-11", "hosting", 100, True], ["2025-11", "qc_ops", 150, True],
        ["2025-11", "payroll", 2000, False], ["2025-11", "marketing", 1000, False],
    ], columns=["month", "category", "amount", "is_cogs"])
    company = {"name": "Tiny", "opening_cash": 10_000, "opening_cash_date": "2025-09-30",
               "window_start": "2025-10", "window_end": "2025-11"}
    return M.build_data(accounts, subs, spend, expenses, company)


NOV = "2025-11"


def test_mrr_and_arr(tiny):
    assert M.mrr(tiny, NOV).value == 1250
    assert M.arr(tiny, NOV).value == 15_000
    by_plan = M.mrr(tiny, NOV, "plan").breakdown.set_index("plan").value
    assert by_plan.to_dict() == {"business": 800, "pro": 450}


def test_mom_growth(tiny):
    assert M.mom_growth(tiny, NOV).value == pytest.approx(100 * 150 / 1100)


def test_mrr_bridge(tiny):
    r = M.mrr_bridge(tiny, NOV)
    bd = r.breakdown.set_index("component")
    assert r.value == 150
    assert bd.mrr.to_dict() == {"new": 300, "expansion": 50, "contraction": 0, "churned": 200}
    assert bd.accounts.to_dict() == {"new": 1, "expansion": 1, "contraction": 0, "churned": 1}
    oct_bd = M.mrr_bridge(tiny, "2025-10").breakdown.set_index("component").mrr
    assert oct_bd["contraction"] == 200


def test_trial_conversion(tiny):
    r = M.trial_conversion(tiny, NOV, "channel")
    assert r.value == 50
    assert r.breakdown.set_index("channel").value["paid_search"] == 50


def test_cac(tiny):
    r = M.cac(tiny, NOV, "channel")
    bd = r.breakdown.set_index("channel")
    assert r.value == 1000
    assert bd.value["paid_search"] == 600
    assert pd.isna(bd.value["organic_search"])  # spend but no new customers
    assert M.cac(tiny, "2025-10").value is None


def test_logo_churn(tiny):
    r = M.logo_churn(tiny, NOV, "plan")
    assert r.value == pytest.approx(100 / 3)
    assert r.breakdown.set_index("plan").value["pro"] == 100  # attributed to the plan they left


def test_nrr(tiny):
    assert M.nrr(tiny, NOV).value == pytest.approx(100 * 950 / 1100)


def test_gross_margin(tiny):
    assert M.gross_margin(tiny, NOV).value == pytest.approx(80)


def test_cac_payback(tiny):
    # CAC 1000 / (new ARPA 300 x GM 0.8)
    assert M.cac_payback(tiny, NOV).value == pytest.approx(1000 / 240)


def test_burn_cash_runway(tiny):
    assert M.net_burn(tiny, "2025-10").value == 1600
    assert M.net_burn(tiny, NOV).value == 2000  # 3,250 expenses - 1,250 MRR
    assert M.cash_balance(tiny, NOV).value == 6400
    assert M.runway(tiny, NOV).value == pytest.approx(6400 / 1800)
    assert M.runway(tiny, "2025-10").value == pytest.approx(8400 / 1600)


def test_supporting_values(tiny):
    assert M.arpa(tiny, NOV).value == pytest.approx(1250 / 3)
    assert M.burn_multiple(tiny, NOV).value == pytest.approx(2000 / 1800)


def test_formatting():
    assert M.fmt_money(216_820) == "$216,820"
    assert M.fmt_money(-5000) == "-$5,000"
    assert M.fmt_pct(2.84) == "2.8%"
    assert M.fmt_months(7.26) == "7.3 mo"


def test_registry_has_ten_core_metrics():
    assert sum(cfg["core"] for cfg in M.METRICS.values()) == 10


# --- generated data ---

@pytest.fixture(scope="module")
def data():
    return M.load_data()


def test_bridge_sums_to_mrr_change(data):
    for m in data.window:
        bd = M.mrr_bridge(data, m).breakdown.set_index("component").mrr
        change = M.mrr(data, m).value - M.mrr(data, M.prev_month(m)).value
        assert round(bd.new + bd.expansion - bd.contraction - bd.churned, 2) == round(change, 2), m


def test_marketing_expense_matches_spend(data):
    mkt = data.expenses[data.expenses.category == "marketing"].set_index("month").amount
    spend = data.spend.groupby("month").spend.sum()
    pd.testing.assert_series_equal(mkt.round(2), spend.round(2), check_names=False)


def test_cash_rolls_forward(data):
    burn = sum(M.net_burn(data, m).value for m in data.window)
    assert M.cash_balance(data, data.window[-1]).value == pytest.approx(data.company["opening_cash"] - burn)


def test_opening_mrr_in_range(data):
    assert 786_000 <= M.mrr(data, "2025-09").value <= 834_000


SANITY = {  # Oct 2025 - Jan 2026 averages, before any story
    "mom_growth": (3, 7), "logo_churn": (2.3, 3.3), "cac": (2600, 3800),
    "gross_margin": (62, 70), "cac_payback": (5, 9), "runway": (18, 36),
}


@pytest.mark.parametrize("metric,bounds", SANITY.items())
def test_baseline_sanity_ranges(data, metric, bounds):
    avg = M.series(data, metric, "2025-10", "2026-01").value.mean()
    assert bounds[0] <= avg <= bounds[1], (metric, round(avg, 2))


def test_matches_independent_story_calculations(data, raw):
    """metrics.py and the pandas code in conftest.py must agree."""
    for m in data.window:
        bd = M.mrr_bridge(data, m).breakdown.set_index("component").mrr
        for comp in M.COMPONENTS:
            assert bd[comp] == pytest.approx(raw.bridge.loc[m, comp]), (m, comp)
        assert M.cac(data, m).value == pytest.approx(raw.cac([m]))
        assert M.logo_churn(data, m).value == pytest.approx(100 * raw.bridge.loc[m, "logo_churn"])


def test_series_with_breakdown(data):
    df = M.series(data, "cac", "2026-06", "2026-09", breakdown="channel")
    assert set(df.channel) == set(data.spend.channel)
    assert len(df) == 4 * 5


def test_cohort_retention_shape(data):
    heat = M.cohort_retention(data)
    assert list(heat.index) == data.window
    assert heat.iloc[:, 0].dropna().eq(100).all()


# --- guardrail: the app and agent never see the answer key ---

@pytest.mark.parametrize("name", ["app.py", "agent.py", "metrics.py", "prompts.py"])
def test_no_answer_key_access(name):
    path = ROOT / name
    if not path.exists():
        pytest.skip(f"{name} not built yet")
    assert not re.search(r"generate_data|answer_key|STORIES", path.read_text())
