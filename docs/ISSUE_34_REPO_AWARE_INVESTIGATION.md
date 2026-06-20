# Issue #34 — OKF + Graph RAG + GitHub MCP: Investigation & Value Assessment

**Status:** Investigation / decision document
**Date:** 2026-06-20
**Author:** Engineering (per issue #34)
**Question asked:** Objectively, what could be added, and would it improve the experience or add significant value?

---

## 1. Verdict (read this first)

**Recommendation: do _not_ adopt the issue as written. Reject the OKF and Graph-RAG framing for now; pursue one small, well-scoped slice instead.**

The issue bundles three things — an "Open Knowledge Framework," a Graph-RAG repo-comprehension pipeline, and "GitHub MCP" — and implicitly asks SpecForge to become a tool that *ingests and explains existing codebases*. That is a **different product for a different user** than the one SpecForge serves today (greenfield *idea → spec*). The heavy parts (graph store, embeddings, incremental repo sync) are large, unproven bets that mostly serve a **new segment** we don't currently have, and the marquee "GitHub" piece is **largely redundant** with the Phase-21 GitHub App we already operate.

The one piece worth doing is small and reuses what we already built:

> **Recommended slice — "Inbound issue → increment idea":** turn GitHub Issues we already receive on the webhook into `IncrementIdea(source="github")` rows, and let the existing increment pipeline draft tasks from them. This needs **no embeddings, no graph, no new infra**, and it directly extends the timeline/increment model. It is the only part of #34 that is high-confidence positive-value for *current* users.

Everything below is the evidence for that verdict. An honest "not now, scope to X" is the deliverable the issue's "investigate objectively" ask invites — this is not a plan to build all three.

---

## 2. The frame that decides everything: who is the user?

SpecForge today is a **greenfield generator**. Its core loop is `idea → Spec → Plan → Harness → Tasks`, streamed and refined, and then *exported* to GitHub (Phase 13/21) as the system of record. The repo is an **output**, produced *from* the spec.

Issue #34 asks to **invert the arrow**: take an *existing* repo as **input**, comprehend it, and emit context/issues/tasks *from the code*. That is a real and reasonable product idea — but it serves a different job:

| | Today's user | Issue #34's user |
|---|---|---|
| Starting point | An idea, no code | A large existing codebase |
| Job to be done | "Turn my idea into a spec + tasks" | "Help me understand this repo and find work" |
| SpecForge's role | Author of record | Reader/analyst of someone else's code |
| Maturity in product | Core, shipped, monetised | Net-new, zero infra today |

**This is the load-bearing judgment.** The question is not "is Graph RAG cool" (it can be); it is "do we want to build a code-comprehension product for an onboarding-onto-a-large-repo user we don't currently have, when our paying user is mid-greenfield-spec?" For the current user, repo comprehension is mostly orthogonal to the job they're paying for. So "significant value" is the wrong yardstick for most of #34 — it would be a **pivot**, not a feature.

Where the two *do* touch is the **increment** loop: a finalised workspace already has a connected GitHub repo and absorbs new feature requests as deltas. That seam — not full-repo comprehension — is where modest, genuine value lives.

---

## 3. Unbundling the three components

They are not equally valuable. Objectivity means scoring them separately.

### 3.1 "GitHub MCP" — mostly redundant; one interesting inversion

The issue conflates two very different readings:

**(a) Consuming GitHub *via* an MCP server.** Low marginal value. We already run a **direct GitHub App** (Phase 21) that is *more* capable than the public GitHub MCP server for our paths: App-JWT → per-installation tokens, HMAC-verified webhooks with two-secret rotation, a durable arq worker with idempotent/checkpointed jobs, dead-letter queues, drift reconcile crons, and bidirectional issue↔task sync. A generic MCP client would be a *downgrade* in reliability and would duplicate `github_api_client.py`. **Don't replace working first-party integration with an MCP shim.** (Caveat: I did not spike the current public GitHub MCP server's exact tool surface; if it exposes something our App genuinely lacks, that's a small spike, not a rebuild. I'd assume redundancy until proven otherwise.)

**(b) Exposing *SpecForge itself* as an MCP server.** This is the genuinely interesting inversion the issue doesn't quite name. An MCP server that lets an external agent / IDE (Claude Code, Cursor, etc.) pull a workspace's **spec, plan, harness, and tasks as live context** would put SpecForge's *output* where developers already work. That is on-brand (we're the author of record), reuses existing read endpoints, needs **no RAG and no graph**, and serves our *current* user. **If anything MCP-shaped is worth doing, it's this — and it should be its own issue, not buried under repo ingestion.**

> **Score:** consuming-GitHub-via-MCP = redundant (skip). Exposing-SpecForge-as-MCP = promising but out of #34's stated scope; spin out separately.

### 3.2 Graph RAG — the real net-new bet, and the weakest-justified one

This is the part with no existing infrastructure (confirmed: no `pgvector`/embeddings/graph store anywhere in the backend) and the largest build: repo ingestion, chunking, embeddings, a vector store, a knowledge-graph builder, a retriever, graph propagation, **and** incremental sync to keep all of it fresh as repos change. That is a standing system with real COGS (embedding spend, graph/vector storage, RAG latency) and real ops surface.

Before funding that, it has to beat the cheaper baselines — and for our use case it probably doesn't:

- **Vanilla vector RAG** (chunk + embed + top-k) is far simpler and, for "answer a question about this repo," is frequently *as good or better* than Graph RAG per dollar. Graph RAG earns its keep mainly on **multi-hop, relationship-heavy** queries ("what breaks if I change X"), which is a narrow slice of what onboarding users ask.
- **Large-context "just put the relevant files in the prompt."** Our pipeline already routes to current-generation models with large context windows and an event-driven watchdog that tolerates long reasoning. For many repos, a smart file-selection + big-context pass is *dramatically* cheaper to build than a graph and competitive in quality.
- The Phase-21 export already gives us **structured task/issue graph data for free** — the relationships #34 wants a graph to *discover*, we partly *author*. We don't need to reverse-engineer a code graph to know which task maps to which issue/PR; we wrote that mapping.

**Graph RAG here reads as trend-following.** The literature is mixed on it beating well-tuned vanilla RAG for the cost, and our highest-value relationship data is already structured. **Do not build a knowledge graph on speculation.** If repo Q&A is ever pursued, start with vanilla RAG or large-context, measure, and only add a graph if multi-hop queries demonstrably fail — gated like every other risky route change in this codebase (golden-corpus / route-promotion gate).

> **Score:** highest effort, weakest justification, wrong-segment user. Defer; if ever needed, start two tiers simpler.

### 3.3 "Open Knowledge Framework" — underspecified; no clear marginal value

Unlike "RAG" or "MCP," **"Open Knowledge Framework" is not a standard term** with an agreed schema or implementation. Read charitably it means "an open, interoperable, provenance-bearing schema for the knowledge graph" — but that's just *a property of* the Graph-RAG store in 3.2, not a separate system. There is no concrete artifact to evaluate, and the provenance need it gestures at (where did this fact come from, which file/commit/issue) is **already modelled** by our `IntegrationPush` / `IntegrationPushTask` / `IncrementIdea.external_ref` rows for the data we author.

> **Score:** underspecified. No demonstrable marginal value over the structured provenance we already keep. Drop from scope until someone can state what concrete artifact it adds.

---

## 4. What's reusable vs. truly net-new (grounding the cost)

The reason the recommended slice is cheap and the full issue is expensive:

**Already built (reuse):**
- GitHub App + webhook + worker + bidirectional sync — `services/integrations/*`, `worker.py` (Phase 21).
- **`IncrementIdea` model already has `source: "user" | "github"` and `external_ref`** — i.e., the data model for "a GitHub issue became a SpecForge idea" *already exists* and is waiting to be populated.
- **Increment pipeline** (`increment_service.py`) already turns a feature request into appended tasks with stable content-derived `task_ref`s and pushes them back as issues — automated issue/task generation, already shipped, already credit-safe.
- **Fail-open external-context pattern** (`services/research/`, Brave issue #12): sanitised, prompt-injection-guarded, additive, never blocks generation. **Any** repo-context injection should clone this contract rather than invent one.

**Net-new (expensive, mostly unjustified):**
- Embeddings + vector store (no infra today).
- Knowledge-graph builder + graph propagation retriever.
- Full-repo ingestion/chunking for *source code* (parsers per language) and incremental re-index on every push.
- The privacy/permission surface for **reading arbitrary user source** at rest (embeddings/graph of someone's private code is a materially larger security + compliance footprint than today, where we store specs the user authored, not their proprietary codebase).

The gap between the two columns *is* the cost of issue #34 as written.

---

## 5. Recommended path

**Tier 0 — do now (high confidence, days not weeks):**
"**Inbound issue → increment idea.**" On the existing webhook, when a connected repo opens an issue, create `IncrementIdea(source="github", external_ref=<issue>)`. Surface these in the workspace; let the user promote one into the existing increment flow, which already drafts tasks and can push them back. Reuses Phase 21 + increment service end-to-end. No embeddings, no graph, no new security surface. This is the **only** part of #34 that clearly helps *current* users.

**Tier 1 — separate issue, evaluate on its own merits:**
"**SpecForge as an MCP server**" (§3.1b) — expose a workspace's spec/plan/harness/tasks as live MCP context for IDEs/agents. On-brand, no RAG, serves current users. Worth a design doc; **not** part of this issue.

**Tier 2 — only if we deliberately choose to pursue the onboarding/code-comprehension segment:**
Repo Q&A. If so, **start with vanilla vector RAG or large-context file selection**, copy the Brave fail-open contract, ship behind a flag, and *measure*. Add a knowledge graph **only** if measured multi-hop failures justify it. Treat any model-route impact as a golden-corpus-gated change. This is a **strategy decision (new segment), not a feature request** — escalate it as such before any build.

**Drop entirely:** "OKF" as a named workstream (§3.3) and "consume GitHub via MCP" (§3.1a, redundant).

---

## 6. Risks & costs if we built #34 as written

- **Segment risk (largest):** months of work serving a user we don't have, while the greenfield core gets no investment.
- **Security/compliance:** storing embeddings + a graph of users' **private source code** is a much bigger blast radius than today's user-authored specs; needs its own threat model, data-retention, and deletion story (cf. the rigor in `PAYMENT_THREAT_MODEL.md`).
- **COGS & latency:** embedding spend + vector/graph storage + RAG hops, against a product that just spent issue #17/#26 driving generation cost *down* to cheap-primary models. Repo-scale embeddings cut the other way.
- **Ops surface:** a freshness/incremental-sync system is a second living integration to keep honest (drift, reconcile, dead-letter) — we already carry that weight once for Phase 21.
- **Build-vs-baseline risk:** real chance the graph never beats vanilla RAG/large-context for the money — the classic Graph-RAG disappointment.

---

## 7. Suggested next step

1. Take this report back to the issue as the investigation deliverable.
2. **Approve Tier 0** (inbound issue → increment idea) as a normal scoped issue.
3. **Spin out Tier 1** (SpecForge-as-MCP) as its own enhancement issue if there's appetite.
4. **Explicitly decide** whether SpecForge wants the code-comprehension segment *before* anyone touches Graph RAG (Tier 2). If no, close the Graph-RAG/OKF scope of #34 as "investigated — not pursuing; rationale in this doc."
