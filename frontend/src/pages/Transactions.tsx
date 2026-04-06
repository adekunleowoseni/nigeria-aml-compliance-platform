import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { transactionsApi } from '../services/api';
import DashboardLayout from '../components/layout/DashboardLayout';

export default function Transactions() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [statusFilter, setStatusFilter] = useState('');
  const [entityId, setEntityId] = useState('');
  const [transactionType, setTransactionType] = useState('');
  const [textQ, setTextQ] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [minAmount, setMinAmount] = useState('');
  const [maxAmount, setMaxAmount] = useState('');

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedQ(textQ.trim()), 300);
    return () => window.clearTimeout(t);
  }, [textQ]);

  useEffect(() => {
    setPage(1);
  }, [
    pageSize,
    statusFilter,
    entityId,
    transactionType,
    debouncedQ,
    startDate,
    endDate,
    minAmount,
    maxAmount,
  ]);

  const { data: list, isLoading, error } = useQuery({
    queryKey: [
      'transactions',
      page,
      pageSize,
      statusFilter,
      entityId,
      transactionType,
      debouncedQ,
      startDate,
      endDate,
      minAmount,
      maxAmount,
    ],
    queryFn: () =>
      transactionsApi.list({
        page,
        page_size: pageSize,
        status: statusFilter || undefined,
        entity_id: entityId.trim() || undefined,
        transaction_type: transactionType.trim().toLowerCase() || undefined,
        q: debouncedQ || undefined,
        start_date: startDate.trim() || undefined,
        end_date: endDate.trim() || undefined,
        min_amount: minAmount.trim() !== '' ? Number(minAmount) : undefined,
        max_amount: maxAmount.trim() !== '' ? Number(maxAmount) : undefined,
      }),
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
  const total = list?.total ?? 0;
  const totalPages = pageSize > 0 ? Math.max(1, Math.ceil(total / pageSize)) : 1;
  const skip = list?.skip ?? (page - 1) * pageSize;
  const fromIx = total === 0 ? 0 : skip + 1;
  const toIx = Math.min(skip + items.length, total);

  return (
    <DashboardLayout>
      <h1 className="text-2xl font-bold text-slate-900 mb-6">Transactions</h1>
      {error && (
        <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm">
          Could not load transactions. Is the backend running? (Try port 8002 if using default.)
          <br />
          <span className="font-mono">{(error as Error).message}</span>
        </div>
      )}

      <div className="mb-4 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        <div className="md:col-span-2 lg:col-span-3">
          <label className="block text-xs font-medium text-slate-600 mb-1" htmlFor="txn-q">
            Search (ID, customer, type, narrative)
          </label>
          <input
            id="txn-q"
            value={textQ}
            onChange={(e) => setTextQ(e.target.value)}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            placeholder="Fragment match across fields"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1" htmlFor="txn-customer">
            Customer ID contains
          </label>
          <input
            id="txn-customer"
            value={entityId}
            onChange={(e) => setEntityId(e.target.value)}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono"
            placeholder="Substring filter"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1" htmlFor="txn-type">
            Transaction type
          </label>
          <input
            id="txn-type"
            value={transactionType}
            onChange={(e) => setTransactionType(e.target.value)}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            placeholder="e.g. transfer (exact match)"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1" htmlFor="txn-status">
            Status
          </label>
          <select
            id="txn-status"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="w-full rounded-lg border border-slate-300 px-2 py-2 text-sm bg-white"
          >
            <option value="">All</option>
            <option value="received">received</option>
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1" htmlFor="txn-start">
            From date
          </label>
          <input
            id="txn-start"
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="w-full rounded-lg border border-slate-300 px-2 py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1" htmlFor="txn-end">
            To date
          </label>
          <input
            id="txn-end"
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="w-full rounded-lg border border-slate-300 px-2 py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1" htmlFor="txn-min">
            Min amount
          </label>
          <input
            id="txn-min"
            type="number"
            min={0}
            step={0.01}
            value={minAmount}
            onChange={(e) => setMinAmount(e.target.value)}
            className="w-full rounded-lg border border-slate-300 px-2 py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1" htmlFor="txn-max">
            Max amount
          </label>
          <input
            id="txn-max"
            type="number"
            min={0}
            step={0.01}
            value={maxAmount}
            onChange={(e) => setMaxAmount(e.target.value)}
            className="w-full rounded-lg border border-slate-300 px-2 py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1" htmlFor="txn-page-size">
            Page size
          </label>
          <select
            id="txn-page-size"
            value={pageSize}
            onChange={(e) => setPageSize(Number(e.target.value))}
            className="w-full rounded-lg border border-slate-300 px-2 py-2 text-sm bg-white"
          >
            {[10, 20, 50, 100].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </div>
      </div>

      <p className="text-slate-600 mb-2">
        {total === 0 ? (
          'No transactions match the current filters.'
        ) : (
          <>
            Showing <strong>{fromIx}</strong>–<strong>{toIx}</strong> of <strong>{total}</strong>
          </>
        )}
      </p>
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <button
          type="button"
          disabled={page <= 1 || isLoading}
          onClick={() => setPage((p) => Math.max(1, p - 1))}
          className="px-3 py-1.5 text-sm rounded-lg border border-slate-300 bg-white hover:bg-slate-50 disabled:opacity-50"
        >
          Previous
        </button>
        <button
          type="button"
          disabled={isLoading || page >= totalPages}
          onClick={() => setPage((p) => p + 1)}
          className="px-3 py-1.5 text-sm rounded-lg border border-slate-300 bg-white hover:bg-slate-50 disabled:opacity-50"
        >
          Next
        </button>
        <span className="text-sm text-slate-600">
          Page <strong>{page}</strong> of <strong>{totalPages}</strong>
        </span>
      </div>

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
                <td colSpan={6} className="p-4 text-slate-500">
                  Loading…
                </td>
              </tr>
            )}
            {!isLoading && !error && items.length === 0 && (
              <tr>
                <td colSpan={6} className="p-4 text-slate-500">
                  No transactions
                </td>
              </tr>
            )}
            {!isLoading &&
              items.map((tx) => (
                <tr key={tx.id} className="border-b border-slate-100 hover:bg-slate-50">
                  <td className="p-3 text-sm font-mono text-slate-600">{tx.id}</td>
                  <td className="p-3">{tx.customer_id}</td>
                  <td className="p-3 capitalize">{tx.transaction_type}</td>
                  <td className="p-3 text-right font-medium">{Number(tx.amount).toLocaleString('en-NG')}</td>
                  <td className="p-3">
                    <span
                      className={
                        tx.risk_score != null && tx.risk_score >= 0.8 ? 'text-red-600 font-medium' : 'text-slate-600'
                      }
                    >
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
