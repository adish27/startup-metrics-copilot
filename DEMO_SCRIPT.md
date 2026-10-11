# Demo video script (under 5 minutes)

Record with Loom (screen + camera). Before you hit record:

- [ ] `.env` has your `ANTHROPIC_API_KEY`; app running with `uv run streamlit run app.py`
- [ ] Browser zoom ~110%, sidebar open, Overview tab selected, month range = full year, segment = All
- [ ] **Pre-generate the investor update once** before recording. It takes 1–2 minutes, which is too long to wait on camera. During the demo, click Generate and narrate over it, or cut the wait in Loom.
- [ ] Open in tabs: the GitHub repo, `BUILD_LOG.md`, `answer_key.md` (to show it exists but the agent never reads it)

---

## 0:00–0:30 · The problem

> "Founders spend hours every month turning metrics into a board update: finding what moved, figuring out why, writing it up. I built **Startup Metrics Copilot**: a dashboard of 10 core SaaS metrics for a fictional AI mortgage-processing startup, Closepath AI, plus a Claude agent that investigates metric changes and drafts the investor update. The data has three hidden stories planted in it. The test is whether the agent finds them from the data alone."

**Screen:** Overview tab.

## 0:30–1:30 · Dashboard tour

- **Overview:** "10 metrics in 5 categories (growth, acquisition, retention, unit economics, cash). Each card shows Sep vs Aug, green or red by whether the move is good, and the formula on hover." *(Hover the CAC card.)*
- **Growth tab:** "The MRR bridge splits each month's change into new, expansion, contraction and churned." Point without explaining: **"Expansion spikes in March and April. There's an odd contraction bar in May. And August is the only month MRR went down: look at that churn bar."**
- **Acquisition tab:** "Paid social spend nearly triples from June, and its CAC line takes off."
- *(Optional, 5 seconds)* change Segment to show filters, then set it back.

## 1:30–2:30 · Ask why: the whale

- **Ask the agent tab:** click the **"Why did MRR drop in August?"** pill.
- While it runs: "The agent can't see the CSVs. It can only call 7 read-only tools over the metric functions, and it's told to answer only from tool results."
- Read the answer's first line, then **open the Agent trace**: "It goes bridge → churned component → top accounts. It finds **Harborline Home Loans**, one enterprise account worth about 5% of MRR, and it also finds the **May contraction as the early warning sign**. Logo churn looked normal; revenue churn didn't."

## 2:30–3:30 · CAC and a what-if

- Click **"What's driving CAC since June?"**. "It compares periods by channel: paid social spend up ~2.9x, new customers flat, CAC up ~290%, while every other channel stays within 20%."
- Click **"What happens to runway if paid social goes back to $45k?"**. "It calls the runway scenario tool: runway goes from about 24 to about 30 months."

## 3:30–4:30 · Investor update

- **Investor update tab:** click **Generate investor update** (or show the pre-generated one).
- Scroll: TL;DR, key metrics table, wins, concerns, recommended actions, Asks left for the founder.
- **The key moment:** "I never asked about pricing, but the agent found it: the March–April expansion was 240 existing Pro accounts each going up $150 with **no plan change**, which looks like a price increase. It also flagged that it raised Pro churn."
- Click **Download .md**.

## 4:30–5:00 · How I built it

> "I gave a written spec to Claude Code and built it in steps: the data generator first, then tests proving the three stories are detectable, then the metric functions, the dashboard and the agent. Along the way I re-themed the spec from a helpdesk SaaS to mortgage AI. One lesson: with only ~1,400 customers, some story checks were random noise. A 30-seed sweep showed the outbound channel only won 5 customers a month, so I tuned the data until the tests passed reliably instead of loosening them. Code, tests and build log are on GitHub."

**Screen:** GitHub repo → `BUILD_LOG.md`.

---

### If something goes wrong live
- **The agent gives a weak answer:** open the trace anyway. "Every number is traceable to a tool call" is the point.
- **API error or slow response:** switch to the pre-generated investor update and narrate the trace.
