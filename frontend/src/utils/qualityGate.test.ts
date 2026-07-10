import { describe, expect, it } from "vitest"

import type {
  EvalResult,
  QualityGateFinding,
  QualityGateInfo,
  Stage,
  StageType,
} from "../types/stage"
import {
  blockedDraftLabel,
  deriveAdvisoryFindings,
  deriveFinaliseGateBlock,
  deriveJudgeReconciliationNote,
  findingKindLabel,
  findingSeverityLabel,
  gateFallbackMessage,
  isInformationalFinding,
} from "./qualityGate"

function makeStage(quality_gate?: QualityGateInfo | null): Stage {
  return {
    id: "stage-1",
    workspace_id: "ws-1",
    type: "spec",
    content: "partial",
    status: "draft",
    current_version: 2,
    eval_result: null,
    finalised_at: null,
    review_gate_acknowledged: false,
    gap_patch_used: false,
    quality_gate: quality_gate ?? null,
    created_at: "2026-06-14T00:00:00Z",
    updated_at: "2026-06-14T00:00:00Z",
  }
}

function blockedGate(
  kind: string,
  recoveryMessage?: string,
): QualityGateInfo {
  return {
    stage: "spec" as StageType,
    kind,
    status: "blocked",
    recovery: recoveryMessage
      ? {
          action: "regenerate",
          overridable: kind === "missing_sections" || kind === "critic_findings",
          credit_required: 10,
          refunded_prior_attempt: kind === "incomplete_output",
          message: recoveryMessage,
        }
      : null,
  }
}

describe("deriveFinaliseGateBlock", () => {
  it("is not blocked when there is no quality gate", () => {
    expect(deriveFinaliseGateBlock(makeStage(null))).toEqual({
      blocked: false,
      message: "Regenerate, or override to finalise this version as-is",
      kind: null,
      label: "Blocked draft",
    })
  })

  it("is not blocked when the gate is clear/overridden, not blocked", () => {
    const stage = makeStage({ stage: "spec", kind: null, status: "overridden" })
    expect(deriveFinaliseGateBlock(stage).blocked).toBe(false)
  })

  it("handles a null/undefined stage without throwing", () => {
    expect(deriveFinaliseGateBlock(null).blocked).toBe(false)
    expect(deriveFinaliseGateBlock(undefined).blocked).toBe(false)
  })

  it("surfaces the backend recovery message verbatim when blocked", () => {
    // "after refetch": given a persisted stage object with status=blocked, the
    // disable derives blocked=true and shows the backend's authoritative copy.
    const message =
      "This version stopped before it was complete and can't be finalised. " +
      "Regenerate to produce a full version. Your previous attempt was refunded."
    const result = deriveFinaliseGateBlock(
      makeStage(blockedGate("incomplete_output", message)),
    )
    expect(result).toEqual({
      blocked: true,
      message,
      kind: "incomplete_output",
      label: "Blocked partial draft",
    })
  })

  // The guardrail: regression coverage across ALL gate kinds, not just the repro.
  it.each([
    [
      "incomplete_output",
      "Regenerate for a complete version, or finalise this one as-is",
      "Blocked partial draft",
    ],
    [
      "technology_safety",
      "Regenerate for an up-to-date version, or finalise this one as-is",
      "Blocked draft",
    ],
    [
      "missing_sections",
      "Regenerate, or override to finalise this version as-is",
      "Blocked draft",
    ],
    [
      "critic_findings",
      "Regenerate, or override to finalise this version as-is",
      "Blocked draft",
    ],
  ])(
    "falls back to kind-specific copy for %s when recovery is absent",
    (kind, expected, label) => {
      const result = deriveFinaliseGateBlock(makeStage(blockedGate(kind)))
      expect(result).toEqual({ blocked: true, message: expected, kind, label })
    },
  )
})

describe("blockedDraftLabel", () => {
  it("only calls an incomplete_output block a 'partial' draft", () => {
    // incomplete_output is the one kind that truly produced a partial document;
    // the others produced a complete draft the gate flagged.
    expect(blockedDraftLabel("incomplete_output")).toBe("Blocked partial draft")
    expect(blockedDraftLabel("technology_safety")).toBe("Blocked draft")
    expect(blockedDraftLabel("critic_findings")).toBe("Blocked draft")
    expect(blockedDraftLabel("missing_sections")).toBe("Blocked draft")
    expect(blockedDraftLabel(null)).toBe("Blocked draft")
    expect(blockedDraftLabel(undefined)).toBe("Blocked draft")
  })
})

describe("gateFallbackMessage", () => {
  it("covers known kinds and an unknown/forward-compatible default", () => {
    expect(gateFallbackMessage("incomplete_output")).toMatch(/complete version/)
    expect(gateFallbackMessage("technology_safety")).toMatch(/up-to-date/)
    expect(gateFallbackMessage("missing_sections")).toMatch(/override/)
    expect(gateFallbackMessage(undefined)).toMatch(/override/)
  })
})

describe("findingKindLabel", () => {
  it("maps known critic kinds to plain language", () => {
    expect(findingKindLabel("CoverageGap")).toBe("Uncovered requirement")
    expect(findingKindLabel("ShallowSection")).toBe("Needs more detail")
    expect(findingKindLabel("DeprecatedAPI")).toBe("Outdated technology")
  })

  it("falls back to a generic label for unknown/empty kinds", () => {
    expect(findingKindLabel("SomethingNew")).toBe("Suggestion")
    expect(findingKindLabel(null)).toBe("Suggestion")
    expect(findingKindLabel(undefined)).toBe("Suggestion")
  })

  it("maps the Phase-D condensation notice to a friendly label", () => {
    expect(findingKindLabel("ProblemStatementCondensed")).toBe(
      "Condensed problem statement",
    )
  })

  it("humanizes every blocking technology-safety code", () => {
    // The blocking gate popup used to render these raw; none may fall through.
    const codes = [
      "technology_eol",
      "technology_near_eol",
      "support_status_blocked",
      "vulnerable_dependency",
      "technology_unmaintained",
      "hard_denylist_match",
      "technology_safety_unverified",
      "technology_policy_stale",
      "technology_policy_unverified",
      "provider_stopped_by_limit",
    ]
    for (const code of codes) {
      const label = findingKindLabel(code, "Issue")
      expect(label).not.toBe("Issue")
      expect(label).not.toBe(code)
    }
  })

  it("uses the caller's neutral fallback on a blocking surface, not 'Suggestion'", () => {
    // An unmapped code on a blocking gate must never read as optional.
    expect(findingKindLabel("brand_new_block_code", "Issue")).toBe("Issue")
  })
})

describe("findingSeverityLabel", () => {
  it("capitalizes known severities and relabels the confusing 'unknown'", () => {
    expect(findingSeverityLabel("critical")).toBe("Critical")
    expect(findingSeverityLabel("HIGH")).toBe("High")
    expect(findingSeverityLabel("unknown")).toBe("Could not verify")
  })

  it("returns null when there is no severity to show", () => {
    expect(findingSeverityLabel(null)).toBeNull()
    expect(findingSeverityLabel(undefined)).toBeNull()
    expect(findingSeverityLabel("")).toBeNull()
  })
})

describe("isInformationalFinding", () => {
  it("flags the condensation notice as informational (no regenerate action)", () => {
    expect(isInformationalFinding("ProblemStatementCondensed")).toBe(true)
  })

  it("treats real critic findings and unknown/empty kinds as actionable", () => {
    expect(isInformationalFinding("CoverageGap")).toBe(false)
    expect(isInformationalFinding("SomethingNew")).toBe(false)
    expect(isInformationalFinding(null)).toBe(false)
    expect(isInformationalFinding(undefined)).toBe(false)
  })
})

describe("deriveAdvisoryFindings", () => {
  it("returns findings only for an advisory gate (issue #34)", () => {
    const advisory = makeStage({
      stage: "spec",
      kind: "critic_findings",
      status: "advisory",
      findings: [{ kind: "ShallowSection", detail: "thin", reference: null }],
    })
    expect(deriveAdvisoryFindings(advisory)).toHaveLength(1)
  })

  it("returns nothing for blocked/clear stages or a missing stage", () => {
    const blocked = makeStage({
      stage: "spec",
      kind: "critic_findings",
      status: "blocked",
      findings: [{ kind: "ShallowSection", detail: "thin", reference: null }],
    })
    expect(deriveAdvisoryFindings(blocked)).toEqual([])
    expect(deriveAdvisoryFindings(makeStage(null))).toEqual([])
    expect(deriveAdvisoryFindings(null)).toEqual([])
  })

  it("suppresses suggestions once the stage is finalised, restores on unlock", () => {
    const advisoryGate = {
      stage: "spec" as StageType,
      kind: "critic_findings",
      status: "advisory" as const,
      findings: [{ kind: "ShallowSection", detail: "thin", reference: null }],
    }
    // Finalised: the user accepted the artifact as-is — no floating suggestions.
    const finalised = { ...makeStage(advisoryGate), status: "finalised" as const }
    expect(deriveAdvisoryFindings(finalised)).toEqual([])
    // Unlocking it back to draft (same persisted gate) brings them back.
    const unlocked = { ...finalised, status: "draft" as const }
    expect(deriveAdvisoryFindings(unlocked)).toHaveLength(1)
  })
})

describe("deriveJudgeReconciliationNote", () => {
  const criticFinding: QualityGateFinding = {
    kind: "ShallowSection",
    detail: "Security section is thin",
    reference: "## Security",
  }
  const infoFinding: QualityGateFinding = {
    kind: "ProblemStatementCondensed",
    detail: "Input was condensed to fit budget",
    reference: null,
  }

  function makeEval(overrides: Partial<EvalResult> = {}): EvalResult {
    return {
      id: "eval-1",
      stage_version_id: "sv-1",
      stage_type: "spec",
      overall_score: 88,
      completeness: 90,
      clarity: 85,
      coverage_percent: null,
      uncovered_reqs: [],
      tasks_without_ref: [],
      flagged: false,
      created_at: "2026-07-10T00:00:00Z",
      ...overrides,
    }
  }

  it("notes the disagreement when the eval is clean but the critic left suggestions", () => {
    const note = deriveJudgeReconciliationNote(makeEval(), [criticFinding])
    expect(note).toBeTruthy()
    expect(note).toMatch(/found no gaps/i)
    expect(note).toMatch(/not a lower overall rating/i)
  })

  it("stays silent when both judges agree there are gaps", () => {
    // Eval flagged + critic suggestions point the same way — nothing to reconcile.
    expect(
      deriveJudgeReconciliationNote(makeEval({ flagged: true }), [criticFinding]),
    ).toBeNull()
    expect(
      deriveJudgeReconciliationNote(
        makeEval({ uncovered_reqs: ["FR-003"] }),
        [criticFinding],
      ),
    ).toBeNull()
  })

  it("stays silent without an eval result — a missing signal is not agreement", () => {
    expect(deriveJudgeReconciliationNote(null, [criticFinding])).toBeNull()
    expect(deriveJudgeReconciliationNote(undefined, [criticFinding])).toBeNull()
  })

  it("ignores purely informational findings — they are not judge disagreement", () => {
    expect(deriveJudgeReconciliationNote(makeEval(), [infoFinding])).toBeNull()
    expect(deriveJudgeReconciliationNote(makeEval(), [])).toBeNull()
    // ...but one actionable finding among informational ones still reconciles.
    expect(
      deriveJudgeReconciliationNote(makeEval(), [infoFinding, criticFinding]),
    ).toBeTruthy()
  })
})
