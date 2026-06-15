import { useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"

import { ActionAlertPanel } from "../components/shared/ActionAlert"
import { BrandLoader } from "../components/shared/BrandLoader"
import { BrandLockup } from "../components/shared/BrandLogo"
import { featureFlags } from "../config/featureFlags"
import { completeGoogleCallback, setAccessToken } from "../services/api"
import { useUserStore } from "../store/userStore"
import { authCallbackAlert } from "../utils/errorPresentation"

type AuthErrorReason = "cancelled" | "missing-code" | "exchange-failed"

export default function AuthCallback() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const fetchMe = useUserStore((state) => state.fetchMe)
  const [message, setMessage] = useState("Completing Google sign-in...")
  const [status, setStatus] = useState<"loading" | "error">("loading")
  const [errorReason, setErrorReason] = useState<AuthErrorReason | null>(null)
  const didRun = useRef(false)

  useEffect(() => {
    if (didRun.current) return
    didRun.current = true

    const error = searchParams.get("error")
    const code = searchParams.get("code")
    const state = searchParams.get("state")

    if (error) {
      const alert = authCallbackAlert("cancelled")
      setStatus("error")
      setErrorReason("cancelled")
      setMessage(alert.message)
      return
    }

    if (!code || !state) {
      const alert = authCallbackAlert("missing-code")
      setStatus("error")
      setErrorReason("missing-code")
      setMessage(alert.message)
      return
    }

    completeGoogleCallback(code, state)
      .then(async ({ access_token }) => {
        setAccessToken(access_token)
        await fetchMe()
        navigate("/dashboard", { replace: true })
      })
      .catch(() => {
        const alert = authCallbackAlert("exchange-failed")
        setStatus("error")
        setErrorReason("exchange-failed")
        setMessage(alert.message)
      })
  }, [fetchMe, navigate, searchParams])

  return (
    <main className="auth-callback-shell">
      <div className="ambient-field" aria-hidden="true">
        <span className="ambient-band band-saffron" />
        <span className="ambient-band band-lotus" />
        <span className="ambient-band band-slate" />
        <span className="ambient-grid" />
      </div>

      <section className="auth-callback-panel" aria-live="polite">
        <div className="auth-callback-brand">
          <BrandLockup />
        </div>

        {featureFlags.brandedLoaders && status === "loading" ? (
          // The panel <section> already owns the aria-live region, so the
          // branded mark is rendered with the decorative `overlay` variant to
          // avoid nesting live regions.
          <div className="auth-callback-orbit">
            <BrandLoader variant="overlay" size="lg" />
          </div>
        ) : (
          <div className="auth-callback-orbit" aria-hidden="true">
            <span className="auth-orbit-ring" />
            <span className="auth-orbit-ring auth-orbit-ring-secondary" />
            <div className={status === "error" ? "auth-google-mark error" : "auth-google-mark"}>
              <GoogleIcon />
            </div>
          </div>
        )}

        <div className="auth-callback-copy">
          <span className={status === "error" ? "auth-callback-kicker error" : "auth-callback-kicker"}>
            {status === "error" ? "Sign-in needs attention" : "Securing session"}
          </span>
          <h1>
            {status === "error" ? "Could not finish sign-in" : "Taking you to your workspace"}
          </h1>
          <p>{message}</p>
        </div>

        <div className={status === "error" ? "auth-progress error" : "auth-progress"}>
          <span />
          <span />
          <span />
        </div>

        {status === "error" && errorReason && (
          <ActionAlertPanel
            {...authCallbackAlert(errorReason)}
            className="auth-callback-alert"
          />
        )}

        {status === "error" && (
          <div className="auth-callback-actions">
            <button
              type="button"
              className="auth-callback-primary"
              onClick={() => window.location.assign(`${import.meta.env.VITE_API_URL}/auth/google`)}
            >
              Try again
            </button>
            <button
              type="button"
              className="auth-callback-secondary"
              onClick={() => navigate("/", { replace: true })}
            >
              Back to home
            </button>
          </div>
        )}
      </section>
    </main>
  )
}

function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path
        fill="#4285F4"
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
      />
      <path
        fill="#34A853"
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
      />
      <path
        fill="#FBBC05"
        d="M5.84 14.1c-.22-.66-.35-1.36-.35-2.1s.13-1.44.35-2.1V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l3.66-2.84z"
      />
      <path
        fill="#EA4335"
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06L5.84 9.9C6.71 7.3 9.14 5.38 12 5.38z"
      />
    </svg>
  )
}
