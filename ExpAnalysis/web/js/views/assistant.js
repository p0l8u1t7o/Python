/** AI 助理：對話式查詢。LLM 只負責翻譯，數字全部來自工具。 */

import { api } from '../api.js';
import { h, card, badge, notice, mdToHtml, spinner, toast } from '../ui.js';

const history = [];

export default async function assistant() {
  const root = h('div');
  let status = null;
  try { status = await api.assistantStatus(); } catch { /* 顯示為未知 */ }

  if (status) {
    root.append(notice(status.degraded ? 'warn' : 'good',
      `目前使用：${status.active_provider}${status.model ? `（${status.model}）` : ''}`,
      status.note));
  }

  const log = h('div', { class: 'chat-log' });
  const input = h('textarea', {
    placeholder: '例如：IN-25004 的 Cu 為什麼比上一批差？　／　下一批該跑什麼條件？',
    onkeydown: (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); }
    },
  });
  const sendBtn = h('button', { onclick: () => send() }, '送出');

  const chat = h('div', { class: 'chat' }, log,
    h('div', { class: 'chat-input' }, input, sendBtn));

  root.append(card('對話式查詢',
    'LLM 不做任何計算。它的工作是解讀你的問題 → 呼叫對應的分析工具 → '
    + '把工具算出來的數字組織成人話。每則回覆都會列出實際呼叫了哪些工具。'
    + '（Ctrl/⌘ + Enter 送出）',
    chat));

  try {
    const sq = await api.suggestedQuestions();
    root.querySelector('.card-body').insertBefore(
      h('div', { class: 'chips', style: 'margin-bottom:12px' },
        ...sq.questions.map((q) => h('button', {
          class: 'chip', onclick: () => { input.value = q; send(); },
        }, q))),
      chat);
  } catch { /* 建議問題失敗不影響主功能 */ }

  if (!history.length) {
    log.append(h('div', { class: 'msg bot' },
      h('div', { class: 'who' }, '✦'),
      h('div', { class: 'bubble' },
        h('p', {}, '你可以直接問我製程資料的問題。我會先呼叫分析工具取得數字，再解釋給你聽。'),
        h('p', { class: 'muted' }, '所有數字都來自 Pfann/BPS 物理模型與高斯過程映射，'
          + '不是語言模型自己算的。'))));
  } else {
    for (const m of history) log.append(renderMsg(m));
  }

  async function send() {
    const q = input.value.trim();
    if (!q) return;
    input.value = '';
    sendBtn.disabled = true;

    const userMsg = { role: 'user', content: q };
    history.push(userMsg);
    log.append(renderMsg(userMsg));
    const pending = h('div', { class: 'msg bot' },
      h('div', { class: 'who' }, '✦'),
      h('div', { class: 'bubble' }, spinner('查詢資料與模型…')));
    log.append(pending);
    log.scrollTop = log.scrollHeight;

    try {
      const res = await api.chat({
        question: q,
        history: history.slice(-9, -1).map((m) => ({ role: m.role, content: m.content })),
      });
      const botMsg = { role: 'assistant', content: res.answer, meta: res };
      history.push(botMsg);
      pending.replaceWith(renderMsg(botMsg));
      if (res.error) toast(res.error, 'error');
    } catch (e) {
      pending.replaceWith(h('div', { class: 'msg bot' },
        h('div', { class: 'who' }, '!'),
        h('div', { class: 'bubble' },
          notice('error', '查詢失敗', e.message))));
      toast(e.message, 'error');
    } finally {
      sendBtn.disabled = false;
      log.scrollTop = log.scrollHeight;
      input.focus();
    }
  }

  return root;
}

function renderMsg(m) {
  if (m.role === 'user') {
    return h('div', { class: 'msg user' },
      h('div', { class: 'who' }, '你'),
      h('div', { class: 'bubble' }, m.content));
  }
  const meta = m.meta || {};
  const trace = h('div', { class: 'tool-trace' });
  if (meta.tools_used?.length) {
    trace.append(h('span', {}, '資料來源：'));
    for (const t of meta.tools_used) trace.append(badge(t, 'neutral'));
  }
  if (meta.cited_batches?.length) {
    trace.append(h('span', { style: 'margin-left:8px' },
      `引用批次：${meta.cited_batches.join('、')}`));
  }
  if (meta.degraded) {
    trace.append(h('span', { style: 'margin-left:8px' }, badge('本地模板模式', 'warn')));
  }
  return h('div', { class: 'msg bot' },
    h('div', { class: 'who' }, '✦'),
    h('div', { class: 'bubble' },
      h('div', { html: mdToHtml(m.content) }),
      meta.tools_used?.length ? trace : null));
}
