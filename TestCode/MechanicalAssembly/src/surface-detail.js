// Object-space, derivative-filtered surface finish for CAD meshes without UVs.
// It changes shading only: source geometry and saved materials stay untouched.
export function addSurfaceDetail(material, finish) {
  if (
    !finish ||
    material.normalMap ||
    material.bumpMap ||
    material.roughnessMap
  )
    return;
  const brushed = finish === "brushed";
  const strength = finish === "rubber" ? 0.12 : brushed ? 0.14 : 0.065;
  material.onBeforeCompile = (shader) => {
    shader.uniforms.cadGrainStrength = { value: strength };
    shader.vertexShader = shader.vertexShader
      .replace(
        "#include <common>",
        `#include <common>
        varying vec3 vCadSurfacePosition;
        varying vec3 vCadSurfaceNormal;`,
      )
      .replace(
        "#include <begin_vertex>",
        `#include <begin_vertex>
        vCadSurfacePosition = position * vec3(length(modelMatrix[0].xyz),
          length(modelMatrix[1].xyz), length(modelMatrix[2].xyz));
        vCadSurfaceNormal = normal;`,
      );
    shader.fragmentShader = shader.fragmentShader
      .replace(
        "#include <common>",
        `#include <common>
        varying vec3 vCadSurfacePosition;
        varying vec3 vCadSurfaceNormal;
        uniform float cadGrainStrength;
        float cadHash(vec2 p) {
          vec3 q = fract(vec3(p.xyx) * 0.1031);
          q += dot(q, q.yzx + 33.33);
          return fract((q.x + q.y) * q.z);
        }
        float cadNoise(vec2 p) {
          vec2 i = floor(p), f = fract(p);
          f = f * f * (3.0 - 2.0 * f);
          return mix(mix(cadHash(i), cadHash(i + vec2(1,0)), f.x),
            mix(cadHash(i + vec2(0,1)), cadHash(i + vec2(1,1)), f.x), f.y);
        }
        float cadFilteredGrain(vec2 uv) {
          vec2 p = uv * ${brushed ? "vec2(6000.0, 100.0)" : "vec2(2500.0)"};
          float footprint = max(length(dFdx(p)), length(dFdy(p)));
          float detail = 1.0 - smoothstep(0.5, 2.5, footprint);
          return mix(0.5, cadNoise(p), detail);
        }`,
      )
      .replace(
        "#include <roughnessmap_fragment>",
        `#include <roughnessmap_fragment>
        vec3 cadWeights = pow(abs(normalize(vCadSurfaceNormal)), vec3(4.0));
        cadWeights /= max(dot(cadWeights, vec3(1.0)), 0.0001);
        float cadGrain = dot(cadWeights, vec3(
          cadFilteredGrain(vCadSurfacePosition.zy),
          cadFilteredGrain(vCadSurfacePosition.xz),
          cadFilteredGrain(vCadSurfacePosition.xy)));
        roughnessFactor = clamp(roughnessFactor +
          (cadGrain - 0.5) * cadGrainStrength, 0.045, 1.0);`,
      )
      .replace(
        "#include <normal_fragment_maps>",
        `#include <normal_fragment_maps>
        // Screen derivatives keep the finish attached to the part, without UVs.
        vec3 cadDx = dFdx(-vViewPosition), cadDy = dFdy(-vViewPosition);
        vec3 cadR1 = cross(cadDy, normal), cadR2 = cross(normal, cadDx);
        float cadDet = dot(cadDx, cadR1);
        float cadHeight = cadGrain * ${brushed ? "0.000012" : "0.000008"};
        vec3 cadGradient = sign(cadDet) *
          (dFdx(cadHeight) * cadR1 + dFdy(cadHeight) * cadR2);
        normal = normalize(normal - cadGradient / max(abs(cadDet), 1e-10));`,
      );
  };
  material.customProgramCacheKey = () => `cad-finish-v2-${finish}`;
  material.userData.surfaceFinish = finish;
}
