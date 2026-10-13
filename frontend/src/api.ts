import type { components } from './api.generated';

export type Analysis = components['schemas']['AnalysisResult'];
export type QueryPlan = components['schemas']['QueryPlan'];
export type AnalysisRequest = components['schemas']['AnalysisRequest'];

export async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/v1/${path}`, {
    method: body ? 'POST' : 'GET',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(15000),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = typeof data.detail === 'string' ? data.detail
      : Array.isArray(data.detail) ? data.detail.map((e: { msg: string }) => e.msg).join(' ')
      : 'The request could not be completed. Please try again.';
    throw new Error(detail);
  }
  return response.json();
}
