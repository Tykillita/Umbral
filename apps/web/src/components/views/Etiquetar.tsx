import { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight, Download, EyeOff, Layers, Quote, Tag } from 'lucide-react';
import { fetchSheets, sheetItems, type SheetClaim, type SheetSource } from '../../lib/labelSheets';
import {
  fetchLabels,
  labelsForSession,
  latestLabels,
  mergeById,
  retrySharing,
  storeLabel,
  type LabelType,
} from '../../lib/team';
import { fmtDateTime } from '../../lib/format';
import { useApp } from '../context';
import { TeamStatus, useLocalTeam, useSharedConfiguration } from '../TeamStatus';
import { Button, Card, ErrorBox, Field, Loading, Notice, SectionTitle, inputCls } from '../ui';
import { downloadJson } from './Mesa';

const OPTIONS: Record<LabelType, { value: string; label: string }[]> = {
  topic: [
    { value: 'economia', label: 'Economía' },
    { value: 'logistica_canal', label: 'Logística / Canal' },
    { value: 'turismo', label: 'Turismo' },
    { value: 'servicios_publicos', label: 'Servicios públicos' },
    { value: 'eventos_naturales', label: 'Eventos naturales' },
    { value: 'regulacion', label: 'Regulación' },
    { value: 'indeterminado', label: 'Ninguno de los seis' },
    { value: 'no_se', label: 'No sé' },
  ],
  pair: [
    { value: 'si', label: 'Sí, el mismo hecho' },
    { value: 'no', label: 'No, son distintos' },
    { value: 'no_se', label: 'No sé' },
  ],
  claim: [
    { value: 'respaldada', label: 'Respaldada por la cita' },
    { value: 'no_respaldada', label: 'No respaldada' },
    { value: 'cita_incorrecta', label: 'Cita incorrecta' },
    { value: 'no_se', label: 'No sé' },
  ],
};
const MODES = [
  {
    type: 'topic' as const,
    label: 'Temas',
    icon: Tag,
    help: 'Elige el tema principal del titular. Si encaja en dos, elige el principal y menciona el otro en el comentario.',
  },
  {
    type: 'pair' as const,
    label: '¿Mismo hecho?',
    icon: Layers,
    help: '¿Los dos titulares informan sobre el mismo hecho concreto? No basta con compartir un tema general; una copia de agencia cuenta como el mismo hecho.',
  },
  {
    type: 'claim' as const,
    label: 'Afirmaciones',
    icon: Quote,
    help: 'Compara la afirmación con todas sus citas. Un titular solo respalda que un medio reportó algo; no confirma que sucedió ni permite añadir detalles.',
  },
];
const valueLabel = (type: LabelType, value: string) =>
  OPTIONS[type].find((option) => option.value === value)?.label ?? value;
function SourceText({ source }: { source: SheetSource }) {
  return (
    <div className="rounded border border-rule-strong bg-paper p-3">
      <p className="font-display text-xl font-bold leading-snug">{source.text}</p>
      <p className="mt-2 text-xs text-ink-3">
        {source.outlet} · {fmtDateTime(source.publishedAt ?? source.detectedAt)}
      </p>
      {/^https?:\/\//.test(source.url) && (
        <a
          className="comic-link text-sm underline"
          href={source.url}
          target="_blank"
          rel="noopener noreferrer"
        >
          Abrir fuente
        </a>
      )}
    </div>
  );
}
function ClaimText({ claim }: { claim: SheetClaim }) {
  return (
    <div className="space-y-3">
      <div className="rounded border border-rule-strong bg-paper p-3">
        <p className="kicker">Afirmación del borrador</p>
        <p className="font-semibold">{claim.text}</p>
      </div>
      <ul className="grid gap-2 sm:grid-cols-2">
        {claim.citations.map((citation, index) => (
          <li
            key={`${citation.evidenceId}:${index}`}
            className="rounded border border-rule-strong bg-amber-50 p-3"
          >
            <p className="kicker">
              Cita {index + 1} · {citation.field}
            </p>
            <p className="font-semibold">{citation.title ?? 'Fuente no encontrada en el corte'}</p>
            {citation.passage && <p className="mt-1 text-sm">Pasaje: «{citation.passage}»</p>}
            <p className="mt-2 text-xs text-ink-3">
              {citation.outlet ?? citation.evidenceId} ·{' '}
              {fmtDateTime(citation.publishedAt ?? citation.detectedAt)}
            </p>
            {citation.url && /^https?:\/\//.test(citation.url) && (
              <a
                className="comic-link text-sm underline"
                href={citation.url}
                target="_blank"
                rel="noopener noreferrer"
              >
                Abrir fuente
              </a>
            )}
          </li>
        ))}
      </ul>
      {!claim.citations.length && <p className="text-sm text-warn">La afirmación no incluye citas.</p>}
    </div>
  );
}
export function Etiquetar() {
  const { session } = useApp(),
    client = useQueryClient(),
    local = useLocalTeam();
  const { configured } = useSharedConfiguration();
  const sheets = useQuery({
    queryKey: ['label-sheets'],
    queryFn: fetchSheets,
    staleTime: Infinity,
    retry: false,
  });
  const remote = useQuery({
    queryKey: ['team-labels', sheets.data?.snapshotId, sheets.data?.sheetHash],
    queryFn: () => fetchLabels(sheets.data!.snapshotId, sheets.data!.sheetHash),
    enabled: configured && Boolean(sheets.data),
    refetchInterval: 30000,
    retry: false,
  });
  const [type, setType] = useState<LabelType>('topic'),
    [position, setPosition] = useState(0),
    [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null),
    [notice, setNotice] = useState('');
  const h = sheets.data;
  const labels = useMemo(
    () =>
      mergeById(local.data?.labels ?? [], remote.data ?? [], (label) => label.id).filter(
        (label) => label.snapshotId === h?.snapshotId && label.sheetHash === h.sheetHash,
      ),
    [local.data, remote.data, h],
  );
  const own = useMemo(() => latestLabels(labels, session?.sessionId), [labels, session?.sessionId]);
  const exportLabels = useMemo(() => labelsForSession(labels, session?.sessionId), [labels, session?.sessionId]);
  const team = useMemo(() => latestLabels(labels), [labels]);
  if (sheets.isLoading || local.isLoading) return <Loading label="Cargando hojas de etiquetado…" />;
  if (sheets.error) return <ErrorBox error={sheets.error} onRetry={() => sheets.refetch()} />;
  if (local.error) return <ErrorBox error={local.error} />;
  if (!h) return null;
  const items = sheetItems(h, type),
    index = Math.max(0, Math.min(position, items.length - 1)),
    item = items[index];
  const key = (mode: LabelType, id: string) => `${h.snapshotId}:${h.sheetHash}:${mode}:${id}`;
  const current = item ? own.get(key(type, item.id)) : undefined;
  const teamCurrent = item && current ? team.get(key(type, item.id)) : undefined;
  const progress = (mode: LabelType) =>
    sheetItems(h, mode).filter((entry) => own.has(key(mode, entry.id))).length;
  const reset = () => {
    setComment('');
    setNotice('');
    setError(null);
  };
  const mark = async (value: string) => {
    if (!session || !item || busy) return;
    setBusy(true);
    setError(null);
    setNotice('');
    try {
      await storeLabel(session, {
        snapshotId: h.snapshotId,
        sheetHash: h.sheetHash,
        type,
        itemId: item.id,
        value,
        comment: comment.trim(),
      });
      setComment('');
      await client.invalidateQueries({ queryKey: ['local-team'] });
      if (configured) {
        try {
          await retrySharing();
          setNotice('Etiqueta guardada y confirmada en la mesa.');
          await client.invalidateQueries({ queryKey: ['team-labels'] });
        } catch (failure) {
          setNotice('Etiqueta guardada en este navegador; sigue pendiente de compartir.');
          setError(failure);
        }
      } else setNotice('Etiqueta guardada en este navegador. Descarga una copia al terminar.');
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-4" data-testid="etiquetar-view">
      <Card>
        <SectionTitle
          heading
          kicker="Evaluación reproducible · revisión humana"
          aside={
            <Button
              icon={Download}
              onClick={() =>
                downloadJson(
                  { version: 1, snapshotId: h.snapshotId, sheetHash: h.sheetHash, labels: exportLabels },
                  `etiquetas.${h.snapshotId}.json`,
                )
              }
              data-testid="etiquetas-export"
            >
              Descargar etiquetas
            </Button>
          }
        >
          Etiquetado humano
        </SectionTitle>
        <p className="text-sm text-ink-2">
          Se etiqueta a ciegas: no se muestran predicciones ni respuestas ajenas antes de tu primera
          respuesta. Si dudas, elige «No sé». Las métricas se calculan después con los juicios registrados.
        </p>
        <p className="mt-2 text-xs text-ink-3">
          Corte: <span className="font-mono">{h.snapshotId}</span>. Progreso de tu sesión actual.
        </p>
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          {MODES.map(({ type: mode, label, icon: Icon }) => (
            <button
              key={mode}
              type="button"
              className={`comic-label-mode ${mode === type ? 'is-active' : ''}`}
              aria-pressed={mode === type}
              disabled={busy}
              onClick={() => {
                setType(mode);
                setPosition(0);
                reset();
              }}
              data-testid={`etiquetar-modo-${mode}`}
            >
              <span className="flex items-center gap-2 font-display text-xl font-bold">
                <Icon size={18} aria-hidden="true" />
                {label}
              </span>
              <span className="text-sm">
                {progress(mode)} / {sheetItems(h, mode).length} etiquetados
              </span>
              <span className="comic-label-progress" aria-hidden="true">
                <span style={{ width: `${(100 * progress(mode)) / (sheetItems(h, mode).length || 1)}%` }} />
              </span>
            </button>
          ))}
        </div>
      </Card>
      <TeamStatus />
      {remote.error && <ErrorBox error={remote.error} onRetry={() => remote.refetch()} />}
      {item ? (
        <Card data-testid="etiquetar-item">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-sm text-ink-3">
            <span className="flex items-center gap-1.5">
              <EyeOff size={16} aria-hidden="true" />A ciegas · {index + 1} de {items.length}
            </span>
            <span className="flex gap-1">
              <Button
                icon={ChevronLeft}
                variant="ghost"
                aria-label="Elemento anterior"
                disabled={busy || index === 0}
                onClick={() => {
                  setPosition(index - 1);
                  reset();
                }}
              />
              <Button
                icon={ChevronRight}
                variant="ghost"
                aria-label="Elemento siguiente"
                disabled={busy || index === items.length - 1}
                onClick={() => {
                  setPosition(index + 1);
                  reset();
                }}
              />
            </span>
          </div>
          <p className="mb-3 text-sm text-ink-2">{MODES.find((mode) => mode.type === type)!.help}</p>
          {'a' in item ? (
            <div className="grid gap-3 md:grid-cols-2">
              <SourceText source={item.a} />
              <SourceText source={item.b} />
            </div>
          ) : 'citations' in item ? (
            <ClaimText claim={item} />
          ) : (
            <SourceText source={item} />
          )}
          <Field htmlFor="label-comment" label="Comentario opcional">
            <textarea
              id="label-comment"
              className={`${inputCls} mt-3`}
              rows={2}
              maxLength={2000}
              disabled={busy}
              value={comment}
              onChange={(event) => setComment(event.target.value)}
            />
          </Field>
          <div
            className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4"
            role="group"
            aria-label="Registrar mi etiqueta"
          >
            {OPTIONS[type].map((option) => (
              <Button
                key={option.value}
                variant={current?.value === option.value ? 'primary' : 'secondary'}
                aria-pressed={current?.value === option.value}
                busy={busy && current?.value === option.value}
                disabled={busy || !session}
                onClick={() => void mark(option.value)}
                data-testid={`etiqueta-${option.value}`}
              >
                {option.label}
              </Button>
            ))}
          </div>
          <p className="mt-2 text-xs text-ink-3">
            Firma: <strong>{session?.labeler}</strong> · cambiar una respuesta agrega una nueva versión al
            historial.
          </p>
          {current && (
            <div className="mt-3 border-t border-rule pt-3 text-sm" data-testid="label-own-response">
              <p>
                Tu respuesta vigente: <strong>{valueLabel(type, current.value)}</strong>
                {current.comment ? ` · ${current.comment}` : ''}.
              </p>
              {teamCurrent && (
                <p className="mt-1" data-testid="label-team-response">
                  Respuesta más reciente del equipo: <strong>{valueLabel(type, teamCurrent.value)}</strong> ·{' '}
                  {teamCurrent.labeler} · {fmtDateTime(teamCurrent.createdAt)}.
                </p>
              )}
              <p className="mt-1 text-xs text-ink-3">
                Se conservan todos los juicios. La descarga incluye el historial; el equipo y tu sesión tienen
                respuestas vigentes separadas.
              </p>
            </div>
          )}
          {notice && (
            <p className="mt-3 text-sm text-ok" role="status">
              {notice}
            </p>
          )}
          {Boolean(error) && (
            <div className="mt-3">
              <ErrorBox error={error} />
            </div>
          )}
        </Card>
      ) : (
        <Notice tone="info" title="No hay elementos de este tipo en estas hojas">
          Selecciona otro modo de etiquetado.
        </Notice>
      )}
      <Notice tone="info" title="Conservar y entregar las etiquetas">
        Descarga tu historial de respuestas. La copia solo contiene tus juicios, con corte, huella, rol y fecha,
        para no revelar etiquetas ajenas de elementos pendientes. Para evaluar al equipo completo, combina las
        descargas con <code>scripts/import_label_events.py --export uno.json --export dos.json</code>.
      </Notice>
    </div>
  );
}
