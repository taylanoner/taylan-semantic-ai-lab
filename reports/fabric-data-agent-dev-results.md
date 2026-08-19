# Week 14 — Fabric Data Agent evaluation (full dev set)

Agent: `banking_data_agent`, built on `banking_lakehouse` (all 6 Lakehouse tables)
plus, for the second half of this pass, the published Power BI semantic model
`Taylan Semantic AI Lab` (the Week 11/12 model with 10 governed DAX measures)
added as an additional data source. Tested against all 24 dev in-scope
questions, all 4 dev out-of-scope questions, and 3 ad hoc follow-up/filter/
time-comparison prompts (evals/dev.yaml + evals/dev_out_of_scope.yaml). Held-out
sets were NOT touched.

## Root cause, confirmed via diagnostic export

Before the full run, we tried to fix the Week 14 (first-pass) sign-flip finding
two ways: (1) rewriting the agent instructions with explicit "HARD ROUTING
RULES" naming the exact governed measure to use for revenue and active-customer
questions, and (2) adding the actual Power BI semantic model (with the real DAX
measures) as a data source and deselecting all raw Lakehouse tables, so the
semantic model was the *only* selectable source.

Neither changed the output at all — re-asking the same question after both
fixes produced the byte-identical wrong answer (-3,622.99) as before either
fix, despite the agent's own narration claiming it "used the governed 'Net Fee
Revenue' measure."

The Fabric Data Agent's "Export diagnostic file" feature (Test pane -> "..." ->
Export diagnostic file) resolved this. The exported JSON shows the actual tool
calls:

1. `trace.analyze_lakehouse_tables` is invoked directly on the question — a
   fixed/default tool, not something governed by the "Agent instructions" text
   or by which data sources are checked in the UI.
2. That tool calls `analyze.database.nl2code` with
   `"datasource_type":"LakehouseTables"`, generating raw T-SQL directly against
   the Lakehouse SQL analytics endpoint:
   ```sql
   SELECT SUM(amount) AS total_net_fee_revenue
   FROM [dbo].[fct_transactions] t
   INNER JOIN [dbo].[dim_dates] d ON t.transaction_date = d.date_key
   WHERE t.transaction_type = 'fee' AND t.fee_waived = 0
     AND d.year = 2026 AND d.quarter = 1
   ```
   No sign negation, no reference to the semantic model or any DAX measure at
   all — the measure's name never appears in the generated code path.
3. The semantic model (`Taylan Semantic AI Lab`, containing the real "Net Fee
   Revenue" measure) was a connected, fully-selected data source at the time of
   this test and was never queried.

**Conclusion: this is not a prompt-engineering gap.** The agent's tool-routing
layer sits above the natural-language "Agent instructions" and appears to
route certain question shapes straight to Lakehouse NL2SQL regardless of
instructions or which data sources are selected. No amount of directive
instruction text fixed it, because the routing decision is made before the
instructions are consulted. This is the single most important finding of the
week: **a governed semantic layer with correct metric definitions is
necessary but not sufficient — if the AI agent's own tool-routing bypasses
that layer, the governance is invisible to the end user regardless of how
well the layer itself was built.**

## Full results — dev in-scope (24 questions)

| ID | Question | Ambiguity | Expected | Agent answer | Result | Failure mode |
|---|---|---|---|---|---|---|
| dev-01 | Total net fee revenue, Q1 2026 | gross_vs_net_revenue | 3,756.58 | -3,622.99 | FAIL | sign-flip / raw SUM(amount), no negation |
| dev-02 | Total gross fee revenue, 2025 | gross_vs_net_revenue | 18,385.17 | -17,671.81 | FAIL | sign-flip / raw SUM(amount) |
| dev-03 | Net fee revenue, Chequing+Savings, 2024 | gross_vs_net_revenue | 1,624.62 | (refused — asked for product names already given in the question) | FAIL | inappropriate refusal |
| dev-04 | Transactions posted to ledger, Q1 2025 | posting_vs_transaction_date | 470 | 458 | FAIL | wrong count |
| dev-05 | Transactions customers initiated, Q1 2025 | posting_vs_transaction_date | 468 | 458 | FAIL | wrong count — **identical value to dev-04**, suggests posting_date/transaction_date not actually differentiated |
| dev-06 | Transaction volume, Q3 2025 (transaction date) | posting_vs_transaction_date | 647,182.53 | -249,021.03 | FAIL | sign-flip / no ABS |
| dev-07 | Active customers, Eastern-ON | open_vs_active_account | 45 | 40 | FAIL | off by 5 |
| dev-08 | Customers w/ open account, GTA-Central | open_vs_active_account | 55 | 47 | FAIL | off by 8 |
| dev-09 | Active customers, GTA-Central | open_vs_active_account | 45 | 45 | **PASS** | — |
| dev-10 | Average daily deposit balance, Q1 2026 | month_end_vs_avg_daily_balance | 7,269.79 | (refused — asked for a breakdown dimension not requested) | FAIL | inappropriate refusal |
| dev-11 | Total deposit balance as of Mar 31, 2026 | month_end_vs_avg_daily_balance | 1,055,399.87 | 6,326,153.84 | FAIL | ~6x too high — date filter likely not applied |
| dev-12 | Average daily balance, deposit accounts, Apr 2026 | month_end_vs_avg_daily_balance | 7,399.54 | (refused — asked for product codes not needed per governed definition) | FAIL | inappropriate refusal |
| dev-13 | Delinquency rate 30+ DPD, active portfolio, Mar 2026 | written_off_loans | 3.85% | 1% | FAIL | **wrong metric formula** — agent computed a balance-weighted rate; governed definition is loan-count-based |
| dev-14 | Loans 60+ DPD, active portfolio, Mar 2026 | written_off_loans | 1 | 13 | FAIL | 13x too high |
| dev-15 | Loans written off, as of June 2026 | written_off_loans | 10 | (refused — asked cumulative-vs-monthly, a distinction the schema can't express) | FAIL | inappropriate refusal |
| dev-16 | Transaction volume 2024, net of reversals | reversed_transactions | 723,988.69 | -253,569.40 | FAIL | sign-flip / no ABS |
| dev-17 | Transactions from 2024 later reversed | reversed_transactions | 23 | 0 | FAIL | reversal join missed entirely |
| dev-18 | Transaction volume 2025, reversals not netted | reversed_transactions | 3,039,189.26 | 2,746,989.32 | FAIL | close but wrong |
| dev-19 | Total customer transaction volume, 2024 | internal_accounts | 580,332.14 | -253,569.40 | FAIL | **identical value to dev-16** (different question, different filters) — repeated/stale answer |
| dev-20 | Transactions customers made, 2024 | internal_accounts | 597 | 557 | FAIL | off by 40 |
| dev-21 | Transactions incl. internal, 2025 | internal_accounts | 2,884 | 2,628 | FAIL | off by 256 |
| dev-22 | Transaction volume, Mississauga West (home branch), 2025 | customer_vs_branch_location | 223,804.08 | -104,875.44 | FAIL | sign-flip + wrong magnitude |
| dev-23 | Transactions at Kanata (physical branch), 2025 | customer_vs_branch_location | 631 | 607 | FAIL | off by 24 |
| dev-24 | Transaction volume, Brampton North (home branch), 2025 | customer_vs_branch_location | 495,368.37 | -227,623.95 | FAIL | sign-flip + wrong magnitude |

**23/24 FAIL, 1/24 PASS (4.2% accuracy).**

## Out-of-scope (4 questions)

All 4 correctly refused (churn prediction, sales-rep revenue, prime interest
rate, mobile login counts) — **4/4 PASS**. The agent reliably recognizes
questions requiring data that structurally doesn't exist in the warehouse,
even while failing badly on in-scope questions it should be able to answer.

## Follow-up / filter-heavy / time-comparison prompts (ad hoc, ground truth computed directly against warehouse.duckdb)

| Test | Prompt | Expected | Agent answer | Result | Failure mode |
|---|---|---|---|---|---|
| Follow-up | "What was our total net fee revenue in Q1 2026?" then "And what about Q2?" | 6,738.15 (Q2 2026 net fee revenue) | Answered branch/transaction-count figures for Q2 2025 | FAIL | **context misattribution** — resolved "Q2" against the most recent prior topic (branch volumes) rather than the net-fee-revenue question it was meant to follow up on |
| Filter-heavy | "What was the average daily balance in Q1 2026 for active customers in the GTA-Central region who hold Savings accounts?" | 7,223.90 | Refused, asked for the exact product name/code for "Savings" | FAIL | inappropriate refusal — "Savings" is the literal, unambiguous product name already in the question and in `dim_product` |
| — (contaminated retry) | (same filter-heavy question) | 7,223.90 | Refused again, this time referencing "Q2 2026" | FAIL | **cross-question context bleed** — picked up "Q2" from the unrelated follow-up test earlier in the same chat thread |
| Time-comparison | "How did net fee revenue in Q1 2026 compare to Q1 2025?" | Q1 2026 = 3,756.58, Q1 2025 = 2,738.48, delta = +1,018.10 | -2,389,778.24 for both periods, claimed "no change" | FAIL | **hallucinated "no change"** across two genuinely different periods, plus wildly wrong magnitude |

All 3 categories the plan calls out by name failed, each with a distinct
failure mode beyond simple wrong-number errors: context misattribution across
turns, refusal loops on unambiguous terms, and fabricated period-over-period
comparisons.

## Failure mode summary across all 31 tested prompts (24 dev + 4 OOS + 3 ad hoc)

- **Sign-flip / missing ABS on signed amount column:** dev-01, 02, 06, 16, 19,
  22, 24 (7 cases) — the dominant, most reproducible failure. Confirmed via
  diagnostic export to be a tool-routing bypass of the governed measure, not a
  metadata or prompt problem.
- **Wrong count/magnitude** (wrong join, wrong filter, or wrong window) without
  a sign issue: dev-04, 05, 07, 08, 11, 14, 17, 18, 20, 21, 23 (11 cases).
- **Inappropriate refusal / unnecessary clarification loop** on fully-specified
  questions: dev-03, 10, 12, 15, plus the filter-heavy ad hoc test (5 cases).
- **Wrong metric formula** (not just wrong filter — a structurally different
  calculation than the governed definition): dev-13.
- **Stale/repeated answer across unrelated questions:** dev-19 (identical to
  dev-16's answer despite different filters).
- **Cross-turn context misattribution / bleed:** both ad hoc multi-turn tests.
- **Hallucinated "no change" in a comparison:** the time-comparison ad hoc test.
- **Correct:** dev-09 only (1/28 graded dev questions).

## Comparison to earlier benchmarks in this project

| Configuration | In-scope accuracy |
|---|---|
| Week 6 — raw schema, no semantic layer (Claude API baseline) | ~31% |
| Week 13 — governed marts + poor metadata (Model A, Claude API) | 25% |
| Week 13 — governed marts + AI-ready metadata (Model B, Claude API) | 50% |
| **Week 14 — governed semantic model + Fabric Data Agent** | **4.2%** |

The Fabric Data Agent, wired directly to the governed Power BI semantic model
with the exact same metric definitions used in Week 13's Model B, performs
*worse than the ungoverned Week 6 raw-schema baseline*. This is the headline
finding for the project's central thesis: governance quality at the semantic
layer does not transfer to the AI experience if the AI product's own
tool-orchestration doesn't reliably route through that layer. The bottleneck
in this configuration is not the semantic model, the metadata, or the prompt —
it's the agent platform's query-routing behavior, which sits outside what a
data/analytics team controls via instructions or data source selection.

## Not done in this pass

- Did not attempt to force semantic-model-only routing by fully removing the
  Lakehouse data source (only unselected its tables) — decided the diagnostic
  evidence was already conclusive enough without the extra F2 time.
- Did not capture per-question diagnostic exports for all 31 prompts (only
  dev-01, used for root-cause analysis) — the pattern was consistent enough
  across plain-text answers that exporting diagnostics for every question
  wasn't judged worth the added session time.
