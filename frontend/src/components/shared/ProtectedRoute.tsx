import { useEffect } from "react"
import { Navigate } from "react-router-dom"
import { useUserStore } from "../../store/userStore"

interface ProtectedRouteProps {
  children: React.ReactNode
}

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const { user, isLoading, fetchMe } = useUserStore()

  useEffect(() => {
    if (!user && !isLoading) {
      fetchMe()
    }
  }, [user, isLoading, fetchMe])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900" />
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/" replace />
  }

  return <>{children}</>
}
