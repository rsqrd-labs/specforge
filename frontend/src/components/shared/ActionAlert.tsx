import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react"
import { useFocusTrap } from "../../hooks/useFocusTrap"

export type ActionAlertSeverity = "error" | "warning" | "info" | "success"

export interface ActionAlertAction {
  label: string
  onSelect?: () => void | Promise<void>
  href?: string
  variant?: "primary" | "secondary" | "danger"
  autoDismiss?: boolean
}

export interface ActionAlertContent {
  severity: ActionAlertSeverity
  title: string
  message: string
  recovery?: string
  source?: string
  primaryAction?: ActionAlertAction
  secondaryAction?: ActionAlertAction
  dismissLabel?: string
  dismissible?: boolean
}

interface ActionAlertContextValue {
  showAlert: (alert: ActionAlertContent) => void
  dismissAlert: () => void
}

const ActionAlertContext = createContext<ActionAlertContextValue | null>(null)

export function ActionAlertProvider({ children }: { children: ReactNode }) {
  const [alert, setAlert] = useState<ActionAlertContent | null>(null)

  const showAlert = useCallback((next: ActionAlertContent) => {
    setAlert(next)
  }, [])

  const dismissAlert = useCallback(() => {
    setAlert(null)
  }, [])

  const value = useMemo(
    () => ({ showAlert, dismissAlert }),
    [showAlert, dismissAlert],
  )

  return (
    <ActionAlertContext.Provider value={value}>
      {children}
      <ActionAlertDialog alert={alert} onDismiss={dismissAlert} />
    </ActionAlertContext.Provider>
  )
}

export function useActionAlert(): ActionAlertContextValue {
  const value = useContext(ActionAlertContext)
  if (!value) {
    throw new Error("useActionAlert must be used inside ActionAlertProvider")
  }
  return value
}

function ActionAlertIcon({ severity }: { severity: ActionAlertSeverity }) {
  if (severity === "success") {
    return (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <circle cx="10" cy="10" r="8" />
        <polyline points="6.5,10.2 8.8,12.5 13.7,7.4" />
      </svg>
    )
  }

  if (severity === "info") {
    return (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <circle cx="10" cy="10" r="8" />
        <line x1="10" y1="9" x2="10" y2="14" />
        <line x1="10" y1="6" x2="10.01" y2="6" />
      </svg>
    )
  }

  if (severity === "warning") {
    return (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <path d="M10 2.5 18 16.5H2Z" />
        <line x1="10" y1="7" x2="10" y2="11" />
        <line x1="10" y1="14" x2="10.01" y2="14" />
      </svg>
    )
  }

  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <circle cx="10" cy="10" r="8" />
      <line x1="7" y1="7" x2="13" y2="13" />
      <line x1="13" y1="7" x2="7" y2="13" />
    </svg>
  )
}

function ActionButton({
  action,
  fallbackVariant,
  onDismiss,
}: {
  action: ActionAlertAction
  fallbackVariant: "primary" | "secondary"
  onDismiss: () => void
}) {
  const className = `action-alert-btn ${action.variant ?? fallbackVariant}`

  const handleClick = () => {
    const result = action.onSelect?.()
    if (result && typeof result.then === "function") {
      void result.finally(() => {
        if (action.autoDismiss !== false) onDismiss()
      })
      return
    }
    if (action.autoDismiss !== false) onDismiss()
  }

  if (action.href) {
    return (
      <a className={className} href={action.href} onClick={handleClick}>
        {action.label}
      </a>
    )
  }

  return (
    <button type="button" className={className} onClick={handleClick}>
      {action.label}
    </button>
  )
}

export function ActionAlertDialog({
  alert,
  onDismiss,
}: {
  alert: ActionAlertContent | null
  onDismiss: () => void
}) {
  if (!alert) return null

  return <ActionAlertDialogContent alert={alert} onDismiss={onDismiss} />
}

function ActionAlertDialogContent({
  alert,
  onDismiss,
}: {
  alert: ActionAlertContent
  onDismiss: () => void
}) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const initialFocusRef = useRef<HTMLButtonElement>(null)
  const dismissible = alert?.dismissible !== false
  useFocusTrap(dialogRef, dismissible ? onDismiss : () => {}, initialFocusRef)

  return (
    <div
      className="action-alert-backdrop"
      onClick={(event) => {
        if (dismissible && event.target === event.currentTarget) onDismiss()
      }}
    >
      <div
        ref={dialogRef}
        className={`action-alert-dialog ${alert.severity}`}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="action-alert-title"
        aria-describedby="action-alert-message"
      >
        <div className="action-alert-top">
          <span className="action-alert-icon">
            <ActionAlertIcon severity={alert.severity} />
          </span>
          {alert.source ? (
            <span className="action-alert-source">{alert.source}</span>
          ) : null}
          {dismissible ? (
            <button
              ref={initialFocusRef}
              type="button"
              className="action-alert-close"
              onClick={onDismiss}
              aria-label="Dismiss alert"
            >
              X
            </button>
          ) : null}
        </div>

        <div className="action-alert-copy">
          <h2 id="action-alert-title">{alert.title}</h2>
          <p id="action-alert-message">{alert.message}</p>
          {alert.recovery ? (
            <p className="action-alert-recovery">{alert.recovery}</p>
          ) : null}
        </div>

        <div className="action-alert-actions">
          {alert.secondaryAction ? (
            <ActionButton
              action={alert.secondaryAction}
              fallbackVariant="secondary"
              onDismiss={onDismiss}
            />
          ) : null}
          {dismissible ? (
            <button type="button" className="action-alert-btn secondary" onClick={onDismiss}>
              {alert.dismissLabel ?? "Dismiss"}
            </button>
          ) : null}
          {alert.primaryAction ? (
            <ActionButton
              action={alert.primaryAction}
              fallbackVariant="primary"
              onDismiss={onDismiss}
            />
          ) : null}
        </div>
      </div>
    </div>
  )
}

export function ActionAlertPanel({
  className = "",
  onDismiss,
  ...alert
}: ActionAlertContent & {
  className?: string
  onDismiss?: () => void
}) {
  const role =
    alert.severity === "error" || alert.severity === "warning" ? "alert" : "status"

  return (
    <div className={`action-alert-panel ${alert.severity} ${className}`} role={role}>
      <span className="action-alert-panel-icon">
        <ActionAlertIcon severity={alert.severity} />
      </span>
      <div className="action-alert-panel-copy">
        {alert.source ? <span>{alert.source}</span> : null}
        <strong>{alert.title}</strong>
        <p>{alert.message}</p>
        {alert.recovery ? <p className="action-alert-recovery">{alert.recovery}</p> : null}
        {(alert.primaryAction || alert.secondaryAction || onDismiss) && (
          <div className="action-alert-panel-actions">
            {alert.primaryAction ? (
              <ActionButton
                action={alert.primaryAction}
                fallbackVariant="primary"
                onDismiss={onDismiss ?? (() => {})}
              />
            ) : null}
            {alert.secondaryAction ? (
              <ActionButton
                action={alert.secondaryAction}
                fallbackVariant="secondary"
                onDismiss={onDismiss ?? (() => {})}
              />
            ) : null}
            {onDismiss ? (
              <button
                type="button"
                className="action-alert-btn secondary"
                onClick={onDismiss}
              >
                {alert.dismissLabel ?? "Dismiss"}
              </button>
            ) : null}
          </div>
        )}
      </div>
    </div>
  )
}
