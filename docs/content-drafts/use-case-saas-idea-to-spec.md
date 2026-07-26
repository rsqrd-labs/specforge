<!--
Sanity document type: seoPage (section: use-case)
Field mapping — apps/marketing/sanity/schemaTypes/documents/seoPage.ts
NOTE on "examples" below: these are illustrative, representative snippets of the
KIND of output the pipeline produces — written for this page, not copy-pasted from a
live generation run. Do not present them as a verbatim export. (Verbatim, first-party,
unedited generation output belongs in a demoPage — see docs/content-drafts/README.md
for why those aren't drafted yet.)
-->

- **section**: `use-case`
- **slug**: `saas-idea-to-spec`
- **seo.title**: Turning a Rough SaaS Idea Into a Build-Ready Spec
- **seo.description**: A one-line SaaS idea and a structured spec are separated by a specific set of decisions. Here's how Thought2Build makes each one explicit instead of leaving it to guesswork.
- **heading**: From a One-Line SaaS Idea to a Build-Ready Spec
- **definition**: Thought2Build turns a rough SaaS idea — a sentence, not a document — into a structured SPEC covering requirements, constraints, and acceptance criteria, then a PLAN, HARNESS, and TASKS breakdown, so the idea is build-ready before an engineer or coding agent touches it.

---

## workflowSteps

1. **Name:** Start from the idea, not a template
   **Description:** You describe the SaaS product in a sentence or two — the actual
   words a founder would use, not a structured brief. The pipeline's job is to ask the
   questions a structured brief would have forced you to answer anyway: who's the user,
   what's the core action, what's explicitly out of scope for a first version.

2. **Name:** Generate the SPEC
   **Description:** Functional and non-functional requirements, constraints, and
   acceptance criteria come back as a structured document, not a paragraph. Vague ideas
   ("users can manage their team") become specific, checkable requirements ("an owner can
   remove a member; a removed member's active sessions are revoked within 60 seconds").

3. **Name:** Generate the PLAN
   **Description:** The spec becomes an architecture and sequencing decision — what gets
   built first, what depends on what, which parts of the system own which responsibility.
   This is the stage that stops "add billing" from silently becoming a rewrite of the
   auth system because nobody decided the boundary up front.

4. **Name:** Generate the HARNESS
   **Description:** Acceptance tests derived directly from the spec's criteria — the
   part that turns "I think this covers it" into something an engineer or agent can
   actually run and check.

5. **Name:** Generate the TASKS
   **Description:** The plan breaks into individually reviewable units, each traceable
   back to a specific requirement — small enough to hand to one engineer, one coding-agent
   session, or one GitHub issue at a time.

6. **Name:** Human review gate
   **Description:** Nothing advances automatically. Each stage is a checkpoint — you
   approve, refine, or regenerate before the next stage builds on it, so an early
   misunderstanding gets caught before it compounds through three more stages.

7. **Name:** Hand off
   **Description:** The finished artifacts export as-is — into a repository as tracked
   issues, or straight into a coding agent's context — so the handoff step doesn't
   require re-typing anything the pipeline already produced.

---

## examples

- **title**: Requirement — before and after
  **input**: "Users should be able to invite teammates."
  **output**: "FR-14: An owner or admin can invite a teammate by email. An invite is a
  signed link valid for 7 days. Re-inviting the same email invalidates the prior link.
  Constraint: a workspace may have at most 20 pending invites; the 21st attempt is
  rejected with a specific error, not silently dropped. AC-9: an expired invite link
  returns 410; an already-accepted invite returns 409."

---

## body (Markdown — paste into the Studio's Portable Text field)

Most "idea to spec" tools optimize for the wrong half of the problem: they make the
*document* appear quickly and leave the *decisions* for later. A generated PRD that reads
well but doesn't specify what happens when an invite link expires isn't a shortcut — it's
the same blank-page problem wearing nicer formatting.

The gap between "I have a SaaS idea" and "I have something build-ready" isn't really a
writing problem. It's a decision problem. Every real product idea contains dozens of
unstated decisions — what happens on the edge cases, who's allowed to do what, what's
explicitly out of scope for a first version — and someone has to make those decisions
explicit before an engineer, or a coding agent, can build the right thing on the first
try. Thought2Build's use case here is narrow and specific: take a SaaS idea from a
sentence to a document where those decisions have actually been made and written down,
not deferred.

### What "build-ready" means in practice

A spec is build-ready when a different engineer, reading it cold, would build the same
thing you would. That's a higher bar than "clear" — plenty of clear-sounding requirements
("fast," "secure," "intuitive") leave enormous room for two people to build different
things. Build-ready means:

- Requirements are specific enough to test, not just describe.
- Constraints are stated as constraints — rate limits, data retention, access rules —
  not buried in a sentence about something else.
- Non-goals are explicit, so the first version doesn't quietly grow scope nobody
  approved.
- There's a plan for how the pieces fit together, not just a list of features.

### Why this is a SaaS-specific problem, not a generic one

SaaS ideas have a particular shape that makes under-specification expensive: multi-tenant
data boundaries, billing edge cases, role-based permissions, and integration surfaces all
tend to hide inside a one-line feature description. "Add team billing" sounds like one
requirement. It's actually a dozen: what happens on a failed payment, who can change the
plan, what happens to data when a workspace downgrades, whether usage resets or carries
over. A generic idea-to-document tool won't surface those questions because it isn't
looking for them. A pipeline built around requirements, constraints, and acceptance
criteria as first-class fields — rather than free-form prose — has somewhere to put the
answer to each one, which makes it much harder to skip asking the question in the first
place.

### From spec to something you can actually hand off

The reason this use case doesn't stop at the SPEC stage is that a spec alone still leaves
the architecture and task-breakdown work undone — and that's usually where a second round
of unstated assumptions creeps in. The PLAN stage forces an explicit architectural
decision instead of leaving it to whoever implements first. The HARNESS stage turns the
spec's acceptance criteria into something checkable, so "done" has a test attached to it
instead of a feeling. And the TASKS stage breaks the plan into units small enough that a
reviewer can actually evaluate each one — which matters whether the person doing the work
is an engineer or a coding agent picking up one task at a time.

None of these stages are locked once generated. Each one is a human review checkpoint —
approve it, edit it, or regenerate it — because the discipline here isn't "trust the
first draft," it's "catch a wrong assumption at the cheapest possible point," which is
always before the next stage has built on top of it.

### Who this is actually for

This use case fits a founder scoping a first version before writing a single line of
code, a solo builder who wants a real spec instead of a mental model that lives only in
their head, or a small team's first attempt to standardize how they write specs before
they've accumulated three different formats across three different people. It's a
narrower claim than "AI writes your whole product" — it's specifically about closing the
gap between a rough idea and a document detailed enough that the next person (or agent)
in the chain doesn't have to guess.

### Related reading

For the discipline behind why this matters when a coding agent is doing the building, see
[How to Write a Spec a Coding Agent Actually Follows](/guides). If you'd rather see the
structure laid out section by section before generating your own, the
[SaaS PRD template](/templates) walks through the same shape. And for how this compares
across other jobs — writing a PRD that survives review, standardizing specs across a
team — see the rest of the [use cases hub](/use-cases).

Ready to see it applied to your own idea? [Generate a spec](/) from a one-line
description and see which of the decisions above it surfaces for your product.

---

## faqs

1. **Q: How rough can the starting idea actually be?**
   A: A sentence is enough to start — "a tool for freelancers to send invoices and get
   paid on time" is a realistic starting point. The pipeline's job is to surface the
   questions a one-line idea doesn't answer, not to require you to have already answered
   them.

2. **Q: Does this replace talking to users or doing product discovery?**
   A: No. It structures what you already know into something build-ready; it doesn't
   generate product-market fit. Feed it a validated idea and it gives you a spec worth
   building from. Feed it an unvalidated guess and you get a well-structured document
   describing an unvalidated guess — the structure doesn't manufacture the validation.

3. **Q: What if the generated spec gets something wrong about my product?**
   A: That's what the human review gate is for. Every stage — spec, plan, harness, tasks
   — is a checkpoint you approve, edit, or regenerate before it's treated as final.
   Nothing ships to the next stage automatically.

4. **Q: Can I hand the output straight to a coding agent?**
   A: Yes — the tasks stage is specifically sized for that: units of work small enough
   to review individually, each traceable back to a requirement, which is the format a
   coding agent needs to avoid re-deriving scope on its own.

5. **Q: How is this different from just asking a general-purpose AI assistant to write a PRD?**
   A: A general assistant will produce prose that sounds like a PRD. The difference here
   is structure as a first-class constraint — requirements, constraints, and acceptance
   criteria are distinct, checkable fields carried through to an architecture plan and a
   task breakdown, not a single free-form document you have to manually decompose
   yourself afterward.
