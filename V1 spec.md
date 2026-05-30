
---

tags:

- specforge
- spec
- v1
- asdd created: 2026-04-25 status: final version: 1.5.0 stage: spec

---

# SpecForge V1 — SPEC.md

> [!tip] Core Hypothesis Developers find enough value in the ASDD pipeline output to use it in real projects.

---

## Table of Contents

- [[#1. Overview]]
- [[#2. Goals and Non-Goals]]
- [[#3. Users]]
- [[#4. User Flows]]
- [[#5. Pipeline Stages — Detailed Specification]]
- [[#6. Stage Interaction Modes]]
- [[#7. Quality and Evals]]
- [[#8. Authentication and Accounts]]
- [[#9. Credit System and Billing]]
- [[#10. Data Models]]
- [[#11. API Contracts]]
- [[#12. Non-Functional Requirements]]
- [[#13. Assumptions]]
- [[#14. Out of Scope for V1]]

---

## 1. Overview

SpecForge is a web-based agentic workspace that transforms a raw problem statement into a complete, agent-ready development blueprint through a structured four-stage AI-driven pipeline. The pipeline follows the ASDD (Agentic Specification-Driven Development) methodology, producing four interconnected documents in a fixed dependency order.

```
SPEC.md → PLAN.md → HARNESS → TASKS.md
```

V1 validates one core hypothesis: developers find enough value in the pipeline output to use it in real projects.

Once the four-stage workspace is finalised, SpecForge can also generate premium downstream artifacts from the same source of truth: exports for builders, public links for reviewers, and Storyboard keynotes for presenting the product vision and architecture to an audience.

---

## 2. Goals and Non-Goals

### Goals

- Generate high-quality SPEC.md, PLAN.md, Harness skeleton, and TASKS.md from a problem statement through an AI-driven collaborative workspace
- Allow users to iteratively refine each stage through generate, refine, and regenerate interactions before finalising
- Enforce the correct pipeline dependency order — SPEC → PLAN → HARNESS → TASKS — so that tasks always reference specific harness tests as their definition of done
- Provide quality signals on every generation through automated online evals and quality score badges
- Support all three major AI providers — Anthropic, OpenAI, and Google — with user-selectable models
- Authenticate users via Google OAuth and enforce a 50-credit free tier
- Allow users to export all four finalised documents as a zip file for use with coding agents
- Allow users to push a finalised workspace directly to a new GitHub repository, with each task created as a GitHub Issue, when they have connected their GitHub account
- Lift the baseline quality of every spec by asking the user a small set of clarifying questions before the first stage generation runs
- Annotate every generated task with a priority label and an effort estimate, and aggregate them into a project-level effort summary, so the TASKS output is a plan a user can execute against rather than a flat list
- Let users publish a read-only public link to any finalised workspace so a spec can be shared with cofounders, investors, or clients without granting an account
- Let users download a branded PDF of the finalised spec for audiences that do not work with Markdown
- Offer a small library of starter templates on the landing dashboard so a first-time user can begin from a worked example rather than a blank textarea
- Surface harness coverage prominently in the workspace summary so the harness stage is recognisable as a differentiator rather than a buried artefact
- Allow users to purchase additional credits in a single pack (200 credits for $9, valid 30 days from purchase date) via Stripe Hosted Checkout so the product has a clear monetisation path from V1
- Allow users to generate a paid **Storyboard**: a browser-native, shareable, downloadable product keynote presentation that turns a finalised workspace into a stunning big-tech-style launch narrative with architecture diagrams, presenter notes, source-backed claims, and a technical appendix

### Non-Goals for V1

> [!warning] Explicitly Out of Scope These are not deferred — they are deliberately excluded from V1 to maintain focus.

- Subscriptions and recurring billing (one-time credit packs are in scope; subscription management is not)
- Approval workflows
- Jira integration
- Team workspaces or shared pipelines
- Chat panel per stage
- Mobile responsiveness
- Self-host documentation
- Bidirectional sync
- Enterprise features of any kind
- Native PowerPoint / Apple Keynote file export for Storyboard; V1 Storyboards are browser-native HTML/PDF/notes artifacts

---

## 3. Users

### Primary User — The Developer

A software developer or technical founder starting a new project or feature who wants to produce a complete, structured development blueprint before writing any code. They are familiar with AI coding tools and looking for a better way to give their coding agent the context it needs to work effectively.

They understand TDD and what a test harness is. They may not have heard of ASDD specifically but will understand the value immediately when they see tasks linked to specific tests.

They are evaluating SpecForge as a tool that will save them hours of planning and prompt engineering work.

### Secondary User — The Technical Lead

A tech lead or senior engineer at a small team who wants a structured, repeatable process for turning product requirements into engineering-ready work. They want something to use before handing work off to junior developers or coding agents.

> [!note] This user is the one who will push for a Team subscription in V2.

---

## 4. User Flows

### 4.1 First Visit — Unauthenticated

```
Land on landing page
        ↓
Read methodology explanation + watch demo
        ↓
Click "Sign in with Google"
        ↓
Complete Google OAuth
        ↓
Redirect to dashboard (welcome state)
        ↓
Account created with 50 free credits
```

No credit card required. No onboarding form. No profile setup step.

### 4.2 Creating a Workspace

User clicks **Create Workspace** on the dashboard. Prompted for:

|Field|Constraints|
|---|---|
|Workspace name|Required, max 200 chars|
|Problem statement|Required, min 50 chars, max 10,000 chars|
|AI provider|Anthropic / OpenAI / Google|
|Model|Filtered by selected provider|

A placeholder in the problem statement field guides them on what a good problem statement looks like.

**Start from a template (optional):** Above the form, a strip of starter templates ("Stripe-like checkout," "Linear-like ticketing," "Slack bot for X," etc.) is available. Clicking a template card pre-fills the workspace name and problem statement, which the user can then edit before continuing. See §4.11.

They click Create and land in the workspace view.

### 4.3 The Workspace View

Two-panel layout:

**Left panel — Stage Navigator** Vertical list of the four stages in order. Each stage shows its current status. Only the active stage and prior finalised stages are accessible. Downstream stages are locked until dependencies are finalised.

```
● SPEC.md     ← finalised (green)
● PLAN.md     ← in progress (yellow)
○ HARNESS     ← locked (grey)
○ TASKS.md    ← locked (grey)
```

**Right panel — Stage Editor** Full-height CodeMirror markdown editor. Above: stage name, status badge, quality score badge, action buttons. Below: generate / refine / finalise toolbar.

### 4.4 Generating a Stage

```
Click Generate
        ↓
[Spec stage only] Spec Clarification sub-flow (see below)
        ↓
Credit deduction warning shown (10 credits + remaining balance)
        ↓
User confirms
        ↓
Tokens stream into editor in real time via SSE
        ↓
Generation completes
        ↓
Online eval runs asynchronously
        ↓
Quality badge updates (e.g. 87/100)
```

> [!tip] Refine Flow User selects text → types instruction → clicks Refine → diff appears → Accept or Reject. Costs 3 credits. Credits only finalised on acceptance.

User satisfied → clicks **Finalise** → stage marked finalised → next stage unlocks → green checkmark in Stage Navigator.

#### 4.4.1 Spec Clarification (Spec stage only)

The single largest determinant of spec quality is the depth of the problem statement. To raise the floor before the pipeline runs, the **first** generation of the spec stage is preceded by a lightweight clarification step:

```
User clicks Generate on the spec stage (first time)
        ↓
Backend asks judge model for 3–5 targeted questions about
the problem statement (who the user is, the hard constraint,
what success looks like, etc.)
        ↓
Modal opens with the questions, each as a short-answer field
        ↓
User answers — or clicks "Skip" to proceed with the raw
problem statement as today
        ↓
Answers are concatenated as additional context and passed
into the spec generation prompt alongside the original
problem statement
        ↓
Standard generation flow continues (credit warning, stream, eval)
```

**Constraints:**

- Questions are produced by the same judge model used for evals (Claude Haiku · GPT-4o Mini · Gemini Flash), so the additional latency is small (typically under 3 seconds) and the cost is sub-cent.
- The clarification call is **free** — no credits deducted. Only the subsequent spec generation costs the standard 10 credits.
- The clarification step runs only on the **first** spec generation per workspace. Regenerating the spec re-uses the captured answers and does not re-prompt.
- The user can always click **Skip** to bypass the step. The product is usable without ever answering a clarifying question.
- Q&A pairs are persisted on the workspace so they remain visible to the user and continue to inform regenerations.

> [!note] The clarification call is best-effort. If the judge model is unavailable or times out (>5s), the modal is skipped automatically and the user is taken straight to the standard generate flow.

### 4.5 Human Review Gate

After SPEC is finalised and before PLAN generation begins, a mandatory review prompt appears:

> _"You are about to generate PLAN.md from this spec. Take a moment to review the spec above. Once PLAN is generated it will be based on this version. Are you ready to proceed?"_

This gate appears once per stage transition. It is a deliberate pause, not a hard blocker.

### 4.6 Completing the Pipeline

User proceeds through PLAN → HARNESS → TASKS in order. Same pattern at each stage: generate, review, refine as needed, finalise.

**HARNESS generation** — quality badge includes a coverage score (% of spec requirements with a corresponding test). If below 80%, uncovered requirements are listed below the editor as action items.

**TASKS generation** — a task-harness validation runs automatically. Each task references specific harness tests by name. Flagged tasks (missing test references or references to nonexistent tests) are listed as action items.

Every generated task additionally carries a **Priority** label (`MUST` / `SHOULD` / `COULD`) and an **Estimate** as a T-shirt size (`S` / `M` / `L` / `XL`). A project-level summary appears at the top of the TASKS view aggregating the estimates into a rough effort range (e.g. *"~3 weeks of effort: 1×XL · 4×L · 7×M · 3×S"*) and counting MUST-only tasks for a minimum-viable cut. See §5.4 for the per-task fields.

### 4.7 Staleness

```
User edits finalised SPEC.md
        ↓
PLAN.md  → marked STALE ⚠
HARNESS  → marked STALE ⚠
TASKS.md → marked STALE ⚠
        ↓
Banner per stage:
"This stage was generated from a previous version
of SPEC.md. Regenerate or keep as-is?"
```

> [!warning] Nothing is regenerated automatically. The user decides per stage.

### 4.8 Export

Once all four stages are finalised the export and launch options activate in the workspace header:

```
[↓ Download ZIP]   [↑ Export to GitHub]   [📄 Export PDF]   [🔗 Share Public Link]   [🎬 Create Storyboard]
```

No credits are deducted for ZIP, GitHub, PDF, or public share. **Create Storyboard** is a paid generation flow described in §4.13, because it uses the LLM pipeline to create a new launch keynote artifact. The ZIP and GitHub paths produce the same file layout.

**File layout (ZIP and GitHub repo root):**

```
├── SPEC.md
├── PLAN.md
├── TASKS.md
└── harness/
    ├── <setup-file>          ← conftest.py · vitest.setup.ts · spec_helper.rb
    ├── factories/
    ├── tests/
    │   ├── unit/
    │   ├── integration/
    │   ├── e2e/
    │   ├── security/
    │   ├── observability/
    │   └── performance/
    ├── contract/
    └── schemas/
```

#### ZIP Download

Click **Download ZIP** → browser downloads `specforge-{workspace-id}.zip` immediately. No configuration required. Always available on a finalised workspace regardless of GitHub connection status.

#### Export to GitHub

Available only when a GitHub account is connected (see §4.9). Click **Export to GitHub** → a configuration modal opens:

```
Repo name:    [my-project          ]   ← pre-filled from workspace name
Visibility:   ● Public  ○ Private
              Will create 12 issues — one per task
                    [Cancel]  [Export →]
```

On confirm:

```
SpecForge creates a new GitHub repo
         ↓
Commits all files to the default branch in one commit
         ↓
Creates one GitHub Issue per task from TASKS.md
         ↓
Success: "Exported to github.com/username/repo-name"
         [Open on GitHub ↗]   [Done]
```

**Re-export (idempotent):** If the workspace was previously exported to GitHub, the modal pre-fills the existing repo name (read-only) and notes the previous export date. Re-exporting updates files and issues in the existing repo rather than creating a new one. New tasks are created as new issues; existing tasks are updated in place. Issues are never deleted.

**GitHub Issue format:** Each `T-NNN` task becomes one issue titled `T-NNN: {task title}`, with the full task body — phase, risk, description, steps, acceptance criteria, and harness references — preserved as the issue body. Issues are created in task order.

#### Export PDF

Click **Export PDF** → backend renders SPEC.md, PLAN.md, and TASKS.md to a single branded PDF and the browser downloads `specforge-{workspace-name}.pdf` immediately. The harness directory is **not** included in the PDF — PDFs are for human audiences (founders, clients, investors, PMs) who want a readable artefact, not a runnable scaffold.

The PDF carries the Modern Indica visual identity: cover page with workspace name and provider used, table of contents, syntax-highlighted code blocks, and a footer crediting SpecForge with a link back to the marketing site.

Always available on a finalised workspace regardless of GitHub connection status. Rate-limited per §12.

#### Share Public Link

Click **Share Public Link** → a modal opens:

```
Public read-only link

[ https://specforge.app/p/k3f9a2 ]   [Copy]

● Public  ○ Disabled

Anyone with the link can view your finalised SPEC.md,
PLAN.md, HARNESS coverage, and TASKS.md. They cannot
see your credit balance, billing, account email, other
workspaces, or any draft / pre-finalisation content.

                                      [Close]
```

When the user enables sharing the workspace gets a random 6-character public slug (`/p/{slug}`). Visitors to that URL see a read-only rendered view of the finalised stages in the Modern Indica design — no login required, no credits consumed, no editing affordances. The judge-model eval scores and harness coverage figure are shown alongside as social proof.

**Constraints:**

- Only workspaces with **all four stages finalised** can be shared. Toggling sharing on a workspace with any draft / locked / stale stage is rejected.
- The slug is opaque and unguessable (sufficient entropy to resist enumeration). It is not derived from the workspace ID.
- Re-enabling sharing after a disable cycle reuses the same slug, so previously shared URLs continue to work unless the user explicitly rotates the slug from the modal.
- Search engines are excluded from the public view via `noindex, nofollow` meta tags. The marketing site explicitly does not crawl `/p/*`.
- The public view is cached at the edge for low-cost serving; cache is invalidated when the user re-finalises any stage or toggles sharing off.

### 4.9 GitHub Connection

A GitHub connection is required for the Export to GitHub flow. Users connect once from Settings.

```
Settings → Integrations → Connect GitHub
         ↓
GitHub OAuth consent (scope: repo, read:user)
         ↓
User authorises SpecForge
         ↓
Token stored encrypted in key vault
         ↓
Settings shows: "✓ Connected as @username"  [Disconnect]
```

Disconnecting removes the stored token. Previously exported repos and issues on GitHub are not affected. If a GitHub token is found to be expired or revoked during an export attempt, it is deleted automatically and the user is prompted to reconnect.

### 4.10 Dashboard

Workspace cards show: name, creation date, AI provider used, pipeline progress indicator (which stages are finalised). User can return to any workspace by clicking its card.

Above the workspace grid, a **Start from a template** strip surfaces the curated starter templates (see §4.11). For a first-time user with an empty workspace list this strip is the dominant element on the dashboard.

Credit balance shown prominently. A **Buy Credits** button is always visible next to the credit meter for users who want to top up proactively. When credits expire or run out:

> [!danger] Credit Exhaustion State "You're out of credits. Buy 200 credits for $9 →" links directly to `/billing`. No waitlist, no form — one click to Stripe Checkout.

When a purchased pack is within 7 days of expiry, a warning chip appears on the credit meter: "⚠ X credits expire in N days — Buy more →". This gives users enough lead time to purchase a new pack before their current one lapses mid-pipeline.

### 4.11 Starter Templates

A curated library of worked starter templates is available on the dashboard and on the workspace creation form. Each template is a hand-tuned problem statement that produces a high-quality spec on first generation.

```
Dashboard → "Start from a template" strip
        ↓
User clicks a template card (e.g. "Stripe-like checkout")
        ↓
Workspace creation form opens, pre-filled with:
  - workspace name (editable)
  - problem statement (editable)
  - suggested provider and model (editable)
        ↓
User edits if desired, clicks Create
        ↓
Standard workspace creation flow continues
```

**Constraints:**

- Templates are **system-owned and curated** in V1. End users cannot create, edit, or publish their own templates. User-authored templates are explicitly V2 (see §14).
- Templates are content-only: they pre-fill the form fields. They do not produce a pre-generated spec; the user still runs the four-stage pipeline.
- Each template carries: name, short description, category (auth · payments · content · realtime · agent · tooling), suggested provider/model, and the seed problem statement.
- The template library is read-only from the user's perspective and ships with the application. Adding or rotating templates is a deploy-time operation.
- V1 ships with 6–10 templates covering the most common SaaS / agent / developer-tool starting points.

### 4.12 Credit Purchase Flow

Users who exhaust their free credits — or want to top up proactively — use the Billing page at `/billing`.

```
Dashboard → click "Buy Credits" (credit meter) or visit /billing directly
        ↓
Billing page shows:
  - Current credit balance + expiry info (if any active pack)
  - Single package card: 200 credits · $9.00 · valid 30 days
        ↓
User clicks "Buy Credits →"
        ↓
POST /billing/checkout → redirect to Stripe Hosted Checkout
        ↓
User enters card details on Stripe's page (no card data on SpecForge servers)
        ↓
Stripe redirects back to /billing?session_id={id}&success=1
        ↓
Billing page polls GET /billing/status?session_id={id} (2 s interval, max 10 attempts)
until status = 'active'
        ↓
Success state: "200 credits added. Expires {date}."
Balance updates immediately.
```

> [!important] Webhook is the authoritative credit source
> Credits are granted by the backend on receipt of Stripe's `checkout.session.completed` webhook — not by the success redirect. The redirect polling is only to confirm the webhook has already processed. If the user closes the tab immediately after payment, the webhook still fires and credits are still granted.

**Billing page sections:**

1. **Balance summary** — current credit count, earliest pack expiry date (if within 14 days), link to ledger history
2. **Package card** — single package: 200 credits · $9.00 · 30-day validity · "Buy Credits →" CTA. Package details are loaded from `GET /billing/package` so the price can be updated server-side without a frontend deploy.
3. **Purchase history** — accordion list of past packs with status badges: `Active` (green, shows credits remaining and expiry date) · `Expired` (grey) · `Refunded` (yellow)

**Cancelled checkout:** If the user cancels on Stripe's page, they are redirected to `/billing?cancelled=1`. The pending pack row is created but remains `status='pending'` until the checkout window expires on Stripe's side. No credits are granted for a cancelled session.

### 4.13 Storyboard — Product Keynote

Storyboard is a paid, one-click product keynote generator. It turns a completed SpecForge workspace into a stunning browser-native launch presentation that feels like a big-tech product keynote while remaining grounded in the actual SPEC, PLAN, HARNESS, and TASKS artifacts.

Storyboard is **not** a generic slide template. It is a product-specific launch narrative with technical depth, architecture diagrams, speaker notes, source-backed claims, and downloadable presentation materials.

```
All four stages finalised
        ↓
User clicks "Create Storyboard"
        ↓
Credit confirmation modal shown (25 credits + remaining balance)
        ↓
User confirms
        ↓
Storyboard generation runs from SPEC + PLAN + HARNESS + TASKS
        ↓
Browser keynote opens when ready
        ↓
User can present, share, download, or regenerate
```

**Credit model:**

|Action|Cost|Notes|
|---|---:|---|
|Generate Storyboard|25 credits|Full keynote, notes, demo script, appendix, diagrams|
|Regenerate full Storyboard|25 credits|Requires confirmation; prior version preserved|
|Regenerate one Storyboard section|5 credits|Only available after a Storyboard exists|
|Present, share, download PDF/HTML/notes/appendix|0 credits|Included after generation|

Credits are pre-checked before generation. The debit is created when generation starts and is refunded if generation fails before a usable Storyboard is persisted. Refreshing the page or retrying status polling never double-charges. If any upstream stage is re-finalised after Storyboard generation, the Storyboard is marked **stale** and the UI prompts the user to regenerate before presenting or sharing.

#### Storyboard Structure

The main keynote has six acts:

1. **Opening Thesis**
   - Product name
   - Category framing
   - Why now
   - Big promise

2. **Product Vision**
   - User problem
   - Target audience
   - Before/after transformation
   - Product principles

3. **Product Walkthrough**
   - Hero workflow
   - Feature reveals
   - Demo-style journey
   - Product-specific interaction moments

4. **Technical Architecture**
   - Cinematic architecture reveal
   - System components
   - Data flow
   - Integrations
   - Scaling model
   - Technical tradeoffs

5. **Trust, Security, Reliability**
   - Auth/access model
   - Data boundaries
   - Threat model highlights
   - SLOs
   - Failure handling
   - Recovery model

6. **Launch Close**
   - Final product statement
   - What ships
   - What comes next
   - Memorable closing line

Validation and execution planning are intentionally **not** top-level keynote acts. HARNESS and TASKS still inform the Storyboard, but they appear as supporting evidence, demo details, Q&A backup, and technical appendix material rather than as project-review sections.

#### Cinematic Architecture Reveal

Every Storyboard must include at least one architecture diagram. The primary diagram is not presented as a static documentation block; it reveals the product architecture in layers:

1. User/client layer
2. Frontend experience
3. API/backend services
4. Data stores
5. LLM/provider layer, when applicable
6. External integrations
7. Trust boundaries
8. Failure and recovery paths

The MVP representation is structured diagram JSON or Mermaid generated by the backend and rendered by the browser deck. The visual style is upgraded by the frontend renderer: premium spacing, large labels, animation timing, and product-specific color/shape treatment. Raw Mermaid syntax is never shown to viewers unless they open a technical/source view.

#### Presentation Experience

The Storyboard viewer is browser-native and requires no PowerPoint, Apple Keynote, Google Slides, or browser extension.

Core modes:

- **Launch page** — shareable first screen with product title, one-line promise, architecture preview, and buttons for Present / Download / Notes.
- **Presentation mode** — full-screen deck with keyboard navigation, smooth section transitions, and cinematic architecture reveal.
- **Presenter mode** — current slide, next slide preview, speaker notes, timer, transition cues, suggested pauses, demo cues, and backup talking points.
- **Source layer** — optional overlay showing whether a claim came from SPEC, PLAN, HARNESS, or TASKS. Public viewers can inspect source attribution only when the owner enables it, and never see private account, billing, or draft data.

#### Generated Artifacts

Each Storyboard stores and exposes:

- `storyboard.json` — structured presentation payload, sections, slides, diagrams, theme, and source map
- `storyboard.html` — downloadable offline browser package
- `storyboard.pdf` — static audience handout
- `speaker-notes.md` — presenter talk track
- `speaker-notes.pdf` — printable presenter notes
- `demo-script.md` — step-by-step product demo script
- `technical-appendix.md` — architecture, security, reliability, validation, task, and Q&A backup notes

The main slides stay visually sparse: one idea, one strong visual, minimal text. Speaker notes and the appendix carry the depth. This is the standard that makes Storyboard feel like a keynote rather than a report.

#### Visual Identity Generator

Every Storyboard receives a product-specific visual identity inferred from the workspace:

- Color palette
- Typography mood
- Diagram style
- Section transition style
- Product motif
- Tone based on category: enterprise SaaS, AI product, developer tool, infra platform, fintech, content product, realtime collaboration product, etc.

The renderer may use curated themes, but the output must never look like a generic deck template. Copy, diagrams, demo moments, and source-backed claims are always specific to the workspace.

#### Product Demo Script

Storyboard generates a practical demo path:

- What screen or product state to start on
- What user action to take
- What to say during each moment
- When to pause
- Which capability or architecture point is being demonstrated
- Which slide the live demo moment supports

The demo script is downloadable and visible in Presenter mode. It is not shown in the main public keynote unless the owner enables source/appendix access.

#### Source-Backed Confidence Layer

Every major claim, architecture element, workflow, and trust statement in Storyboard has a source map back to one or more finalised artifacts:

|Source|Typical use|
|---|---|
|SPEC|Problem framing, target users, product promise, user flows|
|PLAN|Architecture, data flow, technical decisions, integrations, tradeoffs|
|HARNESS|Validation confidence, critical behavior, reliability/test evidence|
|TASKS|What ships, implementation shape, demo sequence, next-step context|

The source layer exists to make the keynote defensible without making the visible presentation heavy. Source excerpts are sanitized, bounded in length, and never include draft content.

#### Sharing and Downloads

Storyboard sharing is separate from the existing public workspace share link. A user may share the workspace bundle, the Storyboard, both, or neither.

```
Storyboard → Share
        ↓
[ https://specforge.app/sb/k3f9a2 ]   [Copy]

● Public  ○ Disabled

Anyone with the link can view the launch page,
present the browser keynote, and download only the
artifacts the owner has enabled.
```

Owner controls:

- Public on/off
- Rotate public slug
- Allow PDF download
- Allow speaker-notes download
- Allow technical-appendix download
- Allow source-layer access

Default public permissions: presentation and PDF download enabled; speaker notes, technical appendix, and source layer disabled until the owner opts in.

Public Storyboard pages are `noindex, nofollow`, rate-limited, and served with a strict CSP. Public visitors cannot see the owner's account email, credit balance, billing history, private workspace list, draft stages, or previous Storyboard versions.

#### Signature Slide Moments

Every Storyboard must deliberately include two or three memorable keynote moments:

- The bold opening promise
- The before/after transformation
- The animated architecture reveal
- The trust/reliability reveal
- The closing line

The acceptance bar is human and product-facing: one click should produce a Storyboard the user would feel proud to present to customers, investors, teammates, or technical leadership.

---

## 5. Pipeline Stages — Detailed Specification

### 5.1 SPEC.md

**Input:** Problem statement from the user, plus optional Spec Clarification Q&A (see §4.4.1)

**Output:** Structured specification document

**Required sections:**

- Overview and purpose
- Target users
- Core user flows
- Data models
- API contracts (inputs, outputs, error cases)
- Non-functional requirements (performance, security, scale)
- Out of scope
- Assumptions made

**Eval checks:**

- [ ] All required sections present
- [ ] Scope aligned with original problem statement
- [ ] Assumptions explicitly listed
- [ ] Data models defined with field names and types
- [ ] Non-functional requirements present and specific
- [ ] No unexplained jargon

> [!note] Human Review Gate Mandatory after SPEC is finalised before PLAN generation begins.

---

### 5.2 PLAN.md

**Input:** Finalised SPEC.md

**Output:** Architecture and planning document

**Required sections:**

- Architecture overview
- Tech stack with justification for each choice
- Module breakdown
- Data flow and component interaction
- Risks and mitigations
- Open questions

**Eval checks:**

- [ ] Tech stack choices justified, not just listed
- [ ] Module breakdown specific enough to act on
- [ ] Risks realistic with concrete mitigations
- [ ] No circular dependencies in module breakdown
- [ ] Consistent with SPEC.md — no contradictions

---

### 5.3 HARNESS

**Input:** Finalised SPEC.md + finalised PLAN.md

**Output:** Test scaffold directory with starter test files, type contracts, and schema stubs

**Output structure:**

```
harness/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── types/
└── schemas/
```

**Eval checks:**

|Check|Threshold|
|---|---|
|Spec requirement coverage|Warning < 80%, Error < 60%|
|Trivial always-passing tests|Must be zero|
|Edge cases on critical paths|Must be present|
|Type contracts for all data models|Must be complete|
|Test names map to spec requirements|Must be descriptive|

> [!tip] Coverage Action Items Uncovered requirements shown in red below the editor with a suggested prompt: _"Add a test for [requirement]."_ Clicking the suggestion opens a pre-filled refine prompt.

---

### 5.4 TASKS.md

**Input:** Finalised SPEC.md + finalised PLAN.md + finalised HARNESS

**Output:** Ordered list of atomic tasks, each referencing specific harness tests as machine-verifiable done conditions

> [!danger] Task 1 Rule Task 1 is **always**: Set up the project structure and confirm the harness runs (all tests fail as expected — red phase).

**Required fields per task:**

```
## Task N — [Title]

Priority: MUST | SHOULD | COULD
Estimate: S | M | L | XL          ← T-shirt size
Input:    [files or dependencies]
Goal:     [what to build]
Tests:    [specific test names from harness]
Done when: All named tests pass with no skips or mocks
Reference: SPEC.md §N · PLAN.md §N
```

**Project-level summary block** is emitted at the top of TASKS.md:

```
## Effort Summary

Estimate range: ~3 weeks
Tasks:          15 total · 6 MUST · 7 SHOULD · 2 COULD
Sizes:          1×XL · 4×L · 7×M · 3×S
Minimum cut:    Ship MUST-only → ~9 days
```

**Estimate calibration:** T-shirt sizes map to a rough developer-day range used to compute the summary band: `S` = 0.5–1d · `M` = 1–3d · `L` = 3–7d · `XL` = 7d+. The summary is informational only — it is not a contract.

**Eval checks:**

- [ ] Every task references at least one harness test by name
- [ ] Referenced tests exist in the harness output
- [ ] No task has a vague done condition
- [ ] Tasks in valid dependency order
- [ ] First task is always harness setup
- [ ] Every task carries a Priority and an Estimate field with a value from the allowed enum
- [ ] At least one task is labelled `MUST` (the minimum-viable cut is non-empty)

---

## 6. Stage Interaction Modes

### Generate

- **Cost:** 10 credits
- **Available when:** Stage is unlocked and not yet finalised
- **Behaviour:** Streams output token by token into the editor via SSE. Online eval runs on completion. Quality badge updates.
- **On failure:** Credits refunded, clear error shown with one-click retry.

### Refine

- **Cost:** 3 credits (only on acceptance)
- **Available when:** Stage has any content
- **Behaviour:** User selects text, types instruction. AI generates targeted edit for selected section only. Diff returned for accept or reject.
- **On reject:** Document unchanged, credits not deducted.

### Regenerate

- **Cost:** 10 credits
- **Available when:** Stage has content
- **Behaviour:** Full new draft incorporating current state of all upstream dependencies. Prior content preserved as a version. User can roll back.

### Version History

- **Cost:** 0 credits
- **Available when:** Stage has more than one version
- **Behaviour:** User views and restores any prior version from version history panel. Restoring marks all downstream finalised stages as stale.

### Storyboard Generation

- **Cost:** 25 credits for full generation; 5 credits for a single-section regeneration
- **Available when:** SPEC, PLAN, HARNESS, and TASKS are all finalised and not stale
- **Behaviour:** Generates a separate Storyboard artifact from the finalised stage versions. The artifact includes the browser keynote payload, architecture diagram data, speaker notes, demo script, source map, and technical appendix.
- **On failure:** Credits refunded, Storyboard marked failed, clear error shown with one-click retry.
- **On upstream change:** Storyboard marked stale until regenerated. Existing shared Storyboard links remain accessible but show a stale banner to the owner and can be disabled or rotated.

---

## 7. Quality and Evals

### Online Evals

Every generation triggers an automated eval before results are shown. Runs asynchronously — user sees generated content immediately, badge updates when eval completes (typically a few seconds).

**Judge model:** Fast cheap model per provider:

|Provider|Judge Model|
|---|---|
|Anthropic|Claude Haiku|
|OpenAI|GPT-4o Mini|
|Google|Gemini Flash|

### Quality Badge States

|Score|Badge|Action|
|---|---|---|
|85–100|🟢 Green|High confidence output|
|70–84|🟡 Yellow|Review recommended|
|Below 70|🔴 Red|Regeneration suggested (one-click prompt)|

### Harness Coverage Display

After HARNESS generation, a coverage panel appears below the editor:

```
Spec Requirements Coverage: 74% ⚠

✓ User authentication flow
✓ JWT token generation
✗ Refresh token rotation    ← "Add a test for this →"
✗ Session expiry handling   ← "Add a test for this →"
✓ Password validation
```

**Workspace-level prominence:** the harness coverage figure (e.g. *"24 tests cover 18 of 21 requirements"*) is additionally surfaced in the workspace header summary, on the workspace dashboard card, and in the public share view (§4.8). The intent is that the harness stage — SpecForge's main differentiator versus generic PRD wrappers — is recognisable at a glance rather than discovered only by users who open the HARNESS stage.

### Task Harness Reference Display

After TASKS generation, a validation panel shows:

```
Task Validation

⚠ Task 3 — "Implement email notifications"
  No harness test referenced. Add test reference →

⚠ Task 7 — "Build payment flow"
  References test_stripe_webhook which does not exist
  in harness. Fix reference →
```

---

## 8. Authentication and Accounts

### Google OAuth

Sign in with Google is the only authentication method for SpecForge accounts.

```
User clicks "Sign in with Google"
        ↓
Authlib initiates OAuth flow (backend)
        ↓
User completes Google consent
        ↓
Backend receives auth code → exchanges for profile
        ↓
JWT access token issued (RS256, 15min expiry)
        ↓
Refresh token issued (7 days, httpOnly cookie)
        ↓
User redirected to dashboard
```

**Token storage:**

|Token|Storage|Expiry|
|---|---|---|
|Access token|JS memory only|15 minutes|
|Refresh token|httpOnly, Secure, SameSite=Strict cookie|7 days|

> [!danger] Security Rule Access tokens are never stored in localStorage or sessionStorage. Refresh token cookie is scoped to `/auth/refresh` only.

### Account Creation

On first sign-in an account is created automatically from the Google profile. Name, email, and avatar URL stored. Account starts with 50 free credits. User lands directly on dashboard.

### Session Management

Refresh tokens rotate on every use. If an already-used refresh token is presented — indicating possible token theft — all tokens for that user are immediately revoked and a security event is logged.

### GitHub OAuth (Integration Only)

GitHub OAuth is used exclusively to obtain a GitHub access token for the Export to GitHub feature. It does not create or replace a SpecForge account — the user must already be signed in via Google.

The GitHub OAuth flow is initiated from Settings → Integrations. On completion, the access token is encrypted with Fernet (same key vault as user-supplied LLM API keys) and stored in `UserIntegration`. The plaintext token is never written to logs or error responses.

| OAuth scope | Reason |
|---|---|
| `repo` | Create repositories, push files, create issues |
| `read:user` | Display the connected GitHub username in Settings |

The flow uses a one-time CSRF state parameter (32-byte random hex stored in the user's session for the duration of the flow). The callback endpoint rejects any request where the state does not match.

If a GitHub API call returns 401 at any point after connection, the stored token is deleted and the user is prompted to reconnect. SpecForge never retries with a known-invalid token.

---

## 9. Credit System and Billing

### Credit Ledger

> [!note] Design Rule The credit ledger is append-only. Every balance change is a new row. Credits are never updated in place. Every deduction, credit grant, expiry, refund, purchase, and Storyboard generation is a distinct ledger entry with a descriptive `reason` field (`signup_bonus`, `stripe_purchase:{pack_id}`, `generate`, `storyboard_generate:{storyboard_id}`, `storyboard_section:{storyboard_id}:{section_id}`, `refund:{ledger_id}`, `expiry:{pack_id}`, `stripe_refund:{pack_id}`).

`user.credit_balance` is a denormalised integer kept in sync with the ledger. It is the fast path for balance reads and is cache-backed in Redis (5-minute TTL). Invariant: `credit_balance >= SUM(stripe_credit_packs.credits_remaining)` for all active packs owned by that user at any point in time.

### Credit Deduction Flow

```
User triggers LLM action
        ↓
Lazy expiry check — any active purchased packs past their expires_at?
  Yes → deduct expired credits, update ledger, mark packs expired
        ↓
Credit balance checked
        ↓
Insufficient? → Request rejected, clear message shown, "Buy Credits →" CTA
        ↓
Sufficient? → Credits deducted atomically (SELECT FOR UPDATE)
              FIFO drain from soonest-expiring active pack first,
              then platform credits (signup bonus, manual grants)
        ↓
LLM call made
        ↓
Call fails? → Deduction reversed (positive ledger entry — refund)
        ↓
Call succeeds? → Deduction stands
```

### Free Tier

- 50 credits granted on first account creation (`reason: signup_bonus`)
- Platform credits do not expire
- When zero: credit exhaustion state with "Buy Credits →" link to `/billing`

### Purchased Credits

Users can buy one credit pack at a time via Stripe Hosted Checkout. V1 ships with a single package; price and credit count are configurable server-side.

| | |
|---|---|
| Pack size | 200 credits |
| Price | $9.00 USD |
| Validity | 30 days from purchase date |
| Currency | USD only in V1 |
| Refund policy | Unused credits revoked on Stripe refund; no negative balance |

**Purchase is authoritative on webhook receipt**, not on success redirect. Credits become available in the user's balance as soon as `checkout.session.completed` is processed by the backend. If payment fails or is cancelled, no credits are granted.

### Storyboard Credit Costs

Storyboard is a premium generation feature and is not treated as a free export.

|Action|Cost|Failure behavior|
|---|---:|---|
|Full Storyboard generation|25 credits|Refund if no usable Storyboard is persisted|
|Full Storyboard regeneration|25 credits|Refund if regeneration fails; previous Storyboard remains active|
|Single-section regeneration|5 credits|Refund if section repair fails; previous section remains active|
|Present / share / download|0 credits|No LLM call; no credit mutation|

Storyboard credit deductions use the same atomic balance and FIFO pack-drain path as stage generation. A browser refresh, duplicate request, or polling retry must never create a second charge for the same in-progress Storyboard job.

### Credit Expiry

Purchased credits expire 30 days from the date of purchase. Expiry is enforced **lazily** — at the top of every `get_balance()` and `deduct()` call, the backend checks for any active packs past their `expires_at` and converts the remaining pack credits into a negative ledger entry (`reason: expiry:{pack_id}`), reducing `credit_balance` accordingly.

The amount expired per pack is `MIN(pack.credits_remaining, user.credit_balance)` — the balance can never go below zero from expiry alone.

Platform credits (signup bonus, manually granted credits) **never expire**.

### FIFO Pack Drain

When credits are deducted for an LLM action, the cost is drawn from the user's active purchased packs in ascending `expires_at` order (soonest-expiring first). Each pack's `credits_remaining` is decremented accordingly inside the same `SELECT FOR UPDATE` transaction as the balance update. This ensures that:

- Credits closest to expiry are consumed first
- The `credits_remaining` field accurately reflects what would be lost if a pack expired right now
- Platform credits (no pack row) are always consumed last

### Stripe Refunds and Disputes

If a user disputes a charge or requests a refund:

1. Stripe fires `charge.refunded` or `charge.dispute.created`
2. Backend looks up the pack by `stripe_payment_intent_id`
3. Revokes `MIN(pack.credits_remaining, user.credit_balance)` credits
4. Creates a negative ledger entry (`reason: stripe_refund:{pack_id}`)
5. Sets pack `status = 'refunded'`, `credits_remaining = 0`

Disputed charges are revoked immediately on `dispute.created` and are **not** automatically reinstated if the dispute is resolved in the seller's favour — reinstatement is a manual admin action.

### Credit Display

|Location|Display|
|---|---|
|Top navigation bar|Current balance on all authenticated pages|
|Workspace view|Credit meter below stage action buttons|
|Below 10 credits|Low-credit warning shown|
|Active pack within 7 days of expiry|"⚠ X credits expire in N days — Buy more →" chip|
|Zero credits|"You're out of credits. Buy 200 credits for $9 →"|
|Billing page|Balance, earliest expiry date, purchase card, history|

---

## 10. Data Models

### User

|Field|Type|Constraints|
|---|---|---|
|id|UUID|Primary key|
|email|TEXT|Unique, not null|
|google_id|TEXT|Unique, not null|
|name|TEXT||
|avatar_url|TEXT||
|credit_balance|INTEGER|Not null, default 0, check ≥ 0 — denormalised fast-path balance; kept in sync with ledger|
|created_at|TIMESTAMPTZ||

### Workspace

|Field|Type|Constraints|
|---|---|---|
|id|UUID|Primary key|
|user_id|UUID|FK → users.id|
|name|TEXT|Not null, max 200 chars|
|problem_statement|TEXT|Not null, min 50, max 10,000 chars|
|provider|TEXT|anthropic / openai / google|
|model|TEXT|Not null|
|status|TEXT|active / archived|
|template_slug|TEXT|Nullable — the slug of the template the workspace was created from, if any|
|clarification_qa|JSONB|Nullable — captured `[ { question, answer } ]` pairs from the Spec Clarification step (§4.4.1)|
|public_share_slug|TEXT|Nullable, unique when present — opaque slug exposed at `/p/{slug}` when sharing is enabled|
|public_share_enabled|BOOLEAN|Default false — current on/off state of the public share|
|created_at|TIMESTAMPTZ||
|updated_at|TIMESTAMPTZ||

Unique constraint: `public_share_slug` when not null.

### Stage

|Field|Type|Constraints|
|---|---|---|
|id|UUID|Primary key|
|workspace_id|UUID|FK → workspaces.id|
|type|TEXT|spec / plan / harness / tasks|
|content|TEXT||
|status|TEXT|locked / draft / in_progress / finalised / stale|
|current_version|INTEGER|Default 0|
|finalised_at|TIMESTAMPTZ||
|created_at|TIMESTAMPTZ||
|updated_at|TIMESTAMPTZ||

### Stage Version

|Field|Type|Constraints|
|---|---|---|
|id|UUID|Primary key|
|stage_id|UUID|FK → stages.id|
|version|INTEGER|Not null|
|content|TEXT|Not null|
|created_by|TEXT|user / ai|
|created_at|TIMESTAMPTZ||

### Credit Ledger

|Field|Type|Constraints|
|---|---|---|
|id|UUID|Primary key|
|user_id|UUID|FK → users.id|
|amount|INTEGER|Positive = credit, negative = debit|
|reason|TEXT|Not null|
|metadata|JSONB||
|created_at|TIMESTAMPTZ||

### User Integration

Stores an encrypted OAuth token for a connected external service. One row per user per provider.

|Field|Type|Constraints|
|---|---|---|
|id|UUID|Primary key|
|user_id|UUID|FK → users.id|
|provider|TEXT|`github` (extensible)|
|encrypted_token|TEXT|Fernet-encrypted access token|
|github_username|TEXT|Display only — shown in Settings|
|connected_at|TIMESTAMPTZ||
|last_used_at|TIMESTAMPTZ|Updated on each export|

Unique constraint: `(user_id, provider)`.

### Integration Push

Records each GitHub export attempt. One row per workspace per provider; re-export updates this row in place.

|Field|Type|Constraints|
|---|---|---|
|id|UUID|Primary key|
|workspace_id|UUID|FK → workspaces.id|
|user_id|UUID|FK → users.id|
|provider|TEXT|`github`|
|repo_full_name|TEXT|e.g. `username/repo-name`|
|repo_url|TEXT|Full HTTPS URL|
|status|TEXT|`pending` / `completed` / `failed`|
|pushed_at|TIMESTAMPTZ|Set on completion|
|created_at|TIMESTAMPTZ||

Unique constraint: `(workspace_id, provider)`.

### Integration Push Task

Maps each task to its created GitHub Issue number, enabling idempotent re-export.

|Field|Type|Constraints|
|---|---|---|
|id|UUID|Primary key|
|push_id|UUID|FK → integration_pushes.id|
|task_ref|TEXT|e.g. `T-001`|
|external_issue_number|INTEGER|GitHub issue number|
|created_at|TIMESTAMPTZ||

Unique constraint: `(push_id, task_ref)`.

### Eval Result

|Field|Type|Constraints|
|---|---|---|
|id|UUID|Primary key|
|stage_version_id|UUID|FK → stage_versions.id|
|stage_type|TEXT|Not null|
|overall_score|INTEGER||
|completeness|INTEGER||
|clarity|INTEGER||
|coverage_percent|INTEGER|Harness stage only|
|uncovered_reqs|JSONB|Harness stage only|
|tasks_without_ref|JSONB|Tasks stage only|
|flagged|BOOLEAN|Default false|
|created_at|TIMESTAMPTZ||

### Stripe Credit Pack

One row per Stripe Checkout session. Created with `status='pending'` when the checkout session is initiated; updated to `status='active'` when `checkout.session.completed` fires. Tracks remaining credits for FIFO drain and lazy expiry.

|Field|Type|Constraints|
|---|---|---|
|id|UUID|Primary key|
|user_id|UUID|FK → users.id, CASCADE|
|stripe_checkout_session_id|TEXT|Unique, not null|
|stripe_payment_intent_id|TEXT|Unique, nullable — populated on checkout completion|
|credits_purchased|INTEGER|Not null, check > 0|
|credits_remaining|INTEGER|Not null, check ≥ 0 and ≤ credits_purchased — decremented FIFO on deduct; drives expiry calculation|
|price_cents|INTEGER|Not null, check > 0|
|expires_at|TIMESTAMPTZ|Not null — set to `created_at + 30 days` on activation|
|status|TEXT|`pending` / `active` / `expired` / `refunded`|
|created_at|TIMESTAMPTZ||

Indexes: `(user_id)`, `(user_id, expires_at)` WHERE `status = 'active'` for lazy-expiry lookups.

### Stripe Webhook Event

Idempotency table. One row per processed Stripe event. A second insert for the same `stripe_event_id` raises a unique constraint error, which the handler catches and silently skips — making every webhook handler idempotent regardless of event type.

|Field|Type|Constraints|
|---|---|---|
|id|UUID|Primary key|
|stripe_event_id|TEXT|Unique, not null — e.g. `evt_1AbC...`|
|event_type|TEXT|Not null — e.g. `checkout.session.completed`|
|processed_at|TIMESTAMPTZ|Not null, default now()|

---

### Template

System-owned, deploy-time-seeded library of starter problem statements. Read-only from the user's perspective in V1.

|Field|Type|Constraints|
|---|---|---|
|id|UUID|Primary key|
|slug|TEXT|Unique, not null — stable identifier referenced from `Workspace.template_slug`|
|name|TEXT|Not null, max 200 chars|
|description|TEXT|Not null, short marketing line shown on the card|
|category|TEXT|`auth` / `payments` / `content` / `realtime` / `agent` / `tooling`|
|problem_statement|TEXT|Not null — seed text inserted into the workspace form|
|suggested_provider|TEXT|Nullable — default provider hint|
|suggested_model|TEXT|Nullable — default model hint|
|sort_order|INTEGER|Default 0 — controls dashboard ordering|
|active|BOOLEAN|Default true — soft-disable without deletion|
|created_at|TIMESTAMPTZ||

---

### Storyboard

One row per generated Storyboard version. Storyboards are derived from a completed workspace but stored as their own artifact so they can be presented, shared, downloaded, regenerated, and marked stale independently from the four pipeline stages.

|Field|Type|Constraints|
|---|---|---|
|id|UUID|Primary key|
|workspace_id|UUID|FK → workspaces.id|
|user_id|UUID|FK → users.id|
|version|INTEGER|Not null, monotonically increasing per workspace|
|status|TEXT|`generating` / `ready` / `failed` / `stale`|
|title|TEXT|Generated product/keynote title, max 200 chars|
|theme|TEXT|Generated or selected visual identity key|
|content_json|JSONB|Structured sections, slides, diagrams, animation hints, launch page payload|
|speaker_notes_md|TEXT|Downloadable presenter talk track|
|demo_script_md|TEXT|Downloadable product demo script|
|technical_appendix_md|TEXT|Downloadable technical appendix and Q&A prep|
|source_map_json|JSONB|Slide/claim → SPEC/PLAN/HARNESS/TASKS source references|
|source_stage_version_ids|JSONB|Stage version IDs used as generation inputs|
|credit_ledger_id|UUID|Nullable FK → credit_ledger.id for the generation debit|
|public_share_slug|TEXT|Nullable, unique when present — opaque slug exposed at `/sb/{slug}`|
|public_share_enabled|BOOLEAN|Default false|
|allow_pdf_download|BOOLEAN|Default true|
|allow_notes_download|BOOLEAN|Default false|
|allow_appendix_download|BOOLEAN|Default false|
|allow_source_layer|BOOLEAN|Default false|
|created_at|TIMESTAMPTZ||
|updated_at|TIMESTAMPTZ||

Unique constraints: `(workspace_id, version)` and `public_share_slug` when not null.

**Content JSON contract:**

```json
{
  "sections": [
    {
      "id": "opening-thesis",
      "title": "Opening Thesis",
      "slides": [
        {
          "id": "slide-001",
          "type": "hero",
          "headline": "...",
          "visual": {...},
          "speaker_notes_ref": "notes.slide-001",
          "sources": ["SPEC"]
        }
      ]
    }
  ],
  "diagrams": [
    {
      "id": "architecture-reveal",
      "type": "architecture_reveal",
      "layers": ["client", "frontend", "api", "data", "integrations", "trust", "recovery"]
    }
  ],
  "theme": {
    "palette": ["#..."],
    "typography": "executive-technical",
    "motif": "..."
  }
}
```

The renderer owns final visual presentation. The LLM produces structured content and diagram intent; the frontend prevents arbitrary script/style injection.

---

## 11. API Contracts

### Authentication

|Method|Endpoint|Description|
|---|---|---|
|POST|/auth/google|Initiate Google OAuth flow|
|GET|/auth/callback|Handle OAuth callback, issue tokens|
|POST|/auth/refresh|Rotate refresh token, issue new access token|
|POST|/auth/logout|Revoke refresh token, clear cookie|
|GET|/auth/me|Return current user profile and credit balance|
|GET|/auth/github|Initiate GitHub OAuth flow (must be signed in)|
|GET|/auth/github/callback|Handle GitHub callback, store encrypted token|

### Integrations

|Method|Endpoint|Description|
|---|---|---|
|GET|/integrations/github|Return GitHub connection status and username|
|DELETE|/integrations/github|Disconnect GitHub — delete stored token|

### Workspaces

|Method|Endpoint|Description|
|---|---|---|
|GET|/workspaces|List user's workspaces|
|POST|/workspaces|Create a new workspace (accepts optional `template_slug` to record provenance)|
|GET|/workspaces/{id}|Get workspace with all stages|
|PATCH|/workspaces/{id}|Update workspace name|
|DELETE|/workspaces/{id}|Archive workspace (soft delete)|
|POST|/workspaces/{id}/export|Download zip of all four stages|
|POST|/workspaces/{id}/export/github|Push workspace to a new GitHub repo; create issues|
|GET|/workspaces/{id}/export/github|Return latest GitHub push record for this workspace|
|POST|/workspaces/{id}/export/pdf|Render and stream back a branded PDF of the finalised workspace|
|POST|/workspaces/{id}/share|Enable public sharing — returns the public slug and URL|
|DELETE|/workspaces/{id}/share|Disable public sharing — preserves the slug for re-enable|
|POST|/workspaces/{id}/share/rotate|Rotate the public slug (invalidates the prior URL)|
|POST|/workspaces/{id}/clarify|Request 3–5 clarifying questions for the spec stage (judge model, free, no credit deduction)|
|PATCH|/workspaces/{id}/clarify|Store the user's answers to the clarifying questions|

### Storyboards

|Method|Endpoint|Auth|CSRF|Description|
|---|---|---|---|---|
|GET|/workspaces/{id}/storyboards|Required|No|List Storyboards for a workspace, newest first|
|GET|/workspaces/{id}/storyboards/latest|Required|No|Return latest Storyboard summary and stale status|
|POST|/workspaces/{id}/storyboards|Required|Yes|Generate a full Storyboard from the finalised workspace; costs 25 credits; returns Storyboard ID and generation status|
|GET|/storyboards/{id}|Required|No|Return full Storyboard payload for browser presentation|
|POST|/storyboards/{id}/regenerate|Required|Yes|Regenerate full Storyboard; costs 25 credits; previous ready version remains available until replacement succeeds|
|POST|/storyboards/{id}/sections/{section_id}/regenerate|Required|Yes|Regenerate one Storyboard section; costs 5 credits|
|GET|/storyboards/{id}/presenter|Required|No|Return presenter-mode payload: slides, notes, next-slide preview data, demo cues|
|GET|/storyboards/{id}/download/html|Required|No|Download offline browser package|
|GET|/storyboards/{id}/download/pdf|Required|No|Download static Storyboard PDF|
|GET|/storyboards/{id}/download/notes|Required|No|Download `speaker-notes.md` or PDF variant by query parameter|
|GET|/storyboards/{id}/download/demo-script|Required|No|Download `demo-script.md`|
|GET|/storyboards/{id}/download/appendix|Required|No|Download `technical-appendix.md`|
|POST|/storyboards/{id}/share|Required|Yes|Enable Storyboard public sharing and configure public download/source permissions|
|DELETE|/storyboards/{id}/share|Required|Yes|Disable Storyboard public sharing — preserves slug for re-enable|
|POST|/storyboards/{id}/share/rotate|Required|Yes|Rotate Storyboard public slug and invalidate prior public URL|

### Stages

|Method|Endpoint|Description|
|---|---|---|
|GET|/stages/{id}|Get stage with current content|
|POST|/stages/{id}/generate|Generate stage content — SSE stream|
|POST|/stages/{id}/refine|Refine a section — returns diff|
|POST|/stages/{id}/regenerate|Regenerate full stage — SSE stream|
|POST|/stages/{id}/finalise|Mark stage as finalised|
|POST|/stages/{id}/rollback|Restore a prior version|
|GET|/stages/{id}/versions|List all versions for a stage|
|GET|/stages/{id}/eval|Get latest eval result for a stage|

### Credits

|Method|Endpoint|Description|
|---|---|---|
|GET|/credits/balance|Return current balance, generation cost, and earliest pack expiry info (`expires_soon`, `next_expiry_at`)|
|GET|/credits/history|Return credit ledger entries (paginated)|

### Billing

|Method|Endpoint|Auth|CSRF|Description|
|---|---|---|---|---|
|GET|/billing/package|Required|No|Return the single available credit package (`credits`, `price_cents`, `validity_days`)|
|POST|/billing/checkout|Required|Yes|Create a Stripe Checkout session; returns `{checkout_url}` for frontend redirect|
|GET|/billing/status|Required|No|Poll checkout session status by `?session_id=...`; ownership-scoped by `user_id`; returns `{status, expires_at}`|
|GET|/billing/history|Required|No|Return user's pack purchase history (paginated)|
|POST|/billing/webhook|None|Exempt|Stripe webhook endpoint; authenticated by `Stripe-Signature` HMAC-SHA256; no Bearer token|

> [!important] Webhook security boundary
> `/billing/webhook` carries no Bearer token and is exempt from CSRF enforcement. Its only authentication mechanism is the `Stripe-Signature` header validated against `STRIPE_WEBHOOK_SECRET` with a 300-second timestamp tolerance. The endpoint is also exempt from all per-IP rate limiting — Stripe's retry schedule must not be blocked.

### Providers

|Method|Endpoint|Description|
|---|---|---|
|GET|/providers|Return available providers and models|

### Templates

|Method|Endpoint|Description|
|---|---|---|
|GET|/templates|List active starter templates (public, no auth required so the marketing dashboard preview works)|

### Public Share (read-only, no auth)

|Method|Endpoint|Description|
|---|---|---|
|GET|/public/{slug}|Return the read-only finalised workspace bundle (spec, plan, harness coverage summary, tasks). 404 if the slug is unknown or sharing is currently disabled.|
|GET|/storyboards/public/{slug}|Return public Storyboard launch page and presentation payload. 404 if the slug is unknown or sharing is disabled. Download/source-layer access follows owner permissions.|
|GET|/storyboards/public/{slug}/download/{kind}|Download a public Storyboard artifact when the owner has enabled that permission. `kind` is `pdf`, `notes`, `demo-script`, or `appendix`; public HTML package download is not exposed by default.|

---

## 12. Non-Functional Requirements

### Performance

|Requirement|Target|
|---|---|
|SSE stream first token latency|Under 2 seconds from request to first token rendered|
|API response time (non-streaming)|Under 500ms at p95|
|Editor responsiveness during streaming|Must not block the UI thread|

> [!note] 2 seconds to first token is the critical threshold. Beyond this the user perceives the generation as broken.

### Reliability

- LLM gateway handles provider errors gracefully — partial content discarded, credits refunded, clear error shown with one-click retry
- SSE stream drops trigger automatic client reconnection up to three times before showing an error
- Credit deductions are atomic — no deduction without a corresponding LLM call, no LLM call without a successful deduction

### Security

- All communication over HTTPS with TLS 1.3. No exceptions.
- JWT access tokens expire in 15 minutes. Refresh tokens rotate on every use.
- All user input scanned for prompt injection patterns before any LLM call
- All LLM output validated for system prompt leakage before delivery to client
- SQL injection prevented by ORM-only database access — no raw SQL strings
- Rate limiting applied at global, per-user, and per-user LLM tiers via Redis sliding window
- GitHub OAuth access tokens stored encrypted with Fernet; plaintext never written to logs, errors, or audit fields. Auto-deleted on 401 from GitHub API.
- Stripe webhook requests authenticated by HMAC-SHA256 `Stripe-Signature` header with a 300-second timestamp tolerance. Invalid signature → 400 (no Sentry noise). Expired timestamp → 400.
- Stripe secret keys (`sk_live_*`, `sk_test_*`) and webhook signing secrets (`whsec_*`) scrubbed from all log, error, and trace pipelines alongside existing secret patterns.
- `GET /billing/status` lookups are scoped by `user_id` in addition to `session_id` to prevent IDOR — a user cannot poll another user's checkout session status. Returns 404 (not 403) on ownership mismatch to avoid confirming existence.
- PII boundary with Stripe: only the user's email is passed to Stripe (for checkout form pre-fill). No card data touches SpecForge servers at any point. `client_reference_id` carries only the opaque UUID `user_id`.
- Production guard: `STRIPE_SECRET_KEY` must be set and must not be a test key (`sk_test_*`) in production; enforced at startup alongside existing production validation checks.
- Storyboard public links expose only the generated Storyboard payload and owner-enabled downloads. They never expose account email, credit balance, billing history, private workspace lists, draft stage content, previous Storyboard versions, or raw prompts.
- Storyboard source excerpts are sanitized, bounded in length, and sourced only from finalised stage versions. The source layer is disabled on public links by default.
- Storyboard HTML downloads contain no arbitrary LLM-generated scripts. Deck rendering uses the trusted frontend renderer over structured JSON; generated Markdown, diagram labels, notes, and appendix content pass through the same sanitization policy as public share and PDF export.
- Public Storyboard pages use `noindex, nofollow`, `X-Robots-Tag`, and a strict CSP. Offline HTML packages include the minimum assets needed to render the deck and do not fetch remote scripts.

### Rate Limits

|Tier|Scope|Limit|Window|
|---|---|---|---|
|Global|Per IP|1,000 requests|1 minute|
|User API|Per user|100 requests|1 minute|
|User LLM|Per user|10 LLM calls|1 minute|
|User LLM Daily|Per user|200 LLM calls|24 hours|
|Auth Login|Per IP|5 attempts|5 minutes|
|GitHub Export|Per user|3 exports|1 hour|
|PDF Export|Per user|10 exports|1 hour|
|Spec Clarify|Per user|6 calls|1 hour|
|Public Share Toggle|Per user|20 toggles|1 hour|
|Public View|Per IP|120 reads|1 minute|
|Billing Checkout|Per user|5 sessions|1 hour|
|Billing Webhook|Exempt|Signature-validated; no rate cap|—|
|Storyboard Generate|Per user|3 full generations|1 hour|
|Storyboard Section Regenerate|Per user|10 section regenerations|1 hour|
|Storyboard Share Toggle|Per user|20 toggles|1 hour|
|Storyboard Public View|Per IP|120 reads|1 minute|
|Storyboard Download|Per user/IP|30 downloads|1 hour|

### Scalability

V1 is designed for hundreds of concurrent users, not thousands. Railway's default configuration is sufficient. The stateless FastAPI design supports horizontal scaling when needed — Redis handles all session state.

### Observability

- Structured JSON logs for every significant event via structlog. Sensitive data filtered before emission.
- Prometheus metrics at `/metrics` covering LLM call duration, token counts, credit deductions, active SSE streams, pipeline action counts
- Sentry on both frontend and backend for error tracking
- Grafana Cloud connected from day one for log aggregation and dashboards
- LLM call traces (full system prompt, full user prompt, raw model output, input and output token counts, latency, provider, model) captured per generation via Langfuse
- Eval scores linked to the specific generation that produced the content, so prompt quality and model output quality can be inspected together
- Prompt version tracking across deployments, so prompt edits can be correlated with eval-score trends over time
- All LLM observability is **optional** and degrades gracefully when Langfuse is unavailable or unconfigured. The platform falls back to local prompt templates and skips trace/score submission silently.
- **No user-facing feature depends on Langfuse availability.** Stage generation, refine, finalise, eval scoring, credit accounting, and export work identically with or without Langfuse configured.

**Billing observability** — the following Prometheus counters are emitted for all Stripe billing events:

|Metric|Description|
|---|---|
|`specforge_billing_checkout_created_total`|Stripe Checkout sessions initiated|
|`specforge_billing_purchase_completed_total`|Purchases completed and credits granted|
|`specforge_billing_purchase_revenue_cents_total`|Total revenue from completed purchases|
|`specforge_billing_credits_granted_total`|Credits added via Stripe purchase|
|`specforge_billing_refunds_total`|Refund events processed|
|`specforge_billing_credits_revoked_total`|Credits revoked on refund or dispute|
|`specforge_billing_disputes_total`|Dispute events processed|
|`specforge_billing_webhook_errors_total`|Webhook processing failures (labelled by `error_type`)|
|`specforge_billing_credits_expired_total`|Credits expired by lazy-expiry mechanism|
|`specforge_billing_webhook_duplicates_total`|Webhook events skipped as duplicates (labelled by `event_type`)|

Structlog billing events follow a consistent schema — fields always include `event_type`, `stripe_event_id`, `user_id`, and `pack_id`; email and raw payloads are never logged. Key event names: `billing.checkout.created`, `billing.purchase.activated`, `billing.refund.processed`, `billing.dispute.flagged`, `billing.webhook.duplicate_skipped`, `billing.expiry.run`.

Recommended Grafana alert rules (documented in `RUNBOOK.md §9`):

|Alert|Expression|Severity|
|---|---|---|
|Webhook errors|`rate(specforge_billing_webhook_errors_total[5m]) > 0`|Warning|
|Dispute spike|`increase(specforge_billing_disputes_total[24h]) > 5`|Critical|
|Zero purchases 72 h|`increase(specforge_billing_purchase_completed_total[72h]) == 0`|Warning|
|Unexpected expiry spike|`rate(specforge_billing_credits_expired_total[1h]) > 500`|Warning|

**Storyboard observability** — the following metrics are emitted for the paid keynote flow:

|Metric|Description|
|---|---|
|`specforge_storyboard_generation_started_total`|Full Storyboard generations started|
|`specforge_storyboard_generation_completed_total`|Full Storyboard generations persisted successfully|
|`specforge_storyboard_generation_failed_total`|Full Storyboard generations failed, labelled by failure type|
|`specforge_storyboard_section_regenerated_total`|Single-section regenerations completed|
|`specforge_storyboard_generation_duration_seconds`|Histogram of full Storyboard generation duration|
|`specforge_storyboard_credits_deducted_total`|Credits deducted for Storyboard actions|
|`specforge_storyboard_credits_refunded_total`|Credits refunded after Storyboard failures|
|`specforge_storyboard_public_view_total`|Public Storyboard launch page/deck views|
|`specforge_storyboard_download_total`|Downloads by type: html, pdf, notes, demo_script, appendix|
|`specforge_storyboard_source_missing_total`|Expected source sections absent during Storyboard source extraction, labelled by source and section|

Structlog Storyboard events include `storyboard_id`, `workspace_id`, `user_id`, `version`, `action`, `status`, `credit_ledger_id`, and `source_stage_version_ids`. Speaker notes, source excerpts, raw generated JSON, and technical appendix content are never logged.

---

## 13. Assumptions

> [!warning] Validate These Each assumption below should be validated before or during V1 development. If an assumption is wrong it may require a spec change.

**Assumption 1 — Model selection is not friction.** Developers are willing to select their preferred provider and model rather than having SpecForge choose for them. If this creates too much friction, a pre-selected recommended default can be added.

**Assumption 2 — 50 credits is enough to experience full pipeline value before asking for payment.** If users consistently run out before completing their first workspace the free allocation needs to increase. Users can purchase additional credits at any time, so exhaustion is no longer a terminal state.

**Assumption 3 — Export to zip is the right delivery mechanism.** Users want to drop files into their project and use them with a coding agent. A future version might integrate directly with the coding agent's context window.

**Assumption 4 — The pipeline order is strict and non-skippable.** Users cannot skip stages. If experienced users want to jump directly to HARNESS on a well-understood project type, a skip mode could be added post-V1.

**Assumption 5 — Google OAuth is sufficient for sign-in.** GitHub OAuth is used only for the export integration, not for authentication. Enterprise SSO is explicitly out of scope.

**Assumption 8 — One repo per workspace is the right export model.** Users want to start a fresh repo each time rather than push updates into an existing one. Re-export updates the previously created repo in place.

**Assumption 9 — GitHub Issues are the right unit for tasks.** Developers working in GitHub use Issues as their unit of work. No GitHub Projects, Milestones, or Labels are created in the initial export; users can add these on GitHub after export.

**Assumption 10 — Synchronous export is acceptable.** A workspace with 30 tasks will take roughly 30 seconds end-to-end under normal GitHub API conditions. If this is consistently too slow, a background job with SSE progress streaming can be added using the same pattern as stage generation.

**Assumption 6 — A single credit pack at $9 is the right pricing entry point.** A single no-choice purchase removes decision paralysis. If conversion data shows users wanting larger or smaller packs, tiered pricing can be introduced without a schema change (the `stripe_credit_packs` table is pack-agnostic). 200 credits = 5 full four-stage pipeline runs, which should be enough for users to validate SpecForge on a real project.

**Assumption 7 — Langfuse is an optional observability enhancement.** Its unavailability must never surface to users or affect credit accounting, stage generation, or eval scoring. The system runs identically with `LANGFUSE_SECRET_KEY` unset; when it is set, Langfuse becomes an additional sink for prompt-level traces, prompt versions, eval scores, and dataset items. If a Langfuse call fails for any reason — network error, auth failure, rate limit, schema rejection — the failure is logged and swallowed. No user-facing flow may raise on a Langfuse error.

**Assumption 11 — Spec Clarification meaningfully improves spec quality.** The lightweight Q&A step before the first spec generation is expected to lift baseline eval scores enough to justify the extra UI step. If users skip it more than ~60% of the time *and* eval scores show no detectable lift, the modal becomes opt-in (a small "Refine my idea first" button) rather than the default pre-generate flow.

**Assumption 12 — A 6-character opaque slug is sufficient unguessability for public sharing.** The shared content is the user's own finalised spec — not credentials and not personal data — so the risk of accidental discovery is modest. The slug entropy is 36⁶ ≈ 2.2B values; combined with the per-IP read rate limit (120/min) enumeration is impractical. If sharing is later extended to anything more sensitive the slug length is increased.

**Assumption 13 — A PDF without the harness directory is what non-engineering audiences want.** Founders, PMs, clients and investors want the readable artefacts (SPEC, PLAN, TASKS) rather than the runnable scaffold. If user research shows demand for a harness summary inside the PDF, an appendix is added.

**Assumption 14 — A small curated template library is enough for cold-start.** 6–10 hand-tuned templates covering the most common SaaS / agent / developer-tool starting points are expected to remove the blank-page problem for a typical first-time user. If template attach rate is below ~25% the library is expanded; if a long tail of niches is requested, user-authored templates are revisited for V2.

**Assumption 15 — Stripe Hosted Checkout is acceptable UX for a developer audience.** A full-page redirect to Stripe's checkout page is industry-standard and removes all PCI scope from SpecForge. If user research shows meaningful drop-off at the redirect step, an embedded Stripe Payment Element can replace it without changes to the backend billing logic.

**Assumption 16 — 30-day credit validity is long enough to avoid frustration but short enough to drive re-purchase.** If expiry triggers significant support requests ("my credits expired while I was away") the validity period can be extended server-side via `STRIPE_CREDIT_VALIDITY_DAYS` without a schema migration. If credits are expiring with significant remaining balances (visible in `specforge_billing_credits_expired_total`), the expiry period is too short.

**Assumption 17 — Webhook delivery is sufficiently reliable for credit granting.** Stripe retries failed webhooks for up to 72 hours with exponential backoff. If the backend is down for longer than that — an extreme scenario — purchased credits would not be granted automatically. A manual admin script that replays events from Stripe's event log is the recovery path; documenting this in `RUNBOOK.md §9` is sufficient for V1.

**Assumption 18 — Storyboard is valuable enough to be paid.** A 25-credit price is expected to feel fair because Storyboard produces a separate launch artifact: keynote, architecture reveal, speaker notes, demo script, downloadable materials, and share page. If users frequently abandon at the confirmation modal, lower the price or offer a preview mode.

**Assumption 19 — Browser-native is the correct default presentation format.** Users want a link they can present immediately without PowerPoint, Apple Keynote, or Google Slides. PDF and offline HTML downloads cover most portability needs. Native slide-file export can be added later if customer demand is clear.

**Assumption 20 — Source-backed claims are a differentiator, not visual clutter.** The main Storyboard must stay cinematic and sparse, but the optional source layer gives technical buyers confidence that claims are derived from SPEC, PLAN, HARNESS, and TASKS rather than generic marketing text. If public viewers find the source layer confusing, it remains owner-only by default.

---

## 14. Out of Scope for V1

| Feature                              | When           |
| ------------------------------------ | -------------- |
| Subscriptions and recurring billing  | V2             |
| Tiered credit packages               | V2             |
| Approval workflows                   | V2 Team        |
| Jira integration                     | V2             |
| Team workspaces                      | V2             |
| Chat panel per stage                 | V2             |
| Mobile and tablet responsive design  | Post V1        |
| Self-host installation documentation | Post V1 launch |
| Email notifications                  | V2             |
| Custom prompt templates              | V3             |
| User-authored starter templates      | V2             |
| Public-share comments or reactions   | V2             |
| Editable PDF (interactive form)      | V2             |
| Storyboard PPTX / `.key` export      | V2             |
| API access for programmatic use      | V3             |
| Audit logging                        | V3 Enterprise  |
| Enterprise SSO or SAML               | V3 Enterprise  |
| Bidirectional ticket sync            | V3 Enterprise  |

---

## V1 Success Metrics

|Metric|Target|Meaning|
|---|---|---|
|Pipeline completion rate|≥ 30%|% of workspaces that reach a finalised TASKS stage|
|Export rate|≥ 60%|% of completed workspaces that result in a download|
|Storyboard generation rate|≥ 15%|% of completed workspaces that generate a Storyboard|
|Storyboard presentation/share rate|≥ 50%|% of generated Storyboards that are presented, shared, or downloaded|
|Return rate|≥ 40%|% of users who complete one workspace and start a second|
|Credit purchase conversion|≥ 10%|% of users who exhaust free credits and purchase a pack|
|Credit expiry waste|< 20%|% of purchased credits that expire unused — indicates over-buying or insufficient re-engagement|
|Qualitative signal|10 user interviews|Did they use the output in a real project?|

---

_SpecForge V1 SPEC.md · Version 1.5.0 · 2026-05-30 — added Storyboard paid product-keynote generation: §2 adds Storyboard as a paid goal and excludes native PPTX/Keynote export from V1; §4.8 adds the Create Storyboard action; new §4.13 defines six-act keynote structure, credit pricing, cinematic architecture reveal, browser presentation mode, presenter mode, launch page, source-backed confidence layer, product demo script, visual identity generator, hidden technical appendix, sharing controls, downloads, and signature slide moments; §6 adds Storyboard generation interaction mode; §9 adds Storyboard credit ledger reasons and pricing/refund rules; §10 adds Storyboard data model and JSON contract; §11 adds Storyboard API and public route contracts; §12 adds Storyboard security, rate limits, and observability metrics; §13 adds assumptions for paid Storyboard value, browser-native presentation, and source-backed claims; §14 adds native slide export as V2; Success Metrics adds Storyboard generation and presentation/share targets._

_Version 1.4.0 · 2026-05-27 — Stripe payments integration: §2 Goals adds credit purchase goal; §2 Non-Goals changes "Payments and subscriptions" to "Subscriptions and recurring billing"; §4.10 Dashboard replaces waitlist callout with purchase CTA and expiry warning chip; new §4.12 Credit Purchase Flow with checkout redirect, webhook-authoritative crediting, Billing page sections, and cancellation handling; §9 fully rewritten as "Credit System and Billing" covering ledger invariant, FIFO pack drain, lazy expiry, Stripe refund/dispute policy, and updated credit display table; §10 adds `User.credit_balance` field, new `StripeCreditPack` and `StripeWebhookEvent` data models; §11 Credits endpoint updated with expiry fields, new Billing endpoints table with auth/CSRF/ownership notes; §12 Security adds 5 Stripe-specific rules, Rate Limits adds Billing Checkout and Billing Webhook tiers, Observability adds 10 billing Prometheus counters, structlog event schema, and 4 Grafana alert rules; §13 updates Assumptions 2 and 6, adds Assumptions 15–17 for Stripe UX, expiry period, and webhook reliability; §14 replaces "Payments and subscriptions" with "Subscriptions and recurring billing" + "Tiered credit packages"; Success Metrics adds credit purchase conversion and expiry waste targets._

_Version 1.3.0 · 2026-05-20 — added six v1 usefulness features: Spec Clarification pre-generation step (§4.4.1, §5.1), per-task Priority + Estimate fields with an Effort Summary block (§4.6, §5.4), PDF export and Public Share read-only link (§4.8), Starter Templates library and §4.11 flow, harness-coverage workspace-summary surfacing (§7). Adds `Workspace.template_slug / clarification_qa / public_share_slug / public_share_enabled` fields and the `Template` table (§10), new endpoints under Workspaces / Templates / Public Share (§11), new rate-limit tiers PDF/Clarify/Share/Public-view (§12), Assumptions 11–14, and three new V2 entries in §14. Existing ZIP and GitHub export paths unchanged._

_Version 1.2.0 · 2026-05-19 — added GitHub export integration: §4.8 expanded with GitHub export flow, §4.9 GitHub connection flow, §8 GitHub OAuth, §10 UserIntegration/IntegrationPush/IntegrationPushTask models, §11 integrations and GitHub export endpoints, §12 GitHub token security and rate limit, Assumptions 8–10. ZIP export unchanged._

_Version 1.1.0 · 2026-05-07 — added Langfuse-backed LLM observability under §12 and Assumption 7. No product-flow changes._
