import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import DashboardLayout from '../components/layout/DashboardLayout';
import { customersApi } from '../services/api';

function toCsv(rows: Array<Record<string, unknown>>): string {
  if (!rows.length) return 'customer_id,customer_name,account_number,risk_rating,last_review_date,next_review_due_at,review_status\n';
  const headers = Object.keys(rows[0]);
  const esc = (v: unknown) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const body = rows.map((r) => headers.map((h) => esc(r[h])).join(',')).join('\n');
  return `${headers.join(',')}\n${body}\n`;
}

function downloadCsv(filename: string, csv: string) {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export default function RiskReviews() {
  const [daysAhead, setDaysAhead] = useState(0);
  const [rmEmail, setRmEmail] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  const dueQ = useQuery({
    queryKey: ['risk-reviews-due', daysAhead],
    queryFn: () => customersApi.listDueRiskReviews({ days_ahead: daysAhead, limit: 1000 }),
  });

  const customersQ = useQuery({
    queryKey: ['customers-risk-review-dashboard'],
    queryFn: () => customersApi.list({ page: 1, page_size: 200 }),
  });

  const dueItems = (dueQ.data?.items ?? []) as Array<Record<string, unknown>>;
  const reviewedRows = useMemo(
    () => (customersQ.data?.items ?? []).filter((x) => x.review_status === 'reviewed'),
    [customersQ.data?.items]
  );

  async function sendBulkDueAlerts() {
    setBusy('bulk');
    setMsg(null);
    try {
      const out = await customersApi.sendDueRiskReviewAlerts({
        relationship_manager_email: rmEmail || undefined,
        mode: 'bulk',
      });
      setMsg({ type: 'ok', text: `Bulk alert dispatch done: ${out.sent.length} sent, ${out.failures.length} failed.` });
      await dueQ.refetch();
      await customersQ.refetch();
    } catch (err) {
      setMsg({ type: 'err', text: (err as Error).message });
    } finally {
      setBusy(null);
    }
  }

  async function sendSingleDueAlert(customerId: string) {
    setBusy(`single-${customerId}`);
    setMsg(null);
    try {
      const out = await customersApi.sendDueRiskReviewAlerts({
        customer_ids: [customerId],
        relationship_manager_email: rmEmail || undefined,
        mode: 'individual',
      });
      setMsg({ type: 'ok', text: `Alert sent: ${out.sent.length} success, ${out.failures.length} failed.` });
      await dueQ.refetch();
      await customersQ.refetch();
    } catch (err) {
      setMsg({ type: 'err', text: (err as Error).message });
    } finally {
      setBusy(null);
    }
  }

  const exportRows = (customersQ.data?.items ?? []).map((r) => ({
    customer_id: r.customer_id,
    customer_name: r.customer_name,
    account_number: r.account_number,
    risk_rating: r.risk_rating ?? '',
    last_review_date: r.last_review_date ?? '',
    next_review_due_at: r.next_review_due_at ?? '',
    review_status: r.review_status ?? '',
  }));

  return (
    <DashboardLayout>
      <h1 className="text-2xl font-bold text-slate-900 mb-2">Risk review dashboard</h1>
      <p className="text-sm text-slate-600 mb-5">
        Tracks customers due for periodic review, reviewed customers, and alerting to CCO / relationship manager with
        audit logging for regulator checks.
      </p>

      {msg && (
        <div
          className={`mb-4 p-3 rounded-lg text-sm ${
            msg.type === 'ok'
              ? 'bg-emerald-50 text-emerald-900 border border-emerald-200'
              : 'bg-red-50 text-red-900 border border-red-200'
          }`}
        >
          {msg.text}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        <div className="bg-white border border-slate-200 rounded-lg p-4">
          <div className="text-xs text-slate-500">Due now / horizon</div>
          <div className="text-2xl font-semibold text-rose-700">{dueItems.length}</div>
        </div>
        <div className="bg-white border border-slate-200 rounded-lg p-4">
          <div className="text-xs text-slate-500">Reviewed customers</div>
          <div className="text-2xl font-semibold text-emerald-700">{reviewedRows.length}</div>
        </div>
        <div className="bg-white border border-slate-200 rounded-lg p-4">
          <div className="text-xs text-slate-500">Total monitored</div>
          <div className="text-2xl font-semibold text-slate-800">{customersQ.data?.items?.length ?? 0}</div>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-lg p-4 mb-4 flex flex-wrap gap-2 items-end">
        <label className="text-xs text-slate-700">
          Due horizon (days)
          <input
            type="number"
            min={0}
            max={365}
            className="block mt-1 rounded border border-slate-300 px-2 py-1 w-32"
            value={daysAhead}
            onChange={(e) => setDaysAhead(Math.max(0, Number(e.target.value || 0)))}
          />
        </label>
        <label className="text-xs text-slate-700">
          Relationship manager email (optional)
          <input
            className="block mt-1 rounded border border-slate-300 px-2 py-1 w-72"
            placeholder="rm@bank.com"
            value={rmEmail}
            onChange={(e) => setRmEmail(e.target.value)}
          />
        </label>
        <button
          type="button"
          onClick={() => dueQ.refetch()}
          className="px-3 py-2 rounded border border-slate-300 text-sm text-slate-700 hover:bg-slate-50"
        >
          Refresh due list
        </button>
        <button
          type="button"
          disabled={busy === 'bulk'}
          onClick={sendBulkDueAlerts}
          className="px-3 py-2 rounded bg-rose-700 text-white text-sm hover:bg-rose-600 disabled:opacity-50"
        >
          {busy === 'bulk' ? 'Sending...' : 'Send bulk due alerts'}
        </button>
        <button
          type="button"
          onClick={() => downloadCsv(`risk-review-register-${new Date().toISOString().slice(0, 10)}.csv`, toCsv(exportRows))}
          className="px-3 py-2 rounded border border-emerald-300 text-emerald-800 text-sm hover:bg-emerald-50"
        >
          Export regulator CSV
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <section className="bg-white border border-slate-200 rounded-lg p-4">
          <h2 className="font-semibold text-slate-900 mb-3">Accounts due for review</h2>
          <div className="max-h-[480px] overflow-auto border border-slate-200 rounded">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs text-slate-600 sticky top-0">
                <tr>
                  <th className="p-2">Customer</th>
                  <th className="p-2">Risk</th>
                  <th className="p-2">Due</th>
                  <th className="p-2">Action</th>
                </tr>
              </thead>
              <tbody>
                {dueItems.map((r) => {
                  const cid = String(r.customer_id ?? '');
                  const b = busy === `single-${cid}`;
                  return (
                    <tr key={`${cid}-${String(r.next_review_due_at ?? '')}`} className="border-t border-slate-100">
                      <td className="p-2">
                        <div className="font-mono text-xs">{cid}</div>
                        <div className="text-xs text-slate-600">{String(r.customer_name ?? '')}</div>
                      </td>
                      <td className="p-2 text-xs">{String(r.risk_rating ?? 'medium')}</td>
                      <td className="p-2 text-xs">{String(r.next_review_due_at ?? '').slice(0, 10)}</td>
                      <td className="p-2">
                        <button
                          type="button"
                          disabled={b}
                          onClick={() => sendSingleDueAlert(cid)}
                          className="px-2 py-1 rounded border border-rose-300 text-rose-800 text-xs hover:bg-rose-50 disabled:opacity-50"
                        >
                          {b ? 'Sending...' : 'Send alert'}
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {!dueItems.length && (
                  <tr>
                    <td className="p-3 text-sm text-slate-500" colSpan={4}>
                      No due reviews in the selected horizon.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="bg-white border border-slate-200 rounded-lg p-4">
          <h2 className="font-semibold text-slate-900 mb-3">Reviewed accounts</h2>
          <div className="max-h-[480px] overflow-auto border border-slate-200 rounded">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs text-slate-600 sticky top-0">
                <tr>
                  <th className="p-2">Customer</th>
                  <th className="p-2">Risk</th>
                  <th className="p-2">Last review</th>
                  <th className="p-2">Next due</th>
                </tr>
              </thead>
              <tbody>
                {reviewedRows.map((r) => (
                  <tr key={r.customer_id} className="border-t border-slate-100">
                    <td className="p-2">
                      <div className="font-mono text-xs">{r.customer_id}</div>
                      <div className="text-xs text-slate-600">{r.customer_name}</div>
                    </td>
                    <td className="p-2 text-xs">{r.risk_rating ?? 'medium'}</td>
                    <td className="p-2 text-xs">{String(r.last_review_date ?? '').slice(0, 10)}</td>
                    <td className="p-2 text-xs">{String(r.next_review_due_at ?? '').slice(0, 10)}</td>
                  </tr>
                ))}
                {!reviewedRows.length && (
                  <tr>
                    <td className="p-3 text-sm text-slate-500" colSpan={4}>
                      No reviewed accounts yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </DashboardLayout>
  );
}
