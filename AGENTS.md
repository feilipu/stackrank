# Stackrank — Grok project rules

## Qwen3.8 helper slices (mandatory)

Qwen3.8 (`qwen38-coder`) only gets **tiny slices**. Never hand it a spec, a whole file rewrite, or a multi-file feature in one prompt.

A slice is one of:

- one function, or
- one route handler, or
- one template partial, or
- one test, or
- one docs paragraph

Hard limits for a Qwen prompt:

- one concrete file path
- one acceptance check (a test name or a curl)
- no “also update the docs / tests / related files”
- no dumping `docs/06-budget-pool-rebalance.md` or other long specs into the worker

If Qwen stalls (~15 min, no file write), cancel. Next: Gemma 4 (`gemma4-coder`) on the same tiny slice. If Gemma fails or corrupts files, cut the slice smaller and go back to Qwen. One helper at a time. Parent orchestrates only — do not do the helper’s work yourself when the user said not to.

Qwen’s hard fail here was **output truncation** (`max_completion_tokens`), not a 128k context miss. Tiny slices keep both input and generation short. Gemma’s fail was over-reading (tens/hundreds of k input). Same rule: do not hand either the repo.

## Other standing constraints

- Do not commit unless asked.
- Do not start or restart `omlx` (`brew services` stays off; user runs `omlx serve` on port 11435). Do not start Ollama.
- Detached uvicorn only — not launchd/systemd. Do not auto-restart it unless asked.
- No React, auth, live FX, or a second frontend.
