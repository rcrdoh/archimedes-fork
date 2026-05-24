import { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import ForceGraph2D from 'react-force-graph-2d'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

// Cluster palette — high-contrast, colorblind-friendly-ish
const CLUSTER_PALETTE = [
  '#6366f1', '#06b6d4', '#f59e0b', '#ef4444', '#10b981',
  '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#84cc16',
  '#e879f9', '#22d3ee', '#fb923c', '#a3e635', '#f472b6',
]

/**
 * SPECTER2 similarity scatter plot.
 *
 * Fetches from ``/api/corpus/graph`` (honest KB-pipeline endpoint).
 * Response shape: ``{points: [{arxiv_id, x, y, cluster_id}], topics, cluster_count, point_count}``.
 * Each point is a paper projected into 2D via UMAP. Colored by cluster_id.
 * Topics provide human-readable labels per cluster.
 *
 * Returns 503 when no KB artifact exists yet — renders explicit empty state.
 */
export default function CorpusGraph() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [hoverNode, setHoverNode] = useState(null)
  const containerRef = useRef(null)
  const fgRef = useRef(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetch(`${API_BASE}/api/corpus/graph`)
      .then(r => {
        if (r.status === 503) throw new Error('KB pipeline still running — first artifact pending')
        if (!r.ok) throw new Error(r.statusText)
        return r.json()
      })
      .then(d => { if (!cancelled) setData(d) })
      .catch(e => { if (!cancelled) setError(e.message || 'Failed to load graph') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  // Build cluster → color map from the topics dict or cluster_id values
  const clusterColorMap = useMemo(() => {
    if (!data?.points) return {}
    const clusters = [...new Set(data.points.map(p => p.cluster_id ?? 'default'))]
    const map = {}
    clusters.forEach((c, i) => { map[c] = CLUSTER_PALETTE[i % CLUSTER_PALETTE.length] })
    return map
  }, [data])

  // Transform scatter points into react-force-graph-2d node/link format
  const graphData = useMemo(() => {
    if (!data?.points) return { nodes: [], links: [] }
    return {
      nodes: data.points.map(p => ({
        id: p.arxiv_id,
        label: p.arxiv_id,
        cluster: p.cluster_id ?? 'default',
        x: p.x,
        y: p.y,
        val: 2,
        color: clusterColorMap[p.cluster_id ?? 'default'] || CLUSTER_PALETTE[0],
      })),
      // No edges in UMAP scatter — similarity is encoded in spatial proximity
      links: [],
    }
  }, [data, clusterColorMap])

  // Custom node painting
  const nodeCanvasObject = useCallback((node, ctx, globalScale) => {
    const radius = Math.max(2, node.val * 1.5)
    ctx.fillStyle = node.color
    ctx.beginPath()
    ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI)
    ctx.fill()

    // Label only when zoomed in enough
    if (globalScale > 1.5) {
      ctx.fillStyle = '#d4d4d8'
      ctx.font = `${Math.max(8, 10 / globalScale)}px system-ui`
      ctx.textAlign = 'center'
      ctx.fillText(node.label.slice(0, 40), node.x, node.y + radius + 10 / globalScale)
    }
  }, [])

  const nodePointerAreaPaint = useCallback((node, color, ctx) => {
    const radius = Math.max(4, node.val * 2)
    ctx.fillStyle = color
    ctx.beginPath()
    ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI)
    ctx.fill()
  }, [])

  // --- Loading / error / empty states ---

  if (loading) {
    return (
      <div className="corpus-graph-loading" style={{ padding: 40, textAlign: 'center' }}>
        <div className="caption">Loading similarity graph…</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="corpus-graph-error" style={{ padding: 24 }}>
        <div className="info-box warning">
          {error.includes('503') || error.includes('KB pipeline')
            ? 'KB pipeline still running — first artifact pending. The graph will populate once embeddings are computed.'
            : `Graph unavailable: ${error}`}
        </div>
      </div>
    )
  }

  if (!data || !data.points || data.points.length === 0) {
    return (
      <div className="corpus-graph-empty" style={{ padding: 40, textAlign: 'center' }}>
        <div className="caption">No papers in corpus yet.</div>
      </div>
    )
  }

  // Legend
  const legendClusters = Object.entries(clusterColorMap).slice(0, 12)

  return (
    <div ref={containerRef} className="corpus-graph-wrapper" style={{ position: 'relative' }}>
      <div className="corpus-graph-stats flex gap-2 flex-wrap mb-2" style={{ padding: '0 12px' }}>
        <span className="tag tag-muted">{data.point_count ?? data.points.length} papers</span>
        <span className="tag tag-muted">{data.cluster_count ?? Object.keys(data.topics || {}).length} clusters</span>
      </div>

      {/* Force graph */}
      <ForceGraph2D
        ref={fgRef}
        graphData={graphData}
        nodeCanvasObject={nodeCanvasObject}
        nodePointerAreaPaint={nodePointerAreaPaint}
        onNodeHover={node => setHoverNode(node)}
        linkColor={() => 'rgba(100,100,140,0.08)'}
        linkWidth={0.5}
        backgroundColor="transparent"
        nodeRelSize={1}
        warmupTicks={50}
        cooldownTicks={100}
        width={containerRef.current?.offsetWidth || 800}
        height={500}
      />

      {/* Legend — cluster IDs + topic labels when available */}
      <div className="corpus-graph-legend" style={{
        position: 'absolute', top: 48, right: 12,
        background: 'rgba(10,10,16,0.85)', borderRadius: 8, padding: '10px 14px',
        border: '1px solid var(--glass-border)', fontSize: '0.78rem', maxWidth: 200,
      }}>
        <div className="caption mb-1 uppercase tracking-wider" style={{ color: 'var(--text-4)' }}>Clusters</div>
        {legendClusters.map(([cluster, color]) => (
          <div key={cluster} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
            <span style={{ width: 10, height: 10, borderRadius: '50%', background: color, flexShrink: 0 }} />
            <span style={{ color: 'var(--text-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {data.topics?.[cluster] || `Cluster ${cluster}`}
            </span>
          </div>
        ))}
      </div>

      {/* Hover tooltip */}
      {hoverNode && (
        <div className="corpus-graph-tooltip" style={{
          position: 'absolute', bottom: 16, left: 12,
          background: 'rgba(10,10,16,0.92)', borderRadius: 8, padding: '10px 14px',
          border: '1px solid var(--glass-border)', maxWidth: 360, pointerEvents: 'none',
        }}>
          <div className="mono caption" style={{ color: 'var(--text-4)', marginBottom: 4 }}>{hoverNode.id}</div>
          <div className="body" style={{ color: 'var(--text-1)', lineHeight: 1.4 }}>Paper {hoverNode.id}</div>
          {hoverNode.cluster != null && (
            <div className="caption mt-1" style={{ color: clusterColorMap[hoverNode.cluster] }}>
              Cluster: {data.topics?.[hoverNode.cluster] || hoverNode.cluster}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
