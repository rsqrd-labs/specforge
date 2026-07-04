# SpecForge Data Retention Policy

_Policy version: **trash-v1**_

This page explains how long SpecForge keeps your data and how you stay in control
of it. It is the user-facing companion to the operational runbook (`RUNBOOK.md`
§18) and must be published — alongside the Terms of Service / Privacy updates
that reference it — **before** workspace hard-deletion is enabled in production.

**Published at `/legal/retention`** (the URL the Settings → Data retention panel
links to), served by the marketing zone from
`apps/marketing/src/pages/legal/retention.astro`. That page is the rendered form
of this document — keep the two in sync and bump the policy version on any
semantic change.

The guiding principle: SpecForge keeps your **active** work indefinitely, prunes
only redundant history and internal telemetry on a schedule, and **never**
hard-deletes a workspace without either your recorded acknowledgment plus a
restore/export window, or a long conservative fallback window.

## Deleting a workspace → Trash → permanent deletion

Deleting a workspace **moves it to the trash**. It leaves your active dashboard
but is not destroyed:

- It appears under **Recently deleted** on your dashboard with a countdown.
- You can **Restore** it (it returns to active exactly as it was) or **Export**
  it (a full ZIP of the finalised spec/plan/harness/tasks) any time during the
  window.
- After **30 days** (`retention_trash_days`), it is permanently deleted along
  with its versions, keynotes, and GitHub-sync records. Your **credit history and
  account remain untouched.**

Restoring, then deleting again, restarts the 30-day clock.

Workspaces deleted before this policy took effect (or by an out-of-date browser
tab that could not record the notice) are kept for a longer conservative window
of **180 days** (`retention_legacy_archived_days`) before permanent deletion.

Permanent deletion is irreversible. Export anything you want to keep first.

## Version & keynote history

To keep your workspaces fast and your storage bounded, older redundant history is
pruned:

- **Stage versions** — the most recent **20** versions of each stage are always
  kept. Older versions are pruned only once they are more than **90 days** old.
  The version your workspace currently points at is never pruned, and neither is
  any version that has been pushed to GitHub.
- **Keynotes (Storyboards)** — the most recent **5** keynotes per workspace are
  kept; older ones are pruned once more than **90 days** old. A keynote with a
  live public share link is never pruned.

## Internal telemetry

SpecForge keeps internal operational logs (LLM cost/quality events, evaluation
results, failed background-job records) for **up to 180 days** to run and improve
the service. These contain no shareable artifact content beyond what is needed
for cost and quality accounting, and are never surfaced in the product.

## What is kept indefinitely

Your **account**, **credit ledger and billing history**, connected **integrations**
(e.g. GitHub installations), and starter **templates** are retained for as long
as your account exists, for financial, security, and audit reasons.

## Your controls

- **Restore** or **Export** any trashed workspace before its window ends.
- **Export** any finalised workspace at any time (ZIP or PDF).
- The live windows above are shown in **Settings → Data retention**.

## Account deletion & data-subject requests

Deleting your entire account (as opposed to a single workspace) and formal
data-subject access/erasure requests are handled separately; contact support.
Billing settlement on account closure follows the billing operations runbook
(`RUNBOOK.md` §9).
