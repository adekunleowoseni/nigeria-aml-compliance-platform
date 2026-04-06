import { useEffect, useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { alertsApi, customersApi, type Alert } from '../services/api';
import DashboardLayout from '../components/layout/DashboardLayout';
import { useReportActionStore } from '../store/reportActionStore';

/** Sent on every escalation; not shown in the Alert action UI. */
const DEFAULT_ESCALATED_TO = 'Chief Compliance Officer / MLRO';

function isOtcEstrAlert(a: Pick<Alert, 'otc_report_kind'> | null | undefined): boolean {
  return a?.otc_report_kind === 'otc_estr';
}

/** OTC extended returns: supporting PDF excludes AOP package; AOP downloads separately. */
function isOtcExtendedReturnAlert(a: Pick<Alert, 'otc_report_kind'> | null | undefined): boolean {
  return a?.otc_report_kind === 'otc_estr' || a?.otc_report_kind === 'otc_esar';
}

function ccoRejectionMeta(alert: Alert): { rejected_by?: string } {
  const hist = [...(alert.investigation_history ?? [])].reverse();
  const row = hist.find(
    (h) => h && typeof h === 'object' && (h as Record<string, unknown>).action === 'cco_reject',
  ) as Record<string, unknown> | undefined;
  const by = row?.rejected_by;
  return typeof by === 'string' && by.trim() ? { rejected_by: by.trim() } : {};
}

export default function Alerts() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [actionTab, setActionTab] = useState<'investigate' | 'resolve' | 'escalate' | null>(null);
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [investigatorId, setInvestigatorId] = useState('');
  const [investigateNotes, setInvestigateNotes] = useState('');
  const [resolveNotes, setResolveNotes] = useState('');
  const [escalateReason, setEscalateReason] = useState('');
  const [escalationType, setEscalationType] = useState<'true_positive' | 'cco_review'>('cco_review');
  const [eddEmail, setEddEmail] = useState('');
  const [eddName, setEddName] = useState('');
  const [sendEddWithAction, setSendEddWithAction] = useState(false);
  const [notifyCcoWithAction, setNotifyCcoWithAction] = useState(false);
  const [ccoExtraRecipient, setCcoExtraRecipient] = useState('');
  const [workflowBusy, setWorkflowBusy] = useState(false);
  const [otcEstrRefinementNotes, setOtcEstrRefinementNotes] = useState('');
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [riskSortFirst, setRiskSortFirst] = useState(true);
  const [alertsTab, setAlertsTab] = useState<'all' | 'otc_estr'>('all');
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(20);
  const [statusFilter, setStatusFilter] = useState('');
  const [severityFilter, setSeverityFilter] = useState('');
  const setLastAction = useReportActionStore((s) => s.setLastAction);

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedSearch(search.trim()), 250);
    return () => window.clearTimeout(t);
  }, [search]);

  useEffect(() => {
    setPage(0);
  }, [statusFilter, severityFilter, pageSize, debouncedSearch, alertsTab]);

  const skip = page * pageSize;
  const sort = riskSortFirst ? 'risk' : 'newest';
  const queueParam = alertsTab === 'otc_estr' ? ('otc_estr' as const) : undefined;

  const listQuery = useQuery({
    queryKey: ['alerts', 'list', skip, pageSize, statusFilter, severityFilter, sort, alertsTab],
    queryFn: () =>
      alertsApi.list({
        skip,
        limit: pageSize,
        status: statusFilter || undefined,
        severity: severityFilter || undefined,
        sort,
        queue: queueParam,
      }),
    enabled: debouncedSearch.length === 0,
  });
  const searchQuery = useQuery({
    queryKey: ['alerts', 'search', debouncedSearch, skip, pageSize, statusFilter, severityFilter, sort, alertsTab],
    queryFn: () =>
      alertsApi.search({
        q: debouncedSearch,
        skip,
        limit: pageSize,
        status: statusFilter || undefined,
        severity: severityFilter || undefined,
        sort,
        queue: queueParam,
      }),
    enabled: debouncedSearch.length > 0,
  });
  const activeQuery = debouncedSearch.length > 0 ? searchQuery : listQuery;
  const { data: list, isLoading, error } = activeQuery;

  const { data: alertDetail, isLoading: detailLoading } = useQuery({
    queryKey: ['alert', selectedId],
    queryFn: () => alertsApi.get(selectedId!),
    enabled: !!selectedId,
  });

  const { data: snapshot, isLoading: snapshotLoading } = useQuery({
    queryKey: ['alert', 'snapshot', selectedId],
    queryFn: () => alertsApi.getSnapshot(selectedId!),
    enabled: !!selectedId,
  });

  useEffect(() => {
    if (!selectedId || !snapshot) return;
    const prof = snapshot.customer_profile as Record<string, unknown> | undefined;
    if (!prof) return;
    const name = String(prof.customer_name ?? '').trim();
    const email = String(prof.email ?? '').trim();
    setEddName(name);
    setEddEmail(email);
  }, [selectedId, snapshot]);

  useEffect(() => {
    setSendEddWithAction(false);
    setNotifyCcoWithAction(false);
    setCcoExtraRecipient('');
    setEscalateReason('');
    setEscalationType('cco_review');
    setOtcEstrRefinementNotes('');
  }, [selectedId]);

  function openAlertActionModal(alertId: string) {
    setSelectedId(alertId);
    setActionTab(null);
    setMessage(null);
  }

  const patchAlertCaches = (_alertId: string, _patch: Partial<Alert>) => {
    void _alertId;
    void _patch;
    queryClient.invalidateQueries({ queryKey: ['alerts'], exact: false });
  };

  const investigateMutation = useMutation({
    mutationFn: ({ alertId, body }: { alertId: string; body: { investigator_id: string; notes?: string } }) =>
      alertsApi.investigate(alertId, body),
    onSuccess: (_, { alertId }) => {
      patchAlertCaches(alertId, { status: 'investigating' });
    },
  });

  const resolveMutation = useMutation({
    mutationFn: ({
      alertId,
      body,
    }: {
      alertId: string;
      body: { resolution: 'false_positive'; notes: string; action_taken?: string };
    }) => alertsApi.resolve(alertId, body),
    onSuccess: (_, { alertId, body }) => {
      patchAlertCaches(alertId, {
        status: 'closed',
        last_resolution: body.resolution,
        cco_str_approved: false,
        escalation_classification: null,
      });
    },
  });

  const escalateMutation = useMutation({
    mutationFn: ({
      alertId,
      body,
    }: {
      alertId: string;
      body: { escalated_to: string; escalation_type: 'true_positive' | 'cco_review'; reason: string };
    }) => alertsApi.escalate(alertId, body),
    onSuccess: (data, { alertId, body }) => {
      patchAlertCaches(alertId, {
        status: 'escalated',
        cco_str_approved: data.cco_str_approved ?? false,
        cco_otc_approved: data.cco_otc_approved ?? false,
        escalation_classification: body.escalation_type,
      });
      void queryClient.invalidateQueries({ queryKey: ['alerts-dashboard'] });
      void queryClient.invalidateQueries({ queryKey: ['reports', 'otc-eligible'], exact: false });
      void queryClient.invalidateQueries({ queryKey: ['alerts', 'cco-pending-str'] });
      void queryClient.invalidateQueries({ queryKey: ['alerts', 'cco-pending-otc'] });
    },
  });

  const resetWorkflowMutation = useMutation({
    mutationFn: (alertId: string) => alertsApi.resetWorkflow(alertId),
    onSuccess: async (_, alertId) => {
      await queryClient.invalidateQueries({ queryKey: ['alerts'], exact: false });
      await queryClient.invalidateQueries({ queryKey: ['alert', alertId] });
      await queryClient.invalidateQueries({ queryKey: ['alert', 'snapshot', alertId] });
      await queryClient.invalidateQueries({ queryKey: ['alerts-dashboard'] });
      await queryClient.invalidateQueries({ queryKey: ['reports', 'otc-eligible'], exact: false });
      await queryClient.invalidateQueries({ queryKey: ['reports', 'str-eligible-alerts'] });
      await queryClient.invalidateQueries({ queryKey: ['alerts', 'cco-pending-str'] });
      await queryClient.invalidateQueries({ queryKey: ['alerts', 'cco-pending-otc'] });
      setMessage({
        type: 'success',
        text: 'Workflow reset to Open. Transaction, OTC filing, and KYC-linked data were kept for re-testing.',
      });
      if (selectedId === alertId) setSelectedId(null);
    },
    onError: (e) => {
      setMessage({
        type: 'error',
        text: e instanceof Error ? e.message : 'Could not reset workflow.',
      });
    },
  });

  const showResetWorkflowButton = (a: Alert) =>
    (a.status || '').toLowerCase() !== 'open' || Boolean(a.cco_str_approved);

  const OTC_ESTR_ESCALATE_DEFAULT_REASON =
    'OTC ESTR (cash) — escalate for Chief Compliance Officer review and approval before extended return generation on Regulatory Reports.';

  const handleOtcEstrEscalate = async () => {
    if (!selectedId) return;
    const alertId = selectedId;
    const reason = otcEstrRefinementNotes.trim() || OTC_ESTR_ESCALATE_DEFAULT_REASON;
    setWorkflowBusy(true);
    setMessage(null);
    try {
      const escRes = await escalateMutation.mutateAsync({
        alertId,
        body: {
          escalated_to: DEFAULT_ESCALATED_TO,
          escalation_type: 'true_positive',
          reason,
        },
      });
      void queryClient.invalidateQueries({ queryKey: ['alert', alertId] });
      void queryClient.invalidateQueries({ queryKey: ['alerts'], exact: false });
      setMessage({
        type: 'success',
        text:
          escRes.cco_notification_detail ||
          'Escalated. The CCO must approve OTC reporting on CCO review before Regulatory Reports lists this alert for ESTR.',
      });
      setOtcEstrRefinementNotes('');
      setSelectedId(null);
      const a = (list?.items ?? []).find((x) => x.id === alertId);
      setLastAction({
        action_key: 'ESCALATE_CCO_REVIEW',
        alert_id: alertId,
        transaction_id: a?.transaction_id,
        customer_id: a?.customer_id,
        summary: a?.summary,
        at: new Date().toISOString(),
      });
    } catch (e) {
      setMessage({ type: 'error', text: e instanceof Error ? e.message : 'Could not escalate alert.' });
    } finally {
      setWorkflowBusy(false);
    }
  };

  const items = list?.items ?? [];
  const alert = selectedId ? (alertDetail ?? items.find((a) => a.id === selectedId) ?? null) : null;
  const actionKey = useMemo(() => {
    if (!actionTab) return null;
    if (actionTab === 'investigate') return 'INVESTIGATE';
    if (actionTab === 'escalate') {
      return escalationType === 'true_positive' ? 'ESCALATE_TRUE_POSITIVE' : 'ESCALATE_CCO_REVIEW';
    }
    return 'RESOLVE_FALSE_POSITIVE';
  }, [actionTab, escalationType]);

  const handleInvestigate = async () => {
    if (!selectedId || !investigatorId.trim()) return;
    if (sendEddWithAction && !eddEmail.trim()) {
      setMessage({
        type: 'error',
        text: 'Enter the customer’s email to send the EDD request, or untick that option.',
      });
      return;
    }
    const alertId = selectedId;
    const inv = investigatorId.trim();
    const notes = investigateNotes.trim() || undefined;
    const extraRec = ccoExtraRecipient.trim() ? [ccoExtraRecipient.trim()] : undefined;
    setWorkflowBusy(true);
    setMessage(null);
    try {
      await investigateMutation.mutateAsync({ alertId, body: { investigator_id: inv, notes } });
      const parts: string[] = ['Investigation started.'];
      if (notifyCcoWithAction) {
        try {
          await alertsApi.notifyCco(alertId, {
            action: 'investigate',
            investigator_id: inv,
            investigation_notes: notes,
            extra_recipients: extraRec,
          });
          parts.push('CCO notified.');
        } catch (e) {
          parts.push(`CCO email failed: ${e instanceof Error ? e.message : 'Unknown error'}`);
        }
      }
      if (sendEddWithAction) {
        try {
          await alertsApi.notifyEdd(alertId, {
            customer_email: eddEmail.trim(),
            customer_name: eddName.trim() || undefined,
            compliance_action: 'investigate',
            investigator_id: inv,
            investigation_notes: notes,
          });
          parts.push('EDD request sent to customer.');
        } catch (e) {
          parts.push(`EDD email failed: ${e instanceof Error ? e.message : 'Unknown error'}`);
        }
      }
      const failed = parts.some((p) => p.includes('failed'));
      setMessage({ type: failed ? 'error' : 'success', text: parts.join(' ') });
      setActionTab(null);
      setInvestigatorId('');
      setInvestigateNotes('');
      const a = (list?.items ?? []).find((x) => x.id === alertId);
      setLastAction({
        action_key: 'INVESTIGATE',
        alert_id: alertId,
        transaction_id: a?.transaction_id,
        customer_id: a?.customer_id,
        summary: a?.summary,
        at: new Date().toISOString(),
      });
    } catch (e) {
      setMessage({ type: 'error', text: e instanceof Error ? e.message : 'Could not start investigation.' });
    } finally {
      setWorkflowBusy(false);
    }
  };

  const handleResolve = async () => {
    if (!selectedId || !resolveNotes.trim()) return;
    if (sendEddWithAction && !eddEmail.trim()) {
      setMessage({
        type: 'error',
        text: 'Enter the customer’s email to send the EDD request, or untick that option.',
      });
      return;
    }
    const alertId = selectedId;
    const res = 'false_positive' as const;
    const notes = resolveNotes.trim();
    const extraRec = ccoExtraRecipient.trim() ? [ccoExtraRecipient.trim()] : undefined;
    setWorkflowBusy(true);
    setMessage(null);
    try {
      await resolveMutation.mutateAsync({ alertId, body: { resolution: res, notes } });
      const parts: string[] = ['Alert resolved and closed.'];
      if (notifyCcoWithAction) {
        try {
          await alertsApi.notifyCco(alertId, {
            action: 'resolve',
            resolution: res,
            resolution_notes: notes,
            extra_recipients: extraRec,
          });
          parts.push('CCO notified.');
        } catch (e) {
          parts.push(`CCO email failed: ${e instanceof Error ? e.message : 'Unknown error'}`);
        }
      }
      if (sendEddWithAction) {
        try {
          await alertsApi.notifyEdd(alertId, {
            customer_email: eddEmail.trim(),
            customer_name: eddName.trim() || undefined,
            compliance_action: 'resolve',
            resolution: res,
            resolution_notes: notes,
          });
          parts.push('EDD request sent to customer.');
        } catch (e) {
          parts.push(`EDD email failed: ${e instanceof Error ? e.message : 'Unknown error'}`);
        }
      }
      const failed = parts.some((p) => p.includes('failed'));
      setMessage({ type: failed ? 'error' : 'success', text: parts.join(' ') });
      setActionTab(null);
      setResolveNotes('');
      setSelectedId(null);
      const a = (list?.items ?? []).find((x) => x.id === alertId);
      setLastAction({
        action_key: 'RESOLVE_FALSE_POSITIVE',
        alert_id: alertId,
        transaction_id: a?.transaction_id,
        customer_id: a?.customer_id,
        summary: a?.summary,
        at: new Date().toISOString(),
      });
    } catch (e) {
      setMessage({ type: 'error', text: e instanceof Error ? e.message : 'Could not resolve alert.' });
    } finally {
      setWorkflowBusy(false);
    }
  };

  const handleEscalate = async () => {
    if (!selectedId) return;
    if (escalationType === 'cco_review' && !escalateReason.trim()) return;
    if (sendEddWithAction && !eddEmail.trim()) {
      setMessage({
        type: 'error',
        text: 'Enter the customer’s email to send the EDD request, or untick that option.',
      });
      return;
    }
    const alertId = selectedId;
    const reason = escalateReason.trim();
    const to = DEFAULT_ESCALATED_TO;
    const escType = escalationType;
    setWorkflowBusy(true);
    setMessage(null);
    try {
      const escRes = await escalateMutation.mutateAsync({
        alertId,
        body: { escalated_to: to, escalation_type: escType, reason },
      });
      const eddEscalateReason =
        reason ||
        (escType === 'true_positive'
          ? 'Confirmed suspicious activity (true positive escalation).'
          : 'Referred for Chief Compliance Officer review.');
      const parts: string[] = [escRes.cco_notification_detail || 'Escalation recorded.'];
      if (sendEddWithAction) {
        try {
          await alertsApi.notifyEdd(alertId, {
            customer_email: eddEmail.trim(),
            customer_name: eddName.trim() || undefined,
            compliance_action: 'escalate',
            escalate_reason: eddEscalateReason,
            escalated_to: to,
          });
          parts.push('EDD request sent to customer.');
        } catch (e) {
          parts.push(`EDD email failed: ${e instanceof Error ? e.message : 'Unknown error'}`);
        }
      }
      const failed = parts.some((p) => p.includes('failed'));
      setMessage({ type: failed ? 'error' : 'success', text: parts.join(' ') });
      setActionTab(null);
      setEscalateReason('');
      setSelectedId(null);
      const a = (list?.items ?? []).find((x) => x.id === alertId);
      setLastAction({
        action_key: escType === 'true_positive' ? 'ESCALATE_TRUE_POSITIVE' : 'ESCALATE_CCO_REVIEW',
        alert_id: alertId,
        transaction_id: a?.transaction_id,
        customer_id: a?.customer_id,
        summary: a?.summary,
        at: new Date().toISOString(),
      });
    } catch (e) {
      setMessage({ type: 'error', text: e instanceof Error ? e.message : 'Could not escalate alert.' });
    } finally {
      setWorkflowBusy(false);
    }
  };

  return (
    <DashboardLayout>
      <h1 className="text-2xl font-bold text-slate-900 mb-3">Alerts</h1>
      <div className="flex flex-wrap gap-2 mb-6" role="tablist" aria-label="Alert queues">
        <button
          type="button"
          role="tab"
          aria-selected={alertsTab === 'all'}
          onClick={() => setAlertsTab('all')}
          className={`px-4 py-2 text-sm font-medium rounded-lg border ${
            alertsTab === 'all'
              ? 'bg-slate-800 text-white border-slate-800'
              : 'bg-white text-slate-700 border-slate-300 hover:bg-slate-50'
          }`}
        >
          All alerts
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={alertsTab === 'otc_estr'}
          onClick={() => setAlertsTab('otc_estr')}
          className={`px-4 py-2 text-sm font-medium rounded-lg border ${
            alertsTab === 'otc_estr'
              ? 'bg-amber-800 text-white border-amber-800'
              : 'bg-white text-slate-700 border-slate-300 hover:bg-slate-50'
          }`}
        >
          OTC / ESTR alerts
        </button>
      </div>
      <p className="text-sm text-slate-600 mb-4 max-w-3xl">
        {alertsTab === 'otc_estr' ? (
          <>
            <strong>OTC ESTR</strong> (cash extended return): after a <strong>true-positive</strong> OTC filing, the compliance
            officer must <strong>escalate</strong> the alert. The <strong>Chief Compliance Officer</strong> then approves OTC
            reporting on <strong>CCO review</strong>. Only then does the alert appear under{' '}
            <strong>Regulatory Reports → Generate OTC ESTR</strong>. Email to the CCO runs when <span className="font-mono">SMTP</span>{' '}
            and <span className="font-mono">CCO_EMAIL</span> are set.
          </>
        ) : (
          <>
            Select any alert and choose <strong>Take action</strong> to review details and snapshot, then investigate, resolve,
            or escalate as needed.
          </>
        )}
      </p>
      <div className="mb-4 flex flex-col gap-3">
        <div className="flex flex-col md:flex-row md:items-end gap-3">
          <div className="flex-1">
            <label className="block text-sm font-medium text-slate-700 mb-1" htmlFor="alert-search">
              Search (summary, customer, transaction, alert ID)
            </label>
            <input
              id="alert-search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="e.g. DEMO-PERSON-ADESANYA or alert id fragment"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm bg-white"
            />
            <p className="text-xs text-slate-500 mt-1">Filters below apply to both list and search results.</p>
          </div>
          <button
            type="button"
            onClick={() => setRiskSortFirst((v) => !v)}
            className={`self-start md:self-end px-3 py-2 text-sm rounded-lg border whitespace-nowrap ${
              riskSortFirst
                ? 'bg-blue-600 text-white border-blue-600 hover:bg-blue-700'
                : 'bg-white text-slate-800 border-slate-300 hover:bg-slate-50'
            }`}
          >
            {riskSortFirst ? 'Sort: highest risk' : 'Sort: newest first'}
          </button>
          {debouncedSearch.length > 0 && (
            <button
              type="button"
              onClick={() => setSearch('')}
              className="self-start md:self-end px-3 py-2 text-sm rounded-lg bg-slate-200 text-slate-800 hover:bg-slate-300"
            >
              Clear search
            </button>
          )}
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1" htmlFor="alert-filter-status">
              Status
            </label>
            <select
              id="alert-filter-status"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="rounded-lg border border-slate-300 px-2 py-2 text-sm bg-white min-w-[140px]"
            >
              <option value="">All statuses</option>
              <option value="open">open</option>
              <option value="investigating">investigating</option>
              <option value="escalated">escalated</option>
              <option value="closed">closed</option>
              <option value="rejected">rejected</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1" htmlFor="alert-filter-severity">
              Risk band
            </label>
            <select
              id="alert-filter-severity"
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value)}
              className="rounded-lg border border-slate-300 px-2 py-2 text-sm bg-white min-w-[140px]"
            >
              <option value="">All bands</option>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1" htmlFor="alert-page-size">
              Page size
            </label>
            <select
              id="alert-page-size"
              value={pageSize}
              onChange={(e) => setPageSize(Number(e.target.value))}
              className="rounded-lg border border-slate-300 px-2 py-2 text-sm bg-white"
            >
              {[10, 20, 50, 100].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>
      {message && (
        <div
          className={`mb-4 p-4 rounded-lg text-sm ${message.type === 'success' ? 'bg-green-50 text-green-800 border border-green-200' : 'bg-red-50 text-red-800 border border-red-200'}`}
          role="alert"
        >
          {message.text}
          <button
            type="button"
            className="ml-2 underline"
            onClick={() => setMessage(null)}
            aria-label="Dismiss"
          >
            Dismiss
          </button>
        </div>
      )}
      {error && (
        <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm">
          Could not load alerts. Is the backend running? (Try port 8002 if using default.)
          <br />
          <span className="font-mono">{error.message}</span>
        </div>
      )}
      <p className="text-slate-600 mb-2">
        {(() => {
          const total = list?.total ?? 0;
          if (total === 0) return 'No alerts match the current filters.';
          const start = skip + 1;
          const end = Math.min(skip + items.length, total);
          return (
            <>
              Showing <strong>{start}</strong>–<strong>{end}</strong> of <strong>{total}</strong> alerts
            </>
          );
        })()}
      </p>
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <button
          type="button"
          disabled={page <= 0 || isLoading}
          onClick={() => setPage((p) => Math.max(0, p - 1))}
          className="px-3 py-1.5 text-sm rounded-lg border border-slate-300 bg-white hover:bg-slate-50 disabled:opacity-50"
        >
          Previous
        </button>
        <button
          type="button"
          disabled={isLoading || skip + pageSize >= (list?.total ?? 0)}
          onClick={() => setPage((p) => p + 1)}
          className="px-3 py-1.5 text-sm rounded-lg border border-slate-300 bg-white hover:bg-slate-50 disabled:opacity-50"
        >
          Next
        </button>
        <span className="text-sm text-slate-600">
          Page <strong>{page + 1}</strong>
          {list?.total != null && pageSize > 0 ? (
            <>
              {' '}
              of <strong>{Math.max(1, Math.ceil(list.total / pageSize))}</strong>
            </>
          ) : null}
        </span>
      </div>
      <div className="bg-white rounded-lg shadow overflow-hidden">
        {isLoading && <p className="p-4 text-slate-500">Loading…</p>}
        {!isLoading && !error && items.length === 0 && <p className="p-4 text-slate-500">No alerts</p>}
        {!isLoading && items.length > 0 && (
          <ul className="divide-y divide-slate-100">
            {items.map((a) => (
              <li
                key={a.id}
                className="p-4 hover:bg-slate-50 cursor-pointer transition-colors"
                onClick={() => openAlertActionModal(a.id)}
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-slate-900">{a.summary ?? 'Suspicious activity'}</p>
                    <p className="text-sm text-slate-500 mt-1">
                      Customer: {a.customer_id} · Txn: {a.transaction_id}
                      {a.linked_transaction_type ? (
                        <span className="ml-1 text-xs font-mono text-slate-400">
                          · {String(a.linked_transaction_type).replace(/_/g, ' ')}
                        </span>
                      ) : null}
                    </p>
                    {(a.walk_in_otc || a.otc_report_kind) && (
                      <p className="text-xs text-amber-800 mt-1">
                        {a.walk_in_otc ? 'OTC walk-in · ' : ''}
                        {a.otc_report_kind === 'otc_estr'
                          ? 'OTC ESTR path'
                          : a.otc_report_kind === 'otc_esar'
                            ? 'OTC ESAR path'
                            : ''}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-2 flex-wrap" onClick={(e) => e.stopPropagation()}>
                    <span
                      className={`px-2 py-1 rounded text-xs font-medium ${
                        a.severity >= 0.9 ? 'bg-red-100 text-red-800' : a.severity >= 0.7 ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-700'
                      }`}
                    >
                      {(a.severity * 100).toFixed(0)}% risk
                    </span>
                    <span
                      className={`px-2 py-1 rounded text-xs capitalize ${
                        (a.status || '').toLowerCase() === 'rejected'
                          ? 'bg-rose-100 text-rose-900 font-medium'
                          : 'bg-slate-100 text-slate-700'
                      }`}
                    >
                      {a.status}
                    </span>
                    <button
                      type="button"
                      onClick={() => openAlertActionModal(a.id)}
                      className="px-2 py-1 text-xs font-medium rounded border border-slate-300 bg-white text-slate-800 hover:bg-slate-100"
                    >
                      Take action
                    </button>
                    {showResetWorkflowButton(a) && (
                      <button
                        type="button"
                        title="Set status back to Open and clear STR/escalation flags; keeps transaction and OTC data"
                        disabled={resetWorkflowMutation.isPending}
                        onClick={() => {
                          if (
                            !window.confirm(
                              `Reset workflow for this alert to Open?\n\nKeeps customer, transaction, and OTC filing data; clears escalated/closed state and CCO STR approval so you can re-test.`
                            )
                          )
                            return;
                          resetWorkflowMutation.mutate(a.id);
                        }}
                        className="px-2 py-1 text-xs font-medium rounded border border-amber-400 bg-amber-50 text-amber-950 hover:bg-amber-100 disabled:opacity-50"
                      >
                        Reset workflow
                      </button>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Alert action modal */}
      {selectedId && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50"
          onClick={() => setSelectedId(null)}
          role="dialog"
          aria-modal="true"
          aria-labelledby="alert-detail-title"
        >
          <div
            className="bg-white rounded-xl shadow-xl max-w-3xl w-full max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-6 border-b border-slate-200 flex justify-between items-start">
              <h2 id="alert-detail-title" className="text-lg font-semibold text-slate-900">
                Alert action
              </h2>
              <button
                type="button"
                onClick={() => setSelectedId(null)}
                className="text-slate-400 hover:text-slate-600"
                aria-label="Close"
              >
                ✕
              </button>
            </div>
            <div className="p-6 space-y-4">
              {detailLoading && !alert && <p className="text-slate-500">Loading…</p>}
              {alert && (
                <>
                  <p className="font-medium text-slate-900">{alert.summary ?? 'Suspicious activity'}</p>
                  {(alert.status || '').toLowerCase() === 'rejected' && (
                    <div
                      className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-950"
                      role="region"
                      aria-label="CCO rejection details"
                    >
                      <p className="font-semibold text-rose-900">Rejected by Chief Compliance Officer</p>
                      {(() => {
                        const { rejected_by } = ccoRejectionMeta(alert);
                        return rejected_by ? (
                          <p className="text-xs text-rose-800 mt-1">Recorded by: {rejected_by}</p>
                        ) : null;
                      })()}
                      <p className="mt-2 whitespace-pre-wrap text-rose-950">
                        {alert.cco_str_rejection_reason?.trim() || '—'}
                      </p>
                      <p className="mt-2 text-xs text-rose-800">
                        Use <strong>Reset workflow</strong> when you need to re-open this alert for rework (demo/QA).
                      </p>
                    </div>
                  )}
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="px-2 py-0.5 rounded text-xs bg-slate-100 text-slate-700 capitalize">
                      Status: {alert.status}
                    </span>
                    {showResetWorkflowButton(alert) && (
                      <button
                        type="button"
                        disabled={resetWorkflowMutation.isPending}
                        onClick={() => {
                          if (
                            !window.confirm(
                              `Reset workflow to Open? OTC and transaction data stay on the alert for re-testing.`
                            )
                          )
                            return;
                          resetWorkflowMutation.mutate(alert.id);
                        }}
                        className="px-2 py-1 text-xs font-medium rounded border border-amber-400 bg-amber-50 text-amber-950 hover:bg-amber-100 disabled:opacity-50"
                      >
                        Reset workflow
                      </button>
                    )}
                  </div>
                  {alert.customer_id ? (
                    <div className="space-y-2">
                      {isOtcExtendedReturnAlert(alert) ? (
                        <>
                          <p className="text-xs text-slate-600">
                            <strong>OTC regulatory</strong> (ESTR / ESAR): supporting PDF includes only evidence for{' '}
                            <strong>profile/detail changes</strong> or <strong>cash over threshold</strong> — not the account
                            opening package. Download AOP file uploads separately below; generate the account opening
                            package (PDF) from <strong>Customers</strong> or <strong>Regulatory Reports</strong>.
                          </p>
                          <div className="flex flex-wrap items-center gap-2">
                            <button
                              type="button"
                              onClick={async () => {
                                setMessage(null);
                                try {
                                  await customersApi.downloadSupportingDocumentsBundle(
                                    alert.customer_id,
                                    'otc_estr_supporting',
                                  );
                                } catch (e) {
                                  setMessage({
                                    type: 'error',
                                    text:
                                      e instanceof Error
                                        ? e.message
                                        : 'Could not download OTC ESTR supporting PDF.',
                                  });
                                }
                              }}
                              className="px-3 py-1.5 text-xs font-medium rounded-lg bg-teal-700 text-white hover:bg-teal-600"
                            >
                              OTC ESTR supporting PDF
                            </button>
                            <button
                              type="button"
                              onClick={async () => {
                                setMessage(null);
                                try {
                                  await customersApi.downloadSupportingDocumentsBundle(
                                    alert.customer_id,
                                    'aop_package',
                                  );
                                } catch (e) {
                                  setMessage({
                                    type: 'error',
                                    text:
                                      e instanceof Error ? e.message : 'Could not download AOP package PDF.',
                                  });
                                }
                              }}
                              className="px-3 py-1.5 text-xs font-medium rounded-lg bg-emerald-700 text-white hover:bg-emerald-600"
                            >
                              AOP package PDF
                            </button>
                          </div>
                        </>
                      ) : (
                        <div className="flex flex-wrap items-center gap-2">
                          <button
                            type="button"
                            onClick={async () => {
                              setMessage(null);
                              try {
                                await customersApi.downloadSupportingDocumentsBundle(alert.customer_id);
                              } catch (e) {
                                setMessage({
                                  type: 'error',
                                  text:
                                    e instanceof Error
                                      ? e.message
                                      : 'Could not download supporting documents bundle.',
                                });
                              }
                            }}
                            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-teal-700 text-white hover:bg-teal-600"
                          >
                            Download customer documents (one PDF)
                          </button>
                          <span className="text-xs text-slate-500">
                            Full archive: all categorized uploads from the Customers page.
                          </span>
                        </div>
                      )}
                    </div>
                  ) : null}
                  <dl className="grid grid-cols-1 gap-2 text-sm">
                    {!isOtcEstrAlert(alert) && (
                      <>
                        <div>
                          <dt className="text-slate-500">Alert ID</dt>
                          <dd className="font-mono">{alert.id}</dd>
                        </div>
                        <div>
                          <dt className="text-slate-500">Transaction ID</dt>
                          <dd className="font-mono">{alert.transaction_id}</dd>
                        </div>
                        <div>
                          <dt className="text-slate-500">Customer</dt>
                          <dd>{alert.customer_id}</dd>
                        </div>
                      </>
                    )}
                    <div>
                      <dt className="text-slate-500">Risk</dt>
                      <dd>{(alert.severity * 100).toFixed(0)}%</dd>
                    </div>
                    <div>
                      <dt className="text-slate-500">Status</dt>
                      <dd className="capitalize">{alert.status}</dd>
                    </div>
                    {alert.status === 'escalated' && (
                      <>
                        <div>
                          <dt className="text-slate-500">Escalation type</dt>
                          <dd className="capitalize">
                            {alert.escalation_classification?.replace(/_/g, ' ') ?? '—'}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-slate-500">CCO approved for STR</dt>
                          <dd>{alert.cco_str_approved ? 'Yes' : 'No — use CCO review queue'}</dd>
                        </div>
                      </>
                    )}
                    {(() => {
                      const raw = alert.rule_ids ?? [];
                      const forDisplay = isOtcEstrAlert(alert)
                        ? raw.filter((r) => !String(r).startsWith('REF-STR'))
                        : raw;
                      if (forDisplay.length === 0) return null;
                      return (
                        <div>
                          <dt className="text-slate-500">Rules triggered</dt>
                          <dd className="font-mono text-xs">{forDisplay.join(', ')}</dd>
                        </div>
                      );
                    })()}
                    {alert.otc_outcome && (
                      <>
                        <div>
                          <dt className="text-slate-500">OTC filing</dt>
                          <dd className="capitalize">
                            Outcome: {alert.otc_outcome.replace(/_/g, ' ')}
                            {alert.otc_report_kind
                              ? ` — ${alert.otc_report_kind === 'otc_estr' ? 'OTC ESTR (cash)' : 'OTC ESAR (SAR)'}`
                              : ''}
                          </dd>
                        </div>
                        {alert.otc_subject && (
                          <div>
                            <dt className="text-slate-500">OTC subject</dt>
                            <dd className="font-mono text-xs">{alert.otc_subject.replace(/_/g, ' ')}</dd>
                          </div>
                        )}
                        {alert.otc_filing_reason && (
                          <div>
                            <dt className="text-slate-500">OTC reason for filing</dt>
                            <dd className="text-xs">
                              {alert.otc_filing_reason.replace(/_/g, ' ')}
                              {alert.otc_filing_reason_detail
                                ? ` — ${alert.otc_filing_reason_detail.slice(0, 120)}${alert.otc_filing_reason_detail.length > 120 ? '…' : ''}`
                                : ''}
                            </dd>
                          </div>
                        )}
                        {alert.otc_outcome === 'true_positive' && isOtcEstrAlert(alert) && (
                          <>
                            <div>
                              <dt className="text-slate-500">OTC filing (regulatory)</dt>
                              <dd>
                                True-positive OTC is on file. <strong>Escalate</strong> the alert, then the CCO must{' '}
                                <strong>approve OTC reporting</strong> on CCO review before ESTR generation is available (unless an
                                admin enables auto-OTC workflow in Settings).
                              </dd>
                            </div>
                            <div>
                              <dt className="text-slate-500">Regulatory Reports (OTC ESTR)</dt>
                              <dd>
                                {alert.cco_otc_approved && (alert.status || '').toLowerCase() === 'escalated'
                                  ? 'Unlocked — generate Word/XML on Regulatory Reports'
                                  : (alert.status || '').toLowerCase() !== 'escalated'
                                    ? 'Pending — escalate this alert after true-positive OTC filing'
                                    : 'Pending — CCO approval of OTC reporting (CCO review queue)'}
                              </dd>
                            </div>
                          </>
                        )}
                        {alert.otc_outcome === 'true_positive' && !isOtcEstrAlert(alert) && (
                          <div>
                            <dt className="text-slate-500">OTC regulatory path</dt>
                            <dd>
                              True-positive identity/profile OTC on file. Escalate and obtain CCO approval for OTC reporting, then
                              use <strong>Generate OTC ESAR</strong> on Reports when eligible.
                            </dd>
                          </div>
                        )}
                      </>
                    )}
                  </dl>

                  {isOtcEstrAlert(alert) && (alert.status || '').toLowerCase() !== 'rejected' && (
                    <div className="rounded-lg border border-cyan-200 bg-cyan-50/50 p-4 space-y-3">
                      <h3 className="text-sm font-semibold text-slate-900">
                        OTC extended return (ESTR){alert.walk_in_otc ? ' · walk-in' : ''}
                      </h3>
                      <p className="text-xs text-slate-600">
                        <strong>Do not generate the Word pack from this screen.</strong> After true-positive OTC filing,{' '}
                        <strong>escalate</strong> so the Chief Compliance Officer can approve OTC reporting. Then use{' '}
                        <strong>Regulatory Reports → Generate OTC ESTR</strong>.
                      </p>
                      {alert.otc_outcome !== 'true_positive' && (
                        <div className="text-xs text-amber-950 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
                          Record this matter as a <strong>true-positive OTC</strong> filing before any extended return can be
                          drafted.
                          <button
                            type="button"
                            onClick={() => navigate('/cco-review')}
                            className="mt-2 block text-sm font-medium text-amber-900 underline hover:text-amber-950"
                          >
                            Open CCO review
                          </button>
                        </div>
                      )}
                      <label className="block text-sm font-medium text-slate-700">
                        Optional notes for the Chief Compliance Officer (included in escalation)
                        <textarea
                          value={otcEstrRefinementNotes}
                          onChange={(e) => setOtcEstrRefinementNotes(e.target.value)}
                          rows={3}
                          placeholder="e.g. Request review of cash threshold breach and branch referral; facts on file in snapshot."
                          className="mt-1 block w-full rounded border border-slate-300 px-3 py-2 text-sm"
                        />
                      </label>
                      <button
                        type="button"
                        onClick={() => {
                          if (!selectedId || workflowBusy) return;
                          setMessage(null);
                          void handleOtcEstrEscalate();
                        }}
                        disabled={!selectedId || workflowBusy || escalateMutation.isPending}
                        className="px-4 py-2 text-sm font-medium rounded-lg bg-red-600 text-white hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {workflowBusy || escalateMutation.isPending
                          ? 'Escalating…'
                          : 'Escalate to CCO (required before ESTR generation)'}
                      </button>
                    </div>
                  )}

                  {(alert.status || '').toLowerCase() === 'rejected' && isOtcEstrAlert(alert) && (
                    <p className="text-sm text-rose-800 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2">
                      This OTC alert was <strong>rejected</strong> by the CCO. Escalation and regulatory actions are
                      unavailable until you use <strong>Reset workflow</strong> if appropriate.
                    </p>
                  )}

                  {!isOtcEstrAlert(alert) && (alert.status || '').toLowerCase() !== 'rejected' && (
                  <div className="pt-4 border-t border-slate-200">
                    <h3 className="text-sm font-semibold text-slate-900 mb-2">Compliance actions (pre-resolution)</h3>
                    <p className="text-xs text-slate-600 mb-3">
                      <strong>Resolve</strong> closes the alert as a <strong>false positive</strong> (no STR). Those alerts
                      become eligible for <strong>SAR</strong> (suspicious activity) generation on the Reports page.{' '}
                      <strong>Escalate</strong> for a <strong>true positive</strong> or <strong>CCO review</strong>; the Chief
                      Compliance Officer is notified when configured, and STR filing follows CCO approval. Attach customer{' '}
                      <strong>AOP</strong> documents on the <strong>Customers</strong> page when needed for the file.
                    </p>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => setActionTab(actionTab === 'investigate' ? null : 'investigate')}
                        className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700"
                      >
                        Investigate
                      </button>
                      <button
                        type="button"
                        onClick={() => setActionTab(actionTab === 'resolve' ? null : 'resolve')}
                        className="px-3 py-1.5 text-sm bg-amber-600 text-white rounded hover:bg-amber-700"
                      >
                        Resolve
                      </button>
                      <button
                        type="button"
                        onClick={() => setActionTab(actionTab === 'escalate' ? null : 'escalate')}
                        className="px-3 py-1.5 text-sm bg-red-600 text-white rounded hover:bg-red-700"
                      >
                        Escalate
                      </button>
                    </div>
                    {actionKey && (
                      <div className="mt-3">
                        <span className="inline-flex items-center gap-2 px-2 py-1 rounded bg-slate-100 text-slate-700 text-xs font-mono">
                          action_key: <span className="text-slate-900">{actionKey}</span>
                        </span>
                      </div>
                    )}

                    {actionTab && (
                      <div className="mt-4 p-3 rounded-lg border border-slate-200 bg-white space-y-3">
                        <p className="text-xs font-semibold text-slate-800">Email notifications (with this submission)</p>
                        <p className="text-xs text-slate-500">
                          Customer contact is pre-filled when the snapshot loads (KYC / metadata). Confirm or replace before
                          sending live mail.
                        </p>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                          <label className="block text-sm font-medium text-slate-700">
                            Customer email
                            <input
                              type="email"
                              value={eddEmail}
                              onChange={(e) => setEddEmail(e.target.value)}
                              className="mt-1 block w-full rounded border border-slate-300 px-3 py-2 text-sm"
                              autoComplete="off"
                            />
                          </label>
                          <label className="block text-sm font-medium text-slate-700">
                            Customer name
                            <input
                              type="text"
                              value={eddName}
                              onChange={(e) => setEddName(e.target.value)}
                              className="mt-1 block w-full rounded border border-slate-300 px-3 py-2 text-sm"
                            />
                          </label>
                        </div>
                        <label className="flex items-start gap-2 text-sm text-slate-700 cursor-pointer select-none">
                          <input
                            type="checkbox"
                            checked={sendEddWithAction}
                            onChange={(e) => setSendEddWithAction(e.target.checked)}
                            className="mt-0.5 rounded border-slate-300"
                          />
                          <span>Send enhanced due diligence (EDD) request to the customer</span>
                        </label>
                        {actionTab !== 'escalate' && (
                          <label className="flex items-start gap-2 text-sm text-slate-700 cursor-pointer select-none">
                            <input
                              type="checkbox"
                              checked={notifyCcoWithAction}
                              onChange={(e) => setNotifyCcoWithAction(e.target.checked)}
                              className="mt-0.5 rounded border-slate-300"
                            />
                            <span>Also notify Chief Compliance Officer (CCO) by email (optional duplicate)</span>
                          </label>
                        )}
                        {actionTab === 'escalate' && (
                          <p className="text-xs text-slate-600 bg-slate-50 border border-slate-100 rounded px-2 py-2">
                            Set <span className="font-mono">CCO_EMAIL</span> and SMTP for automatic email; otherwise the CCO uses
                            the in-app <strong>CCO review</strong> queue for STR and OTC reporting approvals.
                          </p>
                        )}
                        <label className="block text-sm font-medium text-slate-700">
                          Extra CCO recipient email (optional)
                          <input
                            type="email"
                            value={ccoExtraRecipient}
                            onChange={(e) => setCcoExtraRecipient(e.target.value)}
                            placeholder="CC another mailbox on the CCO notification"
                            className="mt-1 block w-full rounded border border-slate-300 px-3 py-2 text-sm"
                          />
                        </label>
                      </div>
                    )}

                    {actionTab === 'investigate' && (
                      <div className="mt-4 p-4 bg-slate-50 rounded-lg space-y-3">
                        <label className="block text-sm font-medium text-slate-700">
                          Investigator ID <span className="text-red-500">*</span>
                          <input
                            type="text"
                            value={investigatorId}
                            onChange={(e) => setInvestigatorId(e.target.value)}
                            placeholder="e.g. INV-001"
                            className="mt-1 block w-full rounded border border-slate-300 px-3 py-2 text-sm"
                          />
                        </label>
                        <label className="block text-sm font-medium text-slate-700">
                          Notes
                          <textarea
                            value={investigateNotes}
                            onChange={(e) => setInvestigateNotes(e.target.value)}
                            placeholder="Optional notes"
                            rows={2}
                            className="mt-1 block w-full rounded border border-slate-300 px-3 py-2 text-sm"
                          />
                        </label>
                        <button
                          type="button"
                          onClick={handleInvestigate}
                          disabled={
                            workflowBusy ||
                            !investigatorId.trim() ||
                            investigateMutation.isPending
                          }
                          className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
                        >
                          {workflowBusy || investigateMutation.isPending ? 'Working…' : 'Start investigation'}
                        </button>
                      </div>
                    )}

                    {actionTab === 'resolve' && (
                      <div className="mt-4 p-4 bg-slate-50 rounded-lg space-y-3">
                        <p className="text-sm text-slate-700">
                          You are closing this alert as a <strong>false positive</strong> (no STR). After closure, this case
                          is eligible for <strong>SAR</strong> filing from Regulatory reports — activity-led, including batch
                          generation. Use <strong>Escalate</strong> if you need the STR / CCO path instead.
                        </p>
                        <label className="block text-sm font-medium text-slate-700">
                          Notes <span className="text-red-500">*</span>
                          <textarea
                            value={resolveNotes}
                            onChange={(e) => setResolveNotes(e.target.value)}
                            placeholder="Document why this alert is a false positive"
                            rows={2}
                            className="mt-1 block w-full rounded border border-slate-300 px-3 py-2 text-sm"
                          />
                        </label>
                        <button
                          type="button"
                          onClick={handleResolve}
                          disabled={workflowBusy || !resolveNotes.trim() || resolveMutation.isPending}
                          className="px-3 py-1.5 text-sm bg-amber-600 text-white rounded hover:bg-amber-700 disabled:opacity-50"
                        >
                          {workflowBusy || resolveMutation.isPending ? 'Working…' : 'Resolve & close'}
                        </button>
                      </div>
                    )}

                    {actionTab === 'escalate' && (
                      <div className="mt-4 p-4 bg-slate-50 rounded-lg space-y-3">
                        <fieldset className="space-y-2">
                          <legend className="text-sm font-medium text-slate-700">Escalation type</legend>
                          <label className="flex items-start gap-2 text-sm text-slate-700 cursor-pointer">
                            <input
                              type="radio"
                              name="escalation-type"
                              checked={escalationType === 'true_positive'}
                              onChange={() => setEscalationType('true_positive')}
                              className="mt-1"
                            />
                            <span>
                              <strong>True positive</strong> — confirmed suspicious; CCO must approve before STR can be
                              generated.
                            </span>
                          </label>
                          <label className="flex items-start gap-2 text-sm text-slate-700 cursor-pointer">
                            <input
                              type="radio"
                              name="escalation-type"
                              checked={escalationType === 'cco_review'}
                              onChange={() => setEscalationType('cco_review')}
                              className="mt-1"
                            />
                            <span>
                              <strong>CCO review</strong> — provide a reason for the Chief Compliance Officer to assess and
                              approve STR filing.
                            </span>
                          </label>
                        </fieldset>
                        {escalationType === 'cco_review' && (
                          <>
                            <div className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-950">
                              The <strong>reason for CCO review</strong> must be entered below. This is{' '}
                              <strong>required</strong> when escalation type is <strong>CCO review</strong>.
                            </div>
                            <label className="block text-sm font-medium text-slate-700">
                              Reason for CCO review <span className="text-red-500">*</span>
                              <textarea
                                value={escalateReason}
                                onChange={(e) => setEscalateReason(e.target.value)}
                                rows={4}
                                placeholder="e.g. Unusual cash pattern relative to stated occupation; need MLRO sign-off before STR."
                                className="mt-1 block w-full rounded border border-slate-300 px-3 py-2 text-sm"
                              />
                            </label>
                          </>
                        )}
                        {escalationType === 'true_positive' && (
                          <label className="block text-sm font-medium text-slate-700">
                            Context for escalation (optional)
                            <textarea
                              value={escalateReason}
                              onChange={(e) => setEscalateReason(e.target.value)}
                              rows={2}
                              placeholder="Optional notes for the CCO email and audit trail (a default line is used if empty)."
                              className="mt-1 block w-full rounded border border-slate-300 px-3 py-2 text-sm"
                            />
                          </label>
                        )}
                        <button
                          type="button"
                          onClick={handleEscalate}
                          disabled={
                            workflowBusy ||
                            (escalationType === 'cco_review' && !escalateReason.trim()) ||
                            escalateMutation.isPending
                          }
                          className="px-3 py-1.5 text-sm bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50"
                        >
                          {workflowBusy || escalateMutation.isPending ? 'Working…' : 'Escalate'}
                        </button>
                      </div>
                    )}
                  </div>
                  )}

                  <div className="pt-4 border-t border-slate-200">
                    <h3 className="text-sm font-semibold text-slate-900 mb-2">
                      {isOtcEstrAlert(alert) ? 'Profile snapshot (pre-resolution)' : 'Transaction snapshot (pre-resolution)'}
                    </h3>
                    {snapshotLoading && <p className="text-sm text-slate-500">Loading snapshot…</p>}
                    {!snapshotLoading && snapshot && (
                      <div className="space-y-3 text-sm text-slate-700 bg-slate-50 rounded-lg p-4 border border-slate-100">
                        {(() => {
                          const tx = snapshot.transaction as Record<string, unknown> | undefined;
                          const prof = snapshot.customer_profile as Record<string, unknown> | undefined;
                          const bvn = (snapshot.bvn_linked_accounts as unknown[]) ?? [];
                          const why = snapshot.why_suspicious as Record<string, unknown> | undefined;
                          const typ = (why?.typologies as Array<Record<string, string>>) ?? [];
                          const rw = snapshot.rolling_windows as Record<string, unknown> | undefined;
                          const h24 = rw?.last_24_hours as Record<string, unknown> | undefined;
                          const y12 = rw?.twelve_month_ytd as Record<string, unknown> | undefined;
                          const life = rw?.lifetime_for_narrative as Record<string, unknown> | undefined;
                          const ff = snapshot.flagged_flows as Record<string, unknown> | undefined;
                          const san = snapshot.sanctions_screening as Record<string, unknown> | undefined;
                          const adverseNote = snapshot.adverse_media_note as string | undefined;
                          const sanctionsNote = snapshot.sanctions_screening_note as string | undefined;
                          const otcEstr = isOtcEstrAlert(alert);
                          return (
                            <>
                              {tx && !otcEstr && (
                                <div>
                                  <p className="font-medium text-slate-800">Flagged transaction</p>
                                  <p>
                                    Amount:{' '}
                                    <span className="font-mono">
                                      {String(tx.currency ?? 'NGN')} {Number(tx.amount ?? 0).toLocaleString('en-NG')}
                                    </span>
                                    {' · '}
                                    <span className="text-amber-800 font-medium">{String(tx.debit_credit ?? '')}</span>
                                  </p>
                                  <p className="text-xs text-slate-600 mt-1">
                                    Account: <span className="font-mono">{String(prof?.account_number ?? '—')}</span>
                                    {' · '}
                                    Counterparty: {String(tx.counterparty_name || tx.counterparty_id || '—')}
                                  </p>
                                  {tx.narrative ? (
                                    <p className="mt-1 text-slate-600">Narration: {String(tx.narrative)}</p>
                                  ) : null}
                                </div>
                              )}
                              {prof && (
                                <div>
                                  <p className="font-medium text-slate-800">Customer profile</p>
                                  <p>
                                    {String(prof.customer_name ?? '')} · {String(prof.line_of_business ?? '')}
                                  </p>
                                  <p className="text-xs text-slate-600">
                                    BVN/ID: {String(prof.bvn ?? prof.id_number ?? '')}
                                    {prof.email ? (
                                      <>
                                        {' · '}
                                        On-file email: <span className="font-mono">{String(prof.email)}</span>
                                      </>
                                    ) : null}
                                  </p>
                                </div>
                              )}
                              {bvn.length > 0 && (
                                <div>
                                  <p className="font-medium text-slate-800">Accounts linked to same BVN</p>
                                  <ul className="list-disc list-inside text-xs text-slate-600">
                                    {bvn.slice(0, 8).map((row, i) => (
                                      <li key={i}>
                                        {String((row as Record<string, unknown>).account_number)} (
                                        {(row as Record<string, unknown>).customer_id as string})
                                      </li>
                                    ))}
                                  </ul>
                                </div>
                              )}
                              {typ.length > 0 && !otcEstr && (
                                <div>
                                  <p className="font-medium text-slate-800">Why suspicious (typologies)</p>
                                  <ul className="space-y-1 text-xs">
                                    {typ.slice(0, 6).map((t, i) => (
                                      <li key={i}>
                                        <span className="font-mono text-slate-700">{t.rule_id}</span>: {t.title} —{' '}
                                        {t.narrative?.slice(0, 160)}
                                        {t.narrative && t.narrative.length > 160 ? '…' : ''}
                                      </li>
                                    ))}
                                  </ul>
                                </div>
                              )}
                              {(h24 || y12 || life) && (
                                <div>
                                  <p className="font-medium text-slate-800">Windows (24h · 12 months · lifetime)</p>
                                  <p className="text-xs text-slate-600">
                                    24h: {String(h24?.transaction_count ?? 0)} txns, in ₦
                                    {Number(h24?.inflow_total ?? 0).toLocaleString('en-NG')}, out ₦
                                    {Number(h24?.outflow_total ?? 0).toLocaleString('en-NG')}
                                  </p>
                                  <p className="text-xs text-slate-600">
                                    12m: in ₦{Number(y12?.inflow_total ?? 0).toLocaleString('en-NG')}, out ₦
                                    {Number(y12?.outflow_total ?? 0).toLocaleString('en-NG')}
                                  </p>
                                  <p className="text-xs text-slate-600">
                                    Lifetime: {String(life?.transaction_count ?? 0)} txns, age{' '}
                                    {String(life?.account_age_days ?? '—')} days
                                  </p>
                                </div>
                              )}
                              {ff && (
                                <div>
                                  <p className="font-medium text-slate-800">Source / destination (top counterparties)</p>
                                  <p className="text-xs text-slate-600">
                                    Inbound sources and outbound destinations summarise banks and senders for this customer.
                                  </p>
                                </div>
                              )}
                              {(adverseNote || snapshot.adverse_media) && (
                                <p className="text-xs text-slate-700 border-l-2 border-amber-300 pl-2">
                                  {String(adverseNote || snapshot.adverse_media)}
                                </p>
                              )}
                              {(sanctionsNote || san) && (
                                <div className="text-xs text-slate-600 space-y-1">
                                  <p>
                                    {sanctionsNote
                                      ? String(sanctionsNote)
                                      : `Online sanctions query: ${String(san?.match_count ?? 0)} match(es). ${san?.note ? String(san.note) : ''}`}
                                  </p>
                                  {san && Number(san.reference_list_match_count) > 0 ? (
                                    <p className="text-amber-900 border-l-2 border-amber-400 pl-2">
                                      Internal reference lists (fuzzy):{' '}
                                      {String(san.reference_list_match_count ?? 0)} sanctions/PEP hit(s); threshold{' '}
                                      {String((san.reference_lists as { fuzzy_threshold?: number })?.fuzzy_threshold ?? '—')}.
                                    </p>
                                  ) : null}
                                  {Array.isArray((snapshot as { reference_adverse_media_hits?: unknown[] }).reference_adverse_media_hits) &&
                                  ((snapshot as { reference_adverse_media_hits: unknown[] }).reference_adverse_media_hits.length >
                                    0) ? (
                                    <p className="text-amber-900 border-l-2 border-amber-400 pl-2">
                                      Adverse-media list:{' '}
                                      {(snapshot as { reference_adverse_media_hits: unknown[] }).reference_adverse_media_hits.length}{' '}
                                      fuzzy match(es) on file.
                                    </p>
                                  ) : null}
                                </div>
                              )}
                            </>
                          );
                        })()}
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </DashboardLayout>
  );
}
