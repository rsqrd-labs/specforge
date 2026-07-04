import { lazy, Suspense, type ReactNode } from "react"
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom"
import { ActionAlertProvider } from "./components/shared/ActionAlert"
import { BrandLoader } from "./components/shared/BrandLoader"
import { ProtectedRoute } from "./components/shared/ProtectedRoute"
import { featureFlags } from "./config/featureFlags"
import AuthCallback from "./pages/AuthCallback"
import Billing from "./pages/Billing"
import Dashboard from "./pages/Dashboard"
import Landing from "./pages/Landing"
import Settings from "./pages/Settings"

// The Workspace editor pulls in CodeMirror (the single largest dependency).
// Lazy-load it so the landing/dashboard first paint never pays for the editor
// bundle — it loads only when a workspace is opened (LF-1 review remediation).
const Workspace = lazy(() => import("./pages/Workspace"))

// T-USE-10: the public read-only view is registered OUTSIDE the auth guard
// and lazy-loaded so unauthenticated visitors don't pay the full bundle.
const PublicWorkspaceView = lazy(() => import("./pages/PublicWorkspaceView"))

// Phase 20 — T-257. The owner Storyboard page is behind the auth guard; the
// public Storyboard view (/sb/:slug) is registered OUTSIDE the guard and lazy
// loaded, exactly like the public workspace view.
const Storyboard = lazy(() => import("./pages/Storyboard"))
const StoryboardPublic = lazy(() => import("./pages/StoryboardPublic"))

// Issue #43 — the published data-retention policy. Outside the auth guard (the
// policy must be readable without signing in) and lazy-loaded like the other
// public surfaces.
const LegalRetention = lazy(() => import("./pages/LegalRetention"))

// Dark-launched behind `branded_loaders`: until the flag flips, lazy chunks
// keep the prior blank fallback; with it on, every route shows the branded
// loader instead of a flash of nothing.
const routeFallback: ReactNode = featureFlags.brandedLoaders ? (
  <BrandLoader variant="block" label="Loading SpecForge…" />
) : null

export default function App() {
  return (
    <BrowserRouter>
      <ActionAlertProvider>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/auth/callback" element={<AuthCallback />} />
          <Route
            path="/p/:slug"
            element={
              <Suspense fallback={routeFallback}>
                <PublicWorkspaceView />
              </Suspense>
            }
          />
          <Route
            path="/sb/:slug"
            element={
              <Suspense fallback={routeFallback}>
                <StoryboardPublic />
              </Suspense>
            }
          />
          <Route
            path="/legal/retention"
            element={
              <Suspense fallback={routeFallback}>
                <LegalRetention />
              </Suspense>
            }
          />
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <Dashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/workspace/:id"
            element={
              <ProtectedRoute>
                <Suspense fallback={routeFallback}>
                  <Workspace />
                </Suspense>
              </ProtectedRoute>
            }
          />
          <Route
            path="/storyboards/:id"
            element={
              <ProtectedRoute>
                <Suspense fallback={routeFallback}>
                  <Storyboard />
                </Suspense>
              </ProtectedRoute>
            }
          />
          <Route
            path="/settings"
            element={
              <ProtectedRoute>
                <Settings />
              </ProtectedRoute>
            }
          />
          <Route
            path="/billing"
            element={
              <ProtectedRoute>
                <Billing />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </ActionAlertProvider>
    </BrowserRouter>
  )
}
