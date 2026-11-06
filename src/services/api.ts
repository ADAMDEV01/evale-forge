import { initialDatasets, initialTestCases, modelMetrics } from '../data/mockData'
import type { Dataset, EvaluationConfig, EvaluationExecution, EvaluationMethod, EvaluationRun, Failure, MockExecutionProgress, Rubric, TestCase } from '../types'

const importMetaWithEnv = import.meta as ImportMeta & {
  env?: {
    VITE_API_URL?: string
    DEV?: boolean
  }
}

// In production, use Vercel's same-origin /api rewrite by default.
// Keep localhost only for local Vite development when no API URL is configured.
const API_BASE = importMetaWithEnv.env?.VITE_API_URL
  || (importMetaWithEnv.env?.DEV ? 'http://localhost:8000/api' : '/api')

const pause = (ms = 180) => new Promise((resolve) => window.setTimeout(resolve, ms))

type RunPersistenceRequest = Omit<EvaluationRun, 'dataset'> & { dataset_id: string }

export interface AuthUser {
  id: string
  email: string
  is_active: boolean
  created_at: string
}

interface AuthResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  user: AuthUser
}

function validateAuthResponse(payload: unknown): AuthResponse {
  if (!payload || typeof payload !== 'object') {
    throw new Error('The authentication service returned an invalid response.')
  }
  const candidate = payload as Partial<AuthResponse>
  if (
    typeof candidate.access_token !== 'string'
    || candidate.token_type !== 'bearer'
    || typeof candidate.expires_in !== 'number'
    || !candidate.user
    || typeof candidate.user.id !== 'string'
    || typeof candidate.user.email !== 'string'
    || typeof candidate.user.is_active !== 'boolean'
    || typeof candidate.user.created_at !== 'string'
  ) {
    throw new Error('The authentication service returned an invalid response.')
  }
  return candidate as AuthResponse
}

async function parseAuthResponse(response: Response): Promise<AuthResponse> {
  return validateAuthResponse(await response.json())
}

let accessToken: string | null = null
let refreshRequest: Promise<AuthResponse | null> | null = null

function setAccessToken(token: string | null) {
  accessToken = token
}

function notifySessionExpired() {
  setAccessToken(null)
  window.dispatchEvent(new Event('evalforge:session-expired'))
}

function readStored<T>(key: string, fallback: T): T {
  const value = localStorage.getItem(`evalforge:${key}`)
  if (!value) {
    localStorage.setItem(`evalforge:${key}`, JSON.stringify(fallback))
    return fallback
  }
  try {
    return JSON.parse(value) as T
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error)
    throw new Error(`Stored ${key} data is invalid JSON: ${detail}`)
  }
}

function writeStored<T>(key: string, value: T): T {
  localStorage.setItem(`evalforge:${key}`, JSON.stringify(value))
  return value
}

function errorFromResponse(response: Response, body: string): Error {
  let detail = body || `Request failed with status ${response.status}`
  try {
    const parsed = JSON.parse(body) as { detail?: string | { message?: string } }
    if (typeof parsed.detail === 'string') detail = parsed.detail
    else if (parsed.detail?.message) detail = parsed.detail.message
  } catch {
    // Keep the response body for non-JSON API errors.
  }
  return new Error(detail)
}

async function fetchRaw(path: string, init: RequestInit = {}): Promise<Response> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch {
    throw new Error('Could not reach the EvalForge backend. Check the API URL and backend availability, then try again.')
  }
  return response
}

function refreshSession(): Promise<AuthResponse | null> {
  if (refreshRequest) return refreshRequest
  const pendingRequest = (async () => {
    const response = await fetchRaw('/auth/refresh', {
      method: 'POST',
      credentials: 'include',
    })
    if (response.status === 401) {
      setAccessToken(null)
      return null
    }
    if (!response.ok) throw errorFromResponse(response, await response.text())
    const payload = await parseAuthResponse(response)
    setAccessToken(payload.access_token)
    return payload
  })()
  refreshRequest = pendingRequest
  void pendingRequest.then(
    () => { if (refreshRequest === pendingRequest) refreshRequest = null },
    () => { if (refreshRequest === pendingRequest) refreshRequest = null },
  )
  return pendingRequest
}

async function fetchJson<T>(
  path: string,
  init: RequestInit = {},
  options: { authenticated?: boolean; credentials?: RequestCredentials; retryAuthentication?: boolean } = {},
): Promise<T> {
  const authenticated = options.authenticated ?? true
  const retryAuthentication = options.retryAuthentication ?? true
  const request = async (token: string | null) => fetchRaw(path, {
    ...init,
    credentials: options.credentials ?? 'omit',
    headers: {
      'Content-Type': 'application/json',
      ...(authenticated && token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  })

  const usedToken = authenticated ? accessToken : null
  let response = await request(usedToken)
  if (authenticated && response.status === 401 && retryAuthentication) {
    if (accessToken && accessToken !== usedToken) {
      response = await request(accessToken)
    } else {
      const renewedToken = (await refreshSession())?.access_token ?? null
      if (renewedToken) {
        response = await request(renewedToken)
      } else {
        notifySessionExpired()
      }
    }
  }

  if (!response.ok) {
    const body = await response.text()
    throw errorFromResponse(response, body)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

async function unauthenticatedAuthRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  return fetchJson<T>(path, init, {
    authenticated: false,
    credentials: 'include',
    retryAuthentication: false,
  })
}

function saveLocal<T extends { id: string }>(key: string, items: T[], id: string, item: T): T[] {
  const updated = [item, ...items.filter((current) => current.id !== id)]
  return writeStored(key, updated)
}

export const api = {
  async register(email: string, password: string): Promise<AuthUser> {
    const response = validateAuthResponse(await unauthenticatedAuthRequest<unknown>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }))
    setAccessToken(response.access_token)
    return response.user
  },
  async login(email: string, password: string): Promise<AuthUser> {
    const response = validateAuthResponse(await unauthenticatedAuthRequest<unknown>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }))
    setAccessToken(response.access_token)
    return response.user
  },
  async restoreSession(): Promise<AuthUser | null> {
    return (await refreshSession())?.user ?? null
  },
  async logout(): Promise<void> {
    try {
      await unauthenticatedAuthRequest<void>('/auth/logout', { method: 'POST' })
    } finally {
      setAccessToken(null)
    }
  },
  async logoutAll(): Promise<void> {
    try {
      await fetchJson<void>('/auth/logout-all', { method: 'POST' })
    } finally {
      setAccessToken(null)
    }
  },
  clearAccessToken() {
    setAccessToken(null)
  },
  async getDatasets(): Promise<Dataset[]> {
    return fetchJson<Dataset[]>('/datasets')
  },
  async getDemoDatasets(): Promise<Dataset[]> {
    return readStored('demo:datasets', initialDatasets)
  },
  async saveDataset(dataset: Dataset): Promise<Dataset[]> {
    return fetchJson<Dataset[]>('/datasets', {
      method: 'POST',
      body: JSON.stringify({
        ...dataset,
        createdAt: dataset.createdAt || new Date().toISOString().slice(0, 10),
        modifiedAt: new Date().toISOString().slice(0, 10),
      }),
    })
  },
  async deleteDataset(id: string): Promise<void> {
    await fetchJson<{ deleted: string }>(`/datasets/${encodeURIComponent(id)}`, { method: 'DELETE' })
  },
  async saveDemoDataset(dataset: Dataset): Promise<Dataset[]> {
    const datasets = readStored('demo:datasets', initialDatasets)
    return saveLocal('demo:datasets', datasets, dataset.id, dataset)
  },
  async deleteDemoDataset(id: string): Promise<void> {
    const datasets = readStored('demo:datasets', initialDatasets)
    const testCases = readStored('demo:testCases', initialTestCases)
    writeStored('demo:testCases', testCases.filter((testCase) => testCase.datasetId !== id))
    writeStored('demo:datasets', datasets.filter((dataset) => dataset.id !== id))
  },
  async getTestCases(): Promise<TestCase[]> {
    return fetchJson<TestCase[]>('/test-cases')
  },
  async getDemoTestCases(): Promise<TestCase[]> {
    return readStored('demo:testCases', initialTestCases)
  },
  async getRubrics(): Promise<Rubric[]> {
    return fetchJson<Rubric[]>('/rubrics')
  },
  async getDemoRubrics(): Promise<Rubric[]> {
    return readStored('demo:rubrics', [])
  },
  async saveRubric(rubric: Rubric): Promise<Rubric[]> {
    return fetchJson<Rubric[]>('/rubrics', {
      method: 'POST',
      body: JSON.stringify(rubric),
    })
  },
  async saveTestCase(testCase: TestCase): Promise<TestCase[]> {
    return fetchJson<TestCase[]>('/test-cases', {
      method: 'POST',
      body: JSON.stringify(testCase),
    })
  },
  async saveDemoTestCase(testCase: TestCase): Promise<TestCase[]> {
    const cases = readStored('demo:testCases', initialTestCases)
    return saveLocal('demo:testCases', cases, testCase.id, testCase)
  },
  async deleteTestCase(id: string): Promise<void> {
    await fetchJson<{ deleted: string }>(`/test-cases/${encodeURIComponent(id)}`, { method: 'DELETE' })
  },
  async deleteDemoTestCase(id: string): Promise<void> {
    const testCases = readStored('demo:testCases', initialTestCases)
    writeStored('demo:testCases', testCases.filter((testCase) => testCase.id !== id))
  },
  async getRuns(): Promise<EvaluationRun[]> {
    return fetchJson<EvaluationRun[]>('/runs')
  },
  async addRun(run: RunPersistenceRequest): Promise<EvaluationRun[]> {
    return fetchJson<EvaluationRun[]>('/runs', {
      method: 'POST',
      body: JSON.stringify({ ...run, passRate: run.passRate ?? 0, config: { model: run.model } }),
    })
  },
  async saveMockRun(run: EvaluationRun): Promise<EvaluationRun[]> {
    const demoRuns = readStored<EvaluationRun[]>('demoRuns', [])
    return saveLocal('demoRuns', demoRuns, run.id, run)
  },
  async getDemoRuns(): Promise<EvaluationRun[]> {
    return readStored('demoRuns', [])
  },
  async getDemoFailures(): Promise<Failure[]> {
    return []
  },
  async saveDemoRubric(rubric: Rubric): Promise<Rubric[]> {
    const rubrics = readStored<Rubric[]>('demo:rubrics', [])
    return saveLocal('demo:rubrics', rubrics, rubric.id, rubric)
  },
  async runEvaluation(config: {
    datasetId: string
    model: string
    provider?: 'ollama' | 'groq'
    evaluationMethod: EvaluationMethod
    rubric: string
    temperature: number
  }): Promise<EvaluationExecution> {
    return fetchJson<EvaluationExecution>('/evaluate', {
      method: 'POST',
      body: JSON.stringify({ provider: config.provider ?? 'ollama', ...config }),
    })
  },
  async getRunDetails(runId: string): Promise<EvaluationExecution> {
    return fetchJson<EvaluationExecution>(`/runs/${encodeURIComponent(runId)}`)
  },
  async checkProvider(provider: 'ollama' | 'groq', model?: string): Promise<{
    provider: 'ollama' | 'groq'
    available: boolean
    model: string | null
    modelInstalled: boolean | null
    error: { code: string; message: string } | null
  }> {
    return fetchJson(`/providers/${provider}/health${model ? `?model=${encodeURIComponent(model)}` : ''}`, {}, { authenticated: false })
  },
  async simulateEvaluation(
    config: EvaluationConfig,
    dataset: Dataset,
    testCount: number,
    onProgress: (progress: MockExecutionProgress) => void,
  ): Promise<EvaluationRun[]> {
    const total = testCount * config.models.length
    const outcomes: MockExecutionProgress = { progress: 0, pending: total, running: 0, passed: 0, failed: 0, errors: 0 }
    const batches = 14
    const batchSize = Math.max(1, Math.ceil(total / batches))
    for (let completed = 0; completed < total; completed += batchSize) {
      await pause(350)
      const finished = Math.min(total, completed + batchSize)
      const remaining = total - finished
      outcomes.progress = Math.round((finished / total) * 100)
      outcomes.running = Math.min(config.concurrency, remaining)
      outcomes.pending = remaining - outcomes.running
      outcomes.passed = Math.round(finished * 0.91)
      outcomes.failed = finished - outcomes.passed
      onProgress({ ...outcomes })
    }

    const date = `${new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })} · ${new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}`
    return config.models.map((model) => {
      const baseline = modelMetrics.find((item) => item.name === model)
      const accuracy = baseline?.accuracy ?? 90
      const passRate = baseline?.passRate ?? accuracy
      const failed = Math.round(testCount * (1 - passRate / 100))
      return {
        id: `run_demo_${Date.now().toString(36)}_${model.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`,
        dataset: dataset.name,
        datasetVersion: dataset.version,
        model,
        provider: 'mock',
        mode: 'mock',
        evaluationMethod: config.evaluationMethod ?? 'exact_match',
        accuracy: Number(accuracy.toFixed(1)),
        passRate,
        latency: baseline?.latency ?? 980,
        status: 'Completed' as const,
        date,
        passed: testCount - failed,
        failed,
        total: testCount,
      }
    })
  },
  async getFailures(): Promise<Failure[]> {
    return fetchJson<Failure[]>('/failures')
  },
  async updateFailure(failure: Failure): Promise<Failure[]> {
    return fetchJson<Failure[]>(
      `/failures/${encodeURIComponent(failure.id)}`,
      {
        method: 'PUT',
        body: JSON.stringify(failure),
      }
    )
  },
}
