# Storyboard Keynote Redesign — Production Plan (issue #17)

> **Issue:** "Redesign storyboard presentation to match technical keynote standards."
> The current Storyboard deck is described as *basic, fragile, and not visually
> appealing*. The one hard, testable acceptance criterion is: **an architecture
> diagram with animated data flow must be included.** Everything else
> ("feels like an Apple/Google I/O keynote") is subjective and must be converted
> into concrete, checkable changes.

## 1. Where we are today (grounded in the code)

The Storyboard is a complete Phase-20 feature, built around one **non-negotiable
security model**: the LLM returns **inert structured data only**; *all* markup,
CSS, SVG, and PDF are owned by trusted application code that escapes every value.
See `backend/prompts/storyboard.py` (the `RENDERING SAFETY` block) and
`backend/services/pipeline/storyboard_renderer.py` (the module docstring).

| Surface | File | Today |
| --- | --- | --- |
| Strict payload schema | `backend/prompts/storyboard.py` (`StoryboardPayload`) | 6 fixed acts; ≥1 `architecture_reveal` diagram; 8 fixed layer **kinds** |
| Frontend types | `frontend/src/types/storyboard.ts` | mirror of the payload |
| Live deck | `frontend/src/components/storyboard/StoryboardDeck.tsx` | single-slide view, act tabs, themed accents, ambient orbs, CSS build animations |
| Architecture visual | `frontend/src/components/storyboard/ArchitectureReveal.tsx` | **static responsive grid of 8 glass tiles — no nodes, no edges, no flow** |
| Deck CSS | `frontend/src/index.css` (~L11179–13260) | reduced-motion block already present |
| Offline HTML/PDF | `backend/services/pipeline/storyboard_renderer.py` + `backend/templates/storyboard.html.j2` | mirrors the deck; architecture is the same static grid |

### The two real gaps
1. **No data-flow diagram.** `ArchitectureReveal` is a grid of cards with *no
   connectors between layers*. There is nothing to "flow" along. Adding particles
   to the grid would ship the same "basic" thing the issue complains about.
2. **The deck reads functional, not cinematic.** Every slide uses the same
   left-text / right-visual split; transitions are minimal.

### Two facts that make this cheap and safe
- **The 8 architecture layer *kinds* are a closed enum** (`client, frontend, api,
  data, llm, integrations, trust, recovery` — `REQUIRED_ARCHITECTURE_LAYERS` in
  `prompts/storyboard.py:57`, `ARCHITECTURE_LAYER_SEQUENCE` in
  `ArchitectureReveal.tsx:8`). Their interconnections are *architecturally
  universal*, so the **topology graph can be a constant in trusted code**. The LLM
  only fills `label` / `summary` / `source_refs` per node — it never describes
  edges. **No schema change, no new injection surface, no harness churn.**
- **The progressive-reveal machinery already exists but is dead.**
  `StoryboardDeck.tsx:493` hardcodes `currentStep = ARCHITECTURE_LAYER_SEQUENCE.length`,
  so all 8 layers always render at once. The `currentStep` prop is ready to drive
  a build-up animation.

## 2. Load-bearing decision

**Render a real node + edge architecture *topology graph* in trusted code, with
animated data flow along the edges, driven by the existing 8 fixed layer kinds —
with zero payload-schema change.**

The topology is a hardcoded constant keyed by the closed enum:

```
client ─▶ frontend ─▶ api ─┬─▶ data
                           ├─▶ llm
                           └─▶ integrations
trust:    boundary overlay spanning frontend·api·data·llm
recovery: backplane under api·data·llm·integrations
```

(The enum also allows a `group` kind that is **not** one of the canonical 8; the
topology constant must tolerate/ignore it — render it, if present, as an
unconnected annotation node, never crash.)

This is the only decision that determines whether we hit the issue's hard
requirement. Everything in §4 builds on it.

## 3. Non-goals (explicit, to prevent scope creep)
- **No LLM-driven edges/topology in v1.** The 8 kinds' relationships are universal;
  letting the model emit a graph buys little fidelity while adding pydantic
  validation, `harness/schemas/storyboard-payload.schema.json` lockstep, a privacy
  review (edges would be a new public-surface field), and a backward-compat /
  grandfather path for every existing Storyboard. Deferred to a possible future
  phase, behind the same canonical fallback.
- **No payload-schema, Pydantic, or harness-contract change at all in v1.** This is
  our strongest "production-ready" guarantee: backend generation, validation, the
  harness contract tests, and every already-generated Storyboard are **untouched**.
- **"Uplift the underlying technology"** (issue flavor text) is read as *the
  presentation redesign itself* — consciously scoped to rendering, not a pipeline
  or model change.

## 4. Phased plan

Each phase is independently shippable and leaves the deck in a working state.
Degradation paths (`prefers-reduced-motion`, WeasyPrint PDF, `sr-only`) are
**designed first as the static complete base**, with animation layered on top —
never bolted on after.

### Phase A — Architecture topology diagram (the hard requirement)
*Scope: `ArchitectureReveal.tsx`, new CSS, its test.*

1. Replace the card grid with an **inline SVG topology graph**. Node positions and
   edge paths are computed deterministically **in trusted code** from a hardcoded
   `ARCHITECTURE_TOPOLOGY` constant (nodes keyed by the 8 fixed kinds + the edge
   list above). LLM data only fills each node's `label` / `summary` / source badge.
2. **Static complete base state** (this is what ships to reduced-motion, PDF, and
   the a11y fallback): all nodes drawn, all edges drawn as solid connectors,
   trust boundary as a dashed enclosing region, recovery as a backplane band.
   Verifiable: 8 nodes + N edges present in the DOM/SVG with no JS timers running.
3. **Animated layer on top:**
   - **Data-flow particles** travelling along each edge path (CSS
     `offset-path`/`motion-path` or an SVG `<animateMotion>` per edge — both are
     trusted-code-only, no LLM input). Particles loop continuously.
   - **Build-up reveal** wired through the existing `currentStep` prop: nodes/edges
     fade in along the canonical client→recovery order on slide entry.
4. **Reduced-motion:** extend the existing `@media (prefers-reduced-motion)` block
   so particles and build-up are disabled and the static complete diagram shows
   immediately. (The deck already has this pattern at `index.css:~11483`.)
5. Keep the existing `architecture-reveal-fallback sr-only` ordered `<ol>` as the
   screen-reader description of the same nodes/edges.

### Phase B — Keynote polish (convert subjective → concrete)
*Scope: `StoryboardDeck.tsx`, `index.css`. No contract change.*

Each item is a checkable change, not a vibe:
- **Full-bleed architecture moment:** give the architecture slide its own
  full-width layout (extend `storyboard-slide--arch`) so the topology graph has
  room instead of being squeezed into the right-half visual panel.
- **Per-slide-type layouts:** distinct layouts for `hero`/`thesis`/`closing`
  (centered, oversized type) vs `product`/`walkthrough` (text + structured visual)
  vs `metric` (giant figure) — today all slide types share one split layout.
- **Cover / act-intro framing:** a title cover and a brief act-intro treatment when
  the active act changes, using the per-act accent rotation that already exists.
- **Typography scale + cinematic transitions:** larger headline scale; map the
  three existing transition classes (`fade`/`glide`/`rise`) onto more deliberate
  cross-slide motion.

### Phase C — Offline parity (same phase as A, not a trailing step)
*Scope: `storyboard_renderer.py`, `backend/templates/storyboard.html.j2`, renderer tests.*

The offline HTML/PDF renderer must draw the **same topology as static SVG** (the
Phase-A base state), or the downloaded deck diverges from the live one. WeasyPrint
cannot animate, so it consumes exactly the static-complete diagram. Build the SVG
node/edge geometry once in Python (mirroring the TS constant) and emit it through
the Jinja template's autoescape. No animation, no remote refs — consistent with the
existing `_build_arch_layers` security posture.

## 5. Test & blast-radius budget

**Will break (must be rewritten — say so up front):**
- `frontend/src/components/storyboard/ArchitectureReveal.test.tsx` — asserts the
  current card-grid structure.
- `frontend/src/components/storyboard/StoryboardDeck.test.tsx` — asserts current
  slide/visual layout; Phase B touches layout.
- `backend/tests/test_storyboard_renderer.py` — asserts the current grid markup in
  the offline deck.

**Untouched (the production-ready argument):**
- `backend/prompts/storyboard.py`, `backend/schemas/storyboard.py` — payload
  unchanged.
- `harness/schemas/storyboard-payload.schema.json` + harness contract tests — no
  contract drift.
- Every already-generated Storyboard renders under the new diagram with no
  migration, because the topology is derived from the fixed kinds it already has.

**New tests:** topology renders all 8 nodes + the canonical edges; `group`/unknown
kinds don't crash; reduced-motion yields the static complete diagram; offline SVG
matches the live node/edge set.

## 6. Acceptance criteria → verification

| Issue criterion | How it's verified |
| --- | --- |
| Architecture diagram **with animated data flow** | Phase A: SVG nodes + edges in DOM; particle animation present live, absent under reduced-motion; static-complete in PDF |
| Immersive / keynote feel | Phase B concrete items: full-bleed arch slide, per-type layouts, cover/act-intro, type scale |
| Robust | Static-complete base state + reduced-motion + `sr-only` fallback all render without JS; unknown layer kinds tolerated |
| Supports technical + exec audiences | Deck = sparse visuals; depth stays in speaker notes / appendix (unchanged); topology reads as a system diagram |
| Owner + public + offline parity | Phase C: same topology in live deck, public share, and PDF/HTML download |

## 7. Suggested sequencing
1. **A + C together** (the hard requirement and its offline mirror) — ship first;
   highest impact, lowest contract risk.
2. **B** as a follow-up polish PR.
3. Revisit LLM-driven edges (§3 non-goal) only if real decks show the canonical
   topology is too generic for specific products.
