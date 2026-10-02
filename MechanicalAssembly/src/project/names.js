// STEP 內的 Big5 中文名稱常被當成 UTF-8 解碼，變成「®ɳW¥ֱa」這類亂碼。
// 還原方式：可辨識的字元轉回原始位元組（Latin-1 字元取碼值、其餘取 UTF-8），再以 Big5 解碼。
let decoder;
try {
  decoder = new TextDecoder("big5");
} catch {
  decoder = null;
}
const encoder = new TextEncoder();

export function repairName(name) {
  if (!decoder || typeof name !== "string" || !/[\u0080-ÿ]/.test(name))
    return name;
  const bytes = [];
  for (const ch of name) {
    const code = ch.codePointAt(0);
    if (code <= 0xff) bytes.push(code);
    else bytes.push(...encoder.encode(ch));
  }
  let text = decoder.decode(Uint8Array.from(bytes));
  // 只接受完整還原，或僅結尾缺一個位元組的結果，避免顯示錯字
  if (text.endsWith("�") && text.indexOf("�") === text.length - 1)
    text = text.slice(0, -1);
  if (text.includes("�") || !/[㐀-鿿＀-￯]/.test(text))
    return name;
  return text;
}

/** 不嚴格的還原（可能含錯字），只用於分類判斷，不顯示給使用者。 */
export function looseName(name) {
  if (!decoder || typeof name !== "string" || !/[-ÿ]/.test(name))
    return name;
  const bytes = [];
  for (const ch of name) {
    const code = ch.codePointAt(0);
    if (code <= 0xff) bytes.push(code);
    else bytes.push(...encoder.encode(ch));
  }
  return decoder.decode(Uint8Array.from(bytes));
}

export function repairNames(root) {
  root.traverse((o) => {
    if (!o.name) return;
    const fixed = repairName(o.name);
    // 保留原始名稱：比對預先推論結果時不受各平台 Big5 解碼差異影響
    if (fixed !== o.name) {
      o.userData.sourceName = o.name;
      o.name = fixed;
    }
  });
  return root;
}
