"""Week 7: integration test that hits the real Claude API. Excluded from the
default test run (see pytest.ini's 'integration' marker) -- costs API credit
and depends on network/model behavior, so it shouldn't slow down or flake out
the normal fast test loop.

Run explicitly with:
    pytest tests/test_ask_integration.py -v -m integration
"""

import pytest

from ask import get_query_plan
from llm_client import get_client


@pytest.mark.integration
def test_unsupported_metric_returns_refusal():
    client = get_client()
    plan = get_query_plan(client, "Which customers are likely to churn next quarter?")
    assert plan["answerable"] is False
