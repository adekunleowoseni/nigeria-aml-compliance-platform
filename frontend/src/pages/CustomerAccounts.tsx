import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import DashboardLayout from '../components/layout/DashboardLayout';
import { customersApi } from '../services/api';

export default function CustomerAccounts() {
  const navigate = useNavigate();
  const { customerId } = useParams<{ customerId: string }>();
  const cid = (customerId || '').trim();

  const { data, isLoading, error } = useQuery({
    queryKey: ['customer-related-accounts-page', cid],
    queryFn: () => customersApi.relatedAccounts(cid),
    enabled: !!cid,
  });

  const otherAccounts = useMemo(
    () => (data?.items ?? []).filter((x) => x.customer_id !== data?.primary_customer_id),
    [data],
  );

  return (
    <DashboardLayout>
      <div className="mb-4">
        <button
          type="button"
          onClick={() => navigate('/customers')}
          className="text-sm text-sky-700 hover:underline"
        >
          ← Back to Customers
        </button>
      </div>

      <h1 className="text-2xl font-bold text-slate-900 mb-1">Linked Accounts</h1>
      <p className="text-sm text-slate-600 mb-5">
        BVN-linked accounts for <strong>{data?.customer_name || cid || 'customer'}</strong>.
      </p>

      {isLoading ? (
        <div className="bg-white border border-slate-200 rounded-xl p-4 text-sm text-slate-500">Loading accounts…</div>
      ) : error ? (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-800">
          Could not load linked accounts. {(error as Error).message}
        </div>
      ) : (
        <section className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
          <div className="text-sm text-slate-600 mb-3">
            Total accounts: <strong>{data?.total_accounts ?? 0}</strong> · Other accounts:{' '}
            <strong>{data?.other_accounts ?? 0}</strong>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs text-slate-600">
                <tr>
                  <th className="p-2">Customer ID</th>
                  <th className="p-2">Name</th>
                  <th className="p-2">Account Number</th>
                  <th className="p-2">Type</th>
                  <th className="p-2">Product</th>
                  <th className="p-2">Ledger</th>
                  <th className="p-2">Reference</th>
                  <th className="p-2">BVN / ID</th>
                </tr>
              </thead>
              <tbody>
                {(otherAccounts.length > 0 ? otherAccounts : data?.items ?? []).map((row) => (
                  <tr key={row.customer_id} className="border-t border-slate-100">
                    <td className="p-2 font-mono text-xs">{row.customer_id}</td>
                    <td className="p-2">{row.customer_name}</td>
                    <td className="p-2 font-mono text-xs">{row.account_number}</td>
                    <td className="p-2 text-xs capitalize">{row.account_holder_type ?? '—'}</td>
                    <td className="p-2 text-xs capitalize">{row.account_product ?? '—'}</td>
                    <td className="p-2 font-mono text-xs">{row.ledger_code ?? '—'}</td>
                    <td className="p-2 font-mono text-xs">{row.account_reference ?? '—'}</td>
                    <td className="p-2 font-mono text-xs">{row.id_number ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </DashboardLayout>
  );
}
