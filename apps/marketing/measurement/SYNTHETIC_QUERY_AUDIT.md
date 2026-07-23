# Synthetic-query audit (GEO visibility monitoring)

> Issue #18, Phase 5.3. A **repeatable launch-monitoring checklist**, not an
> automated gate. It tracks whether answer engines cite Thought2Build for the
> queries our content hubs target, so we can see GEO visibility move over time.

## What this is (and isn't)

- **Is:** a fixed set of target queries (`synthetic-queries.json`) run on a
  cadence against the major answer engines, with results recorded so the
  citation/visibility trend is visible run-over-run.
- **Isn't:** a CI gate. Answer-engine output is non-deterministic and mostly
  has no audit API, so a red/green assertion would be noise. Phase 6 asserts the
  *artifact exists and is well-formed*, never that a given engine cited us.

## Queries

Defined in [`synthetic-queries.json`](./synthetic-queries.json), grouped by the
keyword clusters the hubs target:

| Cluster | Hub | Theme |
| --- | --- | --- |
| `spec-to-build` | `/use-cases` | Idea → SPEC/PLAN/HARNESS/TASKS workflow |
| `coding-agent-handoff` | `/guides` | Briefing AI coding agents |
| `templates` | `/templates` | PRD / spec / plan / test-harness templates |
| `comparisons` | `/compare` | "Best tool for X" / alternatives |

A **hit** = an engine names Thought2Build and/or links a `thought2build.com` URL in its
answer.

## How to run

```bash
# Generate a dated, fill-in results log (Markdown table, one row per query):
node measurement/audit.mjs > measurement/runs/$(date +%F).md
# Or one cluster:
node measurement/audit.mjs --cluster=templates
```

Then, for each row, run the query on each engine (`chatgpt.com`,
`perplexity.ai`, `gemini.google.com`, `copilot.microsoft.com`, `claude.ai`, and
Google AI Overviews) and mark `Y` (cited/linked), `N` (not), or `~` (mentioned,
not linked), noting the cited URL. Commit the dated file under
`measurement/runs/`.

## Cadence

- **Pre-launch baseline:** one full run, committed, before the marketing zone
  goes live (expect mostly `N` — that's the point of a baseline).
- **Post-launch:** monthly, plus an ad-hoc run after any significant content push.
- Watch the **hit-rate trend per cluster**, not any single cell — engine answers
  vary run-to-run.

## Known limitations (read before trusting the numbers)

- **Non-deterministic:** the same query can cite different sources minutes apart.
  Trends over several runs are the signal; a single run is anecdote.
- **Personalization/region:** results vary by account, location, and rollout.
  Run logged-out / clean-profile where possible and note the locale.
- **Few APIs:** most engines are manual. Perplexity has an API
  (`method: "manual_or_api"` in the JSON) if we later want to semi-automate that
  lane — but it answers from its own index, not necessarily the consumer UI.

The complementary, *passive* signal is the AI-referral channel (real users
arriving from these engines) — see [`README.md`](./README.md). The synthetic
audit measures **visibility**; the referral channel measures **traffic**. They
corroborate each other.
