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
import { dashboardApi, alertsApi, transactionsApi, demoApi } from '../services/api';

const PIE_COLORS: Record<string, string> = {
  Critical: '#ef4444',
  High: '#f97316',
  Medium: '#eab308',
  Low: '#22c55e',
};

export default function Dashboard() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
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
    mutationFn: () =>
      transactionsApi.ingest({
        customer_id: 'CUST-NG-9001',
        amount: 10_000_000,
        currency: 'NGN',
        transaction_type: 'wire',
        narrative: 'Demo anomalous transaction for ML alert generation.',
        metadata: { scenario: 'profile_mismatch', fan_in_transfers_2h: 15 },
      }),
    onSuccess: async () => {
      // give the background task a moment then refresh alerts/metrics
      await new Promise((r) => setTimeout(r, 600));
      queryClient.invalidateQueries({ queryKey: ['alerts'] });
      queryClient.invalidateQueries({ queryKey: ['alerts-dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      navigate('/alerts');
    },
  });

  const seedDemoMutation = useMutation({
    mutationFn: () => demoApi.seed(),
    onSuccess: async () => {
      // allow background anomaly processing to complete then refresh
      await new Promise((r) => setTimeout(r, 800));
      queryClient.invalidateQueries({ queryKey: ['alerts'] });
      queryClient.invalidateQueries({ queryKey: ['alerts-dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      navigate('/alerts');
    },
  });

  return (
    <DashboardLayout>
      <h1 className="text-2xl font-bold text-slate-900 mb-6">Dashboard</h1>

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
              onClick={() => ingestMutation.mutate()}
              disabled={ingestMutation.isPending}
              className="px-4 py-2 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
              title="Creates an ML alert using Isolation Forest"
            >
              {ingestMutation.isPending ? 'Ingesting…' : 'Ingest demo suspicious txn'}
            </button>
            <button
              type="button"
              onClick={() => seedDemoMutation.mutate()}
              disabled={seedDemoMutation.isPending}
              className="px-4 py-2 bg-purple-600 text-white rounded hover:bg-purple-700 disabled:opacity-50"
              title="Seed multiple AML scenarios (smurfing, layering, cash anomalies)"
            >
              {seedDemoMutation.isPending ? 'Seeding demo data…' : 'Run full AML demo'}
            </button>
            <button
              type="button"
              onClick={() => navigate('/alerts')}
              className="px-4 py-2 bg-slate-200 text-slate-800 rounded hover:bg-slate-300"
            >
              View Alerts
            </button>
          </div>
          {ingestMutation.isError && (
            <p className="mt-3 text-sm text-red-600">
              Failed to ingest demo transaction: {(ingestMutation.error as Error).message}
            </p>
          )}
          {seedDemoMutation.isError && (
            <p className="mt-3 text-sm text-red-600">
              Failed to seed demo data: {(seedDemoMutation.error as Error).message}
            </p>
          )}
        </div>
      </div>
    </DashboardLayout>
  );
}
