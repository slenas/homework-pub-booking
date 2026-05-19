# Ex5 — Edinburgh research loop scenario

## Your answer

The planner produced five subgoals in `session.json`: sg_1 (search for venues near Haymarket station for 6 people), sg_2 (check weather in Edinburgh for April 25, 2026), sg_3 (calculate total cost for the selected venue), sg_4 (generate HTML flyer with event details), and sg_5 (complete the task). All five subgoals were successfully executed sequentially by the loop half in a single session.

The execution sequence consisted of:
- Turn 1: called `venue_search(near='Haymarket station', party_size=6, budget_max_gbp=800)`
- Turn 2: called `get_weather(city='Edinburgh', date='2026-04-25')`
- Turn 3: called `calculate_cost(venue_id='V123', party_size=6, duration_hours=3, catering_tier='bar_snacks')`
- Turn 4: wrote the flyer using `generate_flyer` passing the extracted facts (`venue_name='Haymarket Tap'`, total cost `£556`, and deposit `£111`)
- Turn 5: called `complete_task` to finalize the session.

The dataflow integrity check was essential for catching silent fabrications during development. For example, if the LLM hallucinated different total cost or weather parameters inside the HTML flyer (such as total cost of £9999), `verify_dataflow` compared the flyer's text against the `_TOOL_CALL_LOG` entries and marked them as unverified facts. This guaranteed that the generated flyer was fully grounded in facts returned by the tools, rather than speculative or fabricated values.

## Citations

- homework/ex5-edinburgh-research/sess_5e6a2143b0a2/logs/trace.jsonl — tool call sequence and execution log
- homework/ex5-edinburgh-research/sess_5e6a2143b0a2/workspace/flyer.html — the generated event flyer HTML file
