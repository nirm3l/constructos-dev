import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import { MermaidDiagram } from './MermaidDiagram'

function isInternalAppHref(href: string): boolean {
  const value = href.trim()
  return value.startsWith('?') || value.startsWith('/?')
}

function navigateInternalHref(href: string): void {
  if (typeof window === 'undefined') return
  const url = new URL(href, window.location.href)
  const next = `${url.pathname}${url.search}${url.hash}`
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`
  if (next === current) {
    window.dispatchEvent(new PopStateEvent('popstate'))
    return
  }
  window.history.pushState(null, '', next)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

function extractText(node: React.ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map((part) => extractText(part)).join('')
  if (!React.isValidElement(node)) return ''
  const maybeChildren = (node.props as { children?: React.ReactNode }).children
  return extractText(maybeChildren)
}

function isMermaidCodeBlock(className: string | undefined, inline: boolean | undefined): boolean {
  if (inline) return false
  const normalized = String(className || '').toLowerCase()
  return normalized.includes('language-mermaid')
}

type MarkdownCodeProps = React.ComponentPropsWithoutRef<'code'> & {
  inline?: boolean
  className?: string
  children?: React.ReactNode
}

type MarkdownPreProps = React.ComponentPropsWithoutRef<'pre'> & {
  children?: React.ReactNode
}

function isMermaidDiagramElement(node: React.ReactNode): boolean {
  if (!React.isValidElement(node)) return false
  const elementType = node.type as unknown
  if (elementType === MermaidDiagram) return true
  const displayName = (elementType as { displayName?: string } | null)?.displayName
  return displayName === 'MermaidDiagram'
}

function isJsonCodeClassName(className: string): boolean {
  const normalized = className.trim().toLowerCase()
  return normalized.includes('language-json')
}

function normalizeCodeText(value: string): string {
  return value.replace(/\r\n/g, '\n').replace(/\s+$/, '')
}

function isValidJsonCandidate(raw: string): boolean {
  const candidate = normalizeCodeText(raw).trim()
  if (!candidate) return false
  if (!(candidate.startsWith('{') || candidate.startsWith('['))) return false
  try {
    JSON.parse(candidate)
    return true
  } catch {
    return false
  }
}

function extractJsonCodeFromNode(node: React.ReactNode): { className: string; rawText: string } | null {
  if (!React.isValidElement(node)) return null
  const props = node.props as { className?: string; children?: React.ReactNode } | undefined
  const className = String(props?.className || '')
  const rawText = extractText(props?.children).replace(/\n$/, '')
  const nodeType = String(node.type || '').toLowerCase()
  const looksLikeCodeNode = nodeType === 'code' || Boolean(className) || rawText.length > 0
  if (looksLikeCodeNode && (isJsonCodeClassName(className) || isValidJsonCandidate(rawText))) {
    const normalizedClassName = isJsonCodeClassName(className)
      ? className
      : `${className} language-json`.trim()
    return { className: normalizedClassName, rawText }
  }
  const nested = React.Children.toArray(props?.children)
  for (const child of nested) {
    const found = extractJsonCodeFromNode(child)
    if (found) return found
  }
  return null
}

function prettifyJsonBlockInMarkdown(
  markdownValue: string,
  targetRawText: string,
  targetOccurrence: number
): string {
  const source = String(markdownValue || '')
  const fencedBlockRe = /```([^\n`]*)\n([\s\S]*?)```/g
  let changed = false
  const normalizedTarget = normalizeCodeText(targetRawText).trim()
  let matchedOccurrence = -1
  const rewritten = source.replace(fencedBlockRe, (fullMatch, rawHeader, rawBody) => {
    const bodyText = String(rawBody || '')
    const candidate = normalizeCodeText(bodyText).trim()
    if (!isValidJsonCandidate(candidate)) return fullMatch
    if (candidate !== normalizedTarget) return fullMatch
    matchedOccurrence += 1
    if (matchedOccurrence !== targetOccurrence) return fullMatch
    let pretty = ''
    try {
      pretty = JSON.stringify(JSON.parse(candidate), null, 2)
    } catch {
      return fullMatch
    }
    if (normalizeCodeText(bodyText).trim() === pretty) return fullMatch
    changed = true
    const header = String(rawHeader || '')
    return `\`\`\`${header}\n${pretty}\n\`\`\``
  })
  return changed ? rewritten : source
}

function JsonPrettifyBlock({
  className,
  rawText,
  onPrettifyJson,
}: {
  className: string
  rawText: string
  onPrettifyJson?: () => void
}) {
  const normalizedRaw = React.useMemo(() => normalizeCodeText(rawText), [rawText])
  const parsed = React.useMemo(() => {
    try {
      return JSON.parse(normalizedRaw)
    } catch {
      return null
    }
  }, [normalizedRaw])
  const prettyText = React.useMemo(() => {
    if (parsed == null) return ''
    return JSON.stringify(parsed, null, 2)
  }, [parsed])
  const canPrettify = Boolean(parsed != null && prettyText && normalizeCodeText(prettyText) !== normalizedRaw)
  const [localPrettified, setLocalPrettified] = React.useState(false)
  const renderedText = canPrettify && localPrettified ? prettyText : normalizedRaw
  const handlePrettify = React.useCallback(() => {
    if (!canPrettify) return
    if (onPrettifyJson) {
      onPrettifyJson()
      return
    }
    setLocalPrettified(true)
  }, [canPrettify, onPrettifyJson])

  return (
    <div className="markdown-json-block">
      {canPrettify && !localPrettified && (
        <div className="markdown-json-block-toolbar">
          <button
            type="button"
            className="markdown-json-prettify-btn"
            onClick={handlePrettify}
            aria-label="Prettify JSON code block"
          >
            Prettify JSON
          </button>
        </div>
      )}
      <pre>
        <code className={className}>{renderedText}</code>
      </pre>
    </div>
  )
}

function MarkdownViewComponent({
  value,
  disableMermaid = false,
  onPrettifyJson,
}: {
  value: string
  disableMermaid?: boolean
  onPrettifyJson?: (next: string) => void
}) {
  const normalizedValue = String(value || '')
  const trimmedValue = normalizedValue.trim()
  const hasMarkdownFence = /```/.test(normalizedValue)
  const isStandaloneJson = React.useMemo(() => {
    if (!trimmedValue) return false
    const startsAsJson = trimmedValue.startsWith('{') || trimmedValue.startsWith('[')
    if (!startsAsJson) return false
    try {
      JSON.parse(trimmedValue)
      return true
    } catch {
      return false
    }
  }, [trimmedValue])
  const handlePrettifyStandaloneJson = React.useCallback(() => {
    if (!onPrettifyJson) return
    try {
      const next = JSON.stringify(JSON.parse(trimmedValue), null, 2)
      onPrettifyJson(next)
    } catch {
      onPrettifyJson(normalizedValue)
    }
  }, [normalizedValue, onPrettifyJson, trimmedValue])

  const handlePrettifyJsonBlock = React.useCallback((rawText: string, occurrence: number) => {
    if (!onPrettifyJson) return
    const next = prettifyJsonBlockInMarkdown(normalizedValue, rawText, occurrence)
    onPrettifyJson(next)
  }, [normalizedValue, onPrettifyJson])

  if (isStandaloneJson && !hasMarkdownFence) {
    return (
      <div className="markdown">
        <JsonPrettifyBlock className="hljs language-json" rawText={trimmedValue} onPrettifyJson={handlePrettifyStandaloneJson} />
      </div>
    )
  }

  const jsonBlockOccurrences = new Map<string, number>()

  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeHighlight, { detect: true, ignoreMissing: true }]]}
        components={{
          a: ({ href, children, ...props }) => {
            const safeHref = String(href || '').trim()
            if (!safeHref) return <a {...props}>{children}</a>
            if (!isInternalAppHref(safeHref)) return <a href={safeHref} {...props}>{children}</a>
            return (
              <a
                href={safeHref}
                {...props}
                onClick={(event) => {
                  event.preventDefault()
                  navigateInternalHref(safeHref)
                }}
              >
                {children}
              </a>
            )
          },
          code: ({ inline, className, children, ...props }: MarkdownCodeProps) => {
            if (!disableMermaid && isMermaidCodeBlock(className, inline)) {
              const source = extractText(children).replace(/\n$/, '')
              return <MermaidDiagram code={source} />
            }
            return (
              <code className={className} {...props}>
                {children}
              </code>
            )
          },
          pre: ({ children, ...props }: MarkdownPreProps) => {
            const parts = React.Children.toArray(children)
            let mermaidNode: React.ReactNode | null = null
            let hasMeaningfulNonMermaidContent = false
            let jsonCode: { className: string; rawText: string } | null = null

            for (const part of parts) {
              if (isMermaidDiagramElement(part)) {
                if (!mermaidNode) mermaidNode = part
                continue
              }
              if (!jsonCode) {
                jsonCode = extractJsonCodeFromNode(part)
              }
              if (extractText(part).trim()) {
                hasMeaningfulNonMermaidContent = true
              }
            }

            if (mermaidNode && !hasMeaningfulNonMermaidContent) {
              return <>{mermaidNode}</>
            }
            if (jsonCode) {
              const isPrettifiableJson = isValidJsonCandidate(jsonCode.rawText)
              if (!isPrettifiableJson) {
                return <pre {...props}>{children}</pre>
              }
              const blockKey = normalizeCodeText(jsonCode.rawText).trim()
              const occurrence = jsonBlockOccurrences.get(blockKey) ?? 0
              jsonBlockOccurrences.set(blockKey, occurrence + 1)
              return (
                <JsonPrettifyBlock
                  className={jsonCode.className}
                  rawText={jsonCode.rawText}
                  onPrettifyJson={() => handlePrettifyJsonBlock(jsonCode.rawText, occurrence)}
                />
              )
            }
            return <pre {...props}>{children}</pre>
          },
        }}
      >
        {value || ''}
      </ReactMarkdown>
    </div>
  )
}

export const MarkdownView = React.memo(
  MarkdownViewComponent,
  (prev, next) =>
    prev.value === next.value &&
    prev.disableMermaid === next.disableMermaid &&
    prev.onPrettifyJson === next.onPrettifyJson
)
