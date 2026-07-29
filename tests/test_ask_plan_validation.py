"""Week 7: validate_plan() unit tests -- no live API calls, just checking our
own JSON-schema validation logic against fixed example dicts.
"""

import pytest

from ask import validate_plan

VALID_PLAN = {
    "metric": "delinquency_rate",
    "dimensions": ["branch"],
    "time_period": "previous_quarter",
    "filters": ["exclude_written_off"],
    "ambiguities": [],
    "answerable": True,
}


def test_valid_plan_passes():
    validate_plan(VALID_PLAN)  # should not raise


def test_plan_with_null_metric_is_still_valid():
    plan = dict(VALID_PLAN, metric=None)
    validate_plan(plan)  # metric is allowed to be None


def test_missing_field_raises():
    plan = dict(VALID_PLAN)
    del plan["answerable"]
    with pytest.raises(ValueError):
        validate_plan(plan)


def test_wrong_type_for_dimensions_raises():
    plan = dict(VALID_PLAN, dimensions="branch")  # should be a list, not a string
    with pytest.raises(ValueError):
        validate_plan(plan)


def test_wrong_type_for_answerable_raises():
    plan = dict(VALID_PLAN, answerable="true")  # should be a bool, not a string
    with pytest.raises(ValueError):
        validate_plan(plan)


def test_non_dict_input_raises():
    with pytest.raises(ValueError):
        validate_plan(["not", "a", "dict"])
