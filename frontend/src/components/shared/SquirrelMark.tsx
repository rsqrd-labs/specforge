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
          {/* The defining squirrel cue: a big, bushy plume of a tail that sweeps
              up the whole back and curls forward at the top — taller and wider
              than the body itself. This is what separates a squirrel from a cat. */}
          <path
            className="squirrel-tail"
            d="M25 41 C41 44 48 27 41 14 C37.5 6.5 30 4 26 9 C31 11 33 17 31.5 23 C30 29 26 30 25 34 C24 37 23.5 39 25 41 Z"
          />
          {/* Little front foot poking out under the seat. */}
          <ellipse className="squirrel-foot" cx="13.5" cy="43" rx="4.8" ry="2.3" />
          {/* Plump upright sitting torso, belly bulging forward. */}
          <path
            className="squirrel-torso"
            d="M17 20 C24 19 27.5 26 27.5 33 C27.5 40 23.5 43.5 18 43.5 C12.5 43.5 10.5 38 11 32 C11.4 25.5 12.5 21 17 20 Z"
          />
          {/* Small, rounded ears set on top of the head — arched, never the tall
              pointed triangles that read as a cat. Drawn before the head so the
              head overlaps their base cleanly. */}
          <path className="squirrel-ear" d="M10.3 8 C9.6 2.4 16.2 2.4 15.5 8 Z" />
          <path className="squirrel-ear" d="M16.5 8.6 C15.9 3.1 21.8 3.1 21.2 8.6 Z" />
          {/* Big round head — kept generous relative to the body for a cuter,
              chubbier-cheeked look. */}
          <circle className="squirrel-head" cx="15.3" cy="14" r="8.4" />
          {/* Short, blunt cheek/muzzle — a squirrel's stubby snout, kept high and
              tucked in so it never stretches into the long pointed snout of a
              mouse. */}
          <path
            className="squirrel-muzzle"
            d="M13 17.8 C10.4 17.5 8.9 18.8 9.1 20.3 C9.3 21.8 11 22.1 12.7 21.3 C14.2 20.6 14.7 18.6 13 17.8 Z"
          />
        </g>
        {/* Cream chest/belly patch hugging the front of the sitting torso — the
            pale underside squirrels show when they sit up. */}
        <path
          className="squirrel-belly"
          d="M14.2 25 C11.6 27.2 11.6 35 14.2 39.6 C15.5 41.9 18 41.2 18.4 36 C18.8 30.8 17.6 25.8 14.2 25 Z"
        />
        {/* Lighter inner ears nested inside the two outer ears. */}
        <path className="squirrel-inner-ear" d="M11.4 6.9 C11 4.1 14.7 4.1 14.3 6.9 Z" />
        <path className="squirrel-inner-ear" d="M17.5 7.5 C17.1 4.8 20.4 4.8 20 7.5 Z" />
        {/* Soft blushed cheek below the eye — a touch bigger and rosier for cute. */}
        <ellipse className="squirrel-cheek" cx="11.2" cy="16.8" rx="2.2" ry="1.7" />
        {/* Two short, subtle whiskers — kept faint and stubby so the face reads
            squirrel, not the long-whiskered snout of a mouse. */}
        <g className="squirrel-whiskers">
          <path d="M9 19.6 C6.8 19.1 5.6 18.9 4.6 19" />
          <path d="M9 20.8 C6.8 20.9 5.6 21.2 4.7 21.6" />
        </g>
        {/* Small smile tucked just under the nose. */}
        <path className="squirrel-mouth" d="M9.4 21.1 C9.8 22.1 10.9 22.3 11.6 21.6" />
        {/* Eye set high in the upper face, with a warm catch-light so it reads
            as a lively eye instead of a flat staring dot. The nose is a much
            smaller dot on the leading tip of the muzzle, so the two dark marks
            never read as a mismatched pair of eyes. The catch-light lives inside
            `.squirrel-eye` so it blinks and squashes together with the eye. */}
        <g className="squirrel-eye">
          <circle cx="14.5" cy="12" r="2.05" />
          <circle className="squirrel-eye-shine" cx="13.7" cy="11.2" r="0.65" />
        </g>
        <circle className="squirrel-nose" cx="9.2" cy="19.4" r="0.95" />
        {/* The clincher: a little acorn clasped in two prominent front paws at
            the chest. The acorn is the unambiguous squirrel cue, and the two
            arms sweep down from the shoulders so the paws read as real hands
            cupping it (the old single paw-nub was invisible; two floating
            ellipses read as disconnected blobs). Drawn last so the paws sit
            over the acorn's sides like a symmetric grip. */}
        <path
          className="squirrel-acorn-nut"
          d="M12.9 30.6 C12.9 29 17.6 29 17.6 30.6 C17.6 33.6 16.1 35.8 15.25 35.8 C14.4 35.8 12.9 33.6 12.9 30.6 Z"
        />
        <path
          className="squirrel-acorn-cap-brim"
          d="M12.2 30.4 C12.2 32 18.3 32 18.3 30.4 C18.3 28 12.2 28 12.2 30.4 Z"
        />
        <path
          className="squirrel-acorn-cap"
          d="M12.5 29.9 C12.5 27.6 18 27.6 18 29.9 C18 30.9 12.5 30.9 12.5 29.9 Z"
        />
        <path className="squirrel-acorn-stem" d="M15.25 27.7 L15.25 26.4" />
        <path
          className="squirrel-arm"
          fill={`url(#${gradientId})`}
          d="M11 26.4 C8.9 27.6 8.6 30.4 10.2 32 C11.6 33.4 13.7 33 14 31.2 C14.2 29.6 13 26.4 11 26.4 Z"
        />
        <path
          className="squirrel-arm"
          fill={`url(#${gradientId})`}
          d="M19.5 26.4 C21.4 27.6 21.7 30.4 20.1 32 C18.7 33.4 16.6 33 16.3 31.2 C16.1 29.6 17.5 26.4 19.5 26.4 Z"
        />
      </g>
    </svg>
  )
}
