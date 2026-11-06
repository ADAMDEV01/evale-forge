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

  it('displays actual Ollama responses after evaluation completes', async () => {
    const onStart = vi.fn().mockResolvedValue(undefined)
    renderWizard(onStart)
    const user = await openOllamaReview()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => execution,
    }))

    await user.click(screen.getByRole('button', { name: /Start evaluation/ }))
    const responseLabel = await screen.findByText('Model response:')
    expect(responseLabel.closest('p')).toHaveTextContent('Model response: Hello')
    expect(screen.getByText(/Actual model responses/)).toBeInTheDocument()
    expect(onStart).toHaveBeenCalledWith([execution.run], 'ollama')
  }, 15000)

  it('shows a real request loading state without simulated progress', async () => {
    renderWizard()
    const user = await openOllamaReview()
    let resolveRequest!: (response: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { resolveRequest = resolve })))

    await user.click(screen.getByRole('button', { name: /Start evaluation/ }))
    expect(await screen.findByText('Live provider request running')).toBeInTheDocument()
    expect(screen.getByText(/no simulated progress/i)).toBeInTheDocument()
    resolveRequest({
      ok: true,
      json: async () => execution,
    } as Response)
    await waitFor(() => expect(screen.getByText('Evaluation complete')).toBeInTheDocument())
  })

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
