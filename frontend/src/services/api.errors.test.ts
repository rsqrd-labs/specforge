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

  it.each([null, { message: 42 }])(
    "falls back for malformed detail %#",
    (detail) => {
      expect(getApiErrorMessage(axiosErrorWithDetail(detail), "fallback")).toBe("fallback")
    },
  )

  it("preserves an explicitly empty string detail or structured message", () => {
    expect(getApiErrorMessage(axiosErrorWithDetail(""), "fallback")).toBe("")
    expect(getApiErrorMessage(axiosErrorWithDetail({ message: "" }), "fallback")).toBe("")
  })

  it("filters non-string structured hints and ignores non-array hints", () => {
    expect(getApiErrorMessage(axiosErrorWithDetail({ message: "Blocked", hints: ["Retry", 42, null] }))).toBe("Blocked Retry")
    expect(getApiErrorMessage(axiosErrorWithDetail({ message: "Blocked", hints: "Retry" }))).toBe("Blocked")
  })

  it("falls back to the generic copy for a non-axios error", () => {
    expect(getApiErrorMessage(new Error("boom"), "fallback copy")).toBe(
      "fallback copy",
    )
  })

  it("surfaces a refine selection_mismatch 409 message (stage screens audit F2)", () => {
    // `runRefine`'s catch now routes through getApiErrorMessage instead of a
    // fixed string, so a genuine race (another tab edited the stage) shows the
    // backend's honest reason. Shape mirrors routers/stage.py refine_stage:
    // `{"error": "selection_mismatch", "message": str(exc)}`.
    const error = axiosErrorWithDetail({
      error: "selection_mismatch",
      message:
        "The selected text no longer matches the current document. " +
        "It may have changed since you selected it — reselect and try again.",
    })

    expect(
      getApiErrorMessage(error, "Refine failed. Check your selection and try again."),
    ).toBe(
      "The selected text no longer matches the current document. " +
        "It may have changed since you selected it — reselect and try again.",
    )
  })

  it("uses the refine fallback for a 402 credit shape that carries no message", () => {
    // The refine 402 detail is `{"code": "insufficient_credits", "required": 3}`
    // — no `message` field — so the honest fallback copy is what the user sees.
    // (Dedicated refine-cost UX is F12 / Phase 6.)
    const error = axiosErrorWithDetail({ code: "insufficient_credits", required: 3 })

    expect(
      getApiErrorMessage(error, "Refine failed. Check your selection and try again."),
    ).toBe("Refine failed. Check your selection and try again.")
  })
})
