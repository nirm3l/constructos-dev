import React from 'react'

type MermaidApi = typeof import('mermaid')['default']
type MermaidThemeMode = 'light' | 'dark'

let mermaidApiPromise: Promise<MermaidApi> | null = null
let mermaidRenderSequence = 0
let mermaidInitializedTheme: MermaidThemeMode | null = null
const mermaidSvgCache = new Map<string, string>()
const MERMAID_RENDER_DEBOUNCE_MS = 220
const MERMAID_STYLE_VERSION = 'terminal-green-v2'

function getMermaidApi(): Promise<MermaidApi> {
  if (mermaidApiPromise) return mermaidApiPromise
  mermaidApiPromise = import('mermaid').then((mod) => mod.default)
  return mermaidApiPromise
}

function isDarkThemeEnabled(): boolean {
  if (typeof document === 'undefined') return false
  return document.documentElement.getAttribute('data-theme') === 'dark'
}

function getMermaidThemeMode(): MermaidThemeMode {
  return isDarkThemeEnabled() ? 'dark' : 'light'
}

function getMermaidThemeVariables(mode: MermaidThemeMode): Record<string, string> {
  if (mode === 'dark') {
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

function getMermaidThemeCss(mode: MermaidThemeMode): string {
  if (mode === 'dark') {
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

function buildCacheKey(source: string, theme: MermaidThemeMode): string {
  return `${MERMAID_STYLE_VERSION}\n${theme}\n${source}`
}

function MermaidDiagramComponent({ code }: { code: string }) {
  const source = React.useMemo(() => String(code || '').trim(), [code])
  const theme = getMermaidThemeMode()
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
        const renderId = `mermaid-diagram-${mermaidRenderSequence}`
        const rendered = await mermaid.render(renderId, source)
        if (cancelled) return
        mermaidSvgCache.set(cacheKey, rendered.svg)
        setSvg(rendered.svg)
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
