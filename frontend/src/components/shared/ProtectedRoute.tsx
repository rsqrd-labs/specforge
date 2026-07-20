import { useEffect, useRef, useState } from "react"
import { Navigate } from "react-router-dom"
import { useUserStore } from "../../store/userStore"
import { BrandLoader } from "./BrandLoader"
import { featureFlags } from "../../config/featureFlags"

interface ProtectedRouteProps {
  children: React.ReactNode
}

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const { user, isLoading, fetchMe } = useUserStore()
  const [hasCheckedSession, setHasCheckedSession] = useState(Boolean(user))
  const attemptedRef = useRef(false)

  useEffect(() => {
    if (user) {
      setHasCheckedSession(true)
      // Mark this mount as having checked the session even though it didn't
      // need to call fetchMe(): otherwise, if `user` later flips back to null
      // within the same mount (e.g. a live session dying mid-use — see
      // SessionExpiryWatcher), this effect re-fires, sees an unset ref, and
      // issues a redundant fetchMe()/refresh call moments before the render
      // below redirects away anyway.
      attemptedRef.current = true
      return
    }

    // Only ever probe the session once per mount. `fetchMe` itself toggles
    // `isLoading`, so gating this on `isLoading` (rather than a ref) re-fires
    // the effect every time it settles back to false while `user` is still
    // null — an infinite fetchMe()/refresh loop for any genuinely logged-out
    // visitor who deep-links to a protected route.
    if (attemptedRef.current) {
      return
    }
    attemptedRef.current = true

    void fetchMe().finally(() => {
      setHasCheckedSession(true)
    })
  }, [user, fetchMe])

  if (isLoading || !hasCheckedSession) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        {featureFlags.brandedLoaders ? (
          <BrandLoader variant="block" label="Loading…" />
        ) : (
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900" />
        )}
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/" replace />
  }

  return <>{children}</>
}
