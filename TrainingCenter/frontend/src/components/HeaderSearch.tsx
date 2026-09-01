import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { IxIcon } from '@siemens/ix-react';
import { iconSearch } from '@siemens/ix-icons/icons';
import { SEARCH_KIND_LABEL, training, type SearchHit, type SearchKind } from '../training';

const KIND_COLOR: Record<SearchKind, string> = {
  card: '#00cccc',
  component: '#ffb100',
  lesson: '#b874ff',
  article: '#7ed957',
  project: '#ff8a5c',
};

const QUICK = 7; // 下拉最多顯示幾筆，其餘到搜尋頁看

/** 橫幅右側的全站搜尋：邊打邊出結果，Enter 進完整搜尋頁。 */
export default function HeaderSearch() {
  const [q, setQ] = useState('');
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const pop = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLDivElement>(null);
  // 下拉用 portal 掛到 body：橫幅會裁切超出的內容，放在裡面會被切掉
  const [rect, setRect] = useState<{ top: number; right: number } | null>(null);
  const navigate = useNavigate();

  const place = useCallback(() => {
    const r = box.current?.getBoundingClientRect();
    if (r) setRect({ top: r.bottom + 6, right: window.innerWidth - r.right });
  }, []);

  useEffect(() => {
    if (!open) return;
    place();
    window.addEventListener('resize', place);
    return () => window.removeEventListener('resize', place);
  }, [open, place]);

  // 打字停 250ms 才查，避免每個字一次請求
  useEffect(() => {
    if (!q.trim()) {
      setHits([]);
      return;
    }
    let stale = false;
    const id = setTimeout(() => {
      training
        .search(q)
        .then((r) => {
          if (stale) return;
          setHits(r);
          setActive(0);
        })
        .catch(() => setHits([]));
    }, 250);
    return () => {
      stale = true;
      clearTimeout(id);
    };
  }, [q]);

  // 點外面就收起下拉
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!box.current?.contains(t) && !pop.current?.contains(t)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const go = (url: string) => {
    setOpen(false);
    navigate(url);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    const shown = hits.slice(0, QUICK);
    if (e.key === 'Escape') {
      setOpen(false);
      return;
    }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!shown.length) return;
      setOpen(true);
      setActive((i) => (i + (e.key === 'ArrowDown' ? 1 : shown.length - 1)) % shown.length);
      return;
    }
    if (e.key === 'Enter') {
      // 有選中的結果就直接跳過去，否則進完整搜尋頁
      if (open && shown[active]) go(shown[active].url);
      else if (q.trim()) go(`/search?q=${encodeURIComponent(q)}`);
    }
  };

  const shown = hits.slice(0, QUICK);

  return (
    <div className="hsearch" ref={box}>
      <IxIcon name={iconSearch} size="16" />
      <input
        type="search"
        value={q}
        placeholder="搜尋元件、料號、教材、錯誤碼…"
        aria-label="全站搜尋"
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
      />
      {open && q.trim() && rect && createPortal(
        <div className="hsearch-pop" ref={pop} style={{ top: rect.top, right: rect.right }}>
          {shown.map((h, i) => (
            <button
              key={`${h.kind}-${h.url}-${i}`}
              type="button"
              className={`hsearch-hit${i === active ? ' on' : ''}`}
              onMouseEnter={() => setActive(i)}
              onClick={() => go(h.url)}
            >
              <span className="hsearch-kind" style={{ background: KIND_COLOR[h.kind] }}>
                {SEARCH_KIND_LABEL[h.kind]}
              </span>
              <span className="hsearch-title">{h.title}</span>
              <span className="hsearch-badge">{h.badge}</span>
            </button>
          ))}
          {!shown.length && <div className="hsearch-empty">找不到「{q}」</div>}
          {hits.length > 0 && (
            <button type="button" className="hsearch-more" onClick={() => go(`/search?q=${encodeURIComponent(q)}`)}>
              查看全部 {hits.length} 筆結果
            </button>
          )}
        </div>,
        document.body,
      )}
    </div>
  );
}
