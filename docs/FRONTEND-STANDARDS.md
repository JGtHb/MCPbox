# Frontend Standards

Canonical style guide for the MCPbox React frontend. All new UI work must follow these standards.

## Color System

Use **only** Rosé Pine tokens from `tailwind.config.js`. Never use generic Tailwind colors (`gray-*`, `blue-*`, `red-*`, etc.).

| Token | Usage |
|-------|-------|
| `base` | Page background |
| `surface` | Card/container background |
| `overlay` | Elevated backgrounds, hover overlays |
| `muted` | Disabled text, tertiary text |
| `subtle` | Secondary text |
| `on-base` | Primary text |
| `love` | Error, destructive actions |
| `gold` | Warning, caution |
| `foam` | Success, positive |
| `iris` | Primary accent (buttons, focus rings, active states) |
| `pine` | Secondary accent (links, info) |
| `rose` | Decorative accent (rarely used) |
| `hl-low` | Subtle highlight background |
| `hl-med` | Borders, dividers |
| `hl-high` | Strong borders, hover borders |

### Badge Pattern

All status/type badges follow this pattern:
```
bg-{color}/10 text-{color}
```

Examples: `bg-foam/10 text-foam` (success), `bg-love/10 text-love` (error), `bg-gold/10 text-gold` (warning).

## Button Sizing

Three tiers. All buttons must use one.

| Tier | Classes | When to Use |
|------|---------|-------------|
| **xs** | `px-2.5 py-1 text-xs font-medium` | Pagination, inline tags, icon-adjacent |
| **sm** | `px-3 py-1.5 text-sm font-medium` | Secondary actions, table row actions, approval buttons |
| **md** | `px-4 py-2 text-sm font-medium` | Primary actions, form submits, modal buttons |

### Button Variants

| Variant | Classes |
|---------|---------|
| **Primary** | `bg-iris text-base hover:bg-iris/80` |
| **Secondary** | `bg-hl-low text-subtle hover:bg-hl-med border border-hl-med` |
| **Ghost** | `text-subtle hover:text-on-base hover:bg-hl-low` |
| **Destructive** | `bg-love text-base hover:bg-love/80` |
| **Destructive ghost** | `text-love hover:bg-love/10` |
| **Success** | `bg-foam text-base hover:bg-foam/80` |
| **Warning** | `bg-gold text-base hover:bg-gold/80` |

All buttons must include:
- `transition-colors` for hover states
- `disabled:opacity-50` when `disabled` prop is possible
- `rounded-lg` (default) or `rounded-md` (within tight inline contexts like segmented controls)

## Focus States

Every interactive element **must** have a visible focus indicator.

### Standard Focus Ring

```
focus:outline-none focus:ring-2 focus:ring-iris
```

For elements on colored backgrounds, add `focus:ring-offset-2` (adds a gap between ring and element).

### Where Required

- All `<button>` elements
- All `<a>` links used as buttons
- All `<input>`, `<select>`, `<textarea>` elements
- All clickable `<div>`/`<li>` elements with `role="button"` or `tabIndex`
- Toggle switches (via `peer-focus:ring-2 peer-focus:ring-iris`)

### Form Inputs

Standard pattern:
```
border border-hl-med rounded-lg bg-surface text-on-base
focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris
```

## ARIA & Accessibility

### Icon-Only Buttons

Every button with only an icon (no visible text) **must** have `aria-label`:
```tsx
<button aria-label="Delete tool" ...>
  <svg .../>
</button>
```

### Expandable Sections

Elements that toggle expanded content must include `aria-expanded`:
```tsx
<button aria-expanded={isExpanded} ...>
```

### Roles

- Lists of items: `<ul role="list">`
- Status indicators: `role="status"` on badge spans
- Clickable non-button elements: `role="button" tabIndex={0}` with `onKeyDown` handler
- Modal dialogs: `role="dialog" aria-modal="true" aria-labelledby="modal-title"`

### Keyboard Navigation

- Expandable rows: respond to Enter and Space (`onKeyDown`)
- Modals: Escape to close, focus trap with Tab cycling
- All custom controls must be keyboard-operable

## Border Radius

| Context | Class | Example |
|---------|-------|---------|
| Cards, containers, modals | `rounded-lg` | Content cards, modal panels |
| Inline elements, segmented controls | `rounded-md` | Segmented button groups |
| Badges, status pills | `rounded-full` | Approval badges, status dots |
| Chart bars, progress | `rounded-t` | Bar chart elements |

## Spacing

### Page-Level Layout

```
p-4 sm:p-6         /* Page content padding */
space-y-6           /* Between major sections */
max-w-4xl mx-auto   /* Constrained content width (where applicable) */
```

### Card Interiors

```
p-4 sm:p-6          /* Standard card padding */
p-3 sm:p-4          /* Compact card (stat cards, list items) */
```

### Section Gaps

```
space-y-6            /* Between cards/sections */
space-y-4            /* Within cards */
space-y-2            /* Tight lists */
gap-3 sm:gap-4       /* Grid gaps */
mb-4                 /* Header-to-content in cards */
```

## Typography Hierarchy

| Element | Classes |
|---------|---------|
| Page title | `text-2xl font-semibold text-on-base` |
| Section header | `text-lg font-medium text-on-base` |
| Card header | `text-sm font-medium text-on-base` |
| Stat label | `text-xs font-medium text-subtle uppercase` |
| Body text | `text-sm text-subtle` |
| Caption/help | `text-xs text-muted` |
| Monospace | `font-mono text-sm` (code), `font-mono text-xs` (inline code) |

## Empty States

All empty states must follow this pattern:

```tsx
<div className="text-center py-8">
  <svg className="w-12 h-12 text-muted mx-auto mb-3" ...>
    {/* Relevant icon */}
  </svg>
  <p className="text-subtle mb-1">{primaryMessage}</p>
  <p className="text-xs text-muted">{secondaryMessage}</p>
</div>
```

- Always include an SVG icon (12x12, `text-muted`)
- Primary message: `text-subtle` (what's empty)
- Secondary message: `text-xs text-muted` (what to do about it)
- Optional CTA button below

## Transitions

| Trigger | Class |
|---------|-------|
| Color/background change | `transition-colors` |
| Shadow change | `transition-shadow` |
| Opacity change | `transition-opacity` |
| Transform (rotate, scale) | `transition-transform` |
| Multiple properties | `transition-all` (use sparingly) |

Every hover/focus state change should have a matching transition class.

## Modals

Always use the `ConfirmModal` component (`components/ui/ConfirmModal.tsx`) instead of `window.confirm()`. The component provides:
- Focus trap
- Escape key handling
- Click-outside dismiss
- ARIA dialog attributes
- Destructive variant with warning icon

For custom modals, follow the same pattern:
```tsx
<div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true">
  <div className="fixed inset-0 bg-base/50" onClick={onClose} />
  <div className="relative bg-surface rounded-lg shadow-xl p-6 w-full max-w-md mx-4">
    {/* Content */}
  </div>
</div>
```

## Mobile Responsiveness

- Toolbars with multiple buttons: `flex flex-wrap gap-2`
- Filter controls: `flex flex-wrap items-center gap-3`
- Grids: `grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3`
- Padding: `p-4 sm:p-6` (never just `p-6` alone)
- Text hidden on mobile: `hidden sm:inline`
- Code blocks: `overflow-x-auto break-all` for long strings
