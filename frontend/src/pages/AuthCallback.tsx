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

    if (error) {
      setMessage("Google sign-in was cancelled or rejected.")
      return
    }

    if (!code) {
      setMessage("Google did not return a sign-in code.")
      return
    }

    completeGoogleCallback(code)
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
    <main className="flex min-h-screen items-center justify-center bg-background px-6 text-on-background">
      <div className="w-full max-w-md rounded-2xl border border-outline-variant bg-surface-container-lowest/85 p-6 text-center shadow-[0_24px_80px_rgba(47,49,49,0.14)] backdrop-blur-xl">
        <div className="mx-auto mb-5 h-10 w-10 animate-spin rounded-full border-2 border-outline-variant border-t-primary" />
        <h1 className="text-xl font-bold text-on-surface">SpecForge</h1>
        <p className="mt-3 text-sm leading-6 text-on-surface-variant">{message}</p>
      </div>
    </main>
  )
}
