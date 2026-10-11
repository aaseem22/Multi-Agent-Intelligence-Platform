# Design: one console, two themes

## Concept

A product-grade operations console in the style of Linear or Vercel. Every screen (chat, agents,
observability and the trace inspector) shares one shell, one token set with a light and a dark
theme, one type family and one accent. Structure comes from white surfaces on a cool canvas, generous spacing and a small
set of reusable components. Colour is reserved for meaning: the accent marks what is current or
live, status colours mark outcomes, and each agent has its own hue.

## Tokens (`src/index.css`, `@theme`)

| Token | Hex | Role |
|---|---|---|
| `canvas` | `#f5f6f8` | Page ground |
| `surface` | `#ffffff` | Cards, panels, composer |
| `subtle` | `#f0f2f5` | Inner blocks: tool logs, evidence, stat tiles |
| `ink` / `ink-2` | `#0e1116` / `#39404a` | Headings and body |
| `muted` / `faint` | `#646c78` / `#8b929c` | Secondary text, timestamps |
| `line` / `line-strong` | `#e4e7ec` / `#d0d5dc` | Borders and dividers |
| `accent` | `#0f766e` (+ `accent-soft`, `accent-strong`) | The single accent: live, active nav, peer traffic, focus ring |
| `ok` / `warn` / `danger` | green / amber / red, each with a `-soft` tint | Status only |
| `agent-*` | CEO `#1f2937`, Finance `#6941c6`, HR `#b8326a`, Tech `#1764b0`, 3 overflow hues | Agent identity. Mirrored in `lib/agents.ts` for SVG |

Primary buttons are near-black ink, not the accent.

## Type

- **Geist** for all UI text, **Geist Mono** for machine text (tool calls, refs, hop counts,
  keyboard hints). Tabular figures are on globally.
- Scale: `2xs` 11, `xs` 12, `sm` 13, `base` 14, `read` 15/25.6, `lg` 17, `xl` 22, `2xl` 30, `3xl` 40.
- Headlines use negative tracking; long text is capped near 68ch and uses `text-wrap: pretty`.

## Themes

- Light values live in `@theme`; `.dark` on `<html>` overrides the same `--color-*` variables, so
  utilities and SVG charts (which read `var(--color-*)`) flip together.
- The viewer picks Light, Dark or System in the sidebar (`hooks/usePreferences.ts`). The choice is
  kept in localStorage, and a small script in `index.html` applies it before first paint.
- Semantic tokens added for theming: `elevated`, `on-ink`, `ink-hover`, `bubble`/`on-bubble`,
  `glow`, and `series-*` for non-agent chart series.

## Shell

- The desktop sidebar collapses to a 68px icon rail (button in the sidebar header, or Cmd/Ctrl + B);
  the state is remembered. On mobile it is a drawer.
- Behind everything sits a fixed ambient layer: two slow, faint accent light fields, a dot grid that
  fades out downward, and a 2.5% grain. All are inert and stop moving under reduced motion.

## Shape and depth

- Containers (cards, panels, composer): `rounded-card` (16px). Inner blocks and controls:
  `rounded-block` (10px). Status chips and the live dot: full pills.
- Shadows are soft and tinted toward the ink hue: `shadow-card` at rest, `shadow-raised` on
  hover and for the trace drawer.
- A 2.5% fixed grain overlay sits over the canvas; it never takes pointer events.

## Components (`@layer components`)

`.card`, `.btn` + `.btn-primary` / `.btn-secondary` / `.btn-ghost` / `.btn-icon`, `.chip`,
`.mono-tag`, `.link`, `.skeleton`, `.live-dot`, `.stagger` (set `--i` for cascade delay), `.spotlight`
(cursor-following glow, driven by `useSpotlight`), `.glow-focus` (accent ring on the composer),
`.frost` (blurred panel with a solid fallback), `.display` (headline ink fade).

Shared React pieces: `PageHeader`, `AgentOrbit` (the live system diagram on the welcome screen),
`AgentAvatar` (icon in a tinted rounded square), `AgentName`, `AgentTag`,
`RunStateLabel` (status pill), `RichText` (bold and inline code from agent markdown),
`LoadingState` (skeletons), `ErrorState`, `EmptyState`.

## Motion

One easing curve, `cubic-bezier(0.16, 1, 0.3, 1)`. Content fades up 8px on entry, lists cascade
60ms apart, cards lift 2px on hover, buttons press to 97%. Only `transform` and `opacity`
animate. Everything collapses to instant under `prefers-reduced-motion`.

## Rules

- One token set everywhere. No screen gets its own palette or fonts; never hardcode a colour in a
  component, add a token instead.
- Lucide icons at stroke 1.75 throughout.
- No em dashes in UI copy. Empty values show `-`.
- Agent colours never style chrome; the accent never identifies an agent.
