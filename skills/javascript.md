---
name: javascript
description: JavaScript and Node.js — modern, async-first, clean
triggers: javascript, js, node, npm, typescript, ts, react, vue, svelte, fetch, async, promise, dom, event listener, api call, frontend js, client side
---

# JavaScript / Node.js

Modern JS only. No legacy patterns.

## Core rules

- `const`/`let` everywhere — never `var`
- Arrow functions for callbacks, regular functions for methods using `this`
- `async/await` over `.then()` chains — always wrap in `try/catch`
- Optional chaining: `user?.profile?.avatar ?? 'default.png'`
- Template literals for any string with variables

## Async pattern

```js
async function fetchData(url) {
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.error('fetchData failed:', err.message);
    return null;
  }
}
```

## DOM

- `querySelector` / `querySelectorAll` — never `getElementById` in new code
- `addEventListener` — never `onclick=`
- Use `data-*` attributes for state: `el.dataset.state = 'active'`
- Debounce input handlers: `clearTimeout(t); t = setTimeout(fn, 300)`
- Always check element exists before using it: `if (!el) return;`

## State

- Keep state in one object — not scattered variables
- Update DOM from state — not the other way around

## Performance

- `requestAnimationFrame` for animations — never `setInterval` for rendering
- Batch DOM reads before writes to avoid layout thrash
- Abort stale requests with `AbortController`

## Node.js

- ES modules (`import/export`) not CommonJS unless forced
- `fs/promises` for file operations
- Environment variables via `process.env` — never hardcode secrets
