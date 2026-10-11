"""Closepath AI metrics dashboard and agent. Run: streamlit run app.py"""

import json
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

import metrics as M

load_dotenv()
st.set_page_config(page_title="Closepath AI Metrics", page_icon="📈", layout="wide")

# --- palette: fixed color per entity, so filters never repaint survivors ---
SLOTS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
CHANNELS = ["organic_search", "referral", "paid_search", "paid_social", "outbound"]
PLANS = ["starter", "pro", "business", "enterprise"]
SEGMENTS = ["broker", "community_lender", "enterprise_lender"]
COLORS = {**dict(zip(CHANNELS, SLOTS)), **dict(zip(PLANS, SLOTS)), **dict(zip(SEGMENTS, SLOTS)),
          "blended": "#52514e",
          "new": "#256abf", "expansion": "#6da7ec", "contraction": "#eb6834", "churned": "#e34948"}
INK = "#52514e"
LABELS = {"organic_search": "Organic search", "referral": "Referral", "paid_search": "Paid search",
          "paid_social": "Paid social (LinkedIn)", "outbound": "Outbound", "starter": "Starter", "pro": "Pro",
          "business": "Business", "enterprise": "Enterprise", "broker": "Broker",
          "community_lender": "Community lender", "enterprise_lender": "Enterprise lender",
          "blended": "Blended", "new": "New", "expansion": "Expansion", "contraction": "Contraction",
          "churned": "Churned"}
SEGMENT_AWARE = {"mrr", "arr", "mom_growth", "net_new_mrr", "trial_conversion", "logo_churn", "nrr", "arpa",
                 "trials_started"}
NO_DATA = "No data for these filters."
LEGEND_ORDER = {"name": [LABELS[k] for k in CHANNELS + ["blended"] + PLANS + SEGMENTS]}


# --- data access (cached) ---

@st.cache_resource
def load(segment: str) -> M.Data:
    return M.filter_segment(M.load_data(), segment)


@st.cache_data
def series(metric: str, segment: str, breakdown: str | None = None) -> pd.DataFrame:
    seg = segment if metric in SEGMENT_AWARE else "all"
    df = M.series(load(seg), metric, breakdown=breakdown)
    df["date"] = pd.to_datetime(df["month"])
    return df


@st.cache_data
def bridge(segment: str) -> pd.DataFrame:
    data = load(segment)
    frames = [M.mrr_bridge(data, m).breakdown.assign(month=m) for m in data.window]
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["month"])
    df["signed"] = df.apply(lambda r: -r.mrr if r.component in ("contraction", "churned") else r.mrr, axis=1)
    return df


@st.cache_data
def cohorts(segment: str) -> pd.DataFrame:
    return M.cohort_retention(load(segment))


def month_label(m: str) -> str:
    return pd.Period(m, freq="M").strftime("%b %Y")


# --- chart helpers ---

def axis_format(unit: str) -> dict:
    if unit.startswith("$"):
        return dict(tickprefix="$", tickformat=",.0f")
    if unit.startswith("%"):
        return dict(ticksuffix="%")
    if unit == "months":
        return dict(ticksuffix=" mo")
    return {}


def hover_format(unit: str) -> str:
    if unit.startswith("$"):
        return "%{y:$,.0f}"
    if unit.startswith("%"):
        return "%{y:.1f}%"
    if unit == "months":
        return "%{y:.1f} mo"
    return "%{y:,.0f}"


def style(fig: go.Figure, title: str, unit: str, y_title: str) -> go.Figure:
    fig.update_layout(title=dict(text=title, font=dict(size=15)), height=340, margin=dict(l=10, r=10, t=50, b=10),
                      legend=dict(orientation="h", y=-0.18, title=None), hovermode="x unified", bargap=0.25)
    fig.update_xaxes(title=None, tickformat="%b<br>%Y", dtick="M1", showgrid=False)
    fig.update_yaxes(title=y_title, **axis_format(unit))
    return fig


def show(fig: go.Figure | None):
    if fig is None:
        st.info(NO_DATA)
    else:
        st.plotly_chart(fig, width="stretch", theme="streamlit")


def in_range(df: pd.DataFrame, months: tuple[str, str]) -> pd.DataFrame:
    return df[(df.month >= months[0]) & (df.month <= months[1])]


def line(df: pd.DataFrame, title: str, unit: str, y_title: str, color: str | None = None) -> go.Figure | None:
    df = df.dropna(subset=["value"])
    if df.empty:
        return None
    df = df.assign(name=df[color].map(LABELS)) if color else df
    fig = px.line(df, x="date", y="value", color="name" if color else None, markers=True,
                  color_discrete_map={LABELS[k]: v for k, v in COLORS.items() if k in LABELS},
                  category_orders=LEGEND_ORDER)
    if not color:
        fig.update_traces(line_color=SLOTS[0])
    fig.update_traces(line_width=2, marker_size=7, hovertemplate=hover_format(unit))
    return style(fig, title, unit, y_title)


def stacked(df: pd.DataFrame, title: str, unit: str, y_title: str, color: str) -> go.Figure | None:
    if df.empty or df.value.fillna(0).eq(0).all():
        return None
    df = df.assign(name=df[color].map(LABELS))
    fig = px.bar(df, x="date", y="value", color="name",
                 color_discrete_map={LABELS[k]: v for k, v in COLORS.items() if k in LABELS},
                 category_orders=LEGEND_ORDER)
    fig.update_traces(marker_line_width=2, marker_line_color="rgba(0,0,0,0)", hovertemplate=hover_format(unit))
    return style(fig, title, unit, y_title)


# --- KPI cards ---

def delta_text(delta: float | None, unit: str) -> str | None:
    if delta is None or pd.isna(delta):
        return None
    sign = "+" if delta >= 0 else "-"
    if unit.startswith("$"):
        return f"{sign}${abs(delta):,.0f}"
    if unit.startswith("%"):
        return f"{sign}{abs(delta):.1f} pts"
    if unit == "months":
        return f"{sign}{abs(delta):.1f} mo"
    return f"{sign}{abs(delta):.2f}"


def kpi(metric: str, segment: str, month: str, label: str | None = None):
    cfg = M.METRICS[metric]
    seg = segment if metric in SEGMENT_AWARE else "all"
    data = load(seg)
    value = cfg["fn"](data, month).value
    prev = cfg["fn"](data, M.prev_month(month)).value if M.prev_month(month) in data.window else None
    delta = None if value is None or prev is None else value - prev
    note = "" if metric in SEGMENT_AWARE or segment == "all" else " Company-wide: not split by segment."
    if metric == "cac":
        note += " Simplification: marketing spend only, no sales salaries."
    st.metric(label or cfg["label"], M.fmt(value, cfg["unit"]), delta_text(delta, cfg["unit"]),
              delta_color="normal" if cfg["good"] == "up" else "inverse",
              help=f"{cfg['formula']}. Unit: {cfg['unit']}.{note}", border=True)


# --- sidebar ---

base = load("all")
window = base.window
st.sidebar.title("Closepath AI")
st.sidebar.caption("AI mortgage processing · monthly metrics")
start, end = st.sidebar.select_slider("Month range", options=window, value=(window[0], window[-1]),
                                      format_func=month_label)
segment = st.sidebar.selectbox("Segment", ["all"] + SEGMENTS, format_func=lambda s: "All" if s == "all" else LABELS[s])
channels = st.sidebar.multiselect("Channel", CHANNELS, default=CHANNELS, format_func=LABELS.get)
st.sidebar.caption("Channel applies to acquisition charts only. Segment applies to revenue and retention "
                   "metrics; CAC, margin and cash are company-wide. The agent always uses the full dataset.")
months = (start, end)

tabs = st.tabs(["Overview", "Growth", "Acquisition", "Retention", "Unit economics & cash",
                "Ask the agent", "Investor update"])

# --- Overview ---
with tabs[0]:
    st.subheader(f"{month_label(end)} vs {month_label(M.prev_month(end))}")
    groups = {"Growth": ["mrr", "mom_growth", "net_new_mrr"], "Acquisition": ["trial_conversion", "cac"],
              "Retention": ["logo_churn", "nrr"], "Unit economics": ["gross_margin", "cac_payback"],
              "Cash": ["net_burn", "runway"]}
    for group, keys in groups.items():
        st.markdown(f"**{group}**")
        for col, key in zip(st.columns(4), keys):
            with col:
                kpi(key, segment, end)
    arr = M.arr(load(segment), end).value
    st.caption(f"ARR {month_label(end)}: {M.fmt_money(arr)} (12 × MRR). Net burn and runway together are metric 10.")
    show(line(in_range(series("mrr", segment), months), "MRR", "$", "MRR ($)"))

# --- Growth ---
with tabs[1]:
    which = st.radio("Show", ["MRR", "ARR"], horizontal=True, label_visibility="collapsed")
    key = which.lower()
    show(line(in_range(series(key, segment), months), f"{which} ({LABELS.get(segment, 'all segments')})", "$",
              f"{which} ($)"))
    b = in_range(bridge(segment), months)
    if b.empty:
        st.info(NO_DATA)
    else:
        fig = go.Figure()
        for comp in M.COMPONENTS:
            d = b[b.component == comp]
            fig.add_bar(x=d.date, y=d.signed, name=LABELS[comp], marker_color=COLORS[comp],
                        hovertemplate="%{y:$,.0f}")
        net = b.groupby("date").signed.sum()
        fig.add_scatter(x=net.index, y=net.values, name="Net new MRR", mode="lines+markers",
                        line=dict(color=INK, width=2), marker=dict(size=7), hovertemplate="%{y:$,.0f}")
        fig.update_layout(barmode="relative")
        show(style(fig, "MRR bridge: new and expansion above zero, contraction and churned below", "$",
                   "MRR change ($)"))

# --- Acquisition ---
with tabs[2]:
    if not channels:
        st.info(NO_DATA)
    else:
        def by_channel(metric):
            df = in_range(series(metric, segment, "channel"), months)
            return df[df.channel.isin(channels)]

        c1, c2 = st.columns(2)
        with c1:
            show(stacked(by_channel("trials_started"), "Trials started by channel", "trials", "Trials", "channel"))
        with c2:
            show(line(by_channel("trial_conversion"), "Trial-to-paid by channel (by trial start month)", "%",
                      "Conversion (%)", "channel"))
        c3, c4 = st.columns(2)
        with c3:
            cac = by_channel("cac")[["month", "date", "channel", "value"]]
            blended = in_range(series("cac", "all"), months).assign(channel="blended")
            show(line(pd.concat([cac, blended]), "CAC by channel and blended", "$ per customer",
                      "CAC ($ per customer)", "channel"))
            st.caption("CAC = marketing spend / new paying accounts. Marketing spend only, no sales salaries.")
        with c4:
            show(stacked(by_channel("marketing_spend"), "Marketing spend by channel", "$", "Spend ($)", "channel"))

# --- Retention ---
with tabs[3]:
    c1, c2 = st.columns(2)
    with c1:
        show(line(in_range(series("logo_churn", segment, "plan"), months), "Logo churn by plan (plan left from)",
                  "%", "Logo churn (% per month)", "plan"))
    with c2:
        fig = line(in_range(series("nrr", segment), months), "Net revenue retention (monthly)", "%", "NRR (%)")
        if fig:
            fig.add_hline(y=100, line_color="#898781", line_width=1, annotation_text="100%",
                          annotation_position="top left")
        show(fig)
    heat = cohorts(segment)
    heat = heat.loc[[m for m in heat.index if start <= m <= end]]
    if heat.empty or heat.isna().all().all():
        st.info(NO_DATA)
    else:
        heat.index = [month_label(m) for m in heat.index]
        fig = px.imshow(heat.astype(float), text_auto=".0f", aspect="auto", zmin=50, zmax=100,
                        color_continuous_scale=["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"],
                        labels=dict(x="Months since first payment", y="Cohort (first paying month)",
                                    color="% still paying"))
        fig.update_traces(hovertemplate="%{y}, month %{x}: %{z:.1f}% still paying<extra></extra>")
        fig.update_layout(title=dict(text="Cohort logo retention (% of accounts still paying)", font=dict(size=15)),
                          height=420, margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(fig, width="stretch", theme="streamlit")

# --- Unit economics & cash ---
with tabs[4]:
    st.caption("Company-wide: spend, COGS and cash are not split by segment.")
    c1, c2 = st.columns(2)
    with c1:
        show(line(in_range(series("gross_margin", "all"), months), "Gross margin", "%", "Gross margin (%)"))
    with c2:
        show(line(in_range(series("cac_payback", "all"), months), "CAC payback", "months", "Payback (months)"))
    c3, c4 = st.columns(2)
    with c3:
        burn = in_range(series("net_burn", "all"), months)
        fig = None
        if not burn.empty:
            fig = px.bar(burn, x="date", y="value")
            fig.update_traces(marker_color=SLOTS[1], hovertemplate="%{y:$,.0f}")
            fig = style(fig, "Net burn (expenses - revenue)", "$", "Net burn ($ per month)")
        show(fig)
    with c4:
        show(line(in_range(series("cash_balance", "all"), months), "Cash balance", "$", "Cash ($)"))
    show(line(in_range(series("runway", "all"), months), "Runway (cash / avg net burn, last 3 months)", "months",
              "Runway (months)"))
    st.caption("Net burn and cash are separate charts on purpose: two y-scales on one plot invent a "
               "visual correlation.")


# --- agent tabs ---

def agent_ready() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    st.warning("Set ANTHROPIC_API_KEY (copy .env.example to .env) to use the agent. "
               "The dashboard tabs work without it.")
    return False


def money_safe(text: str) -> str:
    """Escape $ so Streamlit doesn't render "$3,233 ... $4,025" as LaTeX math."""
    return text.replace("$", "\\$")


def render_trace(trace: list[dict]):
    with st.expander(f"Agent trace ({len(trace)} tool calls)"):
        if not trace:
            st.caption("No tool calls.")
        for i, call in enumerate(trace, 1):
            st.markdown(f"**{i}. `{call['tool']}`** `{json.dumps(call['args'])}`")
            st.code(call["result"], language="json", wrap_lines=True)


def ask(question: str):
    import agent

    st.session_state.chat.append({"role": "user", "content": question})
    with st.spinner("Investigating with the metric tools..."):
        try:
            answer, trace = agent.run_agent(question, st.session_state.thread_id)
        except Exception as e:  # surface API/config errors in the chat instead of crashing the app
            answer, trace = f"Agent error: {type(e).__name__}: {e}", []
    st.session_state.chat.append({"role": "assistant", "content": answer, "trace": trace})


with tabs[5]:
    from prompts import STARTER_QUESTIONS

    if "chat" not in st.session_state:
        import agent

        st.session_state.chat, st.session_state.thread_id = [], agent.new_thread_id()
    st.caption("The agent answers only from read-only metric tools over the full dataset (sidebar filters do not "
               "apply). Every number should appear in the trace.")
    if agent_ready():
        def pick_starter():
            # pills keep a selection; act on it once, then clear so the same question can be asked again
            st.session_state.pending_question = st.session_state.starter
            st.session_state.starter = None

        st.pills("Try a question", STARTER_QUESTIONS, key="starter", on_change=pick_starter)
        if question := st.session_state.pop("pending_question", None):
            ask(question)
        if st.session_state.chat and st.button("New chat", icon=":material/refresh:"):
            import agent

            st.session_state.chat, st.session_state.thread_id = [], agent.new_thread_id()
            st.rerun()
        for msg in st.session_state.chat:
            with st.chat_message(msg["role"]):
                st.markdown(money_safe(msg["content"]))
                if msg["role"] == "assistant":
                    render_trace(msg["trace"])
    if question := st.chat_input("Ask about the metrics", disabled=not os.environ.get("ANTHROPIC_API_KEY")):
        ask(question)
        st.rerun()

with tabs[6]:
    from prompts import INVESTOR_UPDATE_PROMPT

    st.caption("The agent scans for anomalies across Oct 2025 to Sep 2026, investigates the largest, and drafts "
               "the Sep 2026 update. Takes a minute or two.")
    if agent_ready() and st.button("Generate investor update", type="primary"):
        import agent

        with st.spinner("Scanning anomalies and investigating..."):
            try:
                st.session_state.update = agent.run_agent(INVESTOR_UPDATE_PROMPT, agent.new_thread_id())
            except Exception as e:
                st.session_state.update = (f"Agent error: {type(e).__name__}: {e}", [])
    if "update" in st.session_state:
        text, trace = st.session_state.update
        st.download_button("Download .md", text, file_name="closepath_investor_update_2026-09.md",
                           mime="text/markdown")
        st.markdown(money_safe(text))
        render_trace(trace)
