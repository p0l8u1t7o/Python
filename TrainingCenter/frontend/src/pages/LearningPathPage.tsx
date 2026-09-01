import { useEffect, useState } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { IxContentHeader, IxIcon, IxProgressIndicator } from '@siemens/ix-react';
import { iconLock, iconSingleCheck } from '@siemens/ix-icons/icons';
import type { AppContext } from '../App';
import { training, type Course } from '../training';

const LEVEL_NAME: Record<number, string> = {
  1: '觀念與全貌',
  2: '模組與工具',
  3: '機種專章與實戰',
};

/** 學習地圖：課程依 Level 分級，前一級全部章節完成才解鎖下一級。 */
export default function LearningPathPage() {
  const { me } = useOutletContext<AppContext>();
  const [courses, setCourses] = useState<Course[]>([]);
  const navigate = useNavigate();

  useEffect(() => {
    training.listCourses().then(setCourses).catch(console.error);
  }, [me?.lessons_done]);

  const levels = [...new Set(courses.map((c) => c.level))].sort();
  const totalLessons = courses.reduce((n, c) => n + c.lessons.length, 0);
  const doneLessons = courses.reduce((n, c) => n + c.completed_count, 0);

  return (
    <div className="page">
      <IxContentHeader
        headerTitle="學習地圖"
        headerSubtitle={
          me?.authenticated
            ? `已完成 ${doneLessons} / ${totalLessons} 章。完成一級的全部章節才會解鎖下一級。`
            : '登入後才會記錄進度與解鎖下一級。未登入也可以先瀏覽第一級。'
        }
      />
      {totalLessons > 0 && (
        <IxProgressIndicator
          status="info"
          value={doneLessons}
          max={totalLessons}
          style={{ maxWidth: 420, margin: '0.5rem 0 1.5rem' }}
        />
      )}

      {levels.map((lv) => (
        <section key={lv} className="level-block">
          <h3 className="level-title">
            <span className="level-badge">LEVEL {lv}</span>
            {LEVEL_NAME[lv] ?? ''}
          </h3>
          <div className="course-grid">
            {courses
              .filter((c) => c.level === lv)
              .map((c) => (
                <article key={c.slug} className={`course-card${c.locked ? ' locked' : ''}`}>
                  <header>
                    <h4>{c.title}</h4>
                    {c.locked && <IxIcon name={iconLock} size="16" />}
                  </header>
                  <p className="course-desc">{c.description}</p>
                  <div className="course-progress">
                    {c.completed_count} / {c.lessons.length} 章完成
                  </div>
                  <ul className="lesson-list">
                    {c.lessons.map((l) => (
                      <li key={l.slug}>
                        <button
                          type="button"
                          disabled={c.locked}
                          onClick={() => navigate(`/learn/${c.slug}/${l.slug}`)}
                        >
                          <span className="tick">
                            {l.completed ? <IxIcon name={iconSingleCheck} size="16" /> : null}
                          </span>
                          <span className="lesson-title">{l.title}</span>
                          {l.card_count > 0 && <span className="lesson-n">{l.card_count} 元件</span>}
                        </button>
                      </li>
                    ))}
                  </ul>
                  {c.locked && <div className="locked-note">完成前一級的所有章節後解鎖</div>}
                </article>
              ))}
          </div>
        </section>
      ))}
    </div>
  );
}
