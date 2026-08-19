# Week 16 — The benchmark: sealed sets opened

`evals/holdout.yaml` (20 in-scope) and `evals/out_of_scope.yaml` (8
unanswerable) were opened and run for the first time this week, per the
plan's sealing discipline (sealed since 2026-07-27, week 3-5). Neither file
was viewed, edited, or referenced by name in any script before this week.

Four configurations x {dev, held-out} x {in-scope, out-of-scope}, 3 runs
each (672 total model calls), one command
(`python src/run_benchmark.py`) reproducing every number in
`reports/benchmark.csv` from `reports/benchmark-raw-results.csv`.

## Headline numbers

| Config | Dev in-scope accuracy | Held-out in-scope accuracy | Held-out out-of-scope refusal rate | Run-to-run variance* |
|---|---|---|---|---|
| 1. Raw schema | 31.9% | 33.3% | 100% | 14.3% |
| 2. Raw schema + glossary | **69.4%** | **70.0%** | 100% | 8.9% |
| 3. Governed semantic model | 26.4% | 23.3% | 100% | 8.9% |
| 4. Governed + AI-prep | 50.0% | 48.3% | 100% | **1.8%** |

*% of questions where the 3 runs didn't all agree on the same outcome category (lower = more deterministic).

Two things jump out immediately, and both matter more than a clean
"governance wins" story would suggest:

1. **Dev and held-out accuracy track within ~1-5 points of each other for
   every configuration.** This is the methodologically important result: the
   dev set was not overfit, and the numbers generalize. The sealing
   discipline held for real — the held-out set was never looked at, and the
   dev-set numbers turned out to be an honest predictor of it.
2. **All 4 configurations refuse every held-out out-of-scope question,
   every run, regardless of accuracy on in-scope questions.** Scope-boundary
   awareness is robust and doesn't depend on schema richness — a model that
   is terrible at picking the right date field is still reliably good at
   recognizing "this warehouse has no employee data."

## The surprising result: raw + glossary beats governed + AI-prep

This is not the result the project's framing expected going in, and it's
worth being honest about rather than smoothing over. A plain-text business
glossary bolted onto the *raw, ungoverned* schema outperformed the fully
governed semantic model with equivalent-effort AI-ready metadata by ~20
points, and beat governed-with-plain-metadata by over 40 points.

Breaking accuracy down by ambiguity tag (dev + held-out combined) explains
most, but not all, of the gap:

| Ambiguity | 1. Raw | 2. Raw+glossary | 3. Governed | 4. Governed+AI-prep |
|---|---|---|---|---|
| gross_vs_net_revenue | 0% | 72.2% | 0% | 0% |
| posting_vs_transaction_date | 5.6% | 66.7% | 0% | 33.3% |
| open_vs_active_account | 100% | 100% | 66.7% | 66.7% |
| month_end_vs_avg_daily_balance | 27.8% | 100% | 72.2% | 94.4% |
| written_off_loans | 20% | 80% | 53.3% | 100% |
| reversed_transactions | 46.7% | 26.7% | 0% | 0% |
| internal_accounts | 20% | 60% | 0% | 40% |
| customer_vs_branch_location | 40% | 40% | 0% | 60% |

**Two ambiguity categories are structurally, not just informationally,
harder for the governed configs**, and account for a real chunk of the gap:

- **reversed_transactions (0% for both governed configs):** `fct_transactions`
  does not expose `is_reversal` or `reversal_of_transaction_id` at all —
  reversals are already netted out upstream in `stg_transactions` (week 8
  design decision). A question like "how many transactions were later
  reversed" or "volume without netting out reversals" is not just hard, it
  is **structurally unanswerable** from the governed mart — the identifying
  columns don't exist in it. No amount of metadata quality fixes this; it
  would require exposing the raw reversal columns in the mart, which
  would undo the point of governing that logic away in the first place.
- **internal_accounts (0% governed, 40% governed+AI-prep):** documented
  already in week 13 — internal/GL accounts are excluded upstream in
  `stg_transactions`, so "include internal accounts" questions have no data
  to answer from in the governed marts. Same structural pattern as above.

Together these two categories are 2 of 8 ambiguities (30 of 152 in-scope
question-instances across dev+held-out) where governed configs are
mechanically capped near 0% regardless of AI readiness. This is an honest,
by-design consequence of resolving those ambiguities at the transformation
layer rather than leaving them queryable both ways — governance necessarily
forecloses the "wrong" reading, but an explicit-override question that
*asks* for the foreclosed reading has no correct governed answer to give.

**Even excluding those two categories, config 2 still leads on
gross_vs_net_revenue (72.2% vs 0%) and posting_vs_transaction_date (66.7% vs
33.3%).** The gross/net gap traces to a real, avoidable difference between
the two prompts, not an architecture effect: the raw+glossary prompt says
outright *"the amount column stores fees as negative numbers -- negate the
sum"*, while the governed+AI-prep synonym for revenue never states the sign
convention explicitly. That's a prompt-completeness gap I introduced
writing the two configs, not evidence that governed metadata can't work —
it's a reminder that "AI-ready metadata" is only as good as its most
specific, most literal instructions, and abstract business-meaning
descriptions are not a substitute for calling out mechanical gotchas (sign
conventions, unit conventions) explicitly. Notably, the real Fabric Data
Agent in week 14 failed on this exact same sign-flip pattern independently,
via a completely different mechanism (bypassing the semantic model's DAX
measure entirely) — the underlying weakness (models mishandling a signed
column without being told to negate it) is real and reproduces two
different ways.

## The variance result: AI-prep is the most consistent, even where not the most accurate

Config 4 (governed + AI-prep) has by far the lowest run-to-run variance
(1.8% of questions produced different outcomes across the 3 runs, versus
8.9-14.3% for the others). Even where it isn't the most accurate
configuration, it is the most *deterministic* one — the richer the
metadata, the less the model's answer depends on which run you happened to
sample. That's a real, separate axis of value from raw accuracy, and one a
production system would care about independently.

## What this does and doesn't say about governed semantic layers

This benchmark does **not** show that semantic layers don't help AI-native
querying. It shows:

- Simple, explicit, mechanically-specific business rules (a glossary) can
  out-perform a governed model whose AI-facing metadata is comparatively
  abstract, at least for single-shot text-to-SQL against a small schema.
- A governed model's deliberate exclusions (reversals netted, internal
  accounts dropped) are a real, honest cost against any benchmark question
  that asks for the excluded reading — this is a scope limitation of the
  benchmark's dev/held-out question design (some questions test "does the
  model follow explicit override intent," which a governed schema can
  structurally never do once that data is transformed away), not a failure
  of governance as a strategy.
- The value case for a governed semantic layer in this project was never
  purely "higher single-shot text-to-SQL accuracy" — it's consistency
  across every consumer (nobody can hand-roll a wrong revenue query because
  there's one blessed measure), auditability, and reusable security (RLS/OLS).
  Week 14/15 already showed that value proposition breaks down hard the
  moment an AI agent's tool routing bypasses the semantic model layer
  entirely — which is arguably the more important, more damning finding of
  the whole project than this week's raw-accuracy numbers.

## Scope limitations (for the README, in short)

- The dev and held-out sets share the same 8 ambiguity categories by
  design; this benchmark measures whether metadata/glossary quality
  resolves *known, named* ambiguities, not open-ended schema
  understanding.
- Two of those eight ambiguity categories are structurally unanswerable
  under the governed marts as built (reversals, internal accounts) — the
  governed configs' scores are mechanically capped below what better
  prompting could ever fix for those categories specifically.
- One model version, one reasoning setting, one comparison function
  (numeric exact/near-match against a documented tolerance), 3 runs — per
  the plan's "nothing else moves" methodology. No LLM-judge scoring was
  used; this is deterministic comparison only.
- This benchmark tests direct Claude API text-to-SQL against DuckDB, not
  the Fabric Data Agent — that comparison (governed semantic model via a
  real AI agent product) is what weeks 14-15 already covered, with a much
  worse result (4.2% accuracy, security bypassed) than any configuration
  here. The two results together are the actual thesis: metadata quality
  matters a lot for raw text-to-SQL, but it doesn't matter at all if the
  product layer on top doesn't reliably route through the governed layer
  in the first place.
