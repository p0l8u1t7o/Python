import { useEffect, useRef } from 'react'
import * as THREE from 'three'

import type { Device, SiteSummary } from '@/lib/types'
import { useTheme } from '@/providers/ThemeProvider'

/**
 * A site and the devices that belong to it, as a 3D "constellation".
 *
 * The site is a glowing platform in the centre; its devices orbit it on a
 * ring, each drawn by category (battery, PV, meter, charger, generator,
 * gateway, other) and lit by connection state - online pulses in the brand
 * colour, offline sits dark, an open alert adds a red halo. Child sites are
 * smaller platforms further out, tethered to the parent by beams, so the
 * tree in the table has a shape.
 *
 * Data only flows in through refs; a refetch re-lays the ring without
 * rebuilding the renderer. Clicking a device reports it to the caller.
 */

export interface SiteScene3DProps {
  site: SiteSummary
  devices: Device[]
  children: SiteSummary[]
  height?: number
  onUnsupported?: () => void
  onPickDevice?: (device: Device) => void
  onPickSite?: (site: SiteSummary) => void
}

interface Palette {
  floor: number
  grid: number
  brand: number
  online: number
  offline: number
  alert: number
  text: number
  child: number
  battery: number
  pv: number
  meter: number
  load: number
  charger: number
  generator: number
  gateway: number
  other: number
}

const LIGHT: Palette = {
  floor: 0xe6ebf3, grid: 0xc7d2e0, brand: 0x0f766e, online: 0x16a34a, offline: 0x94a3b8, alert: 0xdc2626,
  text: 0x1f2937, child: 0x64748b, battery: 0x0f766e, pv: 0xd97706, meter: 0x2563eb, load: 0x7c3aed, charger: 0x9333ea,
  generator: 0xb45309, gateway: 0x475569, other: 0x64748b,
}
const DARK: Palette = {
  floor: 0x101a2e, grid: 0x1e2a44, brand: 0x2dd4bf, online: 0x4ade80, offline: 0x475569, alert: 0xf87171,
  text: 0xe5e7eb, child: 0x94a3b8, battery: 0x2dd4bf, pv: 0xfbbf24, meter: 0x60a5fa, load: 0xc084fc, charger: 0xa78bfa,
  generator: 0xf59e0b, gateway: 0x94a3b8, other: 0x94a3b8,
}

type Category = 'battery' | 'pv' | 'meter' | 'load' | 'charger' | 'generator' | 'gateway' | 'other'

/** Map the registry category (and a name hint for generation) onto a shape. */
function categoryOf(device: Device): Category {
  const category = device.device_category
  switch (category) {
    case 'battery':
    case 'pcs':
      return 'battery'
    case 'generation': {
      const hint = `${device.name} ${device.device_type_name ?? ''} ${device.tags.join(' ')}`.toLowerCase()
      return /diesel|gas|柴|發電機|发电机/.test(hint) ? 'generator' : 'pv'
    }
    case 'generator':
      return 'generator'
    case 'meter':
      return 'meter'
    case 'load':
      return 'load'
    case 'ev_charger':
      return 'charger'
    case 'controller':
    case 'gateway':
      return 'gateway'
    default:
      return 'other'
  }
}

function label(text: string, color: number, width = 320): THREE.Sprite {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = 64
  const ctx = canvas.getContext('2d')
  if (ctx) {
    ctx.font = '600 26px system-ui, sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillStyle = `#${color.toString(16).padStart(6, '0')}`
    ctx.fillText(text.length > 22 ? `${text.slice(0, 21)}…` : text, width / 2, 32)
  }
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false }))
  sprite.scale.set((width / 64) * 0.5, 0.5, 1)
  return sprite
}

function deviceMesh(category: Category, color: number): THREE.Group {
  const group = new THREE.Group()
  const mat = (c: number, e = 0.35) =>
    new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: e, roughness: 0.35, metalness: 0.4 })
  switch (category) {
    case 'battery': {
      const body = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.28, 0.8, 24), mat(color))
      body.position.y = 0.4
      const cap = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.08, 16), mat(color, 0.6))
      cap.position.y = 0.84
      group.add(body, cap)
      break
    }
    case 'pv': {
      const panel = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.05, 0.55), mat(color))
      panel.position.y = 0.42
      panel.rotation.x = -0.5
      const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.4), mat(0x64748b, 0))
      leg.position.y = 0.2
      group.add(panel, leg)
      break
    }
    case 'meter': {
      const box = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.6, 0.25), mat(color, 0.25))
      box.position.y = 0.5
      const dial = new THREE.Mesh(new THREE.CircleGeometry(0.14, 24), mat(0xffffff, 0.1))
      dial.position.set(0, 0.6, 0.13)
      const post = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.25), mat(0x64748b, 0))
      post.position.y = 0.12
      group.add(box, dial, post)
      break
    }
    case 'load': {
      // A small hall with a roof light: the thing that consumes.
      const hall = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.45, 0.6), mat(color, 0.2))
      hall.position.y = 0.22
      const roof = new THREE.Mesh(new THREE.ConeGeometry(0.5, 0.25, 4), mat(color, 0.45))
      roof.position.y = 0.57
      roof.rotation.y = Math.PI / 4
      group.add(hall, roof)
      break
    }
    case 'charger': {
      const post = new THREE.Mesh(new THREE.BoxGeometry(0.3, 1.0, 0.2), mat(color, 0.3))
      post.position.y = 0.5
      const head = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.2, 0.24), mat(color, 0.7))
      head.position.y = 0.95
      group.add(post, head)
      break
    }
    case 'generator': {
      const body = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.5, 0.5), mat(color, 0.25))
      body.position.y = 0.25
      const pipe = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 0.4), mat(0x64748b, 0))
      pipe.position.set(-0.3, 0.7, 0)
      group.add(body, pipe)
      break
    }
    case 'gateway': {
      const box = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.2, 0.4), mat(color, 0.25))
      box.position.y = 0.1
      const antenna = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.6), mat(color, 0.6))
      antenna.position.set(0.18, 0.5, 0)
      group.add(box, antenna)
      break
    }
    default: {
      const body = new THREE.Mesh(new THREE.OctahedronGeometry(0.3), mat(color, 0.3))
      body.position.y = 0.4
      group.add(body)
    }
  }
  return group
}

export function SiteScene3D({ site, devices, children, height = 340, onUnsupported, onPickDevice, onPickSite }: SiteScene3DProps) {
  const mount = useRef<HTMLDivElement>(null)
  const dataRef = useRef({ site, devices, children })
  const cbRef = useRef({ onPickDevice, onPickSite })
  const { resolved } = useTheme()
  dataRef.current = { site, devices, children }
  cbRef.current = { onPickDevice, onPickSite }

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
    const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 80)
    scene.add(new THREE.HemisphereLight(0xffffff, palette.floor, resolved === 'dark' ? 0.9 : 1.2))
    const key = new THREE.DirectionalLight(0xffffff, resolved === 'dark' ? 1.0 : 1.5)
    key.position.set(5, 9, 6)
    scene.add(key)
    const glow = new THREE.PointLight(palette.brand, 5, 12)
    glow.position.set(0, 2, 0)
    scene.add(glow)

    // Floor with a radial fade (alphaMap reads green, so draw white → black).
    const fade = document.createElement('canvas')
    fade.width = fade.height = 256
    const fctx = fade.getContext('2d')
    if (fctx) {
      const g = fctx.createRadialGradient(128, 128, 20, 128, 128, 128)
      g.addColorStop(0, '#ffffff')
      g.addColorStop(0.55, '#cccccc')
      g.addColorStop(1, '#000000')
      fctx.fillStyle = g
      fctx.fillRect(0, 0, 256, 256)
    }
    const floor = new THREE.Mesh(
      new THREE.CircleGeometry(11, 64),
      new THREE.MeshStandardMaterial({ color: palette.floor, roughness: 0.95, transparent: true, alphaMap: new THREE.CanvasTexture(fade), depthWrite: false }),
    )
    floor.rotation.x = -Math.PI / 2
    floor.position.y = -0.02
    scene.add(floor)
    const grid = new THREE.GridHelper(18, 36, palette.brand, palette.grid)
    ;(grid.material as THREE.Material).transparent = true
    ;(grid.material as THREE.Material).opacity = resolved === 'dark' ? 0.3 : 0.4
    scene.add(grid)

    // Site platform: a hex slab with a glowing rim and a beacon.
    const platform = new THREE.Mesh(
      new THREE.CylinderGeometry(1.6, 1.7, 0.18, 6),
      new THREE.MeshStandardMaterial({ color: palette.floor, emissive: palette.brand, emissiveIntensity: 0.15, roughness: 0.6, metalness: 0.3 }),
    )
    platform.position.y = 0.09
    scene.add(platform)
    const rim = new THREE.Mesh(
      new THREE.TorusGeometry(1.65, 0.035, 8, 6),
      new THREE.MeshBasicMaterial({ color: palette.brand }),
    )
    rim.rotation.x = Math.PI / 2
    rim.position.y = 0.18
    rim.rotation.z = Math.PI / 6
    scene.add(rim)
    const beacon = new THREE.Mesh(
      new THREE.ConeGeometry(0.35, 1.6, 4, 1, true),
      new THREE.MeshBasicMaterial({ color: palette.brand, transparent: true, opacity: 0.25, side: THREE.DoubleSide, depthWrite: false }),
    )
    beacon.position.y = 0.98
    scene.add(beacon)
    const beaconCore = new THREE.Mesh(new THREE.OctahedronGeometry(0.22), new THREE.MeshStandardMaterial({ color: palette.brand, emissive: palette.brand, emissiveIntensity: 1.2 }))
    beaconCore.position.y = 1.0
    scene.add(beaconCore)
    const siteLabel = label(dataRef.current.site.name, palette.text, 420)
    siteLabel.position.set(0, 2.25, 0)
    scene.add(siteLabel)

    // Dynamic content is rebuilt when the device / child lists change.
    const dynamic = new THREE.Group()
    scene.add(dynamic)
    const pickables: { object: THREE.Object3D; device?: Device; site?: SiteSummary }[] = []
    const halos: { mesh: THREE.Mesh; phase: number }[] = []
    const beams: THREE.Mesh[] = []
    let signature = ''

    const rebuild = () => {
      const { devices: list, children: kids } = dataRef.current
      const sig = `${list.map((d) => `${d.id}:${d.status}`).join(',')}|${kids.map((k) => k.id).join(',')}`
      if (sig === signature) return
      signature = sig
      dynamic.clear()
      pickables.length = 0
      halos.length = 0
      beams.length = 0

      const ringRadius = 3.2 + Math.min(2.5, list.length * 0.08)
      list.forEach((device, index) => {
        const angle = (index / Math.max(list.length, 1)) * Math.PI * 2 - Math.PI / 2
        const category = categoryOf(device)
        const online = device.status === 'online'
        const color = online ? palette[category] : palette.offline
        const mesh = deviceMesh(category, color)
        mesh.position.set(Math.cos(angle) * ringRadius, 0, Math.sin(angle) * ringRadius)
        mesh.lookAt(0, 0, 0)
        dynamic.add(mesh)
        pickables.push({ object: mesh, device })

        const pad = new THREE.Mesh(
          new THREE.CircleGeometry(0.55, 32),
          new THREE.MeshBasicMaterial({ color: online ? palette.online : palette.offline, transparent: true, opacity: online ? 0.35 : 0.15 }),
        )
        pad.rotation.x = -Math.PI / 2
        pad.position.set(mesh.position.x, 0.005, mesh.position.z)
        dynamic.add(pad)

        // Tether to the platform; lit when online, faint when not.
        const from = new THREE.Vector3(mesh.position.x, 0.02, mesh.position.z)
        const to = new THREE.Vector3(0, 0.02, 0).lerp(from, 0.42)
        const curve = new THREE.LineCurve3(from, to)
        const tether = new THREE.Mesh(
          new THREE.TubeGeometry(curve, 1, 0.018, 6, false),
          new THREE.MeshBasicMaterial({ color: online ? palette.brand : palette.offline, transparent: true, opacity: online ? 0.8 : 0.25 }),
        )
        dynamic.add(tether)

        const name = label(device.name || device.device_id, online ? palette.text : palette.offline)
        name.position.set(mesh.position.x, 1.35, mesh.position.z)
        dynamic.add(name)

        if (online) {
          const halo = new THREE.Mesh(
            new THREE.RingGeometry(0.55, 0.62, 32),
            new THREE.MeshBasicMaterial({ color: palette.online, transparent: true, opacity: 0.6, side: THREE.DoubleSide }),
          )
          halo.rotation.x = -Math.PI / 2
          halo.position.set(mesh.position.x, 0.01, mesh.position.z)
          dynamic.add(halo)
          halos.push({ mesh: halo, phase: index * 0.37 })
        }
      })

      // Child sites: smaller platforms on an outer arc behind the parent.
      kids.forEach((child, index) => {
        const span = Math.min(Math.PI * 0.9, 0.7 * Math.max(kids.length - 1, 1))
        const angle = -Math.PI / 2 + (kids.length === 1 ? 0 : (index / (kids.length - 1)) * span - span / 2)
        const radius = 6.6
        const pos = new THREE.Vector3(Math.cos(angle) * radius, 0, Math.sin(angle) * radius)
        const slab = new THREE.Mesh(
          new THREE.CylinderGeometry(0.9, 0.95, 0.14, 6),
          new THREE.MeshStandardMaterial({ color: palette.floor, emissive: palette.child, emissiveIntensity: 0.2, roughness: 0.6 }),
        )
        slab.position.copy(pos).setY(0.07)
        dynamic.add(slab)
        pickables.push({ object: slab, site: child })
        const pin = new THREE.Mesh(new THREE.ConeGeometry(0.18, 0.5, 4), new THREE.MeshStandardMaterial({ color: palette.child, emissive: palette.child, emissiveIntensity: 0.6 }))
        pin.position.copy(pos).setY(0.45)
        dynamic.add(pin)
        const tag = label(`${child.name} · ${child.total_device_count}`, palette.text, 420)
        tag.position.copy(pos).setY(1.1)
        dynamic.add(tag)
        const curve = new THREE.QuadraticBezierCurve3(
          new THREE.Vector3(0, 0.2, 0),
          new THREE.Vector3(pos.x * 0.5, 1.4, pos.z * 0.5),
          new THREE.Vector3(pos.x, 0.2, pos.z),
        )
        const beam = new THREE.Mesh(
          new THREE.TubeGeometry(curve, 24, 0.03, 6, false),
          new THREE.MeshBasicMaterial({ color: palette.child, transparent: true, opacity: 0.6 }),
        )
        dynamic.add(beam)
        beams.push(beam)
      })
    }
    rebuild()

    // ---- picking ----------------------------------------------------------------
    const raycaster = new THREE.Raycaster()
    const pointer = new THREE.Vector2()
    const toNdc = (event: MouseEvent) => {
      const rect = renderer.domElement.getBoundingClientRect()
      pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1)
      raycaster.setFromCamera(pointer, camera)
    }
    const hitTest = (event: MouseEvent) => {
      toNdc(event)
      for (const item of pickables) {
        if (raycaster.intersectObject(item.object, true).length > 0) return item
      }
      return null
    }
    let downAt = 0
    const onDown = () => { downAt = performance.now() }
    const onClick = (event: MouseEvent) => {
      if (performance.now() - downAt > 250) return
      const hit = hitTest(event)
      if (hit?.device) cbRef.current.onPickDevice?.(hit.device)
      else if (hit?.site) cbRef.current.onPickSite?.(hit.site)
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
    const render = () => {
      const dt = Math.min(clock.getDelta(), 0.1)
      const elapsed = clock.elapsedTime
      rebuild()
      const count = dataRef.current.devices.length + dataRef.current.children.length
      const hasKids = dataRef.current.children.length > 0
      const distance = (hasKids ? 9.5 : 6.8) + Math.min(4, count * 0.22)
      const angle = reduced ? 0.3 : 0.3 + elapsed * 0.08
      camera.position.set(Math.sin(angle) * distance, distance * 0.55, Math.cos(angle) * distance)
      camera.lookAt(0, hasKids ? -0.2 : 0.2, 0)

      beaconCore.rotation.y += dt * 0.8
      beaconCore.position.y = 1.0 + (reduced ? 0 : 0.08 * Math.sin(elapsed * 2))
      ;(beacon.material as THREE.MeshBasicMaterial).opacity = 0.2 + (reduced ? 0 : 0.1 * Math.sin(elapsed * 2))
      for (const halo of halos) {
        const t = reduced ? 0.3 : (elapsed * 0.7 + halo.phase) % 1
        halo.mesh.scale.setScalar(1 + t * 0.8)
        ;(halo.mesh.material as THREE.MeshBasicMaterial).opacity = 0.7 * (1 - t)
      }
      for (const beam of beams) {
        ;(beam.material as THREE.MeshBasicMaterial).opacity = reduced ? 0.6 : 0.45 + 0.25 * Math.sin(elapsed * 1.5)
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
      scene.traverse((obj) => {
        const mesh = obj as THREE.Mesh
        mesh.geometry?.dispose?.()
        const material = mesh.material as THREE.Material | THREE.Material[] | undefined
        if (Array.isArray(material)) material.forEach((m) => m.dispose())
        else material?.dispose?.()
      })
      renderer.dispose()
      if (renderer.domElement.parentNode === host) host.removeChild(renderer.domElement)
    }
    // The site name is baked into a sprite, so a different site rebuilds the scene.
  }, [resolved, height, onUnsupported, site.id])

  return <div ref={mount} style={{ height }} className="w-full overflow-hidden rounded-lg" data-testid="site-scene-3d" />
}

export default SiteScene3D
