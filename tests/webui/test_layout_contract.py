from pathlib import Path


PROJECT_ROOT = Path.cwd()
STYLES_CSS = PROJECT_ROOT / "src" / "smolagents_webui" / "static" / "styles.css"
APP_JS = PROJECT_ROOT / "src" / "smolagents_webui" / "static" / "app.js"


def test_viewport_layout_is_contained():
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert "height: 100%;" in styles
    assert "height: 100dvh;" in styles
    assert "max-height: 100dvh;" in styles
    assert "overflow: hidden;" in styles
    assert "grid-template-rows: auto auto minmax(0, 1fr);" in styles
    assert ".app-shell {" in styles
    assert "height: 100%;" in styles
    assert "max-height: 100%;" in styles


def test_panel_content_scrolls_internally():
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert ".panel {" in styles
    assert ".session-list {" in styles
    assert ".chat-feed {" in styles
    assert ".workspace-tree," in styles
    assert ".state-viewer {" in styles
    assert "flex: 1 1 auto;" in styles
    assert "flex: 0 0 auto;" in styles


def test_composer_is_bounded_and_scrollable():
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert ".run-form {" in styles
    assert "max-height: min(46dvh, 420px);" in styles
    assert "overflow: auto;" in styles
    assert "#run-btn {\n  grid-row: 2;" in styles
    assert ".config-grid {\n  grid-row: 3;" in styles
    assert "max-height: min(42dvh, 320px);" in styles


def test_tablet_width_uses_one_panel_tabs():
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert "@media (max-width: 1180px)" in styles
    assert ".mobile-nav {\n    display: flex;" in styles
    assert ".panel[data-panel] {\n    display: none;" in styles
    assert 'body[data-mobile-panel="run"] .panel[data-panel="run"]' in styles


def test_session_selection_returns_mobile_users_to_run_panel():
    source = APP_JS.read_text(encoding="utf-8")

    assert 'setMobilePanel("run");' in source


def test_workspace_failures_render_visible_states():
    source = APP_JS.read_text(encoding="utf-8")

    assert "Workspace unavailable" in source
    assert "Recent files unavailable" in source
