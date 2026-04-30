import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom"
import { ProtectedRoute } from "./components/shared/ProtectedRoute"
import Dashboard from "./pages/Dashboard"
import Landing from "./pages/Landing"
import Workspace from "./pages/Workspace"

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
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
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
