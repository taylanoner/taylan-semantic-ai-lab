# Week 14 — Fabric Data Agent evaluation (starter sample)

Agent: `banking_data_agent`, built on `banking_lakehouse` (all 6 tables), with
the Model B-style instructions (terminology, scope, refusal guidance) from
Week 13 pasted into "Agent instructions". Tested against 3 dev-set questions
(evals/dev.yaml), chosen to hit different ambiguity categories. Held-out sets
were NOT touched.

**Limitation of this pass:** the exact generated DAX for each answer wasn't
captured (the "N step completed" detail panel in the test chat wasn't
expanded during testing). A follow-up session should re-run these same
questions and expand that panel to record the actual DAX, which the plan
asks for explicitly. Everything else below (question, expected, actual,
pass/fail, failure hypothesis) was captured in real time.

| ID | Question | Ambiguity | Expected | Agent answer | Result | Failure hypothesis |
|---|---|---|---|---|---|---|
| dev-01 | What was our total net fee revenue in Q1 2026? | gross_vs_net_revenue | 3,756.58 | -3,622.99 | **FAIL** | Agent summed raw `amount` for fee rows (stored negative in this schema) without negating -- didn't use the governed "Net Fee Revenue" measure, which does `-SUM(amount)`. Wrong sign AND wrong magnitude (off by ~133), suggesting it may also have missed the `fee_waived = FALSE` filter or used a different date field. |
| dev-07 | How many active customers do we have in the Eastern-ON region? | open_vs_active_account | 45 | 40 | **FAIL** | Agent's own explanation confirmed it understood "active" correctly in words ("a transaction in the trailing 90 days") but the count is off by 5. Likely computed the 90-day window from the actual current date rather than using the precomputed `dim_customers.is_active` column (which was calculated against a fixed as-of date of 2026-06-30 baked into the warehouse) -- i.e. it may be deriving the definition instead of trusting the governed column that already encodes it. |
| dev-02 | What was our total gross fee revenue (before waivers) in 2025? | gross_vs_net_revenue | 18,385.17 | -17,671.81 | **FAIL** | Same sign-flip pattern as dev-01, on a different year and explicit "gross" framing -- confirms this is a systematic issue with how the agent aggregates the `amount` column for fee transactions, not a one-off mistake. |

## Summary

3/3 in-scope questions failed against known-correct answers, despite the
agent's stated instructions including explicit terminology guidance and
despite governed DAX measures (Net Fee Revenue, Active Customer Count)
already existing in the semantic model. The pattern suggests the agent is
not reliably routing to the named governed measures/columns even when told
what they mean -- it appears to be writing its own ad-hoc aggregation
against raw columns in at least the revenue case, and possibly re-deriving
"active" instead of trusting the precomputed column in the activity case.

This is a real, useful finding for the project's central thesis: a governed
semantic layer with correct metric definitions is necessary but not
sufficient -- the AI layer on top still needs to be verified to actually use
those definitions, not just have access to them. Worth revisiting in Week
15/16: try being more directive in the agent instructions ("always use the
measure named X for revenue questions, never sum the raw amount column"),
and confirm whether that changes the sign-flip behavior.

## Not done in this pass (future paid F2 session)

- Only 3 of the 24 dev in-scope questions were tested (cost-conscious --
  paused capacity as soon as a clear, repeatable pattern emerged).
- Follow-up questions, filter-heavy questions, and time-comparison questions
  (explicitly called for in the plan's Week 14 build list) weren't tested yet.
- Generated DAX wasn't captured per question (see limitation note above).
