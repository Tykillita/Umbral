export interface DesktopStatus {
  snapshotId: string | null; busy: boolean; operation: 'reclassify' | 'update' | null; message: string | null;
  stage: string; completed: number; total: number; error: string | null; available: boolean;
}
export interface DesktopBridge {
  version: string; platform: 'win32'; apiToken: string;
  getStatus(): Promise<DesktopStatus>;
  reclassify(): Promise<DesktopStatus>;
  updateSnapshot(): Promise<DesktopStatus>;
  onProgress(callback: (status: DesktopStatus) => void): () => void;
}
declare global { interface Window { umbralDesktop?: DesktopBridge } }
