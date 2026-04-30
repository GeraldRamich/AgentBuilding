# Recipe Standardization Agent

An agent that reads recipe files in **multiple formats**, normalises them into a standard schema, and produces a single **iPad-friendly HTML document** you can open directly in Safari.

---

## Features

| Capability | Detail |
|---|---|
| **Supported input formats** | `.txt` (plain text), `.json`, `.md` / `.markdown`, `.csv` |
| **Parsed fields** | Title, servings, prep time, cook time, ingredients (amount / unit / item), numbered instructions, notes |
| **Output** | Single self-contained HTML file – no internet connection required on device |
| **iPad optimised** | Responsive layout, system fonts, print-safe, table of contents |

---

## Quick Start

```bash
# Parse all recipes in recipes/input/ and write recipes/output/recipes.html
python3 agent/recipe_agent.py

# Custom paths
python3 agent/recipe_agent.py --input /path/to/my/recipes --output /path/to/output.html
```

Open `recipes/output/recipes.html` in **Safari on your iPad** (or any browser).

---

## Project Layout

```
AgentBuilding/
├── agent/
│   └── recipe_agent.py      # The agent (pure Python, no dependencies)
├── recipes/
│   ├── input/               # Drop your recipe files here
│   │   ├── banana_bread.txt
│   │   ├── caesar_salad.csv
│   │   ├── chicken_tikka_masala.md
│   │   ├── chocolate_chip_cookies.json
│   │   └── spaghetti_carbonara.txt
│   └── output/
│       └── recipes.html     # Generated output (open on iPad)
└── README.md
```

---

## Input Format Examples

### Plain Text (`.txt`)

```
My Recipe Title

Servings: 4
Prep Time: 15 minutes
Cook Time: 30 minutes

Ingredients:
- 2 cups flour
- 1 tsp salt

Instructions:
1. Mix the ingredients.
2. Bake at 350°F for 30 minutes.

Notes:
Don't over-mix the batter.
```

Section headings are flexible — `INGREDIENTS:`, `What you need:`, `You will need:` are all recognised. Instruction headings like `INSTRUCTIONS:`, `Directions:`, `How to make it:` also work.

### JSON (`.json`)

```json
{
  "name": "My Recipe",
  "servings": "4",
  "prepTime": "10 min",
  "cookTime": "25 min",
  "ingredients": [
    { "qty": "2", "unit": "cups", "item": "flour" }
  ],
  "steps": [
    "Mix the ingredients.",
    "Bake for 25 minutes."
  ],
  "notes": "Optional tip here."
}
```

### Markdown (`.md`)

```markdown
# My Recipe

**Servings:** 4
**Prep Time:** 10 minutes
**Cook Time:** 25 minutes

## Ingredients
- 2 cups flour
- 1 tsp salt

## Instructions
1. Mix the ingredients.
2. Bake for 25 minutes.

## Notes
> Optional tip here.
```

### CSV (`.csv`)

```csv
Recipe Name,My Recipe
Servings,4
Prep Time,10 minutes
Cook Time,25 minutes
Notes,Optional tip here.

Section,Amount,Unit,Ingredient
Main,2,cups,flour
Main,1,tsp,salt

Step,Instruction
1,Mix the ingredients.
2,Bake for 25 minutes.
```

---

## Requirements

- Python 3.7 or later
- No third-party libraries required

---

## Adding Your Own Recipes

1. Place your recipe file(s) in `recipes/input/`
2. Run `python3 agent/recipe_agent.py`
3. Open `recipes/output/recipes.html` on your iPad

The agent processes all supported files in the input directory alphabetically and combines them into one document.
