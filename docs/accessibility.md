# Accessibility

candid's dashboard is a single-file local web UI (`candid/data/dashboard.html`,
served by `python -m candid dashboard` on 127.0.0.1 only). It targets
**WCAG 2.2 AA** and ships an automated audit so regressions get caught in CI
instead of by keyboard-only users.

## What was audited

`python -m candid a11y` runs eight static checks against the dashboard HTML
(see `candid/a11y.py` for the engine):

| Check | What it verifies |
|---|---|
| `contrast` | WCAG relative-luminance contrast ratios of the CSS `:root` palette (each text color against each surface), plus the button chrome. Flags below 4.5:1 for normal text, below 3.0:1 for large text. |
| `structure` | A "Skip to main content" link (`class="skip-link"`, `href="#main-content"`), banner/main/contentinfo landmarks, `<main id="main-content">`, exactly one `h1`, and no skipped heading levels. |
| `labels` | Every `input`/`select`/`textarea` has a `<label for>`, a wrapping label, `aria-label`, `aria-labelledby`, or `title`. |
| `buttons` | Every `<button>`, including ones rendered by the inline JS, exposes text or `aria-label`. Buttons whose text is injected at runtime (JS template interpolation) are reported as dynamic and pass. |
| `images` | Every `<img>` has an `alt` attribute. |
| `focus-motion` | `:focus-visible` rules exist, plus an `@media (prefers-reduced-motion: reduce)` block and an `html[data-motion="reduced"]` selector for the manual reduce-motion toggle. |
| `live-region` | At least one `aria-live="polite"` region announces async status updates. |
| `tables` | Every `<table>` has a `<caption>` (or an `aria-label`). |

## Running it

```bash
python -m candid a11y          # human-readable report, exit 0 if all pass, 1 if any fail
python -m candid a11y --json   # machine-readable JSON (same shape, for CI)
python -m candid a11y --file path/to/page.html   # audit a different file
```

The JSON shape is `{"source", "target": "WCAG 2.2 AA", "passed", "checks": [...],
"summary": {"total", "passed", "failed"}}`, where each check carries its
`details` and `failures` lists.

## Known limitations

- The audit is **static**: it parses the HTML, inline CSS, and JS templates,
  but it does not run the page. Runtime states (focus order after dynamic
  re-renders, the `announce()` live-region text, sort-button arrow glyphs)
  need a manual keyboard + screen-reader pass.
- Contrast is computed for the palette's declared foreground/surface pairs;
  semi-transparent overlays and gradient button backgrounds are approximated
  by their dominant colors.
- Dynamic button text (`${label}` template interpolation) is accepted as
  "renders text at runtime" without verifying the runtime value.
- The audit does not measure target size, color independence of meaning, or
  reflow at 400% zoom; those are covered by the manual checklist below.

## Manual checklist (before a release)

1. Tab through the whole dashboard with a keyboard: the skip link appears
   first, every control is reachable, and the `:focus-visible` outline is
   always visible.
2. Toggle "Reduce motion" in the header and confirm transitions stop.
3. With a screen reader, confirm sections announce via their
   `aria-labelledby` headings and async updates are announced politely.
4. Check 320px-wide reflow (the `@media(max-width:760px)` rules) for lost
   controls.
