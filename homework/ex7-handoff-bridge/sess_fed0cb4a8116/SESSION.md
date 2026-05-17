# Session sess_fed0cb4a8116

**Scenario:** ex7-handoff-bridge
**Created:** 2026-05-17T21:24:02.566984+00:00

## Your task

(The loop half reads this file on every turn. The initial task description
has been written below by the orchestrator when the session was created.
Additional per-session instructions — constraints, identity, voice — can
be added by the scenario author.)

## Task description

Book a venue for 12 people in Haymarket, Saturday 2026-04-25 at 19:30.

REQUIRED workflow:
  1. Use venue_search(near='Haymarket', party_size=12) to find candidates.
  2. Choose a candidate (e.g. haymarket_tap) and use calculate_cost for it.
  3. Call handoff_to_structured to commit the booking.

CRITICAL: The 'data' argument of handoff_to_structured MUST NOT be empty. It must contain:
  - venue_id: the ID of the chosen venue (e.g. 'haymarket_tap')
  - date: '2026-04-25'
  - time: '19:30'
  - party_size: 12
  - deposit: the deposit amount from calculate_cost


## Constraints

- Be honest when you do not know something.
- Prefer reading memory over guessing.
- When the task is ambiguous, ask for clarification rather than inventing an answer.
