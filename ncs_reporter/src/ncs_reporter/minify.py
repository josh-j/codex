"""Minification helpers for self-contained HTML reports, backed by minify-html."""

from __future__ import annotations

import minify_html


def minify_html_doc(html: str) -> str:
    """Minify a complete HTML document."""
    return minify_html.minify(  # type: ignore[no-any-return]
        html,
        minify_css=True,
        minify_js=True,
        remove_processing_instructions=True,
    )


def minify_css(css: str) -> str:
    """Minify a standalone CSS fragment."""
    return minify_html.minify(  # type: ignore[no-any-return]
        f"<style>{css}</style>",
        minify_css=True,
    )[7:-8]  # strip <style>...</style> wrapper


def minify_js(js: str) -> str:
    """Minify a standalone JS fragment."""
    return minify_html.minify(  # type: ignore[no-any-return]
        f"<script>{js}</script>",
        minify_css=False,
        minify_js=True,
    )[8:-9]  # strip <script>...</script> wrapper
