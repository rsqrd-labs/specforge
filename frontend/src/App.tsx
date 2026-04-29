import type { Stage } from "./types/stage"
import type { User } from "./types/user"
import type { Workspace } from "./types/workspace"

export default function App() {
  const _typecheck: {
    user?: User
    workspace?: Workspace
    stage?: Stage
  } = {}
  void _typecheck

  return <div>SpecForge</div>
}
