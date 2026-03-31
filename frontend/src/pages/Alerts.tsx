import { useEffect, useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { alertsApi, type Alert } from '../services/api';
import DashboardLayout from '../components/layout/DashboardLayout';
import { useReportActionStore } from '../store/reportActionStore';

export default function Alerts() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [actionTab, setActionTab] = useState<'investigate' | 'resolve' | 'escalate' | null>(null);
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [investigatorId, setInvestigatorId] = useState('');
  const [investigateNotes, setInvestigateNotes] = useState('');
  const [resolution, setResolution] = useState<'true_positive' | 'false_positive'>('false_positive');
  const [resolveNotes, setResolveNotes] = useState('');
  const [escalateReason, setEscalateReason] = useState('');
  const [escalatedTo, setEscalatedTo] = useState('');
  const [eddEmail, setEddEmail] = useState('');
  const [eddName, setEddName] = useState('');
  const [sendEddWithAction, setSendEddWithAction] = useState(false);
  const [notifyCcoWithAction, setNotifyCcoWithAction] = useState(false);
  const [followUpNote, setFollowUpNote] = useState('');
  const [ccoExtraRecipient, setCcoExtraRecipient] = useState('');
  const [workflowBusy, setWorkflowBusy] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const setLastAction = useReportActionStore((s) => s.setLastAction);

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedSearch(search.trim()), 250);
    return () => window.clearTimeout(t);
  }, [search]);

  const listQuery = useQuery({
    queryKey: ['alerts', 'list', 0, 20],
    queryFn: () => alertsApi.list({ skip: 0, limit: 20 }),
  });
  const searchQuery = useQuery({
    queryKey: ['alerts', 'search', debouncedSearch, 0, 20],
    queryFn: () => alertsApi.search({ q: debouncedSearch, skip: 0, limit: 20 }),
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
    setFollowUpNote('');
    setCcoExtraRecipient('');
  }, [selectedId]);

  const investigateMutation = useMutation({
    mutationFn: ({ alertId, body }: { alertId: string; body: { investigator_id: string; notes?: string } }) =>
      alertsApi.investigate(alertId, body),
    onSuccess: (_, { alertId }) => {
      queryClient.setQueryData<{ items: Alert[]; total: number; skip: number; limit: number }>(['alerts', 0, 20], (old) =>
        old ? { ...old, items: old.items.map((a) => (a.id === alertId ? { ...a, status: 'investigating' } : a)) } : old
      );
    },
  });

  const resolveMutation = useMutation({
    mutationFn: ({
      alertId,
      body,
    }: {
      alertId: string;
      body: { resolution: 'true_positive' | 'false_positive'; notes: string; action_taken?: string };
    }) => alertsApi.resolve(alertId, body),
    onSuccess: (_, { alertId }) => {
      queryClient.setQueryData<{ items: Alert[]; total: number; skip: number; limit: number }>(['alerts', 0, 20], (old) =>
        old ? { ...old, items: old.items.map((a) => (a.id === alertId ? { ...a, status: 'closed' } : a)) } : old
      );
    },
  });

  const escalateMutation = useMutation({
    mutationFn: ({ alertId, body }: { alertId: string; body: { reason: string; escalated_to: string } }) =>
      alertsApi.escalate(alertId, body),
    onSuccess: (_, { alertId }) => {
      queryClient.setQueryData<{ items: Alert[]; total: number; skip: number; limit: number }>(['alerts', 0, 20], (old) =>
        old ? { ...old, items: old.items.map((a) => (a.id === alertId ? { ...a, status: 'escalated' } : a)) } : old
      );
    },
  });

  const items = list?.items ?? [];
  const alert = selectedId ? (items.find((a) => a.id === selectedId) ?? alertDetail) : null;
  const actionKey = useMemo(() => {
    if (!actionTab) return null;
    if (actionTab === 'investigate') return 'INVESTIGATE';
    if (actionTab === 'escalate') return 'ESCALATE';
    return `RESOLVE_${resolution === 'true_positive' ? 'TRUE_POSITIVE' : 'FALSE_POSITIVE'}`;
  }, [actionTab, resolution]);

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
    const noteExtra = followUpNote.trim() || undefined;
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
            additional_note: noteExtra,
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
            additional_note: noteExtra,
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
    const res = resolution;
    const notes = resolveNotes.trim();
    const noteExtra = followUpNote.trim() || undefined;
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
            additional_note: noteExtra,
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
            additional_note: noteExtra,
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
        action_key: `RESOLVE_${res === 'true_positive' ? 'TRUE_POSITIVE' : 'FALSE_POSITIVE'}`,
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
    if (!selectedId || !escalateReason.trim() || !escalatedTo.trim()) return;
    if (sendEddWithAction && !eddEmail.trim()) {
      setMessage({
        type: 'error',
        text: 'Enter the customer’s email to send the EDD request, or untick that option.',
      });
      return;
    }
    const alertId = selectedId;
    const reason = escalateReason.trim();
    const to = escalatedTo.trim();
    const noteExtra = followUpNote.trim() || undefined;
    const extraRec = ccoExtraRecipient.trim() ? [ccoExtraRecipient.trim()] : undefined;
    setWorkflowBusy(true);
    setMessage(null);
    try {
      await escalateMutation.mutateAsync({ alertId, body: { reason, escalated_to: to } });
      const parts: string[] = ['Alert escalated.'];
      if (notifyCcoWithAction) {
        try {
          await alertsApi.notifyCco(alertId, {
            action: 'escalate',
            escalate_reason: reason,
            escalated_to: to,
            additional_note: noteExtra,
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
            compliance_action: 'escalate',
            escalate_reason: reason,
            escalated_to: to,
            additional_note: noteExtra,
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
      setEscalatedTo('');
      setSelectedId(null);
      const a = (list?.items ?? []).find((x) => x.id === alertId);
      setLastAction({
        action_key: 'ESCALATE',
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
      <h1 className="text-2xl font-bold text-slate-900 mb-6">Alerts</h1>
      <div className="mb-4 flex flex-col md:flex-row md:items-center gap-3">
        <div className="flex-1">
          <label className="block text-sm font-medium text-slate-700 mb-1" htmlFor="alert-search">
            Search alerts (Customer ID or Transaction ID)
          </label>
          <input
            id="alert-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="e.g. DEMO-PERSON-ADESANYA or DEMO-WORKER-LAGOS"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm bg-white"
          />
          <p className="text-xs text-slate-500 mt-1">Results come from the current store; later this will query Postgres.</p>
        </div>
        {debouncedSearch.length > 0 && (
          <button
            type="button"
            onClick={() => setSearch('')}
            className="self-start md:self-end px-3 py-2 text-sm rounded-lg bg-slate-200 text-slate-800 hover:bg-slate-300"
          >
            Clear
          </button>
        )}
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
      <p className="text-slate-600 mb-4">Total: {list?.total ?? 0} alerts</p>
      <div className="bg-white rounded-lg shadow overflow-hidden">
        {isLoading && <p className="p-4 text-slate-500">Loading…</p>}
        {!isLoading && !error && items.length === 0 && <p className="p-4 text-slate-500">No alerts</p>}
        {!isLoading && items.length > 0 && (
          <ul className="divide-y divide-slate-100">
            {items.map((a) => (
              <li key={a.id} className="p-4 hover:bg-slate-50">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-slate-900">{a.summary ?? 'Suspicious activity'}</p>
                    <p className="text-sm text-slate-500 mt-1">
                      Customer: {a.customer_id} · Txn: {a.transaction_id}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <span
                      className={`px-2 py-1 rounded text-xs font-medium ${
                        a.severity >= 0.9 ? 'bg-red-100 text-red-800' : a.severity >= 0.7 ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-700'
                      }`}
                    >
                      {(a.severity * 100).toFixed(0)}% risk
                    </span>
                    <span className="px-2 py-1 rounded text-xs bg-slate-100 text-slate-700 capitalize">{a.status}</span>
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedId(a.id);
                        setActionTab(null);
                        setMessage(null);
                      }}
                      className="px-2 py-1 text-xs font-medium text-blue-600 hover:text-blue-800 hover:underline"
                    >
                      View & actions
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Detail & actions modal */}
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
                Alert details
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
                  <dl className="grid grid-cols-1 gap-2 text-sm">
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
                    <div>
                      <dt className="text-slate-500">Risk</dt>
                      <dd>{(alert.severity * 100).toFixed(0)}%</dd>
                    </div>
                    <div>
                      <dt className="text-slate-500">Status</dt>
                      <dd className="capitalize">{alert.status}</dd>
                    </div>
                    {alert.rule_ids && alert.rule_ids.length > 0 && (
                      <div>
                        <dt className="text-slate-500">Rules triggered</dt>
                        <dd className="font-mono text-xs">{alert.rule_ids.join(', ')}</dd>
                      </div>
                    )}
                  </dl>

                  <div className="pt-4 border-t border-slate-200">
                    <h3 className="text-sm font-semibold text-slate-900 mb-2">Compliance actions (pre-resolution)</h3>
                    <p className="text-xs text-slate-600 mb-3">
                      Select Investigate, Resolve, or Escalate, confirm customer contact and notification options, then complete
                      the form. On submit, the platform saves the disposition first; ticked notifications are sent immediately
                      afterward with the same structured details to the CCO and/or the customer.
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
                        <label className="flex items-start gap-2 text-sm text-slate-700 cursor-pointer select-none">
                          <input
                            type="checkbox"
                            checked={notifyCcoWithAction}
                            onChange={(e) => setNotifyCcoWithAction(e.target.checked)}
                            className="mt-0.5 rounded border-slate-300"
                          />
                          <span>Notify Chief Compliance Officer (CCO) by email</span>
                        </label>
                        <label className="block text-sm font-medium text-slate-700">
                          Additional note for correspondence (optional)
                          <textarea
                            value={followUpNote}
                            onChange={(e) => setFollowUpNote(e.target.value)}
                            rows={2}
                            className="mt-1 block w-full rounded border border-slate-300 px-3 py-2 text-sm"
                          />
                        </label>
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
                        <label className="block text-sm font-medium text-slate-700">
                          Resolution
                          <select
                            value={resolution}
                            onChange={(e) => setResolution(e.target.value as 'true_positive' | 'false_positive')}
                            className="mt-1 block w-full rounded border border-slate-300 px-3 py-2 text-sm"
                          >
                            <option value="false_positive">False positive</option>
                            <option value="true_positive">True positive</option>
                          </select>
                        </label>
                        <label className="block text-sm font-medium text-slate-700">
                          Notes <span className="text-red-500">*</span>
                          <textarea
                            value={resolveNotes}
                            onChange={(e) => setResolveNotes(e.target.value)}
                            placeholder="Resolution notes"
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
                        <label className="block text-sm font-medium text-slate-700">
                          Reason <span className="text-red-500">*</span>
                          <input
                            type="text"
                            value={escalateReason}
                            onChange={(e) => setEscalateReason(e.target.value)}
                            placeholder="Reason for escalation"
                            className="mt-1 block w-full rounded border border-slate-300 px-3 py-2 text-sm"
                          />
                        </label>
                        <label className="block text-sm font-medium text-slate-700">
                          Escalate to <span className="text-red-500">*</span>
                          <input
                            type="text"
                            value={escalatedTo}
                            onChange={(e) => setEscalatedTo(e.target.value)}
                            placeholder="e.g. Compliance Officer"
                            className="mt-1 block w-full rounded border border-slate-300 px-3 py-2 text-sm"
                          />
                        </label>
                        <button
                          type="button"
                          onClick={handleEscalate}
                          disabled={
                            workflowBusy ||
                            !escalateReason.trim() ||
                            !escalatedTo.trim() ||
                            escalateMutation.isPending
                          }
                          className="px-3 py-1.5 text-sm bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50"
                        >
                          {workflowBusy || escalateMutation.isPending ? 'Working…' : 'Escalate'}
                        </button>
                      </div>
                    )}
                  </div>

                  <div className="pt-4 border-t border-slate-200">
                    <h3 className="text-sm font-semibold text-slate-900 mb-2">Transaction snapshot (pre-resolution)</h3>
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
                          return (
                            <>
                              {tx && (
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
                              {typ.length > 0 && (
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
                              {snapshot.adverse_media && (
                                <p className="text-xs text-slate-700 border-l-2 border-amber-300 pl-2">
                                  {String(snapshot.adverse_media)}
                                </p>
                              )}
                              {san && (
                                <p className="text-xs text-slate-600">
                                  Online sanctions query: {String(san.match_count ?? 0)} match(es).{' '}
                                  {san.note ? String(san.note) : ''}
                                </p>
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
