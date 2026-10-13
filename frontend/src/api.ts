import type { components } from './api.generated';

export type Analysis = components['schemas']['AnalysisResult'];
export type QueryPlan = components['schemas']['QueryPlan'];
export type AnalysisRequest = components['schemas']['AnalysisRequest'];
export type Account = components['schemas']['AccountView'];
export type AccountSession = components['schemas']['SessionView'];
export type Message = components['schemas']['Message'];
export type AdminSummary = components['schemas']['AdminSummary'];

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function request<T>(path: string, body?: unknown, method?: string): Promise<T> {
  const response = await fetch(`/api/v1/${path}`, {
    method: method ?? (body !== undefined ? 'POST' : 'GET'),
    credentials: 'same-origin',
    headers: body !== undefined ? { 'Content-Type': 'application/json', 'X-SDC-Request': '1' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(20000),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = typeof data.detail === 'string' ? data.detail
      : Array.isArray(data.detail) ? data.detail.map((e: { msg: string }) => e.msg).join(' ')
      : 'The request could not be completed. Please try again.';
    if (response.status === 401 && path !== 'auth/login') window.dispatchEvent(new Event('sdc-signed-out'));
    throw new ApiError(detail, response.status);
  }
  return response.json();
}
