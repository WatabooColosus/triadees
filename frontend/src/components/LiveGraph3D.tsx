import { useEffect, useMemo, useRef, useState } from 'react'

type GraphNode = {
  node_id: string
  kind: string
  label: string
  state: string
  color: string
  metadata: Record<string, any>
}

type GraphEdge = {
  source: string
  target: string
  relation: string
  evidence: string
}

type Props = {
  nodes: GraphNode[]
  edges: GraphEdge[]
  selected: string | null
  hot: Set<string>
  onSelect: (nodeId: string) => void
}

type Point3 = { x: number; y: number; z: number }
type ScreenPoint = Point3 & { sx: number; sy: number; depth: number; scale: number }

type Camera = {
  yaw: number
  pitch: number
  zoom: number
  panX: number
  panY: number
}

const CAMERA_DEFAULT: Camera = { yaw: -0.35, pitch: 0.2, zoom: 1, panX: 0, panY: 0 }

/*
 * Render 3D ligero, sin motor externo: el repositorio sigue siendo autónomo y
 * la visualización nunca se convierte en una dependencia de red. La posición
 * es determinista; el mismo grafo produce el mismo espacio y sólo los pulsos
 * reales del backend cambian estado/actividad.
 */
export function LiveGraph3D({ nodes, edges, selected, hot, onSelect }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const [camera, setCamera] = useState<Camera>(CAMERA_DEFAULT)
  const cameraRef = useRef(camera)
  const dragRef = useRef<{ x: number; y: number; button: number; camera: Camera } | null>(null)
  const projectedRef = useRef<Map<string, ScreenPoint>>(new Map())
  const frameRef = useRef<number | null>(null)
  const [hovered, setHovered] = useState<string | null>(null)

  const positions = useMemo(() => layout3d(nodes), [nodes])
  const nodeMap = useMemo(() => new Map(nodes.map(node => [node.node_id, node])), [nodes])

  useEffect(() => { cameraRef.current = camera }, [camera])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const draw = () => {
      frameRef.current = null
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

      const projected = projectAll(positions, cameraRef.current, width, height)
      projectedRef.current = projected

      const edgeQueue = edges
        .map(edge => ({ edge, a: projected.get(edge.source), b: projected.get(edge.target) }))
        .filter(item => item.a && item.b) as { edge: GraphEdge; a: ScreenPoint; b: ScreenPoint }[]
      edgeQueue.sort((left, right) => ((left.a.depth + left.b.depth) - (right.a.depth + right.b.depth)))

      for (const { edge, a, b } of edgeQueue) {
        const active = edge.source === selected || edge.target === selected || hot.has(edge.source) || hot.has(edge.target)
        ctx.beginPath()
        ctx.moveTo(a.sx, a.sy)
        ctx.lineTo(b.sx, b.sy)
        ctx.strokeStyle = active ? 'rgba(88,166,255,0.9)' : 'rgba(110,118,129,0.24)'
        ctx.lineWidth = active ? 1.6 : 0.55
        ctx.stroke()
      }

      const nodeQueue = nodes
        .map(node => ({ node, p: projected.get(node.node_id) }))
        .filter(item => item.p) as { node: GraphNode; p: ScreenPoint }[]
      nodeQueue.sort((left, right) => left.p.depth - right.p.depth)

      for (const { node, p } of nodeQueue) {
        const isHot = hot.has(node.node_id)
        const isSelected = selected === node.node_id
        const isHovered = hovered === node.node_id
        const radius = Math.max(2.4, Math.min(12, 4.2 * p.scale)) * (isHot ? 1.8 : isSelected ? 1.5 : isHovered ? 1.25 : 1)

        if (isHot || isSelected) {
          const glow = ctx.createRadialGradient(p.sx, p.sy, 0, p.sx, p.sy, radius * 3.2)
          glow.addColorStop(0, isHot ? 'rgba(255,255,255,0.5)' : 'rgba(88,166,255,0.45)')
          glow.addColorStop(1, 'rgba(0,0,0,0)')
          ctx.beginPath()
          ctx.arc(p.sx, p.sy, radius * 3.2, 0, Math.PI * 2)
          ctx.fillStyle = glow
          ctx.fill()
        }

        ctx.beginPath()
        ctx.arc(p.sx, p.sy, radius, 0, Math.PI * 2)
        ctx.fillStyle = node.color || '#8b949e'
        ctx.fill()
        ctx.strokeStyle = isHot || isSelected || isHovered ? '#ffffff' : 'rgba(13,17,23,0.9)'
        ctx.lineWidth = isHot || isSelected ? 2 : 1
        ctx.stroke()

        if (isSelected || isHovered) {
          ctx.font = '11px ui-sans-serif, system-ui, sans-serif'
          const text = `${node.label} · ${node.state}`
          const metrics = ctx.measureText(text)
          const tx = p.sx + radius + 7
          const ty = p.sy - radius - 5
          ctx.fillStyle = 'rgba(13,17,23,0.88)'
          ctx.fillRect(tx - 4, ty - 12, metrics.width + 8, 17)
          ctx.fillStyle = '#e6edf3'
          ctx.fillText(text, tx, ty)
        }
      }

      drawAxis(ctx, width, height, cameraRef.current)
    }

    const schedule = () => {
      if (frameRef.current === null) frameRef.current = requestAnimationFrame(draw)
    }

    schedule()
    const observer = new ResizeObserver(schedule)
    observer.observe(canvas)
    return () => {
      observer.disconnect()
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
    }
  }, [nodes, edges, positions, selected, hot, hovered])

  useEffect(() => {
    /* La cámara no altera los datos: sólo reproyecta el mismo estado. */
    const canvas = canvasRef.current
    if (!canvas) return
    const event = new Event('resize')
    window.dispatchEvent(event)
    const rect = canvas.getBoundingClientRect()
    const ctx = canvas.getContext('2d')
    if (ctx && rect.width && rect.height) {
      /* fuerza redibujado por el efecto principal sin mantener un bucle */
      setHovered(current => current)
    }
  }, [camera])

  function nearestNode(clientX: number, clientY: number, maxDistance = 18): string | null {
    const canvas = canvasRef.current
    if (!canvas) return null
    const rect = canvas.getBoundingClientRect()
    const x = clientX - rect.left
    const y = clientY - rect.top
    let best: { id: string; d: number; depth: number } | null = null
    for (const [id, p] of projectedRef.current) {
      const d = Math.hypot(p.sx - x, p.sy - y)
      if (d > maxDistance) continue
      if (!best || d < best.d || (Math.abs(d - best.d) < 2 && p.depth > best.depth)) {
        best = { id, d, depth: p.depth }
      }
    }
    return best?.id || null
  }

  function pointerDown(event: React.PointerEvent<HTMLCanvasElement>) {
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = {
      x: event.clientX,
      y: event.clientY,
      button: event.button,
      camera: { ...cameraRef.current },
    }
  }

  function pointerMove(event: React.PointerEvent<HTMLCanvasElement>) {
    const drag = dragRef.current
    if (!drag) {
      setHovered(nearestNode(event.clientX, event.clientY))
      return
    }
    const dx = event.clientX - drag.x
    const dy = event.clientY - drag.y
    if (drag.button === 2 || event.shiftKey) {
      setCamera({ ...drag.camera, panX: drag.camera.panX + dx, panY: drag.camera.panY + dy })
    } else {
      setCamera({
        ...drag.camera,
        yaw: drag.camera.yaw + dx * 0.008,
        pitch: clamp(drag.camera.pitch + dy * 0.008, -1.45, 1.45),
      })
    }
  }

  function pointerUp(event: React.PointerEvent<HTMLCanvasElement>) {
    const drag = dragRef.current
    dragRef.current = null
    if (!drag) return
    const moved = Math.hypot(event.clientX - drag.x, event.clientY - drag.y)
    if (moved < 5) {
      const hit = nearestNode(event.clientX, event.clientY, 22)
      if (hit && nodeMap.has(hit)) onSelect(hit)
    }
  }

  function wheel(event: React.WheelEvent<HTMLCanvasElement>) {
    event.preventDefault()
    const factor = event.deltaY < 0 ? 1.12 : 0.89
    setCamera(current => ({ ...current, zoom: clamp(current.zoom * factor, 0.25, 6) }))
  }

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative', minHeight: 420 }}>
      <canvas
        ref={canvasRef}
        onPointerDown={pointerDown}
        onPointerMove={pointerMove}
        onPointerUp={pointerUp}
        onPointerLeave={() => { dragRef.current = null; setHovered(null) }}
        onWheel={wheel}
        onContextMenu={event => event.preventDefault()}
        style={{ width: '100%', height: '100%', display: 'block', cursor: dragRef.current ? 'grabbing' : 'grab', touchAction: 'none' }}
      />
      <div style={{
        position: 'absolute', left: 10, bottom: 10, display: 'flex', gap: 6, alignItems: 'center',
        background: 'rgba(13,17,23,.78)', border: '1px solid var(--border)', borderRadius: 7,
        padding: '5px 7px', fontSize: 10, color: 'var(--text-muted)', pointerEvents: 'none',
      }}>
        arrastrar: girar · ⇧/botón derecho: mover · rueda: acercar · clic: inspeccionar
      </div>
      <button
        type="button"
        onClick={() => setCamera(CAMERA_DEFAULT)}
        style={{
          position: 'absolute', right: 10, top: 10, border: '1px solid var(--border)', borderRadius: 6,
          background: 'rgba(13,17,23,.82)', color: 'var(--text-secondary)', padding: '4px 8px',
          cursor: 'pointer', fontSize: 10,
        }}
      >
        centrar 3D
      </button>
    </div>
  )
}

function layout3d(nodes: GraphNode[]): Map<string, Point3> {
  const groups = new Map<string, GraphNode[]>()
  for (const node of nodes) {
    const list = groups.get(node.state) || []
    list.push(node)
    groups.set(node.state, list)
  }

  const positions = new Map<string, Point3>()
  const states = [...groups.keys()].sort()
  states.forEach((state, stateIndex) => {
    const list = groups.get(state) || []
    const shell = 105 + stateIndex * 80
    const offset = stateIndex * 1.71
    list.forEach((node, index) => {
      /* Fibonacci sphere: distribución uniforme y estable sin simulación. */
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

function projectAll(
  positions: Map<string, Point3>, camera: Camera, width: number, height: number,
): Map<string, ScreenPoint> {
  const result = new Map<string, ScreenPoint>()
  const cy = Math.cos(camera.yaw)
  const sy = Math.sin(camera.yaw)
  const cp = Math.cos(camera.pitch)
  const sp = Math.sin(camera.pitch)
  const focal = 760 * camera.zoom
  const cameraDistance = 760

  for (const [id, point] of positions) {
    const x1 = point.x * cy - point.z * sy
    const z1 = point.x * sy + point.z * cy
    const y2 = point.y * cp - z1 * sp
    const z2 = point.y * sp + z1 * cp
    const denominator = Math.max(120, cameraDistance - z2)
    const scale = focal / denominator
    result.set(id, {
      x: x1, y: y2, z: z2,
      sx: width / 2 + camera.panX + x1 * scale,
      sy: height / 2 + camera.panY + y2 * scale,
      depth: z2,
      scale,
    })
  }
  return result
}

function drawAxis(ctx: CanvasRenderingContext2D, width: number, height: number, camera: Camera) {
  ctx.save()
  ctx.translate(width - 38, height - 36)
  ctx.globalAlpha = 0.6
  const axes = [
    { p: rotate({ x: 17, y: 0, z: 0 }, camera), label: 'x' },
    { p: rotate({ x: 0, y: -17, z: 0 }, camera), label: 'y' },
    { p: rotate({ x: 0, y: 0, z: 17 }, camera), label: 'z' },
  ]
  for (const axis of axes) {
    ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(axis.p.x, axis.p.y); ctx.strokeStyle = '#8b949e'; ctx.lineWidth = 1; ctx.stroke()
    ctx.fillStyle = '#8b949e'; ctx.font = '9px sans-serif'; ctx.fillText(axis.label, axis.p.x + 2, axis.p.y)
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
