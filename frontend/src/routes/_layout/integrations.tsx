import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { formatDistanceToNow } from "date-fns"
import { Link2, Loader2, Plus, RefreshCw, Trash2 } from "lucide-react"

import { IntegrationsService } from "@/client"
import type { IntegrationPublic, Platform } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useWorkspace } from "@/contexts/WorkspaceContext"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/integrations")({
  component: IntegrationsPage,
  head: () => ({
    meta: [{ title: "Integrations - Prism" }],
  }),
})

// ---- helpers ----------------------------------------------------------------

const PLATFORM_LABELS: Record<Platform, string> = {
  facebook: "Facebook",
  instagram: "Instagram",
  twitter: "Twitter / X",
  linkedin: "LinkedIn",
  tiktok: "TikTok",
  google_analytics: "Google Analytics",
}

const PLATFORMS: Platform[] = [
  "facebook",
  "instagram",
  "twitter",
  "linkedin",
  "tiktok",
  "google_analytics",
]

function statusVariant(
  status: string,
): "default" | "secondary" | "destructive" | "outline" {
  if (status === "active") return "default"
  if (status === "error") return "destructive"
  return "secondary"
}

function fmtSynced(ts: string | null | undefined): string {
  if (!ts) return "Never"
  return formatDistanceToNow(new Date(ts), { addSuffix: true })
}

// ---- Row actions ------------------------------------------------------------

function IntegrationRow({ integration }: { integration: IntegrationPublic }) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const syncMut = useMutation({
    mutationFn: () =>
      IntegrationsService.triggerSync({ integrationId: integration.id }),
    onSuccess: () => showSuccessToast("Sync enqueued"),
    onError: handleError.bind(showErrorToast),
  })

  const deleteMut = useMutation({
    mutationFn: () =>
      IntegrationsService.deleteIntegration({ integrationId: integration.id }),
    onSuccess: () => {
      showSuccessToast("Integration removed")
      queryClient.invalidateQueries({ queryKey: ["integrations"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  return (
    <TableRow>
      <TableCell>
        <div className="font-medium capitalize">
          {PLATFORM_LABELS[integration.platform] ?? integration.platform}
        </div>
      </TableCell>
      <TableCell className="text-muted-foreground text-sm">
        {integration.external_account_name}
      </TableCell>
      <TableCell>
        <Badge variant={statusVariant(integration.status)} className="capitalize">
          {integration.status}
        </Badge>
      </TableCell>
      <TableCell className="text-sm text-muted-foreground">
        {fmtSynced(integration.last_synced_at)}
      </TableCell>
      <TableCell>
        {integration.sync_error && (
          <span className="text-xs text-destructive line-clamp-1 max-w-xs">
            {integration.sync_error}
          </span>
        )}
      </TableCell>
      <TableCell className="text-right">
        <div className="flex items-center justify-end gap-2">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => syncMut.mutate()}
            disabled={syncMut.isPending}
            title="Sync now"
          >
            {syncMut.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <RefreshCw className="size-4" />
            )}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => deleteMut.mutate()}
            disabled={deleteMut.isPending}
            title="Disconnect"
            className="text-destructive hover:text-destructive"
          >
            {deleteMut.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Trash2 className="size-4" />
            )}
          </Button>
        </div>
      </TableCell>
    </TableRow>
  )
}

// ---- Main page --------------------------------------------------------------

function IntegrationsPage() {
  const { currentWorkspace } = useWorkspace()

  const integrationsQ = useQuery({
    queryKey: ["integrations", currentWorkspace?.id],
    queryFn: () =>
      IntegrationsService.listIntegrations({
        workspaceId: currentWorkspace!.id,
      }),
    enabled: !!currentWorkspace,
  })

  function connectPlatform(platform: Platform) {
    if (!currentWorkspace) return
    const base = import.meta.env.VITE_API_URL ?? "http://localhost:8000"
    const url = `${base}/api/v1/oauth/connect/${platform}?workspace_id=${currentWorkspace.id}`
    window.location.href = url
  }

  if (!currentWorkspace) {
    return (
      <div className="flex flex-col items-center justify-center py-24 gap-3 text-muted-foreground">
        <Link2 className="size-10" />
        <p>Select a workspace to manage integrations.</p>
      </div>
    )
  }

  const integrations = integrationsQ.data?.data ?? []
  const connectedPlatforms = new Set(integrations.map((i) => i.platform))

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Integrations</h1>
          <p className="text-muted-foreground text-sm mt-1">
            {currentWorkspace.name}
          </p>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button>
              <Plus className="mr-2 size-4" />
              Connect platform
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {PLATFORMS.map((p) => (
              <DropdownMenuItem
                key={p}
                onClick={() => connectPlatform(p)}
                disabled={connectedPlatforms.has(p)}
              >
                {PLATFORM_LABELS[p]}
                {connectedPlatforms.has(p) && (
                  <span className="ml-auto text-xs text-muted-foreground">
                    Connected
                  </span>
                )}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Connected accounts</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          {integrationsQ.isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : integrations.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 gap-3 text-muted-foreground">
              <Link2 className="size-8" />
              <p className="text-sm">No integrations yet.</p>
              <p className="text-xs">
                Click "Connect platform" to add your first social media account.
              </p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Platform</TableHead>
                  <TableHead>Account</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Last synced</TableHead>
                  <TableHead>Error</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {integrations.map((integration) => (
                  <IntegrationRow
                    key={integration.id}
                    integration={integration}
                  />
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
