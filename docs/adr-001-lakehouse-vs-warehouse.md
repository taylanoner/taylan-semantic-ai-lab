# ADR-001: Lakehouse vs. Warehouse for the Fabric layer

**Status:** Accepted

## Context

By Week 9 the governed transformation work is already done -- DuckDB + dbt
produce five clean, tested marts (`dim_customers`, `fct_transactions`,
`fct_account_balances_monthly`, `fct_loans_monthly`,
`fct_interest_monthly`). Week 10's job is not to re-do that transformation
inside Fabric, it's to get this already-governed data into Fabric so that
Power BI (Weeks 11-12) and, later, a Fabric data agent (Weeks 14-15) can sit
on top of it.

Fabric offers two storage items for this: a **Lakehouse** (file-based
ingestion, Spark/notebook-native, gets an auto-generated read-only SQL
analytics endpoint) and a **Warehouse** (T-SQL-native, DDL/DML-first,
stricter schema enforcement, full write-capable T-SQL surface including
stored procedures). Both ultimately store data as Delta tables on the same
OneLake, and both can back a Power BI semantic model via Direct Lake.

## Decision

**Lakehouse.**

The deciding factor is where the transformation logic actually lives in
this project: entirely upstream, in dbt and DuckDB, not in Fabric.
Fabric's job here is to host and serve already-governed data, not to
transform raw inputs. Given that:

- **Ingestion fits the Lakehouse model directly.** Our artifact at this
  stage of the pipeline is Parquet files (dbt mart exports). Lakehouse's
  native ingestion path is "drop files, load to Delta tables" -- exactly
  what Week 10 did. A Warehouse would force the same data through T-SQL
  `CREATE TABLE` / `COPY INTO` statements for no added governance benefit,
  since the schema and the exclusions (reversal netting, internal-account
  filtering, etc.) are already locked in by dbt before the data ever
  reaches Fabric.
- **We don't give up SQL querying.** A Lakehouse in current Fabric
  automatically provisions a SQL analytics endpoint, so Power BI, ad-hoc
  T-SQL exploration, and (later) a data agent's governed queries all have
  a real SQL surface to query against -- the traditional Lakehouse/Warehouse
  gap ("Lakehouse means no SQL") no longer applies as sharply as it used to.
- **Lakehouse keeps room open we may still need.** OneLake shortcuts to
  other sources, and Spark notebooks for anything that doesn't fit cleanly
  in dbt/SQL later (e.g. if the consulting-track migration prototype needs
  to touch semi-structured MicroStrategy metadata), are a Lakehouse-native
  capability a Warehouse doesn't offer.

## What we give up

A Warehouse's SQL analytics endpoint is fully read/write, T-SQL-compatible
(stored procedures, multi-statement transactions, the full DML surface).
Our Lakehouse's SQL endpoint is read-only and Spark-SQL-flavored, not a
complete T-SQL engine. If a future requirement needed transactional
writes-via-SQL directly against the Fabric-hosted tables, or genuine
stored-procedure logic living in Fabric itself, that would be a real
reason to reconsider -- but nothing in this project's scope (a read-heavy
BI + AI-agent-query workload sitting on top of an already-governed dataset)
currently needs that.

## Consequences

- Power BI semantic models (Week 11-12) connect to the Lakehouse's SQL
  analytics endpoint / Direct Lake, not a Warehouse.
- If the consulting track (migration prototype) later needs to land raw,
  unmodeled MicroStrategy metadata for exploration before it's governed,
  the Lakehouse's file/Spark path is already available without adding a
  second storage item.
- Re-running `src/build_warehouse.py` + `dbt build` and re-exporting to
  `fabric_export/` is the whole refresh path -- there is intentionally no
  transformation logic to maintain inside Fabric.

## Update (Week 11): Power BI connects via SQL analytics endpoint DirectQuery, not Direct Lake

The Lakehouse-vs-Warehouse decision above stands unchanged. What changed is
*how the Power BI semantic model connects to the Lakehouse*.

The natural choice given the reasoning above -- Direct Lake, reading Delta
tables straight from OneLake -- ran into real reliability problems in Week
11: after any source schema change (e.g. adding a column), Direct Lake's
"Edit tables" / schema-refresh mechanism repeatedly failed to pick up the
new schema, even after a full close/reopen of the semantic model. Root
causes, confirmed against Microsoft's own documentation:

1. Editing/schema-refreshing a Direct Lake semantic model is [documented as
   unavailable on a free Power BI license](https://learn.microsoft.com/en-us/fabric/fundamentals/direct-lake-power-bi-desktop)
   (no Pro/PPU license was purchased for this project -- see the plan's own
   budget line for Power BI Pro, intentionally deferred).
2. A related bug is tracked in Fabric's own known-issues list (schema not
   loading on Direct Lake semantic model reload).

Working around this by connecting via **Get Data > SQL Server** to the
Lakehouse's SQL analytics endpoint, in **DirectQuery** mode, resolved it
completely -- at the cost of losing Direct Lake's zero-copy/high-performance
read path in favor of a standard DirectQuery round-trip per query. For this
project's data volumes (hundreds to thousands of rows per table) that
performance difference is not observable; if this were a production system
at real scale, Direct Lake's reliability problems on a free license would be
a stronger argument for buying the Pro license than for abandoning Direct
Lake outright.
