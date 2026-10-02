/* Heavy CAD tessellation runs off the UI thread. */
importScripts("/vendor/occt-import-js.js");
const engine = occtimportjs({ locateFile: (f) => "/vendor/" + f });
self.onmessage = async ({ data }) => {
  try {
    const occt = await engine;
    const ext = data.ext;
    const method = ["step", "stp"].includes(ext)
      ? "ReadStepFile"
      : ["igs", "iges"].includes(ext)
        ? "ReadIgesFile"
        : "ReadBrepFile";
    const result = occt[method](new Uint8Array(data.buffer), {
      linearUnit: "millimeter",
      linearDeflectionType: "absolute_value",
      linearDeflection: 0.08,
      angularDeflection: 0.22,
    });
    if (!result.success || !result.meshes?.length)
      throw new Error("CAD 解析失敗，請確認檔案包含有效的 3D 實體。");
    const transfers = [];
    result.meshes.forEach((m) => {
      m.attributes.position.array = new Float32Array(
        m.attributes.position.array,
      );
      transfers.push(m.attributes.position.array.buffer);
      if (m.attributes.normal) {
        m.attributes.normal.array = new Float32Array(m.attributes.normal.array);
        transfers.push(m.attributes.normal.array.buffer);
      }
      m.index.array = new Uint32Array(m.index.array);
      transfers.push(m.index.array.buffer);
    });
    self.postMessage({ result }, transfers);
  } catch (e) {
    self.postMessage({ error: e.message });
  }
};
