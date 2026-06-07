# Verification Log

Version: `v0.1.0`

Last verified: `2026-06-07`

This log records release-readiness checks for the standalone `smolagents-webui` package. Screenshots and receipt files are verification artifacts for this version and should be refreshed when UI behavior or visual output changes.

## Release Verification Summary

| Area | Verification | Result |
|---|---|---|
| Package identity | Project metadata builds `smolagents-webui` version `0.1.0`; CLI entry point is `smolagents-webui = smolagents_webui.server:main`. | Pass |
| Dependency boundary | `smolagents` is an external dependency and upstream source is not bundled. | Pass |
| Package contents | Wheel contains `smolagents_webui`; wheel does not contain upstream `smolagents`; sdist does not contain `docs/source`; `NOTICE` is included. | Pass |
| Runtime execution | A real `smolagents.CodeAgent` run completed through the WebUI API using `smolagents.OpenAIModel` against an Ollama OpenAI-compatible endpoint. | Pass |
| Event streaming | Run events included `run_started`, `assistant_delta`, `tool_call`, `action_step`, `final_answer_step`, and `run_completed`. | Pass |
| Persistence | Session history persisted after a completed run. | Pass |
| Secret handling | API keys and token-like values are redacted before event storage, session persistence, and stream replay. | Pass |
| Run concurrency | Concurrent run-start requests for the same session allow one start and reject the other with conflict status. | Pass |
| Cancellation | Active runs can be marked for cancellation; history records `run_cancelled`; session state returns to idle. | Pass |
| History management | Sessions can be deleted individually or cleared in bulk. | Pass |
| Corrupt history handling | Corrupt session history is backed up and a storage warning is exposed through health state. | Pass |
| Session cap | Session storage is capped at 200 sessions and preserves currently running sessions. | Pass |
| Theme contract | Supported themes are `dark`, `light`, and `modern-tech`; theme selection persists across reload. | Pass |
| Layout contract | Desktop and mobile panel layouts remain bounded and internally scrollable. | Pass |
| Workspace browser | Workspace tree and recent-file views handle unavailable paths and ignore local runtime directories. | Pass |

## Verification Commands

```bash
node --check src/smolagents_webui/static/app.js
python -m py_compile src/smolagents_webui/server.py src/smolagents_webui/runner.py src/smolagents_webui/model_factory.py src/smolagents_webui/store.py src/smolagents_webui/workspace.py src/smolagents_webui/serialization.py
python -m pytest tests/webui -q --noconftest -p no:cacheprovider
python -m build
```

## Receipt Files

- `docs/receipts/theme-dark.png`
- `docs/receipts/theme-light.png`
- `docs/receipts/theme-modern-tech.png`
- `docs/receipts/verification-desktop.png`
- `docs/receipts/verification-mobile.png`
- `docs/receipts/verification-report.json`
