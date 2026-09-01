import { useCallback, useEffect, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  IxApplication,
  IxApplicationHeader,
  IxContent,
  IxMenu,
  IxMenuItem,
} from '@siemens/ix-react';
import {
  iconBook,
  iconBoxOpen,
  iconBulb,
  iconCheckboxes,
  iconDocument,
  iconDocumentInfo,
  iconEye,
  iconHome,
  iconPlant,
  iconRoboticArm,
  iconSearch,
  iconMaintenance,
  iconUser,
} from '@siemens/ix-icons/icons';
import HeaderSearch from './components/HeaderSearch';
import { api, type EquipmentSummary } from './api';
import { training, type Me } from './training';

const SCENE_ICON: Record<string, string> = {
  fuelcell: iconPlant,
  aoi: iconSearch,
  transfer: iconMaintenance,
  robotcell: iconRoboticArm,
};

/** 所有頁面共用的 outlet context。 */
export interface AppContext {
  equipment: EquipmentSummary[];
  me: Me | null;
  refreshMe: () => Promise<void>;
}

export default function App() {
  const [equipment, setEquipment] = useState<EquipmentSummary[]>([]);
  const [me, setMe] = useState<Me | null>(null);
  const navigate = useNavigate();
  const { pathname } = useLocation();

  const refreshMe = useCallback(async () => {
    setMe(await training.me().catch(() => null));
  }, []);

  useEffect(() => {
    api.listEquipment().then(setEquipment).catch(console.error);
    refreshMe();
  }, [refreshMe]);

  const item = (path: string, icon: string, label: string) => (
    <IxMenuItem
      key={path}
      icon={icon}
      active={pathname === path || pathname.startsWith(path + '/')}
      onClick={() => navigate(path)}
    >
      {label}
    </IxMenuItem>
  );

  return (
    <IxApplication>
      <IxApplicationHeader name="設備教育訓練中心">
        {/* default slot 會排在橫幅右側 */}
        <HeaderSearch />
      </IxApplicationHeader>
      <IxMenu>
        {item('/', iconHome, '設備總覽')}
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
        {item('/learn', iconBulb, '學習地圖')}
        {item('/knowledge', iconBook, '元件知識卡')}
        {item('/docs', iconDocumentInfo, '技術文檔')}
        {item('/identify', iconEye, '來料辨識')}
        {item('/quiz', iconCheckboxes, '隨堂測驗')}
        {item('/projects', iconDocument, '實戰演練')}
        {item('/glossary', iconBook, '元件字典')}
        {item('/cad-studio', iconBoxOpen, 'CAD Studio')}
        {item('/me', iconUser, me?.authenticated ? me.display_name : '登入')}
      </IxMenu>
      <IxContent>
        <Outlet context={{ equipment, me, refreshMe } satisfies AppContext} />
      </IxContent>
    </IxApplication>
  );
}
