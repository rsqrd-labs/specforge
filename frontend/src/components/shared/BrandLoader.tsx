import { useEffect, useId, useState } from "react"

import { BrandLogo, type BrandLogoSize } from "./BrandLogo"

export type BrandLoaderVariant = "inline" | "block" | "overlay"
export type BrandLoaderSize = "sm" | "md" | "lg"

interface BrandLoaderProps {
  /**
   * - `inline`  — sits in flow next to text (buttons, async rows). Owns its own
   *   live region.
   * - `block`   — centered loader for a route/section (lazy chunks, panels).
   *   Owns its own live region.
   * - `overlay` — the mark for a full-generation surface. Rendered **decoratively**
   *   (no inner `role="status"`/`aria-live`): the hosting overlay already owns a
   *   live region, and nesting them makes screen readers double-announce or drop
   *   the message. Host it inside a container that announces.
   */
  variant?: BrandLoaderVariant
  size?: BrandLoaderSize
  /**
   * Visible caption and screen-reader announcement. MUST be static, app-authored
   * copy — it is echoed verbatim into an `aria-live` region, so never pass
   * untrusted or model-generated content here.
   */
  label?: string
  className?: string
}

const SIZE_TO_LOGO: Record<BrandLoaderSize, BrandLogoSize> = {
  sm: "compact",
  md: "small",
  lg: "default",
}

function classNames(...values: Array<string | false | undefined>): string {
  return values.filter(Boolean).join(" ")
}

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)"

/**
 * Tracks `prefers-reduced-motion`. When true the caller renders the static brand
 * mark instead of mounting the animated one — the accessible equivalent of "do
 * not start the player". Fails safe to `false` where `matchMedia` is absent
 * (SSR, older jsdom) so the animation is opt-out, never accidentally suppressed.
 */
function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return false
    }
    return window.matchMedia(REDUCED_MOTION_QUERY).matches
  })

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return undefined
    }
    const mql = window.matchMedia(REDUCED_MOTION_QUERY)
    const onChange = (event: MediaQueryListEvent) => setReduced(event.matches)
    // `addEventListener` is the standard API; fall back to the deprecated
    // `addListener` for the small set of engines that predate it.
    if (typeof mql.addEventListener === "function") {
      mql.addEventListener("change", onChange)
      return () => mql.removeEventListener("change", onChange)
    }
    mql.addListener(onChange)
    return () => mql.removeListener(onChange)
  }, [])

  return reduced
}

/**
 * Tracks `document.hidden` via the Page Visibility API so the animation can be
 * paused while the tab is backgrounded — no wasted compositor frames when no one
 * is looking.
 */
function useDocumentHidden(): boolean {
  const [hidden, setHidden] = useState(() =>
    typeof document === "undefined" ? false : document.hidden,
  )

  useEffect(() => {
    if (typeof document === "undefined") {
      return undefined
    }
    const onChange = () => setHidden(document.hidden)
    document.addEventListener("visibilitychange", onChange)
    return () => document.removeEventListener("visibilitychange", onChange)
  }, [])

  return hidden
}

/**
 * The animated brand mark. A self-hosted, CSS-only placeholder today: the
 * animation runs entirely on the compositor (transform/opacity only) and ships
 * no extra runtime dependency.
 *
 * This is a deliberate swap seam — the designer-authored Lottie squirrel drops
 * in here later (lazy-loaded player, falling back to {@link BrandLogo} on
 * load/asset failure) without changing {@link BrandLoader}'s public API.
 */
function BrandLoaderMark({ paused }: { paused: boolean }) {
  // `useId` keeps the gradient id unique per instance so multiple loaders on one
  // page never collide on the same DOM id (which would make every arc resolve
  // `url(#…)` to the first match). Colons from `useId` are stripped because
  // `url(#:r0:)` is an unreliable reference target across browsers.
  const gradientId = `brand-loader-arc-${useId().replace(/:/g, "")}`
  return (
    <span
      className={classNames("brand-loader-mark", paused && "is-paused")}
      aria-hidden="true"
    >
      <svg viewBox="0 0 48 48" focusable="false" role="presentation">
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#ff9933" />
            <stop offset="100%" stopColor="#fd80a9" />
          </linearGradient>
        </defs>
        <circle className="brand-loader-track" cx="24" cy="24" r="18" />
        <path
          className="brand-loader-arc"
          d="M24 6 a18 18 0 0 1 18 18"
          stroke={`url(#${gradientId})`}
        />
        <circle className="brand-loader-core" cx="24" cy="24" r="6" />
      </svg>
    </span>
  )
}

/**
 * The single branded loading primitive (issue #21, Phase 1). Every loader in the
 * app refactors to this — no bespoke spinners.
 */
export function BrandLoader({
  variant = "block",
  size = "md",
  label,
  className,
}: BrandLoaderProps) {
  const prefersReducedMotion = usePrefersReducedMotion()
  const hidden = useDocumentHidden()

  const mark = prefersReducedMotion ? (
    <BrandLogo size={SIZE_TO_LOGO[size]} decorative />
  ) : (
    <BrandLoaderMark paused={hidden} />
  )

  const rootClassName = classNames(
    "brand-loader",
    `brand-loader--${variant}`,
    `brand-loader--${size}`,
    className,
  )

  // The overlay variant is decorative: its host already owns a live region, so
  // re-announcing here would nest `aria-live` regions. The mark is hidden and
  // the caption (if any) is shown silently.
  if (variant === "overlay") {
    return (
      <span className={rootClassName} aria-hidden="true">
        {mark}
        {label ? <span className="brand-loader-label">{label}</span> : null}
      </span>
    )
  }

  // inline / block own their accessibility: a polite status region announces the
  // (visible or screen-reader-only) label without depending on motion.
  return (
    <span className={rootClassName} role="status" aria-live="polite" aria-busy="true">
      {mark}
      {label ? (
        <span className="brand-loader-label">{label}</span>
      ) : (
        <span className="brand-loader-sr">Loading</span>
      )}
    </span>
  )
}
