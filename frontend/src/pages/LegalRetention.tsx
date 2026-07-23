import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { BrandLockup } from "../components/shared/BrandLogo"
import { MarkdownRenderer } from "../components/workspace/MarkdownRenderer"
import { getRetentionPolicy } from "../services/api"
import type { RetentionPolicy } from "../types/retention"

// The published data-retention policy (issue #43, plan §5.5) — the page the
// Settings → Data retention panel and the delete-confirmation acknowledgment
// point at. Registered OUTSIDE the auth guard: the policy must be readable
// without signing in, and (like PublicWorkspaceView) this file must not import
// any authenticated client-side store.
//
// The prose is the user-facing rendering of docs/RETENTION_POLICY.md — keep the
// two in sync and bump the policy version on any semantic change. Windows are
// interpolated from GET /retention/policy so the page always states the live
// values; the defaults below mirror backend/config.py so the page is complete
// even while the request is in flight or if the backend is unreachable.

const DEFAULT_POLICY: RetentionPolicy = {
  policy_version: "trash-v1",
  trash_days: 30,
  legacy_archived_days: 180,
  stage_versions_keep: 20,
  stage_versions_min_age_days: 90,
  storyboards_keep: 5,
  storyboards_min_age_days: 90,
  cost_events_days: 180,
  eval_results_days: 180,
}

export function policyMarkdown(p: RetentionPolicy): string {
  return `
This page explains how long Thought2Build keeps your data and how you stay in
control of it.

The guiding principle: Thought2Build keeps your **active** work indefinitely, prunes
only redundant history and internal telemetry on a schedule, and **never**
permanently deletes a workspace without either your recorded acknowledgment plus
a restore/export window, or a long conservative fallback window.

## Deleting a workspace: trash, then permanent deletion

Deleting a workspace **moves it to the trash**. It leaves your active dashboard
but is not destroyed:

- It appears under **Recently deleted** on your dashboard with a countdown.
- You can **Restore** it (it returns to active exactly as it was) or **Export**
  it (a full ZIP of the finalised spec, plan, harness, and tasks) any time
  during the window.
- After **${p.trash_days} days** it is permanently deleted along with its
  versions, keynotes, and GitHub-sync records. Your credit history and account
  remain untouched, and anything already pushed to your GitHub repository stays
  in your repository — Thought2Build only removes its own sync records.

Restoring, then deleting again, restarts the ${p.trash_days}-day clock.

Workspaces deleted before this policy took effect (or from an out-of-date
browser session that could not record the notice) are kept for a longer
conservative window of **${p.legacy_archived_days} days** before permanent
deletion.

Permanent deletion is irreversible. Export anything you want to keep first.

## Version and keynote history

To keep your workspaces fast and your storage bounded, older redundant history
is pruned:

- **Stage versions** — the most recent **${p.stage_versions_keep}** versions of
  each stage are always kept. Older versions are pruned only once they are more
  than **${p.stage_versions_min_age_days} days** old. The version your workspace
  currently points at is never pruned, and neither is any version that has been
  pushed to GitHub.
- **Keynotes (Storyboards)** — the most recent **${p.storyboards_keep}**
  keynotes per workspace are kept; older ones are pruned once more than
  **${p.storyboards_min_age_days} days** old. A keynote with a live public share
  link is never pruned.

## Internal telemetry

Thought2Build keeps internal operational logs (LLM cost and quality events,
evaluation results, failed background-job records) for up to
**${p.cost_events_days} days** to run and improve the service. These contain no
shareable artifact content beyond what is needed for cost and quality
accounting, and are never surfaced in the product.

## What is kept indefinitely

Your account, credit ledger and billing history, connected integrations (for
example GitHub installations), and starter templates are retained for as long as
your account exists, for financial, security, and audit reasons.

## Your controls

- **Restore** or **Export** any trashed workspace before its window ends.
- **Export** any finalised workspace at any time (ZIP or PDF).
- The live retention windows are always shown in **Settings → Data retention**.

## Account deletion and data-subject requests

Deleting your entire account (as opposed to a single workspace) and formal
data-subject access or erasure requests are handled separately — contact support
and we will process your request.
`.trim()
}

export default function LegalRetention() {
  const [policy, setPolicy] = useState<RetentionPolicy>(DEFAULT_POLICY)

  useEffect(() => {
    let cancelled = false
    getRetentionPolicy()
      .then((p) => {
        if (!cancelled) setPolicy(p)
      })
      .catch(() => {
        // Keep the config-default copy — a legal page must never render empty.
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    document.title = "Data Retention Policy — Thought2Build"
    return () => {
      document.title = "Thought2Build"
    }
  }, [])

  return (
    <div className="public-view-shell">
      <header className="public-view-cover">
        <BrandLockup variant="compact" className="public-view-brand" />
        <h1 className="public-view-title">Data Retention Policy</h1>
        <p className="public-view-attribution">
          Policy version: {policy.policy_version}
        </p>
      </header>

      <main className="public-view-content legal-prose">
        <MarkdownRenderer content={policyMarkdown(policy)} />
      </main>

      <footer className="public-view-footer">
        <p>
          <Link to="/legal/terms" className="public-view-footer-link">
            Terms of Service
          </Link>
          {" · "}
          <Link to="/legal/privacy" className="public-view-footer-link">
            Privacy Policy
          </Link>
          {" · "}
          <Link to="/" className="public-view-footer-link">
            ← Back to Thought2Build
          </Link>
        </p>
      </footer>
    </div>
  )
}
