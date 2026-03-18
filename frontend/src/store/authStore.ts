import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface AuthState {
  user: { displayName: string; email?: string } | null;
  setUser: (user: { displayName: string; email?: string } | null) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: { displayName: 'User', email: 'user@aml-platform.ng' },
      setUser: (user) => set({ user }),
      logout: () => set({ user: null }),
    }),
    { name: 'aml-auth' }
  )
);
