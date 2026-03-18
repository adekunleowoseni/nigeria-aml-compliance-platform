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

  const investigateMutation = useMutation({
    mutationFn: ({ alertId, body }: { alertId: string; body: { investigator_id: string; notes?: string } }) =>
      alertsApi.investigate(alertId, body),
    onSuccess: (_, { alertId }) => {
      queryClient.setQueryData<{ items: Alert[]; total: number; skip: number; limit: number }>(['alerts', 0, 20], (old) =>
        old ? { ...old, items: old.items.map((a) => (a.id === alertId ? { ...a, status: 'investigating' } : a)) } : old
      );
      setMessage({ type: 'success', text: 'Investigation started.' });
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
    },
    onError: (e: Error) => setMessage({ type: 'error', text: e.message }),
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
      setMessage({ type: 'success', text: 'Alert resolved and closed.' });
      setActionTab(null);
      setResolveNotes('');
      setSelectedId(null);
      const a = (list?.items ?? []).find((x) => x.id === alertId);
      setLastAction({
        action_key: `RESOLVE_${resolution === 'true_positive' ? 'TRUE_POSITIVE' : 'FALSE_POSITIVE'}`,
        alert_id: alertId,
        transaction_id: a?.transaction_id,
        customer_id: a?.customer_id,
        summary: a?.summary,
        at: new Date().toISOString(),
      });
    },
    onError: (e: Error) => setMessage({ type: 'error', text: e.message }),
  });

  const escalateMutation = useMutation({
    mutationFn: ({ alertId, body }: { alertId: string; body: { reason: string; escalated_to: string } }) =>
      alertsApi.escalate(alertId, body),
    onSuccess: (_, { alertId }) => {
      queryClient.setQueryData<{ items: Alert[]; total: number; skip: number; limit: number }>(['alerts', 0, 20], (old) =>
        old ? { ...old, items: old.items.map((a) => (a.id === alertId ? { ...a, status: 'escalated' } : a)) } : old
      );
      setMessage({ type: 'success', text: 'Alert escalated.' });
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
    },
    onError: (e: Error) => setMessage({ type: 'error', text: e.message }),
  });

  const items = list?.items ?? [];
  const alert = selectedId ? (items.find((a) => a.id === selectedId) ?? alertDetail) : null;
  const actionKey = useMemo(() => {
    if (!actionTab) return null;
    if (actionTab === 'investigate') return 'INVESTIGATE';
    if (actionTab === 'escalate') return 'ESCALATE';
    return `RESOLVE_${resolution === 'true_positive' ? 'TRUE_POSITIVE' : 'FALSE_POSITIVE'}`;
  }, [actionTab, resolution]);

  const handleInvestigate = () => {
    if (!selectedId || !investigatorId.trim()) return;
    investigateMutation.mutate({
      alertId: selectedId,
      body: { investigator_id: investigatorId.trim(), notes: investigateNotes.trim() || undefined },
    });
  };

  const handleResolve = () => {
    if (!selectedId || !resolveNotes.trim()) return;
    resolveMutation.mutate({
      alertId: selectedId,
      body: { resolution, notes: resolveNotes.trim() },
    });
  };

  const handleEscalate = () => {
    if (!selectedId || !escalateReason.trim() || !escalatedTo.trim()) return;
    escalateMutation.mutate({
      alertId: selectedId,
      body: { reason: escalateReason.trim(), escalated_to: escalatedTo.trim() },
    });
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
            placeholder="e.g. demo-txn-wire-001 or CUST-NG-2002"
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
            className="bg-white rounded-xl shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto"
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

                  <div className="pt-4 border-t border-slate-100">
                    <p className="text-sm font-medium text-slate-700 mb-2">Actions</p>
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
                          disabled={!investigatorId.trim() || investigateMutation.isPending}
                          className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
                        >
                          {investigateMutation.isPending ? 'Starting…' : 'Start investigation'}
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
                          disabled={!resolveNotes.trim() || resolveMutation.isPending}
                          className="px-3 py-1.5 text-sm bg-amber-600 text-white rounded hover:bg-amber-700 disabled:opacity-50"
                        >
                          {resolveMutation.isPending ? 'Resolving…' : 'Resolve & close'}
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
                          disabled={!escalateReason.trim() || !escalatedTo.trim() || escalateMutation.isPending}
                          className="px-3 py-1.5 text-sm bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50"
                        >
                          {escalateMutation.isPending ? 'Escalating…' : 'Escalate'}
                        </button>
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
