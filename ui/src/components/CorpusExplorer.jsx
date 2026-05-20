import { useState, useEffect, useCallback, useRef } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

async function apiGet(path) {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

const TABS = ['catalog', 'overview', 'graph', 'knowledge-graph']

export default function CorpusExplorer() {
  const [tab, setTab] = useState('overview')
  const [overview, setOverview] = useState(null)
  const [papers, setPapers] = useState([])
  const [graphData, setGraphData] = useState(null)
  const [kgData, setKgData] = useState(null)
  const [selectedPaper, setSelectedPaper] = useState(null)
  const [search, setSearch] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [page, setPage] = useState(1)
  const [totalPapers, setTotalPapers] = useState(0)
  const [loading, setLoading] = useState(false)
  const [kgEntity, setKgEntity] = useState('')
  const graphCanvasRef = useRef(null)

  // Fetch overview
  useEffect(() => {
    apiGet('/api/papers/corpus/overview')
      .then(setOverview)
      .catch(() => setOverview(null))
  }, [])

  // Fetch papers catalog
  const fetchPapers = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ page: String(page), limit: '20' })
      if (search) params.set('search', search)
      if (categoryFilter) params.set('category', categoryFilter)
      const data = await apiGet(`/api/papers?${params}`)
      setPapers(data.papers || [])
      setTotalPapers(data.total || 0)
    } catch { setPapers([]) }
    setLoading(false)
  }, [page, search, categoryFilter])

  useEffect(() => { fetchPapers() }, [fetchPapers])

  // Fetch graph data
  useEffect(() => {
    if (tab !== 'graph') return
    apiGet('/api/papers/corpus/graph?sample=200&lod=1')
      .then(setGraphData)
      .catch(() => setGraphData(null))
  }, [tab])

  // Fetch KG data
  const fetchKG = useCallback(async () => {
    setLoading(true)
    try {
      const params = kgEntity ? `?entity=${encodeURIComponent(kgEntity)}` : ''
      const data = await apiGet(`/api/papers/corpus/kg${params}`)
      setKgData(data)
    } catch { setKgData(null) }
    setLoading(false)
  }, [kgEntity])

  useEffect(() => { if (tab === 'knowledge-graph') fetchKG() }, [tab, fetchKG])

  // Fetch paper detail
  const openPaper = async (arxivId) => {
    try {
      const data = await apiGet(`/api/papers/${arxivId}`)
      setSelectedPaper(data)
    } catch { setSelectedPaper(null) }
  }

  // Simple canvas graph renderer
  useEffect(() => {
    if (tab !== 'graph' || !graphData || !graphCanvasRef.current || graphData.nodes.length === 0) return
    const canvas = graphCanvasRef.current
    const ctx = canvas.getContext('2d')
    const W = canvas.width = canvas.offsetWidth
    const H = canvas.height = canvas.offsetHeight
    ctx.clearRect(0, 0, W, H)

    // Circular layout for nodes
    const cx = W / 2, cy = H / 2, R = Math.min(W, H) * 0.38
    const nodeMap = {}
    graphData.nodes.forEach((n, i) => {
      const angle = (2 * Math.PI * i) / graphData.nodes.length - Math.PI / 2
      n.x = cx + R * Math.cos(angle)
      n.y = cy + R * Math.sin(angle)
      nodeMap[n.id] = n
    })

    // Color by cluster
    const clusters = [...new Set(graphData.nodes.map(n => n.cluster || 'default'))]
    const clusterColors = {}
    const palette = ['#6366f1', '#06b6d4', '#f59e0b', '#ef4444', '#10b981', '#8b5cf6', '#ec4899', '#14b8a6']
    clusters.forEach((c, i) => { clusterColors[c] = palette[i % palette.length] })

    // Draw edges
    ctx.strokeStyle = 'rgba(100,100,140,0.12)'
    ctx.lineWidth = 0.5
    graphData.edges.forEach(e => {
      const s = nodeMap[e.source], t = nodeMap[e.target]
      if (!s || !t) return
      ctx.beginPath()
      ctx.moveTo(s.x, s.y)
      ctx.lineTo(t.x, t.y)
      ctx.stroke()
    })

    // Draw nodes
    graphData.nodes.forEach(n => {
      ctx.fillStyle = clusterColors[n.cluster || 'default'] || '#6366f1'
      ctx.beginPath()
      ctx.arc(n.x, n.y, 3, 0, 2 * Math.PI)
      ctx.fill()
    })

    // Legend
    ctx.font = '11px system-ui'
    clusters.slice(0, 8).forEach((c, i) => {
      ctx.fillStyle = clusterColors[c]
      ctx.fillRect(10, 10 + i * 18, 10, 10)
      ctx.fillStyle = '#a1a1aa'
      ctx.fillText(c.length > 30 ? c.slice(0, 30) + '...' : c, 26, 19 + i * 18)
    })
  }, [tab, graphData])

  if (selectedPaper) {
    return <PaperDetail paper={selectedPaper} onBack={() => setSelectedPaper(null)} />
  }

  return (
    <div className="corpus-explorer">
      <div className="corpus-header">
        <h2>Research Corpus Explorer</h2>
        {overview && (
          <div className="corpus-stats">
            <span className="stat-chip">{overview.total_papers?.toLocaleString()} papers</span>
            <span className="stat-chip">{overview.categories?.length} categories</span>
            <span className="stat-chip">{overview.source} source</span>
          </div>
        )}
      </div>

      <div className="corpus-tabs">
        {TABS.map(t => (
          <button key={t} className={`corpus-tab${tab === t ? ' active' : ''}`} onClick={() => setTab(t)}>
            {t.replace('-', ' ').replace(/\b\w/g, c => c.toUpperCase())}
          </button>
        ))}
      </div>

      {tab === 'overview' && <OverviewTab overview={overview} />}
      {tab === 'catalog' && (
        <CatalogTab
          papers={papers} total={totalPapers} page={page} loading={loading}
          search={search} setSearch={setSearch}
          categoryFilter={categoryFilter} setCategoryFilter={setCategoryFilter}
          setPage={setPage} openPaper={openPaper}
          categories={overview?.categories || []}
        />
      )}
      {tab === 'graph' && (
        <div className="corpus-graph-container">
          {graphData?.status === 'empty' ? (
            <div className="corpus-empty">No papers in corpus yet.</div>
          ) : (
            <>
              {graphData?.note && <div className="corpus-note">{graphData.note}</div>}
              <canvas ref={graphCanvasRef} className="corpus-canvas" style={{ width: '100%', height: '500px' }} />
              <div className="corpus-graph-stats">
                {graphData && (
                  <span className="stat-chip">{graphData.sampled} nodes / {graphData.edges?.length} edges (sampled from {graphData.total_papers?.toLocaleString()})</span>
                )}
              </div>
            </>
          )}
        </div>
      )}
      {tab === 'knowledge-graph' && (
        <div className="corpus-kg-container">
          <div className="kg-controls">
            <input
              type="text" placeholder="Filter by entity (author, topic, category)..."
              value={kgEntity} onChange={e => setKgEntity(e.target.value)}
              className="kg-search"
            />
          </div>
          {kgData?.status === 'empty' ? (
            <div className="corpus-empty">No papers in corpus yet.</div>
          ) : (
            <>
              {kgData?.note && <div className="corpus-note">{kgData.note}</div>}
              <KGViewer data={kgData} openPaper={openPaper} />
            </>
          )}
        </div>
      )}
    </div>
  )
}

function OverviewTab({ overview }) {
  if (!overview) return <div className="corpus-loading">Loading overview...</div>

  const maxCatCount = Math.max(...(overview.categories || []).map(c => c.count), 1)
  const maxYearCount = Math.max(...(overview.year_distribution || []).map(y => y.count), 1)

  return (
    <div className="corpus-overview">
      <div className="overview-section">
        <h3>Category Distribution</h3>
        <div className="bar-chart">
          {(overview.categories || []).map(c => (
            <div key={c.name} className="bar-row">
              <span className="bar-label" title={c.name}>{c.name}</span>
              <div className="bar-track">
                <div className="bar-fill" style={{ width: `${(c.count / maxCatCount) * 100}%` }} />
              </div>
              <span className="bar-count">{c.count.toLocaleString()}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="overview-section">
        <h3>Year Distribution</h3>
        <div className="year-chart">
          {(overview.year_distribution || []).map(y => (
            <div key={y.year} className="year-bar-row">
              <span className="year-label">{y.year}</span>
              <div className="year-track">
                <div className="year-fill" style={{ width: `${(y.count / maxYearCount) * 100}%` }} />
              </div>
              <span className="year-count">{y.count.toLocaleString()}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="overview-summary">
        <h3>Library Summary</h3>
        <div className="summary-grid">
          <div className="summary-card">
            <div className="summary-value">{overview.total_papers?.toLocaleString()}</div>
            <div className="summary-label">Total Papers</div>
          </div>
          <div className="summary-card">
            <div className="summary-value">{overview.categories?.length}</div>
            <div className="summary-label">Categories</div>
          </div>
          <div className="summary-card">
            <div className="summary-value">{overview.year_distribution?.length}</div>
            <div className="summary-label">Year Span</div>
          </div>
        </div>
      </div>
    </div>
  )
}

function CatalogTab({ papers, total, page, loading, search, setSearch, categoryFilter, setCategoryFilter, setPage, openPaper, categories }) {
  const totalPages = Math.ceil(total / 20)
  return (
    <div className="corpus-catalog">
      <div className="catalog-controls">
        <input
          type="text" placeholder="Search papers..." value={search}
          onChange={e => { setSearch(e.target.value); setPage(1) }}
          className="catalog-search"
        />
        <select value={categoryFilter} onChange={e => { setCategoryFilter(e.target.value); setPage(1) }} className="catalog-filter">
          <option value="">All Categories</option>
          {categories.map(c => <option key={c.name} value={c.name}>{c.name} ({c.count})</option>)}
        </select>
      </div>

      {loading ? <div className="corpus-loading">Loading...</div> : (
        <>
          <div className="catalog-results-info">{total.toLocaleString()} papers found</div>
          <div className="paper-list">
            {papers.map(p => (
              <div key={p.arxiv_id} className="paper-card" onClick={() => openPaper(p.arxiv_id)}>
                <div className="paper-title">{p.title || p.arxiv_id}</div>
                <div className="paper-meta">
                  <span className="paper-id">{p.arxiv_id}</span>
                  {p.primary_category && <span className="paper-cat">{p.primary_category}</span>}
                  {p.published && <span className="paper-year">{p.published?.slice(0, 4)}</span>}
                  {p.cluster_id && <span className="paper-cluster">Cluster: {p.cluster_id}</span>}
                </div>
                <div className="paper-abstract">{(p.abstract || '').slice(0, 200)}{(p.abstract || '').length > 200 ? '...' : ''}</div>
                {p.citing_strategies?.length > 0 && (
                  <div className="paper-strategies">
                    Used by {p.citing_strategies.length} strateg{p.citing_strategies.length === 1 ? 'y' : 'ies'}
                  </div>
                )}
              </div>
            ))}
          </div>
          {totalPages > 1 && (
            <div className="catalog-pagination">
              <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Previous</button>
              <span>Page {page} of {totalPages}</span>
              <button disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>Next</button>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function KGViewer({ data, openPaper }) {
  if (!data || !data.entities) return null
  const entityTypes = {}
  data.entities.forEach(e => {
    if (!entityTypes[e.type]) entityTypes[e.type] = []
    entityTypes[e.type].push(e)
  })
  return (
    <div className="kg-viewer">
      <div className="kg-stats">
        <span className="stat-chip">{data.entities?.length} entities</span>
        <span className="stat-chip">{data.relations?.length} relations</span>
        <span className="stat-chip">{data.filtered} papers matched</span>
      </div>
      {Object.entries(entityTypes).map(([type, entities]) => (
        <div key={type} className="kg-section">
          <h4>{type.charAt(0).toUpperCase() + type.slice(1)}s ({entities.length})</h4>
          <div className="kg-entity-list">
            {entities.slice(0, 50).map(e => (
              <span key={e.id} className={`kg-entity kg-entity-${e.type}`}>
                {type === 'paper' ? (
                  <a onClick={() => openPaper(e.id)} title={e.label}>{e.label?.slice(0, 60)}</a>
                ) : (
                  <span>{e.label}</span>
                )}
              </span>
            ))}
            {entities.length > 50 && <span className="kg-more">+{entities.length - 50} more</span>}
          </div>
        </div>
      ))}
    </div>
  )
}

function PaperDetail({ paper, onBack }) {
  return (
    <div className="corpus-explorer">
      <button className="back-btn" onClick={onBack}>Back to Explorer</button>
      <div className="paper-detail">
        <h2>{paper.title || paper.arxiv_id}</h2>
        <div className="paper-detail-meta">
          <span className="paper-id">{paper.arxiv_id}</span>
          {paper.primary_category && <span className="paper-cat">{paper.primary_category}</span>}
          {paper.published && <span className="paper-year">{paper.published}</span>}
          {paper.cluster_id && <span className="paper-cluster">Cluster: {paper.cluster_id}</span>}
          {paper.topic_label && <span className="paper-cluster">Topic: {paper.topic_label}</span>}
        </div>
        {paper.pdf_url && (
          <a href={paper.pdf_url} target="_blank" rel="noopener noreferrer" className="arxiv-link">
            View on arXiv
          </a>
        )}
        {paper.authors?.length > 0 && (
          <div className="paper-authors">
            <h4>Authors</h4>
            <p>{paper.authors.join(', ')}</p>
          </div>
        )}
        {paper.abstract && (
          <div className="paper-abstract-full">
            <h4>Abstract</h4>
            <p>{paper.abstract}</p>
          </div>
        )}
        {paper.citing_strategies?.length > 0 && (
          <div className="paper-provenance">
            <h4>Citing Strategies</h4>
            {paper.citing_strategies.map(s => (
              <div key={s.name || s.id} className="provenance-link">
                <span className="strategy-name">{s.name || s.id}</span>
                {s.source_papers?.length > 0 && (
                  <span className="source-refs">Sources: {s.source_papers.join(', ')}</span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
