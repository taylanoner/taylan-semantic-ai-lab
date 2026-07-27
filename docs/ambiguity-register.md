# Ambiguity Register

Eight deliberate ambiguities seeded into the warehouse. Each one becomes: test
cases (evals/) -> a metric definition (dbt Semantic Layer, week 9) -> a
synonym + verified answer (week 13) -> rows in the benchmark (week 16).

## 1. Gross vs. net revenue

- **Reading A:** Sum of every fee charged, including ones later waived or refunded.
- **Reading B:** Gross fees minus waived/refunded amounts — what was actually retained.
- **Business meaning:** "Revenue" without qualification is ambiguous; "net" must be honored explicitly when stated, not silently defaulted to a simple sum.
- **Detecting a wrong answer:** If the reported figure equals the naive sum of all fee transactions, waivers weren't excluded.

## 2. Posting vs. transaction date

- **Reading A:** Transaction date — when the customer initiated it.
- **Reading B:** Posting date — when it settled to the ledger (0-3 days later).
- **Business meaning:** Regulatory/period-close reporting uses posting date; customer-activity analysis wants transaction date. Quarter-boundary transactions can land in different quarters depending on which is used.
- **Detecting a wrong answer:** Seeded boundary-crossing transactions should produce different quarter totals depending on which date field is used; the wrong field for the stated intent is the failure.

## 3. Open vs. active account

- **Reading A (structural):** Customer holds at least one account with status = open.
- **Reading B (behavioral):** Customer transacted within a defined recency window, regardless of account status.
- **Business meaning:** Segment/engagement reporting means behavioral activity, not just non-closed status.
- **Detecting a wrong answer:** If the "active" count matches the simple open-account count, the model used status instead of behavior.

## 4. Month-end vs. average daily balance

- **Reading A:** Balance snapshot on the last calendar day of the period.
- **Reading B:** Average of the daily balance across every day in the period.
- **Business meaning:** Balance reporting tied to typical holdings wants average daily balance; point-in-time regulatory snapshots want month-end.
- **Detecting a wrong answer:** These two numbers commonly diverge 10-20%; picking the wrong one for the stated intent is measurable.

## 5. Written-off loans

- **Reading A:** Keep written-off loans in the delinquency-rate denominator.
- **Reading B:** Exclude them — they've moved to a separate charge-off/recovery process.
- **Business meaning:** Delinquency reporting is about the active book; written-off loans get their own charge-off-rate metric.
- **Detecting a wrong answer:** Seeded write-off-flagged loans left in the denominator measurably skew the rate from the definition that excludes them.

## 6. Reversed transactions

- **Reading A:** Count every row as-is, original and reversal both.
- **Reading B:** Net the pair out — zero real economic activity.
- **Business meaning:** "Volume" should reflect real activity, not a corrected error counted twice.
- **Detecting a wrong answer:** Seeded reversal pairs should net to a lower total than a naive un-netted sum; matching the inflated number is the failure.

## 7. Internal accounts

- **Reading A:** Include all accounts, including the bank's own internal/GL/suspense accounts.
- **Reading B:** Exclude them — they're bookkeeping, not customers.
- **Business meaning:** Any customer-facing metric should exclude internal accounts entirely.
- **Detecting a wrong answer:** Seeded internal-account transactions left unfiltered inflate customer-facing volume.

## 8. Customer vs. branch location

- **Reading A:** Attribute a metric to the customer's home/registered branch.
- **Reading B:** Attribute it to wherever the transaction physically occurred.
- **Business meaning:** Branch performance reporting means home branch — it reflects the relationship, not foot traffic.
- **Detecting a wrong answer:** Seeded transactions where the transaction branch differs from the customer's home branch should produce different, measurably distinct totals per branch depending on which is used.
