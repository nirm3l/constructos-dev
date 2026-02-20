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

function MarkdownViewComponent({
  value,
  disableMermaid = false,
}: {
  value: string
  disableMermaid?: boolean
}) {
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

            for (const part of parts) {
              if (isMermaidDiagramElement(part)) {
                if (!mermaidNode) mermaidNode = part
                continue
              }
              if (extractText(part).trim()) {
                hasMeaningfulNonMermaidContent = true
                break
              }
            }

            if (mermaidNode && !hasMeaningfulNonMermaidContent) {
              return <>{mermaidNode}</>
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
  (prev, next) => prev.value === next.value && prev.disableMermaid === next.disableMermaid
)
