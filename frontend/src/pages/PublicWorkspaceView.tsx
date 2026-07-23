import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { AiDisclaimer } from "../components/shared/AiDisclaimer"
import { BrandLockup } from "../components/shared/BrandLogo"
import { HarnessCoverageChip } from "../components/workspace/HarnessCoverageChip"
import { MarkdownRenderer } from "../components/workspace/MarkdownRenderer"
import { getPublicWorkspace } from "../services/api"
import type {
  PublicStageType,
  PublicWorkspaceResponse,
} from "../types/publicShare"

// T-USE-10 — Surface B. This page is the most-seen surface for non-customers.
//
// SECURITY: this file must NOT import any authenticated client-side store
// (the workspace data, the signed-in viewer's profile, or the credit
// balance). The harness contract test enforces this by string-searching
// the source. The public view reads exclusively from the unauthenticated
// /public/{slug} endpoint via the bare axios path in api.ts (no CSRF /
// auth headers attached).

const STAGE_LABELS: Record<PublicStageType, string> = {
  spec: "Spec",
  plan: "Plan",
  harness: "Harness",
  tasks: "Tasks",
}
const STAGE_ORDER: PublicStageType[] = ["spec", "plan", "harness", "tasks"]

const NOINDEX_META_ID = "thought2build-public-noindex"

/**
 * Inject `<meta name="robots" content="noindex, nofollow">` into <head>
 * for the duration of the public view. Belt-and-suspenders with the
 * backend's X-Robots-Tag header — a crawler that misses one will see the
 * other.
 */
function useNoIndexMeta() {
  useEffect(() => {
    const existing = document.getElementById(NOINDEX_META_ID)
    if (existing) return
    const meta = document.createElement("meta")
    meta.id = NOINDEX_META_ID
    meta.name = "robots"
    meta.content = "noindex, nofollow"
    document.head.appendChild(meta)
    return () => {
      meta.remove()
    }
  }, [])
}

function CoverChip({
  coverage,
}: {
  coverage: PublicWorkspaceResponse["coverage_summary"]
}) {
  if (!coverage) return null
  // T-USE-13: the public view uses the same HarnessCoverageChip component as
  // the workspace header and dashboard card so all three surfaces read as
  // one product element — the single most important signal for visitors.
  return (
    <div className="public-view-coverage-wrap">
      <HarnessCoverageChip coverage_summary={coverage} />
    </div>
  )
}

function Footer() {
  return (
    <footer className="public-view-footer">
      <p>
        Made with{" "}
        <a
          className="public-view-footer-link"
          href="https://thought2build.com"
          rel="noopener noreferrer"
        >
          Thought2Build
        </a>
        {" "}— turn your idea into a spec, plan, harness, and ready-to-ship
        tasks in 10 minutes →
      </p>
      <AiDisclaimer variant="footer" className="public-view-ai-disclaimer" />
    </footer>
  )
}

function LoadingSkeleton() {
  return (
    <div className="public-view-skeleton" aria-busy="true">
      <div className="public-view-skeleton-cover" />
      <div className="public-view-skeleton-tabs" />
      <div className="public-view-skeleton-body" />
    </div>
  )
}

function NotFound() {
  return (
    <div className="public-view-empty">
      <h1>This shared workspace link is no longer available</h1>
      <p>
        This link may have been disabled, rotated, or mistyped. Ask the owner
        for a fresh workspace share link.
      </p>
      <p>
        <Link to="/" className="public-view-footer-link">
          ← Back to thought2build.com
        </Link>
      </p>
    </div>
  )
}

export default function PublicWorkspaceView() {
  const { slug = "" } = useParams<{ slug: string }>()
  useNoIndexMeta()

  const [data, setData] = useState<PublicWorkspaceResponse | null | undefined>(
    undefined,
  )
  const [activeStage, setActiveStage] = useState<PublicStageType>("spec")
  const [errored, setErrored] = useState<boolean>(false)

  useEffect(() => {
    let cancelled = false
    setData(undefined)
    setErrored(false)
    void (async () => {
      try {
        const result = await getPublicWorkspace(slug)
        if (!cancelled) setData(result)
      } catch {
        if (!cancelled) setErrored(true)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [slug])

  useEffect(() => {
    if (data) {
      document.title = `${data.name} — Thought2Build`
    }
    return () => {
      document.title = "Thought2Build"
    }
  }, [data])

  if (data === undefined && !errored) return <LoadingSkeleton />
  if (errored || data === null) return <NotFound />
  if (!data) return null

  const stageContent =
    data.stages.find((s) => s.type === activeStage)?.content ?? ""

  return (
    <div className="public-view-shell">
      <header className="public-view-cover">
        <BrandLockup variant="compact" className="public-view-brand" />
        <h1 className="public-view-title">{data.name}</h1>
        <p className="public-view-attribution">Generated with Thought2Build</p>
        <CoverChip coverage={data.coverage_summary} />
      </header>

      <nav className="public-view-tabs" aria-label="Stage navigation">
        {STAGE_ORDER.map((type) => (
          <button
            key={type}
            type="button"
            className={`public-view-tab ${activeStage === type ? "active" : ""}`}
            onClick={() => setActiveStage(type)}
            aria-current={activeStage === type ? "page" : undefined}
          >
            {STAGE_LABELS[type]}
          </button>
        ))}
      </nav>

      <main className="public-view-content">
        <MarkdownRenderer
          content={stageContent}
          variant={activeStage === "harness" ? "harness" : "default"}
        />
      </main>

      <Footer />
    </div>
  )
}
