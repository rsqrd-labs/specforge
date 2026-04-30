import { useEffect, useState } from "react"
import { CreditBanner } from "../components/dashboard/CreditBanner"
import { CreateWorkspaceModal } from "../components/dashboard/CreateWorkspaceModal"
import { WorkspaceCard } from "../components/dashboard/WorkspaceCard"
import { getCredits } from "../services/api"
import { useWorkspaceStore } from "../store/workspaceStore"

export default function Dashboard() {
  const { workspaces, isLoading, fetchWorkspaces } = useWorkspaceStore()
  const [balance, setBalance] = useState<number | null>(null)
  const [showCreate, setShowCreate] = useState(false)

  useEffect(() => {
    void fetchWorkspaces()
    getCredits()
      .then((data) => setBalance(data.balance))
      .catch(() => setBalance(null))
  }, [fetchWorkspaces])

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-5xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-on-background">
            Your Workspaces
          </h1>
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 text-sm font-medium bg-primary text-on-primary rounded-lg hover:opacity-90"
          >
            + Create Workspace
          </button>
        </div>

        {balance !== null && (
          <div className="mb-6">
            <CreditBanner balance={balance} />
          </div>
        )}

        {isLoading ? (
          <div className="flex justify-center py-16">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
          </div>
        ) : workspaces.length === 0 ? (
          <div className="flex flex-col items-center py-16 text-center">
            <p className="text-on-surface-variant mb-4">
              No workspaces yet. Create one to get started.
            </p>
            <button
              onClick={() => setShowCreate(true)}
              className="px-4 py-2 text-sm font-medium bg-primary text-on-primary rounded-lg hover:opacity-90"
            >
              Create your first workspace
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {workspaces.map((ws) => (
              <WorkspaceCard key={ws.id} workspace={ws} />
            ))}
          </div>
        )}
      </div>

      {showCreate && (
        <CreateWorkspaceModal onClose={() => setShowCreate(false)} />
      )}
    </div>
  )
}
