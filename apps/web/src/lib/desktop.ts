import type { MotionPreference } from './motionPreference';

export interface DesktopStatus {
  snapshotId: string | null; busy: boolean; operation: 'reclassify' | 'update' | 'news' | null; message: string | null;
  stage: string; completed: number; total: number; error: string | null; available: boolean;
  newsAutomation?: {
    enabled: boolean; intervalHours: number; lastAttemptAt: string | null; lastSuccessAt: string | null;
    lastCandidateId: string | null; lastWarning: string | null; nextRunAt: string | null;
  };
}
export interface DesktopWindowState { maximized: boolean }
export interface DesktopUpdateState {
  status: 'idle' | 'checking' | 'available' | 'downloading' | 'downloaded' | 'error';
  version?: string;
  percent?: number;
  autoUpdateEnabled?: boolean;
}
export interface DesktopDownloadStatus {
  filename: string;
  status: 'started' | 'progress' | 'completed' | 'error';
  percent: number | null;
}
export interface DesktopWindowControls {
  minimize(): Promise<DesktopWindowState>;
  toggleMaximize(): Promise<DesktopWindowState>;
  close(): Promise<DesktopWindowState>;
  getState(): Promise<DesktopWindowState>;
  onStateChange(callback: (state: DesktopWindowState) => void): () => void;
}
export interface DesktopBridge {
  version: string; platform: 'win32'; apiToken: string;
  firebaseConfig?: { apiKey: string; authDomain: string; projectId: string; appId: string };
  requestConnector?(request: {
    path: string;
    method: 'GET' | 'POST' | 'PUT' | 'DELETE';
    body?: unknown;
    token: string;
  }): Promise<{ status: number; body: unknown; retryAfter: string | null }>;
  motionPreference?: MotionPreference;
  setMotionPreference?(preference: MotionPreference): Promise<MotionPreference>;
  getStatus(): Promise<DesktopStatus>;
  reclassify(): Promise<DesktopStatus>;
  updateSnapshot(): Promise<DesktopStatus>;
  getUpdateState(): Promise<DesktopUpdateState>;
  checkForUpdates(): Promise<void>;
  installUpdate(): Promise<boolean>;
  updateNow?(): Promise<boolean>;
  autoUpdateEnabled?: boolean;
  setAutoUpdateEnabled?(enabled: boolean): Promise<boolean>;
  openChatGPTAuth?(url: string): Promise<void>;
  onUpdateState(callback: (state: DesktopUpdateState) => void): () => void;
  onDownloadStatus?(callback: (status: DesktopDownloadStatus) => void): () => void;
  windowControls?: DesktopWindowControls;
  onProgress(callback: (status: DesktopStatus) => void): () => void;
}
declare global { interface Window { umbralDesktop?: DesktopBridge } }

export function desktopConnectorEnabled(): boolean {
  return typeof window !== 'undefined' && typeof window.umbralDesktop?.requestConnector === 'function';
}
