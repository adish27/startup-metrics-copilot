"""The three planted stories must be detectable in the data.

If one fails, tune that story's strength in STORIES, never these thresholds.
"""

import numpy as np

BASE = ("2025-10", "2026-01")


# --- Story 1: Pro price increase ---

def test_s1_expansion_spikes_in_mar_and_apr(raw):
    base = raw.bridge.loc[raw.window(*BASE), "expansion"].mean()
    for m in ("2026-03", "2026-04"):
        assert raw.bridge.loc[m, "expansion"] >= 2.5 * base, m


def test_s1_expansion_comes_from_pro_accounts_without_plan_change(raw):
    for prev, m in (("2026-02", "2026-03"), ("2026-03", "2026-04")):
        a, b = raw.mrr[prev], raw.mrr[m]
        expanded = (a > 0) & (b > a)
        stayed_pro = (raw.plan[prev] == "pro") & (raw.plan[m] == "pro")
        delta = b - a
        assert delta[expanded & stayed_pro].sum() >= 0.8 * delta[expanded].sum(), m


def test_s1_logo_churn_rises_in_apr(raw):
    base = raw.bridge.loc[raw.window(*BASE), "logo_churn"].mean()
    assert raw.bridge.loc["2026-04", "logo_churn"] >= base + 0.008


# --- Story 2: paid social scale-up ---

def test_s2_blended_cac_rises_from_june(raw):
    before, after = raw.window("2026-01", "2026-05"), raw.window("2026-06", "2026-09")
    assert raw.cac(after) >= 1.2 * raw.cac(before)


def test_s2_cac_increase_isolated_to_paid_social(raw):
    before, after = raw.window("2025-10", "2026-05"), raw.window("2026-06", "2026-09")
    assert raw.cac(after, "paid_social") >= 2 * raw.cac(before, "paid_social")
    for channel in set(raw.spend.channel) - {"paid_social"}:
        change = raw.cac(after, channel) / raw.cac(before, channel) - 1
        assert abs(change) < 0.20, (channel, round(change, 3))


def test_s2_cac_payback_lengthens(raw):
    before = np.mean([raw.cac_payback(m) for m in raw.window("2026-01", "2026-05")])
    after = np.mean([raw.cac_payback(m) for m in raw.window("2026-06", "2026-09")])
    assert after >= before + 1.5


# --- Story 3: whale churn ---

WHALE = "A00042"


def test_s3_whale_contracts_in_may_then_leaves(raw):
    whale = raw.mrr.loc[WHALE]
    assert whale["2026-04"] - whale["2026-05"] == 13_000
    assert whale["2026-07"] > 0
    assert (whale[[m for m in raw.months if m >= "2026-08"]] == 0).all()


def test_s3_churned_mrr_spikes_in_aug(raw):
    others = raw.bridge.drop("2026-08")["churned"].mean()
    assert raw.bridge.loc["2026-08", "churned"] >= 4 * others


def test_s3_revenue_drops_while_logo_churn_stays_normal(raw):
    assert raw.bridge.loc["2026-08", "mom_growth"] < 0
    normal = raw.bridge.loc[raw.window("2026-01", "2026-07"), "logo_churn"].mean()
    assert abs(raw.bridge.loc["2026-08", "logo_churn"] - normal) <= 0.01
