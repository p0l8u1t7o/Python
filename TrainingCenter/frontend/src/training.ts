/** 教育訓練（LMS）API 客戶端。寫入類請求需要 Django session + CSRF token。 */

export type CardCategory = 'mech' | 'pne' | 'elec' | 'soft' | 'cnv' | 'arm' | 'aoi' | 'fcs';

export interface KnowledgeCard {
  id: number;
  code: string;
  category: CardCategory;
  name: string;
  name_en: string;
  function: string;
  install_location: string;
  tip: string;
  photo: string | null;
  photo_credit: string;
  photo_source_url: string;
  component_ids: number[];
}

export interface IdentificationGuide {
  id: number;
  look: string;
  tell: string;
  key_fields: string;
  common_mistake: string;
  candidates: KnowledgeCard[];
}

export interface LessonSummary {
  id: number;
  slug: string;
  title: string;
  summary: string;
  card_category: string;
  equipment_slug: string | null;
  card_count: number;
  completed: boolean;
}

export interface Lesson extends LessonSummary {
  content_markdown: string;
  video_url: string;
  cards: KnowledgeCard[];
}

export interface Course {
  id: number;
  slug: string;
  title: string;
  description: string;
  level: number;
  lessons: LessonSummary[];
  locked: boolean;
  completed_count: number;
}

export interface Question {
  id: number;
  prompt: string;
  options: string[];
  answered_index: number | null;
  answered_correct: boolean | null;
}

export interface AnswerResult {
  correct: boolean;
  answer_index: number;
  explanation: string;
}

export interface ProjectSummary {
  id: number;
  slug: string;
  title: string;
  level: number;
  summary: string;
  course_slug: string | null;
  my_status: string | null;
}

export interface Project extends ProjectSummary {
  spec_markdown: string;
  acceptance_markdown: string;
}

export interface Submission {
  id: number;
  project_slug: string;
  project_title: string;
  student: string;
  repo_url: string;
  note: string;
  status: 'submitted' | 'under_review' | 'passed' | 'rejected';
  mentor_feedback: string;
  score: number | null;
  submitted_at: string;
  reviewed_at: string | null;
}

export interface Article {
  id: number;
  slug: string;
  title: string;
  category: ArticleCategory;
  tags: string[];
  summary: string;
  updated_at: string;
  author: string | null;
  content_markdown?: string;
}

export type ArticleCategory = 'hardware' | 'vision' | 'motion' | 'software' | 'troubleshooting';

export type SearchKind = 'card' | 'component' | 'lesson' | 'article' | 'project';

export interface SearchHit {
  kind: SearchKind;
  title: string;
  subtitle: string;
  snippet: string;
  badge: string;
  url: string;
  score: number;
}

export interface Me {
  authenticated: boolean;
  username: string;
  display_name: string;
  role: 'student' | 'mentor' | 'admin' | '';
  department: string;
  lessons_done: number;
  lessons_total: number;
  quiz_correct: number;
  quiz_answered: number;
}

export const CATEGORY_LABEL: Record<CardCategory, string> = {
  mech: '機構',
  pne: '氣路',
  elec: '電控',
  soft: '軟體',
  cnv: '輸送帶模組',
  arm: '機械手臂',
  aoi: 'AOI 光學',
  fcs: '氫燃料電池',
};

export const CATEGORY_COLOR: Record<CardCategory, string> = {
  mech: '#00cccc',
  pne: '#4aa3ff',
  elec: '#ffb100',
  soft: '#b874ff',
  cnv: '#7ed957',
  arm: '#ff8a5c',
  aoi: '#ff6fae',
  fcs: '#3ddc97',
};

export const CATEGORIES = Object.keys(CATEGORY_LABEL) as CardCategory[];

export const STATUS_LABEL: Record<Submission['status'], string> = {
  submitted: '已提交',
  under_review: '審核中',
  passed: '通過',
  rejected: '退回',
};

export const ARTICLE_CATEGORY_LABEL: Record<ArticleCategory, string> = {
  hardware: '硬體與通訊',
  vision: '視覺與 AI',
  motion: '運動控制',
  software: '軟體與系統',
  troubleshooting: '除錯與 Log 分析',
};

export const ARTICLE_CATEGORIES = Object.keys(ARTICLE_CATEGORY_LABEL) as ArticleCategory[];

export const SEARCH_KIND_LABEL: Record<SearchKind, string> = {
  card: '元件知識卡',
  component: '設備元件',
  lesson: '課程章節',
  article: '技術文檔',
  project: '實戰題目',
};

export const SEARCH_KINDS = Object.keys(SEARCH_KIND_LABEL) as SearchKind[];

export const ROLE_LABEL: Record<string, string> = {
  student: '學員',
  mentor: '導師',
  admin: '管理員',
};

const BASE = '/api/training';

function cookie(name: string): string | null {
  const m = document.cookie.match(new RegExp(`(?:^|;\\s*)${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : null;
}

/**
 * 每次都從 cookie 現讀 CSRF token，不快取。
 * Django 在 login()／logout() 會輪替 token，快取住的舊值會讓之後的 POST 全部 403。
 */
async function getCsrf(): Promise<string> {
  const fromCookie = cookie('csrftoken');
  if (fromCookie) return fromCookie;
  const res = await fetch(`${BASE}/csrf`);
  return (await res.json()).csrf_token as string;
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* 非 JSON 回應就沿用狀態碼 */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

async function get<T>(path: string): Promise<T> {
  return parse<T>(await fetch(BASE + path));
}

async function send<T>(path: string, method: 'POST' | 'DELETE', body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': await getCsrf() },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return parse<T>(res);
}

const qs = (params: Record<string, string | number | undefined>) => {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') s.set(k, String(v));
  return s.toString() ? `?${s}` : '';
};

export const training = {
  // 知識庫
  listCards: (p: { category?: string; q?: string; component_id?: number } = {}) =>
    get<KnowledgeCard[]>(`/cards${qs(p)}`),
  listIdentification: () => get<IdentificationGuide[]>('/identification'),
  listArticles: (p: { category?: string; tag?: string; q?: string } = {}) =>
    get<Article[]>(`/articles${qs(p)}`),
  getArticle: (slug: string) => get<Required<Article>>(`/articles/${slug}`),
  listTags: () => get<string[]>('/tags'),
  search: (q: string, kind = '') => get<SearchHit[]>(`/search${qs({ q, kind })}`),

  // 課程
  listCourses: () => get<Course[]>('/courses'),
  getLesson: (course: string, lesson: string) => get<Lesson>(`/courses/${course}/lessons/${lesson}`),
  completeLesson: (id: number) => send<{ ok: boolean; detail: string }>(`/lessons/${id}/complete`, 'POST'),
  uncompleteLesson: (id: number) => send<{ ok: boolean; detail: string }>(`/lessons/${id}/complete`, 'DELETE'),

  // 測驗
  listQuiz: () => get<Question[]>('/quiz'),
  answer: (id: number, chosen_index: number) =>
    send<AnswerResult>(`/quiz/${id}/answer`, 'POST', { chosen_index }),

  // Mini Project
  listProjects: () => get<ProjectSummary[]>('/projects'),
  getProject: (slug: string) => get<Project>(`/projects/${slug}`),
  submitProject: (slug: string, repo_url: string, note: string) =>
    send<Submission>(`/projects/${slug}/submit`, 'POST', { repo_url, note }),
  listSubmissions: (p: { project?: string; status?: string } = {}) =>
    get<Submission[]>(`/submissions${qs(p)}`),
  review: (id: number, status: string, mentor_feedback: string, score: number | null) =>
    send<Submission>(`/submissions/${id}/review`, 'POST', { status, mentor_feedback, score }),

  // 身分
  me: () => get<Me>('/me'),
  login: (username: string, password: string) => send<Me>('/auth/login', 'POST', { username, password }),
  logout: () => send<{ ok: boolean }>('/auth/logout', 'POST'),
  register: (username: string, password: string, display_name: string, department: string) =>
    send<Me>('/auth/register', 'POST', { username, password, display_name, department }),
};
