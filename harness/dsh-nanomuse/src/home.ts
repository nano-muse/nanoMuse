/**
 * The agent's home on this computer: `~/nanoMuse`, a folder of its own and a dsh workspace.
 * Every chat the plugin opens — for the person, for the rooms' batches, for another device's
 * task — starts there, never in the bare home folder: a workspace that is the whole profile
 * folder cannot run a `workspace-write` command on Windows at all, since the sandbox's temp root
 * (`%LOCALAPPDATA%\Temp`, inside the profile) must lie outside the workspace (#705).
 */
import { mkdir } from 'node:fs/promises'
import { join } from 'node:path'
import type { SessionCreateRequest } from '@deepseek-ai/dsh-api-session-controller/types'

/** The person's home folder, as the shell sees it. */
export function homeDir(): string {
  return process.env.HOME ?? process.env.USERPROFILE ?? process.cwd()
}

/** `~/nanoMuse`, created when missing. */
export async function homeFolder(): Promise<string> {
  const folder = join(homeDir(), 'nanoMuse')
  await mkdir(folder, { recursive: true }).catch(() => undefined)
  return folder
}

interface RegistryLike {
  /** The workspace owning `path`, created when there is none yet (idempotent by canonical path). */
  create(path: string, title?: string): Promise<{ id: string }>
}

/**
 * What to create a chat with so it lives in `~/nanoMuse`: the registered workspace when the
 * registry is up (a session the browser cannot place in a workspace shows a disabled composer
 * and no transcript), else the folder as the cwd.
 */
export async function homeWorkspace(ctx: { get(name: string): unknown }, warn?: (error: unknown) => void): Promise<SessionCreateRequest> {
  const folder = await homeFolder()
  try {
    const id = (await (ctx.get('workspaceRegistry') as RegistryLike | undefined)?.create(folder, 'nanoMuse'))?.id
    if (id) return { agentPreset: 'nanomuse', workspaceId: id as NonNullable<SessionCreateRequest['workspaceId']> }
  } catch (error) {
    warn?.(error)
  }
  return { agentPreset: 'nanomuse', cwd: folder }
}
