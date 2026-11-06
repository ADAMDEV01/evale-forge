import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams, useSearchParams } from 'react-router-dom'
import {
  ArrowDownRight, ArrowRight, ArrowUpRight, Check, CheckCheck, CheckCircle2, Database,
  ChevronDown, ChevronLeft, ChevronRight, CircleAlert, Clock3, Copy, Download, Ellipsis,
  FileDown, FileSpreadsheet, Filter, Flag, FlaskConical, Gauge,
  GitCompareArrows, Info, Layers3, LoaderCircle, MoreHorizontal, Plus, Search, ShieldCheck,
  Sparkles, Target, Timer, Trash2, Upload, X,
} from 'lucide-react'
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
  Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { initialDatasets, initialTestCases, modelMetrics } from './data/mockData'
import { api } from './services/api'
import type { Dataset, EvaluationExecution, EvaluationMethod, EvaluationMode, EvaluationRun, Failure, Importance, MockExecutionProgress, Rubric, RubricCriterion, TestCase } from './types'
import { Badge, Button, Card, EmptyState, Field, Modal, PageHeader, SearchField } from './components/ui'

type Navigate = (to: string) => void
type Notify = (message: string) => void

function isLiveRun(run: EvaluationRun) {
  return ['ollama', 'groq'].includes(run.provider ?? '')
}

function runTypeLabel(run: EvaluationRun) {
  return isLiveRun(run) ? `Live / ${run.provider === 'groq' ? 'Groq' : 'Ollama'}` : 'Demo / Mock'
}

function StatCard({ label, value, change, changeLabel, icon: Icon, tone, footnote }: { label: string; value: string; change: string; changeLabel: string; icon: typeof Gauge; tone: string; footnote: string }) {
  return <Card className="stat-card"><div className="stat-head"><span>{label}</span><span className={`stat-icon ${tone}`}><Icon size={16} /></span></div><div className="stat-value">{value}</div><div className="stat-foot"><span className="change-positive"><ArrowUpRight size={13} />{change}</span><span>{changeLabel}</span><span className="stat-period">{footnote}</span></div></Card>
}

export function DashboardPage({ datasets, cases, runs, failures, onNavigate }: { datasets: Dataset[]; cases: TestCase[]; runs: EvaluationRun[]; failures: Failure[]; onNavigate: Navigate }) {
  const liveRuns = runs.filter(isLiveRun)
  const demoRuns = runs.filter((run) => !isLiveRun(run))
  const completed = liveRuns.filter((run) => run.status === 'Completed')
  const avgAccuracy = completed.length ? (completed.reduce((sum, run) => sum + run.accuracy, 0) / completed.length).toFixed(1) : '—'
  const avgLatency = completed.length ? Math.round(completed.reduce((sum, run) => sum + run.latency, 0) / completed.length) : null
  const totalCases = completed.reduce((sum, run) => sum + run.total, 0)
  const failedCases = completed.reduce((sum, run) => sum + run.failed, 0)
  const failureRate = totalCases ? (failedCases / totalCases * 100).toFixed(1) : '—'
  const accuracySeries = [...completed].reverse().map((run) => ({
    date: run.date,
    accuracy: run.accuracy,
  }))
  const runCounts = new Map<string, { liveRuns: number; demoRuns: number }>()
  for (const run of runs) {
    const date = run.date.slice(0, 10)
    const counts = runCounts.get(date) ?? { liveRuns: 0, demoRuns: 0 }
    if (isLiveRun(run)) counts.liveRuns += 1
    else counts.demoRuns += 1
    runCounts.set(date, counts)
  }
  const volumeSeries = [...runCounts].map(([date, counts]) => ({ date, ...counts }))
  const modelSummaries = [...new Set(completed.map((run) => run.model))].map((model) => {
    const modelRuns = completed.filter((run) => run.model === model)
    return {
      name: model,
      provider: modelRuns[0]?.provider ?? 'unknown',
      accuracy: modelRuns.reduce((sum, run) => sum + run.accuracy, 0) / modelRuns.length,
      color: modelMetrics.find((metric) => metric.name === model)?.color ?? '#a78bfa',
    }
  })
  const pendingFailures = failures.filter((failure) => !failure.reviewed)
  const currentHour = new Date().getHours()
  const greeting = currentHour < 12 ? 'Good morning' : currentHour < 18 ? 'Good afternoon' : 'Good evening'
  const today = new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }).toUpperCase()
  return <div className="page">
    <PageHeader eyebrow={today} title={greeting} description="Here’s what’s happening across your AI evaluations." actions={<><Button onClick={() => onNavigate('/datasets')}><Plus size={15} /> New dataset</Button><Button variant="primary" onClick={() => onNavigate('/evaluations/new')}><FlaskConical size={15} /> Run evaluation</Button></>} />
    <div className="stats-grid">
      <StatCard label="Evaluation runs" value={runs.length.toLocaleString()} change={`${liveRuns.length} Live · ${demoRuns.length} Demo`} changeLabel="all run types" footnote={`${datasets.length} datasets`} icon={FlaskConical} tone="violet-icon" />
      <StatCard label="Average accuracy" value={avgAccuracy === '—' ? '—' : `${avgAccuracy}%`} change={`${completed.length} runs`} changeLabel="Live provider" footnote="Live runs only" icon={Target} tone="blue-icon" />
      <StatCard label="Average latency" value={avgLatency === null ? '—' : `${avgLatency} ms`} change={`${completed.length} runs`} changeLabel="Live provider" footnote="Live runs only" icon={Timer} tone="green-icon" />
      <StatCard label="Failure rate" value={failureRate === '—' ? '—' : `${failureRate}%`} change={`${failedCases} failed tests`} changeLabel="Live provider completed runs" footnote={`${totalCases.toLocaleString()} live tests evaluated`} icon={ShieldCheck} tone="amber-icon" />
    </div>
    <div className="dashboard-charts">
      <Card className="chart-card accuracy-chart"><div className="card-heading"><div><h2>Live accuracy over time</h2><p>Completed Live provider evaluation runs only</p></div></div><div className="chart-legend"><span><i className="legend-dot violet-dot" />Live provider</span></div><div className="chart-wrap chart-lg"><ResponsiveContainer width="100%" height="100%"><AreaChart data={accuracySeries} margin={{ top: 10, right: 8, left: -20, bottom: 0 }}><defs><linearGradient id="accuracyFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#9b87f5" stopOpacity={0.17} /><stop offset="100%" stopColor="#9b87f5" stopOpacity={0} /></linearGradient></defs><CartesianGrid stroke="#20232c" vertical={false} /><XAxis dataKey="date" tickLine={false} axisLine={false} tick={{ fill: '#7c8393', fontSize: 11 }} dy={10} /><YAxis domain={[0, 100]} tickLine={false} axisLine={false} tick={{ fill: '#7c8393', fontSize: 11 }} tickFormatter={(value) => `${value}%`} /><Tooltip contentStyle={{ background: '#171a22', border: '1px solid #2a2e39', borderRadius: 8, color: '#e5e7eb', fontSize: 12 }} /><Area type="monotone" dataKey="accuracy" name="Live provider accuracy" stroke="#a78bfa" strokeWidth={2} fill="url(#accuracyFill)" /></AreaChart></ResponsiveContainer></div></Card>
      <Card className="chart-card runs-chart"><div className="card-heading"><div><h2>Run volume</h2><p>Live and Demo runs grouped by run date</p></div><span className="chart-total"><strong>{runs.length}</strong><small>total runs</small></span></div><div className="chart-legend"><span><i className="legend-dot violet-dot" />Live provider</span><span><i className="legend-dot" />Demo / Mock</span></div><div className="chart-wrap chart-lg"><ResponsiveContainer width="100%" height="100%"><BarChart data={volumeSeries} margin={{ top: 14, right: 0, left: -26, bottom: 0 }}><CartesianGrid stroke="#20232c" vertical={false} /><XAxis dataKey="date" tickLine={false} axisLine={false} tick={{ fill: '#7c8393', fontSize: 10 }} dy={10} /><YAxis tickLine={false} axisLine={false} tick={{ fill: '#7c8393', fontSize: 10 }} /><Tooltip cursor={{ fill: '#262a34' }} contentStyle={{ background: '#171a22', border: '1px solid #2a2e39', borderRadius: 8, color: '#e5e7eb', fontSize: 12 }} /><Bar dataKey="liveRuns" name="Live provider" stackId="runs" fill="#806cf0" radius={[4, 4, 0, 0]} barSize={20} /><Bar dataKey="demoRuns" name="Demo / Mock" stackId="runs" fill="#687386" radius={[4, 4, 0, 0]} barSize={20} /></BarChart></ResponsiveContainer></div><div className="chart-summary"><span>{liveRuns.length} Live provider</span><span>{demoRuns.length} Demo / Mock</span></div></Card>
    </div>
    <div className="dashboard-lower">
      <Card className="table-card recent-runs"><div className="card-heading"><div><h2>Recent evaluation runs</h2><p>Demo and Live runs are labeled separately</p></div><button className="text-button" onClick={() => onNavigate('/evaluations')}>View all <ArrowRight size={14} /></button></div><RunTable runs={runs.slice(0, 4)} onNavigate={onNavigate} compact /></Card>
      <Card className="model-summary"><div className="card-heading"><div><h2>Live model performance</h2><p>Average across completed Live provider runs only</p></div></div>{modelSummaries.length ? <div className="model-list">{modelSummaries.map((model, index) => <div className="model-row" key={model.name}><span className={`rank rank-${index + 1}`}>{index + 1}</span><span className="model-avatar" style={{ color: model.color, background: `${model.color}17` }}>{model.name.split(' ').map((word) => word[0]).slice(0, 2).join('')}</span><span className="model-name"><strong>{model.name}</strong><small>{model.provider}</small></span><span className="model-score">{model.accuracy.toFixed(1)}%<small>accuracy</small></span></div>)}</div> : <p className="muted-copy">No completed Live provider evaluation runs yet.</p>}<button className="model-compare" onClick={() => onNavigate('/comparisons')}><GitCompareArrows size={14} /> Compare models <ArrowRight size={13} /></button></Card>
    </div>
    <div className="dashboard-bottom">
      <Card className="failed-card"><div className="card-heading"><div><h2>Live evaluation failures</h2><p>Cases from persisted Live provider runs that need a closer look</p></div><Badge tone="red">{pendingFailures.length} unreviewed</Badge></div>{pendingFailures.slice(0, 3).map((failure) => <button className="failure-preview" key={failure.id} onClick={() => onNavigate('/failures')}><span className="failure-alert"><CircleAlert size={15} /></span><span className="failure-preview-copy"><strong>{failure.testCase}</strong><small>{failure.model} · {failure.dataset}</small></span><Badge tone={failure.category === 'Hallucination' ? 'violet' : 'yellow'}>{failure.category}</Badge><ChevronRight size={15} /></button>)}{pendingFailures.length === 0 && <p className="muted-copy">No unreviewed Live provider failures. Nice work.</p>}</Card>
      <Card className="dataset-summary"><div className="card-heading"><div><h2>Active datasets</h2><p>{datasets.length} datasets · {cases.length} test cases</p></div><button className="text-button" onClick={() => onNavigate('/datasets')}>Manage <ArrowRight size={14} /></button></div>{datasets.slice(0, 4).map((dataset) => <div className="dataset-mini" key={dataset.id}><span className={`dataset-dot ${dataset.color}`} /><span><strong>{dataset.name}</strong><small>{dataset.version} · {dataset.cases} cases</small></span><span className="dataset-mini-date">{new Date(`${dataset.modifiedAt}T12:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span></div>)}</Card>
    </div>
  </div>
}

export function RunTable({ runs, onNavigate, compact = false }: { runs: EvaluationRun[]; onNavigate: Navigate; compact?: boolean }) {
  return <div className="table-wrap"><table className={`data-table ${compact ? 'compact-table' : ''}`}><thead><tr><th>Run</th><th>Type</th><th>Dataset</th><th>Model</th><th>Accuracy</th><th>Latency</th><th>Status</th>{!compact && <th>Started</th>}</tr></thead><tbody>{runs.map((run) => <tr key={run.id} className="clickable-row" onClick={() => onNavigate(`/evaluations/${run.id}`)}><td><span className="run-id">{run.id}</span></td><td><Badge tone={isLiveRun(run) ? 'violet' : 'neutral'}>{runTypeLabel(run)}</Badge></td><td><span className="table-primary">{run.dataset}</span><small className="table-secondary">{run.datasetVersion}</small></td><td><span className="model-cell-dot" />{run.model}</td><td><span className="metric-strong">{run.accuracy}%</span><span className="mini-bar"><i style={{ width: `${run.accuracy}%` }} /></span></td><td>{run.latency.toLocaleString()} ms</td><td><Badge tone={run.status === 'Completed' ? 'green' : run.status === 'Running' ? 'blue' : 'red'}><i className="status-dot" />{run.status}</Badge></td>{!compact && <td className="date-cell">{run.date}</td>}</tr>)}</tbody></table>{runs.length === 0 && <EmptyState title="No evaluation runs yet" description="Create an evaluation to see run results here." />}</div>
}

function DatasetForm({ dataset, onClose, onSave }: { dataset?: Dataset; onClose: () => void; onSave: (dataset: Dataset) => Promise<unknown> }) {
  const [name, setName] = useState(dataset?.name ?? '')
  const [description, setDescription] = useState(dataset?.description ?? '')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!name.trim()) { setError('Dataset name is required.'); return }
    setSaving(true)
    try {
      await onSave({ id: dataset?.id ?? `ds-${Date.now()}`, name: name.trim(), description: description.trim(), version: dataset?.version ?? 'v1.0', cases: dataset?.cases ?? 0, createdAt: dataset?.createdAt ?? new Date().toISOString().slice(0, 10), modifiedAt: new Date().toISOString().slice(0, 10), color: dataset?.color ?? 'violet' })
      onClose()
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Dataset could not be saved.')
    } finally {
      setSaving(false)
    }
  }
  return <Modal title={dataset ? 'Edit dataset' : 'Create dataset'} description="Organize a versioned collection of evaluation test cases." onClose={onClose}><form className="form-stack" onSubmit={(event) => void submit(event)}><Field label="Dataset name"><input autoFocus value={name} onChange={(event) => { setName(event.target.value); setError('') }} placeholder="e.g. Customer support v3" /></Field><Field label="Description"><textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="What should this dataset evaluate?" rows={3} /></Field>{error && <span className="form-error">{error}</span>}<div className="modal-actions"><Button type="button" onClick={onClose} disabled={saving}>Cancel</Button><Button variant="primary" type="submit" disabled={saving}>{saving ? 'Saving…' : dataset ? 'Save changes' : 'Create dataset'}</Button></div></form></Modal>
}

export function DatasetPage({ datasets, cases, onSave, onSaveCase, onDelete, onNavigate, search, notify }: { datasets: Dataset[]; cases: TestCase[]; onSave: (dataset: Dataset) => Promise<unknown>; onSaveCase: (testCase: TestCase) => Promise<unknown>; onDelete: (id: string) => Promise<unknown>; onNavigate: Navigate; search: string; notify: Notify }) {
  const [query, setQuery] = useState(search)
  const [modal, setModal] = useState<Dataset | null | undefined>(undefined)
  const [versionDataset, setVersionDataset] = useState<Dataset | null>(null)
  const [showVersions, setShowVersions] = useState<string | null>(null)
  const filtered = datasets.filter((dataset) => `${dataset.name} ${dataset.description}`.toLowerCase().includes(query.toLowerCase()))
  useEffect(() => setQuery(search), [search])
  const deleteDataset = async (id: string) => {
    try {
      await onDelete(id)
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Dataset could not be deleted.')
    }
  }
  const doImport = async (file?: File) => {
    if (!file) return
    try {
      const text = await file.text()
      let records: Record<string, unknown>[]
      if (file.name.toLowerCase().endsWith('.json')) {
        const parsed: unknown = JSON.parse(text)
        const payload = Array.isArray(parsed) ? parsed : parsed && typeof parsed === 'object' && 'testCases' in parsed ? (parsed as { testCases: unknown }).testCases : null
        if (!Array.isArray(payload)) throw new Error('JSON must contain an array of test cases')
        records = payload.filter((row): row is Record<string, unknown> => !!row && typeof row === 'object' && !Array.isArray(row))
      } else {
        const lines = text.split(/\r?\n/).filter((line) => line.trim())
        if (lines.length < 2) throw new Error('CSV must include a header and at least one test case')
        const parseRow = (line: string) => {
          const columns: string[] = []
          let cell = ''
          let quoted = false
          for (let index = 0; index < line.length; index += 1) {
            const char = line[index]
            if (char === '"' && quoted && line[index + 1] === '"') { cell += '"'; index += 1 }
            else if (char === '"') quoted = !quoted
            else if (char === ',' && !quoted) { columns.push(cell.trim()); cell = '' }
            else cell += char
          }
          columns.push(cell.trim())
          return columns
        }
        const headers = parseRow(lines[0]).map((header) => header.toLowerCase())
        records = lines.slice(1).map((line) => Object.fromEntries(parseRow(line).map((value, index) => [headers[index], value])))
      }
      if (!records.length) throw new Error('No valid test case records were found')
      const readText = (record: Record<string, unknown>, keys: string[]) => {
        const key = Object.keys(record).find((candidate) => keys.includes(candidate.toLowerCase()))
        return key && typeof record[key] === 'string' ? record[key].trim() : ''
      }
      const datasetId = `ds-${Date.now()}`
      const importedCases = records.map((record, index) => {
        const input = readText(record, ['input', 'prompt', 'question'])
        const expected = readText(record, ['expected', 'expected_answer', 'expectedanswer', 'reference'])
        if (!input || !expected) throw new Error(`Test case ${index + 1} needs input/prompt and expected/expected_answer fields`)
        return {
          id: `TC-${Math.floor(1000 + Math.random() * 8999)}-${index}`,
          datasetId,
          title: readText(record, ['title', 'name']) || `Imported test case ${index + 1}`,
          input,
          expected,
          criteria: readText(record, ['criteria', 'evaluation_criteria']) || 'Evaluate for correctness and relevance.',
          category: readText(record, ['category']) || 'Imported',
          tags: [],
          importance: 'Medium' as Importance,
          expectedBehavior: 'Respond accurately and follow all instructions.',
        }
      })
      await onSave({ id: datasetId, name: file.name.replace(/\.(csv|json)$/i, ''), description: `Imported from ${file.name}`, version: 'v1.0', cases: importedCases.length, createdAt: new Date().toISOString().slice(0, 10), modifiedAt: new Date().toISOString().slice(0, 10), color: 'blue' })
      await Promise.all(importedCases.map((testCase) => onSaveCase(testCase)))
      notify(`Imported ${importedCases.length} test cases from ${file.name}`)
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Dataset import failed due to an unknown error.')
    }
  }
  const duplicateDataset = async (dataset: Dataset) => {
    const id = `ds-${Date.now()}`
    try {
      await onSave({ ...dataset, id, name: `${dataset.name} copy`, version: 'v1.0', createdAt: new Date().toISOString().slice(0, 10), modifiedAt: new Date().toISOString().slice(0, 10) })
      await Promise.all(cases.filter((testCase) => testCase.datasetId === dataset.id).map((testCase, index) => onSaveCase({ ...testCase, id: `${id}-${index + 1}`, datasetId: id })))
      notify('Dataset and its test cases duplicated')
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Dataset duplication failed.')
    }
  }
  return <div className="page"><PageHeader eyebrow="WORKSPACE / DATA" title="Datasets" description="Curate and version the data that powers your evaluations." actions={<><label className="button button-secondary button-md upload-label"><Upload size={15} /> Import dataset<input type="file" accept=".csv,.json,application/json,text/csv" onChange={(event) => { void doImport(event.target.files?.[0]); event.currentTarget.value = '' }} /></label><Button variant="primary" onClick={() => setModal(null)}><Plus size={15} /> Create dataset</Button></>} />
    <div className="dataset-toolbar"><SearchField value={query} onChange={setQuery} placeholder="Search datasets..." /><div className="toolbar-right"><span className="result-count">{filtered.length} datasets</span><button className="select-button" onClick={() => notify('Showing all datasets')}><Filter size={14} /> All datasets <ChevronDown size={14} /></button></div></div>
    {filtered.length ? <div className="dataset-grid">{filtered.map((dataset) => {
      const caseCount = cases.filter((testCase) => testCase.datasetId === dataset.id).length
      return <Card className="dataset-card" key={dataset.id}><div className="dataset-card-top"><div className={`dataset-icon ${dataset.color}`}><Database size={18} /></div><button className="icon-button" aria-label={`Actions for ${dataset.name}`} onClick={() => setShowVersions(showVersions === dataset.id ? null : dataset.id)}><Ellipsis size={18} /></button>{showVersions === dataset.id && <div className="popover-menu"><button onClick={() => { setVersionDataset(dataset); setShowVersions(null) }}><Layers3 size={14} /> Version history</button><button onClick={() => { void duplicateDataset(dataset); setShowVersions(null) }}><Copy size={14} /> Duplicate</button><button onClick={() => { setModal(dataset); setShowVersions(null) }}><MoreHorizontal size={14} /> Edit details</button><button className="danger-menu-item" onClick={() => { if (window.confirm(`Delete "${dataset.name}"?`)) void deleteDataset(dataset.id); setShowVersions(null) }}><Trash2 size={14} /> Delete dataset</button></div>}</div><h3>{dataset.name}</h3><p className="dataset-description">{dataset.description}</p><div className="dataset-stats"><span><BookOpenIcon />{caseCount} test cases</span><Badge tone="violet">{dataset.version}</Badge></div><div className="dataset-footer"><span>Updated {new Date(`${dataset.modifiedAt}T12:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</span><button onClick={() => onNavigate(`/datasets/${encodeURIComponent(dataset.id)}`)}>Open dataset <ArrowRight size={13} /></button></div></Card>
    })}</div> : <EmptyState title="No datasets found" description="Try a different search, or create a dataset to get started." action={<Button variant="primary" onClick={() => setModal(null)}><Plus size={14} /> Create dataset</Button>} />}
    {modal !== undefined && <DatasetForm dataset={modal ?? undefined} onClose={() => setModal(undefined)} onSave={onSave} />}
    {versionDataset && <Modal title="Dataset version history" description={`${versionDataset.name} · current ${versionDataset.version}`} onClose={() => setVersionDataset(null)}><div className="version-list"><div><span className="version-dot current" /><span><strong>{versionDataset.version}</strong><small>Current version · {versionDataset.cases} test cases</small></span><Badge tone="green">Current</Badge></div><div><span className="version-dot" /><span><strong>v2.3</strong><small>Feb 08, 2025 · 244 test cases</small></span><button className="text-button" onClick={() => notify('Version restore prepared')}>Restore</button></div><div><span className="version-dot" /><span><strong>v2.2</strong><small>Jan 29, 2025 · 231 test cases</small></span><button className="text-button" onClick={() => notify('Version restore prepared')}>Restore</button></div><div><span className="version-dot" /><span><strong>v2.1</strong><small>Jan 16, 2025 · 216 test cases</small></span><button className="text-button" onClick={() => notify('Version restore prepared')}>Restore</button></div></div></Modal>}
  </div>
}

export function DatasetDetailsPage({ datasets, cases, onNavigate }: { datasets: Dataset[]; cases: TestCase[]; onNavigate: Navigate }) {
  const { datasetId } = useParams<{ datasetId: string }>()
  const dataset = datasets.find((item) => item.id === datasetId)

  if (!dataset) {
    return <div className="page"><EmptyState title="Dataset not found" description="This dataset may have been removed or the link may be incorrect." action={<Button onClick={() => onNavigate('/datasets')}>Back to datasets</Button>} /></div>
  }

  const datasetCases = cases.filter((testCase) => testCase.datasetId === dataset.id)

  return <div className="page">
    <PageHeader
      eyebrow="WORKSPACE / DATASET"
      title={dataset.name}
      description={dataset.description}
      actions={<Button onClick={() => onNavigate('/datasets')}><ChevronLeft size={14} /> All datasets</Button>}
    />
    <Card className="case-table-card">
      <div className="card-heading">
        <div><h2>Test cases</h2><p>{dataset.version} · {datasetCases.length} test cases</p></div>
      </div>
      {datasetCases.length ? <div className="table-wrap"><table className="data-table test-case-table">
        <thead><tr><th>Test case</th><th>Category</th><th>Importance</th><th>Tags</th></tr></thead>
        <tbody>{datasetCases.map((testCase) => <tr key={testCase.id}>
          <td><strong>{testCase.title}</strong><small className="table-secondary">{testCase.input}</small></td>
          <td><Badge tone="neutral">{testCase.category}</Badge></td>
          <td><ImportanceBadge importance={testCase.importance} /></td>
          <td><div className="tag-list">{testCase.tags.map((tag) => <span className="tag" key={tag}>{tag}</span>)}</div></td>
        </tr>)}</tbody>
      </table></div> : <EmptyState title="No test cases in this dataset" description="Test cases associated with this dataset will appear here." />}
    </Card>
  </div>
}

function BookOpenIcon() { return <Layers3 size={14} /> }

function TestCaseForm({ testCase, datasets, onClose, onSave }: { testCase?: TestCase; datasets: Dataset[]; onClose: () => void; onSave: (testCase: TestCase) => Promise<unknown> }) {
  const [title, setTitle] = useState(testCase?.title ?? '')
  const [input, setInput] = useState(testCase?.input ?? '')
  const [expected, setExpected] = useState(testCase?.expected ?? '')
  const [expectedKeywords, setExpectedKeywords] = useState(testCase?.expectedKeywords?.join(', ') ?? '')
  const [criteria, setCriteria] = useState(testCase?.criteria ?? '')
  const [datasetId, setDatasetId] = useState(testCase?.datasetId ?? datasets[0]?.id ?? '')
  const [category, setCategory] = useState(testCase?.category ?? 'General')
  const [importance, setImportance] = useState<Importance>(testCase?.importance ?? 'Medium')
  const [tags, setTags] = useState(testCase?.tags.join(', ') ?? '')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!title.trim() || !input.trim() || !expected.trim()) { setError('Title, input, and expected answer are required.'); return }
    setSaving(true)
    try {
      await onSave({ id: testCase?.id ?? `TC-${Math.floor(1000 + Math.random() * 8999)}`, datasetId, title: title.trim(), input: input.trim(), expected: expected.trim(), expectedKeywords: expectedKeywords.split(',').map((keyword) => keyword.trim()).filter(Boolean), criteria: criteria.trim() || 'Evaluate for correctness and relevance.', category, importance, tags: tags.split(',').map((tag) => tag.trim()).filter(Boolean), expectedBehavior: testCase?.expectedBehavior ?? 'Respond accurately and follow all instructions.' })
      onClose()
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Test case could not be saved.')
    } finally {
      setSaving(false)
    }
  }
  return <Modal title={testCase ? 'Edit test case' : 'New test case'} description="Define the prompt and the behavior you expect from the model." onClose={onClose} wide><form className="form-stack" onSubmit={(event) => void submit(event)}><div className="form-two-col"><Field label="Test case name"><input autoFocus value={title} onChange={(event) => setTitle(event.target.value)} placeholder="e.g. Refund policy eligibility" /></Field><Field label="Dataset"><select value={datasetId} onChange={(event) => setDatasetId(event.target.value)}>{datasets.map((dataset) => <option value={dataset.id} key={dataset.id}>{dataset.name}</option>)}</select></Field></div><Field label="Input prompt"><textarea rows={3} value={input} onChange={(event) => setInput(event.target.value)} placeholder="What should the model respond to?" /></Field><Field label="Expected answer"><textarea rows={3} value={expected} onChange={(event) => setExpected(event.target.value)} placeholder="The ideal answer or expected behavior..." /></Field><Field label="Expected keywords (comma-separated)"><input value={expectedKeywords} onChange={(event) => setExpectedKeywords(event.target.value)} placeholder="business plan, audit logs" /></Field><Field label="Evaluation criteria"><textarea rows={2} value={criteria} onChange={(event) => setCriteria(event.target.value)} placeholder="How should this answer be scored?" /></Field><div className="form-three-col"><Field label="Category"><input value={category} onChange={(event) => setCategory(event.target.value)} /></Field><Field label="Importance"><select value={importance} onChange={(event) => setImportance(event.target.value as Importance)}>{['Critical', 'High', 'Medium', 'Low'].map((value) => <option key={value}>{value}</option>)}</select></Field><Field label="Tags"><input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="billing, policy" /></Field></div>{error && <span className="form-error">{error}</span>}<div className="modal-actions"><Button type="button" onClick={onClose} disabled={saving}>Cancel</Button><Button variant="primary" type="submit" disabled={saving}>{saving ? 'Saving…' : testCase ? 'Save changes' : 'Create test case'}</Button></div></form></Modal>
}

export function TestCasePage({ cases, datasets, onSave, onDelete, search, notify }: { cases: TestCase[]; datasets: Dataset[]; onSave: (testCase: TestCase) => Promise<unknown>; onDelete: (id: string) => Promise<unknown>; search: string; notify: Notify }) {
  const [query, setQuery] = useState(search)
  const [datasetFilter, setDatasetFilter] = useState('all')
  const [modal, setModal] = useState<TestCase | null | undefined>(undefined)
  const [selected, setSelected] = useState<string[]>([])
  useEffect(() => setQuery(search), [search])
  const filtered = useMemo(() => cases.filter((testCase) => `${testCase.title} ${testCase.input} ${testCase.category} ${testCase.tags.join(' ')}`.toLowerCase().includes(query.toLowerCase()) && (datasetFilter === 'all' || testCase.datasetId === datasetFilter)), [cases, datasetFilter, query])
  const toggle = (id: string) => setSelected((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id])
  const bulkDelete = async () => {
    if (!window.confirm(`Delete ${selected.length} selected test cases?`)) return
    try {
      await Promise.all(selected.map(onDelete))
      setSelected([])
      notify('Selected test cases deleted')
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Test cases could not be deleted.')
    }
  }
  return <div className="page"><PageHeader eyebrow="WORKSPACE / DATA" title="Test cases" description="Define expected behaviors and the criteria your models should meet." actions={<Button variant="primary" onClick={() => setModal(null)}><Plus size={15} /> New test case</Button>} />
    <div className="dataset-toolbar case-toolbar"><SearchField value={query} onChange={setQuery} placeholder="Search test cases..." /><div className="toolbar-right">{selected.length > 0 && <Button size="sm" variant="danger" onClick={() => void bulkDelete()}><Trash2 size={13} /> Delete {selected.length}</Button>}<select className="select-button" value={datasetFilter} onChange={(event) => setDatasetFilter(event.target.value)}><option value="all">All datasets</option>{datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.name}</option>)}</select><span className="result-count">{filtered.length} cases</span></div></div>
    <Card className="case-table-card"><div className="table-wrap"><table className="data-table test-case-table"><thead><tr><th><input type="checkbox" checked={filtered.length > 0 && filtered.every((item) => selected.includes(item.id))} onChange={() => setSelected(filtered.every((item) => selected.includes(item.id)) ? selected.filter((id) => !filtered.some((item) => item.id === id)) : [...new Set([...selected, ...filtered.map((item) => item.id)])])} aria-label="Select all test cases" /></th><th>Test case</th><th>Dataset</th><th>Category</th><th>Importance</th><th>Tags</th><th /></tr></thead><tbody>{filtered.map((testCase) => <tr key={testCase.id}><td><input type="checkbox" checked={selected.includes(testCase.id)} onChange={() => toggle(testCase.id)} aria-label={`Select ${testCase.title}`} /></td><td><button className="case-name-cell" onClick={() => setModal(testCase)}><strong>{testCase.title}</strong><small>{testCase.id} · {testCase.input.slice(0, 66)}{testCase.input.length > 66 ? '…' : ''}</small></button></td><td>{datasets.find((dataset) => dataset.id === testCase.datasetId)?.name ?? '—'}</td><td><Badge tone="neutral">{testCase.category}</Badge></td><td><ImportanceBadge importance={testCase.importance} /></td><td><div className="tag-list">{testCase.tags.slice(0, 2).map((tag) => <span className="tag" key={tag}>{tag}</span>)}</div></td><td><button className="icon-button" onClick={() => setModal(testCase)} aria-label={`Edit ${testCase.title}`}><MoreHorizontal size={16} /></button></td></tr>)}</tbody></table>{filtered.length === 0 && <EmptyState title="No test cases found" description="Change the filters or add your first test case." />}</div></Card>
    {modal !== undefined && <TestCaseForm testCase={modal ?? undefined} datasets={datasets} onClose={() => setModal(undefined)} onSave={onSave} />}
  </div>
}

function ImportanceBadge({ importance }: { importance: Importance }) {
  const tone = importance === 'Critical' || importance === 'High' ? 'red' : importance === 'Medium' ? 'yellow' : 'neutral'
  return <Badge tone={tone}>{importance}</Badge>
}

export function ModelsPage() {
  const ollamaHealth = useQuery({
    queryKey: ['ollama-health'],
    queryFn: () => api.checkProvider('ollama'),
    refetchInterval: 15000,
    retry: 1,
  })

  const groqHealth = useQuery({
    queryKey: ['groq-health'],
    queryFn: () => api.checkProvider('groq'),
    refetchInterval: 60000,
    retry: 1,
  })

  const connected = Boolean(
    ollamaHealth.data?.available &&
    ollamaHealth.data?.modelInstalled
  )
  const groqConnected = Boolean(groqHealth.data?.available)

  return (
    <div className="page">
      <PageHeader
        eyebrow="ANALYZE / PROVIDERS"
        title="Models"
        description="Monitor provider performance and configure the models your team evaluates."
        actions={
          <Button
            variant="primary"
            onClick={() => { void ollamaHealth.refetch(); void groqHealth.refetch() }}
          >
            <LoaderCircle size={15} />
            Refresh status
          </Button>
        }
      />

      <div className="model-cards">
        <Card className="provider-card">
          <div className="provider-heading">
            <span className="provider-logo">O</span>

            <span>
              <strong>Ollama</strong>
              <small>Local AI provider · Model endpoint</small>
            </span>

            {ollamaHealth.isLoading ? (
              <Badge tone="green">Checking...</Badge>
            ) : connected ? (
              <Badge tone="green">
                <i className="status-dot" />
                Connected
              </Badge>
            ) : (
              <Badge tone="red">Disconnected</Badge>
            )}
          </div>

          <div className="provider-stats">
            <div>
              <small>Model</small>
              <strong>{ollamaHealth.data?.model ?? 'Unavailable'}</strong>
            </div>

            <div>
              <small>Installation</small>
              <strong>
                {ollamaHealth.data?.modelInstalled === true
                  ? 'Installed'
                  : ollamaHealth.data?.modelInstalled === false
                    ? 'Not installed'
                    : 'Unknown'}
              </strong>
            </div>

            <div>
              <small>Provider</small>
              <strong>
                {ollamaHealth.data?.available
                  ? 'Available'
                  : 'Unavailable'}
              </strong>
            </div>
          </div>

          <div className="provider-footer">
            <span>
              {ollamaHealth.isLoading
                ? 'Checking Ollama connection...'
                : connected
                  ? 'Local model is ready'
                  : ollamaHealth.data?.error?.message ??
                    (ollamaHealth.isError
                      ? 'Could not reach the backend'
                      : 'Ollama is not ready')}
            </span>
          </div>
        </Card>
        <Card className="provider-card">
          <div className="provider-heading">
            <span className="provider-logo">G</span>
            <span>
              <strong>Groq</strong>
              <small>Hosted AI provider · API endpoint</small>
            </span>
            {groqHealth.isLoading ? (
              <Badge tone="green">Checking...</Badge>
            ) : groqConnected ? (
              <Badge tone="green"><i className="status-dot" />Connected</Badge>
            ) : (
              <Badge tone="red">Disconnected</Badge>
            )}
          </div>
          <div className="provider-stats">
            <div><small>Model</small><strong>{groqHealth.data?.model ?? 'Unavailable'}</strong></div>
            <div><small>API key</small><strong>{groqHealth.data?.available ? 'Accepted' : 'Not verified'}</strong></div>
            <div><small>Provider</small><strong>{groqHealth.data?.available ? 'Available' : 'Unavailable'}</strong></div>
          </div>
          <div className="provider-footer">
            <span>{groqHealth.isLoading ? 'Checking Groq connection...' : groqConnected ? 'Hosted model is ready' : groqHealth.data?.error?.message ?? (groqHealth.isError ? 'Could not reach the backend' : 'Check GROQ_API_KEY in the backend environment')}</span>
          </div>
        </Card>
      </div>

      <Card className="provider-note">
        <Info size={16} />
        <span>
          <strong>Provider integrations</strong>
          <small>
            Groq and Ollama connection status is checked through the FastAPI backend.
            Ollama refreshes every 15 seconds; Groq refreshes every 60 seconds.
          </small>
        </span>
      </Card>
    </div>
  )
}

const comparisonColors = ['#a78bfa', '#60a5fa', '#34d399', '#f59e0b', '#f472b6', '#22d3ee']

export function ComparisonPage({ runs, datasets }: { runs: EvaluationRun[]; datasets: Dataset[] }) {
  const [datasetId, setDatasetId] = useState(datasets[0]?.id ?? '')
  const [searchParams] = useSearchParams()
  const dataset = datasets.find((item) => item.id === datasetId) ?? datasets[0]
  const datasetRuns = runs.filter((run) => isLiveRun(run) && run.dataset === dataset?.name && run.status === 'Completed')
  const latestByModel = new Map<string, EvaluationRun>()
  for (const run of datasetRuns) {
    const key = `${run.provider}:${run.model}`
    if (!latestByModel.has(key)) latestByModel.set(key, run)
  }
  const compared = [...latestByModel.values()].map((run, index) => ({ run, label: `${run.model} · ${run.provider === 'groq' ? 'Groq' : 'Ollama'}`, color: comparisonColors[index % comparisonColors.length]! }))
  const comparedRunIds = (searchParams.get('runs') ?? '').split(',').filter(Boolean)
  const comparedRuns = comparedRunIds.length === 2 ? comparedRunIds.map((id) => runs.find((run) => run.id === id)).filter((run): run is EvaluationRun => run !== undefined) : []
  const mixedModeComparison = comparedRuns.length === 2 && isLiveRun(comparedRuns[0]!) !== isLiveRun(comparedRuns[1]!)
  const comparisonRows: Array<[string, (run: EvaluationRun) => string]> = [
    ['Accuracy', (run) => `${run.accuracy}%`],
    ['Pass rate', (run) => `${run.passRate}%`],
    ['Average latency', (run) => `${run.latency} ms`],
    ['Failed test cases', (run) => `${run.failed} / ${run.total}`],
    ['Token usage', (run) => run.tokenUsage == null ? 'Unavailable' : run.tokenUsage.toLocaleString()],
    ['Estimated cost', (run) => run.estimatedCost == null ? 'Unavailable' : `$${run.estimatedCost}`],
  ]
  const bestAccuracy = compared.length ? Math.max(...compared.map((item) => item.run.accuracy)) : 0
  const chartData = [
    { metric: 'Accuracy', ...Object.fromEntries(compared.map((item) => [item.label, item.run.accuracy])) },
    { metric: 'Pass rate', ...Object.fromEntries(compared.map((item) => [item.label, item.run.passRate])) },
  ]
  const exportComparison = () => {
    const header = ['Model', 'Provider', 'Run', 'Accuracy', 'Pass rate', 'Average latency ms', 'Failed', 'Total', 'Tokens', 'Estimated cost']
    const rows = compared.map(({ run }) => [run.model, run.provider ?? '', run.id, run.accuracy, run.passRate, run.latency, run.failed, run.total, run.tokenUsage ?? '', run.estimatedCost ?? ''])
    const csv = [header, ...rows].map((row) => row.map((value) => `"${String(value).replace(/"/g, '""')}"`).join(',')).join('\r\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'evalforge-model-comparison.csv'
    link.click()
    URL.revokeObjectURL(url)
  }
  return <div className="page"><PageHeader eyebrow="ANALYZE / BENCHMARKS" title="Model comparison" description="Compare the latest completed Live provider run of each model on the same dataset. Demo / Mock runs are excluded." actions={<Button onClick={exportComparison} disabled={compared.length === 0}><Download size={14} /> Export comparison</Button>} />
    {mixedModeComparison && <div className="wizard-error" role="alert">Demo / Mock and Live provider runs cannot be compared together. Select two runs of the same type.</div>}
    {comparedRuns.length === 2 && !mixedModeComparison && <Card className="run-pair-comparison"><div className="card-heading"><div><h2>Selected run comparison</h2><p>{comparedRuns[0].id} vs {comparedRuns[1].id} · {comparedRuns[0].dataset} and {comparedRuns[1].dataset}</p></div><Badge tone={isLiveRun(comparedRuns[0]!) ? 'violet' : 'neutral'}>{runTypeLabel(comparedRuns[0]!)} historical runs</Badge></div><div className="table-wrap"><table className="data-table comparison-table"><thead><tr><th>Metric</th>{comparedRuns.map((run) => <th key={run.id}>{run.model}<small className="table-secondary">{runTypeLabel(run)}</small></th>)}</tr></thead><tbody>{comparisonRows.map(([label, value]) => <tr key={label}><td>{label}</td>{comparedRuns.map((run) => <td key={run.id}>{value(run)}</td>)}</tr>)}</tbody></table></div></Card>}
    <Card className="comparison-config"><div className="compare-config-label"><span className="config-icon"><GitCompareArrows size={16} /></span><span><strong>Dataset</strong><small>Only Live runs on the selected dataset are compared. Start new runs from the Evaluation wizard.</small></span></div><div className="compare-selects"><label className="mini-field"><small>Dataset</small><select value={dataset?.id ?? ''} onChange={(event) => setDatasetId(event.target.value)}>{datasets.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.version}</option>)}</select></label></div></Card>
    {compared.length < 2
      ? <Card><EmptyState title="Not enough Live results to compare" description={compared.length === 1 ? 'Only one model has a completed Live run on this dataset. Run a second model on the same dataset to compare.' : 'No completed Live provider runs exist for this dataset yet. Run an evaluation with Ollama or Groq first.'} /></Card>
      : <>
        <Card className="comparison-chart-card"><div className="card-heading"><div><h2>Live quality metrics</h2><p>Latest completed Live run per model on {dataset?.name}.</p></div><Badge tone="green">{compared.length} models</Badge></div><div className="chart-wrap chart-md"><ResponsiveContainer width="100%" height="100%"><BarChart data={chartData} margin={{ top: 10, right: 12, left: -20, bottom: 0 }}><CartesianGrid stroke="#20232c" vertical={false} /><XAxis dataKey="metric" tickLine={false} axisLine={false} tick={{ fill: '#969baa', fontSize: 11 }} dy={10} /><YAxis domain={[0, 100]} tickLine={false} axisLine={false} tick={{ fill: '#7c8393', fontSize: 10 }} /><Tooltip contentStyle={{ background: '#171a22', border: '1px solid #2a2e39', borderRadius: 8, color: '#e5e7eb', fontSize: 12 }} /><Legend wrapperStyle={{ fontSize: 11, color: '#a2a8b5', paddingTop: 16 }} />{compared.map((item) => <Bar key={item.label} dataKey={item.label} fill={item.color} radius={[3, 3, 0, 0]} barSize={24} />)}</BarChart></ResponsiveContainer></div></Card>
        <Card className="comparison-table-card"><div className="card-heading"><div><h2>Side-by-side Live metrics</h2><p>Values come from persisted Live runs. Best accuracy is highlighted.</p></div><span className="muted-copy">{dataset?.name} · {dataset?.cases ?? 0} test cases</span></div><div className="table-wrap"><table className="data-table comparison-table"><thead><tr><th>Metric</th>{compared.map((item) => <th key={item.run.id}><span className="model-color-swatch" style={{ background: item.color }} />{item.label}<small className="table-secondary">{item.run.id}</small></th>)}</tr></thead><tbody>{comparisonRows.map(([label, value]) => <tr key={label}><td>{label}</td>{compared.map((item) => <td key={item.run.id} className={label === 'Accuracy' && item.run.accuracy === bestAccuracy ? 'best-metric' : ''}>{value(item.run)}</td>)}</tr>)}</tbody></table></div></Card>
      </>}
  </div>
}

export function HistoryPage({ runs, onNavigate }: { runs: EvaluationRun[]; onNavigate: Navigate }) {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('all')
  const [selected, setSelected] = useState<string[]>([])
  const filtered = runs.filter((run) => `${run.id} ${run.dataset} ${run.model}`.toLowerCase().includes(query.toLowerCase()) && (status === 'all' || run.status.toLowerCase() === status))
  const liveRunCount = runs.filter(isLiveRun).length
  const demoRunCount = runs.length - liveRunCount
  const completedRuns = runs.filter((run) => isLiveRun(run) && run.status === 'Completed')
  const averageAccuracy = completedRuns.length ? (completedRuns.reduce((sum, run) => sum + run.accuracy, 0) / completedRuns.length).toFixed(1) : '—'
  const previousAccuracyBySuite = new Map<string, number>()
  let regressionCount = 0
  for (const run of [...completedRuns].reverse()) {
    const suiteKey = `${run.dataset}:${run.model}`
    const previousAccuracy = previousAccuracyBySuite.get(suiteKey)
    if (previousAccuracy !== undefined && run.accuracy < previousAccuracy - 3) regressionCount += 1
    previousAccuracyBySuite.set(suiteKey, run.accuracy)
  }
  return <div className="page"><PageHeader eyebrow="WORKSPACE / RUNS" title="Evaluation runs" description="Review run history, compare results, and catch quality regressions." actions={<Button variant="primary" onClick={() => onNavigate('/evaluations/new')}><Plus size={15} /> New evaluation</Button>} />
    <div className="history-summary"><Card><span className="history-summary-icon violet-icon"><FlaskConical size={16} /></span><span><small>Total runs</small><strong>{runs.length.toLocaleString()}</strong><small>{liveRunCount} Live · {demoRunCount} Demo</small></span></Card><Card><span className="history-summary-icon green-icon"><Target size={16} /></span><span><small>Avg Live accuracy</small><strong>{averageAccuracy}%</strong><small>Live provider runs only</small></span></Card><Card><span className="history-summary-icon amber-icon"><CircleAlert size={16} /></span><span><small>Live regression alerts</small><strong>{regressionCount}</strong></span><span className="summary-alert-label">Live accuracy drops &gt; 3 pts</span></Card></div>
    <div className="dataset-toolbar"><SearchField value={query} onChange={setQuery} placeholder="Search runs, datasets, models..." /><div className="toolbar-right">{selected.length === 2 && <Button size="sm" onClick={() => onNavigate(`/comparisons?runs=${encodeURIComponent(selected.join(','))}`)}><GitCompareArrows size={14} /> Compare 2 runs</Button>}<select className="select-button" value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">All statuses</option><option value="completed">Completed</option><option value="running">Running</option><option value="failed">Failed</option></select><button className="select-button" onClick={() => onNavigate('/reports')}><Filter size={14} /> View report <ChevronDown size={14} /></button></div></div>
    <Card className="history-table-card"><div className="table-wrap"><table className="data-table history-table"><thead><tr><th></th><th>Run ID</th><th>Type</th><th>Dataset / version</th><th>Model</th><th>Results</th><th>Accuracy</th><th>Pass rate</th><th>Latency</th><th>Status</th><th>Executed</th><th /></tr></thead><tbody>{filtered.map((run) => {
      const persistedCount = run.persisted_results_count
      const hasPersistedCount = isLiveRun(run) && Number.isInteger(persistedCount) && (persistedCount ?? -1) >= 0
      const plannedCount = Math.max(0, run.total)
      const isPartialFailure = hasPersistedCount && run.status === 'Failed' && (persistedCount ?? 0) > 0 && (persistedCount ?? 0) < plannedCount
      return <tr key={run.id}>
        <td><input type="checkbox" checked={selected.includes(run.id)} onChange={() => setSelected((current) => current.includes(run.id) ? current.filter((id) => id !== run.id) : [...current, run.id])} aria-label={`Select run ${run.id}`} /></td>
        <td><button className="run-id" onClick={() => onNavigate(`/evaluations/${run.id}`)}>{run.id}</button></td>
        <td><Badge tone={isLiveRun(run) ? 'violet' : 'neutral'}>{runTypeLabel(run)}</Badge></td>
        <td><span className="table-primary">{run.dataset}</span><small className="table-secondary">{run.datasetVersion}</small></td>
        <td>{run.model}</td>
        <td>{!isLiveRun(run) ? <span className="table-secondary">Demo / Mock data</span> : hasPersistedCount ? <span aria-label={`${persistedCount} of ${plannedCount} persisted results`}>{persistedCount} / {plannedCount} results</span> : <span className="table-secondary">Result count unavailable</span>}</td>
        <td><span className="metric-strong">{run.accuracy}%</span></td>
        <td>{run.passRate}%</td>
        <td>{run.latency} ms</td>
        <td><Badge tone={run.status === 'Completed' ? 'green' : run.status === 'Running' ? 'blue' : 'red'}><i className="status-dot" />{run.status}</Badge>{run.status === 'Failed' && hasPersistedCount && <small className="table-secondary">{isPartialFailure ? 'Partial results saved' : (persistedCount ?? 0) === 0 ? 'No results saved' : 'Results saved'}</small>}</td>
        <td className="date-cell">{run.date}</td>
        <td><button className="icon-button" aria-label="View run" onClick={() => onNavigate(`/evaluations/${run.id}`)}><ChevronRight size={16} /></button></td>
      </tr>
    })}</tbody></table>{filtered.length === 0 && <EmptyState title="No runs match your filters" description="Try widening the search or status filter." />}</div><div className="table-pagination"><span>Showing {filtered.length} of {runs.length} runs</span><div><button className="icon-button" aria-label="Previous page"><ChevronLeft size={15} /></button><button className="pagination-active">1</button><button className="pagination-page">2</button><button className="pagination-page">3</button><button className="icon-button" aria-label="Next page"><ChevronRight size={16} /></button></div></div></Card>
    <div className="regression-alert"><span className="regression-alert-icon"><ArrowDownRight size={16} /></span><span><strong>Regression detected in RAG factuality</strong><small>GPT-4o accuracy dropped 3.2% compared to the previous run. 6 test cases newly failing.</small></span><button className="text-button" onClick={() => onNavigate('/reports')}>Review report <ArrowRight size={13} /></button><button className="icon-button" aria-label="Dismiss regression"><X size={15} /></button></div>
  </div>
}

export function FailurePage({ failures, onUpdate, notify }: { failures: Failure[]; onUpdate: (failure: Failure) => Promise<unknown>; notify: Notify }) {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('all')
  const [active, setActive] = useState<Failure | null>(null)
  const [category, setCategory] = useState('all')
  const [failureType, setFailureType] = useState('all')
  const filtered = failures.filter((failure) => `${failure.testCase} ${failure.id} ${failure.model} ${failure.dataset}`.toLowerCase().includes(query.toLowerCase()) && (filter === 'all' || (filter === 'unreviewed' ? !failure.reviewed : failure.reviewed)) && (category === 'all' || failure.category === category) && (failureType === 'all' || failure.failure_type === failureType))
  const topCategory = failures.reduce<string>((top, failure, _, all) => all.filter((item) => item.category === failure.category).length > all.filter((item) => item.category === top).length ? failure.category : top, failures[0]?.category ?? '—')
  const evaluationFailureCount = failures.filter((failure) => failure.failure_type === 'evaluation_failure').length
  const evaluationErrorCount = failures.filter((failure) => failure.failure_type === 'evaluation_error').length
  const exportFailures = () => {
    const header = ['Failure ID', 'Test case', 'Dataset', 'Model', 'Category', 'Score', 'Timestamp', 'Reviewed', 'Reviewer note', 'Input', 'Expected', 'Actual', 'Explanation']
    const rows = filtered.map((failure) => [failure.id, failure.testCase, failure.dataset, failure.model, failure.category, failure.score, failure.timestamp, failure.reviewed, failure.note ?? '', failure.input, failure.expected, failure.actual, failure.explanation])
    const csv = [header, ...rows].map((row) => row.map((value) => `"${String(value).replace(/"/g, '""')}"`).join(',')).join('\r\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'evalforge-failures.csv'
    link.click()
    URL.revokeObjectURL(url)
    notify(`Exported ${filtered.length} failures`)
  }
  const saveReview = async (failure: Failure) => {
    try {
      await onUpdate(failure)
      setActive(failure)
      notify(failure.reviewed ? 'Failure marked as reviewed' : 'Review updated')
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Failure review could not be saved.')
    }
  }
  return <div className="page">
    <PageHeader eyebrow="ANALYZE / QUALITY" title="Failure analysis" description="Investigate model failures, add context, and improve your evaluation coverage." actions={<Button onClick={exportFailures}><Download size={14} /> Export failures</Button>} />
    <p className="failure-scope-note">Includes recorded live-provider evaluation failures and execution errors from parent runs with status Completed or Failed. Failed runs can still contain useful persisted result records.</p>
    <div className="failure-type-summary" aria-label="Failure type counts">
      <Card><small>Evaluation Failures</small><strong>{evaluationFailureCount}</strong><span>Evaluation completed, but the model response did not pass.</span></Card>
      <Card><small>Evaluation Errors</small><strong>{evaluationErrorCount}</strong><span>An error occurred while executing the evaluation.</span></Card>
    </div>
    <div className="failure-stats"><Card><span className="failure-stat-icon red-icon"><CircleAlert size={16} /></span><span><small>Total records</small><strong>{failures.length}</strong></span></Card><Card><span className="failure-stat-icon amber-icon"><Search size={16} /></span><span><small>Need review</small><strong>{failures.filter((failure) => !failure.reviewed).length}</strong></span></Card><Card><span className="failure-stat-icon violet-icon"><Flag size={16} /></span><span><small>Top category</small><strong className="stat-category">{topCategory}</strong></span></Card><Card><span className="failure-stat-icon blue-icon"><CheckCheck size={16} /></span><span><small>Reviewed</small><strong>{failures.filter((failure) => failure.reviewed).length}</strong></span></Card></div>
    <div className="dataset-toolbar"><SearchField value={query} onChange={setQuery} placeholder="Search failures..." /><div className="toolbar-right"><select className="select-button" value={failureType} onChange={(event) => setFailureType(event.target.value)} aria-label="Filter by failure type"><option value="all">All result types</option><option value="evaluation_failure">Evaluation failures</option><option value="evaluation_error">Evaluation errors</option></select><select className="select-button" value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">All failures</option><option value="unreviewed">Needs review</option><option value="reviewed">Reviewed</option></select><select className="select-button" value={category} onChange={(event) => setCategory(event.target.value)}><option value="all">All categories</option>{['Incorrect information', 'Missing information', 'Hallucination', 'Instruction following', 'Formatting error', 'Timeout', 'API error'].map((value) => <option key={value}>{value}</option>)}</select><button className="select-button" onClick={() => notify('Showing failures from the last 30 days')}><Filter size={14} /> Last 30 days</button></div></div>
    <Card className="failure-table-card"><div className="table-wrap"><table className="data-table failure-table"><thead><tr><th>Test case</th><th>Result type</th><th>Failure category</th><th>Model</th><th>Dataset</th><th>Score</th><th>Run time</th><th>Review status</th><th /></tr></thead><tbody>{filtered.map((failure) => <tr key={failure.id} className="clickable-row" onClick={() => setActive(failure)}><td><span className="table-primary">{failure.testCase}</span><small className="table-secondary">{failure.id}</small></td><td><Badge tone={failure.failure_type === 'evaluation_error' ? 'yellow' : 'red'}>{failure.failure_type === 'evaluation_error' ? 'Evaluation error' : 'Evaluation failure'}</Badge></td><td><Badge tone={failure.category === 'Hallucination' ? 'violet' : failure.category === 'Incorrect information' ? 'red' : 'yellow'}>{failure.category}</Badge></td><td>{failure.model}</td><td>{failure.dataset}</td><td><span className="failure-score">{failure.score.toFixed(2)}</span><span className="score-track"><i style={{ width: `${failure.score * 100}%` }} /></span></td><td className="date-cell">{failure.timestamp}</td><td><Badge tone={failure.reviewed ? 'green' : 'yellow'}><i className="status-dot" />{failure.reviewed ? 'Reviewed' : 'Needs review'}</Badge></td><td><ChevronRight size={15} /></td></tr>)}</tbody></table>{filtered.length === 0 && <EmptyState title="No failures found" description="All clear for this filter. Try changing your search." />}</div><div className="table-pagination"><span>Showing {filtered.length} of {failures.length} displayed records</span><div><button className="icon-button"><ChevronLeft size={15} /></button><button className="pagination-active">1</button><button className="pagination-page">2</button><button className="pagination-page">3</button><button className="icon-button"><ChevronRight size={15} /></button></div></div></Card>
    {active && <FailureDetail failure={active} onClose={() => setActive(null)} onSave={saveReview} />}
  </div>
}

function FailureDetail({ failure, onClose, onSave }: { failure: Failure; onClose: () => void; onSave: (failure: Failure) => Promise<void> }) {
  const [note, setNote] = useState(failure.note ?? '')
  const [judgment, setJudgment] = useState<'pass' | 'fail' | null>(
    failure.humanJudgment ?? null
  )
  const isEvaluationError = failure.failure_type === 'evaluation_error'
  return <Modal title={isEvaluationError ? 'Evaluation error inspection' : 'Evaluation failure inspection'} description={`${failure.id} · ${failure.testCase}`} onClose={onClose} wide><div className="failure-detail"><div className="failure-meta"><Badge tone={isEvaluationError ? 'yellow' : 'red'}>{isEvaluationError ? 'Evaluation error' : 'Evaluation failure'}</Badge><Badge tone={failure.run_status === 'Failed' ? 'red' : 'green'}>Run {failure.run_status}</Badge><Badge tone="violet">Provider: {failure.run_provider}</Badge><Badge tone={failure.category === 'Hallucination' ? 'violet' : 'red'}>{failure.category}</Badge><span><span className="model-color-swatch" style={{ background: '#60a5fa' }} />{failure.model}</span><span>{failure.dataset}</span><span><Clock3 size={13} />{failure.timestamp}</span></div><p role="note">{isEvaluationError ? 'An error occurred while executing this evaluation.' : 'Evaluation completed, but the model response did not pass.'}</p><div className="response-block"><div className="response-label"><span className="response-mark input-mark">IN</span><strong>Original input</strong></div><p>{failure.input}</p></div><div className="response-block expected-block"><div className="response-label"><span className="response-mark expected-mark">EX</span><strong>Expected answer</strong></div><p>{failure.expected}</p></div><div className="response-block actual-block"><div className="response-label"><span className="response-mark actual-mark">AI</span><strong>Model response</strong><span className="response-score">Score <b>{failure.score.toFixed(2)} / 1.00</b></span></div><p>{failure.actual}</p></div><div className="explanation-block"><Sparkles size={14} /><span><strong>{isEvaluationError ? 'Execution error' : 'Why this failed'}</strong><p>{failure.explanation}</p></span></div><Field label="Reviewer notes"><textarea rows={3} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Add context for your team..." /></Field>  <div className="human-judgment"><span><strong>Override automated judgment</strong><small>Optional · record a human evaluation</small></span><div><Button size="sm" className={judgment === 'pass' ? 'judgment-selected-pass' : ''} onClick={() => setJudgment('pass')}><CheckCircle2 size={13} /> Pass</Button><Button size="sm" className={judgment === 'fail' ? 'judgment-selected-fail' : ''} onClick={() => setJudgment('fail')}><CircleAlert size={13} /> Fail</Button></div></div><div className="modal-actions"><Button onClick={onClose}>Close</Button><Button variant="primary" onClick={() => void onSave({ ...failure, note, humanJudgment: judgment ?? failure.humanJudgment, reviewed: true })}><CheckCheck size={14} /> Mark reviewed</Button></div></div></Modal>
}

export function ReportsPage({ runs, failures, notify }: { runs: EvaluationRun[]; failures: Failure[]; notify: Notify }) {
  const completed = runs.filter((run) => isLiveRun(run) && run.status === 'Completed')
  const failedLiveRunCount = runs.filter((run) => isLiveRun(run) && run.status === 'Failed').length
  const runningLiveRunCount = runs.filter((run) => isLiveRun(run) && run.status === 'Running').length
  const otherIncompleteLiveRunCount = runs.filter(
    (run) => isLiveRun(run) && run.status !== 'Completed' && run.status !== 'Failed' && run.status !== 'Running',
  ).length
  const demoRunCount = runs.filter((run) => !isLiveRun(run)).length
  const completedByModel = Object.values(
    completed.reduce<
      Record<
        string,
        {
          name: string
          count: number
          accuracy: number
          passRate: number
          latency: number
          estimatedCost: number
          costedRuns: number
        }
      >
    >((groups, run) => {
      const name = run.model || 'Unknown model'
      const group = groups[name] ?? {
        name,
        count: 0,
        accuracy: 0,
        passRate: 0,
        latency: 0,
        estimatedCost: 0,
        costedRuns: 0,
      }

      group.count += 1
      group.accuracy += run.accuracy
      group.passRate += run.passRate
      group.latency += run.latency
      if (run.estimatedCost !== undefined && run.estimatedCost !== null) {
        group.estimatedCost += run.estimatedCost
        group.costedRuns += 1
      }
      groups[name] = group

      return groups
    }, {})
  ).sort((a, b) => a.name.localeCompare(b.name))
  const evaluatedCases = completed.reduce((sum, run) => sum + run.total, 0)
  const failedCases = completed.reduce((sum, run) => sum + run.failed, 0)
  const averageAccuracy = completed.length ? (completed.reduce((sum, run) => sum + run.accuracy, 0) / completed.length).toFixed(1) : '—'
  const averageLatency = completed.length ? Math.round(completed.reduce((sum, run) => sum + run.latency, 0) / completed.length) : null
  const failureRate = evaluatedCases ? `${(failedCases / evaluatedCases * 100).toFixed(1)}%` : '—'
  const failureColors = ['#f87171', '#fb923c', '#fbbf24', '#a78bfa', '#60a5fa', '#34d399', '#2dd4bf']
  const failureCounts = failures.reduce<Map<Failure['category'], number>>((counts, failure) => {
    counts.set(failure.category, (counts.get(failure.category) ?? 0) + 1)
    return counts
  }, new Map())
  const evaluationFailureCount = failures.filter((failure) => failure.failure_type === 'evaluation_failure').length
  const evaluationErrorCount = failures.filter((failure) => failure.failure_type === 'evaluation_error').length
  const reportFailureBreakdown = Array.from(failureCounts, ([name, value], index) => ({
    name,
    value,
    fill: failureColors[index % failureColors.length],
  })).sort((a, b) => a.name.localeCompare(b.name))
  const pdfFailureRecords = failures.filter((failure) =>
    ['ollama', 'groq'].includes(failure.run_provider)
    && (failure.run_status === 'Completed' || failure.run_status === 'Failed')
    && (failure.failure_type === 'evaluation_failure' || failure.failure_type === 'evaluation_error')
  )
  const pdfEvaluationFailureCount = pdfFailureRecords.filter(
    (failure) => failure.failure_type === 'evaluation_failure',
  ).length
  const pdfEvaluationErrorCount = pdfFailureRecords.filter(
    (failure) => failure.failure_type === 'evaluation_error',
  ).length
  const pdfFailureCategoryCounts = pdfFailureRecords.reduce<Map<Failure['category'], number>>((counts, failure) => {
    counts.set(failure.category, (counts.get(failure.category) ?? 0) + 1)
    return counts
  }, new Map())
  const pdfFailureBreakdown = Array.from(pdfFailureCategoryCounts, ([name, value]) => ({
    name,
    value,
  })).sort((a, b) => a.name.localeCompare(b.name))
  const chartData = completed.slice().sort((a, b) => {
    const dateA = Date.parse(a.date.replace(' · ', ' '))
    const dateB = Date.parse(b.date.replace(' · ', ' '))
    return (Number.isNaN(dateA) ? 0 : dateA) - (Number.isNaN(dateB) ? 0 : dateB)
  })
  const exportCsv = () => {
    const columns: Array<{
      header: string
      value: (run: EvaluationRun) => string | number | null | undefined
      optional?: boolean
    }> = [
      { header: 'Run ID', value: (run) => run.id },
      { header: 'Dataset', value: (run) => run.dataset },
      { header: 'Dataset version', value: (run) => run.datasetVersion },
      { header: 'Model', value: (run) => run.model },
      { header: 'Accuracy', value: (run) => run.accuracy },
      { header: 'Pass rate', value: (run) => run.passRate },
      { header: 'Latency ms', value: (run) => run.latency },
      { header: 'Status', value: (run) => run.status },
      { header: 'Date', value: (run) => run.date },
      { header: 'Passed', value: (run) => run.passed },
      { header: 'Failed', value: (run) => run.failed },
      { header: 'Total', value: (run) => run.total },
      { header: 'Provider', value: (run) => run.provider, optional: true },
      { header: 'Mode', value: (run) => run.mode, optional: true },
      { header: 'Evaluation method', value: (run) => run.evaluationMethod, optional: true },
      { header: 'Token usage', value: (run) => run.tokenUsage, optional: true },
      { header: 'Estimated cost', value: (run) => run.estimatedCost, optional: true },
      { header: 'Error type', value: (run) => run.errorType, optional: true },
      { header: 'Error message', value: (run) => run.errorMessage, optional: true },
    ]
    const availableColumns = columns.filter(({ optional, value }) =>
      !optional || completed.some((run) => value(run) !== undefined && value(run) !== null && value(run) !== '')
    )
    const rows = completed.map((run) => availableColumns.map(({ value }) => value(run) ?? ''))
    const csv = [availableColumns.map(({ header }) => header), ...rows]
      .map((row) => row.map((value) => `"${String(value).replace(/"/g, '""')}"`).join(','))
      .join('\r\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'evalforge-evaluation-report.csv'
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 0)
    notify('CSV report downloaded')
  }
  const downloadReport = async () => {
    const { jsPDF } = await import('jspdf')
    const doc = new jsPDF()
    const generatedAt = new Date().toLocaleString()
    let y = 22
    const addPage = () => {
      doc.addPage()
      doc.setFillColor(16, 18, 26)
      doc.rect(0, 0, 210, 297, 'F')
      y = 20
    }
    const addText = (text: string, x: number, fontSize: number, lineHeight: number) => {
      doc.setFontSize(fontSize)
      const lines = doc.splitTextToSize(text, 174)
      const height = lines.length * lineHeight
      if (y + height > 278) addPage()
      doc.text(lines, x, y)
      y += height
    }

    doc.setFillColor(16, 18, 26)
    doc.rect(0, 0, 210, 297, 'F')
    doc.setTextColor(232, 229, 255)
    doc.setFontSize(22)
    doc.text('EvalForge', 18, y)
    y += 9
    doc.setTextColor(178, 169, 220)
    doc.setFontSize(10)
    doc.text('EVALUATION REPORT', 18, y)
    y += 12
    doc.setTextColor(220, 223, 231)
    doc.setFontSize(16)
    doc.text('Evaluation summary', 18, y)
    y += 8
    doc.setTextColor(155, 162, 176)
    addText(`Generated: ${generatedAt}`, 18, 10, 5)
    addText(`Completed evaluations: ${completed.length}`, 18, 10, 5)
    addText(`Evaluation failures: ${pdfEvaluationFailureCount}`, 18, 10, 5)
    addText(`Evaluation errors: ${pdfEvaluationErrorCount}`, 18, 10, 5)
    addText(`Combined failure and error records: ${pdfFailureRecords.length}`, 18, 10, 5)
    addText(`Test executions: ${evaluatedCases.toLocaleString()}`, 18, 10, 5)
    addText(`Average accuracy: ${averageAccuracy === '—' ? '—' : `${averageAccuracy}%`}`, 18, 10, 5)
    addText(`Failure rate: ${failureRate}`, 18, 10, 5)
    addText(`Average latency: ${averageLatency === null ? '—' : `${averageLatency} ms`}`, 18, 10, 5)

    y += 5
    doc.setTextColor(220, 223, 231)
    doc.setFontSize(13)
    doc.text('Completed evaluations', 18, y)
    y += 7
    doc.setTextColor(155, 162, 176)
    for (const run of completed) {
      addText(`${run.id} | ${run.dataset} (${run.datasetVersion})`, 18, 9, 4.5)
      addText(`${run.date} | ${run.model} | ${run.accuracy}% accuracy | ${run.latency} ms`, 22, 9, 4.5)
      y += 2
    }

    y += 4
    if (y > 270) addPage()
    doc.setTextColor(220, 223, 231)
    doc.setFontSize(13)
    doc.text('Failure Breakdown', 18, y)
    y += 7
    doc.setTextColor(155, 162, 176)
    addText('Includes recorded live-provider evaluation failures and execution errors from parent runs with status Completed or Failed.', 18, 9, 4.5)
    addText('A Failed parent run may still contain persisted results useful for diagnosis.', 18, 9, 4.5)
    if (pdfFailureBreakdown.length) {
      addText('Recorded failure and error records by category:', 18, 9, 4.5)
      for (const category of pdfFailureBreakdown) {
        addText(`${category.name}: ${category.value} (${(category.value / pdfFailureRecords.length * 100).toFixed(1)}%)`, 18, 9, 4.5)
      }
    } else {
      addText('No recorded live-provider evaluation failures or execution errors.', 18, 9, 4.5)
    }
    doc.setTextColor(132, 139, 154)
    addText(completed.length || pdfFailureRecords.length
      ? 'This report is based on saved evaluation runs and recorded failure breakdown data.'
      : 'No saved evaluation results are available yet.', 18, 8, 4)
    doc.save('evalforge-evaluation-report.pdf')
    notify('PDF report downloaded')
  }
  const formatChartDate = (date: string) => {
    const parsedDate = new Date(date.replace(' · ', ' '))
    return Number.isNaN(parsedDate.getTime())
      ? date
      : parsedDate.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  }

  return <div className="page"><PageHeader eyebrow="ANALYZE / EXPORTS" title="Reports" description="Share a clear picture of model quality with your team." actions={<><Button onClick={exportCsv}><FileSpreadsheet size={14} /> Export CSV</Button><Button variant="primary" onClick={downloadReport}><FileDown size={14} /> Download report</Button></>} />
    <div className="report-controls"><span className="report-date-icon"><Clock3 size={15} /></span><span><strong>Live provider evaluation summary</strong><small>Performance metrics and exported run records use Completed Live provider runs only. PDF failure details are listed separately.</small></span><button className="select-button" onClick={() => notify('Metrics include Live provider runs only; Demo / Mock runs are excluded.')}>Live runs only <ChevronDown size={14} /></button><button className="select-button" onClick={() => notify('All saved datasets included')}>All datasets <ChevronDown size={14} /></button></div>
    <div className="report-scope-summary report-kpis" aria-label="Report scope summary">
      <Card><small>Included in performance metrics and run exports</small><strong>{completed.length.toLocaleString()}</strong><span>Completed Live provider runs</span></Card>
      <Card><small>Excluded</small><strong>{failedLiveRunCount.toLocaleString()}</strong><span>Failed Live provider runs</span></Card>
      <Card><small>Excluded</small><strong>{runningLiveRunCount.toLocaleString()}</strong><span>Running Live provider runs</span></Card>
      <Card><small>Excluded</small><strong>{otherIncompleteLiveRunCount.toLocaleString()}</strong><span>Other non-completed Live runs</span></Card>
      <Card><small>Excluded</small><strong>{demoRunCount.toLocaleString()}</strong><span>Demo / Mock runs</span></Card>
    </div>
    <div className="report-kpis"><Card><small>Live provider evaluations</small><strong>{completed.length.toLocaleString()}</strong><span>{evaluatedCases.toLocaleString()} live test executions</span></Card><Card><small>Average Live accuracy</small><strong>{averageAccuracy === '—' ? '—' : `${averageAccuracy}%`}</strong><span>Live provider runs only</span></Card><Card><small>Live failure rate</small><strong>{failureRate}</strong><span>{failedCases.toLocaleString()} failed live test cases</span></Card><Card><small>Average Live latency</small><strong>{averageLatency === null ? '—' : <>{averageLatency} <small>ms</small></>}</strong><span>Live provider runs only</span></Card></div>
    <div className="report-grid"><Card className="chart-card report-trend"><div className="card-heading"><div><h2>Live historical performance</h2><p>Accuracy for completed Live provider evaluations only</p></div></div>{completed.length ? <div className="chart-wrap chart-md"><ResponsiveContainer width="100%" height="100%">
      <LineChart
        data={chartData}
        margin={{ top: 10, right: 12, left: -20, bottom: 0 }}
      >
        <CartesianGrid stroke="#20232c" vertical={false} />
        <XAxis
          dataKey="date"
          tickLine={false}
          axisLine={false}
          tick={{ fill: '#7c8393', fontSize: 11 }}
          tickFormatter={formatChartDate}
          dy={10}
        />
        <YAxis
          domain={[0, 100]}
          tickLine={false}
          axisLine={false}
          tick={{ fill: '#7c8393', fontSize: 10 }}
          tickFormatter={(value) => `${value}%`}
        />
        <Tooltip
          labelFormatter={(label) => String(label)}
          formatter={(value, _name, item) => [`${value}% · ${item.payload.model}`, 'Accuracy']}
          contentStyle={{
            background: '#171a22',
            border: '1px solid #2a2e39',
            borderRadius: 8,
            color: '#e5e7eb',
            fontSize: 12,
          }}
        />
        <Line
          type="monotone"
          dataKey="accuracy"
          name="Live provider accuracy"
          stroke="#60a5fa"
          strokeWidth={2}
          dot={{ r: 4 }}
        />
      </LineChart>
    </ResponsiveContainer></div> : <EmptyState title="No completed Live evaluations" description="The accuracy chart will appear after a Live provider evaluation has been completed and saved." />}</Card>
      <Card className="failure-breakdown"><div className="card-heading"><div><h2>Live failure breakdown</h2><p>Live-provider results from Completed and Failed parent runs; failed runs can retain useful diagnostics.</p></div></div><div className="failure-type-summary" aria-label="Failure type counts"><div><small>Evaluation Failures</small><strong>{evaluationFailureCount}</strong><span>Completed evaluations whose model response did not pass.</span></div><div><small>Evaluation Errors</small><strong>{evaluationErrorCount}</strong><span>Errors encountered while executing an evaluation.</span></div></div>{failures.length ? <><div className="donut-wrap"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={reportFailureBreakdown} dataKey="value" nameKey="name" innerRadius={58} outerRadius={78} paddingAngle={3} stroke="none">{reportFailureBreakdown.map((entry) => <Cell key={entry.name} fill={entry.fill} />)}</Pie><Tooltip contentStyle={{ background: '#171a22', border: '1px solid #2a2e39', borderRadius: 8, color: '#e5e7eb', fontSize: 12 }} /></PieChart></ResponsiveContainer><div className="donut-center"><strong>{failures.length}</strong><small>records</small></div></div><div className="failure-legend">{reportFailureBreakdown.map((item) => <div key={item.name}><span><i style={{ background: item.fill }} />{item.name}</span><strong>{(item.value / failures.length * 100).toFixed(1)}%</strong></div>)}</div></> : <EmptyState title="No recorded Live failures or errors" description="Evaluation failures and execution errors will appear here when recorded by live-provider runs." />}</Card></div>
    <Card className="report-models"><div className="card-heading"><div><h2>Live model comparison</h2><p>Average performance across completed Live provider evaluations only</p></div><button className="text-button" onClick={() => notify('Live provider report is ready to share')}>Share report <ArrowRight size={13} /></button></div><div className="table-wrap"><table className="data-table comparison-table"><thead><tr><th>Model</th><th>Runs</th><th>Accuracy</th><th>Pass rate</th><th>Avg latency</th><th>Total est. cost</th><th>Trend</th></tr></thead><tbody>{completedByModel.length ? completedByModel.map((model) => (
      <tr key={model.name}>
        <td>{model.name}</td>
        <td>{model.count}</td>
        <td className="metric-strong">{(model.accuracy / model.count).toFixed(1)}%</td>
        <td>{(model.passRate / model.count).toFixed(1)}%</td>
        <td>{Math.round(model.latency / model.count)} ms</td>
        <td>{model.costedRuns === model.count ? `${model.estimatedCost.toFixed(6)}` : '—'}</td>
        <td>—</td>
      </tr>
    )) : <tr><td colSpan={7}><EmptyState title="No completed Live evaluations" description="Live provider model comparisons will appear here after a real evaluation has been completed and saved." /></td></tr>}</tbody></table></div></Card>
    <div className="report-footnote"><Info size={14} />{completed.length || failures.length ? `This report uses ${completed.length} completed Live provider evaluation${completed.length === 1 ? '' : 's'} and ${failures.length} persisted Live failure${failures.length === 1 ? '' : 's'}. ${demoRunCount} Demo / Mock run${demoRunCount === 1 ? ' is' : 's are'} excluded from all report metrics.` : `No completed Live provider evaluation results are available yet. ${demoRunCount} Demo / Mock run${demoRunCount === 1 ? ' is' : 's are'} excluded from report metrics.`}</div>
  </div>
}

export function RubricsPage({ rubrics, onSave, notify }: { rubrics: Rubric[]; onSave: (rubric: Rubric) => Promise<unknown>; notify: Notify }) {
  const [selectedId, setSelectedId] = useState(rubrics[0]?.id ?? '')
  const [name, setName] = useState(rubrics[0]?.name ?? 'New deterministic rubric')
  const [description, setDescription] = useState(rubrics[0]?.description ?? '')
  const [criteria, setCriteria] = useState<RubricCriterion[]>(rubrics[0]?.criteria ?? [
    { name: 'Accuracy', description: 'Expected terms that represent a correct response.', weight: 100, scale: '0–5', expectedKeywords: [] },
  ])
  const [error, setError] = useState('')
  useEffect(() => {
    if (!selectedId && rubrics[0]) {
      setSelectedId(rubrics[0].id)
      return
    }
    const selected = rubrics.find((rubric) => rubric.id === selectedId)
    if (selected) {
      setName(selected.name)
      setDescription(selected.description)
      setCriteria(selected.criteria)
    }
  }, [rubrics, selectedId])
  const weightTotal = criteria.reduce((sum, criterion) => sum + criterion.weight, 0)
  const addCriterion = () => setCriteria((current) => [
    ...current,
    { name: '', description: '', weight: 0, scale: '0–5', expectedKeywords: [] },
  ])
  const save = async () => {
    if (!name.trim() || criteria.length === 0 || criteria.some((criterion) => !criterion.name.trim() || criterion.weight < 0 || criterion.weight > 100 || criterion.expectedKeywords.length === 0)) {
      setError('Add a name, valid weights, and at least one expected keyword for every criterion.')
      return
    }
    if (weightTotal <= 0) {
      setError('The total rubric weight must be greater than zero.')
      return
    }
    setError('')
    const rubric: Rubric = {
      id: selectedId || `rubric_${crypto.randomUUID()}`,
      name: name.trim(),
      description: description.trim(),
      active: true,
      criteria,
    }
    try {
      await onSave(rubric)
      setSelectedId(rubric.id)
      notify('Deterministic rubric saved')
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Rubric could not be saved.')
    }
  }
  return <div className="page"><PageHeader eyebrow="CONFIGURE / SCORING" title="Evaluation rubrics" description="Configure transparent, deterministic weighted keyword criteria for local scoring." actions={<Button variant="primary" onClick={addCriterion}><Plus size={15} /> Add criterion</Button>} />
    <div className="rubric-layout"><div><Card className="rubric-main"><div className="rubric-form-footer"><Field label="Rubric name"><input value={name} onChange={(event) => setName(event.target.value)} /></Field><Field label="Description"><input value={description} onChange={(event) => setDescription(event.target.value)} /></Field></div>{rubrics.length > 0 && <Field label="Saved rubric"><select value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>{rubrics.map((rubric) => <option value={rubric.id} key={rubric.id}>{rubric.name}</option>)}</select></Field>}<div className="rubric-criterion-editor">{criteria.map((criterion, index) => <div className="rubric-criterion-edit" key={`${criterion.id ?? criterion.name}-${index}`}><span className="criterion-index">{String(index + 1).padStart(2, '0')}</span><div className="form-two-col"><Field label="Criterion"><input value={criterion.name} onChange={(event) => setCriteria((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, name: event.target.value } : item))} /></Field><Field label="Weight"><input type="number" min="0" max="100" value={criterion.weight} onChange={(event) => setCriteria((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, weight: Number(event.target.value) } : item))} /></Field><Field label="Expected keywords (comma-separated)"><input value={criterion.expectedKeywords.join(', ')} onChange={(event) => setCriteria((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, expectedKeywords: event.target.value.split(',').map((keyword) => keyword.trim()).filter(Boolean) } : item))} /></Field><Field label="Scale"><input value={criterion.scale} onChange={(event) => setCriteria((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, scale: event.target.value } : item))} /></Field></div><button className="icon-button" aria-label={`Remove criterion ${index + 1}`} onClick={() => setCriteria((current) => current.filter((_, itemIndex) => itemIndex !== index))}><X size={14} /></button></div>)}</div><div className={`rubric-total ${weightTotal > 0 ? '' : 'rubric-warning'}`}><span>Total weight</span><strong>{weightTotal}%</strong>{weightTotal > 0 ? <span className="weight-ok"><CheckCircle2 size={14} /> Weights are normalized</span> : <span className="weight-invalid"><CircleAlert size={14} /> Weight must be positive</span>}</div>{error && <span className="form-error">{error}</span>}<div className="rubric-form-footer"><Button variant="primary" onClick={() => void save()}>Save rubric</Button></div></Card></div><div className="rubric-aside"><Card><div className="rubric-aside-icon"><Sparkles size={16} /></div><h3>How deterministic scoring works</h3><p>Each criterion matches its configured keywords case-insensitively as whole words or phrases. Its score is the matched keyword fraction multiplied by the scale maximum.</p><div className="score-formula"><span>Final score =</span><strong>Σ (criterion score × normalized weight)</strong></div><div className="example-total"><span>Pass threshold</span><strong>60% <small>of maximum score</small></strong></div></Card><Card className="rubric-note"><Info size={15} /><span><strong>No LLM judge is used</strong><small>Rubric Evaluation is deterministic keyword scoring. The configured model only generates the response being evaluated.</small></span></Card></div></div>
  </div>
}

export function SettingsPage({ user }: { user: { email: string } | null }) {
  const providers = [
    { id: 'ollama' as const, name: 'Ollama', note: 'Self-hosted. Configure OLLAMA_BASE_URL and OLLAMA_MODEL on the backend. A local Ollama process is not reachable from a hosted deployment.' },
    { id: 'groq' as const, name: 'Groq', note: 'Hosted API. Configure GROQ_API_KEY and GROQ_MODEL on the backend; the key is never sent to the browser.' },
  ]
  const [status, setStatus] = useState<Record<string, { tone: 'green' | 'red' | 'neutral'; text: string }>>({})
  const [checking, setChecking] = useState<string | null>(null)
  const check = async (provider: 'ollama' | 'groq') => {
    setChecking(provider)
    try {
      const result = await api.checkProvider(provider)
      setStatus((current) => ({ ...current, [provider]: result.available ? { tone: 'green', text: `Connected${result.model ? ` · ${result.model}` : ''}` } : { tone: 'red', text: result.error?.message ?? 'Unavailable' } }))
    } catch (error) {
      setStatus((current) => ({ ...current, [provider]: { tone: 'red', text: error instanceof Error ? error.message : 'Provider check failed' } }))
    } finally {
      setChecking(null)
    }
  }
  return <div className="page"><PageHeader eyebrow="CONFIGURE / WORKSPACE" title="Settings" description="Account details and live provider connectivity. Provider credentials are configured on the backend, not in the browser." />
    <div className="settings-content">
      <Card className="settings-section"><div className="settings-section-heading"><h2>Account</h2><p>{user ? 'The authenticated account that owns your datasets, rubrics and runs.' : 'You are in local demo mode; data stays in this browser only.'}</p></div><div className="settings-fields"><Field label="Email"><input value={user?.email ?? 'Local demo (not signed in)'} readOnly /></Field></div></Card>
      <Card className="settings-section"><div className="settings-section-heading"><h2>Live providers</h2><p>Providers supported by the backend. Check whether each one is reachable and configured.</p></div>
        {providers.map((item) => <div className="integration-row" key={item.id}><span className="provider-logo">{item.name.slice(0, 1)}</span><span><strong>{item.name}</strong><small>{item.note}</small></span><Badge tone={status[item.id]?.tone ?? 'neutral'}>{status[item.id]?.text ?? 'Not checked'}</Badge><Button size="sm" disabled={checking === item.id} onClick={() => void check(item.id)}>{checking === item.id ? 'Checking…' : 'Check connection'}</Button></div>)}
        <div className="provider-security-note"><ShieldCheck size={14} />Only Ollama and Groq are integrated. Demo / Mock runs never call a model and are labelled as such everywhere.</div>
      </Card>
    </div>
  </div>
}

const availableModels = [
  { name: 'Demo Model 1', provider: 'Demo', color: '#a78bfa', context: 'Placeholder label · sample data only' },
  { name: 'Demo Model 2', provider: 'Demo', color: '#60a5fa', context: 'Placeholder label · sample data only' },
  { name: 'Demo Model 3', provider: 'Demo', color: '#34d399', context: 'Placeholder label · sample data only' },
]

export function EvaluationWizard({ datasets, cases, rubrics, onStart, onNavigate, demoOnly = false, liveOnly = false }: { datasets: Dataset[]; cases: TestCase[]; rubrics: Rubric[]; onStart: (runs: EvaluationRun[], mode: EvaluationMode) => Promise<void>; onNavigate: Navigate; demoOnly?: boolean; liveOnly?: boolean }) {
  const [step, setStep] = useState(1)
  const [datasetId, setDatasetId] = useState(datasets[0]?.id ?? '')
  const [mode, setMode] = useState<EvaluationMode>(demoOnly ? 'mock' : liveOnly ? 'ollama' : 'mock')
  const [models, setModels] = useState(['Demo Model 1', 'Demo Model 2'])
  const [ollamaModel, setOllamaModel] = useState('')
  const [provider, setProvider] = useState<'ollama' | 'groq'>('ollama')
  const [metrics, setMetrics] = useState(['Accuracy', 'Relevance', 'Instruction following'])
  const [rubric, setRubric] = useState(rubrics[0]?.id ?? '')
  const [evaluationMethod, setEvaluationMethod] = useState<EvaluationMethod>('exact_match')
  const [concurrency, setConcurrency] = useState(5)
  const [temperature, setTemperature] = useState(0)
  const [progress, setProgress] = useState(0)
  const [execution, setExecution] = useState<MockExecutionProgress>({ progress: 0, pending: 0, running: 0, passed: 0, failed: 0, errors: 0 })
  const [completed, setCompleted] = useState(false)
  const [failed, setFailed] = useState(false)
  const [realResult, setRealResult] = useState<EvaluationExecution | null>(null)
  const [providerStatus, setProviderStatus] = useState('')
  const [checkingProvider, setCheckingProvider] = useState(false)
  const [error, setError] = useState('')
  const displayedDatasets = mode === 'mock' && datasets.length === 0 ? initialDatasets : datasets
  const displayedCases = mode === 'mock' && cases.length === 0 ? initialTestCases : cases
  const dataset = displayedDatasets.find((item) => item.id === datasetId)
  const datasetCases = displayedCases.filter((testCase) => testCase.datasetId === datasetId)
  const caseCount = datasetCases.length || dataset?.cases || 0

  useEffect(() => {
    if (!displayedDatasets.some((item) => item.id === datasetId)) setDatasetId(displayedDatasets[0]?.id ?? '')
  }, [displayedDatasets, datasetId])

  useEffect(() => {
    if (!rubrics.some((item) => item.id === rubric)) setRubric(rubrics[0]?.id ?? '')
  }, [rubrics, rubric])

  const toggle = (list: string[], setList: (value: string[]) => void, value: string) => setList(list.includes(value) ? list.filter((item) => item !== value) : [...list, value])
  const nextStep = () => {
    if (step === 1 && (!datasetId || caseCount === 0)) { setError('Select a dataset with at least one test case.'); return }
    if (step === 2 && mode === 'mock' && models.length === 0) { setError('Select at least one model to evaluate.'); return }
    if (step === 3 && mode === 'mock' && metrics.length === 0) { setError('Select at least one evaluation metric.'); return }
    if (step === 3 && mode === 'ollama' && evaluationMethod === 'keyword_match' && datasetCases.some((testCase) => !testCase.expectedKeywords?.length)) { setError('Add expected keywords to every test case in this dataset before using Keyword Match.'); return }
    if (step === 3 && mode === 'ollama' && evaluationMethod === 'rubric' && !rubrics.some((item) => item.id === rubric)) { setError('Create and save a rubric with expected keywords for every criterion first.'); return }
    setError('')
    setStep((current) => Math.min(4, current + 1))
  }
  const start = async () => {
    if (!dataset || (mode === 'mock' && models.length === 0) || (mode === 'ollama' && datasetCases.length === 0)) {
      setError('Choose a dataset with test cases and at least one model before starting.')
      return
    }
    setError('')
    setCompleted(false)
    setFailed(false)
    setRealResult(null)
    setStep(5)
    setProgress(0)
    setExecution({ progress: 0, pending: mode === 'mock' ? caseCount * models.length : datasetCases.length, running: mode === 'ollama' ? 1 : 0, passed: 0, failed: 0, errors: 0 })
    try {
      if (mode === 'mock') {
        const newRuns = await api.simulateEvaluation(
          { datasetId, models, metrics, rubric, concurrency, temperature, evaluationMethod },
          dataset,
          caseCount,
          (nextProgress) => {
            setExecution(nextProgress)
            setProgress(nextProgress.progress)
          },
        )
        await onStart(newRuns, 'mock')
        setCompleted(true)
        window.setTimeout(() => onNavigate('/evaluations'), 1600)
      } else {
        const result = await api.runEvaluation({
          datasetId,
          model: ollamaModel.trim(),
          provider,
          evaluationMethod,
          rubric,
          temperature,
        })
        setRealResult(result)
        setExecution({
          progress: 100,
          pending: 0,
          running: 0,
          passed: result.run.passed,
          failed: result.run.failed,
          errors: result.errors,
        })
        setProgress(100)
        setCompleted(result.run.status === 'Completed')
        setFailed(result.run.status === 'Failed')
        await onStart([result.run], 'ollama')
      }
    } catch (startError) {
      setFailed(true)
      setExecution((current) => ({ ...current, pending: 0, running: 0 }))
      setError(startError instanceof Error ? startError.message : 'Evaluation failed.')
      if (mode === 'ollama') await onStart([], 'ollama')
    }
  }
  const checkProvider = async () => {
    setCheckingProvider(true)
    setProviderStatus('')
    try {
      const status = await api.checkProvider(provider, ollamaModel.trim())
      setProviderStatus(status.available
        ? `Connected · ${status.model}${provider === 'ollama' ? ' is installed' : ''}`
        : status.error?.message ?? 'Provider is unavailable.')
    } catch (checkError) {
      setProviderStatus(checkError instanceof Error ? checkError.message : 'Could not check provider.')
    } finally {
      setCheckingProvider(false)
    }
  }
  const steps = ['Dataset', 'Models', 'Metrics', 'Review']
  return <div className="page wizard-page"><PageHeader eyebrow="EVALUATIONS / NEW RUN" title="New evaluation" description="Configure a repeatable benchmark across your selected models." actions={<Button onClick={() => onNavigate('/evaluations')}>Cancel</Button>} />
    <div className="wizard-progress">{steps.map((label, index) => <div className={`wizard-step ${step > index + 1 || completed ? 'step-done' : step === index + 1 ? 'step-current' : ''}`} key={label}><span>{step > index + 1 || completed ? <Check size={13} /> : index + 1}</span><strong>{label}</strong>{index < steps.length - 1 && <i />}</div>)}</div>
    <div className="wizard-content">
      {step === 1 && <Card className="wizard-card">
        <div className="wizard-card-heading"><span className="wizard-number">01</span><div><h2>Choose a dataset</h2><p>Select the test cases you want to run against your model.</p></div></div>
        {(demoOnly || liveOnly)
          ? <div className={`wizard-demo-warning ${demoOnly ? '' : 'live-mode-note'}`}><Sparkles size={15} /><span><strong>{demoOnly ? 'Local Demo workspace' : 'Authenticated Live workspace'}</strong><small>{demoOnly ? 'Only local sample execution is available here.' : 'Live evaluations use only your authenticated backend data.'}</small></span></div>
          : <Field label="Evaluation mode"><select value={mode} onChange={(event) => { setMode(event.target.value as EvaluationMode); setError('') }}><option value="mock">Demo / Mock — sample results, no model call</option><option value="ollama">Live provider — call and persist real model responses</option></select></Field>}
        <div className="wizard-dataset-grid">{displayedDatasets.map((item) => <button key={item.id} className={`wizard-dataset-option ${datasetId === item.id ? 'selected-option' : ''}`} onClick={() => { setDatasetId(item.id); setError('') }}><span className={`dataset-icon ${item.color}`}><Database size={17} /></span><span className="wizard-dataset-copy"><strong>{item.name}</strong><small>{item.description}</small><span className="wizard-dataset-meta"><Layers3 size={12} />{displayedCases.filter((entry) => entry.datasetId === item.id).length || item.cases} test cases <span>·</span>{item.version}</span></span><span className="radio-indicator">{datasetId === item.id && <i />}</span></button>)}</div>
        <div className="wizard-info"><Info size={14} />Dataset and expected-answer snapshots are saved with each real run.</div>
      </Card>}
      {step === 2 && <Card className="wizard-card">
        <div className="wizard-card-heading"><span className="wizard-number">02</span><div><h2>{mode === 'mock' ? 'Select demo models' : 'Configure live provider'}</h2><p>{mode === 'mock' ? 'Demo model labels do not call provider APIs.' : 'Choose a hosted Groq model or a locally running Ollama model.'}</p></div></div>
        {mode === 'mock'
          ? <><div className="wizard-model-list">{availableModels.map((model) => <button className={`wizard-model-option ${models.includes(model.name) ? 'selected-option' : ''}`} key={model.name} onClick={() => toggle(models, setModels, model.name)}><span className="model-color-swatch" style={{ background: model.color }} /><span className="wizard-model-copy"><strong>{model.name}</strong><small>Demo data · no model API call</small></span><span className="checkbox-visual">{models.includes(model.name) && <Check size={12} />}</span></button>)}</div><div className="provider-security-note"><Info size={14} />Demo model names and outcomes are sample data only.</div></>
           : <><Field label="Model provider"><select value={provider} onChange={(event) => { setProvider(event.target.value as 'ollama' | 'groq'); setProviderStatus('') }}><option value="ollama">Ollama · local server</option><option value="groq">Groq · hosted API</option></select></Field><Field label="Model name"><input value={ollamaModel} onChange={(event) => setOllamaModel(event.target.value)} placeholder={provider === 'groq' ? 'Leave blank to use GROQ_MODEL' : 'Leave blank to use OLLAMA_MODEL'} /></Field><div className="wizard-form-grid"><Button onClick={() => void checkProvider()} disabled={checkingProvider}>{checkingProvider ? 'Checking provider…' : 'Check provider connection'}</Button>{providerStatus && <span role="status">{providerStatus}</span>}</div><div className="provider-security-note"><Info size={14} />The browser sends requests only to the EvalForge backend. Provider credentials and configuration stay on the backend. Groq requires GROQ_API_KEY in the backend environment.</div></>}
      </Card>}
      {step === 3 && <Card className="wizard-card">
        <div className="wizard-card-heading"><span className="wizard-number">03</span><div><h2>Configure evaluation</h2><p>Choose a deterministic method and its persisted scoring criteria.</p></div></div>
        {mode === 'mock'
          ? <><h3 className="wizard-section-label">Demo metrics</h3><div className="metrics-check-grid">{['Accuracy', 'Relevance', 'Completeness', 'Instruction following', 'Safety', 'Response latency'].map((metric) => <button key={metric} className={`metric-check ${metrics.includes(metric) ? 'metric-check-selected' : ''}`} onClick={() => toggle(metrics, setMetrics, metric)}><span className="checkbox-visual">{metrics.includes(metric) && <Check size={12} />}</span><span><strong>{metric}</strong><small>Sample demonstration metric</small></span></button>)}</div></>
          : <div className="wizard-form-grid"><Field label="Evaluation method"><select value={evaluationMethod} onChange={(event) => setEvaluationMethod(event.target.value as EvaluationMethod)}><option value="exact_match">Exact Match</option><option value="keyword_match">Keyword Match</option><option value="rubric">Deterministic Rubric</option></select></Field>{evaluationMethod === 'rubric' && <Field label="Saved rubric"><select value={rubric} onChange={(event) => setRubric(event.target.value)}><option value="">Select a saved rubric</option>{rubrics.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></Field>}</div>}
        <div className="wizard-form-grid"><Field label={`Temperature · ${temperature.toFixed(1)}`}><input type="range" min="0" max="2" step="0.1" value={temperature} onChange={(event) => setTemperature(Number(event.target.value))} /></Field>{mode === 'mock' && <Field label={`Demo concurrency · ${concurrency}`}><input type="range" min="1" max="20" value={concurrency} onChange={(event) => setConcurrency(Number(event.target.value))} /></Field>}</div>
        {mode === 'ollama' && evaluationMethod === 'keyword_match' && <div className="wizard-info">Keyword Match requires expected keywords on every test case in this dataset.</div>}
        {mode === 'ollama' && evaluationMethod === 'rubric' && <div className="wizard-info">Each rubric criterion must include expected keywords and a valid positive total weight. This does not call an LLM judge.</div>}
      </Card>}
      {step === 4 && <Card className="wizard-card">
        <div className="wizard-card-heading"><span className="wizard-number">04</span><div><h2>Review configuration</h2><p>Confirm the selected mode before starting.</p></div></div>
        <div className="review-summary"><div><span>Dataset</span><strong>{dataset?.name ?? '—'} <Badge tone="violet">{dataset?.version ?? 'v1.0'}</Badge></strong><small>{datasetCases.length} saved test cases</small></div><div><span>Mode / model</span><strong>{mode === 'mock' ? 'Demo / Mock' : provider === 'groq' ? 'Groq' : 'Ollama'}</strong><small>{mode === 'mock' ? models.join(' · ') : ollamaModel.trim() || 'Backend default model'}</small></div><div><span>Scoring</span><strong>{mode === 'mock' ? 'Sample metrics' : evaluationMethod.replace('_', ' ')}</strong><small>{evaluationMethod === 'rubric' ? rubrics.find((item) => item.id === rubric)?.name ?? 'Select a saved rubric' : evaluationMethod === 'keyword_match' ? 'All configured keywords must match' : 'Case-folded, whitespace-normalized exact match'}</small></div><div><span>Execution</span><strong>{mode === 'mock' ? `${concurrency} simulated workers` : `Actual ${provider === 'groq' ? 'Groq' : 'Ollama'} responses`}</strong><small>Temperature {temperature.toFixed(1)}</small></div></div>
        <div className="wizard-demo-warning"><Sparkles size={15} /><span><strong>{mode === 'mock' ? 'Demo execution only' : 'Live provider evaluation'}</strong><small>{mode === 'mock' ? 'Results use existing sample data and never claim a model was called.' : 'This request requires the selected provider and model to be configured. Provider errors are shown; no mock fallback is used.'}</small></span></div>
      </Card>}
      {step === 5 && <Card className="execution-card">
        <div className="execution-top"><span className={`execution-icon ${completed ? 'execution-complete' : ''}`}>{completed ? <CheckCircle2 size={21} /> : failed ? <CircleAlert size={21} /> : <LoaderCircle className="spin" size={21} />}</span><span><h2>{completed ? 'Evaluation complete' : failed ? 'Evaluation failed' : 'Evaluation in progress'}</h2><p>{mode === 'mock' ? 'Demo / Mock mode · no AI model was called.' : 'Live provider mode · waiting for the real model evaluation response.'}</p></span><Badge tone={completed ? 'green' : failed ? 'red' : 'blue'}>{completed ? 'Completed' : failed ? 'Failed' : 'Running'}</Badge></div>
        {mode === 'mock' || completed || failed ? <><div className="execution-progress-header"><span>{mode === 'mock' ? 'Demo progress' : 'Evaluation status'}</span><strong>{progress}%</strong></div><div className="execution-progress"><i style={{ width: `${progress}%` }} /></div></> : <div className="execution-log"><strong><span className="log-dot" />Live provider request running</strong><small>Progress is reported when the backend finishes; no simulated progress is shown.</small></div>}
        <div className="execution-stats"><div><span className="execution-stat-dot blue-dot-bg" /><small>Pending</small><strong>{execution.pending}</strong></div><div><span className="execution-stat-dot violet-dot-bg" /><small>Running</small><strong>{execution.running}</strong></div><div><span className="execution-stat-dot green-dot-bg" /><small>Passed</small><strong>{execution.passed}</strong></div><div><span className="execution-stat-dot red-dot-bg" /><small>Failed</small><strong>{execution.failed}</strong></div><div><span className="execution-stat-dot amber-dot-bg" /><small>Errors</small><strong>{execution.errors}</strong></div></div>
        {realResult && <div className="run-case-results"><h3>Actual model responses</h3>{realResult.results.map((result) => <div className="response-block actual-block" key={result.id}><div className="response-label"><strong>{result.testCaseTitle}</strong><Badge tone={result.status === 'Error' ? 'yellow' : result.passed ? 'green' : 'red'}>{result.status === 'Error' ? 'Evaluation error' : result.passed ? 'Pass' : 'Fail'}</Badge><span className="result-time">{result.latencyMs} ms</span></div><p><strong>Expected:</strong> {result.expected}</p><p><strong>Model response:</strong> {result.actual}</p>{result.errorMessage && <p role="alert">{result.errorMessage}</p>}</div>)}</div>}
        {mode === 'mock' && <div className="execution-log"><strong><span className={completed ? 'log-dot-complete' : 'log-dot'} />{completed ? 'Demo finished' : 'Demo simulation running'}</strong><small>Sample metrics only. No provider request was made.</small></div>}
      </Card>}
      {error && <div className="wizard-error"><CircleAlert size={14} />{error}</div>}
      {step < 5 && <div className="wizard-footer"><button className="text-button" onClick={() => { if (step > 1) setStep(step - 1); else onNavigate('/evaluations') }}>{step === 1 ? 'Cancel' : <><ChevronLeft size={14} /> Back</>}</button><span>Step {step} of 4</span>{step < 4 ? <Button variant="primary" onClick={nextStep}>Continue <ArrowRight size={14} /></Button> : <Button variant="primary" onClick={start}><FlaskConical size={14} /> Start evaluation</Button>}</div>}
    </div>
  </div>
}

export function RunDetailPage({ runs, onNavigate }: { runs: EvaluationRun[]; onNavigate: Navigate }) {
  const { runId } = useParams()
  const run = runs.find((entry) => entry.id === runId)
  const details = useQuery({
    queryKey: ['runDetails', runId],
    queryFn: () => api.getRunDetails(runId ?? ''),
    enabled: Boolean(runId && ['ollama', 'groq'].includes(run?.provider ?? '')),
    retry: false,
  })
  if (!run) return <div className="page"><EmptyState title="Run not found" description="This evaluation run may have been removed." action={<Button onClick={() => onNavigate('/evaluations')}>Back to runs</Button>} /></div>
  const isReal = isLiveRun(run)
  const detailsLoaded = Boolean(details.data) && !details.isError
  const results = detailsLoaded ? details.data?.results ?? [] : []
  const plannedCount = Math.max(0, run.total)
  const completedResults = results.filter((result) => result.status === 'Completed')
  const completedPassed = completedResults.filter((result) => result.passed).length
  const completedFailed = completedResults.filter((result) => !result.passed).length
  const resultErrors = results.filter((result) => result.status === 'Error').length
  const isTerminal = run.status === 'Completed' || run.status === 'Failed'
  const unprocessed = Math.max(0, plannedCount - results.length)
  const data = isReal
    ? [
      { name: 'Passed', value: completedPassed, fill: '#34d399' },
      { name: 'Failed', value: completedFailed, fill: '#f87171' },
      { name: 'Result Errors', value: resultErrors, fill: '#fbbf24' },
      ...(isTerminal ? [{ name: 'Unprocessed', value: unprocessed, fill: '#687386' }] : []),
    ]
    : [
      { name: 'Passed', value: run.passed, fill: '#34d399' },
      { name: 'Failed', value: run.failed, fill: '#f87171' },
    ]
  const metricValue = (value: string | number) => detailsLoaded ? value : '—'
  return <div className="page"><PageHeader eyebrow={`EVALUATIONS / ${run.id}`} title="Evaluation run" description={`${run.dataset} ${run.datasetVersion} · ${run.model}`} actions={<Button onClick={() => onNavigate('/evaluations')}><ChevronLeft size={14} /> All runs</Button>} />
    <div className="run-detail-meta"><Badge tone={run.status === 'Completed' ? 'green' : run.status === 'Running' ? 'blue' : 'red'}><i className="status-dot" />{run.status}</Badge><Badge tone={isReal ? 'violet' : 'neutral'}>{isReal ? `${run.provider === 'groq' ? 'Groq' : 'Ollama'} · Real evaluation` : 'Demo / Mock'}</Badge><span><Clock3 size={13} />{run.date}</span><span><Layers3 size={13} />{run.total} test cases</span><span className="run-id">{run.id}</span></div>
    {isReal && <div className="run-detail-kpis" aria-label="Run case counts">
      <Card><small>Planned</small><strong>{plannedCount}</strong><span>Cases selected for this run</span></Card>
      <Card><small>Persisted</small><strong>{metricValue(results.length)}</strong><span>Saved result records</span></Card>
      <Card><small>Completed</small><strong>{metricValue(completedResults.length)}</strong><span>Results included in pass metrics</span></Card>
      <Card><small>Result Errors</small><strong>{metricValue(resultErrors)}</strong><span>Persisted evaluation errors</span></Card>
      {isTerminal && <Card><small>Unprocessed</small><strong>{metricValue(unprocessed)}</strong><span>Planned cases without a saved result</span></Card>}
    </div>}
    <div className="run-detail-kpis"><Card><small>Accuracy</small><strong>{isReal ? completedResults.length && detailsLoaded ? `${run.accuracy}%` : '—' : `${run.accuracy}%`}</strong><span><Target size={13} />{isReal && detailsLoaded ? `Based on ${completedResults.length} Completed results` : 'Passed generated responses'}</span></Card><Card><small>Pass rate</small><strong>{isReal ? completedResults.length && detailsLoaded ? `${run.passRate}%` : '—' : `${run.passRate}%`}</strong><span><CheckCircle2 size={13} />{isReal ? detailsLoaded && completedResults.length ? `${completedPassed} of ${completedResults.length} Completed results passed` : 'No Completed results to calculate pass rate' : `${run.passed} of ${run.total} passed`}</span></Card><Card><small>Average latency</small><strong>{run.latency} <small>ms</small></strong><span><Timer size={13} />Measured model response latency</span></Card><Card><small>{isReal ? 'Failed results' : 'Failures'}</small><strong className="failure-kpi">{isReal ? metricValue(completedFailed) : run.failed}</strong><span><CircleAlert size={13} />Incorrect model answers</span></Card></div>
    <div className="run-detail-grid"><Card><div className="card-heading"><div><h2>Run outcome</h2><p>{isReal ? 'Persisted result statuses; unprocessed cases are shown separately when the run ends.' : 'Pass and fail distribution across test cases'}</p></div></div><div className="run-outcome-content"><div className="run-donut"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={data} dataKey="value" innerRadius={56} outerRadius={78} stroke="none" startAngle={90} endAngle={-270}>{data.map((item) => <Cell key={item.name} fill={item.fill} />)}</Pie></PieChart></ResponsiveContainer><span><strong>{isReal ? metricValue(results.length) : run.total}</strong><small>{isReal ? 'persisted' : 'cases'}</small></span></div><div className="run-outcome-legend">{isReal ? detailsLoaded ? data.map((item) => <div key={item.name}><span><i className="legend-dot" style={{ backgroundColor: item.fill }} />{item.name}</span><strong>{item.value}</strong></div>) : <p>{details.isError ? 'Result counts unavailable.' : 'Loading persisted result counts…'}</p> : <><div><span><i className="legend-dot green-dot" />Passed</span><strong>{run.passed} <small>{run.total ? `${((run.passed / run.total) * 100).toFixed(1)}%` : '0%'}</small></strong></div><div><span><i className="legend-dot red-dot" />Failed</span><strong>{run.failed} <small>{run.total ? `${((run.failed / run.total) * 100).toFixed(1)}%` : '0%'}</small></strong></div></>}</div></div>{isReal && detailsLoaded && completedResults.length === 0 && <p role="status">No Completed results; pass rate is not defined.</p>}</Card><Card><div className="card-heading"><div><h2>Execution details</h2><p>Configuration used for this run</p></div><Badge tone={isReal ? 'violet' : 'neutral'}>{isReal ? (run.provider === 'groq' ? 'Groq' : 'Ollama') : 'Demo / Mock'}</Badge></div><div className="execution-detail-list"><div><span>Model provider</span><strong>{run.provider ?? 'mock'}</strong></div><div><span>Model</span><strong>{run.model}</strong></div><div><span>Dataset version</span><strong>{run.datasetVersion}</strong></div><div><span>Evaluation method</span><strong>{run.evaluationMethod ?? 'Sample results'}</strong></div><div><span>Token usage</span><strong>{run.tokenUsage ?? 'Unavailable'}</strong></div><div><span>Estimated cost</span><strong>{run.estimatedCost == null ? 'Unavailable' : `$${run.estimatedCost}`}</strong></div></div>{run.errorMessage && <div className="wizard-error" role="alert">{run.errorType}: {run.errorMessage}</div>}</Card></div>
    <Card className="run-case-results"><div className="card-heading"><div><h2>{isReal ? 'Persisted model responses' : 'Demo results'}</h2><p>{isReal ? 'Actual responses, expected answers, and deterministic evaluation outcomes.' : 'This run contains demonstration metrics only; no model response was generated.'}</p></div>{isReal && <button className="text-button" onClick={() => onNavigate('/failures')}>Review failures <ArrowRight size={13} /></button>}</div>
      {isReal && details.isLoading && <div role="status">Loading persisted evaluation results…</div>}
      {isReal && details.isError && <div className="wizard-error" role="alert">Could not load persisted run results. {details.error instanceof Error ? details.error.message : ''}</div>}
      {isReal && !details.isLoading && results.length === 0 && !details.isError && <EmptyState title="No test results were generated" description="The run failed before a model response was available. Review its provider error above." />}
      {results.map((result) => <div className="response-block actual-block" key={result.id}><div className="response-label"><strong>{result.testCaseTitle}</strong><Badge tone={result.status === 'Error' ? 'yellow' : result.passed ? 'green' : 'red'}>{result.status === 'Error' ? 'Evaluation error' : result.passed ? 'Pass' : 'Fail'}</Badge><span className="response-score">{result.score.toFixed(2)}</span><span className="result-time">{result.latencyMs} ms</span></div><p><strong>Input:</strong> {result.input}</p><p><strong>Expected:</strong> {result.expected}</p><p><strong>Actual response:</strong> {result.actual}</p>{result.errorMessage && <p role="alert">{result.errorType}: {result.errorMessage}</p>}{result.criteriaBreakdown.length > 0 && <details><summary>Scoring breakdown</summary><pre>{JSON.stringify(result.criteriaBreakdown, null, 2)}</pre></details>}</div>)}
    </Card>
  </div>
}
