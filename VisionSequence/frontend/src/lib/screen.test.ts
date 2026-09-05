/** 畫面快照與文字摘要：標題／對話框／鎖定橫幅／整合分頁；摘要取標題、警示、表格前幾列、表單值（跳過密碼）、按鈕，跳過助手視窗，有長度上限。 */
import { afterEach, describe, expect, it } from 'vitest'

import { integrationTab, pageSnapshot, screenSummary, setIntegrationTab } from '@/lib/screen'

afterEach(() => {
  document.body.innerHTML = ''
  sessionStorage.clear()
})

describe('pageSnapshot', () => {
  it('reads the heading, an open dialog, the lock banner and the integration tab', () => {
    document.body.innerHTML = `
      <main><h1>Source library</h1></main>
      <div role="dialog"><h2>New source</h2></div>
      <div data-testid="lock-banner">Engine locked by integrator</div>`
    setIntegrationTab('modbus-server', 'connections')
    expect(pageSnapshot('/integration/modbus-server')).toEqual({ title: 'Source library', dialog: 'New source', banner: 'Engine locked by integrator', tab: 'connections' })
    expect(integrationTab('/sources')).toBe('')
    expect(pageSnapshot('/sources')).toEqual({ title: 'Source library', dialog: 'New source', banner: 'Engine locked by integrator' })
  })
})

describe('screenSummary', () => {
  it('summarises headings, alerts, tables, form values and buttons but not passwords or the assistant', () => {
    const rows = Array.from({ length: 10 }, (_, i) => `<tr><td>conn${i}</td><td>${i % 2 ? 'open' : 'closed'}</td></tr>`).join('')
    document.body.innerHTML = `
      <nav><button>Sidebar item</button></nav>
      <main>
        <h1>Modbus server</h1><h3>Connections</h3>
        <div role="status">Engine locked</div>
        <button aria-selected="true">Connections</button>
        <table><thead><tr><th>Name</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table>
        <label for="host">Host</label><input id="host" value="10.0.0.5">
        <label>Port <input value="502"></label>
        <input type="password" aria-label="Secret" value="hunter2">
        <label>Enabled <input type="checkbox" checked></label>
        <button>New connection</button><button>Test</button><button>Test</button>
        <section data-testid="assistant-dock"><h2>AI assistant</h2><button>Send</button></section>
      </main>`
    const out = screenSummary()
    expect(out).toContain('# Modbus server')
    expect(out).toContain('# Connections')
    expect(out).toContain('! Engine locked')
    expect(out).toContain('tab: Connections')
    expect(out).toContain('table: Name | Status')
    expect(out).toContain('conn0 | closed')
    expect(out).toContain('... 2 more rows')
    expect(out).toContain('Host: 10.0.0.5')
    expect(out).toContain('Port: 502')
    expect(out).toContain('Enabled: on')
    expect(out).not.toContain('hunter2')
    expect(out).not.toContain('Secret')
    expect(out).toContain('buttons: Connections, New connection, Test')
    expect(out).not.toContain('AI assistant')
    expect(out).not.toContain('Sidebar item')
    expect(out).not.toContain('Send')
  })

  it('caps the length and works without a main element', () => {
    document.body.innerHTML = `<h1>${'x'.repeat(5000)}</h1>`
    const out = screenSummary(100)
    expect(out.length).toBe(101)
    expect(out.endsWith('…')).toBe(true)
    document.body.innerHTML = ''
    expect(screenSummary()).toBe('')
  })
})
