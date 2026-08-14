# Week 13: AI-ready metadata (Model B)

Model A is the semantic model as it stood before this document -- business
names and descriptions from Week 11, but no synonyms, no verified answers,
no explicit scope guidance. Model B adds the three things below, sourced
**only from the development sets** (`evals/dev.yaml`, `evals/dev_out_of_scope.yaml`).
The held-out sets remain sealed until week 16.

## Synonyms per ambiguity

Each entry maps alternate phrasings a user might type to the governed
concept the semantic model already resolves. These get entered into the
Fabric data agent's synonym configuration in Week 14.

| Ambiguity | User might say... | Maps to |
|---|---|---|
| #1 Gross vs. net revenue | "revenue", "income", "fee income" | `Net Fee Revenue` (net is the default unless "gross" is stated explicitly) |
| #2 Posting vs. transaction date | "when it happened", "activity date" | `transaction_date` |
| | "when it posted", "ledger date", "settlement date" | `posting_date` |
| #3 Open vs. active account | "active customers", "engaged customers" | behavioral `is_active` / `Active Customer Count` |
| | "customers with an account", "account holders" | structural open-account count |
| #4 Month-end vs. avg daily balance | "average balance", "typical balance" | `Average Daily Balance` |
| | "current balance", "ending balance", "balance as of [date]" | `month_end_balance` |
| #5 Written-off loans | "delinquency", "past due", "overdue" | `Delinquency Rate 30D` / `90D` (active portfolio only) |
| | "charged off", "written off", "bad debt" | `Charge-off Rate` |
| #6 Reversed transactions | "transaction volume", "activity volume" | `Transaction Volume` (already netted) |
| #7 Internal accounts | "customer transactions", "customer activity" | `Transaction Volume` / `Net Fee Revenue` (internal already excluded) |
| #8 Customer vs. branch location | "branch performance", "branch's book of business" | `home_branch_name` |
| | "branch traffic", "walk-ins", "foot traffic" | `transaction_branch_name` |

## Verified answers

Sourced from `evals/dev.yaml` (24 in-scope) -- each question's `sql` field
is the verified query. When configuring the Fabric data agent in Week 14,
add these as verified answers (question text + SQL) rather than retyping
them; they're already committed and reproducible.

## Scope + refusal guidance

Instruction block for the data agent's system/scope configuration:

> This agent answers questions about the bank's transaction, account
> balance, loan, and interest data for the period 2024-01-01 through
> 2026-06-30. It does not have and should refuse to answer questions about:
> - Regulatory or capital metrics (e.g. Basel III ratios) -- not modeled.
> - Predictive or propensity scores (e.g. churn, default likelihood) -- no
>   predictive model exists.
> - Any dimension not present in the schema (e.g. sales representative,
>   teller, merchant category, marital status).
> - External/competitor data or macroeconomic indicators.
> - HR, payroll, or headcount data.
>
> When a question falls outside this scope, refuse clearly and state what
> data would be needed, rather than guessing or approximating.

This directly mirrors `evals/dev_out_of_scope.yaml`'s 4 questions (churn,
sales rep, prime rate, mobile logins) -- the agent should refuse all four
cleanly once this guidance is in place.
