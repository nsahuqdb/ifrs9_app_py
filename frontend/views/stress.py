"""Stress test: one stress, or several side by side.

A package, a what-if on named customers and a staging-policy change are the
same thing here -- a scope (portfolios, stages, customers) and the levers that
move for it -- priced by the engine's one stress function
(ifrs9qdb.stress.apply_stress), which reprices through the function the run
priced with. Every lever reaches the scope and nothing else. Packages are
saved to the project's config/stress_packages.yml, the file the R app uses.
"""
import pandas as pd
import streamlit as st

import api
from ui import (bar, callout, caption, fmt_table, guard, metric_row, money,
                page_setup, pct, signed)

S = st.session_state
run_id = S.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Stress test",
           "Choose who is stressed and what moves, then reprice the run. "
           "Nothing in the run is changed.")

with guard():
    sc = api.scope(run_id)
internal, external = sc["internal"], sc["external"]
run_thr, run_lgd, run_floor = sc["run_threshold"], sc["lgd_base"], sc["lgd_floor"]
scenarios = sc.get("scenarios") or []


def _blank(name: str) -> dict:
    return {"name": name, "portfolios": list(internal), "stages": [],
            "customers": [], "dpd_threshold": None, "contagion": True,
            "tasdeer_collective": True, "watchlist_triggers": True,
            "local_triggers": True, "stage_to": None, "default_top_n": 0,
            "pd_multiplier": 1.0, "pd_scenario": "", "rating_notches": 0,
            "lgd_base": None, "lgd_floor": None, "collateral_pct": 100.0,
            "exposure_pct": 100.0, "maturity_years": 0.0}


def _add(specs: list[dict]) -> None:
    for sp in specs:
        S["stress_uid"] = S.get("stress_uid", 0) + 1
        S["stress_pkgs"].append({**_blank(sp.get("name") or "Stress"), **sp,
                                 "uid": S["stress_uid"]})


key_run = S.get("stress_pkgs_run")
if "stress_pkgs" not in S or key_run != run_id:
    S["stress_pkgs"], S["stress_pkgs_run"] = [], run_id
    _add([_blank("Stress 1")])

b1, b2, b3, b4 = st.columns(4)
if b1.button("Add a package", use_container_width=True):
    _add([_blank(f"Stress {len(S['stress_pkgs']) + 1}")])
if b2.button("Add the standard packages", use_container_width=True,
             help="Mild and severe downturn, collateral revaluation, staging "
                  "tightened to 30 days, the largest five customers defaulting."):
    _add(sc["standard"])
if b3.button("Load saved", use_container_width=True,
             help="Replace the packages on screen with the ones last saved "
                  "(config/stress_packages.yml)."):
    with guard():
        saved = api.packages_saved()
    if saved:
        S["stress_pkgs"] = []
        _add(saved)
    else:
        st.info("No saved packages yet.", icon="ℹ️")


def _min_lgd(p: dict) -> float:
    """The package's minimum LGD: its maximum LGD times its floor share."""
    base = run_lgd if p["lgd_base"] is None else p["lgd_base"]
    share = run_floor if p["lgd_floor"] is None else p["lgd_floor"]
    return round(float(base) * float(share), 4)


def _read(p: dict) -> dict:
    """One package's fields back off the screen, a run-own value as None."""
    u = p["uid"]
    g = lambda k, d: S.get(f"sp{u}_{k}", d)  # noqa: E731
    thr = g("thr", run_thr if p["dpd_threshold"] is None else p["dpd_threshold"])
    lgdb = g("lgdb", run_lgd if p["lgd_base"] is None else p["lgd_base"])
    # shown as the minimum LGD (max LGD x floor share); stored as the share
    lgd_min = g("lgdmin", _min_lgd(p))
    lgdf = float(lgd_min) / float(lgdb) if float(lgdb) > 0 else run_floor
    to = g("to", "unchanged" if not p["stage_to"] else p["stage_to"])
    ids = g("cust", ", ".join(p["customers"]))
    return {
        "name": g("name", p["name"]).strip() or p["name"],
        "portfolios": list(g("pf", p["portfolios"])),
        "stages": [int(x) for x in g("st", p["stages"])],
        "customers": [t.strip() for t in ids.replace(";", ",").split(",") if t.strip()],
        "dpd_threshold": None if float(thr) == float(run_thr) else float(thr),
        # the staging policy stays the run's own: not a lever on this page
        "contagion": bool(p["contagion"]),
        "tasdeer_collective": bool(p["tasdeer_collective"]),
        "watchlist_triggers": bool(p["watchlist_triggers"]),
        "local_triggers": bool(p["local_triggers"]),
        "stage_to": None if to == "unchanged" else int(to),
        "default_top_n": int(g("topn", p["default_top_n"])),
        "pd_multiplier": float(g("pd", p["pd_multiplier"])),
        "pd_scenario": "" if g("scen", p["pd_scenario"] or "none") == "none"
                       else g("scen", p["pd_scenario"]),
        "rating_notches": int(g("notch", p["rating_notches"])),
        "lgd_base": None if float(lgdb) == float(run_lgd) else float(lgdb),
        "lgd_floor": None if abs(float(lgdf) - float(run_floor)) < 1e-9
                     else float(lgdf),
        "collateral_pct": float(g("coll", p["collateral_pct"])),
        "exposure_pct": float(g("exp", p["exposure_pct"])),
        "maturity_years": float(g("mat", p["maturity_years"])),
    }


drop = None
for i, p in enumerate(S["stress_pkgs"]):
    u = p["uid"]
    cur = _read(p)
    with st.expander(cur["name"], expanded=len(S["stress_pkgs"]) == 1):
        c = st.columns([2, 3, 1, 3, 1], vertical_alignment="bottom")
        c[0].text_input("Name", p["name"], key=f"sp{u}_name")
        # a saved package may name a portfolio this run does not hold
        c[1].multiselect("Portfolios", sc["all"],
                         [x for x in p["portfolios"] if x in sc["all"]],
                         key=f"sp{u}_pf", help="Empty: every portfolio.")
        c[2].multiselect("Stages", [1, 2, 3], p["stages"], key=f"sp{u}_st",
                         help="Empty: every stage.")
        c[3].text_input("Customer ids", ", ".join(p["customers"]), key=f"sp{u}_cust",
                        help="Comma separated. Empty: every customer.")
        if c[4].button("Remove", key=f"sp{u}_rm", use_container_width=True,
                       disabled=len(S["stress_pkgs"]) == 1):
            drop = i
        if cur["customers"]:
            # the named customers as they stand, so a mistyped id shows before
            # anything is priced
            try:
                lk = api.customers(run_id, "; ".join(cur["customers"]), spaces=False)
            except api.BackendError as e:       # the rest of the page still works
                lk = {}
                st.caption(f"The customers could not be looked up: {e}")
            fd = pd.DataFrame(lk.get("found") or [])
            if len(fd):
                cols = [x for x in ("customer", "portfolios", "rating", "stage",
                                    "contracts", "exposure", "ecl") if x in fd]
                st.dataframe(fmt_table(fd[cols], money_cols=("exposure", "ecl")),
                             use_container_width=True, hide_index=True)
            if lk.get("missing"):
                st.warning("Not in this run: " + ", ".join(lk["missing"]), icon="⚠️")

        c = st.columns(6)
        c[0].number_input("Stage 2 DPD threshold", 0, 365,
                          int(run_thr if p["dpd_threshold"] is None
                              else p["dpd_threshold"]), 5, key=f"sp{u}_thr",
                          help=f"This run's is {run_thr:g} days.")
        c[1].selectbox("Move to stage", ["unchanged", 1, 2, 3],
                       ["unchanged", 1, 2, 3].index(p["stage_to"] or "unchanged"),
                       key=f"sp{u}_to")
        c[2].number_input("Largest N default", 0, 100, int(p["default_top_n"]), 1,
                          key=f"sp{u}_topn",
                          help="The N largest customers by exposure that are "
                               "not in Stage 3 already go to Stage 3.")
        c[3].number_input("PD multiplier", 0.0, 10.0, float(p["pd_multiplier"]),
                          0.05, key=f"sp{u}_pd")
        opts = ["none"] + scenarios
        c[4].selectbox("PD scenario", opts,
                       opts.index(p["pd_scenario"]) if p["pd_scenario"] in opts else 0,
                       key=f"sp{u}_scen",
                       help="Price on one scenario's PD curves instead of the "
                            "weighted ones.")
        c[5].number_input("Rating notches", -10, 20, int(p["rating_notches"]), 1,
                          key=f"sp{u}_notch", help="Positive is a downgrade.")
        c = st.columns(6)
        c[0].number_input("Maximum LGD (unsecured)", 0.0, 1.0,
                          float(run_lgd if p["lgd_base"] is None else p["lgd_base"]),
                          0.01, key=f"sp{u}_lgdb",
                          help=f"This run's is {run_lgd:g}.")
        c[1].number_input("Minimum LGD (fully secured)", 0.0, 1.0, _min_lgd(p),
                          0.005, format="%.3f", key=f"sp{u}_lgdmin",
                          help=f"This run's is {run_lgd * run_floor:.3f} "
                               f"({run_floor:g} of the maximum).")
        c[2].number_input("Collateral %", 0.0, 300.0, float(p["collateral_pct"]),
                          5.0, key=f"sp{u}_coll")
        c[3].number_input("Exposure %", 0.0, 300.0, float(p["exposure_pct"]), 5.0,
                          key=f"sp{u}_exp")
        c[4].number_input("Extend maturity (years)", -10.0, 30.0,
                          float(p["maturity_years"]), 0.25, key=f"sp{u}_mat")

if drop is not None:
    S["stress_pkgs"].pop(drop)
    st.rerun()

specs = [_read(p) for p in S["stress_pkgs"]]
if b4.button("Save", use_container_width=True,
             help="To config/stress_packages.yml, so the same stresses run "
                  "next quarter. The R app reads the same file."):
    with guard():
        r = api.packages_save(specs)
    st.success(f"Saved {r['saved']} package(s).", icon="✅")

go = st.button("Run" if len(specs) == 1 else f"Run all {len(specs)}",
               type="primary", use_container_width=True)
if not go and S.get("stress_last") is None:
    st.stop()
if go:
    S["stress_last"] = (run_id, specs)
last_run, specs = S["stress_last"]
if last_run != run_id:
    st.stop()

results = []
for sp in specs:
    with guard():
        results.append(api.apply_stress(run_id, sp))


def _detail(r: dict) -> None:
    metric_row([
        ("Provision now", money(r["before"])),
        ("Under this stress", money(r["after"])),
        ("Change", signed(r["delta"])),
        ("% change", pct(100 * r["delta"] / max(r["before"], 1))),
        ("Contracts in scope", money(r["scoped"])),
    ])
    if abs(r["delta"]) < 1e-6:
        st.info("Nothing in this package changes the provision.", icon="ℹ️")
    if r.get("defaulted"):
        caption(f"Forced to default ({len(r['defaulted'])}): "
                + ", ".join(map(str, r["defaulted"])))
    c1, c2 = st.columns([2, 3])
    with c1:
        st.markdown("**By portfolio**")
        bp = pd.DataFrame(r["by_portfolio"])
        bar(bp, "portfolio", "change", diverging=True)
        mig = pd.DataFrame(r.get("migration") or [])
        if len(mig):
            st.markdown("**Stage moves**")
            st.dataframe(fmt_table(mig, money_cols=("contracts", "customers",
                                                    "exposure", "ecl_change")),
                         use_container_width=True, hide_index=True)
    with c2:
        st.markdown("**Customers affected**")
        bc = pd.DataFrame(r["by_customer"])
        if len(bc):
            bc = bc[bc["change"].abs() > 0]
        if len(bc) == 0:
            st.info("No customer's provision moved.")
        else:
            st.dataframe(
                fmt_table(bc[["customer", "facilities", "stage", "stage_after",
                              "exposure", "ecl_before", "ecl_after", "change"]],
                          money_cols=("facilities", "exposure", "ecl_before",
                                      "ecl_after", "change")),
                use_container_width=True, hide_index=True, height=440)


if len(results) == 1:
    _detail(results[0])
else:
    rows = pd.DataFrame([{"package": r["name"], "before": r["before"],
                          "after": r["after"], "change": r["delta"],
                          "pct": 100 * r["delta"] / max(r["before"], 1),
                          "contracts in scope": r["scoped"],
                          "re-staged": r["moved"]} for r in results])
    rows = rows.sort_values("change", ascending=False)
    worst = rows.iloc[0]
    metric_row([
        ("Provision now", money(rows["before"].iloc[0])),
        ("Worst package", worst["package"]),
        ("Under it", money(worst["after"])),
        ("Change", signed(worst["change"])),
        ("As a share", pct(worst["pct"])),
    ])
    bar(rows, "package", "change", diverging=True,
        title="Change in provision by package")
    caption("Each package is priced on its own from the same run: the changes "
            "do not add up.")
    st.dataframe(fmt_table(rows, money_cols=("before", "after", "change",
                                             "contracts in scope", "re-staged"),
                           pct_cols=("pct",)),
                 use_container_width=True, hide_index=True)
    for r in results:
        with st.expander(f"{r['name']} — {signed(r['delta'])}"):
            _detail(r)
