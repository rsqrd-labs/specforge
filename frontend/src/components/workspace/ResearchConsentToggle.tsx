import { useRef, useState } from "react"
import { useFocusTrap } from "../../hooks/useFocusTrap"
import { setWorkspaceResearch } from "../../services/api"

interface ResearchConsentToggleProps {
  workspaceId: string
  enabled: boolean
  /** When true the control is read-only (e.g. a generation is in flight). */
  disabled?: boolean
  /** Notified with the new value after a successful backend toggle. */
  onChanged: (enabled: boolean) => void
}

/**
 * Per-workspace opt-in for Brave web-research enrichment (issue #12, §6.5).
 *
 * Turning research ON is a third-party data egress AND a credit charge, so the
 * first enable is gated behind an explicit consent dialog that spells out both.
 * Turning it OFF is immediate (no dialog) — opting out is always one click.
 * Generation works fully without research, so this only controls *whether we
 * may*, never *whether generation runs*.
 */
export function ResearchConsentToggle({
  workspaceId,
  enabled,
  disabled = false,
  onChanged,
}: ResearchConsentToggleProps) {
  const [consentOpen, setConsentOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  useFocusTrap(dialogRef, () => setConsentOpen(false))

  async function applyChange(next: boolean) {
    setBusy(true)
    setError(null)
    try {
      const updated = await setWorkspaceResearch(workspaceId, next)
      onChanged(updated.brave_research_enabled ?? next)
      setConsentOpen(false)
    } catch {
      setError("Couldn't update web research. Please try again.")
    } finally {
      setBusy(false)
    }
  }

  function handleToggle() {
    if (disabled || busy) return
    if (enabled) {
      // Opting out is immediate — never gated.
      void applyChange(false)
    } else {
      // Opting in requires explicit consent first.
      setError(null)
      setConsentOpen(true)
    }
  }

  return (
    <div className="research-consent">
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        aria-label="Web research for this workspace"
        disabled={disabled || busy}
        onClick={handleToggle}
        className={`research-consent-switch ${enabled ? "on" : "off"}`}
      >
        <span className="research-consent-knob" aria-hidden="true" />
      </button>
      <div className="research-consent-label">
        <span className="research-consent-title">Web research</span>
        <span className="research-consent-state">
          {enabled ? "On — grounds generation in current web context" : "Off"}
        </span>
      </div>
      {error && !consentOpen ? (
        <p className="research-consent-error" role="alert">
          {error}
        </p>
      ) : null}

      {consentOpen ? (
        <div
          className="create-modal-backdrop"
          onClick={(e) => e.target === e.currentTarget && !busy && setConsentOpen(false)}
        >
          <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="research-consent-title"
            className="create-modal"
          >
            <div className="create-modal-header">
              <h2 id="research-consent-title" className="create-modal-title">
                Enable web research for this workspace?
              </h2>
              <button
                onClick={() => !busy && setConsentOpen(false)}
                className="create-modal-close"
                aria-label="Close"
              >
                ✕
              </button>
            </div>
            <div className="create-modal-body">
              <p className="workspace-credit-value-copy">
                To ground your spec in current tools and best practices, SpecForge
                will send this workspace's idea text to{" "}
                <strong>Brave Search (a third-party service)</strong> to fetch
                relevant, up-to-date web context. <strong>This is off by default
                and costs 1 credit per generation that uses it.</strong> Your idea
                text is shared with Brave only while research is enabled; turn it
                off any time. Generation still works fully without research.
              </p>
              {error ? (
                <p className="modal-error" role="alert" style={{ marginTop: 0 }}>
                  {error}
                </p>
              ) : null}
              <div className="modal-footer">
                <button
                  type="button"
                  onClick={() => setConsentOpen(false)}
                  disabled={busy}
                  className="modal-cancel"
                >
                  Not now
                </button>
                <button
                  type="button"
                  onClick={() => void applyChange(true)}
                  disabled={busy}
                  className="modal-submit"
                >
                  {busy ? "Enabling…" : "Enable web research"}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
