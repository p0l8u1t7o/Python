export type Domain = 'mechanical' | 'electrical' | 'software' | 'utility';

export interface Component {
  id: number;
  slug: string;
  name: string;
  category: string;
  brand: string;
  part_number: string;
  function: string;
  install_location: string;
  specs: Record<string, string>;
  photo: string | null;
  photo_credit: string;
  photo_source_url: string;
  model_file: string | null;
  pos: [number, number, number];
  mesh_name: string;
  animation_key: string;
}

export interface Module {
  id: number;
  slug: string;
  name: string;
  domain: Domain;
  description: string;
  diagram: string | null;
  components: Component[];
}

export interface EquipmentSummary {
  id: number;
  slug: string;
  name: string;
  summary: string;
  scene_key: string;
  hero_image: string | null;
  component_count: number;
}

export interface Equipment extends EquipmentSummary {
  description: string;
  model_file: string | null;
  utility_guide: GuideSection[];
  modules: Module[];
}

export const DOMAIN_LABEL: Record<Domain, string> = {
  mechanical: '機構',
  electrical: '電控',
  software: '軟體',
  utility: '水氣電',
};

export const DOMAINS: Domain[] = ['mechanical', 'electrical', 'software', 'utility'];

export interface GuideSection {
  title: string;
  icon: string;
  items: string[];
}

export const DOMAIN_COLOR: Record<Domain, string> = {
  mechanical: '#00cccc',
  electrical: '#ffb100',
  software: '#b874ff',
  utility: '#4aa3ff',
};

async function get<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export const api = {
  listEquipment: () => get<EquipmentSummary[]>('/api/equipment'),
  getEquipment: (slug: string) => get<Equipment>(`/api/equipment/${slug}`),
  search: (q: string) => get<Component[]>(`/api/search?q=${encodeURIComponent(q)}`),
};
