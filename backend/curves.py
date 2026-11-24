"""PD curves by year, from the monthly curves.

The cumulative PD at the end of year y is the monthly curve at month 12y; the
marginal PD of year y is what it adds over the year,
cum(12y) - cum(12(y-1)), with cum = 0 at the start. Same units as the input
(the analytics give percent).
"""
from __future__ import annotations

import pandas as pd


def yearly(curves: pd.DataFrame) -> pd.DataFrame:
    """Monthly curves (rating, month, cum_pd, ...) -> one row per rating and
    year: year, cum_pd, marginal_pd, plus the other id columns kept."""
    if curves is None or not len(curves):
        return pd.DataFrame(columns=["rating", "year", "cum_pd", "marginal_pd"])
    keys = [k for k in ("scale", "bucket", "rating") if k in curves.columns]
    c = curves[curves["month"] > 0].copy()
    c["year"] = (c["month"] - 1) // 12 + 1
    last = (c.sort_values("month").groupby(keys + ["year"], as_index=False, sort=False)
            .agg(cum_pd=("cum_pd", "last"), month=("month", "last")))
    last = last[last["month"] == 12 * last["year"]].drop(columns="month")
    last = last.sort_values(keys + ["year"])
    prev = last.groupby(keys, sort=False)["cum_pd"].shift(1).fillna(0.0)
    last["marginal_pd"] = last["cum_pd"] - prev
    return last.reset_index(drop=True)
