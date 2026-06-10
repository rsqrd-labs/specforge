import { useCallback, useRef, useState } from "react"
import { exportWorkspacePdf, getApiErrorMessage } from "../../services/api"
import { ActionAlertPanel } from "../shared/ActionAlert"
import { PDFIcon } from "../shared/icons"

interface ExportPDFButtonProps {
  workspaceId: string
  workspaceName: string
  disabled: boolean
  /**
   * Tooltip text rendered on the wrap element when `disabled` is true.
   * Should name the specific blocker (e.g. "Finalise HARNESS to enable PDF
   * export.") — generic copy is a regression per the T-167 design brief.
   */
  disabledReason?: string
  allFinalised: boolean
}

/**
 * T-USE-08 — Export PDF button.
 *
 * Sibling of the ZIP and GitHub buttons in the workspace header. Click →
 * fetch the PDF blob → trigger a browser download via a hidden anchor.
 * No toast, no banner: the browser's download UI is the confirmation.
 *
 * Failure surfaces as a single inline chip with a retry affordance — never
 * a full-screen error. We swap the label *in place* during the request so
 * the row layout does not jitter (the button width is held by the longer
 * "Generating PDF…" label so a 1-pixel shift cannot regress).
 */
export function ExportPDFButton({
  workspaceId,
  workspaceName,
  disabled,
  disabledReason,
  allFinalised,
}: ExportPDFButtonProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const anchorRef = useRef<HTMLAnchorElement | null>(null)

  const handleClick = useCallback(async () => {
    if (busy || disabled) return
    setBusy(true)
    setError(null)
    try {
      const blob = await exportWorkspacePdf(workspaceId)
      const url = URL.createObjectURL(blob)
      const anchor = anchorRef.current ?? document.createElement("a")
      anchor.href = url
      anchor.download = `specforge-${slugify(workspaceName)}.pdf`
      // Programmatically click so the browser's native download UI fires.
      // The anchor is not part of the document (when we built it inline)
      // but click() works regardless.
      anchor.click()
      // Defer revocation: some browsers need the URL to remain valid for a
      // moment after the click hands off to the download manager.
      window.setTimeout(() => URL.revokeObjectURL(url), 1_500)
    } catch (exc) {
      setError(getApiErrorMessage(exc, "Couldn't generate PDF. Try again?"))
    } finally {
      setBusy(false)
    }
  }, [busy, disabled, workspaceId, workspaceName])

  return (
    <div
      className="workspace-pdf-btn-wrap"
      data-tooltip={disabled ? disabledReason : undefined}
    >
      <button
        type="button"
        className={`workspace-pdf-btn ${allFinalised ? "ready" : ""}`}
        disabled={disabled || busy}
        onClick={() => void handleClick()}
        aria-label="Export PDF"
      >
        {busy ? "Generating PDF…" : <><PDFIcon />PDF</>}
      </button>
      <a ref={anchorRef} hidden aria-hidden="true" />
      {error && (
        <ActionAlertPanel
          severity="error"
          title="PDF export failed"
          message={error}
          recovery="Your workspace is saved. Try exporting again."
          source="Export"
          primaryAction={{
            label: "Retry",
            onSelect: () => {
              void handleClick()
            },
            autoDismiss: false,
          }}
          onDismiss={() => setError(null)}
          className="workspace-pdf-btn-error"
        />
      )}
    </div>
  )
}

function slugify(name: string): string {
  return (
    name
      .toLowerCase()
      .replace(/[^a-z0-9-]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || "workspace"
  )
}
