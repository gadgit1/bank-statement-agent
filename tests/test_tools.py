"""Deterministic tool tests based on the ACTUAL tools.py API."""
import pytest

OCT = {"date_from": "2026-10-01", "date_to": "2026-10-31"}


def test_spending_category_and_calculation(tools, session):
    out = tools.execute_tool("get_spending_summary", {**OCT, "category": "taxi"}, session)
    assert out["result"]["total_rub"] == 500
    assert out["result"]["operations_count"] == 2


def test_other_account_cannot_be_forced_by_model(tools, session):
    out = tools.execute_tool("get_spending_summary", {**OCT, "account_id": "other"}, session)
    assert out["error"]["type"] == "validation"
    assert out["error"]["field"] == "account_id"


def test_reversed_dates_return_validation(tools, session):
    out = tools.execute_tool("get_spending_summary", {"date_from": "2026-11-01", "date_to": "2026-10-01"}, session)
    assert out["error"]["type"] == "validation"


def test_unexpected_category_is_invalid(tools, session):
    out = tools.execute_tool("get_spending_summary", {**OCT, "category": "secret"}, session)
    assert out["error"]["type"] == "validation"


def test_invalid_json_returned_as_error(tools, session):
    out = tools.execute_tool("get_spending_summary", '{wrong', session)
    assert out["error"]["type"] == "validation"


def test_empty_period_returned_as_not_found(tools, session):
    out = tools.execute_tool("get_spending_summary", {"date_from": "2026-01-01", "date_to": "2026-01-31"}, session)
    assert out["error"]["type"] == "not_found"


def test_bad_recurring_months_invalid(tools, session):
    out = tools.execute_tool("find_recurring_payments", {"min_months": 13}, session)
    assert out["error"]["type"] == "validation"


def test_recurring_and_duplicate(tools, session):
    out = tools.execute_tool("find_recurring_payments", {"min_months": 3}, session)["result"]
    assert len(out["recurring"]) == 2
    assert out["possible_duplicates"] == [{"merchant": "Yandex Go", "amount_rub": 250.0, "date": "2026-10-12", "times": 2}]


def test_action_requires_explicit_confirmation(tools, session):
    sub_id = tools._sub_id("Video Service", 100)
    out = tools.execute_tool("flag_subscription", {"subscription_id": sub_id}, session)
    assert out == {"cancelled": True}
    assert not session.flagged


def test_action_confirmation_carries_specific_arguments(tools, session):
    sub_id = tools._sub_id("Video Service", 100)
    seen = []
    def confirm(name, args):
        seen.append((name, args))
        return True
    out = tools.execute_tool("flag_subscription", {"subscription_id": sub_id}, session, confirm)
    assert out["result"]["status"] == "flagged"
    assert seen == [("flag_subscription", {"subscription_id": sub_id})]
    assert sub_id in session.flagged


def test_unknown_subscription_not_found(tools, session):
    out = tools.execute_tool("flag_subscription", {"subscription_id": "sub_ffffffff"}, session, lambda *_: True)
    assert out["error"]["type"] == "not_found"


def test_timeout_retry_then_structured_error(tools, session):
    tools.FAULTS["get_spending_summary"] = ["timeout"] * 3
    out = tools.execute_tool("get_spending_summary", OCT, session)
    assert out["error"]["type"] == "timeout"
    assert tools.FAULTS["get_spending_summary"] == []


def test_timeout_once_eventually_recovers(tools, session):
    tools.FAULTS["get_spending_summary"] = ["timeout"]
    out = tools.execute_tool("get_spending_summary", {**OCT, "category": "taxi"}, session)
    assert out["result"]["total_rub"] == 500


def test_two_different_subscription_amounts_have_different_ids(tools, session):
    out = tools.execute_tool("find_recurring_payments", {"min_months": 3}, session)["result"]["recurring"]
    assert len({s["subscription_id"] for s in out}) == len(out)


def test_spending_summary_excludes_incoming_transfer(tools, session):
    out = tools.execute_tool("get_spending_summary", OCT, session)["result"]
    # The synthetic data convention is: positive=signed expenditure, negative=incoming transfer.
    assert out["total_rub"] == 800
