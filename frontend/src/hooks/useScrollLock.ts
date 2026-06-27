import { useEffect } from "react"

/**
 * Locks scrolling on the underlying page while a modal/overlay is mounted, so a
 * wheel/trackpad gesture only scrolls the overlay itself — never the content
 * behind it — regardless of where the pointer sits. Restores the previous body
 * styles on unmount and compensates for the removed scrollbar so the page
 * doesn't shift sideways when the lock toggles.
 */
export function useScrollLock(active = true) {
  useEffect(() => {
    if (!active) return
    const { body, documentElement } = document
    const scrollbarWidth = window.innerWidth - documentElement.clientWidth
    const prevOverflow = body.style.overflow
    const prevPaddingRight = body.style.paddingRight
    body.style.overflow = "hidden"
    if (scrollbarWidth > 0) {
      body.style.paddingRight = `${scrollbarWidth}px`
    }
    return () => {
      body.style.overflow = prevOverflow
      body.style.paddingRight = prevPaddingRight
    }
  }, [active])
}
