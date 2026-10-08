import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  ArrowLeft,
  Bot,
  CalendarClock,
  ExternalLink,
  FilePlus2,
  GitCompare,
  Globe,
  Quote,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react';
import type { Claim, Contradiction, EvidenceArticle, IndicatorPoint, TopicDetail } from '../../lib/api/types';
import { useSetImpact, useTopic, useTopics } from '../../lib/hooks';
import { CATEGORY_LABEL, CLAIM_HELP, CLAIM_LABEL } from '../../lib/labels';
import { fmtDateTime, fmtNumber, fmtScore } from '../../lib/format';
import { ApiError, describeError } from '../../lib/api/client';
import { useEntrance } from '../../lib/useMotion';
import { useApp } from '../context';
import { BandPill, Button, Card, ErrorBox, EvidencePill, Field, KV, Loading, Notice, Pill, ReviewPill, SectionTitle, inputCls } from '../ui';
import { Checkbox, Disclosure, Select, Tooltip } from '../ui/controls';
import { ScoreBreakdown } from '../ScoreBreakdown';
import { TopicFlags } from './Agenda';

const GEO_LABEL: Record<string, string> = {
  panama: 'Panamá',
  regional: 'Regional',
  none: 'Sin relación geográfica',
  indeterminate: 'Indeterminada',
};

function Source({ a }: { a: EvidenceArticle }) {
  const basis =
    a.publishedAtBasis === 'rss_pubdate'
      ? 'según RSS'
      : a.publishedAtBasis === 'url_pattern'
        ? 'inferida del patrón de la URL'
        : a.publishedAtBasis === 'news_sitemap_publication'
          ? 'según sitemap de noticias'
          : 'sin base verificable';
  return (
    <li
      id={`src-${a.id}`}
      data-testid="source-item"
      data-evidence-id={a.id}
      className={`rounded-md border p-3 ${a.suspiciousInstructions ? 'border-bad/50 bg-bad-bg/40' : 'border-rule bg-card'}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="font-semibold leading-snug">
          {a.title}{' '}
          {/^https?:\/\//.test(a.url) && (
            <a
              href={a.url}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="inline-flex items-center gap-1 text-sm font-medium text-info underline underline-offset-2"
            >
              Abrir fuente <ExternalLink size={13} aria-hidden="true" />
              <span className="sr-only">(se abre en otra pestaña)</span>
            </a>
          )}
        </p>
        <div className="flex flex-wrap gap-1.5">
          {a.isTvn && <Pill tone="info">TVN</Pill>}
          {a.suspiciousInstructions && (
            <Pill tone="bad" icon={ShieldAlert} testId="source-untrusted-badge">
              Contenido no confiable (contiene instrucciones)
            </Pill>
          )}
          {a.dataOrigin === 'fixture' && <Pill tone="warn">fixture</Pill>}
        </div>
      </div>
      <dl className="mt-2 grid gap-x-6 gap-y-0.5 text-sm sm:grid-cols-2">
        <KV k="Medio:">{a.outlet}</KV>
        <KV k="Procedencia:">
          {a.originKnown ? a.origin : <span className="text-warn">origen desconocido ({a.originKey})</span>}
        </KV>
        <KV k="Publicada:">
          <span data-testid="source-published">{fmtDateTime(a.publishedAt, 'fecha de publicación desconocida')}</span>{' '}
          <span className="text-xs text-ink-3">({basis})</span>
        </KV>
        <KV k="Detectada:">
          <span data-testid="source-detected">{fmtDateTime(a.detectedAt, 'sin fecha de detección')}</span>
        </KV>
        <KV k="Extraída:">{fmtDateTime(a.extractedAt, 'sin fecha de extracción')}</KV>
        <KV k="Tema:">
          {CATEGORY_LABEL[a.category]}
          {a.categoryProbability !== null && ` (salida del modelo: ${Math.round(a.categoryProbability * 100)} %, ${a.classifier ?? 'clasificador'})`}
        </KV>
        <KV k="Geografía:">{GEO_LABEL[a.geoRelevance] ?? a.geoRelevance}</KV>
      </dl>
      <p className="mt-1 text-xs text-ink-3">Indicios geográficos en el contenido: {a.geoEvidence.length ? a.geoEvidence.join('; ') : 'sin indicios registrados'}.</p>
      <p className="mt-1.5 text-xs text-ink-3">Alcance del texto: {a.scopeText}. ID: {a.id}</p>
      {a.flags.length > 0 && <p className="mt-1 text-xs text-warn">Marcas: {a.flags.join(', ')}</p>}
    </li>
  );
}

function Indicator({ p }: { p: IndicatorPoint }) {
  return (
    <li
      data-testid="official-indicator"
      data-year={p.year}
      data-unit={p.unit ?? ''}
      data-country={p.countryIso3}
      data-evidence-id={p.id}
      className="rounded-md border border-rule bg-card p-3"
    >
      <p className="font-semibold">{p.indicatorName}</p>
      <p className="mt-0.5 flex flex-wrap items-baseline gap-x-3 text-sm">
        <span className="font-display text-2xl font-bold tabular-nums">{p.isMissing ? 'Sin dato' : fmtNumber(p.value, 2)}</span>
        <span className="text-ink-2">{p.unit ?? 'unidad no indicada'}</span>
        <span>
          <span className="text-ink-3">País:</span> {p.countryName ?? p.countryIso3} ({p.countryIso3})
        </span>
        <span>
          <span className="text-ink-3">Año:</span> {p.year}
        </span>
      </p>
      <p className="mt-1 flex items-start gap-1.5 text-sm text-warn">
        <CalendarClock size={14} className="mt-1 shrink-0" aria-hidden="true" />
        {p.note}
      </p>
      <p className="mt-1 text-xs text-ink-3">
        {p.license ? `Licencia: ${p.license}. ` : ''}
        {p.sourceUrl && /^https?:\/\//.test(p.sourceUrl) && (
          <a href={p.sourceUrl} target="_blank" rel="noopener noreferrer" className="underline">
            Fuente oficial
          </a>
        )}
        {p.dataOrigin === 'fixture' && ' · dato de fixture'}
      </p>
    </li>
  );
}

function ClaimItem({ c }: { c: Claim }) {
  return (
    <li data-testid="claim-item" data-claim-type={c.type} className="rounded-md border border-rule bg-card p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Pill tone={c.type === 'hecho' ? 'ok' : c.type === 'declaracion' ? 'info' : 'warn'} icon={Quote} title={CLAIM_HELP[c.type]}>
          {CLAIM_LABEL[c.type]}
        </Pill>
        <p className="min-w-0 flex-1">{c.text}</p>
      </div>
      <ul className="mt-2 flex flex-wrap gap-1.5 text-xs">
        {c.citations.map((ct, i) => (
          <li key={`${ct.evidenceId}-${ct.field}-${i}`}>
            {ct.passage ? (
              <Tooltip content={ct.passage}>
            <a
              href={`#src-${ct.evidenceId}`}
              data-testid="citation"
              data-evidence-id={ct.evidenceId}
              className="inline-flex items-center gap-1 rounded border border-rule-strong bg-paper px-1.5 py-0.5 font-mono text-[11px] text-ink-2 hover:border-amber-600"
              onClick={(e) => {
                const el = document.getElementById(`src-${ct.evidenceId}`);
                if (el) {
                  e.preventDefault();
                  el.scrollIntoView({ block: 'center' });
                  el.focus?.();
                }
              }}
            >
              {ct.evidenceId} · {ct.field}
            </a>
              </Tooltip>
            ) : (
            <a
              href={`#src-${ct.evidenceId}`}
              data-testid="citation"
              data-evidence-id={ct.evidenceId}
              className="inline-flex items-center gap-1 rounded border border-rule-strong bg-paper px-1.5 py-0.5 font-mono text-[11px] text-ink-2 hover:border-amber-600"
              onClick={(e) => {
                const el = document.getElementById(`src-${ct.evidenceId}`);
                if (el) {
                  e.preventDefault();
                  el.scrollIntoView({ block: 'center' });
                  el.focus?.();
                }
              }}
            >
              {ct.evidenceId} · {ct.field}
            </a>
            )}
          </li>
        ))}
        {c.citations.length === 0 && <li className="text-bad">Sin cita: no debe tratarse como respaldada.</li>}
      </ul>
    </li>
  );
}

function ContradictionItem({ k }: { k: Contradiction }) {
  return (
    <li data-testid="contradiction" data-contradiction-id={k.id} className="rounded-md border border-bad/50 bg-bad-bg/40 p-3">
      <p className="flex items-center gap-2 font-semibold text-bad">
        <GitCompare size={16} aria-hidden="true" /> {k.description}
      </p>
      <ul className="mt-2 grid gap-2 md:grid-cols-2">
        {k.versions.map((v) => (
          <li key={v.evidenceId} data-testid="contradiction-version" data-evidence-id={v.evidenceId} className="rounded border border-rule bg-card p-2 text-sm">
            <p className="italic">«{v.statement}»</p>
            <p className="mt-1 text-xs text-ink-3">
              {v.outlet} · {fmtDateTime(v.publishedAt)} · alcance: {v.scope}
            </p>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-sm">
        <strong>Verificación pendiente:</strong> {k.pendingVerification} <span className="text-ink-3">(estado: {k.status})</span>
      </p>
      <p className="text-xs text-ink-3">El sistema no elige una versión: la revisión humana decide.</p>
    </li>
  );
}

function ImpactForm({ d }: { d: TopicDetail }) {
  const { reviewer, setReviewer } = useApp();
  const m = useSetImpact(d.summary.id);
  const currentTopic = useTopic(d.summary.id);
  const [baseVersion, setBaseVersion] = useState(d.case.version);
  const [level, setLevel] = useState<'bajo' | 'medio' | 'alto'>(d.impact.level);
  const [justification, setJustification] = useState('');
  const [reason, setReason] = useState('');
  const [ids, setIds] = useState<string[]>(d.articles.slice(0, 1).map((a) => a.id));
  useEffect(() => { if (!justification && !reason) setBaseVersion(d.case.version); }, [d.case.version, justification, reason]);
  const tooShort = justification.trim().length < 20;
  return (
    <Disclosure
      testId="impact-form"
      className="rounded-md border border-rule bg-paper px-3"
      summary={<span className="text-sm font-semibold">Asignar impacto editorial (cambia el puntaje y queda versionado)</span>}
    >
      <form
        noValidate
        className="mb-3 mt-1 grid grid-cols-1 gap-3 sm:grid-cols-2 [&>*]:min-w-0"
        onSubmit={(e) => {
          e.preventDefault();
          m.mutate({
            expectedVersion: baseVersion,
            level,
            justification: justification.trim(),
            evidenceIds: ids,
            author: reviewer.trim(),
            reason: reason.trim(),
          }, { onSuccess: (updated) => setBaseVersion(updated.version) });
        }}
      >
        <Field label="Persona responsable" htmlFor="imp-author">
          <input id="imp-author" className={inputCls} value={reviewer} onChange={(e) => setReviewer(e.target.value)} aria-required="true" />
        </Field>
        <Field label="Nivel de impacto" htmlFor="imp-level">
          <Select<'bajo' | 'medio' | 'alto'>
            id="imp-level"
            testId="impact-level"
            value={level}
            onChange={setLevel}
            options={[
              { value: 'bajo', label: 'Bajo (0,25)' },
              { value: 'medio', label: 'Medio (0,5)' },
              { value: 'alto', label: 'Alto (1)' },
            ]}
          />
        </Field>
        <div className="sm:col-span-2">
          <Field label="Justificación con evidencia (mínimo 20 caracteres)" htmlFor="imp-just" hint={tooShort ? `${justification.trim().length}/20 caracteres` : undefined}>
            <textarea id="imp-just" rows={2} className={inputCls} value={justification} onChange={(e) => setJustification(e.target.value)} aria-required="true" />
          </Field>
        </div>
        <div className="sm:col-span-2">
          <Field label="Motivo del cambio" htmlFor="imp-reason">
            <input id="imp-reason" className={inputCls} value={reason} onChange={(e) => setReason(e.target.value)} aria-required="true" />
          </Field>
        </div>
        <fieldset className="sm:col-span-2">
          <legend className="text-sm font-semibold">Evidencia que lo respalda (al menos una)</legend>
          <div className="mt-1 flex flex-wrap gap-x-4">
            {d.articles.map((a) => (
              <Checkbox key={a.id} testId="impact-evidence" className="w-full sm:w-auto sm:max-w-sm" checked={ids.includes(a.id)} onChange={(on) => setIds(on ? [...ids, a.id] : ids.filter((x) => x !== a.id))}>
                <Tooltip block content={a.title}>
                  <span className="block truncate text-sm">{a.title}</span>
                </Tooltip>
              </Checkbox>
            ))}
          </div>
        </fieldset>
        <div className="sm:col-span-2">
          <Button type="submit" variant="primary" busy={m.isPending} disabled={tooShort || !reviewer.trim() || !reason.trim() || ids.length === 0} data-testid="impact-save">
            Guardar impacto
          </Button>
          {m.isSuccess && <span className="ml-3 text-sm text-ok" role="status">Impacto guardado; puntaje recalculado.</span>}
          {m.error && (
            <div className="mt-2">
              <Notice tone="bad" role="alert" title={m.error instanceof ApiError && m.error.isConflict ? 'Conflicto de versión: recarga la ficha' : 'No se guardó'}>
                {describeError(m.error)}
                {m.error instanceof ApiError && m.error.isConflict && <Button className="mt-2" onClick={async () => { const latest = await currentTopic.refetch(); if (latest.data) { setBaseVersion(latest.data.case.version); setLevel(latest.data.impact.level); setJustification(''); setReason(''); m.reset(); } }}>Recargar ficha (descartar cambios)</Button>}
              </Notice>
            </div>
          )}
        </div>
      </form>
    </Disclosure>
  );
}

function FichaBody({ d }: { d: TopicDetail }) {
  const { go, openAssistant } = useApp();
  const s = d.summary;
  const ref = useRef<HTMLElement>(null);
  // Se repite al cambiar de tema sin remontar la ficha, así que el formulario de impacto conserva sus ediciones.
  useEntrance(ref, `ficha:${s.id}`);
  return (
    <article ref={ref} data-testid="ficha" data-topic-id={s.id} className="space-y-6">
      <header data-motion="heading" className="comic-page-heading space-y-3">
        <button
          type="button"
          onClick={() => go({ view: 'agenda' })}
          className="comic-link -ml-1 gap-1 px-1 text-sm font-medium text-ink-2 underline-offset-2 hover:underline"
        >
          <ArrowLeft size={14} aria-hidden="true" /> Volver a la agenda
        </button>
        <p className="kicker">{CATEGORY_LABEL[s.category]} · ficha de evidencia</p>
        <h1 className="font-display text-3xl font-bold leading-tight sm:text-4xl">{s.title}</h1>
        <div className="flex flex-wrap items-center gap-1.5">
          <BandPill band={s.band} />
          <EvidencePill status={s.evidenceStatus} testId="topic-evidence-status" />
          <ReviewPill status={d.case.status} testId="ficha-review-status" />
          <TopicFlags t={s} />
        </div>
        <div className="comic-action-pair">
          <Button variant="primary" icon={FilePlus2} onClick={() => go({ view: 'borradores', topicId: s.id })} data-testid="go-drafts">
            Borradores y revisión
          </Button>
          <Button icon={Bot} onClick={() => openAssistant(`¿Qué falta verificar de «${s.title}»?`, s.id, s.title)}>
            Preguntar al asistente sobre este tema
          </Button>
        </div>
      </header>

      {d.warnings.length > 0 && (
        <div className="space-y-2" data-testid="ficha-warnings">
          {d.warnings.map((w) => (
            <Notice key={w} tone="warn">
              {w}
            </Notice>
          ))}
        </div>
      )}
      {s.needsInvestigation && (
        <Notice tone="amber" icon={ShieldAlert} title="Prioridad alta con evidencia insuficiente: requiere investigación" testId="ficha-needs-investigation">
          La prioridad ordena la atención; no habilita publicación. Resuelve las verificaciones pendientes antes de avanzar.
        </Notice>
      )}
      {s.headlineOnly && (
        <Notice tone="info" title="basado únicamente en titular/metadatos" testId="headline-only-notice">
          El sistema no leyó los artículos completos ni les atribuye detalles que no aparecen en el titular o los metadatos.
        </Notice>
      )}

      <Card aria-labelledby="h-reported">
        <SectionTitle id="h-reported" kicker="1 · Qué se reporta">
          Resumen y acción recomendada
        </SectionTitle>
        <p data-testid="ficha-reported" className="max-w-3xl text-base">
          {d.whatIsReported}
        </p>
        <p className="mt-3 flex gap-2 rounded-md bg-amber-50 px-3 py-2 text-sm" data-testid="ficha-recommended">
          <TriangleAlert size={16} className="mt-0.5 shrink-0 text-amber-600" aria-hidden="true" />
          <span>
            <strong>Acción recomendada:</strong> {d.recommendedAction}
          </span>
        </p>
      </Card>

      <Card aria-labelledby="h-evidence" data-testid="evidence-card">
        <SectionTitle id="h-evidence" kicker="2 · Estado de evidencia" aside={<EvidencePill status={d.evidence.status} testId="evidence-status" />}>
          ¿Hay evidencia suficiente para un borrador?
        </SectionTitle>
        <p className="mb-2 max-w-3xl">{d.evidence.rationale}</p>
        <dl className="grid gap-x-8 gap-y-0.5 text-sm sm:grid-cols-3">
          <KV k="Procedencias independientes:">{d.evidence.independentProvenances}</KV>
          <KV k="Fuente primaria enlazada:">{d.evidence.primarySourceLinked ? 'sí' : 'no'}</KV>
          <KV k="Contexto oficial enlazado:">{d.evidence.officialContextLinked ? 'sí (no confirma el hecho por sí solo)' : 'no'}</KV>
          <KV k="Confirmación del revisor:">
            {d.evidence.reviewerConfirmed ? `sí (${d.evidence.reviewerConfirmedBy ?? '—'})` : 'pendiente'}
          </KV>
        </dl>
        {d.evidence.gaps.length > 0 && (
          <div className="mt-3">
            <p className="text-sm font-semibold">Vacíos detectados</p>
            <ul data-testid="evidence-gaps" className="mt-1 list-disc space-y-0.5 pl-5 text-sm">
              {d.evidence.gaps.map((g) => (
                <li key={g.code} data-code={g.code}>
                  {g.message}
                </li>
              ))}
            </ul>
          </div>
        )}
        <p className="mt-2 text-xs text-ink-3">El sistema detecta vacíos; la suficiencia final la confirma la persona revisora.</p>
      </Card>

      <Card aria-labelledby="h-score">
        <SectionTitle
          id="h-score"
          kicker={`3 · Puntaje de atención · ${d.score.rulesVersion}`}
          aside={
            <p className="flex items-baseline gap-1">
              <span className="font-display text-4xl font-bold tabular-nums" data-testid="ficha-score">
                {fmtScore(d.score.total)}
              </span>
              <span className="text-xs text-ink-3">/ 100</span>
            </p>
          }
        >
          Cómo se calculó
        </SectionTitle>
        <p className="mb-3 text-sm text-ink-2">
          <code className="rounded bg-sunk px-1.5 py-0.5 font-mono text-xs">{d.score.formula}</code> · desempate: urgencia ({fmtNumber(d.score.urgencyTiebreak, 2)}) y luego ID ({d.score.idTiebreak}).
        </p>
        <ScoreBreakdown components={d.score.components} variant="full" testIdPrefix="score-component" />
        <Notice tone="neutral" icon={ShieldCheck}>
          {d.score.disclaimer}
        </Notice>
        <div className="mt-3 space-y-3 text-sm">
          <p data-testid="impact-summary">
            <strong>Impacto:</strong> {d.impact.level} ·{' '}
            {d.impact.origin === 'asignacion_editorial' ? (
              <>asignación editorial por {d.impact.author ?? '—'} ({fmtDateTime(d.impact.at)}): {d.impact.justification}</>
            ) : (
              <span className="text-warn">propuesta automática pendiente de confirmación editorial. {d.impact.justification}</span>
            )}
          </p>
          <ImpactForm d={d} />
        </div>
      </Card>

      <Card aria-labelledby="h-reporters">
        <SectionTitle id="h-reporters" kicker="4 · Quién lo reporta">
          Medios y procedencias
        </SectionTitle>
        <p className="mb-2 text-sm text-ink-2">Una agencia replicada cuenta como una sola procedencia: repetir no es corroborar.</p>
        <ul className="grid gap-2 sm:grid-cols-2" data-testid="reporters">
          {d.reporters.map((r) => (
            <li key={`${r.outlet}-${r.origin}`} className="rounded border border-rule bg-paper px-3 py-2 text-sm" data-testid="reporter">
              <strong>{r.outlet}</strong> · {r.role === 'original' ? 'cobertura original' : r.role === 'replica' ? 'réplica' : r.role}
              <br />
              <span className="text-xs text-ink-3">
                Procedencia: {r.originKnown ? r.origin : `desconocida (${r.origin})`} · {r.evidenceIds.length} documento{r.evidenceIds.length === 1 ? '' : 's'}
              </span>
            </li>
          ))}
        </ul>
      </Card>

      <Card aria-labelledby="h-articles">
        <SectionTitle id="h-articles" kicker="5 · Noticias agrupadas" aside={<span className="text-sm text-ink-3">{d.articles.length} documento(s)</span>}>
          Procedencia y fechas (hora de Panamá)
        </SectionTitle>
        <ul data-testid="ficha-articles" className="space-y-2">
          {d.articles.map((a) => (
            <Source key={a.id} a={a} />
          ))}
        </ul>
      </Card>

      <Card aria-labelledby="h-official">
        <SectionTitle id="h-official" kicker="6 · Contexto oficial">
          Indicadores relacionados
        </SectionTitle>
        <p className="mb-2 text-sm text-ink-2">{d.officialContext.relationRationale}</p>
        {d.officialContext.indicators.length > 0 ? (
          <ul className="grid gap-2 md:grid-cols-2" data-testid="official-context">
            {d.officialContext.indicators.map((p) => (
              <Indicator key={p.id} p={p} />
            ))}
          </ul>
        ) : (
          <Notice tone="neutral" icon={Globe} testId="official-empty">
            Sin indicador oficial relacionado con sustento. No se fuerza una relación.
          </Notice>
        )}
        {d.officialContext.limitations.length > 0 && (
          <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm text-warn">
            {d.officialContext.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        )}
      </Card>

      <Card aria-labelledby="h-claims">
        <SectionTitle id="h-claims" kicker="7 · Afirmaciones respaldadas">
          Qué está sustentado y con qué cita
        </SectionTitle>
        {d.supportedClaims.length ? (
          <ul data-testid="supported-claims" className="space-y-2">
            {d.supportedClaims.map((c) => (
              <ClaimItem key={c.id} c={c} />
            ))}
          </ul>
        ) : (
          <Notice tone="neutral" testId="claims-empty">
            Aún no hay afirmaciones respaldadas por la evidencia disponible.
          </Notice>
        )}
        <p className="mt-2 text-xs text-ink-3">Una cita estructuralmente válida no prueba sustento: lo comprueba la revisión humana.</p>
      </Card>

      <Card aria-labelledby="h-contra">
        <SectionTitle id="h-contra" kicker="8 · Contradicciones">
          Versiones incompatibles
        </SectionTitle>
        {d.contradictions.length ? (
          <ul data-testid="contradictions" className="space-y-3">
            {d.contradictions.map((k) => (
              <ContradictionItem key={k.id} k={k} />
            ))}
          </ul>
        ) : (
          <p className="text-sm text-ink-2" data-testid="contradictions-none">
            No se detectaron contradicciones entre las fuentes de este tema.
          </p>
        )}
      </Card>

      <Card aria-labelledby="h-pending">
        <SectionTitle id="h-pending" kicker="9 · Verificaciones pendientes">
          Qué falta comprobar
        </SectionTitle>
        {d.pendingVerifications.length ? (
          <ul data-testid="pending-verifications" className="list-none space-y-1.5">
            {d.pendingVerifications.map((v) => (
              <li key={v} data-testid="pending-verification" className="flex gap-2 text-sm">
                <TriangleAlert size={16} className="mt-0.5 shrink-0 text-amber-600" aria-hidden="true" />
                {v}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-ink-2">Sin verificaciones pendientes registradas.</p>
        )}
      </Card>
      <p className="text-xs text-ink-3">
        Snapshot {d.snapshotId} · reglas {d.rulesVersion} · modo de datos: {d.dataMode}.
      </p>
    </article>
  );
}

function Picker(): ReactNode {
  const { go } = useApp();
  const { data, isLoading, error, refetch } = useTopics({ limit: 50 });
  const ref = useRef<HTMLDivElement>(null);
  useEntrance(ref, 'ficha', Boolean(data));
  return (
    <div ref={ref} className="space-y-3" data-testid="ficha-picker">
      <h1 data-motion="heading" className="font-display text-3xl font-bold">Ficha de evidencia</h1>
      <p className="text-ink-2">Elige un tema de la agenda para abrir su ficha.</p>
      {isLoading && <Loading />}
      {error && <ErrorBox error={error} onRetry={() => refetch()} />}
      <ul className="space-y-2">
        {data?.items.map((t) => (
          <li key={t.id} data-motion="card">
            <button type="button" className="w-full rounded-md border border-rule bg-card p-3 text-left hover:border-amber-600" onClick={() => go({ view: 'ficha', topicId: t.id })}>
              <span className="font-semibold">{t.title}</span>
              <span className="ml-2 text-sm text-ink-3">{fmtScore(t.score)} pts</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Ficha() {
  const { route } = useApp();
  const topicId = route.view === 'ficha' ? route.topicId : null;
  const { data, error, isLoading, refetch } = useTopic(topicId);
  if (!topicId) return <Picker />;
  if (isLoading) return <Loading label="Cargando ficha…" />;
  if (error) return <ErrorBox error={error} onRetry={() => refetch()} />;
  return data ? <FichaBody d={data} /> : null;
}
