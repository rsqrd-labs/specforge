<!--
Sanity document type: guide
Field mapping — apps/marketing/sanity/schemaTypes/documents/guide.ts
-->

- **slug**: `spec-for-coding-agents`
- **seo.title**: How to Write a Spec a Coding Agent Actually Follows
- **seo.description**: A coding agent doesn't push back on ambiguity — it resolves it silently and keeps building. Here's the structure that stops that from happening.
- **heading**: How to Write a Spec a Coding Agent Actually Follows
- **excerpt**: The gap between "the agent almost got it right" and "the agent got it right" is almost never the model. It's what you handed it.
- **author**: *(leave blank — attributes to Thought2Build)*
- **publishedAt**: `<set at actual publish time>`

---

## body (Markdown — paste into the Studio's Portable Text field)

Ask a coding agent to "add a way for users to invite teammates" and you'll get code back
in under a minute. It will probably run. It will almost certainly be wrong in some way you
didn't anticipate — no rate limit on invite emails, no handling for inviting someone
already on the team, an invite link that never expires, a role field you didn't ask for
but the model assumed you wanted. None of that is the model failing at coding. It's the
model resolving ambiguity you left in the prompt, silently, in whatever direction its
training data leans — and then building forty more lines on top of that guess before you
ever see it.

This is the single most common failure mode in agent-assisted development, and it has a
name now: spec drift. A written spec is how you close the gap before the agent ever opens
an editor.

### The spec is the contract, not the ticket

A Jira ticket that says "add team invites" is not a spec. A spec says what "done" means
precisely enough that two different people — or two different agent runs — would build
the same thing from it. That means:

- **Explicit requirements**, not implied ones. Not "invites should work," but "an invite
  is a signed link valid for 7 days; a second invite to the same email invalidates the
  first."
- **Explicit non-goals.** What you're *not* building matters as much as what you are —
  "no bulk CSV invite in this version" prevents an agent from scope-creeping into a
  feature you didn't ask for and now have to review.
- **Constraints stated as constraints**, not buried in prose. Rate limits, data
  retention rules, who's allowed to do what — if it's not called out as a constraint,
  an agent has no signal that it's non-negotiable.
- **Acceptance criteria a test can check.** "Works correctly" is not acceptance
  criteria. "An expired invite link returns a 410, not a 200 with an error message" is.

### Why this matters more, not less, with a capable model

It's tempting to assume a stronger model needs less specification — that Claude Code or
GPT-5-class agents are smart enough to infer the right thing. In practice the opposite
risk shows up: a more capable model is *more* confident in its guess, and a confident
wrong guess is harder to catch in review than an obviously broken one. The failure isn't
a syntax error you'll notice immediately. It's a plausible-looking pull request that does
something subtly different from what you meant, reviewed by someone who's skimming
because the code looks fine.

There's a compounding version of this problem too, and it's worth naming because it gets
worse as agent workflows get more automated: when one agent's output becomes the next
step's input — a spec agent handing off to a planning agent, a planning agent handing off
to a coding agent — any drift in the first step doesn't get corrected in the second. The
second agent has no way to know the first one went slightly off course. It builds
confidently on the wrong foundation, and by the time a human looks at the result, the
original ambiguity is three layers deep and much harder to spot.

### A structure that actually holds up

This is why Thought2Build's own pipeline is four stages, not one document. Each stage
closes a different kind of gap:

1. **SPEC** — functional and non-functional requirements, constraints, and acceptance
   criteria. This is where "invite should work" becomes the seven-day-signed-link
   requirement above.
2. **PLAN** — the architecture and sequencing decision. Which service owns invite state,
   how it's stored, what changes in the data model. A spec without a plan leaves the
   agent to invent architecture mid-implementation, which is exactly where silent
   assumptions creep in.
3. **HARNESS** — acceptance tests derived directly from the spec's criteria. This is the
   part most hand-written specs skip, and it's the part that turns "I think this is done"
   into "here's proof it's done."
4. **TASKS** — the plan broken into units small enough to review individually, each one
   traceable back to a specific requirement. A task that can't be traced to a requirement
   is a sign the plan invented scope the spec never asked for.

You don't need Thought2Build specifically to apply this discipline — the same four
questions (what exactly are we building, how will it be structured, how will we know it's
correct, and what are the individually-reviewable units of work) hold whether you're
writing markdown by hand or generating it. What the structure buys you either way is a
spec an agent can't quietly misread, because there's nowhere left for an unstated
assumption to hide.

### A short worked example

Compare these two inputs to a coding agent:

> **Vague:** "Add a way for users to invite teammates to their workspace."

> **Specified:** "Add workspace invites. Requirement: an owner or admin can invite by
> email; a non-member of the org cannot. Invite is a signed link valid 7 days; re-inviting
> the same email invalidates the prior link. Constraint: max 20 pending invites per
> workspace at a time — reject the 21st with a clear error, don't silently drop it.
> Acceptance: expired link → 410; invite already accepted → 409; happy path → 201 and the
> invitee's role matches what the inviter selected."

The second version isn't longer because it's padded — every sentence removes one decision
the agent would otherwise have had to make up. That's the actual difference between "the
agent almost got it right" and "the agent got it right the first time."

### Where to go from here

If you're handing specs off to Claude Code, Cursor, or GitHub Copilot specifically, the
next guide covers the handoff format each of those tools reads best — see
[Handing Off a Task to a Coding Agent Without Losing Requirements](/guides). If you'd
rather start from a structure instead of a blank page, the
[SaaS PRD template](/templates) walks through exactly this shape section by section. And
if you want to see this discipline applied to a real one-line idea rather than a snippet,
the [use cases hub](/use-cases) has worked examples end to end.

Or skip straight to trying it: [generate your own spec](/) from a rough idea and see
what a structured first draft actually looks like before you write the next ticket by
hand.

---

## faqs

1. **Q: Isn't writing a detailed spec slower than just prompting the agent directly?**
   A: It's slower than firing off one prompt, but almost always faster than the
   review-and-redo cycle that follows a vague one. The time spent specifying requirements
   up front is time you'd otherwise spend re-explaining them after the agent guesses
   wrong — the difference is you're paying that cost once, in a document you can reuse,
   instead of every time you re-prompt.

2. **Q: Do I need all four stages (spec, plan, harness, tasks) for a small change?**
   A: No — the discipline scales down. A one-line bug fix doesn't need a plan stage. The
   point isn't "always use four documents," it's "don't let ambiguity survive into the
   prompt." For small changes, a spec with explicit acceptance criteria is often enough.

3. **Q: What's the difference between a spec and a PRD?**
   A: In practice, very little — a PRD is usually product-facing (why we're building
   this, for whom) and a spec is usually build-facing (what exactly gets built, how we'll
   verify it). A good spec often includes both. The templates on this site combine them
   rather than forcing you to write two documents that say the same thing twice.

4. **Q: My coding agent has a memory/instructions file already (CLAUDE.md, AGENTS.md). Isn't that enough?**
   A: Those files are project-wide conventions — how to run tests, code style, repo
   layout. They don't replace a per-feature spec any more than a company style guide
   replaces a ticket description. Use both: the instructions file tells the agent how you
   work, the spec tells it what to build this time.

5. **Q: How specific is too specific?**
   A: If a requirement is dictating implementation details the agent should reasonably
   decide (which internal function name to use, for instance), that's over-specified —
   it belongs in the plan stage, not the spec. If a requirement is leaving room for the
   agent to guess at something a user would notice (what happens on an error, what the
   limits are), that's under-specified. The acceptance-criteria test is the fastest way
   to tell: if you can't write a pass/fail check for it, it's not specific enough yet.
