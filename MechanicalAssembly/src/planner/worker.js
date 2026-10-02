// 組裝順序推論在背景執行緒進行，避免大型模型卡住介面。
import { deserializeAssembly } from "./extract.js";
import { planAssembly } from "./sequence.js";

self.onmessage = ({ data }) => {
  try {
    let last = 0;
    const result = planAssembly(deserializeAssembly(data.assembly), {
      up: data.up,
      onProgress(done, total, label) {
        const now = Date.now();
        if (now - last < 150 && done < total) return;
        last = now;
        self.postMessage({ progress: { done, total, label } });
      },
    });
    self.postMessage({ result });
  } catch (e) {
    self.postMessage({ error: e.message || String(e) });
  }
};
