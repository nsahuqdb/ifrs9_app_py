"""Scenario stress: the library, the builder, saved scenarios, and a
scenario priced on a run.

Every endpoint is a call to ``ifrs9qdb.stresstest`` or ``ifrs9qdb.macro.system``.
A scenario sets a few main variables; the linked effects -- estimated on the
store's vintage -- move the rest, and the book is repriced through the same
function the run priced with, so an empty scenario is the run's provision.

Fitting the linked effects takes a few seconds, reading a run for scenarios a
few more, and decomposing it for the Monte Carlo about a minute, so each is
kept per vintage, run and stress config; a result is kept too, until any of
those change.
"""
from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ifrs9qdb.macro import refresh
from ifrs9qdb.macro.system import fit_system
from ifrs9qdb.stresstest import (CATEGORIES, REGIONS, SHAPES, Scenario, ScenarioStore,
                                 library, prepare, read_stress_config, transmit)
from ifrs9qdb.stresstest import risk as st_risk
from ifrs9qdb.stresstest.config import config_hash
from ifrs9qdb.stresstest.library import check_library, derivation, episode

from ..settings import PROJECT_ROOT, RUNS_DIR, SCENARIOS_DB, current_user
from .macro import js, store
from .runs import _output_dir
from .stress import _load

router = APIRouter(tags=["scenarios"])

_LOCK = threading.Lock()
_KEY_LOCKS: dict = {}
_CACHE: "OrderedDict[tuple, object]" = OrderedDict()
_MAX = 48


def _cached(key: tuple, build):
    """One value per key, built once even when two requests ask together."""
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
        lk = _KEY_LOCKS.setdefault(key, threading.Lock())
    with lk:
        with _LOCK:
            if key in _CACHE:
                return _CACHE[key]
        v = build()
        with _LOCK:
            _CACHE[key] = v
            while len(_CACHE) > _MAX:
                _CACHE.popitem(last=False)
        return v


def _cfg() -> dict:
    return read_stress_config(PROJECT_ROOT)


def _db() -> ScenarioStore:
    return ScenarioStore(SCENARIOS_DB)


def _vintage(v: str | None) -> str:
    """The vintage asked for, else the latest. An empty store is seeded with
    the package's own history so the library opens before the first refresh;
    the Macro data page fetches the rest."""
    st = store()
    if v:
        if v not in set(st.vintages()["vintage"]):
            raise HTTPException(404, f"No vintage {v!r} in the macro store")
        return v
    latest = st.latest()
    if latest is None:
        refresh(st, PROJECT_ROOT, sources=("STATIC",), label="Package history")
        latest = st.latest()
    return latest


def _system(vintage: str):
    return _cached(("system", vintage),
                   lambda: fit_system(store(), vintage=vintage, project_root=PROJECT_ROOT))


def _horizon() -> int:
    return int(_cfg().get("horizon_years", 5))


def _first_year(system) -> int:
    """Year 1 of a scenario off a run: the year after the world's last
    outturn."""
    la = system.last_actual("GDP_WLD")
    import datetime as _dt
    return int(la) + 1 if la else _dt.date.today().year


def _run_path(run_id: str) -> Path:
    out = _output_dir(RUNS_DIR / run_id)
    if out is None:
        raise HTTPException(404, f"No run named {run_id!r}")
    return out.parent if out != RUNS_DIR / run_id else RUNS_DIR / run_id


def _rc(run_id: str, vintage: str | None):
    cfg = _cfg()
    v = _vintage(vintage)
    system = _system(v)

    def build():
        inputs, report = _load(run_id)
        return prepare(inputs, report, _run_path(run_id), system, cfg=cfg,
                       project_root=PROJECT_ROOT)
    return _cached(("rc", run_id, v, config_hash(cfg)), build), v, cfg


def _proxy(run_id: str, vintage: str | None):
    rc, v, cfg = _rc(run_id, vintage)
    return rc, _cached(("proxy", run_id, v, config_hash(cfg)),
                       lambda: st_risk.build_proxy(rc)), v, cfg


def _scenario(d: dict) -> Scenario:
    try:
        return Scenario.from_dict(d)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"The scenario could not be read: {exc}") from exc


def _key(scn: Scenario) -> str:
    """A scenario's numbers, as a cache key (its name and story aside)."""
    body = {"main": scn.given(_horizon()), "linked": scn.linked,
            "restructured": scn.restructured}
    return hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def _all_scenarios() -> list[Scenario]:
    return library(_horizon()) + _db().scenarios()


def _variables(system) -> list[dict]:
    rows = []
    for v in system.order:
        m = system.meta.get(v) or {}
        rows.append({"variable": v, "label": system.label(v), "unit": system.unit(v),
                     "level": m.get("level", ""), "transform": m.get("transform", ""),
                     "sd": system.sd(v),
                     "has_equation": system.has_equation(v), "adverse": system.adverse(v),
                     "last_actual": system.last_actual(v), "about": system.about(v)})
    return rows


# ---------------------------------------------------------------- library --
@router.get("/scenarios/setup")
def setup(vintage: str | None = None) -> dict:
    """What a scenario is built from: the variables (unit, size of a
    standard deviation, which way is adverse), the shapes, the library and
    the saved scenarios, the horizon, and the vintage the linked effects
    were fitted on."""
    v = _vintage(vintage)
    system = _system(v)
    st = store()
    try:
        label = str((st.meta(v) or {}).get("label") or "")
    except Exception:
        label = ""
    return js({"vintage": v, "vintage_label": label,
               "vintages": list(st.vintages()["vintage"])[::-1],
               "horizon": _horizon(), "first_year": _first_year(system),
               "variables": _variables(system), "shapes": list(SHAPES),
               "categories": CATEGORIES, "regions": REGIONS,
               "library": [s.to_dict() for s in library(_horizon())],
               "saved": _db().list(), "user": current_user()})


@router.get("/scenarios/library/{sid}/history")
def history(sid: str, vintage: str | None = None) -> dict:
    """How every variable moved through a historical scenario's episode."""
    v = _vintage(vintage)
    r = episode(sid, _system(v))
    if not r.get("ok"):
        raise HTTPException(404, r.get("reason", "No history for that scenario."))
    return js(r)


@router.get("/scenarios/library/{sid}/derivation")
def library_derivation(sid: str, vintage: str | None = None) -> dict:
    """How each of a library scenario's shocks was derived, year by year."""
    v = _vintage(vintage)
    t = derivation(sid, _system(v))
    if not len(t):
        raise HTTPException(404, f"No library scenario {sid!r}")
    return js({"id": sid, "rows": t})


class PreviewIn(BaseModel):
    scenario: dict
    vintage: str | None = None
    first_year: int | None = None


@router.post("/scenarios/preview")
def preview(body: PreviewIn) -> dict:
    """A scenario's path for every variable -- main ones as set, the rest by
    the linked effects -- with the store's baseline and the variables the
    main ones reach, without pricing."""
    v = _vintage(body.vintage)
    system = _system(v)
    H = _horizon()
    scn = _scenario(body.scenario)
    sim = system.simulate(scn.given(H), scn.linked, H)
    y0 = body.first_year or _first_year(system)
    years = list(range(y0, y0 + H))
    rows = []
    for var in system.order:
        p = np.asarray(sim["paths"][var], float)
        base = system.baseline(var, years)
        for j, y in enumerate(years):
            rows.append({"variable": var, "label": system.label(var), "unit": system.unit(var),
                         "role": sim["role"][var], "year": y, "move": float(p[j]),
                         "set": var in scn.given(H) and scn.given(H)[var][j] is not None,
                         "baseline": base[j],
                         "scenario": None if base[j] is None else base[j] + float(p[j]),
                         "beyond_data": j in (sim["flags"].get(var) or [])})
    sev = {}
    for var, p in scn.given(H).items():
        vals = [x for x in p if x is not None]
        sd = system.sd(var)
        if vals and sd and np.isfinite(sd):
            sev[var] = max(vals, key=abs) / sd
    ex = system.explain(scn.given(H), scn.linked, H)
    if len(ex):
        ex["driver_label"] = [("Its own momentum" if d == var else system.label(d))
                              for d, var in zip(ex["driver"], ex["variable"])]
    links = [{"variable": var, "driver": t["driver"], "lag": int(t["lag"]),
              "coef": float(t["coef"]), "driver_label": system.label(t["driver"]),
              "driver_unit": system.unit(t["driver"]), "unit": system.unit(var)}
             for var, eq in system.equations.items() for t in eq.terms]
    return js({"years": years, "paths": rows, "recommended": sim["recommended"],
               "severity": sev, "explain": ex, "links": links})


# ------------------------------------------------------------------ saved --
class SaveIn(BaseModel):
    scenario: dict
    user: str | None = None


def _complete(scn: Scenario) -> None:
    """A saved scenario carries its reasons like a library one: the event or
    basis it stands for, its narrative, and the rationale for each main
    variable; a supervisory one also names its publisher."""
    system = _system(_vintage(None))
    missing = []
    if not scn.description.strip():
        missing.append("a one-line description")
    if not scn.history.strip():
        missing.append("the historical event or basis")
    if not scn.narrative.strip():
        missing.append("the scenario narrative")
    if scn.category == "supervisory" and not scn.source.strip():
        missing.append("the publisher (source)")
    if not scn.given(_horizon()) and not scn.restructured:
        missing.append("at least one main variable")
    for v in scn.given(_horizon()):
        if not str((scn.why or {}).get(v, "")).strip():
            missing.append(f"the rationale for {system.label(v) if v in system.order else v}")
    if missing:
        raise HTTPException(400, "Before saving, give " + "; ".join(missing) + ".")


@router.get("/scenarios/saved")
def saved() -> list[dict]:
    return js(_db().list())


@router.post("/scenarios/saved")
def save_new(body: SaveIn) -> dict:
    """Save a scenario as a new one (a library scenario edited is always
    saved this way, under a name of its own)."""
    scn = _scenario(body.scenario)
    _complete(scn)
    if any(s.name.strip().lower() == scn.name.strip().lower() for s in library(_horizon())):
        raise HTTPException(400, f"{scn.name!r} is a library scenario's name; "
                                 "give yours a name of its own.")
    scn.id = None
    try:
        sid = _db().save(scn, user=body.user or current_user())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return js(_db().get(sid))


@router.put("/scenarios/saved/{sid}")
def save_version(sid: str, body: SaveIn) -> dict:
    """Save a new version of a saved scenario."""
    scn = _scenario(body.scenario)
    _complete(scn)
    try:
        _db().save(scn, user=body.user or current_user(), sid=sid)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return js(_db().get(sid))


@router.delete("/scenarios/saved/{sid}")
def delete(sid: str, user: str | None = None) -> dict:
    try:
        _db().delete(sid, user=user or current_user())
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    return {"deleted": sid}


@router.get("/scenarios/saved/{sid}/history")
def saved_history(sid: str) -> list[dict]:
    return js(_db().history(sid))


# ----------------------------------------------------------- supervisory --
class FedIn(BaseModel):
    year: int
    tables: dict | None = None          # {table key: CSV text}; fetched when absent
    vintage: str | None = None


@router.post("/scenarios/supervisory/fed")
def supervisory_fed(body: FedIn) -> dict:
    """The Fed's severely adverse scenario for ``year``, from its published
    tables (downloaded, or the four files uploaded), translated to world GDP
    and the US rate. Returned for review; saving is a normal save."""
    from ifrs9qdb.stresstest.supervisory import (FED_TABLES, fed_scenario, fed_urls,
                                                 fetch_fed, region_weights)
    tables = {k: v for k, v in (body.tables or {}).items() if k in FED_TABLES and v}
    fetched = False
    if len(tables) < len(FED_TABLES):
        try:
            tables = {**fetch_fed(body.year), **tables}
            fetched = True
        except Exception as e:
            msg = str(e)
            why = (f"the {body.year} tables are not published (yet)" if "HTTP 404" in msg
                   else "federalreserve.gov could not be reached from this server"
                   if "HTTP 0" in msg else msg[:120])
            raise HTTPException(502, f"Could not download the Fed's tables: {why}. "
                                     "Upload the four files instead.") from e
    v = _vintage(body.vintage)
    w = region_weights(store(), v, body.year)
    try:
        scn = fed_scenario(body.year, tables, w)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return js({"scenario": scn, "fetched": fetched, "urls": fed_urls(body.year),
               "weights": w})


# ---------------------------------------------------------------- system --
@router.get("/scenarios/system")
def system_table(vintage: str | None = None) -> dict:
    """The linked effects as estimated on the vintage: one row per
    equation term, and every historical library shock recomputed on it."""
    v = _vintage(vintage)
    system = _system(v)
    return js({"vintage": v, "table": system.table(), "variables": _variables(system),
               "library_check": check_library(system)})


# ------------------------------------------------------------------ pricing --
def _summary(r: dict) -> dict:
    if not r.get("ok"):
        raise HTTPException(400, r.get("reason", "The scenario could not be priced."))
    out = {k: r[k] for k in ("name", "id", "before", "after", "delta", "pct", "years",
                             "severity", "recommended", "staging", "collateral", "pd12",
                             "notes")}
    for k in ("paths", "waterfall", "by_book", "by_segment", "by_portfolio", "by_stage"):
        out[k] = r[k]
    bc = r.get("by_customer")
    out["by_customer"] = bc[bc["change"].abs() > 0].head(50) if bc is not None else []
    return js(out)


class RunIn(BaseModel):
    scenario: dict
    vintage: str | None = None


@router.get("/scenarios/{run_id}/context")
def context(run_id: str, vintage: str | None = None) -> dict:
    """The run as scenarios see it: year 1, the provision, the books, and
    the notes on what was read."""
    rc, v, cfg = _rc(run_id, vintage)
    seg = pd.DataFrame({"segment": rc.segment,
                        "book": np.where(rc.external, "Externally rated", "Internally rated")})
    by = seg.value_counts().rename("contracts").reset_index()
    return js({"run": run_id, "vintage": v, "first_year": rc.first_year, "horizon": rc.H,
               "ecl": rc.base_total, "segments": by, "notes": rc.notes,
               "stage1": int((rc.stage0 == 1).sum())})


@router.post("/scenarios/{run_id}/price")
def price(run_id: str, body: RunIn) -> dict:
    """Price one scenario: totals, the waterfall by channel, every
    variable's path, and the split by book, sector, portfolio, stage and
    customer."""
    rc, v, cfg = _rc(run_id, body.vintage)
    scn = _scenario(body.scenario)
    r = _cached(("price", run_id, v, config_hash(cfg), _key(scn)),
                lambda: _summary(transmit(rc, scn)))
    return {**r, "name": scn.name, "id": scn.id}


@router.post("/scenarios/{run_id}/drivers")
def drivers(run_id: str, body: RunIn) -> dict:
    """The scenario's change split by its main variables (Shapley values:
    priced in full for up to three, read from the Monte Carlo proxy beyond
    and scaled to the full price)."""
    rc, v, cfg = _rc(run_id, body.vintage)
    scn = _scenario(body.scenario)
    n = len(scn.given(rc.H)) + (scn.restructured > 0)
    P = _proxy(run_id, body.vintage)[1] if n > 3 else None
    r = _cached(("drivers", run_id, v, config_hash(cfg), _key(scn)),
                lambda: st_risk.drivers(rc, scn, P=P))
    if not r.get("ok"):
        raise HTTPException(400, r.get("reason", "Could not split the scenario."))
    return js(r)


class CompareIn(BaseModel):
    scenarios: list[dict]
    vintage: str | None = None


@router.post("/scenarios/{run_id}/compare")
def compare(run_id: str, body: CompareIn) -> dict:
    """Several scenarios side by side: the change, its split by channel, and
    the internal PD driver's path in each."""
    rc, v, cfg = _rc(run_id, body.vintage)
    rows, chans, paths = [], [], []
    # the variables the PD models and collateral read, as stress.yml names them
    pl = rc.cfg.get("pd_link") or {}
    drivers = {k: pl[k] for k in ("internal", "external") if pl.get(k)}
    collateral = set((rc.cfg.get("collateral") or {}).keys())
    for d in body.scenarios:
        scn = _scenario(d)
        r = _cached(("price", run_id, v, config_hash(cfg), _key(scn)),
                    lambda scn=scn: _summary(transmit(rc, scn)))
        wf = {w["key"]: w["change"] for w in r["waterfall"]}
        rows.append({"id": scn.id, "scenario": scn.name, "category": scn.category,
                     "ecl": r["after"], "change": r["delta"], "change_pct": r["pct"],
                     "pd": wf.get("pd"), "staging": wf.get("staging"),
                     "collateral": wf.get("collateral"),
                     "stage_moves": r["staging"]["expected_moves"]})
        for w in r["waterfall"]:
            chans.append({"scenario": scn.name, "channel": w["layer"], "change": w["change"]})
        for p in r["paths"]:
            if p["variable"] in drivers.values() or p["variable"] in collateral:
                paths.append({**p, "level": p.get("scenario"), "scenario": scn.name})
    return js({"before": rc.base_total, "table": rows, "channels": chans, "paths": paths,
               "years": rc.years, "drivers": drivers})


class SensIn(BaseModel):
    size_sd: float = 1.0
    shape: str = "one_year"
    linked: bool = True
    vintage: str | None = None


@router.post("/scenarios/{run_id}/sensitivity")
def sensitivity(run_id: str, body: SensIn) -> dict:
    """An adverse move of ``size_sd`` standard deviations in each variable,
    on its own with its linked effects, ranked."""
    rc, v, cfg = _rc(run_id, body.vintage)
    return js(_cached(("sens", run_id, v, config_hash(cfg), body.size_sd, body.shape,
                       body.linked),
                      lambda: st_risk.sensitivity(rc, body.size_sd, body.shape, body.linked)))


class CurveIn(BaseModel):
    variable: str
    shape: str = "one_year"
    linked: bool = True
    vintage: str | None = None


@router.post("/scenarios/{run_id}/sensitivity/curve")
def sensitivity_curve(run_id: str, body: CurveIn) -> dict:
    """The change in ECL as one variable moves from -3 to +3 standard
    deviations (positive is adverse)."""
    rc, v, cfg = _rc(run_id, body.vintage)
    if body.variable not in rc.system.order:
        raise HTTPException(404, f"No variable {body.variable!r}")
    t = _cached(("curve", run_id, v, config_hash(cfg), body.variable, body.shape, body.linked),
                lambda: st_risk.sensitivity_curve(rc, body.variable, shape=body.shape,
                                                  linked=body.linked))
    return js({"variable": body.variable, "label": rc.system.label(body.variable),
               "unit": rc.system.unit(body.variable), "sd": rc.system.sd(body.variable),
               "curve": t})


@router.post("/scenarios/{run_id}/pd_link")
def pd_link(run_id: str, body: RunIn) -> dict:
    """The scenario at both ends of the PD model's slope range."""
    rc, v, cfg = _rc(run_id, body.vintage)
    scn = _scenario(body.scenario)
    return js(_cached(("pdlink", run_id, v, config_hash(cfg), _key(scn)),
                      lambda: st_risk.pd_link_range(rc, scn)))


class RiskIn(BaseModel):
    paths: int | None = None
    seed: int | None = None
    threshold: float | None = None
    vintage: str | None = None


@router.post("/scenarios/{run_id}/risk")
def risk(run_id: str, body: RiskIn) -> dict:
    """ECL at risk: the provision over thousands of macro paths drawn from
    the linked-effects system, its tail, the sectors and channels behind
    it, the credit loss from customer default draws, and where every
    scenario falls in the distribution."""
    rc, P, v, cfg = _proxy(run_id, body.vintage)
    rcfg = cfg.get("risk") or {}
    n = int(body.paths or rcfg.get("paths", 2000))
    seed = int(body.seed or rcfg.get("seed", 20261027))
    scns = _all_scenarios()
    r = _cached(("risk", run_id, v, config_hash(cfg), n, seed,
                 tuple(_key(s) for s in scns)),
                lambda: st_risk.ecl_at_risk(rc, P, n=n, seed=seed, scenarios=scns))
    ecl = np.asarray(r["ecl"])
    hist, edges = np.histogram(ecl, bins=40)
    out = {k: r[k] for k in ("paths", "seed", "base", "summary", "by_segment", "by_channel",
                             "named", "loss_summary", "customers", "expected_loss")}
    out["histogram"] = [{"from": float(edges[i]), "to": float(edges[i + 1]),
                         "count": int(hist[i])} for i in range(len(hist))]
    out["mean"] = float(ecl.mean())
    if r.get("credit_loss") is not None:
        cl = np.asarray(r["credit_loss"])
        h2, e2 = np.histogram(cl, bins=40)
        out["loss_histogram"] = [{"from": float(e2[i]), "to": float(e2[i + 1]),
                                  "count": int(h2[i])} for i in range(len(h2))]
    if body.threshold is not None:
        out["threshold"] = body.threshold
        out["p_exceed"] = float(np.mean(ecl > float(body.threshold)))
    return js(out)


@router.get("/scenarios/{run_id}/proxy_check")
def proxy_check(run_id: str, vintage: str | None = None) -> dict:
    """The Monte Carlo pricing against full repricing on every scenario."""
    rc, P, v, cfg = _proxy(run_id, vintage)
    scns = _all_scenarios()
    return js({"table": _cached(("check", run_id, v, config_hash(cfg),
                                 tuple(_key(s) for s in scns)),
                                lambda: st_risk.proxy_check(rc, P, scns))})


class ReverseIn(BaseModel):
    target: float = Field(..., description="the increase in ECL to reach, QAR")
    vintage: str | None = None


@router.post("/scenarios/{run_id}/reverse")
def reverse(run_id: str, body: ReverseIn) -> dict:
    """What raises the provision by ``target``: how far each scenario must
    be scaled, how large a shock each variable needs, and how often the
    macro paths get there."""
    rc, P, v, cfg = _proxy(run_id, body.vintage)
    scns = _all_scenarios()
    r = _cached(("reverse", run_id, v, config_hash(cfg), round(float(body.target), 2),
                 tuple(_key(s) for s in scns)),
                lambda: st_risk.reverse(rc, P, float(body.target), scenarios=scns))
    return js(r)
