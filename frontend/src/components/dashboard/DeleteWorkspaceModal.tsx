import { useRef } from "react"
import { useFocusTrap } from "../../hooks/useFocusTrap"
import type { RetentionPolicy } from "../../types/retention"
import type { Workspace } from "../../types/workspace"
import { ActionAlertPanel } from "../shared/ActionAlert"

interface DeleteWorkspaceModalProps {
  workspace: Workspace
  error: string | null
  isDeleting: boolean
  /**
   * The retention policy (windows + ack version). Null while it is still loading
   * or if the policy endpoint failed — the dialog degrades to a generic window
   * message and still deletes (the backend falls back to the legacy window).
   */
  policy: RetentionPolicy | null
  onCancel: () => void
  onConfirm: () => void
}

export function DeleteWorkspaceModal({
  workspace,
  error,
  isDeleting,
  policy,
  onCancel,
  onConfirm,
}: DeleteWorkspaceModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  useFocusTrap(dialogRef, onCancel)

  const windowDays = policy?.trash_days ?? null

  return (
    <div
      className="create-modal-backdrop"
      onClick={(e) => e.target === e.currentTarget && !isDeleting && onCancel()}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-workspace-title"
        aria-describedby="delete-workspace-description"
        className="create-modal delete-workspace-modal"
      >
        <div className="create-modal-header">
          <h2 id="delete-workspace-title" className="create-modal-title danger">
            Move to Trash
          </h2>
          <button
            onClick={onCancel}
            className="create-modal-close"
            aria-label="Close"
            disabled={isDeleting}
          >
            X
          </button>
        </div>

        <div className="create-modal-body">
          <p id="delete-workspace-description" className="delete-workspace-copy">
            Move <strong>{workspace.name}</strong> to the trash?{" "}
            {windowDays !== null ? (
              <>
                It will be permanently deleted after <strong>{windowDays} days</strong>.
                You can restore or export it until then.
              </>
            ) : (
              <>
                It will be permanently deleted after the retention window. You can
                restore or export it from "Recently deleted" until then.
              </>
            )}
          </p>
          {error && (
            <ActionAlertPanel
              severity="error"
              title="Workspace could not be moved to trash"
              message={error}
              recovery="The workspace is still available. Try again."
              source="Dashboard"
            />
          )}
          <div className="modal-footer">
            <button
              type="button"
              onClick={onCancel}
              className="modal-cancel"
              disabled={isDeleting}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={onConfirm}
              disabled={isDeleting}
              className="modal-submit danger"
            >
              {isDeleting ? "Moving..." : "Move to Trash"}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
