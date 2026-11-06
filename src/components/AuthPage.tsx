import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api } from '../services/api'
import type { AuthUser } from '../services/api'
import { Button, Field } from './ui'

interface AuthPageProps {
  onAuthenticated: (user: AuthUser) => void
  onDemo: () => void
  onRetrySession?: () => void
  initialError?: string
}

export function AuthPage({ onAuthenticated, onDemo, onRetrySession, initialError = '' }: AuthPageProps) {
  const location = useLocation()
  const registering = location.pathname === '/register'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(initialError)
  const [submitting, setSubmitting] = useState(false)

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      const user = registering
        ? await api.register(email, password)
        : await api.login(email, password)
      onAuthenticated(user)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Authentication failed.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="auth-title">
        <div className="auth-brand"><span className="brand-mark"><span /></span><span className="brand-name">eval<span>forge</span></span></div>
        <p className="eyebrow">SECURE EVALUATION WORKSPACE</p>
        <h1 id="auth-title">{registering ? 'Create your account' : 'Welcome back'}</h1>
        <p className="auth-description">
          {registering ? 'Register to create a private workspace for your evaluations.' : 'Sign in to access your private evaluation workspace.'}
        </p>
        <form className="auth-form" onSubmit={(event) => void submit(event)}>
          <Field label="Email">
            <input
              autoComplete="email"
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
            />
          </Field>
          <Field label="Password">
            <input
              autoComplete={registering ? 'new-password' : 'current-password'}
              type="password"
              required
              minLength={registering ? 12 : 1}
              maxLength={128}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder={registering ? 'At least 12 characters' : 'Your password'}
            />
          </Field>
          {error && <div className="auth-error" role="alert">{error}</div>}
          <Button variant="primary" disabled={submitting}>
            {submitting ? 'Please wait…' : registering ? 'Create account' : 'Sign in'}
          </Button>
        </form>
        {onRetrySession && <Button onClick={onRetrySession}>Retry session</Button>}
        <p className="auth-switch">
          {registering ? 'Already have an account?' : 'New to EvalForge?'}{' '}
          <Link to={registering ? '/login' : '/register'}>{registering ? 'Sign in' : 'Create an account'}</Link>
        </p>
        <div className="auth-separator"><span>or</span></div>
        <Button onClick={onDemo}>Explore local Demo</Button>
        <p className="auth-demo-note">Demo data stays in this browser and is never sent to the backend.</p>
      </section>
    </main>
  )
}
