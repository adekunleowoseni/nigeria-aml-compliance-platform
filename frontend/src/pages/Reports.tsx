import { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { reportsApi, alertsApi } from '../services/api';
import DashboardLayout from '../components/layout/DashboardLayout';
import { useReportActionStore } from '../store/reportActionStore';

export default function Reports() {
  const [strResult, setStrResult] = useState<{ report_id: string; xml_preview: string | null; validation_passed: boolean } | null>(null);
  const [ctrResult, setCtrResult] = useState<{ report_id: string; validation_passed: boolean } | null>(null);
  const [strAlertId, setStrAlertId] = useState('');
  const [showStrModal, setShowStrModal] = useState(false);
  const [downloading, setDownloading] = useState<{ str?: string; ctr?: string }>({});
  const [alertSearch, setAlertSearch] = useState('');
  const lastAction = useReportActionStore((s) => s.lastAction);
  const clearLastAction = useReportActionStore((s) => s.clearLastAction);

  const { data: alertsList } = useQuery({
    queryKey: ['alerts', 0, 20],
    queryFn: () => alertsApi.list({ skip: 0, limit: 20 }),
  });

  const alerts = alertsList?.items ?? [];
  const openAlerts = alerts.filter((a) => a.status === 'open' || a.status === 'investigating' || a.status === 'escalated');

  const strMutation = useMutation({
    mutationFn: (alertId: string) => reportsApi.generateSTR({ alert_id: alertId }),
    onSuccess: (data) => {
      setStrResult(data);
      setShowStrModal(false);
      setStrAlertId('');
    },
    onError: () => setStrResult(null),
  });

  const ctrMutation = useMutation({
    mutationFn: () => reportsApi.generateCTR({}),
    onSuccess: (data) => setCtrResult(data),
    onError: () => setCtrResult(null),
  });

  const handleGenerateSTR = () => {
    if (alerts.length === 0) return;
    if (alerts.length === 1) {
      strMutation.mutate(alerts[0].id);
      return;
    }
    setAlertSearch('');
    setStrAlertId(lastAction?.alert_id ?? alerts[0]?.id ?? '');
    setShowStrModal(true);
  };

  const submitSTRFromModal = () => {
    const alertId = strAlertId || alerts[0]?.id;
    if (alertId) strMutation.mutate(alertId);
  };

  const handleDownloadSTR = async (format: 'word' | 'xml') => {
    if (!strResult?.report_id) return;
    setDownloading((d) => ({ ...d, str: format }));
    try {
      await reportsApi.downloadSTR(strResult.report_id, format);
    } catch (e) {
      console.error(e);
    } finally {
      setDownloading((d) => ({ ...d, str: undefined }));
    }
  };

  const handleDownloadCTR = async (format: 'word' | 'xml') => {
    if (!ctrResult?.report_id) return;
    setDownloading((d) => ({ ...d, ctr: format }));
    try {
      await reportsApi.downloadCTR(ctrResult.report_id, format);
    } catch (e) {
      console.error(e);
    } finally {
      setDownloading((d) => ({ ...d, ctr: undefined }));
    }
  };

  return (
    <DashboardLayout>
      <h1 className="text-2xl font-bold text-slate-900 mb-6">goAML Reports</h1>
      <p className="text-slate-600 mb-4">Generate and submit goAML-compliant STR/CTR reports.</p>

      {lastAction && (
        <div className="mb-6 p-4 bg-indigo-50 border border-indigo-200 rounded-lg text-indigo-900 text-sm">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <p className="font-medium">Last alert action</p>
              <p className="mt-1">
                <span className="font-mono bg-white/60 px-2 py-0.5 rounded border border-indigo-200">action_key: {lastAction.action_key}</span>
              </p>
              <p className="mt-1 text-indigo-800">
                Alert: <span className="font-mono">{lastAction.alert_id}</span>
                {lastAction.transaction_id ? (
                  <>
                    {' '}· Txn: <span className="font-mono">{lastAction.transaction_id}</span>
                  </>
                ) : null}
                {lastAction.customer_id ? (
                  <>
                    {' '}· Customer: <span className="font-mono">{lastAction.customer_id}</span>
                  </>
                ) : null}
              </p>
              {lastAction.summary && <p className="mt-1 text-indigo-800">{lastAction.summary}</p>}
            </div>
            <button
              type="button"
              onClick={clearLastAction}
              className="px-3 py-2 text-sm rounded-lg bg-white border border-indigo-200 hover:bg-indigo-100"
            >
              Clear
            </button>
          </div>
          <p className="mt-2 text-xs text-indigo-700">
            Tip: Generate STR will default to this alert.
          </p>
        </div>
      )}

      <div className="flex flex-wrap gap-4 mb-8">
        <button
          type="button"
          onClick={handleGenerateSTR}
          disabled={alerts.length === 0 || strMutation.isPending}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {strMutation.isPending ? 'Generating…' : 'Generate STR'}
        </button>
        <button
          type="button"
          onClick={() => ctrMutation.mutate()}
          disabled={ctrMutation.isPending}
          className="px-4 py-2 bg-slate-200 text-slate-800 rounded-lg hover:bg-slate-300 disabled:opacity-50"
        >
          {ctrMutation.isPending ? 'Generating…' : 'Generate CTR'}
        </button>
      </div>

      {strResult && (
        <div className="mb-6 p-4 bg-white rounded-lg shadow border border-slate-200">
          <h3 className="font-semibold text-slate-900 mb-2">STR generated (NFIU goAML)</h3>
          <p className="text-sm text-slate-600">
            Report ID: <span className="font-mono">{strResult.report_id}</span>
          </p>
          <p className="text-sm text-slate-600">
            Validation: {strResult.validation_passed ? (
              <span className="text-green-600">Passed</span>
            ) : (
              <span className="text-red-600">Failed</span>
            )}
          </p>
          <p className="text-sm font-medium text-slate-700 mt-3 mb-2">Download report</p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => handleDownloadSTR('word')}
              disabled={!!downloading.str}
              className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {downloading.str === 'word' ? 'Downloading…' : 'Download as Word (.docx)'}
            </button>
            <button
              type="button"
              onClick={() => handleDownloadSTR('xml')}
              disabled={!!downloading.str}
              className="px-3 py-1.5 text-sm bg-slate-600 text-white rounded hover:bg-slate-700 disabled:opacity-50"
            >
              {downloading.str === 'xml' ? 'Downloading…' : 'Download as XML (NFIU)'}
            </button>
          </div>
          {strResult.xml_preview && (
            <pre className="mt-2 p-2 bg-slate-50 rounded text-xs overflow-auto max-h-40">{strResult.xml_preview}</pre>
          )}
        </div>
      )}

      {ctrResult && (
        <div className="mb-6 p-4 bg-white rounded-lg shadow border border-slate-200">
          <h3 className="font-semibold text-slate-900 mb-2">CTR generated (NFIU goAML)</h3>
          <p className="text-sm text-slate-600">
            Report ID: <span className="font-mono">{ctrResult.report_id}</span>
          </p>
          <p className="text-sm text-slate-600">
            Validation: {ctrResult.validation_passed ? (
              <span className="text-green-600">Passed</span>
            ) : (
              <span className="text-red-600">Failed</span>
            )}
          </p>
          <p className="text-sm font-medium text-slate-700 mt-3 mb-2">Download report</p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => handleDownloadCTR('word')}
              disabled={!!downloading.ctr}
              className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {downloading.ctr === 'word' ? 'Downloading…' : 'Download as Word (.docx)'}
            </button>
            <button
              type="button"
              onClick={() => handleDownloadCTR('xml')}
              disabled={!!downloading.ctr}
              className="px-3 py-1.5 text-sm bg-slate-600 text-white rounded hover:bg-slate-700 disabled:opacity-50"
            >
              {downloading.ctr === 'xml' ? 'Downloading…' : 'Download as XML (NFIU)'}
            </button>
          </div>
        </div>
      )}

      {strMutation.isError && (
        <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm">
          Failed to generate STR: {(strMutation.error as Error).message}
        </div>
      )}
      {ctrMutation.isError && (
        <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm">
          Failed to generate CTR: {(ctrMutation.error as Error).message}
        </div>
      )}

      {/* Modal: choose alert for STR */}
      {showStrModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50"
          onClick={() => setShowStrModal(false)}
          role="dialog"
          aria-modal="true"
          aria-labelledby="str-modal-title"
        >
          <div
            className="bg-white rounded-xl shadow-xl max-w-2xl w-full p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id="str-modal-title" className="text-lg font-semibold text-slate-900 mb-4">
              Select alert for STR
            </h2>
            <p className="text-sm text-slate-600 mb-4">
              Choose the alert to generate a Suspicious Transaction Report.
            </p>
            {lastAction && (
              <div className="mb-3 text-xs text-slate-700">
                Default from last action: <span className="font-mono">{lastAction.action_key}</span>
              </div>
            )}
            <label className="block text-sm font-medium text-slate-700 mb-1" htmlFor="str-alert-search">
              Search alerts (Customer ID or Transaction ID)
            </label>
            <input
              id="str-alert-search"
              value={alertSearch}
              onChange={(e) => setAlertSearch(e.target.value)}
              placeholder="e.g. demo-txn-wire-001 or CUST-NG-2002"
              className="w-full rounded border border-slate-300 px-3 py-2 text-sm mb-3"
            />
            <select
              value={strAlertId}
              onChange={(e) => setStrAlertId(e.target.value)}
              className="w-full rounded border border-slate-300 px-3 py-2 text-sm mb-4"
            >
              <option value="">Select an alert</option>
              {alerts
                .filter((a) => {
                  const q = alertSearch.trim().toLowerCase();
                  if (!q) return true;
                  return (
                    a.id.toLowerCase().includes(q) ||
                    a.customer_id.toLowerCase().includes(q) ||
                    a.transaction_id.toLowerCase().includes(q) ||
                    (a.summary ?? '').toLowerCase().includes(q)
                  );
                })
                .map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.summary ?? a.id} ({a.customer_id}) · {a.transaction_id}
                  </option>
                ))}
            </select>
            <div className="flex gap-2 justify-end">
              <button
                type="button"
                onClick={() => setShowStrModal(false)}
                className="px-3 py-1.5 text-sm bg-slate-200 text-slate-800 rounded hover:bg-slate-300"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={submitSTRFromModal}
                disabled={!strAlertId && alerts.length > 0 ? false : !strAlertId}
                className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
              >
                Generate STR
              </button>
            </div>
          </div>
        </div>
      )}
    </DashboardLayout>
  );
}
