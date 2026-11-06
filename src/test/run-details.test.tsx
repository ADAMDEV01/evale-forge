import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { RunDetailPage } from '../pages'
import { api } from '../services/api'
import type { EvaluationExecution, EvaluationResult, EvaluationRun } from '../types'

vi.mock('recharts', async () => {
  const React = await import('react')
  const EmptyChartPart = () => null
  const ChartContainer = ({ children }: { children: ReactNode }) =>
    React.createElement('div', null, children)

  return {
    Area: EmptyChartPart,
    AreaChart: ChartContainer,
    Bar: EmptyChartPart,
    BarChart: ChartContainer,
    CartesianGrid: EmptyChartPart,
    Cell: EmptyChartPart,
    Legend: EmptyChartPart,
    Line: EmptyChartPart,
    LineChart: ChartContainer,
    Pie: ChartContainer,
    PieChart: ChartContainer,
    ResponsiveContainer: ChartContainer,
    Tooltip: EmptyChartPart,
    XAxis: EmptyChartPart,
    YAxis: EmptyChartPart,
  }
})

const createRun = (overrides: Partial<EvaluationRun> = {}): EvaluationRun => ({
  id: 'run-live',
  dataset: 'Dataset',
  datasetVersion: 'v1',
  model: 'llama3.2',
  provider: 'ollama',
  accuracy: 100,
  passRate: 100,
  latency: 100,
  status: 'Failed',
  date: '2026-11-01',
  passed: 1,
  failed: 0,
  total: 3,
  ...overrides,
})

const createResult = (overrides: Partial<EvaluationResult> = {}): EvaluationResult => ({
  id: 'result-1',
  testCaseId: 'case-1',
  testCaseTitle: 'Case 1',
  category: 'General',
  status: 'Completed',
  score: 1,
  latencyMs: 100,
  input: 'Prompt',
  expected: 'Expected',
  actual: 'Actual',
  passed: true,
  evaluationMethod: 'exact_match',
  tokenUsage: 7,
  criteriaBreakdown: [],
  errorType: null,
  errorMessage: null,
  ...overrides,
})

const createExecution = (
  run: EvaluationRun,
  results: EvaluationResult[],
  errors = results.filter((result) => result.status === 'Error').length,
): EvaluationExecution => ({
  run,
  results,
  metrics: {
    accuracy: 100,
    passRate: 100,
    failureRate: 0,
    averageLatency: 100,
    averageScore: 1,
    tokenUsage: 7,
    estimatedCost: null,
  },
  errors,
})

function renderRunDetails(
  run: EvaluationRun,
  execution?: EvaluationExecution,
  detailsError?: Error,
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const getRunDetails = vi.spyOn(api, 'getRunDetails')
  if (execution) getRunDetails.mockResolvedValue(execution)
  else getRunDetails.mockRejectedValue(detailsError ?? new Error('Missing test execution data'))
  return {
    getRunDetails,
    ...render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[`/evaluations/${run.id}`]}>
          <Routes>
            <Route
              path="/evaluations/:runId"
              element={<RunDetailPage runs={[run]} onNavigate={vi.fn()} />}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  }
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Live run details for partial runs', () => {
  it('distinguishes planned, persisted, completed, error, and unprocessed cases', async () => {
    const run = createRun()
    renderRunDetails(run, createExecution(run, [createResult()]))

    await waitFor(() => {
      expect(screen.getByLabelText('Run case counts')).toHaveTextContent('Planned3')
      expect(screen.getByLabelText('Run case counts')).toHaveTextContent('Persisted1')
      expect(screen.getByLabelText('Run case counts')).toHaveTextContent('Completed1')
      expect(screen.getByLabelText('Run case counts')).toHaveTextContent('Result Errors0')
      expect(screen.getByLabelText('Run case counts')).toHaveTextContent('Unprocessed2')
    })
    expect(screen.getByText('1 of 1 Completed results passed')).toBeInTheDocument()
    expect(screen.getByText('Pass rate').closest('.card')).toHaveTextContent('100%')
    expect(screen.getByText('Passed').closest('.run-outcome-legend')).toHaveTextContent('1')
    expect(within(screen.getByLabelText('Run case counts')).getByText('Unprocessed').closest('.card')).toHaveTextContent('2')
  })

  it('does not count run-level provider failure as a result error', async () => {
    const run = createRun({
      errorType: 'provider_connection',
      errorMessage: 'Could not connect to Ollama.',
    })
    renderRunDetails(run, createExecution(run, [], 0))

    await waitFor(() => {
      const counts = within(screen.getByLabelText('Run case counts'))
      expect(counts.getByText('Result Errors').closest('.card')).toHaveTextContent('Result Errors0')
    })
    expect(screen.getByRole('alert')).toHaveTextContent('provider_connection: Could not connect to Ollama.')
  })

  it('separates a persisted Error result from completed and unprocessed cases', async () => {
    const run = createRun()
    const errorResult = createResult({
      id: 'result-error',
      testCaseId: 'case-2',
      testCaseTitle: 'Case 2',
      status: 'Error',
      passed: false,
      score: 0,
      errorType: 'evaluation_engine',
      errorMessage: 'Scoring failed.',
    })
    renderRunDetails(run, createExecution(run, [createResult(), errorResult], 1))

    await waitFor(() => {
      expect(screen.getByLabelText('Run case counts')).toHaveTextContent('Planned3')
      expect(screen.getByLabelText('Run case counts')).toHaveTextContent('Persisted2')
      expect(screen.getByLabelText('Run case counts')).toHaveTextContent('Completed1')
      expect(screen.getByLabelText('Run case counts')).toHaveTextContent('Result Errors1')
      expect(screen.getByLabelText('Run case counts')).toHaveTextContent('Unprocessed1')
    })
  })

  it('does not label the remaining planned cases as unprocessed while running', async () => {
    const run = createRun({ status: 'Running' })
    renderRunDetails(run, createExecution(run, [createResult()]))

    await waitFor(() => {
      expect(screen.getByLabelText('Run case counts')).toHaveTextContent('Planned3')
      expect(screen.getByLabelText('Run case counts')).toHaveTextContent('Persisted1')
    })
    expect(screen.queryByText('Unprocessed')).not.toBeInTheDocument()
  })

  it('shows an undefined pass rate when there are no Completed results', async () => {
    const run = createRun({ accuracy: 0, passRate: 0, passed: 0 })
    const errorResult = createResult({
      status: 'Error',
      passed: false,
      score: 0,
      errorType: 'evaluation_engine',
      errorMessage: 'Scoring failed.',
    })
    renderRunDetails(run, createExecution(run, [errorResult], 1))

    expect(await screen.findByText('No Completed results; pass rate is not defined.')).toBeInTheDocument()
    expect(screen.getByText('Pass rate').closest('.card')).toHaveTextContent('—')
    expect(screen.getByText('No Completed results to calculate pass rate')).toBeInTheDocument()
    expect(screen.getByText('Accuracy').closest('.card')).toHaveTextContent('—')
  })

  it('does not fabricate result-error counts when details fail to load', async () => {
    const run = createRun({
      errorType: 'provider_connection',
      errorMessage: 'Could not connect to Ollama.',
    })
    renderRunDetails(run, undefined, new Error('Details unavailable'))

    await screen.findByText('Result counts unavailable.')
    expect(within(screen.getByLabelText('Run case counts')).getByText('Result Errors').closest('.card')).toHaveTextContent('—')
  })
})
