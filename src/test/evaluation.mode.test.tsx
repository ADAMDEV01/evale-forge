import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { EvaluationWizard } from '../pages'
import { api } from '../services/api'
import type { Dataset, EvaluationExecution, TestCase } from '../types'

const dataset: Dataset = {
  id: 'ds-live',
  name: 'Live dataset',
  description: 'test',
  version: 'v1',
  cases: 1,
  createdAt: '',
  modifiedAt: '',
  color: 'violet',
}

const testCase: TestCase = {
  id: 'case-live',
  datasetId: dataset.id,
  title: 'A real test',
  input: 'Say hello',
  expected: 'Hello',
  expectedKeywords: ['hello'],
  criteria: '',
  category: 'General',
  tags: [],
  importance: 'Medium',
  expectedBehavior: '',
}

const execution: EvaluationExecution = {
  run: {
    id: 'run-live',
    dataset: dataset.name,
    datasetVersion: dataset.version,
    model: 'llama3.2',
    provider: 'ollama',
    mode: 'ollama',
    evaluationMethod: 'exact_match',
    accuracy: 100,
    passRate: 100,
    latency: 21,
    status: 'Completed',
    date: '2026-10-30',
    passed: 1,
    failed: 0,
    total: 1,
  },
  results: [{
    id: 'result-live',
    testCaseId: testCase.id,
    testCaseTitle: testCase.title,
    category: 'General',
    status: 'Completed',
    score: 1,
    latencyMs: 21,
    input: testCase.input,
    expected: testCase.expected,
    actual: 'Hello',
    passed: true,
    evaluationMethod: 'exact_match',
    tokenUsage: 4,
    criteriaBreakdown: [],
    errorType: null,
    errorMessage: null,
  }],
  metrics: {
    accuracy: 100,
    passRate: 100,
    failureRate: 0,
    averageLatency: 21,
    averageScore: 1,
    tokenUsage: 4,
    estimatedCost: null,
  },
  errors: 0,
}

function renderWizard(onStart = vi.fn().mockResolvedValue(undefined)) {
  return {
    onStart,
    ...render(
      <MemoryRouter>
        <EvaluationWizard datasets={[dataset]} cases={[testCase]} rubrics={[]} onStart={onStart} onNavigate={vi.fn()} />
      </MemoryRouter>,
    ),
  }
}

async function openOllamaReview() {
  const user = userEvent.setup()
  await user.selectOptions(screen.getByLabelText('Evaluation mode'), 'ollama')
  await user.click(screen.getByRole('button', { name: /Continue/ }))
  await user.click(screen.getByRole('button', { name: /Continue/ }))
  await user.click(screen.getByRole('button', { name: /Continue/ }))
  return user
}

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('Evaluation mode selection', () => {
  it('keeps Mock mode explicit and lets the user select Ollama mode', async () => {
    renderWizard()
    const mode = screen.getByLabelText('Evaluation mode')
    expect(mode).toHaveValue('mock')
    fireEvent.change(mode, { target: { value: 'ollama' } })
    expect(mode).toHaveValue('ollama')
    fireEvent.change(mode, { target: { value: 'mock' } })
    expect(mode).toHaveValue('mock')
  })

  it('displays actual Ollama responses after the queued evaluation completes', async () => {
    const onStart = vi.fn().mockResolvedValue(undefined)
    renderWizard(onStart)
    const user = await openOllamaReview()
    const queuedRun = { ...execution.run, status: 'Pending' as const }
    const queued = {
      jobId: 'job-live',
      status: 'Pending',
      attempts: 0,
      progress: 0,
      pending: 1,
      lastError: null,
      run: queuedRun,
      results: [],
      metrics: execution.metrics,
      errors: 0,
    }
    const completed = {
      ...queued,
      status: 'Completed',
      progress: 100,
      pending: 0,
      run: execution.run,
      results: execution.results,
    }
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 202,
        json: async () => queued,
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => completed,
      }))

    await user.click(screen.getByRole('button', { name: /Start evaluation/ }))
    const responseLabel = await screen.findByText('Model response:', {}, { timeout: 5000 })
    expect(responseLabel.closest('p')).toHaveTextContent('Model response: Hello')
    expect(screen.getByText(/Actual model responses/)).toBeInTheDocument()
    await waitFor(() => expect(onStart).toHaveBeenLastCalledWith([execution.run], 'ollama'))
  }, 15000)

  it('shows the durable queue state without displaying simulated progress', async () => {
    const onStart = vi.fn().mockResolvedValue(undefined)
    renderWizard(onStart)
    const user = await openOllamaReview()
    let resolveRequest!: (response: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { resolveRequest = resolve })))

    await user.click(screen.getByRole('button', { name: /Start evaluation/ }))
    expect(await screen.findByText('Evaluation queued')).toBeInTheDocument()
    expect(screen.getByText('Persisted evaluation progress')).toBeInTheDocument()
    expect(screen.getByText(/progress is based on persisted test-case results/i)).toBeInTheDocument()

    const queuedRun = { ...execution.run, status: 'Pending' as const }
    resolveRequest({
      ok: true,
      status: 202,
      json: async () => ({
        jobId: 'job-pending',
        status: 'Pending',
        attempts: 0,
        progress: 0,
        pending: 1,
        lastError: null,
        run: queuedRun,
        results: [],
        metrics: execution.metrics,
        errors: 0,
      }),
    } as Response)
    await waitFor(() => expect(onStart).toHaveBeenCalledWith([queuedRun], 'ollama'))
  }, 15000)

  it('shows provider errors and never silently falls back to mock evaluation', async () => {
    renderWizard()
    const user = await openOllamaReview()
    const mockEvaluation = vi.spyOn(api, 'simulateEvaluation')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      text: async () => JSON.stringify({
        detail: { code: 'provider_connection', message: 'Could not connect to Ollama.', runId: 'run-error' },
      }),
    }))

    await user.click(screen.getByRole('button', { name: /Start evaluation/ }))
    expect(await screen.findByText('Evaluation failed')).toBeInTheDocument()
    expect(screen.getByText(/Could not connect to Ollama/)).toBeInTheDocument()
    expect(mockEvaluation).not.toHaveBeenCalled()
    expect(screen.queryByText('Demo finished')).not.toBeInTheDocument()
  })
})
