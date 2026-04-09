import { Link, useLocation } from 'react-router-dom';
import { useAuthStore } from '../../store/authStore';

function complianceNavItems(role: string | undefined) {
  const r = (role || '').toLowerCase();
  const showClosedReview = r === 'admin' || r === 'compliance_officer' || r === 'chief_compliance_officer';
  const items = [{ to: '/compliance', label: 'Compliance' }];
  if (showClosedReview) {
    items.push({ to: '/compliance/closed-case-reviews', label: 'Closed case review' });
  }
  return items;
}

const baseNavCore = [
  { to: '/', label: 'Dashboard' },
  { to: '/transactions', label: 'Transactions' },
  { to: '/customers', label: 'Customers' },
  { to: '/risk-reviews', label: 'Risk reviews' },
  { to: '/alerts', label: 'Alerts' },
];

export default function Sidebar() {
  const location = useLocation();
  const role = useAuthStore((s) => s.user?.role);
  const r = (role || '').toLowerCase();
  const showCco = r === 'admin' || r === 'chief_compliance_officer';
  const complianceBlock = complianceNavItems(role);
  const restAfterCompliance = [
    { to: '/reports', label: 'Reports' },
    { to: '/analytics', label: 'Analytics' },
    { to: '/settings', label: 'Settings' },
  ];
  const nav = showCco
    ? [
        ...baseNavCore,
        { to: '/cco-review', label: 'CCO review' },
        { to: '/audit', label: 'Audit & governance' },
        ...complianceBlock,
        ...restAfterCompliance,
      ]
    : [...baseNavCore, ...complianceBlock, ...restAfterCompliance];
  return (
    <aside className="w-56 min-h-0 h-screen sticky top-0 bg-slate-800 text-white flex flex-col shrink-0">
      <div className="p-4 border-b border-slate-700 shrink-0">
        <h2 className="font-semibold text-lg">Nigeria AML</h2>
      </div>
      <nav className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden p-2" aria-label="Main navigation">
        {nav.map(({ to, label }) => (
          <Link
            key={to}
            to={to}
            className={`block px-3 py-2 rounded-md mb-1 ${
              location.pathname === to ? 'bg-slate-600 text-white' : 'text-slate-300 hover:bg-slate-700'
            }`}
          >
            {label}
          </Link>
        ))}
      </nav>
    </aside>
  );
}
