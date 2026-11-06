export type RunStatus = 'Completed' | 'Running' | 'Failed' | 'Pending' | 'Cancelled'
export type EvaluationMode = 'mock' | 'ollama'
export type EvaluationMethod = 'exact_match' | 'keyword_match' | 'rubric'
export type Importance = 'Critical' | 'High' | 'Medium' | 'Low'
export type FailureCategory =
  | 'Incorrect information'
  | 'Missing information'
  | 'Hallucination'
  | 'Instruction following'
  | 'Formatting error'
  | 'Timeout'
  | 'API error'
  | (string & {})

export interface Dataset {
  id: string
  name: string
  description: string
  version: string
  cases: number
  createdAt: string
  modifiedAt: string
  color: string
}

export interface EvaluationResult {
  id: string
  testCaseId: string
  testCaseTitle: string
  category: string
  status: string
  score: number
  latencyMs: number
  input: string
  expected: string
  actual: string
  passed: boolean
  evaluationMethod: EvaluationMethod
  tokenUsage: number | null
  criteriaBreakdown: Array<Record<string, unknown>>
  errorType: string | null
  errorMessage: string | null
}

export interface EvaluationExecution {
  run: EvaluationRun
  results: EvaluationResult[]
  metrics: {
    accuracy: number
    passRate: number
    failureRate: number
    averageLatency: number
    averageScore: number
    tokenUsage: number
    estimatedCost: number | null
  }
  errors: number
}

export interface TestCase {
  id: string
  datasetId: string
  title: string
  input: string
  expected: string
  expectedKeywords?: string[]
  criteria: string
  category: string
  tags: string[]
  importance: Importance
  expectedBehavior: string
}

export interface RubricCriterion {
  id?: string
  name: string
  description: string
  weight: number
  scale: string
  expectedKeywords: string[]
}

export interface Rubric {
  id: string
  name: string
  description: string
  active: boolean
  criteria: RubricCriterion[]
}

export interface EvaluationRun {
  id: string
  dataset: string
  datasetVersion: string
  model: string
  provider?: string
  mode?: EvaluationMode
  evaluationMethod?: EvaluationMethod
  tokenUsage?: number | null
  estimatedCost?: number | null
  errorType?: string | null
  errorMessage?: string | null
  accuracy: number
  passRate: number
  latency: number
  status: RunStatus
  date: string
  passed: number
  failed: number
  total: number
  persisted_results_count?: number
}

export interface Failure {
  id: string
  testCase: string
  dataset: string
  model: string
  run_status: string
  run_provider: string
  failure_type: 'evaluation_failure' | 'evaluation_error'
  category: FailureCategory
  score: number
  timestamp: string
  input: string
  expected: string
  actual: string
  explanation: string
  reviewed: boolean
  note?: string
  humanJudgment?: 'pass' | 'fail'
}

export interface ModelMetric {
  name: string
  provider: string
  accuracy: number
  passRate: number
  latency: number
  failureRate: number
  score: number
  tokens: string
  cost: string
  color: string
}

export interface EvaluationConfig {
  datasetId: string
  models: string[]
  metrics: string[]
  rubric: string
  concurrency: number
  temperature: number
  evaluationMethod?: EvaluationMethod
}

export interface MockExecutionProgress {
  progress: number
  pending: number
  running: number
  passed: number
  failed: number
  errors: number
}
