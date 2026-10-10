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
