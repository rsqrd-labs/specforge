import { estimateEta } from "./useEtaEstimate"
import type { StageType } from "../../types/stage"

interface StageEmptyStateProps {
  stageType: StageType
  creditCost: number
}

/** Short, honest description of what a first generation produces — themed on
 *  the stage's actual section contract (backend `SECTION_CONTRACTS`) without
 *  enumerating exact headings here, so this copy can't drift out of sync with
 *  the prompt if a heading is renamed. */
const STAGE_PREVIEW_COPY: Record<StageType, string> = {
  spec: "requirements, user flows, and acceptance criteria",
  plan: "architecture, technology choices, and requirement traceability",
  harness: "test scaffolding and coverage mapping against the plan",
  tasks: "an ordered, dependency-aware task breakdown",
}

const STAGE_DISPLAY_NAME: Record<StageType, string> = {
  spec: "Spec",
  plan: "Plan",
  harness: "Harness",
  tasks: "Tasks",
}

/**
 * Replaces a bare, empty markdown panel before a stage's first generation.
 * The design review found this moment — the highest-anticipation,
 * highest-anxiety point in the product, since generation spends credits —
 * rendered as an unfurnished blank rectangle. This surfaces the one thing a
 * user needs before committing: what they'll get, what it costs, and roughly
 * how long it takes. The actual Generate action stays in the bar above (a
 * second button here would just duplicate the one real CTA).
 */
export function StageEmptyState({ stageType, creditCost }: StageEmptyStateProps) {
  const eta = estimateEta(stageType, "generate")
  return (
    <div className="stage-empty-state" role="status">
      <span className="stage-empty-state-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none">
          <path
            d="M6 3.5h9l4.5 4.5V20a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1Z"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinejoin="round"
          />
          <path d="M14.5 3.5V8h4.5" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
          <path d="M8 12.5h8M8 15.5h8M8 18.5h5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        </svg>
      </span>
      <p className="stage-empty-state-title">Nothing generated yet</p>
      <p className="stage-empty-state-copy">
        Generate will produce {STAGE_PREVIEW_COPY[stageType]} — {creditCost} credits, usually ready in ~{eta.p50}s.
      </p>
    </div>
  )
}
