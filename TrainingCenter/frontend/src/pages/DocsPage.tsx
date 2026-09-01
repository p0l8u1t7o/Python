import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { IxButton, IxContentHeader, IxInput, IxPill } from '@siemens/ix-react';
import Markdown from '../components/Markdown';
import {
  ARTICLE_CATEGORIES,
  ARTICLE_CATEGORY_LABEL,
  training,
  type Article,
  type ArticleCategory,
} from '../training';

/** 技術文檔庫：依分類與標籤篩選，內文以 Markdown 呈現。 */
export default function DocsPage() {
  const { slug } = useParams();
  return slug ? <ArticleView slug={slug} /> : <ArticleList />;
}

function ArticleList() {
  const [articles, setArticles] = useState<Article[]>([]);
  const [cat, setCat] = useState<ArticleCategory | ''>('');
  const [tag, setTag] = useState('');
  const [q, setQ] = useState('');
  const navigate = useNavigate();

  useEffect(() => {
    training.listArticles().then(setArticles).catch(console.error);
  }, []);

  const kw = q.trim().toLowerCase();
  const filtered = useMemo(
    () =>
      articles.filter(
        (a) =>
          (!cat || a.category === cat) &&
          (!tag || a.tags.includes(tag)) &&
          (!kw || `${a.title}${a.summary}${a.tags.join('')}`.toLowerCase().includes(kw)),
      ),
    [articles, cat, tag, kw],
  );

  // 標籤雲只顯示目前分類底下實際用到的標籤
  const tags = useMemo(() => {
    const inCat = articles.filter((a) => !cat || a.category === cat);
    return [...new Set(inCat.flatMap((a) => a.tags))].sort((a, b) => a.localeCompare(b));
  }, [articles, cat]);

  return (
    <div className="page">
      <IxContentHeader
        headerTitle="技術知識庫"
        headerSubtitle="現場整理出來的技術文檔：通訊協定、運動控制、視覺、除錯與錯誤碼速查。"
      />
      <div className="filter-bar">
        <IxInput
          placeholder="搜尋標題、摘要、標籤…"
          value={q}
          onValueChange={(e) => setQ(e.detail)}
          style={{ width: 320 }}
        />
        <IxPill
          variant={cat === '' ? 'primary' : 'neutral'}
          outline={cat !== ''}
          onClick={() => {
            setCat('');
            setTag('');
          }}
          style={{ cursor: 'pointer' }}
        >
          全部 {articles.length}
        </IxPill>
        {ARTICLE_CATEGORIES.map((c) => {
          const n = articles.filter((a) => a.category === c).length;
          if (!n) return null;
          return (
            <IxPill
              key={c}
              variant={cat === c ? 'primary' : 'neutral'}
              outline={cat !== c}
              onClick={() => {
                setCat(c);
                setTag('');
              }}
              style={{ cursor: 'pointer' }}
            >
              {ARTICLE_CATEGORY_LABEL[c]} {n}
            </IxPill>
          );
        })}
      </div>

      <div className="tag-cloud">
        {tags.map((t) => (
          <button
            key={t}
            type="button"
            className={`tag${tag === t ? ' on' : ''}`}
            onClick={() => setTag(tag === t ? '' : t)}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="doc-list">
        {filtered.map((a) => (
          <article key={a.slug} className="doc-card" onClick={() => navigate(`/docs/${a.slug}`)}>
            <header>
              <span className="doc-cat">{ARTICLE_CATEGORY_LABEL[a.category]}</span>
              <h4>{a.title}</h4>
            </header>
            <p>{a.summary}</p>
            <div className="doc-tags">
              {a.tags.map((t) => (
                <span key={t} className="tag sm">
                  {t}
                </span>
              ))}
            </div>
          </article>
        ))}
        {!filtered.length && <p className="muted">沒有符合的文檔。</p>}
      </div>
    </div>
  );
}

function ArticleView({ slug }: { slug: string }) {
  const [article, setArticle] = useState<Article | null>(null);
  const [missing, setMissing] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    setMissing(false);
    training
      .getArticle(slug)
      .then(setArticle)
      .catch(() => setMissing(true));
  }, [slug]);

  if (missing) return <div className="page">找不到這篇文檔。</div>;
  if (!article) return <div className="page">載入中…</div>;

  return (
    <div className="page">
      <IxContentHeader headerTitle={article.title} headerSubtitle={article.summary} />
      <div className="lesson-actions">
        <IxButton variant="subtle-secondary" onClick={() => navigate('/docs')}>
          回文檔列表
        </IxButton>
        <span className="doc-cat">{ARTICLE_CATEGORY_LABEL[article.category]}</span>
        <div className="doc-tags">
          {article.tags.map((t) => (
            <span key={t} className="tag sm">
              {t}
            </span>
          ))}
        </div>
      </div>
      <Markdown>{article.content_markdown ?? ''}</Markdown>
    </div>
  );
}
