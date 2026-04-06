import { useEffect, useRef, useState } from 'react';
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

function SnapshotPanel({ alertId, open }: { alertId: string; open: boolean }) {
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
  const strSnapshotAutoOnce = useRef(false);
  const [rejectingId, setRejectingId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState('');

  const allowed = canAccessCcoReviewPage(role);
  const ccoMayApprove = isCcoOrAdmin(role);

  const pendingQuery = useQuery({
    queryKey: ['alerts', 'cco-pending-str'],
    queryFn: () => alertsApi.listCcoPendingStrApprovals({ skip: 0, limit: 200 }),
    enabled: allowed && ccoMayApprove,
  });

  const pendingOtcQuery = useQuery({
    queryKey: ['alerts', 'cco-pending-otc'],
    queryFn: () => alertsApi.listCcoPendingOtcApprovals({ skip: 0, limit: 200 }),
    enabled: allowed && ccoMayApprove,
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

  const items = pendingQuery.data?.items ?? [];
  const otcItems = pendingOtcQuery.data?.items ?? [];

  useEffect(() => {
    if (items.length > 0 && !strSnapshotAutoOnce.current) {
      strSnapshotAutoOnce.current = true;
      setStrSnapshotOpenId(items[0].id);
    }
  }, [items]);

  const setNote = (id: string, v: string) => {
    setNotesById((prev) => ({ ...prev, [id]: v }));
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
                      {a.id} · {a.customer_id} · {a.otc_report_kind === 'otc_estr' ? 'OTC ESTR (cash)' : 'OTC ESAR'}
                    </p>
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
                        await approveOtcMutation.mutateAsync({ alertId: a.id, notes });
                        setMessage({
                          type: 'success',
                          text: 'OTC reporting approved. Compliance can generate ESTR or ESAR on Regulatory Reports.',
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
                    {a.id} · {a.customer_id} · {a.transaction_id}
                  </p>
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
