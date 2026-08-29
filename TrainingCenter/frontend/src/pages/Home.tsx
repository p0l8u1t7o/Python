import { useNavigate, useOutletContext } from 'react-router-dom';
import { IxCard, IxCardContent, IxContentHeader, IxPill, IxTypography } from '@siemens/ix-react';
import type { EquipmentSummary } from '../api';
import { ScenePreview } from '../three/Viewer';

export default function Home() {
  const { equipment } = useOutletContext<{ equipment: EquipmentSummary[] }>();
  const navigate = useNavigate();

  return (
    <div className="page">
      <IxContentHeader
        headerTitle="設備總覽"
        headerSubtitle="點選設備進入：以 3D 多角度觀察機台，逐一認識機構、電控與軟體元件的功用與安裝位置。"
      />
      <div className="equipment-grid" style={{ marginTop: '1rem' }}>
        {equipment.map((e) => (
          <IxCard key={e.slug} className="equipment-card" onClick={() => navigate(`/equipment/${e.slug}`)}>
            <IxCardContent>
              <div className="thumb">
                {e.hero_image ? <img src={e.hero_image} alt={e.name} /> : <ScenePreview sceneKey={e.scene_key} />}
              </div>
              <IxTypography format="h4">{e.name}</IxTypography>
              <IxTypography format="body-sm" textColor="soft" style={{ margin: '0.5rem 0' }}>
                {e.summary}
              </IxTypography>
              <IxPill variant="info" outline>
                {e.component_count} 個元件
              </IxPill>
            </IxCardContent>
          </IxCard>
        ))}
      </div>
    </div>
  );
}
