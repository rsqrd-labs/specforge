
---

tags:

- specforge
- spec
- v1
- asdd created: 2026-04-25 status: final version: 1.1.0 stage: spec

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
- [[#9. Credit System]]
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

### Non-Goals for V1

> [!warning] Explicitly Out of Scope These are not deferred — they are deliberately excluded from V1 to maintain focus.

- Payments and subscriptions
- Approval workflows
- Jira integration
- Team workspaces or shared pipelines
- Chat panel per stage
- Mobile responsiveness
- Self-host documentation
- Bidirectional sync
- Enterprise features of any kind

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

A placeholder in the problem statement field guides them on what a good problem statement looks like. They click Create and land in the workspace view.

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

### 4.5 Human Review Gate

After SPEC is finalised and before PLAN generation begins, a mandatory review prompt appears:

> _"You are about to generate PLAN.md from this spec. Take a moment to review the spec above. Once PLAN is generated it will be based on this version. Are you ready to proceed?"_

This gate appears once per stage transition. It is a deliberate pause, not a hard blocker.

### 4.6 Completing the Pipeline

User proceeds through PLAN → HARNESS → TASKS in order. Same pattern at each stage: generate, review, refine as needed, finalise.

**HARNESS generation** — quality badge includes a coverage score (% of spec requirements with a corresponding test). If below 80%, uncovered requirements are listed below the editor as action items.

**TASKS generation** — a task-harness validation runs automatically. Each task references specific harness tests by name. Flagged tasks (missing test references or references to nonexistent tests) are listed as action items.

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

Once all four stages are finalised two export options activate in the workspace header:

```
[↓ Download ZIP]   [↑ Export to GitHub]
```

Both exports produce the same file layout. No credits are deducted for either export path.

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

Credit balance shown prominently. When credits reach zero:

> [!danger] Credit Exhaustion State "You've used all 50 free credits. The Pro plan offers 1,000 credits per month." → Waitlist link (payments not in V1).

---

## 5. Pipeline Stages — Detailed Specification

### 5.1 SPEC.md

**Input:** Problem statement from the user

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

Input:    [files or dependencies]
Goal:     [what to build]
Tests:    [specific test names from harness]
Done when: All named tests pass with no skips or mocks
Reference: SPEC.md §N · PLAN.md §N
```

**Eval checks:**

- [ ] Every task references at least one harness test by name
- [ ] Referenced tests exist in the harness output
- [ ] No task has a vague done condition
- [ ] Tasks in valid dependency order
- [ ] First task is always harness setup

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

## 9. Credit System

### Credit Ledger

> [!note] Design Rule The credit ledger is append-only. Balance is always computed as `SUM(amount) WHERE user_id = ?`. Credits are never updated in place. Every change is a new ledger entry.

### Credit Deduction Flow

```
User triggers LLM action
        ↓
Credit balance checked
        ↓
Insufficient? → Request rejected, clear message shown
        ↓
Sufficient? → Credits deducted atomically
        ↓
LLM call made
        ↓
Call fails? → Deduction reversed (positive ledger entry)
        ↓
Call succeeds? → Deduction stands
```

### Free Tier

- 50 credits on account creation
- One-time allocation (no monthly reset in V1)
- When zero: credit exhaustion state with Pro waitlist link

### Credit Display

|Location|Display|
|---|---|
|Top navigation bar|Current balance on all authenticated pages|
|Workspace view|Credit meter below stage action buttons|
|Below 10 credits|Low-credit warning shown|

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
|created_at|TIMESTAMPTZ||
|updated_at|TIMESTAMPTZ||

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
|POST|/workspaces|Create a new workspace|
|GET|/workspaces/{id}|Get workspace with all stages|
|PATCH|/workspaces/{id}|Update workspace name|
|DELETE|/workspaces/{id}|Archive workspace (soft delete)|
|POST|/workspaces/{id}/export|Download zip of all four stages|
|POST|/workspaces/{id}/export/github|Push workspace to a new GitHub repo; create issues|
|GET|/workspaces/{id}/export/github|Return latest GitHub push record for this workspace|

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
|GET|/credits/balance|Return current credit balance|
|GET|/credits/history|Return credit ledger entries (paginated)|

### Providers

|Method|Endpoint|Description|
|---|---|---|
|GET|/providers|Return available providers and models|

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

### Rate Limits

|Tier|Scope|Limit|Window|
|---|---|---|---|
|Global|Per IP|1,000 requests|1 minute|
|User API|Per user|100 requests|1 minute|
|User LLM|Per user|10 LLM calls|1 minute|
|User LLM Daily|Per user|200 LLM calls|24 hours|
|Auth Login|Per IP|5 attempts|5 minutes|
|GitHub Export|Per user|3 exports|1 hour|

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

---

## 13. Assumptions

> [!warning] Validate These Each assumption below should be validated before or during V1 development. If an assumption is wrong it may require a spec change.

**Assumption 1 — Model selection is not friction.** Developers are willing to select their preferred provider and model rather than having SpecForge choose for them. If this creates too much friction, a pre-selected recommended default can be added.

**Assumption 2 — 50 credits is enough to experience full pipeline value.** If users consistently run out before completing their first workspace the free allocation needs to increase.

**Assumption 3 — Export to zip is the right delivery mechanism.** Users want to drop files into their project and use them with a coding agent. A future version might integrate directly with the coding agent's context window.

**Assumption 4 — The pipeline order is strict and non-skippable.** Users cannot skip stages. If experienced users want to jump directly to HARNESS on a well-understood project type, a skip mode could be added post-V1.

**Assumption 5 — Google OAuth is sufficient for sign-in.** GitHub OAuth is used only for the export integration, not for authentication. Enterprise SSO is explicitly out of scope.

**Assumption 8 — One repo per workspace is the right export model.** Users want to start a fresh repo each time rather than push updates into an existing one. Re-export updates the previously created repo in place.

**Assumption 9 — GitHub Issues are the right unit for tasks.** Developers working in GitHub use Issues as their unit of work. No GitHub Projects, Milestones, or Labels are created in the initial export; users can add these on GitHub after export.

**Assumption 10 — Synchronous export is acceptable.** A workspace with 30 tasks will take roughly 30 seconds end-to-end under normal GitHub API conditions. If this is consistently too slow, a background job with SSE progress streaming can be added using the same pattern as stage generation.

**Assumption 6 — A Pro waitlist is an acceptable credit exhaustion state.** If conversion intent is high, moving payments into V1 may be worth the additional build time.

**Assumption 7 — Langfuse is an optional observability enhancement.** Its unavailability must never surface to users or affect credit accounting, stage generation, or eval scoring. The system runs identically with `LANGFUSE_SECRET_KEY` unset; when it is set, Langfuse becomes an additional sink for prompt-level traces, prompt versions, eval scores, and dataset items. If a Langfuse call fails for any reason — network error, auth failure, rate limit, schema rejection — the failure is logged and swallowed. No user-facing flow may raise on a Langfuse error.

---

## 14. Out of Scope for V1

| Feature                              | When           |
| ------------------------------------ | -------------- |
| Payments and subscriptions           | V2             |
| Approval workflows                   | V2 Team        |
| Jira integration                     | V2             |
| Team workspaces                      | V2             |
| Chat panel per stage                 | V2             |
| Mobile and tablet responsive design  | Post V1        |
| Self-host installation documentation | Post V1 launch |
| Email notifications                  | V2             |
| Custom prompt templates              | V3             |
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
|Return rate|≥ 40%|% of users who complete one workspace and start a second|
|Qualitative signal|10 user interviews|Did they use the output in a real project?|

---

_SpecForge V1 SPEC.md · Version 1.2.0 · 2026-05-19 — added GitHub export integration: §4.8 expanded with GitHub export flow, §4.9 GitHub connection flow, §8 GitHub OAuth, §10 UserIntegration/IntegrationPush/IntegrationPushTask models, §11 integrations and GitHub export endpoints, §12 GitHub token security and rate limit, Assumptions 8–10. ZIP export unchanged._

_Version 1.1.0 · 2026-05-07 — added Langfuse-backed LLM observability under §12 and Assumption 7. No product-flow changes._