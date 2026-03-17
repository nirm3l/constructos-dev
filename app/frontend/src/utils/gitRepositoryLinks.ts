import type { ExternalRef } from '../types'

export type ProjectGitRepositoryTarget = {
  ref?: string
  path?: string
  pathKind?: 'file' | 'directory'
}

function normalizeText(value: string | undefined): string {
  return String(value || '').trim().toLowerCase()
}

function looksLikeCommitSha(value: string): boolean {
  return /^[0-9a-f]{7,40}$/i.test(String(value || '').trim())
}

function normalizeRepoPath(value: string | undefined): string {
  const raw = String(value || '').trim().replace(/\\/g, '/').replace(/^\/+|\/+$/g, '')
  if (!raw || raw.includes('..')) return ''
  return raw
}

function buildPathTarget(ref: string | undefined, rawPath: string | undefined, pathKind: 'file' | 'directory'): ProjectGitRepositoryTarget | null {
  const path = normalizeRepoPath(rawPath)
  if (!path) return null
  return {
    ref: String(ref || '').trim() || 'HEAD',
    path,
    pathKind,
  }
}

function parseKnownGitHostUrl(urlText: string): ProjectGitRepositoryTarget | null {
  let parsed: URL
  try {
    parsed = new URL(urlText)
  } catch {
    return null
  }
  const segments = parsed.pathname.split('/').filter(Boolean).map((segment) => decodeURIComponent(segment))
  if (segments.length === 0) return null

  const commitIndex = segments.findIndex((segment) => segment === 'commit' || segment === 'commits')
  if (commitIndex >= 0) {
    const sha = String(segments[commitIndex + 1] || '').trim()
    if (looksLikeCommitSha(sha)) return { ref: sha }
  }

  const treeIndex = segments.findIndex((segment) => segment === 'tree')
  if (treeIndex >= 0) {
    const ref = String(segments[treeIndex + 1] || '').trim()
    if (!ref) return null
    const path = segments.slice(treeIndex + 2).join('/')
    return path ? buildPathTarget(ref, path, 'directory') : { ref }
  }

  const blobIndex = segments.findIndex((segment) => segment === 'blob')
  if (blobIndex >= 0) {
    const ref = String(segments[blobIndex + 1] || '').trim()
    if (!ref) return null
    return buildPathTarget(ref, segments.slice(blobIndex + 2).join('/'), 'file')
  }

  const srcIndex = segments.findIndex((segment) => segment === 'src')
  if (srcIndex >= 0) {
    const ref = String(parsed.searchParams.get('at') || segments[srcIndex + 1] || '').trim()
    const pathStartIndex = parsed.searchParams.get('at') ? srcIndex + 1 : srcIndex + 2
    if (!ref) return null
    const path = segments.slice(pathStartIndex).join('/')
    if (!path) return { ref }
    const inferredKind: 'file' | 'directory' = parsed.pathname.endsWith('/') ? 'directory' : 'file'
    return buildPathTarget(ref, path, inferredKind)
  }

  return null
}

export function parseProjectGitRepositoryExternalRef(ref: ExternalRef | undefined | null): ProjectGitRepositoryTarget | null {
  if (!ref) return null
  const url = String(ref.url || '').trim()
  if (!url) return null

  const title = normalizeText(ref.title)
  const source = normalizeText(ref.source)
  const meta = `${title} ${source}`.trim()

  if (url.startsWith('commit:')) {
    const sha = url.slice('commit:'.length).trim()
    return looksLikeCommitSha(sha) ? { ref: sha } : null
  }
  if (url.startsWith('branch:')) {
    const branch = url.slice('branch:'.length).trim()
    return branch ? { ref: branch } : null
  }
  if (url.startsWith('file:')) {
    return buildPathTarget('HEAD', url.slice('file:'.length), 'file')
  }
  if (url.startsWith('folder:')) {
    return buildPathTarget('HEAD', url.slice('folder:'.length), 'directory')
  }
  if (url.startsWith('dir:')) {
    return buildPathTarget('HEAD', url.slice('dir:'.length), 'directory')
  }

  const hostUrlTarget = parseKnownGitHostUrl(url)
  if (hostUrlTarget) return hostUrlTarget

  if (meta.includes('commit') && looksLikeCommitSha(url)) {
    return { ref: url }
  }

  if (meta.includes('branch')) {
    const branch = url.trim()
    if (branch && !branch.includes('://') && !branch.includes(':') && !branch.startsWith('/')) {
      return { ref: branch }
    }
  }

  if (meta.includes('folder') || meta.includes('directory')) {
    return buildPathTarget('HEAD', url, 'directory')
  }

  if (meta.includes('file')) {
    return buildPathTarget('HEAD', url, 'file')
  }

  return null
}
