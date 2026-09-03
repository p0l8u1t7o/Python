/**
 * 品牌標誌：取景框四角＋鏡頭圓，圓角方底（與 index.html 的 favicon 同一個圖形）。
 * 側欄、登入頁、空狀態共用；顏色跟主題的 --sidebar-brand 走。
 */
export function BrandMark({ size = 32, className = '' }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" className={`shrink-0 ${className}`} aria-hidden focusable="false">
      <rect width="32" height="32" rx="8" fill="var(--sidebar-brand, #1abb9c)" />
      <path d="M8 12V9.5A1.5 1.5 0 0 1 9.5 8H12M20 8h2.5A1.5 1.5 0 0 1 24 9.5V12M24 20v2.5a1.5 1.5 0 0 1-1.5 1.5H20M12 24H9.5A1.5 1.5 0 0 1 8 22.5V20" stroke="#fff" strokeWidth="2" strokeLinecap="round" fill="none" />
      <circle cx="16" cy="16" r="4.5" stroke="#fff" strokeWidth="2" fill="none" />
      <circle cx="17.6" cy="14.4" r="1.1" fill="#fff" />
    </svg>
  )
}
