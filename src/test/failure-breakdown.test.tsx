import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { FailurePage } from '../pages'
import type { Failure } from '../types'

const createFailure = (overrides: Partial<Failure> & Pick<Failure, 'id' | 'failure_type'>): Failure => {
  const { id, failure_type, ...details } = overrides
  return {
    id,
    testCase: `Case ${id}`,
    dataset: 'Support dataset',
    model: 'test-model',
    run_status: 'Completed',
    run_provider: 'ollama',
    failure_type,
    category: 'Incorrect information',
    score: 0,
    timestamp: '2026-01-01',
    input: 'Question',
    expected: 'Expected answer',
    actual: 'Actual answer',
    explanation: 'Diagnostic details',
    reviewed: false,
    ...details,
  }
}

describe('Failure Breakdown', () => {
  it('separates failure and error counts and shows parent context in the detail view', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined)
    render(
      <FailurePage
        failures={[
          createFailure({ id: 'failed-result', failure_type: 'evaluation_failure' }),
          createFailure({ id: 'error-result', failure_type: 'evaluation_error', run_status: 'Failed' }),
        ]}
        onUpdate={onUpdate}
        notify={vi.fn()}
      />,
    )

    const summary = screen.getByLabelText('Failure type counts')
    expect(within(summary).getByText('Evaluation Failures').parentElement).toHaveTextContent('1')
    expect(within(summary).getByText('Evaluation Errors').parentElement).toHaveTextContent('1')
    expect(screen.getByText(/Failed runs can still contain useful persisted result records/)).toBeInTheDocument()
    expect(screen.getByText('Evaluation failure')).toBeInTheDocument()
    expect(screen.getByText('Evaluation error')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('row', { name: /error-result/ }))
    expect(await screen.findByRole('dialog', { name: 'Evaluation error inspection' })).toBeInTheDocument()
    expect(screen.getByText('Run Failed')).toBeInTheDocument()
    expect(screen.getByText('Provider: ollama')).toBeInTheDocument()
    expect(screen.getByText('An error occurred while executing this evaluation.')).toBeInTheDocument()
    expect(screen.getByText('Diagnostic details')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Pass/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Mark reviewed' }))
    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith(expect.objectContaining({
      id: 'error-result',
      reviewed: true,
      humanJudgment: 'pass',
    })))
  })

  it('shows a real empty state and zero counts for an empty API result', () => {
    render(<FailurePage failures={[]} onUpdate={vi.fn()} notify={vi.fn()} />)

    const summary = screen.getByLabelText('Failure type counts')
    expect(within(summary).getByText('Evaluation Failures').parentElement).toHaveTextContent('0')
    expect(within(summary).getByText('Evaluation Errors').parentElement).toHaveTextContent('0')
    expect(screen.getByText('No failures found')).toBeInTheDocument()
    expect(screen.queryByText('FAIL-2041')).not.toBeInTheDocument()
  })
})
