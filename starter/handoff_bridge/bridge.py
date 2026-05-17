"""Ex7 — handoff bridge.

Routes between the loop half and the Rasa-backed structured half,
supporting REVERSE handoffs (structured → loop) when the structured
half rejects.

The base sovereign-agent LoopHalf only knows how to request a handoff
FORWARD. The bridge you're building here is the thing that decides
what to do when the structured half says "no, go back and try again".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sovereign_agent.errors import ValidationError
from sovereign_agent.halves import HalfResult
from sovereign_agent.halves.loop import LoopHalf
from sovereign_agent.halves.structured import StructuredHalf
from sovereign_agent.handoff import Handoff
from sovereign_agent.memory import MemoryStore, MemoryType
from sovereign_agent.session.directory import Session
from sovereign_agent.session.state import now_utc

BridgeOutcome = Literal["completed", "failed", "max_rounds_exceeded"]


@dataclass
class BridgeResult:
    outcome: BridgeOutcome
    rounds: int
    final_half_result: HalfResult | None
    summary: str


class HandoffBridge:
    """Orchestrates round-trips between LoopHalf and a StructuredHalf.

    Not a sovereign-agent Half itself — it lives one level up, deciding
    which half should run next.
    """

    def __init__(
        self,
        *,
        loop_half: LoopHalf,
        structured_half: StructuredHalf,
        max_rounds: int = 4,
    ) -> None:
        self.loop_half = loop_half
        self.structured_half = structured_half
        self.max_rounds = max_rounds

    # ------------------------------------------------------------------
    # TODO — the main run method
    # ------------------------------------------------------------------
    async def run(self, session: Session, initial_task: dict) -> BridgeResult:
        """Run the bridge until the session completes, fails, or hits max_rounds."""
        from sovereign_agent.handoff import write_handoff

        rounds = 0
        current_input: dict = dict(initial_task)
        last_loop = last_struct = None
        structured_confirmed = False

        while rounds < self.max_rounds:
            rounds += 1
            session.append_trace_event(
                {
                    "event_type": "bridge.round_start",
                    "actor": "bridge",
                    "payload": {"round": rounds, "half": "loop"},
                }
            )

            try:
                loop_result = await self.loop_half.run(session, current_input)
            except ValidationError as e:
                # Real planner occasionally returns empty content; retry once with a compact prompt.
                if "SA_VAL_INVALID_PLANNER_OUTPUT" not in str(e):
                    raise

                rejection_reason = None
                ctx = current_input.get("context") if isinstance(current_input, dict) else None
                if isinstance(ctx, dict):
                    rejection_reason = ctx.get("rejection_reason")

                compact_task = {
                    "task": (
                        "Retry booking proposal after structured rejection.\n"
                        f"Reason: {rejection_reason or 'rejected by structured half'}.\n"
                        "Use venue_search, then calculate_cost, then handoff_to_structured.\n"
                        "Handoff data must include venue_id, date, time, party_size, deposit."
                    ),
                    "context": ctx or {},
                }

                session.append_trace_event(
                    {
                        "event_type": "bridge.recoverable_error",
                        "actor": "bridge",
                        "payload": {
                            "round": rounds,
                            "where": "loop_half.run",
                            "error": str(e),
                            "action": "retry_with_compact_task",
                        },
                    }
                )

                loop_result = await self.loop_half.run(session, compact_task)
            last_loop = loop_result

            if loop_result.next_action == "complete":
                if not structured_confirmed:
                    session.mark_failed(
                        {"reason": ("loop attempted to complete before structured confirmation")}
                    )
                    return BridgeResult(
                        outcome="failed",
                        rounds=rounds,
                        final_half_result=loop_result,
                        summary="loop completed early without structured confirmation",
                    )

                session.mark_complete(loop_result.output)
                session.append_trace_event(
                    {
                        "event_type": "session.state_changed",
                        "actor": "bridge",
                        "payload": {"from": "executing", "to": "complete", "via": "loop"},
                    }
                )
                return BridgeResult(
                    outcome="completed",
                    rounds=rounds,
                    final_half_result=loop_result,
                    summary=f"loop completed in round {rounds}",
                )

            if loop_result.next_action != "handoff_to_structured":
                session.mark_failed(
                    {"reason": f"unexpected loop outcome: {loop_result.next_action}"}
                )
                return BridgeResult(
                    outcome="failed",
                    rounds=rounds,
                    final_half_result=loop_result,
                    summary=f"unexpected loop outcome: {loop_result.next_action}",
                )

            handoff = build_forward_handoff(session, loop_result)

            required = ("venue_id", "date", "time", "party_size", "deposit")
            missing = [k for k in required if handoff.data.get(k) in (None, "", [])]
            if missing:
                synth_struct = HalfResult(
                    success=False,
                    output={"reason": f"missing_required_handoff_fields:{','.join(missing)}"},
                    summary=f"bridge blocked forward handoff; missing fields: {missing}",
                    next_action="escalate",
                )
                current_input = build_reverse_task(
                    loop_result_or_session=session,
                    struct_result_or_loop_result=current_input,
                    loop_result_arg=loop_result,
                    struct_result_arg=synth_struct,
                )
                session.append_trace_event(
                    {
                        "event_type": "bridge.handoff_blocked",
                        "actor": "bridge",
                        "payload": {"round": rounds, "missing_fields": missing},
                    }
                )
                continue
            write_handoff(session, "structured", handoff)
            session.append_trace_event(
                {
                    "event_type": "session.state_changed",
                    "actor": "bridge",
                    "payload": {"from": "loop", "to": "structured", "round": rounds},
                }
            )

            struct_result = await self.structured_half.run(session, {"data": handoff.data})
            last_struct = struct_result

            if struct_result.next_action == "complete":
                # Success! The booking is confirmed.
                # We can now write the 'structured_confirmed' fact and exit successfully.
                store = MemoryStore(session)
                store.write_fact(
                    MemoryType.SEMANTIC,
                    fact_id="structured_confirmed",
                    content="The booking has been successfully confirmed by the structured agent.",
                    metadata={"key": "structured_confirmed", "value": True},
                )
                session.append_trace_event(
                    {
                        "event_type": "session.state_changed",
                        "actor": "bridge",
                        "payload": {
                            "from": "structured",
                            "to": "loop",
                            "round": rounds,
                            "status": "confirmed",
                        },
                    }
                )
                return BridgeResult(
                    outcome="confirmed",
                    rounds=rounds,
                    final_half_result=struct_result,
                    summary=f"booking confirmed by structured half: {struct_result.summary}",
                )

            if struct_result.next_action == "escalate":
                current_input = build_reverse_task(
                    loop_result_or_session=session,
                    struct_result_or_loop_result=current_input,
                    loop_result_arg=loop_result,
                    struct_result_arg=struct_result,
                    attempted_data=handoff.data,
                )
                session.append_trace_event(
                    {
                        "event_type": "session.state_changed",
                        "actor": "bridge",
                        "payload": {
                            "from": "structured",
                            "to": "loop",
                            "round": rounds,
                            "rejection_reason": (struct_result.output or {}).get("reason")
                            or struct_result.summary,
                        },
                    }
                )
                forward_file = session.ipc_input_dir / "handoff_to_structured.json"
                if forward_file.exists():
                    archive = session.handoffs_audit_dir / f"round_{rounds}_forward.json"
                    archive.parent.mkdir(parents=True, exist_ok=True)
                    forward_file.rename(archive)
                continue

            session.mark_failed(
                {"reason": f"unexpected struct outcome: {struct_result.next_action}"}
            )
            return BridgeResult(
                outcome="failed",
                rounds=rounds,
                final_half_result=struct_result,
                summary=f"unexpected struct outcome: {struct_result.next_action}",
            )

        session.mark_failed({"reason": f"max_rounds={self.max_rounds} exceeded"})
        final = last_struct or last_loop
        return BridgeResult(
            outcome="max_rounds_exceeded",
            rounds=rounds,
            final_half_result=final,
            summary=f"bridge exhausted {self.max_rounds} rounds without resolution",
        )


# ---------------------------------------------------------------------------
# Helper constructors — you may use these or write your own
# ---------------------------------------------------------------------------
def build_forward_handoff(session: Session, loop_result: HalfResult) -> Handoff:
    """Package loop result into a forward handoff, preferring latest tool truth."""
    import re

    from sovereign_agent.memory import MemoryStore, MemoryType

    store = MemoryStore(session)
    facts = store.list_facts(memory_type=MemoryType.EPISODIC)

    # Sort chronologically by timestamp in ID
    def _fact_sort_key(f):
        parts = f.id.split("_")
        if len(parts) >= 3:
            return parts[-3:]  # YYYYMMDD, HHMMSS, micros
        return ["0"] * 3

    facts = sorted(facts, key=_fact_sort_key)

    # Start from explicit handoff payload if provided.
    raw_payload = loop_result.handoff_payload or {}
    if (
        isinstance(raw_payload, dict)
        and "data" in raw_payload
        and isinstance(raw_payload["data"], dict)
    ):
        data = dict(raw_payload["data"])
    elif isinstance(raw_payload, dict):
        # Flat payload
        _meta_keys = {"reason", "context", "return_instructions"}
        data = {k: v for k, v in raw_payload.items() if k not in _meta_keys}
    else:
        data = {}

    # 1. Find Ground Truth from Semantic Memory (Current Targets)
    semantic_facts = store.list_facts(memory_type=MemoryType.SEMANTIC)
    targets = {}
    for fact in semantic_facts:
        key = fact.metadata.get("key")
        val = fact.metadata.get("value")
        if key in ("venue_id", "party_size", "deposit"):
            targets[key] = val

    # 2. Find Latest Successful Search and Cost as Fallback
    latest_search = None
    latest_cost = None

    for fact in reversed(facts):
        tool = fact.metadata.get("tool")
        out = fact.metadata.get("output", {})
        if tool == "calculate_cost" and latest_cost is None and fact.metadata.get("success"):
            latest_cost = out
        if tool == "venue_search" and latest_search is None and fact.metadata.get("success"):
            latest_search = out
        if latest_search and latest_cost:
            break

    # 3. Truth-First Augmentation
    # Priority: 1. data (explicit agent call) 2. targets (semantic facts) 3. tool results (episodic)

    if not data.get("venue_id"):
        data["venue_id"] = targets.get("venue_id")
    if not data.get("party_size"):
        data["party_size"] = targets.get("party_size")
    if not data.get("deposit"):
        data["deposit"] = targets.get("deposit")

    # Fallback to episodic if still missing
    cost_is_valid = False
    if latest_cost:
        if not latest_search:
            cost_is_valid = True
        elif latest_cost.get("venue_id") == latest_search.get("results", [{}])[0].get("id"):
            cost_is_valid = True
        elif latest_cost.get("venue_id") in [r.get("id") for r in latest_search.get("results", [])]:
            cost_is_valid = True

    if latest_cost and cost_is_valid:
        if not data.get("venue_id") and latest_cost.get("venue_id"):
            data["venue_id"] = latest_cost["venue_id"]
        if not data.get("party_size") and latest_cost.get("party_size") is not None:
            data["party_size"] = latest_cost["party_size"]
        if not data.get("deposit"):
            dep = latest_cost.get("deposit_required_gbp", latest_cost.get("deposit_gbp"))
            if dep is not None:
                data["deposit"] = f"£{dep}"

    # Next priority: latest venue_search.
    if latest_search:
        results = latest_search.get("results", [])
        if not data.get("venue_id") and results:
            data["venue_id"] = results[0].get("id")
        if not data.get("party_size") and latest_search.get("party_size") is not None:
            data["party_size"] = latest_search["party_size"]

    # Lowest priority: SESSION.md for date/time only.
    session_file = session.directory / "SESSION.md"
    if session_file.exists():
        content = session_file.read_text(encoding="utf-8")

        if not data.get("date"):
            m = re.search(
                r"(?:^|\n)\s*[-*]?\s*date:\s*['\"]?(\d{4}-\d{2}-\d{2})['\"]?",
                content,
                re.IGNORECASE,
            )
            if m:
                data["date"] = m.group(1)

        if not data.get("time"):
            m = re.search(
                r"(?:^|\n)\s*[-*]?\s*time:\s*['\"]?(\d{1,2}:\d{2})['\"]?",
                content,
                re.IGNORECASE,
            )
            if m:
                data["time"] = m.group(1)

        # IMPORTANT: only use SESSION party_size if still missing.
        if not data.get("party_size"):
            m = re.search(
                r"(?:^|\n)\s*[-*]?\s*(?:party_size|party size):\s*['\"]?(\d+)['\"]?",
                content,
                re.IGNORECASE,
            )
            if m:
                data["party_size"] = int(m.group(1))

    return Handoff(
        from_half="loop",
        to_half="structured",
        written_at=now_utc(),
        session_id=session.session_id,
        reason="loop-half requested confirmation",
        context=loop_result.summary,
        data=data,
        return_instructions=(
            "If you cannot confirm, respond with next_action=escalate and include "
            "a machine-readable reason (e.g. party_too_large, deposit_too_high)."
        ),
    )


def build_reverse_task(
    loop_result_or_session,
    struct_result_or_loop_result: HalfResult | None = None,
    loop_result_arg: HalfResult | None = None,
    struct_result_arg: HalfResult | None = None,
    attempted_data: dict | None = None,
    # Legacy keyword form for internal callers
    session: Session | None = None,
    original_task: dict | None = None,
) -> dict:
    """Build retry task preserving original constraints and adding machine-readable adaptation cues.

    Supports two call signatures:
      2-arg: build_reverse_task(loop_result, struct_result)
      4-arg: build_reverse_task(session, original_task, loop_result, struct_result)
    """
    # Detect 2-arg vs 4-arg call pattern
    if isinstance(loop_result_or_session, HalfResult):
        # 2-arg form: build_reverse_task(loop_result, struct_result)
        loop_result = loop_result_or_session
        struct_result = struct_result_or_loop_result  # type: ignore[assignment]
        _session = session
        _original_task = original_task or {}
    else:
        # 4-arg form: build_reverse_task(session, original_task, loop_result, struct_result)
        _session = loop_result_or_session  # type: ignore[assignment]
        _original_task = (
            (struct_result_or_loop_result or {})
            if not isinstance(struct_result_or_loop_result, HalfResult)
            else {}
        )  # type: ignore[assignment]
        loop_result = loop_result_arg  # type: ignore[assignment]
        struct_result = struct_result_arg  # type: ignore[assignment]

    reason_text = (
        (struct_result.output or {}).get("reason")
        or struct_result.summary
        or "rejected by structured half"
    )
    reason_lc = str(reason_text).lower()

    # Architectural Core: Semantic Memory Grounding
    from sovereign_agent.memory import MemoryStore, MemoryType

    store = MemoryStore(_session) if _session is not None else None
    semantic_facts = store.list_facts(memory_type=MemoryType.SEMANTIC) if store else []

    base_task = _original_task.get("task", "") if isinstance(_original_task, dict) else ""

    # Recover attempted values from the last loop handoff/output.
    attempted_party = None
    attempted_deposit_gbp = None
    attempted_venue_id = None

    payload = (
        attempted_data if isinstance(attempted_data, dict) else (loop_result.handoff_payload or {})
    )
    if isinstance(payload, dict):
        handoff_data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    else:
        handoff_data = {}

    if isinstance(handoff_data, dict):
        attempted_party = handoff_data.get("party_size")
        attempted_venue_id = handoff_data.get("venue_id")
        dep = handoff_data.get("deposit")
        if isinstance(dep, (int, float)):
            attempted_deposit_gbp = int(dep)
        elif isinstance(dep, str):
            import re

            m = re.search(r"(\d+)", dep)
            if m:
                attempted_deposit_gbp = int(m.group(1))

    if attempted_party is None and isinstance(loop_result.output, dict):
        attempted_party = loop_result.output.get("party_size")
    if attempted_venue_id is None and isinstance(loop_result.output, dict):
        attempted_venue_id = loop_result.output.get("venue_id")

    detected_city = "Edinburgh"  # Default fallback
    for fact in semantic_facts:
        if fact.metadata.get("key") == "city":
            detected_city = fact.metadata.get("value")
            break

    # Build Grounding Block
    ground_truth = []
    for fact in reversed(semantic_facts):
        key = fact.metadata.get("key")
        val = fact.metadata.get("value")
        if key == "party_size_max" and val:
            ground_truth.append(
                f"!! CRITICAL LIMIT: party_size must be <= {val} (verified by booking system rejection)"
            )
        elif key == "deposit_gbp_max" and val:
            ground_truth.append(
                f"!! CRITICAL LIMIT: deposit must be <= £{val} (verified by booking system rejection)"
            )
        elif key == "primary_candidate" and val:
            ground_truth.append(f"- Primary candidate venue_id: {val} (from search)")

    if attempted_venue_id and not any("venue_id" in s for s in ground_truth):
        ground_truth.append(f"- Last attempted venue_id: {attempted_venue_id}")
    if attempted_party and not any("party_size" in s for s in ground_truth):
        ground_truth.append(f"- Requested party_size: {attempted_party}")

    grounding_block = ""
    if ground_truth:
        grounding_block = (
            "\n"
            "==========================================================\n"
            "CURRENT SESSION CONSTRAINTS (OVERRIDING INITIAL TASK):\n"
            "==========================================================\n"
            + "\n".join(ground_truth)
            + "\n"
            "==========================================================\n\n"
        )

    # Normalize party_size to int if possible.
    if isinstance(attempted_party, str) and attempted_party.isdigit():
        attempted_party = int(attempted_party)

    # Reason-code routing (dynamic, no pinned values).
    constraints: dict = {}
    guidance_lines: list[str] = []
    reason_display = f"Rejection reason: {reason_text}"

    if struct_result.success:
        guidance_lines.append(
            f"✓ Booking CONFIRMED by structured half for {attempted_party} at '{attempted_venue_id}'."
        )
        # guidance_lines.append(
        #     "- FINAL STEPS: Generate the HTML flyer using generate_flyer, then call complete_task."
        # )
        reason_display = "Booking Confirmed"
    elif "party_too_large" in reason_lc:
        # ARCHITECTURAL IMPROVEMENT: Check for Research vs. Structured Dissonance
        research_capacity = None
        from sovereign_agent.memory import MemoryStore, MemoryType

        _store2 = MemoryStore(_session) if _session is not None else None
        epi_facts = _store2.list_facts(memory_type=MemoryType.EPISODIC) if _store2 else []
        for fact in reversed(epi_facts):
            if fact.metadata.get("tool") == "venue_search":
                results = fact.metadata.get("output", {}).get("results", [])
                for r in results:
                    if r.get("id") == attempted_venue_id:
                        research_capacity = r.get("max_capacity")
                        break
                if research_capacity:
                    break

        guidance_lines.append(
            f"- Previous proposal used party_size={attempted_party} at venue '{attempted_venue_id}' and was rejected. Adjust your search to the wider city of the following address {detected_city}."
        )
        # # 2. Propagate Discovered Limits from Structured Half
        metadata = (struct_result.output or {}).get("metadata") or {}
        p_limit = metadata.get("party_limit")
        d_limit = metadata.get("deposit_limit")

        # FALLBACK: Parse from text if metadata is missing (as added in actions.py)
        import re

        if p_limit is None:
            if m := re.search(r"limit is (\d+) people", reason_lc):
                p_limit = float(m.group(1))
        if d_limit is None:
            if m := re.search(r"limit is \u00a3(\d+)", reason_lc):
                d_limit = float(m.group(1))

        if p_limit:
            reason_display += f" (Limit: {p_limit} people)"
            constraints["party_size"] = {"op": "lte", "value": p_limit}
            if attempted_venue_id and research_capacity and research_capacity >= attempted_party:
                # The venue physically fits the party, but the automated system rejected it!
                guidance_lines.append(
                    f"- The online booking system has a global automated booking policy limit: party_size must be <= {p_limit}."
                )
                guidance_lines.append(
                    f"- ACTION: You must lower your target party_size to meet this global online booking limit (<= {p_limit}) and search/re-propose."
                )
            else:
                # The venue is physically too small
                guidance_lines.append(
                    f"- The venue '{attempted_venue_id}' only has capacity for {p_limit} people."
                )
                guidance_lines.append(
                    f"- ACTION: Find another venue in the city of the following address {detected_city} that has enough capacity, OR reduce the party_size to {p_limit} or less."
                )
            # guidance_lines.append(
            #     f"- The booking system reported that {attempted_venue_id} has a maximum capacity of {p_limit}."
            # )
            # guidance_lines.append(
            #     "- ACTION: Extend your search within the city that includes the primary venue, to accomodate the requested party size "
            # )
            # # ARCHITECTURAL IMPROVEMENT: Save rejection limit to Semantic Memory
            # if store is not None:
            #     store.write_fact(
            #         MemoryType.SEMANTIC,
            #         "constraint_party_size_max",
            #         f"Booking Restriction: party_size must be <= {p_limit}",
            #         metadata={"key": "party_size_max", "value": p_limit},
            #     )

        if not research_capacity or research_capacity >= attempted_party:
            guidance_lines.append(
                f"- IMPORTANT: Your research suggested '{attempted_venue_id}' has capacity for {research_capacity or 'Unknown'}, yet it rejected {attempted_party}."
                " This indicates a discrepancy between research data and real-time booking rules. Please find a venue with significantly higher capacity or check for other errors."
            )
        else:
            guidance_lines.append(
                f"- '{attempted_venue_id}' has a lower capacity than requested. Please try another venue within the city that the {attempted_venue_id} belongs to with larger capacity."
            )
    elif "deposit_too_high" in reason_lc:
        # 3. Propagate Deposit Limits
        metadata = (struct_result.output or {}).get("metadata") or {}
        d_limit = metadata.get("deposit_limit")
        if d_limit:
            constraints["deposit_gbp"] = {"op": "lte", "value": d_limit}
            guidance_lines.append(
                f"- The booking system reported a strict limit: deposit must be <= £{d_limit}."
            )
            # ARCHITECTURAL IMPROVEMENT: Save rejection limit to Semantic Memory
            if store is not None:
                store.write_fact(
                    MemoryType.SEMANTIC,
                    "constraint_deposit_gbp_max",
                    f"Booking Restriction: deposit must be <= £{d_limit}",
                    metadata={"key": "deposit_gbp_max", "value": d_limit},
                )

        if isinstance(attempted_deposit_gbp, int):
            constraints["deposit_gbp"] = {"op": "lt", "value": attempted_deposit_gbp}
            guidance_lines.append(
                f"- Previous proposal had deposit≈£{attempted_deposit_gbp}, which was too high."
            )
            guidance_lines.append(
                f"- Next proposal must target a lower deposit than £{attempted_deposit_gbp}."
            )
        guidance_lines.append(
            "- Reduce cost drivers (e.g., smaller party_size and/or cheaper venue profile)."
        )
    elif "missing_party_size" in reason_lc:
        guidance_lines.append("- Include party_size explicitly in handoff data.")
    elif "normalisation failed" in reason_lc:
        guidance_lines.append(
            "- Ensure handoff data is complete and parseable (venue_id, date, time, party_size, deposit)."
        )
    else:
        guidance_lines.append(
            "- Adapt proposal using the rejection reason and retry with a different plan."
        )

    guidance_block = "\n".join(guidance_lines)

    if struct_result.success:
        if store is not None:
            store.write_fact(
                MemoryType.SEMANTIC,
                "structured_confirmed",
                "Booking Confirmed by Rasa",
                metadata={"key": "structured_confirmed", "value": True},
            )
        retry_instructions = (
            "\n\nFINALIZATION INSTRUCTIONS:\n"
            "- Structured half result processed.\n"
            "- Booking Confirmed!\n"
            "- The booking is complete. You MUST NOW call complete_task to end the session.\n"
            "- Do NOT call any other tools. Do not search or calculate cost again.\n"
        )
    else:
        retry_instructions = (
            f"\n\nRETRY INSTRUCTIONS:\n"
            f"- Structured half result processed.\n"
            f"- Rejection reason: {reason_text}\n"
            "- Keep original user intent and constraints where possible.\n"
            "- Required workflow: venue_search -> calculate_cost -> handoff_to_structured.\n"
            "- CRITICAL: You MUST NOT call complete_task. You must produce a revised handoff proposal using handoff_to_structured.\n"
            "- Handoff data must include: venue_id, date, time, party_size, deposit.\n"
            f"{guidance_block}\n"
        )

    return {
        "task": f"{grounding_block}{base_task}{retry_instructions}",
        "context": {
            "retry": not struct_result.success,
            "rejection_reason": reason_text,
            "reason_code_hint": (
                "party_too_large"
                if "party_too_large" in reason_lc
                else "deposit_too_high"
                if "deposit_too_high" in reason_lc
                else "missing_party_size"
                if "missing_party_size" in reason_lc
                else "normalisation_failed"
                if "normalisation failed" in reason_lc
                else "other"
            ),
            "constraints": constraints,
            "attempted": {
                "party_size": attempted_party,
                "deposit_gbp": attempted_deposit_gbp,
                "venue_id": attempted_venue_id,
            },
            "prior_result": loop_result.output,
        },
    }
