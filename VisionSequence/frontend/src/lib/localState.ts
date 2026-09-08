/**
 * 瀏覽器本機狀態的分層：使用者層（登出／工作階段過期就清——共用電腦下一個人不該看到上一個人的助手對話與 TCP 命令歷史）
 * 與裝置層（主題、登入前的語言、側欄與版面偏好——留在這台電腦）。新增 localStorage 鍵時決定它屬於哪一層。
 */
export const USER_SCOPED_KEYS = ['vs.token', 'vs.apiKey', 'vs.assistant.v1', 'vs.assistant.share', 'vs.tcpHistory'] as const
export const USER_SCOPED_SESSION_KEYS = ['vs.assistant.hints.dismissed'] as const
/** 說明用：這些故意保留 */
export const DEVICE_SCOPED_KEYS = ['vs.theme', 'vs.language', 'vs.sidebar', 'vs.navOpen', 'vs.favoriteTools', 'vs.editorLayout', 'vs.canvasMode', 'vs.overlayLimit'] as const

export function clearUserState(): void {
  for (const key of USER_SCOPED_KEYS) {
    try {
      localStorage.removeItem(key)
    } catch {
      /* 私密模式 */
    }
  }
  for (const key of USER_SCOPED_SESSION_KEYS) {
    try {
      sessionStorage.removeItem(key)
    } catch {
      /* 私密模式 */
    }
  }
}
