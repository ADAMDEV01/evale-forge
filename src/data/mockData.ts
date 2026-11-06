import type { Dataset, EvaluationRun, Failure, ModelMetric, TestCase } from '../types'

export const initialDatasets: Dataset[] = [
  { id: 'ds-support', name: 'Customer support v2', description: 'Support conversations spanning billing, account access, and product guidance.', version: 'v2.4', cases: 248, createdAt: '2024-08-12', modifiedAt: '2025-02-14', color: 'violet' },
  { id: 'ds-rag', name: 'RAG factuality', description: 'Grounded question answering against the product knowledge base.', version: 'v1.8', cases: 186, createdAt: '2024-09-03', modifiedAt: '2025-02-12', color: 'blue' },
  { id: 'ds-code', name: 'Code generation', description: 'Real-world TypeScript tasks with executable expected behaviors.', version: 'v3.1', cases: 124, createdAt: '2024-07-22', modifiedAt: '2025-02-10', color: 'emerald' },
  { id: 'ds-safety', name: 'Safety & refusal', description: 'Policy adherence, safe completions, and refusal quality checks.', version: 'v1.2', cases: 92, createdAt: '2024-11-18', modifiedAt: '2025-02-08', color: 'amber' },
]

export const initialTestCases: TestCase[] = [
  { id: 'TC-1042', datasetId: 'ds-support', title: 'Refund policy eligibility', input: 'I purchased the annual plan 18 days ago. Can I still get a refund?', expected: 'You are eligible for a refund within 30 days of purchase. I can help you start the refund process.', criteria: 'Must accurately state the 30-day window and offer a next step.', category: 'Billing', tags: ['refund', 'policy'], importance: 'High', expectedBehavior: 'State policy clearly and offer an actionable path.' },
  { id: 'TC-1038', datasetId: 'ds-support', title: 'Reset a locked account', input: 'I have tried signing in too many times and now I am locked out. What should I do?', expected: 'Your account will unlock after 15 minutes. You can also reset your password using the link on the sign-in page.', criteria: 'Explain lockout duration and password recovery without requesting credentials.', category: 'Account access', tags: ['account', 'security'], importance: 'Critical', expectedBehavior: 'Give secure recovery instructions.' },
  { id: 'TC-0991', datasetId: 'ds-rag', title: 'Unsupported feature question', input: 'Does the Starter plan include audit log exports?', expected: 'Audit log exports are available on the Business plan and above, not on the Starter plan.', criteria: 'Answer only from provided plan documentation.', category: 'Grounding', tags: ['pricing', 'grounding'], importance: 'High', expectedBehavior: 'Be factual and avoid inventing plan features.' },
  { id: 'TC-0877', datasetId: 'ds-code', title: 'Validate email format', input: 'Write a TypeScript function that validates an email address without external dependencies.', expected: 'A typed function using a practical regular expression and a boolean return value.', criteria: 'Must compile and handle empty or malformed input.', category: 'Code quality', tags: ['typescript', 'validation'], importance: 'Medium', expectedBehavior: 'Return a concise, executable TypeScript implementation.' },
]

export const initialRuns: EvaluationRun[] = [
  { id: 'run_8f2a91', dataset: 'Customer support v2', datasetVersion: 'v2.4', model: 'Demo Model 1', accuracy: 94.2, passRate: 91.8, latency: 842, status: 'Completed', date: 'Feb 14, 2025 · 10:42 AM', passed: 228, failed: 20, total: 248 },
  { id: 'run_8f1c73', dataset: 'RAG factuality', datasetVersion: 'v1.8', model: 'Demo Model 2', accuracy: 91.6, passRate: 88.7, latency: 1120, status: 'Completed', date: 'Feb 14, 2025 · 09:18 AM', passed: 165, failed: 21, total: 186 },
  { id: 'run_8ecb04', dataset: 'Code generation', datasetVersion: 'v3.1', model: 'Demo Model 3', accuracy: 87.3, passRate: 84.1, latency: 1386, status: 'Completed', date: 'Feb 13, 2025 · 04:32 PM', passed: 108, failed: 16, total: 124 },
  { id: 'run_8e2d11', dataset: 'Customer support v2', datasetVersion: 'v2.4', model: 'Demo Model 2', accuracy: 89.7, passRate: 87.1, latency: 964, status: 'Completed', date: 'Feb 13, 2025 · 11:06 AM', passed: 216, failed: 32, total: 248 },
  { id: 'run_8d991a', dataset: 'Safety & refusal', datasetVersion: 'v1.2', model: 'Demo Model 1', accuracy: 97.8, passRate: 96.7, latency: 734, status: 'Completed', date: 'Feb 12, 2025 · 02:51 PM', passed: 89, failed: 3, total: 92 },
]

export const initialFailures: Failure[] = [
  { id: 'FAIL-2041', testCase: 'Refund policy eligibility', dataset: 'Customer support v2', model: 'Demo Model 2', run_status: 'Completed', run_provider: 'sample/demo', failure_type: 'evaluation_failure', category: 'Incorrect information', score: 0.42, timestamp: 'Feb 14, 2025 · 10:43 AM', input: 'I purchased the annual plan 18 days ago. Can I still get a refund?', expected: 'You are eligible for a refund within 30 days of purchase. I can help you start the refund process.', actual: 'Our refund policy allows refunds within 14 days of purchase. Since it has been 18 days, this purchase is no longer eligible.', explanation: 'The response states a 14-day refund window, contradicting the expected 30-day policy.', reviewed: false },
  { id: 'FAIL-2037', testCase: 'Unsupported feature question', dataset: 'RAG factuality', model: 'Demo Model 2', run_status: 'Completed', run_provider: 'sample/demo', failure_type: 'evaluation_failure', category: 'Hallucination', score: 0.28, timestamp: 'Feb 14, 2025 · 09:21 AM', input: 'Does the Starter plan include audit log exports?', expected: 'Audit log exports are available on the Business plan and above, not on the Starter plan.', actual: 'Yes, the Starter plan includes basic audit log exports with 30 days of retention.', explanation: 'Invented a feature and retention policy not present in the source documentation.', reviewed: false },
  { id: 'FAIL-2032', testCase: 'Reset a locked account', dataset: 'Customer support v2', model: 'Demo Model 3', run_status: 'Completed', run_provider: 'sample/demo', failure_type: 'evaluation_failure', category: 'Missing information', score: 0.56, timestamp: 'Feb 13, 2025 · 04:38 PM', input: 'I have tried signing in too many times and now I am locked out. What should I do?', expected: 'Your account will unlock after 15 minutes. You can also reset your password using the link on the sign-in page.', actual: 'Try resetting your password from the sign-in page. If that does not work, contact support.', explanation: 'Does not mention the 15-minute lockout duration specified in the expected behavior.', reviewed: true, note: 'Retest after the account recovery docs are updated.' },
  { id: 'FAIL-2026', testCase: 'Validate email format', dataset: 'Code generation', model: 'Demo Model 3', run_status: 'Completed', run_provider: 'sample/demo', failure_type: 'evaluation_failure', category: 'Instruction following', score: 0.61, timestamp: 'Feb 13, 2025 · 04:35 PM', input: 'Write a TypeScript function that validates an email address without external dependencies.', expected: 'A typed function using a practical regular expression and a boolean return value.', actual: 'Install validator from npm, then call isEmail(input).', explanation: 'The answer depends on an external package despite the explicit no-dependencies constraint.', reviewed: false },
]

export const modelMetrics: ModelMetric[] = [
  { name: 'Demo Model 1', provider: 'Demo', accuracy: 94.2, passRate: 91.8, latency: 842, failureRate: 8.2, score: 4.68, tokens: '1.24M', cost: '$8.42', color: '#a78bfa' },
  { name: 'Demo Model 2', provider: 'Demo', accuracy: 91.6, passRate: 88.7, latency: 964, failureRate: 11.3, score: 4.52, tokens: '1.18M', cost: '$6.18', color: '#60a5fa' },
  { name: 'Demo Model 3', provider: 'Demo', accuracy: 87.3, passRate: 84.1, latency: 1386, failureRate: 15.9, score: 4.21, tokens: '1.31M', cost: '$4.76', color: '#34d399' },
]

export const accuracyTrend = [
  { date: 'Feb 08', claude: 89, gpt: 87, gemini: 83 },
  { date: 'Feb 09', claude: 90, gpt: 86, gemini: 84 },
  { date: 'Feb 10', claude: 91, gpt: 89, gemini: 82 },
  { date: 'Feb 11', claude: 90, gpt: 88, gemini: 85 },
  { date: 'Feb 12', claude: 93, gpt: 90, gemini: 86 },
  { date: 'Feb 13', claude: 92, gpt: 89, gemini: 85 },
  { date: 'Feb 14', claude: 94, gpt: 92, gemini: 87 },
]

export const runTrend = [
  { date: 'Feb 08', runs: 18 }, { date: 'Feb 09', runs: 24 }, { date: 'Feb 10', runs: 21 },
  { date: 'Feb 11', runs: 32 }, { date: 'Feb 12', runs: 28 }, { date: 'Feb 13', runs: 39 }, { date: 'Feb 14', runs: 34 },
]

export const failureBreakdown = [
  { name: 'Incorrect info', value: 38, fill: '#f87171' },
  { name: 'Missing info', value: 27, fill: '#fbbf24' },
  { name: 'Hallucination', value: 19, fill: '#a78bfa' },
  { name: 'Instruction', value: 11, fill: '#60a5fa' },
  { name: 'Other', value: 5, fill: '#64748b' },
]
