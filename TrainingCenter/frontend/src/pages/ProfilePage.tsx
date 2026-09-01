import { useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { IxButton, IxContentHeader, IxInput, IxMessageBar, IxProgressIndicator } from '@siemens/ix-react';
import type { AppContext } from '../App';
import { ApiError, ROLE_LABEL, training } from '../training';

/** 個人中心：登入／註冊，以及學習歷程摘要。 */
export default function ProfilePage() {
  const { me, refreshMe } = useOutletContext<AppContext>();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [department, setDepartment] = useState('');
  const [err, setErr] = useState('');

  const run = async () => {
    setErr('');
    try {
      if (mode === 'login') await training.login(username, password);
      else await training.register(username, password, displayName, department);
      setPassword('');
      await refreshMe();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  };

  if (me?.authenticated) {
    return (
      <div className="page">
        <IxContentHeader
          headerTitle={me.display_name}
          headerSubtitle={`${ROLE_LABEL[me.role] ?? me.role}${me.department ? `　${me.department}` : ''}`}
        />
        <div className="stat-row">
          <div className="stat">
            <div className="stat-n">
              {me.lessons_done} / {me.lessons_total}
            </div>
            <div className="stat-l">章節完成</div>
            <IxProgressIndicator status="info" value={me.lessons_done} max={me.lessons_total || 1} />
          </div>
          <div className="stat">
            <div className="stat-n">
              {me.quiz_correct} / {me.quiz_answered}
            </div>
            <div className="stat-l">測驗答對（以最新一次作答計）</div>
          </div>
        </div>
        <IxButton variant="subtle-secondary"
          onClick={async () => {
            await training.logout();
            await refreshMe();
          }}
        >
          登出
        </IxButton>
      </div>
    );
  }

  return (
    <div className="page">
      <IxContentHeader
        headerTitle={mode === 'login' ? '登入' : '註冊新帳號'}
        headerSubtitle="登入後才會記錄章節進度、測驗成績與專案提交。"
      />
      {err && (
        <IxMessageBar type="alarm" onClosedChange={() => setErr('')}>
          {err}
        </IxMessageBar>
      )}
      <div className="auth-form">
        <IxInput label="帳號" value={username} onValueChange={(e) => setUsername(e.detail)} />
        <IxInput
          label="密碼"
          type="password"
          value={password}
          onValueChange={(e) => setPassword(e.detail)}
        />
        {mode === 'register' && (
          <>
            <IxInput label="姓名" value={displayName} onValueChange={(e) => setDisplayName(e.detail)} />
            <IxInput
              label="部門／課別"
              value={department}
              onValueChange={(e) => setDepartment(e.detail)}
            />
          </>
        )}
        <div className="auth-actions">
          <IxButton onClick={run}>{mode === 'login' ? '登入' : '註冊'}</IxButton>
          <IxButton variant="subtle-secondary"
            onClick={() => {
              setErr('');
              setMode(mode === 'login' ? 'register' : 'login');
            }}
          >
            {mode === 'login' ? '沒有帳號？註冊' : '已有帳號？登入'}
          </IxButton>
        </div>
        <p className="muted">
          註冊一律開為「學員」。導師與管理員權限請由管理員在 Django admin（<code>/admin/</code>）調整。
        </p>
      </div>
    </div>
  );
}
