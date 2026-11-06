import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../App'
import { api, type AuthUser } from '../services/api'

const userA: AuthUser = {
  id: 'user-a',
  email: 'a@example.test',
  is_active: true,
  created_at: '2026-01-01T00:00:00',
}
const userB: AuthUser = { ...userA, id: 'user-b', email: 'b@example.test' }

function authPayload(user: AuthUser, token = `access-${user.id}`) {
  return { access_token: token, token_type: 'bearer', expires_in: 900, user }
}

function response(status: number, body?: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => body === undefined ? '' : JSON.stringify(body),
  } as Response
}

function renderApp(initialPath = '/') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[initialPath]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  }
}

beforeEach(() => {
  localStorage.clear()
  api.clearAccessToken()
  class ResizeObserverMock {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  vi.stubGlobal('ResizeObserver', ResizeObserverMock)
})

afterEach(() => {
  api.clearAccessToken()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('Authentication API client', () => {
  it('uses the backend registration and login contracts without persisting credentials', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toMatch(/\/api\/auth\/(register|login)$/)
      expect(init?.credentials).toBe('include')
      expect(new Headers(init?.headers).has('Authorization')).toBe(false)
      return response(200, authPayload(userA))
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.register(userA.email, 'a long test password')).resolves.toEqual(userA)
    const registerBody = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))
    expect(registerBody).toEqual({ email: userA.email, password: 'a long test password' })
    await expect(api.login(userA.email, 'a long test password')).resolves.toEqual(userA)
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })

  it('returns backend validation and invalid-credential errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      response(401, { detail: 'Invalid email or password' }),
    ))

    await expect(api.login(userA.email, 'wrong password')).rejects.toThrow('Invalid email or password')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      response(422, { detail: 'Password must be at least 12 characters' }),
    ))
    await expect(api.register(userA.email, 'short')).rejects.toThrow('Password must be at least 12 characters')
  })

  it('restores a session through the HttpOnly refresh cookie and shares startup refreshes', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.method).toBe('POST')
      expect(init?.credentials).toBe('include')
      expect(new Headers(init?.headers).has('Authorization')).toBe(false)
      await new Promise((resolve) => window.setTimeout(resolve, 5))
      return response(200, authPayload(userA))
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(Promise.all([api.restoreSession(), api.restoreSession()])).resolves.toEqual([userA, userA])
    expect(fetchMock).toHaveBeenCalledOnce()
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })

  it('refreshes after 401 and retries once using the rotated access token', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/auth/login')) return response(200, authPayload(userA, 'old-token'))
      if (url.endsWith('/auth/refresh')) {
        expect(init?.credentials).toBe('include')
        expect(new Headers(init?.headers).has('Authorization')).toBe(false)
        return response(200, authPayload(userA, 'rotated-token'))
      }
      if (url.endsWith('/datasets')) {
        if (new Headers(init?.headers).get('Authorization') === 'Bearer old-token') {
          return response(401, { detail: 'Invalid or missing authentication credentials' })
        }
        return response(200, [])
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    await api.login(userA.email, 'password')

    await expect(api.getDatasets()).resolves.toEqual([])
    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith('/auth/refresh'))).toHaveLength(1)
    const datasetRequests = fetchMock.mock.calls.filter(([input]) => String(input).endsWith('/datasets'))
    const retried = datasetRequests[datasetRequests.length - 1]
    expect(new Headers(retried?.[1]?.headers).get('Authorization')).toBe('Bearer rotated-token')
  })

  it('coalesces concurrent 401 responses into one refresh request', async () => {
    let refreshCount = 0
    const firstRequestByPath = new Set<string>()
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/auth/login')) return response(200, authPayload(userA, 'old-token'))
      if (url.endsWith('/auth/refresh')) {
        refreshCount += 1
        await new Promise((resolve) => window.setTimeout(resolve, 10))
        return response(200, authPayload(userA, 'new-token'))
      }
      if (url.endsWith('/datasets') || url.endsWith('/test-cases')) {
        if (!firstRequestByPath.has(url)) {
          firstRequestByPath.add(url)
          return response(401, { detail: 'Expired' })
        }
        expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer new-token')
        return response(200, [])
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    await api.login(userA.email, 'password')

    await expect(Promise.all([api.getDatasets(), api.getTestCases()])).resolves.toEqual([[], []])
    expect(refreshCount).toBe(1)
  })

  it.each([
    ['network failure', async () => { throw new Error('offline') }],
    ['server failure', async () => response(503, { detail: 'Authentication service unavailable' })],
  ])('preserves the authenticated session after a refresh %s', async (_kind, refreshResult) => {
    const expired = vi.fn()
    window.addEventListener('evalforge:session-expired', expired)
    let datasetRequests = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/auth/login')) return response(200, authPayload(userA, 'current-token'))
      if (url.endsWith('/auth/refresh')) return refreshResult()
      if (url.endsWith('/datasets')) {
        datasetRequests += 1
        if (datasetRequests > 1) {
          expect(new Headers(init?.headers).get('Authorization')).toMatch(/^Bearer /)
        }
        return datasetRequests === 1
          ? response(401, { detail: 'Expired access token' })
          : response(200, [])
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    await api.login(userA.email, 'password')

    await expect(api.getDatasets()).rejects.toThrow(
      _kind === 'network failure' ? 'Could not reach the EvalForge backend' : 'Authentication service unavailable',
    )
    expect(expired).not.toHaveBeenCalled()
    await expect(api.getDatasets()).resolves.toEqual([])
    window.removeEventListener('evalforge:session-expired', expired)
  })

  it('clears local auth state on refresh failure without retrying indefinitely', async () => {
    const expired = vi.fn()
    window.addEventListener('evalforge:session-expired', expired)
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/auth/login')) return response(200, authPayload(userA))
      if (url.endsWith('/auth/refresh')) return response(401, { detail: 'Invalid or missing refresh token' })
      if (url.endsWith('/datasets')) return response(401, { detail: 'Invalid credentials' })
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    await api.login(userA.email, 'password')

    await expect(api.getDatasets()).rejects.toThrow('Invalid credentials')
    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith('/datasets'))).toHaveLength(1)
    expect(expired).toHaveBeenCalledOnce()
    window.removeEventListener('evalforge:session-expired', expired)
  })

  it('uses cookie credentials for logout and bearer auth for logout-all', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/auth/login')) return response(200, authPayload(userA))
      if (url.endsWith('/auth/logout')) {
        expect(init?.credentials).toBe('include')
        expect(new Headers(init?.headers).has('Authorization')).toBe(false)
        return response(204)
      }
      if (url.endsWith('/auth/logout-all')) {
        expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer access-user-a')
        return response(204)
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    await api.login(userA.email, 'password')
    await api.logout()
    await api.login(userA.email, 'password')
    await api.logoutAll()
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes('/auth/logout'))).toHaveLength(2)
  })

  it('keeps Demo records local and does not fall back to them for Live reads', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('offline'))
    vi.stubGlobal('fetch', fetchMock)

    await api.getDemoDatasets()
    await api.saveMockRun({
      id: 'demo-run',
      dataset: 'Demo dataset',
      datasetVersion: 'v1',
      model: 'Sample model',
      provider: 'mock',
      accuracy: 90,
      passRate: 90,
      latency: 1,
      status: 'Completed',
      date: '',
      passed: 1,
      failed: 0,
      total: 1,
    })
    expect(fetchMock).not.toHaveBeenCalled()
    await expect(api.getRuns()).rejects.toThrow('Could not reach the EvalForge backend')
    expect(await api.getDemoRuns()).toHaveLength(1)
  })
})

describe('Authentication UI and protected workspace', () => {
  it('shows login instead of protected data when no refresh session exists', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/auth/refresh')) {
        return response(401, { detail: 'Invalid or missing refresh token' })
      }
      return response(200, [])
    })
    vi.stubGlobal('fetch', fetchMock)

    renderApp('/datasets')

    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith('/datasets'))).toBe(false)
  })

  it('clears cached private data and redirects to login when refresh confirms expiration', async () => {
    let datasetRequests = 0
    let refreshRequests = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/auth/refresh')) {
        refreshRequests += 1
        return refreshRequests === 1
          ? response(200, authPayload(userA))
          : response(401, { detail: 'Invalid or missing refresh token' })
      }
      if (url.endsWith('/datasets')) {
        datasetRequests += 1
        return datasetRequests === 1
          ? response(200, [{
            id: 'private-cached-dataset',
            name: 'User A private dataset',
            description: '',
            version: 'v1',
            cases: 0,
            createdAt: '',
            modifiedAt: '',
            color: 'violet',
          }])
          : response(401, { detail: 'Invalid credentials' })
      }
      if (url.endsWith('/test-cases') || url.endsWith('/runs')
        || url.endsWith('/failures') || url.endsWith('/rubrics')) return response(200, [])
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const { queryClient } = renderApp('/datasets')

    await waitFor(() => {
      expect(queryClient.getQueryData(['datasets'])).toEqual([
        expect.objectContaining({ name: 'User A private dataset' }),
      ])
    })
    expect(screen.getByText('User A private dataset')).toBeInTheDocument()

    await queryClient.invalidateQueries({ queryKey: ['datasets'] })

    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeInTheDocument()
    expect(screen.queryByText('User A private dataset')).not.toBeInTheDocument()
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0)
    expect(refreshRequests).toBe(2)
  })

  it('offers session restoration again after a temporary startup refresh failure', async () => {
    let refreshAttempts = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/auth/refresh')) {
        refreshAttempts += 1
        return refreshAttempts === 1
          ? response(503, { detail: 'Authentication service unavailable' })
          : response(200, authPayload(userA))
      }
      if (String(input).endsWith('/datasets') || String(input).endsWith('/test-cases')
        || String(input).endsWith('/runs') || String(input).endsWith('/failures')
        || String(input).endsWith('/rubrics')) return response(200, [])
      throw new Error(`Unexpected request: ${String(input)}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderApp()

    expect(await screen.findByRole('alert')).toHaveTextContent('Authentication service unavailable')
    fireEvent.click(screen.getByRole('button', { name: 'Retry session' }))

    expect((await screen.findAllByText(userA.email)).length).toBeGreaterThan(0)
    expect(refreshAttempts).toBe(2)
  })

  it('logs in through the UI and only then loads the authenticated workspace', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/auth/refresh')) return response(401, { detail: 'Missing session' })
      if (url.endsWith('/auth/login')) return response(200, authPayload(userA))
      if (url.endsWith('/datasets') || url.endsWith('/test-cases') || url.endsWith('/runs')
        || url.endsWith('/failures') || url.endsWith('/rubrics')) {
        expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer access-user-a')
        return response(200, [])
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderApp('/login')

    fireEvent.change(await screen.findByLabelText('Email'), { target: { value: userA.email } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'correct password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect((await screen.findAllByText(userA.email)).length).toBeGreaterThan(0)
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith('/datasets'))).toBe(true)
  })

  it('keeps Demo mode local and available without a backend session', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/auth/refresh')) {
        return response(401, { detail: 'Invalid or missing refresh token' })
      }
      return response(200, [])
    })
    vi.stubGlobal('fetch', fetchMock)
    renderApp('/login')

    fireEvent.click(await screen.findByRole('button', { name: 'Explore local Demo' }))

    expect(await screen.findByText('DEMO · LOCAL ONLY')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => /\/api\/(datasets|test-cases|runs|failures|rubrics)$/.test(String(input)))).toBe(false)
    expect(screen.queryByLabelText('Evaluation mode')).not.toBeInTheDocument()
  })

  it('clears cached account data when switching users', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    let activeUser = userA
    let loggedOut = false
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/auth/refresh')) return response(200, authPayload(activeUser))
      if (url.endsWith('/auth/logout')) {
        loggedOut = true
        return response(204)
      }
      if (url.endsWith('/auth/login')) {
        activeUser = userB
        loggedOut = false
        return response(200, authPayload(userB))
      }
      if (url.endsWith('/datasets')) return response(200, [{ id: `dataset-${activeUser.id}` }])
      if (url.endsWith('/test-cases') || url.endsWith('/runs') || url.endsWith('/failures') || url.endsWith('/rubrics')) return response(200, [])
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/']}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await waitFor(() => expect(queryClient.getQueryData(['datasets'])).toEqual([{ id: 'dataset-user-a' }]))
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    await waitFor(() => expect(loggedOut).toBe(true))
    await waitFor(() => expect(queryClient.getQueryData(['datasets'])).toBeUndefined())
    fireEvent.change(await screen.findByLabelText('Email'), { target: { value: userB.email } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'another password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    await waitFor(() => expect(queryClient.getQueryData(['datasets'])).toEqual([{ id: 'dataset-user-b' }]))
    expect(screen.queryAllByText(userA.email)).toHaveLength(0)
    expect(screen.getAllByText(userB.email).length).toBeGreaterThan(0)
  })
})
