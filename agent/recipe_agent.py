#!/usr/bin/env python3
"""
Recipe Standardization Agent
=============================
An agent that reads recipe files in various formats (TXT, JSON, Markdown, CSV),
parses and standardizes them into a common schema, and produces a single
iPad-friendly HTML document.

Supported input formats:
  - .txt   plain-text recipes (flexible heading detection)
  - .json  JSON-structured recipes
  - .md    Markdown recipes
  - .csv   CSV-structured recipes (custom two-section format)

Usage:
  python recipe_agent.py [--input <dir>] [--output <file>]

Defaults:
  --input   recipes/input/
  --output  recipes/output/recipes.html
"""

import argparse
import csv
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Ingredient:
    amount: str = ""
    unit: str = ""
    item: str = ""

    def display(self) -> str:
        parts = [p for p in (self.amount, self.unit, self.item) if p]
        return " ".join(parts)


@dataclass
class Recipe:
    title: str = "Untitled Recipe"
    servings: str = ""
    prep_time: str = ""
    cook_time: str = ""
    ingredients: List[Ingredient] = field(default_factory=list)
    instructions: List[str] = field(default_factory=list)
    notes: str = ""
    source_file: str = ""


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

class RecipeParser:
    """Base class – subclasses implement `can_parse` and `parse`."""

    def can_parse(self, path: Path) -> bool:
        raise NotImplementedError

    def parse(self, path: Path) -> Recipe:
        raise NotImplementedError


class JsonParser(RecipeParser):
    """Parses JSON-structured recipe files."""

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() == ".json"

    def parse(self, path: Path) -> Recipe:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        recipe = Recipe(source_file=path.name)
        recipe.title = data.get("name") or data.get("title") or path.stem.replace("_", " ").title()
        recipe.servings = str(data.get("servings") or data.get("yield") or "")
        recipe.prep_time = str(data.get("prepTime") or data.get("prep_time") or "")
        recipe.cook_time = str(data.get("cookTime") or data.get("cook_time") or "")
        recipe.notes = data.get("notes") or ""

        raw_ingredients = data.get("ingredients") or []
        for item in raw_ingredients:
            if isinstance(item, dict):
                recipe.ingredients.append(Ingredient(
                    amount=str(item.get("qty") or item.get("amount") or ""),
                    unit=str(item.get("unit") or ""),
                    item=str(item.get("item") or item.get("name") or ""),
                ))
            elif isinstance(item, str):
                recipe.ingredients.append(Ingredient(item=item))

        instructions = data.get("steps") or data.get("instructions") or []
        recipe.instructions = [str(s) for s in instructions]

        return recipe


class MarkdownParser(RecipeParser):
    """Parses Markdown-structured recipe files."""

    _TIME_KEYS = re.compile(r"(prep|cook|total)\s*time", re.IGNORECASE)
    _SERVING_KEYS = re.compile(r"(servings?|yield|makes)", re.IGNORECASE)
    _HEADING = re.compile(r"^#{1,4}\s+(.*)", re.IGNORECASE)
    _LIST_ITEM = re.compile(r"^\s*[-*+]\s+(.*)")
    _NUMBERED = re.compile(r"^\s*\d+\.\s+(.*)")
    _BOLD_META = re.compile(r"\*\*([^*]+)\*\*\s*:?\s*(.*)")

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() in (".md", ".markdown")

    def parse(self, path: Path) -> Recipe:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()

        recipe = Recipe(source_file=path.name)
        section = "meta"

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Top-level heading → recipe title
            h_match = self._HEADING.match(stripped)
            if h_match:
                heading = h_match.group(1).strip()
                lower = heading.lower()
                if "ingredient" in lower:
                    section = "ingredients"
                elif "instruction" in lower or "direction" in lower or "method" in lower or "step" in lower:
                    section = "instructions"
                elif "note" in lower or "tip" in lower:
                    section = "notes"
                elif section == "meta":
                    recipe.title = heading
                continue

            # Bold metadata lines (e.g. **Servings:** 4)
            bold_match = self._BOLD_META.match(stripped)
            if bold_match:
                key, value = bold_match.group(1).strip(), bold_match.group(2).strip()
                value = value.lstrip(":").strip()
                if self._SERVING_KEYS.search(key):
                    recipe.servings = value
                elif "prep" in key.lower():
                    recipe.prep_time = value
                elif "cook" in key.lower() or "bake" in key.lower():
                    recipe.cook_time = value
                continue

            # List items
            list_match = self._LIST_ITEM.match(stripped)
            if list_match:
                content = list_match.group(1).strip()
                if section == "ingredients":
                    recipe.ingredients.append(_parse_ingredient_string(content))
                elif section == "notes":
                    recipe.notes += content + " "
                continue

            # Numbered steps
            num_match = self._NUMBERED.match(stripped)
            if num_match:
                content = num_match.group(1).strip()
                # Strip bold sub-headings like **Marinate:**
                content = re.sub(r"\*\*[^*]+\*\*:?\s*", "", content).strip()
                if section == "instructions" and content:
                    recipe.instructions.append(content)
                continue

            # Blockquote notes
            if stripped.startswith(">"):
                note_text = stripped.lstrip("> ").strip()
                recipe.notes += note_text + " "

        recipe.notes = recipe.notes.strip()
        return recipe


class CsvParser(RecipeParser):
    """
    Parses a two-section CSV format:
      - Header rows: Recipe Name, Servings, Prep Time, Cook Time, Notes
      - Ingredient rows: Section, Amount, Unit, Ingredient
      - Step rows: Step, Instruction
    """

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() == ".csv"

    def parse(self, path: Path) -> Recipe:
        with open(path, encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))

        recipe = Recipe(source_file=path.name)
        mode = "header"

        for row in rows:
            if not any(cell.strip() for cell in row):
                continue

            first = row[0].strip()
            second = row[1].strip() if len(row) > 1 else ""

            # Detect section transitions
            if first.lower() == "section" and second.lower() in ("amount", "qty"):
                mode = "ingredients"
                continue
            if first.lower() == "step" and second.lower() == "instruction":
                mode = "instructions"
                continue

            if mode == "header":
                key = first.lower()
                value = second
                if "recipe name" in key or "name" == key:
                    recipe.title = value
                elif "servings" in key or "yield" in key:
                    recipe.servings = value
                elif "prep" in key:
                    recipe.prep_time = value
                elif "cook" in key or "bake" in key:
                    recipe.cook_time = value
                elif "note" in key:
                    recipe.notes = value.strip('"')

            elif mode == "ingredients":
                # Row format: Section, Amount, Unit, Ingredient
                amount = row[1].strip() if len(row) > 1 else ""
                unit = row[2].strip() if len(row) > 2 else ""
                item = row[3].strip() if len(row) > 3 else ""
                if item:
                    recipe.ingredients.append(Ingredient(amount=amount, unit=unit, item=item))

            elif mode == "instructions":
                instruction = row[1].strip() if len(row) > 1 else ""
                if instruction:
                    recipe.instructions.append(instruction)

        return recipe


class PlainTextParser(RecipeParser):
    """
    Parses plain-text recipe files with flexible heading detection.
    Handles headings like INGREDIENTS:, INSTRUCTIONS:, What you need:, How to make it: etc.
    """

    _INGREDIENT_HEADINGS = re.compile(
        r"^(ingredients?|what\s+you\s+need|you\s+will\s+need|shopping\s+list)\s*:?\s*$",
        re.IGNORECASE,
    )
    _INSTRUCTION_HEADINGS = re.compile(
        r"^(instructions?|directions?|method|steps?|how\s+to\s+(make\s+)?it|preparation)\s*:?\s*$",
        re.IGNORECASE,
    )
    _NOTES_HEADINGS = re.compile(
        r"^(notes?|tips?|chef['\u2019s]*\s+note)\s*:?\s*$",
        re.IGNORECASE,
    )
    _META_LINE = re.compile(
        r"^(servings?|yield|makes|prep\s*(time)?|cook\s*(time)?|bak(e|ing)\s*(time)?|total\s*(time)?)\s*:\s*(.+)$",
        re.IGNORECASE,
    )
    _NUMBERED = re.compile(r"^\d+[.)]\s+(.*)")
    _BULLET = re.compile(r"^[-*•]\s+(.*)")
    _INLINE_NOTE = re.compile(r"^(tip|note)\s*:\s*(.*)", re.IGNORECASE)

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() in (".txt", ".text", "")

    def parse(self, path: Path) -> Recipe:
        with open(path, encoding="utf-8") as f:
            lines = [l.rstrip("\n") for l in f.readlines()]

        recipe = Recipe(source_file=path.name)
        section = "title"

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Section heading detection
            if self._INGREDIENT_HEADINGS.match(stripped):
                section = "ingredients"
                continue
            if self._INSTRUCTION_HEADINGS.match(stripped):
                section = "instructions"
                continue
            if self._NOTES_HEADINGS.match(stripped):
                section = "notes"
                continue

            # Metadata lines (Servings: 4, Prep Time: 15 min, ...)
            meta = self._META_LINE.match(stripped)
            if meta:
                key = meta.group(1).lower()
                value = meta.group(meta.lastindex).strip() if meta.lastindex else ""
                if not value:
                    # fallback: everything after the first colon
                    value = stripped.split(":", 1)[-1].strip()
                if "serving" in key or "yield" in key or "makes" in key:
                    recipe.servings = value
                elif "prep" in key:
                    recipe.prep_time = value
                elif "cook" in key or "bak" in key:
                    recipe.cook_time = value
                continue

            # Inline tip/note
            note_match = self._INLINE_NOTE.match(stripped)
            if note_match:
                recipe.notes += note_match.group(2).strip() + " "
                continue

            if section == "title":
                recipe.title = stripped
                section = "meta"  # only the first non-empty line is the title

            elif section == "ingredients":
                # Remove leading bullets
                bullet = self._BULLET.match(stripped)
                content = bullet.group(1).strip() if bullet else stripped
                recipe.ingredients.append(_parse_ingredient_string(content))

            elif section == "instructions":
                num = self._NUMBERED.match(stripped)
                if num:
                    recipe.instructions.append(num.group(1).strip())
                else:
                    # Treat non-empty lines as instruction sentences
                    recipe.instructions.append(stripped)

            elif section == "notes":
                recipe.notes += stripped + " "

        recipe.notes = recipe.notes.strip()
        return recipe


# ---------------------------------------------------------------------------
# Ingredient string parser
# ---------------------------------------------------------------------------

_AMOUNT_PATTERN = re.compile(
    # Amount: mixed numbers (e.g. "1 1/2"), plain fractions ("3/4"), integers, or vulgar fractions
    r"^(\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?|[½¼¾⅓⅔⅛⅜⅝⅞])\s*"
    # Unit: must match as a complete word (word boundary) to avoid "l" matching "large"
    r"(cups?|tbsps?|tablespoons?|tsps?|teaspoons?|fl\.?\s*oz|oz|ounces?|lbs?|pounds?|"
    r"grams?|kg|kilograms?|ml|liters?|litres?|cloves?|heads?|bunches?|stalks?|"
    r"cans?|packages?|slices?|pieces?|pinch(?:es)?|dash(?:es)?|"
    r"small|medium|large|whole|g)\b\s*"
    r"(.*)",
    re.IGNORECASE,
)


def _parse_ingredient_string(text: str) -> Ingredient:
    """Best-effort parse of a free-form ingredient string into (amount, unit, item)."""
    m = _AMOUNT_PATTERN.match(text.strip())
    if m:
        amount = m.group(1).strip()
        unit = (m.group(2) or "").strip()
        item = (m.group(3) or "").strip().lstrip(",- ").strip()
        return Ingredient(amount=amount, unit=unit, item=item or text)
    return Ingredient(item=text)


# ---------------------------------------------------------------------------
# Agent orchestrator
# ---------------------------------------------------------------------------

PARSERS: List[RecipeParser] = [
    JsonParser(),
    MarkdownParser(),
    CsvParser(),
    PlainTextParser(),
]


def process_directory(input_dir: Path) -> List[Recipe]:
    """Walk input_dir, select a parser for each file, and return parsed recipes."""
    recipes: List[Recipe] = []
    supported = {".txt", ".text", ".json", ".md", ".markdown", ".csv"}

    for path in sorted(input_dir.iterdir()):
        if path.is_dir() or path.suffix.lower() not in supported:
            continue
        parser = next((p for p in PARSERS if p.can_parse(path)), None)
        if parser is None:
            print(f"  [skip] no parser for {path.name}", file=sys.stderr)
            continue
        print(f"  [parse] {path.name}  ({parser.__class__.__name__})")
        try:
            recipe = parser.parse(path)
            recipes.append(recipe)
        except Exception as exc:  # noqa: BLE001
            print(f"  [error] {path.name}: {exc}", file=sys.stderr)

    return recipes


# ---------------------------------------------------------------------------
# HTML renderer (iPad-optimised)
# ---------------------------------------------------------------------------

_CSS = """
:root {
  --bg: #fdf6ec;
  --card: #ffffff;
  --accent: #c0392b;
  --accent-light: #f9e5e3;
  --text: #2c2c2c;
  --muted: #6b6b6b;
  --border: #e2d9cf;
  --shadow: 0 2px 12px rgba(0,0,0,.08);
  --radius: 14px;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, "Helvetica Neue", Arial, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.65;
  padding: 1.5rem 1rem 3rem;
}

header {
  text-align: center;
  padding: 2rem 1rem 1.5rem;
}
header h1 {
  font-size: 2rem;
  color: var(--accent);
  letter-spacing: -.5px;
}
header p {
  color: var(--muted);
  font-size: .9rem;
  margin-top: .3rem;
}

/* Table of contents */
.toc {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.2rem 1.5rem;
  max-width: 700px;
  margin: 0 auto 2rem;
  box-shadow: var(--shadow);
}
.toc h2 {
  font-size: 1rem;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--muted);
  margin-bottom: .7rem;
}
.toc ol { padding-left: 1.4rem; }
.toc li { margin: .3rem 0; }
.toc a { color: var(--accent); text-decoration: none; font-weight: 500; }
.toc a:hover { text-decoration: underline; }

/* Recipe cards */
.recipes { max-width: 700px; margin: 0 auto; display: flex; flex-direction: column; gap: 2rem; }

.card {
  background: var(--card);
  border-radius: var(--radius);
  border: 1px solid var(--border);
  box-shadow: var(--shadow);
  overflow: hidden;
}

.card-header {
  background: var(--accent);
  color: #fff;
  padding: 1.2rem 1.5rem;
}
.card-header h2 {
  font-size: 1.4rem;
  font-weight: 700;
}
.card-header .source {
  font-size: .75rem;
  opacity: .75;
  margin-top: .2rem;
}

.meta-bar {
  display: flex;
  flex-wrap: wrap;
  gap: .5rem 1.5rem;
  padding: .9rem 1.5rem;
  background: var(--accent-light);
  border-bottom: 1px solid var(--border);
}
.meta-item { font-size: .85rem; color: var(--muted); }
.meta-item strong { color: var(--text); }

.card-body { padding: 1.2rem 1.5rem; }

.section-title {
  font-size: .8rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .1em;
  color: var(--accent);
  margin: 1.2rem 0 .5rem;
  padding-bottom: .3rem;
  border-bottom: 2px solid var(--accent-light);
}
.section-title:first-child { margin-top: 0; }

.ingredients { list-style: none; }
.ingredients li {
  padding: .4rem 0;
  border-bottom: 1px solid var(--border);
  font-size: .95rem;
  display: flex;
  align-items: baseline;
  gap: .4rem;
}
.ingredients li:last-child { border-bottom: none; }
.ingredients .amount { font-weight: 600; min-width: 3rem; }
.ingredients .unit   { color: var(--muted); min-width: 4rem; }

.instructions { list-style: none; counter-reset: step; }
.instructions li {
  counter-increment: step;
  display: flex;
  gap: .9rem;
  padding: .5rem 0;
  font-size: .95rem;
  border-bottom: 1px solid var(--border);
  align-items: flex-start;
}
.instructions li:last-child { border-bottom: none; }
.instructions li::before {
  content: counter(step);
  background: var(--accent);
  color: #fff;
  border-radius: 50%;
  min-width: 1.6rem;
  height: 1.6rem;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: .8rem;
  font-weight: 700;
  flex-shrink: 0;
  margin-top: .1rem;
}

.notes-box {
  background: #fffbf0;
  border-left: 4px solid #f0c040;
  border-radius: 0 8px 8px 0;
  padding: .7rem 1rem;
  font-size: .9rem;
  color: #5a4a00;
  margin-top: .5rem;
}

footer {
  text-align: center;
  color: var(--muted);
  font-size: .8rem;
  margin-top: 3rem;
}

/* iPad / print optimisations */
@media (min-width: 768px) {
  body { padding: 2rem 2rem 4rem; }
  .card-header h2 { font-size: 1.6rem; }
}
@media print {
  body { background: #fff; }
  .card { page-break-inside: avoid; box-shadow: none; border: 1px solid #ccc; }
}
"""


def _escape(text: str) -> str:
    """Minimal HTML escaping."""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )


def render_html(recipes: List[Recipe], generated_at: str, year: str = "") -> str:
    """Return the full HTML document as a string."""
    parts: List[str] = []

    parts.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>My Recipe Book</title>
  <style>{_CSS}</style>
</head>
<body>

<header>
  <h1>🍽 My Recipe Book</h1>
  <p>{len(recipes)} recipe{"s" if len(recipes) != 1 else ""} &nbsp;·&nbsp; Generated {_escape(generated_at)}</p>
</header>
""")

    # Table of contents
    parts.append('<nav class="toc">\n  <h2>Contents</h2>\n  <ol>\n')
    for i, r in enumerate(recipes, 1):
        anchor = f"recipe-{i}"
        parts.append(f'    <li><a href="#{anchor}">{_escape(r.title)}</a></li>\n')
    parts.append("  </ol>\n</nav>\n\n")

    # Recipe cards
    parts.append('<div class="recipes">\n')
    for i, r in enumerate(recipes, 1):
        anchor = f"recipe-{i}"
        parts.append(f'<article class="card" id="{anchor}">\n')

        # Card header
        parts.append(f'  <div class="card-header">\n')
        parts.append(f'    <h2>{_escape(r.title)}</h2>\n')
        if r.source_file:
            parts.append(f'    <div class="source">Source: {_escape(r.source_file)}</div>\n')
        parts.append(f'  </div>\n')

        # Meta bar
        meta_items = []
        if r.servings:
            meta_items.append(f'<span class="meta-item"><strong>Servings:</strong> {_escape(r.servings)}</span>')
        if r.prep_time:
            meta_items.append(f'<span class="meta-item"><strong>Prep:</strong> {_escape(r.prep_time)}</span>')
        if r.cook_time:
            meta_items.append(f'<span class="meta-item"><strong>Cook:</strong> {_escape(r.cook_time)}</span>')
        if meta_items:
            parts.append('  <div class="meta-bar">\n    ')
            parts.append("\n    ".join(meta_items))
            parts.append('\n  </div>\n')

        parts.append('  <div class="card-body">\n')

        # Ingredients
        if r.ingredients:
            parts.append('    <div class="section-title">Ingredients</div>\n')
            parts.append('    <ul class="ingredients">\n')
            for ing in r.ingredients:
                amount_html = f'<span class="amount">{_escape(ing.amount)}</span>' if ing.amount else ""
                unit_html = f'<span class="unit">{_escape(ing.unit)}</span>' if ing.unit else ""
                item_html = _escape(ing.item)
                parts.append(f'      <li>{amount_html}{unit_html}{item_html}</li>\n')
            parts.append('    </ul>\n')

        # Instructions
        if r.instructions:
            parts.append('    <div class="section-title">Instructions</div>\n')
            parts.append('    <ol class="instructions">\n')
            for step in r.instructions:
                parts.append(f'      <li><span>{_escape(step)}</span></li>\n')
            parts.append('    </ol>\n')

        # Notes
        if r.notes:
            parts.append(f'    <div class="section-title">Notes</div>\n')
            parts.append(f'    <div class="notes-box">{_escape(r.notes)}</div>\n')

        parts.append('  </div>\n')  # card-body
        parts.append('</article>\n\n')

    parts.append('</div>\n\n')  # .recipes

    parts.append(f'<footer>Recipe Book &copy; {_escape(year or generated_at[-4:])} &nbsp;·&nbsp; Open in Safari on iPad for best experience</footer>\n')
    parts.append('</body>\n</html>\n')

    return "".join(parts)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recipe Standardization Agent – converts mixed-format recipes to a single iPad-friendly HTML file."
    )
    parser.add_argument(
        "--input",
        default="recipes/input",
        help="Directory containing recipe files (default: recipes/input)",
    )
    parser.add_argument(
        "--output",
        default="recipes/output/recipes.html",
        help="Output HTML file path (default: recipes/output/recipes.html)",
    )
    args = parser.parse_args()

    input_dir = Path(args.input)
    output_path = Path(args.output)

    if not input_dir.is_dir():
        print(f"Error: input directory '{input_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Recipe Standardization Agent")
    print(f"  Input  : {input_dir.resolve()}")
    print(f"  Output : {output_path.resolve()}")
    print()

    recipes = process_directory(input_dir)

    if not recipes:
        print("No recipes parsed – nothing to write.", file=sys.stderr)
        sys.exit(1)

    print(f"\n  {len(recipes)} recipe(s) standardised successfully.")

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    generated_at = now.strftime("%B %d, %Y")
    year = now.strftime("%Y")

    html = render_html(recipes, generated_at, year)
    output_path.write_text(html, encoding="utf-8")
    print(f"  Output written to: {output_path}")


if __name__ == "__main__":
    main()
