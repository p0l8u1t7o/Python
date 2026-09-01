import { useEffect, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { IxContentHeader } from '@siemens/ix-react';
import type { AppContext } from '../App';
import { training, type AnswerResult, type Question } from '../training';

/** 隨堂測驗：作答後由後端判題並回傳解說；已登入會留下紀錄。 */
export default function QuizPage() {
  const { me, refreshMe } = useOutletContext<AppContext>();
  const [questions, setQuestions] = useState<Question[]>([]);
  const [results, setResults] = useState<Record<number, AnswerResult>>({});

  useEffect(() => {
    training.listQuiz().then(setQuestions).catch(console.error);
  }, []);

  const choose = async (q: Question, index: number) => {
    if (results[q.id]) return; // 已作答就不再改
    const r = await training.answer(q.id, index);
    setResults((prev) => ({ ...prev, [q.id]: r }));
    setQuestions((prev) =>
      prev.map((x) =>
        x.id === q.id ? { ...x, answered_index: index, answered_correct: r.correct } : x,
      ),
    );
    refreshMe();
  };

  const answered = Object.keys(results).length;
  const right = Object.values(results).filter((r) => r.correct).length;

  return (
    <div className="page">
      <IxContentHeader
        headerTitle="隨堂測驗"
        headerSubtitle={
          me?.authenticated
            ? `本次答對 ${right} / ${answered}；歷史紀錄 ${me.quiz_correct} / ${me.quiz_answered}。`
            : `本次答對 ${right} / ${answered}。登入後才會保存作答紀錄。`
        }
      />
      <div className="quiz-list">
        {questions.map((q, i) => {
          const res = results[q.id];
          const chosen = res ? q.answered_index : null;
          return (
            <article key={q.id} className="quiz-item">
              <h4>
                <span className="quiz-no">Q{i + 1}</span>
                {q.prompt}
              </h4>
              <div className="quiz-options">
                {q.options.map((opt, idx) => {
                  let state = '';
                  if (res) {
                    if (idx === res.answer_index) state = ' right';
                    else if (idx === chosen) state = ' wrong';
                  }
                  return (
                    <button
                      key={idx}
                      type="button"
                      className={`quiz-opt${state}`}
                      disabled={!!res}
                      onClick={() => choose(q, idx)}
                    >
                      <span className="quiz-key">{'ABCD'[idx]}</span>
                      {opt}
                    </button>
                  );
                })}
              </div>
              {res && (
                <p className={`quiz-exp${res.correct ? ' ok' : ' ng'}`}>
                  <b>{res.correct ? '答對了。' : '再看一次：'}</b>
                  {res.explanation}
                </p>
              )}
              {!res && q.answered_correct !== null && (
                <p className="quiz-prev">上次作答：{q.answered_correct ? '答對' : '答錯'}</p>
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
}
