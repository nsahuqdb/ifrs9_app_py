# The R app, feature by feature, in this app

Every page and control of the R Shiny app (`ifrs9_app`), where it lives here,
and how it was checked. **Every R feature is present.** Where this app does
something differently, it is listed at the end with the reason.

"Browser" means the flow was driven end to end in Chromium against a project
folder holding R and Python runs; "rendered" means the page and every tab were
opened in Chromium without an error; "API" and "engine tests" mean covered by
the test suites.

## Runs → Browse runs (`mod_runs.R` → `views/runs.py`)

| R app | Here | Checked |
|---|---|---|
| Runs table: status, run, date, purpose, type, scenario, portfolio date, run by, approver, config version, calculator, outputs, validation fails, reconciliation; search, sort, page | the same columns, plus the engine that produced the run and whether it carries a readiness report | browser |
| Tiles: total, approved, pending checker, unofficial, with validation fails; runs folder and Refresh | the same | browser |
| Run title, status pill, path | the same | browser |
| Export card, gated: approved or unofficial only, UNOFFICIAL marking, include-inputs choice, zip download; the handler refuses a run that is not exportable | the same, gate enforced in the backend too | browser: 66 files, 9.7 MB, downloaded |
| Apply an overlay to the run (drafts included, status shown); totals model → overlay → final; conflicts; applied list with Remove | the same | rendered; applied in the browser from the overlays page |
| Tabs: Manifest, Validation, Overrides, Reconciliation, Outputs (file pick, size, filterable preview) | the same, plus **Readiness** | browser: every tab |

## Runs → Run the pipeline (`mod_run_trigger.R` → `views/pipeline.py`)

| R app | Here | Checked |
|---|---|---|
| Input source: configured folder / data-drop folder (name, files, complete or INCOMPLETE, newest first) / zip upload (limit shown; files at the top or in one folder; .xlsx or SQL*Plus .xls) | the same, plus a folder on the server | browser: drop folders |
| Validate inputs: structural PASS/FAIL, "All N checks passed" or "N FAIL — Pre-run check disabled", failures listed | the same | browser |
| Data-quality preview: every input check against the chosen version, advisory; repeated-header auto-fix note; "Fix in CONFIG" / "Look in INPUT file" | the same | browser |
| Portfolio date filled from the inputs' EXTRACTDA | the same | browser: 2026-06-09 |
| Config version picker, active version first; status and description | the same | browser |
| Run type; official needs an approved version; purpose follows the type | the same | browser: allowed on an approved version; API: refused on the default config |
| Calculator version picker, fingerprint, archived-code or live badge | the same; an archived version runs its archived code | API |
| Pre-run check: config, static and input checks with the version's suppressions; "N ERROR — Run blocked" / "N WARN — review then proceed"; flagged checks; cleared when the run type or version changes | the same | browser: 5 ERROR on the injected-defect drop, 11 WARN on the repaired one |
| **Pricing readiness** (new in both apps): no ECL, blank in LIC, priced from incomplete inputs; reasons with fixes; row funnel; contracts with a gap | the same; an unsuppressed READY ERROR disables Start, as in the R app | browser |
| Start, gated; "Start OFFICIAL run" / "Start unofficial run" | the same | browser |
| Pause: customers, investments, findings; customer view with filter; one customer at a time | the same, with paging and a stage filter | browser |
| Override editor: rating (master scale), stage (worsening only), restructuring; reason required | the same | browser: a reason-less override refused |
| Pending overrides per kind, with remove | the same | browser (add) |
| Continue (overrides applied, written to `overrides/*.csv` with who, when, prior value) / Cancel | the same | browser: override landed in `CustomerStagingFlag_1` |
| Summary: pending approval or unofficial, duration, outputs, overrides, path, next step, start another | the same, plus readiness counts | browser |
| Run metadata in the manifest: type, purpose, portfolio date, config version, calculator id/label/hash/match | the same, R's manifest schema | read from the manifests of the browser runs |

## Runs → Approval queue (`mod_approval_queue.R` → `views/approval.py`)

| R app | Here | Checked |
|---|---|---|
| Pending runs table | the same, with duration, outputs, validation fails, overrides | browser |
| Run review: dev-mode banner when separation is off; Validation / Overrides applied / Outputs tabs | the same, plus the readiness line | browser |
| Approve / Reject: maker, acting user, separation flag; reason required; Approve disabled for the maker when separation is enforced | the same | browser: approved by checker1; engine tests: the maker refused |
| History of runs with the audit trail | the same | rendered |
| Pending versions: approve or reject with a reason | the same | rendered; a version approved in the browser from Config versions |
| History of versions | the same | rendered |

## Config (`mod_snapshots.R`, `mod_snapshot_manager.R`, `mod_snapshot_editor.R`, `mod_calculator_versions.R` → `views/snapshots.py`, `views/calculator.py`)

| R app | Here | Checked |
|---|---|---|
| Versions table and detail: metadata; every file under `config/` and `static/`, read-only, 200 KB preview | the same | rendered |
| Create: label pattern, description required, base version | the same | browser |
| Promote: draft → tested → pending_final → approved; reason required; the creator cannot approve under separation | the same | browser: created by maker1, approved by checker1 |
| Edit config: drafts only, clone a locked version to a new draft; files grouped, advanced toggle, help per file; YAML with discard and error context; CSV with add/delete rows, download, upload, discard | the same | rendered |
| Calculator versions: registered versions, active one, deployed-code fingerprint and match; register; set active | the same | rendered |

## ECL overlays (`mod_overlays.R` → `views/overlays.py`)

| R app | Here | Checked |
|---|---|---|
| Value guide; values entered in percent, stored as fractions | the same | browser |
| Rules: method, level (whole book, stage, portfolio, rating, flag, sector, customer, contract), target, value, reason | the same; the target is typed (with a guide per level) where R offers a picker | browser |
| Save: an existing id asks replace or append; any save returns the overlay to draft | the same | browser (a new overlay); API |
| Preview against a run: model, overlay, final, per rule; conflicts (a contract matched twice) block | the same | browser: +QAR 87,785,735 (+4.46%) |
| Saved list: Submit (draft/rejected), Approve / Reject (pending), Edit, Remove with confirmation | the same | browser: submitted by maker1, approved by checker1 |
| Apply to a run; applied list; remove its outputs | the same | browser (apply, list) |

## Validation suppressions (`mod_suppressions.R` → `views/suppressions.py`)

| R app | Here | Checked |
|---|---|---|
| The project's `config/validation_suppressions.yml`, applying to the next pre-run check and run | the same file | browser |
| Add: validator, reason (required), approver, optional expiry | the same | browser: a reason-less add refused; the add written in R's schema and audited |
| Catalogue of failed validators across recent runs, by stage | the same | rendered |
| Active suppressions | the same, active or lapsed | browser |

## Audit log (`mod_audit_log.R` → `views/audit.py`)

| R app | Here | Checked |
|---|---|---|
| The project log `logs/etl_audit.jsonl`, path and count, refresh | the same file; both apps write the same events | browser |
| Filters: event, run, user | the same | rendered |
| Friendly label and a sentence per event | the same labels and sentences in both apps, including the new readiness, approval, cancel and overlay events | API |

## Analytics, assistant, help (`mod_analytics.R`, `mod_chatbot.R`, `mod_help.R`)

Every analytics tab is a page here (portfolio, comparison and stress groups).
Like the R app, the pages read the **overlaid** report when an overlay has been
applied to a run. The assistant (grounded on the runs, read-only tools) and the
help page are present.

## Where this app differs, deliberately

| | R app | Here | Why |
|---|---|---|---|
| Cancel at the pause | resets the page; the partial run folder stays | removes the partial folder and logs `run_cancelled` | a cancelled run should not appear in Browse runs |
| Confirmations after an action | a notification | a message at the top of the page that survives the page's rerun | Streamlit reruns the page after an action; without it the message was lost |
| The pre-run readiness dry run | runs in the session (the page waits) | runs as a background job with progress | long runs do not block the page |
| Indicative attribution | not shown in the R app | shown, with an **Overlay** line when a run carries an overlay | the factors explain the model move and the overlay line the adjustment |
| Assistant on an overlaid run | reads the file it is asked for | reads the overlaid report, as the pages do, and says so | one provision per run everywhere |
| Who is acting | the OS user | `IFRS9_USER`, or the name entered on the page | the app has no login of its own |
| A config version's runtime paths | resolved inside the version (so input and drops warn as missing) | resolved against the project | the version freezes config, not the input folders |

## How it was checked

* Every page loaded in Chromium with no exception (34 pages).
* The flows above, end to end: an injected-defect drop blocked (5 errors, 1
  contract blank in LIC); a repaired drop run unofficial with a stage override
  and cancelled; a config version created, tested, submitted and approved by a
  second user; an official run on it, paused, overridden, finished and approved
  by the checker; a suppression, an overlay built, previewed, submitted,
  approved and applied; the run exported and downloaded.
* The R app's new readiness panel, Start gate, Readiness tab and audit labels,
  driven the same way.
* `tests/`: all pass with and without a project of runs.
