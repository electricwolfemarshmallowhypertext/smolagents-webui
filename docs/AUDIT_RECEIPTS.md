# Audit Receipts

## Easy-Wins Hardening Pass

| Issue / Gap | Fix Applied | Receipt / Proof |
|---|---|---|
| `.smolagents-webui/` runtime data could be committed accidentally. | Added `.smolagents-webui/` to ignore list. | File changed: `.gitignore`.<br>Command: `git check-ignore -v .smolagents-webui\\sessions.json`.<br>Result: `.gitignore:155:.smolagents-webui/ " .smolagents-webui\\sessions.json"`. |
| Duplicate run submissions could start overlapping runs. | Added run lock state in frontend submit flow and disabled submit button while a run is active. | File changed: `src/smolagents_webui/static/app.js` (`state.runLocked`, `setRunLock`, early return in `submitRun`).<br>Runtime smoke: `RUN_SUBMIT_RESULTS=[["first",202,null],["second",409,"A run is already active for this session."]]`.<br>Result: `DUPLICATE_BLOCKED=True`. |
| Session list refresh could churn heavily during SSE updates. | Added throttled `loadSessions()` with deferred scheduling (`SESSION_REFRESH_MIN_INTERVAL_MS`). | File changed: `src/smolagents_webui/static/app.js` (`loadSessions`, `scheduleLoadSessions`).<br>Command: `node --check src/smolagents_webui/static/app.js`.<br>Result: pass (exit 0). |
| Store wrote `sessions.json` on every mutation/event. | Added debounced persistence with `threading.Timer` and flush on `close()`. | File changed: `src/smolagents_webui/store.py` (`persist_debounce_seconds`, `_schedule_persist_locked`, `_flush_persist_from_timer`, `close`).<br>Test: `test_store_event_pagination_and_close_flush` in `tests/webui/test_store.py`.<br>Command: `python -m pytest tests/webui -q --noconftest -p no:cacheprovider`.<br>Result: `15 passed in 0.33s`. |
| Event history could grow without bound in memory/disk. | Added per-session event cap with oldest-event trimming. | File changed: `src/smolagents_webui/store.py` (`max_events_per_session`, trim logic in `_load` and `append_event`).<br>Test: `test_store_caps_event_history_per_session` in `tests/webui/test_store.py`.<br>Result: pytest pass (`15 passed`). |
| Very long runs could degrade frontend performance due to unbounded cards. | Added rendered-card cap and pruning logic. | File changed: `src/smolagents_webui/static/app.js` (`MAX_RENDERED_CARDS`, `enforceRenderedCardLimit`).<br>Command: `node --check src/smolagents_webui/static/app.js`.<br>Result: pass. |
| SSE reconnect behavior had no backoff strategy. | Added reconnect with exponential backoff + jitter. | File changed: `src/smolagents_webui/static/app.js` (`SSE_BASE_RETRY_MS`, `SSE_MAX_RETRY_MS`, `scheduleStreamReconnect`).<br>Command: `node --check src/smolagents_webui/static/app.js`.<br>Result: pass. |
| Workspace tree/recent endpoints could rescan repeatedly under rapid refresh. | Added short TTL cache for tree/recent responses. | File changed: `src/smolagents_webui/workspace.py` (`_cache_ttl_seconds`, `_get_cached`, `_set_cached`).<br>Command: `python -m py_compile src/smolagents_webui/workspace.py`.<br>Result: pass (exit 0). |
| Recent-files scan could traverse too much before returning useful results. | Added heap-based top-N collection and early cutoff once enough results exist. | File changed: `src/smolagents_webui/workspace.py` (`heapq`, `early_cutoff`, bounded ranking).<br>Test coverage: `test_workspace_recent_files_returns_items` in `tests/webui/test_workspace.py`.<br>Result: pytest pass (`15 passed`). |
| Historical event loading pulled only the latest slice with no incremental older fetch. | Added low-risk pagination path for older events and frontend lazy load button. | Files changed: `src/smolagents_webui/server.py` (`before` query handling), `src/smolagents_webui/store.py` (`get_events_before`, `_slice_events`), `src/smolagents_webui/static/app.js` (`loadOlderEvents`, history controls).<br>Test: `test_store_event_pagination_and_close_flush`.<br>Result: pytest pass (`15 passed`). |
| Verbose reasoning cards were noisy on mobile screens. | Hide verbose reasoning card bodies by default on small screens. | File changed: `src/smolagents_webui/static/styles.css` (`@media (max-width: 960px) .chat-card.reasoning.verbose .chat-card-body { display: none; }`).<br>Command: `node --check src/smolagents_webui/static/app.js` + manual CSS selector verification.<br>Result: syntax pass; selector present. |
| Motion preferences were not respected. | Added `prefers-reduced-motion` override to disable animations/transitions. | File changed: `src/smolagents_webui/static/styles.css` (`@media (prefers-reduced-motion: reduce)`).<br>Command: static CSS verification + frontend syntax check.<br>Result: selector present; `node --check` pass. |

## Verification Commands Run

```bash
node --check src/smolagents_webui/static/app.js
python -m py_compile src/smolagents_webui/server.py src/smolagents_webui/runner.py src/smolagents_webui/model_factory.py src/smolagents_webui/store.py src/smolagents_webui/workspace.py
python -m pytest tests/webui -q --noconftest -p no:cacheprovider
```

## Exact Verification Results

- `node --check src/smolagents_webui/static/app.js`: pass (exit 0)
- `python -m py_compile ...`: pass (exit 0)
- `python -m pytest tests/webui -q --noconftest -p no:cacheprovider`: `15 passed in 0.33s`

## Runtime Smoke

Command: local server smoke script (`python -m smolagents_webui.server` with temporary data dir) checked:

- `/api/health`
- `/api/workspace/tree?depth=1`
- `/api/workspace/recent?limit=5`
- `/`
- duplicate run-submit prevention

Exact output:

```text
HEALTH_STATUS=ok
TREE_KIND=directory
RECENT_COUNT=5
MAIN_STATUS=200
SESSION_CREATE_STATUS=201
RUN_SUBMIT_RESULTS=[["first", 202, null], ["second", 409, "A run is already active for this session."]]
DUPLICATE_BLOCKED=True
```

## Missing Receipts

- None for this hardening pass.

## Visual Redesign Pass

| Issue / Gap | Fix Applied | Receipt / Proof |
|---|---|---|
| Typography was too small and low-contrast for sustained reading. | Raised base typography and rebalanced code/meta scales (`14px` body, `13px` code, `12px` metadata) with clearer spacing and line-height. | Files changed: `src/smolagents_webui/static/styles.css`.<br>Selectors: `html, body`, `.detail-inline`, `.chat-card-meta`, `.session-item-meta`, `.recent-file-meta`.<br>Command: `node --check src/smolagents_webui/static/app.js`.<br>Result: pass (exit 0). |
| Theme proof was incomplete for the required three-theme contract. | Captured dedicated screenshots for `dark`, `light`, and `modern-tech` after redesign and verified live switch behavior without reload. | Screenshots: `docs/receipts/theme-dark.png`, `docs/receipts/theme-light.png`, `docs/receipts/theme-modern-tech.png`.<br>Manual smoke: step 2 and step 14 passed in `docs/receipts/manual-smoke-report.json`. |
| Three-panel proportions did not give enough room to center timeline/right context panel. | Applied explicit panel clamps and responsive breakpoints with center `minmax(0, 1fr)`. | Files changed: `src/smolagents_webui/static/styles.css`.<br>Selectors: `.app-shell`, `@media (max-width: 1440px)`, `@media (max-width: 960px)`.<br>Runtime proof: manual smoke step 11 + 12 passed in `docs/receipts/manual-smoke-report.json`. |
| Center panel looked like a raw log stream with weak hierarchy. | Reworked card structure into timeline-style cards with compact header, badges, metadata row, and collapsible details. | Files changed: `src/smolagents_webui/static/index.html`, `src/smolagents_webui/static/app.js`, `src/smolagents_webui/static/styles.css`.<br>Code points: `.chat-card-header`, `.chat-card-badges`, `applyCardMetadata`, `appendTextSection`.<br>Manual smoke: step 7 passed (`stream_event_badges=['action']`). |
| Right panel state view was a raw wall of text. | Replaced raw pre-dump rendering with sectioned state cards and collapsible details for large values. | Files changed: `src/smolagents_webui/static/index.html`, `src/smolagents_webui/static/app.js`, `src/smolagents_webui/static/styles.css`.<br>Code points: `renderAgentState`, `buildStateSection`, `.state-section`, `.state-details`.<br>Manual smoke: step 10 passed (`tree_items=77`, `recent_items=20`). |
| Step metadata was inconsistent across event cards. | Added automatic step badge inference from `payload.step_number` and consistent status/type badge rendering. | File changed: `src/smolagents_webui/static/app.js`.<br>Code points: `applyCardMetadata`, `eventStatus`, `humanizeEventType`.<br>Command: `node --check src/smolagents_webui/static/app.js` pass. |
| Older-events smoke validation could not deterministically target a long-history session in UI. | Added `data-session-id` attribute to session rows so verification can select a known session reliably. | File changed: `src/smolagents_webui/static/app.js` (`button.dataset.sessionId = session.id`).<br>Manual smoke step 9 now passes: `button_visible=True, cards_before=7, cards_after=9, seed_selected=True` in `docs/receipts/manual-smoke-report.json`. |
| Manual smoke receipt was stale and contained outdated failing state. | Re-ran full 14-step browser smoke and overwrote receipt JSON; regenerated desktop/mobile screenshots. | Files updated: `docs/receipts/manual-smoke-report.json`, `docs/receipts/manual-smoke-desktop.png`, `docs/receipts/manual-smoke-mobile.png`.<br>Result: `\"all_passed\": true` with steps 1-14 all `ok=true`. |

### Visual Pass Verification Commands

```bash
node --check src/smolagents_webui/static/app.js
python -m py_compile src/smolagents_webui/server.py src/smolagents_webui/runner.py src/smolagents_webui/model_factory.py src/smolagents_webui/store.py src/smolagents_webui/workspace.py
python -m pytest tests/webui -q --noconftest -p no:cacheprovider
```

### Visual Pass Command Results

- `node --check src/smolagents_webui/static/app.js`: pass (exit 0)
- `python -m py_compile ...`: pass (exit 0)
- `python -m pytest tests/webui -q --noconftest -p no:cacheprovider`: `15 passed in 0.48s`

### Visual Smoke Receipt

- `docs/receipts/manual-smoke-report.json`: `all_passed=true`
- `docs/receipts/manual-smoke-desktop.png`
- `docs/receipts/manual-smoke-mobile.png`

## Typography/Theme Identity Pass

| Issue / Gap | Fix Applied | Receipt / Proof |
|---|---|---|
| Themes differed mostly by color and lacked typographic identity. | Added explicit theme font contract with `--font-ui` / `--font-code` mapped per theme: dark+light UI use DM Mono, modern-tech UI uses DM Sans, code surfaces use DM Mono across all themes. | Files changed: `src/smolagents_webui/static/index.html`, `src/smolagents_webui/static/styles.css`.<br>Proof selectors: `body[data-theme="dark"]`, `body[data-theme="light"]`, `body[data-theme="modern-tech"]` font variable assignments.<br>Test: `tests/webui/test_theme_contract.py::test_theme_font_contract_is_enforced` passed. |
| Font usage contract was not enforced for UI vs code surfaces. | Applied `var(--font-ui)` to UI chrome and controls; applied `var(--font-code)` to `pre`, `code`, output/tool raw blocks. | File changed: `src/smolagents_webui/static/styles.css`.<br>Test: `tests/webui/test_theme_contract.py::test_code_elements_use_code_font_variable` passed.<br>Command: `python -m pytest tests/webui -q --noconftest -p no:cacheprovider` → `18 passed in 0.47s`. |
| Modern-tech did not have enough structural distinction from dark/light. | Added tokenized structural overrides in modern-tech (`--radius`, `--radius-lg`, `--panel-padding`, `--card-padding`, `--control-height`, `--shadow-soft`, `--surface-elevated`) and theme-specific card/panel/button treatment for SaaS/devtool feel. | File changed: `src/smolagents_webui/static/styles.css`.<br>Proof selectors: modern-tech token block + modern-tech-specific rules for headers/cards/controls/badges.<br>Screenshots: `docs/receipts/theme-dark.png`, `docs/receipts/theme-light.png`, `docs/receipts/theme-modern-tech.png`. |
| Theme contract did not explicitly assert exactly three supported theme blocks in CSS. | Added contract test to verify CSS theme blocks are exactly `dark`, `light`, `modern-tech`. | File changed: `tests/webui/test_theme_contract.py`.<br>Test: `test_css_theme_blocks_match_supported_values` passed. |
| Concern: runtime could include hard-coded fake data. | Verified no fake/mock/sample data paths were introduced in runtime application source under `src/smolagents_webui`. | Command: `rg -n "seed|fake|mock|dummy|sample" src/smolagents_webui tests/webui -S`.<br>Result: hits only in test doubles under `tests/webui/test_model_factory.py`; no hits in runtime source files. |

## Clean Runtime Behavior Pass

| Issue / Gap | Fix Applied | Receipt / Proof |
|---|---|---|
| Repo-root runs could surface persisted smoke/runtime data as real app history. | Added ignore coverage for `.manual-smoke-data/`, `.manual-smoke.pid`, `.runtime-smoke-data/`, `.shutdown-smoke-data*/`, and `smolui-smoke-*/` alongside existing `.smolagents-webui/`. | File changed: `.gitignore`.<br>Command: `git check-ignore -v .smolagents-webui/sessions.json .manual-smoke-data/sessions.json .runtime-smoke-data/sessions.json .shutdown-smoke-data2/sessions.json smolui-smoke-test/sessions.json`.<br>Result: all five required paths matched ignore rules. |
| First app run created a fake-looking default session. | Removed automatic `Main Session` creation from server startup; sessions are now created only through the `/api/sessions` user action path. | File changed: `src/smolagents_webui/server.py`.<br>Command: `rg -n "Main Session|create_session\\(" src/smolagents_webui/server.py src/smolagents_webui/static/app.js -S`.<br>Result: only the POST `/api/sessions` route calls `create_session`. |
| Empty app states were not explicit enough for first user run. | Added honest frontend empty states: `No sessions yet`, `No run selected`, `Workspace is empty`, and `Agent state will appear after a run`. | Files changed: `src/smolagents_webui/static/app.js`, `src/smolagents_webui/static/styles.css`.<br>Command: `node --check src/smolagents_webui/static/app.js`.<br>Result: pass (exit 0). |
| Workspace browser could show smoke/dev folders when pointed at repo root. | Filtered runtime/smoke folders from workspace tree and recent-files scans. | File changed: `src/smolagents_webui/workspace.py`.<br>Test added: `tests/webui/test_workspace.py::test_workspace_hides_runtime_and_smoke_directories`.<br>Result: pytest pass (`19 passed in 0.58s`). |
| README did not steer users away from repo-root runtime. | Added clean runtime guidance recommending a dedicated workspace directory and separate data directory. | File changed: `README.md`.<br>Section: `Clean Runtime`.<br>Verification: README contains dedicated `--workspace-root` and `--data-dir` example. |
| Runtime source needed proof that fake/demo/seed text was not present. | Removed runtime placeholder attributes and verified strict runtime grep. | Command: `rg -n "fake|mock|dummy|sample|demo|placeholder|seed|lorem" src/smolagents_webui -S`.<br>Result: no matches (exit 1, empty output). |

### Clean Runtime Verification Results

- `rg -n "fake|mock|dummy|sample|demo|placeholder|seed|lorem" src/smolagents_webui -S`: no matches
- `node --check src/smolagents_webui/static/app.js`: pass (exit 0)
- `python -m py_compile src/smolagents_webui/server.py src/smolagents_webui/runner.py src/smolagents_webui/model_factory.py src/smolagents_webui/store.py src/smolagents_webui/workspace.py`: pass (exit 0)
- `python -m pytest tests/webui -q --noconftest -p no:cacheprovider`: `19 passed in 0.58s`

## Full Function Audit Fix Pass

| Issue / Gap | Fix Applied | Receipt / Proof |
|---|---|---|
| Default session persistence still lived under the browsed workspace, so repo-root launches could load stale smoke sessions. | Changed default persistence to the user app data directory; explicit `--data-dir` still works. | File changed: `src/smolagents_webui/server.py` (`default_data_dir`).<br>Test added: `tests/webui/test_server.py::test_default_data_dir_is_not_workspace_runtime_dir`.<br>Command: `python -m pytest tests/webui/test_server.py -q --noconftest -p no:cacheprovider`.<br>Result: `2 passed in 0.02s`. |
| Mobile/tablet composer could keep the Run button below the scrollable config block. | Moved the Run button to visual row 2 and config grid to row 3 so the prompt/action stays reachable before long config. | File changed: `src/smolagents_webui/static/styles.css`.<br>Test updated: `tests/webui/test_layout_contract.py::test_composer_is_bounded_and_scrollable`.<br>Browser smoke: `composerVisible=true`, `runButtonVisible=true`, `timelineUsable=true`. |
| Mobile session creation/selection could leave users on the Sessions tab instead of returning to the Run panel. | After successful session load, call `setMobilePanel("run")`. | File changed: `src/smolagents_webui/static/app.js`.<br>Test added: `tests/webui/test_layout_contract.py::test_session_selection_returns_mobile_users_to_run_panel`.<br>Browser smoke: after tapping `New`, `mobilePanel="run"`. |
| Workspace tree/recent failure paths only logged to console and could leave stale or blank right-panel UI. | Added visible bounded error states for workspace tree and recent-files failures/malformed tree payloads. | File changed: `src/smolagents_webui/static/app.js`.<br>Test added: `tests/webui/test_layout_contract.py::test_workspace_failures_render_visible_states`.<br>Command: `node --check src/smolagents_webui/static/app.js`.<br>Result: pass (exit 0). |
| Unreadable workspace directories could crash `/api/workspace/tree` and disconnect the client. | `WorkspaceBrowser._build_node()` now returns an error-marked node for unreadable paths/directories instead of throwing. | File changed: `src/smolagents_webui/workspace.py`.<br>Test added: `tests/webui/test_workspace.py::test_workspace_tree_handles_unreadable_directories`.<br>Command: `python -m pytest tests/webui/test_workspace.py -q --noconftest -p no:cacheprovider`.<br>Result: `5 passed in 0.04s`. |
| Windows SSE/client disconnects could print server tracebacks. | Added `ConnectionAbortedError` handling in SSE write loop and server-level `handle_error()` for pre-handler aborts; other exceptions still use default handling. | File changed: `src/smolagents_webui/server.py`.<br>Test added: `tests/webui/test_server.py::test_server_handles_windows_client_abort_without_traceback`.<br>Command: `python -m py_compile src/smolagents_webui/server.py` and `python -m pytest tests/webui/test_server.py -q --noconftest -p no:cacheprovider`.<br>Result: compile pass; `2 passed in 0.02s`. |
| Verification-created smoke/temp folders were not fully ignored. | Added `smolui-empty-*/` and `pytest-cache-files-*/` ignore coverage. | File changed: `.gitignore`.<br>Command: `git check-ignore -v .smolagents-webui/sessions.json .manual-smoke-data/sessions.json .runtime-smoke-data/sessions.json .shutdown-smoke-data2/sessions.json smolui-smoke-test/sessions.json smolui-empty-test/sessions.json pytest-cache-files-test/cache.db`.<br>Result: all paths matched ignore rules. |
| Prior manual smoke could be confused by stale port/data and did not prove clean first-run UI. | Ran isolated browser smoke with unique ignored workspace/data dirs and dynamic port. | Runtime smoke command: in-process `SmolagentsWebUIServer` + Playwright Chromium against `.runtime-smoke-data/browser-workspace-*` and `.runtime-smoke-data/browser-data-*`.<br>Result: `/api/health={"status":"ok"}`, `/api/sessions={"sessions":[]}`, `/api/workspace/tree?depth=1` returned empty directory JSON, `/api/workspace/recent?limit=5={"files":[]}`.<br>Browser result: `theme_sequence=["light","modern-tech","dark"]`, `run_posts_observed=1`, `bodyNoScroll=true`, `composerVisible=true`, `runButtonVisible=true`, `visible_tabs={"sessions":true,"run":true,"workspace":true}`, `persisted_theme_after_reload="dark"`. |

### Full Function Audit Verification Results

- `rg -n "fake|mock|dummy|sample|demo|placeholder|seed|lorem" src/smolagents_webui -S`: no matches
- `node --check src/smolagents_webui/static/app.js`: pass (exit 0)
- `python -m py_compile src/smolagents_webui/server.py src/smolagents_webui/runner.py src/smolagents_webui/model_factory.py src/smolagents_webui/store.py src/smolagents_webui/workspace.py`: pass (exit 0)
- `python -m pytest tests/webui -q --noconftest -p no:cacheprovider`: `28 passed in 0.43s`

## Real smolagents End-to-End Acceptance

| Issue / Gap | Fix Applied | Receipt / Proof |
|---|---|---|
| UI-only smoke did not prove real smolagents execution. | Ran a real WebUI server API flow: create session, submit run, instantiate `CodeAgent`, create selected model adapter, stream events, complete `agent.run(prompt)`, persist history. | Model class: `smolagents.OpenAIModel`.<br>Provider/backend: Ollama OpenAI-compatible API.<br>Model ID: `qwen2.5-coder:7b`.<br>API base: `http://127.0.0.1:11434/v1`.<br>Session: `98f7698574ea47ce998c58247db83994`.<br>Result: `codeagent_run_completed=true`, `final_answer="SMOL_UI_REAL_RUN_OK"`, `history_persisted=true`, `provider_error=null`. |
| Acceptance needed proof of streaming, not just final response. | Verified persisted streamed event sequence from the real run. | Event types observed: `run_started`, `assistant_delta`, `tool_call`, `action_step`, `final_answer_step`, `run_completed`.<br>Event count: `81`.<br>Sessions file: `.runtime-smoke-data/real-api-data-36d89651d92e4ad3b72c33cf84fb9977/sessions.json`. |
| HF Inference failure could be mistaken as the only supported path. | Verified a non-HF backend path using smolagents' OpenAI-compatible model adapter with local Ollama. | Official smolagents docs confirm supported model types include `InferenceClientModel`, `TransformersModel`, `VLLMModel`, `MLXModel`, `LiteLLMModel`, `LiteLLMRouterModel`, and `OpenAIModel`.<br>Runtime proof used `OpenAIModel` with Ollama, no HF auth required. |

## Packaging Fix Pass

| Issue / Gap | Fix Applied | Receipt / Proof |
|---|---|---|
| Build artifacts were still packaged as upstream `smolagents`. | Changed project metadata to `smolagents-webui` version `0.1.0`; dependency is `smolagents`; CLI remains `smolagents-webui`. | File changed: `pyproject.toml`.<br>Build command: `python -m build --no-isolation`.<br>Result: `Successfully built smolagents_webui-0.1.0.tar.gz and smolagents_webui-0.1.0-py3-none-any.whl`. |
| Wheel package discovery excluded the UI package because `exclude = ["smolagents*"]` also matched `smolagents_webui`. | Narrowed package exclude to `smolagents` and `smolagents.*`; added `package-dir = { "" = "src" }`. | Files changed: `pyproject.toml`, `MANIFEST.in`.<br>Check: `find_packages('src', include=['smolagents_webui*'], exclude=['smolagents','smolagents.*'])`.<br>Result: `['smolagents_webui']`. |
| Source distribution could include upstream tests/source or omit UI Python modules. | Added `MANIFEST.in` to include `src/smolagents_webui/*.py`, static assets, receipts, and prune upstream `src/smolagents`, root `tests`, `examples`, and upstream docs source. | File changed: `MANIFEST.in`.<br>Artifact inspection: sdist `has_src_smolagents_webui=True`, `has_src_smolagents=False`, `has_root_tests=False`. |
| Wheel needed proof that it installs the UI package, not upstream smolagents. | Installed built wheel into ignored target with `--no-deps` and imported package/entry point metadata. | Command: `python -m pip install --no-deps --target .runtime-smoke-data/pkg-install-target dist/smolagents_webui-0.1.0-py3-none-any.whl`.<br>Result: `Successfully installed smolagents-webui-0.1.0`.<br>Import proof: `distribution=smolagents-webui`, `version=0.1.0`, `cli=smolagents_webui.server:main`, `server_main=main`. |
| Normal verification still needed after packaging metadata changes. | Re-ran syntax/compile/tests. | Commands: `node --check src/smolagents_webui/static/app.js`; `python -m py_compile src/smolagents_webui/server.py src/smolagents_webui/runner.py src/smolagents_webui/model_factory.py src/smolagents_webui/store.py src/smolagents_webui/workspace.py`; `python -m pytest tests/webui -q --noconftest -p no:cacheprovider`.<br>Results: frontend syntax pass; Python compile pass; `28 passed in 0.42s`. |
