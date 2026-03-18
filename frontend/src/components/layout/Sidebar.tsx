import { Link, useLocation } from 'react-router-dom';

const nav = [
  { to: '/', label: 'Dashboard' },
  { to: '/transactions', label: 'Transactions' },
  { to: '/alerts', label: 'Alerts' },
  { to: '/reports', label: 'Reports' },
  { to: '/analytics', label: 'Analytics' },
  { to: '/settings', label: 'Settings' },
];

export default function Sidebar() {
  const location = useLocation();
  return (
    <aside className="w-56 bg-slate-800 text-white flex flex-col">
      <div className="p-4 border-b border-slate-700">
        <h2 className="font-semibold text-lg">Nigeria AML</h2>
      </div>
      <nav className="flex-1 p-2">
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
