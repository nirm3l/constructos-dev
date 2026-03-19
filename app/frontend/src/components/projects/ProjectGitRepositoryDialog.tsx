import React from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import * as Tabs from '@radix-ui/react-tabs'
import { useQuery } from '@tanstack/react-query'
import { Diff, Hunk, parseDiff } from 'react-diff-view'
import type { FileData, ViewType } from 'react-diff-view'
import {
  getProjectGitRepositoryBranches,
  getProjectGitRepositoryDiff,
  getProjectGitRepositoryFile,
  getProjectGitRepositorySummary,
  getProjectGitRepositoryTree,
} from '../../api'
import type {
  ProjectGitRepositoryBranch,
  ProjectGitRepositoryDiffFile,
  ProjectGitRepositoryDiffResponse,
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
  reviewContext?: {
    taskId: string
    taskTitle: string
    taskHref?: string | null
    isPending?: boolean
    onApprove: () => void
    onRequestChanges: () => void
  } | null
}

type InspectorDesktopTab = 'files' | 'diff'
type InspectorMobileTab = 'branches' | 'files' | 'preview' | 'diff'

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

function diffStatusLabel(file: ProjectGitRepositoryDiffFile): string {
  switch (String(file.status || '').trim().toLowerCase()) {
    case 'added':
      return 'Added'
    case 'deleted':
      return 'Deleted'
    case 'renamed':
      return 'Renamed'
    case 'copied':
      return 'Copied'
    case 'type_changed':
      return 'Type changed'
    case 'unmerged':
      return 'Unmerged'
    default:
      return 'Modified'
  }
}

function diffStatusClassName(file: ProjectGitRepositoryDiffFile): string {
  switch (String(file.status || '').trim().toLowerCase()) {
    case 'added':
      return 'is-added'
    case 'deleted':
      return 'is-deleted'
    case 'renamed':
      return 'is-renamed'
    case 'copied':
      return 'is-copied'
    default:
      return 'is-modified'
  }
}

function diffFileKey(file: ProjectGitRepositoryDiffFile): string {
  const oldPath = String(file.old_path || '').trim()
  const path = String(file.path || '').trim()
  return `${oldPath}->${path}`
}

function normalizeDiffFiles(diff: ProjectGitRepositoryDiffResponse | undefined): ProjectGitRepositoryDiffFile[] {
  return Array.isArray(diff?.files) ? diff.files : []
}

export function ProjectGitRepositoryDialog({
  open,
  onOpenChange,
  userId,
  projectId,
  target = null,
  reviewContext = null,
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
  const [mobileTab, setMobileTab] = React.useState<InspectorMobileTab>('branches')
  const [desktopTab, setDesktopTab] = React.useState<InspectorDesktopTab>('files')
  const [diffBaseRef, setDiffBaseRef] = React.useState('')
  const [diffHeadRef, setDiffHeadRef] = React.useState('')
  const [diffViewType, setDiffViewType] = React.useState<ViewType>('split')

  const branches = React.useMemo(
    () => (Array.isArray(branchesQuery.data?.branches) ? branchesQuery.data?.branches : []),
    [branchesQuery.data?.branches]
  )

  const targetRef = String(target?.ref || '').trim()
  const targetPath = String(target?.path || '').trim()
  const targetPathKind = target?.pathKind === 'directory' ? 'directory' : target?.pathKind === 'file' ? 'file' : null
  const targetMode = target?.mode === 'diff' ? 'diff' : 'explorer'
  const targetBaseRef = String(target?.baseRef || '').trim()
  const targetHeadRef = String(target?.headRef || targetRef || '').trim()
  const defaultBranch = String(summaryQuery.data?.default_branch || '').trim()
  const reviewActionsVisible = Boolean(reviewContext && String(target?.reviewTaskId || '').trim() === String(reviewContext?.taskId || '').trim())

  React.useEffect(() => {
    if (!open) {
      setCurrentPath('')
      setSelectedFilePath('')
      setMobileTab('branches')
      setDesktopTab('files')
      setDiffViewType('split')
      return
    }
    const preferredRef =
      targetHeadRef ||
      summaryQuery.data?.current_branch ||
      summaryQuery.data?.default_branch ||
      branches[0]?.name ||
      ''
    if (!preferredRef) return
    setSelectedRef(preferredRef)
    setDiffHeadRef(targetHeadRef || preferredRef)
    setDiffBaseRef(targetBaseRef || summaryQuery.data?.default_branch || preferredRef)
    if (targetMode === 'diff' || preferredRef.startsWith('task/')) {
      setDesktopTab('diff')
      setMobileTab('diff')
    }
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
    targetBaseRef,
    targetHeadRef,
    targetMode,
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

  const diffQuery = useQuery({
    queryKey: ['project-git-repository-diff', userId, projectId, diffBaseRef, diffHeadRef],
    queryFn: () =>
      getProjectGitRepositoryDiff(userId, projectId, {
        base_ref: diffBaseRef,
        head_ref: diffHeadRef,
      }),
    enabled:
      open &&
      Boolean(userId) &&
      Boolean(projectId) &&
      Boolean(summaryQuery.data?.available) &&
      Boolean(diffBaseRef) &&
      Boolean(diffHeadRef),
  })

  const pathSegments = currentPath.split('/').filter(Boolean)
  const entries = React.useMemo(
    () => (Array.isArray(treeQuery.data?.entries) ? treeQuery.data?.entries : []),
    [treeQuery.data?.entries]
  )
  const diffFiles = React.useMemo(() => normalizeDiffFiles(diffQuery.data), [diffQuery.data])
  const parsedDiffFiles = React.useMemo(
    () => (diffQuery.data?.patch && !diffQuery.data.patch_truncated ? parseDiff(diffQuery.data.patch) : []),
    [diffQuery.data?.patch, diffQuery.data?.patch_truncated]
  )

  const branchOptions = React.useMemo(() => {
    const names = new Set<string>()
    if (defaultBranch) names.add(defaultBranch)
    for (const branch of branches) {
      if (branch.name) names.add(branch.name)
    }
    return Array.from(names)
  }, [branches, defaultBranch])

  const openEntry = (entry: ProjectGitRepositoryTreeEntry) => {
    if (entry.kind === 'directory') {
      setCurrentPath(entry.path)
      setSelectedFilePath('')
      setMobileTab('files')
      return
    }
    setSelectedFilePath(entry.path)
    setMobileTab('preview')
  }

  const selectBranch = (branchName: string) => {
    setSelectedRef(branchName)
    setCurrentPath('')
    setSelectedFilePath('')
    setDiffHeadRef(branchName)
    setMobileTab('files')
  }

  const renderBranchesPanel = () => (
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
              onClick={() => selectBranch(branch.name)}
            >
              <strong>{branch.name}</strong>
              <span className="meta">{branchMeta(branch) || 'No metadata available'}</span>
              {branch.subject ? <span className="meta">{branch.subject}</span> : null}
            </button>
          ))}
        </div>
      )}
    </div>
  )

  const renderFilesPanel = () => (
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
  )

  const renderPreviewPanel = () => (
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
  )

  const renderDiffFileSummary = (file: ProjectGitRepositoryDiffFile) => (
    <div key={diffFileKey(file)} className="git-repository-diff-file-card">
      <div className="git-repository-diff-file-card-head">
        <strong>{file.path}</strong>
        <span className={`badge git-repository-diff-status ${diffStatusClassName(file)}`.trim()}>{diffStatusLabel(file)}</span>
      </div>
      {file.old_path && file.old_path !== file.path ? <div className="meta">from {file.old_path}</div> : null}
      <div className="row wrap" style={{ gap: 8 }}>
        <span className="badge">+{file.additions ?? 0}</span>
        <span className="badge">-{file.deletions ?? 0}</span>
        {file.binary ? <span className="badge">Binary</span> : null}
      </div>
    </div>
  )

  const renderDiffPanel = () => (
    <div className="git-repository-diff-panel">
          <div className="git-repository-diff-toolbar">
        <label className="git-repository-branch-picker">
          <span className="meta">Base</span>
          <select value={diffBaseRef} onChange={(event) => setDiffBaseRef(event.target.value)}>
            {branchOptions.map((name) => (
              <option key={`base-${name}`} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label className="git-repository-branch-picker">
          <span className="meta">Compare</span>
          <select
            value={diffHeadRef}
            onChange={(event) => {
              setDiffHeadRef(event.target.value)
              setSelectedRef(event.target.value)
            }}
          >
            {branchOptions.map((name) => (
              <option key={`head-${name}`} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <div className="git-repository-diff-view-switch">
          <span className="meta">View</span>
          <div className="row wrap" style={{ gap: 8 }}>
            <button
              type="button"
              className={`status-chip ${diffViewType === 'split' ? 'active' : ''}`.trim()}
              onClick={() => setDiffViewType('split')}
            >
              Split
            </button>
            <button
              type="button"
              className={`status-chip ${diffViewType === 'unified' ? 'active' : ''}`.trim()}
              onClick={() => setDiffViewType('unified')}
            >
              Unified
            </button>
          </div>
        </div>
      </div>

      {diffQuery.isLoading ? (
        <div className="meta">Loading diff...</div>
      ) : diffQuery.isError ? (
        <div className="notice notice-error">{toErrorMessage(diffQuery.error, 'Unable to load branch diff.')}</div>
      ) : (
        <>
          {reviewActionsVisible ? (
            <div className="git-repository-review-banner">
              <div>
                <strong>Human review required</strong>
                <div className="meta">
                  Reviewing {diffHeadRef || 'task branch'} against {diffBaseRef || summaryQuery.data?.default_branch || 'main'} before merge.
                </div>
                {reviewContext?.taskHref ? (
                  <a className="status-chip" href={reviewContext.taskHref}>Open task</a>
                ) : null}
              </div>
              <div className="row wrap" style={{ gap: 8 }}>
                <button
                  type="button"
                  className="status-chip danger-ghost"
                  onClick={reviewContext?.onRequestChanges}
                  disabled={Boolean(reviewContext?.isPending)}
                >
                  Request changes
                </button>
                <button
                  type="button"
                  className="status-chip active"
                  onClick={reviewContext?.onApprove}
                  disabled={Boolean(reviewContext?.isPending)}
                >
                  Approve review
                </button>
              </div>
            </div>
          ) : null}
          <div className="docker-runtime-summary-grid">
            <div className="docker-runtime-summary-card">
              <span className="meta">Files changed</span>
              <strong>{diffQuery.data?.files_changed ?? 0}</strong>
            </div>
            <div className="docker-runtime-summary-card">
              <span className="meta">Insertions</span>
              <strong>+{diffQuery.data?.insertions ?? 0}</strong>
            </div>
            <div className="docker-runtime-summary-card">
              <span className="meta">Deletions</span>
              <strong>-{diffQuery.data?.deletions ?? 0}</strong>
            </div>
            <div className="docker-runtime-summary-card">
              <span className="meta">Compare mode</span>
              <strong>{diffQuery.data?.compare_mode || 'merge_base'}</strong>
            </div>
          </div>

          <div className="git-repository-diff-file-list">
            {diffFiles.length === 0 ? <div className="meta">No diff between these refs.</div> : diffFiles.map(renderDiffFileSummary)}
          </div>

          {diffQuery.data?.patch_truncated ? (
            <div className="notice">Patch preview is too large to render inline. File summary is still available above.</div>
          ) : parsedDiffFiles.length === 0 ? (
            <div className="meta">No patch hunks to render.</div>
          ) : (
            <div className="git-repository-diff-viewer">
              {parsedDiffFiles.map((file: FileData) => (
                <section key={`${file.oldRevision}-${file.newRevision}-${file.newPath}`} className="git-repository-diff-section">
                  <div className="git-repository-diff-section-head">
                    <strong>{file.newPath || file.oldPath}</strong>
                    <span className="meta">
                      {file.oldPath && file.oldPath !== file.newPath ? `${file.oldPath} -> ${file.newPath}` : diffStatusLabel({ path: file.newPath, status: file.type })}
                    </span>
                  </div>
                  {file.isBinary ? (
                    <div className="notice">Binary diff preview is not available.</div>
                  ) : (
                    <Diff viewType={diffViewType} diffType={file.type} hunks={file.hunks}>
                      {(hunks) => hunks.map((hunk) => <Hunk key={hunk.content} hunk={hunk} />)}
                    </Diff>
                  )}
                </section>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )

  const renderDesktopTabs = () => (
    <div className="git-repository-mode-switch" role="tablist" aria-label="Repository inspector mode">
      <button
        type="button"
        className={`status-chip ${desktopTab === 'files' ? 'active' : ''}`.trim()}
        onClick={() => setDesktopTab('files')}
      >
        Explorer
      </button>
      <button
        type="button"
        className={`status-chip ${desktopTab === 'diff' ? 'active' : ''}`.trim()}
        onClick={() => setDesktopTab('diff')}
      >
        Diff
      </button>
    </div>
  )

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="codex-chat-alert-overlay" />
        <Dialog.Content className="codex-chat-alert-content git-repository-dialog">
          <div className="docker-runtime-dialog-head">
            <div>
              <Dialog.Title className="codex-chat-alert-title">Repository Inspector</Dialog.Title>
              <Dialog.Description className="codex-chat-alert-description">
                Read-only branch explorer and branch-to-branch diff for this Git Delivery project repository.
              </Dialog.Description>
              {reviewActionsVisible ? (
                <div className="meta" style={{ marginTop: 6 }}>
                  Review task: {reviewContext?.taskTitle || reviewContext?.taskId}
                </div>
              ) : null}
            </div>
            <Dialog.Close asChild>
              <button type="button" className="action-icon docker-runtime-dialog-close" aria-label="Close repository inspector">
                <Icon path="M6 6l12 12M18 6L6 18" />
              </button>
            </Dialog.Close>
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
                  <strong className="git-repository-summary-value">{summaryQuery.data.repo_root}</strong>
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
                {renderDesktopTabs()}
                {desktopTab === 'files' ? (
                  <div className="git-repository-breadcrumbs">
                    <button
                      type="button"
                      className="status-chip"
                      onClick={() => {
                        setCurrentPath('')
                        setSelectedFilePath('')
                      }}
                    >
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
                ) : (
                  <div className="meta">Compare the task branch against {diffBaseRef || summaryQuery.data.default_branch || 'main'} before merge.</div>
                )}
              </div>

              <div className="git-repository-desktop-layout">
                {desktopTab === 'files' ? (
                  <div className="git-repository-layout">
                    {renderBranchesPanel()}
                    {renderFilesPanel()}
                    {renderPreviewPanel()}
                  </div>
                ) : (
                  renderDiffPanel()
                )}
              </div>

              <Tabs.Root className="inspector-mobile-tabs" value={mobileTab} onValueChange={(value) => setMobileTab(value as InspectorMobileTab)}>
                <Tabs.List className="inspector-mobile-tab-list" aria-label="Repository inspector sections">
                  <Tabs.Trigger className="inspector-mobile-tab-trigger" value="branches">Branches</Tabs.Trigger>
                  <Tabs.Trigger className="inspector-mobile-tab-trigger" value="files">Files</Tabs.Trigger>
                  <Tabs.Trigger className="inspector-mobile-tab-trigger" value="preview">Preview</Tabs.Trigger>
                  <Tabs.Trigger className="inspector-mobile-tab-trigger" value="diff">Diff</Tabs.Trigger>
                </Tabs.List>
                <Tabs.Content className="inspector-mobile-tab-content" value="branches">
                  {renderBranchesPanel()}
                </Tabs.Content>
                <Tabs.Content className="inspector-mobile-tab-content" value="files">
                  {renderFilesPanel()}
                </Tabs.Content>
                <Tabs.Content className="inspector-mobile-tab-content" value="preview">
                  {renderPreviewPanel()}
                </Tabs.Content>
                <Tabs.Content className="inspector-mobile-tab-content" value="diff">
                  {renderDiffPanel()}
                </Tabs.Content>
              </Tabs.Root>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
