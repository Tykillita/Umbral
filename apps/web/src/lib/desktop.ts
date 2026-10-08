import type { MotionPreference } from './motionPreference';

export interface DesktopStatus {
  snapshotId: string | null; busy: boolean; operation: 'reclassify' | 'update' | null; message: string | null;
  stage: string; completed: number; total: number; error: string | null; available: boolean;
}
export interface DesktopWindowState { maximized: boolean }
export interface DesktopUpdateState {
  status: 'idle' | 'checking' | 'downloading' | 'downloaded' | 'error';
  version?: string;
  percent?: number;
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
  motionPreference?: MotionPreference;
  setMotionPreference?(preference: MotionPreference): Promise<MotionPreference>;
  getStatus(): Promise<DesktopStatus>;
  reclassify(): Promise<DesktopStatus>;
  updateSnapshot(): Promise<DesktopStatus>;
  getUpdateState(): Promise<DesktopUpdateState>;
  checkForUpdates(): Promise<void>;
  installUpdate(): Promise<boolean>;
  onUpdateState(callback: (state: DesktopUpdateState) => void): () => void;
  windowControls?: DesktopWindowControls;
  onProgress(callback: (status: DesktopStatus) => void): () => void;
}
declare global { interface Window { umbralDesktop?: DesktopBridge } }
