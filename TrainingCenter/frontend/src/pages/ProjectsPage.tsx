import { useCallback, useEffect, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import {
  IxButton,
  IxContentHeader,
  IxInput,
  IxMessageBar,
  IxSelect,
  IxSelectItem,
  IxTextarea,
} from '@siemens/ix-react';
import Markdown from '../components/Markdown';
import type { AppContext } from '../App';
import {
  ApiError,
  STATUS_LABEL,
  training,
  type Project,
  type ProjectSummary,
  type Submission,
} from '../training';

/** 實戰演練：看題目規格、提交成果；導師可在同一頁批改。 */
export default function ProjectsPage() {
  const { me } = useOutletContext<AppContext>();
  const isMentor = me?.role === 'mentor' || me?.role === 'admin';

  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [open, setOpen] = useState<Project | null>(null);
  const [subs, setSubs] = useState<Submission[]>([]);
  const [repo, setRepo] = useState('');
  const [note, setNote] = useState('');
  const [msg, setMsg] = useState('');

  const reload = useCallback(() => {
    training.listProjects().then(setProjects).catch(console.error);
    if (me?.authenticated) training.listSubmissions().then(setSubs).catch(console.error);
    else setSubs([]);
  }, [me?.authenticated]);

  useEffect(reload, [reload]);

  const openProject = async (slug: string) => {
    setMsg('');
    setOpen(open?.slug === slug ? null : await training.getProject(slug));
  };

  const submit = async () => {
    if (!open) return;
    try {
      await training.submitProject(open.slug, repo, note);
      setRepo('');
      setNote('');
      setMsg('已提交，等待導師審核。');
      reload();
    } catch (e) {
      setMsg(e instanceof ApiError && e.status === 401 ? '請先登入才能提交。' : String(e));
    }
  };

  return (
    <div className="page">
      <IxContentHeader
        headerTitle="實戰演練"
        headerSubtitle="每個題目都有明確的規格與驗收標準。做完提交 repo 連結，導師會給評分與 Code Review。"
      />
      {msg && (
        <IxMessageBar type="info" onClosedChange={() => setMsg('')}>
          {msg}
        </IxMessageBar>
      )}

      <div className="project-list">
        {projects.map((p) => (
          <article key={p.slug} className="project-card">
            <header onClick={() => openProject(p.slug)}>
              <span className="level-badge small">L{p.level}</span>
              <h4>{p.title}</h4>
              {p.my_status && (
                <span className={`status status-${p.my_status}`}>
                  {STATUS_LABEL[p.my_status as Submission['status']]}
                </span>
              )}
            </header>
            <p className="project-summary">{p.summary}</p>
            {open?.slug === p.slug && (
              <div className="project-body">
                <Markdown>{open.spec_markdown}</Markdown>
                <h4 className="section-title">驗收標準</h4>
                <Markdown>{open.acceptance_markdown}</Markdown>
                <div className="submit-box">
                  <IxInput
                    label="程式碼連結（GitHub / GitLab）"
                    placeholder="https://github.com/…"
                    value={repo}
                    onValueChange={(e) => setRepo(e.detail)}
                  />
                  <IxTextarea
                    label="自述：做法與已知問題"
                    value={note}
                    onValueChange={(e) => setNote(e.detail)}
                  />
                  <IxButton onClick={submit}>提交</IxButton>
                </div>
              </div>
            )}
          </article>
        ))}
      </div>

      {subs.length > 0 && (
        <>
          <h3 className="section-title">{isMentor ? '待批改與已批改' : '我的提交紀錄'}</h3>
          <div className="sub-list">
            {subs.map((s) => (
              <SubmissionRow key={s.id} sub={s} isMentor={isMentor} onDone={reload} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function SubmissionRow({
  sub,
  isMentor,
  onDone,
}: {
  sub: Submission;
  isMentor: boolean;
  onDone: () => void;
}) {
  const [status, setStatus] = useState(sub.status);
  const [feedback, setFeedback] = useState(sub.mentor_feedback);
  const [score, setScore] = useState(sub.score === null ? '' : String(sub.score));
  const [editing, setEditing] = useState(false);

  const save = async () => {
    await training.review(sub.id, status, feedback, score === '' ? null : Number(score));
    setEditing(false);
    onDone();
  };

  return (
    <article className="sub-row">
      <div className="sub-head">
        <b>{sub.project_title}</b>
        <span className="muted">{sub.student}</span>
        <span className={`status status-${sub.status}`}>{STATUS_LABEL[sub.status]}</span>
        {sub.score !== null && <span className="score">{sub.score} 分</span>}
        <span className="muted">{new Date(sub.submitted_at).toLocaleString('zh-TW')}</span>
      </div>
      {sub.repo_url && (
        <a href={sub.repo_url} target="_blank" rel="noreferrer">
          {sub.repo_url}
        </a>
      )}
      {sub.note && <p className="sub-note">{sub.note}</p>}
      {sub.mentor_feedback && (
        <p className="sub-feedback">
          <b>導師評語</b>
          {sub.mentor_feedback}
        </p>
      )}
      {isMentor &&
        (editing ? (
          <div className="review-box">
            <IxSelect
              value={status}
              onValueChange={(e) => setStatus(e.detail as Submission['status'])}
            >
              {(Object.keys(STATUS_LABEL) as Submission['status'][]).map((k) => (
                <IxSelectItem key={k} value={k} label={STATUS_LABEL[k]} />
              ))}
            </IxSelect>
            <IxInput
              label="分數"
              value={score}
              onValueChange={(e) => setScore(e.detail)}
            />
            <IxTextarea
              label="評語 / Code Review"
              value={feedback}
              onValueChange={(e) => setFeedback(e.detail)}
            />
            <IxButton onClick={save}>儲存</IxButton>
            <IxButton variant="subtle-secondary" onClick={() => setEditing(false)}>
              取消
            </IxButton>
          </div>
        ) : (
          <IxButton variant="subtle-secondary" onClick={() => setEditing(true)}>
            批改
          </IxButton>
        ))}
    </article>
  );
}
