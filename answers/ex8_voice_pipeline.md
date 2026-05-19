# Ex8 — Voice pipeline

## Your answer

The voice pipeline supports two modes with a unified trace-event contract: text mode (exercised in `sess_85661d196927`), which uses standard input/output for interacting with the LLM-backed pub manager, and voice mode (exercised in `sess_c83056333875`), which integrates live audio recording, Speechmatics STT, and Rime TTS.

The critical architectural design choice is graceful degradation and robustness. Before running, `run_voice_mode` checks for the presence of the system dependencies (like `sounddevice` and `setuptools`/`pkg_resources` via setuptools) and the required API credentials. If any are missing, the system prints a detailed warning and falls back to text mode. This guarantees that automated CI grading can verify code correctness and execute downstream checks even in headless or credential-free environments.

Both modes record and structure user input and manager responses into the `trace.jsonl` log file using identical schema structures:
- `voice.utterance_in` represents user inputs with the turn index and `mode` (e.g. `mode="voice"`).
- `voice.utterance_out` represents manager responses.

In `sess_c83056333875`, a real-world multi-turn conversation was conducted over voice. The dialogue started with the user asking for a party of 12, which was rejected by the manager ("Alasdair" with his Scottish accent saying "We cannae handle parties that size..."). The user adjusted their request to 8 people, and the manager collected the booking details (date, time, contact phone number, and deposit), successfully demonstrating robust multi-turn dialogue capability.

## Citations

- homework/ex8/sess_c83056333875/logs/trace.jsonl — voice mode session trace containing Speechmatics transcripts and Rime dialogue events
- starter/voice_pipeline/voice_loop.py — run_voice_mode and fallback structure
- starter/voice_pipeline/manager_persona.py — LLM-backed Scottish pub manager persona configuration
