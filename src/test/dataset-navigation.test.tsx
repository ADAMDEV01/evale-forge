import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

import App from '../App'
import { api } from '../services/api'
import type { Dataset, TestCase } from '../types'

const datasets: Dataset[] = [
  { id: 'ds-support', name: 'Support dataset', description: 'Support cases', version: 'v1', cases: 1, createdAt: '2026-01-01', modifiedAt: '2026-01-01', color: 'violet' },
  { id: 'ds-code', name: 'Code dataset', description: 'Code cases', version: 'v2', cases: 1, createdAt: '2026-01-01', modifiedAt: '2026-01-01', color: 'blue' },
  { id: 'ds-empty', name: 'Empty dataset', description: 'No cases yet', version: 'v1', cases: 0, createdAt: '2026-01-01', modifiedAt: '2026-01-01', color: 'emerald' },
]

const cases: TestCase[] = [
  { id: 'case-support', datasetId: 'ds-support', title: 'Support case', input: 'Support prompt', expected: 'Support answer', criteria: '', category: 'Support', tags: [], importance: 'High', expectedBehavior: '' },
  { id: 'case-code', datasetId: 'ds-code', title: 'Code case', input: 'Code prompt', expected: 'Code answer', criteria: '', category: 'Code', tags: [], importance: 'Medium', expectedBehavior: '' },
]

function renderApp(initialRoute: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialRoute]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  api.clearAccessToken()
  vi.spyOn(api, 'restoreSession').mockResolvedValue({
    id: 'test-user',
    email: 'test@example.test',
    is_active: true,
    created_at: '2026-01-01T00:00:00',
  })
  vi.spyOn(api, 'getDatasets').mockResolvedValue(datasets)
  vi.spyOn(api, 'getTestCases').mockResolvedValue(cases)
  vi.spyOn(api, 'getRuns').mockResolvedValue([])
  vi.spyOn(api, 'getFailures').mockResolvedValue([])
  vi.spyOn(api, 'getRubrics').mockResolvedValue([])
})

afterEach(() => {
  api.clearAccessToken()
  vi.restoreAllMocks()
})

describe('Dataset navigation', () => {
  it('opens each dataset card with only its associated cases, including empty datasets', async () => {
    const user = userEvent.setup()
    renderApp('/datasets')
    await screen.findByRole('heading', { name: 'Datasets' })

    for (const [index, dataset] of datasets.entries()) {
      const card = screen.getByRole('heading', { name: dataset.name }).closest('.dataset-card')
      expect(card).not.toBeNull()
      const openButton = within(card as HTMLElement).getByRole('button', { name: 'Open dataset' })
      if (dataset.id === 'ds-empty') {
        expect(within(card as HTMLElement).getByText('0 test cases')).toBeInTheDocument()
      }

      await user.click(openButton)
      expect(await screen.findByRole('heading', { name: dataset.name })).toBeInTheDocument()

      const expectedCase = cases.find((testCase) => testCase.datasetId === dataset.id)
      if (expectedCase) {
        expect(screen.getByText(expectedCase.title)).toBeInTheDocument()
        for (const otherCase of cases.filter((testCase) => testCase.datasetId !== dataset.id)) {
          expect(screen.queryByText(otherCase.title)).not.toBeInTheDocument()
        }
      } else {
        expect(screen.getByText('No test cases in this dataset')).toBeInTheDocument()
      }

      if (index < datasets.length - 1) {
        await user.click(screen.getByRole('button', { name: /All datasets/ }))
        expect(await screen.findByRole('heading', { name: 'Datasets' })).toBeInTheDocument()
      }
    }
  })

  it('loads a dataset details route directly, as on browser refresh', async () => {
    renderApp('/datasets/ds-empty')

    expect(await screen.findByRole('heading', { name: 'Empty dataset' })).toBeInTheDocument()
    expect(screen.getByText('No test cases in this dataset')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Datasets' })).not.toBeInTheDocument()
  })

  it('shows an explicit unavailable state instead of saved sample failures when the API fails', async () => {
    localStorage.setItem('evalforge:failures', JSON.stringify([{ id: 'local-sample-failure' }]))
    vi.mocked(api.getFailures).mockRejectedValue(new Error('Failure API unavailable'))

    renderApp('/failures')

    expect(await screen.findByText('Failure data unavailable')).toBeInTheDocument()
    expect(screen.getByText(/No sample data is being shown/)).toBeInTheDocument()
    expect(screen.queryByText('local-sample-failure')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })
})
