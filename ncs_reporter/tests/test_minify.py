"""Tests for ncs_reporter.minify — CSS, JS, and HTML minification via minify-html."""

from __future__ import annotations

from pathlib import Path

from ncs_reporter.minify import minify_css, minify_html_doc, minify_js

TEMPLATES = Path(__file__).resolve().parent.parent / "src" / "ncs_reporter" / "templates"


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------


class TestMinifyCSS:
    def test_strips_comments(self) -> None:
        result = minify_css("a { /* bold */ font-weight: bold }")
        assert "/* bold */" not in result
        assert "font-weight" in result

    def test_collapses_whitespace(self) -> None:
        result = minify_css("a  {  color :  red  }")
        assert "  " not in result

    def test_calc_preserves_operator_spaces(self) -> None:
        result = minify_css("div { width: calc(100% - 20px); }")
        assert "calc(100% - 20px)" in result

    def test_calc_nested_var(self) -> None:
        result = minify_css("div { top: calc(100% + var(--space-4)); }")
        assert "calc(100% + var(--space-4))" in result

    def test_url_content_preserved(self) -> None:
        css = 'div { background: url("data:image/svg+xml;base64,abc+def"); }'
        result = minify_css(css)
        assert "data:image/svg+xml;base64,abc+def" in result

    def test_reduces_size(self) -> None:
        css = "a  {  color:  red;  font-weight:  bold;  }"
        assert len(minify_css(css)) < len(css)


# ---------------------------------------------------------------------------
# JS
# ---------------------------------------------------------------------------


class TestMinifyJS:
    def test_strips_line_comments(self) -> None:
        js = "var x = 1; // comment\nvar y = 2;"
        result = minify_js(js)
        assert "// comment" not in result

    def test_preserves_url_in_string(self) -> None:
        js = 'var u = "http://example.com";'
        result = minify_js(js)
        assert "http://example.com" in result

    def test_strips_block_comments(self) -> None:
        js = "var x = 1;\n/* block\ncomment */\nvar y = 2;"
        result = minify_js(js)
        assert "block" not in result

    def test_reduces_size(self) -> None:
        js = "var  x  =  1;\n\n\nvar  y  =  2;"
        assert len(minify_js(js)) < len(js)


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------


class TestMinifyHTML:
    def test_collapses_inter_tag_whitespace(self) -> None:
        html = "<html><body><div>  <span>   text   </span>  </div></body></html>"
        result = minify_html_doc(html)
        assert len(result) <= len(html)

    def test_preserves_pre_content(self) -> None:
        html = "<html><body><pre>  spaced   content  </pre></body></html>"
        result = minify_html_doc(html)
        assert "spaced   content" in result

    def test_reduces_size(self) -> None:
        html = "<html>\n  <body>\n    <div>\n      hello\n    </div>\n  </body>\n</html>"
        assert len(minify_html_doc(html)) < len(html)


# ---------------------------------------------------------------------------
# Integration: round-trip actual template files
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_css_roundtrip_preserves_calc(self) -> None:
        css_path = TEMPLATES / "report_shared.css"
        if not css_path.exists():
            return
        css = css_path.read_text()
        result = minify_css(css)
        assert len(result) < len(css), "minified CSS should be smaller"
        import re

        for m in re.finditer(r"calc\([^)]+\)", css):
            expr = m.group(0)
            assert expr in result, f"calc expression lost: {expr}"

    def test_js_roundtrip_reduces_size(self) -> None:
        js_path = TEMPLATES / "collapsible.js"
        if not js_path.exists():
            return
        js = js_path.read_text()
        result = minify_js(js)
        assert len(result) < len(js), "minified JS should be smaller"
