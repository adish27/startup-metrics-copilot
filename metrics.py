"""Metric definitions for Closepath AI. Pure functions over loaded data.

Every metric function has the signature `fn(data, month, breakdown=None)` and
returns a MetricResult. Percent metrics are on a 0-100 scale.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
COMPONENTS = ["new", "expansion", "contraction", "churned"]


@dataclass
class MetricResult:
    value: float | None
    unit: str
    breakdown: pd.DataFrame | None = None


@dataclass
class Data:
    accounts: pd.DataFrame
    subs: pd.DataFrame
    spend: pd.DataFrame
    expenses: pd.DataFrame
    company: dict
    mrr_wide: pd.DataFrame = field(init=False)   # account x month, 0 = not paying
    plan_wide: pd.DataFrame = field(init=False)  # account x month, NaN = not paying
    months: list[str] = field(init=False)        # all snapshot months, incl. opening
    _cache: dict = field(init=False, default_factory=dict, repr=False)

    def __post_init__(self):
        self.mrr_wide = self.subs.pivot_table(index="account_id", columns="month", values="mrr",
                                              fill_value=0, aggfunc="sum")
        self.plan_wide = self.subs.pivot_table(index="account_id", columns="month", values="plan",
                                               aggfunc="first")
        self.months = sorted(self.subs["month"].unique())

    @property
    def window(self) -> list[str]:
        start, end = self.company["window_start"], self.company["window_end"]
        return [m for m in self.months if start <= m <= end]


def build_data(accounts, subs, spend, expenses, company) -> Data:
    accounts = accounts.copy()
    for col in ("trial_start_date", "conversion_date", "churn_date"):
        accounts[col] = accounts[col].astype("string")
    accounts["trial_month"] = accounts["trial_start_date"].str[:7]
    expenses = expenses.copy()
    expenses["is_cogs"] = expenses["is_cogs"].astype(str).str.lower() == "true"
    return Data(accounts.set_index("account_id", drop=False), subs, spend, expenses, company)


def load_data(data_dir: Path = DATA_DIR) -> Data:
    return build_data(
        pd.read_csv(data_dir / "accounts.csv"),
        pd.read_csv(data_dir / "subscriptions_monthly.csv"),
        pd.read_csv(data_dir / "marketing_spend.csv"),
        pd.read_csv(data_dir / "expenses.csv"),
        json.loads((data_dir / "company.json").read_text()),
    )


def filter_segment(data: Data, segment: str | None) -> Data:
    """Keep only one segment's accounts. Spend, expenses and cash stay company-wide,
    so CAC, payback, gross margin and cash metrics should use unfiltered data."""
    if not segment or segment == "all":
        return data
    ids = data.accounts.index[data.accounts["segment"] == segment]
    return Data(data.accounts.loc[ids], data.subs[data.subs["account_id"].isin(ids)],
                data.spend, data.expenses, data.company)


def prev_month(month: str) -> str:
    return str(pd.Period(month, freq="M") - 1)


# --- building block: per-account change between m-1 and m ---

def account_changes(data: Data, month: str) -> pd.DataFrame:
    """One row per account paying in m-1 or m, labelled new/expansion/contraction/churned/flat."""
    key = ("changes", month)
    if key in data._cache:
        return data._cache[key]
    prev = prev_month(month)
    cur = data.mrr_wide[month] if month in data.mrr_wide else pd.Series(0, index=data.mrr_wide.index)
    before = data.mrr_wide[prev] if prev in data.mrr_wide else pd.Series(0, index=data.mrr_wide.index)
    df = pd.DataFrame({"mrr_before": before, "mrr_after": cur})
    df = df[(df.mrr_before > 0) | (df.mrr_after > 0)].copy()
    df["change"] = df.mrr_after - df.mrr_before
    df["component"] = np.select(
        [(df.mrr_before == 0), (df.mrr_after == 0), (df.change > 0), (df.change < 0)],
        ["new", "churned", "expansion", "contraction"], default="flat")
    plans = data.plan_wide
    df["plan_before"] = plans[prev].reindex(df.index) if prev in plans else np.nan
    df["plan_after"] = plans[month].reindex(df.index) if month in plans else np.nan
    df["plan"] = df["plan_after"].fillna(df["plan_before"])
    acc = data.accounts.reindex(df.index)
    df["account_name"] = acc["account_name"]
    df["segment"] = acc["segment"]
    df["channel"] = acc["acquisition_channel"]
    data._cache[key] = df
    return df


def _group(df: pd.DataFrame, by: str, value) -> pd.DataFrame:
    out = df.groupby(by).apply(value, include_groups=False)
    return out.rename("value").reset_index()


def _pct(num: float, den: float) -> float | None:
    return None if not den else 100 * num / den


# --- 1. MRR / ARR ---

def mrr(data: Data, month: str, breakdown: str | None = None) -> MetricResult:
    ch = account_changes(data, month)
    paying = ch[ch.mrr_after > 0]
    bd = _group(paying, breakdown, lambda g: g.mrr_after.sum()) if breakdown else None
    return MetricResult(float(paying.mrr_after.sum()), "$", bd)


def arr(data: Data, month: str, breakdown: str | None = None) -> MetricResult:
    r = mrr(data, month, breakdown)
    bd = r.breakdown.assign(value=r.breakdown.value * 12) if r.breakdown is not None else None
    return MetricResult(12 * r.value, "$", bd)


# --- 2. MoM MRR growth ---

def mom_growth(data: Data, month: str, breakdown: str | None = None) -> MetricResult:
    before = account_changes(data, month).mrr_before.sum()
    return MetricResult(_pct(mrr(data, month).value - before, before), "%")


# --- 3. Net new MRR (bridge) ---

def mrr_bridge(data: Data, month: str, breakdown: str | None = None) -> MetricResult:
    """Value = net new MRR. Breakdown: component rows (default) or plan/segment x component."""
    ch = account_changes(data, month)
    moved = ch[ch.component != "flat"].assign(amount=lambda d: d.change.abs())
    if breakdown in (None, "component"):
        g = moved.groupby("component").agg(mrr=("amount", "sum"), accounts=("amount", "size"))
        bd = g.reindex(COMPONENTS, fill_value=0).reset_index()
    else:
        bd = (moved.pivot_table(index=breakdown, columns="component", values="amount",
                                aggfunc="sum", fill_value=0)
              .reindex(columns=COMPONENTS, fill_value=0).reset_index())
        bd["net"] = bd.new + bd.expansion - bd.contraction - bd.churned
    return MetricResult(float(ch.change.sum()), "$", bd)


# --- 4. Trial-to-paid conversion ---

def trial_conversion(data: Data, month: str, breakdown: str | None = None) -> MetricResult:
    trials = data.accounts[data.accounts.trial_month == month]
    if breakdown == "channel":
        breakdown = "acquisition_channel"
    bd = None
    if breakdown:
        bd = _group(trials, breakdown, lambda g: _pct(g.converted.sum(), len(g)))
        bd = bd.rename(columns={"acquisition_channel": "channel"})
    return MetricResult(_pct(trials.converted.sum(), len(trials)), "%", bd)


# --- 5. CAC ---

def _new_accounts(data: Data, month: str) -> pd.DataFrame:
    ch = account_changes(data, month)
    return ch[ch.component == "new"]


def _spend(data: Data, month: str) -> pd.DataFrame:
    return data.spend[data.spend.month == month]


def cac(data: Data, month: str, breakdown: str | None = None) -> MetricResult:
    """Marketing spend only (no sales salaries) / new paying accounts."""
    new, spend = _new_accounts(data, month), _spend(data, month)
    bd = None
    if breakdown == "channel":
        counts = new.groupby("channel").size()
        bd = spend.groupby("channel").spend.sum().rename("spend").to_frame()
        bd["new_accounts"] = counts.reindex(bd.index, fill_value=0)
        bd["value"] = [s / n if n else None for s, n in zip(bd.spend, bd.new_accounts)]
        bd = bd.reset_index()
    return MetricResult(spend.spend.sum() / len(new) if len(new) else None, "$ per customer", bd)


# --- 6. Logo churn ---

def logo_churn(data: Data, month: str, breakdown: str | None = None) -> MetricResult:
    ch = account_changes(data, month)
    base = ch[ch.mrr_before > 0].copy()
    base["plan"] = base["plan_before"]  # churn is attributed to the plan they left from
    bd = _group(base, breakdown, lambda g: _pct((g.component == "churned").sum(), len(g))) if breakdown else None
    return MetricResult(_pct((base.component == "churned").sum(), len(base)), "% per month", bd)


# --- 7. Net revenue retention ---

def nrr(data: Data, month: str, breakdown: str | None = None) -> MetricResult:
    """Existing accounts only: their MRR in m / their MRR in m-1."""
    base = account_changes(data, month)
    base = base[base.mrr_before > 0]
    bd = _group(base, breakdown, lambda g: _pct(g.mrr_after.sum(), g.mrr_before.sum())) if breakdown else None
    return MetricResult(_pct(base.mrr_after.sum(), base.mrr_before.sum()), "%", bd)


# --- 8. Gross margin ---

def _cogs(data: Data, month: str) -> float:
    e = data.expenses[data.expenses.month == month]
    return float(e.loc[e.is_cogs, "amount"].sum())


def gross_margin(data: Data, month: str, breakdown: str | None = None) -> MetricResult:
    revenue = mrr(data, month).value
    return MetricResult(_pct(revenue - _cogs(data, month), revenue), "%")


# --- 9. CAC payback ---

def cac_payback(data: Data, month: str, breakdown: str | None = None) -> MetricResult:
    """CAC / (new-customer ARPA x gross margin)."""
    new, gm = _new_accounts(data, month), gross_margin(data, month).value
    total = cac(data, month)

    def payback(c, new_mrr, n):
        if c is None or not n or not new_mrr or gm is None:
            return None
        return c / ((new_mrr / n) * gm / 100)

    bd = None
    if breakdown == "channel":
        c_bd = cac(data, month, "channel").breakdown.set_index("channel")
        new_mrr = new.groupby("channel").mrr_after.sum().reindex(c_bd.index, fill_value=0)
        bd = pd.DataFrame({"value": [payback(c, m, n) for c, m, n in
                                     zip(c_bd.value, new_mrr, c_bd.new_accounts)]},
                          index=c_bd.index).reset_index()
    return MetricResult(payback(total.value, new.mrr_after.sum(), len(new)), "months", bd)


# --- 10. Net burn, cash, runway ---

def net_burn(data: Data, month: str, breakdown: str | None = None) -> MetricResult:
    """Total expenses minus revenue (MRR). Breakdown: expense category."""
    e = data.expenses[data.expenses.month == month]
    bd = e.groupby("category").amount.sum().rename("value").reset_index() if breakdown == "category" else None
    return MetricResult(float(e.amount.sum()) - mrr(data, month).value, "$", bd)


def cash_balance(data: Data, month: str, breakdown: str | None = None) -> MetricResult:
    months = [m for m in data.window if m <= month]
    burn = sum(net_burn(data, m).value for m in months)
    return MetricResult(data.company["opening_cash"] - burn, "$")


def runway(data: Data, month: str, breakdown: str | None = None) -> MetricResult:
    """Cash / average net burn over the last 3 months (fewer at the start of the window)."""
    recent = [m for m in data.window if m <= month][-3:]
    avg_burn = np.mean([net_burn(data, m).value for m in recent])
    if avg_burn <= 0:
        return MetricResult(None, "months")  # not burning: runway is unlimited
    return MetricResult(cash_balance(data, month).value / avg_burn, "months")


# --- supporting values ---

def arpa(data: Data, month: str, breakdown: str | None = None) -> MetricResult:
    ch = account_changes(data, month)
    paying = ch[ch.mrr_after > 0]
    bd = _group(paying, breakdown, lambda g: g.mrr_after.mean()) if breakdown else None
    return MetricResult(float(paying.mrr_after.mean()), "$ per account", bd)


def burn_multiple(data: Data, month: str, breakdown: str | None = None) -> MetricResult:
    """Net burn / net new ARR. None when net new ARR is not positive."""
    net_new_arr = 12 * mrr_bridge(data, month).value
    return MetricResult(net_burn(data, month).value / net_new_arr if net_new_arr > 0 else None, "x")


def trials_started(data: Data, month: str, breakdown: str | None = None) -> MetricResult:
    trials = data.accounts[data.accounts.trial_month == month]
    bd = None
    if breakdown == "channel":
        bd = trials.groupby("acquisition_channel").size().rename("value").reset_index()
        bd = bd.rename(columns={"acquisition_channel": "channel"})
    return MetricResult(float(len(trials)), "trials", bd)


def marketing_spend(data: Data, month: str, breakdown: str | None = None) -> MetricResult:
    spend = _spend(data, month)
    bd = spend.groupby("channel").spend.sum().rename("value").reset_index() if breakdown == "channel" else None
    return MetricResult(float(spend.spend.sum()), "$", bd)


def cohort_retention(data: Data) -> pd.DataFrame:
    """Rows = first paying month (in window), columns = months since, values = % of logos still paying."""
    paying = data.mrr_wide > 0
    first = paying.idxmax(axis=1)
    rows = {}
    for cohort in data.window:
        ids = first.index[(first == cohort) & paying[cohort]]
        later = [m for m in data.months if m >= cohort]
        rows[cohort] = [100 * paying.loc[ids, m].mean() if len(ids) else None for m in later]
    width = max(len(v) for v in rows.values())
    return pd.DataFrame({k: v + [None] * (width - len(v)) for k, v in rows.items()}).T.rename_axis("cohort")


# --- registry ---

METRICS = {
    "mrr": dict(fn=mrr, label="MRR", category="Growth", unit="$", core=True, good="up",
                breakdowns=["plan", "segment"], formula="Sum of mrr across paying accounts in month m. ARR = 12 x MRR."),
    "mom_growth": dict(fn=mom_growth, label="MoM MRR growth", category="Growth", unit="%", core=True, good="up",
                       breakdowns=[], formula="(MRR m - MRR m-1) / MRR m-1"),
    "net_new_mrr": dict(fn=mrr_bridge, label="Net new MRR", category="Growth", unit="$", core=True, good="up",
                        breakdowns=["component", "plan", "segment"],
                        formula="New + expansion - contraction - churned, from a per-account diff of m-1 vs m"),
    "trial_conversion": dict(fn=trial_conversion, label="Trial-to-paid", category="Acquisition", unit="%",
                             core=True, good="up", breakdowns=["channel"],
                             formula="Trials started in m that converted / trials started in m"),
    "cac": dict(fn=cac, label="CAC", category="Acquisition", unit="$ per customer", core=True, good="down",
                breakdowns=["channel"],
                formula="Marketing spend in m / new paying accounts in m (marketing spend only, no sales salaries)"),
    "logo_churn": dict(fn=logo_churn, label="Logo churn", category="Retention", unit="% per month", core=True,
                       good="down", breakdowns=["plan", "segment"],
                       formula="Accounts paying in m-1 and not in m / accounts paying in m-1"),
    "nrr": dict(fn=nrr, label="Net revenue retention", category="Retention", unit="%", core=True, good="up",
                breakdowns=["segment", "plan"],
                formula="(MRR m-1 + expansion - contraction - churned) / MRR m-1, existing accounts only"),
    "gross_margin": dict(fn=gross_margin, label="Gross margin", category="Unit economics", unit="%", core=True,
                         good="up", breakdowns=[],
                         formula="(MRR - COGS) / MRR. COGS = hosting + AI inference + human QC ops"),
    "cac_payback": dict(fn=cac_payback, label="CAC payback", category="Unit economics", unit="months",
                        core=True, good="down", breakdowns=["channel"],
                        formula="CAC / (new-customer ARPA x gross margin)"),
    "runway": dict(fn=runway, label="Runway", category="Cash", unit="months", core=True, good="up",
                   breakdowns=[], formula="Cash m / average net burn over the last 3 months"),
    # supporting series
    "arr": dict(fn=arr, label="ARR", category="Growth", unit="$", core=False, good="up",
                breakdowns=["plan", "segment"], formula="12 x MRR"),
    "net_burn": dict(fn=net_burn, label="Net burn", category="Cash", unit="$", core=False, good="down",
                     breakdowns=["category"], formula="Total expenses - revenue (MRR)"),
    "cash_balance": dict(fn=cash_balance, label="Cash balance", category="Cash", unit="$", core=False,
                         good="up", breakdowns=[], formula="Opening cash - cumulative net burn"),
    "arpa": dict(fn=arpa, label="ARPA", category="Growth", unit="$ per account", core=False, good="up",
                 breakdowns=["plan", "segment"], formula="MRR / paying accounts"),
    "burn_multiple": dict(fn=burn_multiple, label="Burn multiple", category="Cash", unit="x", core=False,
                          good="down", breakdowns=[], formula="Net burn / net new ARR"),
    "trials_started": dict(fn=trials_started, label="Trials started", category="Acquisition", unit="trials",
                           core=False, good="up", breakdowns=["channel"], formula="Trials started in month m"),
    "marketing_spend": dict(fn=marketing_spend, label="Marketing spend", category="Acquisition", unit="$",
                            core=False, good="down", breakdowns=["channel"], formula="Marketing spend in month m"),
}


def series(data: Data, metric: str, start: str | None = None, end: str | None = None,
           breakdown: str | None = None) -> pd.DataFrame:
    """Monthly values: columns month, value (or month, <breakdown>, value...)."""
    fn = METRICS[metric]["fn"]
    months = [m for m in data.window if (start is None or m >= start) and (end is None or m <= end)]
    if not breakdown:
        return pd.DataFrame({"month": months, "value": [fn(data, m).value for m in months]})
    frames = [fn(data, m, breakdown).breakdown.assign(month=m) for m in months]
    df = pd.concat(frames, ignore_index=True)
    return df[["month"] + [c for c in df.columns if c != "month"]]


# --- formatting ---

def fmt_money(v: float | None) -> str:
    if v is None or pd.isna(v):
        return "n/a"
    return f"-${abs(v):,.0f}" if v < 0 else f"${v:,.0f}"


def fmt_pct(v: float | None) -> str:
    return "n/a" if v is None or pd.isna(v) else f"{v:.1f}%"


def fmt_months(v: float | None) -> str:
    return "n/a" if v is None or pd.isna(v) else f"{v:.1f} mo"


def fmt(v: float | None, unit: str) -> str:
    if unit.startswith("$"):
        return fmt_money(v)
    if unit.startswith("%"):
        return fmt_pct(v)
    if unit == "months":
        return fmt_months(v)
    return "n/a" if v is None or pd.isna(v) else f"{v:.1f}{unit}"
