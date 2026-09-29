"""Run the pipeline with an ARCHIVED calculator version, in its own process.

The R app sources an archived version's code into a fresh environment and runs
that. Python cannot swap a live package's modules safely, so the app starts
this script in a separate interpreter whose ``PYTHONPATH`` puts the archived
copy of ``ifrs9qdb`` first: the run is then produced by that version's code,
end to end.

    python archived_runner.py <args.json> <result.json>

``args.json`` holds ``input_dir``, ``runs_dir`` and ``kwargs`` for
``run_etl``. Arguments the archived version does not accept are dropped and
listed in the result, so a caller can say what an older calculator could not
do (an old version with no override support, say) instead of pretending.
"""
from __future__ import annotations

import inspect
import json
import sys
import traceback


def main(args_path: str, result_path: str) -> int:
    with open(args_path, encoding="utf-8") as fh:
        args = json.load(fh)
    out: dict = {"ok": False}
    try:
        import ifrs9qdb
        from ifrs9qdb.etl import pipeline
        kw = dict(args.get("kwargs") or {})
        sig = inspect.signature(pipeline.run_etl)
        takes_any = any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values())
        dropped = [] if takes_any else [k for k in kw if k not in sig.parameters]
        for k in dropped:
            kw.pop(k)
        r = pipeline.run_etl(args["input_dir"], args["runs_dir"], **kw)
        out = r.as_dict()
        out["dropped_args"] = dropped
        out["engine_file"] = getattr(ifrs9qdb, "__file__", "")
        out["engine_version"] = getattr(ifrs9qdb, "__version__", "")
    except Exception as exc:  # reported, not raised: the caller reads the file
        out = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
               "traceback": traceback.format_exc()}
    with open(result_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, default=str)
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
