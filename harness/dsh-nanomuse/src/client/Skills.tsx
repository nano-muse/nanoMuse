import { createElement as h, useCallback, useEffect, useRef, useState, type ChangeEvent, type ReactNode } from 'react'
import { errorCode, failureText, type Translate } from './api.ts'
import { IconRefresh, IconSearch } from './icons.tsx'
import { useWin } from './win.ts'

export const SKILLS_SECTION = 'nanomuse-skills'
export type SkillScope = 'global' | 'workspace'

export interface SkillEntry {
  name: string
  description: string
  source: string
  provider: string
  path?: string
  globalDisabled: boolean
  workspaceDisabled: boolean
  enabled: boolean
}

export interface SkillCatalog {
  workspace: string | null
  complete: boolean
  policyError?: string
  managed: boolean
  skills: SkillEntry[]
}

async function skillsCall<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/nanomuse/skills/${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'content-type': 'application/json', 'x-nanomuse': '1' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
  const data = await response.json().catch(() => null) as (T & { error?: { code?: string; message?: string } }) | null
  if (!data) throw Object.assign(new Error(''), { code: 'skills_operation_failed' })
  if (!response.ok) throw Object.assign(new Error(data.error?.message ?? String(response.status)), {
    code: data.error?.code ?? String(response.status),
  })
  return data
}

export function skillsFailure(t: Translate, cause: unknown): string {
  switch (errorCode(cause)) {
    case 'skills_policy_unavailable': return t('skPolicyError')
    case 'skills_workspace_unavailable': return t('skWorkspaceUnavailable')
    case 'skills_scope_unavailable': return t('skUnmanaged')
    case 'skills_policy_limit': return t('skPolicyLimit')
    case 'skills_session_unavailable': return t('skSessionUnavailable')
    case 'skills_bad_request':
    case 'skills_operation_failed': return t('skRequestFailed')
    default: return failureText(t, cause)
  }
}

export interface SkillsPanelProps {
  t: Translate
  catalog: SkillCatalog | null
  hasSession: boolean
  scope: SkillScope
  query: string
  loading: boolean
  saving: string | null
  error: string | null
  onScope(scope: SkillScope): void
  onQuery(query: string): void
  onRefresh(): void
  onToggle(skill: SkillEntry, scope: SkillScope): void
}

/** Metadata is plain text. The panel never loads a skill body or follows a provider's file path. */
export function SkillsPanel({ t, catalog, hasSession, scope, query, loading, saving, error, onScope, onQuery, onRefresh, onToggle }: SkillsPanelProps): ReactNode {
  const effectiveScope = hasSession ? scope : 'global'
  const unknown = catalog?.managed === false || Boolean(catalog?.policyError)
  const blocked = loading || saving !== null || error !== null || unknown
  const needle = query.trim().toLocaleLowerCase()
  const rows = catalog?.skills.filter((skill) => `${skill.name}\n${skill.description}`.toLocaleLowerCase().includes(needle)) ?? []

  return h('section', { className: 'nm-skills' },
    h('div', { className: 'nm-skills-head' },
      h('div', null, h('h2', { className: 'nm-page-title' }, t('skTitle')), h('p', { className: 'nm-page-sub' }, t('skAbout'))),
      h('button', { type: 'button', className: 'nm-icon-btn', disabled: loading || saving !== null, title: t('skRefresh'), 'aria-label': t('skRefresh'), onClick: onRefresh }, h(IconRefresh, { size: 18 }))),
    h('div', { className: 'nm-card nm-skills-scope' },
      h('label', { className: 'nm-skills-scope-picker' },
        h('span', null, t('skScope')),
        h('select', { className: 'nm-input nm-select', value: effectiveScope, disabled: loading || saving !== null, onChange: (event: ChangeEvent<HTMLSelectElement>) => onScope(event.currentTarget.value === 'workspace' ? 'workspace' : 'global') },
          h('option', { value: 'global' }, t('skGlobal')),
          h('option', { value: 'workspace', disabled: !hasSession }, t('skWorkspace')))),
      h('p', { className: 'nm-skills-hint' }, effectiveScope === 'global' ? t('skGlobalHint') : t('skWorkspaceHint')),
      h('p', { className: 'nm-skills-context' }, catalog?.workspace
        ? h('span', null, t('skCatalogContext'), ' ', h('code', null, catalog.workspace))
        : !hasSession ? t('skNoWorkspace') : effectiveScope === 'global' ? t('skGlobalCatalogContext') : t(loading ? 'skLoading' : 'skWorkspacePending'))),
    error ? h('p', { className: 'nm-room-error', role: 'alert' }, error) : null,
    catalog?.policyError ? h('p', { className: 'nm-room-error', role: 'alert' }, catalog.policyError === 'skills_workspace_unavailable' ? t('skWorkspaceUnavailable') : t('skPolicyError')) : null,
    catalog?.managed === false ? h('p', { className: 'nm-skills-hint', role: 'status' }, t('skUnmanaged')) : null,
    catalog && !catalog.complete ? h('p', { className: 'nm-skills-hint', role: 'status' }, t(effectiveScope === 'global' ? 'skIncompleteGlobal' : 'skIncomplete')) : null,
    h('label', { className: 'nm-skills-search' },
      h(IconSearch, { size: 17 }),
      h('input', { type: 'search', className: 'nm-input', value: query, placeholder: t('skSearch'), 'aria-label': t('skSearch'), onChange: (event: ChangeEvent<HTMLInputElement>) => onQuery(event.currentTarget.value) })),
    loading && !catalog ? h('p', { className: 'nm-skills-hint', role: 'status' }, t('skLoading')) : null,
    catalog && rows.length === 0 && !unknown && (needle ? catalog.skills.length > 0 : catalog.complete) ? h('p', { className: 'nm-skills-hint' }, needle ? t('skNoMatches') : t('skEmpty')) : null,
    h('div', { className: 'nm-card nm-skills-list', 'aria-busy': loading || saving !== null }, rows.map((skill) => {
      const globallyBlocked = effectiveScope === 'workspace' && skill.globalDisabled
      const checked = !unknown && (effectiveScope === 'global' ? !skill.globalDisabled : !skill.globalDisabled && !skill.workspaceDisabled)
      const status = unknown ? t('skUnknown') : skill.globalDisabled ? t('skDisabledGlobally') : skill.workspaceDisabled ? t('skDisabledHere') : t('skEnabled')
      return h('article', { key: skill.name, className: 'nm-skill', 'data-skill-name': skill.name },
        h('div', { className: 'nm-skill-head' },
          h('div', { className: 'nm-row-main' }, h('h3', { className: 'nm-row-title' }, skill.name), h('span', { className: 'nm-row-sub' }, saving === skill.name ? t('skSaving') : status)),
          h('button', { type: 'button', role: 'switch', className: 'nm-switch', 'aria-checked': checked, 'aria-label': t(effectiveScope === 'global' ? 'skAllowGlobal' : 'skAllowHere', { name: skill.name }), disabled: blocked || globallyBlocked, onClick: () => onToggle(skill, effectiveScope) })),
        h('p', { className: 'nm-skill-description' }, skill.description || t('skNoDescription')),
        globallyBlocked ? h('p', { className: 'nm-skills-hint' }, t('skGlobalBlocked')) : null,
        h('details', { className: 'nm-skill-details' },
          h('summary', null, t('skDetails')),
          h('dl', null,
            h('dt', null, t('skSource')), h('dd', null, skill.source),
            h('dt', null, t('skProvider')), h('dd', null, skill.provider),
            skill.path ? h('dt', null, t('skPath')) : null,
            skill.path ? h('dd', null, h('code', null, skill.path)) : null)))
    })),
    h('p', { className: 'nm-skills-hint' }, t('skLimits')))
}

export function makeSkillsSection(t: Translate) {
  return function SkillsSection(): ReactNode {
    const sessionId = useWin().current ?? ''
    const [scope, setScope] = useState<SkillScope>('workspace')
    const effectiveScope = sessionId ? scope : 'global'
    const requestedSession = effectiveScope === 'workspace' ? sessionId : ''
    const key = effectiveScope === 'global' ? 'global' : `workspace:${sessionId}`
    const currentKey = useRef(key)
    currentKey.current = key
    const mounted = useRef(false)
    const requestId = useRef(0)
    const mutationId = useRef(0)
    const [snapshot, setSnapshot] = useState<{ key: string; catalog: SkillCatalog } | null>(null)
    const [query, setQuery] = useState('')
    const [loading, setLoading] = useState(true)
    const [saving, setSaving] = useState<{ id: number; key: string; name: string } | null>(null)
    const [error, setError] = useState<{ key: string; message: string } | null>(null)
    // Scope and session both identify the catalog. Never show a previous workspace's controls.
    const catalog = snapshot?.key === key ? snapshot.catalog : null

    const refresh = useCallback(async () => {
      const id = ++requestId.current
      setLoading(true)
      setError(null)
      try {
        const path = requestedSession ? `catalog?sessionId=${encodeURIComponent(requestedSession)}` : 'catalog'
        const result = await skillsCall<SkillCatalog>(path)
        if (mounted.current && id === requestId.current && currentKey.current === key) setSnapshot({ key, catalog: result })
      } catch (cause: unknown) {
        if (mounted.current && id === requestId.current && currentKey.current === key) setError({ key, message: skillsFailure(t, cause) })
      } finally {
        if (mounted.current && id === requestId.current && currentKey.current === key) setLoading(false)
      }
    }, [key, requestedSession, t])

    useEffect(() => {
      mounted.current = true
      void refresh()
      return () => { mounted.current = false; requestId.current++ }
    }, [refresh])

    const toggle = async (skill: SkillEntry, targetScope: SkillScope): Promise<void> => {
      if (!catalog || !catalog.managed || catalog.policyError || loading || saving?.key === key || targetScope !== effectiveScope || (targetScope === 'workspace' && (!catalog.workspace || !sessionId || skill.globalDisabled))) return
      const id = ++mutationId.current
      setSaving({ id, key, name: skill.name })
      setError(null)
      try {
        await skillsCall('toggle', {
          name: skill.name,
          scope: targetScope,
          disabled: targetScope === 'global' ? !skill.globalDisabled : !skill.workspaceDisabled,
          ...(targetScope === 'workspace' ? { workspace: catalog.workspace, sessionId } : {}),
        })
        if (mounted.current && currentKey.current === key) await refresh()
      } catch (cause: unknown) {
        if (mounted.current && currentKey.current === key) setError({ key, message: skillsFailure(t, cause) })
      } finally {
        if (mounted.current) setSaving((value) => value?.id === id ? null : value)
      }
    }

    return h(SkillsPanel, {
      t, catalog, hasSession: Boolean(sessionId), scope, query, loading,
      saving: saving?.key === key ? saving.name : null,
      error: error?.key === key ? error.message : null,
      onScope: setScope, onQuery: setQuery, onRefresh: () => { void refresh() },
      onToggle: (skill, targetScope) => { void toggle(skill, targetScope) },
    })
  }
}
