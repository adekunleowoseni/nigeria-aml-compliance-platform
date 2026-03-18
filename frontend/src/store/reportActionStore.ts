import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type ReportAction = {
  action_key: string;
  alert_id: string;
  transaction_id?: string;
  customer_id?: string;
  summary?: string;
  at: string; // ISO
};

interface ReportActionState {
  lastAction: ReportAction | null;
  setLastAction: (action: ReportAction) => void;
  clearLastAction: () => void;
}

export const useReportActionStore = create<ReportActionState>()(
  persist(
    (set) => ({
      lastAction: null,
      setLastAction: (action) => set({ lastAction: action }),
      clearLastAction: () => set({ lastAction: null }),
    }),
    { name: 'aml-last-action' }
  )
);

