---
name: debugging
description: Debugging and problem solving — systematic, honest, root-cause focused
triggers: error, bug, erreur, doesn't work, not working, crash, exception, traceback, fix, debug, broken, fails, ne marche pas, ça marche pas, ça bug, why, pourquoi, help me fix
---

# Debugging

## Approach

1. **Reproduce** — understand exactly what's failing before touching anything
2. **Isolate** — smallest piece of code that shows the bug
3. **Hypothesize** — one theory at a time, test it
4. **Fix** — minimal change that solves the root cause, not the symptom

## Reading Python tracebacks

- Read the **last line first** — that's the actual error
- The line number is a starting point; the real bug is often a few lines above
- `AttributeError: 'NoneType' has no attribute 'X'` → something returned `None` unexpectedly — trace where it came from
- `KeyError: 'name'` → dict doesn't have that key — check where the dict is built
- `IndentationError` → mixed tabs and spaces, or wrong indent level
- `ModuleNotFoundError` → package not installed (`pip install X`) or wrong import path

## Reading JS errors

- `TypeError: Cannot read properties of undefined` → accessing property on `undefined` — check the chain above
- `CORS error` → server-side issue, not client — check headers and allowed origins
- `Uncaught ReferenceError` → variable used before declaration, or typo in name
- Network tab in DevTools shows actual HTTP errors — always check there first

## When you don't know

- Say so, then explain what you'd try next
- Never hallucinate a fix and present it as certain
- Suggest a minimal reproduction: "Try this isolated snippet to confirm the cause"
- If the fix is a guess, say it's a guess

## Checklist before declaring it fixed

- Does it handle the error case too, or just the happy path?
- Could this break something else?
- Is the fix addressing the root cause or just hiding the symptom?
