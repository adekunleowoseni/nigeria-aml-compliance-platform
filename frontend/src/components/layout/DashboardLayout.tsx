import { ReactNode } from 'react';
import Sidebar from './Sidebar';
import Header from './Header';
import { useStore } from '../../store/uiStore';

interface DashboardLayoutProps {
  children: ReactNode;
}

export default function DashboardLayout({ children }: DashboardLayoutProps) {
  const { sidebarOpen } = useStore();
  return (
    <div className="flex min-h-screen bg-slate-100">
      {sidebarOpen && (
        <div className="flex-shrink-0">
          <Sidebar />
        </div>
      )}
      <div className="flex-1 flex flex-col min-w-0">
        <Header />
        <main className="flex-1 p-6 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
