"""Macro stress scenarios: shocks on any variable of the macro store, priced
on a run.

Every endpoint is a call to ``ifrs9qdb.stresstest``; a scenario prices
through the same repricing as the stress packages and the run itself, so an
empty scenario is the run's provision. Reading a run for scenarios (its
contracts, curves, sectors and the macro model) takes a few seconds and the
Monte Carlo proxy half a minute, so both are kept per run, store vintage and
stress config; a Monte Carlo result is kept too, until any of those change.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ifrs9qdb.macro import concepts as macro_concepts
from ifrs9qdb.macro import refresh
from ifrs9qdb.macro.var import fit_macro_model
from ifrs9qdb.stresstest import (Scenario, library, prepare, read_scenarios,
                                 read_stress_config, transmit, write_scenarios)
from ifrs9qdb.stresstest import risk as st_risk
from ifrs9qdb.stresstest.config import config_hash
from ifrs9qdb.stresstest.scenarios import scenario_paths

from ..settings import PROJECT_ROOT, RUNS_DIR, STRESS_SCENARIOS_FILE
from .macro import js, store
from .runs import _output_dir
from .stress import _load

router = APIRouter(tags=["scenarios"])

_LOCK = threading.Lock()
_KEY_LOCKS: dict = {}
_CACHE: "OrderedDict[tuple, object]" = OrderedDict()
_MAX = 12


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


def _vintage(v: str | None) -> str:
    """The vintage asked for, else the latest. An empty store is seeded with
    the package's own history (GCC growth, non-oil GDP) so scenarios work
    before the first refresh; the Macro data page fetches the rest."""
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


def _model(vintage: str, cfg: dict):
    mm = cfg.get("macro_model") or {}

    def build():
        return fit_macro_model(store(), vintage=vintage, project_root=PROJECT_ROOT,
                               min_years=int(mm.get("min_years", 12)),
                               tightness=float(mm.get("tightness", 0.2)),
                               cross=float(mm.get("cross", 0.5)),
                               start_year=int(mm.get("start_year", 1990)),
                               extra=list(macro_concepts(PROJECT_ROOT)["concept"]))
    return _cached(("model", vintage, config_hash(cfg)), build)


def _run_path(run_id: str) -> Path:
    out = _output_dir(RUNS_DIR / run_id)
    if out is None:
        raise HTTPException(404, f"No run named {run_id!r}")
    return out.parent if out != RUNS_DIR / run_id else RUNS_DIR / run_id


def _rc(run_id: str, vintage: str | None):
    cfg = _cfg()
    v = _vintage(vintage)
    model = _model(v, cfg)

    def build():
        inputs, report = _load(run_id)
        return prepare(inputs, report, _run_path(run_id), store(), model=model, cfg=cfg,
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


def _concept_table(model, cfg) -> list[dict]:
    cat = macro_concepts(PROJECT_ROOT)
    rows = []
    for _, r in cat.iterrows():
        c = r["concept"]
        rows.append({"concept": c, "label": r["label"], "unit": r["unit"],
                     "core": bool(r["core"]), "in_model": c in model.concepts,
                     "in_var": c in model.var_concepts,
                     "sd": model.sd.get(c, None)})
    return rows


# ---------------------------------------------------------------- catalogue --
@router.get("/scenarios/setup")
def setup(vintage: str | None = None) -> dict:
    """What a scenario can be built from: the variables with their units and
    standard deviations, the library, the saved scenarios, the horizon and
    the store vintage the macro model was fitted on."""
    cfg = _cfg()
    v = _vintage(vintage)
    model = _model(v, cfg)
    st = store()
    return js({"vintage": v, "vintages": list(st.vintages()["vintage"])[::-1],
               "horizon": int(cfg.get("horizon_years", 5)),
               "model_years": list(model.years), "var_concepts": model.var_concepts,
               "concepts": _concept_table(model, cfg),
               "library": [s.to_dict() for s in library()],
               "saved": [s.to_dict() for s in read_scenarios(STRESS_SCENARIOS_FILE)],
               "config_path": cfg.get("_path", ""),
               "shapes": ["one_year", "held", "build", "recover", "custom"]})


class SavedIn(BaseModel):
    scenarios: list[dict] = Field(default_factory=list)


@router.get("/scenarios/saved")
def saved() -> list[dict]:
    """The project's config/stress_scenarios.yml, which the R app reads and
    writes too."""
    return js([s.to_dict() for s in read_scenarios(STRESS_SCENARIOS_FILE)])


@router.put("/scenarios/saved")
def save(body: SavedIn) -> dict:
    p = write_scenarios([_scenario(d) for d in body.scenarios], STRESS_SCENARIOS_FILE)
    return {"saved": len(body.scenarios), "path": str(p)}


class PreviewIn(BaseModel):
    scenario: dict
    vintage: str | None = None
    first_year: int | None = None


@router.post("/scenarios/preview")
def preview(body: PreviewIn) -> dict:
    """A scenario's paths for every variable (given and knock-on) and its
    severity, without pricing: the macro model alone."""
    cfg = _cfg()
    v = _vintage(body.vintage)
    model = _model(v, cfg)
    H = int(cfg.get("horizon_years", 5))
    scn = _scenario(body.scenario)
    sp = scenario_paths(scn, model, H)
    y0 = body.first_year
    years = list(range(y0, y0 + H)) if y0 else list(range(1, H + 1))
    labels = dict(zip(macro_concepts(PROJECT_ROOT)["concept"],
                      macro_concepts(PROJECT_ROOT)["label"]))
    rows = []
    for c, p in sp["paths"].items():
        p = np.asarray(p, float)
        if not np.any(np.abs(p) > 1e-9):
            continue
        rows.append({"concept": c, "label": labels.get(c, c), "given": c in sp["given"],
                     "sd": model.sd.get(c), **{str(y): float(p[j]) for j, y in enumerate(years)}})
    return js({"years": years, "paths": rows, "severity": sp["severity"],
               "outside_model": [c for c in scn.concepts() if c not in model.concepts]})


# ------------------------------------------------------------------ pricing --
def _result(r: dict) -> dict:
    if not r.get("ok"):
        raise HTTPException(400, r.get("reason", "The scenario could not be priced."))
    out = {k: r[k] for k in ("name", "before", "after", "delta", "pct", "severity", "years",
                             "moved", "customers_moved", "notes")}
    for k in ("paths", "waterfall", "by_book", "by_segment", "by_portfolio", "by_stage",
              "migration"):
        out[k] = r[k]
    out["by_customer"] = r["by_customer"].head(50) if r.get("by_customer") is not None else []
    info = r.get("info") or {}
    out["info"] = {k: v for k, v in info.items()
                   if isinstance(v, (int, float, str, bool, dict, list)) and k != "rows"}
    return js(out)


class RunIn(BaseModel):
    scenario: dict
    vintage: str | None = None


@router.get("/scenarios/{run_id}/context")
def context(run_id: str, vintage: str | None = None) -> dict:
    """The run as scenarios see it: the first forecast year, the provision,
    contracts by segment and book, and the notes on what was read."""
    rc, v, cfg = _rc(run_id, vintage)
    seg = pd.DataFrame({"segment": rc.segment,
                        "book": np.where(rc.external, "Externally rated", "Internally rated")})
    by = seg.value_counts().rename("contracts").reset_index()
    return js({"run": run_id, "vintage": v, "first_year": rc.first_year, "horizon": rc.H,
               "ecl": float(np.nansum(rc.base["ecl"])), "segments": by,
               "notes": rc.notes, "linked": [{"concept": c, "adverse": s, "channel": ch}
                                             for c, (s, ch) in
                                             st_risk.linked_concepts(rc).items()]})


@router.post("/scenarios/{run_id}/run")
def run(run_id: str, body: RunIn) -> dict:
    """Price one scenario: totals, the waterfall by layer, the paths, the
    severity and the split by book, segment, portfolio, stage and customer."""
    rc, _, _ = _rc(run_id, body.vintage)
    return _result(transmit(rc, _scenario(body.scenario)))


@router.post("/scenarios/{run_id}/shapley")
def shapley(run_id: str, body: RunIn) -> dict:
    """The scenario's change split by its shocks (Shapley values)."""
    rc, _, _ = _rc(run_id, body.vintage)
    r = st_risk.shapley(rc, _scenario(body.scenario))
    if not r.get("ok"):
        raise HTTPException(400, r.get("reason", "Could not split the scenario."))
    return js(r)


class CompareIn(BaseModel):
    scenarios: list[dict]
    vintage: str | None = None


@router.post("/scenarios/{run_id}/compare")
def compare(run_id: str, body: CompareIn) -> dict:
    """Several scenarios side by side, each with its waterfall."""
    rc, _, _ = _rc(run_id, body.vintage)
    rows, layers, segs = [], [], []
    for d in body.scenarios:
        r = transmit(rc, _scenario(d))
        if not r.get("ok"):
            rows.append({"scenario": d.get("name", ""), "error": r.get("reason")})
            continue
        sev = r["severity"] or {}
        rows.append({"scenario": r["name"], "ecl": r["after"], "change": r["delta"],
                     "change_pct": r["pct"], "one_in": sev.get("one_in"),
                     "moved": r["moved"]})
        for _, w in r["waterfall"].iterrows():
            layers.append({"scenario": r["name"], "layer": w["layer"], "change": w["change"]})
        for _, s in r["by_segment"].iterrows():
            segs.append({"scenario": r["name"], "segment": s["segment"],
                         "change": s["change"], "change_pct": s["change_pct"]})
    return js({"before": float(np.nansum(rc.base["ecl"])), "table": rows,
               "layers": layers, "segments": segs})


@router.get("/scenarios/{run_id}/sensitivity")
def sensitivity(run_id: str, size_sd: float = 1.0, shape: str = "held",
                knock_on: bool = False, vintage: str | None = None) -> dict:
    """An adverse move of ``size_sd`` standard deviations in each variable
    that reaches the book, on its own, ranked; and by segment."""
    rc, _, _ = _rc(run_id, vintage)
    return js(st_risk.sensitivities(rc, size_sd=size_sd, shape=shape, knock_on=knock_on))


class RiskIn(BaseModel):
    paths: int | None = None
    seed: int | None = None
    threshold: float | None = None
    vintage: str | None = None


@router.post("/scenarios/{run_id}/risk")
def risk(run_id: str, body: RiskIn) -> dict:
    """ECL at risk: the provision over thousands of macro paths drawn from
    the model, its tail, the segments and channels behind the tail, the
    credit loss from customer default draws, and where the named scenarios
    fall in the distribution."""
    rc, P, v, cfg = _proxy(run_id, body.vintage)
    rcfg = cfg.get("risk") or {}
    n = int(body.paths or rcfg.get("paths", 2000))
    seed = int(body.seed or rcfg.get("seed", 20261023))
    scns = library() + read_scenarios(STRESS_SCENARIOS_FILE)
    r = _cached(("risk", run_id, v, config_hash(cfg), n, seed, len(scns)),
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
    """The Monte Carlo pricing against full repricing on the library."""
    rc, P, _, _ = _proxy(run_id, vintage)
    return js({"table": st_risk.proxy_check(rc, P)})


class ReverseIn(BaseModel):
    target: float = Field(..., description="the increase in ECL to reach, QAR")
    vintage: str | None = None


@router.post("/scenarios/{run_id}/reverse")
def reverse(run_id: str, body: ReverseIn) -> dict:
    """The most likely macro path that raises the provision by ``target``."""
    rc, P, _, _ = _proxy(run_id, body.vintage)
    r = st_risk.reverse(rc, P, float(body.target))
    if not r.get("ok"):
        raise HTTPException(400, r.get("reason", "No path found."))
    out = {k: v for k, v in r.items() if k != "result"}
    if r.get("result"):
        res = r["result"]
        out["waterfall"] = res["waterfall"]
        out["by_segment"] = res["by_segment"]
    return js(out)
