import { Building2 } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import CreateWorkspaceModal from "./CreateWorkspaceModal"

export function NoWorkspace() {
  const [open, setOpen] = useState(false)

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="flex flex-col items-center gap-6 text-center max-w-sm px-4">
        <div className="flex size-16 items-center justify-center rounded-full bg-muted">
          <Building2 className="size-8 text-muted-foreground" />
        </div>
        <div>
          <h1 className="text-xl font-semibold">Create your first workspace</h1>
          <p className="text-muted-foreground text-sm mt-2">
            A workspace groups your social media integrations and lets you view
            analytics across all your accounts in one place.
          </p>
        </div>
        <Button onClick={() => setOpen(true)}>Create workspace</Button>
      </div>
      <CreateWorkspaceModal isOpen={open} onClose={() => setOpen(false)} />
    </div>
  )
}
