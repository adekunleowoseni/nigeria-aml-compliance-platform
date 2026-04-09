import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import DashboardLayout from '../components/layout/DashboardLayout';
import {
  adminRedFlagsApi,
  adminReferenceListsApi,
  adminReportingApi,
  aiApi,
  authApi,
  customersApi,
  type AiProvider,
  type AdminUserRow,
  type DetectionRuleCatalogItem,
  type RegulatoryCalendarEntry,
} from '../services/api';
import { useAuthStore } from '../store/authStore';

function mapLoginUserToStore(u: {
  display_name: string;
  email: string;
  role: string;
  aml_region?: string;
  aml_zones?: string[];
  aml_branch_codes?: string[];
}) {
  return {
    displayName: u.display_name,
    email: u.email,
    role: u.role,
    amlRegion: u.aml_region,
    amlZones: u.aml_zones,
    amlBranchCodes: u.aml_branch_codes,
  };
}

function SettingsMessageBanner({
  message,
}: {
  message: { type: 'success' | 'error'; text: string } | null;
}) {
  if (!message) return null;
  return (
    <div
      className={`mb-4 p-3 rounded-lg text-sm border ${
        message.type === 'success'
          ? 'bg-emerald-50 text-emerald-900 border-emerald-200'
          : 'bg-red-50 text-red-800 border-red-200'
      }`}
    >
      {message.text}
    </div>
  );
}

function SettingsSectionCard({
  id,
  title,
  description,
  badge,
  children,
}: {
  id?: string;
  title: string;
  description?: ReactNode;
  badge?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      id={id}
      className="bg-white rounded-xl border border-slate-200/90 shadow-sm scroll-mt-24 overflow-hidden"
    >
      <header className="px-5 py-4 border-b border-slate-100 bg-gradient-to-r from-slate-50/90 to-white">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-slate-900 tracking-tight">{title}</h2>
            {description ? <p className="text-sm text-slate-600 mt-1 leading-relaxed">{description}</p> : null}
          </div>
          {badge ? <div className="shrink-0">{badge}</div> : null}
        </div>
      </header>
      <div className="p-5">{children}</div>
    </section>
  );
}

type SettingsSectionId =
  | 'account'
  | 'scope'
  | 'users'
  | 'workflow'
  | 'reference-lists'
  | 'red-flags'
  | 'rule-catalog'
  | 'reporting'
  | 'ai'
  | 'preferences';

const ADMIN_ONLY_SECTIONS: SettingsSectionId[] = [
  'users',
  'workflow',
  'reference-lists',
  'red-flags',
  'rule-catalog',
  'reporting',
  'ai',
];

function SettingsNavItem({
  sectionId,
  activeSection,
  onSelect,
  children,
}: {
  sectionId: SettingsSectionId;
  activeSection: SettingsSectionId;
  onSelect: (id: SettingsSectionId) => void;
  children: ReactNode;
}) {
  const active = activeSection === sectionId;
  return (
    <button
      type="button"
      aria-pressed={active}
      className={`w-full text-left rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
        active
          ? 'bg-blue-50 text-blue-900 ring-1 ring-blue-200/80'
          : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
      }`}
      onClick={() => onSelect(sectionId)}
    >
      {children}
    </button>
  );
}

export default function Settings() {
  const queryClient = useQueryClient();
  const setSession = useAuthStore((s) => s.setSession);
  const authUser = useAuthStore((s) => s.user);
  const token = useAuthStore((s) => s.token);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [aiMessage, setAiMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [aiSaving, setAiSaving] = useState(false);
  const [scopeMessage, setScopeMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [selZones, setSelZones] = useState<string[]>([]);
  const [selBranches, setSelBranches] = useState<string[]>([]);
  const [adminMsg, setAdminMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [workflowMsg, setWorkflowMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [workflowSaving, setWorkflowSaving] = useState(false);
  const [wfAutoOtc, setWfAutoOtc] = useState(false);
  const [wfAutoStr, setWfAutoStr] = useState(false);
  const [reviewHighMonths, setReviewHighMonths] = useState(12);
  const [reviewMediumMonths, setReviewMediumMonths] = useState(18);
  const [reviewLowMonths, setReviewLowMonths] = useState(36);
  const [studentCorporateThreshold, setStudentCorporateThreshold] = useState(10000000);
  const [idExpiryWarningDays, setIdExpiryWarningDays] = useState(0);
  const [additionalDocsThreshold, setAdditionalDocsThreshold] = useState(20000000);
  const [newUserEmail, setNewUserEmail] = useState('');
  const [newUserPassword, setNewUserPassword] = useState('');
  const [newUserRole, setNewUserRole] = useState('compliance_officer');
  const [newUserName, setNewUserName] = useState('');
  const [newUserZones, setNewUserZones] = useState('zone_1');
  const [newUserBranches, setNewUserBranches] = useState('001,002');
  const [reportingMsg, setReportingMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [rpPack, setRpPack] = useState('cbn_default');
  const [rpInst, setRpInst] = useState('');
  const [rpEntity, setRpEntity] = useState('');
  const [rpReg, setRpReg] = useState('');
  const [rpNarrative, setRpNarrative] = useState('cbn_formal');
  const [rpOutputsJson, setRpOutputsJson] = useState('{}');
  const [rpApplyPreset, setRpApplyPreset] = useState(false);
  const [rpSaving, setRpSaving] = useState(false);
  const [calSlug, setCalSlug] = useState('');
  const [calTitle, setCalTitle] = useState('');
  const [calFamily, setCalFamily] = useState('other');
  const [calFreq, setCalFreq] = useState('monthly');
  const [calSaving, setCalSaving] = useState(false);
  const [refListMsg, setRefListMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [refListBusy, setRefListBusy] = useState(false);
  const [rfMsg, setRfMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [rfBusy, setRfBusy] = useState(false);
  const role = useAuthStore((s) => s.user?.role);
  const isAdmin = (role || '').toLowerCase() === 'admin';
  const canEditScope =
    (role || '').toLowerCase() === 'compliance_officer' || (role || '').toLowerCase() === 'chief_compliance_officer';

  const [activeSection, setActiveSection] = useState<SettingsSectionId>('account');

  useEffect(() => {
    if (activeSection === 'scope' && !canEditScope) {
      setActiveSection('account');
      return;
    }
    if (!isAdmin && ADMIN_ONLY_SECTIONS.includes(activeSection)) {
      setActiveSection('account');
    }
  }, [activeSection, canEditScope, isAdmin]);

  const catalogQuery = useQuery({
    queryKey: ['auth', 'catalog-zones'],
    queryFn: () => authApi.catalogZones(),
    enabled: !!token && (canEditScope || isAdmin),
  });

  const swZones = catalogQuery.data?.regions?.south_west?.zones ?? {};

  useEffect(() => {
    if (!authUser?.amlZones && !authUser?.amlBranchCodes) return;
    setSelZones(authUser.amlZones ?? []);
    setSelBranches(authUser.amlBranchCodes ?? []);
  }, [authUser?.amlZones, authUser?.amlBranchCodes]);

  const allBranchCodes = useMemo(() => {
    const codes: string[] = [];
    Object.values(swZones).forEach((z) => {
      if (z?.branches) codes.push(...Object.keys(z.branches));
    });
    return [...new Set(codes)].sort();
  }, [swZones]);

  const assignmentsMutation = useMutation({
    mutationFn: () =>
      authApi.updateAssignments({
        aml_region: 'south_west',
        aml_zones: selZones,
        aml_branch_codes: selBranches,
      }),
    onSuccess: (data) => {
      setSession(data.access_token, mapLoginUserToStore(data.user));
      setScopeMessage({ type: 'success', text: 'Zone and branch scope updated. JWT refreshed.' });
      queryClient.invalidateQueries({ queryKey: ['alerts'], exact: false });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['transactions'], exact: false });
    },
    onError: (e: Error) => setScopeMessage({ type: 'error', text: e.message }),
  });

  const usersQuery = useQuery({
    queryKey: ['auth', 'admin-users'],
    queryFn: () => authApi.adminListUsers(),
    enabled: isAdmin && !!token,
  });

  const reportingProfileQ = useQuery({
    queryKey: ['admin', 'reporting-profile'],
    queryFn: () => adminReportingApi.getProfile(),
    enabled: isAdmin && !!token,
  });

  const reportingCalQ = useQuery({
    queryKey: ['admin', 'reporting-calendar'],
    queryFn: () => adminReportingApi.getCalendar(),
    enabled: isAdmin && !!token,
  });

  const referenceListsQ = useQuery({
    queryKey: ['admin', 'reference-lists'],
    queryFn: () => adminReferenceListsApi.summary(),
    enabled: isAdmin && !!token,
  });

  const redFlagsQ = useQuery({
    queryKey: ['admin', 'red-flags'],
    queryFn: () => adminRedFlagsApi.listRules(),
    enabled: isAdmin && !!token,
  });
  const detectionCatalogQ = useQuery({
    queryKey: ['admin', 'detection-rule-catalog'],
    queryFn: () => adminRedFlagsApi.ruleCatalog(),
    enabled: isAdmin && !!token,
  });

  useEffect(() => {
    const p = reportingProfileQ.data?.profile;
    if (!p || Object.keys(p).length === 0) return;
    setRpPack((p.template_pack as string) || 'cbn_default');
    setRpInst((p.institution_display_name as string) || '');
    setRpEntity((p.reporting_entity_name as string) || '');
    setRpReg((p.entity_registration_ref as string) || '');
    setRpNarrative((p.narrative_style as string) || 'cbn_formal');
    try {
      setRpOutputsJson(JSON.stringify(p.default_outputs ?? {}, null, 2));
    } catch {
      setRpOutputsJson('{}');
    }
  }, [reportingProfileQ.data]);

  const createUserMutation = useMutation({
    mutationFn: () =>
      authApi.adminCreateUser({
        email: newUserEmail.trim(),
        password: newUserPassword,
        role: newUserRole,
        display_name: newUserName.trim() || newUserEmail.trim(),
        aml_region: 'south_west',
        aml_zones: newUserZones.split(',').map((s) => s.trim()).filter(Boolean),
        aml_branch_codes: newUserBranches.split(',').map((s) => s.trim()).filter(Boolean),
      }),
    onSuccess: () => {
      setAdminMsg({ type: 'success', text: 'User created.' });
      setNewUserEmail('');
      setNewUserPassword('');
      usersQuery.refetch();
    },
    onError: (e: Error) => setAdminMsg({ type: 'error', text: e.message }),
  });

  const toggleZone = (z: string) => {
    setSelZones((prev) => (prev.includes(z) ? prev.filter((x) => x !== z) : [...prev, z]));
  };

  const toggleBranch = (b: string) => {
    setSelBranches((prev) => (prev.includes(b) ? prev.filter((x) => x !== b) : [...prev, b]));
  };

  const aiSettingsQuery = useQuery({
    queryKey: ['ai-settings'],
    queryFn: () => aiApi.getSettings(),
    enabled: isAdmin,
  });

  const workflowQuery = useQuery({
    queryKey: ['auth', 'workflow-settings'],
    queryFn: () => authApi.getWorkflowSettings(),
    enabled: isAdmin && !!token,
  });
  const reviewRulesQuery = useQuery({
    queryKey: ['customers', 'review-rules'],
    queryFn: () => customersApi.getReviewRules(),
    enabled: isAdmin && !!token,
  });

  useEffect(() => {
    const d = workflowQuery.data;
    if (!d) return;
    setWfAutoOtc(d.cco_auto_approve_otc_reporting);
    setWfAutoStr(d.cco_auto_approve_str_on_escalation);
  }, [workflowQuery.data]);
  useEffect(() => {
    const r = reviewRulesQuery.data?.rules;
    if (!r) return;
    setReviewHighMonths(r.high_months);
    setReviewMediumMonths(r.medium_months);
    setReviewLowMonths(r.low_months);
    setStudentCorporateThreshold(r.student_monthly_turnover_recommend_corporate_ngn);
    setIdExpiryWarningDays(r.id_expiry_warning_days);
    setAdditionalDocsThreshold(r.require_additional_docs_when_monthly_turnover_above_ngn);
  }, [reviewRulesQuery.data]);

  const [selectedProvider, setSelectedProvider] = useState<AiProvider>('gemini');

  useEffect(() => {
    const p = aiSettingsQuery.data?.provider;
    if (p) setSelectedProvider(p);
  }, [aiSettingsQuery.data?.provider]);

  const handleChangePassword = async (e: FormEvent) => {
    e.preventDefault();
    if (newPassword !== confirmPassword) {
      setMessage({ type: 'error', text: 'New password and confirmation do not match.' });
      return;
    }
    if (newPassword.length < 8) {
      setMessage({ type: 'error', text: 'Password must be at least 8 characters.' });
      return;
    }
    setLoading(true);
    setMessage(null);
    try {
      await authApi.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      });
      setMessage({ type: 'success', text: 'Password updated successfully.' });
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } catch (e) {
      setMessage({
        type: 'error',
        text: e instanceof Error ? e.message : 'Failed to update password. Try again.',
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <DashboardLayout>
      <div className="max-w-7xl mx-auto pb-10">
        <header className="mb-8">
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Settings</h1>
          <p className="text-slate-600 mt-2 max-w-2xl text-sm sm:text-base leading-relaxed">
            Choose a topic in the sidebar to work on one area at a time. Your selection stays until you pick another.
          </p>
        </header>

        <div className="flex flex-col xl:flex-row gap-8 xl:gap-10 items-start">
          <aside className="w-full xl:w-60 shrink-0 xl:sticky xl:top-20 space-y-3 order-first xl:order-none">
            <nav
              className="rounded-xl border border-slate-200/90 bg-white p-3 shadow-sm"
              aria-label="Settings sections"
            >
              <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider px-2 mb-2">
                On this page
              </p>
              <ul className="space-y-0.5">
                <li>
                  <SettingsNavItem
                    sectionId="account"
                    activeSection={activeSection}
                    onSelect={setActiveSection}
                  >
                    Account & password
                  </SettingsNavItem>
                </li>
                {canEditScope ? (
                  <li>
                    <SettingsNavItem sectionId="scope" activeSection={activeSection} onSelect={setActiveSection}>
                      Zone & branch scope
                    </SettingsNavItem>
                  </li>
                ) : null}
                {isAdmin ? (
                  <>
                    <li className="pt-2 mt-2 border-t border-slate-100">
                      <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider px-2 block mb-1">
                        Administration
                      </span>
                    </li>
                    <li>
                      <SettingsNavItem sectionId="users" activeSection={activeSection} onSelect={setActiveSection}>
                        User management
                      </SettingsNavItem>
                    </li>
                    <li>
                      <SettingsNavItem sectionId="workflow" activeSection={activeSection} onSelect={setActiveSection}>
                        Workflow shortcuts
                      </SettingsNavItem>
                    </li>
                    <li>
                      <SettingsNavItem
                        sectionId="reference-lists"
                        activeSection={activeSection}
                        onSelect={setActiveSection}
                      >
                        Reference lists
                      </SettingsNavItem>
                    </li>
                    <li>
                      <SettingsNavItem sectionId="red-flags" activeSection={activeSection} onSelect={setActiveSection}>
                        Red-flag rules
                      </SettingsNavItem>
                    </li>
                    <li>
                      <SettingsNavItem sectionId="rule-catalog" activeSection={activeSection} onSelect={setActiveSection}>
                        Detection rule catalog
                      </SettingsNavItem>
                    </li>
                    <li>
                      <SettingsNavItem sectionId="reporting" activeSection={activeSection} onSelect={setActiveSection}>
                        Institution reporting
                      </SettingsNavItem>
                    </li>
                    <li>
                      <SettingsNavItem sectionId="ai" activeSection={activeSection} onSelect={setActiveSection}>
                        AI provider
                      </SettingsNavItem>
                    </li>
                  </>
                ) : null}
                <li className={isAdmin ? 'pt-2 mt-2 border-t border-slate-100' : ''}>
                  <SettingsNavItem
                    sectionId="preferences"
                    activeSection={activeSection}
                    onSelect={setActiveSection}
                  >
                    Preferences
                  </SettingsNavItem>
                </li>
              </ul>
            </nav>
            {!isAdmin ? (
              <p className="text-xs text-slate-500 leading-relaxed px-1 hidden xl:block">
                Organization-wide options appear when you sign in as an administrator.
              </p>
            ) : null}
          </aside>

          <div className="flex-1 min-w-0 w-full">
            {activeSection === 'account' && (
            <SettingsSectionCard
              title="Account & password"
              description="Change your password. Use a strong password with at least 8 characters."
            >
              <SettingsMessageBanner message={message} />
          <form onSubmit={handleChangePassword} className="space-y-4">
            <div>
              <label htmlFor="current-password" className="block text-sm font-medium text-slate-700 mb-1">
                Current password
              </label>
              <input
                id="current-password"
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
                placeholder="Enter current password"
                autoComplete="current-password"
              />
            </div>
            <div>
              <label htmlFor="new-password" className="block text-sm font-medium text-slate-700 mb-1">
                New password
              </label>
              <input
                id="new-password"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
                placeholder="At least 8 characters"
                autoComplete="new-password"
              />
            </div>
            <div>
              <label htmlFor="confirm-password" className="block text-sm font-medium text-slate-700 mb-1">
                Confirm new password
              </label>
              <input
                id="confirm-password"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
                placeholder="Confirm new password"
                autoComplete="new-password"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm font-medium"
            >
              {loading ? 'Updating…' : 'Change password'}
            </button>
          </form>
            </SettingsSectionCard>
            )}

        {canEditScope && activeSection === 'scope' && (
          <SettingsSectionCard
            title="Zone & branch scope"
            description="Compliance and CCO users can choose Southwest zones and branch codes. Transactions and alerts are filtered to customers mapped into those branches (demo: branch is derived from customer ID)."
          >
            <SettingsMessageBanner message={scopeMessage} />
            {catalogQuery.isLoading ? (
              <p className="text-sm text-slate-500">Loading catalog…</p>
            ) : (
              <>
                <p className="text-sm font-medium text-slate-800 mb-2">Zones</p>
                <div className="flex flex-wrap gap-2 mb-4">
                  {Object.entries(swZones).map(([key, z]) => (
                    <label key={key} className="inline-flex items-center gap-2 text-sm border rounded px-2 py-1 cursor-pointer">
                      <input type="checkbox" checked={selZones.includes(key)} onChange={() => toggleZone(key)} />
                      {z.label ?? key}
                    </label>
                  ))}
                </div>
                <p className="text-sm font-medium text-slate-800 mb-2">Branch codes</p>
                <div className="flex flex-wrap gap-2 mb-4 max-h-40 overflow-y-auto border border-slate-100 rounded p-2">
                  {allBranchCodes.map((code) => (
                    <label key={code} className="inline-flex items-center gap-1 text-xs border rounded px-2 py-0.5 cursor-pointer">
                      <input type="checkbox" checked={selBranches.includes(code)} onChange={() => toggleBranch(code)} />
                      {code}
                    </label>
                  ))}
                </div>
                <button
                  type="button"
                  disabled={assignmentsMutation.isPending || selZones.length === 0 || selBranches.length === 0}
                  onClick={() => assignmentsMutation.mutate()}
                  className="px-4 py-2 bg-slate-800 text-white rounded-lg text-sm hover:bg-slate-900 disabled:opacity-50"
                >
                  {assignmentsMutation.isPending ? 'Saving…' : 'Save scope & refresh session'}
                </button>
              </>
            )}
          </SettingsSectionCard>
        )}

        {isAdmin && activeSection === 'users' && (
          <SettingsSectionCard
            title="User management"
            description="Create users with roles and comma-separated zone / branch lists."
            badge={
              <span className="text-[10px] font-semibold uppercase tracking-wide text-amber-800 bg-amber-100 border border-amber-200/80 rounded-md px-2 py-0.5">
                Admin
              </span>
            }
          >
            <SettingsMessageBanner message={adminMsg} />
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
              <input
                className="text-sm border rounded px-2 py-2"
                placeholder="Email"
                value={newUserEmail}
                onChange={(e) => setNewUserEmail(e.target.value)}
              />
              <input
                type="password"
                className="text-sm border rounded px-2 py-2"
                placeholder="Password (min 8)"
                value={newUserPassword}
                onChange={(e) => setNewUserPassword(e.target.value)}
              />
              <input
                className="text-sm border rounded px-2 py-2"
                placeholder="Display name"
                value={newUserName}
                onChange={(e) => setNewUserName(e.target.value)}
              />
              <select
                className="text-sm border rounded px-2 py-2"
                value={newUserRole}
                onChange={(e) => setNewUserRole(e.target.value)}
              >
                <option value="compliance_officer">compliance_officer</option>
                <option value="chief_compliance_officer">chief_compliance_officer</option>
                <option value="admin">admin</option>
              </select>
              <input
                className="text-sm border rounded px-2 py-2 sm:col-span-2"
                placeholder="Zones e.g. zone_1,zone_2"
                value={newUserZones}
                onChange={(e) => setNewUserZones(e.target.value)}
              />
              <input
                className="text-sm border rounded px-2 py-2 sm:col-span-2"
                placeholder="Branches e.g. 001,002,003"
                value={newUserBranches}
                onChange={(e) => setNewUserBranches(e.target.value)}
              />
            </div>
            <button
              type="button"
              disabled={createUserMutation.isPending || !newUserEmail.trim() || newUserPassword.length < 8}
              onClick={() => createUserMutation.mutate()}
              className="px-4 py-2 bg-blue-700 text-white rounded-lg text-sm hover:bg-blue-800 disabled:opacity-50 mb-6"
            >
              {createUserMutation.isPending ? 'Creating…' : 'Create user'}
            </button>
            <h3 className="text-sm font-semibold text-slate-800 mb-2">Existing users</h3>
            {usersQuery.isLoading ? (
              <p className="text-sm text-slate-500">Loading…</p>
            ) : (
              <ul className="text-sm border border-slate-100 rounded divide-y max-h-48 overflow-y-auto">
                {(usersQuery.data?.items ?? []).map((u: AdminUserRow) => (
                  <li key={u.email} className="px-3 py-2 flex flex-wrap justify-between gap-2">
                    <span>
                      <span className="font-mono">{u.email}</span> · {u.role}
                    </span>
                    <span className="text-slate-500 text-xs">
                      {(u.aml_zones ?? []).join(',') || '—'} / {(u.aml_branch_codes ?? []).join(',') || '—'}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </SettingsSectionCard>
        )}

        {isAdmin && activeSection === 'workflow' && (
          <SettingsSectionCard
            title="Compliance workflow shortcuts"
            description={
              <>
                Defaults require a compliance officer to <strong>escalate</strong> and the CCO to approve before STR or
                OTC ESTR/ESAR generation. Enable these only for demos or training.
              </>
            }
            badge={
              <span className="text-[10px] font-semibold uppercase tracking-wide text-amber-800 bg-amber-100 border border-amber-200/80 rounded-md px-2 py-0.5">
                Admin
              </span>
            }
          >
            <SettingsMessageBanner message={workflowMsg} />
            {workflowQuery.isLoading ? (
              <p className="text-sm text-slate-500">Loading workflow settings…</p>
            ) : workflowQuery.isError ? (
              <p className="text-sm text-red-600">{(workflowQuery.error as Error).message}</p>
            ) : (
              <div className="space-y-3">
                <label className="flex items-start gap-2 text-sm text-slate-800 cursor-pointer">
                  <input
                    type="checkbox"
                    className="mt-1 rounded border-slate-300"
                    checked={wfAutoOtc}
                    onChange={(e) => setWfAutoOtc(e.target.checked)}
                  />
                  <span>
                    <strong>Auto OTC reporting approval</strong> — true-positive OTC filings immediately set CCO OTC approval
                    (and escalation is not required for Regulatory Reports eligibility). Also applies on escalation when enabled.
                  </span>
                </label>
                <label className="flex items-start gap-2 text-sm text-slate-800 cursor-pointer">
                  <input
                    type="checkbox"
                    className="mt-1 rounded border-slate-300"
                    checked={wfAutoStr}
                    onChange={(e) => setWfAutoStr(e.target.checked)}
                  />
                  <span>
                    <strong>Auto STR approval on true-positive escalation</strong> — when compliance escalates as true positive,
                    STR is pre-approved without a separate CCO click (excludes OTC ESTR/ESAR alerts).
                  </span>
                </label>
                <p className="text-xs text-slate-500">{workflowQuery.data?.description}</p>
                <button
                  type="button"
                  disabled={workflowSaving}
                  onClick={async () => {
                    setWorkflowSaving(true);
                    setWorkflowMsg(null);
                    try {
                      await authApi.putWorkflowSettings({
                        cco_auto_approve_otc_reporting: wfAutoOtc,
                        cco_auto_approve_str_on_escalation: wfAutoStr,
                      });
                      setWorkflowMsg({ type: 'success', text: 'Workflow settings updated for this running server.' });
                      await workflowQuery.refetch();
                      await queryClient.invalidateQueries({ queryKey: ['alerts'], exact: false });
                      await queryClient.invalidateQueries({ queryKey: ['reports', 'otc-eligible'], exact: false });
                    } catch (e) {
                      setWorkflowMsg({
                        type: 'error',
                        text: e instanceof Error ? e.message : 'Could not save workflow settings.',
                      });
                    } finally {
                      setWorkflowSaving(false);
                    }
                  }}
                  className="px-4 py-2 bg-slate-800 text-white rounded-lg text-sm hover:bg-slate-900 disabled:opacity-50"
                >
                  {workflowSaving ? 'Saving…' : 'Save workflow shortcuts'}
                </button>
                <div className="border-t border-slate-200 pt-4 mt-2">
                  <h4 className="text-sm font-semibold text-slate-900">Automatic customer review rules</h4>
                  <p className="text-xs text-slate-500 mt-1">
                    Controls next review date computation and profile-update recommendations shown on Customers page.
                  </p>
                  {reviewRulesQuery.isLoading ? (
                    <p className="text-sm text-slate-500 mt-2">Loading review rules…</p>
                  ) : reviewRulesQuery.isError ? (
                    <p className="text-sm text-red-600 mt-2">{(reviewRulesQuery.error as Error).message}</p>
                  ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
                      <label className="text-xs text-slate-700">
                        High risk review cycle (months)
                        <input
                          type="number"
                          min={1}
                          className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
                          value={reviewHighMonths}
                          onChange={(e) => setReviewHighMonths(Math.max(1, Number(e.target.value || 1)))}
                        />
                      </label>
                      <label className="text-xs text-slate-700">
                        Medium risk review cycle (months)
                        <input
                          type="number"
                          min={1}
                          className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
                          value={reviewMediumMonths}
                          onChange={(e) => setReviewMediumMonths(Math.max(1, Number(e.target.value || 1)))}
                        />
                      </label>
                      <label className="text-xs text-slate-700">
                        Low risk review cycle (months)
                        <input
                          type="number"
                          min={1}
                          className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
                          value={reviewLowMonths}
                          onChange={(e) => setReviewLowMonths(Math.max(1, Number(e.target.value || 1)))}
                        />
                      </label>
                      <label className="text-xs text-slate-700">
                        Student turnover threshold for corporate recommendation (NGN)
                        <input
                          type="number"
                          min={0}
                          className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
                          value={studentCorporateThreshold}
                          onChange={(e) => setStudentCorporateThreshold(Math.max(0, Number(e.target.value || 0)))}
                        />
                      </label>
                      <label className="text-xs text-slate-700">
                        ID expiry warning window (days)
                        <input
                          type="number"
                          min={0}
                          className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
                          value={idExpiryWarningDays}
                          onChange={(e) => setIdExpiryWarningDays(Math.max(0, Number(e.target.value || 0)))}
                        />
                      </label>
                      <label className="text-xs text-slate-700">
                        Turnover threshold for additional docs recommendation (NGN)
                        <input
                          type="number"
                          min={0}
                          className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
                          value={additionalDocsThreshold}
                          onChange={(e) => setAdditionalDocsThreshold(Math.max(0, Number(e.target.value || 0)))}
                        />
                      </label>
                      <div className="md:col-span-2">
                        <button
                          type="button"
                          disabled={workflowSaving}
                          onClick={async () => {
                            setWorkflowSaving(true);
                            setWorkflowMsg(null);
                            try {
                              await customersApi.putReviewRules({
                                high_months: reviewHighMonths,
                                medium_months: reviewMediumMonths,
                                low_months: reviewLowMonths,
                                student_monthly_turnover_recommend_corporate_ngn: studentCorporateThreshold,
                                id_expiry_warning_days: idExpiryWarningDays,
                                require_additional_docs_when_monthly_turnover_above_ngn: additionalDocsThreshold,
                              });
                              setWorkflowMsg({ type: 'success', text: 'Automatic review rules updated.' });
                              await reviewRulesQuery.refetch();
                              await queryClient.invalidateQueries({ queryKey: ['customers'], exact: false });
                            } catch (e) {
                              setWorkflowMsg({
                                type: 'error',
                                text: e instanceof Error ? e.message : 'Could not save automatic review rules.',
                              });
                            } finally {
                              setWorkflowSaving(false);
                            }
                          }}
                          className="px-4 py-2 bg-blue-700 text-white rounded-lg text-sm hover:bg-blue-800 disabled:opacity-50"
                        >
                          Save automatic review rules
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </SettingsSectionCard>
        )}

        {isAdmin && activeSection === 'reference-lists' && (
          <SettingsSectionCard
            title="Reference lists"
            description={
              <>
                Upload <strong>JSON</strong> or <strong>XML</strong> ({'<items><item>…</item></items>'}) for sanctions,
                PEP, and adverse media. Names use fuzzy matching against customers. Full-database screening can run on a
                schedule (API or Celery Beat).
              </>
            }
            badge={
              <span className="text-[10px] font-semibold uppercase tracking-wide text-amber-800 bg-amber-100 border border-amber-200/80 rounded-md px-2 py-0.5">
                Admin
              </span>
            }
          >
            <SettingsMessageBanner message={refListMsg} />
            {referenceListsQ.isLoading ? (
              <p className="text-sm text-slate-500">Loading reference list counts…</p>
            ) : referenceListsQ.isError ? (
              <p className="text-sm text-red-600">{(referenceListsQ.error as Error).message}</p>
            ) : (
              <div className="space-y-4 text-sm">
                <p className="text-slate-700">
                  <span className="font-medium">Records on server:</span> sanctions{' '}
                  <span className="font-mono">{referenceListsQ.data?.counts?.sanctions ?? 0}</span>, PEP{' '}
                  <span className="font-mono">{referenceListsQ.data?.counts?.pep ?? 0}</span>, adverse media{' '}
                  <span className="font-mono">{referenceListsQ.data?.counts?.adverse_media ?? 0}</span>
                </p>
                {referenceListsQ.data?.latest_screening_run &&
                  typeof referenceListsQ.data.latest_screening_run === 'object' && (
                    <p className="text-xs text-slate-600">
                      Last full scan:{' '}
                      {String(
                        (referenceListsQ.data.latest_screening_run as { run_at?: string }).run_at ?? '—',
                      )}{' '}
                      · customers{' '}
                      {(referenceListsQ.data.latest_screening_run as { customers_scanned?: number }).customers_scanned ?? '—'}{' '}
                      · hits{' '}
                      {(referenceListsQ.data.latest_screening_run as { hits_total?: number }).hits_total ?? '—'}
                    </p>
                  )}
                {(
                  [
                    { key: 'sanctions' as const, label: 'Sanctions / watchlist' },
                    { key: 'pep' as const, label: 'PEP list' },
                    { key: 'adverse_media' as const, label: 'Adverse media' },
                  ] as const
                ).map(({ key, label }) => (
                  <label key={key} className="flex flex-col sm:flex-row sm:items-center gap-2 border border-slate-100 rounded-lg p-3 bg-slate-50/50">
                    <span className="text-slate-800 font-medium sm:w-44 shrink-0">{label}</span>
                    <input
                      type="file"
                      accept=".json,.xml,application/json,application/xml,text/xml"
                      className="text-xs text-slate-600 flex-1 min-w-0"
                      disabled={refListBusy}
                      onChange={async (e) => {
                        const f = e.target.files?.[0];
                        e.target.value = '';
                        if (!f) return;
                        setRefListBusy(true);
                        setRefListMsg(null);
                        try {
                          const r = await adminReferenceListsApi.uploadFile(key, f);
                          setRefListMsg({
                            type: 'success',
                            text: `Loaded ${r.records_loaded} record(s) into ${r.list_type}.`,
                          });
                          await referenceListsQ.refetch();
                        } catch (err) {
                          setRefListMsg({
                            type: 'error',
                            text: err instanceof Error ? err.message : 'Upload failed.',
                          });
                        } finally {
                          setRefListBusy(false);
                        }
                      }}
                    />
                  </label>
                ))}
                <div className="flex flex-wrap items-center gap-2 pt-2">
                  <button
                    type="button"
                    disabled={refListBusy}
                    onClick={async () => {
                      setRefListBusy(true);
                      setRefListMsg(null);
                      try {
                        const r = await adminReferenceListsApi.runScreeningNow();
                        setRefListMsg({
                          type: 'success',
                          text: `Screening finished: ${r.customers_scanned} customers scanned, ${r.hits_total} hit(s) (threshold ${r.fuzzy_threshold}).${r.hits_truncated ? ' Results truncated in log.' : ''}`,
                        });
                        await referenceListsQ.refetch();
                      } catch (err) {
                        setRefListMsg({
                          type: 'error',
                          text: err instanceof Error ? err.message : 'Screening failed.',
                        });
                      } finally {
                        setRefListBusy(false);
                      }
                    }}
                    className="px-4 py-2 bg-slate-800 text-white rounded-lg text-sm hover:bg-slate-900 disabled:opacity-50"
                  >
                    {refListBusy ? 'Working…' : 'Run full-database screening now'}
                  </button>
                  <span className="text-xs text-slate-500">Admin JWT or scheduled worker with internal key.</span>
                </div>
              </div>
            )}
          </SettingsSectionCard>
        )}

        {isAdmin && activeSection === 'red-flags' && (
          <SettingsSectionCard
            title="AML red-flag rule library"
            description={
              <>
                Map <strong>titles</strong> to <strong>descriptions</strong> and optional <strong>match_patterns</strong>{' '}
                (keywords OR-matched on narration, remarks, KYC, counterparty, metadata). The LLM uses remarks plus a{' '}
                <strong>customer activity summary</strong> to map to catalog{' '}
                <code className="text-xs bg-slate-100 px-1 rounded">rule_code</code>s and can raise{' '}
                <span className="font-mono text-xs">RF-AI-EXT-*</span> when nothing fits. Optional:{' '}
                <span className="font-mono text-xs">AML_RED_FLAG_AI_OBSERVATION_LOG</span>. Use{' '}
                <code className="text-xs bg-slate-100 px-1 rounded">regex:</code> for regex. Upload JSON{' '}
                <strong>array</strong> or <code className="text-xs bg-slate-100 px-1 rounded">rules</code> /{' '}
                <code className="text-xs bg-slate-100 px-1 rounded">items</code>. Starter:{' '}
                <span className="font-mono text-xs">backend/data/red_flag_rules_starter.json</span>.
              </>
            }
            badge={
              <span className="text-[10px] font-semibold uppercase tracking-wide text-amber-800 bg-amber-100 border border-amber-200/80 rounded-md px-2 py-0.5">
                Admin
              </span>
            }
          >
            <SettingsMessageBanner message={rfMsg} />
            {redFlagsQ.isLoading ? (
              <p className="text-sm text-slate-500">Loading red-flag rules…</p>
            ) : redFlagsQ.isError ? (
              <p className="text-sm text-red-600">{(redFlagsQ.error as Error).message}</p>
            ) : (
              <div className="space-y-4 text-sm">
                <p className="text-slate-700">
                  <span className="font-medium">Rules on server:</span>{' '}
                  <span className="font-mono">{redFlagsQ.data?.items?.length ?? 0}</span> (
                  <span className="font-mono">
                    {redFlagsQ.data?.items?.filter((r) => r.enabled).length ?? 0}
                  </span>{' '}
                  enabled)
                </p>
                <label className="flex flex-col gap-2 border border-slate-100 rounded-lg p-3 bg-slate-50/50">
                  <span className="font-medium text-slate-800">Upload / merge JSON array</span>
                  <input
                    type="file"
                    accept=".json,application/json"
                    className="text-xs text-slate-600"
                    disabled={rfBusy}
                    onChange={async (e) => {
                      const f = e.target.files?.[0];
                      e.target.value = '';
                      if (!f) return;
                      setRfBusy(true);
                      setRfMsg(null);
                      try {
                        const raw = JSON.parse(await f.text()) as unknown;
                        let payload: Record<string, unknown>[] | Record<string, unknown>;
                        if (Array.isArray(raw)) {
                          payload = raw as Record<string, unknown>[];
                        } else if (raw && typeof raw === 'object') {
                          const o = raw as Record<string, unknown>;
                          const arr = o.rules ?? o.items;
                          if (!Array.isArray(arr))
                            throw new Error(
                              'JSON must be an array of rules, or an object with a "rules" or "items" array (see starter file).',
                            );
                          payload = o;
                        } else {
                          throw new Error('Invalid JSON.');
                        }
                        const res = await adminRedFlagsApi.uploadJson(payload);
                        const errs = res.errors?.length ? ` Warnings: ${res.errors.slice(0, 5).join(' · ')}` : '';
                        setRfMsg({
                          type: res.errors?.length ? 'error' : 'success',
                          text: `Upserted ${res.upserted} rule(s).${errs}`,
                        });
                        await redFlagsQ.refetch();
                      } catch (err) {
                        setRfMsg({
                          type: 'error',
                          text: err instanceof Error ? err.message : 'Upload failed.',
                        });
                      } finally {
                        setRfBusy(false);
                      }
                    }}
                  />
                </label>
                {(redFlagsQ.data?.items?.length ?? 0) > 0 ? (
                  <div className="max-h-56 overflow-y-auto border border-slate-100 rounded-md">
                    <table className="w-full text-xs">
                      <thead className="bg-slate-100 text-slate-700 text-left">
                        <tr>
                          <th className="p-2">Code</th>
                          <th className="p-2">Title</th>
                          <th className="p-2">On</th>
                          <th className="p-2 w-16"> </th>
                        </tr>
                      </thead>
                      <tbody>
                        {(redFlagsQ.data?.items ?? []).map((r) => (
                          <tr key={r.id} className="border-t border-slate-100">
                            <td className="p-2 font-mono text-slate-800">{r.rule_code}</td>
                            <td className="p-2 text-slate-700">{r.title}</td>
                            <td className="p-2">{r.enabled ? 'Yes' : 'No'}</td>
                            <td className="p-2">
                              <button
                                type="button"
                                className="text-red-700 hover:underline disabled:opacity-50"
                                disabled={rfBusy}
                                onClick={async () => {
                                  if (!confirm(`Delete rule ${r.rule_code}?`)) return;
                                  setRfBusy(true);
                                  setRfMsg(null);
                                  try {
                                    await adminRedFlagsApi.deleteRule(r.rule_code);
                                    setRfMsg({ type: 'success', text: `Deleted ${r.rule_code}.` });
                                    await redFlagsQ.refetch();
                                  } catch (err) {
                                    setRfMsg({
                                      type: 'error',
                                      text: err instanceof Error ? err.message : 'Delete failed.',
                                    });
                                  } finally {
                                    setRfBusy(false);
                                  }
                                }}
                              >
                                Delete
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </div>
            )}
          </SettingsSectionCard>
        )}

        {isAdmin && activeSection === 'reporting' && (
          <SettingsSectionCard
            title="Institution reporting"
            description="Template pack, entity names, and the regulatory return calendar drive goAML-style stubs, STR/XML headers, and FTR XML. Adjust for your institution."
            badge={
              <span className="text-[10px] font-semibold uppercase tracking-wide text-amber-800 bg-amber-100 border border-amber-200/80 rounded-md px-2 py-0.5">
                Admin
              </span>
            }
          >
            <SettingsMessageBanner message={reportingMsg} />
            {reportingProfileQ.isLoading ? (
              <p className="text-sm text-slate-500 mb-6">Loading reporting profile…</p>
            ) : reportingProfileQ.isError ? (
              <p className="text-sm text-red-600 mb-6">{(reportingProfileQ.error as Error).message}</p>
            ) : (
              <div className="space-y-4 mb-8">
                <div className="grid sm:grid-cols-2 gap-3">
                  <label className="block text-sm font-medium text-slate-700">
                    Template pack
                    <select
                      className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
                      value={rpPack}
                      onChange={(e) => setRpPack(e.target.value)}
                    >
                      <option value="cbn_default">CBN-aligned (generic)</option>
                      <option value="gtbank">GTBank-style</option>
                      <option value="zenith">Zenith-style</option>
                      <option value="uba">UBA-style</option>
                      <option value="access">Access-style</option>
                      <option value="custom">Custom</option>
                    </select>
                  </label>
                  <label className="block text-sm font-medium text-slate-700">
                    Narrative style
                    <select
                      className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
                      value={rpNarrative}
                      onChange={(e) => setRpNarrative(e.target.value)}
                    >
                      <option value="cbn_formal">CBN formal</option>
                      <option value="bank_standard">Bank standard</option>
                      <option value="concise">Concise</option>
                    </select>
                  </label>
                  <label className="block text-sm font-medium text-slate-700 sm:col-span-2">
                    Institution display name
                    <input
                      className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
                      value={rpInst}
                      onChange={(e) => setRpInst(e.target.value)}
                    />
                  </label>
                  <label className="block text-sm font-medium text-slate-700 sm:col-span-2">
                    Reporting entity name (XML / goAML)
                    <input
                      className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
                      value={rpEntity}
                      onChange={(e) => setRpEntity(e.target.value)}
                    />
                  </label>
                  <label className="block text-sm font-medium text-slate-700 sm:col-span-2">
                    Entity registration reference (RC / licence)
                    <input
                      className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
                      value={rpReg}
                      onChange={(e) => setRpReg(e.target.value)}
                    />
                  </label>
                </div>
                <label className="flex items-start gap-2 text-sm text-slate-800 cursor-pointer">
                  <input
                    type="checkbox"
                    className="mt-1 rounded border-slate-300"
                    checked={rpApplyPreset}
                    onChange={(e) => setRpApplyPreset(e.target.checked)}
                  />
                  <span>
                    On save, apply selected pack defaults to institution / entity / RC fields (overwrites the three text
                    fields above; ignored for Custom).
                  </span>
                </label>
                <label className="block text-sm font-medium text-slate-700">
                  Default output hints (JSON)
                  <textarea
                    className="mt-1 w-full font-mono text-xs rounded border border-slate-300 px-3 py-2 min-h-[100px]"
                    value={rpOutputsJson}
                    onChange={(e) => setRpOutputsJson(e.target.value)}
                    spellCheck={false}
                  />
                </label>
                {reportingProfileQ.data?.default_outputs_effective && (
                  <p className="text-xs text-slate-500">
                    Effective defaults after merge:{' '}
                    <code className="bg-slate-100 px-1 rounded">
                      {JSON.stringify(reportingProfileQ.data.default_outputs_effective)}
                    </code>
                  </p>
                )}
                <button
                  type="button"
                  disabled={rpSaving || !rpInst.trim() || !rpEntity.trim() || !rpReg.trim()}
                  onClick={async () => {
                    setRpSaving(true);
                    setReportingMsg(null);
                    let parsed: Record<string, unknown> = {};
                    try {
                      parsed = JSON.parse(rpOutputsJson || '{}') as Record<string, unknown>;
                      if (typeof parsed !== 'object' || parsed === null) throw new Error('Must be a JSON object');
                    } catch (e) {
                      setReportingMsg({
                        type: 'error',
                        text: e instanceof Error ? e.message : 'Invalid JSON for default outputs.',
                      });
                      setRpSaving(false);
                      return;
                    }
                    try {
                      await adminReportingApi.putProfile({
                        template_pack: rpPack,
                        institution_display_name: rpInst.trim(),
                        reporting_entity_name: rpEntity.trim(),
                        entity_registration_ref: rpReg.trim(),
                        default_outputs: parsed,
                        narrative_style: rpNarrative,
                        apply_preset_defaults: rpApplyPreset,
                      });
                      setReportingMsg({ type: 'success', text: 'Reporting profile saved.' });
                      await reportingProfileQ.refetch();
                    } catch (e) {
                      setReportingMsg({
                        type: 'error',
                        text: e instanceof Error ? e.message : 'Could not save reporting profile.',
                      });
                    } finally {
                      setRpSaving(false);
                    }
                  }}
                  className="px-4 py-2 bg-emerald-700 text-white rounded-lg text-sm hover:bg-emerald-800 disabled:opacity-50"
                >
                  {rpSaving ? 'Saving…' : 'Save reporting profile'}
                </button>
              </div>
            )}

            <h3 className="text-sm font-semibold text-slate-800 mb-2">Regulatory return calendar</h3>
            {reportingCalQ.isLoading ? (
              <p className="text-sm text-slate-500">Loading calendar…</p>
            ) : reportingCalQ.isError ? (
              <p className="text-sm text-red-600">{(reportingCalQ.error as Error).message}</p>
            ) : (
              <>
                <div className="overflow-x-auto border border-slate-100 rounded mb-4">
                  <table className="min-w-full text-sm">
                    <thead className="bg-slate-50 text-left">
                      <tr>
                        <th className="px-3 py-2 font-medium">Slug</th>
                        <th className="px-3 py-2 font-medium">Title</th>
                        <th className="px-3 py-2 font-medium">Family</th>
                        <th className="px-3 py-2 font-medium">Frequency</th>
                        <th className="px-3 py-2 font-medium">On</th>
                        <th className="px-3 py-2 font-medium w-24" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {(reportingCalQ.data?.items ?? []).map((row: RegulatoryCalendarEntry) => (
                        <tr key={row.id}>
                          <td className="px-3 py-2 font-mono text-xs">{row.slug}</td>
                          <td className="px-3 py-2">{row.title}</td>
                          <td className="px-3 py-2">{row.report_family}</td>
                          <td className="px-3 py-2">{row.frequency}</td>
                          <td className="px-3 py-2">
                            <label className="inline-flex items-center gap-1 cursor-pointer">
                              <input
                                type="checkbox"
                                checked={row.enabled !== false}
                                onChange={async (e) => {
                                  try {
                                    await adminReportingApi.patchCalendar(row.id, { enabled: e.target.checked });
                                    await reportingCalQ.refetch();
                                  } catch (err) {
                                    setReportingMsg({
                                      type: 'error',
                                      text: err instanceof Error ? err.message : 'Could not update entry.',
                                    });
                                  }
                                }}
                              />
                              <span className="text-xs text-slate-600">enabled</span>
                            </label>
                          </td>
                          <td className="px-3 py-2">
                            <button
                              type="button"
                              className="text-red-700 text-xs hover:underline"
                              onClick={async () => {
                                if (!confirm(`Remove calendar row “${row.slug}”?`)) return;
                                try {
                                  await adminReportingApi.deleteCalendar(row.id);
                                  await reportingCalQ.refetch();
                                  setReportingMsg({ type: 'success', text: 'Calendar entry removed.' });
                                } catch (err) {
                                  setReportingMsg({
                                    type: 'error',
                                    text: err instanceof Error ? err.message : 'Could not delete.',
                                  });
                                }
                              }}
                            >
                              Delete
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="text-xs text-slate-500 mb-3">
                  Upcoming preview (next occurrences):{' '}
                  {(reportingCalQ.data?.upcoming_preview ?? []).length
                    ? JSON.stringify(reportingCalQ.data?.upcoming_preview).slice(0, 400) +
                      ((reportingCalQ.data?.upcoming_preview?.length ?? 0) > 3 ? '…' : '')
                    : '—'}
                </p>
                <div className="grid sm:grid-cols-2 gap-3 border-t border-slate-100 pt-4">
                  <input
                    className="text-sm border rounded px-2 py-2"
                    placeholder="slug (unique)"
                    value={calSlug}
                    onChange={(e) => setCalSlug(e.target.value)}
                  />
                  <input
                    className="text-sm border rounded px-2 py-2 sm:col-span-2"
                    placeholder="Title"
                    value={calTitle}
                    onChange={(e) => setCalTitle(e.target.value)}
                  />
                  <input
                    className="text-sm border rounded px-2 py-2"
                    placeholder="Report family e.g. str, ctr, ftr"
                    value={calFamily}
                    onChange={(e) => setCalFamily(e.target.value)}
                  />
                  <select
                    className="text-sm border rounded px-2 py-2"
                    value={calFreq}
                    onChange={(e) => setCalFreq(e.target.value)}
                  >
                    <option value="daily">daily</option>
                    <option value="weekly">weekly</option>
                    <option value="monthly">monthly</option>
                    <option value="quarterly">quarterly</option>
                    <option value="annual">annual</option>
                    <option value="cron">cron</option>
                  </select>
                  <button
                    type="button"
                    disabled={calSaving || !calSlug.trim() || !calTitle.trim()}
                    className="sm:col-span-2 px-4 py-2 bg-slate-700 text-white rounded-lg text-sm hover:bg-slate-800 disabled:opacity-50"
                    onClick={async () => {
                      setCalSaving(true);
                      setReportingMsg(null);
                      try {
                        await adminReportingApi.createCalendar({
                          slug: calSlug.trim().toLowerCase(),
                          title: calTitle.trim(),
                          report_family: calFamily.trim().toLowerCase() || 'other',
                          frequency: calFreq,
                          preferred_formats: {},
                        });
                        setCalSlug('');
                        setCalTitle('');
                        setReportingMsg({ type: 'success', text: 'Calendar entry added.' });
                        await reportingCalQ.refetch();
                      } catch (e) {
                        setReportingMsg({
                          type: 'error',
                          text: e instanceof Error ? e.message : 'Could not add calendar entry.',
                        });
                      } finally {
                        setCalSaving(false);
                      }
                    }}
                  >
                    {calSaving ? 'Adding…' : 'Add calendar row'}
                  </button>
                </div>
              </>
            )}
          </SettingsSectionCard>
        )}

        {isAdmin && activeSection === 'rule-catalog' && (
          <SettingsSectionCard
            title="Detection rule catalog"
            description="Read-only catalog of all rule families used to flag transactions: configurable red-flags/patterns, typologies, and anomaly logic."
            badge={
              <span className="text-[10px] font-semibold uppercase tracking-wide text-amber-800 bg-amber-100 border border-amber-200/80 rounded-md px-2 py-0.5">
                Admin
              </span>
            }
          >
            {detectionCatalogQ.isLoading ? (
              <p className="text-sm text-slate-500">Loading detection catalog…</p>
            ) : detectionCatalogQ.isError ? (
              <p className="text-sm text-red-600">{(detectionCatalogQ.error as Error).message}</p>
            ) : (
              <div className="space-y-6 text-sm">
                <div className="rounded-lg border border-slate-200 p-4 bg-slate-50/40">
                  <p className="font-semibold text-slate-900 mb-2">Pattern sources</p>
                  <ul className="space-y-2">
                    {(detectionCatalogQ.data?.pattern_sources ?? []).map((p) => (
                      <li key={p.source} className="text-slate-700">
                        <span className="font-medium">{p.source}:</span> {p.description}
                      </li>
                    ))}
                  </ul>
                </div>

                {(
                  [
                    {
                      title: 'Custom red-flag rules (admin-managed)',
                      rows: (detectionCatalogQ.data?.red_flag_rules ?? []).map((r) => ({
                        rule_id: r.rule_code,
                        title: r.title,
                        description: r.description,
                      })),
                      empty: 'No red-flag rules available.',
                    },
                    {
                      title: 'Built-in typology rules',
                      rows: detectionCatalogQ.data?.typology_rules ?? [],
                      empty: 'No typology rules found.',
                    },
                    {
                      title: 'Anomaly rules',
                      rows: detectionCatalogQ.data?.anomaly_rules ?? [],
                      empty: 'No anomaly rules found.',
                    },
                  ] as const
                ).map((block) => (
                  <div key={block.title} className="rounded-lg border border-slate-200 overflow-hidden">
                    <div className="px-4 py-3 bg-slate-100/70 border-b border-slate-200">
                      <p className="font-semibold text-slate-900">{block.title}</p>
                    </div>
                    {block.rows.length === 0 ? (
                      <p className="px-4 py-3 text-slate-500">{block.empty}</p>
                    ) : (
                      <div className="max-h-80 overflow-auto">
                        <table className="w-full text-xs">
                          <thead className="bg-white text-slate-600 text-left sticky top-0">
                            <tr>
                              <th className="px-3 py-2 w-56">Rule ID / Code</th>
                              <th className="px-3 py-2 w-56">Title</th>
                              <th className="px-3 py-2">Description</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-100">
                            {block.rows.map((r: DetectionRuleCatalogItem) => (
                              <tr key={r.rule_id}>
                                <td className="px-3 py-2 font-mono text-slate-800 align-top">{r.rule_id}</td>
                                <td className="px-3 py-2 text-slate-800 align-top">{r.title}</td>
                                <td className="px-3 py-2 text-slate-700 align-top">
                                  {r.description}
                                  {r.parameters ? (
                                    <div className="mt-1 text-[11px] text-slate-500">
                                      Params: <code>{JSON.stringify(r.parameters)}</code>
                                    </div>
                                  ) : null}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </SettingsSectionCard>
        )}

        {isAdmin && activeSection === 'ai' && (
          <SettingsSectionCard
            title="AI provider"
            description="Choose the model provider for decision-support and report narratives. Gemini is the default."
            badge={
              <span className="text-[10px] font-semibold uppercase tracking-wide text-amber-800 bg-amber-100 border border-amber-200/80 rounded-md px-2 py-0.5">
                Admin
              </span>
            }
          >
            <SettingsMessageBanner message={aiMessage} />
            {aiSettingsQuery.isLoading ? (
              <p className="text-sm text-slate-500">Loading AI settings…</p>
            ) : aiSettingsQuery.isError ? (
              <p className="text-sm text-red-600">
                Could not load AI settings: {(aiSettingsQuery.error as Error).message}
              </p>
            ) : (
              <div className="space-y-3">
                <label className="block text-sm font-medium text-slate-700">
                  Active provider
                  <select
                    className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
                    value={selectedProvider}
                    onChange={(e) => setSelectedProvider(e.target.value as AiProvider)}
                  >
                    {(aiSettingsQuery.data?.available_providers ?? ['gemini', 'openai', 'ollama']).map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  disabled={aiSaving}
                  onClick={async () => {
                    setAiSaving(true);
                    setAiMessage(null);
                    try {
                      const r = await aiApi.updateSettings({ provider: selectedProvider });
                      setAiMessage({ type: 'success', text: r.message });
                      await aiSettingsQuery.refetch();
                    } catch (e) {
                      setAiMessage({ type: 'error', text: e instanceof Error ? e.message : 'Failed to update AI provider.' });
                    } finally {
                      setAiSaving(false);
                    }
                  }}
                  className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 text-sm font-medium"
                >
                  {aiSaving ? 'Saving…' : 'Save AI provider'}
                </button>
              </div>
            )}
          </SettingsSectionCard>
        )}

            {activeSection === 'preferences' && (
            <SettingsSectionCard
              title="Preferences"
              description="Additional options (notifications, language, and display) can be extended here."
            >
              <p className="text-sm text-slate-600">
                No configurable preferences yet. Check back after future releases.
              </p>
            </SettingsSectionCard>
            )}
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}
