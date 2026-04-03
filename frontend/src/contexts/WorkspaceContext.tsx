import { useQuery } from "@tanstack/react-query"
import { createContext, useContext, useEffect, useState } from "react"
import type { ReactNode } from "react"

import { WorkspacesService } from "@/client"
import type { WorkspacePublic } from "@/client"

interface WorkspaceContextValue {
  workspaces: WorkspacePublic[]
  currentWorkspace: WorkspacePublic | null
  setCurrentWorkspace: (ws: WorkspacePublic) => void
  isLoading: boolean
}

const WorkspaceContext = createContext<WorkspaceContextValue>({
  workspaces: [],
  currentWorkspace: null,
  setCurrentWorkspace: () => {},
  isLoading: false,
})

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [currentWorkspace, setCurrentWorkspaceState] =
    useState<WorkspacePublic | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ["workspaces"],
    queryFn: () => WorkspacesService.listWorkspaces({}),
  })

  const workspaces = data?.data ?? []

  // Auto-select first workspace when list loads
  useEffect(() => {
    if (workspaces.length > 0 && !currentWorkspace) {
      setCurrentWorkspaceState(workspaces[0])
    }
  }, [workspaces, currentWorkspace])

  const setCurrentWorkspace = (ws: WorkspacePublic) => {
    setCurrentWorkspaceState(ws)
  }

  return (
    <WorkspaceContext.Provider
      value={{ workspaces, currentWorkspace, setCurrentWorkspace, isLoading }}
    >
      {children}
    </WorkspaceContext.Provider>
  )
}

export function useWorkspace() {
  return useContext(WorkspaceContext)
}
