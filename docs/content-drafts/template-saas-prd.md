<!--
Sanity document type: templatePage
Field mapping — apps/marketing/sanity/schemaTypes/documents/templatePage.ts
-->

- **slug**: `saas-prd-template`
- **seo.title**: SaaS PRD Template — Requirements, Architecture, Validation, Tasks
- **seo.description**: A PRD template with the sections that actually prevent scope drift and rework — requirements with acceptance criteria, an explicit architecture decision, a validation plan, and a task breakdown you can hand off directly.
- **heading**: SaaS PRD Template
- **templateName**: SaaS PRD Template
- **definition**: A SaaS PRD template that treats requirements, constraints, acceptance criteria, architecture, and task breakdown as distinct, checkable sections — the same structure Thought2Build generates from a one-line idea — so you can see the shape of a build-ready spec before writing your own.

---

## workflowSteps

1. **Name:** Fill in Overview and Non-Goals first
   **Description:** Before requirements, state what this version is *not* doing.
   Non-goals prevent the requirements section from silently growing scope nobody
   approved.

2. **Name:** Write requirements as testable statements
   **Description:** Each requirement should be specific enough that someone could write
   a pass/fail check against it. "Fast" and "intuitive" are not requirements; "search
   results return in under 500ms for a 10k-row dataset" is.

3. **Name:** Separate constraints from requirements
   **Description:** Rate limits, data-retention rules, compliance boundaries — anything
   non-negotiable — gets its own section so it isn't buried inside a requirement about
   something else.

4. **Name:** Commit to one architecture decision
   **Description:** Name the approach and the tradeoff you're accepting. A plan that
   hedges between two architectures isn't a plan — it's deferred to whoever implements
   first, which is exactly the ambiguity this template exists to remove.

5. **Name:** Define acceptance criteria per requirement
   **Description:** Every requirement in section 2 gets at least one linked acceptance
   criterion. If you can't write one, the requirement isn't specific enough yet — go
   back to step 2.

6. **Name:** Break the plan into tasks
   **Description:** Each task should be small enough for one person, or one coding-agent
   session, to complete and for a reviewer to evaluate on its own — and should trace back
   to a specific requirement ID.

---

## examples

- **title**: A single requirement, fully specified
  **input**: "Section 2, Requirement 7 (illustrative)"
  **output**: "FR-7: A workspace owner can downgrade from Team to Free plan.
  Constraint: downgrading is blocked if the workspace has more than 3 active members
  (Free plan's seat limit) — show a specific error naming the seat count, don't allow a
  silent partial downgrade. AC-7a: downgrade with ≤3 members succeeds and billing stops
  at the end of the current cycle. AC-7b: downgrade attempt with 4+ members returns a
  409 with the member count in the response body."

---

## body (Markdown — paste into the Studio's Portable Text field)

Templates are supposed to save you from a blank page. Most PRD templates fail at that in
a specific way: they give you section headers — "Overview," "Requirements," "Timeline" —
without showing you what a *good* answer to each section actually looks like. You end up
staring at "Requirements" the same way you'd stare at a blank document, just with a
heading now sitting above the blank space.

This template is built the other way around: every section below includes a worked
example of the kind of content that belongs there, not just the label. It's also
structured to match exactly what Thought2Build's own pipeline produces from a one-line
idea — SPEC, PLAN, HARNESS, TASKS — so if you generate your own from scratch, the shape
will look familiar, and if you write this one by hand, you'll produce something the
pipeline could have generated.

### 1. Overview

One paragraph: what you're building, for whom, and why now. Not a pitch — a plain
statement an engineer could read in ten seconds and understand the goal. Example:
*"A billing and seat-management system for the existing workspace product, so teams can
self-serve upgrade/downgrade instead of filing a support ticket for every plan change."*

### 2. Non-goals

Explicit statements of what this version deliberately excludes. This section prevents
the most common form of scope creep: an engineer or coding agent reasonably assuming a
feature belongs "since we're already in this area." Example: *"Not in this version:
usage-based billing, annual contracts, or a self-serve plan for more than 3 tiers."*

### 3. Requirements

Functional requirements, numbered, each specific enough to test. This is the section
most templates get vague on because vague requirements are faster to write — and the
most expensive place to be vague, because every unstated detail here becomes a decision
an implementer makes for you, possibly wrong. Write each one so a reader who's never seen
your product could still tell whether a given implementation satisfies it.

### 4. Constraints

Non-negotiable rules — rate limits, retention windows, compliance requirements, access
control boundaries. Keep these separate from requirements even though they're related;
a constraint buried inside a requirement's prose is easy for an implementer (human or
agent) to miss, because it doesn't read like a rule, it reads like detail.

### 5. Architecture / Plan

Name the actual decision: which service owns which responsibility, what changes in the
data model, what the sequencing is if this ships in phases. A plan section that says "we
could either do X or Y" isn't a plan — it's the requirements section again, wearing an
architecture-shaped costume. Commit to one, and note the tradeoff you're accepting by not
choosing the other.

### 6. Validation / Acceptance Criteria

For every requirement in section 3, at least one linked, checkable acceptance criterion.
This is the section that turns "I believe this is done" into "here's how we'd prove it."
If you find a requirement with no acceptance criterion you can write, that's a sign the
requirement itself needs to be more specific — go back and tighten it before moving on.

### 7. Tasks

The plan broken into units small enough to hand to one person, or one coding-agent
session, at a time — each one traceable back to a specific requirement ID from section 3.
A task with no traceable requirement is a sign the plan invented scope nobody approved in
section 1 or 2.

### Using this without Thought2Build

Nothing here requires the product — the structure itself is the value, and you can fill
it in by hand for any SaaS feature. What generating it instead buys you is speed on the
first draft and a built-in check that every requirement has an acceptance criterion and
every task traces to a requirement, which is easy to let slip when you're filling in a
template by hand under deadline pressure.

### Related reading

For the reasoning behind why each of these sections exists — especially constraints and
acceptance criteria — see [How to Write a Spec a Coding Agent Actually Follows](/guides).
To see this structure applied to a real one-line idea instead of a blank template, visit
[Turning a Rough SaaS Idea Into a Build-Ready Spec](/use-cases). Looking for a narrower
template — an API spec, or an internal tool brief — check the rest of the
[templates hub](/templates).

Want this filled in for your actual idea instead of a generic example? [Generate a spec](/)
from a one-line description and get a first draft in this exact structure.

---

## faqs

1. **Q: Do I need all seven sections for every feature?**
   A: No — scale it to the size of the change. A small feature might collapse
   Architecture and Tasks into a couple of sentences each. What shouldn't get cut,
   regardless of size, is at least one acceptance criterion per requirement — that's the
   section that prevents "I think this is done" disputes later.

2. **Q: What's the difference between a Requirement and a Constraint?**
   A: A requirement describes something the system does ("a user can invite a teammate").
   A constraint limits how it can be done ("no more than 20 pending invites per
   workspace"). Mixing them into one section makes constraints easy to miss during
   implementation, because they don't read like rules — separating them fixes that.

3. **Q: Can I use this template for a non-SaaS project?**
   A: Yes — the section structure (requirements, constraints, architecture, validation,
   tasks) isn't SaaS-specific. The examples in each section lean SaaS because that's the
   most common request, but a mobile app or an internal tool follows the same shape.

4. **Q: Why put Non-Goals so early, before Requirements?**
   A: Because scope creep almost always shows up as a "reasonable-sounding" addition to
   the requirements list, and it's much easier to catch if there's already an explicit
   non-goals statement to check it against. Writing non-goals after requirements means
   you're checking your list against nothing.

5. **Q: How specific should the Architecture section be?**
   A: Specific enough that two engineers reading it would build the same system — which
   service owns which data, what the API boundary looks like, what changes in the schema.
   It doesn't need line-level implementation detail; it does need to make the actual
   structural decision instead of listing options.
