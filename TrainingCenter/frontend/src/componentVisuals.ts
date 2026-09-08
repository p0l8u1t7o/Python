import manifest from './assets/component-visuals.json';

export function componentVisual(item: { slug?: string; code?: string }) {
  const model = item.code
    ? (manifest.cards as Record<string, string>)[item.code]
    : item.slug ? (manifest.components as Record<string, string>)[item.slug] : undefined;
  if (!model) return null;
  const base = `${import.meta.env.BASE_URL}component-visuals/${model}`;
  return { model: `${base}.glb`, thumbnail: `${base}.png`, conceptual: model.startsWith('software_') };
}
