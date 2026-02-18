# Frontend Standards

Reference for the MCPbox frontend: theming system, color palette, component patterns, and conventions.

---

## Theme System

MCPbox uses **Rosé Pine** as its color palette:
- **Light mode**: Rosé Pine Dawn
- **Dark mode**: Rosé Pine Moon

### How It Works

1. **CSS custom properties** in `frontend/src/index.css` define colors as space-separated RGB values (e.g., `250 244 237`)
2. **Tailwind config** (`frontend/tailwind.config.js`) maps semantic names to these variables using `rgb(var(--color-*) / <alpha-value>)`
3. **Theme switching** is handled by `useTheme()` hook (`frontend/src/hooks/useTheme.ts`) which adds/removes the `.dark` class on `<html>`
4. No `dark:*` prefixes needed — CSS variables auto-switch between `:root` (Dawn) and `.dark` (Moon)

### Color Palette

| Token | Dawn (Light) | Moon (Dark) | Usage |
|-------|-------------|-------------|-------|
| `base` | `#faf4ed` | `#232136` | Page backgrounds |
| `surface` | `#fffaf3` | `#2a273f` | Card/panel backgrounds |
| `overlay` | `#f2e9e1` | `#393552` | Sidebar, elevated surfaces |
| `muted` | `#9893a5` | `#6e6a86` | Disabled/tertiary text, placeholders |
| `subtle` | `#797593` | `#908caa` | Secondary text, labels |
| `on-base` | `#575279` | `#e0def4` | Primary text (body, headings) |
| `love` | `#b4637a` | `#eb6f92` | Errors, destructive actions |
| `gold` | `#ea9d34` | `#f6c177` | Warnings |
| `rose` | `#d7827e` | `#ea9a97` | Decorative accents |
| `pine` | `#286983` | `#3e8fb0` | Links, informational |
| `foam` | `#56949f` | `#9ccfd8` | Success states |
| `iris` | `#907aa9` | `#c4a7e7` | Primary brand, buttons, active states |
| `hl-low` | `#f4ede8` | `#2a283e` | Subtle highlights, hover backgrounds |
| `hl-med` | `#dfdad9` | `#44415a` | Borders, dividers, medium highlights |
| `hl-high` | `#cecacd` | `#56526e` | Strong highlights, active borders |

### Semantic Usage Guide

#### Backgrounds
```
bg-base        → Page-level background
bg-surface     → Cards, panels, modals, inputs
bg-overlay     → Sidebar, elevated surfaces
bg-hl-low      → Hover state backgrounds, subtle emphasis
bg-hl-med      → Skeleton loaders, medium emphasis
bg-hl-high     → Active/pressed state backgrounds
```

#### Text
```
text-on-base   → Primary text (headings, body, labels)
text-subtle    → Secondary text (descriptions, metadata)
text-muted     → Tertiary text (placeholders, disabled, timestamps)
text-base      → Text on colored backgrounds (buttons) — gives contrast
```

#### Accent Colors
```
bg-iris / text-iris     → Primary actions, active nav, brand elements
bg-foam / text-foam     → Success states, "running" status
bg-love / text-love     → Errors, destructive actions, "error" status
bg-gold / text-gold     → Warnings, "needs attention" states
bg-pine / text-pine     → Links, informational, "ready" status
bg-rose / text-rose     → Decorative accents (rarely used)
```

#### Borders
```
border-hl-med  → Default borders (cards, inputs, dividers)
border-hl-high → Hover/active borders
border-iris/30 → Active/selected item borders
border-love/20 → Error state borders
```

#### Opacity Modifiers
Use Tailwind's `/` syntax for tinted backgrounds:
```
bg-iris/10     → Very light iris tint (badges, pills)
bg-iris/20     → Light iris tint (hover on tinted bg)
bg-love/10     → Error tint background
bg-foam/10     → Success tint background
bg-gold/10     → Warning tint background
hover:bg-iris/80  → Darkened iris on hover (buttons)
```

---

## Component Patterns

### Buttons

**Primary action** (submit, create, save):
```tsx
className="px-4 py-2 bg-iris text-base text-sm font-medium rounded-md hover:bg-iris/80 disabled:opacity-50 transition-colors"
```

**Secondary/cancel** (cancel, dismiss):
```tsx
className="px-4 py-2 text-sm font-medium text-subtle bg-surface border border-hl-med rounded-md hover:bg-hl-low transition-colors"
```

**Destructive** (delete, remove):
```tsx
className="px-4 py-2 bg-love text-base text-sm font-medium rounded-md hover:bg-love/80 disabled:opacity-50 transition-colors"
```

**Ghost/text** (inline actions):
```tsx
className="text-sm font-medium text-iris hover:text-iris/80"
// or for destructive:
className="text-sm font-medium text-love hover:bg-love/10 px-3 py-1.5 rounded-lg"
```

**Small action** (table row actions):
```tsx
className="px-2.5 py-1 text-xs font-medium text-subtle bg-surface border border-hl-med rounded hover:bg-hl-low"
```

### Cards
```tsx
className="bg-surface rounded-lg shadow p-6"
// or bordered:
className="bg-surface border border-hl-med rounded-lg p-4"
```

### Modals
```tsx
{/* Backdrop */}
<div className="fixed inset-0 bg-base/75" />
{/* Panel */}
<div className="bg-surface rounded-lg shadow-xl max-w-md w-full p-6" />
```

### Form Inputs
```tsx
className="w-full px-3 py-2 border border-hl-med rounded-md text-sm bg-surface text-on-base placeholder-muted focus:ring-2 focus:ring-iris focus:border-iris"
```

### Status Badges
Defined in `frontend/src/lib/constants.ts`:
```tsx
className="px-2 py-0.5 text-xs font-medium rounded-full"
// + STATUS_COLORS[status]
```
| Status | Classes |
|--------|---------|
| imported | `bg-overlay text-subtle` |
| ready | `bg-pine/10 text-pine` |
| running | `bg-foam/10 text-foam` |
| stopped | `bg-overlay text-muted` |
| error | `bg-love/10 text-love` |

### Error States
```tsx
{/* Error banner */}
<div className="p-3 bg-love/10 border border-love/20 rounded-md">
  <p className="text-sm text-love">{errorMessage}</p>
</div>
```

### Empty States
```tsx
<div className="text-center py-12 bg-hl-low rounded-lg border-2 border-dashed border-hl-med">
  <svg className="mx-auto h-12 w-12 text-muted" ... />
  <h3 className="mt-2 text-sm font-medium text-on-base">No items</h3>
  <p className="mt-1 text-sm text-subtle">Description text.</p>
  <button className="mt-4 px-4 py-2 bg-iris text-base ...">Action</button>
</div>
```

### Loading States
```tsx
{/* Skeleton card */}
<div className="bg-surface rounded-lg shadow p-6 animate-pulse">
  <div className="h-5 bg-hl-med rounded w-3/4" />
  <div className="h-4 bg-hl-med rounded w-1/2 mt-3" />
</div>

{/* Inline loading */}
<div className="text-sm text-subtle py-4 text-center">Loading...</div>
```

### Pagination
```tsx
<div className="flex items-center justify-between mt-4 text-sm">
  <button className="px-3 py-1 border border-hl-med rounded disabled:opacity-50 hover:bg-hl-low">
    Previous
  </button>
  <span className="text-subtle">Page {page} of {totalPages}</span>
  <button className="px-3 py-1 border border-hl-med rounded disabled:opacity-50 hover:bg-hl-low">
    Next
  </button>
</div>
```

---

## Conventions

### Do
- Use semantic color tokens (`bg-surface`, `text-on-base`) — never hardcode Tailwind default colors (`bg-gray-800`, `text-blue-600`)
- Use `transition-colors` on interactive elements
- Use `disabled:opacity-50` for disabled states
- Use `text-base` for text on colored backgrounds (iris, love, foam buttons)
- Use `/10` opacity modifiers for tinted badge backgrounds
- Use `rounded-lg` for cards, panels, and modals; `rounded-md` for buttons and inputs; `rounded-full` for badges/pills
- Add `focus:outline-none focus:ring-2 focus:ring-iris` for keyboard accessibility on buttons
- Include `aria-label` on icon-only buttons

### Don't
- Don't use `dark:*` prefixes — CSS variables handle theme switching
- Don't hardcode colors from Tailwind defaults (`gray-*`, `blue-*`, `red-*`, etc.)
- Don't mix `bg-white` / `bg-gray-900` — use `bg-surface` or `bg-base`
- Don't add new color variables without updating this document
- Don't use `rounded-xl` or other non-standard border radiuses

### Adding New Colors
If a new semantic color is needed:
1. Add the CSS variable to both `:root` and `.dark` in `frontend/src/index.css`
2. Add the Tailwind mapping in `frontend/tailwind.config.js`
3. Update this document's color table
4. Use the official [Rosé Pine palette](https://rosepinetheme.com/palette) for values

---

## Key Files

| File | Purpose |
|------|---------|
| `frontend/src/index.css` | CSS custom properties (Dawn + Moon palettes) |
| `frontend/tailwind.config.js` | Semantic color token definitions |
| `frontend/src/hooks/useTheme.ts` | Theme state management (light/dark/system) |
| `frontend/src/lib/constants.ts` | STATUS_COLORS, STATUS_LABELS |
| `frontend/src/components/Layout/Sidebar.tsx` | Theme toggle UI |
| `frontend/src/components/ui/ConfirmModal.tsx` | Reusable modal pattern |
| `frontend/src/components/ui/LoadingSkeleton.tsx` | Loading skeleton pattern |
| `frontend/src/components/ui/ErrorBoundary.tsx` | Error display pattern |
