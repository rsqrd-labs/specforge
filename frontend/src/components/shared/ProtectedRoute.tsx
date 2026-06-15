import { useEffect, useState } from "react"
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

  useEffect(() => {
    let cancelled = false

    if (user) {
      setHasCheckedSession(true)
      return
    }

    if (!isLoading) {
      fetchMe().finally(() => {
        if (!cancelled) {
          setHasCheckedSession(true)
        }
      })
    }

    return () => {
      cancelled = true
    }
  }, [user, isLoading, fetchMe])

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
