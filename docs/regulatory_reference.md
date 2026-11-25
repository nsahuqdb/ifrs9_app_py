---
title: "Regulatory reference"
subtitle: "What IFRS 9, Basel, QCB and the main stress-testing supervisors require, and how QDB compares"
author: "QDB Financial Risk Management"
date: "November 2026"
---

# 1. About this document

This document puts QDB's ECL and stress test settings beside what the
standards and supervisors say: IFRS 9, the Basel Framework, the Qatar Central
Bank (QCB), and the stress tests of the EBA, the Bank of England, the Federal
Reserve and FINMA. Each requirement carries its paragraph, so it can be
checked in the original.

Three points to keep in mind when reading the comparisons:

- **IFRS 9 sets principles, not numbers.** It asks for an unbiased,
  probability-weighted estimate; it does not prescribe haircuts, LGDs or CCFs.
- **Basel values are capital rules.** They size regulatory capital, not
  accounting provisions. They are used here, as in the methodology pack, as a
  reference point, not as a requirement for the ECL.
- **QCB.** QDB applies IFRS 9 under QCB Circular 9/2017. Where this document
  quotes QCB, the source is the methodology pack's quotation of the circular
  or KPMG's published summary of the QCB instructions. Collateral haircuts
  and CCFs come from QCB's Basel III Pillar 1 instructions (2014), QCB's
  capital rule; like Basel, a reference point, not an ECL requirement.

QDB's values in the tables are the configuration at the time of writing. The
assistant compares with the values a run actually used.

# 2. IFRS 9: the impairment requirements

| Requirement | IFRS 9 | What QDB does | ECL methodology |
|---|---|---|---|
| Loss allowance on assets at amortised cost, FVOCI, loan commitments and financial guarantees | 5.5.1 | lending and investment books, guarantees and letters of credit included | 1 |
| 12-month ECL while credit risk has not increased significantly | 5.5.5 | Stage 1: 12 months | 8.4, 10.1 |
| Lifetime ECL once credit risk has increased significantly | 5.5.3 | Stage 2: remaining life | 8.4, 10.1 |
| Significant increase: default risk now against default risk at initial recognition | 5.5.9 | no rating at origination, so no such test; DPD, watchlist, restructuring and overrides | 6.1, 17 |
| Low credit risk: no significant increase assumed (investment grade is one example) | 5.5.10, B5.5.22–23 | pack: AAA and AA debt securities; the tool has no rating-based test for investments | 16.5 |
| Significant increase presumed at more than 30 days past due (rebuttable) | 5.5.11, B5.5.19 | rebutted: 60 days, with a yearly forward-flow analysis | 6.1 |
| Default presumed no later than 90 days past due (rebuttable) | B5.5.37 | worst DPD above 90 at customer level, or the default flag | 6.1 |
| Modified assets compared with the original terms | 5.5.12 | restructured customers are Stage 2 | 6.1 |
| Unbiased, probability-weighted, time value of money, reasonable and supportable information | 5.5.17 | five weighted scenarios; discounting at the EIR | 7.2–7.6, 10.1 |
| The possibility of loss is always reflected, even when low | 5.5.18 | | |
| At least two outcomes when scenarios are modelled | B5.5.42 | five scenarios | 7.2 |
| Measured over the maximum contractual period | 5.5.19, B5.5.38 | to maturity; a matured facility is extended by 12 months | 4.4 |
| Revolving facilities: the period of actual exposure | 5.5.20 | QDB has no revolving facilities (pack, slide 80) | |
| Discounted at the original effective interest rate | B5.5.44 | monthly at the EIR | 10.1 |
| Cash flows from collateral, net of the costs to obtain and sell it, are part of the cash shortfalls | B5.5.55 | collateral net of haircut lowers the LGD, up to half the balance; none on Stage 3 | 9, 10.3 |
| Write-off when there is no reasonable expectation of recovery | 5.4.4 | outside the tool | |

# 3. Basel: the credit risk parameters

The methodology pack takes the 45% unsecured LGD and the CCFs from Basel
(slides 69, 71, 77–78). The values below are the BIS consolidated Basel
Framework.

## 3.1 Collateral haircuts (standardised approach)

Supervisory haircuts of the comprehensive approach (CRE22.49), assuming daily
mark-to-market and a 10-business-day holding period:

| Collateral | Haircut |
|---|---|
| Cash in the same currency | 0% |
| Gold | 20% |
| Equities in a main index (and convertible bonds) | 20% |
| Other equities listed on a recognised exchange | 30% |
| Sovereign debt rated AAA to AA- | 0.5% (up to 1 year) to 12% (over 10 years) |
| Sovereign debt rated A+ to BBB- | 1% to 20% by maturity |
| Sovereign debt rated BB+ to BB- | 15% |
| Other issuers rated AAA to AA- | 1% (up to 1 year), 3% (1–3 years), 6% (5–10 years) |
| Other issuers rated A+ to BBB- | 2% (up to 1 year), 4% (1–3 years), 12% (5–10 years) |
| Currency mismatch between collateral and exposure | 8% on top (CRE22.52) |

Guarantees are recognised by putting the guarantor's risk in place of the
borrower's, not through a haircut (CRE22, guarantees and credit derivatives).

## 3.2 LGD under the foundation IRB approach

| Claim | LGD | Basel |
|---|---|---|
| Senior unsecured, non-financial corporates | 40% | CRE32.6 |
| Senior unsecured, financial institutions | 45% | CRE32.6 |
| Subordinated | 75% | CRE32.7 |

For a secured exposure the LGD blends the unsecured and secured parts
(CRE32.10):

$$
\text{LGD}^* = \text{LGD}_U \times \frac{E_U}{E(1+H_E)} + \text{LGD}_S \times \frac{E_S}{E(1+H_E)}
$$

with the secured part valued after the collateral haircut $H_C$ (CRE32.11):

| Collateral | LGD on the secured part | Haircut $H_C$ |
|---|---|---|
| Eligible financial collateral | 0% | the CRE22 haircuts |
| Receivables | 20% | 40% |
| Commercial or residential real estate | 20% | 40% |
| Other physical collateral | 25% | 40% |
| Ineligible collateral | | 100% |

## 3.3 Floors

| | Floor | Basel |
|---|---|---|
| PD, corporate and bank exposures (not sovereigns) | 0.05% | CRE32.4 |
| LGD, advanced approach, unsecured | 25% | CRE32.16 |
| LGD, advanced approach, fully secured | financial 0%, receivables 10%, real estate 10%, other physical 15% | CRE32.16 |

## 3.4 Credit conversion factors

| Off-balance item | CCF | Basel |
|---|---|---|
| Direct credit substitutes (general guarantees of indebtedness, standby LCs serving as financial guarantees, acceptances) | 100% | CRE20.95 |
| Transaction-related contingent items (performance bonds, bid bonds, warranties) | 50% | CRE20.97 |
| Commitments | 40% | CRE20.98 |
| Short-term self-liquidating trade letters of credit | 20% | CRE20.99 |
| Commitments the bank can cancel unconditionally at any time | 10% | CRE20.100 |

## 3.5 Default

An exposure more than 90 days past due, or owed by a defaulted borrower, is
in default (CRE20.104).

# 4. QCB

What can be stated without the circular, and where it comes from:

| Requirement | QCB | Source |
|---|---|---|
| IFRS 9 applied under QCB's instructions | Circular 9/2017 | methodology pack, slide 92 |
| Default | 90 days past due, with QCB's irregularities: an instalment unpaid for three months or more, a limit exceeded by 10% or more without reason, insufficient repayments on overdrafts, evidence of insolvency | pack, slide 84 |
| Stage 2 backstop | the 30-day presumption may be rebutted with supporting analysis | pack, slide 92 |
| Rating deterioration | two-notch downgrade threshold | pack, slide 90 |
| Low credit risk | AAA and AA | pack, slide 87 |
| Unsecured LGD | 45% minimum for non-subordinated claims | pack, slide 71 |
| Scenarios | at least three, at most five | KPMG, IFRS 9 transition impact on banks in the GCC – Qatar, p.34; pack, slide 108 |
| Moving back a stage | 12-month cooling-off period from Stage 3/2 to Stage 2/1 | KPMG, p.34; pack, slide 92 (12 months, with QCB approval) |
| Level of staging | obligor level; exceptions need QCB approval | KPMG, p.34 |
| Collateral (IFRS 9 instructions) | a list of eligible collateral with regulatory haircuts | KPMG, p.34 |
| Eligible collateral (capital) | cash, gold, rated debt securities, unrated senior bank debt, main-index and other listed equities, funds; real estate, machinery, goods and personal guarantees are not eligible | QCB Basel III Pillar 1 instructions (2014), para 151 |
| Haircuts (capital, 10-day basis) | cash in the same currency 0%; gold and main-index equities 15%; other listed equities 25%; debt securities 0.5%–24% by rating, maturity and issuer; currency mismatch 8%; scaled up for secured lending (20-day holding period) | same, para 153, 155–158 |
| Guarantees (capital) | recognised by substitution if direct, explicit, irrevocable and unconditional, from sovereigns, Qatar Government entities, PSEs, banks or rated entities with a lower risk weight | same, para 150, 168–171 |
| Real estate (capital) | through risk weights, not as collateral: residential mortgage loans 75%, commercial mortgage loans 100% | same, para 103–105 |
| CCFs (capital) | unconditionally cancellable 0%; commitments 20% (up to 1 year) / 50%; trade LCs 20%; transaction-related guarantees 50%; direct credit substitutes and other guarantees 100% | same, para 112–115 |
| Domestic sovereign | exposures to the Government of Qatar (through the Ministry of Finance and QCB) are outside the ECL model | KPMG, pp.33–34 |
| Reporting | quarterly templates with agreed-upon procedures by the auditors; annual templates with the audit report | KPMG, p.34 |

Still to read in Circular 9/2017 itself: the IFRS 9 haircut list (if it
differs from the capital rule), any LGD or provision minimum, and the cure and
restructuring rules in full. The 45% unsecured LGD is the pack's attribution;
the Pillar 1 instructions use the standardised approach, which has no LGD.

# 5. How QDB compares

## 5.1 Collateral

QDB's haircut is the share of the value **not** counted: net collateral =
value × allocation × (1 − haircut) (ECL methodology, chapter 9).

| Collateral | QDB haircut | Value QDB counts | Basel | QCB |
|---|---|---|---|---|
| Cash collateral, collateral account | 100% | nothing | 0% haircut (CRE22.49); F-IRB LGD 0% on the covered part (CRE32.11) | 0% haircut, same currency (para 155) |
| Bank guarantee | 0% | all | guarantor's risk in place of the borrower's (CRE22) | the same, if irrevocable and unconditional (para 168–171) |
| Residential property | 50% | half | F-IRB: 40% haircut, LGD 20% on the secured part (CRE32.11) | not eligible collateral; 75% risk weight for residential mortgage loans (para 103–104) |
| Commercial property | 75% | a quarter | F-IRB: 40% haircut, LGD 20% on the secured part (CRE32.11) | not eligible collateral; 100% risk weight, no relief (para 105) |
| Farm property | 100% | nothing | real estate: 40% haircut, LGD 20% (CRE32.11) | not eligible (para 151) |
| Listed shares | 100% | nothing | 20% (main index), 30% (other listed) (CRE22.49) | 15% (main index), 25% (other listed), 10-day basis (para 155) |
| Bonds | 100% | nothing | 0.5%–20% for investment-grade debt by issuer, rating and maturity (CRE22.49) | 0.5%–24% by rating, maturity and issuer (para 155) |
| Gold, precious metal | 100% | nothing | 20% (CRE22.49) | 15% (para 155) |
| Machinery, goods | 100% | nothing | F-IRB: 40% haircut, LGD 25% (CRE32.11) | not eligible (para 151) |
| Personal and corporate guarantees, cheques, insurance, documents | 100% | nothing | only eligible guarantors count; ineligible collateral 100% (CRE32.11) | guarantees only from eligible guarantors; the rest not eligible (para 151, 170) |
| Currency mismatch | none | | 8% on top (CRE22.52) | 8% (para 153) |

**What this shows.** QDB counts value only for bank guarantees, residential
and commercial property, and then at most up to half the balance (the 50%
unsecured floor). Cash, shares, bonds and gold, which Basel and QCB count with
small or no haircuts, give no benefit at QDB. QCB's capital rule does not count
real estate as collateral at all (QCB column: QCB Basel III Pillar 1
instructions, 2014). IFRS 9 asks that collateral cash
flows be part of the estimate (B5.5.55).

## 5.2 LGD

| | QDB | Basel | QCB |
|---|---|---|---|
| Unsecured | 45% | 40% non-financial corporates, 45% financial institutions; 75% subordinated (CRE32.6–32.7) | 45% minimum (pack, slide 71) |
| Lowest possible | 22.5% (45% × at least 50% unsecured) | advanced approach floors: 25% unsecured; 0–15% fully secured (CRE32.16) | none found (the Pillar 1 instructions have no LGD) |
| Stage 3 | 100% of the balance | | not read (Circular 9/2017) |

The pack's 45% for all senior unsecured claims is the earlier Basel value;
the current framework gives non-financial corporates 40%.

## 5.3 EAD and CCF

| Product | QDB | Basel | QCB (capital) |
|---|---|---|---|
| Letters of guarantee | guarantee amount × CCF in the extract; pack CCF 50% for bank guarantees | 50% transaction-related (CRE20.97); 100% guarantees of indebtedness (CRE20.95) | 50% transaction-related, net of cash margin (para 114); 100% direct credit substitutes and other guarantees (para 115) |
| Letters of credit | LC outstanding × CCF in the extract; pack CCF 20% | 20% short-term trade LCs (CRE20.99) | 20% (para 113) |
| Al Dhameen | full amount (CCF 100%); the pack says 50% | 100% direct credit substitutes (CRE20.95) | 100% (para 115) |
| Undrawn on-balance limits | not counted (drawdown factor 0: facilities are revocable, pack slide 79) | 40% commitments; 10% unconditionally cancellable (CRE20.98, 20.100) | 0% if unconditionally cancellable; otherwise 20% (up to 1 year) or 50% (para 112) |

## 5.4 Staging and default

| | QDB | IFRS 9 | QCB |
|---|---|---|---|
| Default | worst DPD above 90, or the default flag | presumed no later than 90 DPD (B5.5.37) | 90 DPD with irregularities (pack, slide 84) |
| Stage 2 backstop | worst DPD above 60 | presumed above 30 DPD, rebuttable (5.5.11) | rebuttal allowed (pack, slide 92) |
| Rating deterioration | not used (no rating at origination) | the core test (5.5.9) | two notches (pack, slide 90) |
| Low credit risk | no rating-based test for investments | allowed (5.5.10, B5.5.22–23) | AAA and AA (pack, slide 87) |
| Cure | none in the tool: each quarter is staged from its own data | | 12-month cooling-off (KPMG, p.34) |
| Level | customer, with contagion | | obligor (KPMG, p.34) |

## 5.5 Scenarios and measurement

| | QDB | IFRS 9 | QCB |
|---|---|---|---|
| Scenarios | five, weighted | at least two outcomes (B5.5.42) | three to five (KPMG, p.34) |
| Weights | from where the forecast sits on the history (V2) | unbiased, probability-weighted (5.5.17) | |
| Horizon | contractual maturity; matured facilities + 12 months | maximum contractual period (5.5.19) | |
| Discounting | monthly at the EIR | original EIR (B5.5.44) | |
| PD floor | none (lowest internal TTC PD 0.013%) | possibility of loss always reflected (5.5.18) | Basel: 0.05% (CRE32.4) |

# 6. Stress testing

| Supervisor | Horizon | Balance sheet | Credit risk |
|---|---|---|---|
| EBA, EU-wide stress test 2025 | 3 years (2025–2027) from year-end 2024 | static: maturing exposures replaced like for like | point-in-time 12-month stage transition rates and lifetime loss rates under the scenario; Stage 1 → 2 at a three-fold rise in lifetime PD; no cures out of Stage 3 and no release of Stage 3 provisions; real estate collateral follows the house price path; accounting, not regulatory, haircuts |
| Bank of England, Bank Capital Stress Test 2025 | 5 years from end-2024 | | one severe scenario: UK GDP −5%, unemployment peak 8.5% (quarter 9), house prices −28%, commercial property −50% from the 2022 peak, Bank Rate 8%; first test after the IFRS 9 transitional arrangements ended |
| Federal Reserve, supervisory stress test 2026 | 9 quarters (2026Q1–2028Q1) | | severely adverse: unemployment +5.5 points to 10%, GDP −4.6%, house prices −30%, commercial real estate −39%, equities −58% |
| FINMA | | | whole-bank tests and portfolio tests (mortgage credit, interest rate risk), run on several banks to compare; FINMA can order risk reduction or more capital |
| Basel Committee, stress testing principles (2018) | | | principles on objectives, governance, policies, processes, methodology, resources and documentation |
| QCB | ICAAP: 5 years | base, gross stress, net stress after management actions | sudden and sustained shocks; Financial Stability Review: sudden NPL shocks and a break-even test |

How QDB's stress test sits against these is set out in the stress testing
methodology (chapter 6): Method 1 prices a scenario at the reporting date;
Method 2 runs five years on QDB's own rating and stage migration matrices,
with a static book and no management actions.

# 7. Sources

- IFRS 9 Financial Instruments, as endorsed in the EU by Commission Regulation (EU) 2016/2067: paragraphs 5.4.4, 5.5.1–5.5.20, B5.5.17–B5.5.55.
- Basel Committee, Basel Framework (BIS): CRE20 (standardised approach: individual exposures), CRE22 (credit risk mitigation), CRE32 (IRB risk components). <https://www.bis.org/basel_framework/>
- Basel Committee, Stress testing principles, October 2018 (d450). <https://www.bis.org/bcbs/publ/d450.htm>
- QCB, Circular 9/2017 (IFRS 9 instructions to banks), as quoted in the IFRS 9 methodology pack (v11, May 2025).
- QCB, Implementation Instructions – Basel III Framework for Conventional Banks, Pillar 1 Guidelines for Capital Adequacy (January 2014), sections 4.1.1, 4.1.2 and 4.1.5. <https://www.qcb.gov.qa/Documents/BankInstructions2024/AR/0381-0464_annex001.pdf>
- KPMG, IFRS 9: Transition impact on banks in the GCC – Qatar (2018), pp.33–34.
- EBA, 2025 EU-wide stress test – Methodological Note.
- Bank of England, Key elements of the 2025 Bank Capital Stress Test.
- Federal Reserve, 2026 Stress Test Results (June 2026) and 2026 Supervisory Stress Test Methodology.
- FINMA, Supervisory instruments: stress tests.

# 8. The regulatory folder

The assistant answers from this document and from any official text put in
the folder `docs/regulatory` of the app (on the machine that runs it):

1. Save the PDF (or Word file) in `docs/regulatory`. Sub-folders are fine
   (for example `QCB/`, `Basel/`, `EBA/`).
2. Ask the assistant. A new or changed file is read the first time it is
   needed and remembered after that; nothing is sent anywhere.

The assistant cites the file and page. A scanned PDF without a text layer
cannot be searched; the assistant lists it as unreadable. Recommended
documents, with where to get them, are in `docs/regulatory/README.md`.
