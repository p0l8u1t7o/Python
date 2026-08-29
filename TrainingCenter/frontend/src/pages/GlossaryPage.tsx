import { useEffect, useMemo, useState } from 'react';
import { IxCard, IxCardContent, IxContentHeader, IxInput, IxPill, IxTabItem, IxTabs, IxTypography } from '@siemens/ix-react';
import { useOutletContext } from 'react-router-dom';
import { api, type Component, type Domain, type Equipment, type EquipmentSummary, DOMAIN_COLOR, DOMAIN_LABEL, DOMAINS } from '../api';
import { MechanismAnimation } from '../components/Animations';

interface Row extends Component {
  equipmentName: string;
  moduleName: string;
  domain: Domain;
}

/** 跨設備的元件字典：依領域分頁，再用類別（機械手臂部件／輸送帶模組／氣路元件／接頭…）與關鍵字過濾。 */
export default function GlossaryPage() {
  const { equipment } = useOutletContext<{ equipment: EquipmentSummary[] }>();
  const [rows, setRows] = useState<Row[]>([]);
  const [domain, setDomain] = useState<Domain | 'all'>('all');
  const [q, setQ] = useState('');
  const [cat, setCat] = useState<string>('');

  useEffect(() => {
    Promise.all(equipment.map((e) => api.getEquipment(e.slug))).then((all: Equipment[]) => {
      setRows(
        all.flatMap((eq) =>
          eq.modules.flatMap((m) =>
            m.components.map((c) => ({ ...c, equipmentName: eq.name, moduleName: m.name, domain: m.domain })),
          ),
        ),
      );
    });
  }, [equipment]);

  const inDomain = useMemo(() => rows.filter((r) => domain === 'all' || r.domain === domain), [rows, domain]);
  const categories = useMemo(() => [...new Set(inDomain.map((r) => r.category).filter(Boolean))].sort(), [inDomain]);
  const filtered = inDomain.filter(
    (r) =>
      (!cat || r.category === cat) &&
      (!q || `${r.name}${r.function}${r.brand}${r.part_number}`.toLowerCase().includes(q.toLowerCase())),
  );
  const count = (d: Domain | 'all') => rows.filter((r) => d === 'all' || r.domain === d).length;

  return (
    <div className="page">
      <IxContentHeader headerTitle="元件字典" headerSubtitle="所有設備的元件一覽，依機構／電控／軟體／水氣電分頁，再依類別過濾。" />
      <IxTabs activeTabKey={domain} onTabChange={(e) => { setDomain((e.detail as Domain | 'all') ?? 'all'); setCat(''); }}>
        <IxTabItem tabKey="all">全部<span className="tab-count">{count('all')}</span></IxTabItem>
        {DOMAINS.map((d) => (
          <IxTabItem key={d} tabKey={d}>
            <span className="domain-dot" style={{ background: DOMAIN_COLOR[d] }} />
            {DOMAIN_LABEL[d]}
            <span className="tab-count">{count(d)}</span>
          </IxTabItem>
        ))}
      </IxTabs>
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center', margin: '1rem 0' }}>
        <IxInput placeholder="搜尋名稱、功用、品牌、型號…" value={q} onValueChange={(e) => setQ(e.detail)} style={{ width: 320 }} />
        <IxPill variant={cat === '' ? 'primary' : 'neutral'} outline={cat !== ''} onClick={() => setCat('')} style={{ cursor: 'pointer' }}>
          全部類別
        </IxPill>
        {categories.map((c) => (
          <IxPill key={c} variant={cat === c ? 'primary' : 'neutral'} outline={cat !== c} onClick={() => setCat(c)} style={{ cursor: 'pointer' }}>
            {c}
          </IxPill>
        ))}
      </div>
      <IxTypography format="body-sm" textColor="soft">{filtered.length} 筆</IxTypography>
      <div className="glossary-grid" style={{ marginTop: '0.5rem' }}>
        {filtered.map((r) => (
          <IxCard key={r.id}>
            <IxCardContent>
              <div style={{ display: 'grid', gridTemplateColumns: r.photo ? '72px 1fr' : '1fr', gap: '0.6rem', alignItems: 'start' }}>
                {r.photo && <img src={r.photo} alt={r.name} style={{ width: 72, height: 72, objectFit: 'cover', borderRadius: 4 }} />}
                <div>
                  <IxTypography format="h5">{r.name}</IxTypography>
                  <IxTypography format="body-sm" textColor="soft">
                    <span className="domain-dot" style={{ background: DOMAIN_COLOR[r.domain] }} />
                    {r.equipmentName} › {r.moduleName}
                  </IxTypography>
                </div>
              </div>
              <IxTypography format="body-sm" style={{ margin: '0.5rem 0' }}>{r.function}</IxTypography>
              {r.animation_key && (
                <div className="animation-box">
                  <MechanismAnimation animationKey={r.animation_key} />
                </div>
              )}
              <div style={{ display: 'flex', gap: '0.25rem', flexWrap: 'wrap', marginTop: '0.5rem' }}>
                {r.category && <IxPill variant="neutral" outline>{r.category}</IxPill>}
                {r.brand && <IxPill variant="info" outline>{r.brand}</IxPill>}
              </div>
            </IxCardContent>
          </IxCard>
        ))}
      </div>
    </div>
  );
}
