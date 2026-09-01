import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { IxCard, IxCardContent, IxContentHeader, IxPill, IxSpinner, IxTabItem, IxTabs, IxTypography } from '@siemens/ix-react';
import { api, type Component, type Domain, type Equipment, DOMAIN_COLOR, DOMAIN_LABEL, DOMAINS } from '../api';
import { Viewer, type HotspotItem } from '../three/Viewer';
import { ComponentDetail } from '../components/ComponentDetail';

const GUIDE_ICON: Record<string, string> = { bolt: '⚡', air: '💨', water: '💧', gas: '🔥', lock: '🔒', robot: '🦾' };

export default function EquipmentPage() {
  const { slug = '' } = useParams();
  const [params] = useSearchParams();
  const [eq, setEq] = useState<Equipment | null>(null);
  const [domain, setDomain] = useState<Domain>('mechanical');
  const [selected, setSelected] = useState<Component | null>(null);
  const layoutRef = useRef<HTMLDivElement>(null);
  const pendingScroll = useRef<number | null>(null);

  useEffect(() => {
    setEq(null);
    setSelected(null);
    setDomain('mechanical');
    api.getEquipment(slug).then(setEq).catch(console.error);
  }, [slug]);

  // 從全站搜尋帶 ?component=<id> 進來時，載入後直接選取並捲到該元件
  const wanted = params.get('component');
  useEffect(() => {
    if (!eq || !wanted) return;
    const id = Number(wanted);
    for (const m of eq.modules) {
      const c = m.components.find((x) => x.id === id);
      if (c) {
        setSelected(c);
        setDomain(m.domain);
        pendingScroll.current = c.id;
        return;
      }
    }
  }, [eq, wanted]);

  // 3D 可點選全部元件（不限目前分頁）；清單只顯示目前分頁
  const allHotspots: HotspotItem[] = useMemo(
    () => (eq ? eq.modules.flatMap((m) => m.components.map((c) => ({ component: c, domain: m.domain }))) : []),
    [eq],
  );
  const modules = useMemo(() => (eq ? eq.modules.filter((m) => m.domain === domain) : []), [eq, domain]);
  const selectedModule = eq?.modules.find((m) => m.components.some((c) => c.id === selected?.id));

  /** 從 3D 或清單選取：切到該元件的分頁、捲到分頁頂（詳細面板）並把清單列捲入視野。 */
  const select = useCallback((c: Component) => {
    const mod = eq?.modules.find((m) => m.components.some((x) => x.id === c.id));
    setSelected(c);
    if (mod && mod.domain !== domain) setDomain(mod.domain);
    pendingScroll.current = c.id;
  }, [eq, domain]);

  useEffect(() => {
    const id = pendingScroll.current;
    if (id == null) return;
    pendingScroll.current = null;
    layoutRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    const row = document.getElementById(`component-${id}`);
    if (row) setTimeout(() => row.scrollIntoView({ behavior: 'smooth', block: 'center' }), 350);
  }, [selected, domain]);

  if (!eq) {
    return (
      <div className="page" style={{ display: 'grid', placeItems: 'center', height: '60vh' }}>
        <IxSpinner size="large" />
      </div>
    );
  }

  return (
    <div className="page">
      <IxContentHeader headerTitle={eq.name} headerSubtitle={eq.summary} />
      <IxTypography format="body" style={{ margin: '0.75rem 0 1rem', maxWidth: 1000 }}>
        {eq.description}
      </IxTypography>

      {/* 注意：程式改 activeTabKey 時 IxTabs 也會發 tabChange，這裡只同步 domain、不清除選取 */}
      <IxTabs activeTabKey={domain} onTabChange={(e) => setDomain((e.detail as Domain) ?? 'mechanical')}>
        {DOMAINS.map((d) => (
          <IxTabItem key={d} tabKey={d}>
            <span className="domain-dot" style={{ background: DOMAIN_COLOR[d] }} />
            {DOMAIN_LABEL[d]}
            <span className="tab-count">{eq.modules.filter((m) => m.domain === d).reduce((n, m) => n + m.components.length, 0)}</span>
          </IxTabItem>
        ))}
      </IxTabs>

      <div className="equipment-layout" style={{ marginTop: '0.75rem' }} ref={layoutRef}>
        <div>
          <Viewer sceneKey={eq.scene_key} modelFile={eq.model_file} hotspots={allHotspots} activeDomain={domain} selected={selected} onSelect={select} />

          {domain === 'utility' && eq.utility_guide.length > 0 && (
            <section className="guide">
              <IxTypography format="h4" style={{ marginTop: '1rem' }}>水氣電教育訓練</IxTypography>
              <IxTypography format="body-sm" textColor="soft">
                新人接手設備前必須先懂：能量從哪裡來、怎麼安全地開與關、維修前怎麼把能量歸零（LOTO）。
              </IxTypography>
              <div className="guide-grid">
                {eq.utility_guide.map((g) => (
                  <IxCard key={g.title}>
                    <IxCardContent>
                      <IxTypography format="h5">
                        <span style={{ marginRight: 6 }}>{GUIDE_ICON[g.icon] ?? '•'}</span>
                        {g.title}
                      </IxTypography>
                      <ol className="guide-list">
                        {g.items.map((it, i) => (
                          <li key={i}>{it}</li>
                        ))}
                      </ol>
                    </IxCardContent>
                  </IxCard>
                ))}
              </div>
            </section>
          )}

          {modules.map((m) => (
            <section key={m.id}>
              <div className="module-header">
                <span className="domain-dot" style={{ background: DOMAIN_COLOR[m.domain] }} />
                <IxTypography format="h5">{m.name}</IxTypography>
                <IxTypography format="body-sm" textColor="soft">{m.description}</IxTypography>
              </div>
              <div className="component-list">
                {m.components.map((c) => (
                  <div key={c.id} id={`component-${c.id}`} className={`component-row ${selected?.id === c.id ? 'active' : ''}`} onClick={() => select(c)}>
                    {c.photo ? <img className="thumb" src={c.photo} alt={c.name} /> : <div className="thumb">待上傳照片</div>}
                    <div>
                      <div className="title">{c.name}</div>
                      <div className="sub">{c.function}</div>
                      <div className="sub">📍 {c.install_location}</div>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-end' }}>
                      {c.category && <IxPill variant="neutral" outline>{c.category}</IxPill>}
                      {c.animation_key && <IxPill variant="info" outline>動畫</IxPill>}
                      {c.model_file && <IxPill variant="success" outline>3D CAD</IxPill>}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
        <ComponentDetail component={selected} domain={selectedModule?.domain} moduleName={selectedModule?.name} />
      </div>
    </div>
  );
}
