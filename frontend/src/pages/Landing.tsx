import { useState } from "react"

import { api } from "../services/api"

interface LandingProps {
  assignLocation?: (url: string) => void
}

export default function Landing({
  assignLocation = (url) => window.location.assign(url),
}: LandingProps) {
  const [authError, setAuthError] = useState<string | null>(null)
  const [isSigningIn, setIsSigningIn] = useState(false)

  function handleGoogleSignIn() {
    setAuthError(null)
    setIsSigningIn(true)
    api
      .post<{ redirect_url: string }>("/auth/google")
      .then((res) => {
        assignLocation(res.data.redirect_url)
      })
      .catch(() => {
        setIsSigningIn(false)
        setAuthError("Google sign-in could not be started. Check the OAuth setup.")
      })
  }

  return (
    <main className="relative min-h-screen overflow-hidden bg-background text-on-background">
      <div className="absolute inset-0 -z-10">
        <div className="absolute left-[-10rem] top-[-8rem] h-[32rem] w-[32rem] rounded-full bg-primary-container/30 blur-3xl" />
        <div className="absolute bottom-[-12rem] right-[-8rem] h-[34rem] w-[34rem] rounded-full bg-secondary-container/25 blur-3xl" />
      </div>

      <section className="mx-auto grid min-h-screen w-full max-w-[1280px] grid-cols-1 items-center gap-12 px-6 py-10 lg:grid-cols-[minmax(0,1fr)_480px] lg:px-10">
        <div className="max-w-3xl">
          <div className="mb-8 inline-flex items-center gap-3 rounded-full border border-outline-variant bg-surface-container-lowest/80 px-4 py-2 text-sm font-semibold uppercase tracking-[0.18em] text-on-surface-variant shadow-sm backdrop-blur">
            <span className="h-2.5 w-2.5 rounded-full bg-primary" />
            SpecForge
          </div>

          <h1 className="max-w-3xl text-5xl font-extrabold leading-[1.05] text-on-background sm:text-6xl lg:text-7xl">
            Turn rough product ideas into build-ready specs.
          </h1>

          <p className="mt-6 max-w-2xl text-lg leading-8 text-on-surface-variant">
            Shape a problem statement into a reviewed spec, plan, harness, and
            implementation task list with a focused AI workflow built for teams
            that care about precision.
          </p>

          <div className="mt-10 grid max-w-2xl grid-cols-1 gap-3 sm:grid-cols-3">
            {["SPEC", "PLAN", "HARNESS"].map((label, index) => (
              <div
                key={label}
                className="rounded-lg border border-outline-variant bg-surface-container-lowest/75 px-4 py-3 shadow-sm backdrop-blur"
              >
                <div className="text-xs font-bold uppercase tracking-[0.18em] text-primary">
                  0{index + 1}
                </div>
                <div className="mt-1 text-sm font-semibold text-on-surface">
                  {label}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-2xl border border-outline-variant bg-surface-container-lowest/80 p-6 shadow-[0_24px_80px_rgba(47,49,49,0.14)] backdrop-blur-xl">
          <div className="mb-6">
            <h2 className="text-2xl font-bold text-on-surface">Welcome back</h2>
            <p className="mt-2 text-sm leading-6 text-on-surface-variant">
              Sign in to continue to your workspaces.
            </p>
          </div>

          <button
            type="button"
            onClick={handleGoogleSignIn}
            disabled={isSigningIn}
            className="flex h-12 w-full items-center justify-center gap-3 rounded-lg border border-outline-variant bg-surface px-4 text-sm font-semibold text-on-surface shadow-sm transition hover:border-outline hover:bg-surface-container-low disabled:opacity-60"
          >
            <GoogleIcon />
            {isSigningIn ? "Opening Google..." : "Sign in with Google"}
          </button>

          {authError && (
            <p className="mt-4 rounded-lg border border-error-container bg-error-container px-3 py-2 text-sm text-on-error-container">
              {authError}
            </p>
          )}

          <div className="mt-6 rounded-lg bg-primary-container/20 p-4">
            <p className="text-sm font-semibold text-on-surface">
              Spec - Plan - Harness - Tasks
            </p>
            <p className="mt-1 text-sm leading-6 text-on-surface-variant">
              A calm, structured workspace for moving from intent to execution.
            </p>
          </div>
        </div>
      </section>
    </main>
  )
}

function GoogleIcon() {
  return (
    <svg aria-hidden="true" className="h-5 w-5" viewBox="0 0 24 24">
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
        d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
      />
      <path
        fill="#EA4335"
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
      />
    </svg>
  )
}
