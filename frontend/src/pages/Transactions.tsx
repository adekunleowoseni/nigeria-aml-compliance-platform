import { useQuery } from '@tanstack/react-query';
import { transactionsApi } from '../services/api';
import DashboardLayout from '../components/layout/DashboardLayout';

export default function Transactions() {
  const { data: list, isLoading, error } = useQuery({
    queryKey: ['transactions', 0, 20],
    queryFn: () => transactionsApi.list({ skip: 0, limit: 20 }),
  });

  type TxRow = {
    id: string;
    customer_id: string;
    transaction_type: string;
    amount: number;
    risk_score?: number;
    alert_id?: string;
  };
  const items = (list?.items ?? []) as TxRow[];

  return (
    <DashboardLayout>
      <h1 className="text-2xl font-bold text-slate-900 mb-6">Transactions</h1>
      {error && (
        <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm">
          Could not load transactions. Is the backend running? (Try port 8002 if using default.)
          <br />
          <span className="font-mono">{error.message}</span>
        </div>
      )}
      <p className="text-slate-600 mb-4">Total: {list?.total ?? 0}</p>
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50">
              <th className="text-left p-3 font-medium text-slate-700">ID</th>
              <th className="text-left p-3 font-medium text-slate-700">Customer</th>
              <th className="text-left p-3 font-medium text-slate-700">Type</th>
              <th className="text-right p-3 font-medium text-slate-700">Amount (NGN)</th>
              <th className="text-left p-3 font-medium text-slate-700">Risk</th>
              <th className="text-left p-3 font-medium text-slate-700">Alert</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={6} className="p-4 text-slate-500">Loading…</td>
              </tr>
            )}
            {!isLoading && !error && items.length === 0 && (
              <tr>
                <td colSpan={6} className="p-4 text-slate-500">No transactions</td>
              </tr>
            )}
            {!isLoading && items.map((tx) => (
              <tr key={tx.id} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="p-3 text-sm font-mono text-slate-600">{tx.id}</td>
                <td className="p-3">{tx.customer_id}</td>
                <td className="p-3 capitalize">{tx.transaction_type}</td>
                <td className="p-3 text-right font-medium">{Number(tx.amount).toLocaleString('en-NG')}</td>
                <td className="p-3">
                  <span className={tx.risk_score != null && tx.risk_score >= 0.8 ? 'text-red-600 font-medium' : 'text-slate-600'}>
                    {tx.risk_score != null ? `${(tx.risk_score * 100).toFixed(0)}%` : '–'}
                  </span>
                </td>
                <td className="p-3 text-sm">{tx.alert_id ? 'Yes' : '–'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </DashboardLayout>
  );
}
