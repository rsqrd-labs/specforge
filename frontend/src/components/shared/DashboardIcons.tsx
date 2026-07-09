/**
 * Small stroke-icon set for the Dashboard's stat tiles and empty state.
 * Matches the existing icon vocabulary (viewBox 20x20, stroked currentColor
 * paths, round caps/joins — see .logout-button-icon svg) instead of emoji,
 * which render inconsistently per OS/browser and (for the green checkmark)
 * were the single most off-palette color on the screen.
 */

type IconProps = {
  className?: string
}

export function FolderIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} focusable="false" aria-hidden="true">
      <path d="M2.5 5.8c0-.9.7-1.6 1.6-1.6h3.4l1.6 1.8h6.9c.9 0 1.5.7 1.5 1.6v6.6c0 .9-.7 1.6-1.6 1.6H4.1c-.9 0-1.6-.7-1.6-1.6V5.8Z" />
    </svg>
  )
}

export function CheckCircleIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} focusable="false" aria-hidden="true">
      <circle cx="10" cy="10" r="7.3" />
      <path d="M6.8 10.2 8.9 12.3 13.3 7.7" />
    </svg>
  )
}

export function BoltIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} focusable="false" aria-hidden="true">
      <path d="M10.9 2.5 4.6 11.3h4.1l-.9 6.2 6.5-9.1h-4.2l.8-5.9Z" />
    </svg>
  )
}
