import { createContext, useContext } from 'react';
import type { UmbralApi } from '../lib/api/client';
import type { Route } from '../lib/router';
import type { DemoSession } from '../lib/session';

export interface AppCtx {
  api: UmbralApi;
  mockReason: string | null;
  route: Route;
  go: (r: Route) => void;
  toast: AppToast | null;
  showToast: (message: Omit<AppToast, 'id'>) => void;
  dismissToast: () => void;
  reviewer: string;
  setReviewer: (name: string) => void;
  openAssistant: (prompt?: string, topicId?: string, topicTitle?: string) => void;
  authMode: 'public' | 'local' | 'firebase-anonymous';
  session?: DemoSession;
  changeRole?: () => void;
}

export interface AppToast {
  id: number;
  tone: 'pending' | 'success' | 'error' | 'info';
  title: string;
  description?: string;
  durationMs?: number;
  progress?: number | null;
  actionLabel?: string;
  actionHref?: string;
}

export const AppContext = createContext<AppCtx | null>(null);

export function useApp(): AppCtx {
  const c = useContext(AppContext);
  if (!c) throw new Error('useApp fuera de AppContext');
  return c;
}
