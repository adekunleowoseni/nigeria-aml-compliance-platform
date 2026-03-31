import { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import DashboardLayout from '../components/layout/DashboardLayout';
import { complianceApi } from '../services/api';

export default function Compliance() {
  const [screenName, setScreenName] = useState('');
  const refQuery = useQuery({
    queryKey: ['compliance', 'reference-jurisdictions'],
    queryFn: () => complianceApi.referenceJurisdictions(),
  });

  const screenMutation = useMutation({
    mutationFn: (name: string) => complianceApi.screenSanctions(name),
  });

  return (
    <DashboardLayout>
      <h1 className="text-2xl font-bold text-slate-900 mb-2">Compliance</h1>
      <p className="text-slate-600 mb-6 max-w-3xl">
        Reference high-risk jurisdictions for analyst awareness, and run a manual name screen against the online
        OpenSanctions search API (configure <code className="text-xs bg-slate-100 px-1 rounded">OPENSANCTIONS_API_KEY</code>{' '}
        if your environment returns 401).
      </p>

      <div className="grid gap-8 lg:grid-cols-2">
        <section className="bg-white rounded-lg shadow border border-slate-100 p-6">
          <h2 className="text-lg font-semibold text-slate-900 mb-1">Reference jurisdictions</h2>
          <p className="text-sm text-slate-500 mb-4">{refQuery.data?.disclaimer}</p>
          {refQuery.isLoading && <p className="text-slate-500 text-sm">Loading…</p>}
          {refQuery.error && (
            <p className="text-red-600 text-sm">{(refQuery.error as Error).message}</p>
          )}
          {refQuery.data?.jurisdictions && (
            <div className="overflow-x-auto max-h-[480px] overflow-y-auto border border-slate-100 rounded-lg">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 sticky top-0">
                  <tr>
                    <th className="text-left p-3 font-medium text-slate-700">Jurisdiction</th>
                    <th className="text-left p-3 font-medium text-slate-700">Note</th>
                  </tr>
                </thead>
                <tbody>
                  {refQuery.data.jurisdictions.map((row) => (
                    <tr key={row.jurisdiction} className="border-t border-slate-100 hover:bg-slate-50/80">
                      <td className="p-3 font-medium text-slate-900">{row.jurisdiction}</td>
                      <td className="p-3 text-slate-600">{row.note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="bg-white rounded-lg shadow border border-slate-100 p-6">
          <h2 className="text-lg font-semibold text-slate-900 mb-1">Manual sanctions name screen</h2>
          <p className="text-sm text-slate-500 mb-4">
            Queries OpenSanctions over the network. Empty matches are not a clearance — escalate per policy.
          </p>
          <div className="flex flex-col sm:flex-row gap-2 mb-4">
            <input
              type="text"
              value={screenName}
              onChange={(e) => setScreenName(e.target.value)}
              placeholder="Person or entity name"
              className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
            <button
              type="button"
              disabled={screenName.trim().length < 2 || screenMutation.isPending}
              onClick={() => screenMutation.mutate(screenName.trim())}
              className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {screenMutation.isPending ? 'Searching…' : 'Screen name'}
            </button>
          </div>
          {screenMutation.isError && (
            <p className="text-sm text-red-600 mb-2">{(screenMutation.error as Error).message}</p>
          )}
          {screenMutation.data && (
            <div className="rounded-lg bg-slate-50 border border-slate-100 p-4 text-sm">
              <p className="font-medium text-slate-800 mb-2">
                Query: <span className="font-mono">{String(screenMutation.data.query ?? screenName)}</span>
                {' · '}
                Matches: {String(screenMutation.data.match_count ?? 0)}
              </p>
              {'note' in screenMutation.data && screenMutation.data.note != null && (
                <p className="text-slate-600 mb-3">{String(screenMutation.data.note)}</p>
              )}
              {Array.isArray(screenMutation.data.matches) && screenMutation.data.matches.length > 0 && (
                <ul className="space-y-2">
                  {(screenMutation.data.matches as Array<Record<string, unknown>>).slice(0, 10).map((m, i) => (
                    <li key={i} className="border-l-2 border-amber-400 pl-3 text-slate-700">
                      <span className="font-medium">{String(m.caption ?? m.id ?? 'Match')}</span>
                      {m.schema != null && (
                        <span className="text-slate-500 text-xs block">Schema: {String(m.schema)}</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </section>
      </div>
    </DashboardLayout>
  );
}
