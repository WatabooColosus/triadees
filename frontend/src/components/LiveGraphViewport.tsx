import { useEffect, useMemo, useRef, useState } from 'react'

export type GraphNode3D = {
  node_id: string
  kind: string
  label: string
  state: string
  color: string
  metadata: Record<string, any>
}

export type GraphEdge3D = {
  source: string
  target: string
  relation: string
  evidence: string
}

type Point3 = { x: number; y: number; z: number }
type ScreenPoint = Point3 & { sx: number; sy: number; depth: number; scale: number }
type Camera = { yaw: number; pitch: number; zoom: number; panX: number; panY: number }

const DEFAULT_CAMERA: Camera = { yaw: -0.35, pitch: 0.2, zoom: 1, panX: 0, panY: 0 }

export function LiveGraphViewport({
  nodes, edges, selected, hot, onSelect,
}: {
  nodes: GraphNode3D[]
  edges: GraphEdge3D[]
  selected: string | null
  hot: Set<string>
  onSelect: (nodeId: string) => void
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const projectedRef = useRef<Map<string, ScreenPoint>>(new Map())
  const dragRef = useRef<{ x: number; y: number; button: number; camera: Camera } | null>(null)
  const [camera, setCamera] = useState<Camera>(DEFAULT_CAMERA)
  const [hovered, setHovered] = useState<string | null>(null)
  const positions = useMemo(() => layout3d(nodes), [nodes])
  const nodeIds = useMemo(() => new Set(nodes.map(node => node.node_id)), [nodes])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    function draw() {
      if (!canvas) return
      const rect = canvas.getBoundingClientRect()
      const dpr = Math.max(1, Math.min(window.devicePixelRatio || 1, 2))
      const width = Math.max(1, rect.width)
      const height = Math.max(1, rect.height)
      const pixelWidth = Math.round(width * dpr)
      const pixelHeight = Math.round(height * dpr)
      if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
        canvas.width = pixelWidth
        canvas.height = pixelHeight
      }
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, width, height)

      const projected = projectAll(positions, camera, width, height)
      projectedRef.current = projected

      const edgeQueue = edges
        .map(edge => ({ edge, a: projected.get(edge.source), b: projected.get(edge.target) }))
        .filter(item => item.a && item.b) as { edge: GraphEdge3D; a: ScreenPoint; b: ScreenPoint }[]
      edgeQueue.sort((a, b) => (a.a.depth + a.b.depth) - (b.a.depth + b.b.depth))

      for (const item of edgeQueue) {
        const active = item.edge.source === selected || item.edge.target === selected ||
          hot.has(item.edge.source) || hot.has(item.edge.target)
        ctx.beginPath()
        ctx.moveTo(item.a.sx, item.a.sy)
        ctx.lineTo(item.b.sx, item.b.sy)
        ctx.strokeStyle = active ? 'rgba(88,166,255,.92)' : 'rgba(110,118,129,.22)'
        ctx.lineWidth = active ? 1.7 : 0.55
        ctx.stroke()
      }

      const nodeQueue = nodes
        .map(node => ({ node, p: projected.get(node.node_id) }))
        .filter(item => item.p) as { node: GraphNode3D; p: ScreenPoint }[]
      nodeQueue.sort((a, b) => a.p.depth - b.p.depth)

      for (const item of nodeQueue) {
        const isHot = hot.has(item.node.node_id)
        const isSelected = selected === item.node.node_id
        const isHovered = hovered === item.node.node_id
        const base = Math.max(2.3, Math.min(11, 4.1 * item.p.scale))
        const radius = base * (isHot ? 1.9 : isSelected ? 1.55 : isHovered ? 1.25 : 1)

        if (isHot || isSelected) {
          const glow = ctx.createRadialGradient(item.p.sx, item.p.sy, 0, item.p.sx, item.p.sy, radius * 3.3)
          glow.addColorStop(0, isHot ? 'rgba(255,255,255,.48)' : 'rgba(88,166,255,.42)')
          glow.addColorStop(1, 'rgba(0,0,0,0)')
          ctx.beginPath()
          ctx.arc(item.p.sx, item.p.sy, radius * 3.3, 0, Math.PI * 2)
          ctx.fillStyle = glow
          ctx.fill()
        }

        ctx.beginPath()
        ctx.arc(item.p.sx, item.p.sy, radius, 0, Math.PI * 2)
        ctx.fillStyle = item.node.color || '#8b949e'
        ctx.fill()
        ctx.strokeStyle = isHot || isSelected || isHovered ? '#fff' : 'rgba(13,17,23,.9)'
        ctx.lineWidth = isHot || isSelected ? 2 : 1
        ctx.stroke()

        if (isSelected || isHovered) {
          const text = `${item.node.label} · ${item.node.state}`
          ctx.font = '11px ui-sans-serif, system-ui, sans-serif'
          const w = ctx.measureText(text).width
          const x = item.p.sx + radius + 7
          const y = item.p.sy - radius - 5
          ctx.fillStyle = 'rgba(13,17,23,.9)'
          ctx.fillRect(x - 4, y - 12, w + 8, 17)
          ctx.fillStyle = '#e6edf3'
          ctx.fillText(text, x, y)
        }
      }

      drawAxis(ctx, width, height, camera)
    }

    draw()
    const observer = new ResizeObserver(draw)
    observer.observe(canvas)
    return () => observer.disconnect()
  }, [nodes, edges, positions, selected, hot, hovered, camera])

  function nearest(clientX: number, clientY: number, maxDistance = 18): string | null {
    const canvas = canvasRef.current
    if (!canvas) return null
    const rect = canvas.getBoundingClientRect()
    const x = clientX - rect.left
    const y = clientY - rect.top
    let best: { id: string; distance: number; depth: number } | null = null
    for (const [id, p] of projectedRef.current) {
      const distance = Math.hypot(p.sx - x, p.sy - y)
      if (distance > maxDistance) continue
      if (!best || distance < best.distance || (Math.abs(distance - best.distance) < 2 && p.depth > best.depth)) {
        best = { id, distance, depth: p.depth }
      }
    }
    return best?.id || null
  }

  function pointerDown(event: React.PointerEvent<HTMLCanvasElement>) {
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = { x: event.clientX, y: event.clientY, button: event.button, camera: { ...camera } }
  }

  function pointerMove(event: React.PointerEvent<HTMLCanvasElement>) {
    const drag = dragRef.current
    if (!drag) {
      setHovered(nearest(event.clientX, event.clientY))
      return
    }
    const dx = event.clientX - drag.x
    const dy = event.clientY - drag.y
    if (drag.button === 2 || event.shiftKey) {
      setCamera({ ...drag.camera, panX: drag.camera.panX + dx, panY: drag.camera.panY + dy })
      return
    }
    setCamera({
      ...drag.camera,
      yaw: drag.camera.yaw + dx * 0.008,
      pitch: clamp(drag.camera.pitch + dy * 0.008, -1.45, 1.45),
    })
  }

  function pointerUp(event: React.PointerEvent<HTMLCanvasElement>) {
    const drag = dragRef.current
    dragRef.current = null
    if (!drag) return
    if (Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < 5) {
      const hit = nearest(event.clientX, event.clientY, 22)
      if (hit && nodeIds.has(hit)) onSelect(hit)
    }
  }

  return (
    <div style={{ width: '100%', height: '100%', minHeight: 420, position: 'relative' }}>
      <canvas
        ref={canvasRef}
        onPointerDown={pointerDown}
        onPointerMove={pointerMove}
        onPointerUp={pointerUp}
        onPointerLeave={() => { dragRef.current = null; setHovered(null) }}
        onWheel={event => {
          event.preventDefault()
          const factor = event.deltaY < 0 ? 1.12 : 0.89
          setCamera(value => ({ ...value, zoom: clamp(value.zoom * factor, 0.25, 6) }))
        }}
        onContextMenu={event => event.preventDefault()}
        style={{ width: '100%', height: '100%', display: 'block', touchAction: 'none', cursor: dragRef.current ? 'grabbing' : 'grab' }}
      />
      <div style={{
        position: 'absolute', left: 10, bottom: 10, padding: '5px 7px', borderRadius: 7,
        border: '1px solid var(--border)', background: 'rgba(13,17,23,.78)',
        color: 'var(--text-muted)', fontSize: 10, pointerEvents: 'none',
      }}>
        arrastrar: girar · ⇧/botón derecho: mover · rueda: acercar · clic: inspeccionar
      </div>
      <button type="button" onClick={() => setCamera(DEFAULT_CAMERA)} style={{
        position: 'absolute', right: 10, top: 10, border: '1px solid var(--border)', borderRadius: 6,
        background: 'rgba(13,17,23,.82)', color: 'var(--text-secondary)', padding: '4px 8px',
        cursor: 'pointer', fontSize: 10,
      }}>centrar 3D</button>
    </div>
  )
}

function layout3d(nodes: GraphNode3D[]) {
  const groups = new Map<string, GraphNode3D[]>()
  for (const node of nodes) {
    const list = groups.get(node.state) || []
    list.push(node)
    groups.set(node.state, list)
  }
  const positions = new Map<string, Point3>()
  ;[...groups.keys()].sort().forEach((state, stateIndex) => {
    const list = groups.get(state) || []
    const shell = 105 + stateIndex * 80
    const offset = stateIndex * 1.71
    list.forEach((node, index) => {
      const n = Math.max(list.length, 1)
      const y = 1 - ((index + 0.5) / n) * 2
      const radial = Math.sqrt(Math.max(0, 1 - y * y))
      const phi = index * Math.PI * (3 - Math.sqrt(5)) + offset
      positions.set(node.node_id, {
        x: Math.cos(phi) * radial * shell,
        y: y * shell,
        z: Math.sin(phi) * radial * shell,
      })
    })
  })
  return positions
}

function projectAll(positions: Map<string, Point3>, camera: Camera, width: number, height: number) {
  const result = new Map<string, ScreenPoint>()
  const cy = Math.cos(camera.yaw), sy = Math.sin(camera.yaw)
  const cp = Math.cos(camera.pitch), sp = Math.sin(camera.pitch)
  const focal = 760 * camera.zoom
  const cameraDistance = 760
  for (const [id, point] of positions) {
    const x1 = point.x * cy - point.z * sy
    const z1 = point.x * sy + point.z * cy
    const y2 = point.y * cp - z1 * sp
    const z2 = point.y * sp + z1 * cp
    const scale = focal / Math.max(120, cameraDistance - z2)
    result.set(id, {
      x: x1, y: y2, z: z2,
      sx: width / 2 + camera.panX + x1 * scale,
      sy: height / 2 + camera.panY + y2 * scale,
      depth: z2, scale,
    })
  }
  return result
}

function drawAxis(ctx: CanvasRenderingContext2D, width: number, height: number, camera: Camera) {
  ctx.save()
  ctx.translate(width - 38, height - 36)
  ctx.globalAlpha = 0.6
  const axes = [
    { point: rotate({ x: 17, y: 0, z: 0 }, camera), label: 'x' },
    { point: rotate({ x: 0, y: -17, z: 0 }, camera), label: 'y' },
    { point: rotate({ x: 0, y: 0, z: 17 }, camera), label: 'z' },
  ]
  for (const axis of axes) {
    ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(axis.point.x, axis.point.y)
    ctx.strokeStyle = '#8b949e'; ctx.lineWidth = 1; ctx.stroke()
    ctx.fillStyle = '#8b949e'; ctx.font = '9px sans-serif'; ctx.fillText(axis.label, axis.point.x + 2, axis.point.y)
  }
  ctx.restore()
}

function rotate(point: Point3, camera: Camera): Point3 {
  const cy = Math.cos(camera.yaw), sy = Math.sin(camera.yaw)
  const cp = Math.cos(camera.pitch), sp = Math.sin(camera.pitch)
  const x = point.x * cy - point.z * sy
  const z = point.x * sy + point.z * cy
  return { x, y: point.y * cp - z * sp, z: point.y * sp + z * cp }
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}
