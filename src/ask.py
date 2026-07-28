"""Week 2 build: turn a natural-language question into a validated JSON query plan.

Usage:
    python src/ask.py "Show delinquency by branch last quarter"

This does NOT write SQL. It returns a machine-readable query plan (metric,
dimensions, time_period, filters, ambiguities, answerable) that later weeks
validate against a governed semantic layer. Separating "did it understand the
question" from "did it write correct SQL" is the point.
"""

import argparse
import json
import sys

from anthropic import Anthropic, APIError

from llm_client import MODEL, get_client

SYSTEM_PROMPT = """You are a query-plan generator for a banking analytics system. \
Given a natural-language question, output ONLY a JSON object with this exact shape:

{
  "metric": string or null,
  "dimensions": [string, ...],
  "time_period": string or null,
  "filters": [string, ...],
  "ambiguities": [string, ...],
  "answerable": boolean
}

Rules:
- Do not write SQL. Do not answer the question. Only produce the query plan.
- "metric" is the single business metric being asked for (e.g. "delinquency_rate", \
"net_interest_margin", "transaction_volume"), or null if none applies.
- "dimensions" lists how the metric should be broken down (e.g. "branch", "product").
- "time_period" is the requested time window in plain terms (e.g. "previous_quarter"), \
or null if none was specified.
- "filters" lists any exclusions or conditions implied by the question.
- "ambiguities" lists anything in the question that is genuinely unclear or could be \
read more than one way (e.g. "revenue could mean gross or net").
- "answerable" is false if the question asks for something no banking data warehouse \
could plausibly contain (e.g. predictive churn scores, data outside the domain), or if \
required information is missing entirely. Otherwise true.
- Output raw JSON only. No markdown fences, no commentary, no leading or trailing text.
"""

REQUIRED_FIELDS = {
    "metric": (str, type(None)),
    "dimensions": (list,),
    "time_period": (str, type(None)),
    "filters": (list,),
    "ambiguities": (list,),
    "answerable": (bool,),
}


def validate_plan(plan: dict) -> None:
    if not isinstance(plan, dict):
        raise ValueError(f"expected a JSON object, got {type(plan).__name__}")
    for field, types in REQUIRED_FIELDS.items():
        if field not in plan:
            raise ValueError(f"missing required field: {field}")
        if not isinstance(plan[field], types):
            raise ValueError(
                f"field {field!r} has wrong type: expected {types}, got {type(plan[field]).__name__}"
            )


def get_query_plan(client: Anthropic, question: str) -> dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": question}],
    )
    raw_text = response.content[0].text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()

    try:
        plan = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"model did not return valid JSON: {exc}\nraw output: {raw_text!r}")

    validate_plan(plan)
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Turn a question into a JSON query plan.")
    parser.add_argument("question", help="Natural-language question to convert")
    args = parser.parse_args()

    try:
        client = get_client()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        plan = get_query_plan(client, args.question)
    except APIError as exc:
        print(f"Error: Claude API request failed: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(plan, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
