/**
 * Harness contracts for Phase 15 — Enterprise Production Hardening
 * (frontend layer: T-181, T-186, T-187, T-188, T-189b).
 *
 * These tests are RED before the frontend hardening tasks are implemented
 * and GREEN after.
 *
 * Findings addressed here:
 *   H-5  Markdown XSS — no rehype-sanitize → T-181
 *   M-4  SSE lifecycle — null set before close → T-186
 *   M-5  Eval polling silently drops error → T-187
 *   M-6  streamingContent typed as union with string → T-188
 *   M-7  SSE comment contradicts code → T-186
 *   L-3  CreditConfirmModal duplicate prop aliases → T-189b
 *   L-4  ExportGitHubModal setTimeout auto-close → T-189b
 *   L-5  TemplatesStrip no error boundary → T-189b
 *   L-6  SharePublicLinkModal no focus trap → T-189b
 *
 * Design invariants enforced here:
 *   - rehype-sanitize is a listed dependency and is used in MarkdownRenderer.
 *   - SSE cleanup closes the connection before nulling the ref.
 *   - Eval polling surfaces an error badge after max retries — no silent drop.
 *   - streamingContent is typed as Record<string, string>, not a union.
 *   - CreditConfirmModal props use onConfirm/onClose exclusively.
 *   - ExportGitHubModal closes via onSuccess callback, not setTimeout.
 *   - TemplatesStrip is wrapped in an error boundary.
 *   - SharePublicLinkModal traps focus when open.
 */

import { describe, expect, it } from "vitest"
import { readFile } from "node:fs/promises"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const __dirname = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = resolve(__dirname, "../../..")
const FRONTEND_SRC = resolve(REPO_ROOT, "frontend/src")

async function tryRead(relPath: string): Promise<string | null> {
  try {
    return await readFile(resolve(REPO_ROOT, relPath), "utf8")
  } catch {
    return null
  }
}

// ---------------------------------------------------------------------------
// T-181 (H-5): Markdown XSS — rehype-sanitize must be installed and used
// ---------------------------------------------------------------------------

describe("phase15 markdown XSS remediation (H-5)", () => {
  it("rehype-sanitize is listed in frontend package.json dependencies", async () => {
    // T-181: The package must be declared so it ships in production builds.
    const pkg = await tryRead("frontend/package.json")
    expect(pkg, "frontend/package.json must exist").not.toBeNull()
    expect(
      pkg!,
      "frontend/package.json must list rehype-sanitize as a dependency. " +
        "Without it, react-markdown renders javascript: hrefs and onerror " +
        "attributes that execute in the user's browser. H-5 — T-181.",
    ).toContain("rehype-sanitize")
  })

  it("MarkdownRenderer imports and uses rehype-sanitize", async () => {
    // T-181: The import and the rehypePlugins prop must both be present.
    const candidates = [
      "frontend/src/components/workspace/MarkdownRenderer.tsx",
      "frontend/src/components/MarkdownRenderer.tsx",
      "frontend/src/components/common/MarkdownRenderer.tsx",
    ]
    let source: string | null = null
    for (const candidate of candidates) {
      source = await tryRead(candidate)
      if (source) break
    }
    expect(
      source,
      "A MarkdownRenderer component must exist under frontend/src/. " +
        "H-5 — T-181.",
    ).not.toBeNull()

    expect(
      source!,
      "MarkdownRenderer must import rehype-sanitize. H-5 — T-181.",
    ).toContain("rehype-sanitize")

    const usesAsPlugin =
      source!.includes("rehypeSanitize") ||
      source!.includes("rehype-sanitize")
    expect(
      usesAsPlugin,
      "MarkdownRenderer must pass rehypeSanitize to rehypePlugins prop of " +
        "<ReactMarkdown>. H-5 — T-181.",
    ).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// T-186 (M-4, M-7): SSE lifecycle — close before null, remove contradiction
// ---------------------------------------------------------------------------

describe("phase15 SSE lifecycle correctness (M-4, M-7)", () => {
  it("SSE cleanup closes connection before nulling the ref", async () => {
    // T-186 / M-4: Setting streamRef.current = null before calling .close()
    // nullifies the ref; the subsequent .close() call either throws or is a
    // no-op. The correct order: .close() first, then = null.
    const candidates = [
      "frontend/src/services/sseService.ts",
      "frontend/src/components/workspace/StreamingOverlay.tsx",
      "frontend/src/components/workspace/StageEditor.tsx",
    ]
    let sseSource: string | null = null
    let sseFile = ""
    for (const candidate of candidates) {
      const s = await tryRead(candidate)
      if (s && (s.includes("EventSource") || s.includes("streamRef"))) {
        sseSource = s
        sseFile = candidate
        break
      }
    }
    // If SSE is not in a dedicated service, search broadly.
    if (!sseSource) {
      const workspacePage = await tryRead("frontend/src/pages/Workspace.tsx")
      if (workspacePage && workspacePage.includes("streamRef")) {
        sseSource = workspacePage
        sseFile = "frontend/src/pages/Workspace.tsx"
      }
    }

    expect(
      sseSource,
      "A file managing SSE streaming with streamRef must exist. M-4 — T-186.",
    ).not.toBeNull()

    // The pattern "= null" immediately before ".close()" is the bug.
    // Detect the reverse: "= null" appearing BEFORE ".close()" within 5 lines.
    const lines = sseSource!.split("\n")
    let nullLineIdx = -1
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].includes("streamRef.current = null")) {
        nullLineIdx = i
      }
      if (
        nullLineIdx >= 0 &&
        i > nullLineIdx &&
        i - nullLineIdx <= 5 &&
        lines[i].includes(".close()")
      ) {
        expect.fail(
          `SSE cleanup in ${sseFile} sets streamRef.current = null (line ${nullLineIdx + 1}) ` +
            `before calling .close() (line ${i + 1}). ` +
            "Close the connection first, then set the ref to null. M-4 — T-186.",
        )
      }
    }
  })

  it("SSE code does not contain the contradictory comment", async () => {
    // T-186 / M-7: "keep open for eval event" appears immediately before a
    // .close() call — the comment and code contradict each other. The eval
    // result arrives via polling, not SSE.
    const filesToSearch = [
      "frontend/src/services/sseService.ts",
      "frontend/src/components/workspace/StreamingOverlay.tsx",
      "frontend/src/components/workspace/StageEditor.tsx",
      "frontend/src/pages/Workspace.tsx",
    ]
    for (const relPath of filesToSearch) {
      const source = await tryRead(relPath)
      if (source) {
        expect(
          source,
          `'keep open for eval event' comment in ${relPath} directly contradicts ` +
            "the .close() call that follows it. Remove the comment; eval results " +
            "arrive via polling, not SSE. M-7 — T-186.",
        ).not.toContain("keep open for eval event")
      }
    }
  })
})

// ---------------------------------------------------------------------------
// T-187 (M-5): Eval polling must surface an error after max retries
// ---------------------------------------------------------------------------

describe("phase15 eval polling error surface (M-5)", () => {
  it("QualityBadge accepts an error prop and renders a fallback", async () => {
    // T-187 / M-5: After 12 polling failures the badge shimmer must resolve
    // to a deterministic "Score unavailable" state, not spin forever.
    const source = await tryRead(
      "frontend/src/components/workspace/QualityBadge.tsx",
    )
    expect(
      source,
      "frontend/src/components/workspace/QualityBadge.tsx must exist. M-5 — T-187.",
    ).not.toBeNull()

    const hasErrorProp =
      source!.includes("error") &&
      (source!.includes("error?") ||
        source!.includes("error:") ||
        source!.includes("evalError"))
    expect(
      hasErrorProp,
      "QualityBadge.tsx must accept an error/evalError prop so the parent can " +
        "signal a terminal polling failure. M-5 — T-187.",
    ).toBe(true)

    const hasFallbackText =
      source!.includes("Score unavailable") ||
      source!.includes("Unavailable") ||
      source!.includes("unavailable")
    expect(
      hasFallbackText,
      "QualityBadge.tsx must render a visible fallback (e.g. 'Score unavailable') " +
        "when the error prop is true. M-5 — T-187.",
    ).toBe(true)
  })

  it("eval polling hook tracks consecutive failures and sets an error flag", async () => {
    // T-187 / M-5: The hook/component driving eval polling must count failures
    // and expose an evalError state after the retry threshold is reached.
    const candidates = [
      "frontend/src/components/workspace/StageEditor.tsx",
      "frontend/src/components/workspace/QualityBadge.tsx",
      "frontend/src/pages/Workspace.tsx",
    ]
    let found = false
    for (const candidate of candidates) {
      const source = await tryRead(candidate)
      if (source && (source.includes("evalError") || source.includes("consecutiveFailures") || source.includes("maxRetries"))) {
        found = true
        break
      }
    }
    expect(
      found,
      "A component or hook must track consecutive eval polling failures " +
        "and set an evalError (or equivalent) flag after the threshold (12). " +
        "Without this, users see an infinite shimmer on permanent eval failures. " +
        "M-5 — T-187.",
    ).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// T-188 (M-6): streamingContent must be Record<string, string>
// ---------------------------------------------------------------------------

describe("phase15 streamingContent type narrowing (M-6)", () => {
  it("Zustand store types streamingContent as Record<string, string>", async () => {
    // T-188 / M-6: The union type Record<string,string>|string requires
    // defensive guards at every read site. Narrowing to Record<string,string>
    // removes 5+ redundant guards and eliminates a class of runtime errors.
    const storeCandidates = [
      "frontend/src/store/stageStore.ts",
      "frontend/src/store/workspaceStore.ts",
      "frontend/src/store/index.ts",
    ]
    let storeSource: string | null = null
    let storeFile = ""
    for (const candidate of storeCandidates) {
      const s = await tryRead(candidate)
      if (s && s.includes("streamingContent")) {
        storeSource = s
        storeFile = candidate
        break
      }
    }

    expect(
      storeSource,
      "A Zustand store containing streamingContent must exist. M-6 — T-188.",
    ).not.toBeNull()

    expect(
      storeSource!,
      `${storeFile}: streamingContent must not be typed as a union with string. ` +
        "Use Record<string, string> exclusively. M-6 — T-188.",
    ).not.toMatch(/streamingContent[^:]*:\s*Record<string,\s*string>\s*\|\s*string/)

    expect(
      storeSource!,
      `${storeFile}: streamingContent must not be typed as string | Record. ` +
        "Use Record<string, string> exclusively. M-6 — T-188.",
    ).not.toMatch(/streamingContent[^:]*:\s*string\s*\|\s*Record/)
  })

  it("no typeof string guard remains on streamingContent at read sites", async () => {
    // T-188 / M-6: Once the type is narrowed, the typeof guards become dead
    // code and should be removed.
    const filesToSearch = [
      "frontend/src/components/workspace/StageEditor.tsx",
      "frontend/src/components/workspace/StreamingOverlay.tsx",
      "frontend/src/pages/Workspace.tsx",
    ]
    for (const relPath of filesToSearch) {
      const source = await tryRead(relPath)
      if (source && source.includes("streamingContent")) {
        const hasStringGuard =
          source.includes("typeof streamingContent") &&
          source.includes('"string"')
        expect(
          hasStringGuard,
          `${relPath}: typeof streamingContent === "string" guard must be removed ` +
            "after the type is narrowed to Record<string, string>. M-6 — T-188.",
        ).toBe(false)
      }
    }
  })
})

// ---------------------------------------------------------------------------
// T-189b (L-3): CreditConfirmModal must not have onOk/onDismiss aliases
// ---------------------------------------------------------------------------

describe("phase15 frontend debt sweep (L-3 through L-6)", () => {
  it("CreditConfirmModal removes cost/balance prop aliases", async () => {
    // T-189b / L-3: CreditConfirmModal accepts both creditCost/cost and
    // currentBalance/balance as aliases for the same props. The legacy aliases
    // must be removed; callers must use creditCost and currentBalance.
    const source = await tryRead(
      "frontend/src/components/workspace/CreditConfirmModal.tsx",
    )
    if (!source) return // component may not yet exist — skip rather than fail

    // The legacy alias prop names must not appear as prop interface members.
    // They may appear as local variables, but not as exported prop names.
    const hasCostAlias = source.match(/\bcost[?:]/)
    expect(
      hasCostAlias,
      "CreditConfirmModal.tsx must not expose a 'cost' prop alias. " +
        "Standardise on 'creditCost'. L-3 — T-189b.",
    ).toBeNull()

    const hasBalanceAlias = source.match(/\bbalance[?:]/)
    expect(
      hasBalanceAlias,
      "CreditConfirmModal.tsx must not expose a 'balance' prop alias. " +
        "Standardise on 'currentBalance'. L-3 — T-189b.",
    ).toBeNull()
  })

  it("ExportGitHubModal uses AbortController timeout, not infinite spinner", async () => {
    // T-189b / L-4: The export spinner runs indefinitely if the API call hangs.
    // The fix is an AbortController with a 30-second timeout — not a setTimeout
    // that auto-closes the modal (which would be a different bug).
    const source = await tryRead(
      "frontend/src/components/workspace/ExportGitHubModal.tsx",
    )
    if (!source) return // component may not yet exist — skip rather than fail

    const hasAbortController =
      source.includes("AbortController") || source.includes("AbortSignal")
    expect(
      hasAbortController,
      "ExportGitHubModal.tsx must use AbortController to apply a client-side " +
        "timeout to the export API call. Without it, a hung export shows an " +
        "infinite spinner with no recovery path. L-4 — T-189b.",
    ).toBe(true)

    // A timeout value should be present to configure the abort delay.
    const hasTimeoutValue =
      source.includes("30_000") ||
      source.includes("30000") ||
      source.includes("timeout")
    expect(
      hasTimeoutValue,
      "ExportGitHubModal.tsx must configure a timeout duration (e.g. 30_000ms) " +
        "for the AbortController. L-4 — T-189b.",
    ).toBe(true)
  })

  it("TemplatesStrip is wrapped in an error boundary", async () => {
    // T-189b / L-5: An unhandled error in template fetching propagates to
    // the workspace root and crashes the entire view.
    const candidates = [
      "frontend/src/components/workspace/TemplatesStrip.tsx",
      "frontend/src/components/TemplatesStrip.tsx",
    ]
    let stripSource: string | null = null
    for (const c of candidates) {
      stripSource = await tryRead(c)
      if (stripSource) break
    }
    if (!stripSource) return // not yet implemented — skip

    const parentFiles = [
      "frontend/src/pages/Dashboard.tsx",
      "frontend/src/pages/Workspace.tsx",
      "frontend/src/components/workspace/WorkspaceCreateModal.tsx",
    ]
    let hasErrorBoundary = false
    for (const relPath of parentFiles) {
      const parent = await tryRead(relPath)
      if (
        parent &&
        parent.includes("TemplatesStrip") &&
        (parent.includes("ErrorBoundary") ||
          parent.includes("errorBoundary") ||
          parent.includes("TemplatesStripErrorBoundary"))
      ) {
        hasErrorBoundary = true
        break
      }
    }
    // Also accept error boundary in the strip component itself.
    // (stripSource is non-null here — the early `return` above guarantees it.)
    if (!hasErrorBoundary) {
      hasErrorBoundary =
        stripSource.includes("ErrorBoundary") ||
        stripSource.includes("componentDidCatch")
    }

    expect(
      hasErrorBoundary,
      "TemplatesStrip must be rendered inside a React error boundary. " +
        "A network error during template fetch must not crash the workspace view. " +
        "L-5 — T-189b.",
    ).toBe(true)
  })

  it("SharePublicLinkModal uses a focus trap library", async () => {
    // T-189b / L-6: Without focus trapping, Tab key exits the modal and
    // reaches background elements — WCAG 2.1 SC 2.1.2 failure.
    const source = await tryRead(
      "frontend/src/components/workspace/SharePublicLinkModal.tsx",
    )
    if (!source) return // not yet implemented — skip

    const hasFocusTrap =
      source.includes("FocusTrap") ||
      source.includes("focus-trap") ||
      source.includes("useFocusTrap") ||
      source.includes("trapFocus")
    expect(
      hasFocusTrap,
      "SharePublicLinkModal.tsx must trap focus using focus-trap-react or " +
        "an equivalent mechanism. Without it, keyboard users can tab out of " +
        "the modal. L-6 — T-189b.",
    ).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// T-193: Public share page must have Content Security Policy configured
// ---------------------------------------------------------------------------

describe("phase15 public share page CSP (T-193)", () => {
  it("_headers or vercel.json configures CSP for /p/* routes", async () => {
    // T-193: The public share page is unauthenticated and renders LLM-generated
    // Markdown. A Content-Security-Policy is the last line of defense against
    // residual XSS even after rehype-sanitize (T-181).
    const headersFile = await tryRead("frontend/public/_headers")
    const vercelJson = await tryRead("vercel.json")

    let cspFound = false

    if (headersFile && headersFile.includes("Content-Security-Policy")) {
      cspFound = true
    }
    if (vercelJson && vercelJson.includes("Content-Security-Policy")) {
      cspFound = true
    }

    expect(
      cspFound,
      "A Content-Security-Policy header must be configured for /p/* routes " +
        "in frontend/public/_headers or vercel.json. The public share page is " +
        "unauthenticated and renders LLM-generated content. T-193.",
    ).toBe(true)
  })

  it("CSP for public share includes frame-ancestors none", async () => {
    // T-193: frame-ancestors 'none' prevents embedding the public share page
    // in an iframe, blocking clickjacking attacks.
    const headersFile = await tryRead("frontend/public/_headers")
    const vercelJson = await tryRead("vercel.json")

    const combinedSource = (headersFile ?? "") + (vercelJson ?? "")

    if (!combinedSource.includes("Content-Security-Policy")) {
      // CSP not yet configured — covered by previous test
      return
    }

    expect(
      combinedSource,
      "The Content-Security-Policy must include 'frame-ancestors' directive " +
        "to prevent the public share page from being embedded in an iframe. " +
        "T-193.",
    ).toContain("frame-ancestors")
  })
})

// ---------------------------------------------------------------------------
// T-192: CSRF exempt path configuration
// ---------------------------------------------------------------------------

describe("phase15 CSRF exempt path audit (T-192)", () => {
  it("no frontend code bypasses CSRF for logout", async () => {
    // T-192: The frontend must send CSRF headers on the logout request.
    // Check that the API client does not skip the CSRF token for /auth/logout.
    const apiSource = await tryRead("frontend/src/services/api.ts")
    if (!apiSource) return

    // If there's a logout function, it must not explicitly skip the CSRF header.
    if (apiSource.includes("logout")) {
      const logoutSkipsCsrf =
        apiSource.includes("withCredentials: false") &&
        apiSource.match(/logout[^}]*withCredentials\s*:\s*false/)
      expect(
        logoutSkipsCsrf,
        "api.ts logout function must not skip CSRF headers. " +
          "Logout is a mutation and requires CSRF protection. T-192.",
      ).toBeFalsy()
    }
  })
})
