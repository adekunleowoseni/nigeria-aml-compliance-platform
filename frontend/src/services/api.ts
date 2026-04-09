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

export type LoginUserPayload = {
  email: string;
  role: string;
  display_name: string;
  aml_region?: string;
  aml_zones?: string[];
  aml_branch_codes?: string[];
};

export type LoginResponse = {
  access_token: string;
  token_type: string;
  user: LoginUserPayload;
};

export type ZonesCatalog = {
  regions: Record<
    string,
    {
      label: string;
      zones: Record<string, { label: string; branches: Record<string, string> }>;
    }
  >;
};

export type AdminUserRow = {
  email: string;
  role: string;
  display_name: string;
  aml_region?: string;
  aml_zones?: string[];
  aml_branch_codes?: string[];
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
  me: () =>
    request<{
      sub?: string;
      email?: string;
      role?: string;
      display_name?: string;
      aml_region?: string;
      aml_zones?: string[];
      aml_branch_codes?: string[];
    }>('/auth/me'),
  catalogZones: () => request<ZonesCatalog>('/auth/catalog/zones'),
  updateAssignments: (body: { aml_region: string; aml_zones: string[]; aml_branch_codes: string[] }) =>
    request<LoginResponse>('/auth/me/assignments', {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  adminListUsers: () => request<{ items: AdminUserRow[]; total: number }>('/auth/admin/users'),
  adminCreateUser: (body: {
    email: string;
    password: string;
    role: string;
    display_name: string;
    aml_region?: string;
    aml_zones?: string[];
    aml_branch_codes?: string[];
  }) => request<{ status: string; user: AdminUserRow }>('/auth/admin/users', { method: 'POST', body: JSON.stringify(body) }),
  adminPatchUser: (
    email: string,
    body: Partial<{
      display_name: string;
      role: string;
      password: string;
      aml_region: string;
      aml_zones: string[];
      aml_branch_codes: string[];
    }>
  ) => request<{ status: string; user: AdminUserRow }>(`/auth/admin/users/${encodeURIComponent(email)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  }),
  adminDeleteUser: (email: string) =>
    request<{ status: string }>(`/auth/admin/users/${encodeURIComponent(email)}`, { method: 'DELETE' }),
  getWorkflowSettings: () =>
    request<{
      cco_auto_approve_otc_reporting: boolean;
      cco_auto_approve_str_on_escalation: boolean;
      description: string;
    }>('/auth/admin/workflow-settings'),
  putWorkflowSettings: (body: {
    cco_auto_approve_otc_reporting: boolean;
    cco_auto_approve_str_on_escalation: boolean;
  }) =>
    request<{
      status: string;
      cco_auto_approve_otc_reporting: boolean;
      cco_auto_approve_str_on_escalation: boolean;
    }>('/auth/admin/workflow-settings', { method: 'PUT', body: JSON.stringify(body) }),
  changePassword: (body: { current_password: string; new_password: string }) =>
    request<{ status: string; message: string }>('/auth/change-password', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
};

export type AiProvider = 'gemini' | 'openai' | 'ollama';

export const aiApi = {
  getSettings: () =>
    request<{
      provider: AiProvider;
      available_providers: AiProvider[];
      defaults: { gemini_model: string; openai_model: string; ollama_model: string };
    }>('/ai/settings'),
  updateSettings: (body: { provider: AiProvider }) =>
    request<{ status: string; provider: AiProvider; message: string }>('/ai/settings', {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  refineReport: (body: { draft_text: string; instruction?: string; alert_id?: string }) =>
    request<{ provider: string; model: string; refined_text: string }>('/ai/refine-report', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
};

function auditQueryString(params: Record<string, string | number | undefined | null | boolean>) {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : '';
}

export type AuditEvent = {
  id: string;
  sequence: number;
  timestamp: string;
  action: string;
  resource_type: string;
  resource_id: string;
  actor_sub?: string;
  actor_email: string;
  actor_role: string;
  details: Record<string, unknown>;
  ip_address?: string | null;
  prev_chain_hash?: string;
  integrity_hash?: string;
};

export type AuditPaginated = { items: AuditEvent[]; total: number; skip: number; limit: number };

export type AuditGovernanceSummary = {
  period: { from: string | null | undefined; to: string | null | undefined };
  total_events: number;
  unique_actions: number;
  by_action: Record<string, number>;
  by_actor_role: Record<string, number>;
  report_events_count: number;
};

export const auditApi = {
  listEvents: (params: {
    skip?: number;
    limit?: number;
    from_ts?: string;
    to_ts?: string;
    q?: string;
    actor_email?: string;
    action_contains?: string;
    resource_type?: string;
  }) => request<AuditPaginated>(`/audit/events${auditQueryString(params)}`),
  listReports: (params: {
    skip?: number;
    limit?: number;
    from_ts?: string;
    to_ts?: string;
    report_type?: string;
    q?: string;
    actor_email?: string;
  }) => request<AuditPaginated>(`/audit/reports${auditQueryString(params)}`),
  summary: (params?: { from_ts?: string; to_ts?: string }) =>
    request<AuditGovernanceSummary>(`/audit/summary${auditQueryString(params ?? {})}`),
  integrity: () =>
    request<{
      valid: boolean;
      events_verified: number;
      chain_head: string;
      storage?: string;
      postgres_total_rows?: number | null;
      verify_truncated?: boolean;
      retention_config?: {
        audit_trail_backend: string;
        audit_retention_days: number | null;
        audit_retention_interval_hours: number;
        document_retention_note: string;
      };
    }>('/audit/integrity'),
  retentionConfig: () =>
    request<{
      audit_trail_backend: string;
      audit_retention_days: number | null;
      audit_retention_interval_hours: number;
      document_retention_note: string;
    }>('/audit/retention-config'),
  async exportAudit(format: 'csv' | 'json', params?: { from_ts?: string; to_ts?: string }) {
    const sp = new URLSearchParams();
    sp.set('format', format);
    if (params?.from_ts) sp.set('from_ts', params.from_ts);
    if (params?.to_ts) sp.set('to_ts', params.to_ts);
    const url = `${BASE.replace(/\/$/, '')}/audit/export?${sp.toString()}`;
    const token = getBearerToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(url, { headers });
    if (!res.ok) throw new Error(await parseErrorMessage(res));
    const blob = await res.blob();
    const disposition = res.headers.get('Content-Disposition');
    const filename =
      disposition?.match(/filename="?([^";]+)"?/)?.[1] || (format === 'json' ? 'audit_export.json' : 'audit_export.csv');
    downloadBlob(blob, filename);
  },
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

export type ReportingProfileRow = {
  id?: number;
  template_pack?: string;
  institution_display_name?: string;
  reporting_entity_name?: string;
  entity_registration_ref?: string;
  default_outputs?: Record<string, unknown>;
  narrative_style?: string;
  updated_at?: string;
  updated_by?: string | null;
};

export type RegulatoryCalendarEntry = {
  id: string;
  slug: string;
  title: string;
  report_family: string;
  frequency: string;
  cron_expression?: string | null;
  day_of_month?: number | null;
  day_of_week?: number | null;
  submission_offset_days?: number;
  reminder_days_before?: number;
  enabled?: boolean;
  preferred_formats?: Record<string, unknown>;
  notes?: string | null;
  updated_at?: string;
  updated_by?: string | null;
};

/** Admin: CBN / bank reporting profile and regulatory return calendar. */
export const adminReportingApi = {
  templatePacks: () =>
    request<{ packs: { id: string; label: string; defaults: Record<string, string> }[] }>(
      '/admin/reporting/template-packs',
    ),
  getProfile: () =>
    request<{
      profile: ReportingProfileRow;
      default_outputs_effective: Record<string, unknown>;
      template_pack_presets: Record<string, Record<string, string>>;
    }>('/admin/reporting/profile'),
  putProfile: (body: {
    template_pack: string;
    institution_display_name: string;
    reporting_entity_name: string;
    entity_registration_ref: string;
    default_outputs: Record<string, unknown>;
    narrative_style: string;
    apply_preset_defaults?: boolean;
  }) =>
    request<{ status: string; profile: ReportingProfileRow; default_outputs_effective: Record<string, unknown> }>(
      '/admin/reporting/profile',
      { method: 'PUT', body: JSON.stringify(body) },
    ),
  getCalendar: () =>
    request<{ items: RegulatoryCalendarEntry[]; upcoming_preview: Record<string, unknown>[] }>(
      '/admin/reporting/calendar',
    ),
  createCalendar: (body: {
    slug: string;
    title: string;
    report_family: string;
    frequency: string;
    cron_expression?: string | null;
    day_of_month?: number | null;
    day_of_week?: number | null;
    submission_offset_days?: number;
    reminder_days_before?: number;
    enabled?: boolean;
    preferred_formats?: Record<string, unknown>;
    notes?: string | null;
  }) =>
    request<{ status: string; entry: RegulatoryCalendarEntry }>('/admin/reporting/calendar', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  patchCalendar: (
    entryId: string,
    body: Partial<{
      title: string;
      report_family: string;
      frequency: string;
      cron_expression: string | null;
      day_of_month: number | null;
      day_of_week: number | null;
      submission_offset_days: number;
      reminder_days_before: number;
      enabled: boolean;
      preferred_formats: Record<string, unknown>;
      notes: string | null;
    }>,
  ) =>
    request<{ status: string; entry: RegulatoryCalendarEntry }>(`/admin/reporting/calendar/${entryId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  deleteCalendar: (entryId: string) =>
    request<{ status: string }>(`/admin/reporting/calendar/${entryId}`, { method: 'DELETE' }),
};

/** Admin: uploaded sanctions / PEP / adverse-media reference lists (JSON or XML) and full-database fuzzy screening. */
export const adminReferenceListsApi = {
  summary: () =>
    request<{
      counts: Record<string, number>;
      latest_screening_run: Record<string, unknown> | null;
    }>('/admin/reference-lists'),
  uploadFile: async (listType: 'sanctions' | 'pep' | 'adverse_media', file: File) => {
    const url = `${BASE}/admin/reference-lists/${listType}/upload`;
    const headers: Record<string, string> = {};
    const token = getBearerToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch(url, { method: 'POST', headers, body: fd });
    if (!res.ok) throw new Error(await parseErrorMessage(res));
    return res.json() as Promise<{ status: string; list_type: string; records_loaded: number }>;
  },
  runScreeningNow: () =>
    request<{
      status: string;
      customers_scanned: number;
      customer_rows_reported_total?: number;
      hits_total: number;
      fuzzy_threshold: number;
      hits_truncated?: boolean;
    }>('/admin/reference-lists/screening/run-now', { method: 'POST' }),
};

export type RedFlagRuleRow = {
  id: string;
  rule_code: string;
  title: string;
  description: string;
  enabled: boolean;
  match_patterns: string[];
  updated_by?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type DetectionRuleCatalogItem = {
  rule_id: string;
  title: string;
  description: string;
  parameters?: Record<string, unknown>;
};

/** Admin: configurable AML red-flag library (pattern-matched on ingest + snapshots). */
export const adminRedFlagsApi = {
  listRules: () => request<{ items: RedFlagRuleRow[] }>('/admin/red-flags/rules'),
  ruleCatalog: () =>
    request<{
      red_flag_rules: RedFlagRuleRow[];
      typology_rules: DetectionRuleCatalogItem[];
      anomaly_rules: DetectionRuleCatalogItem[];
      pattern_sources: Array<{ source: string; description: string }>;
    }>('/admin/red-flags/rule-catalog'),
  upsertRule: (body: {
    rule_code: string;
    title: string;
    description: string;
    enabled?: boolean;
    match_patterns?: string[];
  }) =>
    request<{ status: string; rule: RedFlagRuleRow }>('/admin/red-flags/rules', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  uploadJson: (body: Record<string, unknown>[] | Record<string, unknown>) =>
    request<{ status: string; upserted: number; errors: string[] }>('/admin/red-flags/upload-json', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  deleteRule: (ruleCode: string) =>
    request<{ status: string; deleted: string }>(`/admin/red-flags/rules/${encodeURIComponent(ruleCode)}`, {
      method: 'DELETE',
    }),
};

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
  list: (params: {
    page?: number;
    page_size?: number;
    start_date?: string;
    end_date?: string;
    min_amount?: number;
    max_amount?: number;
    status?: string;
    entity_id?: string;
    transaction_type?: string;
    q?: string;
  }) => {
    const page = params.page ?? 1;
    const page_size = params.page_size ?? 20;
    const sp = new URLSearchParams({
      page: String(Math.max(1, page)),
      page_size: String(page_size),
    });
    if (params.start_date) sp.set('start_date', params.start_date);
    if (params.end_date) sp.set('end_date', params.end_date);
    if (params.min_amount != null) sp.set('min_amount', String(params.min_amount));
    if (params.max_amount != null) sp.set('max_amount', String(params.max_amount));
    if (params.status) sp.set('status', params.status);
    if (params.entity_id) sp.set('entity_id', params.entity_id);
    if (params.transaction_type) sp.set('transaction_type', params.transaction_type);
    if (params.q) sp.set('q', params.q);
    return request<{
      items: unknown[];
      total: number;
      skip: number;
      limit: number;
      page?: number;
      page_size?: number;
    }>(`/transactions/?${sp.toString()}`);
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

export type CustomerKycDto = {
  customer_name: string;
  account_number: string;
  account_opened: string;
  customer_address: string;
  line_of_business: string;
  phone_number: string;
  date_of_birth: string;
  id_number: string;
};

export type CustomerRiskReview = {
  review_id: string;
  customer_id: string;
  reviewed_at: string;
  risk_rating: 'high' | 'medium' | 'low';
  previous_risk_rating?: string | null;
  next_review_due_at: string;
  suggested_risk_profile?: 'high' | 'medium' | 'low';
  recommendation?: string;
  status?: string;
  pep_flag?: boolean;
  profile_changed?: boolean;
  account_update_within_period?: boolean;
  management_approval_within_period?: boolean;
  age_commensurate?: boolean;
  activity_commensurate?: boolean;
  expected_turnover_match?: boolean;
  expected_lodgement_match?: boolean;
  expected_activity_match?: boolean;
};

/** Backend: aop_package | profile_change | cash_threshold */
export type CustomerUploadDocumentKind = 'aop_package' | 'profile_change' | 'cash_threshold';

export type CustomerAopUploadMeta = {
  upload_id: string;
  filename: string;
  uploaded_at: string;
  size: number;
  /** When true, metadata is stored in Postgres (aml_customer_aop_upload). */
  persisted?: boolean;
  document_kind?: CustomerUploadDocumentKind;
};

export const customersApi = {
  list: (params?: { page?: number; page_size?: number; q?: string }) => {
    const sp = new URLSearchParams();
    if (params?.page != null) sp.set('page', String(params.page));
    if (params?.page_size != null) sp.set('page_size', String(params.page_size));
    if (params?.q?.trim()) sp.set('q', params.q.trim());
    const qs = sp.toString();
    return request<{
      items: Array<{
        customer_id: string;
        customer_name: string;
        account_number: string;
        account_opened: string;
        line_of_business?: string | null;
        contact_email?: string | null;
        account_holder_type?: 'individual' | 'corporate' | string;
        account_product?: 'savings' | 'current' | string;
        ledger_code?: string | null;
        account_reference?: string | null;
        id_number?: string;
        updated_at?: string | null;
        aop_on_file?: boolean;
        aop_upload_count?: number;
        /** Present when at least one AOP upload exists — use with downloadAopUpload. */
        primary_aop_upload_id?: string;
        primary_aop_filename?: string;
        risk_rating?: 'high' | 'medium' | 'low';
        last_review_date?: string | null;
        next_review_due_at?: string | null;
        review_status?: 'due' | 'reviewed' | 'pending';
        needs_profile_update?: boolean;
        review_recommendations?: string[];
      }>;
      total: number;
      page: number;
      page_size: number;
    }>(`/customers${qs ? `?${qs}` : ''}`);
  },
  create: (body: {
    customer_id?: string | null;
    customer_name: string;
    account_number: string;
    account_opened: string;
    customer_address: string;
    line_of_business: string;
    phone_number?: string;
    date_of_birth: string;
    id_number: string;
  }) =>
    request<{ customer_id: string; kyc: CustomerKycDto }>('/customers', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  get: (customerId: string) =>
    request<{
      customer_id: string;
      kyc: CustomerKycDto;
      aop_uploads?: CustomerAopUploadMeta[];
      risk_reviews?: CustomerRiskReview[];
      account_profile?: {
        customer_name?: string;
        account_holder_type?: string;
        account_product?: string;
        ledger_code?: string;
        account_reference?: string | null;
        line_of_business?: string;
      };
      linked_companies?: Array<{
        company_customer_id: string;
        company_name: string;
        company_account_number: string;
        relationship_role: string;
      }>;
    }>(`/customers/${encodeURIComponent(customerId)}`),
  submitRiskReview: (
    customerId: string,
    body: {
      last_review_date: string;
      risk_rating: 'high' | 'medium' | 'low';
      id_card_expiry_date?: string | null;
      expected_turnover_match: boolean;
      expected_lodgement_match: boolean;
      expected_activity_match: boolean;
      pep_flag: boolean;
      account_update_within_period: boolean;
      management_approval_within_period: boolean;
      profile_changed: boolean;
      age_commensurate: boolean;
      activity_commensurate: boolean;
      recommendation?: string;
      send_edd_request?: boolean;
      checklist?: Record<string, unknown>;
    }
  ) =>
    request<{ customer_id: string; review: CustomerRiskReview }>(
      `/customers/${encodeURIComponent(customerId)}/risk-review`,
      { method: 'POST', body: JSON.stringify(body) }
    ),
  listDueRiskReviews: (params?: { days_ahead?: number; limit?: number }) => {
    const sp = new URLSearchParams();
    if (params?.days_ahead != null) sp.set('days_ahead', String(params.days_ahead));
    if (params?.limit != null) sp.set('limit', String(params.limit));
    const qs = sp.toString();
    return request<{ items: Array<Record<string, unknown>>; as_of: string; days_ahead: number }>(
      `/customers/risk-reviews/due${qs ? `?${qs}` : ''}`
    );
  },
  sendDueRiskReviewAlerts: (body: {
    customer_ids?: string[];
    cco_email?: string;
    relationship_manager_email?: string;
    mode?: 'individual' | 'bulk';
  }) =>
    request<{
      status: string;
      sent: Array<{ customer_id: string; recipient_email: string; recipient_role: string; log_id: string }>;
      failures: Array<{ customer_id: string; recipient_email: string; error: string }>;
    }>('/customers/risk-reviews/alerts/send', { method: 'POST', body: JSON.stringify(body) }),
  autoReviewAll: (body?: { only_due?: boolean; limit?: number }) =>
    request<{ status: string; processed: number; skipped: number; only_due: boolean }>(
      '/customers/risk-reviews/review-all',
      { method: 'POST', body: JSON.stringify(body ?? {}) }
    ),
  getReviewRules: () =>
    request<{
      rules: {
        high_months: number;
        medium_months: number;
        low_months: number;
        student_monthly_turnover_recommend_corporate_ngn: number;
        id_expiry_warning_days: number;
        require_additional_docs_when_monthly_turnover_above_ngn: number;
      };
    }>('/customers/admin/review-rules'),
  putReviewRules: (body: {
    high_months: number;
    medium_months: number;
    low_months: number;
    student_monthly_turnover_recommend_corporate_ngn: number;
    id_expiry_warning_days: number;
    require_additional_docs_when_monthly_turnover_above_ngn: number;
  }) =>
    request<{
      status: string;
      rules: {
        high_months: number;
        medium_months: number;
        low_months: number;
        student_monthly_turnover_recommend_corporate_ngn: number;
        id_expiry_warning_days: number;
        require_additional_docs_when_monthly_turnover_above_ngn: number;
      };
    }>('/customers/admin/review-rules', { method: 'PUT', body: JSON.stringify(body) }),
  relatedAccounts: (customerId: string) =>
    request<{
      primary_customer_id: string;
      customer_name: string;
      total_accounts: number;
      other_accounts: number;
      items: Array<{
        customer_id: string;
        customer_name: string;
        account_number: string;
        id_number?: string | null;
        updated_at?: string | null;
        account_holder_type?: 'individual' | 'corporate' | string;
        account_product?: 'savings' | 'current' | string;
        ledger_code?: string | null;
        account_reference?: string | null;
      }>;
    }>(`/customers/${encodeURIComponent(customerId)}/related-accounts`),
  patch: (customerId: string, body: Partial<CustomerKycDto>) =>
    request<{ customer_id: string; kyc: CustomerKycDto }>(`/customers/${encodeURIComponent(customerId)}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  generateAop: (
    customerId: string,
    body?: { account_product?: string; risk_rating?: string; use_llm?: boolean }
  ) =>
    request<{ report_id: string; xml_preview: string | null; validation_passed: boolean }>(
      `/customers/${encodeURIComponent(customerId)}/aop/generate`,
      { method: 'POST', body: JSON.stringify(body ?? {}) }
    ),
  async uploadAopForm(
    customerId: string,
    file: File,
    documentKind: CustomerUploadDocumentKind = 'aop_package',
  ): Promise<CustomerAopUploadMeta> {
    const url = `${BASE.replace(/\/$/, '')}/customers/${encodeURIComponent(customerId)}/aop-upload`;
    const token = getBearerToken();
    const fd = new FormData();
    fd.append('file', file);
    fd.append('document_kind', documentKind);
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(url, { method: 'POST', body: fd, headers });
    if (!res.ok) throw new Error(await parseErrorMessage(res));
    return res.json() as Promise<CustomerAopUploadMeta>;
  },
  async downloadAopUpload(customerId: string, uploadId: string, fallbackFilename: string) {
    const url = `${BASE.replace(/\/$/, '')}/customers/${encodeURIComponent(customerId)}/aop-upload/${encodeURIComponent(uploadId)}/download`;
    const token = getBearerToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(url, { headers });
    if (!res.ok) throw new Error(await parseErrorMessage(res));
    const blob = await res.blob();
    const disposition = res.headers.get('Content-Disposition');
    const filename =
      disposition?.match(/filename="?([^";]+)"?/)?.[1] || fallbackFilename;
    downloadBlob(blob, filename);
  },
  async downloadCustomerStatement(customerId: string, params?: { period_start?: string; period_end?: string }) {
    const q = new URLSearchParams();
    if (params?.period_start) q.set('period_start', params.period_start);
    if (params?.period_end) q.set('period_end', params.period_end);
    const qs = q.toString();
    const url = `${BASE.replace(/\/$/, '')}/customers/${encodeURIComponent(customerId)}/statement/download${qs ? `?${qs}` : ''}`;
    const token = getBearerToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(url, { headers });
    if (!res.ok) throw new Error(await parseErrorMessage(res));
    const blob = await res.blob();
    const disposition = res.headers.get('Content-Disposition');
    const filename = disposition?.match(/filename="?([^";]+)"?/)?.[1] || `SOA_${customerId}.docx`;
    downloadBlob(blob, filename);
  },
  /**
   * Merge customer uploads into one PDF.
   * @param scope all | otc_estr_supporting (profile + cash evidence, excludes AOP package) | aop_package
   */
  async downloadSupportingDocumentsBundle(
    customerId: string,
    scope: 'all' | 'otc_estr_supporting' | 'aop_package' = 'all',
  ) {
    const sp = new URLSearchParams();
    sp.set('scope', scope);
    const url = `${BASE.replace(/\/$/, '')}/customers/${encodeURIComponent(customerId)}/aop-upload/bundle?${sp.toString()}`;
    const token = getBearerToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(url, { headers });
    if (!res.ok) throw new Error(await parseErrorMessage(res));
    const blob = await res.blob();
    const disposition = res.headers.get('Content-Disposition');
    const filename =
      disposition?.match(/filename="?([^";]+)"?/)?.[1] || `${customerId}-supporting-doc.pdf`;
    downloadBlob(blob, filename);
  },
  walkIn: (
    customerId: string,
    body: {
      direction: 'deposit' | 'withdrawal';
      amount: number;
      currency?: string;
      narrative?: string | null;
    }
  ) =>
    request<{
      id: string;
      customer_id: string;
      amount: number;
      currency: string;
      transaction_type: string;
      narrative?: string | null;
      risk_score?: number;
      alert_id?: string | null;
      created_at: string;
    }>(`/customers/${encodeURIComponent(customerId)}/walk-in-transaction`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
};

export type Alert = {
  id: string;
  transaction_id: string;
  customer_id: string;
  customer_name?: string | null;
  severity: number;
  status: string;
  rule_ids?: string[];
  summary?: string;
  last_resolution?: string | null;
  cco_str_approved?: boolean;
  /** CCO rejected this alert; see cco_str_rejection_reason and status rejected. */
  cco_str_rejected?: boolean;
  cco_str_rejection_reason?: string | null;
  escalation_classification?: string | null;
  escalation_reason_notes?: string | null;
  otc_filing_reason?: string | null;
  otc_filing_reason_detail?: string | null;
  otc_outcome?: 'false_positive' | 'true_positive' | null;
  otc_subject?: string | null;
  otc_officer_rationale?: string | null;
  otc_report_kind?: 'otc_estr' | 'otc_esar' | null;
  cco_otc_approved?: boolean;
  /** Legacy: optional CCO ESTR Word flag (no longer used for gating; retained for old demo data). */
  cco_estr_word_approved?: boolean;
  otc_submitted_at?: string | null;
  linked_transaction_type?: string | null;
  linked_channel?: string | null;
  walk_in_otc?: boolean;
  primary_account_number?: string | null;
  linked_accounts_count?: number;
  linked_accounts?: Array<{
    customer_id?: string;
    customer_name?: string | null;
    account_number?: string | null;
    bvn?: string | null;
  }>;
  related_transactions?: Array<{
    transaction_id?: string;
    customer_id?: string;
    transaction_type?: string;
    amount?: number;
    currency?: string;
    from_account?: string | null;
    to_account?: string | null;
    narrative?: string | null;
    channel?: string | null;
    created_at?: string | null;
    seeded_by_alert?: boolean;
  }>;
  investigation_history?: Array<Record<string, unknown>>;
  created_at: string;
  updated_at?: string;
};

export type ClosedCaseReviewItem = {
  id: string;
  alert_id: string;
  review_period_start: string;
  review_period_end: string;
  sample_type: string;
  reviewer_id?: string | null;
  review_status: string;
  findings?: string | null;
  pattern_identified?: string | null;
  recommendation_tuning?: string | null;
  requires_reopen?: boolean;
  reopened_alert_id?: string | null;
  reviewed_at?: string | null;
  created_at?: string;
  alert?: Alert | null;
};

export type AlertsDashboard = {
  counts_by_severity: { low: number; medium: number; high: number; critical: number };
  counts_by_status: Record<string, number>;
  trend_over_time: Array<{ date: string; critical: number; high: number; medium: number; low: number }>;
  average_resolution_time_hours?: number | null;
  /** Non-closed alerts by age since creation (hours). */
  open_case_ageing?: { lt_24h: number; d1_3: number; d3_7: number; gt_7d: number };
  outcome_summary?: {
    closed_false_positive: number;
    closed_other: number;
    escalated: number;
    investigating: number;
    open: number;
    rejected?: number;
  };
  otc_outcome_counts?: { true_positive: number; false_positive: number; not_filed: number };
  closed_cases_in_avg_sample?: number;
  pending_cco_str_approvals?: number;
  pending_cco_otc_approvals?: number;
  pending_cco_estr_word_approvals?: number;
  /** In-app inbox for compliance (e.g. CCO rejection) scoped to signed-in user email. */
  co_notifications_unread?: Array<{
    id?: string;
    kind?: string;
    alert_id?: string;
    summary?: string;
    reason?: string;
    cco_name?: string;
    at?: string;
    read?: boolean;
  }>;
};

export const alertsApi = {
  list: (params: {
    skip?: number;
    limit?: number;
    status?: string;
    severity?: string;
    sort?: 'risk' | 'newest';
    /** Cash / walk-in OTC and alerts already in OTC workflow */
    queue?: 'core' | 'otc_estr' | 'otc_esar';
  }) => {
    const skip = params.skip ?? 0;
    const limit = params.limit ?? 20;
    const sp = new URLSearchParams({ skip: String(skip), limit: String(limit) });
    if (params.status) sp.set('status', params.status);
    if (params.severity) sp.set('severity', params.severity);
    if (params.sort) sp.set('sort', params.sort);
    if (params.queue) sp.set('queue', params.queue);
    return request<{ items: Alert[]; total: number; skip: number; limit: number }>(`/alerts/?${sp.toString()}`);
  },
  search: (params: {
    q: string;
    skip?: number;
    limit?: number;
    status?: string;
    severity?: string;
    sort?: 'risk' | 'newest';
    queue?: 'core' | 'otc_estr' | 'otc_esar';
  }) => {
    const skip = params.skip ?? 0;
    const limit = params.limit ?? 20;
    const sp = new URLSearchParams({
      q: params.q,
      skip: String(skip),
      limit: String(limit),
    });
    if (params.status) sp.set('status', params.status);
    if (params.severity) sp.set('severity', params.severity);
    if (params.sort) sp.set('sort', params.sort);
    if (params.queue) sp.set('queue', params.queue);
    return request<{ items: Alert[]; total: number; skip: number; limit: number }>(
      `/alerts/search?${sp.toString()}`
    );
  },
  getDashboard: () => request<AlertsDashboard>('/alerts/dashboard'),
  markCoNotificationsRead: (body?: { notification_ids?: string[] | null }) =>
    request<{ marked_read: number; email: string }>('/alerts/co-notifications/mark-read', {
      method: 'POST',
      body: JSON.stringify(body ?? {}),
    }),
  async exportMiCsv() {
    const url = `${BASE.replace(/\/$/, '')}/alerts/dashboard/mi-export`;
    const token = getBearerToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(url, { headers });
    if (!res.ok) throw new Error(await parseErrorMessage(res));
    const blob = await res.blob();
    downloadBlob(blob, 'alert_mi_summary.csv');
  },
  get: (id: string) => request<Alert>(`/alerts/${id}`),
  /** Demo/QA: status → open; clears STR/CCO escalation flags; keeps transaction & OTC filing data. */
  resetWorkflow: (alertId: string) =>
    request<{ alert_id: string; status: string; action_key: string }>(
      `/alerts/${encodeURIComponent(alertId)}/reset-workflow`,
      { method: 'POST' }
    ),
  investigate: (alertId: string, body: { investigator_id: string; notes?: string }) =>
    request<{ alert_id: string; status: string; investigator_id: string; action_key: string }>(`/alerts/${alertId}/investigate`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  resolve: (alertId: string, body: { resolution: 'false_positive'; notes: string; action_taken?: string }) =>
    request<{ alert_id: string; resolution: string; status: string; action_key: string }>(`/alerts/${alertId}/resolve`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  escalate: (
    alertId: string,
    body: {
      escalated_to: string;
      escalation_type: 'true_positive' | 'cco_review';
      reason?: string;
    }
  ) =>
    request<{
      alert_id: string;
      status: string;
      escalated_to: string;
      escalation_type: string;
      cco_str_approved: boolean;
      cco_otc_approved?: boolean;
      cco_email_notified?: boolean;
      cco_notification_detail?: string;
      action_key: string;
    }>(`/alerts/${alertId}/escalate`, {
      method: 'POST',
      body: JSON.stringify({
        escalated_to: body.escalated_to,
        escalation_type: body.escalation_type,
        reason: body.reason ?? '',
      }),
    }),
  listCcoPendingStrApprovals: (params?: { skip?: number; limit?: number }) => {
    const skip = params?.skip ?? 0;
    const limit = params?.limit ?? 100;
    return request<{ items: Alert[]; total: number; skip: number; limit: number }>(
      `/alerts/cco/pending-str-approvals?skip=${skip}&limit=${limit}`
    );
  },
  ccoApproveStr: (alertId: string, body?: { notes?: string }) =>
    request<{
      alert_id: string;
      status: string;
      cco_str_approved: boolean;
      str_draft_report_id?: string | null;
      action_key: string;
    }>(`/alerts/${encodeURIComponent(alertId)}/cco-approve-str`, {
      method: 'POST',
      body: JSON.stringify(body ?? {}),
    }),
  ccoReject: (alertId: string, body: { reason: string }) =>
    request<{
      alert_id: string;
      status: string;
      cco_str_rejected: boolean;
      cco_str_rejection_reason?: string;
      co_notified_email?: string | null;
      email_sent?: boolean;
      email_detail?: string;
      notification_id?: string | null;
      action_key: string;
    }>(`/alerts/${encodeURIComponent(alertId)}/cco-reject`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  listCcoPendingOtcApprovals: (params?: { skip?: number; limit?: number }) => {
    const skip = params?.skip ?? 0;
    const limit = params?.limit ?? 100;
    return request<{ items: Alert[]; total: number; skip: number; limit: number }>(
      `/alerts/cco/pending-otc-approvals?skip=${skip}&limit=${limit}`
    );
  },
  submitOtcReport: (
    alertId: string,
    body: {
      filing_reason: string;
      filing_reason_detail?: string;
      outcome: 'false_positive' | 'true_positive';
      subject: string;
      officer_rationale?: string;
    }
  ) =>
    request<{
      alert_id: string;
      otc_outcome: string | null;
      otc_report_kind: string | null;
      cco_otc_approved: boolean;
      action_key: string;
    }>(`/alerts/${encodeURIComponent(alertId)}/otc-report`, { method: 'POST', body: JSON.stringify(body) }),
  ccoApproveOtc: (alertId: string, body?: { notes?: string }) =>
    request<{
      alert_id: string;
      cco_otc_approved: boolean;
      otc_report_kind: string | null;
      cco_estr_word_approved?: boolean;
      estr_draft_report_id?: string | null;
      otc_draft_report_id?: string | null;
      action_key: string;
    }>(`/alerts/${encodeURIComponent(alertId)}/cco-approve-otc`, {
      method: 'POST',
      body: JSON.stringify(body ?? {}),
    }),
  /** Pre-resolution AML snapshot: transaction, customer, BVN-linked accounts, windows, typologies, screening. */
  getSnapshot: (alertId: string) =>
    request<Record<string, unknown>>(`/alerts/${encodeURIComponent(alertId)}/snapshot`),
  notifyEdd: (
    alertId: string,
    body: {
      customer_email: string;
      customer_name?: string;
      compliance_action?: 'investigate' | 'resolve' | 'escalate';
      investigator_id?: string;
      investigation_notes?: string;
      resolution?: 'true_positive' | 'false_positive';
      resolution_notes?: string;
      escalate_reason?: string;
      escalated_to?: string;
      additional_note?: string;
    }
  ) =>
    request<{ status: string; to: string; type: string; compliance_action?: string }>(
      `/alerts/${encodeURIComponent(alertId)}/notify/edd`,
      {
        method: 'POST',
        body: JSON.stringify(body),
      }
    ),
  notifyCco: (
    alertId: string,
    body: {
      action: 'investigate' | 'resolve' | 'escalate';
      investigator_id?: string;
      investigation_notes?: string;
      resolution?: 'true_positive' | 'false_positive';
      resolution_notes?: string;
      escalate_reason?: string;
      escalated_to?: string;
      additional_note?: string;
      extra_recipients?: string[];
    }
  ) =>
    request<{ status: string; to: string; type: string; action: string }>(
      `/alerts/${encodeURIComponent(alertId)}/notify/cco`,
      {
        method: 'POST',
        body: JSON.stringify(body),
      }
    ),
};

export const complianceApi = {
  referenceJurisdictions: () =>
    request<{ source: string; disclaimer: string; jurisdictions: Array<{ jurisdiction: string; note: string }> }>(
      '/compliance/sanctions/reference-jurisdictions'
    ),
  screenSanctions: (name: string) =>
    request<Record<string, unknown>>(`/compliance/sanctions/screen?name=${encodeURIComponent(name)}`),
  closedCasePatterns: () =>
    request<{ items: Array<{ id: string; label: string }> }>('/compliance/closed-case-reviews/patterns'),
  generateClosedCaseReviews: (body: {
    review_period_start: string;
    review_period_end: string;
    sample_type?: string;
    force?: boolean;
  }) =>
    request<Record<string, unknown>>('/compliance/closed-case-reviews/generate', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  listClosedCaseReviews: (params?: { status?: string; reviewer_id?: string; skip?: number; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.status) q.set('status', params.status);
    if (params?.reviewer_id) q.set('reviewer_id', params.reviewer_id);
    if (params?.skip != null) q.set('skip', String(params.skip));
    if (params?.limit != null) q.set('limit', String(params.limit));
    const qs = q.toString();
    return request<{ items: ClosedCaseReviewItem[]; total: number; skip: number; limit: number }>(
      `/compliance/closed-case-reviews${qs ? `?${qs}` : ''}`
    );
  },
  putClosedCaseReview: (
    id: string,
    body: {
      findings: string;
      pattern_identified?: string | null;
      recommendation_tuning?: string | null;
      requires_reopen?: boolean;
      notify_cco?: boolean;
    }
  ) =>
    request<{ status: string; review: Record<string, unknown>; reopened_alert_id?: string | null }>(
      `/compliance/closed-case-reviews/${encodeURIComponent(id)}`,
      { method: 'PUT', body: JSON.stringify(body) }
    ),
  closedCaseTuningProposals: (limit = 100) =>
    request<{
      aggregated_by_pattern: Array<Record<string, unknown>>;
      recent_recommendations: Array<Record<string, unknown>>;
    }>(`/compliance/closed-case-reviews/tuning-proposals?limit=${limit}`),
};

export const reportsApi = {
  listStrEligibleAlerts: (limit = 500) =>
    request<{ items: Alert[]; total: number }>(`/reports/str/eligible-alerts?limit=${limit}`),
  generateSTR: (body: {
    alert_id: string;
    str_notes: string;
    additional_context?: Record<string, unknown>;
    include_aop?: boolean;
    generate_aop?: boolean;
    aop_account_product?: string;
    aop_risk_rating?: string;
    include_soa?: boolean;
    generate_statement_of_account?: boolean;
    statement_period_start?: string;
    statement_period_end?: string;
    use_saved_draft?: boolean;
  }) =>
    request<{
      report_id: string;
      xml_preview: string | null;
      validation_passed: boolean;
      aop_report_id?: string;
      soa_report_id?: string;
      soa_period_start?: string;
      soa_period_end?: string;
    }>('/reports/str/generate', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  generateSTRBulk: (body: {
    alert_ids: string[];
    str_notes: string;
    include_aop?: boolean;
    generate_aop?: boolean;
    aop_account_product?: string;
    aop_risk_rating?: string;
    include_soa?: boolean;
    generate_statement_of_account?: boolean;
    statement_period_start?: string;
    statement_period_end?: string;
    use_saved_draft?: boolean;
  }) =>
    request<{
      results: Array<
        | {
            alert_id: string;
            ok: true;
            report_id: string;
            xml_preview: string | null;
            validation_passed: boolean;
            aop_report_id?: string;
            soa_report_id?: string;
            soa_period_start?: string;
            soa_period_end?: string;
            soa_error?: string;
          }
        | { alert_id: string; ok: false; error?: string }
      >;
      generated: number;
      requested: number;
    }>('/reports/str/generate-bulk', { method: 'POST', body: JSON.stringify(body) }),
  getSTRDraftPreview: (alertId: string) =>
    request<{
      alert_id: string;
      str_notes: string;
      has_saved_draft: boolean;
      word_preview_lines: string[];
    }>(`/reports/str/draft/${encodeURIComponent(alertId)}`),
  saveSTRDraft: (alertId: string, body: { str_notes: string }) =>
    request<{ status: string; alert_id: string; str_notes: string }>(
      `/reports/str/draft/${encodeURIComponent(alertId)}`,
      { method: 'POST', body: JSON.stringify(body) }
    ),
  strDraftStatusBulk: (alertIds: string[]) =>
    request<{ items: Record<string, boolean> }>('/reports/str/draft/status', {
      method: 'POST',
      body: JSON.stringify({ alert_ids: alertIds }),
    }),
  getOtcWordDraftPreview: (alertId: string) =>
    request<{
      alert_id: string;
      estr_notes: string;
      has_saved_draft: boolean;
      otc_report_kind?: string | null;
      word_preview_lines: string[];
      preview_warning?: string;
    }>(`/reports/otc-word/draft/${encodeURIComponent(alertId)}`),
  saveOtcWordDraft: (alertId: string, body: { estr_notes: string }) =>
    request<{ status: string; alert_id: string; estr_notes: string }>(
      `/reports/otc-word/draft/${encodeURIComponent(alertId)}`,
      { method: 'POST', body: JSON.stringify(body) }
    ),
  otcWordDraftStatusBulk: (alertIds: string[]) =>
    request<{ items: Record<string, boolean> }>('/reports/otc-word/draft/status', {
      method: 'POST',
      body: JSON.stringify({ alert_ids: alertIds }),
    }),
  async downloadOtcWordDraftPreview(alertId: string) {
    const url = `${BASE.replace(/\/$/, '')}/reports/otc-word/draft/${encodeURIComponent(alertId)}/download`;
    const token = getBearerToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(url, { headers });
    if (!res.ok) throw new Error(res.statusText);
    const blob = await res.blob();
    const disposition = res.headers.get('Content-Disposition');
    const filename =
      disposition?.match(/filename="?([^";]+)"?/)?.[1] || `OTC-Word-Draft-${alertId.slice(0, 8)}.docx`;
    downloadBlob(blob, filename);
  },
  async downloadSTRDraftPreview(alertId: string) {
    const url = `${BASE.replace(/\/$/, '')}/reports/str/draft/${encodeURIComponent(alertId)}/download`;
    const token = getBearerToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(url, { headers });
    if (!res.ok) throw new Error(res.statusText);
    const blob = await res.blob();
    const disposition = res.headers.get('Content-Disposition');
    const filename =
      disposition?.match(/filename="?([^";]+)"?/)?.[1] || `STR-Draft-Preview-${alertId.slice(0, 8)}.docx`;
    downloadBlob(blob, filename);
  },
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
  generateSAR: (body: {
    alert_id?: string;
    customer_id?: string;
    transaction_id?: string;
    sar_notes?: string;
    notes?: string;
    use_saved_draft?: boolean;
    /** When true, narrative may reference US-person / USD nexus when plausible (demo). Default off if omitted. */
    us_activity?: boolean;
  }) =>
    request<{
      report_id: string;
      xml_preview: string | null;
      validation_passed: boolean;
      narrative_source?: string;
      activity_basis?: string;
    }>('/reports/sar/generate', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  listSarEligibleAlerts: (limit = 500) =>
    request<{
      items: Array<{
        alert_id: string;
        customer_id: string;
        customer_name?: string | null;
        linked_channel?: string | null;
        transaction_id: string;
        summary?: string | null;
        severity: number;
        updated_at?: string | null;
      }>;
      total: number;
    }>(`/reports/sar/eligible-alerts?limit=${limit}`),

  listOtcEligibleAlerts: (kind: 'estr' | 'esar', limit = 500) =>
    request<{
      items: Array<{
        alert_id: string;
        customer_id: string;
        customer_name?: string | null;
        linked_channel?: string | null;
        transaction_id: string;
        summary?: string | null;
        otc_subject?: string | null;
        otc_report_kind?: string | null;
        severity: number;
        updated_at?: string | null;
      }>;
      total: number;
      kind: string;
    }>(`/reports/otc/eligible-alerts?kind=${kind}&limit=${limit}`),

  generateSARBulk: (body: {
    alert_ids?: string[];
    limit?: number;
    sar_notes?: string;
    notes?: string;
    use_saved_draft?: boolean;
    /** Default off if omitted. */
    us_activity?: boolean;
  }) =>
    request<{
      results: Array<
        | {
            alert_id: string;
            ok: true;
            report_id: string;
            xml_preview: string | null;
            validation_passed: boolean;
            narrative_source?: string;
            activity_basis?: string;
          }
        | { alert_id: string; ok: false; error?: string }
      >;
      generated: number;
      requested: number;
    }>('/reports/sar/generate-bulk', { method: 'POST', body: JSON.stringify(body) }),
  generateAOP: (body: { customer_id: string; account_product?: string; risk_rating?: string }) =>
    request<{ report_id: string; xml_preview: string | null; validation_passed: boolean }>('/reports/aop/generate', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  generateESTR: (body: { alert_id?: string; estr_notes?: string; notes?: string; use_saved_draft?: boolean }) =>
    request<{ report_id: string; xml_preview: string | null; validation_passed: boolean }>('/reports/estr/generate', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  generateESTRBulk: (body: {
    alert_ids?: string[];
    limit?: number;
    estr_notes?: string;
    notes?: string;
    use_saved_draft?: boolean;
  }) =>
    request<{
      results: Array<
        | {
            alert_id: string;
            ok: true;
            report_id: string;
            xml_preview: string | null;
            validation_passed: boolean;
          }
        | { alert_id: string; ok: false; error?: string }
      >;
      generated: number;
      requested: number;
    }>('/reports/estr/generate-bulk', { method: 'POST', body: JSON.stringify(body) }),
  generateNfiuCustomerChange: (body: Record<string, unknown>) =>
    request<{ report_id: string; xml_preview: string | null; validation_passed: boolean; change_type: string }>(
      '/reports/nfiu/customer-change/generate',
      { method: 'POST', body: JSON.stringify(body) }
    ),
  async downloadSAR(reportId: string, format: 'word' | 'xml') {
    await downloadRegulatoryFile(`/reports/sar/${encodeURIComponent(reportId)}/download?format=${format}`, reportId, format);
  },
  /** Account opening package for the customer — PDF only (no Word/XML). */
  async downloadAOP(reportId: string) {
    await downloadRegulatoryFile(
      `/reports/aop/${encodeURIComponent(reportId)}/download?format=pdf`,
      reportId,
      'pdf',
    );
  },
  /** Statement of account — Word (.docx) only; XML is not supported by the API. */
  async downloadSOA(reportId: string) {
    const format = 'word' as const;
    await downloadRegulatoryFile(
      `/reports/soa/${encodeURIComponent(reportId)}/download?format=${format}`,
      reportId,
      format,
    );
  },
  async downloadESTR(reportId: string, format: 'word' | 'xml') {
    await downloadRegulatoryFile(`/reports/estr/${encodeURIComponent(reportId)}/download?format=${format}`, reportId, format);
  },
  async downloadNfiu(reportId: string, format: 'word' | 'xml') {
    await downloadRegulatoryFile(`/reports/nfiu/${encodeURIComponent(reportId)}/download?format=${format}`, reportId, format);
  },

  /** CBN Funds Transfer Report (FTR) — wire / remittance over threshold. */
  listFtr: (params?: { from_date?: string; to_date?: string; status?: string; skip?: number; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.from_date) q.set('from_date', params.from_date);
    if (params?.to_date) q.set('to_date', params.to_date);
    if (params?.status) q.set('status', params.status);
    if (params?.skip != null) q.set('skip', String(params.skip));
    if (params?.limit != null) q.set('limit', String(params.limit));
    const qs = q.toString();
    return request<{
      items: Record<string, unknown>[];
      total: number;
      skip: number;
      limit: number;
      retention_years?: number;
    }>(`/reports/ftr${qs ? `?${qs}` : ''}`);
  },
  getFtr: (id: string) =>
    request<{
      ftr: Record<string, unknown>;
      sample_template_xml?: string;
      retention_years?: number;
      retention_note?: string;
      download_formats?: string[];
    }>(`/reports/ftr/${encodeURIComponent(id)}`),
  generateFtr: (transactionId: string, force?: boolean) =>
    request<{ status: string; ftr: Record<string, unknown>; retention_years?: number }>(
      `/reports/ftr/generate/${encodeURIComponent(transactionId)}${force ? '?force=true' : ''}`,
      { method: 'POST' }
    ),
  patchFtrDraft: (id: string, body: Record<string, unknown>) =>
    request<{ status: string; ftr: Record<string, unknown> }>(`/reports/ftr/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  submitFtr: (id: string) =>
    request<{ status: string; ftr: Record<string, unknown> }>(`/reports/ftr/${encodeURIComponent(id)}/submit`, {
      method: 'POST',
    }),
  getFtrSchedule: () =>
    request<Record<string, unknown>>('/reports/ftr/schedule'),
  postFtrSchedule: (body: Record<string, unknown>) =>
    request<{ status: string; schedule: Record<string, unknown> }>('/reports/ftr/schedule', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  runFtrScan: () => request<Record<string, unknown>>('/reports/ftr/scan/run', { method: 'POST' }),
  async downloadFtrFile(id: string, format: 'xml' | 'csv' | 'docx' = 'xml') {
    const url = `${BASE.replace(/\/$/, '')}/reports/ftr/${encodeURIComponent(id)}/file?format=${format}`;
    const token = getBearerToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(url, { headers });
    if (!res.ok) throw new Error(await parseErrorMessage(res));
    const blob = await res.blob();
    const disposition = res.headers.get('Content-Disposition');
    const ext = format === 'docx' ? 'docx' : format;
    const filename =
      disposition?.match(/filename="?([^";]+)"?/)?.[1] || `ftr-${id.slice(0, 8)}.${ext}`;
    downloadBlob(blob, filename);
  },
};

export type LeaRequestRecord = {
  id: string;
  status: string;
  customer_id: string;
  agency: string;
  period_start: string;
  period_end: string;
  account_opened_kyc?: string;
  account_context_start?: string;
  recipient_email: string;
  include_aop: boolean;
  workstation_mac?: string;
  internal_notes?: string;
  requester_ip?: string;
  client_public_ip?: string | null;
  created_at?: string;
  cco_notified_at?: string;
  approved_by?: string | null;
  approved_at?: string | null;
  cco_notes?: string;
  aop_report_id?: string | null;
  sent_at?: string | null;
  transaction_rows_sent?: number;
  email_subject_override?: string;
  email_body_override?: string;
};

export type LeaPreview = {
  customer_id: string;
  customer_name?: string | null;
  account_number?: string | null;
  recipient_email: string;
  period_start: string;
  period_end: string;
  account_opened_kyc?: string;
  include_aop: boolean;
  aop_on_file?: boolean;
  statement_generated: boolean;
  statement_rows: number;
  attachments: Array<{ name: string; kind: string; generated: boolean; rows?: number; on_file?: boolean }>;
  email_subject: string;
  email_body: string;
  internal_notes?: string;
};

export const leaApi = {
  agencies: () => request<{ agencies: string[] }>('/lea/agencies'),
  createRequest: (body: {
    customer_id: string;
    agency: string;
    recipient_email: string;
    period_start?: string;
    period_end?: string;
    include_aop?: boolean;
    workstation_mac?: string;
    internal_notes?: string;
    client_public_ip?: string;
    email_subject_override?: string;
    email_body_override?: string;
    submit_for_cco?: boolean;
  }) =>
    request<LeaRequestRecord>('/lea/requests', { method: 'POST', body: JSON.stringify(body) }),
  preview: (body: {
    customer_id: string;
    agency: string;
    recipient_email: string;
    period_start?: string;
    period_end?: string;
    include_aop?: boolean;
    workstation_mac?: string;
    internal_notes?: string;
    client_public_ip?: string;
    email_subject_override?: string;
    email_body_override?: string;
  }) => request<LeaPreview>('/lea/preview', { method: 'POST', body: JSON.stringify(body) }),
  getRequest: (id: string) => request<LeaRequestRecord>(`/lea/requests/${encodeURIComponent(id)}`),
  pendingCco: () => request<{ items: LeaRequestRecord[] }>('/lea/requests/pending-cco'),
  notifyCco: (id: string) =>
    request<LeaRequestRecord>(`/lea/requests/${encodeURIComponent(id)}/notify-cco`, { method: 'POST' }),
  ccoApprove: (id: string, body?: { notes?: string }) =>
    request<LeaRequestRecord>(`/lea/requests/${encodeURIComponent(id)}/cco-approve`, {
      method: 'POST',
      body: JSON.stringify(body ?? {}),
    }),
  sendPackage: (id: string, body?: { email_subject_override?: string; email_body_override?: string }) =>
    request<LeaRequestRecord>(`/lea/requests/${encodeURIComponent(id)}/send`, {
      method: 'POST',
      body: JSON.stringify(body ?? {}),
    }),
};

async function downloadRegulatoryFile(path: string, reportId: string, format: 'word' | 'xml' | 'pdf') {
  const url = `${BASE.replace(/\/$/, '')}${path}`;
  const token = getBearerToken();
  const headers: Record<string, string> = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(url, { headers });
  if (!res.ok) throw new Error(res.statusText);
  const blob = await res.blob();
  const disposition = res.headers.get('Content-Disposition');
  const ext = format === 'word' ? 'docx' : format === 'pdf' ? 'pdf' : 'xml';
  const filename = disposition?.match(/filename="?([^";]+)"?/)?.[1] || `${reportId}.${ext}`;
  downloadBlob(blob, filename);
}

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

export type ShowcaseSeedResult = {
  seeded_transactions: number;
  transaction_ids: string[];
  showcase_cases: string[];
  note?: string;
  replaced?: boolean;
};

/** Result of loading the fixed 10-row branch STR / OTC intake table (ESTR + ESAR tracks). */
export type OtcBranchSeedResult = {
  seed: string;
  rows: number;
  alert_ids: string[];
  transaction_ids: string[];
  otc_estr_alert_ids: string[];
  otc_esar_alert_ids: string[];
  cco_pre_approved: boolean;
  note?: string;
  replaced?: boolean;
};

export type StatementBulkSeedResult = {
  routine_transactions: number;
  suspicious_outflow_transactions: number;
  scenario_customers: string[];
  total_customers_in_pool: number;
  transaction_ids: string[];
  seed: number;
  seeded_transactions: number;
  in_memory_transaction_count?: number;
};

export type MissingAopSeedResult = {
  applied: number;
  skipped: boolean;
  template?: string;
  persisted_to_database?: boolean;
  reason?: string;
};

export type MassCustomerSeedResult = {
  seeded_customers: number;
  customer_ids: string[];
  risky_customer_ids: string[];
  suspicious_transactions: number;
  total_transactions: number;
  transaction_ids: string[];
  seed: number;
  aop_template_seed?: MissingAopSeedResult;
  in_memory_transaction_count?: number;
  alerts_count?: number;
};

export const demoApi = {
  /** Clears in-memory AML data (and optional Postgres KYC) then loads realistic demo scenarios. */
  seed: (body?: { replace_existing?: boolean; clear_postgres_kyc?: boolean }) =>
    request<{ seeded_transactions: number; transaction_ids: string[]; replaced?: boolean }>('/demo/seed', {
      method: 'POST',
      body: JSON.stringify({
        replace_existing: true,
        clear_postgres_kyc: true,
        ...body,
      }),
    }),
  /** One flagship suspicious transaction after optional full clear. */
  ingestFlagship: (body?: { replace_existing?: boolean; clear_postgres_kyc?: boolean }) =>
    request<{ transaction_id: string; replaced?: boolean }>('/demo/ingest-flagship', {
      method: 'POST',
      body: JSON.stringify({
        replace_existing: true,
        clear_postgres_kyc: true,
        ...body,
      }),
    }),
  /**
   * Twelve high-risk typology tracks (PEP, mole, hub fan-out, identical narrations, terror wording,
   * tax evasion, structuring, rapid in/out, crypto, ransom, government embezzlement narrative, SAR composite).
   * Large amounts; target risk band ~80–96% via demo metadata.
   */
  seedShowcase: (body?: { replace_existing?: boolean; clear_postgres_kyc?: boolean }) =>
    request<ShowcaseSeedResult>('/demo/seed-showcase', {
      method: 'POST',
      body: JSON.stringify({
        replace_existing: true,
        clear_postgres_kyc: true,
        ...body,
      }),
    }),
  /**
   * Branch OTC / STR intake spreadsheet (10 rows): cash ESTR + identity ESAR, real-style branches and narratives.
   * Upserts KYC per row so customers appear on the Customers page for AOP upload.
   */
  seedOtcBranchReference: (body?: {
    replace_existing?: boolean;
    clear_postgres_kyc?: boolean;
    cco_pre_approve?: boolean;
  }) =>
    request<OtcBranchSeedResult>('/demo/seed-otc-branch-reference', {
      method: 'POST',
      body: JSON.stringify({
        replace_existing: true,
        clear_postgres_kyc: true,
        cco_pre_approve: false,
        ...body,
      }),
    }),
  /**
   * Add statement-heavy records across all demo customers:
   * NIBSS/NIP, card, POS, USSD, ATM + suspicious outflow dissipation chains for scenario customers.
   */
  seedStatementBulk: (body?: {
    routine_count?: number;
    suspicious_outflows_per_scenario?: number;
    seed?: number;
  }) =>
    request<StatementBulkSeedResult>('/demo/seed-statement-bulk', {
      method: 'POST',
      body: JSON.stringify({
        routine_count: 1550,
        suspicious_outflows_per_scenario: 20,
        seed: 77,
        ...body,
      }),
    }),
  /** Attach AOP template to customers that currently have no AOP file. */
  seedMissingAop: () => request<MissingAopSeedResult>('/demo/seed-missing-aop', { method: 'POST', body: '{}' }),
  /** Large synthetic load: many random customers + mixed rails + suspicious high-risk scenarios. */
  seedMassCustomers: (body?: {
    customer_count?: number;
    risky_customer_count?: number;
    suspicious_per_risky_customer?: number;
    seed?: number;
  }) =>
    request<MassCustomerSeedResult>('/demo/seed-mass-customers', {
      method: 'POST',
      body: JSON.stringify({
        customer_count: 1234,
        risky_customer_count: 104,
        suspicious_per_risky_customer: 500,
        seed: 20260407,
        ...body,
      }),
    }),
  /**
   * One click: clear stores once, then standard AML + showcase + OTC table + AOP templates + 10-year temporal
   * synthetic history (appended). May take 1–2 minutes.
   */
  seedCompleteDemo: () =>
    request<{
      cleared: boolean;
      standard: { seeded_transactions: number; transaction_ids: string[]; replaced?: boolean };
      showcase: ShowcaseSeedResult;
      otc_branch: OtcBranchSeedResult;
      statement_bulk?: StatementBulkSeedResult;
      missing_aop_seed?: MissingAopSeedResult;
      mass_customer_seed?: MassCustomerSeedResult;
      aop_template_seed?: Record<string, unknown>;
      temporal_simulation?: TemporalSimulationResult;
      seeded_transactions_total: number;
      in_memory_transaction_count?: number;
    }>('/demo/seed-complete-demo', { method: 'POST', body: '{}' }),
  /** Standalone: replace in-memory world with 10-year synthetic history only (use seedCompleteDemo for full pack). */
  simulateTemporal: (body?: {
    years?: number;
    seed?: number;
    clear_existing?: boolean;
    clear_postgres_kyc?: boolean;
    max_transactions?: number;
    refit_every?: number;
  }) =>
    request<TemporalSimulationResult>('/demo/simulate-temporal', {
      method: 'POST',
      body: JSON.stringify({
        years: 10,
        seed: 42,
        clear_existing: true,
        clear_postgres_kyc: true,
        max_transactions: 100_000,
        refit_every: 500,
        ...body,
      }),
    }),
  /** Branch OTC reference rows as JSON (same logical sheet as seed-otc-branch-reference). */
  getOtcBranchReferenceTable: () =>
    request<{ rows: Record<string, unknown>[]; count: number }>('/demo/otc-branch-reference-table'),
  /** Multi-sheet .xlsx: OTC reference, standard seed, showcase, flagship, temporal profiles/scenarios (no DB write). */
  async downloadAllSeedDataXlsx() {
    const url = `${BASE.replace(/\/$/, '')}/demo/export-all-seed-data`;
    const token = getBearerToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(url, { headers });
    if (!res.ok) throw new Error(await parseErrorMessage(res));
    const blob = await res.blob();
    const disposition = res.headers.get('Content-Disposition');
    const filename =
      disposition?.match(/filename="?([^";]+)"?/)?.[1] || 'nigeria-aml-demo-seed-data.xlsx';
    downloadBlob(blob, filename);
  },
  /** CSV (UTF-8 BOM) for Excel — demo table **structure** / reference data, not live DB. */
  async downloadOtcBranchReferenceStructureCsv() {
    const url = `${BASE.replace(/\/$/, '')}/demo/otc-branch-reference-table/export?format=csv`;
    const token = getBearerToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(url, { headers });
    if (!res.ok) throw new Error(await parseErrorMessage(res));
    const blob = await res.blob();
    const disposition = res.headers.get('Content-Disposition');
    const filename =
      disposition?.match(/filename="?([^";]+)"?/)?.[1] || 'otc-branch-reference-demo-structure.csv';
    downloadBlob(blob, filename);
  },
};