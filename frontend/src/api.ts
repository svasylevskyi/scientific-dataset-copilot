import type { components } from './api.generated';

export type Analysis = components['schemas']['AnalysisResult'];
export type QueryPlan = components['schemas']['QueryPlan'];
export type AnalysisRequest = components['schemas']['AnalysisRequest'];
export type Account = components['schemas']['AccountView'];
export type AccountSession = components['schemas']['SessionView'];
export type Message = components['schemas']['Message'];
export type AdminSummary = components['schemas']['AdminSummary'];
export type Plan = components['schemas']['PlanView'];
export type AdminPlan = components['schemas']['AdminPlanView'];
export type PlanInput = components['schemas']['PlanInput'];
export type Usage = components['schemas']['UsageView'];
export type SavedAnalysis = components['schemas']['AnalysisView'];
export type AnalysisInput = components['schemas']['AnalysisInput'];
export type AnalysisRun = components['schemas']['RunView'];
export type RunDetail = components['schemas']['RunDetail'];
export type PlannerStatus = components['schemas']['PlannerStatus'];
export type PlanningView = components['schemas']['PlanningView'];
export type Proposal = components['schemas']['Proposal'];
export type PlanningCosts = components['schemas']['PlanningCosts'];

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function request<T>(path: string, body?: unknown, method?: string, timeout = 20000): Promise<T> {
  const response = await fetch(`/api/v1/${path}`, {
    method: method ?? (body !== undefined ? 'POST' : 'GET'),
    credentials: 'same-origin',
    headers: body !== undefined ? { 'Content-Type': 'application/json', 'X-SDC-Request': '1' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(timeout),
  });
  if (!response.ok) {
    // The development Basic-auth gateway transports app 401s as marked 403s
    // so browsers keep the independent tester-gate credentials cached.
    const status = response.status === 403 && response.headers.get('X-SDC-App-Status') === '401'
      ? 401 : response.status;
    const data = await response.json().catch(() => ({}));
    const detail = typeof data.detail === 'string' ? data.detail
      : Array.isArray(data.detail) ? data.detail.map((e: { msg: string }) => e.msg).join(' ')
      : 'The request could not be completed. Please try again.';
    if (status === 401 && path !== 'auth/login') window.dispatchEvent(new Event('sdc-signed-out'));
    throw new ApiError(detail, status);
  }
  return response.json();
}
