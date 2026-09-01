import { Fragment } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

/** 教材與文檔的 Markdown 渲染（區塊層級）。樣式在 index.css 的 .md 底下。 */
export default function Markdown({ children }: { children: string }) {
  return (
    <div className="md">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  );
}

/**
 * 只處理 `**粗體**` 的行內渲染。
 * 教材原文（元件重點、辨識說明）帶粗體標記但不是完整文件，用區塊渲染會多包一層 <p>。
 */
export function Inline({ children }: { children: string }) {
  return (
    <>
      {children.split('**').map((part, i) =>
        i % 2 ? <b key={i}>{part}</b> : <Fragment key={i}>{part}</Fragment>,
      )}
    </>
  );
}
