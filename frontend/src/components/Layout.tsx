import { ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';

interface LayoutProps {
  children: ReactNode;
}

const nav = [
  { to: '/', label: 'Dashboard' },
  { to: '/transactions', label: 'Transactions' },
  { to: '/alerts', label: 'Alerts' },
  { to: '/reports', label: 'Reports' },
];

export default function Layout({ children }: LayoutProps) {
  const location = useLocation();
  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <aside style={{ width: 220, background: '#0d47a1', color: '#fff', padding: '1rem' }}>
        <h2 style={{ margin: '0 0 1rem', fontSize: '1rem' }}>Nigeria AML</h2>
        <nav>
          {nav.map(({ to, label }) => (
            <Link
              key={to}
              to={to}
              style={{
                display: 'block',
                padding: '0.5rem 0',
                color: location.pathname === to ? '#90caf9' : '#fff',
                textDecoration: 'none',
              }}
            >
              {label}
            </Link>
          ))}
        </nav>
      </aside>
      <main style={{ flex: 1, padding: '1.5rem' }}>{children}</main>
    </div>
  );
}
