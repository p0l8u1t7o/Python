import { useEffect, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  IxApplication,
  IxApplicationHeader,
  IxContent,
  IxMenu,
  IxMenuItem,
} from '@siemens/ix-react';
import { iconBook, iconBoxOpen, iconHome, iconPlant, iconRoboticArm, iconSearch, iconMaintenance } from '@siemens/ix-icons/icons';
import { api, type EquipmentSummary } from './api';

const SCENE_ICON: Record<string, string> = {
  fuelcell: iconPlant,
  aoi: iconSearch,
  transfer: iconMaintenance,
  robotcell: iconRoboticArm,
};

export default function App() {
  const [equipment, setEquipment] = useState<EquipmentSummary[]>([]);
  const navigate = useNavigate();
  const { pathname } = useLocation();

  useEffect(() => {
    api.listEquipment().then(setEquipment).catch(console.error);
  }, []);

  return (
    <IxApplication>
      <IxApplicationHeader name="設備教育訓練中心" />
      <IxMenu>
        <IxMenuItem icon={iconHome} active={pathname === '/'} onClick={() => navigate('/')}>
          設備總覽
        </IxMenuItem>
        {equipment.map((e) => (
          <IxMenuItem
            key={e.slug}
            icon={SCENE_ICON[e.scene_key] ?? iconRoboticArm}
            active={pathname === `/equipment/${e.slug}`}
            onClick={() => navigate(`/equipment/${e.slug}`)}
          >
            {e.name}
          </IxMenuItem>
        ))}
        <IxMenuItem icon={iconBook} active={pathname === '/glossary'} onClick={() => navigate('/glossary')}>
          元件字典
        </IxMenuItem>
        <IxMenuItem icon={iconBoxOpen} active={pathname === '/cad-studio'} onClick={() => navigate('/cad-studio')}>
          CAD Studio
        </IxMenuItem>
      </IxMenu>
      <IxContent>
        <Outlet context={{ equipment }} />
      </IxContent>
    </IxApplication>
  );
}
