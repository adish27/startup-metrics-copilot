# Answer Key: Closepath AI planted stories

> **Never loaded by the app or the agent.** This file and the `STORIES` dict in `data/generate_data.py` are the ground truth for the manual agent check.

Closepath AI is a fictional AI mortgage-processing SaaS. Lenders pay a monthly subscription tiered by committed loan volume. Data runs Sep 2025 (opening snapshot) to Sep 2026, seed 42.

| Story | Window | Metrics it moves | One-line truth |
| --- | --- | --- | --- |
| 1. Pro price increase | Feb to Jun 2026 | Expansion, contraction, logo churn, NRR, ARPA | Repricing Pro from $449 to $599 lifted MRR but raised Pro churn |
| 2. LinkedIn (paid_social) scale-up | Jun to Sep 2026 | CAC, CAC payback, net burn, runway | 2.9x spend on paid social bought almost no extra customers |
| 3. Whale churn | May and Aug 2026 | Contraction, churned MRR, MoM growth, NRR | Harborline Home Loans (~5% of MRR) cut volume, then left |

## Story 1: Pro price increase

**Injection**
- From 2026-02, new Pro conversions and Starter→Pro upgrades are priced at $599.
- Every Pro account paying in 2026-01 moves from $449 to $599 at renewal: a random half in 2026-03, the rest in 2026-04. The plan label stays `pro`, so it shows up as expansion.
- 4% of migrating accounts downgrade to starter in their migration month instead.
- Pro churn is 6% in each account's migration month and the month after, then 3% (vs 2.5% baseline) through Sep 2026.
- From 2026-02, inbound plan mix shifts to starter 58%, pro 32%, business 10%.

**Signals in the data (seed 42):** expansion MRR ~$41k (Mar) and ~$36k (Apr) vs ~$9k Oct–Jan average (about 4x); about 88% of it from accounts on `pro` both months with no plan change. Logo churn 4.3% in Apr vs ~2.4% Oct–Jan average.

**Agent should conclude:** the expansion spike came from existing Pro accounts moving from $449 to $599 with no plan change, consistent with a price increase applied at renewal. It triggered extra Pro churn and downgrades; net MRR effect is positive.

## Story 2: Paid social (LinkedIn ads) scale-up

**Injection**
- From 2026-06, `paid_social` spend goes from $45,000 to $130,000 per month.
- `paid_social` trials rise from a Poisson mean of 60 to 95.
- Trial-to-paid for `paid_social` trials starting 2026-06 or later drops from 10% to 6%.
- `paid_social` accounts acquired from 2026-06 churn at 2x their plan's baseline rate in their first 3 paid months.

**Signals (seed 42):** paid social CAC ~$6.6k (Oct–May) → ~$25.6k (Jun–Sep), about 3.9x; other channels move less than 16%. Blended CAC Jun–Sep about 1.25x Jan–May; CAC payback about 1.7 months longer. Net burn rises by ~$85k per month.

**Agent should conclude:** the CAC increase is isolated to paid social. Spend rose ~2.9x, trials rose ~58%, conversion fell, so new paid social customers stayed roughly flat and churn faster. Recommend pulling paid social back to its prior level.

## Story 3: Whale churn

**Injection**
- Account `A00042`, "Harborline Home Loans" (enterprise_lender, outbound), pays $75,000/month through 2026-04.
- Drops to $62,000 in 2026-05 (volume tier cut, contraction).
- Last paying month 2026-07 (`churn_date` 2026-07-31); no row from 2026-08.

**Signals (seed 42):** May contraction ~$14k, concentrated in one account. Aug churned MRR ~$90k vs ~$18k average of other months (about 5x); Aug MoM MRR growth −2.0%, while Aug logo churn (3.2%) stays normal.

**Agent should conclude:** the Aug MRR decline comes from a single account, so revenue churn and logo churn diverge. The May contraction was an early warning sign. Flag customer concentration risk and report Harborline's share of MRR before it churned (~5% in Jul 2026).
