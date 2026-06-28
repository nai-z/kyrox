---
name: python
description: Python scripting and automation — clean, defensive, production-ready code
triggers: python, script, .py, automate, automation, parse, scrape, csv, json, calculate, bot, scheduler, pathlib, classe, fonction, module, pip
---

# Python Scripting

You write Python like a senior engineer: clean, defensive, readable. No cowboy code.

## Structure

- Every script has a `if __name__ == '__main__':` guard
- Functions do ONE thing — if a function needs a paragraph to describe it, split it
- Use `pathlib.Path` for ALL file operations — never `os.path` string concatenation
- Type hints on all function signatures: `def process(path: Path, count: int) -> list[str]:`
- Docstrings on every non-trivial function (one line is fine if it's clear)
- Name constants at the top in UPPER_SNAKE_CASE — no magic numbers inline

## Error handling

- Wrap I/O and network calls in `try/except` with specific exception types
- Never bare `except:` — catch `Exception as e:` at minimum, log `e`
- Print errors to stderr: `print(f"Error: {e}", file=sys.stderr)`
- Exit with `sys.exit(1)` on fatal errors so shell scripts can detect failure
- Validate inputs early — check file exists, types, ranges before doing work

## Output

- Progress messages for anything that takes > 1 second: `print("Processing 42 files…")`
- Final summary: `print("Done. 42 files processed, 3 skipped, 0 errors.")`
- For scripts that create files: always print the full output path

## CLI tools

- Use `argparse` for any script with more than 1 argument
- Add `--verbose / -v` flag for debug output
- Add `--dry-run` flag for destructive operations
- Help strings should be complete sentences

## Style

- f-strings everywhere — not `.format()` or `%`
- List/dict comprehensions when readable, regular loops when not
- Imports: stdlib first, then third-party, then local. One blank line between groups.

## Common patterns

```python
# Reading files safely
try:
    text = Path(file).read_text(encoding='utf-8')
except FileNotFoundError:
    print(f"File not found: {file}", file=sys.stderr)
    sys.exit(1)

# Making directories
Path(output_dir).mkdir(parents=True, exist_ok=True)

# HTTP with timeout
import httpx
r = httpx.get(url, timeout=10)
r.raise_for_status()
data = r.json()
```
