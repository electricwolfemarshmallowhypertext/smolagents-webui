import re
from pathlib import Path


PROJECT_ROOT = Path.cwd()
INDEX_HTML = PROJECT_ROOT / "src" / "smolagents_webui" / "static" / "index.html"
APP_JS = PROJECT_ROOT / "src" / "smolagents_webui" / "static" / "app.js"
STYLES_CSS = PROJECT_ROOT / "src" / "smolagents_webui" / "static" / "styles.css"


def test_default_theme_is_dark_in_html():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert '<body data-theme="dark"' in html


def test_theme_selector_has_exact_supported_values():
    html = INDEX_HTML.read_text(encoding="utf-8")
    match = re.search(r'<select id="theme-select".*?>(.*?)</select>', html, flags=re.DOTALL)
    assert match is not None
    values = re.findall(r'value="([^"]+)"', match.group(1))
    assert values == ["dark", "light", "modern-tech"]


def test_css_theme_blocks_match_supported_values():
    styles = STYLES_CSS.read_text(encoding="utf-8")
    blocks = re.findall(r'body\[data-theme="([^"]+)"\]\s*\{', styles)
    unique_blocks = sorted(set(blocks))
    assert unique_blocks == ["dark", "light", "modern-tech"]


def test_js_enforces_allowed_themes_and_dark_fallback():
    source = APP_JS.read_text(encoding="utf-8")
    assert 'const ALLOWED_THEMES = ["dark", "light", "modern-tech"];' in source
    assert 'return ALLOWED_THEMES.includes(candidate) ? candidate : "dark";' in source
    assert "const stored = localStorage.getItem(THEME_STORAGE_KEY);" in source
    assert "applyTheme(stored);" in source


def test_modern_tech_theme_selector_exists_in_css():
    styles = STYLES_CSS.read_text(encoding="utf-8")
    assert 'body[data-theme="modern-tech"]' in styles


def _theme_block(styles: str, theme: str) -> str:
    pattern = rf'body\[data-theme="{re.escape(theme)}"\]\s*\{{(.*?)\n\}}'
    match = re.search(pattern, styles, flags=re.DOTALL)
    assert match is not None
    return match.group(1)


def test_theme_font_contract_is_enforced():
    styles = STYLES_CSS.read_text(encoding="utf-8")
    dm_mono_stack = '"DM Mono", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace'
    dm_sans_stack = '"DM Sans", Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'

    dark_block = _theme_block(styles, "dark")
    light_block = _theme_block(styles, "light")
    modern_block = _theme_block(styles, "modern-tech")

    assert f"--font-ui: {dm_mono_stack};" in dark_block
    assert f"--font-ui: {dm_mono_stack};" in light_block
    assert f"--font-ui: {dm_sans_stack};" in modern_block

    assert f"--font-code: {dm_mono_stack};" in dark_block
    assert f"--font-code: {dm_mono_stack};" in light_block
    assert f"--font-code: {dm_mono_stack};" in modern_block


def test_code_elements_use_code_font_variable():
    styles = STYLES_CSS.read_text(encoding="utf-8")
    assert "pre," in styles
    assert "code," in styles
    assert ".output-block," in styles
    assert "font-family: var(--font-code);" in styles

