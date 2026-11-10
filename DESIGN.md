---
name: Researcher
description: Run a supervised team of AI agents on any task and follow each contribution as it happens.
colors:
  launch-blue: "#0d6efd"
  launch-blue-deep: "#0b5ed7"
  link-blue-dark: "#6ea8fe"
  on-accent: "#ffffff"
  crew-indigo: "#4f46e5"
  crew-indigo-dark: "#a5b4fc"
  crew-teal: "#0e7490"
  crew-teal-dark: "#67e8f9"
  crew-green: "#15803d"
  crew-green-dark: "#86efac"
  crew-amber: "#b45309"
  crew-amber-dark: "#fcd34d"
  crew-rose: "#be185d"
  crew-rose-dark: "#f9a8d4"
  crew-violet: "#7c3aed"
  crew-violet-dark: "#c4b5fd"
  supervisor-slate: "#475569"
  supervisor-slate-dark: "#cbd5e1"
  answer-green: "#198754"
  answer-green-dark: "#75b798"
  answer-green-wash: "#d1e7dd"
  answer-green-wash-dark: "#051b11"
  answer-green-ink: "#0a3622"
  answer-green-edge: "#a3cfbb"
  answer-green-edge-dark: "#0f5132"
  failure-red: "#dc3545"
  failure-red-wash: "#f8d7da"
  failure-red-wash-dark: "#2c0b0e"
  failure-red-ink: "#58151c"
  failure-red-ink-dark: "#ea868f"
  canvas: "#f4f6fb"
  canvas-dark: "#0d1014"
  surface: "#ffffff"
  surface-dark: "#212529"
  surface-tint: "#f8f9fa"
  surface-tint-dark: "#2b3035"
  surface-muted: "#e9ecef"
  surface-muted-dark: "#343a40"
  ink: "#212529"
  ink-dark: "#dee2e6"
  ink-muted: "rgba(33, 37, 41, 0.75)"
  ink-muted-dark: "rgba(222, 226, 230, 0.75)"
  quiet-grey: "#6c757d"
  border: "#dee2e6"
  border-dark: "#495057"
  hairline: "rgba(0, 0, 0, 0.175)"
  hairline-dark: "rgba(255, 255, 255, 0.15)"
typography:
  wordmark:
    fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", "Noto Sans", "Liberation Sans", Arial, sans-serif'
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.5
  headline:
    fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", "Noto Sans", "Liberation Sans", Arial, sans-serif'
    fontSize: "1.375rem"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  title:
    fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", "Noto Sans", "Liberation Sans", Arial, sans-serif'
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: 1.2
  body:
    fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", "Noto Sans", "Liberation Sans", Arial, sans-serif'
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  prose:
    fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", "Noto Sans", "Liberation Sans", Arial, sans-serif'
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.65
  body-small:
    fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", "Noto Sans", "Liberation Sans", Arial, sans-serif'
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
  meta:
    fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", "Noto Sans", "Liberation Sans", Arial, sans-serif'
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", "Noto Sans", "Liberation Sans", Arial, sans-serif'
    fontSize: "0.75rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.06em"
  mono:
    fontFamily: 'SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace'
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.65
  mono-caption:
    fontFamily: 'SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace'
    fontSize: "0.6875rem"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  sm: "0.25rem"
  code: "0.3rem"
  md: "0.375rem"
  note: "0.5rem"
  avatar: "0.6rem"
  block: "0.625rem"
  tile: "0.75rem"
  card: "0.875rem"
  pill: "999px"
spacing:
  hair: "0.25rem"
  xs: "0.375rem"
  sm: "0.5rem"
  sm-md: "0.625rem"
  md: "0.75rem"
  md-lg: "0.875rem"
  lg: "1rem"
  xl: "1.5rem"
  section: "3.5rem"
components:
  button-launch:
    backgroundColor: "{colors.launch-blue}"
    textColor: "{colors.on-accent}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "0.375rem 0.75rem"
  button-launch-hover:
    backgroundColor: "{colors.launch-blue-deep}"
    textColor: "{colors.on-accent}"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.body-small}"
    rounded: "{rounded.sm}"
    padding: "0.25rem 0.5rem"
  button-quiet-hover:
    backgroundColor: "{colors.surface-tint}"
    textColor: "{colors.ink}"
  button-outline:
    backgroundColor: "transparent"
    textColor: "{colors.quiet-grey}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "0.375rem 0.75rem"
  button-answer:
    backgroundColor: "{colors.answer-green}"
    textColor: "{colors.on-accent}"
    typography: "{typography.body-small}"
    rounded: "{rounded.sm}"
    padding: "0.25rem 0.5rem"
  input-task:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "0.375rem 0.75rem"
  card-panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.card}"
    padding: "1.5rem"
  card-step:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.card}"
    padding: "1rem"
  card-answer-header:
    backgroundColor: "{colors.answer-green-wash}"
    textColor: "{colors.answer-green-ink}"
    typography: "{typography.title}"
    padding: "0.5rem 1rem"
  tile-roster:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.tile}"
    padding: "0.5rem 0.625rem"
  graph-node:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.tile}"
    padding: "0.625rem 0.5rem"
  chip-step:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.meta}"
    rounded: "{rounded.pill}"
    padding: "0.25rem 0.625rem"
  note-routing:
    backgroundColor: "{colors.surface-tint}"
    textColor: "{colors.ink-muted}"
    typography: "{typography.meta}"
    rounded: "{rounded.note}"
    padding: "0.5rem 0.75rem"
  badge-meta:
    backgroundColor: "{colors.surface-tint}"
    textColor: "{colors.ink-muted}"
    rounded: "{rounded.pill}"
  pill-state-live:
    backgroundColor: "{colors.surface-tint}"
    textColor: "{colors.crew-indigo}"
    rounded: "{rounded.pill}"
    padding: "0.2em 0.65em"
  pill-state-completed:
    backgroundColor: "{colors.answer-green-wash}"
    textColor: "{colors.answer-green-ink}"
    rounded: "{rounded.pill}"
    padding: "0.2em 0.65em"
  avatar:
    rounded: "{rounded.avatar}"
    size: "2rem"
---

# Design System: Researcher

## Overview

**Creative North Star: "The Glass-Box Console"**

Researcher is a calm operations console you can see straight through. Neutral white panels sit on a cool, faintly blue canvas, and colour is spent almost entirely on identity: each agent gets a crew colour when the team is designed, and that colour follows it from the roster to its avatar, its graph node and edges, its steps on the execution path, its timeline dot and its contribution card. You always know who did what, where the work is now, and what is still to come.

The console stays calm and restrained while a run takes a minute or more. It is precise and technical where precision helps: model names in monospace, counts and durations in tabular numerals, exact labels for every state. It is friendly through gently rounded corners, soft tints and plain-language copy. Above all it is transparent: every state (waiting, working, done, not called, failed, stopped) has a visible form made of words, icons and border style, never colour alone.

It is not a chatbot, so runs are never rendered as message bubbles or typing dots. It rejects neon "AI" styling: no glowing gradient washes, glowing borders or sparkle effects. It is not grey enterprise admin, so agents never lose their colour identity. And it is not playful: no mascots, emoji or bouncy motion.

**Key Characteristics:**
- Neutral surfaces, with colour reserved for agent identity, the one launch action and the final answer.
- Every agent's crew colour is consistent across every view of the run.
- State is legible without colour: words, icons, dashed versus solid borders.
- Soft lift for top-level cards only; everything inside them is flat and bordered.
- The platform's own UI typeface, monospace only for machine identifiers and code.
- Light and dark themes are equal partners; every colour has a pair.

## Colors

A restrained neutral console with a six-hue crew palette for identity, one launch blue, and a green kept for the answer.

### Primary
- **Launch Blue** (#0d6efd): the single action that starts a run ("Run workflow"), the control that configures it (the streaming switch) and links. Hover deepens to **Launch Blue Deep** (#0b5ed7). In the dark theme, links lighten to **Link Blue Dark** (#6ea8fe) while the filled button keeps Launch Blue.

### Secondary
The **Crew Colours**. Agents take them in team order, cycling after the sixth. Each has a dark-theme partner: a lighter pastel that keeps contrast on the near-black canvas.
- **Crew Indigo** (#4f46e5; dark #a5b4fc): the first agent. Also the empty-state icon, the live-run indicator and the brand mark's starting hue.
- **Crew Teal** (#0e7490; dark #67e8f9): the second agent.
- **Crew Green** (#15803d; dark #86efac): the third agent.
- **Crew Amber** (#b45309; dark #fcd34d): the fourth agent.
- **Crew Rose** (#be185d; dark #f9a8d4): the fifth agent.
- **Crew Violet** (#7c3aed; dark #c4b5fd): the sixth agent, and the brand mark's ending hue.
- **Supervisor Slate** (#475569; dark #cbd5e1): the supervisor and every system node (task, team designer, finalizer), their edges and their execution-path steps.

### Tertiary
- **Answer Green** (#198754; dark #75b798): the final answer and a completed run. It appears as the answer card's border (**Answer Green Edge**, #a3cfbb; dark #0f5132), its tinted header (**Answer Green Wash**, #d1e7dd; dark #051b11) with **Answer Green Ink** text (#0a3622), the Copy button, the graph's Answer node and the "Completed" pill.
- **Failure Red** (#dc3545): a failed run or node. It appears as the failed node's border and on the "Failed" pill, using **Failure Red Wash** (#f8d7da; dark #2c0b0e) and **Failure Red Ink** (#58151c; dark #ea868f).

### Neutral
- **Canvas** (#f4f6fb; dark #0d1014): the page background behind every card. It is cooler and darker than the cards, so they read as lifted.
- **Surface** (#ffffff; dark #212529): cards, graph nodes, execution-path chips and inputs.
- **Surface Tint** (#f8f9fa; dark #2b3035): routing notes, code blocks, badges, `kbd` keys and quiet hover states.
- **Surface Muted** (#e9ecef; dark #343a40): inline code.
- **Ink** (#212529; dark #dee2e6): body text and headings.
- **Ink Muted** (75% ink): metadata, roles, section labels, status text and secondary copy.
- **Quiet Grey** (#6c757d): Bootstrap's outline-secondary buttons (Clear, theme toggle). See the Do's and Don'ts on its dark-theme contrast.
- **Border** (#dee2e6; dark #495057): input strokes, idle graph edges, dividers and dashed empty or pending outlines.
- **Hairline** (translucent black 17.5%; dark translucent white 15%): the 1px outline of cards, tiles and chips.

### Named Rules
**The Crew Identity Rule.** An agent's crew colour is assigned once, by team order, and follows that agent into every view that shows it. A crew colour never decorates anything that is not that agent.

**The One Launch Rule.** Launch Blue fills exactly one thing on screen: the action that starts a run. Nothing else is blue-filled.

**The Answer Is Green Rule.** Answer Green means "the result" or "completed", nothing else. Crew Green sits close in hue, so the answer is also always distinguished by structure: a 2px border, a tinted header and the "Final answer" label.

**The Paired Theme Rule.** Every colour exists as a light and dark pair, defined on `:root` and under `[data-bs-theme="dark"]`. A colour defined for one theme only does not ship.

## Typography

**Body Font:** the platform UI face (`system-ui`, falling back through Segoe UI, Roboto and Helvetica Neue to Arial)
**Label/Mono Font:** the platform monospace (SFMono-Regular, Menlo, Consolas and so on)

**Character:** No web font is loaded. The platform's own UI face makes Researcher feel like a native developer tool and keeps the page free of extra downloads. Hierarchy comes from weight (400, 500, 600) and a small set of sizes, never from decorative faces.

### Hierarchy
- **Wordmark** (600, 1.25rem): "Researcher" in the navbar, beside the brand mark.
- **Headline** (600, 1.375rem, line-height 1.25, -0.01em): the task panel's question, "What should the team work on?". It is the only headline on the page.
- **Title** (600, 1rem, line-height 1.2): agent names on step cards. Card headings such as "Final answer" and roster names use the same size at 500. Graph-detail titles use 0.9375rem / 600.
- **Body** (400, 1rem, line-height 1.5): controls, inputs and general UI text.
- **Prose** (400, 1rem, line-height 1.65): rendered Markdown in step cards and the final answer. Markdown headings sit at 1.05–1.25rem / 600. Text wraps anywhere rather than overflowing.
- **Body Small** (400, 0.875rem): form help, the status bar, graph-detail text and graph-node names (600).
- **Meta** (400, 0.8125rem): step metadata ("Step 2 · model"), routing notes, execution-path chips and graph-detail metadata.
- **Label** (600, 0.75rem, 0.06em tracking, uppercase): section labels such as TEAM, AGENT CONTRIBUTIONS, WORKFLOW GRAPH and EXECUTION PATH, in Ink Muted.
- **Mono** (0.8125rem, line-height 1.65): code blocks. Inline code uses 0.875em on Surface Muted. The run timer uses 0.875rem.
- **Mono Caption** (0.6875rem): model names under roster entries, in the agent's crew colour.

### Named Rules
**The Measured Mono Rule.** Monospace is only for things that are literally machine text: model names, code and the run timer. It never sets headings, labels or decoration.

**The Tabular Time Rule.** Every count, duration and live clock uses tabular numerals, so values that change every second never shift the layout.

## Layout

The page is a Bootstrap `container-xl` (max 1140px, 1320px at ≥1400px) with 12px gutters, under a sticky 3.5rem navbar.

- **Two columns from 992px:** the task panel (a third of the width) and the results (two thirds). The task panel is sticky 1.5rem below the navbar, capped to the viewport height, and scrolls internally, with its status bar pinned to its bottom edge.
- **Below 992px:** the columns stack, and starting a run scrolls the page to the results.
- **Results, in order:** error alert, empty state, workflow graph, agent contributions timeline, working indicator, final answer. Each section carries `scroll-margin-top` so the navbar never covers a section the page scrolls to.

**Spacing rhythm:**
- Tight inside groups (0.25–0.75rem between an avatar and its text, chips, or meta lines).
- Generous between groups (1–1.5rem between cards and sections).
- Cards pad 1rem, and the task panel pads 1.5rem from 768px.

**Timeline:** a 1.75rem left rail with a 2px line. Each step's dot (0.75rem, in the agent's crew colour) carries a Canvas-coloured halo so the line appears to pass behind it.

**Workflow graph:**
- Two rows separated by 4.25rem.
- The main row is a five-column grid (Task, Team designer, Supervisor, Finalizer, Answer) with 1.75rem gaps.
- The agents row is centred beneath it, with 0.875rem gaps and nodes up to 9.5rem wide.
- The canvas keeps a 34rem minimum width. On narrower screens it scrolls sideways inside its card rather than squeezing the nodes, and it follows the working node.

**At 575.98px and below:** card padding tightens to 0.875rem, the timeline rail narrows to 1.25rem, and the empty state pads 2.5rem by 1rem. The page itself never scrolls horizontally.

## Elevation & Depth

The depth is a soft, layered hybrid. Top-level cards (the task panel, the workflow graph, each step card and the final answer) lift off the tinted Canvas with one ambient two-layer shadow, light in the light theme and deeper in the dark. Everything inside a card is flat: tiles, graph nodes, chips and notes separate themselves with 1px Hairline borders and Surface Tint fills, never shadows. The navbar is the one translucent surface: 88% Surface with a 10px backdrop blur and saturation boost, so content scrolls visibly beneath it.

### Shadow Vocabulary
- **Card lift, light** (`box-shadow: 0 1px 2px rgb(15 23 42 / 0.04), 0 4px 16px -8px rgb(15 23 42 / 0.12)`): every top-level card.
- **Card lift, dark** (`box-shadow: 0 1px 2px rgb(0 0 0 / 0.3), 0 4px 16px -8px rgb(0 0 0 / 0.6)`): the same cards in the dark theme.
- **Key cap** (`box-shadow: inset 0 -1px 0 <border>`): `kbd` keyboard hints, giving them a pressed-key base.
- **Live pulse** (a ring in the agent's colour at 45%, animating from 0 to 6px): the avatar of the agent or node that is working, and the dot on the "Live" pill.
- **Selection ring** (`box-shadow: 0 0 0 2px` the agent's colour at 40%): a graph node the user has pinned.

### Named Rules
**The One Lift Rule.** Only top-level cards cast a shadow. Anything nested inside a card is flat and separated by borders and tints.

**The Ring Means State Rule.** A coloured zero-offset ring appears only to show live or selected state, never as decoration.

## Shapes

Corners are gently rounded and step down with nesting depth, so an inner shape never out-rounds its container:
- Cards: 0.875rem (14px).
- Tiles (roster items, graph nodes, the detail panel): 0.75rem.
- Code blocks: 0.625rem.
- Agent avatars and the brand mark: 0.6rem squircle-like squares.
- Routing notes: 0.5rem.
- Buttons and inputs: 0.375rem.
- Small buttons: 0.25rem.
- `kbd` keys and inline code: 0.3rem.

Pills (999px) are used only for compact status: execution-path chips, meta badges and the run-state pill.

Borders carry meaning:
- **Solid 1px Hairline:** something that exists or has happened.
- **Dashed:** something that has not happened yet or will not happen: pending graph nodes, agents the supervisor did not call, idle graph edges (4px dash, 4px gap) and the empty state (2px dashed).
- **Solid 2px:** reserved for the final answer card.

### Named Rules
**The Dashed Means Not-Yet Rule.** Dashed outlines mark what is pending, unused or empty; solid outlines mark what exists. A finished element is never dashed.

## Components

### Buttons
Quiet and precise: standard Bootstrap controls whose colour signals their weight, with nothing extra.
- **Shape:** gently rounded (0.375rem); small buttons 0.25rem.
- **Launch (primary):** Launch Blue fill, white text, a play icon, and "Run workflow". It grows to fill the action row. While running, a small spinner replaces the icon, the label reads "Running…", and the button is disabled.
- **Stop:** Bootstrap outline-danger, shown only while a run is in progress.
- **Outline (Clear, theme toggle):** Bootstrap outline-secondary in Quiet Grey.
- **Quiet action** ("Read full contribution", "Read final answer"): small, transparent, with Ink text and a Border stroke. On hover the border takes the agent's colour over a Surface Tint fill, and the icon is drawn in the agent's colour.
- **Answer (Copy):** small and filled with Answer Green. It confirms with "Copied!" or "Copy failed" and a matching icon for 2 seconds.
- **Icon toggles** (collapse a step or the graph): transparent, Ink Muted chevrons that gain Ink and a Surface Tint fill on hover or focus.

### Inputs / Fields
- **Task field:** a Bootstrap textarea on Surface with a Border stroke, 0.375rem corners, a 9rem minimum height and vertical resizing only. Focus uses Bootstrap's focus ring. An empty submission turns the field invalid, with "Please describe a task first."
- **Streaming switch:** a Bootstrap form switch filled with Launch Blue when on.
- **Keyboard hints:** `kbd` keys on Surface Tint with a Border stroke and an inset bottom line.

### Chips (execution path)
- **Style:** Surface pills with a Hairline border, Meta text, a leading icon in the node's colour, and the step's duration in tabular Ink Muted. Supervisor steps read "To Coder" or "Finish".
- **State:**
  - **Active:** 600 weight, a border in the agent's colour, and an 8% tint.
  - **Pinned:** an inset 1px ring in the agent's colour.
  - **Failed:** a Failure Red border.
  - **Stopped:** dashed.
- **Connectors:** short 1px Border lines join consecutive chips. Rows wrap, and a row never starts with a dangling connector.

### Cards / Containers
- **Corner style:** 0.875rem.
- **Background:** Surface on Canvas.
- **Shadow strategy:** Card lift (see Elevation & Depth).
- **Border:** a 1px Hairline. The final answer uses a 2px Answer Green Edge.
- **Internal padding:** 1rem. The task panel uses 1.5rem from 768px.
- **Step card:** a transparent header with the agent's avatar, its name (Title), "Step N · model" (Meta), and a collapse toggle. The body holds the routing note, then the rendered Markdown.
- **Final answer card:** an Answer Green Wash header with a stars icon, "Final answer", the model name in monospace, and the Copy button.
- **Empty state:** a 2px dashed outline with a centred people icon in Crew Indigo and a short explanation. Prose is capped at 34rem.

### Navigation
A sticky, translucent bar, 3.5rem tall:
- **Left:** the brand mark (a 2rem rounded square with a 135° Crew Indigo to Crew Violet gradient and a white diagram glyph; in dark mode, the pastel pair with a Canvas-coloured glyph) beside the "Researcher" wordmark.
- **Right:** a "Model per role" badge and the theme toggle.
- There are no other navigation destinations: it is a single-page tool.

### Agent Avatar (signature)
A 2rem rounded square (0.6rem) holding the agent's Bootstrap icon in its crew colour over a 14% tint of the same colour. The icon is chosen from keywords in the agent's name: a search glass for research, a code slash for coding, a shield for review, and a robot when nothing matches. It is the one element that identifies an agent everywhere. While the agent works, it pulses with the Live pulse ring.

### Roster Item (signature)
A tile with the avatar, the agent's name (500), its role (Ink Muted, 0.75rem, clamped to two lines), the skill and model in Mono Caption and crew colour, and a right-aligned status ("Idle", "Working…", "2 replies"). When active, its border takes the agent's colour over an 8% tint.

### Workflow Graph (signature)
The live map of a run. Nodes are vertical tiles: avatar, name (Body Small 600, two-line clamp) and a short status.
- **Node states:**
  - **Pending:** dashed border, faded icon.
  - **Active:** border and 8% tint in the agent's colour, a pulsing avatar, and the status in the agent's colour at 600.
  - **Done:** border at 45% of the agent's colour.
  - **Not called / not reached:** dashed border, faded icon, readable text.
  - **Failed:** Failure Red border.
- **Edges:** drawn as SVG behind the nodes, with drawn arrowheads.
  - Idle edges are dashed Border lines.
  - A traversed edge is solid, at 55% of the agent's colour.
  - The edge into the working node is 2px in the agent's colour, with dashes flowing toward the node.
- **Details panel:** below the execution path. It follows the live step until the user pins one, then offers "Follow live".

### Routing Note
The supervisor's reason for a step: a Surface Tint strip with 0.5rem corners, a signpost icon and Meta text in Ink Muted, at the top of each step card and in the graph's details panel.

### Motion
Motion only reports progress:
- **Entrance:** new roster items, timeline steps, graph nodes and chips rise 6px and fade in over 0.3–0.35s with ease-out.
- **Pulse:** live elements pulse on a 1.6s cycle.
- **Edge flow:** the active edge's dashes flow on a 0.7s linear loop.
- **Flash:** a step opened from the graph flashes an outline in its agent's colour for 1.6s.
- **Hover and state changes:** colour transitions take 0.2s.
- **Reduced motion:** everything collapses to an instant change under `prefers-reduced-motion: reduce`.

## Do's and Don'ts

### Do:
- **Do** give every agent its crew colour by team order, and carry that colour into every view that shows the agent: roster, avatar, graph node and edges, execution path, timeline dot and step card.
- **Do** show state with a word, an icon or a border style as well as colour. "Working…", "Not called" and "Failed" must read correctly in greyscale.
- **Do** keep Launch Blue to the action that starts a run and the controls that configure it.
- **Do** lift only top-level cards with the card shadow (`0 1px 2px rgb(15 23 42 / 0.04), 0 4px 16px -8px rgb(15 23 42 / 0.12)`), and keep everything inside them flat and bordered.
- **Do** define every new colour as a light/dark pair, and check 4.5:1 text contrast in both themes.
- **Do** step corner radii down with nesting: card 0.875rem, tile 0.75rem, control 0.375rem.
- **Do** use tabular numerals for counts, durations and clocks, and monospace only for model names, code and the run timer.
- **Do** use Bootstrap Icons, the one icon family already pinned, for every icon.
- **Do** use Ink text with a Border stroke for quiet buttons on dark surfaces. Bootstrap's outline-secondary grey falls to about 3:1 on the dark card (the Clear and theme-toggle buttons still use it).

### Don't:
- **Don't** render a run as chat bubbles or typing indicators. A run is a structured view of a team, its steps and an answer.
- **Don't** use neon "AI" styling: glowing gradient washes, glowing borders or sparkle effects. The small brand mark is the only gradient.
- **Don't** drift into grey enterprise admin: never strip agents of their crew colours or flatten a run into uniform grey tables.
- **Don't** add mascots, emoji or bouncy animation.
- **Don't** use a crew colour for anything that isn't that agent, or Answer Green for anything other than the answer and a completed run.
- **Don't** use dashed borders on finished elements, or solid borders on pending ones.
- **Don't** put Unicode arrows or symbols where an icon belongs. Draw them from Bootstrap Icons.
- **Don't** load a web font or any new third-party file unless it is pinned with an integrity hash in `CDN_STYLES` / `CDN_SCRIPTS` in `app.py`.
