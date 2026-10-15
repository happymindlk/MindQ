# Design System

<!-- impeccable:design-schema 1 -->

## Mode

Operate — admin task surfaces. Scanability, density, and familiar affordances outrank expression.

## World

Enterprise product surface: charcoal canvas, crisp neutral borders, single violet accent for primary actions and selection. Linear / Stripe / Datadog / Vercel craft level. No glass-card prototype look.

## Anti-patterns (banned)

- Purple-to-pink or multi-stop decorative gradients
- Nested card-in-card containers
- Low-contrast muted gray body text on dark surfaces
- Inter as the default product face
- Playful bounce / hover-lift animations
- Gradient text, decorative blur, thick colored side borders on panels

## Color

| Token | Role | Value |
|-------|------|-------|
| `canvas` | App background | `#0B0F17` |
| `surface` | Panels, sidebar | `#111827` |
| `surface-raised` | Elevated strips, sticky headers | `#161E2E` |
| `border` | Separators | `oklch(0.35 0.01 250 / 0.45)` ≈ `#2A3344` |
| `foreground` | Primary text | `#E8EDF5` |
| `muted` | Secondary / metadata | `#9AA8BC` (≥4.5:1 on canvas) |
| `primary` | CTA fill | `#6B4CE8` |
| `primary-fg` | On primary | `#F5F3FF` |
| `primary-text` | Accent text on dark | `#A78BFA` |
| `success` | Completed / positive | `#34D399` |
| `warning` | In progress / caution | `#FBBF24` |
| `danger` | Error / destructive | `#F87171` |

Accent is used only for primary actions, active nav, and focus rings — never decoration.

## Typography

- Sans: **Poppins** (all portals: ops, HR client, candidate).
- Mono / tabular: **IBM Plex Mono** for metrics, IDs, access codes, timestamps (`tabular-nums`).
- Fixed rem scale, ratio ~1.125–1.2. No fluid clamp headings in product UI.
- Page title: 1.25rem semibold. Section / table headers: 0.75rem medium uppercase tracking optional sparingly. Body: 0.875rem. Meta: 0.75rem muted.

## Spacing & density

- Row / cell padding: 8–12px.
- Modular panels: 16px padding.
- Page content: 12–16px (not 24–32px consumer padding).
- Prefer 1px separators and surface luminance shifts over nested bordered cards.

## Components

- **Buttons:** Flat fills; no gradient; no translate-y lift. `focus-visible:ring-2`.
- **Cards / panels:** Subtle border + surface fill; `rounded-lg` max; no shadow stacks.
- **Tables:** Sticky header, compact rows, sortable columns, tabular nums for data.
- **Drawer:** Right slide-over for record drill-down; modal only when focus must be trapped for a short confirm.
- **Badges:** Compact semantic chips (success / warning / danger / muted).
- **Toast:** Non-blocking feedback; never `alert()`.

## Motion

150–250ms ease-out opacity/transform for drawer and toast only. No page-load choreography. No bounce.

## Cross-surface

Admin Layout + CandidateTracker (Phase 1) and candidate portal + public track (Phase 2) share one Operate design system. Do not invent a second visual world for portal surfaces.
