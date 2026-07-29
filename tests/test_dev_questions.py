"""Week 7: every dev-set in-scope question must reproduce its expected_result
on a clean warehouse rebuild. Held-out questions are deliberately NOT tested
here -- they stay sealed until week 16, not even via an automated check.
"""

import math

import yaml
import pytest

with open("evals/dev.yaml", encoding="utf-8") as f:
    DEV_QUESTIONS = yaml.safe_load(f)

IN_SCOPE = [q for q in DEV_QUESTIONS if q["answerable"]]


@pytest.mark.parametrize("question", IN_SCOPE, ids=[q["id"] for q in IN_SCOPE])
def test_dev_question_reproduces_expected_result(warehouse, question):
    result = warehouse.execute(question["sql"]).fetchone()[0]
    assert result is not None, f"{question['id']} returned NULL"
    assert math.isclose(float(result), question["expected_result"], rel_tol=1e-6, abs_tol=1e-6), (
        f"{question['id']}: got {result}, expected {question['expected_result']}"
    )
