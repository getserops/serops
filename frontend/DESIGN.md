# SerOps frontend: design rules

Short on purpose. It says where the tokens are, which shared pieces to use,
and the rules a change must follow. The token *values* live in the CSS, not
here.

## Tokens

Colours are defined in `src/styles/design.css`, for the light and the dark
theme. Scales (type, spacing, radius, shadow, z-index) are still defined in
`src/index.css`; moving them into `design.css` is a later step of the review.

| Role | Tokens |
|---|---|
| Page and surfaces | `--bg-page`, `--bg-card`, `--bg-elevated`, `--bg-sunken`, `--bg-surface`, `--bg-hover` |
| Borders | `--border-default`, `--border-hover` |
| Text | `--text-primary`, `--text-secondary`, `--text-tertiary`, `--text-link`, `--text-link-hover` |
| Brand | `--brand-fill`, `--brand-fill-hover` (primary buttons, active menu entry), `--focus-ring` |
| Tones, text on a soft fill | `--tone-red-text` / `--tone-red-soft`, `--tone-amber-*`, `--tone-green-*`, `--tone-brand-*`, `--tone-gray-*` |
| Solid red | `--tone-red-solid` (danger button, the 3px accent of an urgent card) |
| Type | `--font-sans`, `--font-mono`, `--text-xs` to `--text-3xl` |
| Spacing | `--space-1` (4px) to `--space-16`, a 4-point scale |
| Radius | `--radius-sm` (4px), `--radius-md` (8px), `--radius-lg` (12px), `--radius-full` |
| Shadow | `--shadow-sm`, `--shadow-md`, `--shadow-pop`, `--shadow-dialog` |
| Layers | `--z-dropdown`, `--z-sticky`, `--z-fixed`, `--z-overlay`, `--z-modal`, `--z-toast` |

## Shared pieces (`src/styles/primitives.css`, `src/styles/design.css`)

| Class | Use |
|---|---|
| `ds-btn` + `ds-btn-primary` / `-secondary` / `-ghost` / `-danger`, `ds-btn-sm` | Every button and button-like link |
| `ds-chip` + `ds-chip-err` / `-warn` / `-ok` / `-brand` / `-neutral` / `-outline`, `ds-dot` | Status, severity and small labels; never build a chip class by hand, use `utils/tones.js` |
| `ds-card`, `ds-card-header`, `ds-card-body`, `ds-card-footer` | A panel |
| `ds-input`, `ds-label`, `ds-help`, `ds-toggle` | Form controls |
| `ds-table` | Tables |
| `ds-empty-state` | "Nothing here yet", with one sentence and one action |
| `ds-notice-info` | An informational notice |
| `ds-mono` | Service names, identifiers, code |
| `ds-skip-link`, `ds-visually-hidden` | Accessibility helpers |

## Colour usage

1. **Red means "needs action now".** The red left accent, red figure and
   filled red chip are for issues that are open, acknowledged or regressed.
   A resolved or muted issue keeps its severity as an outlined neutral chip
   (`ds-chip-outline`) with no coloured accent.
2. **No large tinted background for severity.** Severity is a chip plus a
   3px accent on the left of the row or card.
3. **Amber means warning only.** Not a neutral label, not the "Open"
   status, not an informational banner.
4. **Status chips, one mapping on every page:** Open = brand, Acknowledged
   = neutral, Resolved = green, Muted = gray, Regressed = red.
   **Severity chips:** Critical and High = red, Warning and Medium = amber,
   Info and Low = neutral.
5. **Informational notices** (demo banner, read-only note, Enterprise
   notice) use the info tone: `--tone-brand-soft` with `--text-primary`.
6. **Green means healthy or resolved.**
7. **One brand blue**, from the token, for primary buttons, links, the
   active menu entry and focus rings.

The mappings of rules 1 and 4 are implemented once, in `src/utils/tones.js`
(`statusTone`, `severityTone`, `statusChipClass`, `severityChipClass`,
`severityAccent`, `needsAction`). Pages call it; they do not decide colours.

## Dates

Every date goes through `src/utils/dates.js`, which follows the time zone
and the language of the user menu.

- Detail views: `formatAbsolute()`, always with the zone ("21 Nov 2026,
  00:57:21 UTC").
- Tables and lists: `formatRelative()` ("2 days ago") with
  `formatAbsolute()` in the `title`.
- A column of times says its zone in its heading (`zoneLabel()`).
- No `toLocaleString`, `toLocaleDateString` or `toLocaleTimeString` on a
  date anywhere else. A test fails if one appears.

## Rules for a change

- Tokens and `ds-*` classes only. No literal colour (`#hex`, `rgb()`,
  `hsl()`) outside `src/styles/design.css`.
- Every sentence in English and French (`src/locales/en.json`, `fr.json`).
- Check light and dark.
- A test for each change of behaviour; `npm test` and `npm run lint` pass.
- An entry in `CHANGELOG.md`.

## Guard rail

`npm run lint` runs `scripts/check-literal-colours.mjs` after ESLint. It
counts literal colours per file under `src/` and compares with
`scripts/literal-colours-baseline.json`: a file may have fewer than its
baseline, never more, and a file that is not in the baseline must have
none. After removing literals, lock the lower number in with:

```
npm run lint:colours -- --update
```

Do not raise a number in the baseline to make a change pass; use a token.
