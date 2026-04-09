import React from 'react'

type MermaidApi = typeof import('mermaid')['default']
type MermaidThemeBrand = 'constructos' | 'symphony'
type MermaidThemeMode = 'light' | 'dark'
type MermaidThemeKey = `${MermaidThemeBrand}-${MermaidThemeMode}`

let mermaidApiPromise: Promise<MermaidApi> | null = null
let mermaidRenderSequence = 0
let mermaidInitializedTheme: MermaidThemeKey | null = null
const mermaidSvgCache = new Map<string, string>()
const MERMAID_RENDER_DEBOUNCE_MS = 220
const MERMAID_STYLE_VERSION = 'theme-brand-mode-v3'

function normalizeLabelText(label: string): string {
  return label.replace(/\\n/g, '<br/>').replace(/"/g, '&quot;').trim()
}

function quoteSquareLabelsWithLineBreaks(source: string): string {
  return source.replace(/\b([A-Za-z][\w:-]*)\[([^\]\n]+)\]/g, (full, nodeId: string, rawLabel: string) => {
    const label = String(rawLabel || '')
    if (!label) return full
    if (label.startsWith('"') && label.endsWith('"')) return full
    if (!/\\n|<br\s*\/?\s*>/i.test(label)) return full
    return `${nodeId}["${normalizeLabelText(label)}"]`
  })
}

function fixHalfOpenSlantedNodes(source: string): string {
  return source.replace(/\[\/([^\]\n]*?)\](?=\s*(?:--|==|-\.|$))/g, (_full, label: string) => {
    const trimmed = String(label || '').trim()
    if (!trimmed) return '[//]'
    if (trimmed.endsWith('/')) return `[/${trimmed}]`
    return `[/${trimmed}/]`
  })
}

function normalizeLineBreakNodes(source: string): string {
  let normalized = source
  normalized = normalized.replace(/\b([A-Za-z][\w:-]*)\(([^\)\n]*?(?:\\n|<br\s*\/?\s*>)[^\)\n]*?)\)/gi, (_full, nodeId: string, rawLabel: string) => {
    return `${nodeId}["${normalizeLabelText(rawLabel)}"]`
  })
  normalized = normalized.replace(/\b([A-Za-z][\w:-]*)\{([^\}\n]*?(?:\\n|<br\s*\/?\s*>)[^\}\n]*?)\}/gi, (_full, nodeId: string, rawLabel: string) => {
    return `${nodeId}["${normalizeLabelText(rawLabel)}"]`
  })
  return normalized
}

function quoteSquareLabelsWithPunctuation(source: string): string {
  return source.replace(/\b([A-Za-z][\w:-]*)\[([^\]\n]+)\]/g, (full, nodeId: string, rawLabel: string) => {
    const label = String(rawLabel || '')
    if (!label) return full
    if (label.startsWith('"') && label.endsWith('"')) return full
    if (!/[()]/.test(label)) return full
    return `${nodeId}["${normalizeLabelText(label)}"]`
  })
}

function buildMermaidCandidates(source: string): string[] {
  const candidates: string[] = []
  const add = (value: string) => {
    const trimmed = value.trim()
    if (!trimmed || candidates.includes(trimmed)) return
    candidates.push(trimmed)
  }

  add(source)

  const withLineBreaks = source.replace(/\\n/g, '<br/>')
  add(withLineBreaks)

  const fixedSlanted = fixHalfOpenSlantedNodes(withLineBreaks)
  add(fixedSlanted)

  const quotedBreaks = quoteSquareLabelsWithLineBreaks(fixedSlanted)
  add(quotedBreaks)

  const normalizedBreakShapes = normalizeLineBreakNodes(quotedBreaks)
  add(normalizedBreakShapes)

  const quotedPunctuation = quoteSquareLabelsWithPunctuation(normalizedBreakShapes)
  add(quotedPunctuation)

  const withHtmlBr = quotedPunctuation.replace(/<br\s*\/>/gi, '<br>')
  add(withHtmlBr)

  return candidates
}

function getMermaidApi(): Promise<MermaidApi> {
  if (mermaidApiPromise) return mermaidApiPromise
  mermaidApiPromise = import('mermaid').then((mod) => mod.default)
  return mermaidApiPromise
}

function getThemeSnapshot(): { brand: MermaidThemeBrand; mode: MermaidThemeMode; key: MermaidThemeKey } {
  if (typeof document === 'undefined') {
    return { brand: 'symphony', mode: 'light', key: 'symphony-light' }
  }
  const root = document.documentElement
  const rawBrand = String(root.getAttribute('data-theme-brand') || '').trim().toLowerCase()
  const rawMode = String(root.getAttribute('data-theme') || '').trim().toLowerCase()
  const brand: MermaidThemeBrand = rawBrand === 'constructos' ? 'constructos' : 'symphony'
  const mode: MermaidThemeMode = rawMode === 'dark' ? 'dark' : 'light'
  return { brand, mode, key: `${brand}-${mode}` }
}

function getMermaidThemeVariables(theme: MermaidThemeKey): Record<string, string> {
  if (theme === 'constructos-dark') {
    return {
      fontFamily: '"JetBrains Mono", "Fira Code", "SFMono-Regular", Menlo, Monaco, Consolas, monospace',
      background: 'rgba(0, 0, 0, 0)',
      primaryColor: '#13241a',
      primaryBorderColor: '#4db975',
      primaryTextColor: '#73ff9d',
      secondaryColor: '#0f1b14',
      tertiaryColor: '#16281d',
      lineColor: '#4db975',
      textColor: '#73ff9d',
      mainBkg: '#13241a',
      secondBkg: '#0f1b14',
      tertiaryBkg: '#16281d',
      clusterBkg: '#0f1b14',
      clusterBorder: '#4db975',
      edgeLabelBackground: '#0f1b14',
      titleColor: '#73ff9d',
      actorBkg: '#13241a',
      actorBorder: '#4db975',
      labelBoxBkgColor: '#13241a',
      labelBoxBorderColor: '#4db975',
      labelTextColor: '#73ff9d',
      nodeBkg: '#13241a',
      nodeBorder: '#4db975',
    }
  }
  if (theme === 'constructos-light') {
    return {
      fontFamily: '"JetBrains Mono", "Fira Code", "SFMono-Regular", Menlo, Monaco, Consolas, monospace',
      background: 'rgba(0, 0, 0, 0)',
      primaryColor: '#d9f8e4',
      primaryBorderColor: '#2f8f4d',
      primaryTextColor: '#1f6b39',
      secondaryColor: '#c5f0d5',
      tertiaryColor: '#e8fff0',
      lineColor: '#2f8f4d',
      textColor: '#1f6b39',
      mainBkg: '#d9f8e4',
      secondBkg: '#c5f0d5',
      tertiaryBkg: '#e8fff0',
      clusterBkg: '#e7f8ee',
      clusterBorder: '#2f8f4d',
      edgeLabelBackground: '#eaf7ef',
      titleColor: '#1f6b39',
      actorBkg: '#d9f8e4',
      actorBorder: '#2f8f4d',
      labelBoxBkgColor: '#d9f8e4',
      labelBoxBorderColor: '#2f8f4d',
      labelTextColor: '#1f6b39',
      nodeBkg: '#d9f8e4',
      nodeBorder: '#2f8f4d',
    }
  }
  if (theme === 'symphony-dark') {
    return {
      fontFamily: '"Avenir Next", "Trebuchet MS", "Gill Sans", sans-serif',
      background: 'rgba(0, 0, 0, 0)',
      primaryColor: '#232734',
      primaryBorderColor: '#8ea9ff',
      primaryTextColor: '#ffffff',
      secondaryColor: '#1b1f2a',
      tertiaryColor: '#2a3140',
      lineColor: '#91afea',
      textColor: '#ffffff',
      mainBkg: '#232734',
      secondBkg: '#1b1f2a',
      tertiaryBkg: '#2a3140',
      clusterBkg: '#1b1f2a',
      clusterBorder: '#8ea9ff',
      edgeLabelBackground: '#1e2431',
      titleColor: '#ffffff',
      actorBkg: '#232734',
      actorBorder: '#8ea9ff',
      labelBoxBkgColor: '#232734',
      labelBoxBorderColor: '#8ea9ff',
      labelTextColor: '#ffffff',
      nodeBkg: '#232734',
      nodeBorder: '#8ea9ff',
    }
  }
  return {
    fontFamily: '"Avenir Next", "Trebuchet MS", "Gill Sans", sans-serif',
    background: 'rgba(0, 0, 0, 0)',
    primaryColor: '#edf1ff',
    primaryBorderColor: '#8091de',
    primaryTextColor: '#222453',
    secondaryColor: '#e7ebff',
    tertiaryColor: '#f8f9ff',
    lineColor: '#7d92e8',
    textColor: '#222453',
    mainBkg: '#edf1ff',
    secondBkg: '#e7ebff',
    tertiaryBkg: '#f8f9ff',
    clusterBkg: '#eef2ff',
    clusterBorder: '#8091de',
    edgeLabelBackground: '#f3f5ff',
    titleColor: '#222453',
    actorBkg: '#edf1ff',
    actorBorder: '#8091de',
    labelBoxBkgColor: '#edf1ff',
    labelBoxBorderColor: '#8091de',
    labelTextColor: '#222453',
    nodeBkg: '#edf1ff',
    nodeBorder: '#8091de',
  }
}

function getMermaidThemeCss(theme: MermaidThemeKey): string {
  if (theme === 'constructos-dark') {
    return `
      svg {
        background-color: transparent !important;
      }
      rect.background, .background {
        fill: transparent !important;
      }
      .node rect, .node circle, .node ellipse, .node polygon, .node path {
        fill: #13241a !important;
        stroke: #4db975 !important;
        stroke-width: 1.6px !important;
      }
      .edgePath .path {
        stroke: #4db975 !important;
        stroke-width: 1.6px !important;
      }
      .edgeLabel rect {
        fill: #0f1b14 !important;
        opacity: 0.98 !important;
      }
      .cluster rect {
        fill: #0f1b14 !important;
        stroke: #4db975 !important;
      }
      .label, .label text, .nodeLabel, .edgeLabel text, .cluster text, text {
        fill: #73ff9d !important;
      }
      .marker, marker path {
        fill: #4db975 !important;
        stroke: #4db975 !important;
      }
    `
  }
  if (theme === 'constructos-light') {
    return `
      svg {
        background-color: transparent !important;
      }
      rect.background, .background {
        fill: transparent !important;
      }
      .node rect, .node circle, .node ellipse, .node polygon, .node path {
        fill: #d9f8e4 !important;
        stroke: #2f8f4d !important;
        stroke-width: 1.5px !important;
      }
      .edgePath .path {
        stroke: #2f8f4d !important;
        stroke-width: 1.5px !important;
      }
      .edgeLabel rect {
        fill: #eaf7ef !important;
        opacity: 0.98 !important;
      }
      .cluster rect {
        fill: #e7f8ee !important;
        stroke: #2f8f4d !important;
      }
      .label, .label text, .nodeLabel, .edgeLabel text, .cluster text, text {
        fill: #1f6b39 !important;
      }
      .marker, marker path {
        fill: #2f8f4d !important;
        stroke: #2f8f4d !important;
      }
    `
  }
  if (theme === 'symphony-dark') {
    return `
      svg {
        background-color: transparent !important;
      }
      rect.background, .background {
        fill: transparent !important;
      }
      .node rect, .node circle, .node ellipse, .node polygon, .node path {
        fill: #232734 !important;
        stroke: #8ea9ff !important;
        stroke-width: 1.6px !important;
      }
      .edgePath .path {
        stroke: #91afea !important;
        stroke-width: 1.6px !important;
      }
      .edgeLabel rect {
        fill: #1e2431 !important;
        opacity: 0.98 !important;
      }
      .cluster rect {
        fill: #1b1f2a !important;
        stroke: #8ea9ff !important;
      }
      .label, .label text, .nodeLabel, .edgeLabel text, .cluster text, text {
        fill: #ffffff !important;
      }
      .marker, marker path {
        fill: #91afea !important;
        stroke: #91afea !important;
      }
    `
  }
  return `
    svg {
      background-color: transparent !important;
    }
    rect.background, .background {
      fill: transparent !important;
    }
    .node rect, .node circle, .node ellipse, .node polygon, .node path {
      fill: #edf1ff !important;
      stroke: #8091de !important;
      stroke-width: 1.5px !important;
    }
    .edgePath .path {
      stroke: #7d92e8 !important;
      stroke-width: 1.5px !important;
    }
    .edgeLabel rect {
      fill: #f3f5ff !important;
      opacity: 0.98 !important;
    }
    .cluster rect {
      fill: #eef2ff !important;
      stroke: #8091de !important;
    }
    .label, .label text, .nodeLabel, .edgeLabel text, .cluster text, text {
      fill: #222453 !important;
    }
    .marker, marker path {
      fill: #7d92e8 !important;
      stroke: #7d92e8 !important;
    }
  `
}

function buildCacheKey(source: string, theme: MermaidThemeKey): string {
  return `${MERMAID_STYLE_VERSION}\n${theme}\n${source}`
}

function MermaidDiagramComponent({ code }: { code: string }) {
  const source = React.useMemo(() => String(code || '').trim(), [code])
  const [theme, setTheme] = React.useState<MermaidThemeKey>(() => getThemeSnapshot().key)

  React.useEffect(() => {
    if (typeof document === 'undefined') return () => {}
    const root = document.documentElement
    const syncTheme = () => {
      const next = getThemeSnapshot().key
      setTheme((prev) => (prev === next ? prev : next))
    }
    syncTheme()
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type !== 'attributes') continue
        const name = mutation.attributeName || ''
        if (name === 'data-theme' || name === 'data-theme-brand') {
          syncTheme()
          break
        }
      }
    })
    observer.observe(root, { attributes: true, attributeFilter: ['data-theme', 'data-theme-brand'] })
    return () => observer.disconnect()
  }, [])

  const cacheKey = source ? buildCacheKey(source, theme) : ''
  const [svg, setSvg] = React.useState(() => (cacheKey ? mermaidSvgCache.get(cacheKey) || '' : ''))
  const [error, setError] = React.useState<string | null>(null)
  const latestSvgRef = React.useRef('')

  React.useEffect(() => {
    latestSvgRef.current = svg
  }, [svg])

  React.useEffect(() => {
    let cancelled = false
    if (!source) {
      setSvg('')
      setError('Diagram source is empty.')
      return () => {
        cancelled = true
      }
    }
    setError(null)
    const cachedSvg = mermaidSvgCache.get(cacheKey)
    if (cachedSvg) {
      if (cachedSvg !== latestSvgRef.current) {
        setSvg(cachedSvg)
      }
      return () => {
        cancelled = true
      }
    }

    const render = async () => {
      try {
        const mermaid = await getMermaidApi()
        if (mermaidInitializedTheme !== theme) {
          mermaid.initialize({
            startOnLoad: false,
            securityLevel: 'strict',
            theme: 'base',
            themeVariables: getMermaidThemeVariables(theme),
            themeCSS: getMermaidThemeCss(theme),
          })
          mermaidInitializedTheme = theme
        }
        mermaidRenderSequence += 1
        const candidates = buildMermaidCandidates(source)
        let renderedSvg = ''
        let lastError: unknown = null
        for (let index = 0; index < candidates.length; index += 1) {
          const candidate = candidates[index]
          if (typeof candidate !== 'string' || !candidate) continue
          try {
            const renderId = `mermaid-diagram-${mermaidRenderSequence}-${index}`
            const rendered = await mermaid.render(renderId, candidate)
            renderedSvg = rendered.svg
            break
          } catch (candidateError) {
            lastError = candidateError
          }
        }
        if (!renderedSvg) {
          throw lastError || new Error('Failed to render Mermaid diagram.')
        }
        if (cancelled) return
        mermaidSvgCache.set(cacheKey, renderedSvg)
        setSvg(renderedSvg)
        setError(null)
      } catch (err) {
        if (cancelled) return
        const message = err instanceof Error ? err.message : 'Failed to render Mermaid diagram.'
        if (!latestSvgRef.current) {
          setError(message)
        }
      }
    }
    const timeoutId = globalThis.setTimeout(() => {
      void render()
    }, MERMAID_RENDER_DEBOUNCE_MS)

    return () => {
      cancelled = true
      globalThis.clearTimeout(timeoutId)
    }
  }, [cacheKey, source, theme])

  if (error) {
    return (
      <div className="mermaid-diagram-shell">
        <div className="mermaid-diagram-status">Mermaid render failed: {error}</div>
        <pre className="mermaid-diagram-fallback"><code>{code}</code></pre>
      </div>
    )
  }

  if (!svg) {
    return (
      <div className="mermaid-diagram-shell">
        <div className="mermaid-diagram-status">Rendering Mermaid diagram...</div>
      </div>
    )
  }

  return (
    <div className="mermaid-diagram-shell">
      <div className="mermaid-diagram" dangerouslySetInnerHTML={{ __html: svg }} />
    </div>
  )
}

export const MermaidDiagram = React.memo(MermaidDiagramComponent)
