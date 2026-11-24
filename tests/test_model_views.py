"""Model assumptions, yearly PD curves and the scenario-based stress views."""
import pandas as pd


def test_yearly_curves_add_up():
    from backend.curves import yearly
    m = list(range(0, 37))
    df = pd.DataFrame({"rating": "A", "month": m, "cum_pd": [min(100, 0.7 * x) for x in m]})
    y = yearly(df)
    assert list(y["year"]) == [1, 2, 3]
    assert list(y["cum_pd"]) == [0.7 * 12, 0.7 * 24, 0.7 * 36]
    # each year's marginal is what the year adds; together they are the cumulative
    assert abs(y["marginal_pd"].sum() - y["cum_pd"].iloc[-1]) < 1e-9
    assert abs(y["marginal_pd"].iloc[1] - 0.7 * 12) < 1e-9


def test_model_assumptions_read_the_frozen_config(tmp_path):
    from backend.model_assumptions import key_assumptions
    cu = tmp_path / "config_used"
    (cu / "config").mkdir(parents=True)
    (cu / "static").mkdir()
    (cu / "config" / "model.yml").write_text(
        "ttc_anchor_pd: 0.146\necl:\n  lgd_base: 0.4\n  stage3_method: zero\n"
        "horizons:\n  max_maturity: 50\n  n_forecasts: 5\n")
    (cu / "config" / "model_inputs.yml").write_text("internal_scenario_weights:\n  mode: auto\n")
    (cu / "static" / "staging_thresholds.csv").write_text(
        "key,value,description\ndpd_stage2_threshold_days,60,x\n")
    (cu / "static" / "collateral_types.csv").write_text(
        "collateral_type_id,external_collateral_type,description,haircut_general\n"
        "1,1,COLLATERAL ACCOUNT,1.00\n2,1,Residential Property,0.50\n")
    rows = {r["assumption"]: r for r in key_assumptions(tmp_path / "Output")}
    assert rows["Unsecured LGD"]["value"] == "40%"
    assert rows["Minimum unsecured share of the balance"]["value"] == "50%"   # default
    assert rows["Stage 2: days past due above the threshold (up to 90)"]["value"] == "60 days"
    assert rows["Stage 3 provision"]["value"] == "zero (as LIC)"
    assert "Residential property 50%" in rows[
        "Collateral haircuts (net = value × allocation × (1 − haircut))"]["value"]
    assert all(r["link"].startswith("/help_ecl?ch=") for r in rows.values())


def test_no_frozen_config_no_assumptions(tmp_path):
    from backend.model_assumptions import key_assumptions
    assert key_assumptions(tmp_path) == []
