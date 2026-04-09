import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import DashboardLayout from '../components/layout/DashboardLayout';
import { alertsApi, reportsApi, type Alert } from '../services/api';
import { useAuthStore } from '../store/authStore';

function canAccessCcoReviewPage(role: string | undefined): boolean {
  const r = (role || '').toLowerCase();
  return r === 'admin' || r === 'chief_compliance_officer' || r === 'compliance_officer';
}

function isCcoOrAdmin(role: string | undefined): boolean {
  const r = (role || '').toLowerCase();
  return r === 'admin' || r === 'chief_compliance_officer';
}

function displayCustomer(a: Pick<Alert, 'customer_name' | 'customer_id'>): string {
  return String(a.customer_name || '').trim() || a.customer_id;
}

function displayChannel(a: Pick<Alert, 'linked_channel'>): string {
  const raw = String(a.linked_channel || '').trim().toLowerCase();
  if (!raw) return '';
  if (raw === 'pos' || raw === 'pos_terminal') return 'POS terminal';
  if (raw === 'atm') return 'ATM';
  if (raw === 'otc_branch') return 'OTC branch';
  if (raw === 'nibss_nip' || raw === 'nibss') return 'NIBSS/NIP';
  return raw.replace(/_/g, ' ');
}

function SnapshotPanel({ alertId, open }: { alertId: string; open: boolean }) {
  const { data: alertDetail } = useQuery({
    queryKey: ['alert', alertId, 'cco-detail'],
    queryFn: () => alertsApi.get(alertId),
    enabled: open,
  });
  const { data, isLoading, error } = useQuery({
    queryKey: ['alert', 'snapshot', alertId, 'cco'],
    queryFn: () => alertsApi.getSnapshot(alertId),
    enabled: open,
  });
  if (!open) return null;
  if (isLoading) return <p className="mt-3 text-xs text-slate-500">Loading snapshot…</p>;
  if (error) return <p className="mt-3 text-xs text-red-600">{(error as Error).message}</p>;
  const prof = data?.customer_profile as Record<string, unknown> | undefined;
  const tx = data?.transaction as Record<string, unknown> | undefined;
  const why = data?.why_suspicious as Record<string, unknown> | undefined;
  const typs = (why?.typologies as Array<{ title?: string; narrative?: string }>) ?? [];
  const docs = data?.kyc_documents_on_file as Array<{ label?: string; status?: string }> | undefined;
  return (
    <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm space-y-2">
      <p className="text-xs font-semibold text-slate-700 uppercase tracking-wide">Pre-resolution snapshot</p>
      {prof && (
        <p>
          <span className="text-slate-500">Customer:</span>{' '}
          <strong>{String(prof.customer_name ?? '—')}</strong>
          <span className="text-slate-500"> · Occupation:</span> {String(prof.line_of_business ?? '—')}
        </p>
      )}
      {tx && (
        <div className="text-xs text-slate-800">
          <p className="font-medium text-slate-700">Flagged transaction</p>
          <p>
            {String(tx.currency ?? 'NGN')} {Number(tx.amount ?? 0).toLocaleString('en-NG')} ·{' '}
            <span className="font-mono">{String(tx.transaction_type ?? '—')}</span>
            {tx.debit_credit ? <> · {String(tx.debit_credit)}</> : null}
          </p>
          {tx.narrative ? <p className="mt-1 text-slate-600">Narration: {String(tx.narrative)}</p> : null}
        </div>
      )}
      {typs.length > 0 && (
        <div className="text-xs">
          <p className="font-medium text-slate-700">Why suspicious (typologies)</p>
          <ul className="list-disc pl-4 mt-1 space-y-1 text-slate-600">
            {typs.slice(0, 5).map((t, i) => (
              <li key={i}>
                {t.title ?? 'Rule'}: {(t.narrative ?? '').slice(0, 220)}
                {(t.narrative ?? '').length > 220 ? '…' : ''}
              </li>
            ))}
          </ul>
        </div>
      )}
      {docs && docs.length > 0 && (
        <div className="text-xs">
          <p className="font-medium text-slate-700">Documents on file</p>
          <ul className="list-disc pl-4 mt-1 text-slate-600">
            {docs.map((d, i) => (
              <li key={i}>
                {d.label} — {d.status}
              </li>
            ))}
          </ul>
        </div>
      )}
      {alertDetail?.primary_account_number ? (
        <p className="text-xs text-slate-700">
          <span className="font-medium text-slate-700">Primary account (STR basis):</span>{' '}
          <span className="font-mono">{alertDetail.primary_account_number}</span>
        </p>
      ) : null}
      {(alertDetail?.linked_accounts_count ?? 0) > 1 && (
        <div className="text-xs">
          <p className="font-medium text-slate-700">Linked accounts in this grouped case</p>
          <ul className="list-disc pl-4 mt-1 text-slate-600">
            {(alertDetail?.linked_accounts ?? []).map((acc, i) => (
              <li key={`${acc.customer_id || 'cid'}:${acc.account_number || i}`}>
                <span className="font-mono">{acc.account_number || '—'}</span> ({acc.customer_name || acc.customer_id || '—'})
              </li>
            ))}
          </ul>
        </div>
      )}
      {(alertDetail?.related_transactions ?? []).length > 0 && (
        <div className="text-xs">
          <p className="font-medium text-slate-700">Related transactions (linked accounts)</p>
          <div className="mt-1 max-h-44 overflow-auto rounded border border-slate-200 bg-white">
            <table className="w-full text-xs">
              <thead className="bg-slate-100 text-slate-700">
                <tr>
                  <th className="p-2 text-left">Txn</th>
                  <th className="p-2 text-left">Type</th>
                  <th className="p-2 text-left">Amount</th>
                  <th className="p-2 text-left">From</th>
                  <th className="p-2 text-left">To</th>
                </tr>
              </thead>
              <tbody>
                {(alertDetail?.related_transactions ?? []).slice(0, 15).map((tx, i) => (
                  <tr key={`${tx.transaction_id || i}`} className="border-t border-slate-100">
                    <td className="p-2 font-mono">{tx.transaction_id || '—'}</td>
                    <td className="p-2">{String(tx.transaction_type || '').replace(/_/g, ' ') || '—'}</td>
                    <td className="p-2">
                      {tx.currency || 'NGN'} {Number(tx.amount || 0).toLocaleString('en-NG')}
                    </td>
                    <td className="p-2 font-mono">{tx.from_account || '—'}</td>
                    <td className="p-2 font-mono">{tx.to_account || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

export default function CcoReview() {
  const queryClient = useQueryClient();
  const role = useAuthStore((s) => s.user?.role);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [notesById, setNotesById] = useState<Record<string, string>>({});
  const [strSnapshotOpenId, setStrSnapshotOpenId] = useState<string | null>(null);
  const [strDraftDownloadId, setStrDraftDownloadId] = useState<string | null>(null);
  const [strDraftDownloading, setStrDraftDownloading] = useState(false);
  const [estrDraftDownloadId, setEstrDraftDownloadId] = useState<string | null>(null);
  const [otcDraftKind, setOtcDraftKind] = useState<'otc_estr' | 'otc_esar' | null>(null);
  const [estrDraftDownloading, setEstrDraftDownloading] = useState(false);
  const strSnapshotAutoOnce = useRef(false);
  const [rejectingId, setRejectingId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState('');
  const [queueSearch, setQueueSearch] = useState('');
  const [otcKindFilter, setOtcKindFilter] = useState<'all' | 'otc_estr' | 'otc_esar'>('all');
  const [hiddenRowIds, setHiddenRowIds] = useState<Record<string, true>>({});
  const [strDraftNotesById, setStrDraftNotesById] = useState<Record<string, string>>({});
  const [strPreviewById, setStrPreviewById] = useState<Record<string, string[]>>({});
  const [strDraftBusyById, setStrDraftBusyById] = useState<Record<string, boolean>>({});
  const [strDraftSaveBusyById, setStrDraftSaveBusyById] = useState<Record<string, boolean>>({});
  const [strDraftDownloadBusyById, setStrDraftDownloadBusyById] = useState<Record<string, boolean>>({});
  const [strDraftModalAlertId, setStrDraftModalAlertId] = useState<string | null>(null);
  const [strDraftModalError, setStrDraftModalError] = useState<string | null>(null);
  const [otcWordDraftModalAlertId, setOtcWordDraftModalAlertId] = useState<string | null>(null);
  const [otcWordDraftKind, setOtcWordDraftKind] = useState<'otc_estr' | 'otc_esar' | null>(null);
  const [otcWordDraftNotesById, setOtcWordDraftNotesById] = useState<Record<string, string>>({});
  const [otcWordPreviewById, setOtcWordPreviewById] = useState<Record<string, string[]>>({});
  const [otcWordDraftBusyById, setOtcWordDraftBusyById] = useState<Record<string, boolean>>({});
  const [otcWordDraftSaveBusyById, setOtcWordDraftSaveBusyById] = useState<Record<string, boolean>>({});
  const [otcWordDraftDownloadBusyById, setOtcWordDraftDownloadBusyById] = useState<Record<string, boolean>>({});
  const [otcWordDraftSavedById, setOtcWordDraftSavedById] = useState<Record<string, boolean>>({});
  const [otcWordDraftModalError, setOtcWordDraftModalError] = useState<string | null>(null);

  const allowed = canAccessCcoReviewPage(role);
  const ccoMayApprove = isCcoOrAdmin(role);

  const pendingQuery = useQuery({
    queryKey: ['alerts', 'cco-pending-str'],
    queryFn: () => alertsApi.listCcoPendingStrApprovals({ skip: 0, limit: 200 }),
    enabled: allowed && ccoMayApprove,
    refetchInterval: 4000,
    staleTime: 1500,
  });

  const pendingOtcQuery = useQuery({
    queryKey: ['alerts', 'cco-pending-otc'],
    queryFn: () => alertsApi.listCcoPendingOtcApprovals({ skip: 0, limit: 200 }),
    enabled: allowed && ccoMayApprove,
    refetchInterval: 4000,
    staleTime: 1500,
  });

  const approveMutation = useMutation({
    mutationFn: ({ alertId, notes }: { alertId: string; notes?: string }) =>
      alertsApi.ccoApproveStr(alertId, { notes }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['alerts'], exact: false });
      await queryClient.invalidateQueries({ queryKey: ['alerts-dashboard'] });
      await queryClient.invalidateQueries({ queryKey: ['alerts', 'cco-pending-str'] });
      await queryClient.invalidateQueries({ queryKey: ['reports', 'str-eligible-alerts'] });
      await queryClient.invalidateQueries({ queryKey: ['reports', 'otc-eligible'], exact: false });
    },
  });

  const approveOtcMutation = useMutation({
    mutationFn: ({ alertId, notes }: { alertId: string; notes?: string }) =>
      alertsApi.ccoApproveOtc(alertId, { notes }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['alerts'], exact: false });
      await queryClient.invalidateQueries({ queryKey: ['alerts-dashboard'] });
      await queryClient.invalidateQueries({ queryKey: ['alerts', 'cco-pending-otc'] });
      await queryClient.invalidateQueries({ queryKey: ['reports', 'otc-eligible'], exact: false });
    },
  });

  const rejectMutation = useMutation({
    mutationFn: ({ alertId, reason }: { alertId: string; reason: string }) =>
      alertsApi.ccoReject(alertId, { reason }),
    onSuccess: async (data) => {
      if (rejectingId) setHiddenRowIds((prev) => ({ ...prev, [rejectingId]: true }));
      setRejectingId(null);
      setRejectReason('');
      setMessage({
        type: 'success',
        text:
          data.email_detail ||
          'Alert rejected. The compliance officer is notified in-app when their email is on file; email sends when SMTP is configured.',
      });
      await queryClient.invalidateQueries({ queryKey: ['alerts'], exact: false });
      await queryClient.invalidateQueries({ queryKey: ['alerts-dashboard'] });
      await queryClient.invalidateQueries({ queryKey: ['alerts', 'cco-pending-str'] });
      await queryClient.invalidateQueries({ queryKey: ['alerts', 'cco-pending-otc'] });
      await queryClient.invalidateQueries({ queryKey: ['reports', 'str-eligible-alerts'] });
      await queryClient.invalidateQueries({ queryKey: ['reports', 'otc-eligible'], exact: false });
    },
    onError: (e) => {
      setMessage({
        type: 'error',
        text: e instanceof Error ? e.message : 'Rejection failed.',
      });
    },
  });

  const itemsRaw = pendingQuery.data?.items ?? [];
  const otcItemsRaw = pendingOtcQuery.data?.items ?? [];
  const ql = queueSearch.trim().toLowerCase();
  const items = useMemo(
    () =>
      itemsRaw.filter((a) => {
        if (hiddenRowIds[a.id]) return false;
        if (!ql) return true;
        const blob = `${a.id} ${a.summary || ''} ${displayCustomer(a)} ${a.transaction_id || ''}`.toLowerCase();
        return blob.includes(ql);
      }),
    [itemsRaw, hiddenRowIds, ql]
  );
  const otcItems = useMemo(
    () =>
      otcItemsRaw.filter((a) => {
        if (hiddenRowIds[a.id]) return false;
        if (otcKindFilter !== 'all' && a.otc_report_kind !== otcKindFilter) return false;
        if (!ql) return true;
        const blob = `${a.id} ${a.summary || ''} ${displayCustomer(a)} ${a.transaction_id || ''} ${a.otc_report_kind || ''}`.toLowerCase();
        return blob.includes(ql);
      }),
    [otcItemsRaw, hiddenRowIds, otcKindFilter, ql]
  );

  useEffect(() => {
    if (items.length > 0 && !strSnapshotAutoOnce.current) {
      strSnapshotAutoOnce.current = true;
      setStrSnapshotOpenId(items[0].id);
    }
  }, [items]);

  const otcPendingAlertIds = useMemo(() => (ccoMayApprove ? otcItems.map((a) => a.id) : []), [ccoMayApprove, otcItems]);
  useEffect(() => {
    if (otcPendingAlertIds.length === 0) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await reportsApi.otcWordDraftStatusBulk(otcPendingAlertIds);
        if (cancelled) return;
        setOtcWordDraftSavedById((prev) => ({ ...prev, ...(res.items || {}) }));
      } catch {
        /* best-effort */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [otcPendingAlertIds]);

  const setNote = (id: string, v: string) => {
    setNotesById((prev) => ({ ...prev, [id]: v }));
  };
  const setDraftBusy = (id: string, busy: boolean) =>
    setStrDraftBusyById((prev) => ({ ...prev, [id]: busy }));
  const isStrScaffoldDraft = (text: string) => {
    const t = String(text || '').toLowerCase();
    return (
      t.includes('suspicious transaction report') &&
      t.includes('alert:') &&
      t.includes('narrative source:') &&
      t.includes('xml payload (excerpt)')
    );
  };
  const isLowValueStrDraft = (text: string) => {
    const t = String(text || '').trim().toLowerCase();
    if (!t) return true;
    if (t === 'str draft note' || t === 'suspicious transaction report') return true;
    return t.length <= 180 && t.includes('confirmed suspicious activity') && t.includes('true positive escalation');
  };
  const editorTextFromPreview = (res: { str_notes?: string; word_preview_lines?: string[]; has_saved_draft?: boolean }) => {
    const rawNotes = String(res.str_notes || '').trim();
    const notes = isStrScaffoldDraft(rawNotes) ? '' : rawNotes;
    const fullPreview = (res.word_preview_lines || []).join('\n\n').trim();
    if (res.has_saved_draft && notes && !isLowValueStrDraft(notes)) return notes;
    if (fullPreview) return fullPreview;
    if (notes && !isLowValueStrDraft(notes)) return notes;
    return fullPreview || notes || 'STR draft note';
  };
  const setOtcWordDraftBusy = (id: string, busy: boolean) =>
    setOtcWordDraftBusyById((prev) => ({ ...prev, [id]: busy }));
  const editorTextFromOtcWordPreview = (res: {
    estr_notes?: string;
    word_preview_lines?: string[];
    has_saved_draft?: boolean;
  }) => {
    const notes = String(res.estr_notes || '').trim();
    const fullPreview = (res.word_preview_lines || []).join('\n\n').trim();
    if (res.has_saved_draft && notes) return notes;
    if (fullPreview) return fullPreview;
    if (notes) return notes;
    return fullPreview || notes || '';
  };

  if (!allowed) {
    return (
      <DashboardLayout>
        <h1 className="text-2xl font-bold text-slate-900 mb-4">CCO review queue</h1>
        <div className="p-4 bg-amber-50 border border-amber-200 rounded-lg text-amber-900 text-sm max-w-xl">
          This area is for compliance officers (OTC escalation), the Chief Compliance Officer, or an administrator. Sign in
          as <span className="font-mono">compliance.sw@demo.com</span>, <span className="font-mono">cco@demo.com</span>, or{' '}
          <span className="font-mono">admin@admin.com</span> (default passwords as seeded).
        </div>
        <Link to="/login" className="inline-block mt-4 text-blue-600 hover:underline text-sm">
          Go to login
        </Link>
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout>
      {ccoMayApprove ? (
        <>
          <h1 className="text-2xl font-bold text-slate-900 mb-2">CCO review — STR &amp; OTC reporting</h1>
          <p className="text-slate-600 text-sm mb-6 max-w-3xl">
            <strong>OTC reporting</strong> (ESTR cash path and ESAR identity path): escalated alerts with a true-positive OTC
            filing appear in the first queue until you approve OTC reporting; then compliance can generate ESTR/ESAR on{' '}
            <strong>Regulatory Reports</strong>. <strong>STR pre-approval</strong> below covers non–OTC ESTR escalations (cash OTC
            ESTR is not an STR). Email to the CCO is sent on escalation when <span className="font-mono">SMTP</span> and{' '}
            <span className="font-mono">CCO_EMAIL</span> are configured.
          </p>
        </>
      ) : (
        <>
          <h1 className="text-2xl font-bold text-slate-900 mb-2">CCO review</h1>
          <p className="text-slate-600 text-sm mb-6 max-w-3xl">
            Signed in as a compliance officer, use the <strong>Alerts</strong> page to investigate, resolve, or escalate. After
            a <strong>true-positive OTC</strong> filing, <strong>escalate</strong> the alert so the Chief Compliance Officer can
            approve OTC reporting; then <strong>Regulatory Reports</strong> will list the matter for <strong>OTC ESTR</strong> or{' '}
            <strong>OTC ESAR</strong> as appropriate.
          </p>
        </>
      )}

      {message && (
        <div
          className={`mb-4 p-3 rounded-lg text-sm ${message.type === 'success' ? 'bg-green-50 text-green-800 border border-green-200' : 'bg-red-50 text-red-800 border border-red-200'}`}
          role="alert"
        >
          {message.text}
          <button type="button" className="ml-2 underline" onClick={() => setMessage(null)}>
            Dismiss
          </button>
        </div>
      )}

      {ccoMayApprove && (
        <div className="mb-4 flex flex-wrap gap-3 items-end">
          <label className="text-xs font-medium text-slate-700">
            Quick search
            <input
              type="text"
              value={queueSearch}
              onChange={(e) => setQueueSearch(e.target.value)}
              placeholder="Search alert ID, customer, summary, txn..."
              className="mt-1 block w-72 max-w-full rounded border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="text-xs font-medium text-slate-700">
            OTC kind
            <select
              value={otcKindFilter}
              onChange={(e) => setOtcKindFilter(e.target.value as 'all' | 'otc_estr' | 'otc_esar')}
              className="mt-1 block rounded border border-slate-300 px-3 py-2 text-sm bg-white"
            >
              <option value="all">All OTC</option>
              <option value="otc_estr">OTC ESTR</option>
              <option value="otc_esar">OTC ESAR</option>
            </select>
          </label>
          <button
            type="button"
            onClick={() => {
              void pendingQuery.refetch();
              void pendingOtcQuery.refetch();
            }}
            className="px-3 py-2 text-sm rounded border border-slate-300 bg-white hover:bg-slate-50"
          >
            Refresh now
          </button>
        </div>
      )}

      {ccoMayApprove && pendingOtcQuery.isLoading && <p className="text-slate-500 text-sm">Loading OTC approval queue…</p>}
      {ccoMayApprove && pendingOtcQuery.isError && (
        <p className="text-red-600 text-sm">
          {(pendingOtcQuery.error as Error).message || 'Could not load OTC pending approvals.'}
        </p>
      )}

      {ccoMayApprove && !pendingOtcQuery.isLoading && !pendingOtcQuery.isError && otcItems.length > 0 && (
        <>
          <h2 className="text-lg font-semibold text-slate-900 mb-2">Approve OTC reporting (ESTR / ESAR)</h2>
          <p className="text-sm text-slate-600 mb-4 max-w-3xl">
            These alerts have a <strong>true-positive</strong> OTC filing and were <strong>escalated</strong> by compliance.
            Approve to unlock generation on Regulatory Reports.
          </p>
          <ul className="space-y-4 mb-10">
            {otcItems.map((a: Alert) => (
              <li key={a.id} className="bg-white rounded-lg border border-violet-200 shadow-sm p-4">
                <div className="flex flex-wrap justify-between gap-2">
                  <div className="min-w-0">
                    <p className="font-medium text-slate-900">{a.summary ?? 'OTC matter'}</p>
                    <p className="text-xs text-slate-500 mt-1 font-mono">
                      {a.id} · {displayCustomer(a)} · {a.otc_report_kind === 'otc_estr' ? 'OTC ESTR (cash)' : 'OTC ESAR'}
                    </p>
                    {(a.linked_accounts_count ?? 0) > 1 ? (
                      <p className="text-xs text-indigo-700 mt-1">
                        {a.linked_accounts_count} linked accounts involved (BVN grouped case)
                      </p>
                    ) : null}
                    {displayChannel(a) ? (
                      <p className="text-xs text-slate-500 mt-1">Channel: {displayChannel(a)}</p>
                    ) : null}
                  </div>
                  <button
                    type="button"
                    disabled={approveOtcMutation.isPending || rejectMutation.isPending}
                    onClick={() => {
                      setRejectingId(a.id);
                      setRejectReason('');
                    }}
                    className="shrink-0 px-4 py-2 text-sm bg-rose-600 text-white rounded-lg hover:bg-rose-700 disabled:opacity-50"
                  >
                    Reject alert
                  </button>
                  <button
                    type="button"
                    disabled={approveOtcMutation.isPending}
                    onClick={async () => {
                      setMessage(null);
                      const notes = (notesById[`otc-${a.id}`] ?? '').trim() || undefined;
                      try {
                        const res = await approveOtcMutation.mutateAsync({ alertId: a.id, notes });
                        setHiddenRowIds((prev) => ({ ...prev, [a.id]: true }));
                        const ridRaw = res.otc_draft_report_id || res.estr_draft_report_id || null;
                        const rid = ridRaw ? String(ridRaw) : null;
                        setOtcDraftKind((a.otc_report_kind as 'otc_estr' | 'otc_esar') || null);
                        setEstrDraftDownloadId(rid);
                        setMessage({
                          type: 'success',
                          text:
                            'OTC reporting approved. Compliance can generate ESTR or ESAR on Regulatory Reports. ' +
                            (rid
                              ? `A preliminary ${a.otc_report_kind === 'otc_esar' ? 'OTC ESAR' : 'OTC ESTR'} draft was created (${rid}). You can download it below.`
                              : ''),
                        });
                      } catch (e) {
                        setMessage({
                          type: 'error',
                          text: e instanceof Error ? e.message : 'Approval failed.',
                        });
                      }
                    }}
                    className="shrink-0 px-4 py-2 text-sm bg-violet-700 text-white rounded-lg hover:bg-violet-800 disabled:opacity-50"
                  >
                    Approve OTC reporting
                  </button>
                </div>
                <label className="block mt-3 text-xs font-medium text-slate-700">
                  Optional notes
                  <textarea
                    value={notesById[`otc-${a.id}`] ?? ''}
                    onChange={(e) => setNote(`otc-${a.id}`, e.target.value)}
                    rows={2}
                    className="mt-1 block w-full rounded border border-slate-300 px-3 py-2 text-sm"
                  />
                </label>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    disabled={!!otcWordDraftBusyById[a.id]}
                    onClick={async () => {
                      setOtcWordDraftModalAlertId(a.id);
                      setOtcWordDraftKind(a.otc_report_kind === 'otc_esar' ? 'otc_esar' : 'otc_estr');
                      setOtcWordDraftBusy(a.id, true);
                      try {
                        const res = await reportsApi.getOtcWordDraftPreview(a.id);
                        setOtcWordDraftModalError(res.preview_warning ? res.preview_warning : null);
                        setOtcWordDraftNotesById((prev) => ({
                          ...prev,
                          [a.id]: editorTextFromOtcWordPreview(res),
                        }));
                        setOtcWordPreviewById((prev) => ({ ...prev, [a.id]: res.word_preview_lines || [] }));
                      } catch (e) {
                        setOtcWordDraftModalError(
                          e instanceof Error ? e.message : 'Could not load OTC Word draft preview.'
                        );
                      } finally {
                        setOtcWordDraftBusy(a.id, false);
                      }
                    }}
                    className="px-3 py-1.5 text-xs rounded bg-violet-700 text-white disabled:opacity-50"
                  >
                    {otcWordDraftBusyById[a.id] ? 'Loading…' : 'Load draft preview'}
                  </button>
                  {otcWordDraftSavedById[a.id] ? (
                    <span className="text-[11px] text-emerald-700 font-medium">Draft saved</span>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}

      {ccoMayApprove && !pendingOtcQuery.isLoading && !pendingOtcQuery.isError && otcItems.length === 0 && (
        <p className="text-slate-500 text-sm mb-8">No escalated OTC filings are waiting for your approval.</p>
      )}

      {ccoMayApprove && strDraftDownloadId && (
        <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-950">
          <span className="font-mono text-xs">{strDraftDownloadId}</span>
          <button
            type="button"
            disabled={strDraftDownloading}
            onClick={async () => {
              setStrDraftDownloading(true);
              try {
                await reportsApi.downloadSTR(strDraftDownloadId, 'word');
              } catch (e) {
                setMessage({
                  type: 'error',
                  text: e instanceof Error ? e.message : 'Download failed.',
                });
              } finally {
                setStrDraftDownloading(false);
              }
            }}
            className="px-3 py-1.5 rounded-lg bg-emerald-700 text-white text-xs hover:bg-emerald-800 disabled:opacity-50"
          >
            {strDraftDownloading ? 'Downloading…' : 'Download preliminary STR (Word)'}
          </button>
          <button type="button" className="text-xs underline text-emerald-900" onClick={() => setStrDraftDownloadId(null)}>
            Dismiss
          </button>
        </div>
      )}

      {ccoMayApprove && estrDraftDownloadId && (
        <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-sm text-violet-950">
          <span className="font-mono text-xs">{estrDraftDownloadId}</span>
          <button
            type="button"
            disabled={estrDraftDownloading}
            onClick={async () => {
              setEstrDraftDownloading(true);
              try {
                await reportsApi.downloadESTR(estrDraftDownloadId, 'word');
              } catch (e) {
                setMessage({
                  type: 'error',
                  text: e instanceof Error ? e.message : 'ESTR download failed.',
                });
              } finally {
                setEstrDraftDownloading(false);
              }
            }}
            className="px-3 py-1.5 rounded-lg bg-violet-700 text-white text-xs hover:bg-violet-800 disabled:opacity-50"
          >
            {estrDraftDownloading
              ? 'Downloading…'
              : `Download preliminary ${otcDraftKind === 'otc_esar' ? 'OTC ESAR' : 'OTC ESTR'} (Word)`}
          </button>
          <button type="button" className="text-xs underline text-violet-900" onClick={() => setEstrDraftDownloadId(null)}>
            Dismiss
          </button>
        </div>
      )}

      {ccoMayApprove && pendingQuery.isLoading && <p className="text-slate-500 text-sm">Loading STR queue…</p>}
      {ccoMayApprove && pendingQuery.isError && (
        <p className="text-red-600 text-sm">
          {(pendingQuery.error as Error).message || 'Could not load pending approvals.'}
        </p>
      )}

      {ccoMayApprove && !pendingQuery.isLoading && !pendingQuery.isError && items.length === 0 && (
        <p className="text-slate-500 text-sm">No alerts are waiting for STR pre-approval.</p>
      )}

      {ccoMayApprove && items.length > 0 && (
        <>
          <h2 className="text-lg font-semibold text-slate-900 mb-2 mt-2">STR pre-approval</h2>
        <ul className="space-y-4">
          {items.map((a: Alert) => (
            <li key={a.id} className="bg-white rounded-lg border border-slate-200 shadow-sm p-4">
              <div className="flex flex-wrap justify-between gap-2">
                <div className="min-w-0">
                  <p className="font-medium text-slate-900">{a.summary ?? 'Suspicious activity'}</p>
                  <p className="text-xs text-slate-500 mt-1 font-mono">
                    {a.id} · {displayCustomer(a)} · {a.transaction_id}
                  </p>
                  {(a.linked_accounts_count ?? 0) > 1 ? (
                    <p className="text-xs text-indigo-700 mt-1">
                      {a.linked_accounts_count} linked accounts involved (BVN grouped case)
                    </p>
                  ) : null}
                  {displayChannel(a) ? (
                    <p className="text-xs text-slate-500 mt-1">Channel: {displayChannel(a)}</p>
                  ) : null}
                  <p className="text-xs text-slate-600 mt-1 capitalize">
                    Escalation: {a.escalation_classification?.replace(/_/g, ' ') ?? '—'} ·{' '}
                    {(a.severity * 100).toFixed(0)}% risk
                  </p>
                  {(a.escalation_reason_notes || '').trim() ? (
                    <div className="mt-2 rounded-md bg-amber-50 border border-amber-100 px-2 py-2 text-xs text-amber-950">
                      <span className="font-semibold text-amber-900">Compliance reason for CCO review:</span>{' '}
                      {a.escalation_reason_notes}
                    </div>
                  ) : (
                    <p className="mt-2 text-xs text-slate-500 italic">
                      No escalation reason text on file (legacy alert or true-positive path without free-text reason).
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  disabled={approveMutation.isPending || rejectMutation.isPending}
                  onClick={() => {
                    setRejectingId(a.id);
                    setRejectReason('');
                  }}
                  className="shrink-0 px-4 py-2 text-sm bg-rose-600 text-white rounded-lg hover:bg-rose-700 disabled:opacity-50"
                >
                  Reject alert
                </button>
                <button
                  type="button"
                  disabled={approveMutation.isPending}
                  onClick={async () => {
                    setMessage(null);
                    try {
                      const res = await approveMutation.mutateAsync({ alertId: a.id });
                      setHiddenRowIds((prev) => ({ ...prev, [a.id]: true }));
                      const rid = res.str_draft_report_id;
                      setStrDraftDownloadId(rid ? String(rid) : null);
                      setMessage({
                        type: 'success',
                        text:
                          'Approval recorded. Compliance can generate or refine STR on Regulatory reports. ' +
                          (rid
                            ? `A preliminary STR Word draft was created (${rid}). If SMTP and CCO_EMAIL are set, the same Word file was emailed to the CCO inbox. You can also download the same file below.`
                            : 'If SMTP is configured, check your email for the preliminary STR Word attachment.'),
                      });
                    } catch (e) {
                      setMessage({
                        type: 'error',
                        text: e instanceof Error ? e.message : 'Approval failed.',
                      });
                    }
                  }}
                  className="shrink-0 px-4 py-2 text-sm bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50"
                >
                  Approve for STR
                </button>
              </div>
              <button
                type="button"
                className="mt-2 text-xs font-medium text-blue-700 hover:underline"
                onClick={() => setStrSnapshotOpenId((id) => (id === a.id ? null : a.id))}
              >
                {strSnapshotOpenId === a.id ? 'Hide' : 'Show'} customer, occupation, suspicious transaction, and snapshot
              </button>
              <div className="mt-3">
                <button
                  type="button"
                  disabled={!!strDraftBusyById[a.id]}
                  onClick={async () => {
                    setStrDraftModalAlertId(a.id);
                    setDraftBusy(a.id, true);
                    try {
                      const res = await reportsApi.getSTRDraftPreview(a.id);
                      setStrDraftModalError(null);
                      setStrDraftNotesById((prev) => ({ ...prev, [a.id]: editorTextFromPreview(res) }));
                      setStrPreviewById((prev) => ({ ...prev, [a.id]: res.word_preview_lines || [] }));
                    } catch (e) {
                      setStrDraftModalError(e instanceof Error ? e.message : 'Could not load STR draft preview.');
                    } finally {
                      setDraftBusy(a.id, false);
                    }
                  }}
                  className="px-3 py-1.5 text-xs rounded bg-indigo-600 text-white disabled:opacity-50"
                >
                  {strDraftBusyById[a.id] ? 'Loading…' : 'Load draft preview'}
                </button>
              </div>
              <SnapshotPanel alertId={a.id} open={strSnapshotOpenId === a.id} />
            </li>
          ))}
        </ul>
        </>
      )}

      <p className="mt-8 text-sm flex flex-wrap gap-4">
        <Link to="/reports" className="text-blue-600 hover:underline">
          Open Reports (STR, SAR, ESTR)
        </Link>
      </p>

      {strDraftModalAlertId && ccoMayApprove && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/50"
          onClick={() =>
            !strDraftBusyById[strDraftModalAlertId] &&
            !strDraftSaveBusyById[strDraftModalAlertId] &&
            setStrDraftModalAlertId(null)
          }
          role="dialog"
          aria-modal="true"
          aria-labelledby="str-draft-modal-title"
        >
          <div className="bg-white rounded-xl shadow-xl max-w-6xl w-full p-6" onClick={(e) => e.stopPropagation()}>
            <h2 id="str-draft-modal-title" className="text-lg font-semibold text-slate-900 mb-2">
              Live STR draft edit before approval
            </h2>
            <p className="text-xs text-slate-600 mb-3 font-mono">Alert: {strDraftModalAlertId}</p>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <div>
                <p className="text-xs font-semibold text-slate-700 mb-1">Editor</p>
                <textarea
                  value={strDraftNotesById[strDraftModalAlertId] ?? ''}
                  onChange={(e) =>
                    setStrDraftNotesById((prev) => ({
                      ...prev,
                      [strDraftModalAlertId]: e.target.value,
                    }))
                  }
                  rows={14}
                  placeholder="Edit draft notes used for STR Word preview and post-approval generation..."
                  className="w-full rounded border border-indigo-300 px-3 py-2 text-sm bg-white"
                />
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={!!strDraftBusyById[strDraftModalAlertId]}
                    onClick={async () => {
                      const aid = strDraftModalAlertId;
                      if (!aid) return;
                      setDraftBusy(aid, true);
                      try {
                        const res = await reportsApi.getSTRDraftPreview(aid);
                        setStrDraftModalError(null);
                        setStrDraftNotesById((prev) => ({ ...prev, [aid]: editorTextFromPreview(res) }));
                        setStrPreviewById((prev) => ({ ...prev, [aid]: res.word_preview_lines || [] }));
                      } catch (e) {
                        setStrDraftModalError(e instanceof Error ? e.message : 'Could not refresh STR draft preview.');
                      } finally {
                        setDraftBusy(aid, false);
                      }
                    }}
                    className="px-3 py-1.5 text-xs rounded bg-indigo-600 text-white disabled:opacity-50"
                  >
                    {strDraftBusyById[strDraftModalAlertId] ? 'Refreshing…' : 'Refresh preview'}
                  </button>
                  <button
                    type="button"
                    disabled={
                      !!strDraftBusyById[strDraftModalAlertId] ||
                      !!strDraftSaveBusyById[strDraftModalAlertId] ||
                      !(strDraftNotesById[strDraftModalAlertId] || '').trim()
                    }
                    onClick={async () => {
                      const aid = strDraftModalAlertId;
                      if (!aid) return;
                      const v = (strDraftNotesById[aid] || '').trim();
                      if (!v) return;
                      if (isStrScaffoldDraft(v) || isLowValueStrDraft(v)) {
                        setStrDraftModalError('This draft text is still placeholder content. Click "Refresh preview", then edit and save real report text.');
                        return;
                      }
                      setStrDraftSaveBusyById((prev) => ({ ...prev, [aid]: true }));
                      try {
                        await reportsApi.saveSTRDraft(aid, { str_notes: v });
                        const res = await reportsApi.getSTRDraftPreview(aid);
                        setStrPreviewById((prev) => ({ ...prev, [aid]: res.word_preview_lines || [] }));
                        setStrDraftModalError(null);
                        setMessage({
                          type: 'success',
                          text: 'STR draft edits saved. Approval will keep and pass these edits to Compliance generation.',
                        });
                      } catch (e) {
                        setStrDraftModalError(e instanceof Error ? e.message : 'Could not save STR draft edits.');
                      } finally {
                        setStrDraftSaveBusyById((prev) => ({ ...prev, [aid]: false }));
                      }
                    }}
                    className="px-3 py-1.5 text-xs rounded bg-emerald-600 text-white disabled:opacity-50"
                  >
                    {strDraftSaveBusyById[strDraftModalAlertId] ? 'Saving…' : 'Save draft edits'}
                  </button>
                  <button
                    type="button"
                    disabled={!!strDraftDownloadBusyById[strDraftModalAlertId]}
                    onClick={async () => {
                      const aid = strDraftModalAlertId;
                      if (!aid) return;
                      setStrDraftDownloadBusyById((prev) => ({ ...prev, [aid]: true }));
                      try {
                        await reportsApi.downloadSTRDraftPreview(aid);
                        setStrDraftModalError(null);
                      } catch (e) {
                        setStrDraftModalError(e instanceof Error ? e.message : 'Could not download preview.');
                      } finally {
                        setStrDraftDownloadBusyById((prev) => ({ ...prev, [aid]: false }));
                      }
                    }}
                    className="px-3 py-1.5 text-xs rounded bg-slate-700 text-white disabled:opacity-50"
                  >
                    {strDraftDownloadBusyById[strDraftModalAlertId] ? 'Downloading…' : 'Download preview (.docx)'}
                  </button>
                  <button
                    type="button"
                    disabled={!!strDraftBusyById[strDraftModalAlertId] || !!strDraftSaveBusyById[strDraftModalAlertId]}
                    onClick={async () => {
                      const aid = strDraftModalAlertId;
                      if (!aid) return;
                      setDraftBusy(aid, true);
                      try {
                        await reportsApi.deleteSTRDraft(aid);
                        const res = await reportsApi.getSTRDraftPreview(aid);
                        setStrDraftNotesById((prev) => ({ ...prev, [aid]: editorTextFromPreview(res) }));
                        setStrPreviewById((prev) => ({ ...prev, [aid]: res.word_preview_lines || [] }));
                        setStrDraftModalError(null);
                      } catch (e) {
                        setStrDraftModalError(e instanceof Error ? e.message : 'Could not reset saved draft.');
                      } finally {
                        setDraftBusy(aid, false);
                      }
                    }}
                    className="px-3 py-1.5 text-xs rounded bg-amber-600 text-white disabled:opacity-50"
                  >
                    Reset saved draft
                  </button>
                  <button
                    type="button"
                    disabled={
                      approveMutation.isPending ||
                      !!strDraftBusyById[strDraftModalAlertId] ||
                      !!strDraftSaveBusyById[strDraftModalAlertId]
                    }
                    onClick={async () => {
                      const aid = strDraftModalAlertId;
                      if (!aid) return;
                      const v = (strDraftNotesById[aid] || '').trim();
                      try {
                        if (v) await reportsApi.saveSTRDraft(aid, { str_notes: v });
                        const res = await approveMutation.mutateAsync({ alertId: aid });
                        setHiddenRowIds((prev) => ({ ...prev, [aid]: true }));
                        setStrDraftModalAlertId(null);
                        const rid = res.str_draft_report_id;
                        setStrDraftDownloadId(rid ? String(rid) : null);
                        setMessage({
                          type: 'success',
                          text:
                            'Approved for STR from the modal. ' +
                            (rid ? `Preliminary STR draft created (${rid}).` : ''),
                        });
                      } catch (e) {
                        setStrDraftModalError(e instanceof Error ? e.message : 'Could not approve STR.');
                      }
                    }}
                    className="px-3 py-1.5 text-xs rounded bg-emerald-700 text-white disabled:opacity-50"
                  >
                    {approveMutation.isPending ? 'Approving…' : 'Approve for STR'}
                  </button>
                </div>
              </div>
              <div>
                <p className="text-xs font-semibold text-slate-700 mb-1">Word preview</p>
                <div className="h-full min-h-[290px] max-h-[460px] overflow-auto rounded border border-indigo-200 bg-slate-50 p-3 text-xs whitespace-pre-wrap">
                  {(strDraftNotesById[strDraftModalAlertId] || '').trim()
                    ? (strDraftNotesById[strDraftModalAlertId] || '').trim()
                    : (strPreviewById[strDraftModalAlertId] || []).length > 0
                    ? (strPreviewById[strDraftModalAlertId] || []).join('\n\n')
                    : 'No preview loaded yet. Click "Refresh preview".'}
                </div>
              </div>
            </div>
            {strDraftModalError ? (
              <p className="mt-3 text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded px-2 py-1">
                {strDraftModalError}
              </p>
            ) : null}
            <div className="mt-4 flex justify-end">
              <button
                type="button"
                onClick={() => setStrDraftModalAlertId(null)}
                className="px-4 py-2 text-sm rounded-lg border border-slate-300 bg-white hover:bg-slate-50"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {otcWordDraftModalAlertId && ccoMayApprove && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/50"
          onClick={() =>
            !otcWordDraftBusyById[otcWordDraftModalAlertId] &&
            !otcWordDraftSaveBusyById[otcWordDraftModalAlertId] &&
            setOtcWordDraftModalAlertId(null)
          }
          role="dialog"
          aria-modal="true"
          aria-labelledby="cco-otc-word-draft-title"
        >
          <div className="bg-white rounded-xl shadow-xl max-w-6xl w-full p-6" onClick={(e) => e.stopPropagation()}>
            <h2 id="cco-otc-word-draft-title" className="text-lg font-semibold text-slate-900 mb-2">
              Live OTC {otcWordDraftKind === 'otc_esar' ? 'ESAR' : 'ESTR'} Word draft (pre-approval)
            </h2>
            <p className="text-xs text-slate-600 mb-3 font-mono">Alert: {otcWordDraftModalAlertId}</p>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <div>
                <p className="text-xs font-semibold text-slate-700 mb-1">Editor</p>
                <textarea
                  value={otcWordDraftNotesById[otcWordDraftModalAlertId] ?? ''}
                  onChange={(e) =>
                    setOtcWordDraftNotesById((prev) => ({
                      ...prev,
                      [otcWordDraftModalAlertId]: e.target.value,
                    }))
                  }
                  rows={14}
                  placeholder="Extension narrative / reasons for filing…"
                  className="w-full rounded border border-violet-300 px-3 py-2 text-sm bg-white"
                />
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={!!otcWordDraftBusyById[otcWordDraftModalAlertId]}
                    onClick={async () => {
                      const aid = otcWordDraftModalAlertId;
                      if (!aid) return;
                      setOtcWordDraftBusy(aid, true);
                      try {
                        const res = await reportsApi.getOtcWordDraftPreview(aid);
                        setOtcWordDraftModalError(res.preview_warning ? res.preview_warning : null);
                        setOtcWordDraftNotesById((prev) => ({ ...prev, [aid]: editorTextFromOtcWordPreview(res) }));
                        setOtcWordPreviewById((prev) => ({ ...prev, [aid]: res.word_preview_lines || [] }));
                      } catch (e) {
                        setOtcWordDraftModalError(e instanceof Error ? e.message : 'Could not refresh OTC draft preview.');
                      } finally {
                        setOtcWordDraftBusy(aid, false);
                      }
                    }}
                    className="px-3 py-1.5 text-xs rounded bg-violet-600 text-white disabled:opacity-50"
                  >
                    {otcWordDraftBusyById[otcWordDraftModalAlertId] ? 'Refreshing…' : 'Refresh preview'}
                  </button>
                  <button
                    type="button"
                    disabled={
                      !!otcWordDraftBusyById[otcWordDraftModalAlertId] ||
                      !!otcWordDraftSaveBusyById[otcWordDraftModalAlertId] ||
                      !(otcWordDraftNotesById[otcWordDraftModalAlertId] || '').trim()
                    }
                    onClick={async () => {
                      const aid = otcWordDraftModalAlertId;
                      if (!aid) return;
                      const v = (otcWordDraftNotesById[aid] || '').trim();
                      if (!v) return;
                      setOtcWordDraftSaveBusyById((prev) => ({ ...prev, [aid]: true }));
                      try {
                        await reportsApi.saveOtcWordDraft(aid, { estr_notes: v });
                        const res = await reportsApi.getOtcWordDraftPreview(aid);
                        setOtcWordPreviewById((prev) => ({ ...prev, [aid]: res.word_preview_lines || [] }));
                        setOtcWordDraftSavedById((prev) => ({ ...prev, [aid]: true }));
                        setOtcWordDraftModalError(res.preview_warning ? res.preview_warning : null);
                        setMessage({
                          type: 'success',
                          text: 'OTC Word draft saved. Approval passes these notes to Regulatory Reports generation.',
                        });
                      } catch (e) {
                        setOtcWordDraftModalError(e instanceof Error ? e.message : 'Could not save OTC draft edits.');
                      } finally {
                        setOtcWordDraftSaveBusyById((prev) => ({ ...prev, [aid]: false }));
                      }
                    }}
                    className="px-3 py-1.5 text-xs rounded bg-emerald-600 text-white disabled:opacity-50"
                  >
                    {otcWordDraftSaveBusyById[otcWordDraftModalAlertId] ? 'Saving…' : 'Save draft edits'}
                  </button>
                  <button
                    type="button"
                    disabled={!!otcWordDraftDownloadBusyById[otcWordDraftModalAlertId]}
                    onClick={async () => {
                      const aid = otcWordDraftModalAlertId;
                      if (!aid) return;
                      setOtcWordDraftDownloadBusyById((prev) => ({ ...prev, [aid]: true }));
                      try {
                        await reportsApi.downloadOtcWordDraftPreview(aid);
                        setOtcWordDraftModalError(null);
                      } catch (e) {
                        setOtcWordDraftModalError(e instanceof Error ? e.message : 'Could not download preview.');
                      } finally {
                        setOtcWordDraftDownloadBusyById((prev) => ({ ...prev, [aid]: false }));
                      }
                    }}
                    className="px-3 py-1.5 text-xs rounded bg-slate-700 text-white disabled:opacity-50"
                  >
                    {otcWordDraftDownloadBusyById[otcWordDraftModalAlertId]
                      ? 'Downloading…'
                      : 'Download preview (.docx)'}
                  </button>
                  <button
                    type="button"
                    disabled={
                      approveOtcMutation.isPending ||
                      !!otcWordDraftBusyById[otcWordDraftModalAlertId] ||
                      !!otcWordDraftSaveBusyById[otcWordDraftModalAlertId]
                    }
                    onClick={async () => {
                      const aid = otcWordDraftModalAlertId;
                      if (!aid) return;
                      const v = (otcWordDraftNotesById[aid] || '').trim();
                      setMessage(null);
                      try {
                        if (v) await reportsApi.saveOtcWordDraft(aid, { estr_notes: v });
                        const notes = (notesById[`otc-${aid}`] ?? '').trim() || undefined;
                        const res = await approveOtcMutation.mutateAsync({ alertId: aid, notes });
                        setHiddenRowIds((prev) => ({ ...prev, [aid]: true }));
                        setOtcWordDraftModalAlertId(null);
                        const ridRaw = res.otc_draft_report_id || res.estr_draft_report_id || null;
                        const rid = ridRaw ? String(ridRaw) : null;
                        setOtcDraftKind(otcWordDraftKind);
                        setEstrDraftDownloadId(rid);
                        setMessage({
                          type: 'success',
                          text:
                            'OTC reporting approved from the draft modal. Compliance can generate the return on Regulatory Reports. ' +
                            (rid ? `Preliminary draft: ${rid}.` : ''),
                        });
                      } catch (e) {
                        setOtcWordDraftModalError(e instanceof Error ? e.message : 'Could not approve OTC reporting.');
                      }
                    }}
                    className="px-3 py-1.5 text-xs rounded bg-emerald-700 text-white disabled:opacity-50"
                  >
                    {approveOtcMutation.isPending ? 'Approving…' : 'Approve OTC reporting'}
                  </button>
                </div>
              </div>
              <div>
                <p className="text-xs font-semibold text-slate-700 mb-1">Word preview</p>
                <div className="h-full min-h-[290px] max-h-[460px] overflow-auto rounded border border-violet-200 bg-slate-50 p-3 text-xs whitespace-pre-wrap">
                  {(otcWordDraftNotesById[otcWordDraftModalAlertId] || '').trim()
                    ? (otcWordDraftNotesById[otcWordDraftModalAlertId] || '').trim()
                    : (otcWordPreviewById[otcWordDraftModalAlertId] || []).length > 0
                    ? (otcWordPreviewById[otcWordDraftModalAlertId] || []).join('\n\n')
                    : 'No preview loaded yet.'}
                </div>
              </div>
            </div>
            {otcWordDraftModalError ? (
              <p className="mt-3 text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded px-2 py-1">
                {otcWordDraftModalError}
              </p>
            ) : null}
            <div className="mt-4 flex justify-end">
              <button
                type="button"
                onClick={() => setOtcWordDraftModalAlertId(null)}
                className="px-4 py-2 text-sm rounded-lg border border-slate-300 bg-white hover:bg-slate-50"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {rejectingId && ccoMayApprove && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/50"
          onClick={() => !rejectMutation.isPending && setRejectingId(null)}
          role="dialog"
          aria-modal="true"
          aria-labelledby="cco-reject-title"
        >
          <div
            className="bg-white rounded-xl shadow-xl max-w-lg w-full p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id="cco-reject-title" className="text-lg font-semibold text-slate-900 mb-2">
              Reject alert
            </h2>
            <p className="text-xs text-slate-600 mb-3">
              The alert status will be set to <strong>rejected</strong>. The compliance officer who last acted (escalate,
              investigate, resolve, or OTC filing) receives an in-app notification and an email when SMTP is configured and
              their login email is on file.
            </p>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Rejection reason (required)
              <textarea
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                rows={5}
                className="mt-1 block w-full rounded border border-slate-300 px-3 py-2 text-sm"
                placeholder="Explain why this escalation or alert is not approved for STR / OTC reporting."
              />
            </label>
            <div className="mt-4 flex flex-wrap justify-end gap-2">
              <button
                type="button"
                disabled={rejectMutation.isPending}
                onClick={() => setRejectingId(null)}
                className="px-4 py-2 text-sm rounded-lg border border-slate-300 bg-white hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={rejectMutation.isPending || rejectReason.trim().length < 3}
                onClick={() => {
                  if (!rejectingId) return;
                  rejectMutation.mutate({ alertId: rejectingId, reason: rejectReason.trim() });
                }}
                className="px-4 py-2 text-sm rounded-lg bg-rose-700 text-white hover:bg-rose-800 disabled:opacity-50"
              >
                {rejectMutation.isPending ? 'Rejecting…' : 'Confirm rejection'}
              </button>
            </div>
          </div>
        </div>
      )}
    </DashboardLayout>
  );
}
