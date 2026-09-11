import { fireEvent, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ENGINEERING_NOTE, installApiMock, routes } from './apiMock'
import { renderPage } from './render'
import { NotesPage } from '@/pages/NotesPage'
import { DecisionNotes } from '@/components/notes/DecisionNotes'
import { api } from '@/lib/api'
import i18n from '@/i18n'

installApiMock()
beforeEach(async () => { vi.clearAllMocks(); await i18n.changeLanguage('en'); vi.mocked(api.get).mockImplementation(async (path) => routes(path) as never) })

describe('engineering notes', () => {
  it('creates a draft with conditions and version bounds', async () => {
    renderPage(<NotesPage />, { route: '/notes?flow=1' })
    fireEvent.click(await screen.findByRole('button', { name: 'New draft' }))
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Backlight for cups' } })
    fireEvent.change(screen.getByLabelText('Engineering knowledge'), { target: { value: 'Use a diffuser' } })
    fireEvent.change(screen.getByLabelText('From flow version'), { target: { value: '3' } })
    fireEvent.change(screen.getByLabelText('Through flow version'), { target: { value: '6' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add condition' }))
    fireEvent.change(screen.getByLabelText('Condition'), { target: { value: 'Material' } })
    fireEvent.change(screen.getByLabelText('Value'), { target: { value: 'Steel' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save draft' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/vision/notes', expect.objectContaining({ title: 'Backlight for cups', body: 'Use a diffuser', flow: 1, conditions: { Material: 'Steel' }, applies_from_version: 3, applies_to_version: 6 })))
  })

  it('confirms and retracts through dedicated actions', async () => {
    renderPage(<NotesPage />, { route: '/notes?note=1' })
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/vision/notes/1/confirm', {}))
    await screen.findByText('Confirmed', { selector: 'span' })
    fireEvent.click(screen.getByRole('button', { name: 'Retract' }))
    fireEvent.click(screen.getAllByRole('button', { name: 'Retract' }).at(-1)!)
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/vision/notes/1/retract', {}))
  })

  it('disables self-confirmation and hides writes for a reader', async () => {
    vi.mocked(api.get).mockImplementation(async (path) => path === '/vision/notes/1' ? { ...ENGINEERING_NOTE, can_confirm: false } as never : routes(path) as never)
    const view = renderPage(<NotesPage />, { route: '/notes?note=1' })
    expect(await screen.findByRole('button', { name: 'Confirm' })).toBeDisabled()
    view.unmount()
    vi.mocked(api.get).mockImplementation(async (path) => path === '/auth/me' ? { ...(routes(path) as object), role: 'operator', permissions: [] } as never : routes(path) as never)
    renderPage(<NotesPage />, { route: '/notes?note=1' })
    await screen.findByText(ENGINEERING_NOTE.body)
    expect(screen.queryByRole('button', { name: 'New draft' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirm' })).not.toBeInTheDocument()
  })

  it('saves a conversation decision as a draft without changing work state', async () => {
    const decisions = [{ at: '2026-09-11T00:00:00Z', text: 'Use diffuse lighting', by: 'user' as const }]
    renderPage(<DecisionNotes decisions={decisions} flowId={1} />)
    fireEvent.click(await screen.findByText('Engineering decisions'))
    fireEvent.click(screen.getByRole('button', { name: 'Save as engineering note' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/vision/notes', { title: decisions[0].text, body: decisions[0].text, kind: 'decision', flow: 1 }))
    expect(await screen.findByRole('link', { name: 'Open note' })).toHaveAttribute('href', '/notes?note=1')
    expect(decisions).toEqual([{ at: '2026-09-11T00:00:00Z', text: 'Use diffuse lighting', by: 'user' }])
  })

  it.each(['en', 'zh-Hant', 'zh-Hans'])('renders the note form in %s', async (language) => {
    await i18n.changeLanguage(language)
    const view = renderPage(<NotesPage />, { route: '/notes' })
    fireEvent.click(await screen.findByRole('button', { name: i18n.t('notes.create') }))
    expect(screen.getByRole('button', { name: i18n.t('notes.save') })).toBeInTheDocument()
    expect(view.container.textContent).not.toMatch(/(?:notes|common)\.[a-zA-Z]/)
  })
})
