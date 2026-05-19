# Ex7 — Handoff bridge

## Your answer

The HandoffBridge orchestrates the round-trip execution between the loop half and the structured half. In session `sess_494a1be4f7fa`, the orchestration ran for two complete rounds before completion:
- Round 1: The loop half planned and executed its subgoals. It searched for Haymarket (party=12) and Old Town (party=10) and calculated a total cost of £1103 and a deposit of £330 for the Royal Oak. The bridge generated a forward handoff file and invoked the structured half.
- Structured Rejection: The structured half (Rasa webhook) analyzed the booking payload and rejected it, stating: `party_too_large. The strict limit is 8 people.`
- Escalation & Round 2: The bridge generated a reverse task using the rejection feedback, routing control back to the loop half. In Round 2, the loop half adjusted its search to a party size of 8 at the Haymarket Tap, calculating a cost of £675 and a deposit of £135. It handed off to structured again, which successfully confirmed the booking.

Every state transition between the halves (from loop to structured and vice versa) emitted a `session.state_changed` event with attributes such as `round` and `rejection_reason` or `status='confirmed'`. The integrity check validated that the session trace correctly recorded `bridge.round_start`, `session.state_changed`, and `executor.tool_called` events to guarantee that actual round-trip progress was achieved.

Old handoff files were cleaned up by moving them to the `logs/handoffs/` directory instead of deleting them, ensuring a robust audit trail for debugging multi-half interactions.

## Citations

- homework/ex7-handoff-bridge/sess_494a1be4f7fa/logs/trace.jsonl — full round-trip trace showing transitions and tool calls
- starter/handoff_bridge/bridge.py — HandoffBridge implementation and state-switching logic
- starter/handoff_bridge/integrity.py — round-trip integrity validator
