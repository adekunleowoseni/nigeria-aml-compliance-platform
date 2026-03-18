import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LineChart,
  Line,
} from 'recharts';
import DashboardLayout from '../components/layout/DashboardLayout';
import { analyticsApi, dashboardApi } from '../services/api';

export default function Analytics() {
  const navigate = useNavigate();
  const { data: metrics } = useQuery({
    queryKey: ['dashboard'],
    queryFn: () => dashboardApi.getMetrics(),
  });
  const { data: riskDist, isLoading: riskLoading } = useQuery({
    queryKey: ['analytics-risk'],
    queryFn: () => analyticsApi.getRiskDistribution(),
  });
  const { data: volumeTrend } = useQuery({
    queryKey: ['analytics-trends', 'volume'],
    queryFn: () => analyticsApi.getTrends({ metric: 'volume', granularity: 'day' }),
  });
  const { data: alertsTrend } = useQuery({
    queryKey: ['analytics-trends', 'alerts'],
    queryFn: () => analyticsApi.getTrends({ metric: 'alerts', granularity: 'day' }),
  });

  const riskData = riskDist?.buckets ?? [];
  const volumeSeries = volumeTrend?.series ?? [];
  const alertsSeries = alertsTrend?.series ?? [];

  return (
    <DashboardLayout>
      <h1 className="text-2xl font-bold text-slate-900 mb-2">Analytics</h1>
      <p className="text-slate-600 mb-6">Risk trends, volume analytics, and custom reports.</p>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div className="bg-white rounded-lg shadow p-4 border border-slate-100">
          <p className="text-sm text-slate-500">Total transactions</p>
          <p className="text-2xl font-semibold text-slate-900">{metrics?.total_transactions ?? 0}</p>
        </div>
        <div className="bg-white rounded-lg shadow p-4 border border-slate-100">
          <p className="text-sm text-slate-500">Total alerts</p>
          <p className="text-2xl font-semibold text-slate-900">{metrics?.total_alerts ?? 0}</p>
        </div>
        <div className="bg-white rounded-lg shadow p-4 border border-slate-100">
          <p className="text-sm text-slate-500">High-risk count</p>
          <p className="text-2xl font-semibold text-red-600">{metrics?.high_risk_count ?? 0}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="font-semibold text-slate-900 mb-4">Risk score distribution</h3>
          {riskLoading ? (
            <div className="h-64 flex items-center justify-center text-slate-500 text-sm">Loading…</div>
          ) : riskData.length > 0 ? (
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={riskData} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="label" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="count" name="Count" fill="#3b82f6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-64 flex items-center justify-center text-slate-500 text-sm">No risk data</div>
          )}
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="font-semibold text-slate-900 mb-4">Volume trend (30 days)</h3>
          {volumeSeries.length > 0 ? (
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={volumeSeries} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="date" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip />
                <Line type="monotone" dataKey="value" name="Transactions" stroke="#3b82f6" strokeWidth={2} dot={{ r: 4 }} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-64 flex items-center justify-center text-slate-500 text-sm">No volume data</div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="font-semibold text-slate-900 mb-4">Alert trend (30 days)</h3>
          {alertsSeries.length > 0 ? (
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={alertsSeries} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="date" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip />
                <Line type="monotone" dataKey="value" name="Alerts" stroke="#f97316" strokeWidth={2} dot={{ r: 4 }} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-64 flex items-center justify-center text-slate-500 text-sm">No alert trend data</div>
          )}
        </div>
        <div className="bg-white rounded-lg shadow p-4 flex flex-col justify-center">
          <h3 className="font-semibold text-slate-900 mb-2">Custom reports</h3>
          <p className="text-slate-600 text-sm mb-4">Generate NFIU goAML STR/CTR reports for submission.</p>
          <button
            type="button"
            onClick={() => navigate('/reports')}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 w-fit"
          >
            Go to Reports
          </button>
        </div>
      </div>
    </DashboardLayout>
  );
}
