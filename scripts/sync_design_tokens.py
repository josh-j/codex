#!/usr/bin/env python3
"""Sync design tokens from design_tokens.yaml to XAML and CSS targets.

Usage:
    python3 scripts/sync_design_tokens.py           # Write generated sections
    python3 scripts/sync_design_tokens.py --check   # Exit 1 if out of sync
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
TOKENS_FILE = REPO_ROOT / "design_tokens.yaml"
XAML_FILE = REPO_ROOT / "ncs-console" / "App" / "MainWindow.Resources.xaml"
CSS_FILE = REPO_ROOT / "ncs-reporter" / "src" / "ncs_reporter" / "templates" / "report_shared.css"

XAML_START = "<!-- @@GENERATED_TOKENS_START@@"
XAML_END = "<!-- @@GENERATED_TOKENS_END@@ -->"
CSS_START = "/* @@GENERATED_TOKENS_START@@"
CSS_END = "/* @@GENERATED_TOKENS_END@@ */"

# Token color name → XAML SolidColorBrush key (only tokens used in XAML)
XAML_COLOR_MAP: dict[str, str] = {
    "surface": "PanelBrush",
    "surface-alt": "SurfaceAltBrush",
    "brand": "AccentBrush",
    "brand-soft": "AccentSoftBrush",
    "warn": "WarnBrush",
    "critical": "DangerBrush",
    "info": "InfoBrush",
    "line": "BorderBrush",
    "text": "TextBrush",
    "text-muted": "TextMutedBrush",
}

# Token font-size name → XAML sys:Double key
XAML_SIZE_MAP: dict[str, str] = {
    "micro": "FontSizeXs",
    "tiny": "FontSizeSm",
    "xs": "FontSizeMd",
    "sm": "FontSizeLg",
    "md": "FontSizeXl",
    "base": "FontSizeTitle",
}

# Token font key → (XAML key, WPF font family name)
XAML_FONT_MAP: dict[str, tuple[str, str]] = {
    "font-sans": ("FontUI", "Segoe UI"),
    "font-mono": ("FontMono", "Consolas"),
}


def load_tokens() -> dict:
    with open(TOKENS_FILE) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# XAML generation
# ---------------------------------------------------------------------------

def generate_xaml(tokens: dict) -> str:
    indent = "        "
    lines: list[str] = []

    for token_name, xaml_key in XAML_COLOR_MAP.items():
        color = tokens["colors"][token_name]
        lines.append(f'{indent}<SolidColorBrush x:Key="{xaml_key}" Color="{color}" />')

    lines.append("")
    for name, value in tokens["radii"].items():
        key = f"Radius{name.capitalize()}"
        lines.append(f'{indent}<CornerRadius x:Key="{key}">{value}</CornerRadius>')

    lines.append("")
    for _token_key, (xaml_key, wpf_name) in XAML_FONT_MAP.items():
        lines.append(f'{indent}<FontFamily x:Key="{xaml_key}">{wpf_name}</FontFamily>')

    lines.append("")
    for token_name, xaml_key in XAML_SIZE_MAP.items():
        value = tokens["typography"]["sizes"].get(token_name)
        if value is not None:
            lines.append(f'{indent}<sys:Double x:Key="{xaml_key}">{value}</sys:Double>')

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CSS generation
# ---------------------------------------------------------------------------

def generate_css(tokens: dict) -> str:
    indent = "  "
    lines: list[str] = []

    lines.append(f"{indent}/* Colors (shared) */")
    for name, value in tokens["colors"].items():
        lines.append(f"{indent}--{name}: {value};")

    lines.append("")
    lines.append(f"{indent}/* Radii */")
    for name, value in tokens["radii"].items():
        lines.append(f"{indent}--radius-{name}: {value}px;")

    lines.append("")
    lines.append(f"{indent}/* Typography */")
    for name, value in tokens["typography"]["sizes"].items():
        lines.append(f"{indent}--text-{name}: {value}px;")
    lines.append(f"{indent}--font-sans: {tokens['typography']['font-sans']};")
    lines.append(f"{indent}--font-mono: {tokens['typography']['font-mono']};")

    lines.append("")
    lines.append(f"{indent}/* Spacing */")
    for name, value in tokens["spacing"].items():
        lines.append(f"{indent}--space-{name}: {value}px;")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Marker replacement
# ---------------------------------------------------------------------------

def replace_between_markers(content: str, start_marker: str, end_marker: str, generated: str) -> str:
    file_lines = content.split("\n")
    start_idx: int | None = None
    end_idx: int | None = None
    for i, line in enumerate(file_lines):
        if start_idx is None:
            if start_marker in line:
                start_idx = i
        elif end_marker in line:
            end_idx = i
            break
    if start_idx is None or end_idx is None:
        raise ValueError(f"Markers not found (start={start_marker!r}, end={end_marker!r})")
    return "\n".join(file_lines[: start_idx + 1] + generated.split("\n") + file_lines[end_idx:])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def sync(check: bool = False) -> int:
    tokens = load_tokens()
    xaml_generated = generate_xaml(tokens)
    css_generated = generate_css(tokens)

    xaml_content = XAML_FILE.read_text()
    css_content = CSS_FILE.read_text()

    new_xaml = replace_between_markers(xaml_content, XAML_START, XAML_END, xaml_generated)
    new_css = replace_between_markers(css_content, CSS_START, CSS_END, css_generated)

    if check:
        errors: list[str] = []
        if xaml_content != new_xaml:
            errors.append(f"  {XAML_FILE.relative_to(REPO_ROOT)}")
        if css_content != new_css:
            errors.append(f"  {CSS_FILE.relative_to(REPO_ROOT)}")
        if errors:
            print("Design tokens out of sync:", file=sys.stderr)
            for e in errors:
                print(e, file=sys.stderr)
            print("\nHint: run 'just sync-tokens' then re-stage.", file=sys.stderr)
            return 1
        print("Design tokens in sync.")
        return 0

    changed = False
    if xaml_content != new_xaml:
        XAML_FILE.write_text(new_xaml)
        print(f"  Updated {XAML_FILE.relative_to(REPO_ROOT)}")
        changed = True
    if css_content != new_css:
        CSS_FILE.write_text(new_css)
        print(f"  Updated {CSS_FILE.relative_to(REPO_ROOT)}")
        changed = True
    if not changed:
        print("Already in sync.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync design tokens to XAML and CSS")
    parser.add_argument("--check", action="store_true", help="Check sync without writing (exit 1 if stale)")
    args = parser.parse_args()
    sys.exit(sync(check=args.check))


if __name__ == "__main__":
    main()
