import axios from "axios"
import { afterEach, describe, expect, it, vi } from "vitest"

import {
  downloadPublicStoryboard,
  getPublicStoryboard,
} from "./api"
import type {
  StoryboardDownloadKind,
  StoryboardPublicDownloadKind,
  StoryboardPublicResponse,
  StoryboardSharePermissions,
} from "../types/storyboard"

// A minimal allow-list public response used as the happy-path payload.
const PUBLIC_RESPONSE: StoryboardPublicResponse = {
  title: "Launch Keynote",
  presentation: {
    title: "Launch Keynote",
    theme: {
      palette: ["#101418", "#1fb6ff", "#f5a623"],
      typography: "Geometric sans",
      motif: "Indica glassmorphism",
      transition_style: "Cinematic fade",
      diagram_style: "Layered planes",
    },
    sections: [],
    diagrams: [],
    source_map: {},
    notes: {},
    demo_script_md: "## Demo",
    technical_appendix_md: "## Appendix",
  },
  permissions: {
    allow_pdf_download: true,
    allow_notes_download: false,
    allow_appendix_download: false,
    allow_source_layer: false,
  },
  downloads: ["pdf", "demo-script"],
  shared_at: "2026-05-30T00:00:00Z",
}

function axios404(): unknown {
  // Shape that axios.isAxiosError recognises (isAxiosError === true) carrying a
  // 404 response — mirrors a real unknown/disabled/rotated public slug.
  return Object.assign(new Error("Not Found"), {
    isAxiosError: true,
    response: { status: 404 },
  })
}

describe("getPublicStoryboard 404 handling", () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("returns null for an unknown / disabled / rotated slug (404)", async () => {
    vi.spyOn(axios, "get").mockRejectedValueOnce(axios404())
    const result = await getPublicStoryboard("badslug")
    expect(result).toBeNull()
  })

  it("returns the public response for a valid slug", async () => {
    vi.spyOn(axios, "get").mockResolvedValueOnce({ data: PUBLIC_RESPONSE })
    const result = await getPublicStoryboard("goodslug")
    expect(result).not.toBeNull()
    expect(result?.title).toBe("Launch Keynote")
    // Permissions ride along so the public page can gate downloads.
    expect(result?.permissions.allow_pdf_download).toBe(true)
    expect(result?.downloads).toContain("pdf")
  })

  it("re-throws non-404 errors (it does not swallow real failures)", async () => {
    vi.spyOn(axios, "get").mockRejectedValueOnce(
      Object.assign(new Error("boom"), {
        isAxiosError: true,
        response: { status: 500 },
      }),
    )
    await expect(getPublicStoryboard("anyslug")).rejects.toThrow()
  })

  it("requests bytes as a Blob for a permitted public download kind", async () => {
    const spy = vi
      .spyOn(axios, "get")
      .mockResolvedValueOnce({ data: new Blob(["%PDF"]) })
    const blob = await downloadPublicStoryboard("goodslug", "pdf")
    expect(blob).toBeInstanceOf(Blob)
    // The bare public call requests a blob and targets the public download path.
    const [url, config] = spy.mock.calls[0]
    expect(String(url)).toContain("/storyboards/public/goodslug/download/pdf")
    expect((config as { responseType?: string }).responseType).toBe("blob")
  })
})

// ---------------------------------------------------------------------------
// Type compile coverage — these assignments fail `tsc --noEmit` if the unions
// or permission fields drift from the contract.
// ---------------------------------------------------------------------------

describe("Storyboard type contracts", () => {
  it("download kinds and public download kinds are the expected unions", () => {
    const ownerKinds: StoryboardDownloadKind[] = [
      "html",
      "pdf",
      "notes",
      "demo-script",
      "appendix",
    ]
    const publicKinds: StoryboardPublicDownloadKind[] = [
      "pdf",
      "notes",
      "demo-script",
      "appendix",
    ]
    // The public set is a strict subset of the owner set (no html).
    const ownerSet = new Set<string>(ownerKinds)
    expect(publicKinds.every((k) => ownerSet.has(k))).toBe(true)
    expect(ownerKinds).toContain("html")
    expect(publicKinds).not.toContain("html" as StoryboardPublicDownloadKind)
  })

  it("permission fields are the four documented booleans", () => {
    const perms: StoryboardSharePermissions = {
      allow_pdf_download: true,
      allow_notes_download: false,
      allow_appendix_download: false,
      allow_source_layer: false,
    }
    expect(Object.keys(perms).sort()).toEqual(
      [
        "allow_appendix_download",
        "allow_notes_download",
        "allow_pdf_download",
        "allow_source_layer",
      ].sort(),
    )
  })
})
