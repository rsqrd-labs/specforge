import { useEffect, useState } from "react"
import { CreateWorkspaceModal } from "../components/dashboard/CreateWorkspaceModal"
import { WorkspaceCard } from "../components/dashboard/WorkspaceCard"
import { getCredits } from "../services/api"
import { useUserStore } from "../store/userStore"
import { useWorkspaceStore } from "../store/workspaceStore"

export default function Dashboard() {
  const { workspaces, isLoading, fetchWorkspaces } = useWorkspaceStore()
  const user = useUserStore((state) => state.user)
  const [balance, setBalance] = useState<number | null>(null)
  const [showCreate, setShowCreate] = useState(false)

  useEffect(() => {
    void fetchWorkspaces()
    getCredits()
      .then((data) => setBalance(data.balance))
      .catch(() => setBalance(null))
  }, [fetchWorkspaces])

  const initials = user
    ? (user.name ?? user.email).charAt(0).toUpperCase()
    : "?"

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-outline-variant bg-surface-container-lowest/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-3">
          <div className="flex items-center gap-3">
            <span className="brand-mark brand-mark-sm">
              <span>SF</span>
            </span>
            <span className="brand-wordmark brand-wordmark-sm">SpecForge</span>
          </div>

          <div className="flex items-center gap-4">
            {balance !== null && (
              <span className="hidden items-center gap-1.5 rounded-full border border-outline-variant bg-surface-container-low px-3 py-1.5 text-xs font-semibold text-on-surface-variant sm:inline-flex">
                <span className="h-1.5 w-1.5 rounded-full bg-primary" />
                {balance} credits
              </span>
            )}
            {user && (
              <div className="flex items-center gap-2.5">
                {user.avatar_url ? (
                  <img
                    src={user.avatar_url}
                    alt=""
                    className="h-8 w-8 rounded-full ring-2 ring-outline-variant"
                  />
                ) : (
                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-xs font-bold text-on-primary">
                    {initials}
                  </div>
                )}
                <span className="hidden text-sm font-medium text-on-surface sm:block">
                  {user.name ?? user.email}
                </span>
              </div>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-10">
        <div className="mb-8 flex items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-on-surface">
              Workspaces
            </h1>
            <p className="mt-1 text-sm text-on-surface-variant">
              Each workspace runs a full Spec → Plan → Harness → Tasks pipeline.
            </p>
          </div>
          <button
            onClick={() => setShowCreate(true)}
            className="flex shrink-0 items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-on-primary shadow-[0_8px_24px_rgba(143,78,0,0.22)] transition-all hover:-translate-y-0.5 hover:opacity-90"
          >
            <span className="text-base leading-none">+</span>
            New Workspace
          </button>
        </div>

        {balance !== null && balance <= 10 && (
          <div className="mb-6 flex items-center justify-between rounded-lg border border-primary-container/40 bg-primary-container/10 px-4 py-3 text-sm text-on-primary-container">
            <span>
              <span className="font-semibold">{balance}</span> credits remaining
              — running low.
            </span>
          </div>
        )}

        {isLoading ? (
          <div className="flex justify-center py-24">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-outline-variant border-t-primary" />
          </div>
        ) : workspaces.length === 0 ? (
          <div className="flex flex-col items-center rounded-xl border border-dashed border-outline-variant bg-surface-container-lowest/60 py-24 text-center backdrop-blur-sm">
            <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-xl border border-outline-variant bg-surface-container-low">
              <span className="text-2xl">⚡</span>
            </div>
            <p className="mb-1 font-semibold text-on-surface">
              No workspaces yet
            </p>
            <p className="mb-6 text-sm text-on-surface-variant">
              Create one to start building your spec pipeline.
            </p>
            <button
              onClick={() => setShowCreate(true)}
              className="rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-on-primary shadow-[0_8px_24px_rgba(143,78,0,0.22)] hover:opacity-90"
            >
              Create your first workspace
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {workspaces.map((ws) => (
              <WorkspaceCard key={ws.id} workspace={ws} />
            ))}
          </div>
        )}
      </main>

      {showCreate && (
        <CreateWorkspaceModal onClose={() => setShowCreate(false)} />
      )}
    </div>
  )
}
