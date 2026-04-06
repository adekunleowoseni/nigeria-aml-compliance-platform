import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import DashboardLayout from '../components/layout/DashboardLayout';
import { Link } from 'react-router-dom';
import { auditApi, type AuditEvent } from '../services/api';
import { useAuthStore } from '../store/authStore';

function canAccessAudit(role: string | undefined): boolean {
  const r = (role || '').toLowerCase();
  return r === 'admin' || r === 'chief_compliance_officer';
}

function dayStartUtc(isoDate: string): string | undefined {
  if (!isoDate.trim()) return undefined;
  return `${isoDate.trim()}T00:00:00Z`;
}

function dayEndUtc(isoDate: string): string | undefined {
  if (!isoDate.trim()) return undefined;
  return `${isoDate.trim()}T23:59:59Z`;
}

function formatDetails(d: Record<string, unknown>): string {
  try {
    const s = JSON.stringify(d);
    return s.length > 160 ? `${s.slice(0, 157)}…` : s;
  } catch {
    return '—';
  }
}

const REPORT_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'All report types' },
  { value: 'str', label: 'STR' },
  { value: 'sar', label: 'SAR' },
  { value: 'ctr', label: 'CTR' },
  { value: 'aop', label: 'AOP' },
  { value: 'estr', label: 'ESTR' },
  { value: 'nfiu_cir', label: 'NFIU customer change' },
];

export default function AuditGovernance() {
  const role = useAuthStore((s) => s.user?.role);
  const allowed = canAccessAudit(role);

  const [tab, setTab] = useState<'reports' | 'full'>('reports');
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');
  const [q, setQ] = useState('');
  const [actorEmail, setActorEmail] = useState('');
  const [reportType, setReportType] = useState('');
  const [page, setPage] = useState(0);
  const pageSize = 25;

  const from_ts = useMemo(() => dayStartUtc(fromDate), [fromDate]);
  const to_ts = useMemo(() => dayEndUtc(toDate), [toDate]);

  const listParams = useMemo(
    () => ({
      skip: page * pageSize,
      limit: pageSize,
      from_ts,
      to_ts,
      q: q.trim() || undefined,
      actor_email: actorEmail.trim() || undefined,
      ...(tab === 'reports' ? { report_type: reportType || undefined } : {}),
    }),
    [page, pageSize, from_ts, to_ts, q, actorEmail, tab, reportType]
  );

  const listQuery = useQuery({
    queryKey: ['audit', tab, listParams],
    queryFn: () =>
      tab === 'reports' ? auditApi.listReports(listParams) : auditApi.listEvents(listParams),
    enabled: allowed,
  });

  const summaryQuery = useQuery({
    queryKey: ['audit', 'summary', from_ts, to_ts],
    queryFn: () => auditApi.summary({ from_ts, to_ts }),
    enabled: allowed,
  });

  const [integrity, setIntegrity] = useState<{ valid: boolean; events_verified: number; chain_head: string } | null>(
    null
  );
  const [integrityLoading, setIntegrityLoading] = useState(false);

  const total = listQuery.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const setPresetRange = (days: number) => {
    const end = new Date();
    const start = new Date();
    start.setUTCDate(start.getUTCDate() - days);
    setFromDate(start.toISOString().slice(0, 10));
    setToDate(end.toISOString().slice(0, 10));
    setPage(0);
  };

  if (!allowed) {
    return (
      <DashboardLayout>
        <h1 className="text-2xl font-bold text-slate-900 mb-4">Audit &amp; governance</h1>
        <div className="p-4 bg-amber-50 border border-amber-200 rounded-lg text-amber-900 text-sm max-w-xl">
          This area is restricted to the Chief Compliance Officer or an administrator. Sign in as{' '}
          <span className="font-mono">cco@demo.com</span> or <span className="font-mono">admin@admin.com</span>.
        </div>
        <Link to="/login" className="inline-block mt-4 text-blue-600 hover:underline text-sm">
          Go to login
        </Link>
      </DashboardLayout>
    );
  }

  const items = listQuery.data?.items ?? [];

  return (
    <DashboardLayout>
      <h1 className="text-2xl font-bold text-slate-900 mb-2">Audit &amp; governance</h1>
      <p className="text-slate-600 text-sm mb-6 max-w-3xl">
        Tamper-evident activity trail: regulatory report generation and filing, alert dispositions, authentication, and
        configuration changes. Use date filters for daily or weekly reviews; export supports substantive testing and
        supervisory inspection. Chain verification recomputes integrity hashes without blocking other operations.
      </p>

      {summaryQuery.data && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
          <div className="bg-white rounded-lg border border-slate-200 p-4 shadow-sm">
            <p className="text-xs text-slate-500 uppercase tracking-wide">Events in range</p>
            <p className="text-2xl font-semibold text-slate-900">{summaryQuery.data.total_events}</p>
          </div>
          <div className="bg-white rounded-lg border border-slate-200 p-4 shadow-sm">
            <p className="text-xs text-slate-500 uppercase tracking-wide">Distinct actions</p>
            <p className="text-2xl font-semibold text-slate-900">{summaryQuery.data.unique_actions}</p>
          </div>
          <div className="bg-white rounded-lg border border-slate-200 p-4 shadow-sm">
            <p className="text-xs text-slate-500 uppercase tracking-wide">Report-related</p>
            <p className="text-2xl font-semibold text-slate-900">{summaryQuery.data.report_events_count}</p>
          </div>
          <div className="bg-white rounded-lg border border-slate-200 p-4 shadow-sm">
            <p className="text-xs text-slate-500 uppercase tracking-wide">Top action</p>
            <p className="text-sm font-medium text-slate-900 truncate" title={Object.keys(summaryQuery.data.by_action)[0]}>
              {Object.entries(summaryQuery.data.by_action).sort((a, b) => b[1] - a[1])[0]?.[0] ?? '—'}
            </p>
            <p className="text-xs text-slate-500">
              {Object.entries(summaryQuery.data.by_action).sort((a, b) => b[1] - a[1])[0]?.[1] ?? 0} occurrences
            </p>
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-2 mb-4">
        <button
          type="button"
          onClick={() => {
            setTab('reports');
            setPage(0);
          }}
          className={`px-3 py-1.5 rounded-md text-sm font-medium ${
            tab === 'reports' ? 'bg-slate-800 text-white' : 'bg-white border border-slate-200 text-slate-700'
          }`}
        >
          Report registry
        </button>
        <button
          type="button"
          onClick={() => {
            setTab('full');
            setPage(0);
          }}
          className={`px-3 py-1.5 rounded-md text-sm font-medium ${
            tab === 'full' ? 'bg-slate-800 text-white' : 'bg-white border border-slate-200 text-slate-700'
          }`}
        >
          Full audit log
        </button>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-4 mb-4 space-y-3">
        <div className="flex flex-wrap gap-3 items-end">
          <div>
            <label className="block text-xs text-slate-500 mb-1">From (UTC date)</label>
            <input
              type="date"
              value={fromDate}
              onChange={(e) => {
                setFromDate(e.target.value);
                setPage(0);
              }}
              className="border border-slate-300 rounded-md px-2 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">To (UTC date)</label>
            <input
              type="date"
              value={toDate}
              onChange={(e) => {
                setToDate(e.target.value);
                setPage(0);
              }}
              className="border border-slate-300 rounded-md px-2 py-1.5 text-sm"
            />
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              className="text-sm text-blue-600 hover:underline"
              onClick={() => setPresetRange(7)}
            >
              Last 7 days
            </button>
            <button type="button" className="text-sm text-blue-600 hover:underline" onClick={() => setPresetRange(30)}>
              Last 30 days
            </button>
            <button
              type="button"
              className="text-sm text-slate-600 hover:underline"
              onClick={() => {
                setFromDate('');
                setToDate('');
                setPage(0);
              }}
            >
              Clear dates
            </button>
          </div>
        </div>
        {tab === 'reports' && (
          <div>
            <label className="block text-xs text-slate-500 mb-1">Report type</label>
            <select
              value={reportType}
              onChange={(e) => {
                setReportType(e.target.value);
                setPage(0);
              }}
              className="border border-slate-300 rounded-md px-2 py-1.5 text-sm min-w-[200px]"
            >
              {REPORT_TYPE_OPTIONS.map((o) => (
                <option key={o.value || 'all'} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="flex flex-wrap gap-3">
          <div className="flex-1 min-w-[200px]">
            <label className="block text-xs text-slate-500 mb-1">Search (JSON / text)</label>
            <input
              type="search"
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setPage(0);
              }}
              placeholder="Customer id, report id, action fragment…"
              className="w-full border border-slate-300 rounded-md px-2 py-1.5 text-sm"
            />
          </div>
          <div className="min-w-[200px]">
            <label className="block text-xs text-slate-500 mb-1">Actor email</label>
            <input
              type="text"
              value={actorEmail}
              onChange={(e) => {
                setActorEmail(e.target.value);
                setPage(0);
              }}
              placeholder="filter@bank.com"
              className="w-full border border-slate-300 rounded-md px-2 py-1.5 text-sm"
            />
          </div>
        </div>
        <div className="flex flex-wrap gap-2 pt-2 border-t border-slate-100">
          <button
            type="button"
            className="px-3 py-1.5 text-sm rounded-md bg-slate-100 text-slate-800 hover:bg-slate-200"
            onClick={() => auditApi.exportAudit('csv', { from_ts, to_ts })}
          >
            Export CSV
          </button>
          <button
            type="button"
            className="px-3 py-1.5 text-sm rounded-md bg-slate-100 text-slate-800 hover:bg-slate-200"
            onClick={() => auditApi.exportAudit('json', { from_ts, to_ts })}
          >
            Export JSON
          </button>
          <button
            type="button"
            disabled={integrityLoading}
            className="px-3 py-1.5 text-sm rounded-md bg-emerald-700 text-white hover:bg-emerald-800 disabled:opacity-50"
            onClick={async () => {
              setIntegrityLoading(true);
              try {
                setIntegrity(await auditApi.integrity());
              } finally {
                setIntegrityLoading(false);
              }
            }}
          >
            {integrityLoading ? 'Verifying…' : 'Verify hash chain'}
          </button>
        </div>
        {integrity && (
          <p
            className={`text-sm ${integrity.valid ? 'text-emerald-800' : 'text-red-700'}`}
            role="status"
          >
            {integrity.valid ? 'Chain valid' : 'Chain invalid — log may have been tampered'} — {integrity.events_verified}{' '}
            events; head <span className="font-mono text-xs">{integrity.chain_head.slice(0, 16)}…</span>
          </p>
        )}
      </div>

      {listQuery.isLoading && <p className="text-slate-500 text-sm">Loading…</p>}
      {listQuery.isError && (
        <p className="text-red-600 text-sm">{(listQuery.error as Error).message || 'Could not load audit data.'}</p>
      )}

      {!listQuery.isLoading && !listQuery.isError && (
        <>
          <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs text-slate-600 uppercase">
                <tr>
                  <th className="px-3 py-2 font-medium">Time (UTC)</th>
                  <th className="px-3 py-2 font-medium">Action</th>
                  <th className="px-3 py-2 font-medium">Actor</th>
                  <th className="px-3 py-2 font-medium">Resource</th>
                  <th className="px-3 py-2 font-medium">Details</th>
                </tr>
              </thead>
              <tbody>
                {items.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-3 py-8 text-center text-slate-500">
                      No events match the current filters.
                    </td>
                  </tr>
                ) : (
                  items.map((ev: AuditEvent) => (
                    <tr key={ev.id} className="border-t border-slate-100 hover:bg-slate-50/80">
                      <td className="px-3 py-2 whitespace-nowrap font-mono text-xs text-slate-700">{ev.timestamp}</td>
                      <td className="px-3 py-2 font-mono text-xs text-slate-900">{ev.action}</td>
                      <td className="px-3 py-2 text-xs">
                        <div className="text-slate-900">{ev.actor_email}</div>
                        <div className="text-slate-500">{ev.actor_role}</div>
                      </td>
                      <td className="px-3 py-2 text-xs">
                        <span className="text-slate-500">{ev.resource_type}</span>
                        <span className="font-mono text-slate-800 block truncate max-w-[12rem]" title={ev.resource_id}>
                          {ev.resource_id}
                        </span>
                      </td>
                      <td className="px-3 py-2 font-mono text-xs text-slate-600 max-w-md" title={JSON.stringify(ev.details)}>
                        {formatDetails(ev.details as Record<string, unknown>)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 mt-4 text-sm text-slate-600">
            <span>
              {total === 0 ? 'No rows' : `${page * pageSize + 1}–${Math.min((page + 1) * pageSize, total)} of ${total}`}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={page <= 0}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                className="px-3 py-1 rounded border border-slate-300 disabled:opacity-40"
              >
                Previous
              </button>
              <button
                type="button"
                disabled={page + 1 >= totalPages}
                onClick={() => setPage((p) => p + 1)}
                className="px-3 py-1 rounded border border-slate-300 disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </DashboardLayout>
  );
}
