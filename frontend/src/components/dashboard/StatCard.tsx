import { ReactNode } from 'react';

export type StatCardColor = 'blue' | 'green' | 'yellow' | 'red';

const colorClasses: Record<StatCardColor, string> = {
  blue: 'border-l-blue-500 bg-blue-50',
  green: 'border-l-green-500 bg-green-50',
  yellow: 'border-l-yellow-500 bg-yellow-50',
  red: 'border-l-red-500 bg-red-50',
};

interface StatCardProps {
  title: string;
  value: number | string;
  trend?: number;
  trendLabel?: string;
  icon?: ReactNode;
  color: StatCardColor;
  onClick?: () => void;
}

export default function StatCard({ title, value, trend, trendLabel, icon, color, onClick }: StatCardProps) {
  const base = 'rounded-lg border-l-4 p-4 shadow-sm';
  const clickable = onClick ? 'cursor-pointer hover:shadow-md transition-shadow' : '';
  return (
    <div
      className={`${base} ${colorClasses[color]} ${clickable}`}
      onClick={onClick}
      onKeyDown={onClick ? (e) => e.key === 'Enter' && onClick() : undefined}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-slate-600">{title}</p>
          <p className="text-2xl font-bold text-slate-900 mt-1">{value}</p>
          {trend != null && (
            <p className="text-xs mt-1 text-slate-500">
              {trend >= 0 ? '+' : ''}{trend}% {trendLabel ?? 'vs last period'}
            </p>
          )}
        </div>
        {icon && <div className="text-slate-400">{icon}</div>}
      </div>
    </div>
  );
}
