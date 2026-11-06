import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from '../App'
import { ComparisonPage, DashboardPage, HistoryPage, ReportsPage } from '../pages'
import { api } from '../services/api'
import type { Dataset, EvaluationRun, Failure } from '../types'

const { pdfMock } = vi.hoisted(() => ({
  pdfMock: {
    addPage: vi.fn(),
    setFillColor: vi.fn(),
    rect: vi.fn(),
    setFontSize: vi.fn(),
    splitTextToSize: vi.fn((text: string) => [text]),
    text: vi.fn(),
    setTextColor: vi.fn(),
    save: vi.fn(),
  },
}))

vi.mock('jspdf', () => ({ jsPDF: vi.fn(() => pdfMock) }))

vi.mock('recharts', async () => {
  const React = await import('react')
  const EmptyChartPart = () => null

  return {
    Area: EmptyChartPart,
    AreaChart: ({ data }: { data: Array<{ accuracy: number }> }) => React.createElement(
      'div',
      { 'data-testid': 'area-chart', 'data-accuracy': data.map((point) => point.accuracy).join(',') },
    ),
    Bar: EmptyChartPart,
    BarChart: ({ data }: { data: Array<{ liveRuns: number; demoRuns: number }> }) => React.createElement(
      'div',
      {
        'data-testid': 'bar-chart',
        'data-live-runs': data.map((point) => point.liveRuns).join(','),
        'data-demo-runs': data.map((point) => point.demoRuns).join(','),
      },
    ),
    CartesianGrid: EmptyChartPart,
    Cell: EmptyChartPart,
    Legend: EmptyChartPart,
    Line: EmptyChartPart,
    LineChart: ({ data }: { data: Array<{ accuracy: number }> }) => React.createElement(
      'div',
      { 'data-testid': 'line-chart', 'data-accuracy': data.map((point) => point.accuracy).join(',') },
    ),
    Pie: EmptyChartPart,
    PieChart: EmptyChartPart,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => React.createElement('div', null, children),
    Tooltip: EmptyChartPart,
    XAxis: EmptyChartPart,
    YAxis: EmptyChartPart,
  }
})

afterEach(() => {
  vi.restoreAllMocks()
})

const createRun = (overrides: Partial<EvaluationRun>): EvaluationRun => ({
  id: 'run-1',
  dataset: 'Dataset',
  datasetVersion: 'v1',
  model: 'model-a',
  provider: 'ollama',
  accuracy: 80,
  passRate: 75,
  latency: 100,
  status: 'Completed',
  date: '2026-10-30',
  passed: 3,
  failed: 1,
  total: 4,
  ...overrides,
})

const createFailure = (
  id: string,
  category: Failure['category'],
  failureType: Failure['failure_type'] = 'evaluation_failure',
  runContext: Partial<Pick<Failure, 'run_status' | 'run_provider'>> = {},
): Failure => ({
  id,
  testCase: 'Case',
  dataset: 'Dataset',
  model: 'model-a',
  run_status: 'Completed',
  run_provider: 'ollama',
  failure_type: failureType,
  category,
  score: 0,
  timestamp: '2026-10-30',
  input: '',
  expected: '',
  actual: '',
  explanation: '',
  reviewed: false,
  ...runContext,
})

describe('Reports page', () => {
  it('uses completed runs and actual failure categories for its summaries', () => {
    render(
      <ReportsPage
        runs={[
          createRun({ id: 'run-2', date: '2026-10-31', accuracy: 100, passRate: 100, latency: 200, total: 2, failed: 0 }),
          createRun({ id: 'run-1', date: '2026-10-30', accuracy: 80, passRate: 75, latency: 100, total: 4, failed: 1 }),
          createRun({ id: 'run-demo', provider: 'mock', mode: 'mock', date: '2026-10-29', accuracy: 0, passRate: 0, latency: 10000, total: 100, failed: 100 }),
          createRun({ id: 'run-running', status: 'Running', accuracy: 10, passRate: 0, latency: 999, total: 10, failed: 10 }),
          createRun({ id: 'run-failed', status: 'Failed', accuracy: 25, passRate: 0, latency: 500, total: 3, failed: 1 }),
          createRun({ id: 'run-cancelled', status: 'Cancelled', accuracy: 0, passRate: 0, latency: 0, total: 5, failed: 0 }),
        ]}
        failures={[
          createFailure('failure-1', 'General'),
          createFailure('failure-2', 'Billing', 'evaluation_error'),
        ]}
        notify={vi.fn()}
      />,
    )

    const reportScope = within(screen.getByLabelText('Report scope summary'))
    const completedRunsCard = reportScope.getByText('Completed Live provider runs').closest('.card')
    expect(completedRunsCard).not.toBeNull()
    expect(within(completedRunsCard as HTMLElement).getByText((2).toLocaleString(), { selector: 'strong' })).toBeInTheDocument()
    expect(screen.getByText('90.0%', { selector: '.report-kpis strong' })).toBeInTheDocument()
    expect(screen.getByText('16.7%')).toBeInTheDocument()
    expect(screen.getByText('150', { selector: '.report-kpis strong' })).toBeInTheDocument()
    expect(screen.getByText(/1 Demo \/ Mock run is excluded from all report metrics/)).toBeInTheDocument()
    expect(reportScope.getByText('Completed Live provider runs').closest('.card')).toHaveTextContent((2).toLocaleString())
    expect(reportScope.getByText('Failed Live provider runs').closest('.card')).toHaveTextContent((1).toLocaleString())
    expect(reportScope.getByText('Running Live provider runs').closest('.card')).toHaveTextContent((1).toLocaleString())
    expect(reportScope.getByText('Other non-completed Live runs').closest('.card')).toHaveTextContent((1).toLocaleString())
    expect(reportScope.getByText('Demo / Mock runs').closest('.card')).toHaveTextContent((1).toLocaleString())

    const modelRow = screen.getByRole('row', { name: /model-a/ })
    expect(within(modelRow).getByText('2')).toBeInTheDocument()
    expect(within(modelRow).getByText('90.0%')).toBeInTheDocument()
    expect(within(modelRow).getByText('87.5%')).toBeInTheDocument()
    expect(within(modelRow).getByText('150 ms')).toBeInTheDocument()
    expect(within(modelRow).getAllByText('—')).toHaveLength(2)

    expect(screen.getByText('General')).toBeInTheDocument()
    expect(screen.getByText('Billing')).toBeInTheDocument()
    const failureBreakdown = screen.getByLabelText('Failure type counts')
    expect(within(failureBreakdown).getByText('Evaluation Failures').parentElement).toHaveTextContent('1')
    expect(within(failureBreakdown).getByText('Evaluation Errors').parentElement).toHaveTextContent('1')
    expect(screen.queryByText('Hallucination')).not.toBeInTheDocument()
    expect(screen.getByTestId('line-chart')).toHaveAttribute('data-accuracy', '80,100')
    expect(screen.queryByText('Claude 3.5 Sonnet')).not.toBeInTheDocument()
  })

  it('shows empty states and safe KPI values when no report data exists', () => {
    render(<ReportsPage runs={[]} failures={[]} notify={vi.fn()} />)

    expect(screen.getAllByText('No completed Live evaluations')).toHaveLength(2)
    expect(screen.getByText('No recorded Live failures or errors')).toBeInTheDocument()
    const failureBreakdown = screen.getByLabelText('Failure type counts')
    expect(within(failureBreakdown).getByText('Evaluation Failures').parentElement).toHaveTextContent('0')
    expect(within(failureBreakdown).getByText('Evaluation Errors').parentElement).toHaveTextContent('0')
    expect(screen.getAllByText('—')).toHaveLength(3)
    const reportScope = within(screen.getByLabelText('Report scope summary'))
    expect(reportScope.getByText('Completed Live provider runs').closest('.card')).toHaveTextContent((0).toLocaleString())
    expect(reportScope.getByText('Failed Live provider runs').closest('.card')).toHaveTextContent((0).toLocaleString())
    expect(reportScope.getByText('Running Live provider runs').closest('.card')).toHaveTextContent((0).toLocaleString())
    expect(reportScope.getByText('Other non-completed Live runs').closest('.card')).toHaveTextContent((0).toLocaleString())
    expect(reportScope.getByText('Demo / Mock runs').closest('.card')).toHaveTextContent((0).toLocaleString())
    expect(screen.getByText('No completed Live provider evaluation results are available yet. 0 Demo / Mock runs are excluded from report metrics.')).toBeInTheDocument()
    expect(screen.queryByTestId('line-chart')).not.toBeInTheDocument()
  })

  it('keeps CSV run rows and PDF completed evaluations limited to Completed Live runs', async () => {
    pdfMock.addPage.mockClear()
    pdfMock.setFillColor.mockClear()
    pdfMock.rect.mockClear()
    pdfMock.setFontSize.mockClear()
    pdfMock.splitTextToSize.mockClear()
    pdfMock.text.mockClear()
    pdfMock.setTextColor.mockClear()
    pdfMock.save.mockClear()
    const exportedBlobs: Blob[] = []
    const createObjectURL = vi.fn((value: Blob | MediaSource) => {
      if (value instanceof Blob) exportedBlobs.push(value)
      return 'blob:report'
    })
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL: vi.fn() })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const runs = [
      createRun({ id: 'completed-live' }),
      createRun({ id: 'failed-live', status: 'Failed' }),
      createRun({ id: 'running-live', status: 'Running' }),
      createRun({ id: 'demo-run', provider: 'mock', mode: 'mock' }),
    ]
    render(
      <ReportsPage
        runs={runs}
        failures={[
          createFailure('failure-1', 'General'),
          createFailure('error-1', 'Billing', 'evaluation_error'),
          createFailure('partial-run-failure', 'General', 'evaluation_failure', { run_status: 'Failed' }),
          createFailure('sample-failure', 'Sample category', 'evaluation_failure', { run_provider: 'sample/demo' }),
        ]}
        notify={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Export CSV/ }))
    await waitFor(() => expect(exportedBlobs).toHaveLength(1))
    const csv = await exportedBlobs[0].text()
    expect(csv).toContain('"completed-live"')
    expect(csv).not.toContain('failed-live')
    expect(csv).not.toContain('running-live')
    expect(csv).not.toContain('demo-run')

    fireEvent.click(screen.getByRole('button', { name: /Download report/ }))
    await waitFor(() => expect(pdfMock.save).toHaveBeenCalledWith('evalforge-evaluation-report.pdf'))
    const pdfText = pdfMock.text.mock.calls
      .flatMap(([value]) => Array.isArray(value) ? value : [value])
      .join('\n')
    expect(pdfText).toContain('Completed evaluations: 1')
    expect(pdfText).toContain('completed-live')
    expect(pdfText).not.toContain('failed-live')
    expect(pdfText).not.toContain('running-live')
    expect(pdfText).not.toContain('demo-run')
    expect(pdfText).toContain('Evaluation failures: 2')
    expect(pdfText).toContain('Evaluation errors: 1')
    expect(pdfText).toContain('Combined failure and error records: 3')
    expect(pdfText).toContain('Failure Breakdown')
    expect(pdfText).toContain('Includes recorded live-provider evaluation failures and execution errors from parent runs with status Completed or Failed.')
    expect(pdfText).toContain('A Failed parent run may still contain persisted results useful for diagnosis.')
    expect(pdfText).toContain('General: 2 (66.7%)')
    expect(pdfText).toContain('Billing: 1 (33.3%)')
    expect(pdfText).not.toContain('Sample category')
  })

  it('exports an explicit empty PDF breakdown without adding sample failures', async () => {
    pdfMock.addPage.mockClear()
    pdfMock.setFillColor.mockClear()
    pdfMock.rect.mockClear()
    pdfMock.setFontSize.mockClear()
    pdfMock.splitTextToSize.mockClear()
    pdfMock.text.mockClear()
    pdfMock.setTextColor.mockClear()
    pdfMock.save.mockClear()
    render(<ReportsPage runs={[]} failures={[]} notify={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: /Download report/ }))
    await waitFor(() => expect(pdfMock.save).toHaveBeenCalledWith('evalforge-evaluation-report.pdf'))
    const pdfText = pdfMock.text.mock.calls
      .flatMap(([value]) => Array.isArray(value) ? value : [value])
      .join('\n')

    expect(pdfText).toContain('Evaluation failures: 0')
    expect(pdfText).toContain('Evaluation errors: 0')
    expect(pdfText).toContain('Combined failure and error records: 0')
    expect(pdfText).toContain('No recorded live-provider evaluation failures or execution errors.')
    expect(pdfText).not.toContain('FAIL-2041')
  })

  it('does not offer a PDF report when the failures API is unavailable', async () => {
    api.clearAccessToken()
    vi.spyOn(api, 'restoreSession').mockResolvedValue({
      id: 'report-user',
      email: 'reports@example.test',
      is_active: true,
      created_at: '2026-01-01T00:00:00',
    })
    vi.spyOn(api, 'getDatasets').mockResolvedValue([])
    vi.spyOn(api, 'getTestCases').mockResolvedValue([])
    vi.spyOn(api, 'getRuns').mockResolvedValue([])
    vi.spyOn(api, 'getFailures').mockRejectedValue(new Error('Failure API unavailable'))
    vi.spyOn(api, 'getRubrics').mockResolvedValue([])
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/reports']}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByText('Failure data unavailable')).toBeInTheDocument()
    expect(screen.getByText(/No sample data is being shown/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Download report/ })).not.toBeInTheDocument()
    expect(screen.queryByText(/Combined failure and error records/)).not.toBeInTheDocument()
  })
})

describe('Dashboard and run history', () => {
  const liveRun = createRun({ id: 'run-live', date: '2026-10-31', accuracy: 80, passRate: 75, latency: 100, total: 4, failed: 1, persisted_results_count: 4 })
  const demoRun = createRun({ id: 'run-demo', provider: 'mock', mode: 'mock', date: '2026-10-31', accuracy: 0, passRate: 0, latency: 10000, total: 100, failed: 100 })

  it('labels Live and Demo runs in history', () => {
    render(<HistoryPage runs={[demoRun, liveRun]} onNavigate={vi.fn()} />)

    expect(screen.getByRole('row', { name: /run-live.*Live \/ Ollama/ })).toBeInTheDocument()
    expect(screen.getByRole('row', { name: /run-demo.*Demo \/ Mock/ })).toBeInTheDocument()
    expect(screen.getByText('Avg Live accuracy').parentElement).toHaveTextContent('80.0%')
    expect(screen.getByText('Live regression alerts').parentElement).toHaveTextContent('0')
  })

  it('identifies a failed Live run with persisted partial results', () => {
    const run = createRun({
      id: 'run-partial-failure',
      status: 'Failed',
      total: 3,
      persisted_results_count: 1,
    })
    render(<HistoryPage runs={[run]} onNavigate={vi.fn()} />)

    const row = screen.getByRole('row', { name: /run-partial-failure/ })
    expect(within(row).getByText('1 / 3 results')).toBeInTheDocument()
    expect(within(row).getByText('Partial results saved')).toBeInTheDocument()
  })

  it('distinguishes a failed Live run with no persisted results', () => {
    const run = createRun({
      id: 'run-empty-failure',
      status: 'Failed',
      total: 3,
      persisted_results_count: 0,
    })
    render(<HistoryPage runs={[run]} onNavigate={vi.fn()} />)

    const row = screen.getByRole('row', { name: /run-empty-failure/ })
    expect(within(row).getByText('0 / 3 results')).toBeInTheDocument()
    expect(within(row).getByText('No results saved')).toBeInTheDocument()
    expect(within(row).queryByText('Partial results saved')).not.toBeInTheDocument()
  })

  it('shows all persisted results for a completed Live run', () => {
    const run = createRun({
      id: 'run-completed-all',
      status: 'Completed',
      total: 3,
      persisted_results_count: 3,
    })
    render(<HistoryPage runs={[run]} onNavigate={vi.fn()} />)

    const row = screen.getByRole('row', { name: /run-completed-all/ })
    expect(within(row).getByText('3 / 3 results')).toBeInTheDocument()
  })

  it('shows persisted progress for a Running Live run without calling cases unprocessed', () => {
    const run = createRun({
      id: 'run-progress',
      status: 'Running',
      total: 3,
      persisted_results_count: 1,
    })
    render(<HistoryPage runs={[run]} onNavigate={vi.fn()} />)

    const row = screen.getByRole('row', { name: /run-progress/ })
    expect(within(row).getByText('1 / 3 results')).toBeInTheDocument()
    expect(within(row).queryByText(/unprocessed/i)).not.toBeInTheDocument()
  })

  it('keeps Demo data distinct from persisted Live result counts', () => {
    const run = createRun({
      id: 'run-demo-local',
      provider: 'mock',
      mode: 'mock',
      total: 3,
      persisted_results_count: undefined,
    })
    render(<HistoryPage runs={[run]} onNavigate={vi.fn()} />)

    const row = screen.getByRole('row', { name: /run-demo-local/ })
    expect(within(row).getByText('Demo / Mock')).toBeInTheDocument()
    expect(within(row).getByText('Demo / Mock data')).toBeInTheDocument()
    expect(within(row).queryByText(/results/)).not.toBeInTheDocument()
  })

  it('uses Live runs only for dashboard performance metrics and separates run-volume counts', () => {
    render(<DashboardPage datasets={[]} cases={[]} runs={[liveRun, demoRun]} failures={[]} onNavigate={vi.fn()} />)

    expect(screen.getByText('Average accuracy').closest('.stat-card')).toHaveTextContent('80.0%')
    expect(screen.getByText('Average latency').closest('.stat-card')).toHaveTextContent('100 ms')
    expect(screen.getByText('Failure rate').closest('.stat-card')).toHaveTextContent('25.0%')
    expect(screen.getByTestId('area-chart')).toHaveAttribute('data-accuracy', '80')
    expect(screen.getByTestId('bar-chart')).toHaveAttribute('data-live-runs', '1')
    expect(screen.getByTestId('bar-chart')).toHaveAttribute('data-demo-runs', '1')
    expect(screen.getByText('Live model performance')).toBeInTheDocument()
    expect(screen.getAllByText('Demo / Mock').length).toBeGreaterThan(0)
  })

  it('prevents selected run comparisons from mixing Demo and Live results', () => {
    const dataset: Dataset = {
      id: 'dataset-1',
      name: 'Dataset',
      description: '',
      version: 'v1',
      cases: 1,
      createdAt: '',
      modifiedAt: '',
      color: 'violet',
    }

    render(
      <MemoryRouter initialEntries={['/comparisons?runs=run-live,run-demo']}>
        <ComparisonPage runs={[liveRun, demoRun]} datasets={[dataset]} />
      </MemoryRouter>,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('Demo / Mock and Live provider runs cannot be compared together.')
    expect(screen.queryByText('Selected run comparison')).not.toBeInTheDocument()
    expect(screen.getByText('Not enough Live results to compare')).toBeInTheDocument()
    expect(screen.queryByText('Catalog estimate')).not.toBeInTheDocument()
  })
})
