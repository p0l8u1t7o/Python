import { useEffect, useState } from 'react';
import KnowledgeCards from './KnowledgeCards';
import { Inline } from './Markdown';
import { training, type IdentificationGuide } from '../training';

/** 來料辨識互動面板：左邊挑外觀，右邊出辨識重點與候選元件。 */
export default function IdentificationPanel() {
  const [guides, setGuides] = useState<IdentificationGuide[]>([]);
  const [picked, setPicked] = useState<IdentificationGuide | null>(null);

  useEffect(() => {
    training.listIdentification().then(setGuides).catch(console.error);
  }, []);

  return (
    <div className="ident-layout">
      <div className="ident-list">
        {guides.map((g) => (
          <button
            key={g.id}
            type="button"
            className={`ident-btn${picked?.id === g.id ? ' on' : ''}`}
            onClick={() => setPicked(g)}
          >
            {g.look}
          </button>
        ))}
      </div>
      <div className="ident-out">
        {!picked ? (
          <p className="ident-hint">先從左邊挑一個最像你手上那顆的外觀描述。</p>
        ) : (
          <>
            <h4>怎麼確定是哪一種</h4>
            <p>
              <Inline>{picked.tell}</Inline>
            </p>
            <h4>一定要核對的欄位</h4>
            <p>
              <Inline>{picked.key_fields}</Inline>
            </p>
            <h4 className="warn">最常見的收錯</h4>
            <p>
              <Inline>{picked.common_mistake}</Inline>
            </p>
            <h4>可能是這些元件</h4>
            <KnowledgeCards cards={picked.candidates} />
          </>
        )}
      </div>
    </div>
  );
}
