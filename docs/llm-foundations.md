# LLM Foundations

## Why LLMs hallucinate

An LLM is a next-token predictor: given the tokens so far, it outputs a probability
distribution over the next token and samples from it. There is no separate fact
database it checks against — "knowledge" is compressed into the model's weights
during training, and generation is pattern completion, not lookup. When the
training data is sparse, contradictory, or the question falls outside what the
model actually encoded, the model still produces a fluent, high-probability
continuation. That continuation can be confidently wrong. Hallucination isn't a
bug that occasional gets triggered — it's the same generation mechanism that
produces correct answers, just pointed at a gap in the model's knowledge.

This is why a raw text-to-SQL setup is risky in a bank: the model will produce
syntactically valid, plausible-looking SQL against ambiguous or unfamiliar
schema even when it has guessed wrong about what a column or join means (gross
vs. net revenue, which date field, which account is "active"). The output looks
exactly as confident whether it's right or wrong.

## Why temperature = 0 does not mean correct

Temperature controls how sharply the output distribution is sampled.
Temperature = 0 (or near it) makes the model greedily pick the highest-probability
token at each step, which makes output **deterministic** (same input → same
output, run to run) — it does not make the output **accurate**. If the
highest-probability continuation is a wrong join or the wrong metric
definition, temperature = 0 will reproduce that wrong answer reliably every
time. Determinism and correctness are independent properties: determinism is
about reproducibility, correctness is about matching ground truth.

## RAG vs. querying structured data

RAG (retrieval-augmented generation) retrieves relevant unstructured text
(documents, passages) and stuffs it into the context window so the model can
condition its generation on it. It's suited to open-ended, prose-shaped
knowledge — policies, documentation, support tickets — where the answer is a
synthesis of retrieved language.

Querying structured data (a data warehouse) is a different problem: the answer
isn't a synthesis of retrieved text, it's the deterministic result of executing
a correct query against governed tables. The LLM's job here isn't to "know" the
answer from context, it's to translate a natural-language question into a
correct, governed query plan (metric, dimensions, filters, time grain) — and to
recognize when no valid query exists. RAG answers by retrieving and blending;
structured querying answers by computing. Treating a metrics question like a
RAG problem (paste some docs, let the model guess the SQL) throws away the
determinism a warehouse can actually offer.

## Why raw-schema text-to-SQL is dangerous in a bank

Raw DDL and column names carry no business meaning — the model has to guess:
which of two date columns is "the" transaction date, whether "revenue" means
gross or net, whether written-off loans belong in a delinquency calculation. In
a bank, these aren't cosmetic ambiguities: they silently shift regulatory
numbers, risk metrics, and reported financials. And because the generated SQL
runs and returns a number, a wrong guess is indistinguishable from a right one
at the output — there's no refusal, no flag, just a plausible-looking result
that may be wrong. The failure mode is silent and confident, which is the worst
combination for a regulated numbers.

## What a semantic layer constrains, and what it still cannot guarantee

A governed semantic layer (certified metrics, entities, dimensions, explicit
joins, synonyms, verified answers) constrains the *vocabulary and mechanics* of
querying: it fixes what "revenue" means, which join path is valid, which
column is the authoritative date, and it can refuse outright when a question
maps to no defined metric or dimension. That closes off an entire class of
hallucination — the model can no longer invent a join or silently pick the
wrong column, because those choices are no longer the model's to make.

What it cannot guarantee is **intent disambiguation** — when a user's question
is genuinely ambiguous between two *valid*, well-defined metrics (e.g. "active
customers" could validly mean two different certified definitions), the
semantic layer doesn't know which one the user meant any more than a human
analyst would without asking a follow-up. It converts "the model guessed the
wrong join" into "the model (or the user) has to pick between two correct
answers" — a much safer failure mode, but not a solved one. This is exactly why
the benchmark measures refusal quality and metric-selection accuracy
separately: a governed layer changes *how* things go wrong, it doesn't
eliminate all ways they can.
