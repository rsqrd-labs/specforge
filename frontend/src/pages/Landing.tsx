import { useEffect } from "react"
import { Link, Navigate } from "react-router-dom"
import { BrandLockup } from "../components/shared/BrandLogo"
import { useUserStore } from "../store/userStore"

interface LandingProps {
  assignLocation?: (url: string) => void
}

export default function Landing({
  assignLocation = (url) => window.location.assign(url),
}: LandingProps) {
  const { user } = useUserStore()

  // Sign-in leaves the SPA via a full-page redirect (window.location.assign
  // below), so returning to "/" via browser Back is a cross-document
  // navigation: either a fresh document (in-memory store starts empty) or a
  // bfcache restore (JS is frozen, this effect won't re-run on its own —
  // pageshow with `persisted` is the signal that fires when it's restored).
  // Both cases need a real session probe, not just the in-memory user check
  // above, to catch an already-authenticated visitor and bounce them off
  // this screen.
  useEffect(() => {
    const { user, isLoading, fetchMe } = useUserStore.getState()
    if (!user && !isLoading) {
      fetchMe()
    }

    function handlePageShow(event: PageTransitionEvent) {
      if (event.persisted) {
        useUserStore.getState().fetchMe()
      }
    }

    window.addEventListener("pageshow", handlePageShow)
    return () => window.removeEventListener("pageshow", handlePageShow)
  }, [])

  if (user) {
    return <Navigate to="/dashboard" replace />
  }

  function handleGoogleSignIn() {
    assignLocation(`${import.meta.env.VITE_API_URL}/auth/google`)
  }

  return (
    <main className="landing-shell">
      <div className="ambient-field" aria-hidden="true">
        <span className="ambient-band band-saffron" />
        <span className="ambient-band band-lotus" />
        <span className="ambient-band band-slate" />
        <span className="ambient-grid" />
      </div>
      <section className="landing-hero" aria-labelledby="landing-title">
        <header className="landing-nav">
          <BrandLockup />
          <span className="landing-status">AI spec-to-build workspace</span>
        </header>

        <div className="hero-grid">
          <div className="hero-copy">
            <h1 id="landing-title">
              Turn rough product ideas into build-ready specs, tests, and tasks.
            </h1>
            <p className="hero-lede">
              SpecForge helps founders, product teams, and engineers turn messy
              intent into a structured build package: requirements, plans,
              validation harnesses, and traceable implementation tasks.
            </p>

            <div className="hero-value-row" aria-label="SpecForge outcomes">
              <span>Less ambiguity</span>
              <span>Earlier validation</span>
              <span>Cleaner AI handoffs</span>
            </div>

            <div className="auth-card">
              <div className="auth-card-glow" aria-hidden="true" />
              <div className="auth-card-header">
                <div>
                  <span className="auth-kicker">Start with one idea</span>
                  <strong>Build your first spec</strong>
                </div>
                <div className="auth-pulse" aria-hidden="true">
                  <span />
                </div>
              </div>

              <button
                type="button"
                onClick={handleGoogleSignIn}
                className="google-button"
                aria-label="Sign in with Google"
              >
                <span className="google-button-icon">
                  <GoogleIcon />
                </span>
                <span>Start your first workspace</span>
                <span className="button-arrow" aria-hidden="true">
                  &rarr;
                </span>
              </button>

              <div className="auth-meta" aria-label="Authentication safeguards">
                <span>OAuth secured</span>
                <span>50 starter credits</span>
                <span>No setup required</span>
              </div>

              <p className="auth-consent">
                By continuing you agree to our{" "}
                <Link to="/legal/terms">Terms of Service</Link> and{" "}
                <Link to="/legal/privacy">Privacy Policy</Link>.
              </p>
            </div>

            <div className="workflow-showcase" aria-label="SpecForge workflow">
              <div className="workflow-heading">
                <span>Delivery pipeline</span>
                <strong>Spec - Plan - Harness - Tasks</strong>
              </div>

              <div className="workflow-board">
                <span className="pipeline-beam" aria-hidden="true" />
                {[
                  ["01", "Spec", "Requirements, users, and acceptance criteria.", "Output: SPEC.md"],
                  ["02", "Plan", "Architecture, risks, and implementation path.", "Output: PLAN.md"],
                  ["03", "Harness", "Validation assets before execution begins.", "Output: tests"],
                  ["04", "Tasks", "Traceable work items ready for delivery.", "Output: tasks.md"],
                ].map(([number, label, description, output]) => (
                  <div className="workflow-card" key={label}>
                    <div className="workflow-card-top">
                      <span className="workflow-number">{number}</span>
                      <strong>{label}</strong>
                    </div>
                    <p>{description}</p>
                    <em>{output}</em>
                  </div>
                ))}
              </div>

              <div className="workflow-outcomes">
                <div>
                  <span>Validated</span>
                  <strong>review gates</strong>
                </div>
                <div>
                  <span>Traceable</span>
                  <strong>task coverage</strong>
                </div>
                <div>
                  <span>Exportable</span>
                  <strong>build package</strong>
                </div>
              </div>
            </div>
          </div>

          <div className="product-panel" aria-label="SpecForge product preview">
            <div className="panel-topbar">
              <span />
              <span />
              <span />
              <strong>Workspace</strong>
            </div>

            <div className="stage-rail">
              {["Spec", "Plan", "Harness", "Tasks"].map((stage, index) => (
                <div className={index === 0 ? "stage-pill active" : "stage-pill"} key={stage}>
                  <span>0{index + 1}</span>
                  {stage}
                </div>
              ))}
            </div>

            <div className="before-after-panel" aria-label="Before and after SpecForge">
              <div>
                <span>Rough input</span>
                <p>“Build an onboarding assistant for new SaaS users.”</p>
              </div>
              <div>
                <span>Build package</span>
                <p>SPEC.md, PLAN.md, validation harness, and implementation tasks.</p>
              </div>
            </div>

            <div className="workspace-status">
              <div>
                <span>Readiness</span>
                <strong>92%</strong>
              </div>
              <div>
                <span>Risks closed</span>
                <strong>14</strong>
              </div>
            </div>

            <div className="document-card">
              <div className="document-header">
                <span>SPEC.md</span>
                <em>Quality 92</em>
              </div>
              <h2>Problem framing, user journeys, and acceptance criteria</h2>
              <div className="doc-line wide" />
              <div className="doc-line" />
              <div className="doc-line short" />
            </div>

            <div className="handoff-card">
              <div>
                <span>Next handoff</span>
                <strong>Harness coverage review</strong>
              </div>
              <em>3 checks waiting</em>
            </div>

            <div className="insight-grid">
              <div>
                <span>Coverage</span>
                <strong>87%</strong>
              </div>
              <div>
                <span>Review gate</span>
                <strong>Ready</strong>
              </div>
              <div>
                <span>Next stage</span>
                <strong>Plan</strong>
              </div>
            </div>

            <div className="activity-feed" aria-label="Workspace activity">
              {[
                ["Spec gate passed", "Acceptance criteria linked"],
                ["Plan draft ready", "Architecture risks mapped"],
                ["Harness queued", "Contract checks prepared"],
              ].map(([title, detail]) => (
                <div className="activity-item" key={title}>
                  <span aria-hidden="true" />
                  <div>
                    <strong>{title}</strong>
                    <p>{detail}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <section className="landing-problem-section" aria-labelledby="problem-title">
          <div className="section-copy">
            <span>Why teams lose momentum</span>
            <h2 id="problem-title">
              Product ideas usually break between “we should build this” and
              “here is exactly how.”
            </h2>
          </div>
          <div className="problem-grid">
            {[
              ["Requirements stay vague", "Everyone agrees on the idea, then discovers different assumptions during implementation."],
              ["Tests arrive too late", "Validation often starts after decisions are already embedded in code."],
              ["AI agents need better context", "Coding agents move faster when the brief, constraints, and acceptance checks are explicit."],
            ].map(([title, copy]) => (
              <div className="problem-card" key={title}>
                <strong>{title}</strong>
                <p>{copy}</p>
              </div>
            ))}
          </div>
        </section>

        <div className="landing-proof-panel" aria-label="SpecForge platform highlights">
          {[
            ["01", "Quality gates", "Every stage includes review checkpoints before the build moves forward."],
            ["02", "Harness-first coverage", "Validation assets are generated alongside the plan, not after delivery."],
            ["03", "Traceable execution", "Tasks stay connected to requirements, risks, and acceptance criteria."],
            ["04", "Clean handoff", "Export a structured package that another engineer or agent can continue from."],
          ].map(([number, title, copy]) => (
            <div className="proof-tile" key={title}>
              <span>{number}</span>
              <strong>{title}</strong>
              <p>{copy}</p>
            </div>
          ))}
        </div>

        <section className="audience-section" aria-labelledby="audience-title">
          <div className="section-copy">
            <span>Built for execution-minded teams</span>
            <h2 id="audience-title">Use it when the next step needs to be clearer than the idea.</h2>
          </div>
          <div className="audience-grid">
            {[
              ["Founders", "Turn a promising product idea into a brief engineers can challenge and build."],
              ["Product teams", "Convert intent, edge cases, and user journeys into requirements and review gates."],
              ["Engineers", "Start with architecture, risks, tests, and traceable tasks instead of a vague ticket."],
              ["AI agent teams", "Give coding agents cleaner instructions, stronger constraints, and validation targets."],
            ].map(([title, copy]) => (
              <div className="audience-card" key={title}>
                <strong>{title}</strong>
                <p>{copy}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="landing-final-cta" aria-labelledby="final-cta-title">
          <div>
            <span>Bring one messy idea</span>
            <h2 id="final-cta-title">Leave with a build plan your team can act on.</h2>
            <p>
              Start with Google, use your starter credits, and turn the first
              product thought into a structured SpecForge workspace.
            </p>
          </div>
          <button
            type="button"
            onClick={handleGoogleSignIn}
            className="final-cta-button"
          >
            Start your first workspace
          </button>
        </section>

        <footer className="landing-footer">
          <Link to="/legal/privacy">Privacy Policy</Link>
          <Link to="/legal/terms">Terms of Service</Link>
          <Link to="/legal/retention">Data Retention Policy</Link>
        </footer>
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
