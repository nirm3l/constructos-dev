import React from 'react'
import * as AlertDialog from '@radix-ui/react-alert-dialog'
import { useQuery } from '@tanstack/react-query'
import {
  getProjectGitRepositoryBranches,
  getProjectGitRepositoryFile,
  getProjectGitRepositorySummary,
  getProjectGitRepositoryTree,
} from '../../api'
import type {
  ProjectGitRepositoryBranch,
  ProjectGitRepositoryFileResponse,
  ProjectGitRepositoryTreeEntry,
} from '../../types'
import type { ProjectGitRepositoryTarget } from '../../utils/gitRepositoryLinks'
import { MarkdownView } from '../../markdown/MarkdownView'
import { toErrorMessage } from '../../utils/ui'
import { Icon } from '../shared/uiHelpers'

type ProjectGitRepositoryDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  userId: string
  projectId: string
  target?: ProjectGitRepositoryTarget | null
}

function branchMeta(branch: ProjectGitRepositoryBranch): string {
  const parts = [
    branch.is_current ? 'Current' : '',
    branch.is_default ? 'Default' : '',
    branch.merged_to_main ? 'Merged' : '',
    branch.author_name || '',
    branch.committed_at || '',
  ].filter(Boolean)
  return parts.join(' | ')
}

function filePreviewCopy(file: ProjectGitRepositoryFileResponse | undefined): string {
  if (!file) return 'Select a file to preview.'
  if (file.binary) return 'Binary file preview is not available.'
  if (!file.previewable) return 'File is too large for inline preview.'
  return String(file.content || '')
}

function inferCodeLanguage(path: string | undefined): string {
  const normalized = String(path || '').trim().toLowerCase()
  if (!normalized) return ''
  const extension = normalized.includes('.') ? normalized.split('.').pop() || '' : ''
  switch (extension) {
    case 'ts':
    case 'tsx':
      return 'typescript'
    case 'js':
    case 'jsx':
    case 'mjs':
    case 'cjs':
      return 'javascript'
    case 'py':
      return 'python'
    case 'json':
      return 'json'
    case 'md':
      return 'markdown'
    case 'yml':
    case 'yaml':
      return 'yaml'
    case 'html':
      return 'html'
    case 'css':
      return 'css'
    case 'scss':
      return 'scss'
    case 'sh':
    case 'bash':
      return 'bash'
    case 'toml':
      return 'toml'
    case 'xml':
      return 'xml'
    case 'sql':
      return 'sql'
    case 'go':
      return 'go'
    case 'rs':
      return 'rust'
    case 'java':
      return 'java'
    case 'kt':
      return 'kotlin'
    case 'php':
      return 'php'
    case 'rb':
      return 'ruby'
    case 'dockerfile':
      return 'dockerfile'
    default:
      if (normalized.endsWith('/dockerfile') || normalized === 'dockerfile') return 'dockerfile'
      return extension || ''
  }
}

function buildHighlightedPreviewMarkdown(file: ProjectGitRepositoryFileResponse | undefined): string {
  const content = filePreviewCopy(file)
  if (!file || file.binary || !file.previewable) return content
  const language = inferCodeLanguage(file.path)
  return `\`\`\`${language}\n${content}\n\`\`\``
}

export function ProjectGitRepositoryDialog({
  open,
  onOpenChange,
  userId,
  projectId,
  target = null,
}: ProjectGitRepositoryDialogProps) {
  const summaryQuery = useQuery({
    queryKey: ['project-git-repository-summary', userId, projectId],
    queryFn: () => getProjectGitRepositorySummary(userId, projectId),
    enabled: open && Boolean(userId) && Boolean(projectId),
  })
  const branchesQuery = useQuery({
    queryKey: ['project-git-repository-branches', userId, projectId],
    queryFn: () => getProjectGitRepositoryBranches(userId, projectId),
    enabled: open && Boolean(userId) && Boolean(projectId) && Boolean(summaryQuery.data?.available),
  })
  const [selectedRef, setSelectedRef] = React.useState('')
  const [currentPath, setCurrentPath] = React.useState('')
  const [selectedFilePath, setSelectedFilePath] = React.useState('')

  const branches = React.useMemo(
    () => (Array.isArray(branchesQuery.data?.branches) ? branchesQuery.data?.branches : []),
    [branchesQuery.data?.branches]
  )

  const targetRef = String(target?.ref || '').trim()
  const targetPath = String(target?.path || '').trim()
  const targetPathKind = target?.pathKind === 'directory' ? 'directory' : target?.pathKind === 'file' ? 'file' : null

  React.useEffect(() => {
    if (!open) {
      setCurrentPath('')
      setSelectedFilePath('')
      return
    }
    const preferredRef =
      targetRef ||
      summaryQuery.data?.current_branch ||
      summaryQuery.data?.default_branch ||
      branches[0]?.name ||
      ''
    if (!preferredRef) return
    setSelectedRef(preferredRef)
    if (!targetPath) {
      setCurrentPath('')
      setSelectedFilePath('')
      return
    }
    if (targetPathKind === 'directory') {
      setCurrentPath(targetPath)
      setSelectedFilePath('')
      return
    }
    const segments = targetPath.split('/').filter(Boolean)
    setCurrentPath(segments.slice(0, -1).join('/'))
    setSelectedFilePath(targetPath)
  }, [
    open,
    targetRef,
    targetPath,
    targetPathKind,
    summaryQuery.data?.current_branch,
    summaryQuery.data?.default_branch,
    branches,
  ])

  const treeQuery = useQuery({
    queryKey: ['project-git-repository-tree', userId, projectId, selectedRef, currentPath],
    queryFn: () => getProjectGitRepositoryTree(userId, projectId, { ref: selectedRef, path: currentPath }),
    enabled: open && Boolean(userId) && Boolean(projectId) && Boolean(selectedRef),
  })

  const fileQuery = useQuery({
    queryKey: ['project-git-repository-file', userId, projectId, selectedRef, selectedFilePath],
    queryFn: () => getProjectGitRepositoryFile(userId, projectId, { ref: selectedRef, path: selectedFilePath }),
    enabled: open && Boolean(userId) && Boolean(projectId) && Boolean(selectedRef) && Boolean(selectedFilePath),
  })

  const pathSegments = currentPath.split('/').filter(Boolean)
  const entries = React.useMemo(
    () => (Array.isArray(treeQuery.data?.entries) ? treeQuery.data?.entries : []),
    [treeQuery.data?.entries]
  )

  const openEntry = (entry: ProjectGitRepositoryTreeEntry) => {
    if (entry.kind === 'directory') {
      setCurrentPath(entry.path)
      setSelectedFilePath('')
      return
    }
    setSelectedFilePath(entry.path)
  }

  return (
    <AlertDialog.Root open={open} onOpenChange={onOpenChange}>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="codex-chat-alert-overlay" />
        <AlertDialog.Content className="codex-chat-alert-content git-repository-dialog">
          <div className="docker-runtime-dialog-head">
            <div>
              <AlertDialog.Title className="codex-chat-alert-title">Repository Inspector</AlertDialog.Title>
              <AlertDialog.Description className="codex-chat-alert-description">
                Read-only branch, tree, and file preview for this Git Delivery project repository.
              </AlertDialog.Description>
            </div>
            <AlertDialog.Cancel asChild>
              <button type="button" className="action-icon docker-runtime-dialog-close" aria-label="Close repository inspector">
                <Icon path="M6 6l12 12M18 6L6 18" />
              </button>
            </AlertDialog.Cancel>
          </div>

          {summaryQuery.isLoading ? (
            <div className="meta">Loading repository state...</div>
          ) : summaryQuery.isError ? (
            <div className="notice notice-error">{toErrorMessage(summaryQuery.error, 'Unable to load repository state.')}</div>
          ) : !summaryQuery.data?.available ? (
            <div className="notice">Project repository is not available yet.</div>
          ) : (
            <div className="git-repository-dialog-body">
              <div className="docker-runtime-summary-grid">
                <div className="docker-runtime-summary-card">
                  <span className="meta">Repository root</span>
                  <strong>{summaryQuery.data.repo_root}</strong>
                </div>
                <div className="docker-runtime-summary-card">
                  <span className="meta">Current branch</span>
                  <strong>{summaryQuery.data.current_branch || 'Detached HEAD'}</strong>
                </div>
                <div className="docker-runtime-summary-card">
                  <span className="meta">Default branch</span>
                  <strong>{summaryQuery.data.default_branch || 'Unknown'}</strong>
                </div>
                <div className="docker-runtime-summary-card">
                  <span className="meta">Branches</span>
                  <strong>{summaryQuery.data.branch_count}</strong>
                </div>
              </div>

              <div className="git-repository-toolbar">
                <label className="git-repository-branch-picker">
                  <span className="meta">Branch</span>
                  <select value={selectedRef} onChange={(event) => setSelectedRef(event.target.value)}>
                          {branches.map((branch) => (
                        <option key={branch.name} value={branch.name}>
                          {branch.name}
                        </option>
                      ))}
                      {selectedRef && !branches.some((branch) => branch.name === selectedRef) ? (
                        <option value={selectedRef}>{`Detached revision (${selectedRef.slice(0, 12)})`}</option>
                      ) : null}
                    </select>
                  </label>
                <div className="git-repository-breadcrumbs">
                  <button type="button" className="status-chip" onClick={() => {
                    setCurrentPath('')
                    setSelectedFilePath('')
                  }}>
                    root
                  </button>
                  {pathSegments.map((segment, index) => {
                    const nextPath = pathSegments.slice(0, index + 1).join('/')
                    return (
                      <button
                        key={nextPath}
                        type="button"
                        className="status-chip"
                        onClick={() => {
                          setCurrentPath(nextPath)
                          setSelectedFilePath('')
                        }}
                      >
                        {segment}
                      </button>
                    )
                  })}
                </div>
              </div>

              <div className="git-repository-layout">
                <div className="git-repository-branches-panel">
                  <div className="meta">Branches</div>
                  {branchesQuery.isError ? (
                    <div className="notice notice-error">{toErrorMessage(branchesQuery.error, 'Unable to load branches.')}</div>
                  ) : (
                    <div className="git-repository-branch-list">
                    {branches.map((branch) => (
                        <button
                          key={branch.name}
                          type="button"
                          className={`git-repository-branch-card ${branch.name === selectedRef ? 'active' : ''}`.trim()}
                          onClick={() => setSelectedRef(branch.name)}
                        >
                          <strong>{branch.name}</strong>
                          <span className="meta">{branchMeta(branch) || 'No metadata available'}</span>
                          {branch.subject ? <span className="meta">{branch.subject}</span> : null}
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                <div className="git-repository-tree-panel">
                  <div className="meta">Files</div>
                  {treeQuery.isLoading ? (
                    <div className="meta">Loading tree...</div>
                  ) : treeQuery.isError ? (
                    <div className="notice notice-error">{toErrorMessage(treeQuery.error, 'Unable to load repository tree.')}</div>
                  ) : (
                    <div className="git-repository-tree-list">
                      {currentPath ? (
                        <button
                          type="button"
                          className="git-repository-tree-entry"
                          onClick={() => {
                            const parent = pathSegments.slice(0, -1).join('/')
                            setCurrentPath(parent)
                            setSelectedFilePath('')
                          }}
                        >
                          <span className="meta">..</span>
                        </button>
                      ) : null}
                      {entries.length === 0 ? (
                        <div className="meta">No entries in this location.</div>
                      ) : (
                        entries.map((entry) => (
                          <button
                            key={entry.path}
                            type="button"
                            className={`git-repository-tree-entry ${entry.path === selectedFilePath ? 'active' : ''}`.trim()}
                            onClick={() => openEntry(entry)}
                          >
                            <span className="git-repository-tree-entry-icon">
                              <Icon path={entry.kind === 'directory' ? 'M3 7h5l2 2h11v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z' : 'M7 3h7l5 5v13a1 1 0 01-1 1H7a2 2 0 01-2-2V5a2 2 0 012-2z'} />
                            </span>
                            <span>{entry.name}</span>
                          </button>
                        ))
                      )}
                    </div>
                  )}
                </div>

                <div className="git-repository-preview-panel">
                  <div className="git-repository-preview-head">
                    <div className="meta">Preview</div>
                    {selectedFilePath ? <code>{selectedFilePath}</code> : selectedRef ? <code>{selectedRef}</code> : null}
                  </div>
                  {fileQuery.isLoading ? (
                    <div className="meta">Loading file preview...</div>
                  ) : fileQuery.isError ? (
                    <div className="notice notice-error">{toErrorMessage(fileQuery.error, 'Unable to load file preview.')}</div>
                  ) : (
                    <>
                      {fileQuery.data?.size_bytes != null ? (
                        <div className="row wrap" style={{ gap: 8, marginBottom: 8 }}>
                          <span className="badge">Size: {fileQuery.data.size_bytes} bytes</span>
                          {fileQuery.data.binary ? <span className="badge">Binary</span> : null}
                          {!fileQuery.data.previewable ? <span className="badge">Preview unavailable</span> : null}
                        </div>
                      ) : null}
                      <div className="git-repository-preview">
                        {fileQuery.data && fileQuery.data.previewable && !fileQuery.data.binary ? (
                          <MarkdownView value={buildHighlightedPreviewMarkdown(fileQuery.data)} disableMermaid />
                        ) : (
                          <pre className="git-repository-preview-fallback">{filePreviewCopy(fileQuery.data)}</pre>
                        )}
                      </div>
                    </>
                  )}
                </div>
              </div>
            </div>
          )}
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  )
}
