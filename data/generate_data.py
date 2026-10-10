"""Seeded generator for Closepath AI, a fictional AI mortgage-processing SaaS.

Writes accounts.csv, subscriptions_monthly.csv, marketing_spend.csv,
expenses.csv and company.json next to this file.

The app and agent must NEVER import this module: STORIES is the answer key.
"""

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).parent
SEED = 42

# --- Planted stories (the answer key; never exposed to the app or agent) ---
STORIES = {
    "pro_price_increase": {
        "enabled": True,
        "new_price_from": "2026-02",       # new Pro conversions/upgrades at new price
        "old_price": 449,
        "new_price": 599,
        "migration_months": ["2026-03", "2026-04"],  # Jan-2026 Pro book split in half
        "downgrade_prob": 0.04,            # downgrade to starter instead of migrating
        "churn_migration": 0.06,           # migration month and the month after
        "churn_after": 0.03,               # later months, through end of window
        "inbound_mix_from": "2026-02",
        "inbound_mix": {"starter": 0.58, "pro": 0.32, "business": 0.10},
    },
    "paid_social_scale_up": {
        "enabled": True,
        "from": "2026-06",
        "spend": 130_000,
        "trials_mean": 95,
        "conversion": 0.06,
        "early_churn_multiplier": 2.0,
        "early_churn_months": 3,
    },
    "whale_churn": {
        "enabled": True,
        "account_id": "A00042",
        "name": "Harborline Home Loans",
        "mrr": 75_000,
        "contract_month": "2026-05",
        "contracted_mrr": 62_000,
        "last_paying_month": "2026-07",
    },
}

# --- Baseline business (tune these, not the stories, to hit sanity ranges) ---
BASELINE = {
    "company": {
        "name": "Closepath AI",
        "opening_cash": 16_000_000,
        "opening_cash_date": "2025-09-30",
        "window_start": "2025-10",
        "window_end": "2026-09",
    },
    "opening_month": "2025-09",
    "plans": {
        # plan: segment, opening accounts, monthly churn probability
        "starter": {"segment": "broker", "price": 199, "opening": 600, "churn": 0.035},
        "pro": {"segment": "broker", "price": 449, "opening": 450, "churn": 0.025},
        "business": {"segment": "community_lender", "price": 1_500, "step": 250,
                     "opening": 130, "churn": 0.012},
        "enterprise": {"segment": "enterprise_lender", "price_range": (6_000, 12_000),
                       "opening": 20, "churn": 0.005},
    },
    "opening_business_step_prob": 0.15,  # share of opening business accounts with +1 step
    "channels": {
        # trials Poisson mean, monthly growth (trials and spend), trial-to-paid, spend $/mo
        "organic_search": {"trials": 150, "growth": 0.02, "conversion": 0.18, "spend": 30_000},
        "referral": {"trials": 60, "growth": 0.02, "conversion": 0.25, "spend": 9_000},
        "paid_search": {"trials": 120, "growth": 0.0, "conversion": 0.14, "spend": 120_000},
        "paid_social": {"trials": 60, "growth": 0.0, "conversion": 0.10, "spend": 45_000},
        "outbound": {"trials": 40, "growth": 0.0, "conversion": 0.25, "spend": 40_000},
    },
    "spend_noise": 0.05,
    "inbound_mix": {"starter": 0.50, "pro": 0.40, "business": 0.10},
    "outbound_mix": {"business": 0.90, "enterprise": 0.10},
    "max_conversion_days": 21,
    "moves": {
        "starter_to_pro": 0.010,
        "pro_to_business": 0.006,
        "business_step_up": 0.03,
        "pro_to_starter": 0.007,
        "business_step_down": 0.01,
    },
    "expenses": {
        "payroll": 800_000, "payroll_growth": 0.01,
        "hosting": 15_000,           # COGS, fixed
        "ai_inference_pct": 0.14,    # COGS, % of MRR
        "qc_ops_pct": 0.18,          # COGS, human loan reviewers, % of MRR
        "g_and_a": 80_000, "g_and_a_noise": 0.05,
    },
}

COGS_CATEGORIES = {"hosting", "ai_inference", "qc_ops"}

NAME_PARTS = {
    "prefix": ["Summit", "Keystone", "Pinecrest", "Bluewater", "Redwood", "Lakeshore",
               "Granite", "Cedar", "Meridian", "Oakline", "Silverleaf", "Northgate",
               "Riverbend", "Fairway", "Highland", "Prairie", "Coastal", "Liberty",
               "Heritage", "Sterling", "Crescent", "Evergreen", "Beacon", "Copper",
               "Maple", "Horizon", "Canyon", "Willow", "Union", "Bayview"],
    "broker": ["Mortgage", "Lending", "Home Loans", "Mortgage Group", "Funding"],
    "community_lender": ["Credit Union", "Community Bank", "Federal CU", "Savings Bank"],
    "enterprise_lender": ["Home Lending", "Mortgage Corp", "Financial", "Bancorp"],
}


def month_list(start: str, end: str) -> list[str]:
    return [str(p) for p in pd.period_range(start, end, freq="M")]


def month_of(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_end(m: str) -> date:
    return pd.Period(m, freq="M").end_time.date()


def random_day_in_month(rng, m: str) -> date:
    p = pd.Period(m, freq="M")
    return p.start_time.date() + timedelta(days=int(rng.integers(0, p.days_in_month)))


def segment_for(plan: str) -> str:
    return BASELINE["plans"][plan]["segment"]


def pro_price(m: str) -> int:
    s = STORIES["pro_price_increase"]
    return s["new_price"] if s["enabled"] and m >= s["new_price_from"] else s["old_price"]


def plan_price(rng, plan: str, m: str) -> int:
    if plan == "pro":
        return pro_price(m)
    if plan == "enterprise":
        lo, hi = BASELINE["plans"]["enterprise"]["price_range"]
        return int(round(rng.uniform(lo, hi), -2))
    return BASELINE["plans"][plan]["price"]


def account_name(rng, segment: str) -> str:
    return f"{rng.choice(NAME_PARTS['prefix'])} {rng.choice(NAME_PARTS[segment])}"


class Generator:
    def __init__(self):
        self.rng = np.random.default_rng(SEED)
        self.accounts: list[dict] = []   # every account ever trialed
        self.state: dict[str, dict] = {}  # account_id -> live state for paying accounts
        self.snapshots: list[dict] = []
        self.pending: dict[str, list[dict]] = {}  # conversion month -> accounts
        self.months = month_list(BASELINE["opening_month"], BASELINE["company"]["window_end"])

    # --- account creation ---
    def new_account_id(self) -> str:
        return f"A{len(self.accounts) + 1:05d}"

    def add_account(self, **fields) -> dict:
        acct = {"account_id": self.new_account_id(), "churn_date": None, **fields}
        self.accounts.append(acct)
        return acct

    def activate(self, acct: dict, plan: str, mrr: int, m: str):
        self.state[acct["account_id"]] = {
            "plan": plan, "mrr": mrr, "steps": 0, "channel": acct["acquisition_channel"],
            "converted_month": m, "months_paid": 0, "migration_month": None,
            "migrated": False,
        }

    def build_opening_book(self):
        rng, m0 = self.rng, BASELINE["opening_month"]
        whale = STORIES["whale_churn"]
        channels = list(BASELINE["channels"])
        weights = np.array([c["trials"] * c["conversion"] for c in BASELINE["channels"].values()])
        weights /= weights.sum()
        plans = [p for p, cfg in BASELINE["plans"].items() for _ in range(cfg["opening"])]
        rng.shuffle(plans)
        whale_index = int(whale["account_id"][1:]) - 1
        start, end = date(2023, 1, 1), date(2025, 8, 31)
        span = (end - start).days

        for i in range(len(plans) + 1):
            if i == whale_index:
                plan, segment, channel, name = "enterprise", "enterprise_lender", "outbound", whale["name"]
            else:
                plan = plans.pop()
                segment = segment_for(plan)
                channel = str(rng.choice(channels, p=weights))
                name = account_name(rng, segment)
            trial = start + timedelta(days=int(rng.integers(0, span + 1)))
            conv = trial + timedelta(days=int(rng.integers(1, BASELINE["max_conversion_days"] + 1)))
            acct = self.add_account(account_name=name, segment=segment, acquisition_channel=channel,
                                    trial_start_date=trial, converted=True, conversion_date=conv,
                                    first_plan=plan)
            if i == whale_index:
                mrr = whale["mrr"]
            elif plan == "pro":
                mrr = STORIES["pro_price_increase"]["old_price"]
            else:
                mrr = plan_price(rng, plan, m0)
            self.activate(acct, plan, mrr, m0)
            if plan == "business" and i != whale_index and rng.random() < BASELINE["opening_business_step_prob"]:
                self.state[acct["account_id"]]["steps"] = 1
                self.state[acct["account_id"]]["mrr"] += BASELINE["plans"]["business"]["step"]

    # --- monthly dynamics ---
    def generate_trials(self, m: str, t: int):
        rng = self.rng
        s1, s2 = STORIES["pro_price_increase"], STORIES["paid_social_scale_up"]
        for channel, cfg in BASELINE["channels"].items():
            mean, conv_rate = cfg["trials"] * (1 + cfg["growth"]) ** t, cfg["conversion"]
            if channel == "paid_social" and s2["enabled"] and m >= s2["from"]:
                mean, conv_rate = s2["trials_mean"], s2["conversion"]
            if channel == "outbound":
                mix = BASELINE["outbound_mix"]
            elif s1["enabled"] and m >= s1["inbound_mix_from"]:
                mix = s1["inbound_mix"]
            else:
                mix = BASELINE["inbound_mix"]
            for _ in range(rng.poisson(mean)):
                plan = str(rng.choice(list(mix), p=list(mix.values())))
                segment = segment_for(plan)
                trial = random_day_in_month(rng, m)
                converted = bool(rng.random() < conv_rate)
                conv = (trial + timedelta(days=int(rng.integers(1, BASELINE["max_conversion_days"] + 1)))
                        if converted else None)
                acct = self.add_account(account_name=account_name(rng, segment), segment=segment,
                                        acquisition_channel=channel, trial_start_date=trial,
                                        converted=converted, conversion_date=conv,
                                        first_plan=plan if converted else None)
                if converted:
                    self.pending.setdefault(month_of(conv), []).append(acct)

    def churn_probability(self, st: dict, m: str) -> float:
        plan_cfg = BASELINE["plans"][st["plan"]]
        p = plan_cfg["churn"]
        s1, s2 = STORIES["pro_price_increase"], STORIES["paid_social_scale_up"]
        if s1["enabled"] and st["plan"] == "pro" and st["migration_month"]:
            mig = pd.Period(st["migration_month"], freq="M")
            cur = pd.Period(m, freq="M")
            if mig <= cur <= mig + 1:
                p = s1["churn_migration"]
            elif cur > mig + 1:
                p = s1["churn_after"]
        if (s2["enabled"] and st["channel"] == "paid_social" and st["converted_month"] >= s2["from"]
                and st["months_paid"] <= s2["early_churn_months"]):
            p *= s2["early_churn_multiplier"]
        return p

    def apply_moves(self, st: dict, m: str):
        u, mv = self.rng.random(), BASELINE["moves"]
        step = BASELINE["plans"]["business"]["step"]
        if st["plan"] == "starter" and u < mv["starter_to_pro"]:
            st["plan"], st["mrr"] = "pro", pro_price(m)
        elif st["plan"] == "pro":
            if u < mv["pro_to_business"]:
                st["plan"], st["mrr"], st["steps"] = "business", BASELINE["plans"]["business"]["price"], 0
            elif u < mv["pro_to_business"] + mv["pro_to_starter"]:
                st["plan"], st["mrr"] = "starter", BASELINE["plans"]["starter"]["price"]
        elif st["plan"] == "business":
            if u < mv["business_step_up"]:
                st["steps"] += 1
                st["mrr"] += step
            elif u < mv["business_step_up"] + mv["business_step_down"] and st["steps"] > 0:
                st["steps"] -= 1
                st["mrr"] -= step

    def assign_pro_migrations(self):
        """Split the Jan-2026 Pro book into the two renewal months."""
        s1 = STORIES["pro_price_increase"]
        for st in self.state.values():
            if st["plan"] == "pro":
                st["migration_month"] = str(self.rng.choice(s1["migration_months"]))

    def step_whale(self, aid: str, m: str) -> bool:
        """Scripted path for the whale. Returns False once it has churned."""
        w, st = STORIES["whale_churn"], self.state[aid]
        if m > w["last_paying_month"]:
            self.accounts[int(aid[1:]) - 1]["churn_date"] = month_end(w["last_paying_month"])
            return False
        if m >= w["contract_month"]:
            st["mrr"] = w["contracted_mrr"]
        return True

    def step_existing(self, m: str):
        prev = str(pd.Period(m, freq="M") - 1)
        s1, w = STORIES["pro_price_increase"], STORIES["whale_churn"]
        for aid in list(self.state):
            st = self.state[aid]
            if w["enabled"] and aid == w["account_id"]:
                if not self.step_whale(aid, m):
                    del self.state[aid]
                continue
            if self.rng.random() < self.churn_probability(st, m):
                self.accounts[int(aid[1:]) - 1]["churn_date"] = month_end(prev)
                del self.state[aid]
                continue
            if (s1["enabled"] and st["plan"] == "pro" and st["migration_month"] == m
                    and not st["migrated"]):
                st["migrated"] = True
                if self.rng.random() < s1["downgrade_prob"]:
                    st["plan"], st["mrr"] = "starter", BASELINE["plans"]["starter"]["price"]
                else:
                    st["mrr"] = s1["new_price"]
                continue
            self.apply_moves(st, m)

    def activate_new(self, m: str):
        for acct in self.pending.pop(m, []):
            plan = acct["first_plan"]
            self.activate(acct, plan, plan_price(self.rng, plan, m), m)

    def snapshot(self, m: str):
        for aid, st in self.state.items():
            st["months_paid"] += 1
            self.snapshots.append({"month": m, "account_id": aid, "plan": st["plan"], "mrr": st["mrr"]})

    def run(self):
        self.build_opening_book()
        s1 = STORIES["pro_price_increase"]
        for t, m in enumerate(self.months):
            if t > 0:
                if s1["enabled"] and m == s1["new_price_from"]:
                    self.assign_pro_migrations()  # book as of the prior (Jan) snapshot
                self.step_existing(m)
            self.generate_trials(m, max(t - 1, 0))
            self.activate_new(m)
            self.snapshot(m)

    # --- money ---
    def marketing_spend(self) -> pd.DataFrame:
        rng, s2, rows = self.rng, STORIES["paid_social_scale_up"], []
        noise = BASELINE["spend_noise"]
        for t, m in enumerate(self.months[1:]):
            for channel, cfg in BASELINE["channels"].items():
                base = cfg["spend"] * (1 + cfg["growth"]) ** t
                if channel == "paid_social" and s2["enabled"] and m >= s2["from"]:
                    base = s2["spend"]
                rows.append({"month": m, "channel": channel,
                             "spend": round(base * rng.uniform(1 - noise, 1 + noise), 2)})
        return pd.DataFrame(rows)

    def expenses(self, subs: pd.DataFrame, spend: pd.DataFrame) -> pd.DataFrame:
        e, rows = BASELINE["expenses"], []
        mrr = subs.groupby("month")["mrr"].sum()
        mkt = spend.groupby("month")["spend"].sum()
        for t, m in enumerate(self.months[1:]):
            amounts = {
                "payroll": e["payroll"] * (1 + e["payroll_growth"]) ** t,
                "hosting": e["hosting"],
                "ai_inference": e["ai_inference_pct"] * mrr[m],
                "qc_ops": e["qc_ops_pct"] * mrr[m],
                "marketing": mkt[m],
                "g_and_a": e["g_and_a"] * self.rng.uniform(1 - e["g_and_a_noise"], 1 + e["g_and_a_noise"]),
            }
            for cat, amt in amounts.items():
                rows.append({"month": m, "category": cat, "amount": round(amt, 2),
                             "is_cogs": cat in COGS_CATEGORIES})
        return pd.DataFrame(rows)

    def write(self, out_dir: Path = DATA_DIR):
        subs = pd.DataFrame(self.snapshots)
        accounts = pd.DataFrame(self.accounts)
        spend = self.marketing_spend()
        expenses = self.expenses(subs, spend)
        accounts.to_csv(out_dir / "accounts.csv", index=False)
        subs.to_csv(out_dir / "subscriptions_monthly.csv", index=False)
        spend.to_csv(out_dir / "marketing_spend.csv", index=False)
        expenses.to_csv(out_dir / "expenses.csv", index=False)
        (out_dir / "company.json").write_text(json.dumps(BASELINE["company"], indent=2) + "\n")
        return accounts, subs, spend, expenses


def summarize(accounts, subs, spend, expenses):
    """Quick eyeball table; the real metric definitions live in metrics.py."""
    wide = subs.pivot_table(index="account_id", columns="month", values="mrr", fill_value=0)
    months = list(wide.columns)
    rows = []
    for prev, m in zip(months, months[1:]):
        a, b = wide[prev], wide[m]
        new = b[(a == 0) & (b > 0)].sum()
        exp = (b - a)[(a > 0) & (b > a)].sum()
        con = (a - b)[(b > 0) & (b < a)].sum()
        chn = a[(a > 0) & (b == 0)].sum()
        new_n = int(((a == 0) & (b > 0)).sum())
        mkt = spend.loc[spend.month == m, "spend"].sum()
        exp_m = expenses[expenses.month == m]
        cogs = exp_m.loc[exp_m.is_cogs, "amount"].sum()
        rows.append({
            "month": m, "mrr": b.sum(), "mom%": 100 * (b.sum() / a.sum() - 1),
            "new": new, "expansion": exp, "contraction": con, "churned": chn,
            "logo_churn%": 100 * ((a > 0) & (b == 0)).sum() / (a > 0).sum(),
            "cac": mkt / new_n, "gm%": 100 * (1 - cogs / b.sum()),
            "burn": exp_m.amount.sum() - b.sum(),
        })
    df = pd.DataFrame(rows).set_index("month")
    print(f"Opening MRR ({months[0]}): ${wide[months[0]].sum():,.0f} "
          f"across {(wide[months[0]] > 0).sum()} accounts")
    print(df.round(1).to_string())


if __name__ == "__main__":
    gen = Generator()
    gen.run()
    summarize(*gen.write())
