import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { reportsApi, leaApi, customersApi, type Alert } from '../services/api';
import DashboardLayout from '../components/layout/DashboardLayout';
import { useReportActionStore } from '../store/reportActionStore';
import { useAuthStore } from '../store/authStore';
import { fetchClientPublicIp } from '../lib/clientPublicIp';

function alertEligibleForStr(a: Alert): boolean {
  if ((a.last_resolution || '').trim() === 'false_positive') return false;
  if (a.status !== 'escalated') return false;
  return Boolean(a.cco_str_approved);
}

/** Sent when the UI no longer collects analyst STR notes (API still requires a non-empty value). */
const STR_BULK_DEFAULT_NOTES =
  'STR package generated from Regulatory Reports (bulk workflow; analyst notes not captured in this step).';

type StubResult = { report_id: string; xml_preview: string | null; validation_passed: boolean };
type SarGenResult = StubResult & { narrative_source?: string; activity_basis?: string };
type SarBulkRow =
  | { alert_id: string; ok: true; report_id: string; narrative_source?: string; activity_basis?: string }
  | { alert_id: string; ok: false; error?: string };

type StrBulkRow =
  | {
      alert_id: string;
      customer_id?: string;
      ok: true;
      report_id: string;
      aop_report_id?: string;
      soa_report_id?: string;
      soa_period_start?: string;
      soa_period_end?: string;
      soa_error?: string;
    }
  | { alert_id: string; ok: false; error?: string };

type EstrBulkRow =
  | {
      alert_id: string;
      customer_id?: string;
      ok: true;
      report_id: string;
      xml_preview: string | null;
      validation_passed: boolean;
    }
  | { alert_id: string; ok: false; error?: string; customer_id?: string };

type SarModalRow = {
  alert_id: string;
  customer_id: string;
  transaction_id: string;
  summary?: string | null;
  otc_subject?: string | null;
  severity: number;
  kind: 'false_positive' | 'otc_esar';
};

export default function Reports() {
  const [reportFamily, setReportFamily] = useState<'goaml' | 'lea'>('goaml');
  const [strBulkResults, setStrBulkResults] = useState<StrBulkRow[] | null>(null);
  const [strBulkSummary, setStrBulkSummary] = useState<{ generated: number; requested: number } | null>(null);
  const [ctrResult, setCtrResult] = useState<StubResult | null>(null);
  const [sarResult, setSarResult] = useState<SarGenResult | null>(null);
  const [otcEstrBulkResults, setOtcEstrBulkResults] = useState<EstrBulkRow[] | null>(null);
  const [otcEstrBulkSummary, setOtcEstrBulkSummary] = useState<{ generated: number; requested: number } | null>(null);

  const [strSelectedIds, setStrSelectedIds] = useState<string[]>([]);
  const [strIncludeAop, setStrIncludeAop] = useState(false);
  const [strIncludeSoa, setStrIncludeSoa] = useState(false);
  const [strSoaStart, setStrSoaStart] = useState('');
  const [strSoaEnd, setStrSoaEnd] = useState('');
  const [strAopProduct, setStrAopProduct] = useState('Savings');
  const strSelectAllRef = useRef<HTMLInputElement>(null);
  const [showStrModal, setShowStrModal] = useState(false);
  const [downloading, setDownloading] = useState<Record<string, string | undefined>>({});
  const [alertSearch, setAlertSearch] = useState('');
  const [modalRiskFirst, setModalRiskFirst] = useState(true);

  const [sarModalSelectedIds, setSarModalSelectedIds] = useState<string[]>([]);
  const [sarModalSearch, setSarModalSearch] = useState('');
  const [sarModalRiskFirst, setSarModalRiskFirst] = useState(true);
  const [showSarModal, setShowSarModal] = useState(false);
  const [otcEsarModalSelectedIds, setOtcEsarModalSelectedIds] = useState<string[]>([]);
  const [otcEsarModalSearch, setOtcEsarModalSearch] = useState('');
  const [otcEsarModalRiskFirst, setOtcEsarModalRiskFirst] = useState(true);
  const otcEsarSelectAllRef = useRef<HTMLInputElement>(null);
  const [showOtcEsarModal, setShowOtcEsarModal] = useState(false);
  const [sarBulkResults, setSarBulkResults] = useState<SarBulkRow[] | null>(null);
  const [sarBulkSummary, setSarBulkSummary] = useState<{ generated: number; requested: number } | null>(null);

  const [otcEstrSelectedIds, setOtcEstrSelectedIds] = useState<string[]>([]);
  const [otcEstrNotes, setOtcEstrNotes] = useState('');
  const [otcEstrModalSearch, setOtcEstrModalSearch] = useState('');
  const [otcEstrModalRiskFirst, setOtcEstrModalRiskFirst] = useState(true);
  const otcEstrSelectAllRef = useRef<HTMLInputElement>(null);
  const [showOtcEstrModal, setShowOtcEstrModal] = useState(false);

  const [ftrTxnId, setFtrTxnId] = useState('');
  const [ftrMsg, setFtrMsg] = useState<string | null>(null);

  const [leaCustomerId, setLeaCustomerId] = useState('');
  const [leaAgency, setLeaAgency] = useState('EFCC');
  const [leaPeriodStart, setLeaPeriodStart] = useState('');
  const [leaPeriodEnd, setLeaPeriodEnd] = useState('');
  const [leaRecipientEmail, setLeaRecipientEmail] = useState('');
  const [leaIncludeAop, setLeaIncludeAop] = useState(true);
  const [leaWorkstationId, setLeaWorkstationId] = useState('');
  const [leaInternalNotes, setLeaInternalNotes] = useState('');
  const [leaRequestId, setLeaRequestId] = useState('');
  const [leaCcoNotes, setLeaCcoNotes] = useState('');
  const [leaClientPublicIp, setLeaClientPublicIp] = useState<string | null>(null);
  const [leaClientPublicIpStatus, setLeaClientPublicIpStatus] = useState<'idle' | 'loading' | 'ok' | 'error'>('idle');

  const refreshLeaPublicIp = useCallback(async () => {
    setLeaClientPublicIpStatus('loading');
    const ip = await fetchClientPublicIp();
    setLeaClientPublicIp(ip);
    setLeaClientPublicIpStatus(ip ? 'ok' : 'error');
  }, []);

  const authUser = useAuthStore((s) => s.user);
  const authRole = (authUser?.role || '').toLowerCase();
  const isCcoOrAdmin = authRole === 'chief_compliance_officer' || authRole === 'admin';
  const queryClient = useQueryClient();

  const lastAction = useReportActionStore((s) => s.lastAction);
  const clearLastAction = useReportActionStore((s) => s.clearLastAction);

  const { data: strEligibleAlertsData } = useQuery({
    queryKey: ['reports', 'str-eligible-alerts'],
    queryFn: () => reportsApi.listStrEligibleAlerts(500),
  });

  const { data: sarEligibleData } = useQuery({
    queryKey: ['reports', 'sar-eligible'],
    queryFn: () => reportsApi.listSarEligibleAlerts(500),
  });

  const { data: otcEstrEligible } = useQuery({
    queryKey: ['reports', 'otc-eligible', 'estr'],
    queryFn: () => reportsApi.listOtcEligibleAlerts('estr', 500),
  });
  const { data: otcEsarEligible } = useQuery({
    queryKey: ['reports', 'otc-eligible', 'esar'],
    queryFn: () => reportsApi.listOtcEligibleAlerts('esar', 500),
  });

  const { data: ftrListData, refetch: refetchFtr } = useQuery({
    queryKey: ['reports', 'ftr-list'],
    queryFn: () => reportsApi.listFtr({ limit: 100 }),
    enabled: reportFamily === 'goaml',
  });

  const { data: leaAgenciesData } = useQuery({
    queryKey: ['lea', 'agencies'],
    queryFn: () => leaApi.agencies(),
    enabled: reportFamily === 'lea',
  });

  const { data: leaPendingData } = useQuery({
    queryKey: ['lea', 'pending-cco'],
    queryFn: () => leaApi.pendingCco(),
    enabled: reportFamily === 'lea' && isCcoOrAdmin,
  });

  const { data: leaActiveRequest } = useQuery({
    queryKey: ['lea', 'request', leaRequestId],
    queryFn: () => leaApi.getRequest(leaRequestId),
    enabled: !!leaRequestId.trim(),
  });

  useEffect(() => {
    if (reportFamily !== 'lea') return;
    void refreshLeaPublicIp();
  }, [reportFamily, refreshLeaPublicIp]);

  const alerts = strEligibleAlertsData?.items ?? [];
  const eligibleForStr = alerts;
  const sarEligibleRows = sarEligibleData?.items ?? [];
  const otcEstrRows = otcEstrEligible?.items ?? [];
  const otcEsarRows = otcEsarEligible?.items ?? [];
  const otcEstrModalRows = useMemo(() => {
    const rows = [...(otcEstrEligible?.items ?? [])];
    rows.sort((a, b) => b.severity - a.severity);
    return rows;
  }, [otcEstrEligible]);

  const sarFpModalRows: SarModalRow[] = useMemo(
    () =>
      sarEligibleRows
        .map((r) => ({
          alert_id: r.alert_id,
          customer_id: r.customer_id,
          transaction_id: r.transaction_id,
          summary: r.summary,
          severity: r.severity,
          kind: 'false_positive' as const,
        }))
        .sort((a, b) => b.severity - a.severity),
    [sarEligibleRows]
  );

  const otcEsarSarModalRows: SarModalRow[] = useMemo(
    () =>
      otcEsarRows
        .map((r) => ({
          alert_id: r.alert_id,
          customer_id: r.customer_id,
          transaction_id: r.transaction_id,
          summary: r.summary,
          otc_subject: r.otc_subject,
          severity: r.severity,
          kind: 'otc_esar' as const,
        }))
        .sort((a, b) => b.severity - a.severity),
    [otcEsarRows]
  );

  const filteredSarFpModalRows = useMemo(() => {
    const q = sarModalSearch.trim().toLowerCase();
    let rows = [...sarFpModalRows];
    if (q) {
      rows = rows.filter(
        (r) =>
          r.alert_id.toLowerCase().includes(q) ||
          r.customer_id.toLowerCase().includes(q) ||
          r.transaction_id.toLowerCase().includes(q) ||
          (r.summary ?? '').toLowerCase().includes(q)
      );
    }
    rows.sort((a, b) =>
      sarModalRiskFirst ? b.severity - a.severity : b.alert_id.localeCompare(a.alert_id)
    );
    return rows;
  }, [sarFpModalRows, sarModalSearch, sarModalRiskFirst]);

  const filteredOtcEsarSarModalRows = useMemo(() => {
    const q = otcEsarModalSearch.trim().toLowerCase();
    let rows = [...otcEsarSarModalRows];
    if (q) {
      rows = rows.filter(
        (r) =>
          r.alert_id.toLowerCase().includes(q) ||
          r.customer_id.toLowerCase().includes(q) ||
          r.transaction_id.toLowerCase().includes(q) ||
          (r.summary ?? '').toLowerCase().includes(q) ||
          (r.otc_subject ?? '').toLowerCase().includes(q)
      );
    }
    rows.sort((a, b) =>
      otcEsarModalRiskFirst ? b.severity - a.severity : b.alert_id.localeCompare(a.alert_id)
    );
    return rows;
  }, [otcEsarSarModalRows, otcEsarModalSearch, otcEsarModalRiskFirst]);

  const filteredOtcEstrModalRows = useMemo(() => {
    const q = otcEstrModalSearch.trim().toLowerCase();
    let rows = [...otcEstrModalRows];
    if (q) {
      rows = rows.filter(
        (r) =>
          r.alert_id.toLowerCase().includes(q) ||
          r.customer_id.toLowerCase().includes(q) ||
          r.transaction_id.toLowerCase().includes(q) ||
          (r.summary ?? '').toLowerCase().includes(q) ||
          (r.otc_subject ?? '').toLowerCase().includes(q)
      );
    }
    rows.sort((a, b) =>
      otcEstrModalRiskFirst ? b.severity - a.severity : b.alert_id.localeCompare(a.alert_id)
    );
    return rows;
  }, [otcEstrModalRows, otcEstrModalSearch, otcEstrModalRiskFirst]);

  const otcEstrIdsInView = useMemo(() => filteredOtcEstrModalRows.map((r) => r.alert_id), [filteredOtcEstrModalRows]);
  const otcEstrAllInViewSelected =
    otcEstrIdsInView.length > 0 && otcEstrIdsInView.every((id) => otcEstrSelectedIds.includes(id));
  const otcEstrSomeInViewSelected =
    otcEstrIdsInView.some((id) => otcEstrSelectedIds.includes(id)) && !otcEstrAllInViewSelected;

  useEffect(() => {
    const el = otcEstrSelectAllRef.current;
    if (!el) return;
    el.indeterminate = otcEstrSomeInViewSelected;
  }, [otcEstrSomeInViewSelected]);

  const otcEsarIdsInView = useMemo(
    () => filteredOtcEsarSarModalRows.map((r) => r.alert_id),
    [filteredOtcEsarSarModalRows]
  );
  const otcEsarAllInViewSelected =
    otcEsarIdsInView.length > 0 && otcEsarIdsInView.every((id) => otcEsarModalSelectedIds.includes(id));
  const otcEsarSomeInViewSelected =
    otcEsarIdsInView.some((id) => otcEsarModalSelectedIds.includes(id)) && !otcEsarAllInViewSelected;

  useEffect(() => {
    const el = otcEsarSelectAllRef.current;
    if (!el) return;
    el.indeterminate = otcEsarSomeInViewSelected;
  }, [otcEsarSomeInViewSelected]);

  const modalAlerts = useMemo(() => {
    const q = alertSearch.trim().toLowerCase();
    let rows = alerts.filter((a) => {
      if (!q) return true;
      return (
        a.id.toLowerCase().includes(q) ||
        a.customer_id.toLowerCase().includes(q) ||
        a.transaction_id.toLowerCase().includes(q) ||
        (a.summary ?? '').toLowerCase().includes(q)
      );
    });
    rows = [...rows];
    if (modalRiskFirst) rows.sort((a, b) => b.severity - a.severity);
    else rows.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
    return rows;
  }, [alerts, alertSearch, modalRiskFirst]);

  const strEligibleIdsInView = useMemo(
    () => modalAlerts.filter((a) => alertEligibleForStr(a)).map((a) => a.id),
    [modalAlerts]
  );

  const strAllEligibleInViewSelected =
    strEligibleIdsInView.length > 0 && strEligibleIdsInView.every((id) => strSelectedIds.includes(id));
  const strSomeEligibleInViewSelected =
    strEligibleIdsInView.some((id) => strSelectedIds.includes(id)) && !strAllEligibleInViewSelected;

  useEffect(() => {
    const el = strSelectAllRef.current;
    if (!el) return;
    el.indeterminate = strSomeEligibleInViewSelected;
  }, [strSomeEligibleInViewSelected]);

  const canSubmitStr = strSelectedIds.length > 0;

  const strMutation = useMutation({
    mutationFn: ({
      alertIds,
      includeAop,
      includeSoa,
      soaStart,
      soaEnd,
      aopProduct,
    }: {
      alertIds: string[];
      includeAop: boolean;
      includeSoa: boolean;
      soaStart: string;
      soaEnd: string;
      aopProduct: string;
    }) =>
      reportsApi.generateSTRBulk({
        alert_ids: alertIds,
        str_notes: STR_BULK_DEFAULT_NOTES,
        include_aop: includeAop,
        include_soa: includeSoa,
        statement_period_start: soaStart.trim() || undefined,
        statement_period_end: soaEnd.trim() || undefined,
        aop_account_product: aopProduct,
        aop_risk_rating: 'medium',
      }),
    onSuccess: (data) => {
      setStrBulkResults(data.results as StrBulkRow[]);
      setStrBulkSummary({ generated: data.generated, requested: data.requested });
      setShowStrModal(false);
      setStrSelectedIds([]);
      void queryClient.invalidateQueries({ queryKey: ['reports', 'str-eligible-alerts'] });
    },
    onError: () => {
      setStrBulkResults(null);
      setStrBulkSummary(null);
    },
  });

  const handleGenerateStrClick = useCallback(() => {
    if (strSelectedIds.length === 0 || strMutation.isPending) return;
    const n = strSelectedIds.length;
    const msg =
      n === 1
        ? 'This alert is already escalated and CCO-approved for STR filing. Generate an STR package now? You can run this again later if you need a revised draft.'
        : `These ${n} alerts are already escalated and CCO-approved for STR filing. Generate STR package(s) now? You can run this again later if you need revised drafts.`;
    if (!window.confirm(msg)) return;
    strMutation.mutate({
      alertIds: strSelectedIds,
      includeAop: strIncludeAop,
      includeSoa: strIncludeSoa,
      soaStart: strSoaStart,
      soaEnd: strSoaEnd,
      aopProduct: strAopProduct.trim() || 'Savings',
    });
  }, [
    strSelectedIds,
    strMutation,
    strIncludeAop,
    strIncludeSoa,
    strSoaStart,
    strSoaEnd,
    strAopProduct,
  ]);

  const ctrMutation = useMutation({
    mutationFn: () => reportsApi.generateCTR({}),
    onSuccess: (data) =>
      setCtrResult({
        report_id: data.report_id,
        xml_preview: data.xml_preview ?? null,
        validation_passed: data.validation_passed,
      }),
    onError: () => setCtrResult(null),
  });

  const sarMutation = useMutation({
    mutationFn: () =>
      reportsApi.generateSAR({
        alert_id: sarModalSelectedIds[0],
      }),
    onSuccess: (data) => {
      setSarResult(data);
      setSarBulkResults(null);
      setSarBulkSummary(null);
      setShowSarModal(false);
      setSarModalSelectedIds([]);
    },
    onError: () => setSarResult(null),
  });

  const sarBulkMutation = useMutation({
    mutationFn: (opts: { alert_ids: string[] }) =>
      reportsApi.generateSARBulk({
        alert_ids: opts.alert_ids,
      }),
    onSuccess: (data) => {
      setSarBulkSummary({ generated: data.generated, requested: data.requested });
      setSarBulkResults(data.results as SarBulkRow[]);
      setSarResult(null);
      setShowSarModal(false);
      setSarModalSelectedIds([]);
    },
  });

  const otcEsarSarMutation = useMutation({
    mutationFn: () =>
      reportsApi.generateSAR({
        alert_id: otcEsarModalSelectedIds[0],
      }),
    onSuccess: (data) => {
      setSarResult(data);
      setSarBulkResults(null);
      setSarBulkSummary(null);
      setShowOtcEsarModal(false);
      setOtcEsarModalSelectedIds([]);
    },
    onError: () => setSarResult(null),
  });

  const otcEsarSarBulkMutation = useMutation({
    mutationFn: (opts: { alert_ids: string[] }) =>
      reportsApi.generateSARBulk({
        alert_ids: opts.alert_ids,
      }),
    onSuccess: (data) => {
      setSarBulkSummary({ generated: data.generated, requested: data.requested });
      setSarBulkResults(data.results as SarBulkRow[]);
      setSarResult(null);
      setShowOtcEsarModal(false);
      setOtcEsarModalSelectedIds([]);
    },
  });

  const otcEstrBulkMutation = useMutation({
    mutationFn: (opts: { alert_ids: string[] }) =>
      reportsApi.generateESTRBulk({
        alert_ids: opts.alert_ids,
        estr_notes: otcEstrNotes.trim() || undefined,
      }),
    onSuccess: (data) => {
      setOtcEstrBulkSummary({ generated: data.generated, requested: data.requested });
      setOtcEstrBulkResults(data.results as EstrBulkRow[]);
      setShowOtcEstrModal(false);
      setOtcEstrSelectedIds([]);
      setOtcEstrNotes('');
    },
    onError: () => {
      setOtcEstrBulkResults(null);
      setOtcEstrBulkSummary(null);
    },
  });

  const leaSubmitMutation = useMutation({
    mutationFn: () =>
      leaApi.createRequest({
        customer_id: leaCustomerId.trim(),
        agency: leaAgency,
        recipient_email: leaRecipientEmail.trim(),
        period_start: leaPeriodStart.trim() || undefined,
        period_end: leaPeriodEnd.trim() || undefined,
        include_aop: leaIncludeAop,
        workstation_mac: leaWorkstationId.trim() || undefined,
        internal_notes: leaInternalNotes.trim() || undefined,
        client_public_ip: leaClientPublicIp?.trim() || undefined,
        submit_for_cco: true,
      }),
    onSuccess: (data) => {
      setLeaRequestId(data.id);
      queryClient.setQueryData(['lea', 'request', data.id], data);
      void queryClient.invalidateQueries({ queryKey: ['lea', 'pending-cco'] });
    },
  });

  const leaNotifyMutation = useMutation({
    mutationFn: (id: string) => leaApi.notifyCco(id),
    onSuccess: (_, id) => {
      void queryClient.invalidateQueries({ queryKey: ['lea', 'request', id] });
      void queryClient.invalidateQueries({ queryKey: ['lea', 'pending-cco'] });
    },
  });

  const leaApproveMutation = useMutation({
    mutationFn: ({ id, notes }: { id: string; notes?: string }) => leaApi.ccoApprove(id, { notes }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['lea', 'pending-cco'] });
      void queryClient.invalidateQueries({ queryKey: ['lea', 'request'] });
      setLeaCcoNotes('');
    },
  });

  const leaSendMutation = useMutation({
    mutationFn: (id: string) => leaApi.sendPackage(id),
    onSuccess: (_, id) => {
      void queryClient.invalidateQueries({ queryKey: ['lea', 'request', id] });
    },
  });

  const openStrModal = () => {
    if (eligibleForStr.length === 0) return;
    setAlertSearch('');
    setStrIncludeAop(false);
    setStrAopProduct('Savings');
    setModalRiskFirst(true);
    const preferred = lastAction?.alert_id;
    const preferredOk = preferred && eligibleForStr.some((a) => a.id === preferred);
    setStrSelectedIds([preferredOk ? preferred! : eligibleForStr[0]!.id]);
    setShowStrModal(true);
  };

  const openSarModal = () => {
    if (sarFpModalRows.length === 0) return;
    setSarModalSearch('');
    setSarModalRiskFirst(true);
    const preferred = lastAction?.alert_id;
    const preferredOk = preferred && sarFpModalRows.some((r) => r.alert_id === preferred);
    setSarModalSelectedIds(preferredOk ? [preferred!] : [sarFpModalRows[0]!.alert_id]);
    setShowSarModal(true);
  };

  const toggleSarModalRow = (id: string) => {
    setSarModalSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const openOtcEsarModal = () => {
    if (otcEsarSarModalRows.length === 0) return;
    setOtcEsarModalSearch('');
    setOtcEsarModalRiskFirst(true);
    const preferred = lastAction?.alert_id;
    const preferredOk = preferred && otcEsarSarModalRows.some((r) => r.alert_id === preferred);
    setOtcEsarModalSelectedIds(preferredOk ? [preferred!] : [otcEsarSarModalRows[0]!.alert_id]);
    setShowOtcEsarModal(true);
  };

  const toggleOtcEsarModalRow = (id: string) => {
    setOtcEsarModalSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const openOtcEstrModal = () => {
    if (otcEstrModalRows.length === 0) return;
    setOtcEstrModalSearch('');
    setOtcEstrNotes('');
    setOtcEstrModalRiskFirst(true);
    const preferred = lastAction?.alert_id;
    const preferredOk = preferred && otcEstrModalRows.some((r) => r.alert_id === preferred);
    setOtcEstrSelectedIds(preferredOk ? [preferred!] : [otcEstrModalRows[0]!.alert_id]);
    setShowOtcEstrModal(true);
  };

  const toggleOtcEstrModalRow = (id: string) => {
    setOtcEstrSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const canSubmitSar = sarModalSelectedIds.length > 0;
  const sarFpGeneratePending = sarMutation.isPending || sarBulkMutation.isPending;
  const canSubmitOtcEsarSar = otcEsarModalSelectedIds.length > 0;
  const otcEsarSarGeneratePending = otcEsarSarMutation.isPending || otcEsarSarBulkMutation.isPending;

  const canSubmitOtcEstr = otcEstrSelectedIds.length > 0;
  const otcEstrGeneratePending = otcEstrBulkMutation.isPending;

  const dl = async (key: string, fn: () => Promise<void>) => {
    setDownloading((d) => ({ ...d, [key]: 'pending' }));
    try {
      await fn();
    } finally {
      setDownloading((d) => ({ ...d, [key]: undefined }));
    }
  };

  const StubDownloads = ({
    prefix,
    downloadWord,
    downloadXml,
  }: {
    prefix: string;
    downloadWord: () => Promise<void>;
    downloadXml: () => Promise<void>;
  }) => (
    <div className="flex flex-wrap gap-2 mt-2">
      <button
        type="button"
        onClick={() => dl(`${prefix}-w`, downloadWord)}
        disabled={!!downloading[`${prefix}-w`]}
        className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
      >
        Word (.docx)
      </button>
      <button
        type="button"
        onClick={() => dl(`${prefix}-x`, downloadXml)}
        disabled={!!downloading[`${prefix}-x`]}
        className="px-3 py-1.5 text-sm bg-slate-600 text-white rounded hover:bg-slate-700 disabled:opacity-50"
      >
        XML
      </button>
    </div>
  );

  return (
    <DashboardLayout>
      <h1 className="text-2xl font-bold text-slate-900 mb-2">Regulatory reports</h1>
      <p className="text-slate-600 mb-4 text-sm max-w-3xl">
        <strong>goAML</strong> packs mirror NFIU goAML-style submissions (demo XML/Word stubs).{' '}
        <strong>LEA Request</strong> supports law-enforcement disclosure packages with CCO pre-approval before email
        transmission. Production controls, encryption, and jurisdictional process may differ.
      </p>

      <div className="flex gap-2 mb-6 border-b border-slate-200 pb-1">
        <button
          type="button"
          onClick={() => setReportFamily('goaml')}
          className={`px-4 py-2 text-sm font-medium rounded-t-lg ${
            reportFamily === 'goaml' ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
          }`}
        >
          goAML reports
        </button>
        <button
          type="button"
          onClick={() => setReportFamily('lea')}
          className={`px-4 py-2 text-sm font-medium rounded-t-lg ${
            reportFamily === 'lea' ? 'bg-emerald-700 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
          }`}
        >
          LEA Request
        </button>
      </div>

      {reportFamily === 'goaml' && (
        <>
          <h2 className="text-lg font-semibold text-slate-900 mb-3">goAML (STR, SAR, OTC ESAR, CTR, OTC ESTR)</h2>

          <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 shadow-sm mb-6">
            <h3 className="font-medium text-slate-900">FTR — Funds Transfer Report</h3>
            <p className="text-xs text-slate-700 mt-1 max-w-3xl">
              Wire / remittance transfers at or above threshold (default NGN 1,000,000 or USD 1,000). Filing deadline:{' '}
              <strong>5 business days</strong> from value date. Edit drafts via API before submit; submission writes to the audit
              trail. Retain <strong>{ftrListData?.retention_years ?? 5} years</strong> (configurable).
            </p>
            <div className="mt-3 flex flex-wrap gap-2 items-end">
              <label className="flex flex-col text-xs">
                <span className="text-slate-600">Transaction ID</span>
                <input
                  className="border border-slate-300 rounded px-2 py-1.5 text-sm w-72 font-mono"
                  value={ftrTxnId}
                  onChange={(e) => setFtrTxnId(e.target.value)}
                  placeholder="UUID from Transactions"
                />
              </label>
              <button
                type="button"
                className="px-3 py-2 text-sm bg-amber-700 text-white rounded-lg hover:bg-amber-800 disabled:opacity-50"
                onClick={async () => {
                  setFtrMsg(null);
                  try {
                    await reportsApi.generateFtr(ftrTxnId.trim(), false);
                    setFtrMsg('FTR draft created.');
                    void refetchFtr();
                  } catch (e) {
                    setFtrMsg((e as Error).message);
                  }
                }}
                disabled={!ftrTxnId.trim()}
              >
                Generate draft
              </button>
              {authRole === 'admin' && (
                <button
                  type="button"
                  className="px-3 py-2 text-sm bg-slate-600 text-white rounded-lg hover:bg-slate-700 disabled:opacity-50"
                  onClick={async () => {
                    setFtrMsg(null);
                    try {
                      await reportsApi.generateFtr(ftrTxnId.trim(), true);
                      setFtrMsg('FTR draft created (admin force).');
                      void refetchFtr();
                    } catch (e) {
                      setFtrMsg((e as Error).message);
                    }
                  }}
                  disabled={!ftrTxnId.trim()}
                >
                  Admin force
                </button>
              )}
            </div>
            {ftrMsg && <p className="text-xs mt-2 text-slate-800">{ftrMsg}</p>}
            <div className="mt-4 overflow-x-auto">
              <table className="min-w-full text-xs border border-amber-200 bg-white rounded">
                <thead>
                  <tr className="bg-amber-100/80">
                    <th className="text-left p-2">Ref</th>
                    <th className="text-left p-2">Txn</th>
                    <th className="text-left p-2">Status</th>
                    <th className="text-left p-2">Deadline</th>
                    <th className="text-left p-2">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {(ftrListData?.items ?? []).map((row) => (
                    <tr key={String(row.id)} className="border-t border-amber-100">
                      <td className="p-2 font-mono">{String(row.report_ref)}</td>
                      <td className="p-2 font-mono truncate max-w-[140px]" title={String(row.transaction_id)}>
                        {String(row.transaction_id).slice(0, 12)}…
                      </td>
                      <td className="p-2">{String(row.filing_status)}</td>
                      <td className="p-2">{String(row.filing_deadline ?? '')}</td>
                      <td className="p-2">
                        <div className="flex flex-wrap gap-2">
                          <button
                            type="button"
                            className="text-blue-700 underline"
                            onClick={() => dl(`ftr-${row.id}-x`, () => reportsApi.downloadFtrFile(String(row.id), 'xml'))}
                          >
                            XML
                          </button>
                          <button
                            type="button"
                            className="text-blue-700 underline"
                            onClick={() => dl(`ftr-${row.id}-c`, () => reportsApi.downloadFtrFile(String(row.id), 'csv'))}
                          >
                            CSV
                          </button>
                          {String(row.filing_status) === 'DRAFT' && (
                            <button
                              type="button"
                              className="text-emerald-800 underline"
                              onClick={async () => {
                                try {
                                  await reportsApi.submitFtr(String(row.id));
                                  void refetchFtr();
                                } catch (e) {
                                  setFtrMsg((e as Error).message);
                                }
                              }}
                            >
                              Submit
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {authRole === 'admin' && (
              <p className="text-xs text-slate-600 mt-3">
                Auto-generation: <code className="bg-white/80 px-1 rounded">POST /api/v1/reports/ftr/schedule</code> (enable +
                thresholds) and optional <code className="bg-white/80 px-1 rounded">POST /api/v1/reports/ftr/scan/run</code>.
              </p>
            )}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-8">
            <div className="bg-white border border-slate-200 rounded-lg p-4 shadow-sm">
              <h3 className="font-medium text-slate-900">STR — Suspicious Transaction Report</h3>
              <p className="text-xs text-slate-600 mt-1">Requires escalated + CCO-approved alert.</p>
              <button
                type="button"
                onClick={openStrModal}
                disabled={eligibleForStr.length === 0 || strMutation.isPending}
                className="mt-3 px-3 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
              >
                {strMutation.isPending ? 'Generating…' : 'Generate STR'}
              </button>
            </div>
            <div className="bg-white border border-slate-200 rounded-lg p-4 shadow-sm">
              <h3 className="font-medium text-slate-900">CTR — Currency Transaction Report</h3>
              <p className="text-xs text-slate-600 mt-1">Demo aggregate from current transaction store.</p>
              <button
                type="button"
                onClick={() => ctrMutation.mutate()}
                disabled={ctrMutation.isPending}
                className="mt-3 px-3 py-2 text-sm bg-slate-700 text-white rounded-lg hover:bg-slate-800 disabled:opacity-50"
              >
                {ctrMutation.isPending ? 'Generating…' : 'Generate CTR'}
              </button>
            </div>
            <div className="bg-white border border-slate-200 rounded-lg p-4 shadow-sm">
              <h3 className="font-medium text-slate-900">SAR — Suspicious Activity Report</h3>
              <p className="text-xs text-slate-600 mt-1">
                <strong>False-positive</strong> closures only — select one or more eligible alerts and generate SAR in one step.
              </p>
              <p className="text-xs text-indigo-800 bg-indigo-50 border border-indigo-100 rounded px-2 py-1.5 mt-2">
                Eligible (false-positive path): <strong>{sarFpModalRows.length}</strong>
              </p>
              <button
                type="button"
                onClick={openSarModal}
                disabled={sarFpModalRows.length === 0 || sarFpGeneratePending}
                className="mt-3 px-3 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50"
              >
                {sarFpGeneratePending ? 'Generating…' : 'Generate SAR'}
              </button>
            </div>
            <div className="bg-white border border-slate-200 rounded-lg p-4 shadow-sm">
              <h3 className="font-medium text-slate-900">OTC ESAR — Over-the-counter electronic SAR</h3>
              <p className="text-xs text-slate-600 mt-1">
                <strong>Identity / profile</strong> OTC: after a <strong>true-positive</strong> filing, compliance must{' '}
                <strong>escalate</strong> and the <strong>CCO must approve OTC reporting</strong> (CCO review). Then eligible
                alerts appear here. Separate from false-positive SAR and from cash OTC ESTR below.
              </p>
              <p className="text-xs text-violet-900 bg-violet-50 border border-violet-100 rounded px-2 py-1.5 mt-2">
                Eligible (escalated + CCO-approved OTC reporting): <strong>{otcEsarSarModalRows.length}</strong>
              </p>
              <button
                type="button"
                onClick={openOtcEsarModal}
                disabled={otcEsarSarModalRows.length === 0 || otcEsarSarGeneratePending}
                className="mt-3 px-3 py-2 text-sm bg-violet-700 text-white rounded-lg hover:bg-violet-800 disabled:opacity-50"
              >
                {otcEsarSarGeneratePending ? 'Generating…' : 'Generate OTC ESAR'}
              </button>
            </div>
            <div className="bg-white border border-slate-200 rounded-lg p-4 shadow-sm">
              <h3 className="font-medium text-slate-900">OTC extended return (goAML ESTR stub + Word)</h3>
              <p className="text-xs text-slate-600 mt-1">
                <strong>Cash deposit / withdrawal</strong> (ESTR): after <strong>true-positive</strong> OTC filing, compliance{' '}
                <strong>escalates</strong> and the <strong>CCO approves OTC reporting</strong>; then eligible alerts appear here.
                Select one or many and generate Word + XML in one step. Identity / profile matters use{' '}
                <strong>Generate OTC ESAR</strong> above. Word downloads use the <strong>customer name</strong> as the file name
                when KYC has a display name. <strong>Supporting PDF</strong> here is only profile-change and cash-threshold
                evidence; <strong>AOP package</strong> is a separate download.
              </p>
              <p className="text-xs text-amber-900 bg-amber-50 border border-amber-100 rounded px-2 py-1.5 mt-2">
                Ready for OTC ESTR (escalated + CCO-approved): <strong>{otcEstrModalRows.length}</strong>
              </p>
              <button
                type="button"
                onClick={openOtcEstrModal}
                disabled={otcEstrModalRows.length === 0 || otcEstrGeneratePending}
                className="mt-3 px-3 py-2 text-sm bg-amber-700 text-white rounded-lg hover:bg-amber-800 disabled:opacity-50"
              >
                {otcEstrGeneratePending ? 'Generating…' : 'Generate OTC ESTR'}
              </button>
            </div>
          </div>
        </>
      )}

      {reportFamily === 'lea' && (
        <>
          <h2 className="text-lg font-semibold text-slate-900 mb-3">LEA Request — Law enforcement disclosure</h2>
          <p className="text-sm text-slate-600 max-w-3xl mb-4">
            Build a package with a <strong>statement of account</strong> (filtered by date range; period is clamped to
            account opening through today), optional <strong>AOP</strong> draft, server-recorded <strong>request IP</strong>{' '}
            (reverse proxy / network path), <strong>public IP</strong> auto-detected in the browser when possible, and an
            optional <strong>workstation identifier</strong> (the real MAC address cannot be read in a web browser—enter an
            asset tag or MAC if you have it from IT).
            Submit for <strong>CCO approval</strong> first; the Chief Compliance Officer receives email when SMTP is
            configured. <strong>Send request</strong> to the LEA email stays disabled until approval.
          </p>

          {isCcoOrAdmin && (
            <div className="mb-6 p-4 bg-amber-50 border border-amber-200 rounded-lg">
              <h3 className="font-medium text-amber-950 mb-2">CCO — Pending LEA approvals</h3>
              {(leaPendingData?.items?.length ?? 0) === 0 ? (
                <p className="text-sm text-amber-900">No requests awaiting approval.</p>
              ) : (
                <ul className="space-y-3">
                  {(leaPendingData?.items ?? []).map((req) => (
                    <li
                      key={req.id}
                      className="flex flex-wrap items-end gap-2 text-sm bg-white border border-amber-100 rounded p-2"
                    >
                      <div className="flex-1 min-w-[200px]">
                        <span className="font-mono text-xs text-slate-600">{req.id}</span>
                        <p>
                          <strong>{req.agency}</strong> · {req.customer_id}
                        </p>
                        <p className="text-xs text-slate-500">
                          {req.period_start} → {req.period_end} · To {req.recipient_email}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => leaApproveMutation.mutate({ id: req.id, notes: leaCcoNotes.trim() || undefined })}
                        disabled={leaApproveMutation.isPending}
                        className="px-3 py-1.5 text-sm bg-emerald-800 text-white rounded-lg disabled:opacity-50"
                      >
                        Approve
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <label className="block text-xs font-medium text-amber-900 mt-3 mb-1">
                Optional approval notes (applied to next approval click)
              </label>
              <input
                className="w-full max-w-md text-sm border border-amber-200 rounded px-2 py-1"
                value={leaCcoNotes}
                onChange={(e) => setLeaCcoNotes(e.target.value)}
                placeholder="e.g. Verified court order reference …"
              />
            </div>
          )}

          <div className="bg-white border border-slate-200 rounded-lg p-4 shadow-sm max-w-2xl mb-8">
            <label className="block text-sm font-medium text-slate-700 mb-1">Requesting agency *</label>
            <select
              className="w-full text-sm border rounded px-2 py-2 mb-3"
              value={leaAgency}
              onChange={(e) => setLeaAgency(e.target.value)}
            >
              {(leaAgenciesData?.agencies ?? ['EFCC', 'POLICE', 'NDLEA', 'NSCDC', 'ICPC', 'OTHER']).map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
            <label className="block text-sm font-medium text-slate-700 mb-1">Customer ID *</label>
            <input
              className="w-full text-sm border rounded px-2 py-1.5 mb-3 font-mono"
              value={leaCustomerId}
              onChange={(e) => setLeaCustomerId(e.target.value)}
              placeholder="e.g. DEMO-PERSON-ADESANYA"
            />
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-3">
              <div>
                <label className="block text-xs text-slate-600 mb-1">Statement period start (optional)</label>
                <input
                  type="date"
                  className="w-full text-sm border rounded px-2 py-1.5"
                  value={leaPeriodStart}
                  onChange={(e) => setLeaPeriodStart(e.target.value)}
                />
              </div>
              <div>
                <label className="block text-xs text-slate-600 mb-1">Statement period end (optional)</label>
                <input
                  type="date"
                  className="w-full text-sm border rounded px-2 py-1.5"
                  value={leaPeriodEnd}
                  onChange={(e) => setLeaPeriodEnd(e.target.value)}
                />
              </div>
            </div>
            <p className="text-xs text-slate-500 mb-3">
              Leave dates empty to use the full span from account opening (KYC) through today. The server clamps to that
              window.
            </p>
            <label className="block text-sm font-medium text-slate-700 mb-1">LEA recipient email *</label>
            <input
              type="email"
              className="w-full text-sm border rounded px-2 py-1.5 mb-3"
              value={leaRecipientEmail}
              onChange={(e) => setLeaRecipientEmail(e.target.value)}
              placeholder="investigator@agency.gov.ng"
            />
            <label className="flex items-center gap-2 text-sm text-slate-800 mb-3 cursor-pointer">
              <input
                type="checkbox"
                checked={leaIncludeAop}
                onChange={(e) => setLeaIncludeAop(e.target.checked)}
                className="rounded border-slate-300"
              />
              Include AOP draft with the transmission (generated when you send)
            </label>
            <div className="mb-3 p-2 bg-slate-50 border border-slate-200 rounded text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-slate-800">Public IP (browser)</span>
                <button
                  type="button"
                  onClick={() => void refreshLeaPublicIp()}
                  disabled={leaClientPublicIpStatus === 'loading'}
                  className="text-xs px-2 py-0.5 border border-slate-300 rounded bg-white hover:bg-slate-100 disabled:opacity-50"
                >
                  {leaClientPublicIpStatus === 'loading' ? 'Detecting…' : 'Refresh'}
                </button>
              </div>
              {leaClientPublicIpStatus === 'loading' && leaClientPublicIp == null ? (
                <p className="text-xs text-slate-600 mt-1">Looking up your public address…</p>
              ) : leaClientPublicIp ? (
                <p className="text-xs text-slate-700 mt-1 font-mono">{leaClientPublicIp}</p>
              ) : (
                <p className="text-xs text-amber-800 mt-1">
                  Could not detect (offline, blocked fetch, or timeout). Submit still works; CCO email will show “—” for
                  this line.
                </p>
              )}
            </div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Workstation identifier (optional MAC / asset tag)
            </label>
            <input
              className="w-full text-sm border rounded px-2 py-1.5 mb-3 font-mono"
              value={leaWorkstationId}
              onChange={(e) => setLeaWorkstationId(e.target.value)}
              placeholder="e.g. AA:BB:CC:DD:EE:FF or IT asset ID"
            />
            <textarea
              className="w-full text-sm border rounded px-2 py-1.5 mb-3"
              rows={2}
              placeholder="Internal notes (included in CCO notification)"
              value={leaInternalNotes}
              onChange={(e) => setLeaInternalNotes(e.target.value)}
            />
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => leaSubmitMutation.mutate()}
                disabled={
                  leaSubmitMutation.isPending ||
                  !leaCustomerId.trim() ||
                  !leaRecipientEmail.trim().includes('@')
                }
                className="px-4 py-2 text-sm bg-slate-800 text-white rounded-lg hover:bg-slate-900 disabled:opacity-50"
              >
                {leaSubmitMutation.isPending ? 'Submitting…' : 'Submit for CCO approval (email)'}
              </button>
              {leaRequestId &&
                (leaActiveRequest?.status === 'draft' || leaActiveRequest?.status === 'pending_cco') && (
                <button
                  type="button"
                  onClick={() => leaNotifyMutation.mutate(leaRequestId)}
                  disabled={leaNotifyMutation.isPending}
                  className="px-4 py-2 text-sm bg-amber-700 text-white rounded-lg disabled:opacity-50"
                >
                  {leaNotifyMutation.isPending ? 'Sending…' : 'Resend CCO notification'}
                </button>
              )}
              <button
                type="button"
                onClick={() => {
                  if (leaRequestId) leaSendMutation.mutate(leaRequestId);
                }}
                disabled={!leaRequestId || leaSendMutation.isPending || leaActiveRequest?.status !== 'approved'}
                className="px-4 py-2 text-sm bg-emerald-700 text-white rounded-lg hover:bg-emerald-800 disabled:opacity-50"
              >
                {leaSendMutation.isPending ? 'Sending…' : 'Send request to LEA email'}
              </button>
            </div>
            {leaActiveRequest && (
              <div className="mt-4 p-3 bg-slate-50 rounded border border-slate-200 text-sm space-y-1">
                <p>
                  <span className="text-slate-500">Request</span>{' '}
                  <span className="font-mono text-xs">{leaActiveRequest.id}</span>
                </p>
                <p>
                  <span className="text-slate-500">Status</span>{' '}
                  <strong className="text-slate-900">{leaActiveRequest.status}</strong>
                </p>
                {leaActiveRequest.requester_ip ? (
                  <p className="text-xs text-slate-600">
                    Request IP (server): <span className="font-mono">{leaActiveRequest.requester_ip}</span>
                  </p>
                ) : null}
                {leaActiveRequest.client_public_ip ? (
                  <p className="text-xs text-slate-600">
                    Public IP (browser at submit):{' '}
                    <span className="font-mono">{leaActiveRequest.client_public_ip}</span>
                  </p>
                ) : null}
                {leaActiveRequest.account_opened_kyc ? (
                  <p className="text-xs text-slate-600">
                    KYC account opened: <span className="font-mono">{leaActiveRequest.account_opened_kyc}</span>
                  </p>
                ) : null}
                {leaActiveRequest.approved_by ? (
                  <p className="text-xs text-emerald-800">
                    Approved by {leaActiveRequest.approved_by}
                    {leaActiveRequest.approved_at ? ` at ${leaActiveRequest.approved_at}` : ''}
                  </p>
                ) : null}
                {leaActiveRequest.status === 'sent' && leaActiveRequest.sent_at ? (
                  <p className="text-xs text-emerald-800">
                    Sent at {leaActiveRequest.sent_at}
                    {leaActiveRequest.transaction_rows_sent != null
                      ? ` · ${leaActiveRequest.transaction_rows_sent} transaction rows`
                      : ''}
                  </p>
                ) : null}
                {leaActiveRequest.status === 'approved' ? (
                  <p className="text-xs text-amber-800">
                    CCO approved — you may send the email to the LEA contact when ready.
                  </p>
                ) : null}
                {leaActiveRequest.status === 'pending_cco' ? (
                  <p className="text-xs text-amber-800">
                    Awaiting Chief Compliance Officer approval. Send stays disabled.
                  </p>
                ) : null}
              </div>
            )}
          </div>
        </>
      )}

      {lastAction && (
        <div className="mb-6 p-4 bg-indigo-50 border border-indigo-200 rounded-lg text-indigo-900 text-sm">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <p className="font-medium">Last alert action</p>
              <p className="mt-1 font-mono text-xs bg-white/60 px-2 py-0.5 rounded border border-indigo-200 inline-block">
                {lastAction.action_key}
              </p>
              <p className="mt-1 text-indigo-800 text-xs">
                Alert: {lastAction.alert_id}
                {lastAction.customer_id ? ` · ${lastAction.customer_id}` : ''}
              </p>
            </div>
            <button
              type="button"
              onClick={clearLastAction}
              className="px-3 py-2 text-sm rounded-lg bg-white border border-indigo-200 hover:bg-indigo-100"
            >
              Clear
            </button>
          </div>
        </div>
      )}

      {eligibleForStr.length === 0 && reportFamily === 'goaml' && (
        <p className="mb-4 text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          No STR-eligible alerts yet. Escalate for <strong>CCO review</strong> or <strong>true positive</strong>, then approve
          from <strong>CCO review</strong>. After approval, alerts appear here for Word/XML STR generation.
        </p>
      )}

      {strMutation.isError && (
        <p className="mb-4 text-sm text-red-700">STR: {(strMutation.error as Error).message}</p>
      )}
      {ctrMutation.isError && <p className="mb-4 text-sm text-red-700">CTR: {(ctrMutation.error as Error).message}</p>}
      {sarMutation.isError && <p className="mb-4 text-sm text-red-700">SAR: {(sarMutation.error as Error).message}</p>}
      {sarBulkMutation.isError && (
        <p className="mb-4 text-sm text-red-700">SAR batch: {(sarBulkMutation.error as Error).message}</p>
      )}
      {otcEstrBulkMutation.isError && (
        <p className="mb-4 text-sm text-red-700">OTC ESTR batch: {(otcEstrBulkMutation.error as Error).message}</p>
      )}
      {leaSubmitMutation.isError && (
        <p className="mb-4 text-sm text-red-700">LEA submit: {(leaSubmitMutation.error as Error).message}</p>
      )}
      {leaNotifyMutation.isError && (
        <p className="mb-4 text-sm text-red-700">LEA CCO notify: {(leaNotifyMutation.error as Error).message}</p>
      )}
      {leaApproveMutation.isError && (
        <p className="mb-4 text-sm text-red-700">LEA approval: {(leaApproveMutation.error as Error).message}</p>
      )}
      {leaSendMutation.isError && (
        <p className="mb-4 text-sm text-red-700">LEA send: {(leaSendMutation.error as Error).message}</p>
      )}

      {strBulkResults && strBulkSummary && (
        <div className="mb-6 p-4 bg-white rounded-lg shadow border border-slate-200">
          <h3 className="font-semibold text-slate-900 mb-2">STR generation</h3>
          <p className="text-sm text-slate-600 mb-3">
            Generated <strong>{strBulkSummary.generated}</strong> of <strong>{strBulkSummary.requested}</strong> selected.
          </p>
          <ul className="space-y-2 max-h-72 overflow-y-auto">
            {strBulkResults.map((row) => (
              <li key={row.alert_id} className="flex flex-wrap items-center gap-2 text-sm border-b border-slate-100 pb-2">
                <span className="font-mono text-xs text-slate-500 w-28 shrink-0">{row.alert_id}</span>
                {row.ok ? (
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="text-xs text-slate-600">
                      STR: <span className="font-mono">{row.report_id}</span>
                    </span>
                    <button
                      type="button"
                      onClick={() => dl(`str-b-${row.report_id}-w`, () => reportsApi.downloadSTR(row.report_id, 'word'))}
                      disabled={!!downloading[`str-b-${row.report_id}-w`]}
                      className="px-2 py-0.5 text-xs bg-blue-600 text-white rounded disabled:opacity-50"
                    >
                      Word
                    </button>
                    <button
                      type="button"
                      onClick={() => dl(`str-b-${row.report_id}-x`, () => reportsApi.downloadSTR(row.report_id, 'xml'))}
                      disabled={!!downloading[`str-b-${row.report_id}-x`]}
                      className="px-2 py-0.5 text-xs bg-slate-600 text-white rounded disabled:opacity-50"
                    >
                      XML
                    </button>
                    {row.customer_id ? (
                      <button
                        type="button"
                        onClick={() =>
                          dl(`str-b-${row.report_id}-sup`, () =>
                            customersApi.downloadSupportingDocumentsBundle(row.customer_id!)
                          )
                        }
                        disabled={!!downloading[`str-b-${row.report_id}-sup`]}
                        className="px-2 py-0.5 text-xs bg-teal-700 text-white rounded disabled:opacity-50"
                        title="All customer uploads merged into one PDF"
                      >
                        Supporting PDF
                      </button>
                    ) : null}
                    {row.aop_report_id ? (
                      <>
                        <span className="text-xs text-slate-600">
                          AOP: <span className="font-mono">{row.aop_report_id}</span>
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            dl(`str-b-aop-${row.aop_report_id}-pdf`, () =>
                              reportsApi.downloadAOP(row.aop_report_id!)
                            )
                          }
                          disabled={!!downloading[`str-b-aop-${row.aop_report_id}-pdf`]}
                          className="px-2 py-0.5 text-xs bg-emerald-700 text-white rounded disabled:opacity-50"
                          title="Customer account opening package as PDF only (no Word or XML)"
                        >
                          Account opening package PDF
                        </button>
                      </>
                    ) : null}
                    {row.soa_error ? (
                      <span className="text-xs text-amber-800">SOA: {row.soa_error}</span>
                    ) : row.soa_report_id ? (
                      <>
                        <span className="text-xs text-slate-600">
                          SOA: <span className="font-mono">{row.soa_report_id}</span>
                          {row.soa_period_start && row.soa_period_end ? (
                            <span className="block text-slate-500 normal-case">
                              {row.soa_period_start} → {row.soa_period_end}
                            </span>
                          ) : null}
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            dl(`str-b-soa-${row.soa_report_id}-w`, () =>
                              reportsApi.downloadSOA(row.soa_report_id!)
                            )
                          }
                          disabled={!!downloading[`str-b-soa-${row.soa_report_id}-w`]}
                          className="px-2 py-0.5 text-xs bg-cyan-700 text-white rounded disabled:opacity-50"
                          title="Statement of account as Word (.docx); XML export is not available"
                        >
                          Statement of account
                        </button>
                      </>
                    ) : null}
                  </span>
                ) : (
                  <span className="text-xs text-red-700">{row.error ?? 'Failed'}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {ctrResult && (
        <div className="mb-6 p-4 bg-white rounded-lg shadow border border-slate-200">
          <h3 className="font-semibold text-slate-900 mb-2">CTR generated</h3>
          <p className="text-sm font-mono text-slate-600">{ctrResult.report_id}</p>
          <StubDownloads
            prefix="ctr"
            downloadWord={() => reportsApi.downloadCTR(ctrResult.report_id, 'word')}
            downloadXml={() => reportsApi.downloadCTR(ctrResult.report_id, 'xml')}
          />
        </div>
      )}
      {sarResult && (
        <div className="mb-6 p-4 bg-white rounded-lg shadow border border-slate-200">
          <h3 className="font-semibold text-slate-900 mb-2">SAR generated</h3>
          {sarResult.narrative_source && (
            <p className="text-xs text-slate-500 mb-1">
              Narrative sections II–VI: <strong>{sarResult.narrative_source === 'llm' ? 'AI-generated' : 'Template'}</strong>
              {sarResult.activity_basis ? (
                <>
                  {' '}
                  · Basis: <strong>{sarResult.activity_basis}</strong>
                </>
              ) : null}
            </p>
          )}
          <p className="text-sm font-mono text-slate-600">{sarResult.report_id}</p>
          <StubDownloads
            prefix="sar"
            downloadWord={() => reportsApi.downloadSAR(sarResult.report_id, 'word')}
            downloadXml={() => reportsApi.downloadSAR(sarResult.report_id, 'xml')}
          />
        </div>
      )}
      {sarBulkResults && sarBulkSummary && (
        <div className="mb-6 p-4 bg-violet-50 rounded-lg shadow border border-violet-200">
          <h3 className="font-semibold text-slate-900 mb-1">SAR batch</h3>
          <p className="text-sm text-slate-600 mb-3">
            Generated <strong>{sarBulkSummary.generated}</strong> of <strong>{sarBulkSummary.requested}</strong> requested.
          </p>
          <div className="max-h-64 overflow-y-auto border border-violet-100 rounded bg-white text-sm">
            <ul className="divide-y divide-slate-100">
              {sarBulkResults.map((row) => (
                <li key={row.alert_id} className="p-2 flex flex-wrap items-center gap-2 justify-between">
                  <span className="font-mono text-xs">{row.alert_id}</span>
                  {row.ok ? (
                    <span className="flex flex-wrap gap-1">
                      <button
                        type="button"
                        onClick={() => dl(`sar-b-${row.report_id}-w`, () => reportsApi.downloadSAR(row.report_id, 'word'))}
                        disabled={!!downloading[`sar-b-${row.report_id}-w`]}
                        className="px-2 py-0.5 text-xs bg-indigo-600 text-white rounded disabled:opacity-50"
                      >
                        Word
                      </button>
                      <button
                        type="button"
                        onClick={() => dl(`sar-b-${row.report_id}-x`, () => reportsApi.downloadSAR(row.report_id, 'xml'))}
                        disabled={!!downloading[`sar-b-${row.report_id}-x`]}
                        className="px-2 py-0.5 text-xs bg-slate-600 text-white rounded disabled:opacity-50"
                      >
                        XML
                      </button>
                    </span>
                  ) : (
                    <span className="text-xs text-red-700">{row.error ?? 'Failed'}</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
      {otcEstrBulkResults && otcEstrBulkSummary && (
        <div className="mb-6 p-4 bg-amber-50 rounded-lg shadow border border-amber-200">
          <h3 className="font-semibold text-slate-900 mb-1">OTC ESTR batch</h3>
          <p className="text-sm text-slate-600 mb-3">
            Generated <strong>{otcEstrBulkSummary.generated}</strong> of <strong>{otcEstrBulkSummary.requested}</strong>{' '}
            requested.
          </p>
          <div className="max-h-64 overflow-y-auto border border-amber-100 rounded bg-white text-sm">
            <ul className="divide-y divide-slate-100">
              {otcEstrBulkResults.map((row) => (
                <li key={row.alert_id} className="p-2 flex flex-wrap items-center gap-2 justify-between">
                  <span className="font-mono text-xs">{row.alert_id}</span>
                  {row.ok ? (
                    <span className="flex flex-wrap gap-1">
                      <button
                        type="button"
                        onClick={() =>
                          dl(`estr-b-${row.report_id}-w`, () => reportsApi.downloadESTR(row.report_id, 'word'))
                        }
                        disabled={!!downloading[`estr-b-${row.report_id}-w`]}
                        className="px-2 py-0.5 text-xs bg-amber-700 text-white rounded disabled:opacity-50"
                      >
                        Word
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          dl(`estr-b-${row.report_id}-x`, () => reportsApi.downloadESTR(row.report_id, 'xml'))
                        }
                        disabled={!!downloading[`estr-b-${row.report_id}-x`]}
                        className="px-2 py-0.5 text-xs bg-slate-600 text-white rounded disabled:opacity-50"
                      >
                        XML
                      </button>
                      {row.customer_id ? (
                        <>
                          <button
                            type="button"
                            onClick={() =>
                              dl(`estr-b-${row.report_id}-sup`, () =>
                                customersApi.downloadSupportingDocumentsBundle(
                                  row.customer_id!,
                                  'otc_estr_supporting',
                                )
                              )
                            }
                            disabled={!!downloading[`estr-b-${row.report_id}-sup`]}
                            className="px-2 py-0.5 text-xs bg-teal-700 text-white rounded disabled:opacity-50"
                            title="Profile change + cash threshold evidence only (excludes AOP package)"
                          >
                            Supporting PDF
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              dl(`estr-b-${row.report_id}-aop`, () =>
                                customersApi.downloadSupportingDocumentsBundle(row.customer_id!, 'aop_package')
                              )
                            }
                            disabled={!!downloading[`estr-b-${row.report_id}-aop`]}
                            className="px-2 py-0.5 text-xs bg-emerald-700 text-white rounded disabled:opacity-50"
                            title="Account opening package file uploads only"
                          >
                            AOP PDF
                          </button>
                        </>
                      ) : null}
                    </span>
                  ) : (
                    <span className="text-xs text-red-700">{row.error ?? 'Failed'}</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
      {showStrModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50"
          onClick={() => setShowStrModal(false)}
          role="dialog"
          aria-modal="true"
          aria-labelledby="str-modal-title"
        >
          <div
            className="bg-white rounded-xl shadow-xl max-w-4xl w-full p-6 max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id="str-modal-title" className="text-lg font-semibold text-slate-900 mb-4">
              Select alert(s) for STR
            </h2>
            <p className="text-xs text-slate-600 mb-3">
              Eligible rows are <strong>escalated</strong> and <strong>CCO-approved for STR</strong>. Select one or more
              eligible alerts; use the header checkbox to select all eligible in the current list. You may optionally
              generate an <strong>AOP</strong> draft (medium risk rating applied automatically) and a{' '}
              <strong>statement of account</strong> per customer alongside each STR.
            </p>
            <div className="flex flex-wrap items-end gap-2 mb-3">
              <div className="flex-1 min-w-[200px]">
                <label className="block text-sm font-medium text-slate-700 mb-1" htmlFor="str-alert-search">
                  Search alerts
                </label>
                <input
                  id="str-alert-search"
                  value={alertSearch}
                  onChange={(e) => setAlertSearch(e.target.value)}
                  className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
                />
              </div>
              <button
                type="button"
                onClick={() => setModalRiskFirst((v) => !v)}
                className={`px-3 py-2 text-sm rounded-lg border ${
                  modalRiskFirst ? 'bg-blue-600 text-white border-blue-600' : 'bg-white border-slate-300'
                }`}
              >
                {modalRiskFirst ? 'By risk' : 'By date'}
              </button>
            </div>
            <div className="border border-slate-200 rounded-lg overflow-hidden mb-4 max-h-60 overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left">
                  <tr>
                    <th className="p-2 w-10">
                      <input
                        ref={strSelectAllRef}
                        type="checkbox"
                        checked={strAllEligibleInViewSelected}
                        disabled={strEligibleIdsInView.length === 0}
                        onChange={() => {
                          const viewSet = new Set(strEligibleIdsInView);
                          if (strAllEligibleInViewSelected) {
                            setStrSelectedIds((prev) => prev.filter((id) => !viewSet.has(id)));
                          } else {
                            setStrSelectedIds((prev) => [...new Set([...prev, ...strEligibleIdsInView])]);
                          }
                        }}
                        className="rounded border-slate-300"
                        title="Select all eligible in this list"
                        aria-label="Select all eligible alerts"
                      />
                    </th>
                    <th className="p-2">Risk</th>
                    <th className="p-2">STR</th>
                    <th className="p-2">Workflow</th>
                    <th className="p-2">Summary</th>
                    <th className="p-2">Customer</th>
                  </tr>
                </thead>
                <tbody>
                  {modalAlerts.map((a) => {
                    const ok = alertEligibleForStr(a);
                    const sel = strSelectedIds.includes(a.id);
                    const toggle = () => {
                      if (!ok) return;
                      setStrSelectedIds((prev) =>
                        prev.includes(a.id) ? prev.filter((id) => id !== a.id) : [...prev, a.id]
                      );
                    };
                    return (
                      <tr
                        key={a.id}
                        onClick={toggle}
                        className={`border-t ${ok ? 'cursor-pointer hover:bg-blue-50/60' : 'opacity-50'} ${sel ? 'bg-blue-50' : ''}`}
                      >
                        <td className="p-2" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={sel}
                            disabled={!ok}
                            onChange={toggle}
                            className="rounded border-slate-300"
                          />
                        </td>
                        <td className="p-2">{(a.severity * 100).toFixed(0)}%</td>
                        <td className="p-2">{ok ? 'Eligible' : '—'}</td>
                        <td className="p-2">
                          {ok ? (
                            <span className="inline-flex items-center rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-900 ring-1 ring-amber-200">
                              Escalated
                            </span>
                          ) : (
                            '—'
                          )}
                        </td>
                        <td className="p-2 max-w-[180px] truncate">{a.summary ?? '—'}</td>
                        <td className="p-2 font-mono text-xs">{a.customer_id}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <label className="flex items-center gap-2 text-sm text-slate-800 cursor-pointer mb-2">
              <input
                type="checkbox"
                checked={strIncludeAop}
                onChange={(e) => setStrIncludeAop(e.target.checked)}
                className="rounded border-slate-300"
              />
              Generate customer AOP (one draft per selected alert's customer)
            </label>
            {strIncludeAop && (
              <div className="mb-4">
                <label className="block text-xs font-medium text-slate-600 mb-1">AOP account / product</label>
                <input
                  className="w-full max-w-md rounded border border-slate-300 px-2 py-1.5 text-sm"
                  value={strAopProduct}
                  onChange={(e) => setStrAopProduct(e.target.value)}
                />
                <p className="mt-1 text-xs text-slate-500">AOP risk rating is fixed to medium for this workflow.</p>
              </div>
            )}
            <label className="flex items-center gap-2 text-sm text-slate-800 cursor-pointer mb-2">
              <input
                type="checkbox"
                checked={strIncludeSoa}
                onChange={(e) => setStrIncludeSoa(e.target.checked)}
                className="rounded border-slate-300"
              />
              Generate statement of account (one per selected alert&apos;s customer)
            </label>
            {strIncludeSoa && strSelectedIds.length > 1 && (
              <div className="mb-4 rounded-md border border-sky-100 bg-sky-50 px-3 py-2 text-xs text-sky-950">
                <strong>Bulk selection:</strong> each statement of account uses a <strong>rolling 12-month</strong> window
                ending today, clamped so it cannot start before the customer&apos;s account opening date (same rule engine as
                LEA statements).
              </div>
            )}
            {strIncludeSoa && strSelectedIds.length === 1 && (
              <div className="mb-4 space-y-2">
                <p className="text-xs text-slate-600">
                  <strong>Single alert:</strong> choose the statement window below. The server clamps to account opening
                  through today. Leave both dates empty to use that full span.
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  <div>
                    <label className="block text-xs font-medium text-slate-600 mb-1">Statement period start (optional)</label>
                    <input
                      type="date"
                      className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
                      value={strSoaStart}
                      onChange={(e) => setStrSoaStart(e.target.value)}
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-600 mb-1">Statement period end (optional)</label>
                    <input
                      type="date"
                      className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
                      value={strSoaEnd}
                      onChange={(e) => setStrSoaEnd(e.target.value)}
                    />
                  </div>
                </div>
                <p className="text-xs text-slate-500 font-mono">
                  Requested window: {strSoaStart || '(account open)'} → {strSoaEnd || '(today)'} — final dates appear in
                  results after generation.
                </p>
              </div>
            )}
            <div className="flex gap-2 justify-end">
              <button type="button" onClick={() => setShowStrModal(false)} className="px-3 py-1.5 text-sm bg-slate-200 rounded">
                Cancel
              </button>
              <button
                type="button"
                onClick={handleGenerateStrClick}
                disabled={!canSubmitStr || strMutation.isPending}
                className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded disabled:opacity-50"
              >
                {strMutation.isPending ? 'Generating…' : 'Generate STR'}
              </button>
            </div>
          </div>
        </div>
      )}

      {showSarModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50"
          onClick={() => setShowSarModal(false)}
          role="dialog"
          aria-modal="true"
          aria-labelledby="sar-modal-title"
        >
          <div
            className="bg-white rounded-xl shadow-xl max-w-4xl w-full p-6 max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id="sar-modal-title" className="text-lg font-semibold text-slate-900 mb-4">
              Select alert(s) for SAR (false-positive path)
            </h2>
            <p className="text-xs text-slate-600 mb-3">
              Only <strong>false-positive</strong> closed alerts appear here. For identity / profile OTC ESAR (after compliance
              true-positive OTC filing), use <strong>Generate OTC ESAR</strong> on the reports page.
            </p>
            {sarFpModalRows.length > 0 && (
              <>
                <div className="flex flex-wrap items-end gap-2 mb-3">
                  <div className="flex-1 min-w-[200px]">
                    <label className="block text-sm font-medium text-slate-700 mb-1" htmlFor="sar-alert-search">
                      Search
                    </label>
                    <input
                      id="sar-alert-search"
                      value={sarModalSearch}
                      onChange={(e) => setSarModalSearch(e.target.value)}
                      className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => setSarModalRiskFirst((v) => !v)}
                    className={`px-3 py-2 text-sm rounded-lg border ${
                      sarModalRiskFirst ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-white border-slate-300'
                    }`}
                  >
                    {sarModalRiskFirst ? 'By risk' : 'By alert ID'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setSarModalSelectedIds(filteredSarFpModalRows.map((r) => r.alert_id))}
                    className="px-3 py-2 text-xs rounded-lg border border-slate-300 bg-white hover:bg-slate-50"
                  >
                    Select all in list
                  </button>
                  <button
                    type="button"
                    onClick={() => setSarModalSelectedIds([])}
                    className="px-3 py-2 text-xs rounded-lg border border-slate-300 bg-white hover:bg-slate-50"
                  >
                    Clear
                  </button>
                </div>
                <p className="text-xs text-slate-600 mb-2">
                  Selected: <strong>{sarModalSelectedIds.length}</strong>
                </p>
                <div className="border border-slate-200 rounded-lg overflow-hidden mb-4 max-h-60 overflow-y-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-slate-50 text-left">
                      <tr>
                        <th className="p-2 w-10" />
                        <th className="p-2">Risk</th>
                        <th className="p-2">Summary</th>
                        <th className="p-2">Customer</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredSarFpModalRows.map((r) => {
                        const sel = sarModalSelectedIds.includes(r.alert_id);
                        return (
                          <tr
                            key={r.alert_id}
                            onClick={() => toggleSarModalRow(r.alert_id)}
                            className={`border-t cursor-pointer hover:bg-indigo-50/60 ${sel ? 'bg-indigo-50' : ''}`}
                          >
                            <td className="p-2" onClick={(e) => e.stopPropagation()}>
                              <input
                                type="checkbox"
                                checked={sel}
                                onChange={() => toggleSarModalRow(r.alert_id)}
                                className="rounded border-slate-300"
                              />
                            </td>
                            <td className="p-2">{(r.severity * 100).toFixed(0)}%</td>
                            <td className="p-2 max-w-[220px] truncate">{r.summary ?? '—'}</td>
                            <td className="p-2 font-mono text-xs">{r.customer_id}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </>
            )}
            {sarFpModalRows.length === 0 && (
              <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2 mb-3">
                No false-positive SAR-eligible alerts in your scope. Close alerts as false positive to see rows here.
              </p>
            )}
            <div className="flex gap-2 justify-end">
              <button type="button" onClick={() => setShowSarModal(false)} className="px-3 py-1.5 text-sm bg-slate-200 rounded">
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  if (!canSubmitSar || sarFpGeneratePending) return;
                  const ids = [...sarModalSelectedIds];
                  if (ids.length === 1) sarMutation.mutate();
                  else sarBulkMutation.mutate({ alert_ids: ids });
                }}
                disabled={!canSubmitSar || sarFpGeneratePending}
                className="px-3 py-1.5 text-sm bg-indigo-600 text-white rounded disabled:opacity-50"
              >
                {sarFpGeneratePending
                  ? 'Generating…'
                  : sarModalSelectedIds.length > 1
                    ? `Generate ${sarModalSelectedIds.length} SARs`
                    : 'Generate SAR'}
              </button>
            </div>
          </div>
        </div>
      )}

      {showOtcEsarModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50"
          onClick={() => setShowOtcEsarModal(false)}
          role="dialog"
          aria-modal="true"
          aria-labelledby="otc-esar-modal-title"
        >
          <div
            className="bg-white rounded-xl shadow-xl max-w-4xl w-full p-6 max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id="otc-esar-modal-title" className="text-lg font-semibold text-slate-900 mb-4">
              Select alert(s) for OTC ESAR
            </h2>
            <p className="text-xs text-slate-600 mb-3">
              <strong>Identity / profile</strong> OTC matters where compliance has filed a <strong>true-positive</strong> OTC
              assessment (regulatory path unlocked in the system — same SAR generate API as false-positive SAR, listed
              separately from cash OTC ESTR). For cash OTC ESTR, use <strong>Generate OTC ESTR</strong>.
            </p>
            {otcEsarSarModalRows.length > 0 && (
              <>
                <div className="flex flex-wrap items-end gap-2 mb-3">
                  <div className="flex-1 min-w-[200px]">
                    <label className="block text-sm font-medium text-slate-700 mb-1" htmlFor="otc-esar-sar-search">
                      Search
                    </label>
                    <input
                      id="otc-esar-sar-search"
                      value={otcEsarModalSearch}
                      onChange={(e) => setOtcEsarModalSearch(e.target.value)}
                      className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => setOtcEsarModalRiskFirst((v) => !v)}
                    className={`px-3 py-2 text-sm rounded-lg border ${
                      otcEsarModalRiskFirst ? 'bg-violet-700 text-white border-violet-700' : 'bg-white border-slate-300'
                    }`}
                  >
                    {otcEsarModalRiskFirst ? 'By risk' : 'By alert ID'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setOtcEsarModalSelectedIds(filteredOtcEsarSarModalRows.map((r) => r.alert_id))}
                    className="px-3 py-2 text-xs rounded-lg border border-slate-300 bg-white hover:bg-slate-50"
                  >
                    Select all in list
                  </button>
                  <button
                    type="button"
                    onClick={() => setOtcEsarModalSelectedIds([])}
                    className="px-3 py-2 text-xs rounded-lg border border-slate-300 bg-white hover:bg-slate-50"
                  >
                    Clear
                  </button>
                </div>
                <p className="text-xs text-slate-600 mb-2">
                  Selected: <strong>{otcEsarModalSelectedIds.length}</strong>
                </p>
                <div className="border border-slate-200 rounded-lg overflow-hidden mb-4 max-h-60 overflow-y-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-slate-50 text-left">
                      <tr>
                        <th className="p-2 w-10">
                          <input
                            ref={otcEsarSelectAllRef}
                            type="checkbox"
                            checked={otcEsarAllInViewSelected}
                            onChange={() =>
                              otcEsarAllInViewSelected
                                ? setOtcEsarModalSelectedIds((prev) => prev.filter((id) => !otcEsarIdsInView.includes(id)))
                                : setOtcEsarModalSelectedIds((prev) => Array.from(new Set([...prev, ...otcEsarIdsInView])))
                            }
                            className="rounded border-slate-300"
                            aria-label="Select all visible OTC ESAR rows"
                          />
                        </th>
                        <th className="p-2">Risk</th>
                        <th className="p-2">Summary</th>
                        <th className="p-2">Subject</th>
                        <th className="p-2">Customer</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredOtcEsarSarModalRows.map((r) => {
                        const sel = otcEsarModalSelectedIds.includes(r.alert_id);
                        return (
                          <tr
                            key={r.alert_id}
                            onClick={() => toggleOtcEsarModalRow(r.alert_id)}
                            className={`border-t cursor-pointer hover:bg-violet-50/60 ${sel ? 'bg-violet-50' : ''}`}
                          >
                            <td className="p-2" onClick={(e) => e.stopPropagation()}>
                              <input
                                type="checkbox"
                                checked={sel}
                                onChange={() => toggleOtcEsarModalRow(r.alert_id)}
                                className="rounded border-slate-300"
                              />
                            </td>
                            <td className="p-2">{(r.severity * 100).toFixed(0)}%</td>
                            <td className="p-2 max-w-[180px] truncate">{r.summary ?? '—'}</td>
                            <td className="p-2 max-w-[140px] truncate text-xs">{r.otc_subject ?? '—'}</td>
                            <td className="p-2 font-mono text-xs">{r.customer_id}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </>
            )}
            {otcEsarSarModalRows.length === 0 && (
              <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2 mb-3">
                No OTC ESAR-eligible alerts in your scope. File OTC as <strong>true positive</strong>, <strong>escalate</strong>,
                then have the CCO <strong>approve OTC reporting</strong> on CCO review.
              </p>
            )}
            <div className="flex gap-2 justify-end">
              <button
                type="button"
                onClick={() => setShowOtcEsarModal(false)}
                className="px-3 py-1.5 text-sm bg-slate-200 rounded"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  if (!canSubmitOtcEsarSar || otcEsarSarGeneratePending) return;
                  const ids = [...otcEsarModalSelectedIds];
                  if (ids.length === 1) otcEsarSarMutation.mutate();
                  else otcEsarSarBulkMutation.mutate({ alert_ids: ids });
                }}
                disabled={!canSubmitOtcEsarSar || otcEsarSarGeneratePending}
                className="px-3 py-1.5 text-sm bg-violet-700 text-white rounded disabled:opacity-50"
              >
                {otcEsarSarGeneratePending
                  ? 'Generating…'
                  : otcEsarModalSelectedIds.length > 1
                    ? `Generate ${otcEsarModalSelectedIds.length} OTC ESARs`
                    : 'Generate OTC ESAR'}
              </button>
            </div>
          </div>
        </div>
      )}

      {showOtcEstrModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50"
          onClick={() => setShowOtcEstrModal(false)}
          role="dialog"
          aria-modal="true"
          aria-labelledby="otc-estr-modal-title"
        >
          <div
            className="bg-white rounded-xl shadow-xl max-w-4xl w-full p-6 max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id="otc-estr-modal-title" className="text-lg font-semibold text-slate-900 mb-4">
              Select alert(s) for OTC ESTR
            </h2>
            <p className="text-xs text-slate-600 mb-3">
              Eligible rows are <strong>cash</strong> OTC ESTR matters that are <strong>escalated</strong> with{' '}
              <strong>CCO-approved</strong> OTC reporting (and true-positive filing on file). Select one or more; use the header
              checkbox to select every row in the current filtered list. Shared extension notes apply to each draft.
            </p>
            <div className="flex flex-wrap items-end gap-2 mb-3">
              <div className="flex-1 min-w-[200px]">
                <label className="block text-sm font-medium text-slate-700 mb-1" htmlFor="otc-estr-search">
                  Search
                </label>
                <input
                  id="otc-estr-search"
                  value={otcEstrModalSearch}
                  onChange={(e) => setOtcEstrModalSearch(e.target.value)}
                  className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
                />
              </div>
              <button
                type="button"
                onClick={() => setOtcEstrModalRiskFirst((v) => !v)}
                className={`px-3 py-2 text-sm rounded-lg border ${
                  otcEstrModalRiskFirst ? 'bg-amber-700 text-white border-amber-700' : 'bg-white border-slate-300'
                }`}
              >
                {otcEstrModalRiskFirst ? 'By risk' : 'By alert ID'}
              </button>
            </div>
            <div className="border border-slate-200 rounded-lg overflow-hidden mb-4 max-h-60 overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left">
                  <tr>
                    <th className="p-2 w-10">
                      <input
                        ref={otcEstrSelectAllRef}
                        type="checkbox"
                        checked={otcEstrAllInViewSelected}
                        disabled={otcEstrIdsInView.length === 0}
                        onChange={() => {
                          const viewSet = new Set(otcEstrIdsInView);
                          if (otcEstrAllInViewSelected) {
                            setOtcEstrSelectedIds((prev) => prev.filter((id) => !viewSet.has(id)));
                          } else {
                            setOtcEstrSelectedIds((prev) => [...new Set([...prev, ...otcEstrIdsInView])]);
                          }
                        }}
                        className="rounded border-slate-300"
                        title="Select all in this list"
                        aria-label="Select all OTC ESTR alerts in this list"
                      />
                    </th>
                    <th className="p-2">Risk</th>
                    <th className="p-2">Path</th>
                    <th className="p-2">Subject</th>
                    <th className="p-2">Summary</th>
                    <th className="p-2">Customer</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredOtcEstrModalRows.map((r) => {
                    const sel = otcEstrSelectedIds.includes(r.alert_id);
                    return (
                      <tr
                        key={r.alert_id}
                        onClick={() => toggleOtcEstrModalRow(r.alert_id)}
                        className={`border-t cursor-pointer hover:bg-amber-50/60 ${sel ? 'bg-amber-50' : ''}`}
                      >
                        <td className="p-2" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={sel}
                            onChange={() => toggleOtcEstrModalRow(r.alert_id)}
                            className="rounded border-slate-300"
                          />
                        </td>
                        <td className="p-2">{(r.severity * 100).toFixed(0)}%</td>
                        <td className="p-2 text-xs">Cash → ESTR</td>
                        <td className="p-2 text-xs font-mono">{(r.otc_subject ?? '—').replace(/_/g, ' ')}</td>
                        <td className="p-2 max-w-[180px] truncate">{r.summary ?? '—'}</td>
                        <td className="p-2 font-mono text-xs">{r.customer_id}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Extension notes (optional)</label>
            <textarea
              value={otcEstrNotes}
              onChange={(e) => setOtcEstrNotes(e.target.value)}
              rows={3}
              className="w-full rounded border border-slate-300 px-3 py-2 text-sm mb-4"
            />
            <div className="flex gap-2 justify-end">
              <button
                type="button"
                onClick={() => setShowOtcEstrModal(false)}
                className="px-3 py-1.5 text-sm bg-slate-200 rounded"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() =>
                  canSubmitOtcEstr && !otcEstrGeneratePending && otcEstrBulkMutation.mutate({ alert_ids: otcEstrSelectedIds })
                }
                disabled={!canSubmitOtcEstr || otcEstrGeneratePending}
                className="px-3 py-1.5 text-sm bg-amber-700 text-white rounded disabled:opacity-50"
              >
                {otcEstrGeneratePending
                  ? 'Generating…'
                  : otcEstrSelectedIds.length > 1
                    ? `Generate ${otcEstrSelectedIds.length} ESTRs`
                    : 'Generate ESTR'}
              </button>
            </div>
          </div>
        </div>
      )}
    </DashboardLayout>
  );
}
