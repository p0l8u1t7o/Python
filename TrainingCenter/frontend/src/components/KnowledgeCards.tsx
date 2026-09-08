import { useState } from 'react';
import { IxIcon } from '@siemens/ix-react';
import { iconInfo, iconLocation, iconWarning } from '@siemens/ix-icons/icons';
import { Inline } from './Markdown';
import { ComponentImage } from './ComponentImage';
import { CATEGORY_COLOR, CATEGORY_LABEL, type KnowledgeCard } from '../training';

/** 一張元件知識卡。點一下展開安裝位置與現場重點。 */
function Card({ card }: { card: KnowledgeCard }) {
  const [open, setOpen] = useState(false);
  return (
    <article
      className={`kcard${open ? ' open' : ''}`}
      tabIndex={0}
      role="button"
      aria-expanded={open}
      onClick={() => setOpen((v) => !v)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          setOpen((v) => !v);
        }
      }}
    >
      <div className="kcard-head">
        <span className="kcard-code" style={{ background: CATEGORY_COLOR[card.category] }}>
          {card.code}
        </span>
        <span className="kcard-cat">{CATEGORY_LABEL[card.category]}</span>
      </div>
      <ComponentImage item={card} className="kcard-photo" showCredit={open} />
      <h5>{card.name}</h5>
      <div className="kcard-en">{card.name_en}</div>
      <p className="kcard-fn">
        <IxIcon name={iconInfo} size="16" />
        <Inline>{card.function}</Inline>
      </p>
      {open && (
        <div className="kcard-more">
          <p>
            <IxIcon name={iconLocation} size="16" />
            <span>
              <b>位置</b>
              <Inline>{card.install_location}</Inline>
            </span>
          </p>
          {card.tip && (
            <p className="tip">
              <IxIcon name={iconWarning} size="16" />
              <span>
                <b>重點</b>
                <Inline>{card.tip}</Inline>
              </span>
            </p>
          )}
        </div>
      )}
    </article>
  );
}

export default function KnowledgeCards({ cards }: { cards: KnowledgeCard[] }) {
  if (!cards.length) return <div className="kcard-empty">沒有符合的元件。</div>;
  return (
    <div className="kcard-grid">
      {cards.map((c) => (
        <Card key={c.id} card={c} />
      ))}
    </div>
  );
}
