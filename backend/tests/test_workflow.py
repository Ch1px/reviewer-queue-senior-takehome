"""Regression tests for the reviewer workflow rules and queue behavior.

These exercise the API through the HTTP layer (routing, validation, and
status codes included), and reset the in-memory store before each test so
they stay independent.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# Stable fixtures from data/review_items.json:
UNASSIGNED = "RV-1024"
IN_REVIEW_BY_ALEX = "RV-1030"
IN_REVIEW_BY_SAM = "RV-1027"
TERMINAL_ITEMS = {
    "approved": "RV-1029",
    "rejected": "RV-1034",
    "escalated": "RV-1033",
}


@pytest.fixture(autouse=True)
def reset_state():
    client.post("/dev/reset")


def act(item_id: str, action: str, reviewer: str = "alex"):
    return client.post(
        f"/review-items/{item_id}/actions",
        json={"action": action, "reviewer": reviewer},
    )


def get_item(item_id: str) -> dict:
    response = client.get(f"/review-items/{item_id}")
    assert response.status_code == 200
    return response.json()["item"]


# --- claim ---------------------------------------------------------------


def test_claim_moves_unassigned_item_to_in_review_and_records_reviewer():
    response = act(UNASSIGNED, "claim")
    assert response.status_code == 200
    item = response.json()["item"]
    assert item["status"] == "in_review"
    assert item["assigned_reviewer"] == "alex"


def test_claim_is_rejected_for_item_already_in_review():
    response = act(IN_REVIEW_BY_SAM, "claim")
    assert response.status_code == 409
    # The original reviewer must not be silently replaced.
    assert get_item(IN_REVIEW_BY_SAM)["assigned_reviewer"] == "sam"


# --- decisions -----------------------------------------------------------


@pytest.mark.parametrize(
    "action,expected_status",
    [("approve", "approved"), ("reject", "rejected"), ("escalate", "escalated")],
)
def test_decisions_move_in_review_item_to_terminal_status(action, expected_status):
    response = act(IN_REVIEW_BY_ALEX, action)
    assert response.status_code == 200
    assert response.json()["item"]["status"] == expected_status


@pytest.mark.parametrize("action", ["approve", "reject", "escalate"])
def test_decisions_are_rejected_for_unclaimed_items(action):
    response = act(UNASSIGNED, action)
    assert response.status_code == 409
    assert get_item(UNASSIGNED)["status"] == "unassigned"


# --- terminal states -----------------------------------------------------


@pytest.mark.parametrize("status", sorted(TERMINAL_ITEMS))
@pytest.mark.parametrize("action", ["claim", "approve", "reject", "escalate"])
def test_terminal_items_allow_no_further_actions(status, action):
    item_id = TERMINAL_ITEMS[status]
    response = act(item_id, action)
    assert response.status_code == 409
    assert get_item(item_id)["status"] == status


# --- invalid input fails cleanly -----------------------------------------


def test_unknown_action_is_rejected_by_validation():
    assert act(UNASSIGNED, "publish").status_code == 422


def test_unknown_item_returns_404():
    assert act("RV-9999", "claim").status_code == 404


# --- queue behavior -------------------------------------------------------


def test_active_queue_excludes_all_terminal_statuses():
    items = client.get("/review-items").json()["items"]
    listed_ids = {item["id"] for item in items}
    assert {item["status"] for item in items} <= {"unassigned", "in_review"}
    assert listed_ids.isdisjoint(set(TERMINAL_ITEMS.values()))


def test_full_queue_is_available_when_active_only_is_false():
    items = client.get("/review-items", params={"active_only": False}).json()["items"]
    assert len(items) == 12


def test_active_queue_is_ordered_by_risk_then_tier_then_oldest():
    items = client.get("/review-items").json()["items"]
    assert [item["id"] for item in items] == [
        "RV-1024",  # high / priority / 04-02 08:15
        "RV-1030",  # high / priority / 04-02 11:55
        "RV-1025",  # high / standard / 04-01 09:30
        "RV-1032",  # high / standard / 04-01 17:20
        "RV-1035",  # medium / priority / 04-02 06:50
        "RV-1026",  # medium / priority / 04-03 07:20
        "RV-1028",  # medium / standard / 04-01 14:05
        "RV-1027",  # low / standard / 04-02 10:45
        "RV-1031",  # low / standard / 04-03 08:40
    ]


# --- allowed actions exposed to the client --------------------------------


def test_items_expose_allowed_actions_for_their_status():
    assert get_item(UNASSIGNED)["allowed_actions"] == ["claim"]
    assert get_item(IN_REVIEW_BY_ALEX)["allowed_actions"] == [
        "approve",
        "reject",
        "escalate",
    ]
    assert get_item(TERMINAL_ITEMS["approved"])["allowed_actions"] == []
