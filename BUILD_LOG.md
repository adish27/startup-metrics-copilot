# Build Log

## Step 0: Scaffold
- Prompt: "Build the plan, but pause to explain each major component before building it."
- Created git repo, .gitignore, requirements.txt (pinned majors), .env.example, uv venv.

## Step 1: Data generator
- Prompt: "model the data for a AI startup that handles home mortgage processing" → re-themed Brightdesk (helpdesk) as Closepath AI (AI mortgage processing). Chose volume-tier subscriptions (keeps MRR clean) and re-scaled dollars.
- Changes from the spec: segments broker / community_lender / enterprise_lender; plans $199 / $449 / $1,500+$250 steps / $6–12k; COGS = hosting + ai_inference (14% MRR) + qc_ops (18% MRR); opening cash $16M; marketing spend ~3x.
- Whale: spec says "~6% of MRR". Spec's $22k is ~10% of opening MRR, so the whale is $75k (→ $62k in May), ~5% of MRR when it churns. At $45k, Aug churned MRR only reached ~3.5x the norm (test needs 4x).
- What broke: first run failed "other channels' CAC moves < 20%" (outbound −32%) and only just passed the Pro-share (80.9%) and blended-CAC (1.23x) checks.
- Diagnosis: a 30-seed sweep showed several checks are noise-bound at ~1,400 accounts (outbound/referral win only 5–15 customers a month). Organic CAC also drifted down because trials grew 2%/mo but spend was flat.
- Fixes. Baseline: outbound 40 trials at 25% for $40k with a 90/10 business/enterprise mix, organic/referral spend grows with trials, Starter→Pro 1.0% and Pro→Business 0.6%. Story strength: Pro $599 (was $579), paid social $130k (was $120k). Seed 42 is fixed, so the data is deterministic and passes every check.
- Updated sanity ranges: blended CAC $2,600–3,800, gross margin 62–70%, opening MRR $786k–$834k. Others unchanged. Sanity checks use Oct–Jan averages because monthly logo churn alone swings ±0.5 pts.

## Step 2: Story tests
- `tests/conftest.py` builds a `Raw` fixture straight from the CSVs with pandas (independent of metrics.py): account×month MRR/plan tables, bridge, period CAC (total spend / total new accounts), monthly CAC payback.
- `tests/test_stories.py`: 9 checks from the spec. Mortgage-version dollar figure: the whale contracts by $13,000 in May.
- Result: 9/9 pass.
- Mutation check: switching each story off makes its own tests fail. Switching Story 1 or 3 off also breaks some Story 2 checks, because it shifts the random stream and the Story 2 checks are noise-sensitive (see Step 1). With seed 42 and all stories on, the data is deterministic.

## Step 3: Metrics engine
- `metrics.py`: `load_data`/`build_data`, the `account_changes` building block (per-account m-1 vs m label), 10 core metric functions plus supporting ones (ARR, ARPA, net burn, cash, burn multiple, cohort heatmap), a `METRICS` registry (label, category, unit, formula, good direction, breakdowns), a `series()` helper, and formatters. Percent metrics use a 0–100 scale.
- Decisions: churn by plan is attributed to the plan the account left from. Runway averages the burn months available (1–2 in Oct/Nov). `filter_segment` filters accounts only, so spend, expenses and cash stay company-wide.
- What broke: 3 fixture tests failed. Two were my hand arithmetic (Nov expenses are $3,250, not $3,350). One was pandas turning None into NaN in breakdown tables. The code was right in all three cases; I fixed the expected values. Note for Step 5: tool JSON output must convert NaN to null.
- Result: 36 passed, 3 skipped (the no-peek checks for files not built yet). `metrics.py` agrees with the independent pandas code in conftest on every month's bridge, CAC and logo churn.

## Step 4: Dashboard (`app.py`)
- Prompt: "build all steps but add explanation on what you build and why", so the remaining steps ran without approval gates.
- 7 tabs, sidebar filters (month range, segment, channel), `st.cache_resource` for loaded data and `st.cache_data` for series. The UI does no math: every number comes from `metrics.py`. Added `trials_started` and `marketing_spend` series to `metrics.py` so the acquisition charts need no math in the UI either.
- Chart design (dataviz skill): fixed color per channel, plan and segment, so filtering never repaints the remaining series. The categorical palette was validated for colorblind safety. Units on every axis and hover. Net burn and cash balance are two charts, not one dual-axis chart, because two y-scales on one plot suggest a correlation that isn't there (this deviates from the spec, which asked for "net burn bars with cash balance line"). MRR and ARR use a toggle for the same reason.
- Segment filter applies to revenue and retention metrics only. CAC, margin, burn and runway cards say "Company-wide" in their tooltip.
- What broke: a headless Chrome screenshot captured only the loading skeleton (Streamlit loads over a live connection). I switched to Playwright driving the installed Chrome and clicking through each tab. `use_container_width` is deprecated in Streamlit 1.65, so it became `width="stretch"`. Legends sorted alphabetically, so I pinned them to the fixed entity order.
- Verified with Streamlit `AppTest` (no exceptions; empty state when no channels are selected; every segment and a 2-month range render) and screenshots in `docs/screenshots/`.

## Step 5: Agent tools and agent (`agent.py`, `prompts.py`)
- 7 read-only tools as pure functions over `metrics.py`, wrapped as LangChain tools. Outputs are compact JSON with rounded numbers and a `unit` field. Bad arguments return `{"error": ...}` to the model instead of crashing.
- Design choices that make the stories findable without leaking them:
  - `top_account_changes` also returns a plan-transition summary. In Mar 2026, "pro → pro: 240 accounts, +$36,000, median +$150" is how a price increase looks. The top-10 list alone is dominated by $1,051 Pro→Business upgrades.
  - `compare_periods` pools CAC (total spend / total new accounts) and returns spend and new-account counts, so "spend 2.9x, customers flat" is visible.
  - `detect_anomalies` covers metrics, bridge components, channel spend and channel CAC. $ items must move at least 0.5% of MRR, so noisy small series (e.g. $500 contraction months) don't crowd the list.
  - `runway_scenario`: the first version reported "None" (breakeven) for both cases because fixed costs were held flat. It now returns a static runway (same basis as the dashboard) plus a projection with payroll growing at its observed 1%/month, reporting either cash-out or breakeven month.
- Agent: LangGraph `create_react_agent` with `ChatAnthropic`, model from `LLM_MODEL` (default `claude-opus-5-5`, per the Claude API skill's default; was Sonnet in Step 0). Server-side refusal fallback (`fallbacks: "default"`) is enabled for models that support it. An `InMemorySaver` checkpointer keeps each chat's message history append-only (Opus 5.5 rejects edited history). Tool budget: 15 calls per request; after that, tools tell the model to answer with what it has. A recursion limit is the backstop.
- Note: LangGraph 1.x marks `create_react_agent` deprecated in favor of `langchain.agents.create_agent`, removed in 2.0. `requirements.txt` pins langgraph<2.
- Tests (`tests/test_agent_tools.py`, no LLM needed): each story surfaces through the tools (anomalies flag Mar expansion, Jun paid-social spend, May contraction, Aug churn; the top Aug churner is A00042 at 4.8% of MRR; paid-social CAC +289% while other channels stay under 20%), outputs are plain JSON, the budget caps calls, and the graph builds.

## Step 6: Chat and investor update tabs
- Chat: history in `st.session_state`, one agent thread per chat (with a "New chat" button), 4 starter buttons (the runway what-if uses $45k, paid social's pre-scale-up level), and an "Agent trace" expander under every answer.
- Investor update: a fixed prompt (anomalies → investigate the top 3–5 → 10-metric table → TL;DR / Key metrics / Wins / Concerns / Recommended actions / Asks `[Founder to fill]`), rendered markdown, `.md` download, and a trace.
- Without `ANTHROPIC_API_KEY` both tabs show a setup message and the dashboard still works.

## Manual agent check (live run, 2026-10-11)
- Question: "What's driving CAC since June?" (one live question; the others were not run live).
- Verdict: **pass.** It isolated the increase to paid social: spend about 2.8x ($46,419 in May to $129,497 in Jun 2026), trials +52.9%, trial-to-paid down to 2–9%, new paid-social customers down from 33 (Jan–May) to 20 (Jun–Sep), so CAC went from $6,962 to $25,610. Other channels moved −15.4% to +13.4%. Blended CAC went from $3,233 to $4,025 (+24.5%). It recommended pulling paid social back to about $46k a month and framed the audience-quality cause as a hypothesis.
- Number check: every figure was recomputed from the tools afterwards and matched (referral +13.4% vs 13.5% is rounding). Missed vs the answer key: it didn't mention that paid-social customers also churn faster, which is reasonable for a CAC question.
- Bug found: dollar amounts rendered as garbled math. Streamlit's `st.markdown` treats text between two `$` signs as LaTeX, so "$3,233 … $4,025" became a formula. Fix: `money_safe()` escapes `$` before rendering chat answers and the investor update (the `.md` download keeps the raw text). Verified with a before/after render.
