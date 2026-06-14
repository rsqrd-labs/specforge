import { describe, expect, it } from "vitest"

import { getApiErrorMessage } from "./api"

/** Shape that `axios.isAxiosError` recognises (it checks `isAxiosError === true`). */
function axiosErrorWithDetail(detail: unknown) {
  return { isAxiosError: true, response: { data: { detail } } }
}

describe("getApiErrorMessage", () => {
  it("surfaces the message of a structured quality-gate 409 (issue #28)", () => {
    // The honest-copy path: finalise on a blocked stage returns
    // `{error, kind, message, recovery}`. The user must see the backend's
    // recovery message, never the generic draft-only copy.
    const error = axiosErrorWithDetail({
      error: "quality_gate_blocked",
      kind: "incomplete_output",
      message:
        "This version stopped before it was complete and can't be finalised. " +
        "Regenerate to produce a full version. Your previous attempt was refunded.",
      recovery: {
        action: "regenerate",
        overridable: false,
        credit_required: 10,
        refunded_prior_attempt: true,
        message: "ignored — top-level message wins",
      },
    })

    expect(getApiErrorMessage(error, "Only draft stages can be finalised.")).toBe(
      "This version stopped before it was complete and can't be finalised. " +
        "Regenerate to produce a full version. Your previous attempt was refunded.",
    )
  })

  it("surfaces a plain-string 409 detail verbatim (status-branch ValueError)", () => {
    // The non-gate finalise failure (e.g. status already finalised) is a bare
    // string detail; it is surfaced as-is, not replaced by the generic fallback.
    const error = axiosErrorWithDetail(
      "Stage status 'finalised' cannot be finalised",
    )

    expect(getApiErrorMessage(error, "Only draft stages can be finalised.")).toBe(
      "Stage status 'finalised' cannot be finalised",
    )
  })

  it("falls back to the generic copy only when there is no structured detail", () => {
    const error = { isAxiosError: true, response: { data: {} } }

    expect(getApiErrorMessage(error, "Only draft stages can be finalised.")).toBe(
      "Only draft stages can be finalised.",
    )
  })

  it("falls back to the generic copy for a non-axios error", () => {
    expect(getApiErrorMessage(new Error("boom"), "fallback copy")).toBe(
      "fallback copy",
    )
  })
})
