import { useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity, AlertTriangle, BookOpenCheck, Boxes, ChartNoAxesCombined,
  Database, Gauge, GitCompareArrows, Layers3, Menu, Plus, Search, Settings2, Sparkles, X,
} from 'lucide-react'
import { api } from './services/api'
import type { AuthUser } from './services/api'
import { Button, ErrorState, LoadingState } from './components/ui'
import { AuthPage } from './components/AuthPage'
import type { Dataset, EvaluationMode, EvaluationRun, Failure, Rubric, TestCase } from './types'
import {
  ComparisonPage, DashboardPage, DatasetDetailsPage, DatasetPage, FailurePage, HistoryPage, ModelsPage,
  ReportsPage, RubricsPage, SettingsPage, TestCasePage, EvaluationWizard, RunDetailPage,
} from './pages'

const navigation = [
  { label: 'Workspace', items: [
    { label: 'Overview', path: '/', icon: Gauge },
    { label: 'Evaluations', path: '/evaluations', icon: Activity },
    { label: 'Datasets', path: '/datasets', icon: Database },
    { label: 'Test cases', path: '/test-cases', icon: BookOpenCheck },
  ] },
  { label: 'Analyze', items: [
    { label: 'Models', path: '/models', icon: Boxes },
    { label: 'Comparisons', path: '/comparisons', icon: GitCompareArrows },
    { label: 'Failures', path: '/failures', icon: AlertTriangle },
    { label: 'Reports', path: '/reports', icon: ChartNoAxesCombined },
  ] },
]

const titles: Record<string, string> = {
  '/': 'Overview', '/evaluations': 'Evaluations', '/evaluations/new': 'New evaluation', '/datasets': 'Datasets', '/test-cases': 'Test cases',
  '/models': 'Models', '/comparisons': 'Comparisons', '/failures': 'Failure analysis',
  '/reports': 'Reports', '/rubrics': 'Rubrics', '/settings': 'Settings',
}

type SessionState =
  | { status: 'loading' }
  | { status: 'anonymous'; error?: string }
  | { status: 'restore-error'; error: string }
  | { status: 'authenticated'; user: AuthUser }
  | { status: 'demo' }

export default function App() {
  const [session, setSession] = useState<SessionState>({ status: 'loading' })
  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  useEffect(() => {
    let active = true
    void api.restoreSession().then((user) => {
      if (!active) return
      queryClient.clear()
      setSession(user ? { status: 'authenticated', user } : { status: 'anonymous' })
    }).catch((error: unknown) => {
      if (!active) return
      setSession({ status: 'restore-error', error: error instanceof Error ? error.message : 'Could not restore your session.' })
    })
    return () => { active = false }
  }, [queryClient])

  useEffect(() => {
    const expireSession = () => {
      queryClient.clear()
      setSession({ status: 'anonymous' })
      navigate('/login', { replace: true })
    }
    window.addEventListener('evalforge:session-expired', expireSession)
    return () => window.removeEventListener('evalforge:session-expired', expireSession)
  }, [navigate, queryClient])

  if (session.status === 'loading') return <LoadingState />
  if (session.status === 'anonymous' || session.status === 'restore-error') {
    return <AuthPage
      onRetrySession={session.status === 'restore-error' ? async () => {
        setSession({ status: 'loading' })
        try {
          const user = await api.restoreSession()
          queryClient.clear()
          setSession(user ? { status: 'authenticated', user } : { status: 'anonymous' })
        } catch (error) {
          setSession({
            status: 'restore-error',
            error: error instanceof Error ? error.message : 'Could not restore your session.',
          })
        }
      } : undefined}
      onAuthenticated={(user) => {
        queryClient.clear()
        setSession({ status: 'authenticated', user })
        navigate('/', { replace: true })
      }}
      onDemo={() => {
        queryClient.clear()
        setSession({ status: 'demo' })
        navigate('/', { replace: true })
      }}
      initialError={session.error}
    />
  }

  if (session.status === 'authenticated' && ['/login', '/register'].includes(location.pathname)) {
    return <Navigate to="/" replace />
  }

  return <Workspace
    user={session.status === 'authenticated' ? session.user : null}
    isDemo={session.status === 'demo'}
    onLogout={async (allSessions) => {
      try {
        if (allSessions) await api.logoutAll()
        else await api.logout()
      } finally {
        api.clearAccessToken()
        queryClient.clear()
        setSession({ status: 'anonymous' })
        navigate('/login', { replace: true })
      }
    }}
    onExitDemo={() => {
      queryClient.clear()
      setSession({ status: 'anonymous' })
      navigate('/login', { replace: true })
    }}
  />
}

function Workspace({
  user,
  isDemo,
  onLogout,
  onExitDemo,
}: {
  user: AuthUser | null
  isDemo: boolean
  onLogout: (allSessions: boolean) => Promise<void>
  onExitDemo: () => void
}) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [mobileSearchOpen, setMobileSearchOpen] = useState(false)
  const [globalSearch, setGlobalSearch] = useState('')
  const [toast, setToast] = useState('')
  const notify = (message: string) => {
    setToast(message)
    window.setTimeout(() => setToast(''), 2800)
  }
  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const datasets = useQuery({ queryKey: ['datasets'], queryFn: isDemo ? api.getDemoDatasets : api.getDatasets })
  const testCases = useQuery({ queryKey: ['testCases'], queryFn: isDemo ? api.getDemoTestCases : api.getTestCases })
  const runs = useQuery({ queryKey: ['runs'], queryFn: isDemo ? api.getDemoRuns : api.getRuns })
  const failures = useQuery({ queryKey: ['failures'], queryFn: isDemo ? api.getDemoFailures : api.getFailures })
  const rubrics = useQuery({ queryKey: ['rubrics'], queryFn: isDemo ? api.getDemoRubrics : api.getRubrics })
  const loaded = [datasets, testCases, runs, failures, rubrics].every((query) => query.isSuccess)
  const failed = [datasets, testCases, runs, failures, rubrics].some((query) => query.isError)

  const saveDataset = useMutation({ mutationFn: (dataset: Dataset) => isDemo ? api.saveDemoDataset(dataset) : api.saveDataset(dataset), onSuccess: (data) => queryClient.setQueryData(['datasets'], data) })
  const removeDataset = useMutation({
    mutationFn: (id: string) => isDemo ? api.deleteDemoDataset(id) : api.deleteDataset(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['datasets'] })
      await queryClient.invalidateQueries({ queryKey: ['testCases'] })
    },
  })
  const saveCase = useMutation({ mutationFn: (testCase: TestCase) => isDemo ? api.saveDemoTestCase(testCase) : api.saveTestCase(testCase), onSuccess: (data) => queryClient.setQueryData(['testCases'], data) })
  const removeCase = useMutation({
    mutationFn: (id: string) => isDemo ? api.deleteDemoTestCase(id) : api.deleteTestCase(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['testCases'] }),
  })
  const saveMockRun = useMutation({
    mutationFn: api.saveMockRun,
    onSuccess: (demoRuns) => queryClient.setQueryData(['runs'], demoRuns),
  })
  const saveRubric = useMutation({
    mutationFn: (rubric: Rubric) => isDemo ? api.saveDemoRubric(rubric) : api.saveRubric(rubric),
    onSuccess: (data) => queryClient.setQueryData(['rubrics'], data),
  })
  const updateFailure = useMutation({ mutationFn: api.updateFailure, onSuccess: (data) => queryClient.setQueryData(['failures'], data) })
  const title = location.pathname.startsWith('/evaluations/') && location.pathname !== '/evaluations/new'
    ? 'Run details'
    : location.pathname.startsWith('/datasets/')
      ? 'Dataset details'
      : titles[location.pathname] ?? 'Overview'

  const handleSearch = (value: string) => {
    setGlobalSearch(value)
    if (value && location.pathname !== '/datasets' && location.pathname !== '/test-cases') navigate('/datasets')
  }

  if (failures.isError) {
    return <ErrorState
      title="Failure data unavailable"
      description="Could not load persisted live-provider failures and errors. No sample data is being shown."
      onRetry={() => void failures.refetch()}
    />
  }
  if (failed) return <ErrorState onRetry={() => [datasets, testCases, runs, failures, rubrics].forEach((query) => void query.refetch())} />
  if (!loaded) return <LoadingState />

  const handleEvaluationStart = async (newRuns: EvaluationRun[], mode: EvaluationMode) => {
    if (mode === 'mock') {
      await Promise.all(newRuns.map((run) => saveMockRun.mutateAsync(run)))
    } else {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['runs'] }),
        queryClient.invalidateQueries({ queryKey: ['failures'] }),
      ])
    }
    if (newRuns.length > 0) notify(mode === 'mock' ? 'Demo evaluation run created' : 'Live-provider evaluation results saved')
  }

  return (
    <div className="app-shell">
      {sidebarOpen && <button className="mobile-backdrop" aria-label="Close navigation" onClick={() => setSidebarOpen(false)} />}
      <aside className={`sidebar ${sidebarOpen ? 'sidebar-open' : ''}`}>
        <div className="brand-row"><div className="brand-mark"><span /></div><span className="brand-name">eval<span>forge</span></span><button className="mobile-close icon-button" aria-label="Close menu" onClick={() => setSidebarOpen(false)}><X size={17} /></button></div>
        <div className="workspace-switch"><span className="workspace-avatar">E</span><span className="workspace-copy"><strong>EvalForge</strong><small>{isDemo ? 'Local demo workspace' : 'Private workspace'}</small></span></div>
        <div className="side-nav">
          {navigation.map((group) => <div className="nav-group" key={group.label}><div className="nav-heading">{group.label}</div>{group.items.map(({ label, path, icon: Icon }) => <NavLink key={path} to={path} end={path === '/'} className={({ isActive }) => `nav-link ${isActive ? 'nav-active' : ''}`} onClick={() => setSidebarOpen(false)}><Icon size={16} strokeWidth={1.8} /><span>{label}</span></NavLink>)}</div>)}
          <div className="nav-group"><div className="nav-heading">Configure</div><NavLink to="/rubrics" className={({ isActive }) => `nav-link ${isActive ? 'nav-active' : ''}`}><Layers3 size={16} strokeWidth={1.8} /><span>Rubrics</span></NavLink><NavLink to="/settings" className={({ isActive }) => `nav-link ${isActive ? 'nav-active' : ''}`}><Settings2 size={16} strokeWidth={1.8} /><span>Settings</span></NavLink></div>
        </div>
        <div className="sidebar-bottom">
          <div className="profile-row"><span className="profile-avatar">{isDemo ? 'D' : user?.email.slice(0, 1).toUpperCase()}</span><span className="profile-copy"><strong>{isDemo ? 'Local Demo' : user?.email}</strong><small>{isDemo ? 'This browser only' : 'Authenticated account'}</small></span>{isDemo
            ? <button className="text-button" onClick={onExitDemo}>Exit</button>
            : <button className="text-button" onClick={() => void onLogout(false).catch((error: unknown) => notify(error instanceof Error ? error.message : 'Sign out failed.'))}>Sign out</button>}</div>
        </div>
      </aside>
      <main className="main-shell">
        <header className="topbar"><div className="topbar-left"><button className="menu-toggle icon-button" aria-label="Open navigation" onClick={() => setSidebarOpen(true)}><Menu size={18} /></button><div className="breadcrumb"><span>{isDemo ? 'Local Demo' : user?.email}</span><span className="crumb-slash">/</span><strong>{title}</strong></div><span className={`session-mode ${isDemo ? 'session-demo' : ''}`}>{isDemo ? 'DEMO · LOCAL ONLY' : 'LIVE · PRIVATE'}</span></div><div className="topbar-actions"><label className={`global-search ${mobileSearchOpen ? 'global-search-open' : ''}`} onKeyDown={(event) => { if (event.key === 'Escape') setMobileSearchOpen(false) }}><Search size={15} /><input value={globalSearch} onChange={(event) => handleSearch(event.target.value)} placeholder="Search anything..." /><kbd>⌘ K</kbd></label><button className="mobile-search-toggle icon-button" aria-label={mobileSearchOpen ? 'Close search' : 'Open search'} onClick={() => setMobileSearchOpen((open) => !open)}><Search size={17} /></button><Button variant="primary" size="sm" onClick={() => navigate('/evaluations/new')}><Plus size={15} /> New evaluation</Button>{!isDemo && <Button size="sm" onClick={() => void onLogout(true).catch((error: unknown) => notify(error instanceof Error ? error.message : 'Sign out failed.'))}>Sign out all</Button>}</div></header>
        <div className="content-area">
          <Routes>
            <Route path="/" element={<DashboardPage datasets={datasets.data as Dataset[]} cases={testCases.data as TestCase[]} runs={runs.data as EvaluationRun[]} failures={failures.data as Failure[]} onNavigate={navigate} />} />
            <Route path="/evaluations" element={<HistoryPage runs={runs.data as EvaluationRun[]} onNavigate={navigate} />} />
            <Route path="/evaluations/new" element={<EvaluationWizard datasets={datasets.data as Dataset[]} cases={testCases.data as TestCase[]} rubrics={rubrics.data as Rubric[]} onStart={handleEvaluationStart} onNavigate={navigate} demoOnly={isDemo} liveOnly={!isDemo} />} />
            <Route path="/evaluations/:runId" element={<RunDetailPage runs={runs.data as EvaluationRun[]} onNavigate={navigate} />} />
            <Route path="/datasets/:datasetId" element={<DatasetDetailsPage datasets={datasets.data as Dataset[]} cases={testCases.data as TestCase[]} onNavigate={navigate} />} />
            <Route path="/datasets" element={<DatasetPage datasets={datasets.data as Dataset[]} cases={testCases.data as TestCase[]} onSave={(dataset) => saveDataset.mutateAsync(dataset)} onSaveCase={(testCase) => saveCase.mutateAsync(testCase)} onDelete={(id) => removeDataset.mutateAsync(id)} onNavigate={navigate} search={globalSearch} notify={notify} />} />
            <Route path="/test-cases" element={<TestCasePage cases={testCases.data as TestCase[]} datasets={datasets.data as Dataset[]} onSave={(testCase) => saveCase.mutateAsync(testCase)} onDelete={(id) => removeCase.mutateAsync(id)} search={globalSearch} notify={notify} />} />
            <Route path="/models" element={<ModelsPage />} />
            <Route path="/comparisons" element={<ComparisonPage runs={runs.data as EvaluationRun[]} datasets={datasets.data as Dataset[]} />} />
            <Route path="/failures" element={<FailurePage failures={failures.data as Failure[]} onUpdate={(failure) => updateFailure.mutateAsync(failure)} notify={notify} />} />
            <Route path="/reports" element={<ReportsPage runs={runs.data as EvaluationRun[]} failures={failures.data as Failure[]} notify={notify} />} />
            <Route path="/rubrics" element={<RubricsPage rubrics={rubrics.data as Rubric[]} onSave={(rubric) => saveRubric.mutateAsync(rubric)} notify={notify} />} />
            <Route path="/settings" element={<SettingsPage user={user} />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </main>
      {toast && <div className="toast"><Sparkles size={15} />{toast}</div>}
    </div>
  )
}
