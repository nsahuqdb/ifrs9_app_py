---
title: "Stress testing methodology"
subtitle: "Scenario stress (stressed ECL today and the five-year path) and parameter stress"
author: "QDB Financial Risk Management"
date: "Version 2.0 · November 2026 · engine 0.51"
---

# 1. What the stress test answers

The tool has two kinds of stress test:

| | Scenario stress | Parameter stress |
|---|---|---|
| Question | What would an economic scenario (a past crisis, a supervisor's scenario, a what-if) cost? | What if a model input changes, with no macro story (PDs up, ratings down, collateral down, staging tightened, large customers defaulting)? |
| Drives | macro variables → PD model → stages → collateral | the model's own parameters, directly |
| Pages | Stress testing → Scenario library, Scenario stress | Stress testing → Parameter stress |

Both reprice the book with the **same ECL function** the run used (ECL
methodology, section 10), so a stressed number and the booked number are
always comparable. Nothing in the run itself is changed.

**Scenario stress answers two questions, with two methods:**

| | Method 1: stressed ECL today | Method 2: five-year stress path |
|---|---|---|
| Question | If this scenario were our forecast today, what ECL would we book at the reporting date? | If the economy follows this scenario for five years, what will the provision be at the end of each year? |
| Result | one number per scenario, compared with the booked ECL | provision and yearly charge at the end of years 1 to 5, on the forecast and on the scenario |
| Main use | headline result; comparing scenarios; risk appetite; the "if it happened today" shock QCB uses in its own stress tests | ICAAP five-year capital projection (gross stress); stress tests in the style of EBA and the Bank of England |
| In the tool | **yes** (Scenario stress → Price, Compare, Sensitivity, ECL at risk, Reverse stress) | **specified here; to be built** |

**Common to both methods**

- **Starting point:** a completed ECL run (contracts, grades, stages,
  balances, collateral and its ECL calculation).
- **Scenario:** a path for the economy in years 1 to 5, set as a difference
  from the run's forecast.
- **Same models as the booked ECL:** the same PD model, the same five weighted
  scenarios around the forecast (section 2.5) and the same ECL calculation. A
  scenario equal to the forecast gives exactly the booked ECL.
- **The book stays as in the run:** no new loans; balances, schedules and CCFs
  unchanged.
- **No management actions.** The result is before any action QDB could take.

A bad scenario raises the provision in four ways:

| Cause | What happens in a bad year | Method 1 (today) | Method 2 (path) |
|---|---|---|---|
| PD | each grade's PD for the coming years is higher | yes | yes |
| Stage moves | more customers move to Stage 2 and Stage 3; fewer come back | Stage 1 → 2 only, once | all moves, every year |
| Rating moves | more customers are downgraded, fewer upgraded | no (already in the PD) | yes, every year |
| Collateral | property prices fall, so property collateral is worth less | yes, lowest point | yes, at each year end |

# 2. Common steps: from the scenario to the PD

## 2.1 Scenario

The values of the variables the scenario sets, for years 1 to 5, as a
difference from the run's forecast (for example −10 points of non-oil growth
in year 1). The same scenario can be priced on any run.

| Type | Built from |
|---|---|
| Past event | the change recorded at the time (growth: episode growth less the last year before the shock) |
| Supervisory | the published adverse scenario less its baseline (Fed, ESRB/EBA, QCB) |
| What-if | entered by the user, with a reason for each variable |
| Sector | one sector's growth below the forecast |

The library holds, among others: 1986 oil collapse, 1998 oil slump, 2009
crisis, 2015–16 oil fall, COVID, 2017 blockade, 2016–20 property correction,
1990–91 Gulf war, 2026 Iran war and Hormuz closure, Fed severely adverse,
ESRB/EBA adverse, a severe combined scenario, a domestic credit crunch and
fiscal consolidation. Each carries a description, the basis, a rationale per
variable, how the provision is calculated, limitations and sources.

## 2.2 Linked variables

A scenario may set only some variables (for example the oil price). The
others are filled from estimated equations, in a fixed order, so each
variable only uses variables already worked out:

$$
x_{v,y} = c_v + \sum_{d} \beta_{v,d}\, x_{d,y \text{ or } y-1} + \rho_v\, x_{v,y-1}
$$

- **Order:** world growth, oil price, US rate → government spending →
  non-oil growth → private credit → property prices → GCC growth → Qatar real
  GDP.
- **Estimation:** for each variable, candidate drivers with the expected sign
  (from IMF and central-bank work on the GCC). A regression is fitted for every
  combination of candidates; fits with a wrong sign are dropped; the rest are
  averaged with BIC weights (Bayesian model averaging). Qatar variables are
  estimated on the six GCC countries together. Only outturns are used, never
  forecasts. The equations are re-estimated each time the macro data is
  refreshed.
- **Used for:** non-oil growth → internal PDs; GCC growth → external PDs;
  property prices → collateral.

The main coefficients on the data of October 2026, per point of the driver:

| Variable | Moved by |
|---|---|
| Oil price | world growth +10.07 |
| Government spending | own last year +0.22; oil price +0.089; oil price last year +0.103; US rate −1.29 |
| **Non-oil growth** | own last year +0.31; world growth +1.35; credit last year +0.078; oil price last year +0.020 |
| Private credit | own last year +0.21; non-oil growth last year +0.79; oil price last year +0.056 |
| **Property prices** | non-oil growth +2.37 |
| **GCC growth** | own last year +0.14; world growth +0.79 |

A value outside history is still filled, but flagged. A variable that is not
in the system must be expressed through one that is, or added to the system
list with its candidate drivers (a change of the list, not of the code).
Linked effects can be switched off: then only the variables the scenario sets
move.

## 2.3 Shift

One number per year that says how bad the year is for borrowers: 0 is a
normal (long-run) year, above 0 is worse. It comes from the PD model of the
booked ECL:

$$
\text{DR}(g) = \frac{1}{1 + e^{1.54749 + 0.041415\,g}},\qquad
\text{shift} = \Phi^{-1}\big(\text{DR}(g)\big) - \Phi^{-1}(\text{LRDR})
$$

with $g$ non-oil growth in percentage points and **LRDR = 14.6%**, the
long-run default rate the ETL workbook and the tool use
(`ttc_anchor_pd`). The methodology pack defines the LRDR (slides 36 and 39)
but gives no value. Around today's growth, each point of non-oil growth lost
adds about **0.023** to the shift. The external book uses the external model
on GCC growth (ECL methodology, section 7.7).

## 2.4 PDs

As in the booked ECL. Years 1 to 5:
$\text{PD} = \Phi\big(\Phi^{-1}(\text{TTC PD}) + \text{shift}\big)$; after year 5
the PD moves back to the TTC PD, reached in year 50. Each contract gets a new
lifetime PD curve, and year 1 of the curve uses the scenario's year 1, year 2
its year 2 and so on: the year-by-year path of the scenario is already inside
the curve.

## 2.5 Scenario weights

The booked ECL does not use the forecast alone: it builds five scenarios
around the forecast (the forecast plus and minus multiples of the standard
deviation of non-oil growth) and weights them. The stress test keeps this.

| | |
|---|---|
| **Default: the scenario takes the forecast's place** | The scenario path replaces the forecast; the five scenarios are built around it in the same way, and the run's weights are kept (not worked out again). This is the booked calculation with only the forecast changed, and it is how the tool prices scenarios today. A scenario equal to the forecast gives exactly the booked ECL, so the stress effect is the effect of the scenario and nothing else. |
| **Option: scenario alone at 100%** | The scenario is the only path, at weight 100%, as in IFRS 9 sensitivity disclosures and the Bank of England stress test. A mild scenario can come out below the booked ECL, because the booked ECL includes the weighted downside scenarios; the forecast alone at 100% is then shown as a reference line. |

## 2.6 Collateral and LGD

Property collateral (residential, commercial, farm) × (1 + property price
change against the forecast); other collateral does not change. The LGD is
recomputed with the usual formula, 45% × max(50%, uncovered share after
haircuts). Method 1 uses the lowest point property prices reach in years 1 to
5; Method 2 the property price at each year end. Stage 3 is not affected.

## 2.7 Sectors

A scenario can hit one or more sectors (for example construction growth 10
points below the forecast in year 1). The sector of a customer comes from its
industry code. Customers in the sector get the shift for the sector's fall, as
if non-oil growth had fallen by that much; non-oil growth falls by the
sector's fall × its share of non-oil GDP (PSA), and that smaller fall applies
to all other customers.

# 3. Method 1: stressed ECL today

> **The question.** If this scenario were our forecast today, what ECL would
> we book at the reporting date, with the same book?

## 3.1 The steps

1. **PDs.** Each contract's lifetime PD curve is rebuilt with the scenario
   (section 2).
2. **Stage 1 → Stage 2 moves.** If the scenario were known today, some Stage 1
   customers would show a significant increase in credit risk. A share of each
   Stage 1 contract is treated as Stage 2 (lifetime ECL):

   $$
   \text{share} = \Phi\big(\Phi^{-1}(p) + k\,\text{shift}^{scen}_1\big) - \Phi\big(\Phi^{-1}(p) + k\,\text{shift}^{fcst}_1\big)
   $$

   - $p$ = chance that a Stage 1 customer is in Stage 2 or worse a year later,
     in a normal year, from QDB's stage matrix (section 4.2); until the matrix
     is counted the tool uses 6.3%.
   - $k$ = sensitivity of stage moves to the shift compared with defaults:
     1.02 today (section 4.3).
   - Year 1, because staging looks 12 months ahead; in the tool this is the
     move of each contract's 12-month PD on the normal scale, which is the
     year-1 shift. Option: the worst year of years 1 to 5, for scenarios that
     build slowly.
   - If the scenario has a payment-deferral programme (COVID: 72% of eligible
     customers), that share moves to Stage 2 on top.
   - Cost = share × (lifetime ECL − 12-month ECL), an expected value: no
     contract is picked at random.
   - Stage 2 and Stage 3 stay as they are. The external book uses the PD only.
3. **Collateral.** Property collateral at the lowest point property prices
   reach in years 1 to 5; LGD recomputed.
4. **ECL.** The run's ECL calculation, unchanged. The sum over all contracts is
   the **stressed ECL today**.

## 3.2 What is not done, and why

| Not done | Why |
|---|---|
| No rating downgrades | the shift already raises the PD of every grade; downgrading on top would count the same deterioration twice |
| No new Stage 3 | defaults in the coming years are already in the PD curve; moving part of the book to Stage 3 today would count them twice |
| No change to Stage 2 and Stage 3 | they already carry lifetime ECL or 100% of the balance |
| Balances unchanged | the question is about the book as it is today |

## 3.3 Result

| Line | How it is worked out |
|---|---|
| Booked ECL | from the run |
| **Stressed ECL today** | steps 1 to 4 |
| **Stress effect** | stressed ECL today − booked ECL |
| of which PD | step 1 alone |
| of which stage moves | step 2 added |
| of which collateral | step 3 added |

Shown for the whole book and by sector, portfolio and largest customers.
**Check:** a scenario of zeros gives the booked ECL, contract by contract.

# 4. Method 2: five-year stress path

> **The question.** If the economy follows this scenario for five years, what
> will the provision be at the end of each year, and how much higher than on
> the forecast?

- **Start:** the booked ECL of the run, the actual starting point (as in the
  EBA stress test).
- **Two lines,** worked out year by year: the **forecast line** (the run's
  forecast, as booked) and the **scenario line** (the scenario in the
  forecast's place). Both use the run's weights (section 2.5).
- **Each year** customers move between grades and stages, with moves counted
  from QDB's own history and made worse in a bad year by that year's shift.
- **At each year end** the provision is worked out with the run's ECL
  calculation, the PDs from the year after that year end, and the LGD at that
  year end.
- **The book** stays as in the run for the five years: each loan keeps its
  balance and remaining term (static balance sheet).

## 4.1 Rating matrix

For customers in each grade: the share in each grade one year later, in a
normal year. Counted from two LIC outputs one year apart, for customers in
both and not in Stage 3 at the end, every quarter-end as a starting point,
averaged. Counted on the 9 main grades (a customer moving one grade keeps its
notch); thin grades pooled with the next. Customers whose grade is set by a
rule (unrated QDB 5, Al Dhameen QDB 6, collective grades) keep their grade.

## 4.2 Stage matrix

For customers in Stage 1, 2 and 3: the share in each stage one year later, in
a normal year. Customers in both outputs, by customer-level stage; a customer
that left is left out unless written off (then it counts as Stage 3); new
customers are not counted; Tasdeer counted apart (always Stage 2, only the
move to Stage 3 used). The Stage 3 row holds the cures. Check: the share
moving to Stage 3 in a year, averaged over the years, should be close to the
LRDR of 14.6%.

Stage chances at the end of a year = chances at the end of the year before ×
the matrix of that year. With an illustrative matrix (Stage 1: 90 / 6 / 4;
Stage 2: 10 / 72 / 18; Stage 3: 0 / 5 / 95), a Stage 1 customer is in Stage 3
with chance 4.0% after one year and
$90\% \times 4\% + 6\% \times 18\% + 4\% \times 95\% = 8.5\%$ after two.

## 4.3 Correlation and sensitivity

Swing = standard deviation over the years of $\Phi^{-1}$(yearly rate);
correlation = swing² ÷ (1 + swing²). Today: defaults 3.2% (swing 0.182),
Stage 1 → 2 moves 3.3% (swing 0.185). Sensitivity = swing of a kind of move ÷
swing of defaults: 1.02 for stage moves; 1 for rating moves until there are
five years of rating history.

## 4.4 Matrices in a forecast or scenario year

Each customer's credit quality is a score and a grade or stage is a band of
it; a bad year lowers every score by the shift. For each row, take the chance
of ending **at or below** each grade or stage, from the worst end:

$$
\text{chance in the year} = \Phi\big(\Phi^{-1}(\text{normal-year chance}) + \text{shift} \times \text{sensitivity}\big)
$$

then take differences to get the row back. A shift of 0 gives back the
normal-year matrix. With the default weights each of the five scenarios gives
its own matrix and the year's matrix is their weighted average.

## 4.5 The calculation, year by year

Every customer starts in its grade and stage in the run, with chance 100%.
For each year $t = 1 \dots 5$, on each line: the shift of year $t$; the
matrices of year $t$; grade and stage chances at the end of year $t$; the LGD
at the property prices of year $t$; the ECL of each loan in each grade and
stage with the PDs from year $t+1$ on; then

$$
\text{provision}(t) = \sum_{\text{customers}}\Big[\sum_{\text{grades}}\sum_{\text{stages }1,2} P(\text{grade})\,P(\text{stage})\,\text{ECL}(\text{grade},\text{stage},t) + P(\text{Stage 3}) \times \text{balance}\Big]
$$

Grade and stage chances are multiplied because QDB's staging does not use the
rating (checked on the data).

## 4.6 Stage 3 cures and the result

- **Cures:** QDB's own (the Stage 3 row, fewer in a bad year); option: no
  cures, as in the EBA stress test.
- **Result:** forecast and scenario lines at the start and at the end of years
  1 to 5; stress effect = scenario − forecast, split into PD, rating moves,
  stage moves and collateral; **yearly charge** = provision($t$) −
  provision($t-1$) on each line; share in Stage 3 at each year end.
- **After year 5:** the booked rule applies (PDs return to TTC by year 50).
- **Check:** a scenario of zeros gives a scenario line equal to the forecast
  line; before any move the forecast line equals the booked ECL.

# 5. The two methods side by side

| | Method 1: stressed ECL today | Method 2: five-year path |
|---|---|---|
| Time point | reporting date | end of years 1 to 5 |
| Compared with | booked ECL | forecast line, year by year |
| PD | new lifetime curve | new curve, starting one year later each year |
| Stage moves | Stage 1 → 2 only, once | all moves, every year |
| New Stage 3 | no (in the PD) | yes |
| Rating moves | no (in the PD) | yes |
| Collateral | lowest point of property prices | property prices at each year end |
| Output | one number and its split | provisions, yearly charges and split |
| Use | headline, comparing scenarios, risk appetite | ICAAP, EBA / Bank of England style results |

Method 1 counts only what changes today; Method 2 lets defaults and downgrades
happen, so its year-end provisions are higher and the effect stays after the
scenario is over.

# 6. How others do it

| Who | What they do | Closest QDB method |
|---|---|---|
| EBA (EU-wide stress test, 2025) | three years from actual year-end figures; static balance sheet; baseline and adverse; IFRS 9 parameters follow the scenario; stage moves each year; no cures out of Stage 3 | Method 2 |
| Bank of England (2025) | five years; one stress scenario at 100% weight; balance sheet projected by the banks | Method 2 with the 100% option |
| IFRS 9 disclosures | ECL at the reporting date with each scenario at 100%, beside the booked ECL | Method 1 with the 100% option |
| QCB ICAAP (Pillar II) | five-year capital projection: base, gross stress, net stress after management actions; sudden and sustained shocks | Method 2 (gross stress provisions); Method 1 (sudden shock) |
| QCB Financial Stability Review | sudden NPL shocks and a break-even test | Method 1; reverse stress |
| QCB IFRS 9 instructions | at least three scenarios for the booked ECL (methodology pack, slide 108) | kept: the run's five weighted scenarios |

QCB does not prescribe a method for stressing provisions; the choices above
are documented here and reviewed by QDB.

# 7. Scenario stress measures in the tool

All on Stress testing → Scenario stress, on the run selected at the top.

| Tab | What it shows | How |
|---|---|---|
| **Price** | provision now, under the scenario, change and % change; waterfall PD model → stage moves → collateral; change by sector and portfolio; the scenario's path on the run; customers most affected | Method 1 (section 3) |
| **Compare** | several scenarios side by side, split into PD, stage moves and collateral | Method 1 per scenario |
| **Sensitivity** | one chosen scenario: the change in provision with its moves at ×0.5, ×1, ×1.5 and ×2; each of its main variables on its own at the scenario's size | full pricing (Method 1) at each size; each variable with its linked effects, the other main variables held at the forecast |
| **ECL at risk** | for each chosen scenario (and the forecast alone), the distribution of the stressed ECL over n five-year paths per scenario (default 2,000): the scenario path, average, 95% and 99% levels, average beyond 99%, what drives the tail, by sector, and the year's credit loss | each path = the scenario's path + a random path from the macro system; the same random paths for every scenario, so they differ only by their own moves. Random paths: world variables drawn as whole past years; other variables from their equations plus a random error the size of their unexplained part. Each path priced with a fast version checked against full pricing within 1% |
| **Reverse stress** | what it takes to raise the provision by a target, in QAR m or as a % of today's provision: how many times stronger each scenario must be, how large a year-1 move in each variable, how often the random paths reach it | bisection on the scenario scale; the closest candidates confirmed with full pricing |

**Drivers.** "What drives it" on the Price tab splits the stress effect by
main variable with Shapley values: each variable with everything it moves is
added in every possible order and its part is its average extra effect, so the
parts add up exactly to the total.

# 8. Parameter stress

Stress testing → Parameter stress has four views. Each prices on the run
selected at the top with the run's own ECL function; nothing in the run is
changed.

## 8.1 Stress test (packages)

A package names **who** it reaches and **what** changes for them. The scope
is every contract in the chosen portfolios **and** stages **and** customers
(an empty list does not narrow it); every lever reaches the scope only, and
the rest of the book keeps its own price.

| Lever | Effect on the scope |
|---|---|
| Stage 2 DPD threshold | restages with a different threshold (for example 30 days instead of 60) |
| Move to stage | forces Stage 2 or Stage 3 |
| Largest N default | the N largest customers (by exposure) move to Stage 3 |
| PD multiplier | every cumulative PD curve × the multiplier, capped at 1 |
| PD scenario | prices on one scenario's curves at 100% weight |
| Rating notches | downgrade by N notches along the contract's own scale |
| Maximum LGD (unsecured) | replaces the 45% base |
| Minimum LGD (fully secured) | replaces the 22.5% floor |
| Collateral % | collateral values × the percentage, LGD recomputed |
| Exposure % | the EAD curve × the percentage |
| Extend maturity (years) | the EAD curve re-profiled onto a longer term |

**Standard packages** (Add the standard packages):

| Package | Levers |
|---|---|
| Mild downturn | PD × 1.25, 1 notch down, collateral 90% |
| Severe downturn | PD × 2, 3 notches down, collateral 70%, exposure 110% |
| Collateral revaluation | collateral 50% |
| Staging tightened to 30 days | DPD threshold 30 |
| Largest five default | 5 largest customers to Stage 3 |

Each package is priced on its own from the same run, so the changes do not
add up. Results: provision before and after, change, contracts in scope,
contracts re-staged, change by portfolio, stage moves and customers affected.
Packages can be saved and loaded (shared with the R app).

## 8.2 Lever sensitivity

Each lever moved on its own (PD +25%; 1 and 2 notches down; collateral −25%
and −50%; exposure +20%; maximum LGD 45% → 55%; minimum LGD 22.5% → 31.5%;
DPD threshold 60 → 30; largest 5 default) and ranked by effect (tornado). The
bars are comparable but do not add up. **Reverse:** for one lever, the level
that reaches a target provision (bisection; a lever that cannot reach the
target says so).

## 8.3 Forecast and weights

Rebuilds the whole PD chain from the run's frozen configuration with the
forecast (internal non-oil GDP, external GCC growth) or the scenario weights
edited, and reprices. **Scenario weights: keep the run's** (isolates the PD
effect) or **recalculate from the new forecast** (the internal weights are
derived from the same forecast, so the weights and the curves can move in
opposite directions).

## 8.4 Roll forward

The provision in $k$ months if nothing else changes: each contract's balance
is what its own EAD path reaches at month $k$ (the schedule advanced, or the
fallback over the full term), and the PDs are conditional on surviving those
$k$ months.

# 9. Assumptions and limits

| Assumption | Why | Effect |
|---|---|---|
| The book is kept as in the run | shows the scenario only | no effect from new lending or repayments |
| Run's weights held around the scenario | ties to the booked ECL; QCB's three-scenario rule | the 100% option gives the disclosure view |
| Method 1: Stage 1 → 2 only, year-1 shift | staging looks 12 months ahead; defaults are in the PD | worst-year option for slow scenarios |
| One shift moves PDs, ratings and stages | one economy drives all moves | moves consistent with the booked PD model |
| Same shift per point of growth for every sector | not enough history per sector | sector results approximate |
| Only property collateral changes | no price series for other collateral; most other types have a 100% haircut | LGD stress may be understated |
| External book: PDs only | no QDB migration history for banks and investments | their rating and stage moves are not stressed |
| No management actions | standard for stress testing | result before any action |
