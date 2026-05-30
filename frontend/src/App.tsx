import { lazy, Suspense } from "react"
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom"
import { ProtectedRoute } from "./components/shared/ProtectedRoute"
import AuthCallback from "./pages/AuthCallback"
import Billing from "./pages/Billing"
import Dashboard from "./pages/Dashboard"
import Landing from "./pages/Landing"
import Settings from "./pages/Settings"
import Workspace from "./pages/Workspace"

// T-USE-10: the public read-only view is registered OUTSIDE the auth guard
// and lazy-loaded so unauthenticated visitors don't pay the full bundle.
const PublicWorkspaceView = lazy(() => import("./pages/PublicWorkspaceView"))

// Phase 20 — T-257. The owner Storyboard page is behind the auth guard; the
// public Storyboard view (/sb/:slug) is registered OUTSIDE the guard and lazy
// loaded, exactly like the public workspace view.
const Storyboard = lazy(() => import("./pages/Storyboard"))
const StoryboardPublic = lazy(() => import("./pages/StoryboardPublic"))

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/auth/callback" element={<AuthCallback />} />
        <Route
          path="/p/:slug"
          element={
            <Suspense fallback={null}>
              <PublicWorkspaceView />
            </Suspense>
          }
        />
        <Route
          path="/sb/:slug"
          element={
            <Suspense fallback={null}>
              <StoryboardPublic />
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
              <Workspace />
            </ProtectedRoute>
          }
        />
        <Route
          path="/storyboards/:id"
          element={
            <ProtectedRoute>
              <Suspense fallback={null}>
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
    </BrowserRouter>
  )
}
