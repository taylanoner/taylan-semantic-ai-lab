# Week 15 — Row-level and object-level security (RLS/OLS)

## Role design

Four roles, deliberately designed to separate RLS (row filtering) from OLS
(column/table hiding) so each mechanism could be verified independently:

| Role | RLS (row filter) | OLS (hidden columns/tables) |
|---|---|---|
| **National Analyst** | None — all regions/branches visible | None — full access (control/baseline role) |
| **Branch Manager** | `dim_customers[home_branch_name] = "Mississauga West"` (static, for demo — production would use a bridge table mapping Entra identity to branch) | None |
| **Retail Analyst** | None — all regions (cross-branch benchmarking) | `dim_customers[customer_name]` (PII) hidden; `fct_loans_monthly` and `fct_interest_monthly` hidden entirely (credit-risk/interest data out of scope for retail analytics) |
| **Restricted User** | `dim_customers[region] = "Eastern-ON"` (single region) | Same OLS as Retail Analyst — `customer_name` + `fct_loans_monthly` + `fct_interest_monthly` all hidden |

This gives an RLS-only role, an OLS-only role, a role with both, and a role
with neither — enough to prove RLS and OLS are independent mechanisms, not
just that "security exists."

## Implementation

- RLS roles created and filter-DAX assigned via Power BI Desktop's native
  **Manage roles** dialog (Modeling tab) — no external tool needed for this
  part.
- OLS (table- and column-level permissions) required **Tabular Editor 3**,
  connected live to the open PBIX session via Power BI Desktop's **External
  Tools** ribbon (avoids manual XMLA server/credential entry). Set via each
  role's **Table Permissions** property in the TOM Explorer (Default / Read /
  None per table), and per-column via the **OLS Column Permissions** grid
  that appears once a table is set to "Read."
- All 4 roles saved back to the live model from Tabular Editor, then the
  model was re-published from Power BI Desktop (File > Publish).
- **Gotcha:** Publish created a *new* semantic model item (`Banking_Lakehouse`)
  in the workspace rather than overwriting the existing `Taylan Semantic AI
  Lab` item the Fabric Data Agent was already connected to. Worth checking
  which published item actually received a publish before assuming "it
  worked" — the workspace item list, sorted by "Refreshed" timestamp, is the
  fastest way to tell.

## Verification 1: Power BI Desktop (View As) — PASS

Using Modeling > View as:

- **Branch Manager:** confirmed — every visual showed `home_branch_name =
  Mississauga West` only, no other branch's rows appeared.
- **Restricted User:** confirmed — rows limited to Eastern-ON; `Customer
  Name` field absent from the field list; `fct_loans_monthly` and
  `fct_interest_monthly` tables entirely absent from the field list.
- **Retail Analyst:** confirmed — `Customer Name`, `fct_loans_monthly`, and
  `fct_interest_monthly` absent from the field list; all regions still
  visible (no RLS).

RLS and OLS both work correctly at the semantic-model level, verified
independently for each role that has a restriction.

## Verification 2: through the Fabric Data Agent — FAIL

Per the plan's explicit requirement to prove restrictions "through the data
agent," not just in Power BI reports: assigned the test account
(`Taylan.oner@efeuran.com`) to the **Restricted User** role via the
semantic model's Security page (workspace item `...` > Security > role >
Add member), then asked `banking_data_agent` two questions that should have
been restricted for that role.

| Question | Expected under Restricted User | Actual agent answer | Result |
|---|---|---|---|
| "How many active customers do we have?" | 45 (Eastern-ON only, RLS-filtered) | 118 (unfiltered, all regions) | **FAIL — RLS bypassed** |
| "What is our loan delinquency rate?" | Refusal / no data (fct_loans_monthly is OLS-hidden entirely) | "1%" (a real, computed answer) | **FAIL — OLS bypassed** |

Both failures reproduce cleanly on a fresh chat (ruled out session caching).
The loan delinquency answer ("1%") also matches the same wrong
balance-weighted figure the agent produced in Week 14's dev-13 test — further
evidence the agent is running its own ad hoc query against the raw Lakehouse
table, not going through the governed, security-enforced semantic model at
all.

## Why this happens — ties directly to the Week 14 root cause

Week 14's diagnostic export already showed the agent's default tool routing
(`trace.analyze_lakehouse_tables` -> `analyze.database.nl2code` with
`datasource_type: "LakehouseTables"`) generates raw T-SQL against the
Lakehouse's SQL analytics endpoint, bypassing the connected semantic model
entirely — regardless of instructions or which data sources are selected in
the UI. RLS and OLS are semantic-model constructs, enforced by the DAX/AS
engine when a query goes through the model. If the agent's queries never go
through the model, there is no security layer for them to bypass "through
a bug" — they were never subject to it as a matter of how the query got
built.

**This is the headline finding for Week 15, and arguably for the whole
project's security story:** a correctly-configured RLS/OLS model, verified
working end-to-end in Power BI, provides **zero actual protection** against
a natural-language AI agent connected to the same underlying data if that
agent's tool-routing has any path that reaches the raw tables directly.
Governance implemented only at the semantic-model layer is not sufficient
for an AI-native access pattern — the enforcement point needs to be as low
as the data itself (e.g., row-level security at the Lakehouse/SQL endpoint,
or OneLake-level access controls) if an AI agent is a supported client,
not just BI reports.

## Not done in this pass

- Did not test Branch Manager or Retail Analyst through the Data Agent (the
  Restricted User result was conclusive enough that further per-role Data
  Agent testing wasn't judged worth the added F2 time — the bypass is a
  routing-level issue, not likely to be role-specific).
- Did not investigate whether restricting the agent to ONLY the semantic
  model as a selectable data source (already tried once in Week 14 for the
  revenue question, with no effect) changes this outcome for RLS/OLS
  specifically — given the Week 14 result, it's expected to fail the same
  way, but wasn't re-verified here.
- Did not pursue Lakehouse/OneLake-level row security as a fix — flagged as
  a real architecture question worth raising in interviews, not something to
  solve within the scope of this project.
