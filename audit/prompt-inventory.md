# SpecForge Prompt Inventory

Coverage method: traced backward from every LLM adapter call site
(`anthropic_adapter.py` / `openai_adapter.py` / `google_adapter.py` →
`gateway.get_llm` / `call_judge_model` / `complete_background_llm` /
`InstrumentedAdapter.complete|stream`) to every caller in
`backend/services/**` and `backend/routers/**`. Confirmed call-site list
(one `grep` pass, verified against this table): `problem_compressor.py`,
`increment_service.py`, `provider_status.py`, `stage_manager.py`,
`spec_clarifier.py`, `gateway.py` (generic plumbing, no prompt of its own),
`eval_batch.py` (reuses `online_eval.build_eval_request`, no separate
prompt), `critic.py`, `pr_evaluator.py`, `online_eval.py`,
`batch_executor.py` (generic plumbing). No router calls an adapter
directly. No frontend/client-side prompt construction exists — all
generation is server-side (confirmed by grep across `frontend/src`, hits
were only provider-name UI labels).

Explicitly **not** prompts (checked and excluded): `tech_safety.py` (zero-LLM
policy/denylist validator), `demo_day_verdict.py` /
`demo_day_plan_linter.py` (zero-LLM structural linter), `stage_summary_service.py`
(regex summarizer), `services/security/output_validator.py` (regex leak
*detector*, not a prompt), `harness/prompt_eval/graders/*.py` (deterministic
offline graders, no LLM calls).

**Known blind spot (by design, per user direction):** `prompts/base.py:157`
(`load_prompt`) can serve a prompt body fetched live from Langfuse instead of
the in-code fallback, for every stage marked with a `_REMOTE_PROMPT_NAMES` /
`specforge.*.system` key. This audit evaluates the **in-code fallback** and
the load/override contract itself (row P01), not the live Langfuse content,
which this audit has no credentials to read.

| ID | File:Line | Type | Target model | Rendered length (approx) | Dynamic vars | Call site | Remote-overridable? |
|----|-----------|------|---------------|--------------------------|--------------|-----------|----------------------|
| P01 | `backend/prompts/base.py:1-204` | Shared infrastructure (system-prompt fragments + loader) | All (provider-agnostic) | ~700 words shared boilerplate | none (fragments); `load_prompt(name, fallback)` takes remote prompt name | Imported by every core/demo_day/harness_patch prompt module | Yes — is itself the override mechanism |
| P02 | `backend/prompts/spec.py:61-153` | System+user (core stage 1/4) | Anthropic Haiku 4.5 / GPT-5.4 Mini / Gemini 3.5 Flash (primary); mid tier on escalation | System ~900 words; user ~500 words + problem statement | `problem_statement`, `clarification_qa`, `research_context` | `prompt_builder.build_prompt("spec", …)` → `stage_manager.generate()` | Yes (`specforge.spec.system`) |
| P03 | `backend/prompts/plan.py:20-118` | System+user (core stage 2/4) | same tier ladder | System ~1400 words (largest structural spec); user ~350 words + spec | `spec`, `research_context` | `prompt_builder.build_prompt("plan", …)` | Yes (`specforge.plan.system`) |
| P04 | `backend/prompts/harness.py:10-146` | System+user (core stage 3/4) | same tier ladder | System ~1100 words; user ~450 words + spec + plan | `spec`, `plan`, `research_context` | `prompt_builder.build_prompt("harness", …)` | Yes (`specforge.harness.system`) |
| P05 | `backend/prompts/tasks.py:10-221` | System+user (core stage 4/4) | same tier ladder | System ~950 words; user ~600 words + spec+plan+harness | `spec`, `plan`, `harness`, `research_context` | `prompt_builder.build_prompt("tasks", …)` | Yes (`specforge.tasks.system`) |
| P06 | `backend/prompts/harness_patch.py:1-55` | System+user (gap-patch, non-streaming regenerate) | harness-tier route | System ~90 words (deliberately minimal); user ~40 words + truncated harness | `existing_harness` (truncated to 4000 chars), `uncovered_reqs` | `StageManager` gap-patch flow → `stage_manager.py:5529-5530` | Yes (`specforge.harness.patch.system`) |
| P07 | `backend/prompts/demo_day.py:30-434` | System+user, 4 stage variants (Demo Day mode) | same tier ladder, mid-biased | System ~1100-1400 words per stage; user ~250-400 words | same deps as P02-P05 | `prompt_builder.build_prompt` when `workspace.mode == "demo_day"` | Yes, `.demo_day` qualified names |
| P08 | `backend/prompts/storyboard.py:594-787` | System + user + repair (structured JSON output, Pydantic-validated) | Storyboard route (cheap-primary → mid escalation) | System ~1000 words; user ~300 words + source excerpts | `source.excerpts` (per-source-id), `workspace_name`, `problem_statement` | `storyboard_service.py:899-1027` | **No** — deliberately local-only (file docstring, security rationale) |
| P09 | `backend/prompts/spec_clarification.py:23-60` | System+user (pre-spec judge) | cheap judge tier (Haiku/GPT-4o Mini/Gemini Flash per docstring — **stale**, see P09 scorecard) | System ~130 words; user ~40 words + problem statement | `problem_statement` | `spec_clarifier.py:164-202` | **No** — hardcoded constant, no `load_prompt` |
| P10 | `backend/services/pipeline/critic.py:98-201` | System+user (quality-gate judge) | cheap judge tier | System ~350 words; user = full artifact + full deps (**unbounded**, see finding) | `stage_type`, `artifact_text`, `deps` (spec/plan/harness/tasks, whichever are upstream) | `critic_review()` → `stage_manager.py` (async advisory path + legacy sync path) | **No** — inline by design, Phase 19 security directive |
| P11 | `backend/services/pipeline/problem_compressor.py:132-144, 383-391` | System+user (abstractive compression judge, Rung 2) | cheap judge tier | System ~90 words; user = target-token instruction + narrative chunk | `content` (narrative chunk only — normative text never sent), `target_tokens` | `_summarize_chunk()` → `_rung2_abstractive()` → `prompt_builder`/`spec_clarifier` | **No** — inline by design |
| P12 | `backend/services/pipeline/agent_manual_service.py:76-110` | Downstream **agent-facing artifact** (not an API call — a file handed to the user's own Claude Code/Codex instance) | N/A (consumed by an external Claude Code/Codex session, not by SpecForge's own LLM calls) | ~350 words + interpolated PLAN Technology Stack section | `workspace.name`, `workspace.target_agent`, `plan_content`'s `## Technology Stack` section (regex-extracted, **not re-sanitized**) | `build_agent_manual()` → export/GitHub push bundle (Demo Day mode) | N/A — pure Python template |
| P13 | `backend/services/pipeline/increment_service.py:587-634` | System+user (increment delta generation) | increment route (not core-gen tier ladder) | System ~230 words; user = 4 wrapped baseline artifacts + feature request | `stages` (spec/plan/harness/tasks baseline), `feature_request` (sanitized) | `increment_service.py:270-342` | **No** — hardcoded, no Langfuse hook |
| P14 | `backend/services/evals/online_eval.py:109-193, 966-982` | System+user (online quality-scoring judge) | judge tier | System ~60 words; user = rubric (~180 words) + spec/artifact content | `content`, `spec_content` (via **`.replace()` chaining**, see finding) | `_build_eval_prompt()` → `_score_with_retry()` → `_call_eval_judge()`; also `build_eval_request()` reused by `eval_batch.py` (offline batch runner) | **No** — inline, no wrapping/authority-hierarchy framing (see finding) |
| P15 | `backend/services/integrations/pr_evaluator.py:150-172, 474-487` | System+user (PR-diff judge) | judge tier | System ~200 words; user = per-task criteria + bounded/truncated diff | `criteria` (dict of task_ref→text), `diff` (truncated at `_MAX_DIFF_CHARS`) | `run_pr_check()` → GitHub integration worker (`pr_check` job) | **No** — inline by design |
| P16 | `backend/services/llm/provider_status.py:161` | System (trivial health check) | judge-tier model per provider | ~8 words | none | Circuit-breaker health probe before `get_llm()` returns an adapter | **No** — inline literal |
| P17 | `backend/services/research/research_service.py:148-155` | Shared RAG-injection framing fragment (not a standalone call) | N/A — merged into P02-P05/P07 via `render_research_block` | ~70 words fixed header + sanitized/PromptGuard-scanned Brave snippets | Brave search results (sanitized + `PromptGuard`-scanned per item) | `_assemble_block()` → `fetch_context()` → threaded through `prompt_builder.build_prompt` as `research_context` | N/A |
| P18 | `backend/services/pipeline/stage_manager.py:276-301, 4036-4072` | System+user (interactive "refine" — focused/section rewrite) | `_route_for_refine` (cheap-primary, same ladder) | System ~180 words + per-stage boundary rules (~60-90 words); user = doc context + selection + instruction, all wrapped | `stage.type`-keyed `_REFINE_STAGE_RULES`, `content` (windowed doc context), `selected_text`, `instruction`, `request.mode` | `StageManager.refine()` | **No** — inline, no Langfuse hook |
| P19 | `backend/services/pipeline/stage_manager.py:1708-1745`; `backend/services/pipeline/artifact_validator.py:336-364` | Shared prompt fragment (chunk-continuation contract + completion sentinel) | All core-gen chunked calls | ~60-120 words appended per chunk | `chunk.instruction`, `prior_chunks` (wrapped untrusted), `repair_issues`, `chunk_key` | `_generate_chunks_parallel()` path in `stage_manager.py` | N/A — appended to whichever base prompt is active (P02-P05/P07) |
| P20 | `backend/services/pipeline/stage_manager.py:5359-5395` | User-prompt augmentation (critic-findings-injected regenerate — **legacy synchronous critic path only**, gated by `critic_async_advisory=false`) | same as base stage | ~50 words + findings block (findings from P10) | `findings` (list of `CriticFinding`), `base_user_prompt` (the original P02-P05/P07 user prompt) | `_regenerate_with_findings()` (name approximate) → `stage_manager.py` | N/A |

| P21 | `backend/services/integrations/agents_md_builder.py:57-151` | Downstream **agent-facing artifact** (generic, non-Demo-Day `AGENTS.md`; found in Phase 3 via `agent_manual_service.py`'s own docstring cross-reference — a Phase-1 discovery miss caught on the second pass) | N/A — consumed by an external coding agent | ~200 words + sanitized, bounded stage excerpts | `stages` (spec/plan/harness/tasks, each `sanitize_text`-cleaned and length-capped), `existing` (prior file content, round-tripped outside managed markers) | `build_agents_md()` → GitHub export sync (every workspace, all modes) | N/A — pure Python template |

**Total: 21 inventoried prompt/prompt-fragment sources** (8 standalone
system+user pairs feeding core generation surfaces, 5 independent LLM-judge
prompts, 1 shared infra module, 2 downstream-agent artifacts, 2 shared
fragments injected into other prompts, 1 trivial health check, 1 RAG framing
fragment, 1 augmentation-only fragment). Every adapter call site in the
codebase maps to exactly one row above; none were left unmapped. P21 was
added after the initial pass — direct evidence for the Phase-1 checkpoint's
value: a prompt module's own comment pointed at a sibling this audit had not
yet inventoried.
