import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useOutletContext, useParams } from 'react-router-dom';
import { IxButton, IxContentHeader, IxMessageBar } from '@siemens/ix-react';
import Markdown from '../components/Markdown';
import KnowledgeCards from '../components/KnowledgeCards';
import IdentificationPanel from '../components/IdentificationPanel';
import type { AppContext } from '../App';
import { ApiError, training, type Lesson } from '../training';

/** 單一章節：教材本文 + 本章涵蓋的元件卡 + 標記完成。 */
export default function LessonPage() {
  const { course = '', lesson: lessonSlug = '' } = useParams();
  const { me, refreshMe } = useOutletContext<AppContext>();
  const [lesson, setLesson] = useState<Lesson | null>(null);
  const [msg, setMsg] = useState('');
  const navigate = useNavigate();

  const load = useCallback(() => {
    training.getLesson(course, lessonSlug).then(setLesson).catch(console.error);
  }, [course, lessonSlug]);

  useEffect(load, [load]);

  const toggle = async () => {
    if (!lesson) return;
    try {
      if (lesson.completed) await training.uncompleteLesson(lesson.id);
      else await training.completeLesson(lesson.id);
      setMsg('');
      load();
      refreshMe();
    } catch (e) {
      setMsg(e instanceof ApiError && e.status === 401 ? '請先登入才能記錄進度。' : String(e));
    }
  };

  if (!lesson) return <div className="page">載入中…</div>;

  return (
    <div className="page">
      <IxContentHeader headerTitle={lesson.title} headerSubtitle={lesson.summary} />
      {msg && (
        <IxMessageBar type="warning" onClosedChange={() => setMsg('')}>
          {msg}
        </IxMessageBar>
      )}

      <div className="lesson-actions">
        <IxButton variant={lesson.completed ? 'secondary' : 'primary'} onClick={toggle}>
          {lesson.completed ? '取消完成標記' : '標記為已完成'}
        </IxButton>
        {lesson.equipment_slug && (
          <IxButton variant="subtle-secondary"
            onClick={() => navigate(`/equipment/${lesson.equipment_slug}`)}
          >
            看對應設備的 3D
          </IxButton>
        )}
        <IxButton variant="subtle-secondary" onClick={() => navigate('/learn')}>
          回學習地圖
        </IxButton>
        {!me?.authenticated && <span className="muted">未登入，進度不會保存</span>}
      </div>

      <Markdown>{lesson.content_markdown}</Markdown>

      {lesson.slug === 'ident' && <IdentificationPanel />}

      {lesson.cards.length > 0 && (
        <>
          <h3 className="section-title">本章元件（{lesson.cards.length}）</h3>
          <KnowledgeCards cards={lesson.cards} />
        </>
      )}
    </div>
  );
}
