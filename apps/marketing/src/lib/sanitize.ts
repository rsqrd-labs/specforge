// Build-time URL sanitization for CMS-authored content (F5 — issue #42).
//
// The marketing site renders first-party Sanity content to HTML at build time
// via two paths: Portable Text (`@portabletext/to-html`) and Markdown (`marked`,
// with raw HTML already dropped). Both emit a controlled set of tags, so the one
// attacker-influenceable value that still reaches the browser is a link/image
// URL. A `javascript:` or `data:text/html` href would be stored XSS if a Sanity
// editor account were ever compromised. This module neutralizes exactly that at
// the render boundary — defense-in-depth on top of the first-party content gate.

const SAFE_PROTOCOLS = new Set(["http:", "https:", "mailto:", "tel:"])

/**
 * Return `url` when it is safe to place in an `href`/`src`, else `"#"`.
 *
 * Allowed: absolute http(s)/mailto/tel URLs, and relative/anchor/root-relative
 * references (no scheme). Rejected: `javascript:`, `data:`, `vbscript:`, and any
 * other scheme. Protocol-relative `//host` is treated as https.
 */
export function safeUrl(url: string | undefined | null): string {
  if (!url) return "#"
  const trimmed = url.trim()
  if (!trimmed) return "#"

  // Relative, root-relative, or anchor links carry no scheme and are safe.
  if (
    trimmed.startsWith("/") ||
    trimmed.startsWith("#") ||
    trimmed.startsWith("?") ||
    trimmed.startsWith("./") ||
    trimmed.startsWith("../")
  ) {
    return trimmed
  }
  // Protocol-relative URL — resolve against https for the scheme check.
  const candidate = trimmed.startsWith("//") ? `https:${trimmed}` : trimmed

  try {
    const parsed = new URL(candidate)
    return SAFE_PROTOCOLS.has(parsed.protocol.toLowerCase()) ? trimmed : "#"
  } catch {
    // Not a parseable absolute URL and not a recognized relative form. Some
    // schemeless values (e.g. "example.com/path") land here; treat as relative.
    return /^[a-z][a-z0-9+.-]*:/i.test(trimmed) ? "#" : trimmed
  }
}

/** Escape a string for safe interpolation into a double-quoted HTML attribute. */
export function escapeAttr(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
}
