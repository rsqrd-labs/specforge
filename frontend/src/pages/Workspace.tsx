import { useEffect } from "react"
import { useParams } from "react-router-dom"
import { useWorkspaceStore } from "../store/workspaceStore"

export default function Workspace() {
  const { id } = useParams<{ id: string }>()
  const { currentWorkspace, isLoading, fetchWorkspace } = useWorkspaceStore()

  useEffect(() => {
    if (id) {
      fetchWorkspace(id)
    }
  }, [id, fetchWorkspace])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <p className="text-gray-500">Workspace loading...</p>
      </div>
    )
  }

  if (!currentWorkspace) {
    return null
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold text-gray-900">
          {currentWorkspace.name}
        </h1>
      </div>
    </div>
  )
}
