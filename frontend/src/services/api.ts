import { useAuthStore } from '../store/authStore';

// Use full URL when set. If only host (e.g. http://localhost:8002), append /api/v1
const rawBase = import.meta.env.VITE_API_URL || '';
const BASE = rawBase
  ? (rawBase.startsWith('http') && !rawBase.includes('/api/v1')
    ? `${rawBase.replace(/\/$/, '')}/api/v1`
    : rawBase.replace(/\/$/, ''))
  : '/api/v1';

function getBearerToken(): string | null {
  return useAuthStore.getState().token;
}

async function parseErrorMessage(res: Response): Promise<string> {
  let msg = res.statusText || 'Request failed';
  try {
    const j = (await res.json()) as { detail?: string | unknown };
    if (j?.detail != null) {
      msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
    }
  } catch {
    try {
      const t = await res.text();
      if (t) msg = t.slice(0, 200);
    } catch {
      /* ignore */
    }
  }
  return msg;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = path.startsWith('http') ? path : `${BASE}${path}`;
  const headers: Record<string, string> = { 'Content-Type': 'application/json', ...(options?.headers as Record<string, string>) };
  const token = getBearerToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(url, { ...options, headers });
  if (!res.ok) throw new Error(await parseErrorMessage(res));
  return res.json() as Promise<T>;
}

export type LoginResponse = {
  access_token: string;
  token_type: string;
  user: { email: string; role: string; display_name: string };
};

export const authApi = {
  async login(email: string, password: string): Promise<LoginResponse> {
    const url = `${BASE.replace(/\/$/, '')}/auth/login`;
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) throw new Error(await parseErrorMessage(res));
    return res.json() as Promise<LoginResponse>;
  },
  changePassword: (body: { current_password: string; new_password: string }) =>
    request<{ status: string; message: string }>('/auth/change-password', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
};

/** Trigger browser download of a blob with the given filename. */
function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export const dashboardApi = {
  getMetrics: () =>
    request<{
      total_transactions: number;
      total_alerts: number;
      high_risk_count: number;
      pending_strs?: number;
    }>('/analytics/dashboard'),
};

export type RiskBucket = { min: number; max: number; count: number; label: string };

export const analyticsApi = {
  getRiskDistribution: (params?: { bucket_count?: number }) =>
    request<{ buckets: RiskBucket[]; bucket_count: number }>(
      `/analytics/risk-distribution${params?.bucket_count ? `?bucket_count=${params.bucket_count}` : ''}`
    ),
  getTrends: (params: { metric?: string; granularity?: string }) => {
    const sp = new URLSearchParams();
    if (params.metric) sp.set('metric', params.metric);
    if (params.granularity) sp.set('granularity', params.granularity);
    return request<{ series: Array<{ date: string; value: number }>; granularity: string; metric: string }>(
      `/analytics/trends?${sp.toString()}`
    );
  },
};

export const transactionsApi = {
  list: (params: { skip?: number; limit?: number; page?: number; page_size?: number }) => {
    const page = params.page ?? 1;
    const page_size = params.page_size ?? params.limit ?? 20;
    return request<{ items: unknown[]; total: number; skip: number; limit: number }>(
      `/transactions/?page=${page}&page_size=${page_size}`
    );
  },
  ingest: (body: {
    customer_id: string;
    amount: number;
    currency?: string;
    transaction_type?: string;
    counterparty_id?: string | null;
    counterparty_name?: string | null;
    narrative?: string | null;
    channel?: string | null;
    timestamp?: string | null;
    metadata?: Record<string, unknown> | null;
  }) =>
    request<{
      id: string;
      customer_id: string;
      amount: number;
      currency: string;
      transaction_type: string;
      risk_score?: number;
      alert_id?: string | null;
      created_at: string;
      updated_at?: string | null;
    }>('/transactions/ingest', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
};

export type Alert = {
  id: string;
  transaction_id: string;
  customer_id: string;
  severity: number;
  status: string;
  rule_ids?: string[];
  summary?: string;
  created_at: string;
  updated_at?: string;
};

export type AlertsDashboard = {
  counts_by_severity: { low: number; medium: number; high: number; critical: number };
  counts_by_status: Record<string, number>;
  trend_over_time: Array<{ date: string; critical: number; high: number; medium: number; low: number }>;
  average_resolution_time_hours?: number;
};

export const alertsApi = {
  list: (params: { skip: number; limit: number }) =>
    request<{ items: Alert[]; total: number; skip: number; limit: number }>(
      `/alerts/?skip=${params.skip}&limit=${params.limit}`
    ),
  search: (params: { q: string; skip?: number; limit?: number }) => {
    const skip = params.skip ?? 0;
    const limit = params.limit ?? 20;
    return request<{ items: Alert[]; total: number; skip: number; limit: number }>(
      `/alerts/search?q=${encodeURIComponent(params.q)}&skip=${skip}&limit=${limit}`
    );
  },
  getDashboard: () => request<AlertsDashboard>('/alerts/dashboard'),
  get: (id: string) => request<Alert>(`/alerts/${id}`),
  investigate: (alertId: string, body: { investigator_id: string; notes?: string }) =>
    request<{ alert_id: string; status: string; investigator_id: string; action_key: string }>(`/alerts/${alertId}/investigate`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  resolve: (alertId: string, body: { resolution: 'true_positive' | 'false_positive'; notes: string; action_taken?: string }) =>
    request<{ alert_id: string; resolution: string; status: string; action_key: string }>(`/alerts/${alertId}/resolve`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  escalate: (alertId: string, body: { reason: string; escalated_to: string }) =>
    request<{ alert_id: string; status: string; escalated_to: string; action_key: string }>(`/alerts/${alertId}/escalate`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
};

export const reportsApi = {
  generateSTR: (body: { alert_id: string; additional_context?: Record<string, unknown> }) =>
    request<{ report_id: string; xml_preview: string | null; validation_passed: boolean }>('/reports/str/generate', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  generateCTR: (body: { transaction_ids?: string[]; customer_id?: string }) =>
    request<{ report_id: string; xml_preview?: string | null; validation_passed: boolean }>('/reports/ctr/generate', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  /** Download STR as Word or XML (NFIU goAML). */
  async downloadSTR(reportId: string, format: 'word' | 'xml') {
    const url = `${BASE.replace(/\/$/, '')}/reports/str/${encodeURIComponent(reportId)}/download?format=${format}`;
    const token = getBearerToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(url, { headers });
    if (!res.ok) throw new Error(res.statusText);
    const blob = await res.blob();
    const disposition = res.headers.get('Content-Disposition');
    const filename = disposition?.match(/filename="?([^";]+)"?/)?.[1] || `${reportId}.${format === 'word' ? 'docx' : 'xml'}`;
    downloadBlob(blob, filename);
  },
  /** Download CTR as Word or XML (NFIU goAML). */
  async downloadCTR(reportId: string, format: 'word' | 'xml') {
    const url = `${BASE.replace(/\/$/, '')}/reports/ctr/${encodeURIComponent(reportId)}/download?format=${format}`;
    const token = getBearerToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(url, { headers });
    if (!res.ok) throw new Error(res.statusText);
    const blob = await res.blob();
    const disposition = res.headers.get('Content-Disposition');
    const filename = disposition?.match(/filename="?([^";]+)"?/)?.[1] || `${reportId}.${format === 'word' ? 'docx' : 'xml'}`;
    downloadBlob(blob, filename);
  },
};

export type TemporalSimulationResult = {
  total_generated: number;
  year_span: number;
  customers: number;
  scenario_counts: Record<string, number>;
  seed: number;
  approx_start: string;
  approx_end: string;
  alerts_created: number;
  stored_transactions: number;
};

export const demoApi = {
  seed: () => request<{ seeded_transactions: number; transaction_ids: string[] }>('/demo/seed', { method: 'POST' }),
  /** ~10 years of synthetic history per customer + AML scenarios; may take 1–2 minutes. */
  simulateTemporal: (body?: {
    years?: number;
    seed?: number;
    clear_existing?: boolean;
    max_transactions?: number;
    refit_every?: number;
  }) =>
    request<TemporalSimulationResult>('/demo/simulate-temporal', {
      method: 'POST',
      body: JSON.stringify({
        years: 10,
        seed: 42,
        clear_existing: true,
        max_transactions: 100_000,
        refit_every: 500,
        ...body,
      }),
    }),
};