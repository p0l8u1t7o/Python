import { useEffect, useRef } from 'react'
import * as THREE from 'three'

import type { DemandStatus, SiteLive } from '@/lib/types'
import { useTheme } from '@/providers/ThemeProvider'

/**
 * Every site at once, as a 3D "energy map" for the overview.
 *
 * The grid is a glowing hub in the centre. Top-level sites stand on a ring
 * around it, their children on a wider ring tethered to the parent, so the
 * site tree has a shape. Each site is a hex platform with a pillar whose
 * height is its load and whose colour is its demand standing (over the
 * contract → red, above the ceiling → amber, watching → yellow, balanced →
 * brand, exporting → green, unknown → grey). Beams carry particles from the
 * hub to importing sites and back from exporting ones, so the direction of
 * money is visible at a glance.
 *
 * Data flows in through refs; a refetch re-lays the ring without rebuilding
 * the renderer. Clicking a site reports it to the caller.
 */

export interface FleetScene3DProps {
  sites: SiteLive[]
  height?: number
  onUnsupported?: () => void
  onPickSite?: (site: SiteLive) => void
}

interface Palette {
  floor: number
  grid: number
  brand: number
  text: number
  hub: number
  tether: number
  over: number
  high: number
  watch: number
  balanced: number
  exporting: number
  unknown: number
}

const LIGHT: Palette = {
  floor: 0xe6ebf3, grid: 0xc7d2e0, brand: 0x0f766e, text: 0x1f2937, hub: 0x2563eb, tether: 0x94a3b8,
  over: 0xdc2626, high: 0xea580c, watch: 0xca8a04, balanced: 0x0f766e, exporting: 0x16a34a, unknown: 0x94a3b8,
}
const DARK: Palette = {
  floor: 0x101a2e, grid: 0x1e2a44, brand: 0x2dd4bf, text: 0xe5e7eb, hub: 0x60a5fa, tether: 0x475569,
  over: 0xf87171, high: 0xfb923c, watch: 0xfacc15, balanced: 0x2dd4bf, exporting: 0x4ade80, unknown: 0x64748b,
}

function statusColor(palette: Palette, status: DemandStatus): number {
  return palette[status] ?? palette.unknown
}

function label(text: string, color: number, width = 320): THREE.Sprite {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = 72
  const ctx = canvas.getContext('2d')
  if (ctx) {
    ctx.font = '600 30px system-ui, "Noto Sans TC", sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillStyle = `#${color.toString(16).padStart(6, '0')}`
    ctx.fillText(text.length > 18 ? `${text.slice(0, 17)}…` : text, width / 2, 36)
  }
  const texture = new THREE.CanvasTexture(canvas)
  texture.minFilter = THREE.LinearFilter
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false }))
  sprite.scale.set(width / 100, 0.72, 1)
  return sprite
}

/** Curved beam from `a` to `b`, plus its particles. */
function beam(a: THREE.Vector3, b: THREE.Vector3, color: number): { line: THREE.Line; curve: THREE.QuadraticBezierCurve3 } {
  const mid = a.clone().add(b).multiplyScalar(0.5)
  mid.y += a.distanceTo(b) * 0.18
  const curve = new THREE.QuadraticBezierCurve3(a, mid, b)
  const geometry = new THREE.BufferGeometry().setFromPoints(curve.getPoints(32))
  const line = new THREE.Line(geometry, new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.55 }))
  return { line, curve }
}

export function FleetScene3D({ sites, height = 360, onUnsupported, onPickSite }: FleetScene3DProps) {
  const mount = useRef<HTMLDivElement>(null)
  const dataRef = useRef(sites)
  const cbRef = useRef(onPickSite)
  const { resolved } = useTheme()
  dataRef.current = sites
  cbRef.current = onPickSite

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
    renderer.setClearColor(0x000000, 0)
    host.appendChild(renderer.domElement)
    Object.assign(renderer.domElement.style, { display: 'block', width: '100%', height: '100%' })

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 120)
    scene.add(new THREE.HemisphereLight(0xffffff, palette.floor, resolved === 'dark' ? 0.9 : 1.2))
    const key = new THREE.DirectionalLight(0xffffff, resolved === 'dark' ? 1.0 : 1.5)
    key.position.set(6, 10, 6)
    scene.add(key)
    const hubLight = new THREE.PointLight(palette.hub, 6, 14)
    hubLight.position.set(0, 2, 0)
    scene.add(hubLight)

    // Floor with a radial fade (alphaMap reads green, so draw white → black).
    const fade = document.createElement('canvas')
    fade.width = fade.height = 256
    const fctx = fade.getContext('2d')
    if (fctx) {
      const g = fctx.createRadialGradient(128, 128, 20, 128, 128, 128)
      g.addColorStop(0, '#ffffff')
      g.addColorStop(0.6, '#bbbbbb')
      g.addColorStop(1, '#000000')
      fctx.fillStyle = g
      fctx.fillRect(0, 0, 256, 256)
    }
    const floor = new THREE.Mesh(
      new THREE.CircleGeometry(16, 64),
      new THREE.MeshStandardMaterial({ color: palette.floor, roughness: 0.95, transparent: true, alphaMap: new THREE.CanvasTexture(fade), depthWrite: false }),
    )
    floor.rotation.x = -Math.PI / 2
    floor.position.y = -0.02
    scene.add(floor)
    const grid = new THREE.GridHelper(28, 56, palette.brand, palette.grid)
    ;(grid.material as THREE.Material).transparent = true
    ;(grid.material as THREE.Material).opacity = resolved === 'dark' ? 0.28 : 0.4
    scene.add(grid)

    // The hub: a ringed core standing in for the utility grid.
    const hub = new THREE.Group()
    const core = new THREE.Mesh(
      new THREE.IcosahedronGeometry(0.55, 1),
      new THREE.MeshStandardMaterial({ color: palette.hub, emissive: palette.hub, emissiveIntensity: 0.6, roughness: 0.3, metalness: 0.5 }),
    )
    core.position.y = 1.1
    hub.add(core)
    const rings: THREE.Mesh[] = []
    for (let i = 0; i < 2; i += 1) {
      const ring = new THREE.Mesh(
        new THREE.TorusGeometry(0.95 + i * 0.35, 0.03, 8, 48),
        new THREE.MeshBasicMaterial({ color: palette.hub, transparent: true, opacity: 0.7 - i * 0.25 }),
      )
      ring.position.y = 1.1
      ring.rotation.x = Math.PI / 2 + i * 0.5
      rings.push(ring)
      hub.add(ring)
    }
    const hubBase = new THREE.Mesh(
      new THREE.CylinderGeometry(1.2, 1.3, 0.16, 6),
      new THREE.MeshStandardMaterial({ color: palette.floor, emissive: palette.hub, emissiveIntensity: 0.2, roughness: 0.6, metalness: 0.3 }),
    )
    hubBase.position.y = 0.08
    hub.add(hubBase)
    scene.add(hub)

    // ---- site objects, rebuilt when the site list changes -------------------
    const dynamic = new THREE.Group()
    scene.add(dynamic)
    interface SiteNode {
      site: SiteLive
      group: THREE.Group
      pillar: THREE.Mesh
      rim: THREE.Mesh
      position: THREE.Vector3
    }
    let nodes: SiteNode[] = []
    interface Flow {
      curve: THREE.QuadraticBezierCurve3
      particles: THREE.Points
      count: number
      speed: number
      direction: 1 | -1
    }
    let flows: Flow[] = []
    let signature = ''

    const disposeGroup = (group: THREE.Object3D) => {
      group.traverse((obj) => {
        const mesh = obj as THREE.Mesh
        mesh.geometry?.dispose?.()
        const material = mesh.material as THREE.Material | THREE.Material[] | undefined
        if (Array.isArray(material)) material.forEach((m) => m.dispose())
        else material?.dispose?.()
      })
    }

    const rebuild = () => {
      const list = dataRef.current
      const next = list
        .map((s) => `${s.site_id}:${s.parent_id ?? ''}:${s.demand_status}:${Math.round(s.flow.load_kw ?? 0)}:${Math.sign(s.flow.grid_kw ?? 0)}:${s.is_stale ? 1 : 0}`)
        .join('|')
      if (next === signature) return
      signature = next

      dynamic.children.slice().forEach((child) => {
        disposeGroup(child)
        dynamic.remove(child)
      })
      nodes = []
      flows = []

      const byId = new Map(list.map((s) => [s.site_id, s]))
      const roots = list.filter((s) => !s.parent_id || !byId.has(s.parent_id))
      const childrenOf = (id: string) => list.filter((s) => s.parent_id === id)
      const maxLoad = Math.max(1, ...list.map((s) => Math.abs(s.flow.load_kw ?? 0)))
      const positions = new Map<string, THREE.Vector3>()

      const innerRadius = 4.2 + Math.min(3, roots.length * 0.35)
      roots.forEach((root, index) => {
        const angle = (index / Math.max(1, roots.length)) * Math.PI * 2 - Math.PI / 2
        positions.set(root.site_id, new THREE.Vector3(Math.cos(angle) * innerRadius, 0, Math.sin(angle) * innerRadius))
        const kids = childrenOf(root.site_id)
        const spread = Math.min(Math.PI / 2, 0.45 * kids.length)
        kids.forEach((kid, k) => {
          const a = angle + (kids.length === 1 ? 0 : -spread / 2 + (k / (kids.length - 1)) * spread)
          const r = innerRadius + 3.4
          positions.set(kid.site_id, new THREE.Vector3(Math.cos(a) * r, 0, Math.sin(a) * r))
          // Grandchildren sit just beyond their parent; deeper levels share it.
          childrenOf(kid.site_id).forEach((gk, g) => {
            const ga = a + (g - (childrenOf(kid.site_id).length - 1) / 2) * 0.22
            positions.set(gk.site_id, new THREE.Vector3(Math.cos(ga) * (r + 2.4), 0, Math.sin(ga) * (r + 2.4)))
          })
        })
      })

      for (const site of list) {
        const position = positions.get(site.site_id)
        if (!position) continue
        const color = site.is_stale ? palette.unknown : statusColor(palette, site.demand_status)
        const group = new THREE.Group()
        group.position.copy(position)
        const isRoot = !site.parent_id || !byId.has(site.parent_id)
        const radius = isRoot ? 1.05 : 0.75

        const platform = new THREE.Mesh(
          new THREE.CylinderGeometry(radius, radius + 0.08, 0.16, 6),
          new THREE.MeshStandardMaterial({ color: palette.floor, emissive: color, emissiveIntensity: 0.18, roughness: 0.6, metalness: 0.3 }),
        )
        platform.position.y = 0.08
        group.add(platform)
        const rim = new THREE.Mesh(
          new THREE.TorusGeometry(radius + 0.04, 0.03, 8, 6),
          new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.9 }),
        )
        rim.rotation.x = Math.PI / 2
        rim.rotation.z = Math.PI / 6
        rim.position.y = 0.17
        group.add(rim)

        const load = Math.abs(site.flow.load_kw ?? 0)
        const pillarHeight = 0.35 + (load / maxLoad) * 2.6
        const pillar = new THREE.Mesh(
          new THREE.BoxGeometry(radius * 0.7, pillarHeight, radius * 0.7),
          new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.45, transparent: true, opacity: 0.85, roughness: 0.35, metalness: 0.4 }),
        )
        pillar.position.y = 0.16 + pillarHeight / 2
        group.add(pillar)

        if (site.open_alert_count > 0) {
          const halo = new THREE.Mesh(
            new THREE.RingGeometry(radius + 0.15, radius + 0.3, 32),
            new THREE.MeshBasicMaterial({ color: palette.over, transparent: true, opacity: 0.6, side: THREE.DoubleSide, depthWrite: false }),
          )
          halo.rotation.x = -Math.PI / 2
          halo.position.y = 0.02
          group.add(halo)
        }

        const text = label(site.site_name, palette.text)
        text.position.y = 0.16 + pillarHeight + 0.55
        group.add(text)
        dynamic.add(group)
        nodes.push({ site, group, pillar, rim, position })

        // Tether to the parent, beam to the hub for roots.
        const parentPos = site.parent_id ? positions.get(site.parent_id) : undefined
        const from = parentPos ?? new THREE.Vector3(0, 0, 0)
        const a = from.clone().setY(parentPos ? 0.3 : 1.1)
        const b = position.clone().setY(0.3)
        const gridKw = site.flow.grid_kw ?? 0
        const flowColor = gridKw < 0 ? palette.exporting : parentPos ? palette.tether : palette.hub
        const { line, curve } = beam(a, b, flowColor)
        dynamic.add(line)

        if (!site.is_stale && Math.abs(gridKw) > 0.05) {
          const count = 6 + Math.min(14, Math.round(Math.abs(gridKw) / 25))
          const geometry = new THREE.BufferGeometry()
          geometry.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(count * 3), 3))
          const particles = new THREE.Points(
            geometry,
            new THREE.PointsMaterial({ color: flowColor, size: 0.16, transparent: true, opacity: 0.95, depthWrite: false }),
          )
          dynamic.add(particles)
          flows.push({ curve, particles, count, speed: 0.12 + Math.min(0.4, Math.abs(gridKw) / 400), direction: gridKw < 0 ? -1 : 1 })
        }
      }
    }

    // ---- picking --------------------------------------------------------------
    const raycaster = new THREE.Raycaster()
    const pointer = new THREE.Vector2()
    const hitTest = (event: MouseEvent): SiteNode | null => {
      const rect = renderer.domElement.getBoundingClientRect()
      pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1)
      raycaster.setFromCamera(pointer, camera)
      for (const node of nodes) {
        if (raycaster.intersectObject(node.group, true).length > 0) return node
      }
      return null
    }
    let downAt = 0
    const onDown = () => { downAt = performance.now() }
    const onClick = (event: MouseEvent) => {
      if (performance.now() - downAt > 250) return
      const hit = hitTest(event)
      if (hit) cbRef.current?.(hit.site)
    }
    const onMove = (event: MouseEvent) => {
      renderer.domElement.style.cursor = hitTest(event) ? 'pointer' : 'default'
    }
    renderer.domElement.addEventListener('pointerdown', onDown)
    renderer.domElement.addEventListener('click', onClick)
    renderer.domElement.addEventListener('pointermove', onMove)

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

    const clock = new THREE.Clock()
    let frame = 0
    const tmp = new THREE.Vector3()
    const render = () => {
      const dt = Math.min(clock.getDelta(), 0.1)
      const elapsed = clock.elapsedTime
      rebuild()
      const count = dataRef.current.length
      const hasKids = dataRef.current.some((s) => s.parent_id)
      const distance = (hasKids ? 15 : 11) + Math.min(6, count * 0.4)
      const angle = reduced ? 0.4 : 0.4 + elapsed * 0.06
      camera.position.set(Math.sin(angle) * distance, distance * 0.6, Math.cos(angle) * distance)
      camera.lookAt(0, 0.4, 0)

      core.rotation.y += dt * 0.6
      core.rotation.x += dt * 0.2
      rings.forEach((ring, i) => { ring.rotation.z += dt * (0.4 + i * 0.3) })
      hubLight.intensity = 5 + (reduced ? 0 : Math.sin(elapsed * 2) * 1.2)
      for (const node of nodes) {
        const pulse = reduced ? 1 : 1 + 0.06 * Math.sin(elapsed * 2 + node.position.x)
        node.rim.scale.setScalar(pulse)
        if (node.site.demand_status === 'over' && !reduced) {
          ;(node.pillar.material as THREE.MeshStandardMaterial).emissiveIntensity = 0.45 + 0.35 * Math.abs(Math.sin(elapsed * 4))
        }
      }
      for (const flow of flows) {
        const attr = flow.particles.geometry.getAttribute('position') as THREE.BufferAttribute
        for (let i = 0; i < flow.count; i += 1) {
          let t = ((reduced ? 0 : elapsed * flow.speed) + i / flow.count) % 1
          if (flow.direction < 0) t = 1 - t
          flow.curve.getPoint(t, tmp)
          attr.setXYZ(i, tmp.x, tmp.y + 0.05, tmp.z)
        }
        attr.needsUpdate = true
      }
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
      disposeGroup(scene)
      renderer.dispose()
      if (renderer.domElement.parentNode === host) host.removeChild(renderer.domElement)
    }
  }, [resolved, height, onUnsupported])

  return <div ref={mount} style={{ height }} className="w-full overflow-hidden rounded-lg" data-testid="fleet-scene-3d" />
}

export default FleetScene3D
