---
name: frontend
description: Web / HTML / CSS / UI design — comprehensive design intelligence for building professional, visually distinctive pages and components. Use when the task involves UI structure, visual design decisions, interaction patterns, accessibility, or user experience.
triggers: html, page, site, website, web, landing, portfolio, dashboard, game, interface, ui, design, css, animation, card, blog, form, button, navbar, responsive, hero, fais moi un site, crée un site, page web, make a site, make a page, make a game, create a game, faire un site, faire une page, build a page, build a site, create a page, glassmorphism, claymorphism, brutalism, neumorphism, dark mode, layout, typography, color palette, font, accessibility, wcag, mobile-first, breakpoint, chart, dashboard, component, modal, sidebar, table, input
---

# UI/UX Pro Max — Design Intelligence

Comprehensive design guide for web and mobile applications. Contains 67 UI styles, 161 color palettes, 57 font pairings, 161 product types with reasoning rules, 99 UX guidelines, and 25 chart types. Use priority 1→10 to decide which rule category to focus on first.

## When to Apply

**Must use** when:
- Designing new pages (Landing Page, Dashboard, Admin, SaaS, Portfolio, Game)
- Creating or refactoring UI components (buttons, modals, forms, tables, charts)
- Choosing color schemes, typography systems, spacing, or layout systems
- Reviewing UI code for UX, accessibility, or visual consistency
- Implementing navigation, animations, or responsive behavior

**Decision criteria**: If the task changes how something **looks, feels, moves, or is interacted with** — use this skill.

---

## Rule Categories by Priority

| Priority | Category            | Impact   | Key Checks                                                  | Anti-Patterns                                                |
|----------|---------------------|----------|-------------------------------------------------------------|--------------------------------------------------------------|
| 1        | Accessibility       | CRITICAL | Contrast 4.5:1, Alt text, Keyboard nav, Aria-labels         | Removing focus rings, Icon-only buttons without labels       |
| 2        | Touch & Interaction | CRITICAL | Min 44×44px targets, 8px+ spacing, Loading feedback         | Hover-only interactions, Instant state changes (0ms)         |
| 3        | Performance         | HIGH     | WebP/AVIF, Lazy loading, Reserve space (CLS < 0.1)         | Layout thrashing, Cumulative Layout Shift                    |
| 4        | Style Selection     | HIGH     | Match product type, Consistency, SVG icons (no emoji)       | Mixing flat & skeuomorphic randomly, Emoji as icons          |
| 5        | Layout & Responsive | HIGH     | Mobile-first breakpoints, Viewport meta, No horizontal scroll| Horizontal scroll, Fixed px widths, Disable zoom             |
| 6        | Typography & Color  | MEDIUM   | Base 16px, Line-height 1.5, Semantic color tokens           | Text < 12px body, Gray-on-gray, Raw hex in components        |
| 7        | Animation           | MEDIUM   | 150–300ms, Transform/opacity only, Motion conveys meaning   | Decorative-only animation, Animating width/height, No reduced-motion |
| 8        | Forms & Feedback    | MEDIUM   | Visible labels, Error near field, Helper text               | Placeholder-only label, Errors only at top, Overwhelming upfront |
| 9        | Navigation          | HIGH     | Predictable back, Bottom nav ≤5, Deep linking              | Overloaded nav, Broken back behavior, No deep links          |
| 10       | Charts & Data       | LOW      | Legends, Tooltips, Accessible colors                        | Relying on color alone, No table alternative                 |

---

## Design Process (Always Follow This)

### Step 1: Analyze the Brief
Extract:
- **Product type**: Landing page, Dashboard, Portfolio, Game, Tool, E-commerce, SaaS…
- **Audience**: Who uses it, what do they need in the first 3 seconds?
- **Style keywords**: minimal, dark, vibrant, elegant, brutalist…
- **Signature element**: The ONE thing this page will be remembered by

### Step 2: Generate Design System (Do This First)
Build a compact token system:
- **Palette**: 4–5 named hex values as CSS custom properties. Industry-appropriate.
- **Type**: 2 Google Fonts — a characterful display face used with restraint + a readable body face
- **Layout**: Describe in one sentence. Mobile-first.
- **Signature**: The single unique element that embodies the brief

### Step 3: Avoid AI Defaults
Do NOT default to:
- Warm cream (#F4F1EA) + terracotta accent (unless literally asked)
- Near-black + acid green or vermilion (unless it fits)
- Generic 3-card feature grid with emoji icons
- "Why choose us?" sections with checkmark lists
- Numbered markers (01/02/03) unless content is actually sequential
- Lorem ipsum — write real copy

### Step 4: Self-Critique Before Delivering
Ask: does any part of this look like what I'd generate for any similar brief? If yes, revise it. Spend boldness in ONE place — the signature element — and keep everything else quiet and disciplined.

---

## Priority 1: Accessibility (CRITICAL)

- **color-contrast** — Minimum 4.5:1 for normal text, 3:1 for large text
- **focus-states** — Visible focus rings on ALL interactive elements (2–4px outline)
- **alt-text** — Descriptive alt for meaningful images; empty alt="" for decorative
- **aria-labels** — aria-label for icon-only buttons
- **keyboard-nav** — Tab order matches visual order; full keyboard support
- **form-labels** — Every input has a visible `<label>`
- **skip-links** — "Skip to main content" for keyboard users
- **heading-hierarchy** — Sequential h1→h6, never skip levels
- **color-not-only** — Never convey info by color alone (add icon or text)
- **reduced-motion** — Respect `prefers-reduced-motion`; disable animations when requested

---

## Priority 2: Touch & Interaction (CRITICAL)

- **touch-target-size** — Min 44×44px; extend hit area beyond visual bounds if needed
- **touch-spacing** — Minimum 8px gap between touch targets
- **hover-vs-tap** — Use click/tap for primary; don't rely on hover alone
- **loading-buttons** — Disable button during async ops; show spinner or progress
- **error-feedback** — Clear error messages near the problem field
- **cursor-pointer** — Add `cursor: pointer` to ALL clickable elements
- **press-feedback** — Visual feedback on press (opacity, scale, color shift)
- **tap-delay** — Use `touch-action: manipulation` to remove 300ms delay

---

## Priority 3: Performance (HIGH)

- **image-optimization** — WebP/AVIF, `srcset`/`sizes`, lazy load non-critical assets
- **image-dimension** — Declare width/height or use `aspect-ratio` to prevent CLS
- **font-loading** — `font-display: swap` to avoid invisible text
- **font-preload** — Preload only critical fonts
- **critical-css** — Inline critical above-the-fold CSS
- **bundle-splitting** — Split code by route/feature
- **progressive-loading** — Skeleton screens for >1s operations, not blank spinners
- **debounce-throttle** — Debounce scroll/resize/input handlers

---

## Priority 4: Style Selection (HIGH)

### Available Styles (choose one, be intentional)
- **Minimalism & Swiss Style** — Enterprise, dashboards, documentation
- **Glassmorphism** — Modern SaaS, financial dashboards
- **Brutalism / Neubrutalism** — Design portfolios, Gen Z brands, startups
- **Claymorphism** — Educational, children's apps, playful SaaS
- **Dark Mode (OLED)** — Night-mode apps, coding platforms, AI products
- **Soft UI Evolution** — Modern enterprise, wellness
- **Bento Box Grid** — Dashboards, product pages, portfolios
- **AI-Native UI** — Chatbots, copilots, AI products
- **Aurora UI / Gradient Mesh** — Creative agencies, hero sections
- **Neumorphism** — Health/wellness, meditation
- **Retro-Futurism / Y2K** — Music platforms, gaming, Gen Z fashion
- **HUD / Sci-Fi FUI** — Cybersecurity, space tech, gaming
- **Editorial Grid / Magazine** — News sites, blogs
- **Organic Biophilic** — Wellness, sustainability

### Style Rules
- **style-match** — Match style to product type and industry
- **consistency** — Use the SAME style across all pages
- **no-emoji-icons** — Use SVG icons (Heroicons, Lucide), NEVER emojis in UI
- **effects-match-style** — Shadows, blur, radius must align with chosen style
- **primary-action** — Each screen has ONE primary CTA; secondary actions subordinate
- **icon-style-consistent** — One icon set/visual language across the entire product

---

## Priority 5: Layout & Responsive (HIGH)

- **viewport-meta** — `<meta name="viewport" content="width=device-width, initial-scale=1">` — NEVER disable zoom
- **mobile-first** — Base styles for mobile, add complexity at wider breakpoints
- **breakpoints** — 375px (phone), 768px (tablet), 1024px (laptop), 1440px (desktop)
- **readable-font-size** — Minimum 16px body on mobile (avoids iOS auto-zoom)
- **line-length** — 35–60 chars/line mobile; 60–75 desktop
- **horizontal-scroll** — ZERO horizontal scroll on mobile
- **spacing-scale** — 4px base scale: 4, 8, 12, 16, 24, 32, 48, 64, 96
- **container-width** — max-width: 1200–1280px on desktop, centered
- **z-index-management** — Define a z-index scale (0 / 10 / 20 / 40 / 100 / 1000)
- **viewport-units** — Use `min-h-dvh` / `100dvh` not `100vh` on mobile

---

## Priority 6: Typography & Color (MEDIUM)

### Typography
- **line-height** — 1.5–1.75 for body text
- **font-scale** — Consistent scale: 12 / 14 / 16 / 18 / 24 / 32 / 48
- **weight-hierarchy** — Bold headings (600–700), Regular body (400), Medium labels (500)
- **letter-spacing** — Respect platform defaults; avoid tight tracking on body
- **number-tabular** — Monospaced figures for prices, timers, data columns

### Color
- **color-semantic** — Define tokens (primary, secondary, error, surface, on-surface) — not raw hex in components
- **color-dark-mode** — Dark mode = desaturated/lighter tonal variants, NOT inverted
- **color-accessible-pairs** — 4.5:1 (AA) or 7:1 (AAA) for foreground/background
- **color-not-decorative** — Functional colors (error red, success green) must include icon/text too
- **whitespace-balance** — Use whitespace intentionally to group and breathe

### Font Pairing Guide (by mood)
- **Elegant/Luxury** — Cormorant Garamond + Montserrat
- **Modern/Tech** — Syne + Space Grotesk
- **Editorial** — Fraunces + DM Sans
- **Clean/Corporate** — Inter + Inter (weight contrast)
- **Friendly/Startup** — Cabinet Grotesk + Instrument Sans
- **Code/Dev** — Space Mono + Space Grotesk

---

## Priority 7: Animation (MEDIUM)

- **duration-timing** — 150–300ms for micro-interactions; ≤400ms for complex transitions
- **transform-performance** — Animate ONLY `transform` and `opacity`; never `width`, `height`, `top`, `left`
- **loading-states** — Skeleton or progress for >300ms loading
- **easing** — `ease-out` for entering, `ease-in` for exiting; never `linear` for UI
- **motion-meaning** — Every animation expresses cause-effect; NOT decorative
- **excessive-motion** — Max 1–2 animated elements per view
- **exit-faster** — Exit animations should be ~60–70% of enter duration
- **interruptible** — Animations must be interruptible by user action immediately

---

## Priority 8: Forms & Feedback (MEDIUM)

- **input-labels** — Visible label per input (NOT placeholder-only)
- **error-placement** — Error message below the related field
- **submit-feedback** — Loading → success/error state on submit
- **empty-states** — Helpful message + action when no content; not just "No data"
- **toast-dismiss** — Auto-dismiss toasts after 3–5s
- **confirmation-dialogs** — Confirm before destructive actions
- **inline-validation** — Validate on blur (not keystroke); show error after user finishes
- **error-clarity** — Error messages say WHAT went wrong AND how to fix it
- **destructive-emphasis** — Destructive actions use red, visually separated from primary actions

---

## Priority 9: Navigation (HIGH)

- **bottom-nav-limit** — Bottom nav max 5 items; always show labels with icons
- **back-behavior** — Back navigation is predictable; preserves scroll/state
- **deep-linking** — All key screens reachable via URL
- **nav-state-active** — Current location highlighted (color, weight, indicator)
- **modal-escape** — Modals always have a clear close affordance
- **adaptive-navigation** — Sidebar on ≥1024px; bottom/top nav on mobile
- **navigation-consistency** — Nav placement stays the same across ALL pages
- **focus-on-route-change** — After navigation, move focus to main content region

---

## Priority 10: Charts & Data (LOW)

- **chart-type** — Line for trends, Bar for comparisons, Pie/Donut for ≤5 proportions
- **color-guidance** — Accessible palettes; never red/green only
- **legend-visible** — Always show legend near the chart
- **tooltip-on-interact** — Exact values on hover/tap
- **axis-labels** — Label axes with units; no rotated/truncated labels on mobile
- **responsive-chart** — Charts reflow on small screens
- **empty-data-state** — "No data yet" + guidance; not blank axes
- **no-pie-overuse** — Never pie chart with >5 categories; use bar chart

---

## By Page Type

**Landing page** → Real value proposition hero, 2–3 sections max, one CTA, footer with links  
**Dashboard** → Sidebar nav + main area, stat cards with real numbers, one chart, data table  
**Portfolio** → Work first, about second, contact last — let the work speak  
**Game** → Canvas element, requestAnimationFrame loop, score/level UI, keyboard + touch  
**Tool/app** → Input/output clearly separated, loading states, error states, empty states handled  
**E-commerce** → Product-first, trust signals, frictionless checkout, clear CTAs  
**SaaS** → Value prop above fold, feature benefits (not features), pricing, social proof  

---

## Technical Requirements

- Single `.html` file, all CSS + JS inline, no external deps except Google Fonts + cdnjs
- CSS custom properties for EVERY color, spacing, and radius value
- Semantic HTML: `<header>`, `<main>`, `<section>`, `<article>`, `<footer>` correctly used
- Always include `<meta charset="UTF-8">` and `<meta name="viewport">`
- Charts: Chart.js from `cdnjs.cloudflare.com`
- Icons: SVG inline or Unicode symbols — **NEVER emoji as UI elements**

---

## Pre-Delivery Checklist

- [ ] No emojis used as icons (use SVG instead)
- [ ] `cursor: pointer` on ALL clickable elements
- [ ] Hover states with smooth transitions (150–300ms)
- [ ] Light mode: text contrast ≥4.5:1 minimum
- [ ] Focus states visible for keyboard navigation
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive: tested at 375px, 768px, 1024px, 1440px
- [ ] No horizontal scroll on mobile
- [ ] All inputs have visible labels (not placeholder-only)
- [ ] Error messages say what went wrong AND how to fix it
- [ ] One clear primary CTA per screen/section
