# Design: the annotated briefing

## Concept

An executive asks a question and gets back a briefing someone has already marked up. The
reading column is a memo: the question set as a headline, the CEO's plan as a short numbered
table, the answer in a comfortable serif with footnoted findings. Beside it runs the log of
messages between agents: a tree of hops drawn with hairlines, like an engineer's notebook.
There is one colour moment, a **highlighter**, and it only ever marks what is current: the page
you are on, the agent that is working, the citation you opened, the live feed.

Structure comes from type, alignment, rules and whitespace. There are no cards, chips, pills,
shadows or gradients anywhere.

## Palette (tokens in `src/index.css`, `@theme`)

| Token | Hex | Role |
|---|---|---|
| `paper` | `#f1f2ed` | Page ground: cool ledger-grey stock, deliberately not cream |
| `paper-deep` | `#e6e8e1` | The agent-message log, so it reads as a separate sheet |
| `ink` | `#191d1b` | Text, primary rules, the Ask button |
| `graphite` | `#4f5652` | Secondary text (6.7:1 on paper) |
| `pencil` | `#5f6661` | Timestamps, counts, marginal numbers (5.2:1 on paper, 4.8:1 on the log) |
| `rule` / `rule-strong` | `#cacec5` / `#979c94` | Hairlines; strong rules open a section |
| `mark` | `#f3e07a` | The highlighter. Background only, always under ink text |
| `done` / `caution` / `refuse` | `#36652a` / `#83560b` / `#ab2a1f` | Status inks, used as text and glyphs only |
| `agent-*` | ceo ink, finance `#1c6a50`, hr `#893a60`, tech `#1f5188`, 3 overflow inks | An agent's name is set in its ink wherever it appears |

## Type

- **Literata** (variable, optical sizes) for everything readable: headlines, answers, UI text.
  Optical sizing makes the 44px headline and the 13px captions both look right from one family.
- **Fragment Mono** only for things that are literally machine text: evidence refs, tool calls,
  hop counts, timestamps, footnote letters, owned table names.
- Tabular figures are on globally.
- Scale (minor third from 16px): `2xs` 12, `xs` 13, `sm` 15, `base` 16, `read` 18/28.8,
  `lg` 21, `xl` 26, `2xl` 34, display 44. Serif reading text gets a 1.6 line height.
- Line length: answers are capped at 66–70ch, the reading column at 46rem.

## Spacing rhythm

A 4px base. Rows inside a list: 8–12px. Between blocks within a turn: 20–24px. Between turns:
a strong rule and 40px. Hanging markers (claim numbers, footnote letters, plan numbers) sit in a
fixed 1.25–1.75rem gutter so the text column stays flush.

## Rules followed

1. No boxes. Grouping is a hairline, a strong rule above a section, or a 2px coloured left rule
   for exceptions (red for failures, ochre for "Not answered").
2. Status is a word plus a typographic glyph (`○ ◐ ● ◑ ✕ ?`) in a status ink. Never a pill.
3. Agents are named in their own ink, as words in the sentence. No chips, no dots-in-pills.
4. Numbers only where the content is a sequence or is referenced: plan subtasks and findings are
   numbered; evidence uses footnote letters so the two never collide.
5. The highlighter marks the current thing and nothing else.
6. Layout varies by content: the plan is a table, agent progress is a log under each row, the
   answer is a reading column with inline footnotes, the A2A panel is a hop tree with connecting
   elbows (squares are requests, circles are responses, `⊘` in red is a refusal), the Agents
   page is a staff directory table followed by spec sheets with the identity in the margin.
7. No all-caps labels, no eyebrow text, no icons in circles, no emoji. Icons are not used at all;
   disclosure uses a mono `›` that rotates.
8. Radius is 2px and only on the two buttons. Nothing has a shadow.
9. Motion: new log lines fade up 3px, running status breathes. Nothing else moves on its own.
   `prefers-reduced-motion` turns all of it off.
10. Focus is a 2px ink outline everywhere; the composer's rule darkens from grey to ink when the
    textarea has focus.
11. Mobile (below `lg`): the log becomes a second tab ("Agent messages"); navigation is a drawer
    opened from a text "Menu" link. Plan rows restack so status sits beside the agent name.

## Fonts

Self-hosted through `@fontsource-variable/literata` and `@fontsource/fragment-mono` (pinned) so
the app needs no runtime CDN and renders the same offline and in headless screenshots.

Single light theme by choice: the paper metaphor carries the design, and a half-considered dark
mode would dilute it.
