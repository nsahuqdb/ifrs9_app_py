"""Scenario-based views of the macro stress, built on the engine's pricing.

    sensitivity     one chosen scenario: the change in provision as the
                    scenario is made milder or harsher (its moves scaled),
                    and each of its main variables on its own at the size
                    the scenario gives it
    ecl at risk     for each chosen scenario, n five-year paths drawn around
                    it: the scenario's path plus a random path from the
                    macro system (the same random paths for every scenario,
                    so the scenarios differ only by their own moves); the
                    provision's distribution, its tail and who carries it

The pricing itself is the engine's (ifrs9qdb.stresstest.risk): full
repricing for the sensitivity, the decomposed book (the proxy) for the paths.
Nothing here changes how a run's ECL is calculated.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from ifrs9qdb.macro.prng import uniforms
from ifrs9qdb.stresstest import risk as R
from ifrs9qdb.stresstest.scenarios import Scenario
from ifrs9qdb.stresstest.transmission import scenario_paths

SCALES = (0.5, 1.0, 1.5, 2.0)


def _first_move(path) -> tuple[int | None, float | None]:
    for i, x in enumerate(path or []):
        if x is not None and x != 0:
            return i + 1, float(x)
    return None, None


def scenario_sensitivity(rc, scn: Scenario, scales=SCALES) -> dict:
    """How the provision moves with the scenario's severity, and each main
    variable's part on its own (its moves and their linked effects, the
    other main variables held at the forecast)."""
    H = rc.H
    rows = [{"scale": 0.0, "change": 0.0, "pd": 0.0, "staging": 0.0, "collateral": 0.0}]
    for a in scales:
        t = R._total(rc, scn if a == 1.0 else R._scaled(scn, a, H))
        rows.append({"scale": float(a), **{k: t[k] for k in ("change", "pd", "staging",
                                                           "collateral")}})
    parts = []
    for v, p in scn.given(H).items():
        yr, mv = _first_move(p)
        t = R._total(rc, R._part(scn, v, H))
        parts.append({"variable": v, "label": rc.system.label(v), "unit": rc.system.unit(v),
                      "year": yr, "move": mv, "change": t["change"]})
    if scn.restructured > 0:
        t = R._total(rc, R._part(scn, "_deferral", H))
        parts.append({"variable": "_deferral", "label": "Deferral programme", "unit": "share",
                      "year": None, "move": float(scn.restructured), "change": t["change"]})
    tab = pd.DataFrame(parts)
    if len(tab):
        tab = tab.sort_values("change", key=abs, ascending=False).reset_index(drop=True)
    return {"ok": True, "scenario": scn.name, "base": rc.base_total,
            "scaled": pd.DataFrame(rows), "variables": tab}


def _credit_loss(rc, P, ev, n: int, seed: int, pcts) -> dict:
    """The year's credit loss: each performing customer defaults in a path
    at its stressed 12-month PD, losing LGD x exposure (as the engine's
    ECL at risk draws it)."""
    expo = P.onb.copy()
    perf = P.ok & (P.stage0 < 3) & (expo > 0)
    worst = pd.Series(P.stage0).groupby(P.customer).transform("max").to_numpy()
    perf &= worst < 3
    ids, inv = np.unique(P.customer[perf], return_inverse=True)
    C = len(ids)
    if not C:
        return {}
    w = expo[perf]
    ead = np.bincount(inv, weights=w, minlength=C)
    lgd0 = rc.base["lgd"].to_numpy(float)[perf]
    lgd_c = np.bincount(inv, weights=w * np.nan_to_num(lgd0), minlength=C) / np.maximum(ead, 1e-12)
    pdm = np.vstack([np.bincount(inv, weights=w * row[perf], minlength=C)
                     for row in ev["pd12"]]) / np.maximum(ead, 1e-12)[None, :]
    u = uniforms(n * C, seed + 7).reshape(n, C)
    L = (u < pdm) * (lgd_c * ead)[None, :]
    loss = L.sum(axis=1)
    rows = []
    for q in pcts:
        v = float(np.percentile(loss, q))
        rows.append({"measure": f"Credit loss at {q:g}%", "value": v,
                     "expected_shortfall": float(loss[loss >= v].mean())})
    return {"loss_mean": float(loss.mean()), "loss_summary": rows}


def ecl_at_risk(rc, P, scenarios: list, n: int, seed: int, pcts=(95, 99)) -> dict:
    """``scenarios``: Scenario objects, or None for the run's forecast with
    no scenario. ``n`` paths per scenario."""
    H = rc.H
    base = rc.base_total
    noise = R._draws(rc, P, n, seed)
    results, arrays = [], []
    for s in scenarios:
        if s is None:
            D, restr, name, sid = noise, 0.0, "Forecast (no scenario)", "__forecast__"
            centre = 0.0
        else:
            D0 = R.paths_matrix(rc, P, scenario_paths(s, rc.system, H)["paths"])
            D, restr, name, sid = noise + D0, s.restructured, s.name, s.id
            centre = float(R.proxy_eval(P, D0, restr)["total"][0])
        ev = R.proxy_eval(P, D, restr)
        ecl = base + ev["total"]
        arrays.append(ecl)
        q = {p: float(np.percentile(ecl, p)) for p in pcts}
        top = max(pcts)
        tail = ecl >= q[top]
        es = float(ecl[tail].mean()) if tail.any() else q[top]
        seg = pd.DataFrame({"segment": P.segments,
                            "tail_change": ev["by_segment"][tail].mean(axis=0)})
        tail_idx = np.where(tail)[0]
        samp = np.arange(0, n, max(1, n // 200))
        chs = R.proxy_eval(P, D, restr, channels=True,
                           rows=np.unique(np.concatenate([tail_idx, samp])))
        in_tail = np.isin(chs["channel_rows"], tail_idx)
        chan = pd.DataFrame({"channel": list(chs["channels"]),
                             "tail_change": [float(v[in_tail].mean()) if in_tail.any() else np.nan
                                             for v in chs["channels"].values()]})
        r = {"id": sid, "scenario": name, "centre": base + centre,
             "mean": float(ecl.mean()), "median": float(np.median(ecl)),
             **{f"p{p:g}": q[p] for p in pcts}, f"es{top:g}": es,
             "by_segment": seg.sort_values("tail_change", ascending=False)
             .reset_index(drop=True),
             "by_channel": chan}
        if (rc.cfg.get("risk") or {}).get("default_draws", True):
            r.update(_credit_loss(rc, P, ev, n, seed, pcts))
        results.append(r)
    lo = min(float(a.min()) for a in arrays)
    hi = max(float(a.max()) for a in arrays)
    edges = np.linspace(lo, hi if hi > lo else lo + 1, 41)
    for r, a in zip(results, arrays):
        h, _ = np.histogram(a, bins=edges)
        r["histogram"] = [{"from": float(edges[i]), "to": float(edges[i + 1]),
                           "count": int(h[i])} for i in range(len(h))]
    return {"ok": True, "paths": n, "base": base, "percentiles": list(pcts),
            "results": results}
