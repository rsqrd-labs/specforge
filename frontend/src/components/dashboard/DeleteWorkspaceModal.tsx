import { useRef } from "react"
import { useFocusTrap } from "../../hooks/useFocusTrap"
import type { Workspace } from "../../types/workspace"

interface DeleteWorkspaceModalProps {
  workspace: Workspace
  error: string | null
  isDeleting: boolean
  onCancel: () => void
  onConfirm: () => void
}

export function DeleteWorkspaceModal({
  workspace,
  error,
  isDeleting,
  onCancel,
  onConfirm,
}: DeleteWorkspaceModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  useFocusTrap(dialogRef, onCancel)

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
            Delete Workspace
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
            Delete <strong>{workspace.name}</strong> from your dashboard? This removes
            it from active workspaces.
          </p>
          {error && <p className="modal-error">{error}</p>}
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
              {isDeleting ? "Deleting..." : "Delete Workspace"}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
