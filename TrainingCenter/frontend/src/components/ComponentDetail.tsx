import { IxCard, IxCardContent, IxKeyValue, IxKeyValueList, IxPill, IxTypography } from '@siemens/ix-react';
import { type Component, type Domain, DOMAIN_COLOR, DOMAIN_LABEL } from '../api';
import { MechanismAnimation } from './Animations';
import { ModelViewer } from './ModelViewer';
import { ComponentImage } from './ComponentImage';
import { componentVisual } from '../componentVisuals';

interface Props {
  component: Component | null;
  domain?: Domain;
  moduleName?: string;
}

/** 右側詳細面板：真實照片、功用、安裝位置、規格、動畫。 */
export function ComponentDetail({ component, domain, moduleName }: Props) {
  if (!component) {
    return (
      <IxCard className="detail-panel">
        <IxCardContent>
          <IxTypography format="h5">選擇一個元件</IxTypography>
          <IxTypography format="body-sm" textColor="soft">
            滑鼠移到 3D 零件上會高亮並顯示名稱；點擊零件或左側清單中的元件，即可查看照片、功用與安裝位置。
          </IxTypography>
        </IxCardContent>
      </IxCard>
    );
  }
  const specs = Object.entries(component.specs ?? {});
  const visual = componentVisual(component);
  const modelUrl = component.model_file || visual?.model;
  return (
    <IxCard className="detail-panel">
      <IxCardContent>
        <ComponentImage item={component} className="detail-photo" showCredit />
        <div style={{ display: 'flex', gap: '0.25rem', flexWrap: 'wrap', margin: '0.75rem 0 0.25rem' }}>
          {domain && (
            <IxPill variant="custom" background={DOMAIN_COLOR[domain]} pillColor="#000">
              {DOMAIN_LABEL[domain]}
            </IxPill>
          )}
          {component.category && <IxPill variant="neutral" outline>{component.category}</IxPill>}
        </div>
        <IxTypography format="h4">{component.name}</IxTypography>
        {moduleName && <IxTypography format="body-sm" textColor="soft">{moduleName}</IxTypography>}

        <div className="section-title">功用</div>
        <IxTypography format="body">{component.function}</IxTypography>

        <div className="section-title">安裝位置</div>
        <IxTypography format="body">{component.install_location}</IxTypography>

        {modelUrl && (
          <>
            <div className="section-title">{visual?.conceptual ? '3D 軟體概念圖' : '3D 元件模型'}</div>
            <ModelViewer key={modelUrl} url={modelUrl} fallbackUrl={visual?.model} />
          </>
        )}

        {component.animation_key && (
          <>
            <div className="section-title">動作原理</div>
            <div className="animation-box">
              <MechanismAnimation animationKey={component.animation_key} />
            </div>
          </>
        )}

        {(component.brand || component.part_number || specs.length > 0) && (
          <>
            <div className="section-title">規格</div>
            <IxKeyValueList striped>
              {component.brand && <IxKeyValue label="品牌" value={component.brand} />}
              {component.part_number && <IxKeyValue label="型號" value={component.part_number} />}
              {specs.map(([k, v]) => (
                <IxKeyValue key={k} label={k} value={String(v)} />
              ))}
            </IxKeyValueList>
          </>
        )}
      </IxCardContent>
    </IxCard>
  );
}
