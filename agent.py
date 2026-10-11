"""Read-only analysis tools over metrics.py, and the LangGraph ReAct agent that uses them.

The LLM never sees raw CSVs: it can only call these tools, which return compact JSON.
"""

import json
import math
import os
import threading
import uuid
from functools import lru_cache

import numpy as np
import pandas as pd

import metrics as M
from prompts import SYSTEM_PROMPT

MAX_TOOL_CALLS = 15
DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}
FIRST, LAST = "2025-10", "2026-09"


@lru_cache(maxsize=1)
def get_data() -> M.Data:
    return M.load_data()


# --- JSON helpers ---

def _round(v, unit: str):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, (np.integer, np.floating)):
        v = v.item()
    if isinstance(v, float):
        return round(v) if unit.startswith("$") and abs(v) >= 100 else round(v, 2)
    return v


def _records(df: pd.DataFrame, unit: str) -> list[dict]:
    return [{k: _round(v, unit) for k, v in row.items()} for row in df.to_dict("records")]


def _check_metric(metric: str) -> dict | None:
    if metric not in M.METRICS:
        return {"error": f"Unknown metric '{metric}'. Call list_metrics for valid names."}
    return None


def _check_breakdown(metric: str, breakdown: str | None) -> dict | None:
    allowed = M.METRICS[metric]["breakdowns"]
    if breakdown and breakdown not in allowed:
        return {"error": f"'{metric}' supports breakdowns {allowed or 'none'}, not '{breakdown}'."}
    return None


# --- tool implementations (pure; tested directly) ---

def list_metrics() -> dict:
    return {"metrics": [
        {"name": k, "label": c["label"], "category": c["category"], "unit": c["unit"],
         "definition": c["formula"], "breakdowns": c["breakdowns"], "core": c["core"]}
        for k, c in M.METRICS.items()
    ], "months_available": f"{FIRST} to {LAST}"}


def get_metric(metric: str, start_month: str = FIRST, end_month: str = LAST,
               breakdown: str | None = None) -> dict:
    if err := _check_metric(metric) or _check_breakdown(metric, breakdown):
        return err
    unit = M.METRICS[metric]["unit"]
    df = M.series(get_data(), metric, start_month, end_month, breakdown)
    return {"metric": metric, "unit": unit, "breakdown": breakdown, "rows": _records(df, unit)}


def get_mrr_bridge(month: str, breakdown: str | None = None) -> dict:
    data = get_data()
    r = M.mrr_bridge(data, month, breakdown)
    out = {"month": month, "unit": "$", "net_new_mrr": _round(r.value, "$"),
           "mrr_before": _round(M.mrr(data, M.prev_month(month)).value, "$"),
           "mrr_after": _round(M.mrr(data, month).value, "$")}
    key = "components" if breakdown in (None, "component") else f"by_{breakdown}"
    out[key] = _records(r.breakdown, "$")
    return out


def top_account_changes(month: str, component: str | None = None, n: int = 10) -> dict:
    data = get_data()
    ch = M.account_changes(data, month)
    ch = ch[ch.component != "flat"]
    if component:
        ch = ch[ch.component == component]
    total_before = M.mrr(data, M.prev_month(month)).value
    # how accounts moved between plans: reveals price changes (same plan, different MRR)
    transitions = (ch.assign(plan_before=ch.plan_before.fillna("none"), plan_after=ch.plan_after.fillna("none"))
                   .groupby(["component", "plan_before", "plan_after"])
                   .agg(accounts=("change", "size"), total_change=("change", "sum"),
                        median_change=("change", "median"))
                   .reset_index().sort_values("total_change", key=abs, ascending=False))
    top = ch.reindex(ch.change.abs().sort_values(ascending=False).index).head(n).reset_index()
    top["share_of_prior_mrr_pct"] = 100 * top.mrr_before / total_before
    cols = ["account_id", "account_name", "segment", "channel", "component", "plan_before", "plan_after",
            "mrr_before", "mrr_after", "change", "share_of_prior_mrr_pct"]
    return {"month": month, "unit": "$", "component": component or "all",
            "accounts_changed": int(len(ch)),
            "plan_transitions": _records(transitions.head(12), "$"),
            "top_accounts": _records(top[cols], "$")}


def _period_months(start: str, end: str) -> list[str]:
    return [m for m in get_data().window if start <= m <= end]


def _cac_period(months: list[str], channel: str | None = None) -> dict:
    """Pooled CAC: total spend / total new accounts over the period."""
    data = get_data()
    spend = data.spend[data.spend.month.isin(months)]
    new = pd.concat([M.account_changes(data, m) for m in months])
    new = new[new.component == "new"]
    if channel:
        spend, new = spend[spend.channel == channel], new[new.channel == channel]
    s, n = spend.spend.sum(), len(new)
    return {"value": s / n if n else None, "spend": s, "new_accounts": n}


def compare_periods(metric: str, period_a_start: str, period_a_end: str,
                    period_b_start: str, period_b_end: str, breakdown: str | None = None) -> dict:
    if err := _check_metric(metric) or _check_breakdown(metric, breakdown):
        return err
    unit = M.METRICS[metric]["unit"]
    a, b = _period_months(period_a_start, period_a_end), _period_months(period_b_start, period_b_end)
    rows = []
    if metric == "cac":
        keys = sorted(get_data().spend.channel.unique()) if breakdown == "channel" else [None]
        for k in keys:
            pa, pb = _cac_period(a, k), _cac_period(b, k)
            rows.append({"channel": k or "blended", "period_a": pa["value"], "period_b": pb["value"],
                         "spend_a": pa["spend"], "spend_b": pb["spend"],
                         "new_accounts_a": pa["new_accounts"], "new_accounts_b": pb["new_accounts"]})
        method = "pooled: total spend / total new accounts in each period"
    else:
        sa = M.series(get_data(), metric, period_a_start, period_a_end, breakdown)
        sb = M.series(get_data(), metric, period_b_start, period_b_end, breakdown)
        if breakdown:
            ga, gb = sa.groupby(breakdown).value.mean(), sb.groupby(breakdown).value.mean()
            rows = [{breakdown: k, "period_a": ga.get(k), "period_b": gb.get(k)} for k in ga.index.union(gb.index)]
        else:
            rows = [{"period_a": sa.value.mean(), "period_b": sb.value.mean()}]
        method = "mean of monthly values"
    for r in rows:
        pa, pb = r["period_a"], r["period_b"]
        ok = pa is not None and pb is not None and not pd.isna(pa) and not pd.isna(pb)
        r["change_pct"] = 100 * (pb - pa) / abs(pa) if ok and pa else None
        if ok and unit.startswith("%"):
            r["change_pts"] = pb - pa
    return {"metric": metric, "unit": unit, "method": method,
            "period_a": f"{period_a_start} to {period_a_end}", "period_b": f"{period_b_start} to {period_b_end}",
            "rows": [{k: _round(v, unit if not k.startswith("change") else "") for k, v in r.items()} for r in rows]}


ANOMALY_METRICS = ["mrr", "mom_growth", "net_new_mrr", "trial_conversion", "cac", "logo_churn", "nrr",
                   "gross_margin", "cac_payback", "runway", "arpa", "net_burn"]
REL_THRESHOLD, PTS_THRESHOLD = 0.25, 0.8
MATERIALITY_PCT_OF_MRR = 0.5  # $ items must move at least 0.5% of MRR to count


def _anomaly_series(data: M.Data) -> dict[str, tuple[str, pd.Series]]:
    out = {}
    for k in ANOMALY_METRICS:
        s = M.series(data, k)
        out[k] = (M.METRICS[k]["unit"], s.set_index("month").value)
    bridge = pd.DataFrame({m: M.mrr_bridge(data, m).breakdown.set_index("component").mrr for m in data.window}).T
    for comp in M.COMPONENTS:
        out[f"bridge:{comp}"] = ("$", bridge[comp])
    spend = data.spend.pivot_table(index="month", columns="channel", values="spend", aggfunc="sum")
    for ch in spend.columns:
        out[f"marketing_spend:{ch}"] = ("$", spend[ch])
    for ch, g in M.series(data, "cac", breakdown="channel").groupby("channel"):
        out[f"cac:{ch}"] = ("$ per customer", g.set_index("month").value)
    return out


def detect_anomalies(start_month: str = FIRST, end_month: str = LAST) -> dict:
    """Flag values that deviate from the median of the prior 3 months by >25% (relative),
    or by >0.8 points for % metrics. $ items must also be material (>= 0.5% of MRR)."""
    data = get_data()
    mrr_by_month = M.series(data, "mrr").set_index("month").value
    flags = []
    for name, (unit, s) in _anomaly_series(data).items():
        s = s.astype(float)
        for i, m in enumerate(s.index):
            if i < 3 or not (start_month <= m <= end_month) or pd.isna(s[m]):
                continue
            base = s.iloc[i - 3:i].median()
            if pd.isna(base):
                continue
            if unit.startswith("%"):
                dev = s[m] - base
                score = abs(dev) / PTS_THRESHOLD
                rel = None
            else:
                if base == 0:
                    continue
                dev = s[m] - base
                rel = dev / abs(base)
                score = abs(rel) / REL_THRESHOLD
                if unit.startswith("$") and not unit.startswith("$ per") and \
                        abs(dev) < MATERIALITY_PCT_OF_MRR / 100 * mrr_by_month[m]:
                    continue
            if score > 1:
                flags.append({"month": m, "series": name, "unit": unit, "value": _round(s[m], unit),
                              "prior_3mo_median": _round(base, unit),
                              "deviation_pct" if rel is not None else "deviation_pts":
                                  round(float(100 * rel), 1) if rel is not None else round(float(dev), 2),
                              "_score": score})
    flags.sort(key=lambda f: f["_score"], reverse=True)
    for f in flags:
        f.pop("_score")
    return {"window": f"{start_month} to {end_month}",
            "rule": "deviation from median of prior 3 months: >25% relative, or >0.8 pts for % metrics; "
                    "$ items must move >= 0.5% of MRR. Sorted by size relative to threshold.",
            "count": len(flags), "anomalies": flags[:25]}


def runway_scenario(monthly_spend_change: float = 0.0, mrr_growth_rate: float | None = None) -> dict:
    """Runway under a monthly spend change ($, negative = cut) and MRR growth (% per month).

    Static runway = cash / (avg net burn of last 3 months + spend change), same basis as the dashboard.
    Projection rolls cash forward month by month: MRR grows at mrr_growth_rate, COGS stays the same
    % of MRR, payroll grows at its observed monthly rate, other costs stay flat."""
    data = get_data()
    last, prev = data.window[-1], data.window[-2]
    if mrr_growth_rate is None:
        mrr_growth_rate = float(np.mean(M.series(data, "mom_growth", data.window[-3], last).value))
    exp = data.expenses[data.expenses.month == last].set_index("category").amount
    exp_prev = data.expenses[data.expenses.month == prev].set_index("category").amount
    payroll_growth = exp["payroll"] / exp_prev["payroll"] - 1
    mrr0 = M.mrr(data, last).value
    cogs_rate = (exp["ai_inference"] + exp["qc_ops"]) / mrr0
    other_fixed = exp.drop(["ai_inference", "qc_ops", "payroll"]).sum()
    cash0 = M.cash_balance(data, last).value
    avg_burn = float(np.mean([M.net_burn(data, m).value for m in data.window[-3:]]))

    def static(change):
        burn = avg_burn + change
        return cash0 / burn if burn > 0 else None  # None: not burning cash

    def project(change):
        cash, mrr_t, payroll = cash0, mrr0, exp["payroll"]
        for t in range(1, 121):
            mrr_t *= 1 + mrr_growth_rate / 100
            payroll *= 1 + payroll_growth
            burn = payroll + other_fixed + change + cogs_rate * mrr_t - mrr_t
            if burn <= 0:
                return {"cash_out_in_months": None, "breakeven_in_months": t, "cash_at_breakeven": _round(cash, "$")}
            if cash <= burn:
                return {"cash_out_in_months": round(float(t - 1 + cash / burn), 1), "breakeven_in_months": None}
            cash -= burn
        return {"cash_out_in_months": None, "breakeven_in_months": None}

    return {"unit": "months", "as_of": last, "cash": _round(cash0, "$"),
            "avg_net_burn_last_3_months": _round(avg_burn, "$"),
            "static_runway_current": _round(static(0.0), "months"),
            "static_runway_scenario": _round(static(monthly_spend_change), "months"),
            "projection_current": project(0.0),
            "projection_scenario": project(monthly_spend_change),
            "assumptions": {"monthly_spend_change": monthly_spend_change,
                            "mrr_growth_rate_pct_per_month": round(mrr_growth_rate, 2),
                            "payroll_growth_pct_per_month": round(100 * payroll_growth, 2),
                            "variable_cogs_pct_of_mrr": round(100 * cogs_rate, 1)}}


TOOL_FUNCS = [list_metrics, get_metric, get_mrr_bridge, top_account_changes,
              compare_periods, detect_anomalies, runway_scenario]


# --- tool budget (max calls per request) ---

class ToolBudget:
    def __init__(self, limit: int = MAX_TOOL_CALLS):
        self.limit, self.used, self._lock = limit, 0, threading.Lock()

    def take(self) -> bool:
        with self._lock:
            self.used += 1
            return self.used <= self.limit


_budget = ToolBudget()


def _as_tool(fn):
    from langchain_core.tools import StructuredTool

    def run(**kwargs):
        if not _budget.take():
            return json.dumps({"error": f"Tool budget of {MAX_TOOL_CALLS} calls exhausted. "
                                        "Answer now using the results you already have."})
        try:
            return json.dumps(fn(**kwargs), default=str)
        except Exception as e:  # report bad arguments back to the model instead of crashing
            return json.dumps({"error": f"{type(e).__name__}: {e}"})

    return StructuredTool.from_function(func=run, name=fn.__name__, description=TOOL_DOCS[fn.__name__],
                                        args_schema=_schema_for(fn))


TOOL_DOCS = {
    "list_metrics": "List all metrics with name, category, unit, definition, and allowed breakdowns.",
    "get_metric": "Monthly series for one metric (YYYY-MM months), optionally split by a breakdown "
                  "(channel, plan, segment, component, category - see list_metrics for what each metric allows).",
    "get_mrr_bridge": "Decompose one month's MRR change into new, expansion, contraction, churned ($ and account "
                      "counts), optionally split by plan or segment.",
    "top_account_changes": "Accounts with the largest MRR change vs prior month (name, plan before/after, MRR "
                           "before/after, share of prior MRR), plus a summary of plan transitions. Optional "
                           "component filter: new, expansion, contraction, churned.",
    "compare_periods": "Compare a metric's average between two month ranges, optionally per breakdown value. "
                       "CAC is pooled (total spend / total new accounts) and includes spend and new-account counts.",
    "detect_anomalies": "Flag months where a metric, MRR bridge component, channel spend, or channel CAC deviates "
                        "from the median of the prior 3 months. Sorted by size. Start here for open questions.",
    "runway_scenario": "Project runway (months) from Sep 2026 if monthly spend changes by monthly_spend_change "
                       "dollars (negative = cut) and MRR grows at mrr_growth_rate % per month (default: trailing "
                       "3-month average). Compares against an unchanged-spend baseline.",
}


def _schema_for(fn):
    """Pydantic args schema from the function signature."""
    import inspect
    from typing import Optional

    from pydantic import create_model

    fields = {}
    for name, p in inspect.signature(fn).parameters.items():
        ann = p.annotation
        default = ... if p.default is inspect.Parameter.empty else p.default
        if default is None:
            ann = Optional[ann.__args__[0] if hasattr(ann, "__args__") else ann]
        fields[name] = (ann, default)
    return create_model(f"{fn.__name__}_args", **fields)


# --- agent ---

@lru_cache(maxsize=1)
def build_agent():
    from langchain_anthropic import ChatAnthropic
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.prebuilt import create_react_agent

    model_name = os.environ.get("LLM_MODEL") or DEFAULT_MODEL
    kwargs = {}
    if model_name in FALLBACK_MODELS:
        # on a safety refusal, the API re-runs the request on a fallback model
        kwargs = {"betas": ["server-side-fallback-2026-07-01"], "model_kwargs": {"fallbacks": "default"}}
    llm = ChatAnthropic(model=model_name, max_tokens=16000, **kwargs)
    tools = [_as_tool(f) for f in TOOL_FUNCS]
    # the checkpointer keeps each chat's full message history, append-only
    return create_react_agent(llm, tools, prompt=SYSTEM_PROMPT, checkpointer=InMemorySaver())


def new_thread_id() -> str:
    return str(uuid.uuid4())


def _short(text: str, limit: int = 400) -> str:
    return text if len(text) <= limit else text[:limit] + " ..."


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def run_agent(question: str, thread_id: str) -> tuple[str, list[dict]]:
    """Ask the agent a question in a chat thread. Returns (answer markdown, tool trace)."""
    from langchain_core.messages import AIMessage, ToolMessage
    from langgraph.errors import GraphRecursionError

    global _budget
    _budget = ToolBudget()
    agent = build_agent()
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 2 * MAX_TOOL_CALLS + 10}
    before = len(agent.get_state(config).values.get("messages", []))
    try:
        result = agent.invoke({"messages": [("user", question)]}, config)
    except GraphRecursionError:
        return "Stopped: the agent hit its step limit before finishing. Try a narrower question.", []
    new = result["messages"][before:]

    results = {m.tool_call_id: m.content for m in new if isinstance(m, ToolMessage)}
    trace = [{"tool": tc["name"], "args": tc["args"], "result": _short(str(results.get(tc["id"], "")))}
             for m in new if isinstance(m, AIMessage) for tc in m.tool_calls]
    answer = next((_text(m.content) for m in reversed(new) if isinstance(m, AIMessage) and _text(m.content)), "")
    return answer or "The agent returned no answer.", trace
