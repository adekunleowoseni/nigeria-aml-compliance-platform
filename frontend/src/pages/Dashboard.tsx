import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from 'recharts';
import DashboardLayout from '../components/layout/DashboardLayout';
import StatCard from '../components/dashboard/StatCard';
import { dashboardApi, alertsApi, demoApi } from '../services/api';
import { useAuthStore } from '../store/authStore';

const PIE_COLORS: Record<string, string> = {
  Critical: '#ef4444',
  High: '#f97316',
  Medium: '#eab308',
  Low: '#22c55e',
};

export default function Dashboard() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const role = useAuthStore((s) => s.user?.role);
  const r = (role || '').toLowerCase();
  const showCcoBanner = r === 'admin' || r === 'chief_compliance_officer';
  const { data: metrics, isLoading, error } = useQuery({
    queryKey: ['dashboard'],
    queryFn: () => dashboardApi.getMetrics(),
    refetchInterval: 30000,
  });

  const { data: alertsDashboard } = useQuery({
    queryKey: ['alerts-dashboard'],
    queryFn: () => alertsApi.getDashboard(),
  });

  const { data: alertsList } = useQuery({
    queryKey: ['alerts', 0, 20],
    queryFn: () => alertsApi.list({ skip: 0, limit: 20 }),
  });

  if (error) {
    return (
      <DashboardLayout>
        <h1 className="text-2xl font-bold text-slate-900 mb-6">Dashboard</h1>
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg text-red-800">
          Could not load dashboard. Is the backend running? (Default port 8002.)
          <br />
          <span className="font-mono text-sm">{error.message}</span>
        </div>
      </DashboardLayout>
    );
  }

  const alertTrend = alertsDashboard?.trend_over_time ?? [];
  const riskDistribution = alertsDashboard?.counts_by_severity
    ? [
        { name: 'Critical', value: alertsDashboard.counts_by_severity.critical, color: PIE_COLORS.Critical },
        { name: 'High', value: alertsDashboard.counts_by_severity.high, color: PIE_COLORS.High },
        { name: 'Medium', value: alertsDashboard.counts_by_severity.medium, color: PIE_COLORS.Medium },
        { name: 'Low', value: alertsDashboard.counts_by_severity.low, color: PIE_COLORS.Low },
      ].filter((d) => d.value > 0)
    : [];

  const highRiskAlerts = (alertsList?.items ?? []).filter((a) => a.severity >= 0.8).slice(0, 5);

  const ingestMutation = useMutation({
    mutationFn: () => demoApi.ingestFlagship(),
    onSuccess: async () => {
      // give the background task a moment then refresh alerts/metrics
      await new Promise((r) => setTimeout(r, 600));
      queryClient.invalidateQueries({ queryKey: ['alerts'] });
      queryClient.invalidateQueries({ queryKey: ['alerts-dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      navigate('/alerts');
    },
  });

  const seedCompleteDemoMutation = useMutation({
    mutationFn: () => demoApi.seedCompleteDemo(),
    onSuccess: async () => {
      await new Promise((r) => setTimeout(r, 1200));
      queryClient.invalidateQueries({ queryKey: ['alerts'] });
      queryClient.invalidateQueries({ queryKey: ['alerts-dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['transactions'] });
      queryClient.invalidateQueries({ queryKey: ['customers'] });
      navigate('/alerts');
    },
  });

  const pendingCcoStr = alertsDashboard?.pending_cco_str_approvals ?? 0;
  const pendingCcoOtc = alertsDashboard?.pending_cco_otc_approvals ?? 0;
  const pendingCco = pendingCcoStr + pendingCcoOtc;
  const coNotes = alertsDashboard?.co_notifications_unread ?? [];
  const isComplianceRole =
    r === 'compliance_officer' || r === 'admin' || r === 'chief_compliance_officer';

  const anySeedBusy = ingestMutation.isPending || seedCompleteDemoMutation.isPending;

  const [demoExportMsg, setDemoExportMsg] = useState<string | null>(null);

  return (
    <DashboardLayout>
      <h1 className="text-2xl font-bold text-slate-900 mb-6">Dashboard</h1>

      {isComplianceRole && coNotes.length > 0 && (
        <div className="mb-6 p-4 rounded-lg border border-rose-200 bg-rose-50 text-rose-950 text-sm space-y-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <p>
              <strong>{coNotes.length}</strong> notification{coNotes.length === 1 ? '' : 's'} from the Chief Compliance Officer
              (e.g. alert rejections). Open <strong>Alerts</strong> and filter by status <strong>rejected</strong> to review cases.
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => navigate('/alerts')}
                className="px-4 py-2 rounded-lg bg-rose-700 text-white text-sm font-medium hover:bg-rose-800"
              >
                Open Alerts
              </button>
              <button
                type="button"
                onClick={async () => {
                  try {
                    await alertsApi.markCoNotificationsRead({});
                    await queryClient.invalidateQueries({ queryKey: ['alerts-dashboard'] });
                  } catch {
                    /* ignore */
                  }
                }}
                className="px-4 py-2 rounded-lg border border-rose-300 bg-white text-rose-900 text-sm hover:bg-rose-100"
              >
                Mark all read
              </button>
            </div>
          </div>
          <ul className="text-xs space-y-1 border-t border-rose-200/80 pt-2 max-h-32 overflow-y-auto">
            {coNotes.slice(0, 8).map((n) => (
              <li key={n.id ?? `${n.alert_id}-${n.at}`} className="font-mono text-rose-900/90">
                {n.kind === 'cco_rejection' ? 'Rejected' : n.kind}: {n.alert_id?.slice(0, 8)}… —{' '}
                {(n.reason ?? '').slice(0, 120)}
                {(n.reason ?? '').length > 120 ? '…' : ''}
              </li>
            ))}
          </ul>
        </div>
      )}

      {showCcoBanner && pendingCco > 0 && (
        <div className="mb-6 p-4 rounded-lg border border-amber-300 bg-amber-50 text-amber-950 text-sm flex flex-wrap items-center justify-between gap-3">
          <p>
            <strong>{pendingCcoStr}</strong> STR queue
            {pendingCcoOtc > 0 && (
              <>
                {' '}
                · <strong>{pendingCcoOtc}</strong> legacy OTC queue
              </>
            )}{' '}
            awaiting Chief Compliance Officer approval.
          </p>
          <button
            type="button"
            onClick={() => navigate('/cco-review')}
            className="px-4 py-2 rounded-lg bg-amber-700 text-white text-sm font-medium hover:bg-amber-800"
          >
            Open CCO review
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard
          title="Transactions Today"
          value={isLoading ? '–' : (metrics?.total_transactions ?? 0)}
          trend={5}
          trendLabel="vs yesterday"
          color="blue"
        />
        <StatCard
          title="Active Alerts"
          value={isLoading ? '–' : (metrics?.total_alerts ?? 0)}
          color="yellow"
        />
        <StatCard
          title="Pending STRs"
          value={metrics?.pending_strs ?? 0}
          trendLabel="deadline"
          color="red"
        />
        <StatCard
          title="System Health"
          value="Healthy"
          color="green"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="font-semibold mb-4">Alert Trend (30 days)</h3>
          <ResponsiveContainer width="100%" height={280}>
            {alertTrend.length > 0 ? (
              <LineChart data={alertTrend}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="critical" stroke="#ef4444" name="Critical" />
                <Line type="monotone" dataKey="high" stroke="#f97316" name="High" />
                <Line type="monotone" dataKey="medium" stroke="#eab308" name="Medium" />
                <Line type="monotone" dataKey="low" stroke="#22c55e" name="Low" />
              </LineChart>
            ) : (
              <div className="flex items-center justify-center h-full text-slate-500 text-sm">Loading trend…</div>
            )}
          </ResponsiveContainer>
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="font-semibold mb-4">Risk Distribution</h3>
          <ResponsiveContainer width="100%" height={280}>
            {riskDistribution.length > 0 ? (
              <PieChart>
                <Pie
                  data={riskDistribution}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ name, value, percent }) => `${name} ${value} (${(percent * 100).toFixed(0)}%)`}
                >
                  {riskDistribution.map((entry) => (
                    <Cell key={entry.name} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            ) : (
              <div className="flex items-center justify-center h-full text-slate-500 text-sm">No alert data</div>
            )}
          </ResponsiveContainer>
        </div>
      </div>

      <div className="bg-white rounded-lg shadow p-4 mb-8">
        <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
          <div>
            <h3 className="font-semibold">Case MI — resolution, ageing & outcomes</h3>
            <p className="text-xs text-slate-500 mt-1 max-w-2xl">
              Scoped to your branch/zone visibility. Open-case ageing uses age since alert creation. Average resolution uses
              closed alerts only (created → last update).
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              void alertsApi.exportMiCsv().catch((e) => console.error(e));
            }}
            className="shrink-0 px-3 py-1.5 text-sm rounded-lg border border-slate-300 bg-white hover:bg-slate-50"
          >
            Download MI summary (CSV)
          </button>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
          <div className="rounded-lg border border-slate-100 bg-slate-50/80 p-3">
            <p className="text-xs text-slate-500 uppercase tracking-wide">Avg. resolution (closed)</p>
            <p className="text-xl font-semibold text-slate-900">
              {alertsDashboard?.average_resolution_time_hours != null
                ? `${alertsDashboard.average_resolution_time_hours} h`
                : '—'}
            </p>
            <p className="text-xs text-slate-500 mt-1">
              n = {alertsDashboard?.closed_cases_in_avg_sample ?? 0} closed
            </p>
          </div>
          <div className="rounded-lg border border-slate-100 bg-slate-50/80 p-3 sm:col-span-2 lg:col-span-1">
            <p className="text-xs text-slate-500 uppercase tracking-wide mb-2">Open / active ageing</p>
            <ul className="space-y-1 text-slate-700">
              <li className="flex justify-between">
                <span>&lt; 24 h</span>
                <strong>{alertsDashboard?.open_case_ageing?.lt_24h ?? 0}</strong>
              </li>
              <li className="flex justify-between">
                <span>1–3 d</span>
                <strong>{alertsDashboard?.open_case_ageing?.d1_3 ?? 0}</strong>
              </li>
              <li className="flex justify-between">
                <span>3–7 d</span>
                <strong>{alertsDashboard?.open_case_ageing?.d3_7 ?? 0}</strong>
              </li>
              <li className="flex justify-between">
                <span>&gt; 7 d</span>
                <strong>{alertsDashboard?.open_case_ageing?.gt_7d ?? 0}</strong>
              </li>
            </ul>
          </div>
          <div className="rounded-lg border border-slate-100 bg-slate-50/80 p-3 lg:col-span-2">
            <p className="text-xs text-slate-500 uppercase tracking-wide mb-2">Workflow outcomes (alerts)</p>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-slate-700">
              <div>
                Open: <strong>{alertsDashboard?.outcome_summary?.open ?? 0}</strong>
              </div>
              <div>
                Investigating: <strong>{alertsDashboard?.outcome_summary?.investigating ?? 0}</strong>
              </div>
              <div>
                Escalated: <strong>{alertsDashboard?.outcome_summary?.escalated ?? 0}</strong>
              </div>
              <div>
                Closed (FP): <strong>{alertsDashboard?.outcome_summary?.closed_false_positive ?? 0}</strong>
              </div>
              <div>
                Closed (other): <strong>{alertsDashboard?.outcome_summary?.closed_other ?? 0}</strong>
              </div>
              <div>
                Rejected (CCO): <strong>{alertsDashboard?.outcome_summary?.rejected ?? 0}</strong>
              </div>
            </div>
            <p className="text-xs text-slate-500 uppercase tracking-wide mt-3 mb-1">OTC filing outcome</p>
            <div className="flex flex-wrap gap-3 text-slate-700">
              <span>
                TP: <strong>{alertsDashboard?.otc_outcome_counts?.true_positive ?? 0}</strong>
              </span>
              <span>
                FP: <strong>{alertsDashboard?.otc_outcome_counts?.false_positive ?? 0}</strong>
              </span>
              <span>
                Not filed: <strong>{alertsDashboard?.otc_outcome_counts?.not_filed ?? 0}</strong>
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="font-semibold mb-4">Recent High-Risk Alerts</h3>
          {highRiskAlerts.length === 0 ? (
            <p className="text-slate-500 text-sm">No high-risk alerts in the last 24h.</p>
          ) : (
            <ul className="space-y-2">
              {highRiskAlerts.map((a) => (
                <li key={a.id} className="text-sm">
                  <button
                    type="button"
                    onClick={() => navigate('/alerts')}
                    className="text-left w-full px-3 py-2 rounded bg-slate-50 hover:bg-slate-100 border border-slate-100"
                  >
                    <span className="font-medium text-slate-900 line-clamp-1">{a.summary ?? 'Suspicious activity'}</span>
                    <span className="text-slate-500 block mt-0.5">
                      {(a.severity * 100).toFixed(0)}% risk · {a.customer_id}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="font-semibold mb-4">Quick Actions</h3>
          <p className="text-xs text-slate-500 mb-3">
            <strong>Load complete demo</strong> clears prior in-memory transactions and alerts (and demo KYC in Postgres when
            connected), then loads the standard AML pack, the 12-track showcase, the 10-row branch OTC / STR table, demo AOP
            templates, and <strong>10-year synthetic transaction history</strong> (six demo profiles + scenarios) in one run —
            may take <strong>1–2 minutes</strong>. Use <strong>Customers</strong> after loading to upload AOP where needed.
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => navigate('/reports')}
              className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
            >
              Generate STR
            </button>
            <button
              type="button"
              onClick={() => seedCompleteDemoMutation.mutate()}
              disabled={anySeedBusy}
              className="px-4 py-2 bg-violet-700 text-white rounded hover:bg-violet-800 disabled:opacity-50"
              title="Clears once, then: AML pack + showcase + OTC table + AOP templates + 10-year temporal history (append). 1–2 min."
            >
              {seedCompleteDemoMutation.isPending
                ? 'Loading complete demo (1–2 min)…'
                : 'Load complete demo (AML + showcase + OTC + 10-year history)'}
            </button>
            <button
              type="button"
              onClick={() => ingestMutation.mutate()}
              disabled={anySeedBusy}
              className="px-4 py-2 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
              title="Clears demo stores then ingests one high-signal wire (ministry memo / PEP-style)"
            >
              {ingestMutation.isPending ? 'Ingesting…' : 'Ingest demo suspicious txn'}
            </button>
            <button
              type="button"
              onClick={() => navigate('/alerts')}
              className="px-4 py-2 bg-slate-200 text-slate-800 rounded hover:bg-slate-300"
            >
              View Alerts
            </button>
            <button
              type="button"
              onClick={async () => {
                setDemoExportMsg(null);
                try {
                  await demoApi.downloadAllSeedDataXlsx();
                } catch (e) {
                  setDemoExportMsg(e instanceof Error ? e.message : 'Could not download seed workbook.');
                }
              }}
              className="px-4 py-2 bg-white border border-slate-300 text-slate-800 rounded hover:bg-slate-50 text-sm"
              title="All demo seed tables in one workbook (OTC, standard seed, showcase, flagship, temporal). Does not change data."
            >
              Download all demo seed data (Excel)
            </button>
            <button
              type="button"
              onClick={async () => {
                setDemoExportMsg(null);
                try {
                  await demoApi.downloadOtcBranchReferenceStructureCsv();
                } catch (e) {
                  setDemoExportMsg(e instanceof Error ? e.message : 'Could not download reference CSV.');
                }
              }}
              className="px-4 py-2 bg-white border border-slate-300 text-slate-800 rounded hover:bg-slate-50 text-sm"
              title="10-row branch OTC / STR intake reference (structure only). Opens in Excel."
            >
              Download OTC branch reference (CSV)
            </button>
          </div>
          {demoExportMsg && (
            <p className="mt-3 text-sm text-red-600" role="alert">
              {demoExportMsg}
            </p>
          )}
          {ingestMutation.isError && (
            <p className="mt-3 text-sm text-red-600">
              Failed to ingest demo transaction: {(ingestMutation.error as Error).message}
            </p>
          )}
          {seedCompleteDemoMutation.isError && (
            <p className="mt-3 text-sm text-red-600">
              Failed to load complete demo: {(seedCompleteDemoMutation.error as Error).message}
            </p>
          )}
        </div>
      </div>
    </DashboardLayout>
  );
}
