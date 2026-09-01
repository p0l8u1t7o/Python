import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { IxContentHeader, IxInput, IxPill, IxSpinner } from '@siemens/ix-react';
import {
  SEARCH_KINDS,
  SEARCH_KIND_LABEL,
  training,
  type SearchHit,
  type SearchKind,
} from '../training';

const KIND_COLOR: Record<SearchKind, string> = {
  card: '#00cccc',
  component: '#ffb100',
  lesson: '#b874ff',
  article: '#7ed957',
  project: '#ff8a5c',
};

/** 全站搜尋：一次搜知識卡、設備元件、課程章節、技術文檔與實戰題目。 */
export default function SearchPage() {
  const [params, setParams] = useSearchParams();
  const q = params.get('q') ?? '';
  const kind = (params.get('kind') ?? '') as SearchKind | '';
  const [draft, setDraft] = useState(q);
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  // 網址是唯一真相：改網址才觸發查詢，這樣重新整理／分享連結都能還原結果
  useEffect(() => setDraft(q), [q]);

  useEffect(() => {
    if (!q.trim()) {
      setHits([]);
      return;
    }
    setBusy(true);
    let stale = false;
    training
      .search(q)
      .then((r) => !stale && setHits(r))
      .catch(console.error)
      .finally(() => !stale && setBusy(false));
    return () => {
      stale = true;
    };
  }, [q]);

  // 輸入停 300ms 才寫回網址，避免每打一個字就查一次
  useEffect(() => {
    if (draft === q) return;
    const id = setTimeout(() => {
      const next = new URLSearchParams(params);
      if (draft.trim()) next.set('q', draft);
      else next.delete('q');
      setParams(next, { replace: true });
    }, 300);
    return () => clearTimeout(id);
  }, [draft, q, params, setParams]);

  const shown = kind ? hits.filter((h) => h.kind === kind) : hits;
  const countOf = (k: SearchKind) => hits.filter((h) => h.kind === k).length;

  const setKind = (k: SearchKind | '') => {
    const next = new URLSearchParams(params);
    if (k) next.set('kind', k);
    else next.delete('kind');
    setParams(next, { replace: true });
  };

  return (
    <div className="page">
      <IxContentHeader
        headerTitle="搜尋"
        headerSubtitle="元件名稱、料號、英文、功用、現場重點、教材內文、技術文檔、錯誤碼都搜得到。"
      />
      <div className="filter-bar">
        <IxInput
          placeholder="例如：磁簧、NPN、回原點、0x001B、-1073807339"
          value={draft}
          onValueChange={(e) => setDraft(e.detail)}
          style={{ width: 420 }}
        />
        {busy && <IxSpinner size="small" />}
      </div>

      {hits.length > 0 && (
        <div className="filter-bar">
          <IxPill
            variant={kind === '' ? 'primary' : 'neutral'}
            outline={kind !== ''}
            onClick={() => setKind('')}
            style={{ cursor: 'pointer' }}
          >
            全部 {hits.length}
          </IxPill>
          {SEARCH_KINDS.filter((k) => countOf(k) > 0).map((k) => (
            <IxPill
              key={k}
              variant={kind === k ? 'primary' : 'neutral'}
              outline={kind !== k}
              onClick={() => setKind(k)}
              style={{ cursor: 'pointer' }}
            >
              <span className="domain-dot" style={{ background: KIND_COLOR[k] }} />
              {SEARCH_KIND_LABEL[k]} {countOf(k)}
            </IxPill>
          ))}
        </div>
      )}

      {q.trim() && !busy && hits.length === 0 && (
        <p className="muted">找不到「{q}」。試試元件的英文名、料號前綴（MEC / ELE / SFT…）或錯誤碼。</p>
      )}

      <div className="hit-list">
        {shown.map((h, i) => (
          <button key={`${h.kind}-${h.url}-${i}`} type="button" className="hit" onClick={() => navigate(h.url)}>
            <span className="hit-kind" style={{ background: KIND_COLOR[h.kind] }}>
              {SEARCH_KIND_LABEL[h.kind]}
            </span>
            <span className="hit-body">
              <span className="hit-title">
                {h.title}
                {h.subtitle && <span className="hit-sub">{h.subtitle}</span>}
              </span>
              {h.snippet && <span className="hit-snippet">{h.snippet}</span>}
            </span>
            <span className="hit-badge">{h.badge}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
