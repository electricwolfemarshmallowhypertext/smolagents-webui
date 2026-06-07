# Manual Theme Verification Checklist

Use this checklist to produce missing UI screenshot receipts:

- `docs/receipts/theme-dark.png`
- `docs/receipts/theme-light.png`
- `docs/receipts/theme-modern-tech.png`

## Setup

1. Start app:
   - `PYTHONPATH=src python -m smolagents_webui.server --host 127.0.0.1 --port 7865 --workspace-root .`
2. Open:
   - `http://127.0.0.1:7865`

## Theme Checks (run for each: `dark`, `light`, `modern-tech`)

1. Select theme from header selector.
2. Hard refresh page.
3. Confirm selected theme persists.
4. Confirm session list text, borders, and active state are readable.
5. Confirm run panel text/input controls are readable.
6. Confirm live run pill is readable.
7. Confirm streaming/event/tool/code/final/error cards are readable.
8. Confirm workspace tree, recent files, and state viewer are readable.
9. On mobile width, confirm `Sessions / Run / Workspace` tabs still switch panels and remain readable.
10. Capture screenshot and save using exact filename for current theme.

## Expected Contract

- Default first load without stored value: `dark`
- Allowed values only: `dark`, `light`, `modern-tech`
- Invalid stored value fallback: `dark`
- Switching themes is instant and does not reload the page
