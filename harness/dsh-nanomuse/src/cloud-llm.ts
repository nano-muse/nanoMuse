/** Cloud capacity defaults, below the person's editable Harness model fields. */
import type { RelayModel } from './relay.ts'

interface CapacityRow { id: string; contextWindow?: number; maxTokens?: number }
export type CapacityProviders = Record<string, { readonly models?: readonly CapacityRow[] }>

export function inheritCloudCapacity<T extends CapacityProviders>(
  providers: T, models: readonly RelayModel[],
): T {
  const ours = providers.nanomuse
  if (!ours?.models) return providers
  const defaults = new Map(models.map((model) => [model.id, model]))
  return { ...providers, nanomuse: { ...ours, models: ours.models.map((model) => {
    const server = defaults.get(model.id)
    return { ...model,
      ...(model.contextWindow == null && server?.contextWindow != null ? { contextWindow: server.contextWindow } : {}),
      ...(model.maxTokens == null && server?.maxTokens != null ? { maxTokens: server.maxTokens } : {}),
    }
  }) } }
}
