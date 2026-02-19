import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'

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

export function MarkdownView({ value }: { value: string }) {
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
          }
        }}
      >
        {value || ''}
      </ReactMarkdown>
    </div>
  )
}
