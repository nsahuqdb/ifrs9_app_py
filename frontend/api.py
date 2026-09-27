"""
The frontend's only route to the numbers.

Every figure on screen comes from the backend over HTTP. The Streamlit process
never imports the calculation package, which keeps one honest boundary: if the
backend is down or a run is missing, the interface says so rather than quietly
computing something itself and drifting from what the API would return.

Caching matters more here than usual. Streamlit re-runs the whole script on
every widget change, so an uncached call would re-hit the backend on each
click, and the stress endpoints reprice thousands of contracts.
"""
from __future__ import annotations

import os

import requests
import streamlit as st

BACKEND = os.environ.get("IFRS9_BACKEND", "http://127.0.0.1:8000")
TIMEOUT = (5, 180)  # connect, read: a stress can take a couple of minutes


class BackendError(RuntimeError):
    """Raised with a message worth showing the user."""


def _url(path: str) -> str:
    return f"{BACKEND.rstrip('/')}/api{path}"


def _raise(resp: requests.Response) -> None:
    try:
        detail = resp.json().get("detail")
    except Exception:
        detail = None
    raise BackendError(detail or f"{resp.status_code} {resp.reason}")


def get(path: str, **params):
    try:
        r = requests.get(_url(path), params=params or None, timeout=TIMEOUT)
    except requests.exceptions.ConnectionError:
        raise BackendError(
            f"Cannot reach the backend at {BACKEND}. Start it with:\n\n"
            "`uvicorn backend.main:app --reload --port 8000`"
        )
    except requests.exceptions.ReadTimeout:
        raise BackendError("The backend took too long to respond.")
    if not r.ok:
        _raise(r)
    return r.json()


def post(path: str, payload: dict):
    try:
        r = requests.post(_url(path), json=payload, timeout=TIMEOUT)
    except requests.exceptions.ConnectionError:
        raise BackendError(
            f"Cannot reach the backend at {BACKEND}. Start it with:\n\n"
            "`uvicorn backend.main:app --reload --port 8000`"
        )
    except requests.exceptions.ReadTimeout:
        raise BackendError("The backend took too long to respond.")
    if not r.ok:
        _raise(r)
    return r.json()


def request(method: str, path: str, payload: dict | None = None):
    """Any other verb. DELETE mostly, which the two helpers above do not cover."""
    try:
        r = requests.request(method, _url(path), json=payload, timeout=TIMEOUT)
    except requests.exceptions.ConnectionError:
        raise BackendError(
            f"Cannot reach the backend at {BACKEND}. Start it with:\n\n"
            "`uvicorn backend.main:app --reload --port 8000`"
        )
    except requests.exceptions.ReadTimeout:
        raise BackendError("The backend took too long to respond.")
    if not r.ok:
        _raise(r)
    return r.json()


# ------------------------------------------------------------------ cached --
@st.cache_data(ttl=300, show_spinner=False)
def health() -> dict:
    return get("/health")


@st.cache_data(ttl=60, show_spinner=False)
def runs() -> list[dict]:
    return get("/runs")


@st.cache_data(ttl=30, show_spinner=False)
def diagnose() -> dict:
    """What the backend actually looked at when it found no runs."""
    return get("/runs/_diagnose")


@st.cache_data(ttl=600, show_spinner="Loading the run…")
def summary(run_id: str) -> dict:
    return get(f"/analytics/{run_id}/summary")


@st.cache_data(ttl=600, show_spinner=False)
def profile(run_id: str, by: str = "portfolio") -> list[dict]:
    return get(f"/analytics/{run_id}/portfolio", by=by)


@st.cache_data(ttl=600, show_spinner=False)
def staging(run_id: str, dpd_threshold: float = 60) -> dict:
    return get(f"/analytics/{run_id}/staging", dpd_threshold=dpd_threshold)


@st.cache_data(ttl=600, show_spinner=False)
def concentration(run_id: str, level: str = "customer") -> dict:
    return get(f"/analytics/{run_id}/concentration", level=level)


@st.cache_data(ttl=600, show_spinner=False)
def quality(run_id: str) -> list[dict]:
    return get(f"/analytics/{run_id}/quality")


@st.cache_data(ttl=600, show_spinner=False)
def maturity(run_id: str) -> list[dict]:
    return get(f"/analytics/{run_id}/maturity")


@st.cache_data(ttl=600, show_spinner="Comparing the runs…")
def walk(prev: str, curr: str) -> dict:
    return get("/analytics/walk", prev=prev, curr=curr)


@st.cache_data(ttl=600, show_spinner=False)
def scope(run_id: str) -> dict:
    return get(f"/stress/{run_id}/scope")


@st.cache_data(ttl=600, show_spinner="Repricing the book…")
def apply_stress(run_id: str, spec: dict) -> dict:
    return post(f"/stress/{run_id}/apply", spec)


@st.cache_data(ttl=600, show_spinner="Repricing once per lever…")
def tornado(run_id: str) -> dict:
    return get(f"/stress/{run_id}/tornado")


@st.cache_data(ttl=600, show_spinner="Solving each lever…")
def reverse(run_id: str, target_pct: float) -> list[dict]:
    return get(f"/stress/{run_id}/reverse", target_pct=target_pct)


@st.cache_data(ttl=600, show_spinner="Advancing the book…")
def rollforward(run_id: str, months: int) -> dict:
    return get(f"/stress/{run_id}/rollforward", months=months)


def clear() -> None:
    st.cache_data.clear()


# ------------------------------------------------------------------- ETL ---
@st.cache_data(ttl=15, show_spinner=False)
def etl_inputs(input_dir: str | None = None) -> dict:
    return get("/etl/inputs", **({"input_dir": input_dir} if input_dir else {}))


@st.cache_data(ttl=600, show_spinner=False)
def etl_coverage() -> dict:
    return get("/etl/coverage")


def etl_start(input_dir: str | None, reporting_date: str | None = None) -> dict:
    """Not cached: starting a run twice must start two runs."""
    return post("/etl/run", {"input_dir": input_dir,
                             "reporting_date": reporting_date})


def etl_status(job_id: str) -> dict:
    return get(f"/etl/run/{job_id}")


def etl_upload(files) -> dict:
    """Send source extracts to the backend's staging folder."""
    import requests as _rq
    payload = [("files", (f.name, f.getvalue())) for f in files]
    try:
        r = _rq.post(_url("/etl/upload"), files=payload, timeout=TIMEOUT)
    except _rq.exceptions.ConnectionError:
        raise BackendError(f"Cannot reach the backend at {BACKEND}.")
    if not r.ok:
        _raise(r)
    return r.json()


def etl_clear_uploads() -> dict:
    import requests as _rq
    r = _rq.delete(_url("/etl/upload"), timeout=TIMEOUT)
    if not r.ok:
        _raise(r)
    return r.json()


@st.cache_data(ttl=30, show_spinner=False)
def config() -> dict:
    return get("/config")


def config_save(name: str, content: str) -> dict:
    import requests as _rq
    r = _rq.put(_url("/config"), json={"name": name, "content": content},
                timeout=TIMEOUT)
    if not r.ok:
        _raise(r)
    return r.json()


@st.cache_data(ttl=300, show_spinner="Validating the run…")
def validation(run_id: str) -> dict:
    return get(f"/validation/{run_id}")


# ------------------------------------------------------------ governance ---
@st.cache_data(ttl=60, show_spinner=False)
def overlays() -> list:
    return get("/overlays")


def overlay_preview(run_id: str, specs: list) -> dict:
    return post(f"/overlays/{run_id}/preview", specs)


@st.cache_data(ttl=60, show_spinner=False)
def snapshot(run_id: str) -> dict:
    return get(f"/snapshot/{run_id}")


@st.cache_data(ttl=60, show_spinner=False)
def snapshot_compare(a: str, b: str) -> list:
    return get(f"/snapshot/{a}/compare/{b}")


@st.cache_data(ttl=30, show_spinner=False)
def audit(run_id: str) -> list:
    return get(f"/audit/{run_id}")


@st.cache_data(ttl=30, show_spinner=False)
def approval(run_id: str) -> dict:
    return get(f"/approval/{run_id}")


@st.cache_data(ttl=30, show_spinner=False)
def approval_queue() -> list:
    return get("/approval")


def approve(run_id: str, stage: str, approver: str, comment: str = "") -> dict:
    return post(f"/approval/{run_id}",
                {"stage": stage, "approver": approver, "comment": comment})


@st.cache_data(ttl=120, show_spinner="Comparing the runs…")
def reconcile(run_id: str, reference_id: str) -> dict:
    return get(f"/reconcile/{run_id}/against/{reference_id}")


@st.cache_data(ttl=60, show_spinner=False)
def output_summary(run_id: str) -> list:
    return get(f"/summary/{run_id}")


def export_run(run_id: str, include_inputs: bool = False) -> dict:
    return post(f"/export/{run_id}", {"include_inputs": include_inputs})


# ------------------------------------------- accepted findings -------------
@st.cache_data(ttl=30, show_spinner=False)
def suppressions(run_id: str) -> dict:
    return get(f"/suppressions/{run_id}")


def add_suppression(run_id: str, validator_id: str, reason: str,
                    approved_by: str, valid_until: str | None = None) -> dict:
    return post(f"/suppressions/{run_id}",
                {"validator_id": validator_id, "reason": reason,
                 "approved_by": approved_by, "valid_until": valid_until})


# ------------------------------------------- calculator versions -----------
@st.cache_data(ttl=30, show_spinner=False)
def calculator_versions() -> dict:
    return get("/calculator/versions")


def register_calculator(id: str, label: str = "", description: str = "",
                        created_by: str = "", make_active: bool = True) -> dict:
    return post("/calculator/versions",
                {"id": id, "label": label, "description": description,
                 "created_by": created_by, "make_active": make_active})


def activate_calculator(version_id: str) -> dict:
    return post(f"/calculator/active/{version_id}", {})


@st.cache_data(ttl=30, show_spinner=False)
def code_status() -> dict:
    return get("/code/status")


# ------------------------------------------------- maker-checker -----------
@st.cache_data(ttl=20, show_spinner=False)
def run_status(run_id: str) -> dict:
    return get(f"/runstatus/{run_id}")


@st.cache_data(ttl=20, show_spinner=False)
def approval_queue_status() -> dict:
    return get("/runstatus/queue")


def decide_run(run_id: str, decision: str, by: str, reason: str) -> dict:
    return post(f"/runstatus/{run_id}/{decision}", {"by": by, "reason": reason})


# ------------------------------------------------- config snapshots --------
@st.cache_data(ttl=20, show_spinner=False)
def snapshots() -> dict:
    return get("/snapshots")


@st.cache_data(ttl=20, show_spinner=False)
def snapshot_detail(label: str) -> dict:
    return get(f"/snapshots/{label}")


@st.cache_data(ttl=20, show_spinner=False)
def snapshot_file(label: str, relpath: str) -> dict:
    return get(f"/snapshots/{label}/file", relpath=relpath)


def create_snapshot(label: str, description: str, created_by: str,
                    parent: str | None = None) -> dict:
    return post("/snapshots", {"label": label, "description": description,
                               "created_by": created_by, "parent": parent})


def promote_snapshot(label: str, status: str, by: str, reason: str) -> dict:
    return post(f"/snapshots/{label}/promote",
                {"status": status, "by": by, "reason": reason})


def edit_snapshot(label: str, relpath: str, text=None, rows=None,
                  edited_by: str = "") -> dict:
    return post(f"/snapshots/{label}/edit",
                {"relpath": relpath, "text": text, "rows": rows,
                 "edited_by": edited_by})


@st.cache_data(ttl=20, show_spinner="Comparing…")
def diff_snapshots(a: str, b: str) -> dict:
    return get(f"/snapshots/{a}/diff/{b}")


# ------------------------------------------------- overlay bundles ---------
@st.cache_data(ttl=20, show_spinner=False)
def overlay_bundles() -> dict:
    return get("/overlay-bundles")


def save_overlay_bundle(bundle: dict) -> dict:
    return post("/overlay-bundles", bundle)


def delete_overlay_bundle(overlay_id: str) -> dict:
    return request("DELETE", f"/overlay-bundles/{overlay_id}")


def set_bundle_status(overlay_id: str, status: str, by: str,
                      reason: str) -> dict:
    return post(f"/overlay-bundles/{overlay_id}/status",
                {"status": status, "by": by, "reason": reason})


def preview_bundle(overlay_id: str, run_id: str) -> dict:
    return post(f"/overlay-bundles/{overlay_id}/preview/{run_id}", {})


def apply_bundle(overlay_id: str, run_id: str) -> dict:
    return post(f"/overlay-bundles/{overlay_id}/apply/{run_id}", {})


@st.cache_data(ttl=15, show_spinner=False)
def applied_overlays(run_id: str) -> dict:
    return get(f"/overlay-bundles/applied/{run_id}")


def remove_applied_overlay(run_id: str, overlay_id: str) -> dict:
    return request("DELETE", f"/overlay-bundles/applied/{run_id}/{overlay_id}")


# --------------------------------------------------------- analytics ------
@st.cache_data(ttl=600, show_spinner=False)
def risk(run_id: str, by: str = "stage", portfolio: str | None = None) -> dict:
    return get(f"/analytics/{run_id}/risk", by=by, portfolio=portfolio)


@st.cache_data(ttl=600, show_spinner=False)
def collateral(run_id: str) -> dict:
    return get(f"/analytics/{run_id}/collateral")


@st.cache_data(ttl=600, show_spinner=False)
def segments(run_id: str, rows: str = "portfolio", cols: str = "stage",
             value: str = "ecl") -> list[dict]:
    return get(f"/analytics/{run_id}/segments", rows=rows, cols=cols, value=value)


@st.cache_data(ttl=600, show_spinner=False)
def staging_detail(run_id: str, dpd_threshold: float = 60) -> dict:
    return get(f"/analytics/{run_id}/staging-detail", dpd_threshold=dpd_threshold)


@st.cache_data(ttl=600, show_spinner="Matching the two books…")
def migration(prev: str, curr: str, top: int = 12,
              by_customer: bool = True) -> dict:
    return get("/analytics/migration", prev=prev, curr=curr, top=top,
               by_customer=by_customer)


@st.cache_data(ttl=600, show_spinner="Attributing the movement…")
def attribution(prev: str, curr: str, by: str = "portfolio",
                exact: bool = False) -> dict:
    return get("/analytics/attribution", prev=prev, curr=curr, by=by, exact=exact)


@st.cache_data(ttl=600, show_spinner=False)
def scenarios(run_id: str) -> dict:
    return get(f"/analytics/{run_id}/scenarios")


def reweight(run_id: str, weights: dict, shift: float = 0.10) -> dict:
    return post(f"/analytics/{run_id}/scenarios/reweight",
                {"weights": weights, "shift": shift})


@st.cache_data(ttl=600, show_spinner=False)
def model_assumptions(run_id: str) -> dict:
    return get(f"/analytics/{run_id}/model")


@st.cache_data(ttl=600, show_spinner=False)
def quality_detail(run_id: str, n: int = 200) -> dict:
    return get(f"/analytics/{run_id}/quality-detail", n=n)


@st.cache_data(ttl=600, show_spinner=False)
def customers(run_id: str, ids: str) -> dict:
    return get(f"/analytics/{run_id}/customers", ids=ids)


@st.cache_data(ttl=600, show_spinner="Repricing at each threshold…")
def threshold_sweep(run_id: str, thresholds: str) -> dict:
    return get(f"/stress/{run_id}/threshold-sweep", thresholds=thresholds)


def mev_stress(run_id: str, cells: list, shock: dict, weight_mode: str,
               weights: dict | None = None) -> dict:
    return post(f"/stress/{run_id}/mev",
                {"cells": cells, "shock": shock, "weight_mode": weight_mode,
                 "weights": weights})


def whatif_match(run_id: str, rules: list) -> dict:
    return post(f"/stress/{run_id}/whatif/match", {"rules": rules})


def whatif(run_id: str, rules: list) -> dict:
    return post(f"/stress/{run_id}/whatif", {"rules": rules})


@st.cache_data(ttl=600, show_spinner=False)
def distributions(run_id: str) -> dict:
    return get(f"/analytics/{run_id}/distributions")


@st.cache_data(ttl=600, show_spinner="Matching the two books…")
def flows(prev: str, curr: str, by: str = "portfolio", n: int = 25) -> dict:
    return get("/analytics/flows", prev=prev, curr=curr, by=by, n=n)


def scenarios_rebuild(run_id: str) -> dict:
    return post(f"/analytics/{run_id}/scenarios/rebuild", {})


def compare_packages(run_id: str, packages: list) -> list:
    return post(f"/stress/{run_id}/compare", {"packages": packages})


@st.cache_data(ttl=30, show_spinner=False)
def assistant_status() -> dict:
    return get("/assistant/status")


def assistant_ask(question: str, run_id: str | None, history: list) -> dict:
    return post("/assistant/ask",
                {"question": question, "run_id": run_id, "history": history})


def export_download(run_id: str) -> bytes:
    """The packaged zip itself, so a server deployment can hand it over."""
    import requests as _r
    resp = _r.get(_url(f"/export/{run_id}/download"), timeout=TIMEOUT)
    _raise(resp)
    return resp.content
