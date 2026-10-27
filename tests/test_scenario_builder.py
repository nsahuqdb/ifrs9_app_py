"""The scenario builder's table: what an edit does to a row."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "frontend"))

from scenario_ui import MainTable, canon  # noqa: E402

VARS = {"OIL_PRICE": {"label": "Oil price", "sd": 26.0, "adverse": -1},
        "US_RATE": {"label": "US policy rate", "sd": 1.4, "adverse": 1}}
YEARS = [2026, 2027, 2028, 2029, 2030]


@pytest.fixture
def t():
    return MainTable(YEARS, VARS)


def test_a_library_path_is_year_by_year(t):
    d = t.from_scenario({"main": {"OIL_PRICE": [-47.15, -15.02, 22.45, None, None]}})
    r = d.iloc[0]
    assert r["Shape"] == "Year by year" and pd.isna(r["Size"])
    assert t.to_main(d)[0]["OIL_PRICE"] == [-47.15, -15.02, 22.45, None, None]


def test_a_new_row_is_one_adverse_standard_deviation(t):
    old = t.from_scenario({})
    new = pd.DataFrame([{"Variable": "US policy rate"}], columns=t.cols)
    d, _ = t.settle(new, old)
    assert d.iloc[0]["Shape"] == "One year" and d.iloc[0]["2026"] == pytest.approx(1.4)
    assert pd.isna(d.iloc[0]["2027"])


def test_a_shape_redraws_the_years(t):
    old = t.from_scenario({"main": {"OIL_PRICE": [-40, None, None, None, None]},
                           "shapes": {"OIL_PRICE": {"shape": "one_year", "size": -40}}})
    new = old.copy()
    new.loc[0, "Shape"] = "Recovers"
    new.loc[0, "Over years"] = 4
    d, _ = t.settle(new, old)
    assert t.to_main(d)[0]["OIL_PRICE"] == [-40, -30, -20, -10, None]


def test_a_year_typed_in_makes_the_row_year_by_year(t):
    old = t.from_scenario({"main": {"OIL_PRICE": [-40, None, None, None, None]},
                           "shapes": {"OIL_PRICE": {"shape": "one_year", "size": -40}}})
    new = old.copy()
    new.loc[0, "2027"] = -10.0
    d, _ = t.settle(new, old)
    assert d.iloc[0]["Shape"] == "Year by year" and pd.isna(d.iloc[0]["Size"])
    assert t.to_main(d)[0]["OIL_PRICE"][:2] == [-40, -10]


def test_a_size_on_a_year_by_year_row_makes_it_a_shape(t):
    old = t.from_scenario({"main": {"OIL_PRICE": [-47.15, -15.02, None, None, None]}})
    new = old.copy()
    new.loc[0, "Size"] = -30.0
    d, _ = t.settle(new, old)
    assert d.iloc[0]["Shape"] == "One year"
    assert t.to_main(d)[0]["OIL_PRICE"] == [-30, None, None, None, None]


def test_settling_twice_changes_nothing_and_a_duplicate_is_dropped(t):
    old = t.from_scenario({"main": {"OIL_PRICE": [-40, None, None, None, None]}})
    d, _ = t.settle(old, old)
    assert canon(d) == canon(old)
    new = pd.concat([old, old], ignore_index=True)
    d, dup = t.settle(new, old)
    assert len(d) == 1 and dup == ["OIL_PRICE"]
