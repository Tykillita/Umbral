import { createContext, useContext } from 'react';
import type { UmbralApi } from '../lib/api/client';
import type { Route } from '../lib/router';

export interface AppCtx {
  api: UmbralApi;
  mockReason: string | null;
  route: Route;
  go: (r: Route) => void;
  reviewer: string;
  setReviewer: (name: string) => void;
  openAssistant: (prompt?: string, topicId?: string, topicTitle?: string) => void;
  authMode: 'public' | 'local' | 'firebase-anonymous';
}

export const AppContext = createContext<AppCtx | null>(null);

export function useApp(): AppCtx {
  const c = useContext(AppContext);
  if (!c) throw new Error('useApp fuera de AppContext');
  return c;
}
