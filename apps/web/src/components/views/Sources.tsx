import { WorkspaceCard, DesktopCard } from '../Workspace';
import { useRef, type ReactNode } from 'react';
import { Activity, CircleAlert, CircleCheck, CircleX, Database, FlaskConical, Hourglass, PlugZap, ScrollText } from 'lucide-react';
import { useHealth, useRules, useSnapshot } from '../../lib/hooks';
import { DATA_MODE_LABEL } from '../../lib/labels';
import { fmtDateTime, fmtNumber, shortHash } from '../../lib/format';
import { useEntrance } from '../../lib/useMotion';
import { Card, ErrorBox, Loading, Notice, Pill, SectionTitle } from '../ui';
import { Disclosure, Tooltip } from '../ui/controls';
import { ConnectionsCard, RulesEditor } from '../EditorialSettings';

type Rec = Record<string, unknown>;
const isRec = (v: unknown): v is Rec => typeof v === 'object' && v !== null && !Array.isArray(v);
const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);
const strList = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []);

function Scalar({ v }: { v: unknown }): ReactNode {
  if (v === null || v === undefined) return <span className="text-ink-3">—</span>;
  if (typeof v === 'number') return fmtNumber(v, 4);
  if (typeof v === 'boolean') return v ? 'sí' : 'no';
  if (typeof v === 'string') return v;
  if (Array.isArray(v)) return v.map((x) => (isRec(x) ? JSON.stringify(x) : String(x))).join(', ');
  return JSON.stringify(v);
}

/** Aplana un objeto anidado a pares «ruta → valor» (máx. 3 niveles) para mostrar métricas sin suponer su esquema. */
function flatten(obj: Rec, prefix = '', depth = 0): [string, unknown][] {
  const out: [string, unknown][] = [];
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (isRec(v) && depth < 3) out.push(...flatten(v, key, depth + 1));
    else out.push([key, v]);
  }
  return out;
}

function KvTable({ rows, testId }: { rows: [string, unknown][]; testId?: string }) {
  return (
    <div className="overflow-x-auto">
      <table data-testid={testId} className="w-full text-left text-sm">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k} className="border-b border-rule last:border-0">
              <th scope="row" className="w-1/2 py-1 pr-3 align-top font-normal text-ink-3">
                {k}
              </th>
              <td className="py-1 font-medium">
                <Scalar v={v} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --------------------------------------------------------------------------- secciones

function SnapshotCard() {
  const health = useHealth();
  const snap = useSnapshot();
  if (snap.isLoading || health.isLoading) return <Loading label="Cargando snapshot…" />;
  if (snap.error) return <ErrorBox error={snap.error} onRetry={() => snap.refetch()} />;
  const s = snap.data;
  if (!s) return null;
  const h = health.data;
  const m = s.manifest;
  const classifier = isRec(m.classifier) ? m.classifier : {};
  const window = isRec(m.window) ? m.window : {};
  const counts = isRec(m.counts) ? m.counts : {};
  const isBaseline = (str(classifier.classifier) ?? h?.classifier) === 'baseline';
  const provisional = h?.provisional ?? m.provisional === true;
  const fixtures = h?.containsFixtures ?? m.containsFixtures === true;
  const i = s.integrity;
  const predOk = i.predictionsHashVerified;

  return (
    <Card aria-labelledby="snap-title" data-testid="snapshot-card">
      <SectionTitle id="snap-title" kicker="Versión de los datos">
        Snapshot servido
      </SectionTitle>
      <div className="mb-3 flex flex-wrap gap-1.5">
        <Pill tone="neutral" icon={Database} testId="sources-snapshot-id">
          {s.snapshotId}
        </Pill>
        <Pill tone={provisional ? 'warn' : 'ok'} icon={provisional ? Hourglass : CircleCheck} testId="snapshot-provisional" data-provisional={String(provisional)}>
          {provisional ? 'Provisional (no es el paquete congelado)' : 'Congelado'}
        </Pill>
        {s.dataMode !== 'provisional' && (
          <Pill tone={s.dataMode === 'fixture' ? 'bad' : 'neutral'} icon={s.dataMode === 'fixture' ? CircleAlert : Database} testId="snapshot-data-mode">
            {DATA_MODE_LABEL[s.dataMode]}
          </Pill>
        )}
        {fixtures && (
          <Pill tone="bad" icon={FlaskConical} testId="snapshot-fixtures">
            Contiene registros de fixture
          </Pill>
        )}
        {isBaseline && (
          <Pill tone="warn" icon={CircleAlert} testId="classifier-baseline">
            Clasificador léxico (baseline), no Laya
          </Pill>
        )}
      </div>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-sm [overflow-wrap:anywhere] sm:grid-cols-2">
        <div>
          <dt className="text-ink-3">Corte (UTC → Panamá)</dt>
          <dd className="font-medium">{fmtDateTime(h?.cutoffUtc ?? str(m.cutoffUtc))}</dd>
        </div>
        <div>
          <dt className="text-ink-3">Ventana de noticias</dt>
          <dd className="font-medium">
            {window.days !== undefined ? `${String(window.days)} días` : '—'}
            {window.widenedTo90 === true ? ' (ampliada desde 30 por falta de cobertura)' : ''}
          </dd>
        </div>
        <div>
          <dt className="text-ink-3">Versión del paquete / reglas</dt>
          <dd className="font-medium">
            {str(m.version) ?? '—'} · {h?.rulesVersion ?? 'scoring-v1'}
          </dd>
        </div>
        <div>
          <dt className="text-ink-3">Clasificador</dt>
          <dd className="font-medium">
            {str(classifier.modelId) ?? '—'} {str(classifier.modelVersion) ? `(${str(classifier.modelVersion)})` : ''}
          </dd>
        </div>
        <div>
          <dt className="text-ink-3">Registros</dt>
          <dd className="font-medium">
            {fmtNumber(Number(counts.articlesValid ?? h?.counts.articles ?? 0), 0)} noticias · {fmtNumber(Number(counts.indicatorRows ?? h?.counts.indicators ?? 0), 0)} indicadores ·{' '}
            {fmtNumber(Number(counts.clusters ?? h?.counts.clusters ?? 0), 0)} grupos
          </dd>
        </div>
        <div>
          <dt className="text-ink-3">Inválidos separados</dt>
          <dd className="font-medium">{fmtNumber(Number(counts.articlesInvalid ?? 0), 0)}</dd>
        </div>
      </dl>

      <h3 className="mt-4 text-sm font-semibold">Integridad</h3>
      <ul className="mt-1 space-y-1 text-sm" data-testid="integrity-status">
        <li className="flex items-center gap-2" data-ok={i.manifestVerified}>
          {i.manifestVerified ? <CircleCheck size={16} className="text-ok" aria-hidden="true" /> : <CircleX size={16} className="text-bad" aria-hidden="true" />}
          {i.manifestVerified ? `Manifest SHA-256 verificado (${i.filesChecked} archivos)` : 'El manifest SHA-256 NO coincide con los archivos'}
        </li>
        <li className="flex items-center gap-2" data-ok={predOk === true}>
          {predOk ? <CircleCheck size={16} className="text-ok" aria-hidden="true" /> : <CircleX size={16} className="text-bad" aria-hidden="true" />}
          {predOk === true
            ? `Hash de predicciones verificado (${shortHash(i.predictionsSha256, 16)}): corresponde al snapshot servido`
            : predOk === false
              ? 'El hash de las predicciones NO corresponde al snapshot servido'
              : 'Sin predicciones que verificar'}
        </li>
      </ul>
      {i.errors.length > 0 && (
        <ul className="mt-2 list-disc pl-5 text-sm text-bad" role="alert">
          {i.errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      <FilesTable manifest={m} />
    </Card>
  );
}

function FilesTable({ manifest }: { manifest: Rec }) {
  const files = isRec(manifest.files) ? Object.entries(manifest.files) : [];
  if (!files.length) return null;
  return (
    <Disclosure className="mt-3 text-sm" summary={<span className="font-semibold">Archivos del manifest (SHA-256)</span>}>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-left text-xs" data-testid="manifest-files">
          <thead>
            <tr className="border-b border-rule text-ink-3">
              <th className="py-1 pr-3 font-semibold">Archivo</th>
              <th className="py-1 pr-3 font-semibold">Registros</th>
              <th className="py-1 font-semibold">SHA-256</th>
            </tr>
          </thead>
          <tbody>
            {files.map(([name, meta]) => (
              <tr key={name} className="border-b border-rule last:border-0">
                <td className="py-1 pr-3 font-mono">{name}</td>
                <td className="py-1 pr-3">{isRec(meta) && typeof meta.records === 'number' ? fmtNumber(meta.records, 0) : '—'}</td>
                <td className="py-1 font-mono">
                  {isRec(meta) && str(meta.sha256) ? (
                    <Tooltip content={str(meta.sha256) ?? ''}>
                      <span>{shortHash(str(meta.sha256), 20)}</span>
                    </Tooltip>
                  ) : (
                    '—'
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Disclosure>
  );
}

/** Cobertura declarada por la fuente o, si falta, derivada del reporte de calidad del mismo snapshot (se rotula como calculada). */
function coverageText(src: Rec, quality: Rec | null | undefined): string | null {
  const given = str(src.coverage);
  if (given) return given;
  if (!quality) return null;
  const news = isRec(quality.news) ? quality.news : {};
  const ind = isRec(quality.indicators) ? quality.indicators : {};
  const num = (v: unknown) => (typeof v === 'number' ? fmtNumber(v, 0) : null);
  const id = str(src.id);
  if (id === 'tvn_rss' && num(news.tvnValid)) return `${num(news.tvnValid)} noticias válidas en el corte (calculado del reporte de calidad)`;
  if (id === 'gdelt_doc' && num(news.gdeltValid)) return `${num(news.gdeltValid)} noticias válidas; las consultas con HTTP 429 no devolvieron datos (calculado del reporte de calidad)`;
  if (id === 'world_bank' && num(ind.withValue) && num(ind.expectedCombinations))
    return `${num(ind.withValue)} de ${num(ind.expectedCombinations)} combinaciones país × indicador × año con valor (calculado del reporte de calidad)`;
  return null;
}

function CatalogCard() {
  const snap = useSnapshot();
  const sources = snap.data?.sources ?? [];
  const quality = (snap.data?.qualityReport ?? null) as Rec | null;
  return (
    <Card aria-labelledby="cat-title" data-testid="sources-catalog">
      <SectionTitle id="cat-title" kicker="Catálogo" aside={<span className="text-xs text-ink-3">{sources.length} fuentes</span>}>
        Fuentes de datos
      </SectionTitle>
      {sources.length === 0 && !snap.isLoading && <Notice tone="warn" title="El snapshot no declara fuentes" />}
      <ul className="space-y-3">
        {sources.map((src, i) => {
          const fields = strList(src.fields);
          const tr = strList(src.transformations);
          const url = str(src.url);
          return (
            <li key={str(src.id) ?? i} data-testid="source-row" className="rounded-md border border-rule p-3 text-sm">
              <p className="font-semibold">{str(src.name) ?? str(src.id) ?? 'Fuente'}</p>
              <dl className="mt-1 grid gap-x-6 gap-y-0.5 sm:grid-cols-2">
                <div>
                  <dt className="inline text-ink-3">URL: </dt>
                  <dd className="inline break-all">
                    {url && /^https?:\/\//.test(url) ? (
                      <a className="underline underline-offset-2 hover:text-amber-700" href={url} target="_blank" rel="noreferrer noopener">
                        {url}
                      </a>
                    ) : (
                      (url ?? '—')
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="inline text-ink-3">Extracción: </dt>
                  <dd className="inline">{fmtDateTime(str(src.extractedAt))}</dd>
                </div>
                <div>
                  <dt className="inline text-ink-3">Cobertura: </dt>
                  <dd className="inline">{coverageText(src, quality) ?? <span className="text-ink-3">sin dato en el catálogo</span>}</dd>
                </div>
                <div>
                  <dt className="inline text-ink-3">Licencia: </dt>
                  <dd className="inline">{str(src.license) ?? '—'}</dd>
                </div>
                <div className="sm:col-span-2">
                  <dt className="inline text-ink-3">Condiciones de uso: </dt>
                  <dd className="inline">{str(src.terms) ?? '—'}</dd>
                </div>
                {fields.length > 0 && (
                  <div className="sm:col-span-2">
                    <dt className="inline text-ink-3">Campos: </dt>
                    <dd className="inline font-mono text-xs">{fields.join(', ')}</dd>
                  </div>
                )}
                {tr.length > 0 && (
                  <div className="sm:col-span-2">
                    <Disclosure summary={<span className="text-ink-3">Transformaciones aplicadas ({tr.length} pasos)</span>}>
                      <p className="mt-1 [overflow-wrap:anywhere]">{tr.join(' → ')}</p>
                    </Disclosure>
                  </div>
                )}
              </dl>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function QualityCard() {
  const snap = useSnapshot();
  const q = snap.data?.qualityReport;
  return (
    <Card aria-labelledby="qual-title" data-testid="quality-report">
      <SectionTitle id="qual-title" kicker="Validación de la carga">
        Reporte de calidad
      </SectionTitle>
      {!q ? (
        <Notice tone="warn" title="El snapshot no incluye reporte de calidad" />
      ) : (
        <div className="space-y-4">
          {str(q.label) && (
            <Notice tone="bad" title={str(q.label) ?? ''} testId="quality-label" icon={FlaskConical} />
          )}
          {(['news', 'indicators', 'classification', 'clusters'] as const).map((k) => {
            const sec = q[k];
            if (!isRec(sec)) return null;
            const title = { news: 'Noticias', indicators: 'Indicadores', classification: 'Clasificación', clusters: 'Agrupación' }[k];
            const rows = flatten(sec);
            return (
              <Disclosure className="rounded-md border border-rule p-2" summary={<span className="text-sm font-semibold">{title} <span className="font-normal text-ink-3">· {rows.length} valores (abrir para ver el detalle)</span></span>}>
                <div className="mt-2">
                  <KvTable rows={rows} testId={`quality-${k}`} />
                </div>
              </Disclosure>
            );
          })}
          {Array.isArray(q.checks) && q.checks.length > 0 && (
            <div>
              <h3 className="mb-1 text-sm font-semibold">Controles</h3>
              <ul className="space-y-1 text-sm" data-testid="quality-checks">
                {q.checks.filter(isRec).map((c, i) => (
                  <li key={i} className="flex items-start gap-2" data-ok={c.ok === true}>
                    {c.ok === true ? <CircleCheck size={16} className="mt-0.5 text-ok" aria-hidden="true" /> : <CircleX size={16} className="mt-0.5 text-bad" aria-hidden="true" />}
                    <span>
                      <span className="font-mono text-xs">{str(c.id)}</span> · {str(c.detail) ?? ''}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {strList(q.warnings).length > 0 && (
            <Notice tone="warn" title="Advertencias del pipeline" testId="quality-warnings">
              <ul className="list-disc pl-5">
                {strList(q.warnings).map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </Notice>
          )}
        </div>
      )}
    </Card>
  );
}

const METRIC_SECTION_LABEL: Record<string, string> = {
  classification: 'Clasificación (macro-F1)',
  clustering: 'Agrupación de duplicados (precisión/recall)',
  benchmarkDev: 'Benchmark de desarrollo (40 consultas)',
  benchmarkReserved: 'Benchmark reservado (20 consultas, fuera del repo)',
  humanSupport: 'Sustento humano de afirmaciones (≥ 30)',
  agendaPrecisionAt5: 'Precision@5 de la agenda (juicio editorial)',
};

function MetricsCard() {
  const snap = useSnapshot();
  const metrics = snap.data?.metrics ?? null;
  return (
    <Card aria-labelledby="met-title" data-testid="metrics-card">
      <SectionTitle id="met-title" kicker="Evaluación">
        Métricas reales
      </SectionTitle>
      <div data-testid="metrics-table" data-empty={!metrics}>
      {!metrics ? (
        <Notice tone="warn" icon={Hourglass} title="Sin ejecutar" testId="metrics-empty">
          Todavía no hay una ejecución real de las métricas (clasificación, agrupación, benchmark, citas, latencia). No se muestran cifras de ejemplo: se publicarán aquí con su
          comando, fecha y numerador/denominador cuando exista la ejecución.
        </Notice>
      ) : (
        <div className="space-y-4" data-testid="metrics-values">
          {str(metrics.generatedAt) && <p className="text-xs text-ink-3">Generado: {fmtDateTime(str(metrics.generatedAt))}</p>}
          {isRec(metrics.sections) ? (
            Object.entries(metrics.sections).map(([key, sec]) => {
              const status = isRec(sec) ? str(sec.status) : null;
              const executed = status === 'ejecutado';
              const rest = isRec(sec) ? flatten(Object.fromEntries(Object.entries(sec).filter(([k]) => k !== 'status'))) : [];
              return (
                <div key={key} data-testid="metrics-section" data-section={key} data-status={status ?? 'desconocido'}>
                  <h3 className="mb-1 flex flex-wrap items-center gap-2 text-sm font-semibold">
                    {METRIC_SECTION_LABEL[key] ?? key}
                    <Pill tone={executed ? 'ok' : 'neutral'} icon={executed ? Activity : Hourglass}>
                      {executed ? 'Ejecutado' : 'Pendiente (sin ejecutar)'}
                    </Pill>
                  </h3>
                  {executed && rest.length > 0 && (
                    <Disclosure className="rounded-md border border-rule p-2" summary={<span className="text-sm text-ink-3">Ver {rest.length} valores de esta ejecución</span>}>
                      <div className="mt-2">
                        <KvTable rows={rest} />
                      </div>
                    </Disclosure>
                  )}
                </div>
              );
            })
          ) : (
            <KvTable rows={flatten(metrics)} />
          )}
        </div>
      )}
      </div>
    </Card>
  );
}

function SystemCard() {
  const health = useHealth();
  const rules = useRules();
  const h = health.data;
  const r = rules.data;
  return (
    <Card aria-labelledby="sys-title" data-testid="system-card">
      <SectionTitle id="sys-title" kicker="Servicio y reglas">
        Estado del sistema
      </SectionTitle>
      {health.error && <ErrorBox error={health.error} onRetry={() => health.refetch()} />}
      {h && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-1.5">
            <Pill tone={h.status === 'ok' ? 'ok' : 'bad'} icon={h.status === 'ok' ? CircleCheck : CircleX} testId="health-status">
              API {h.status === 'ok' ? 'operativa' : 'degradada'} · v{h.apiVersion}
            </Pill>
            <Pill tone={h.offline ? 'warn' : 'neutral'} icon={PlugZap} testId="offline-pill">
              {h.offline ? 'Modo sin conexión: llamadas externas bloqueadas' : 'Con conexión'}
            </Pill>
            <Pill tone="neutral">Persistencia: {h.persistence}</Pill>
            <Pill tone="neutral">Acceso: {h.authMode === 'local' ? 'usuario único local' : h.authMode}</Pill>
          </div>
          <div>
            <h3 className="mb-1 text-sm font-semibold">Proveedores de redacción</h3>
            <ul className="space-y-1 text-sm" data-testid="providers-list">
              {h.providers.map((p) => (
                <li key={p.name} data-provider={p.name} data-available={p.available} className="flex flex-wrap items-center gap-2">
                  {p.available ? <CircleCheck size={16} className="text-ok" aria-hidden="true" /> : <CircleX size={16} className="text-ink-3" aria-hidden="true" />}
                  <strong>{p.name}</strong>
                  <span className="text-ink-3">
                    {p.available ? 'disponible' : 'no disponible'}
                    {p.localOnly ? ' · solo localhost' : ''}
                    {p.model ? ` · ${p.model}` : ''}
                    {p.reason ? ` · ${p.reason}` : ''}
                  </span>
                </li>
              ))}
            </ul>
          </div>
          {h.notes.length > 0 && (
            <Notice tone="info" testId="health-notes">
              <ul className="list-disc pl-5">
                {h.notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </Notice>
          )}
        </div>
      )}
      {r && (
        <div className="mt-4" data-testid="rules-box">
          <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
            <ScrollText size={16} aria-hidden="true" /> Reglas de puntaje · {r.rulesVersion}
          </h3>
          <p className="font-mono text-xs">{r.formula}</p>
          <ul className="mt-1 space-y-0.5 text-sm">
            {Object.entries(r.rules).map(([k, v]) => (
              <li key={k}>
                <strong>{k}</strong> ({r.weights[k] ?? '—'}): {v}
              </li>
            ))}
          </ul>
          <p className="mt-1 text-xs text-ink-3">
            Bandas: {Object.entries(r.bands).map(([k, v]) => `${k} ${v}`).join(' · ')}. Desempate: urgencia y luego ID.
          </p>
          {r.changelog.map((c) => (
            <p key={c.version} className="mt-1 text-xs text-ink-3">
              {c.version} ({c.date}): {c.reason}
            </p>
          ))}
        </div>
      )}
    </Card>
  );
}

export function Sources() {
  const ref = useRef<HTMLDivElement>(null);
  const snapshot = useSnapshot();
  useEntrance(ref, 'fuentes', !snapshot.isLoading);
  return (
    <div ref={ref} data-testid="sources-view" className="space-y-4">
      <div data-motion="heading">
        <p className="kicker">Fuentes y evaluación</p>
        <h2 className="font-display text-2xl font-bold">Procedencia, calidad y métricas</h2>
        <p className="mt-1 text-sm text-ink-2">
          Todo lo que se muestra sale del snapshot servido y de ejecuciones reales. Si algo no se ejecutó, se indica «sin ejecutar» en lugar de inventar un valor.
        </p>
      </div>
      <SnapshotCard />
      <CatalogCard />
      <QualityCard />
      <MetricsCard />
      <SystemCard />
      <WorkspaceCard />
      <DesktopCard />
      <RulesEditor />
      <ConnectionsCard />
    </div>
  );
}
