import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import type { MotionSpec } from './api'

interface SceneViewerProps {
  modelUrl: string | null
  motion: MotionSpec | null
}

function disposeObject(root: THREE.Object3D) {
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return
    object.geometry.dispose()
    const materials = Array.isArray(object.material) ? object.material : [object.material]
    materials.forEach((material) => material.dispose())
  })
}

export function SceneViewer({ modelUrl, motion }: SceneViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const playingRef = useRef(false)
  const [playing, setPlaying] = useState(false)
  const [modelResult, setModelResult] = useState<{
    url: string
    status: 'ready' | 'error'
  } | null>(null)
  useEffect(() => {
    playingRef.current = playing
  }, [playing])
  const loadState = !modelUrl
    ? 'empty'
    : modelResult?.url === modelUrl
      ? modelResult.status
      : 'loading'

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const scene = new THREE.Scene()
    scene.background = new THREE.Color('#08151c')
    const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 10_000)
    camera.up.set(0, 0, 1)
    camera.position.set(6, -8, 6)
    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.shadowMap.enabled = true
    container.appendChild(renderer.domElement)

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.target.set(0, 0, 1)
    controls.update()
    const grid = new THREE.GridHelper(12, 24, '#31505e', '#20343f')
    grid.rotation.x = Math.PI / 2
    scene.add(grid, new THREE.AxesHelper(2))
    scene.add(new THREE.HemisphereLight('#d8f5ff', '#10202a', 2.2))
    const keyLight = new THREE.DirectionalLight('#ffffff', 3)
    keyLight.position.set(5, -4, 8)
    keyLight.castShadow = true
    scene.add(keyLight)

    let loadedRoot: THREE.Object3D | null = null
    let basePosition: THREE.Vector3 | null = null
    let disposed = false
    if (modelUrl) {
      new GLTFLoader().load(
        modelUrl,
        (gltf) => {
          if (disposed) {
            disposeObject(gltf.scene)
            return
          }
          loadedRoot = gltf.scene
          loadedRoot.rotation.x = Math.PI / 2
          loadedRoot.updateMatrixWorld(true)
          let bounds = new THREE.Box3().setFromObject(loadedRoot)
          const size = bounds.getSize(new THREE.Vector3())
          const largestDimension = Math.max(size.x, size.y, size.z)
          if (largestDimension > 0) loadedRoot.scale.setScalar(4 / largestDimension)
          loadedRoot.updateMatrixWorld(true)
          bounds = new THREE.Box3().setFromObject(loadedRoot)
          const center = bounds.getCenter(new THREE.Vector3())
          loadedRoot.position.add(new THREE.Vector3(-center.x, -center.y, -bounds.min.z))
          basePosition = loadedRoot.position.clone()
          loadedRoot.traverse((object) => {
            if (object instanceof THREE.Mesh) {
              object.castShadow = true
              object.receiveShadow = true
            }
          })
          scene.add(loadedRoot)
          setModelResult({ url: modelUrl, status: 'ready' })
        },
        undefined,
        () => {
          if (!disposed) setModelResult({ url: modelUrl, status: 'error' })
        },
      )
    }

    const resize = () => {
      const width = Math.max(container.clientWidth, 1)
      const height = Math.max(container.clientHeight, 1)
      camera.aspect = width / height
      camera.updateProjectionMatrix()
      renderer.setSize(width, height, false)
    }
    const resizeObserver = new ResizeObserver(resize)
    resizeObserver.observe(container)
    resize()

    const clock = new THREE.Clock()
    let animationFrame = 0
    const render = () => {
      const track = motion?.tracks[0]
      if (loadedRoot && basePosition && track && playingRef.current) {
        const frames = track.keyframes
        const duration = frames.at(-1)?.time_seconds ?? 0
        if (duration > 0) {
          const time = clock.getElapsedTime() % duration
          const found = frames.findIndex((frame) => frame.time_seconds >= time)
          const nextIndex = Math.max(1, found < 0 ? frames.length - 1 : found)
          const before = frames[nextIndex - 1]
          const after = frames[nextIndex] ?? frames.at(-1)
          if (before && after && frames[0]) {
            const span = after.time_seconds - before.time_seconds
            const ratio = span > 0 ? (time - before.time_seconds) / span : 0
            const position = THREE.MathUtils.lerp(before.position, after.position, ratio)
            const positions = frames.map((frame) => frame.position)
            const range = Math.max(...positions) - Math.min(...positions)
            loadedRoot.position.x =
              basePosition.x + (range ? ((position - frames[0].position) / range) * 2 : 0)
          }
        }
      } else if (loadedRoot && basePosition) {
        loadedRoot.position.copy(basePosition)
      }
      controls.update()
      renderer.render(scene, camera)
      animationFrame = requestAnimationFrame(render)
    }
    render()

    return () => {
      disposed = true
      cancelAnimationFrame(animationFrame)
      resizeObserver.disconnect()
      controls.dispose()
      if (loadedRoot) disposeObject(loadedRoot)
      renderer.dispose()
      renderer.domElement.remove()
    }
  }, [modelUrl, motion])

  return (
    <div className="viewer-root" ref={containerRef}>
      <div className={`viewer-state ${loadState}`}>
        {loadState === 'empty' && '上傳 GLB 以啟用 3D 預覽'}
        {loadState === 'loading' && 'GLB 載入中…'}
        {loadState === 'ready' && '模型已載入 · Z-up · Orbit controls'}
        {loadState === 'error' && 'GLB 無法載入，請檢查檔案內容'}
      </div>
      {loadState === 'ready' && motion && (
        <button className="motion-toggle" type="button" onClick={() => setPlaying((value) => !value)}>
          {playing ? '停止動作' : '播放 MotionSpec'}
        </button>
      )}
    </div>
  )
}
