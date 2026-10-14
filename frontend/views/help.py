"""How the tool works, and where each number comes from."""
import streamlit as st

import api
from ui import caption, page_setup

page_setup("Help",
           "What this tool does, in the order you would use it.")

st.markdown("""
## The shape of a quarter

1. **Run the pipeline.** Point it at the twelve source extracts. It reads
   them, builds the eighteen LIC input files, prices the book and writes a run
   folder that is never overwritten — reproducing a quarter means it must
   still be there.
2. **Read the validation.** A run that completes is not the same as a run that
   is safe to sign. 114 checks say which it is.
3. **Look at the portfolio.** Overview, staging, risk parameters,
   concentration, segments, scenarios and data quality all read the same
   priced report, as booked. What-ifs are stress tests, under Stress
   testing.
4. **Compare.** Movement against the previous quarter says how much the
   provision moved and why, cause by cause; Migration says who moved stage
   or rating; Reconcile & export says which files differ.
5. **Overlay, then approve.** Management overlays sit on top of a completed
   run rather than inside it, so the engine's number stays visible underneath.

## Which page answers which question

| Question | Page |
| --- | --- |
| How much, and where does it sit? | Overview, Staging, Concentration |
| What is it made of? | Risk parameters |
| What would a worse world cost? | Scenarios, Macro & scenarios |
| How much did it move, and *why*? | Movement |
| Who moved? | Migration |
| What assumptions produced it? | Model assumptions |
| What if these customers, or this portfolio, deteriorated? | Stress test |
| What would a different staging policy cost? | Stress test, Sensitivity (Staging threshold) |
| Which lever matters most, and how far would it have to go? | Sensitivity |
| What would different scenario weights cost? | Macro & scenarios |
| How is the book spread? | Risk parameters (Exposure), Segments |
| Is the run safe to sign? | Validation |
| Anything, in plain language | Assistant |

**Movement reprices, it does not apportion.** Every contract is priced with
the same ECL function the pipeline uses, once per cause, changing one input at
a time from the previous run to this one (exposure, then stage, rating, macro
inputs, PD model, LGD and collateral, overlay), so the steps sum exactly to
the closing provision. Stress tests reprice with that same function, so a
number on one page cannot disagree with another.

**A stress test is one thing.** It names who it reaches -- portfolios, stages
and customers, together -- and what changes for them: the staging policy, a
forced stage, the largest customers defaulting, the PD, a downgrade, the LGD,
collateral, exposure, the term. A what-if on named customers, a staging-policy
change and a standard package are all stress tests, priced by one engine
function, and every lever reaches the scope and nothing else. Several run side
by side; saved ones are shared with the R app.

**Macro & scenarios rebuilds the whole PD chain** from the config the run
froze, with the forecast or the scenario weights edited. The scenario-weight switch on that page is not a
detail: the internal weights are derived from the first forecast years of the
same matrix, so editing non-oil GDP moves the weights *and* the curves, and
the two can point in opposite directions. Holding the weights isolates the PD
effect.

## Where the numbers come from

Every figure on every page is computed by the `ifrs9qdb` package and served
through the API. Nothing is calculated in the interface, so any number here
can be reproduced in a notebook with the same call — and the interface cannot
quietly disagree with the engine.

## Two things worth knowing

**Stage 3 is provisioned at the full outstanding balance.** That is QDB's
booking basis and it deliberately diverges from what LIC reports, which is
zero. A reconciliation against a LIC extract will therefore show Stage 3
differences by design.

**ECL is capped at the on-balance exposure.** A supplied EAD curve can rise
above today's outstanding, because it includes expected drawdowns on undrawn
commitments. The cap is parity with LIC, not a divergence.

## Validation severities

- **ERROR** — the numbers are wrong or cannot be computed. The run does not
  pass.
- **WARN** — computable, but something is off and a person should look before
  signing.
- **INFO** — worth knowing, not worth stopping for.

A finding can be **accepted** rather than fixed, on the Accepted findings
page, provided a reason and an approver are recorded. The alternative — people
learning to ignore a permanently red screen — is worse than an explicit,
auditable exception.

## The assistant

It answers questions about the runs by looking them up, not by remembering
them. Ten read-only tools are its entire view of the data — a run list, file
and column descriptions, group-by aggregations, run-to-run comparisons, a
row-level diff, filters, the frozen model spec and the validation report —
so every number it quotes came back from a real run during that conversation.
The lookups behind each answer are listed under it.

It cannot start a run, change config or approve anything, and it says which
page does when asked. It needs an OpenAI-compatible endpoint configured; with
none, the page says so and shows what it would be able to look at.

## Reproducing a past quarter

A run freezes the config and static reference it used, records where its
inputs came from, and stamps the calculator version and code fingerprint into
its manifest. Those four together are what let a number be defended months
later.
""")

st.markdown("## This deployment")
try:
    h = api.health()
    code = api.code_status()
    reg = api.calculator_versions()
except api.BackendError as e:
    st.error(str(e))
else:
    c1, c2, c3 = st.columns(3)
    c1.metric("Engine", h.get("engine_version", "—"))
    c2.metric("Calculator", (reg.get("for_run") or {}).get("id") or "—")
    c3.metric("Code", (code.get("sha") or "—")[:12])
    caption(f"API at {api.BACKEND}")
