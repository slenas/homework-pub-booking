"""Ex5 tools. Four tools the agent uses to research an Edinburgh booking.

Each tool:
  1. Reads its fixture from sample_data/ (DO NOT modify the fixtures).
  2. Logs its arguments and output into _TOOL_CALL_LOG (see integrity.py).
  3. Returns a ToolResult with success=True/False, output=dict, summary=str.

The grader checks for:
  * Correct parallel_safe flags (reads True, generate_flyer False).
  * Every tool's results appear in _TOOL_CALL_LOG.
  * Tools fail gracefully on missing fixtures or bad inputs (ToolError,
    not RuntimeError).
"""

from __future__ import annotations

import json
from pathlib import Path

from sovereign_agent.errors import ToolError
from sovereign_agent.memory import MemoryStore, MemoryType
from sovereign_agent.session.directory import Session
from sovereign_agent.tools.registry import ToolRegistry, ToolResult, _RegisteredTool

from .integrity import record_tool_call

_SAMPLE_DATA = Path(__file__).parent / "sample_data"


# ---------------------------------------------------------------------------
# TODO 1 — venue_search
# ---------------------------------------------------------------------------
def venue_search(near: str, party_size: int, budget_max_gbp: int = 1000) -> ToolResult:
    """Search for Edinburgh venues near <near> that can seat the party."""
    venues_path = _SAMPLE_DATA / "venues.json"
    if not venues_path.exists():
        raise ToolError("SA_TOOL_DEPENDENCY_MISSING", f"Fixtures missing: {venues_path}")

    with venues_path.open() as f:
        venues = json.load(f)

    results = []
    near_lower = near.lower()
    for v in venues:
        if not v.get("open_now", False):
            continue
        if near_lower not in v.get("area", "").lower():
            continue
        if v.get("seats_available_evening", 0) < party_size:
            continue

        total_fee = v.get("hire_fee_gbp", 0) + v.get("min_spend_gbp", 0)
        if total_fee > budget_max_gbp:
            continue

        results.append(v)

    # Robustness fallback: if area search failed, return any open venue fitting party/budget
    if not results:
        fallback = []
        for v in venues:
            if v.get("open_now", False) and v.get("seats_available_evening", 0) >= party_size:
                if (v.get("hire_fee_gbp", 0) + v.get("min_spend_gbp", 0)) <= budget_max_gbp:
                    fallback.append(v)

        if fallback:
            results = fallback
            note = f"Area '{near}' not found. Returning alternatives in Edinburgh."
        else:
            note = "No venues matched your criteria."
    else:
        note = None

    output = {
        "near": near,
        "party_size": party_size,
        "budget_max_gbp": budget_max_gbp,
        "results": [
            {
                "id": v["id"],
                "name": v["name"],
                "address": v["address"],
                "area": v["area"],
                "max_capacity": v.get("seats_available_evening", 0),
            }
            for v in results
        ],
        "count": len(results),
    }
    if note:
        output["note"] = note

    record_tool_call(
        "venue_search",
        {"near": near, "party_size": party_size, "budget_max_gbp": budget_max_gbp},
        output,
    )

    summary = f"venue_search({near}, party={party_size}): {len(results)} result(s)"
    if results:
        summary += f". Primary candidate: {results[0]['name']} (id: {results[0]['id']})"

    return ToolResult(success=True, output=output, summary=summary)


# ---------------------------------------------------------------------------
# TODO 2 — get_weather
# ---------------------------------------------------------------------------
def get_weather(city: str, date: str) -> ToolResult:
    """Look up the scripted weather for <city> on <date> (YYYY-MM-DD)."""
    weather_path = _SAMPLE_DATA / "weather.json"
    if not weather_path.exists():
        raise ToolError("SA_TOOL_DEPENDENCY_MISSING", f"Fixtures missing: {weather_path}")

    with weather_path.open() as f:
        weather_data = json.load(f)

    city_key = city.lower()
    if city_key not in weather_data or date not in weather_data[city_key]:
        err = ToolError("SA_TOOL_INVALID_INPUT", f"Weather not found for {city} on {date}")
        return ToolResult(success=False, output={}, summary=str(err), error=err)

    output = dict(weather_data[city_key][date])
    output["city"] = city
    output["date"] = date

    record_tool_call("get_weather", {"city": city, "date": date}, output)

    return ToolResult(
        success=True,
        output=output,
        summary=f"get_weather({city}, {date}): {output['condition']}, {output['temperature_c']}C",
    )


# ---------------------------------------------------------------------------
# TODO 3 — calculate_cost
# ---------------------------------------------------------------------------
def calculate_cost(
    venue_id: str,
    party_size: int,
    duration_hours: int,
    catering_tier: str = "bar_snacks",
) -> ToolResult:
    """Compute the total cost for a booking."""
    catering_path = _SAMPLE_DATA / "catering.json"
    venues_path = _SAMPLE_DATA / "venues.json"
    if not catering_path.exists() or not venues_path.exists():
        raise ToolError("SA_TOOL_DEPENDENCY_MISSING", "Fixtures missing")

    with catering_path.open() as f:
        catering_data = json.load(f)
    with venues_path.open() as f:
        venues = json.load(f)

    venue = next((v for v in venues if v["id"] == venue_id), None)
    if not venue:
        err = ToolError("SA_TOOL_INVALID_INPUT", f"Venue {venue_id} not found")
        return ToolResult(success=False, output={}, summary=str(err), error=err)

    base_rates = catering_data.get("base_rates_gbp_per_head", {})
    if catering_tier not in base_rates:
        err = ToolError("SA_TOOL_INVALID_INPUT", f"Unknown catering tier: {catering_tier}")
        return ToolResult(success=False, output={}, summary=str(err), error=err)

    base_per_head = base_rates[catering_tier]
    venue_mult = catering_data.get("venue_modifiers", {}).get(venue_id, 1.0)

    subtotal = int(base_per_head * venue_mult * party_size * max(1, duration_hours))
    service = int(subtotal * catering_data.get("service_charge_percent", 0) / 100)
    venue_fees = venue.get("hire_fee_gbp", 0) + venue.get("min_spend_gbp", 0)
    total = subtotal + service + venue_fees

    if total < 300:
        deposit = 0
    elif total <= 1000:
        deposit = int(total * 0.2)
    else:
        deposit = int(total * 0.3)

    output = {
        "venue_id": venue_id,
        "party_size": party_size,
        "duration_hours": duration_hours,
        "catering_tier": catering_tier,
        "subtotal_gbp": subtotal,
        "service_gbp": service,
        "total_gbp": total,
        "deposit_required_gbp": deposit,
    }

    record_tool_call(
        "calculate_cost",
        {
            "venue_id": venue_id,
            "party_size": party_size,
            "duration_hours": duration_hours,
            "catering_tier": catering_tier,
        },
        output,
    )

    return ToolResult(
        success=True,
        output=output,
        summary=f"calculate_cost({venue_id}, party={party_size}): total £{total}, deposit £{deposit}",
    )


# ---------------------------------------------------------------------------
# TODO 4 — generate_flyer
# ---------------------------------------------------------------------------
def generate_flyer(session: Session, event_details: dict) -> ToolResult:
    """Produce an HTML flyer and write it to workspace/flyer.html."""
    html = f"""<!DOCTYPE html>
<html>
<head><style>body {{ font-family: sans-serif; max-width: 600px; margin: 2em auto; padding: 1em; border: 1px solid #ccc; }} h1 {{ color: #2c3e50; text-align: center; }} .fact {{ margin: 0.5em 0; }} .label {{ font-weight: bold; }}</style></head>
<body>
    <h1 data-testid="venue_name">{event_details.get("venue_name")}</h1>
    <div class="fact"><span class="label">Address:</span> <span data-testid="venue_address">{event_details.get("venue_address")}</span></div>
    <div class="fact"><span class="label">Date:</span> <span data-testid="date">{event_details.get("date")}</span></div>
    <div class="fact"><span class="label">Time:</span> <span data-testid="time">{event_details.get("time")}</span></div>
    <div class="fact"><span class="label">Party Size:</span> <span data-testid="party_size">{event_details.get("party_size")}</span></div>
    <hr><h2>Weather</h2>
    <div class="fact"><span class="label">Condition:</span> <span data-testid="condition">{event_details.get("condition")}</span></div>
    <div class="fact"><span class="label">Temperature:</span> <span data-testid="temperature_c">{event_details.get("temperature_c")}</span>°C</div>
    <hr><h2>Cost Breakdown</h2>
    <div class="fact"><span class="label">Total Cost:</span> <span data-testid="total_gbp">£{event_details.get("total_gbp")}</span></div>
    <div class="fact"><span class="label">Deposit Required:</span> <span data-testid="deposit_required_gbp">£{event_details.get("deposit_required_gbp")}</span></div>
</body>
</html>
"""
    target_path = session.workspace_dir / "flyer.html"
    session.workspace_dir.mkdir(parents=True, exist_ok=True)
    target_path.write_text(html, encoding="utf-8")

    output = {"path": "workspace/flyer.html", "bytes_written": len(html)}
    record_tool_call("generate_flyer", {"event_details": event_details}, output)

    return ToolResult(
        success=True,
        output=output,
        summary=f"generate_flyer: wrote {output['path']} ({len(html)} chars)",
    )


# ---------------------------------------------------------------------------
# Registry builder — DO NOT MODIFY the name, signature, or registration calls.
# ---------------------------------------------------------------------------
def build_tool_registry(session: Session) -> ToolRegistry:
    """Build a session-scoped tool registry with all four Ex5 tools."""
    from sovereign_agent.tools.builtin import make_builtin_registry

    reg = make_builtin_registry(session)
    store = MemoryStore(session)

    def _save_to_memory(tool_name: str, result: ToolResult, arguments: dict | None = None):
        if result.success:
            from datetime import datetime

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            store.write_fact(
                MemoryType.EPISODIC,
                f"{tool_name}_{timestamp}",
                result.summary,
                metadata={"tool": tool_name, "output": result.output, "arguments": arguments},
            )

            # Write to Semantic Memory (Persistent Verified State)
            if arguments and "party_size" in arguments:
                p_val = arguments["party_size"]
                # 1. Respect Existing Constraints: Don't allow a 'Target' that violates a 'Constraint'
                semantic_facts = store.list_facts(memory_type=MemoryType.SEMANTIC)
                p_max = next(
                    (
                        f.metadata["value"]
                        for f in semantic_facts
                        if f.metadata.get("key") == "party_size_max"
                    ),
                    None,
                )

                if p_max is not None and p_val > p_max:
                    # If we already knew the limit, this target shouldn't have been set.
                    # But if we are here, the tool already succeeded. We just won't update the 'Target' to something invalid.
                    pass
                else:
                    store.write_fact(
                        MemoryType.SEMANTIC,
                        "target_party_size",
                        f"Current Target: party_size={p_val}",
                        metadata={"key": "party_size", "value": p_val},
                    )
            if tool_name == "venue_search" and result.success:
                results = result.output.get("results", [])
                if results:
                    primary = results[0]["id"]
                    store.write_fact(
                        MemoryType.SEMANTIC,
                        "primary_candidate_venue",
                        f"Primary candidate from search: {primary}",
                    metadata={"key": "primary_candidate", "value": primary},
                )
                # Also store it as 'venue_id' for easier lookup
                store.write_fact(
                    MemoryType.SEMANTIC,
                    "target_venue_id",
                    f"Current Target: venue_id={primary}",
                    metadata={"key": "venue_id", "value": primary},
                )
            if tool_name == "calculate_cost" and result.success:
                out = result.output
                dep = out.get("deposit_required_gbp", out.get("deposit_gbp"))
                if dep is not None:
                    store.write_fact(
                        MemoryType.SEMANTIC,
                        "target_deposit",
                        f"Current Target: deposit=£{dep}",
                        metadata={"key": "deposit", "value": f"£{dep}"},
                    )
            if arguments and "time" in arguments:
                t_val = arguments["time"]
                store.write_fact(
                    MemoryType.SEMANTIC,
                    "target_time",
                    f"Current Target: time={t_val}",
                    metadata={"key": "time", "value": t_val},
                )

    # venue_search
    def _venue_search_adapter(near: str, party_size: int, budget_max_gbp: int = 1000) -> ToolResult:
        # --- Search Lock Logic ---
        # If we already have a successful search result in memory, and NO rejection has happened
        # since then, block any further venue_search calls to prevent hallucinatory drift.
        facts = store.list_facts(memory_type=MemoryType.EPISODIC)
        semantic_facts = store.list_facts(memory_type=MemoryType.SEMANTIC)
        
        has_results = False
        for fact in semantic_facts:
            if fact.metadata.get("key") == "primary_candidate":
                has_results = True
                break
        
        has_rejection = False
        for fact in semantic_facts:
            if fact.metadata.get("key") in ("party_size_max", "deposit_gbp_max"):
                has_rejection = True
                break
        
        # If we have results and haven't been rejected, don't search again!
        if has_results and not has_rejection:
            return ToolResult(
                success=False,
                output={"error": "REDUNDANT_SEARCH", "reason": "You already have valid candidates. Proceed to calculate_cost."},
                summary="Error: You already have candidates from your previous search. DO NOT search again. Use calculate_cost for your primary candidate instead."
            )
        # -------------------------

        # ARCHITECTURAL IMPROVEMENT: Check Persistent Rejection Constraints
        semantic_facts = store.list_facts(memory_type=MemoryType.SEMANTIC)
        for fact in semantic_facts:
            if fact.metadata.get("key") == "party_size_max":
                try:
                    p_max = float(fact.metadata["value"])
                    if party_size > p_max:
                        return ToolResult(
                            success=False,
                            output={
                                "error": "CONSTRAINT_VIOLATION",
                                "requested": party_size,
                                "limit": p_max,
                            },
                            summary=f"Error: You already know the booking system has a limit of {p_max} people from a previous rejection. Your search for {party_size} is invalid. DO NOT hand this error off to the structured half. FIX the party_size to {p_max} or less and search again locally.",
                        )
                except (ValueError, TypeError):
                    continue

        res = venue_search(near, party_size, budget_max_gbp)
        _save_to_memory(
            "venue_search",
            res,
            {"near": near, "party_size": party_size, "budget_max_gbp": budget_max_gbp},
        )
        
        # Improvement: Directive Summary
        if res.success and res.output.get("results"):
            primary = res.output["results"][0]
            res.summary = (
                f"venue_search({near}, party={party_size}): {len(res.output['results'])} result(s). "
                f"Primary candidate: {primary['name']} (id: {primary['id']}). "
                f"STOP searching. Use calculate_cost(venue_id='{primary['id']}', party_size={party_size}) next."
            )
        return res

    reg.register(
        _RegisteredTool(
            name="venue_search",
            description=(
                "Search Edinburgh venues by area, party size, and max budget. Results are stored in Session Memory. "
                "Do NOT use list_files to check for results. If no results are found, FIX your parameters and SEARCH AGAIN. "
                "DO NOT hand off a search failure to the structured half."
            ),
            fn=_venue_search_adapter,
            parameters_schema={
                "type": "object",
                "properties": {
                    "near": {"type": "string"},
                    "party_size": {"type": "integer"},
                    "budget_max_gbp": {"type": "integer", "default": 1000},
                },
                "required": ["near", "party_size"],
            },
            returns_schema={"type": "object"},
            is_async=False,
            parallel_safe=True,
        )
    )

    # get_weather
    def _get_weather_adapter(city: str, date: str) -> ToolResult:
        res = get_weather(city, date)
        _save_to_memory("get_weather", res, {"city": city, "date": date})
        return res

    reg.register(
        _RegisteredTool(
            name="get_weather",
            description="Get scripted weather. This is an INTERMEDIATE step; you must proceed to cost calculation and flyer generation after this.",
            fn=_get_weather_adapter,
            parameters_schema={
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "date": {"type": "string"},
                },
                "required": ["city", "date"],
            },
            returns_schema={"type": "object"},
            is_async=False,
            parallel_safe=True,
            # examples=[
            #     {
            #         "input": {"city": "Edinburgh", "date": "2026-04-25"},
            #         "output": {"condition": "cloudy", "temperature_c": 12},
            #     }
            # ],
        )
    )

    # calculate_cost
    def _calculate_cost_adapter(
        venue_id: str, party_size: int, duration_hours: int, catering_tier: str = "bar_snacks"
    ) -> ToolResult:
        # ARCHITECTURAL CORE: Pull Current Commitment and Constraints from Semantic Memory
        semantic_facts = store.list_facts(memory_type=MemoryType.SEMANTIC)
        target_party = None
        target_venue = None
        p_max = None
        d_max = None

        for fact in semantic_facts:
            key = fact.metadata.get("key")
            val = fact.metadata.get("value")
            if key == "party_size":
                target_party = val
            if key == "primary_candidate":
                target_venue = val
            if key == "party_size_max":
                p_max = val
            if key == "deposit_gbp_max":
                d_max = val

        # --- Autofill Logic ---
        if not venue_id or not party_size:
            # Try semantic facts first
            facts = store.list_facts(memory_type=MemoryType.EPISODIC)
            semantic_facts = store.list_facts(memory_type=MemoryType.SEMANTIC)
            for f in semantic_facts:
                if f.metadata.get("key") == "primary_candidate" and not venue_id:
                    venue_id = f.metadata["value"]
                if f.metadata.get("key") == "target_party" and not party_size:
                    party_size = f.metadata["value"]
            
            # Then check latest successful search in episodic memory
            if not venue_id or not party_size:
                for fact in reversed(facts):
                    if fact.metadata.get("tool") == "venue_search" and fact.metadata.get("success"):
                        out = fact.metadata.get("output", {})
                        results = out.get("results", [])
                        if not venue_id and results:
                            venue_id = results[0]["id"]
                        if not party_size:
                            party_size = out.get("party_size")
                        break
        # ----------------------

        # Truth-First: If the agent used a placeholder (as instructed in the task),
        # pull the real venue_id from semantic memory.
        if (venue_id.startswith("V") or venue_id == "<chosen pub's id>") and target_venue:
            venue_id = target_venue

        # 1. Constraint Enforcement
        if p_max is not None:
            try:
                p_max_val = float(p_max)
                if party_size > p_max_val:
                    return ToolResult(
                        success=False,
                        output={"error": "CONSTRAINT_VIOLATION", "requested": party_size, "limit": p_max_val},
                        summary=f"Error: Rejection history shows a limit of {p_max_val} people. You cannot calculate cost for {party_size}.",
                    )
            except (ValueError, TypeError):
                pass

        # Plan Consistency
        if target_party is not None and int(party_size) != int(target_party):
            return ToolResult(
                success=False,
                output={"error": "CONSISTENCY_FAILURE", "requested": party_size, "expected": target_party},
                summary=f"Error: You searched for party_size={target_party}. You cannot calculate cost for {party_size} without doing a new venue_search first. Please use party_size={target_party}.",
            )

        facts = store.list_facts(memory_type=MemoryType.EPISODIC)

        # 1. Evidence-Based Validation: Check venue_id and capacity from search history
        valid_ids = []
        found_venue = False
        for fact in reversed(facts):
            if fact.metadata.get("tool") == "venue_search":
                results = fact.metadata.get("output", {}).get("results", [])
                for r in results:
                    v_id = r["id"]
                    v_cap = r.get("max_capacity")
                    valid_ids.append(v_id)
                    if venue_id == v_id:
                        found_venue = True
                        if party_size > v_cap:
                            return ToolResult(
                                success=False,
                                output={
                                    "error": "CAPACITY_EXCEEDED",
                                    "venue_id": venue_id,
                                    "requested": party_size,
                                    "max_capacity": v_cap,
                                },
                                summary=f"Error: Venue '{venue_id}' only supports up to {v_cap} people according to your research. You requested {party_size}.",
                            )
                if found_venue:
                    break

        if not found_venue:
            return ToolResult(
                success=False,
                output={
                    "error": "INVALID_VENUE_ID",
                    "provided": venue_id,
                    "available": list(set(valid_ids)),
                },
                summary=f"Error: venue_id '{venue_id}' was not found in your previous search results. Available IDs: {list(set(valid_ids))}",
            )

        # --- Truth-First: Enforce Primary Candidate ---
        semantic_facts = store.list_facts(memory_type=MemoryType.SEMANTIC)
        primary_id = None
        for f in semantic_facts:
            if f.metadata.get("key") == "primary_candidate":
                primary_id = f.metadata["value"]
                break
        
        # If we have a primary candidate, you MUST use it.
        # Exception: if we are in Ex7 and have a rejection (meaning the primary failed).
        has_rejection = any(f.metadata.get("key") in ("party_size_max", "deposit_gbp_max") for f in semantic_facts)
        
        if primary_id and venue_id != primary_id and not has_rejection:
            return ToolResult(
                success=False,
                output={"error": "INVALID_VENUE_ID", "provided": venue_id, "required": primary_id},
                summary=f"Error: Your research identified '{primary_id}' as the primary candidate. You MUST calculate cost for it first. Do not use '{venue_id}'."
            )
        # -----------------------------------------------

        res = calculate_cost(venue_id, party_size, duration_hours, catering_tier)
        if res.success and d_max is not None:
            try:
                deposit_val = float(res.output.get("deposit_gbp", res.output.get("deposit", 0)))
                d_max_val = float(d_max)
                if deposit_val > d_max_val:
                    return ToolResult(
                        success=False,
                        output={"error": "CONSTRAINT_VIOLATION", "deposit": deposit_val, "limit": d_max_val},
                        summary=f"Error: The calculated deposit of £{deposit_val} exceeds the strict limit of £{d_max_val}. Try a cheaper catering tier or smaller party.",
                    )
            except (ValueError, TypeError):
                pass
        
        _save_to_memory(
            "calculate_cost",
            res,
            {
                "venue_id": venue_id,
                "party_size": party_size,
                "duration_hours": duration_hours,
                "catering_tier": catering_tier,
            },
        )
        return res

    reg.register(
        _RegisteredTool(
            name="calculate_cost",
            description=(
                "Compute total cost. The venue_id MUST be obtained from the venue_search tool output. Do NOT guess it. "
                "This is an intermediate step; do NOT use list_files or write_file. All results are automatically stored "
                "in Session Memory (Episodic and Semantic facts). Rely on memory, not files in the workspace."
            ),
            fn=_calculate_cost_adapter,
            parameters_schema={
                "type": "object",
                "properties": {
                    "venue_id": {"type": "string"},
                    "party_size": {"type": "integer"},
                    "duration_hours": {"type": "integer"},
                    "catering_tier": {
                        "type": "string",
                        "enum": ["drinks_only", "bar_snacks", "sit_down_meal", "three_course_meal"],
                        "default": "bar_snacks",
                    },
                },
                "required": ["venue_id", "party_size", "duration_hours"],
            },
            returns_schema={"type": "object"},
            is_async=False,
            parallel_safe=True,
            # examples=[
            #     {
            #         "input": {
            #             "venue_id": "haymarket_tap",
            #             "party_size": 6,
            #             "duration_hours": 3,
            #         },
            #         "output": {"total_gbp": 540, "deposit_required_gbp": 0},
            #     }
            # ],
        )
    )

    # generate_flyer — parallel_safe=False because it writes a file
    def _flyer_adapter(event_details: dict) -> ToolResult:
        # TRUTH-FIRST: populate fields from episodic memory, overwriting hallucinations
        facts = store.list_facts(memory_type=MemoryType.EPISODIC)

        seen_tools = set()
        for fact in reversed(facts):
            tool = fact.metadata.get("tool")
            if not tool or tool in seen_tools:
                continue
            seen_tools.add(tool)

            out = fact.metadata.get("output", {})
            if tool == "venue_search":
                res = out.get("results", [])
                if res:
                    event_details["venue_name"] = res[0].get("name")
                    event_details["venue_address"] = res[0].get("address")
                if out.get("party_size"):
                    event_details["party_size"] = out["party_size"]
            elif tool == "get_weather":
                event_details["condition"] = out.get("condition")
                event_details["temperature_c"] = out.get("temperature_c")
                if out.get("date"):
                    event_details["date"] = out["date"]
            elif tool == "calculate_cost":
                event_details["total_gbp"] = out.get("total_gbp")
                event_details["deposit_required_gbp"] = out.get("deposit_required_gbp")
        
        # Finally, check semantic memory for target_time
        semantic_facts = store.list_facts(memory_type=MemoryType.SEMANTIC)
        for f in semantic_facts:
            if f.metadata.get("key") == "time" and not event_details.get("time"):
                event_details["time"] = f.metadata["value"]

        res = generate_flyer(session, event_details)
        if res.success:
            res.summary = f"generate_flyer: wrote workspace/flyer.html ({len(res.output.get('html', ''))} chars). YOU ARE DONE. Call complete_task now."
        return res

    reg.register(
        _RegisteredTool(
            name="generate_flyer",
            description=(
                "Write an HTML flyer to workspace/flyer.html. The event_details dictionary MUST contain these EXACT keys: "
                "venue_name, venue_address, date, time, party_size, condition, temperature_c, total_gbp, deposit_required_gbp. "
                "Extract these from previous tool outputs (venue_search, get_weather, calculate_cost) and the session memory. Do not come up with random values."
            ),
            fn=_flyer_adapter,
            parameters_schema={
                "type": "object",
                "properties": {"event_details": {"type": "object"}},
                "required": ["event_details"],
            },
            returns_schema={"type": "object"},
            is_async=False,
            parallel_safe=False,
            # examples=[
            #     {
            #         "input": {
            #             "event_details": {
            #                 "venue_name": "Haymarket Tap",
            #                 "date": "2026-04-25",
            #                 "party_size": 6,
            #             }
            #         },
            #         "output": {"path": "workspace/flyer.html"},
            #     }
            # ],
        )
    )

    # handoff_to_structured
    try:
        orig_handoff = reg.get("handoff_to_structured")
        base_handoff_fn = orig_handoff.fn

        def _handoff_adapter(reason: str, context: str, data: dict) -> ToolResult:
            facts = store.list_facts(memory_type=MemoryType.EPISODIC)
            semantic_facts = store.list_facts(memory_type=MemoryType.SEMANTIC)

            # Define targets for guard logic
            targets = {}
            for fact in semantic_facts:
                key = fact.metadata.get("key")
                val = fact.metadata.get("value")
                if key in ("venue_id", "party_size", "deposit"):
                    targets[key] = val

            # --- Handoff Guard Logic ---
            # Do NOT allow handing off errors, placeholders, or incomplete data.
            err_keys = {"error", "error_code", "violation", "failure", "missing_parameters", "no_results"}
            data_values = (str(data) + " " + reason + " " + context).lower()
            
            if any(k in data for k in err_keys) or "violation" in reason.lower() or "error" in reason.lower() or \
               "missing" in data_values or "n/a" in data_values or "unknown" in data_values or \
               "no results" in data_values or "empty" in data_values or "workspace" in data_values:
                return ToolResult(
                    success=False,
                    output={"error": "INVALID_HANDOFF", "reason": "You cannot hand off a failure, search miss, or workspace confusion. You must fix the parameters locally (e.g. reduce party size, find venue_id) until you have a COMPLETE and VALID booking proposal (venue_id, party_size, deposit)."},
                    summary="Error: Invalid handoff. You are trying to hand off a search failure or incomplete data. Handle this locally by adjusting your parameters and re-running venue_search/calculate_cost until you have a valid proposal. DO NOT list_files, rely on session memory."
                )
            
            # Mandatory fields for structured half
            mandatory = ["venue_id", "party_size", "deposit"]
            if not all(data.get(k) or targets.get(k) for k in mandatory):
                 return ToolResult(
                    success=False,
                    output={"error": "INCOMPLETE_DATA", "missing": [k for k in mandatory if not data.get(k) and not targets.get(k)]},
                    summary="Error: Your handoff is missing mandatory fields. Ensure you have successfully called venue_search AND calculate_cost before handing off."
                )
            # ---------------------------

            # --- Autofill Logic ---
            # Prioritize Semantic Facts (Current Targets)
            for key, val in targets.items():
                if key == "venue_id" and not data.get("venue_id"):
                    data["venue_id"] = val
                if key == "party_size" and not data.get("party_size"):
                    data["party_size"] = val
                if key == "deposit" and not data.get("deposit"):
                    data["deposit"] = val

            # Fallback to episodic memory if semantic facts missing
            if not data.get("deposit"):
                # Try to recover from latest successful calculate_cost
                for fact in reversed(facts):
                    if fact.metadata.get("tool") == "calculate_cost" and fact.metadata.get("success"):
                        out = fact.metadata.get("output", {})
                        dep = out.get("deposit_required_gbp", out.get("deposit_gbp"))
                        if dep is not None:
                            data["deposit"] = f"£{dep}"
                        if not data.get("venue_id"):
                            data["venue_id"] = out.get("venue_id")
                        if not data.get("party_size"):
                            data["party_size"] = out.get("party_size")
                        break
            
            if not data.get("venue_id") or not data.get("party_size"):
                 # Try to recover from latest venue_search
                 for fact in reversed(facts):
                    if fact.metadata.get("tool") == "venue_search" and fact.metadata.get("success"):
                        out = fact.metadata.get("output", {})
                        results = out.get("results", [])
                        if not data.get("venue_id") and results:
                            data["venue_id"] = results[0]["id"]
                        if not data.get("party_size"):
                            data["party_size"] = out.get("party_size")
                        break
            # ----------------------

            # Consistency Check: party_size and venue_id must match search/cost history
            expected_venue = None
            expected_party = None
            for fact in reversed(facts):
                tool = fact.metadata.get("tool")
                out = fact.metadata.get("output", {})
                if tool == "calculate_cost":
                    expected_venue = out.get("venue_id")
                    expected_party = out.get("party_size")
                    break
                if tool == "venue_search" and not expected_venue:
                    res = out.get("results", [])
                    if res:
                        expected_venue = res[0]["id"]
                        expected_party = out.get("party_size")
                        break

            # If the Agent's handoff data differs from its own tool results, reject it
            if data:
                if expected_venue and data.get("venue_id") and data["venue_id"] != expected_venue:
                    return ToolResult(
                        success=False,
                        output={
                            "error": "CONSISTENCY_FAILURE",
                            "provided": data["venue_id"],
                            "expected": expected_venue,
                        },
                        summary=f"Error: Consistency failure. You are handing off venue_id '{data['venue_id']}', but your own cost calculation was for '{expected_venue}'. Please fix your proposal.",
                    )
                if (
                    expected_party
                    and data.get("party_size")
                    and int(data["party_size"]) != int(expected_party)
                ):
                    return ToolResult(
                        success=False,
                        output={
                            "error": "CONSISTENCY_FAILURE",
                            "provided": data["party_size"],
                            "expected": expected_party,
                        },
                        summary=f"Error: Consistency failure. You are handing off party_size={data['party_size']}, but your own tool results are for {expected_party}. Please fix your proposal.",
                    )

            return base_handoff_fn(reason=reason, context=context, data=data)

        orig_handoff.fn = _handoff_adapter
    except Exception:
        pass

    # Override complete_task to prevent early exits in Ex7
    try:
        complete_tool = reg.get("complete_task")
        base_complete_fn = complete_tool.fn
        
        def _complete_adapter(**kwargs) -> ToolResult:
            has_handoff = False
            try:
                if reg.get("handoff_to_structured") is not None:
                    has_handoff = True
            except Exception:
                pass
            if has_handoff:
                semantic_facts = store.list_facts(memory_type=MemoryType.SEMANTIC)
                is_confirmed = any(f.metadata.get("key") == "structured_confirmed" for f in semantic_facts)
                
                # Exception for Ex5: If flyer exists, it's a research task completion
                import os
                flyer_exists = os.path.exists(os.path.join(session.directory, "workspace", "flyer.html"))
                
                if not is_confirmed and not flyer_exists:
                    return ToolResult(
                        success=False,
                        output={"error": "PREMATURE_COMPLETION"},
                        summary="Error: You MUST call handoff_to_structured with your proposal first. Do not call complete_task until the booking is confirmed by the structured half."
                    )
            return base_complete_fn(**kwargs)
            
        complete_tool.fn = _complete_adapter
        complete_tool.description = "Mark the FULL session as complete. DO NOT call this until generate_flyer has been run and workspace/flyer.html is created. In Ex7, ONLY call this AFTER structured half confirms the booking."
    except Exception:
        pass

    return reg


__all__ = [
    "build_tool_registry",
    "venue_search",
    "get_weather",
    "calculate_cost",
    "generate_flyer",
]
