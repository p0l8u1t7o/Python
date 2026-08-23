import { useEffect, useRef } from 'react'
import * as THREE from 'three'

import type { PowerFlow } from '@/lib/types'
import { useTheme } from '@/providers/ThemeProvider'

/**
 * Live 3D energy scene for the storage page.
 *
 * Four nodes sit on a glowing grid floor - PV array, grid pylon, battery
 * (SOC shown as a glowing liquid level) and the site load - linked to a
 * central hub by arcs along which particles travel in the direction power is
 * actually moving. Particle speed and density scale with kW, so the picture
 * is data, not decoration.
 *
 * Rendering is imperative three.js inside one canvas; React only feeds it the
 * latest flow through a ref so a fresh overview every few seconds does not
 * rebuild the scene. Respects `prefers-reduced-motion` (camera and particles
 * hold still) and bails out to the caller's fallback when WebGL is missing.
 */

export interface EnergyScene3DProps {
  flow: PowerFlow
  /** Height in CSS pixels. */
  height?: number
  /** Demand ceiling (kW) drawn as a floating plane over the grid node; null hides it. */
  ceilingKw?: number | null
  /** Change this value (e.g. the latest command id) to fire a dispatch pulse hub → battery. */
  pulseKey?: string | null
  /** Called once when WebGL cannot be created - render a 2D fallback instead. */
  onUnsupported?: () => void
  /** Node the user clicked (null = none); the camera focuses on it. */
  onFocus?: (node: 'pv' | 'grid' | 'battery' | 'load' | null) => void
}

type NodeKey = 'pv' | 'grid' | 'battery' | 'load'

const NODE_POS: Record<NodeKey, THREE.Vector3> = {
  pv: new THREE.Vector3(-3.2, 0, -2.2),
  grid: new THREE.Vector3(3.2, 0, -2.2),
  battery: new THREE.Vector3(3.2, 0, 2.4),
  load: new THREE.Vector3(-3.2, 0, 2.4),
}
const HUB = new THREE.Vector3(0, 0.35, 0)
const PARTICLES_PER_EDGE = 48

interface Palette {
  bg: number
  grid: number
  floor: number
  brand: number
  pv: number
  gridPower: number
  export: number
  battery: number
  charge: number
  load: number
  text: number
}

const LIGHT: Palette = {
  bg: 0xf4f6fa, grid: 0xc7d2e0, floor: 0xe6ebf3, brand: 0x0f766e, pv: 0xd97706,
  gridPower: 0x2563eb, export: 0x16a34a, battery: 0x0f766e, charge: 0x0891b2, load: 0x7c3aed, text: 0x1f2937,
}
const DARK: Palette = {
  bg: 0x0b1220, grid: 0x1e2a44, floor: 0x101a2e, brand: 0x2dd4bf, pv: 0xfbbf24,
  gridPower: 0x60a5fa, export: 0x4ade80, battery: 0x2dd4bf, charge: 0x22d3ee, load: 0xc084fc, text: 0xe5e7eb,
}

function arc(from: THREE.Vector3, to: THREE.Vector3, lift = 1.1): THREE.QuadraticBezierCurve3 {
  const mid = from.clone().add(to).multiplyScalar(0.5)
  mid.y += lift
  return new THREE.QuadraticBezierCurve3(from.clone().setY(0.35), mid, to.clone().setY(0.35))
}

function makeLabel(text: string, color: number): THREE.Sprite {
  const canvas = document.createElement('canvas')
  canvas.width = 256
  canvas.height = 64
  const ctx = canvas.getContext('2d')
  if (ctx) {
    ctx.font = '600 30px system-ui, sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillStyle = `#${color.toString(16).padStart(6, '0')}`
    ctx.fillText(text, 128, 32)
  }
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false }))
  sprite.scale.set(2.4, 0.6, 1)
  return sprite
}

export function EnergyScene3D({ flow, height = 320, ceilingKw = null, pulseKey = null, onUnsupported, onFocus }: EnergyScene3DProps) {
  const mount = useRef<HTMLDivElement>(null)
  const flowRef = useRef(flow)
  const ceilingRef = useRef(ceilingKw)
  const pulseRef = useRef<{ key: string | null; fired: string | null }>({ key: pulseKey, fired: pulseKey })
  const focusRef = useRef<NodeKey | null>(null)
  const onFocusRef = useRef(onFocus)
  const labelRef = useRef<Record<NodeKey, THREE.Sprite> | null>(null)
  const { resolved } = useTheme()
  flowRef.current = flow
  ceilingRef.current = ceilingKw
  pulseRef.current.key = pulseKey
  onFocusRef.current = onFocus

  useEffect(() => {
    const host = mount.current
    if (!host) return
    const palette = resolved === 'dark' ? DARK : LIGHT
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

    let renderer: THREE.WebGLRenderer
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' })
    } catch {
      onUnsupported?.()
      return
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setClearColor(palette.bg, 0)
    host.appendChild(renderer.domElement)
    renderer.domElement.style.display = 'block'
    renderer.domElement.style.width = '100%'
    renderer.domElement.style.height = '100%'

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 60)
    camera.position.set(0, 7.4, 11)
    camera.lookAt(0, -0.9, 0)

    scene.add(new THREE.HemisphereLight(0xffffff, palette.floor, resolved === 'dark' ? 0.9 : 1.2))
    const key = new THREE.DirectionalLight(0xffffff, resolved === 'dark' ? 1.1 : 1.6)
    key.position.set(4, 8, 6)
    scene.add(key)
    const rim = new THREE.PointLight(palette.brand, 6, 14)
    rim.position.set(0, 2.5, 0)
    scene.add(rim)

    // ---- floor: a glowing grid fading out towards the fog ----------------
    // A radial alpha fade instead of a hard disc: the canvas is transparent
    // over the card, so fog alone cannot hide the floor's edge.
    const fade = document.createElement('canvas')
    fade.width = fade.height = 256
    const fctx = fade.getContext('2d')
    if (fctx) {
      const g = fctx.createRadialGradient(128, 128, 20, 128, 128, 128)
      // alphaMap reads the green channel, so the fade is drawn white → black.
      g.addColorStop(0, '#ffffff')
      g.addColorStop(0.55, '#cccccc')
      g.addColorStop(1, '#000000')
      fctx.fillStyle = g
      fctx.fillRect(0, 0, 256, 256)
    }
    const fadeTexture = new THREE.CanvasTexture(fade)
    const floor = new THREE.Mesh(
      new THREE.CircleGeometry(10, 64),
      new THREE.MeshStandardMaterial({
        color: palette.floor, roughness: 0.95, metalness: 0.05, transparent: true, alphaMap: fadeTexture, depthWrite: false,
      }),
    )
    floor.rotation.x = -Math.PI / 2
    floor.position.y = -0.02
    scene.add(floor)
    const grid = new THREE.GridHelper(16, 32, palette.brand, palette.grid)
    ;(grid.material as THREE.Material).transparent = true
    ;(grid.material as THREE.Material).opacity = resolved === 'dark' ? 0.35 : 0.4
    scene.add(grid)

    // ---- hub ----------------------------------------------------------------
    const hub = new THREE.Mesh(
      new THREE.IcosahedronGeometry(0.42, 1),
      new THREE.MeshStandardMaterial({
        color: palette.brand, emissive: palette.brand, emissiveIntensity: 0.8, roughness: 0.2, metalness: 0.6,
        wireframe: true,
      }),
    )
    hub.position.copy(HUB)
    scene.add(hub)
    const hubCore = new THREE.Mesh(
      new THREE.SphereGeometry(0.24, 24, 24),
      new THREE.MeshStandardMaterial({ color: palette.brand, emissive: palette.brand, emissiveIntensity: 1.4 }),
    )
    hubCore.position.copy(HUB)
    scene.add(hubCore)
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.8, 0.86, 64),
      new THREE.MeshBasicMaterial({ color: palette.brand, transparent: true, opacity: 0.6, side: THREE.DoubleSide }),
    )
    ring.rotation.x = -Math.PI / 2
    ring.position.y = 0.01
    scene.add(ring)

    // ---- nodes ----------------------------------------------------------------
    const standard = (color: number, emissive = 0.25) =>
      new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: emissive, roughness: 0.35, metalness: 0.4 })

    // PV: three tilted panels.
    const pv = new THREE.Group()
    for (let i = 0; i < 3; i += 1) {
      const panel = new THREE.Mesh(new THREE.BoxGeometry(1.1, 0.05, 0.6), standard(palette.pv, 0.35))
      panel.position.set(0, 0.45, (i - 1) * 0.7)
      panel.rotation.x = -0.5
      pv.add(panel)
      const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.45), standard(palette.grid, 0))
      leg.position.set(0, 0.22, (i - 1) * 0.7)
      pv.add(leg)
    }
    pv.position.copy(NODE_POS.pv)
    scene.add(pv)

    // Grid: a pylon with cross arms.
    const pylon = new THREE.Group()
    const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.12, 1.8, 8), standard(palette.gridPower, 0.2))
    mast.position.y = 0.9
    pylon.add(mast)
    for (const y of [1.2, 1.55]) {
      const arm = new THREE.Mesh(new THREE.BoxGeometry(1.2 - (y - 1.2), 0.05, 0.05), standard(palette.gridPower, 0.2))
      arm.position.y = y
      pylon.add(arm)
    }
    pylon.position.copy(NODE_POS.grid)
    scene.add(pylon)

    // Battery: a translucent shell with a glowing liquid level.
    const battery = new THREE.Group()
    const shell = new THREE.Mesh(
      new THREE.CylinderGeometry(0.5, 0.5, 1.5, 32, 1, true),
      new THREE.MeshPhysicalMaterial({
        color: palette.battery, transparent: true, opacity: 0.18, roughness: 0.1, metalness: 0.1,
        side: THREE.DoubleSide, depthWrite: false,
      }),
    )
    shell.position.y = 0.75
    battery.add(shell)
    const cap = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.18, 0.12, 24), standard(palette.battery, 0.5))
    cap.position.y = 1.56
    battery.add(cap)
    const base = new THREE.Mesh(new THREE.CylinderGeometry(0.52, 0.52, 0.06, 32), standard(palette.grid, 0))
    base.position.y = 0.03
    battery.add(base)
    const liquid = new THREE.Mesh(
      new THREE.CylinderGeometry(0.46, 0.46, 1, 32),
      new THREE.MeshStandardMaterial({ color: palette.battery, emissive: palette.battery, emissiveIntensity: 0.9, transparent: true, opacity: 0.85 }),
    )
    battery.add(liquid)
    battery.position.copy(NODE_POS.battery)
    scene.add(battery)

    // Load: a small factory block with a roof light.
    const load = new THREE.Group()
    const hall = new THREE.Mesh(new THREE.BoxGeometry(1.3, 0.7, 1.0), standard(palette.load, 0.15))
    hall.position.y = 0.35
    load.add(hall)
    const roof = new THREE.Mesh(new THREE.ConeGeometry(0.75, 0.35, 4), standard(palette.load, 0.3))
    roof.position.y = 0.87
    roof.rotation.y = Math.PI / 4
    load.add(roof)
    const stack = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.1, 0.6, 12), standard(palette.grid, 0))
    stack.position.set(0.45, 0.95, -0.25)
    load.add(stack)
    load.position.copy(NODE_POS.load)
    scene.add(load)

    // ---- demand ceiling over the grid node ------------------------------------
    // A translucent "roof" whose height is the ceiling kW; the column beneath
    // it is live grid import on the same scale, so an excursion is the column
    // punching through the roof - visible before anyone reads a number.
    const DEMAND_SCALE = 2.2 // scene units at the ceiling
    const ceilingPlane = new THREE.Mesh(
      new THREE.PlaneGeometry(1.9, 1.9),
      new THREE.MeshBasicMaterial({ color: palette.gridPower, transparent: true, opacity: 0.22, side: THREE.DoubleSide, depthWrite: false }),
    )
    ceilingPlane.rotation.x = -Math.PI / 2
    ceilingPlane.position.copy(NODE_POS.grid).add(new THREE.Vector3(0, DEMAND_SCALE, 0))
    ceilingPlane.visible = false
    scene.add(ceilingPlane)
    const ceilingEdge = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.PlaneGeometry(1.9, 1.9)),
      new THREE.LineBasicMaterial({ color: palette.gridPower, transparent: true, opacity: 0.9 }),
    )
    ceilingEdge.rotation.x = -Math.PI / 2
    ceilingEdge.position.copy(ceilingPlane.position)
    ceilingEdge.visible = false
    scene.add(ceilingEdge)
    const column = new THREE.Mesh(
      new THREE.CylinderGeometry(0.32, 0.32, 1, 24, 1, true),
      new THREE.MeshBasicMaterial({ color: palette.gridPower, transparent: true, opacity: 0.3, side: THREE.DoubleSide, depthWrite: false }),
    )
    column.position.copy(NODE_POS.grid).add(new THREE.Vector3(0, 0.5, 0))
    column.visible = false
    scene.add(column)
    const columnCap = new THREE.Mesh(
      new THREE.CylinderGeometry(0.34, 0.34, 0.04, 24),
      new THREE.MeshStandardMaterial({ color: palette.gridPower, emissive: palette.gridPower, emissiveIntensity: 1.2 }),
    )
    columnCap.visible = false
    scene.add(columnCap)
    const ceilingLabel = makeLabel('', palette.text)
    ceilingLabel.scale.set(2.2, 0.55, 1)
    ceilingLabel.visible = false
    scene.add(ceilingLabel)

    // ---- dispatch pulse: a ring that races hub → battery --------------------
    const pulseRing = new THREE.Mesh(
      new THREE.TorusGeometry(0.3, 0.04, 8, 32),
      new THREE.MeshBasicMaterial({ color: palette.brand, transparent: true, opacity: 0 }),
    )
    pulseRing.visible = false
    scene.add(pulseRing)
    const pulseCurve = arc(HUB, NODE_POS.battery, 0.9)
    let pulseT = -1 // <0 idle, 0..1 travelling

    // ---- picking ---------------------------------------------------------------
    const pickables: { key: NodeKey; object: THREE.Object3D }[] = [
      { key: 'pv', object: pv }, { key: 'grid', object: pylon }, { key: 'battery', object: battery }, { key: 'load', object: load },
    ]
    // Labels and thin masts are hard to hit with a ray; fall back to the
    // nearest node in screen space so a click "near enough" still counts.
    const projected = new THREE.Vector3()
    const nearestNode = (ndc: THREE.Vector2, radius: number): NodeKey | null => {
      let best: NodeKey | null = null
      let bestDistance = radius
      for (const item of pickables) {
        projected.copy(NODE_POS[item.key]).add(new THREE.Vector3(0, 0.8, 0)).project(camera)
        const d = Math.hypot(projected.x - ndc.x, (projected.y - ndc.y) * (1 / camera.aspect))
        if (d < bestDistance) { bestDistance = d; best = item.key }
      }
      return best
    }
    const raycaster = new THREE.Raycaster()
    const pointer = new THREE.Vector2()
    let downAt = 0
    const onDown = () => { downAt = performance.now() }
    const onClick = (event: MouseEvent) => {
      if (performance.now() - downAt > 250) return // a drag, not a click
      const rect = renderer.domElement.getBoundingClientRect()
      pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1)
      raycaster.setFromCamera(pointer, camera)
      let hit: NodeKey | null = null
      for (const item of pickables) {
        if (raycaster.intersectObject(item.object, true).length > 0) { hit = item.key; break }
      }
      if (hit === null) hit = nearestNode(pointer, 0.16)
      focusRef.current = focusRef.current === hit ? null : hit
      onFocusRef.current?.(focusRef.current)
      renderer.domElement.style.cursor = focusRef.current ? 'zoom-out' : 'default'
    }
    const onMove = (event: MouseEvent) => {
      const rect = renderer.domElement.getBoundingClientRect()
      pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1)
      raycaster.setFromCamera(pointer, camera)
      const over = pickables.some((item) => raycaster.intersectObject(item.object, true).length > 0)
        || nearestNode(pointer, 0.16) !== null
      renderer.domElement.style.cursor = over ? 'pointer' : focusRef.current ? 'zoom-out' : 'default'
    }
    renderer.domElement.addEventListener('pointerdown', onDown)
    renderer.domElement.addEventListener('click', onClick)
    renderer.domElement.addEventListener('pointermove', onMove)
    const cameraTarget = new THREE.Vector3(0, -0.9, 0)
    const cameraGoal = new THREE.Vector3()
    const lookGoal = new THREE.Vector3()

    // ---- labels ---------------------------------------------------------------
    const labels: Record<NodeKey, THREE.Sprite> = {
      pv: makeLabel('PV', palette.text),
      grid: makeLabel('Grid', palette.text),
      battery: makeLabel('BESS', palette.text),
      load: makeLabel('Load', palette.text),
    }
    for (const k of Object.keys(labels) as NodeKey[]) {
      labels[k].position.copy(NODE_POS[k]).add(new THREE.Vector3(0, 2.15, 0))
      scene.add(labels[k])
    }
    labelRef.current = labels

    // ---- edges and particles --------------------------------------------------
    const edgeColor: Record<NodeKey, () => number> = {
      pv: () => palette.pv,
      grid: () => ((flowRef.current.grid_kw ?? 0) >= 0 ? palette.gridPower : palette.export),
      battery: () => ((flowRef.current.battery_kw ?? 0) >= 0 ? palette.battery : palette.charge),
      load: () => palette.load,
    }
    const edges = (Object.keys(NODE_POS) as NodeKey[]).map((k) => {
      const curve = arc(NODE_POS[k], HUB)
      const tube = new THREE.Mesh(
        new THREE.TubeGeometry(curve, 40, 0.025, 8, false),
        new THREE.MeshBasicMaterial({ color: palette.grid, transparent: true, opacity: 0.7 }),
      )
      scene.add(tube)
      const positions = new Float32Array(PARTICLES_PER_EDGE * 3)
      const geometry = new THREE.BufferGeometry()
      geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
      const material = new THREE.PointsMaterial({
        color: edgeColor[k](), size: 0.14, transparent: true, opacity: 0.95, sizeAttenuation: true, depthWrite: false,
      })
      const points = new THREE.Points(geometry, material)
      scene.add(points)
      const offsets = Float32Array.from({ length: PARTICLES_PER_EDGE }, (_, i) => i / PARTICLES_PER_EDGE)
      return { key: k, curve, points, material, positions, offsets, phase: 0 }
    })

    // ---- resize -----------------------------------------------------------------
    const resize = () => {
      const width = host.clientWidth || 600
      const h = host.clientHeight || height
      renderer.setSize(width, h, false)
      camera.aspect = width / h
      camera.updateProjectionMatrix()
    }
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(host)

    // ---- animation --------------------------------------------------------------
    const clock = new THREE.Clock()
    let frame = 0
    const tmp = new THREE.Vector3()
    const render = () => {
      const dt = Math.min(clock.getDelta(), 0.1)
      const elapsed = clock.elapsedTime
      const f = flowRef.current
      const kw: Record<NodeKey, number> = {
        pv: f.pv_kw ?? 0,
        grid: f.grid_kw ?? 0,
        battery: f.battery_kw ?? 0,
        load: -(f.load_kw ?? 0), // negative = outward from the hub
      }
      const scale = Math.max(50, Math.abs(kw.pv), Math.abs(kw.grid), Math.abs(kw.battery), Math.abs(kw.load))

      for (const edge of edges) {
        const value = kw[edge.key]
        const magnitude = Math.abs(value) / scale // 0..1
        const active = Math.abs(value) > 0.05
        const speed = reduced ? 0 : 0.15 + magnitude * 0.55
        // Towards the hub for positive (pv produce, grid import, battery
        // discharge); away from it for negative.
        edge.phase = (edge.phase + speed * dt * (value >= 0 ? 1 : -1) + 1) % 1
        edge.material.color.setHex(edgeColor[edge.key]())
        edge.material.opacity = active ? 0.35 + magnitude * 0.65 : 0
        edge.material.size = 0.09 + magnitude * 0.12
        const visible = active ? Math.max(6, Math.round(PARTICLES_PER_EDGE * (0.25 + magnitude * 0.75))) : 0
        for (let i = 0; i < PARTICLES_PER_EDGE; i += 1) {
          const t = (edge.offsets[i] + edge.phase) % 1
          if (i < visible) {
            edge.curve.getPoint(t, tmp)
            edge.positions[i * 3] = tmp.x
            edge.positions[i * 3 + 1] = tmp.y
            edge.positions[i * 3 + 2] = tmp.z
          } else {
            edge.positions[i * 3 + 1] = -50
          }
        }
        ;(edge.points.geometry.attributes.position as THREE.BufferAttribute).needsUpdate = true
      }

      // Battery level and glow.
      const soc = Math.max(0, Math.min(100, f.battery_soc_percent ?? 0)) / 100
      const levelHeight = Math.max(0.02, 1.42 * soc)
      liquid.scale.y = levelHeight
      liquid.position.y = 0.06 + levelHeight / 2
      const liquidMaterial = liquid.material as THREE.MeshStandardMaterial
      liquidMaterial.color.setHex(soc < 0.2 ? palette.pv : palette.battery)
      liquidMaterial.emissive.setHex(soc < 0.2 ? palette.pv : palette.battery)
      liquidMaterial.emissiveIntensity = 0.6 + (reduced ? 0 : 0.3 * Math.sin(elapsed * 2.2))

      // Demand ceiling and live import column.
      const ceiling = ceilingRef.current
      const showCeiling = ceiling !== null && ceiling > 0
      ceilingPlane.visible = ceilingEdge.visible = column.visible = columnCap.visible = ceilingLabel.visible = showCeiling
      if (showCeiling && ceiling) {
        const importKw = Math.max(0, f.grid_kw ?? 0)
        const ratio = importKw / ceiling
        const columnHeight = Math.max(0.02, Math.min(ratio, 1.35) * DEMAND_SCALE)
        column.scale.y = columnHeight
        column.position.y = columnHeight / 2
        columnCap.position.copy(NODE_POS.grid).add(new THREE.Vector3(0, columnHeight, 0))
        const over = ratio > 1
        const warn = ratio > 0.9
        const tone = over ? 0xef4444 : warn ? palette.pv : palette.gridPower
        ;(column.material as THREE.MeshBasicMaterial).color.setHex(tone)
        ;(columnCap.material as THREE.MeshStandardMaterial).color.setHex(tone)
        ;(columnCap.material as THREE.MeshStandardMaterial).emissive.setHex(tone)
        ;(ceilingPlane.material as THREE.MeshBasicMaterial).color.setHex(over ? 0xef4444 : palette.gridPower)
        ;(ceilingPlane.material as THREE.MeshBasicMaterial).opacity = over ? 0.35 + (reduced ? 0 : 0.15 * Math.sin(elapsed * 8)) : 0.22
        ;(ceilingEdge.material as THREE.LineBasicMaterial).color.setHex(over ? 0xef4444 : palette.gridPower)
        ceilingLabel.position.copy(ceilingPlane.position).add(new THREE.Vector3(0, 0.45, 0))
        const text = `${Math.round(importKw)} / ${Math.round(ceiling)} kW`
        if (ceilingLabel.userData.text !== text) {
          ceilingLabel.userData.text = text
          const fresh = makeLabel(text, over ? 0xef4444 : palette.text)
          ;(ceilingLabel.material as THREE.SpriteMaterial).map?.dispose()
          ;(ceilingLabel.material as THREE.SpriteMaterial).map = (fresh.material as THREE.SpriteMaterial).map
          ;(ceilingLabel.material as THREE.SpriteMaterial).needsUpdate = true
        }
      }

      // Dispatch pulse: fire once per new key, travel hub → battery.
      if (pulseRef.current.key && pulseRef.current.key !== pulseRef.current.fired) {
        pulseRef.current.fired = pulseRef.current.key
        pulseT = 0
      }
      if (pulseT >= 0) {
        pulseT += dt * (reduced ? 3 : 0.9)
        if (pulseT >= 1) {
          pulseT = -1
          pulseRing.visible = false
          hubCore.scale.setScalar(1)
        } else {
          pulseRing.visible = true
          pulseCurve.getPoint(pulseT, tmp)
          pulseRing.position.copy(tmp)
          pulseRing.lookAt(pulseCurve.getPoint(Math.min(1, pulseT + 0.02)))
          const s = 1 + pulseT * 1.5
          pulseRing.scale.setScalar(s)
          ;(pulseRing.material as THREE.MeshBasicMaterial).opacity = 1 - pulseT
          hubCore.scale.setScalar(1 + 0.6 * Math.max(0, 1 - pulseT * 4))
        }
      }

      // Hub pulse and slow camera orbit.
      const pulse = reduced ? 1 : 1 + 0.06 * Math.sin(elapsed * 2.4)
      hub.scale.setScalar(pulse)
      hub.rotation.y += dt * 0.4
      hub.rotation.x += dt * 0.15
      ring.scale.setScalar(1 + (reduced ? 0 : 0.25 * ((elapsed * 0.6) % 1)))
      ;(ring.material as THREE.MeshBasicMaterial).opacity = reduced ? 0.5 : 0.7 * (1 - ((elapsed * 0.6) % 1))
      // Camera: orbit the whole site, or glide in on the focused node.
      const focused = focusRef.current
      if (focused) {
        const target = NODE_POS[focused]
        cameraGoal.set(target.x * 1.25, 3.2, target.z * 1.25 + 4.2)
        lookGoal.set(target.x, 0.7, target.z)
      } else {
        const angle = reduced ? 0 : Math.sin(elapsed * 0.12) * 0.45
        cameraGoal.set(Math.sin(angle) * 11, 7.4, Math.cos(angle) * 11)
        lookGoal.set(0, -0.9, 0)
      }
      const ease = reduced ? 1 : 1 - Math.exp(-dt * 3.5)
      camera.position.lerp(cameraGoal, ease)
      cameraTarget.lerp(lookGoal, ease)
      camera.lookAt(cameraTarget)

      renderer.render(scene, camera)
      frame = requestAnimationFrame(render)
    }
    frame = requestAnimationFrame(render)

    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
      renderer.domElement.removeEventListener('pointerdown', onDown)
      renderer.domElement.removeEventListener('click', onClick)
      renderer.domElement.removeEventListener('pointermove', onMove)
      scene.traverse((obj) => {
        const mesh = obj as THREE.Mesh
        mesh.geometry?.dispose?.()
        const material = mesh.material as THREE.Material | THREE.Material[] | undefined
        if (Array.isArray(material)) material.forEach((m) => m.dispose())
        else material?.dispose?.()
      })
      renderer.dispose()
      if (renderer.domElement.parentNode === host) host.removeChild(renderer.domElement)
      labelRef.current = null
    }
  }, [resolved, height, onUnsupported])

  return <div ref={mount} style={{ height }} className="w-full overflow-hidden rounded-lg" data-testid="energy-scene-3d" />
}

export default EnergyScene3D
