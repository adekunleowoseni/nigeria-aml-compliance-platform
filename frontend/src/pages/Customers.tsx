import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import DashboardLayout from '../components/layout/DashboardLayout';
import { customersApi, type CustomerUploadDocumentKind } from '../services/api';

export default function Customers() {
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const pageSize = 50;
  const [q, setQ] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [aopDownloadingId, setAopDownloadingId] = useState<string | null>(null);
  const [uploadDocumentKind, setUploadDocumentKind] = useState<CustomerUploadDocumentKind>('aop_package');
  const aopFileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedQ(q.trim()), 300);
    return () => window.clearTimeout(t);
  }, [q]);

  useEffect(() => {
    setPage(1);
  }, [debouncedQ]);

  const { data: listData, isLoading, error, refetch } = useQuery({
    queryKey: ['customers', page, debouncedQ],
    queryFn: () => customersApi.list({ page, page_size: pageSize, q: debouncedQ || undefined }),
  });

  const { data: selectedRow, isLoading: selectedLoading } = useQuery({
    queryKey: ['customer', selectedId],
    queryFn: () => customersApi.get(selectedId!),
    enabled: !!selectedId,
  });

  const items = listData?.items ?? [];
  const total = listData?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  async function onAopFileSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file || !selectedId) return;
    setMsg(null);
    setBusy('aop-upload');
    try {
      const meta = await customersApi.uploadAopForm(selectedId, file, uploadDocumentKind);
      setMsg({
        type: 'ok',
        text:
          meta.persisted === false
            ? `AOP uploaded: ${file.name} (file saved; metadata in this session only — database unavailable.)`
            : `AOP uploaded and saved for this customer: ${file.name}`,
      });
      await qc.invalidateQueries({ queryKey: ['customer', selectedId] });
      await qc.invalidateQueries({ queryKey: ['customers'] });
    } catch (err) {
      setMsg({ type: 'err', text: (err as Error).message });
    } finally {
      setBusy(null);
    }
  }

  function openFilePicker() {
    aopFileInputRef.current?.click();
  }

  return (
    <DashboardLayout>
      <h1 className="text-2xl font-bold text-slate-900 mb-2">Customers</h1>
      <p className="text-sm text-slate-600 mb-1 max-w-3xl">
        Select a customer, then upload files with the correct <strong>category</strong>: AOP package, profile-change
        evidence, or cash-threshold (OTC) evidence. Supported:{' '}
        <code className="text-slate-700">.pdf</code>, <code className="text-slate-700">.doc</code>,{' '}
        <code className="text-slate-700">.docx</code>, <code className="text-slate-700">.jpg</code>,{' '}
        <code className="text-slate-700">.jpeg</code>, <code className="text-slate-700">.png</code> (max 20 MB).
      </p>
      <p className="text-xs text-slate-500 mb-6 max-w-3xl">
        With <code className="text-slate-700">APP_ENV=development</code>, the list includes database customers plus demo-seeded
        transaction personas. Loading demo data copies the shared AOP template PDF per customer (named like{' '}
        <strong>Name-AOP.pdf</strong>) so the AOP column can link a download. Manual uploads still work from the panel.
      </p>

      {msg && (
        <div
          className={`mb-4 p-3 rounded-lg text-sm ${
            msg.type === 'ok' ? 'bg-emerald-50 text-emerald-900 border border-emerald-200' : 'bg-red-50 text-red-900 border border-red-200'
          }`}
        >
          {msg.text}
        </div>
      )}

      {error && (
        <div className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg text-amber-900 text-sm">
          Could not load customers. {(error as Error).message}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <section className="lg:col-span-7 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
          <div className="flex flex-wrap items-end gap-3 mb-3">
            <div className="flex-1 min-w-[160px]">
              <label className="block text-xs font-medium text-slate-600 mb-1">Search</label>
              <input
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Customer ID, name, account…"
              />
            </div>
            <button
              type="button"
              onClick={() => refetch()}
              className="px-3 py-2 text-sm rounded-lg border border-slate-300 text-slate-700 hover:bg-slate-50"
            >
              Refresh
            </button>
          </div>
          <div className="border border-slate-200 rounded-lg overflow-hidden max-h-[min(70vh,560px)] overflow-y-auto">
            {isLoading ? (
              <div className="p-4 text-sm text-slate-500">Loading…</div>
            ) : items.length === 0 ? (
              <div className="p-4 text-sm text-slate-500">No customers match. Adjust search or refresh.</div>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left text-xs text-slate-600 sticky top-0">
                  <tr>
                    <th className="p-2">Customer ID</th>
                    <th className="p-2">Name</th>
                    <th className="p-2">Account</th>
                    <th className="p-2 w-28">AOP</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((row) => (
                    <tr
                      key={row.customer_id}
                      className={`border-t border-slate-100 cursor-pointer hover:bg-slate-50 ${
                        selectedId === row.customer_id ? 'bg-sky-50' : ''
                      }`}
                      onClick={() => {
                        setSelectedId(row.customer_id);
                        setMsg(null);
                      }}
                    >
                      <td className="p-2 font-mono text-xs">{row.customer_id}</td>
                      <td className="p-2">{row.customer_name}</td>
                      <td className="p-2 font-mono text-xs">{row.account_number}</td>
                      <td className="p-2">
                        {row.aop_on_file &&
                        row.primary_aop_upload_id &&
                        (row.primary_aop_filename || row.customer_id) ? (
                          <button
                            type="button"
                            className="text-xs text-sky-700 hover:underline font-medium text-left max-w-[140px] truncate block"
                            title={row.primary_aop_filename ?? 'Download AOP'}
                            disabled={aopDownloadingId === `${row.customer_id}:${row.primary_aop_upload_id}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              const key = `${row.customer_id}:${row.primary_aop_upload_id}`;
                              setAopDownloadingId(key);
                              void customersApi
                                .downloadAopUpload(
                                  row.customer_id,
                                  row.primary_aop_upload_id!,
                                  row.primary_aop_filename || 'AOP.pdf'
                                )
                                .finally(() => setAopDownloadingId(null));
                            }}
                          >
                            {aopDownloadingId === `${row.customer_id}:${row.primary_aop_upload_id}`
                              ? '…'
                              : (row.primary_aop_filename ?? 'AOP').replace(/\.pdf$/i, '')}
                          </button>
                        ) : row.aop_on_file ? (
                          <span
                            className="inline-flex items-center rounded-full bg-emerald-100 text-emerald-900 px-2 py-0.5 text-xs font-medium"
                            title={`${row.aop_upload_count ?? 1} file(s) on file`}
                          >
                            Yes{typeof row.aop_upload_count === 'number' && row.aop_upload_count > 1
                              ? ` (${row.aop_upload_count})`
                              : ''}
                          </span>
                        ) : (
                          <span className="text-slate-400 text-xs">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          {totalPages > 1 && (
            <div className="flex items-center gap-2 mt-3 text-sm text-slate-600">
              <button
                type="button"
                disabled={page <= 1}
                className="px-2 py-1 rounded border border-slate-300 disabled:opacity-40"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Prev
              </button>
              <span>
                Page {page} / {totalPages} ({total} total)
              </span>
              <button
                type="button"
                disabled={page >= totalPages}
                className="px-2 py-1 rounded border border-slate-300 disabled:opacity-40"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              >
                Next
              </button>
            </div>
          )}
        </section>

        <section className="lg:col-span-5 bg-white rounded-xl border border-slate-200 p-5 shadow-sm min-h-[280px]">
          <h2 className="text-lg font-semibold text-slate-800 mb-3">AOP upload</h2>

          {!selectedId ? (
            <p className="text-sm text-slate-500">Click a customer in the list to attach their AOP document.</p>
          ) : selectedLoading ? (
            <p className="text-sm text-slate-500">Loading customer…</p>
          ) : selectedRow?.kyc ? (
            <div className="space-y-4">
              <div className="rounded-lg border border-slate-200 bg-slate-50/80 p-3 text-sm">
                <div className="text-xs font-medium text-slate-500 mb-1">Selected customer</div>
                <div className="font-medium text-slate-900">{selectedRow.kyc.customer_name}</div>
                <div className="font-mono text-xs text-slate-700 mt-1">{selectedId}</div>
                <div className="text-xs text-slate-600 mt-1">
                  Account <span className="font-mono">{selectedRow.kyc.account_number}</span>
                </div>
                {selectedRow.aop_uploads?.some((u) => u.persisted !== false) ? (
                  <p className="text-xs text-emerald-800 mt-2 font-medium">
                    AOP on file — saved to the customer record (database).
                  </p>
                ) : selectedRow.aop_uploads && selectedRow.aop_uploads.length > 0 ? (
                  <p className="text-xs text-amber-800 mt-2">AOP on file for this session only (not persisted to database).</p>
                ) : null}
              </div>

              <label className="block text-xs font-medium text-slate-600 mb-1">File category (required)</label>
              <select
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm mb-3"
                value={uploadDocumentKind}
                onChange={(e) => setUploadDocumentKind(e.target.value as CustomerUploadDocumentKind)}
              >
                <option value="aop_package">Account opening package (AOP)</option>
                <option value="profile_change">Profile / identity change evidence</option>
                <option value="cash_threshold">Cash deposit or withdrawal (threshold) evidence</option>
              </select>
              <input
                ref={aopFileInputRef}
                type="file"
                accept=".pdf,.doc,.docx,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
                className="hidden"
                onChange={onAopFileSelected}
              />
              <button
                type="button"
                onClick={openFilePicker}
                disabled={busy === 'aop-upload'}
                className="w-full px-4 py-3 rounded-lg bg-emerald-700 text-white text-sm font-medium hover:bg-emerald-600 disabled:opacity-50"
              >
                {busy === 'aop-upload' ? 'Uploading…' : 'Choose file to upload'}
              </button>

              {selectedRow.aop_uploads && selectedRow.aop_uploads.length > 0 && (
                <div>
                  <div className="grid grid-cols-1 gap-2 mb-3 mt-4">
                    <button
                      type="button"
                      disabled={busy === 'bundle-otc'}
                      onClick={async () => {
                        if (!selectedId) return;
                        setMsg(null);
                        setBusy('bundle-otc');
                        try {
                          await customersApi.downloadSupportingDocumentsBundle(selectedId, 'otc_estr_supporting');
                        } catch (err) {
                          setMsg({ type: 'err', text: (err as Error).message });
                        } finally {
                          setBusy(null);
                        }
                      }}
                      className="w-full px-4 py-2 rounded-lg border border-teal-600 text-teal-800 text-sm font-medium hover:bg-teal-50 disabled:opacity-50"
                    >
                      {busy === 'bundle-otc' ? 'Building PDF…' : 'OTC ESTR supporting PDF (profile + cash only)'}
                    </button>
                    <button
                      type="button"
                      disabled={busy === 'bundle-aop'}
                      onClick={async () => {
                        if (!selectedId) return;
                        setMsg(null);
                        setBusy('bundle-aop');
                        try {
                          await customersApi.downloadSupportingDocumentsBundle(selectedId, 'aop_package');
                        } catch (err) {
                          setMsg({ type: 'err', text: (err as Error).message });
                        } finally {
                          setBusy(null);
                        }
                      }}
                      className="w-full px-4 py-2 rounded-lg border border-emerald-600 text-emerald-900 text-sm font-medium hover:bg-emerald-50 disabled:opacity-50"
                    >
                      {busy === 'bundle-aop' ? 'Building PDF…' : 'AOP package uploads (one PDF)'}
                    </button>
                    <button
                      type="button"
                      disabled={busy === 'bundle-all'}
                      onClick={async () => {
                        if (!selectedId) return;
                        setMsg(null);
                        setBusy('bundle-all');
                        try {
                          await customersApi.downloadSupportingDocumentsBundle(selectedId, 'all');
                        } catch (err) {
                          setMsg({ type: 'err', text: (err as Error).message });
                        } finally {
                          setBusy(null);
                        }
                      }}
                      className="w-full px-4 py-2 rounded-lg border border-slate-300 text-slate-800 text-sm font-medium hover:bg-slate-50 disabled:opacity-50"
                    >
                      {busy === 'bundle-all' ? 'Building PDF…' : 'Full archive (all uploads, one PDF)'}
                    </button>
                  </div>
                  <div className="text-xs font-medium text-slate-600 mb-2">Files on file for this customer</div>
                  <ul className="space-y-2 text-sm">
                    {selectedRow.aop_uploads.map((u) => (
                      <li
                        key={u.upload_id}
                        className="flex items-center justify-between gap-2 rounded border border-slate-200 px-3 py-2"
                      >
                        <span className="truncate text-slate-800" title={u.filename}>
                          {u.filename}
                          <span className="text-slate-500"> · {(u.size / 1024).toFixed(1)} KB</span>
                          {u.document_kind ? (
                            <span className="ml-2 text-xs text-violet-800 font-medium">
                              · {u.document_kind.replace('_', ' ')}
                            </span>
                          ) : null}
                          {u.persisted !== false ? (
                            <span className="ml-2 text-emerald-700 font-medium">· DB</span>
                          ) : (
                            <span className="ml-2 text-amber-700 font-medium">· session</span>
                          )}
                        </span>
                        <button
                          type="button"
                          className="shrink-0 text-sky-700 hover:underline text-xs font-medium"
                          onClick={() => customersApi.downloadAopUpload(selectedId, u.upload_id, u.filename)}
                        >
                          Download
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-red-700">Could not load this customer.</p>
          )}
        </section>
      </div>
    </DashboardLayout>
  );
}
