from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "review_items.json"

ReviewAction = Literal["claim", "approve", "reject", "escalate"]

# TAKEHOME: The workflow rules live in this one table so they are trivial to
# read, test, and extend. Each action is valid from exactly one status and
# moves the item to exactly one next status. Endpoints and the frontend's
# action buttons (via the `allowed_actions` field we serialize on every item)
# all derive from it, so there is no second copy of the rules to drift.
WORKFLOW_TRANSITIONS: dict[str, tuple[str, str]] = {
    "claim": ("unassigned", "in_review"),
    "approve": ("in_review", "approved"),
    "reject": ("in_review", "rejected"),
    "escalate": ("in_review", "escalated"),
}

TERMINAL_STATUSES = {"approved", "rejected", "escalated"}

RISK_ORDER = {"high": 0, "medium": 1, "low": 2}
TIER_ORDER = {"priority": 0, "standard": 1}


class ActionRequest(BaseModel):
    action: ReviewAction
    reviewer: str = "alex"


app = FastAPI(title="Reviewer Queue API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def load_seed_items() -> list[dict]:
    with DATA_FILE.open() as file:
        return json.load(file)


ITEMS = load_seed_items()


def allowed_actions(item: dict) -> list[str]:
    return [
        action
        for action, (required_status, _) in WORKFLOW_TRANSITIONS.items()
        if item["status"] == required_status
    ]


def serialize_item(item: dict) -> dict:
    payload = deepcopy(item)
    payload["allowed_actions"] = allowed_actions(item)
    return payload


def urgency_sort_key(item: dict) -> tuple[int, int, str]:
    # TAKEHOME: `submitted_at` values are uniform ISO-8601 UTC strings, so
    # lexicographic order is chronological order (oldest first). Unknown
    # risk/tier values sort last instead of crashing the whole queue.
    return (
        RISK_ORDER.get(item["risk_level"], len(RISK_ORDER)),
        TIER_ORDER.get(item["customer_tier"], len(TIER_ORDER)),
        item["submitted_at"],
    )


def rejection_detail(action: str, item: dict) -> str:
    status = item["status"]
    if status in TERMINAL_STATUSES:
        return f"This item is already {status}. No further actions are allowed."
    if action == "claim":
        reviewer = item["assigned_reviewer"]
        suffix = f" by {reviewer}" if reviewer else ""
        return f"This item is already in review{suffix}."
    if status == "unassigned":
        return f"This item must be claimed before it can be {WORKFLOW_TRANSITIONS[action][1]}."
    return f"Cannot {action} an item with status '{status}'."


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/dev/reset")
async def reset_items() -> dict:
    global ITEMS
    ITEMS = load_seed_items()
    return {"items": [serialize_item(item) for item in ITEMS]}


@app.get("/review-items")
async def list_review_items(active_only: bool = True) -> dict:
    items = ITEMS

    if active_only:
        items = [item for item in items if item["status"] not in TERMINAL_STATUSES]

    items = sorted(items, key=urgency_sort_key)
    return {"items": [serialize_item(item) for item in items]}


@app.get("/review-items/{item_id}")
async def get_review_item(item_id: str) -> dict:
    return {"item": serialize_item(find_item(item_id))}


@app.post("/review-items/{item_id}/actions")
async def apply_action(item_id: str, request: ActionRequest) -> dict:
    item = find_item(item_id)
    required_status, next_status = WORKFLOW_TRANSITIONS[request.action]

    if item["status"] != required_status:
        raise HTTPException(status_code=409, detail=rejection_detail(request.action, item))

    item["status"] = next_status
    if request.action == "claim":
        item["assigned_reviewer"] = request.reviewer

    return {"item": serialize_item(item)}


def find_item(item_id: str) -> dict:
    for item in ITEMS:
        if item["id"] == item_id:
            return item
    raise HTTPException(status_code=404, detail="Review item not found")
