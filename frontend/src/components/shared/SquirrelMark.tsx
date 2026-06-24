import { useId } from "react"

interface SquirrelMarkProps {
  className?: string
}

/**
 * The SpecForge squirrel as a self-hosted, dependency-free SVG. This is the
 * single source of the mark's geometry: the product logo ({@link BrandLogo}) and
 * the loader ({@link BrandLoader}) both render it. The compositor-only animation
 * (tail flick, body bob, blink) lives in CSS on the `.squirrel` classes, so it
 * runs wherever the mark renders — the logo and the loader alike — and is held
 * still only under `prefers-reduced-motion`.
 *
 * `useId` keeps the fur gradient id unique per instance so multiple marks on one
 * page never collide on the same DOM id (which would make every squirrel resolve
 * `url(#…)` to the first match). Colons from `useId` are stripped because
 * `url(#:r0:)` is an unreliable reference target across browsers.
 */
export function SquirrelMark({ className }: SquirrelMarkProps) {
  const gradientId = `squirrel-fur-${useId().replace(/:/g, "")}`
  return (
    <svg className={className} viewBox="0 0 48 48" focusable="false" role="presentation">
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#ff9933" />
          <stop offset="100%" stopColor="#fd80a9" />
        </linearGradient>
      </defs>
      <g className="squirrel">
        <g className="squirrel-fur" fill={`url(#${gradientId})`}>
          {/* Bushy tail, taller than the body — the defining squirrel cue. */}
          <path
            className="squirrel-tail"
            d="M29 41 C42 42 46 28 41 17 C38 10 32 8 30 13 C35 15 37 22 36 28 C35 34 32 38 29 41 Z"
          />
          <ellipse className="squirrel-foot" cx="16" cy="41" rx="4.2" ry="2" />
          {/* Sitting torso. */}
          <path
            className="squirrel-torso"
            d="M22 20 C29 20 31 31 30 37 C29 42 14 42 13 37 C12 31 15 20 22 20 Z"
          />
          <circle className="squirrel-head" cx="17" cy="15" r="8" />
          <path className="squirrel-ear" d="M12 8 C10 3 16 3 16 10 Z" />
          <path className="squirrel-ear" d="M19 9 C20 3 25 4 23 10 Z" />
        </g>
        <circle className="squirrel-eye" cx="13.4" cy="14.4" r="1.7" />
        <circle className="squirrel-nose" cx="9.6" cy="16.8" r="1.3" />
      </g>
    </svg>
  )
}
