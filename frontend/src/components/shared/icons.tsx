/** Shared SVG icon components used in the workspace header action bar. */

export function DownloadIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      width="14"
      height="14"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <line x1="8" y1="2" x2="8" y2="11" />
      <polyline points="5,8 8,11 11,8" />
      <line x1="3" y1="14" x2="13" y2="14" />
    </svg>
  )
}

export function PDFIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      width="14"
      height="14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M9 2H4a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V6Z" />
      <polyline points="9,2 9,6 13,6" />
    </svg>
  )
}

export function GitHubIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      width="14"
      height="14"
      fill="currentColor"
      aria-hidden="true"
    >
      <path d="M8 0C3.58 0 0 3.58 0 8a8 8 0 0 0 5.47 7.59c.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
    </svg>
  )
}

export function ShareIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      width="14"
      height="14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <circle cx="13" cy="3" r="1.5" />
      <circle cx="13" cy="13" r="1.5" />
      <circle cx="3" cy="8" r="1.5" />
      <line x1="4.5" y1="7.25" x2="11.5" y2="3.75" />
      <line x1="4.5" y1="8.75" x2="11.5" y2="12.25" />
    </svg>
  )
}

/**
 * A task that has shipped — a checkmark inside a soft ring. The single
 * celebratory glyph of the sync panel; tinted lotus when closed via a merged PR
 * (see `.ws-sync-check.via-pr`), saffron otherwise. Drawn to match the existing
 * 16-grid / 1.75 stroke, not borrowed from an icon set.
 */
export function ShippedCheckIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      width="14"
      height="14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="8" cy="8" r="6.25" />
      <polyline points="5,8.2 7.1,10.2 11,6" />
    </svg>
  )
}

/** A git branch glyph — two nodes on a trunk feeding a branch node. */
export function BranchIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      width="14"
      height="14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="4" cy="3.5" r="1.5" />
      <circle cx="4" cy="12.5" r="1.5" />
      <circle cx="12" cy="3.5" r="1.5" />
      <line x1="4" y1="5" x2="4" y2="11" />
      <path d="M12 5v1.5a3 3 0 0 1-3 3H4" />
    </svg>
  )
}

/**
 * Installed — a shield cradling a check. The settled-trust glyph of the
 * Settings App-install panel: "this tool is installed in your house, and it is
 * safe." Lotus-tinted on the installed confirmation. Drawn to the same 16-grid /
 * 1.75 stroke, not borrowed — a shield, not a generic checkmark.
 */
export function InstalledShieldIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      width="14"
      height="14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M8 1.75 13 3.5v4c0 3.2-2.1 5.6-5 6.75-2.9-1.15-5-3.55-5-6.75v-4Z" />
      <polyline points="5.6,7.9 7.4,9.7 10.6,5.9" />
    </svg>
  )
}

/**
 * Drift — two diverging arrows. Reads as "these have moved apart", a calm
 * informational note for the resync banner (slate, never alarm-red).
 */
export function DriftIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      width="14"
      height="14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M2.5 4.5h4l-1.4-1.4M2.5 4.5l1.4 1.4" />
      <path d="M13.5 11.5h-4l1.4-1.4M13.5 11.5l-1.4 1.4" />
      <line x1="3" y1="11.5" x2="13" y2="4.5" opacity="0.5" />
    </svg>
  )
}
