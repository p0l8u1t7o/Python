// Node 端模組解析：與網頁 importmap 相同的三種名稱，讓檢查程式直接載入網頁用的同一份模組。
//   three          → core/vendor/three.module.js
//   three/addons/* → core/vendor/addons/*
//   @core/*        → core/*
// 用法：node --import <TestCode>/core/tools/register.mjs tools/verify.mjs
const CORE = new URL('../', import.meta.url);
const MAP = [
  ['three', new URL('vendor/three.module.js', CORE).href, true],
  ['three/addons/', new URL('vendor/addons/', CORE).href, false],
  ['@core/', CORE.href, false],
];

export async function resolve(specifier, context, next) {
  for (const [key, target, exact] of MAP) {
    if (exact ? specifier === key : specifier.startsWith(key)) return { url: exact ? target : target + specifier.slice(key.length), shortCircuit: true };
  }
  return next(specifier, context);
}
