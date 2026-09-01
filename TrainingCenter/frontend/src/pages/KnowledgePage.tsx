import { useEffect, useMemo, useState } from 'react';
import { IxContentHeader, IxInput, IxPill } from '@siemens/ix-react';
import KnowledgeCards from '../components/KnowledgeCards';
import {
  CATEGORIES,
  CATEGORY_COLOR,
  CATEGORY_LABEL,
  training,
  type CardCategory,
  type KnowledgeCard,
} from '../training';

/** 技術知識庫：185 張元件知識卡，依系統分類 + 全文關鍵字篩選。 */
export default function KnowledgePage() {
  const [cards, setCards] = useState<KnowledgeCard[]>([]);
  const [cat, setCat] = useState<CardCategory | ''>('');
  const [q, setQ] = useState('');

  useEffect(() => {
    training.listCards().then(setCards).catch(console.error);
  }, []);

  const kw = q.trim().toLowerCase();
  const filtered = useMemo(
    () =>
      cards.filter(
        (c) =>
          (!cat || c.category === cat) &&
          (!kw ||
            `${c.code}${c.name}${c.name_en}${c.function}${c.install_location}${c.tip}`
              .toLowerCase()
              .includes(kw)),
      ),
    [cards, cat, kw],
  );

  const countOf = (c: CardCategory | '') =>
    cards.filter((x) => (!c || x.category === c) && (!kw ||
      `${x.code}${x.name}${x.name_en}${x.function}${x.install_location}${x.tip}`
        .toLowerCase().includes(kw))).length;

  return (
    <div className="page">
      <IxContentHeader
        headerTitle="技術知識庫"
        headerSubtitle="每張卡講一個元件：它在做什麼、裝在哪裡、現場要注意什麼。點卡片展開細節。"
      />
      <div className="filter-bar">
        <IxInput
          placeholder="搜尋料號、名稱、英文、功用、重點…"
          value={q}
          onValueChange={(e) => setQ(e.detail)}
          style={{ width: 340 }}
        />
        <IxPill
          variant={cat === '' ? 'primary' : 'neutral'}
          outline={cat !== ''}
          onClick={() => setCat('')}
          style={{ cursor: 'pointer' }}
        >
          全部 {countOf('')}
        </IxPill>
        {CATEGORIES.map((c) => (
          <IxPill
            key={c}
            variant={cat === c ? 'primary' : 'neutral'}
            outline={cat !== c}
            onClick={() => setCat(c)}
            style={{ cursor: 'pointer' }}
          >
            <span className="domain-dot" style={{ background: CATEGORY_COLOR[c] }} />
            {CATEGORY_LABEL[c]} {countOf(c)}
          </IxPill>
        ))}
      </div>
      <KnowledgeCards cards={filtered} />
    </div>
  );
}
