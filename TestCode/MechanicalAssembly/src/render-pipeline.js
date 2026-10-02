import * as THREE from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { GTAOPass } from "three/addons/postprocessing/GTAOPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";

class CadAOPass extends GTAOPass {
  _overrideVisibility() {
    super._overrideVisibility();
    this.scene.traverse((object) => {
      if (!object.isMesh || !object.visible) return;
      const materials = Array.isArray(object.material)
        ? object.material
        : [object.material];
      // Transparent covers must not become opaque blockers in the depth pass.
      if (materials.every((m) => m.transparent || m.transmission > 0)) {
        object.visible = false;
        this._visibilityCache.push(object);
      }
    });
  }
}

export class RenderPipeline {
  constructor(renderer, scene, camera) {
    this.renderer = renderer;
    const target = new THREE.WebGLRenderTarget(1, 1, {
      type: THREE.HalfFloatType,
      samples: 4,
    });
    this.composer = new EffectComposer(renderer, target);
    this.composer.addPass(new RenderPass(scene, camera));
    this.ao = new CadAOPass(
      scene,
      camera,
      1,
      1,
      undefined,
      {
        radius: 0.13,
        thickness: 0.035,
        distanceExponent: 1.5,
        distanceFallOff: 0.8,
        samples: 16,
      },
      { radius: 4, samples: 8 },
    );
    this.ao.blendIntensity = 0.72;
    this.composer.addPass(this.ao);
    this.composer.addPass(new OutputPass());
    this.width = this.height = 1;
    this.large = false;
    this.detailed = true;
  }
  resize(width, height) {
    this.width = width;
    this.height = height;
    const ratio = this.renderer.getPixelRatio();
    this.composer.setSize(width, height);
    const aoRatio = Math.min(ratio, this.large ? 0.6 : 1);
    this.ao.setSize(
      Math.max(1, Math.round(width * aoRatio)),
      Math.max(1, Math.round(height * aoRatio)),
    );
  }
  configure(detailed, triangles) {
    this.detailed = detailed;
    this.large = triangles > 4_000_000;
    this.ao.enabled = detailed && triangles > 0;
    this.ao.updateGtaoMaterial({ samples: this.large ? 8 : 16 });
    this.resize(this.width, this.height);
  }
  render() {
    this.composer.render();
  }
  dispose() {
    for (const pass of this.composer.passes) pass.dispose();
    this.ao.blendMaterial.dispose();
    this.ao.gtaoMaterial.dispose();
    this.composer.dispose();
  }
}
