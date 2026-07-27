# taylan-semantic-ai-lab

A reproducible benchmark comparing raw text-to-SQL against a governed semantic
layer + AI agent, built on a banking-style data warehouse with deliberately
seeded metric ambiguities (gross vs. net revenue, posting vs. transaction date,
written-off loans, and others).

Status: early build. See `docs/llm-foundations.md` for the LLM foundations
write-up and `src/ask.py` for the first working piece — a natural-language
question to JSON query-plan converter.

## Setup

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # then add your ANTHROPIC_API_KEY
```

## Usage

```
python src/ask.py "Show delinquency by branch last quarter"
```
