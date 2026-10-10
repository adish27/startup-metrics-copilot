"""Shared fixtures. Story tests read the CSVs directly with pandas, independent of metrics.py."""

from pathlib import Path

import pandas as pd
import pytest

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class Raw:
    def __init__(self, data_dir: Path):
        self.subs = pd.read_csv(data_dir / "subscriptions_monthly.csv")
        self.accounts = pd.read_csv(data_dir / "accounts.csv")
        self.spend = pd.read_csv(data_dir / "marketing_spend.csv")
        self.expenses = pd.read_csv(data_dir / "expenses.csv")
        self.accounts["conversion_month"] = self.accounts["conversion_date"].str[:7]
        # account x month MRR (0 = not paying) and plan
        self.mrr = self.subs.pivot_table(index="account_id", columns="month", values="mrr", fill_value=0)
        self.plan = self.subs.pivot_table(index="account_id", columns="month", values="plan", aggfunc="first")
        self.months = list(self.mrr.columns)
        self.bridge = self._bridge()

    def _bridge(self) -> pd.DataFrame:
        rows = {}
        for prev, m in zip(self.months, self.months[1:]):
            a, b = self.mrr[prev], self.mrr[m]
            rows[m] = {
                "mrr": b.sum(),
                "prev_mrr": a.sum(),
                "new": b[(a == 0) & (b > 0)].sum(),
                "expansion": (b - a)[(a > 0) & (b > a)].sum(),
                "contraction": (a - b)[(b > 0) & (b < a)].sum(),
                "churned": a[(a > 0) & (b == 0)].sum(),
                "logo_churn": ((a > 0) & (b == 0)).sum() / (a > 0).sum(),
                "new_accounts": ((a == 0) & (b > 0)).sum(),
            }
        df = pd.DataFrame(rows).T
        df["mom_growth"] = df["mrr"] / df["prev_mrr"] - 1
        return df

    def window(self, start: str, end: str) -> list[str]:
        return [m for m in self.months[1:] if start <= m <= end]

    def cac(self, months: list[str], channel: str | None = None) -> float:
        """Total spend / total new paying accounts over the months (by conversion month)."""
        spend, accts = self.spend[self.spend.month.isin(months)], self.accounts[self.accounts.conversion_month.isin(months)]
        if channel:
            spend, accts = spend[spend.channel == channel], accts[accts.acquisition_channel == channel]
        return spend.spend.sum() / len(accts)

    def cac_payback(self, m: str) -> float:
        row = self.bridge.loc[m]
        cac = self.cac([m])
        arpa_new = row["new"] / row["new_accounts"]
        exp = self.expenses[self.expenses.month == m]
        gm = 1 - exp.loc[exp.is_cogs, "amount"].sum() / row["mrr"]
        return cac / (arpa_new * gm)


@pytest.fixture(scope="session")
def raw() -> Raw:
    return Raw(DATA_DIR)
