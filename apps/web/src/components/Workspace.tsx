import { useId, useState, useEffect, useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useApp } from './context';
import { useHealth } from '../lib/hooks';
import { Button, Card, ErrorBox, Field, Loading, Notice, SectionTitle, inputCls } from './ui';
import { Disclosure } from './ui/controls';
import type { DesktopStatus } from '../lib/desktop';
import { parseWorkspace } from '../lib/api/workspace';

const MAX_COPY_BYTES = 20 * 1024 * 1024;
export function WorkspaceCard() {
  const { api, authMode } = useApp();
  const health = useHealth(), queryClient = useQueryClient(), id = useId();
  const [source, setSource] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const eligible = authMode === 'public' || (authMode === 'local' && health.data?.localMode);
  const exportCopy = useMutation({ mutationFn: async () => {
    if (!api.exportWorkspace) throw new Error('La copia de este espacio de trabajo no está disponible.');
    const data = await api.exportWorkspace();
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url; link.download = 'umbral-workspace-' + data.exportedAt.slice(0, 10) + '.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setMessage('Copia preparada. Guárdala para mover tu trabajo entre navegador y escritorio.');
  } });
  const importCopy = useMutation({ mutationFn: async () => {
    if (!api.importWorkspace) throw new Error('No se puede importar en este espacio.');
    if (new TextEncoder().encode(source).byteLength > MAX_COPY_BYTES) throw new Error('La copia supera el límite de 20 MB.');
    let value: unknown;
    try { value = JSON.parse(source); } catch { throw new Error('El texto no es JSON válido. Pega el contenido completo de la copia.'); }
    const result = await api.importWorkspace(parseWorkspace(value));
    await Promise.all(['topics','topic','rules','workspace-cases'].map((key) => queryClient.invalidateQueries({ queryKey: [key] })));
    setSource(''); setMessage('Copia importada: ' + result.imported + ' casos añadidos. Tus casos existentes se conservaron.');
  } });
  if (!eligible) return null;
  return <Card data-testid="workspace-card">
    <SectionTitle kicker="Tu trabajo">Copia y traslado del espacio de trabajo</SectionTitle>
    <Notice tone="info" title={authMode === 'public' ? 'Privado en este navegador' : 'Guardado en este equipo'}>
      Los borradores, revisiones y pesos no se comparten entre dispositivos. Exporta una copia antes de borrar los datos del navegador o cambiar de equipo.
      Las consultas y la generación se envían a la API; para revisar una edición se envía su texto y evidencia de forma temporal, sin guardar el caso en la nube.
    </Notice>
    <div className="mt-3"><Button data-testid="workspace-export" busy={exportCopy.isPending} onClick={() => { setMessage(null); exportCopy.mutate(); }}>Exportar copia JSON</Button></div>
    <Disclosure className="mt-3" testId="workspace-import-panel" summary={<span className="font-semibold">Importar una copia</span>}>
      <div className={'mt-3 space-y-3 border-2 border-dashed p-3 ' + (dragging ? 'border-amber-600 bg-amber-50' : 'border-rule-strong')}
        data-testid="workspace-drop" onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)} onDrop={async (event) => {
          event.preventDefault(); setDragging(false); setError(null); setMessage(null);
          const file = event.dataTransfer.files[0];
          if (!file) return;
          try { if (file.size > MAX_COPY_BYTES) throw new Error('La copia supera el límite de 20 MB.'); setSource(await file.text()); }
          catch (failure) { setError(failure); }
        }}>
        <Field htmlFor={id} label="Contenido JSON de la copia" hint="Pega el contenido o arrastra el archivo aquí. En móvil, abre la copia y pega el texto. No se sobrescriben casos ni políticas en conflicto.">
          <textarea id={id} data-testid="workspace-json" rows={6} className={inputCls + ' font-mono'} value={source} disabled={importCopy.isPending} onChange={(event) => { setSource(event.target.value); setError(null); setMessage(null); importCopy.reset(); }} />
        </Field>
        <Button data-testid="workspace-import" disabled={!source.trim()} busy={importCopy.isPending} onClick={() => { setMessage(null); importCopy.mutate(); }}>Importar casos y pesos</Button>
      </div>
    </Disclosure>
    {(error || exportCopy.error || importCopy.error) && <div className="mt-3"><ErrorBox error={error || exportCopy.error || importCopy.error} /></div>}
    {message && <Notice tone="ok" role="status" testId="workspace-notice">{message}</Notice>}
  </Card>;
}

export function SavedCases() {
  const { api, go, authMode } = useApp();
  const health = useHealth();
  const eligible = Boolean(api.savedCases) && (authMode === 'public' || health.data?.localMode === true);
  const cases = useQuery({ queryKey: ['workspace-cases'], queryFn: () => api.savedCases!(), enabled: eligible });
  if (!eligible) return null;
  return <Card data-testid="saved-cases"><SectionTitle kicker="Conservados en tu dispositivo">Casos guardados</SectionTitle>
    {cases.isLoading && <Loading />}
    {cases.error && <ErrorBox error={cases.error} onRetry={() => cases.refetch()} />}
    {!cases.isLoading && !cases.error && !cases.data?.length && <p className="text-sm text-ink-3">Los casos aparecerán aquí al guardar un borrador, una revisión o un cambio de impacto.</p>}
    <ul className="space-y-2">{cases.data?.map((entry) => <li key={entry.case.caseId} className="border-l-2 border-rule pl-3">
      <a className="comic-link min-h-11 font-semibold underline underline-offset-4" href={'#/borradores/' + encodeURIComponent(entry.case.topicId)}
        onClick={(event) => { event.preventDefault(); go({ view: 'borradores', topicId: entry.case.topicId }); }}>{entry.detail.summary.title}</a>
      <p className="text-xs text-ink-3">{entry.case.statusLabel} · v{entry.case.version} · snapshot {entry.detail.snapshotId}{health.data && entry.detail.snapshotId !== health.data.snapshotId ? ' · archivado, conserva sus fuentes' : ''}</p>
    </li>)}</ul>
  </Card>;
}

export function DesktopCard() {
  const bridge = typeof window !== 'undefined' ? window.umbralDesktop : undefined;
  const previousStatus = useRef<DesktopStatus | null>(null);
  const [status, setStatus] = useState<DesktopStatus | null>(null);
  const [failure, setFailure] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!bridge) return;
    let live = true;
    void bridge.getStatus().then((next) => { if (live) { previousStatus.current = next; setStatus(next); } }).catch((error) => { if (live) setFailure(error); });
    const unsubscribe = bridge.onProgress((next) => { if (live) { const previous = previousStatus.current; previousStatus.current = next; setStatus(next); if (!next.error && previous && ((previous.busy && !next.busy) || previous.snapshotId !== next.snapshotId)) void queryClient.invalidateQueries(); } });
    return () => { live = false; unsubscribe(); };
  }, [bridge, queryClient]);
  if (!bridge) return null;
  const run = async (operation: 'reclassify' | 'update') => {
    setFailure(null); setPending(true);
    try { setStatus(await (operation === 'reclassify' ? bridge.reclassify() : bridge.updateSnapshot())); await queryClient.invalidateQueries(); }
    catch (error) { setFailure(error); } finally { setPending(false); }
  };
  const busy = pending || status?.busy === true;
  return <Card data-testid="desktop-card"><SectionTitle kicker={'Windows · Umbral ' + bridge.version}>Datos y clasificación en este equipo</SectionTitle>
    <p className="text-sm text-ink-2">Laya clasifica las noticias en este equipo. Actualizar descarga el último corte disponible; si falla, se conserva el snapshot válido y tus casos guardados.</p>
    <div className="mt-3 flex flex-wrap gap-2"><Button disabled={!status?.available || busy} busy={pending} data-testid="desktop-reclassify" onClick={() => run('reclassify')}>Reclasificar con Laya local</Button>
      <Button disabled={!status?.available || busy} data-testid="desktop-update" onClick={() => run('update')}>Actualizar noticias</Button></div>
    {status && <p className="mt-3 text-sm" role="status" aria-live="polite" data-testid="desktop-progress">{status.message ?? status.stage}{status.total > 0 ? ' · ' + status.completed + '/' + status.total : ''}</p>}
    {(failure || status?.error) && <ErrorBox error={failure ?? new Error(status?.error ?? '')} />}
  </Card>;
}
