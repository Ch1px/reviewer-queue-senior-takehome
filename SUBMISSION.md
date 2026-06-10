# Submission

## Summary of changes

Backend: the workflow rules now live in a single transition table in `app/main.py`. Each action is valid from exactly one status, and anything else gets a 409 with a readable reason. The active queue excludes all terminal statuses and is sorted by risk, then customer tier, then oldest first. Every item in API responses also carries `allowed_actions`, computed from the same table.

Frontend: action buttons are driven by `allowed_actions` from the API instead of being always enabled. Errors show the API's actual message. After an action the queue is refetched, so completed items drop out and the next item is selected.

## Bugs fixed

All in `backend/app/main.py`:

1. Claiming was allowed on any non-terminal item, so you could claim something already in review and silently reassign it. Now only `unassigned` items can be claimed.
2. Approve/reject/escalate only checked "not already approved", so you could decide an unclaimed item, or re-decide a rejected/escalated one. Decisions now require `in_review`.
3. `rejected` and `escalated` weren't treated as terminal. All three terminal states now block every action.
4. The active queue only filtered out `approved`. It now excludes all terminal statuses.
5. The queue was sorted newest-first. Now risk > tier > oldest, done server-side.

## Product/UX decisions

- The queue order is the work order: top item = do this next. Rows show risk, priority tier and age so the order makes sense at a glance.
- Buttons disable based on `allowed_actions`, with a short hint explaining the item's state ("In review by sam."). I kept disabled buttons visible rather than hiding them so the layout doesn't jump around.
- API rejection reasons are shown directly instead of a generic "action failed".
- After approve/reject/escalate the item leaves the queue, the next item is selected and a notice confirms what happened.
- One thing I deliberately did not do: the spec gates actions on status only, not on who claimed the item, so alex can approve an item sam is reviewing. I surface ownership clearly in the UI but don't block it. Restricting decisions to the assignee is a product call I'd want to agree with the ops team first.

## Tests added

`backend/tests/test_workflow.py`, run with `cd backend && pytest` (28 pass, including the 2 original smoke tests):

- full transition matrix, including all 4 actions rejected on all 3 terminal statuses
- claim conflict keeps the original assignee
- unknown actions get a 422, unknown items a 404
- active queue excludes terminal items, `active_only=false` returns everything
- exact expected ordering of the seed data
- `allowed_actions` per status

Tests go through FastAPI's TestClient and reset the in-memory store before each test. Added `httpx` to requirements for TestClient.

Manual checks: claimed and approved items through the UI, checked blocked actions show the API's reason, checked terminal items leave the queue and the next item gets selected.

## Known gaps

- No assignee check on decisions (see above, deliberate).
- No concurrency control. Two reviewers could race to claim and last write wins. I'd make claim a compare-and-set and return 409 to the loser, which the UI already handles.
- In-memory store, nothing persists across restarts. Kept `/dev/reset` as a dev tool.
- No live updates between reviewers, just a manual Refresh button for now.
- Escalated items disappear from the active queue (as specced) but there's no escalations view yet. `active_only=false` exists on the API for this.
- No frontend unit tests. The rules are tested server-side, the frontend mostly renders server state.

## Files changed and why

- `backend/app/main.py`: transition table, queue filter/sort, `allowed_actions`, 409 messages
- `backend/tests/test_workflow.py`: new, see above
- `backend/requirements.txt`: httpx for TestClient
- `frontend/src/api.ts`: `allowed_actions` on the type, read `detail` from error responses
- `frontend/src/App.vue`: state-aware buttons, hints, refetch after actions, notices, badges
- `frontend/src/styles.css`: styles for badges/banners/hints

## AI assistance used

I used Claude Code throughout as a pair programmer. I set the priorities and the approach (rules live server-side in one table, frontend consumes `allowed_actions` rather than duplicating them, no assignee restriction) and it generated most of the code and tests to that plan. I reviewed every diff, ran the tests, and clicked through the app to verify the behaviour myself.
