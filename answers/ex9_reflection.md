# Ex9 — Reflection

## Q1 — Planner handoff decision

### Your answer

In my Ex7 run (session `sess_494a1be4f7fa`), the planner generated three subgoals in both Round 1 (`tk_d6e50504`) and Round 2 (`tk_daa46b98`). In both rounds, the third subgoal was to commit the booking via the structured half (`sg_3` "Commit the booking via handoff_to_structured with required data" / "Submit booking with adjusted party size 8") and was assigned to the `structured` half. 

The signal that drove the planner to make this assignment was the task instruction to "commit" or "submit" the booking under policy rules. The LLM's system prompt specifies that the structured half is intended for processing strict rules and formal validations. Therefore, the planner correctly inferred that booking submission is a rule-bound execution task, assigning it to `structured`.

This decision is advisory. The orchestrator only knows how to route execution between halves because we have implemented the cross-half IPC bridge. If the structured half were not present (or if the bridge were broken), a subgoal assigned to structured would simply be lost in transit, leading to a hang or crash. This highlights the importance of the handoff bridge as the physical runtime engine for the planner's high-level architectural designs.

### Citation

- homework/ex7-handoff-bridge/sess_494a1be4f7fa/logs/tickets/tk_d6e50504/raw_output.json — Round 1 subgoal plan
- homework/ex7-handoff-bridge/sess_494a1be4f7fa/logs/tickets/tk_daa46b98/raw_output.json — Round 2 subgoal plan

---

## Q2 — Dataflow integrity catch

### Your answer

During Ex5 development of session `sess_5e6a2143b0a2`, the flyer successfully generated a correct total cost of `£556` and deposit of `£111` matching the `calculate_cost` tool outputs. To evaluate the robustness of the dataflow check, we manually edited `flyer.html` inside the workspace directory, changing `£556` to a fabricated value of `£9999` and re-running the check standalone. 

The `verify_dataflow` function immediately flagged the modification, returning `ok=False` with `unverified_facts=['£9999']`. It caught the discrepancy because it audits every monetary and condition fact in the flyer against the exact in-memory `_TOOL_CALL_LOG` records populated by the tools, rather than just assessing if the number "looks reasonable." 

Without this programmatic check, a human developer or grading script would easily miss a minor hallucination (such as a total cost of £560 instead of £556) because the value falls within plausible ranges. Programmatic audit against verified tool call traces is the only reliable way to guarantee truth-first agent execution.

### Citation

- homework/ex5-edinburgh-research/sess_5e6a2143b0a2/workspace/flyer.html — flyer output file
- homework/ex5-edinburgh-research/sess_5e6a2143b0a2/logs/trace.jsonl — tool call log of actual outputs

---

## Q3 — Removing one framework primitive

### Your answer

If forced to reduce the framework to its absolute minimum and keep only one primitive, I would choose session directories (Decision 1) as the irreplaceable foundation and rebuild everything else around it. 

The forward-only state machine (Decision 2), tickets (Decision 3), and atomic-rename IPC (Decision 5) are all convenient abstractions, but they all depend on the existence of a clean, isolated local directory namespace. Without session directories, the system suffers from cross-session data leaks, race conditions, and an impossible auditing process where multi-agent traces are jumbled together. 

Session directories are like git repositories; they provide a physical boundary and history. You can easily rebuild atomic renaming by using simple file lock checkers or directory polling inside a session directory, but you cannot reconstruct isolated, crash-resilient session states without the physical directory structure itself.

### Citation

- homework/ex5-edinburgh-research/sess_5e6a2143b0a2/ — Ex5 session workspace directory structure
- homework/ex7-handoff-bridge/sess_494a1be4f7fa/logs/trace.jsonl — isolated multi-round trace log
