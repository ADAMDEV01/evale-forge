import React from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

import App from '../App'
import { DatasetPage, TestCasePage } from '../pages'
import { api } from '../services/api'
import type { Dataset, Failure, TestCase } from '../types'

const datasetPayload = [
  { id: 'ds-1', name: 'Demo dataset', description: 'desc', version: 'v1.0', cases: 12, createdAt: '2025-01-01', modifiedAt: '2025-01-01', color: 'violet' },
]
const dataset: Dataset = datasetPayload[0]!
const testCase: TestCase = {
  id: 'case-1',
  datasetId: dataset.id,
  title: 'Test case',
  input: 'Prompt',
  expected: 'Expected answer',
  criteria: '',
  category: 'General',
  tags: [],
  importance: 'Medium',
  expectedBehavior: '',
}
const failedResponse = (detail = 'Write rejected') => ({
  ok: false,
  status: 409,
  text: async () => JSON.stringify({ detail }),
})

function localStorageSnapshot() {
  return Object.fromEntries(
    Array.from({ length: localStorage.length }, (_, index) => {
      const key = localStorage.key(index)!
      return [key, localStorage.getItem(key)]
    }),
  )
}

beforeEach(() => {
  localStorage.clear()
  api.clearAccessToken()
  class ResizeObserverMock {
    constructor(private readonly callback: ResizeObserverCallback) {}
    observe(target: Element) {
      this.callback([{ target, contentRect: { width: 1200, height: 400 } as DOMRectReadOnly } as ResizeObserverEntry], this)
    }
    unobserve() {}
    disconnect() {}
  }
  vi.stubGlobal('ResizeObserver', ResizeObserverMock)
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/auth/refresh')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            access_token: 'test-access-token',
            token_type: 'bearer',
            expires_in: 900,
            user: {
              id: 'test-user',
              email: 'test@example.test',
              is_active: true,
              created_at: '2026-01-01T00:00:00',
            },
          }),
        })
      }
      if (url.includes('/datasets')) {
        return Promise.resolve({ ok: true, json: async () => datasetPayload })
      }
      if (url.includes('/test-cases')) {
        return Promise.resolve({ ok: true, json: async () => [] })
      }
      if (url.includes('/runs')) {
        return Promise.resolve({ ok: true, json: async () => [] })
      }
      if (url.includes('/failures')) {
        return Promise.resolve({ ok: true, json: async () => [] })
      }
      return Promise.resolve({ ok: true, json: async () => ({}) })
    }),
  )
})

afterEach(() => {
  api.clearAccessToken()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('Application shell', () => {
  it('renders the dashboard shell with the overview title', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(
      React.createElement(
        QueryClientProvider,
        { client: queryClient },
        React.createElement(
          MemoryRouter,
          { initialEntries: ['/'] },
          React.createElement(App),
        ),
      ),
    )

    await waitFor(() => expect(screen.getAllByText(/Overview/i).length).toBeGreaterThan(0))
  })

  it('shows a backend 409 message and preserves dataset query state when deletion fails', async () => {
    const message = 'The dataset cannot be permanently deleted because evaluation history exists. Keep the dataset to preserve its history.'
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url.endsWith('/auth/refresh')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            access_token: 'test-access-token',
            token_type: 'bearer',
            expires_in: 900,
            user: {
              id: 'test-user',
              email: 'test@example.test',
              is_active: true,
              created_at: '2026-01-01T00:00:00',
            },
          }),
        })
      }
      if (url.endsWith('/datasets') && method === 'GET') {
        return Promise.resolve({ ok: true, json: async () => datasetPayload })
      }
      if (url.endsWith(`/datasets/${dataset.id}`) && method === 'DELETE') {
        return Promise.resolve(failedResponse(message))
      }
      if (url.endsWith('/test-cases')) return Promise.resolve({ ok: true, json: async () => [] })
      if (url.endsWith('/runs')) return Promise.resolve({ ok: true, json: async () => [] })
      if (url.endsWith('/failures')) return Promise.resolve({ ok: true, json: async () => [] })
      if (url.endsWith('/rubrics')) return Promise.resolve({ ok: true, json: async () => [] })
      return Promise.resolve({ ok: true, json: async () => ({}) })
    })
    vi.stubGlobal('fetch', fetchMock)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(
      React.createElement(
        QueryClientProvider,
        { client: queryClient },
        React.createElement(
          MemoryRouter,
          { initialEntries: ['/datasets'] },
          React.createElement(App),
        ),
      ),
    )

    await waitFor(() => expect(queryClient.getQueryData(['datasets'])).toEqual(datasetPayload))
    const cachedDatasets = queryClient.getQueryData(['datasets'])
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    fireEvent.click(screen.getByRole('button', { name: `Actions for ${dataset.name}` }))
    fireEvent.click(screen.getByRole('button', { name: 'Delete dataset' }))

    expect(await screen.findByText(message)).toBeInTheDocument()
    expect(screen.getByText(dataset.name)).toBeInTheDocument()
    expect(queryClient.getQueryData(['datasets'])).toBe(cachedDatasets)
    expect(fetchMock.mock.calls.filter(([input, init]) =>
      String(input).endsWith('/datasets') && (init?.method ?? 'GET') === 'GET',
    )).toHaveLength(1)
    confirm.mockRestore()
  })
})

describe('API client', () => {
  it('uses fetch responses when the backend is available', async () => {
    const data = await api.getDatasets()

    expect(data).toHaveLength(1)
    expect(data[0]?.name).toBe('Demo dataset')
  })

  it('does not substitute local Demo runs or failures when the Live backend is unavailable', async () => {
    localStorage.clear()
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Backend unavailable')))

    await expect(api.getRuns()).rejects.toThrow('Could not reach the EvalForge backend')
    await expect(api.getFailures()).rejects.toThrow('Could not reach the EvalForge backend')
    expect(localStorage.getItem('evalforge:runs')).toBeNull()
    expect(localStorage.getItem('evalforge:failures')).toBeNull()
  })

  it('preserves a successful empty failures response instead of using local sample data', async () => {
    const storedFailures = [{ id: 'local-sample-failure' }]
    localStorage.setItem('evalforge:failures', JSON.stringify(storedFailures))
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [],
    }))

    await expect(api.getFailures()).resolves.toEqual([])
    expect(JSON.parse(localStorage.getItem('evalforge:failures') ?? 'null')).toEqual(storedFailures)
  })

  it.each([
    ['HTTP', () => vi.fn().mockResolvedValue(failedResponse('Failure service unavailable'))],
    ['network', () => vi.fn().mockRejectedValue(new Error('Network unavailable'))],
  ])('propagates %s failures without returning locally stored failure records', async (_kind, createFetch) => {
    localStorage.setItem('evalforge:failures', JSON.stringify([{ id: 'local-sample-failure' }]))
    vi.stubGlobal('fetch', createFetch())

    await expect(api.getFailures()).rejects.toThrow()
    expect(localStorage.getItem('evalforge:failures')).toContain('local-sample-failure')
  })

  it.each(['create', 'update'])('propagates failed Dataset %s without changing localStorage', async () => {
    localStorage.setItem('evalforge:datasets', JSON.stringify([dataset]))
    const before = localStorageSnapshot()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(failedResponse('Dataset write rejected')))

    await expect(api.saveDataset(dataset)).rejects.toThrow('Dataset write rejected')
    expect(localStorageSnapshot()).toEqual(before)
  })

  it('propagates failed Dataset delete without changing localStorage', async () => {
    localStorage.setItem('evalforge:datasets', JSON.stringify([dataset]))
    const before = localStorageSnapshot()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(failedResponse('Dataset delete rejected')))

    await expect(api.deleteDataset(dataset.id)).rejects.toThrow('Dataset delete rejected')
    expect(localStorageSnapshot()).toEqual(before)
  })

  it('does not change Demo browser records after a Live Dataset deletion', async () => {
    localStorage.setItem('evalforge:datasets', JSON.stringify([dataset]))
    localStorage.setItem('evalforge:testCases', JSON.stringify([testCase]))
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ deleted: dataset.id }),
    }))

    await api.deleteDataset(dataset.id)

    expect(JSON.parse(localStorage.getItem('evalforge:datasets') ?? '[]')).toEqual([dataset])
    expect(JSON.parse(localStorage.getItem('evalforge:testCases') ?? '[]')).toEqual([testCase])
  })

  it.each(['create', 'update'])('propagates failed Test Case %s without changing localStorage', async () => {
    localStorage.setItem('evalforge:testCases', JSON.stringify([testCase]))
    const before = localStorageSnapshot()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(failedResponse('Test case write rejected')))

    await expect(api.saveTestCase(testCase)).rejects.toThrow('Test case write rejected')
    expect(localStorageSnapshot()).toEqual(before)
  })

  it('propagates failed Test Case delete without changing localStorage', async () => {
    localStorage.setItem('evalforge:testCases', JSON.stringify([testCase]))
    const before = localStorageSnapshot()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(failedResponse('Test case delete rejected')))

    await expect(api.deleteTestCase(testCase.id)).rejects.toThrow('Test case delete rejected')
    expect(localStorageSnapshot()).toEqual(before)
  })

  it('does not change Demo browser records after a Live Test Case deletion', async () => {
    localStorage.setItem('evalforge:testCases', JSON.stringify([testCase]))
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ deleted: testCase.id }),
    }))

    await api.deleteTestCase(testCase.id)

    expect(JSON.parse(localStorage.getItem('evalforge:testCases') ?? '[]')).toEqual([testCase])
  })

  it('propagates failed Failure review updates without changing localStorage', async () => {
    const failure: Failure = {
      id: 'failure-1',
      testCase: 'Test case',
      dataset: dataset.name,
      model: 'model',
      run_status: 'Failed',
      run_provider: 'ollama',
      failure_type: 'evaluation_error',
      category: 'Incorrect information',
      score: 0,
      timestamp: '',
      input: 'Prompt',
      expected: 'Expected',
      actual: 'Actual',
      explanation: 'Explanation',
      reviewed: true,
      humanJudgment: 'fail',
    }
    localStorage.setItem('evalforge:failures', JSON.stringify([failure]))
    const before = localStorageSnapshot()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(failedResponse('Review update rejected')))

    await expect(api.updateFailure(failure)).rejects.toThrow('Review update rejected')
    expect(localStorageSnapshot()).toEqual(before)
  })

  it('propagates failed backend run persistence without changing localStorage', async () => {
    const run = {
      id: 'run-1',
      dataset_id: dataset.id,
      datasetVersion: dataset.version,
      model: 'model',
      accuracy: 100,
      passRate: 100,
      latency: 1,
      status: 'Completed' as const,
      date: '',
      passed: 1,
      failed: 0,
      total: 1,
    }
    localStorage.setItem('evalforge:runs', JSON.stringify([run]))
    const before = localStorageSnapshot()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(failedResponse('Run persistence rejected')))

    await expect(api.addRun(run)).rejects.toThrow('Run persistence rejected')
    expect(localStorageSnapshot()).toEqual(before)
  })

  it('sends the Dataset ID as dataset_id when persisting a run', async () => {
    const run = {
      id: 'run-1',
      dataset_id: dataset.id,
      datasetVersion: dataset.version,
      model: 'model',
      accuracy: 100,
      passRate: 100,
      latency: 1,
      status: 'Completed' as const,
      date: '',
      passed: 1,
      failed: 0,
      total: 1,
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{
        ...run,
        dataset: dataset.name,
      }],
    }))

    await api.addRun(run)

    const [, init] = vi.mocked(fetch).mock.calls[0]!
    const requestBody = JSON.parse(String(init?.body)) as Record<string, unknown>
    expect(requestBody.dataset_id).toBe(dataset.id)
    expect(requestBody).not.toHaveProperty('dataset')
  })

  it('gives an actionable error when a write cannot reach the backend', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Failed to fetch')))

    await expect(api.saveDataset(dataset)).rejects.toThrow(
      'Could not reach the EvalForge backend. Check the API URL and backend availability, then try again.',
    )
  })

  it('does not use stored sample datasets when the authenticated backend is unavailable', async () => {
    localStorage.setItem('evalforge:datasets', JSON.stringify([dataset]))
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Backend unavailable')))

    await expect(api.getDatasets()).rejects.toThrow('Could not reach the EvalForge backend')
    expect(localStorage.getItem('evalforge:datasets')).toContain(dataset.id)
  })

  it('persists Mock runs locally without mixing them into Live run reads', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Backend unavailable')))
    const simulatedRuns = await api.simulateEvaluation(
      { datasetId: dataset.id, models: ['Demo model'], metrics: [], rubric: '', concurrency: 1, temperature: 0 },
      dataset,
      1,
      () => undefined,
    )

    await api.saveMockRun(simulatedRuns[0]!)

    expect(fetch).not.toHaveBeenCalled()
    expect(JSON.parse(localStorage.getItem('evalforge:demoRuns') ?? '[]')).toEqual(simulatedRuns)
    await expect(api.getDemoRuns()).resolves.toEqual(simulatedRuns)
    await expect(api.getRuns()).rejects.toThrow('Could not reach the EvalForge backend')
  }, 10000)

  it('keeps failed Dataset saves in the form and displays the backend error', async () => {
    const notify = vi.fn()
    const save = vi.fn().mockRejectedValue(new Error('Dataset write rejected'))
    render(React.createElement(DatasetPage, {
      datasets: [],
      cases: [],
      onSave: save,
      onSaveCase: vi.fn(),
      onDelete: vi.fn(),
      onNavigate: vi.fn(),
      search: '',
      notify,
    }))

    fireEvent.click(screen.getAllByRole('button', { name: 'Create dataset' })[0]!)
    fireEvent.change(screen.getByPlaceholderText('e.g. Customer support v3'), { target: { value: 'New dataset' } })
    fireEvent.submit(screen.getByPlaceholderText('e.g. Customer support v3').closest('form')!)

    expect(await screen.findByText('Dataset write rejected')).toBeInTheDocument()
    expect(save).toHaveBeenCalledOnce()
  })

  it('keeps failed Test Case saves in the form and displays the backend error', async () => {
    const save = vi.fn().mockRejectedValue(new Error('Test case write rejected'))
    render(React.createElement(TestCasePage, {
      cases: [],
      datasets: [dataset],
      onSave: save,
      onDelete: vi.fn(),
      search: '',
      notify: vi.fn(),
    }))

    fireEvent.click(screen.getByRole('button', { name: 'New test case' }))
    fireEvent.change(screen.getByPlaceholderText('e.g. Refund policy eligibility'), { target: { value: 'New case' } })
    fireEvent.change(screen.getByPlaceholderText('What should the model respond to?'), { target: { value: 'Prompt' } })
    fireEvent.change(screen.getByPlaceholderText('The ideal answer or expected behavior...'), { target: { value: 'Expected' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create test case' }))

    expect(await screen.findByText('Test case write rejected')).toBeInTheDocument()
    expect(save).toHaveBeenCalledOnce()
  })

  it('keeps a Dataset visible and displays an error when deletion fails', async () => {
    const notify = vi.fn()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const remove = vi.fn().mockRejectedValue(new Error('Dataset delete rejected'))
    render(React.createElement(DatasetPage, {
      datasets: [dataset],
      cases: [],
      onSave: vi.fn(),
      onSaveCase: vi.fn(),
      onDelete: remove,
      onNavigate: vi.fn(),
      search: '',
      notify,
    }))

    fireEvent.click(screen.getByRole('button', { name: `Actions for ${dataset.name}` }))
    fireEvent.click(screen.getByRole('button', { name: 'Delete dataset' }))

    await waitFor(() => expect(notify).toHaveBeenCalledWith('Dataset delete rejected'))
    expect(screen.getByText(dataset.name)).toBeInTheDocument()
    expect(remove).toHaveBeenCalledOnce()
    confirm.mockRestore()
  })

  it('keeps failed Test Case bulk deletes visible and displays an error', async () => {
    const notify = vi.fn()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const remove = vi.fn().mockRejectedValue(new Error('Test case delete rejected'))
    render(React.createElement(TestCasePage, {
      cases: [testCase],
      datasets: [dataset],
      onSave: vi.fn(),
      onDelete: remove,
      search: '',
      notify,
    }))

    fireEvent.click(screen.getByRole('checkbox', { name: `Select ${testCase.title}` }))
    fireEvent.click(screen.getByRole('button', { name: 'Delete 1' }))

    await waitFor(() => expect(notify).toHaveBeenCalledWith('Test case delete rejected'))
    expect(screen.getAllByText(testCase.title).length).toBeGreaterThan(0)
    expect(remove).toHaveBeenCalledOnce()
    confirm.mockRestore()
  })
})
