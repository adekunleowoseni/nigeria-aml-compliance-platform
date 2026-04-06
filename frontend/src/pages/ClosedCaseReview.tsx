import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import DashboardLayout from '../components/layout/DashboardLayout';
import { complianceApi, type ClosedCaseReviewItem } from '../services/api';
import { useAuthStore } from '../store/authStore';

function formatHistEntry(h: Record<string, unknown>, i: number) {
  const action = String(h.action ?? '—');
  const at = String(h.at ?? '');
  return (
    <li key={i} className="text-xs text-slate-600 border-b border-slate-100 py-1">
      <span className="font-medium text-slate-800">{action}</span>
      {at ? <span className="text-slate-400 ml-2">{at}</span> : null}
      {h.investigator_id ? <div>Investigator: {String(h.investigator_id)}</div> : null}
      {h.resolution ? <div>Resolution: {String(h.resolution)}</div> : null}
      {h.notes ? <div className="mt-0.5 whitespace-pre-wrap">{String(h.notes).slice(0, 500)}</div> : null}
    </li>
  );
}

export default function ClosedCaseReview() {
  const user = useAuthStore((s) => s.user);
  const role = (user?.role || '').toLowerCase();
  const email = (user?.email || '').trim().toLowerCase();
  const isAdmin = role === 'admin';
  const isCco = role === 'chief_compliance_officer';
  const isCo = role === 'compliance_officer';
  const canAccess = isAdmin || isCco || isCo;

  const [tab, setTab] = useState<'queue' | 'tuning' | 'generate'>('queue');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [periodStart, setPeriodStart] = useState('');
  const [periodEnd, setPeriodEnd] = useState('');
  const [sampleType, setSampleType] = useState('RANDOM');
  const [forceRegen, setForceRegen] = useState(false);

  const [findings, setFindings] = useState('');
  const [patternId, setPatternId] = useState('');
  const [recommendation, setRecommendation] = useState('');
  const [requiresReopen, setRequiresReopen] = useState(false);
  const [notifyCco, setNotifyCco] = useState(false);

  const qc = useQueryClient();

  const listQ = useQuery({
    queryKey: ['closed-case-reviews', tab],
    queryFn: () => complianceApi.listClosedCaseReviews({ limit: 100 }),
    enabled: canAccess && tab === 'queue',
  });

  const patternsQ = useQuery({
    queryKey: ['closed-case-patterns'],
    queryFn: () => complianceApi.closedCasePatterns(),
    enabled: canAccess,
  });

  const tuningQ = useQuery({
    queryKey: ['closed-case-tuning'],
    queryFn: () => complianceApi.closedCaseTuningProposals(80),
    enabled: canAccess && tab === 'tuning',
  });

  const genMut = useMutation({
    mutationFn: () =>
      complianceApi.generateClosedCaseReviews({
        review_period_start: periodStart,
        review_period_end: periodEnd,
        sample_type: sampleType,
        force: isAdmin && forceRegen,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['closed-case-reviews'] });
    },
  });

  const putMut = useMutation({
    mutationFn: (id: string) =>
      complianceApi.putClosedCaseReview(id, {
        findings,
        pattern_identified: patternId || undefined,
        recommendation_tuning: recommendation || undefined,
        requires_reopen: requiresReopen,
        notify_cco: notifyCco || requiresReopen,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['closed-case-reviews'] });
      qc.invalidateQueries({ queryKey: ['closed-case-tuning'] });
      setSelectedId(null);
      setFindings('');
      setPatternId('');
      setRecommendation('');
      setRequiresReopen(false);
      setNotifyCco(false);
    },
  });

  const selected = useMemo(() => {
    if (!selectedId || !listQ.data?.items) return null;
    return listQ.data.items.find((r) => r.id === selectedId) ?? null;
  }, [selectedId, listQ.data]);

  const canSubmitSelected = useMemo(() => {
    if (!selected || (selected.review_status || '').toUpperCase() === 'COMPLETED') return false;
    if (isAdmin || isCco) return true;
    const rev = (selected.reviewer_id || '').trim().toLowerCase();
    return Boolean(email && rev && email === rev);
  }, [selected, isAdmin, isCco, email]);

  if (!canAccess) {
    return (
      <DashboardLayout>
        <h1 className="text-2xl font-bold text-slate-900 mb-2">Closed case review</h1>
        <p className="text-slate-600">Compliance officer, CCO, or admin access is required.</p>
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout>
      <h1 className="text-2xl font-bold text-slate-900 mb-2">Closed case review</h1>
      <p className="text-slate-600 mb-6 max-w-3xl">
        Periodic sampling of closed alerts: document findings, control weaknesses, and scenario tuning.
        A batch is generated automatically on the 1st of each month for the prior calendar month (5% sample, minimum 10).
      </p>

      <div className="flex gap-2 mb-6 border-b border-slate-200 pb-2">
        {(['queue', 'tuning', 'generate'] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-lg text-sm font-medium ${
              tab === t ? 'bg-slate-800 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
            }`}
          >
            {t === 'queue' ? 'Review queue' : t === 'tuning' ? 'Tuning proposals' : 'Generate sample'}
          </button>
        ))}
      </div>

      {tab === 'generate' && (
        <section className="bg-white rounded-lg shadow border border-slate-100 p-6 mb-8 max-w-xl">
          <h2 className="text-lg font-semibold text-slate-900 mb-4">Generate review sample</h2>
          <div className="space-y-3">
            <label className="block text-sm">
              <span className="text-slate-600">Period start</span>
              <input
                type="date"
                value={periodStart}
                onChange={(e) => setPeriodStart(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="block text-sm">
              <span className="text-slate-600">Period end</span>
              <input
                type="date"
                value={periodEnd}
                onChange={(e) => setPeriodEnd(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="block text-sm">
              <span className="text-slate-600">Sample type</span>
              <select
                value={sampleType}
                onChange={(e) => setSampleType(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="RANDOM">Random (5%, min 10)</option>
                <option value="HIGH_RISK">High risk</option>
                <option value="ALL">All closed in period (capped)</option>
              </select>
            </label>
            {isAdmin && (
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input type="checkbox" checked={forceRegen} onChange={(e) => setForceRegen(e.target.checked)} />
                Force (ignore existing batch row; admin only)
              </label>
            )}
            <button
              type="button"
              disabled={!periodStart || !periodEnd || genMut.isPending}
              onClick={() => genMut.mutate()}
              className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {genMut.isPending ? 'Generating…' : 'Generate'}
            </button>
            {genMut.isError && (
              <p className="text-sm text-red-600">{(genMut.error as Error).message}</p>
            )}
            {genMut.isSuccess && (
              <pre className="text-xs bg-slate-50 p-3 rounded-lg overflow-auto max-h-48">
                {JSON.stringify(genMut.data, null, 2)}
              </pre>
            )}
          </div>
        </section>
      )}

      {tab === 'tuning' && (
        <section className="bg-white rounded-lg shadow border border-slate-100 p-6 mb-8">
          <h2 className="text-lg font-semibold text-slate-900 mb-4">Aggregated tuning signals</h2>
          {tuningQ.isLoading && <p className="text-slate-500 text-sm">Loading…</p>}
          {tuningQ.error && <p className="text-red-600 text-sm">{(tuningQ.error as Error).message}</p>}
          {tuningQ.data && (
            <div className="grid gap-6 lg:grid-cols-2">
              <div>
                <h3 className="text-sm font-medium text-slate-700 mb-2">By pattern</h3>
                <div className="overflow-x-auto border border-slate-100 rounded-lg max-h-[360px] overflow-y-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-slate-50 sticky top-0">
                      <tr>
                        <th className="text-left p-2">Pattern</th>
                        <th className="text-right p-2">Count</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(
                        tuningQ.data.aggregated_by_pattern as Array<{
                          pattern_identified?: string | null;
                          review_count?: number;
                        }>
                      ).map((row, i) => (
                        <tr key={i} className="border-t border-slate-100">
                          <td className="p-2">{String(row.pattern_identified ?? '—')}</td>
                          <td className="p-2 text-right">{row.review_count ?? 0}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
              <div>
                <h3 className="text-sm font-medium text-slate-700 mb-2">Recent recommendations</h3>
                <ul className="space-y-2 text-sm text-slate-600 max-h-[360px] overflow-y-auto">
                  {tuningQ.data.recent_recommendations.map((r, i) => (
                    <li key={i} className="border border-slate-100 rounded-lg p-2">
                      <div className="font-medium text-slate-800">{String(r.pattern_identified ?? '—')}</div>
                      <div className="text-xs mt-1 whitespace-pre-wrap">
                        {String(r.recommendation_tuning ?? '').slice(0, 400)}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </section>
      )}

      {tab === 'queue' && (
        <div className="grid gap-6 lg:grid-cols-2">
          <section className="bg-white rounded-lg shadow border border-slate-100 p-6">
            <h2 className="text-lg font-semibold text-slate-900 mb-4">Sample queue</h2>
            {listQ.isLoading && <p className="text-slate-500 text-sm">Loading…</p>}
            {listQ.error && <p className="text-red-600 text-sm">{(listQ.error as Error).message}</p>}
            {listQ.data && (
              <div className="overflow-x-auto max-h-[520px] overflow-y-auto border border-slate-100 rounded-lg">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 sticky top-0">
                    <tr>
                      <th className="text-left p-2">Status</th>
                      <th className="text-left p-2">Alert</th>
                      <th className="text-left p-2">Reviewer</th>
                      <th className="text-left p-2">Period</th>
                    </tr>
                  </thead>
                  <tbody>
                    {listQ.data.items.map((row: ClosedCaseReviewItem) => (
                      <tr
                        key={row.id}
                        className={`border-t border-slate-100 cursor-pointer hover:bg-slate-50 ${
                          selectedId === row.id ? 'bg-blue-50' : ''
                        }`}
                        onClick={() => setSelectedId(row.id)}
                      >
                        <td className="p-2">{row.review_status}</td>
                        <td className="p-2 font-mono text-xs">{row.alert_id.slice(0, 8)}…</td>
                        <td className="p-2 text-xs">{row.reviewer_id}</td>
                        <td className="p-2 text-xs">
                          {row.review_period_start} → {row.review_period_end}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="bg-white rounded-lg shadow border border-slate-100 p-6">
            {!selected && <p className="text-slate-500 text-sm">Select a row to view the alert and submit findings.</p>}
            {selected && (
              <div className="space-y-4">
                <div>
                  <h3 className="text-sm font-semibold text-slate-800">Alert summary</h3>
                  {selected.alert ? (
                    <div className="mt-2 text-sm text-slate-600 space-y-1">
                      <div>
                        <span className="text-slate-500">ID:</span> {selected.alert.id}
                      </div>
                      <div>
                        <span className="text-slate-500">Customer:</span> {selected.alert.customer_id}
                      </div>
                      <div>
                        <span className="text-slate-500">Severity:</span> {selected.alert.severity}
                      </div>
                      <div>
                        <span className="text-slate-500">Summary:</span> {selected.alert.summary}
                      </div>
                    </div>
                  ) : (
                    <p className="text-amber-700 text-sm mt-1">Alert not in memory (ID: {selected.alert_id})</p>
                  )}
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-slate-800">Investigation history</h3>
                  <ul className="mt-2 max-h-40 overflow-y-auto border border-slate-100 rounded-lg p-2 bg-slate-50">
                    {(selected.alert?.investigation_history || []).length === 0 && (
                      <li className="text-xs text-slate-500">No history</li>
                    )}
                    {(selected.alert?.investigation_history || []).map((h, i) =>
                      formatHistEntry(h as Record<string, unknown>, i)
                    )}
                  </ul>
                </div>

                {(selected.review_status || '').toUpperCase() === 'COMPLETED' ? (
                  <div className="text-sm text-slate-600 border border-slate-200 rounded-lg p-3 bg-slate-50">
                    <div className="font-medium text-slate-800">Completed</div>
                    {selected.findings && (
                      <div className="mt-2 whitespace-pre-wrap">{selected.findings}</div>
                    )}
                    {selected.pattern_identified && <div className="mt-1">Pattern: {selected.pattern_identified}</div>}
                    {selected.recommendation_tuning && (
                      <div className="mt-1 whitespace-pre-wrap">{selected.recommendation_tuning}</div>
                    )}
                    {selected.reopened_alert_id && (
                      <div className="mt-2 text-amber-800">Re-opened alert: {selected.reopened_alert_id}</div>
                    )}
                  </div>
                ) : canSubmitSelected ? (
                  <form
                    className="space-y-3 border-t border-slate-100 pt-4"
                    onSubmit={(e) => {
                      e.preventDefault();
                      if (findings.trim().length < 10) return;
                      putMut.mutate(selected.id);
                    }}
                  >
                    <label className="block text-sm">
                      <span className="text-slate-600">Findings (min 10 characters)</span>
                      <textarea
                        value={findings}
                        onChange={(e) => setFindings(e.target.value)}
                        rows={5}
                        className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                        placeholder="Control weaknesses, inconsistencies, pattern notes…"
                      />
                    </label>
                    <label className="block text-sm">
                      <span className="text-slate-600">Pattern (typology)</span>
                      <select
                        value={patternId}
                        onChange={(e) => setPatternId(e.target.value)}
                        className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                      >
                        <option value="">— Select —</option>
                        {(patternsQ.data?.items || []).map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="block text-sm">
                      <span className="text-slate-600">Tuning / recommendation</span>
                      <textarea
                        value={recommendation}
                        onChange={(e) => setRecommendation(e.target.value)}
                        rows={3}
                        className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                        placeholder="Suggested scenario threshold, rule, or process change…"
                      />
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={requiresReopen}
                        onChange={(e) => setRequiresReopen(e.target.checked)}
                      />
                      Requires re-open (creates new alert linked to original)
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <input type="checkbox" checked={notifyCco} onChange={(e) => setNotifyCco(e.target.checked)} />
                      Notify CCO by email (if SMTP configured)
                    </label>
                    <button
                      type="submit"
                      disabled={findings.trim().length < 10 || putMut.isPending}
                      className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-lg hover:bg-emerald-700 disabled:opacity-50"
                    >
                      {putMut.isPending ? 'Submitting…' : 'Submit review'}
                    </button>
                    {putMut.isError && (
                      <p className="text-sm text-red-600">{(putMut.error as Error).message}</p>
                    )}
                  </form>
                ) : (
                  <p className="text-sm text-amber-800">
                    Only the assigned reviewer (or CCO/admin) can submit findings for this row.
                  </p>
                )}
              </div>
            )}
          </section>
        </div>
      )}
    </DashboardLayout>
  );
}
