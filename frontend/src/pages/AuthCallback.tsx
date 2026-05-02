import { useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"

import { completeGoogleCallback, setAccessToken } from "../services/api"
import { useUserStore } from "../store/userStore"

export default function AuthCallback() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const fetchMe = useUserStore((state) => state.fetchMe)
  const [message, setMessage] = useState("Completing Google sign-in...")
  const didRun = useRef(false)

  useEffect(() => {
    if (didRun.current) return
    didRun.current = true

    const error = searchParams.get("error")
    const code = searchParams.get("code")
    const state = searchParams.get("state")

    if (error) {
      setMessage("Google sign-in was cancelled or rejected.")
      return
    }

    if (!code || !state) {
      setMessage("Google did not return a sign-in code.")
      return
    }

    completeGoogleCallback(code, state)
      .then(async ({ access_token }) => {
        setAccessToken(access_token)
        await fetchMe()
        navigate("/dashboard", { replace: true })
      })
      .catch(() => {
        setMessage("Google sign-in failed. Check the OAuth configuration.")
      })
  }, [fetchMe, navigate, searchParams])

  return (
    <main className="flex min-h-screen items-center justify-center px-6">
      <div className="w-full max-w-sm text-center">
        <div className="mb-8 flex items-center justify-center gap-3">
          <span className="brand-mark brand-mark-sm">
            <span>SF</span>
          </span>
          <span className="brand-wordmark brand-wordmark-sm">SpecForge</span>
        </div>
        <div className="rounded-xl border border-outline-variant bg-surface-container-lowest/85 p-8 shadow-[0_28px_80px_rgba(47,49,49,0.14)] backdrop-blur-xl">
          <div className="mx-auto mb-5 h-10 w-10 animate-spin rounded-full border-2 border-outline-variant border-t-primary" />
          <p className="text-sm leading-6 text-on-surface-variant">{message}</p>
        </div>
      </div>
    </main>
  )
}
