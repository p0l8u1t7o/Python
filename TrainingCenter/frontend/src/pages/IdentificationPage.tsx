import { IxContentHeader } from '@siemens/ix-react';
import IdentificationPanel from '../components/IdentificationPanel';

/** 來料辨識：從外觀反查元件，並提醒驗收時該核對什麼。 */
export default function IdentificationPage() {
  return (
    <div className="page">
      <IxContentHeader
        headerTitle="來料了，這到底是什麼元件？"
        headerSubtitle="先從外觀對號入座，再照「要核對的欄位」逐項比對銘牌，最後看常見的收錯。"
      />
      <IdentificationPanel />
    </div>
  );
}
