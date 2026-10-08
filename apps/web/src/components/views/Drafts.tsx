import { SavedCases } from '../Workspace';
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  BadgeCheck,
  CircleAlert,
  CircleCheck,
  CircleX,
  ClipboardCopy,
  FileDown,
  FilePenLine,
  Link2,
  Newspaper,
  RefreshCw,
  Save,
  ShieldAlert,
  Sparkles,
} from 'lucide-react';
import type {
  CaseView,
  ClaimInput,
  ClaimType,
  DraftProviderChoice,
  DraftRecord,
  ReviewStatus,
  TopicDetail,
} from '../../lib/api/types';
import { ApiError, describeError } from '../../lib/api/client';
import { useCreateDraft, useHealth, useReview, useSaveDraft, useTopic, useTopics } from '../../lib/hooks';
import { CLAIM_HELP, CLAIM_LABEL, FALLBACK_LABEL, PROVIDER_CHOICES, REVIEW_LABEL } from '../../lib/labels';
import { fmtDateTime, fmtNumber, pct } from '../../lib/format';
import { useEntrance } from '../../lib/useMotion';
import { useApp } from '../context';
import {
  Button,
  Card,
  ErrorBox,
  EvidencePill,
  Field,
  GenerationPill,
  Loading,
  Notice,
  Pill,
  ReviewPill,
  SectionTitle,
  inputCls,
} from '../ui';
import { Modal, Select, Tooltip } from '../ui/controls';
import { ConnectionsCard } from '../EditorialSettings';

// Límites del plan (PLAN §3): brief ≤250, copy ≤80, guion 45–60 s a ~2,5 palabras/s, 3 preguntas.
const BRIEF_MAX = 250;
const COPY_MAX = 80;
const WPS = 2.5;
const SCRIPT_MIN_S = 45;
const SCRIPT_MAX_S = 60;

const WORD_RE = /[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ%]+(?:[.,'’-][0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)*/g;
const stripMarkers = (t: string) => t.replace(/\s*\[c\d+\]/g, '');
export function wordCount(t: string): number {
  return (stripMarkers(t).match(WORD_RE) ?? []).length;
}

const TRANSITION_LABEL: Record<ReviewStatus, string> = {
  nuevo: 'Volver a nuevo',
  en_revision: 'Poner en revisión',
  requiere_evidencia: 'Marcar «requiere evidencia»',
  aprobado_como_borrador: 'Aprobar como borrador',
  descartado: 'Descartar',
};
const NEEDS_COMMENT: ReviewStatus[] = ['requiere_evidencia', 'descartado'];

const CLAIM_TONE: Record<ClaimType, 'ok' | 'info' | 'warn' | 'neutral'> = {
  hecho: 'ok',
  declaracion: 'info',
  inferencia: 'warn',
  hipotesis: 'neutral',
};

function Counter({ n, max, min, unit = 'palabras', testId }: { n: number; max?: number; min?: number; unit?: string; testId?: string }) {
  const over = max !== undefined && n > max;
  const under = min !== undefined && n < min;
  const bad = over || under;
  const Ico = bad ? CircleX : CircleCheck;
  return (
    <p data-testid={testId} data-ok={!bad} className={`mt-1 flex items-center gap-1.5 text-xs ${bad ? 'font-semibold text-bad' : 'text-ink-3'}`}>
      <Ico size={14} aria-hidden="true" />
      {n} {unit}
      {max !== undefined && min === undefined && ` (máximo ${max})`}
      {min !== undefined && max !== undefined && ` (rango ${min}–${max})`}
      {over && ' · excede el límite'}
      {under && ' · por debajo del mínimo'}
    </p>
  );
}

// --------------------------------------------------------------------------- citas

function evidenceLabel(detail: TopicDetail, id: string): { label: string; url: string | null; kind: 'articulo' | 'indicador' | 'desconocida' } {
  const a = detail.articles.find((x) => x.id === id);
  if (a) return { label: `${a.outlet}: «${a.suspiciousInstructions ? '[texto con instrucciones omitido]' : a.title}»`, url: a.url, kind: 'articulo' };
  const p = detail.officialContext.indicators.find((x) => x.id === id);
  if (p) return { label: `Banco Mundial · ${p.indicatorName} · ${p.countryIso3} ${p.year}`, url: p.sourceUrl ?? null, kind: 'indicador' };
  return { label: 'Evidencia no encontrada en esta ficha', url: null, kind: 'desconocida' };
}

function ClaimItem({
  claim,
  detail,
  value,
  onText,
  rejected,
}: {
  claim: ClaimInput;
  detail: TopicDetail;
  value: string;
  onText: (t: string) => void;
  rejected: boolean;
}) {
  const id = useId();
  const factual = claim.type === 'hecho' || claim.type === 'declaracion';
  const cites = claim.citations ?? [];
  const missingCite = factual && cites.length === 0;
  return (
    <li
      data-testid="draft-claim"
      data-claim-id={claim.id}
      data-claim-type={claim.type}
      className="rounded-md border border-rule bg-card p-3"
    >
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-ink-3">[{claim.id}]</span>
        <Pill tone={CLAIM_TONE[claim.type]} testId="draft-claim-type">
          {CLAIM_LABEL[claim.type]}
        </Pill>
        <span className="text-xs text-ink-3">{CLAIM_HELP[claim.type]}</span>
        {rejected && (
          <Pill tone="bad" icon={CircleX}>
            Rechazada por validación
          </Pill>
        )}
        {missingCite && (
          <Pill tone="bad" icon={CircleAlert}>
            Sin cita
          </Pill>
        )}
      </div>
      <label htmlFor={id} className="sr-only">
        Texto de la afirmación {claim.id}
      </label>
      <textarea id={id} rows={2} className={inputCls} value={value} onChange={(e) => onText(e.target.value)} />
      <ul className="mt-2 space-y-1 text-xs text-ink-2" aria-label={`Citas de la afirmación ${claim.id}`}>
        {cites.map((c, i) => {
          const ev = evidenceLabel(detail, c.evidenceId);
          return (
            <li key={`${c.evidenceId}-${c.field}-${i}`} data-testid="draft-claim-citation" data-evidence-id={c.evidenceId} data-field={c.field} className="flex gap-1.5">
              <Link2 size={14} className="mt-0.5 shrink-0 text-ink-3" aria-hidden="true" />
              <span>
                <span className="font-mono">{c.evidenceId}</span> · campo <strong>{c.field}</strong>
                {c.passage ? <> · pasaje «{c.passage}»</> : null}
                <span className="block text-ink-3">
                  {ev.url ? (
                    <a className="underline underline-offset-2 hover:text-amber-700" href={ev.url} target="_blank" rel="noreferrer noopener">
                      {ev.label}
                    </a>
                  ) : (
                    ev.label
                  )}
                </span>
              </span>
            </li>
          );
        })}
        {cites.length === 0 && <li className="text-ink-3">{factual ? 'Sin citas: este tipo de afirmación las exige.' : 'Sin citas (no respaldada: se presenta como conjetura).'}</li>}
      </ul>
    </li>
  );
}

// --------------------------------------------------------------------------- validación

function ValidationPanel({ d, live }: { d: DraftRecord; live: { brief: number; script: number; copy: number; questions: number } }) {
  const v = d.validation;
  const secs = live.script / WPS;
  const errors = v.issues.filter((i) => i.severity === 'error');
  const warnings = v.issues.filter((i) => i.severity !== 'error');
  const factual = v.factualCitationCoverage;
  return (
    <Card data-testid="draft-validation" data-ok={v.ok} aria-labelledby="validation-title">
      <SectionTitle
        id="validation-title"
        kicker="Controles automáticos"
        aside={
          <Pill tone={v.ok ? 'ok' : 'bad'} icon={v.ok ? CircleCheck : CircleX} testId="draft-validation-status">
            {v.ok ? 'Validación correcta' : 'Validación con errores'}
          </Pill>
        }
      >
        Validación del borrador
      </SectionTitle>
      <dl className="grid gap-2 text-sm sm:grid-cols-2">
        <div data-testid="draft-factual-coverage" data-value={factual ?? ''}>
          <dt className="text-ink-3">Cobertura de citas en afirmaciones factuales (hecho + declaración)</dt>
          <dd className="font-semibold">{factual === null ? 'Sin afirmaciones factuales' : pct(factual)}</dd>
        </div>
        <div data-testid="draft-citation-coverage">
          <dt className="text-ink-3">Cobertura de citas en todas las afirmaciones</dt>
          <dd className="font-semibold">{pct(v.citationCoverage)}</dd>
        </div>
        <div>
          <dt className="text-ink-3">Brief / copy (en edición)</dt>
          <dd className="font-semibold">
            {live.brief} / {BRIEF_MAX} · {live.copy} / {COPY_MAX} palabras
          </dd>
        </div>
        <div>
          <dt className="text-ink-3">Guion estimado (en edición)</dt>
          <dd className="font-semibold">
            ≈{fmtNumber(secs, 0)} s ({live.script} palabras; guardado: ≈{fmtNumber(v.scriptSecondsEstimate, 0)} s)
          </dd>
        </div>
        <div>
          <dt className="text-ink-3">Preguntas de investigación</dt>
          <dd className="font-semibold">{live.questions} de 3</dd>
        </div>
      </dl>
      {errors.length > 0 && (
        <ul className="mt-3 space-y-1" data-testid="draft-validation-errors" role="alert">
          {errors.map((i, k) => (
            <li key={k} className="flex gap-2 text-sm text-bad">
              <CircleX size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
              <span>
                <span className="font-mono text-xs">{i.code}</span> · {i.message}
              </span>
            </li>
          ))}
        </ul>
      )}
      {warnings.length > 0 && (
        <ul className="mt-2 space-y-1" data-testid="draft-validation-warnings">
          {warnings.map((i, k) => (
            <li key={k} className="flex gap-2 text-sm text-warn">
              <CircleAlert size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
              <span>
                <span className="font-mono text-xs">{i.code}</span> · {i.message}
              </span>
            </li>
          ))}
        </ul>
      )}
      {v.rejectedClaimIds.length > 0 && (
        <p className="mt-2 text-sm text-bad">Afirmaciones rechazadas (no se muestran como respaldadas): {v.rejectedClaimIds.join(', ')}.</p>
      )}
      <p className="mt-3 text-xs text-ink-3">{v.note}</p>
    </Card>
  );
}

// --------------------------------------------------------------------------- editor

type Form = {
  title: string;
  angle: string;
  brief: string;
  script: string;
  copy: string;
  questions: string[];
  pending: string;
  claims: ClaimInput[];
};

function formFrom(d: DraftRecord): Form {
  const p = d.package;
  const qs = [...p.researchQuestions];
  while (qs.length < 3) qs.push('');
  return {
    title: p.proposedTitle,
    angle: p.publicInterestAngle,
    brief: p.brief,
    script: p.script,
    copy: p.socialCopy,
    questions: qs.slice(0, 3),
    pending: p.pendingVerifications.join('\n'),
    claims: p.claims.map((c) => ({ id: c.id, type: c.type, text: c.text, citations: c.citations.map((x) => ({ evidenceId: x.evidenceId, field: x.field, passage: x.passage })) })),
  };
}

function ReloadCase({ topicId, onReload }: { topicId: string; onReload?: (detail: TopicDetail) => void }) {
  const qc = useQueryClient();
  const { api } = useApp();
  return <Button className="mt-2" icon={RefreshCw} data-testid="reload-case" onClick={async () => {
    await Promise.all([qc.invalidateQueries({ queryKey: ['topic', topicId] }), qc.invalidateQueries({ queryKey: ['topics'] })]);
    const current = qc.getQueryData<TopicDetail>(['topic', topicId, api.kind]);
    if (current) onReload?.(current);
  }}>Recargar caso{onReload ? ' (descartar mis cambios)' : ''}</Button>;
}

function DraftEditor({ detail, draft, caseView, reviewer }: { detail: TopicDetail; draft: DraftRecord; caseView: CaseView; reviewer: string }) {
  const [baseDraft, setBaseDraft] = useState(draft);
  const [baseVersion, setBaseVersion] = useState(caseView.version);
  const [form, setForm] = useState<Form>(() => formFrom(draft));
  const baseline = useMemo(() => JSON.stringify(formFrom(baseDraft)), [baseDraft]);
  const dirty = JSON.stringify(form) !== baseline;
  const save = useSaveDraft(detail.summary.id, caseView.caseId);
  // Conservar la versión leída impide que una actualización de otra pestaña borre una edición pendiente.
  // Conservar el aviso desde el dato persistido evita perder la confirmación de guardado.
  const [savedAt, setSavedAt] = useState<string | null>(draft.editedAt);
  const idT = useId();
  const idA = useId();
  const idB = useId();
  const idS = useId();
  const idC = useId();
  const idP = useId();
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => ({ ...f, [k]: v }));
  const live = { brief: wordCount(form.brief), script: wordCount(form.script), copy: wordCount(form.copy), questions: form.questions.filter((q) => q.trim()).length };
  const conflict = save.error instanceof ApiError && save.error.isConflict ? save.error : null;
  const rejected = new Set(baseDraft.validation.rejectedClaimIds);

  useEffect(() => {
    if (caseView.version <= baseVersion || dirty) return;
    setBaseDraft(draft); setBaseVersion(caseView.version); setForm(formFrom(draft)); setSavedAt(draft.editedAt);
  }, [caseView.version, baseVersion, dirty, draft]);

  const onSave = () => {
    setSavedAt(null);
    save.mutate(
      {
        expectedVersion: baseVersion,
        editor: reviewer.trim() || 'sin nombre',
        proposedTitle: form.title,
        publicInterestAngle: form.angle,
        brief: form.brief,
        script: form.script,
        socialCopy: form.copy,
        researchQuestions: form.questions.map((q) => q.trim()).filter(Boolean),
        pendingVerifications: form.pending.split('\n').map((l) => l.trim()).filter(Boolean),
        claims: form.claims,
      },
      { onSuccess: (updated) => { if (updated.currentDraft) { setBaseDraft(updated.currentDraft); setBaseVersion(updated.version); setForm(formFrom(updated.currentDraft)); } setSavedAt(new Date().toISOString()); } },
    );
  };

  return (
    <div className="space-y-4" data-testid="draft-editor">
      {dirty && caseView.version > baseVersion && <Notice tone="warn" title="Otra pestaña actualizó este caso" testId="draft-concurrent-change">
        Tu edición permanece sobre la versión {baseVersion}; la vigente es {caseView.version}. Guarda para comprobar el conflicto o copia tus cambios antes de recargar.
        <ReloadCase topicId={detail.summary.id} onReload={(current) => { if (current.case.currentDraft) { setBaseDraft(current.case.currentDraft); setBaseVersion(current.case.version); setForm(formFrom(current.case.currentDraft)); save.reset(); } }} />
      </Notice>}

      <Card aria-labelledby="editor-title">
        <SectionTitle
          id="editor-title"
          kicker="Edición humana"
          aside={
            dirty ? (
              <Pill tone="warn" icon={FilePenLine} testId="draft-dirty">
                Cambios sin guardar
              </Pill>
            ) : (
              <Pill tone="neutral" icon={CircleCheck}>
                Sin cambios pendientes
              </Pill>
            )
          }
        >
          Paquete editorial
        </SectionTitle>
        <div className="space-y-4">
          <Field label="Título propuesto" htmlFor={idT}>
            <input id={idT} data-testid="draft-title" className={inputCls} value={form.title} maxLength={160} onChange={(e) => set('title', e.target.value)} />
          </Field>
          <Field label="Enfoque de interés público" htmlFor={idA}>
            <textarea id={idA} data-testid="draft-angle" rows={2} className={inputCls} value={form.angle} onChange={(e) => set('angle', e.target.value)} />
          </Field>
          <Field label="Brief (máximo 250 palabras; los marcadores [c1] remiten a las afirmaciones)" htmlFor={idB}>
            <textarea id={idB} data-testid="draft-brief" rows={8} className={inputCls} value={form.brief} onChange={(e) => set('brief', e.target.value)} />
            <Counter n={live.brief} max={BRIEF_MAX} testId="draft-brief-count" />
          </Field>
          <fieldset>
            <legend className="mb-1 text-sm font-semibold">Tres preguntas de investigación</legend>
            <div className="space-y-2">
              {form.questions.map((q, i) => (
                <input
                  key={i}
                  data-testid="draft-question"
                  aria-label={`Pregunta de investigación ${i + 1}`}
                  className={inputCls}
                  value={q}
                  onChange={(e) => set('questions', form.questions.map((x, j) => (j === i ? e.target.value : x)))}
                />
              ))}
            </div>
            <Counter n={live.questions} min={3} max={3} unit="preguntas" />
          </fieldset>
          <Field label="Verificaciones pendientes (una por línea)" htmlFor={idP}>
            <textarea id={idP} data-testid="draft-pending" rows={4} className={inputCls} value={form.pending} onChange={(e) => set('pending', e.target.value)} />
          </Field>
          <Field label="Guion estimado (45–60 s)" htmlFor={idS}>
            <textarea id={idS} data-testid="draft-script" rows={7} className={inputCls} value={form.script} onChange={(e) => set('script', e.target.value)} />
            <Counter n={Math.round(live.script / WPS)} min={SCRIPT_MIN_S} max={SCRIPT_MAX_S} unit={`s estimados (${live.script} palabras)`} testId="draft-script-count" />
          </Field>
          <Field label="Copy digital (máximo 80 palabras)" htmlFor={idC}>
            <textarea id={idC} data-testid="draft-copy" rows={3} className={inputCls} value={form.copy} onChange={(e) => set('copy', e.target.value)} />
            <Counter n={live.copy} max={COPY_MAX} testId="draft-copy-count" />
          </Field>
        </div>
      </Card>

      <Card aria-labelledby="claims-title">
        <SectionTitle id="claims-title" kicker="Trazabilidad" aside={<span className="text-xs text-ink-3">{form.claims.length} afirmaciones</span>}>
          Afirmaciones y citas
        </SectionTitle>
        <p className="mb-3 text-sm text-ink-2">
          Cada afirmación está tipada (hecho, declaración, inferencia o hipótesis) y cita el ID y el campo que la respaldan. Una cita estructuralmente válida
          no prueba sustento: la revisión humana lo confirma.
        </p>
        <ul className="space-y-3">
          {form.claims.map((c, i) => (
            <ClaimItem
              key={c.id}
              claim={c}
              detail={detail}
              value={c.text}
              rejected={rejected.has(c.id)}
              onText={(t) => set('claims', form.claims.map((x, j) => (j === i ? { ...x, text: t } : x)))}
            />
          ))}
        </ul>
      </Card>

      <ValidationPanel d={baseDraft} live={live} />

      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" icon={Save} data-testid="draft-save" busy={save.isPending} disabled={!dirty} onClick={onSave}>
          Guardar edición
        </Button>
        <span className="text-xs text-ink-3">
          Se guarda como «{reviewer.trim() || 'sin nombre'}» sobre la versión {baseVersion} del caso. Al guardar se vuelve a validar.
        </span>
      </div>
      <div aria-live="polite">
        {savedAt && !save.isPending && !save.error && (
          <Notice tone="ok" title="Edición guardada" testId="draft-saved" stamp>
            {fmtDateTime(savedAt)}. Se volvió a validar el borrador; revisa el panel de validación.
          </Notice>
        )}
      </div>
      {conflict && (
        <Notice tone="bad" title="Conflicto de versión: el caso cambió" testId="draft-conflict" role="alert">
          Otra persona (u otra pestaña) modificó el caso: esperabas la versión {baseVersion}
          {conflict.currentVersion !== null ? ` y la actual es la ${conflict.currentVersion}` : ''}. Tus ediciones siguen aquí sin guardar; copia lo que necesites,
          recarga el caso y vuelve a aplicarlas.
          <br />
          <ReloadCase topicId={detail.summary.id} onReload={(current) => { if (current.case.currentDraft) { setBaseDraft(current.case.currentDraft); setBaseVersion(current.case.version); setForm(formFrom(current.case.currentDraft)); save.reset(); } }} />
        </Notice>
      )}
      {save.error && !conflict && <ErrorBox error={save.error} testId="draft-save-error" />}
    </div>
  );
}

// --------------------------------------------------------------------------- revisión

function ReviewPanel({ detail, caseView }: { detail: TopicDetail; caseView: CaseView }) {
  const { reviewer, setReviewer } = useApp();
  const review = useReview(detail.summary.id, caseView.caseId);
  const [baseVersion, setBaseVersion] = useState(caseView.version);
  const [comment, setComment] = useState('');
  const [confirm, setConfirm] = useState<'unset' | 'yes' | 'no'>('unset');
  const [primary, setPrimary] = useState<'unset' | 'yes' | 'no'>('unset');
  const idR = useId();
  const idC = useId();
  const idE = useId();
  const idP = useId();
  const conflict = review.error instanceof ApiError && review.error.isConflict ? review.error : null;
  const sys = detail.evidence.status;
  const draft = caseView.currentDraft;

  useEffect(() => { if (!comment && confirm === 'unset' && primary === 'unset') setBaseVersion(caseView.version); }, [caseView.version, comment, confirm, primary]);

  const run = (to: ReviewStatus) =>
    review.mutate(
      {
        expectedVersion: baseVersion,
        status: to,
        reviewer: reviewer.trim(),
        comment: comment.trim() || null,
        evidenceConfirmed: confirm === 'unset' ? null : confirm === 'yes',
        primarySourceConfirmed: primary === 'unset' ? null : primary === 'yes',
      },
      { onSuccess: (updated) => { setComment(''); setBaseVersion(updated.version); } },
    );

  const blockedReason = (to: ReviewStatus): string | null => {
    if (!reviewer.trim()) return 'Indica la persona responsable.';
    if (primary === 'yes' && !comment.trim()) return 'Identifica la fuente primaria y el hecho respaldado en el comentario.';
    if (NEEDS_COMMENT.includes(to) && !comment.trim()) return 'Este estado requiere un comentario.';
    if (to === 'aprobado_como_borrador') {
      if (!draft) return 'No hay borrador que aprobar.';
      if (!draft.validation.ok) return 'El borrador tiene errores de validación.';
      if (sys === 'insuficiente' && !(confirm === 'yes' && comment.trim())) return 'Evidencia insuficiente: confirma la suficiencia y comenta.';
    }
    return null;
  };

  return (
    <Card aria-labelledby="review-title" data-testid="review-panel">
      <SectionTitle id="review-title" kicker="Control humano" aside={
          <span data-testid="review-status" data-status={caseView.status} data-version={caseView.version}>
            <ReviewPill status={caseView.status} />
          </span>
        }
      >
        Revisión del caso
      </SectionTitle>
      <p className="mb-3 text-sm text-ink-2">
        Versión del caso: <strong data-testid="case-version">{caseView.version}</strong>
        {caseView.reviewer ? <> · última persona responsable: <strong>{caseView.reviewer}</strong></> : null}. Aprobar como borrador <strong>no equivale a publicar</strong>.
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Persona responsable" htmlFor={idR} hint="Queda registrada en el historial.">
          <input id={idR} data-testid="review-reviewer" className={inputCls} value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="Nombre y apellido" autoComplete="name" />
        </Field>
        <Field label="Suficiencia de evidencia (confirmación del revisor)" htmlFor={idE} hint={`El sistema indica: ${sys}. Tú confirmas o no.`}>
          <Select<'unset' | 'yes' | 'no'>
            id={idE}
            testId="review-evidence-confirmed"
            value={confirm}
            onChange={setConfirm}
            options={[
              { value: 'unset', label: `Sin cambios${caseView.evidenceConfirmed !== null ? ` (actual: ${caseView.evidenceConfirmed ? 'confirmada' : 'no confirmada'})` : ''}` },
              { value: 'yes', label: 'Confirmo que es suficiente para el borrador' },
              { value: 'no', label: 'No es suficiente' },
            ]}
          />
        </Field>
      </div>
      <div className="mt-3">
        <Field label="Fuente primaria pertinente (confirmación del revisor)" htmlFor={idP} hint="Para E = 1, identifica en el comentario la fuente primaria y el hecho que respalda. Un indicador anual de contexto no basta.">
          <Select<'unset' | 'yes' | 'no'>
            id={idP}
            testId="review-primary-source"
            value={primary}
            onChange={setPrimary}
            options={[
              { value: 'unset', label: `Sin cambios${caseView.primarySourceConfirmed !== null ? ` (actual: ${caseView.primarySourceConfirmed ? 'confirmada' : 'no confirmada'})` : ''}` },
              { value: 'yes', label: 'Confirmo una fuente primaria pertinente' },
              { value: 'no', label: 'No hay fuente primaria pertinente' },
            ]}
          />
        </Field>
      </div>
      <div className="mt-3">
        <Field label="Comentario (obligatorio al descartar o pedir evidencia)" htmlFor={idC}>
          <textarea id={idC} data-testid="review-comment" rows={3} className={inputCls} value={comment} maxLength={2000} onChange={(e) => setComment(e.target.value)} />
        </Field>
      </div>
      <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Transiciones permitidas">
        {caseView.allowedTransitions.map((to) => {
          const why = blockedReason(to);
          const action = (
            <Button
              key={to}
              data-testid={`review-action-${to}`}
              variant={to === 'descartado' ? 'danger' : to === 'aprobado_como_borrador' ? 'primary' : 'secondary'}
              icon={to === 'aprobado_como_borrador' ? BadgeCheck : undefined}
              busy={review.isPending && review.variables?.status === to}
              disabled={review.isPending || why !== null}
              className={why !== null ? 'pointer-events-none' : ''}
              onClick={() => run(to)}
            >
              {TRANSITION_LABEL[to]}
            </Button>
          );
          return why !== null ? (
            <Tooltip key={to} content={why}>
              {action}
            </Tooltip>
          ) : (
            action
          );
        })}
      </div>
      {caseView.allowedTransitions.length > 0 && (
        <p className="mt-2 text-xs text-ink-3">
          Estado actual: {REVIEW_LABEL[caseView.status]}. Pasos permitidos: {caseView.allowedTransitions.map((t) => REVIEW_LABEL[t]).join(', ')}. Los botones desactivados explican el motivo al pasar el cursor.
        </p>
      )}
      <div aria-live="polite" className="mt-3 space-y-2">
        {conflict && (
          <Notice tone="bad" title="Conflicto de versión: no se guardó la revisión" testId="review-conflict" role="alert">
            Esperabas la versión {caseView.version}
            {conflict.currentVersion !== null ? ` pero la actual es la ${conflict.currentVersion}` : ''}: otra revisión se guardó antes. Recarga el caso para ver su estado y repite tu
            decisión si aún aplica; no se sobrescribió nada. El texto del comentario se conserva.
            <br />
            <ReloadCase topicId={detail.summary.id} onReload={(current) => { setBaseVersion(current.case.version); setComment(''); setConfirm('unset'); setPrimary('unset'); review.reset(); }} />
          </Notice>
        )}
        {review.error && !conflict && <ErrorBox error={review.error} testId="review-error" />}
        {review.isSuccess && !review.error && (
          <Notice tone="ok" title={`Revisión registrada: ${REVIEW_LABEL[review.data.status]}`} testId="review-saved" stamp>
            Versión {review.data.version} · responsable {review.data.reviewer ?? '—'}.
          </Notice>
        )}
      </div>

      <h3 className="mt-5 text-sm font-semibold">Historial</h3>
      <ol data-testid="review-history" className="mt-1 space-y-1 text-sm">
        {caseView.history.length === 0 && <li className="text-ink-3">Sin eventos todavía.</li>}
        {[...caseView.history].reverse().map((e) => (
          <li key={e.version} data-testid="review-history-item" className="rounded border border-rule bg-sunk px-2.5 py-1.5">
            <span className="font-mono text-xs text-ink-3">v{e.version}</span> · {fmtDateTime(e.at)} · <strong>{e.kind}</strong>
            {e.toStatus ? <> · {e.fromStatus ? `${REVIEW_LABEL[e.fromStatus]} → ` : ''}{REVIEW_LABEL[e.toStatus]}</> : null} · {e.actor}
            {e.rulesVersion && <> · {e.rulesVersion}</>}
            {e.comment ? <span className="block text-ink-2">«{e.comment}»</span> : null}
          </li>
        ))}
      </ol>
    </Card>
  );
}

// --------------------------------------------------------------------------- exportación

function ExportPanel({ caseId }: { caseId: string }) {
  const { api } = useApp();
  const exp = useMutation({ mutationFn: () => api.exportCase(caseId) });
  const [copied, setCopied] = useState(false);
  useEffect(() => setCopied(false), [exp.data]);
  const download = () => {
    if (!exp.data) return;
    const url = URL.createObjectURL(new Blob([exp.data.markdown], { type: 'text/markdown;charset=utf-8' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = exp.data.filename;
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <Card aria-labelledby="export-title">
      <SectionTitle id="export-title" kicker="Notion">
        Exportar ficha
      </SectionTitle>
      <p className="mb-2 text-sm text-ink-2">Genera Markdown listo para pegar en Notion con puntaje, evidencia, borrador, citas e historial.</p>
      <div className="flex flex-wrap gap-2">
        <Button icon={FileDown} data-testid="export-markdown" busy={exp.isPending} onClick={() => exp.mutate()}>
          Generar Markdown
        </Button>
        {exp.data && (
          <>
            <Button
              icon={ClipboardCopy}
              data-testid="export-copy"
              onClick={() => navigator.clipboard.writeText(exp.data.markdown).then(() => setCopied(true)).catch(() => setCopied(false))}
            >
              {copied ? 'Copiado' : 'Copiar'}
            </Button>
            <Button icon={FileDown} data-testid="export-download" onClick={download}>
              Descargar .md
            </Button>
          </>
        )}
      </div>
      {exp.error && <div className="mt-2"><ErrorBox error={exp.error} testId="export-error" /></div>}
      {exp.data && (
        <pre data-testid="export-preview" className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap rounded-md border border-rule bg-sunk p-3 text-xs">
          {exp.data.markdown}
        </pre>
      )}
    </Card>
  );
}

// --------------------------------------------------------------------------- vista

function TopicPicker() {
  const { go } = useApp();
  const q = useTopics({ limit: 20 });
  const ref = useRef<HTMLDivElement>(null);
  useEntrance(ref, 'borradores', Boolean(q.data));
  return (
    <div ref={ref} data-testid="draft-view" className="space-y-4">
      <header data-motion="heading" className="comic-page-heading space-y-2">
        <p className="kicker">Borradores</p>
        <h1 className="font-display text-3xl font-bold leading-tight">Elige un tema para redactar</h1>
      </header>
      <SavedCases />
      {q.isLoading && <Loading label="Cargando temas…" />}
      {q.error && <ErrorBox error={q.error} onRetry={() => q.refetch()} />}
      <ul className="space-y-3">
        {q.data?.items.map((t) => (
          <li key={t.id} data-motion="card" data-press-host className="comic-panel relative flex flex-wrap items-center justify-between gap-3 p-3 hover:bg-amber-50">
            <div className="flex min-w-0 flex-1 items-start gap-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center border-2 border-ink bg-amber-300 font-display text-xl font-extrabold shadow-[2px_2px_0_var(--color-ink)]" aria-hidden="true">
                {t.rank ?? '–'}
              </span>
              <a
                href={`#/borradores/${encodeURIComponent(t.id)}`}
                data-testid="draft-pick-topic"
                className="min-w-0 font-display text-xl font-bold leading-snug after:absolute after:inset-0 hover:text-amber-700"
                onClick={(e) => {
                  e.preventDefault();
                  go({ view: 'borradores', topicId: t.id });
                }}
              >
                <span className="sr-only">{t.rank ? `${t.rank}. ` : ''}</span>
                {t.title}
              </a>
            </div>
            <span className="flex flex-wrap gap-1.5 pl-[3.25rem] sm:pl-0">
              <EvidencePill status={t.evidenceStatus} testId="pick-evidence" />
              <ReviewPill status={t.reviewStatus} />
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CreatePanel({ detail, caseView }: { detail: TopicDetail; caseView: CaseView }) {
  const { authMode } = useApp();
  const health = useHealth();
  const create = useCreateDraft(detail.summary.id);
  const [provider, setProvider] = useState<DraftProviderChoice>('auto');
  const [accountsOpen, setAccountsOpen] = useState(false);
  const [providerNotice, setProviderNotice] = useState('');
  const id = useId();
  const localConnectionsAllowed = authMode === 'local' && health.data?.localMode === true && health.data.authMode === 'local';
  const choices = useMemo(() => PROVIDER_CHOICES.filter((choice) => {
    if (choice.value === 'chatgpt' || choice.value === 'claude') {
      if (!localConnectionsAllowed) return false;
      return health.data?.providers.find((item) => item.name === choice.value)?.available === true;
    }
    if (choice.value === 'gemini') {
      const status = health.data?.providers.find((item) => item.name === 'gemini');
      return !status || status.available;
    }
    return true;
  }), [health.data, localConnectionsAllowed]);
  useEffect(() => {
    if (choices.some((choice) => choice.value === provider)) return;
    setProvider('auto');
    setProviderNotice('El proveedor dejó de estar disponible; se eligió Automático. No se cambiará a otro proveedor personal.');
  }, [choices, provider]);
  const selectedChoice = choices.find((item) => item.value === provider);
  const choice = selectedChoice ?? PROVIDER_CHOICES.find((item) => item.value === 'auto');
  const unavailableConnections = localConnectionsAllowed && ['chatgpt', 'claude'].some((name) =>
    !health.data?.providers.find((item) => item.name === name)?.available,
  );
  return (
    <>
      <Card aria-labelledby="create-title">
        <SectionTitle id="create-title" kicker="Generación">
          {caseView.currentDraft ? 'Generar otro borrador' : 'Crear borrador'}
        </SectionTitle>
        <div className="draft-create-row">
          <div className="min-w-0">
            <Field label="Proveedor de redacción" htmlFor={id}>
              <Select id={id} testId="draft-provider" value={provider} onChange={(value) => { setProvider(value); setProviderNotice(''); }} options={choices.map((item) => {
                const status = health.data?.providers.find((entry) => entry.name === item.value);
                const label = status?.model && ['gemini', 'chatgpt', 'claude'].includes(item.value) ? `${item.label} · ${status.model}` : item.label;
                const hint = item.value === 'chatgpt' || item.value === 'claude'
                  ? `${item.help} Solo en este equipo; usa tu plan o suscripción.`
                  : item.help;
                return { value: item.value, label, hint };
              })} />
            </Field>
          </div>
          <Button variant="primary" icon={Sparkles} data-testid="draft-generate" busy={create.isPending} onClick={() => create.mutate(provider)}>
            {create.isPending ? 'Generando…' : 'Generar borrador'}
          </Button>
        </div>
        {choice?.help && <p className="mt-2 text-xs text-ink-3" data-testid="draft-provider-help">{choice.help}</p>}
        {providerNotice && <Notice tone="warn" role="status" testId="draft-provider-changed">{providerNotice}</Notice>}
        {unavailableConnections && <div className="mt-2 flex flex-wrap items-center gap-2">
          <p className="text-xs text-ink-3">ChatGPT y Claude aparecen en este selector cuando Umbral reconoce una sesión local.</p>
          <Button variant="ghost" data-testid="draft-provider-accounts" onClick={() => setAccountsOpen(true)}>Cuentas y modelos…</Button>
        </div>}
        {localConnectionsAllowed && !unavailableConnections && <div className="mt-2"><Button variant="ghost" data-testid="draft-provider-accounts" onClick={() => setAccountsOpen(true)}>Cuentas y modelos…</Button></div>}
        <p className="mt-2 text-xs text-ink-3">
          Se usa solo la evidencia recuperada del corpus. Si el modelo deja de responder o se agota su cuota, se recurre a un borrador recuperado o a la plantilla con citas; nunca se cambia automáticamente a otro proveedor personal.
        </p>
        <div aria-live="polite" className="mt-2 space-y-2">
          {create.data?.notices.map((n, i) => (
            <Notice key={i} tone="info" testId="draft-notice">
              {n}
            </Notice>
          ))}
        </div>
        {create.error && (
          <div className="mt-2">
            <ErrorBox error={create.error} testId="draft-create-error" />
            {create.error instanceof ApiError && create.error.status === 403 && (
              <p className="mt-1 text-xs text-ink-3">Las conexiones personales (ChatGPT, Claude) solo funcionan al ejecutar en localhost.</p>
            )}
          </div>
        )}
      </Card>
      <Modal open={accountsOpen} title="Cuentas y modelos" description="Umbral reconoce las conexiones locales de ChatGPT y Claude; no importa sesiones de otros clientes." onClose={() => setAccountsOpen(false)} testId="draft-provider-accounts-modal">
        <ConnectionsCard />
      </Modal>
    </>
  );
}

function DraftBody({ detail }: { detail: TopicDetail }) {
  const { reviewer, go } = useApp();
  const caseView = detail.case;
  const drafts = caseView.drafts;
  const [pickedId, setPickedId] = useState<string | null>(null);
  const current = caseView.currentDraft;
  const shown = drafts.find((d) => d.draftId === pickedId) ?? current;
  const s = detail.summary;
  const isLatest = !!shown && !!current && shown.draftId === current.draftId;
  const ref = useRef<HTMLDivElement>(null);
  // La entrada se identifica por sección y tema; el editor no se remonta, así que no se pierden ediciones.
  useEntrance(ref, `borradores:${s.id}`);

  return (
    <div ref={ref} data-testid="draft-view" data-topic-id={s.id} className="space-y-4">
      <header data-motion="heading" className="comic-page-heading space-y-2">
        <a
          href="#/borradores"
          className="comic-link -ml-1 gap-1 px-1 text-sm text-ink-2 underline-offset-4 hover:text-amber-700 hover:underline"
          onClick={(e) => {
            e.preventDefault();
            go({ view: 'borradores', topicId: null });
          }}
        >
          <ArrowLeft size={14} aria-hidden="true" /> Cambiar de tema
        </a>
        <p className="kicker">Borradores · snapshot {detail.snapshotId} · {detail.rulesVersion}</p>
        <h1 className="font-display text-3xl font-bold leading-tight" data-testid="draft-topic-title">
          {s.title}
        </h1>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <EvidencePill status={s.evidenceStatus} />
          <ReviewPill status={caseView.status} />
          <Pill tone="neutral" icon={Newspaper} testId="headline-only-notice">
            basado únicamente en titular/metadatos
          </Pill>
          {detail.dataMode !== 'congelado' && (
            <Pill tone="warn" icon={CircleAlert} testId="data-mode-pill">
              Datos {detail.dataMode === 'fixture' ? 'de fixture (no reales)' : 'provisionales'}
            </Pill>
          )}
          <a
            href={`#/ficha/${encodeURIComponent(s.id)}`}
            className="comic-link px-2 text-sm underline underline-offset-4 hover:text-amber-700"
            onClick={(e) => {
              e.preventDefault();
              go({ view: 'ficha', topicId: s.id });
            }}
          >
            Ver ficha
          </a>
        </div>
      </header>

      {s.needsInvestigation && (
        <Notice tone="amber" icon={ShieldAlert} title="Requiere investigación: no habilita publicación" testId="topic-needs-investigation">
          La prioridad es alta pero la evidencia es insuficiente. Un borrador aquí es solo un punto de partida para investigar.
        </Notice>
      )}
      {detail.contradictions.length > 0 && (
        <Notice tone="bad" title="Hay versiones incompatibles en las fuentes" testId="draft-contradiction">
          El borrador no debe elegir una versión: {detail.contradictions[0]?.description}
        </Notice>
      )}

      <CreatePanel detail={detail} caseView={caseView} />

      {!shown ? (
        <Notice tone="info" title="Aún no hay borrador para este tema" testId="draft-empty">
          Genera uno con el proveedor que prefieras. La plantilla con citas funciona incluso sin internet.
        </Notice>
      ) : (
        <>
          <Card aria-labelledby="origin-title" data-testid="draft-meta">
            <SectionTitle
              id="origin-title"
              kicker={`Borrador #${shown.number}${isLatest ? ' (vigente)' : ''}`}
              aside={
                drafts.length > 1 ? (
                  <div className="flex w-full min-w-0 items-center gap-2 text-xs sm:w-auto">
                    <span id="draft-version-label" className="shrink-0 text-ink-3">
                      Versión
                    </span>
                    <div className="min-w-0 flex-1 sm:min-w-48 sm:flex-none">
                      <Select
                        id="draft-version"
                        testId="draft-version-select"
                        labelledBy="draft-version-label"
                        value={shown.draftId}
                        onChange={setPickedId}
                        options={drafts.map((d) => ({ value: d.draftId, label: `#${d.number} · ${d.generationLabel}` }))}
                      />
                    </div>
                  </div>
                ) : undefined
              }
            >
              Origen del borrador
            </SectionTitle>
            <div className="flex flex-wrap items-center gap-2">
              <GenerationPill mode={shown.generationMode} label={shown.generationLabel} />
              <span className="text-sm text-ink-2" data-testid="draft-provider-info">
                proveedor <strong>{shown.provider}</strong>
                {shown.model ? <> · modelo <strong>{shown.model}</strong></> : null}
              </span>
              <span className="text-xs text-ink-3">{fmtDateTime(shown.createdAt)}</span>
              {shown.editedBy && <span className="text-xs text-ink-3">Editado por {shown.editedBy} · {fmtDateTime(shown.editedAt)}</span>}
            </div>
            {shown.fallbackReason && (
              <p className="mt-2 text-sm text-ink-2" data-testid="draft-fallback-reason">
                <RefreshCw size={14} className="mr-1 inline" aria-hidden="true" />
                Se recurrió a este modo por: <strong>{FALLBACK_LABEL[shown.fallbackReason]}</strong>
                {shown.fallbackDetail ? ` — ${shown.fallbackDetail}` : ''}.
              </p>
            )}
            {shown.recoveredFromDraftId && <p className="mt-1 text-xs text-ink-3">Recuperado del borrador {shown.recoveredFromDraftId}.</p>}
            {shown.previousDraftId && <p className="mt-1 text-xs text-ink-3">Edición de {shown.previousDraftId}; la versión anterior se conserva.</p>}
            {shown.usage && <dl data-testid="draft-usage" className="mt-3 grid gap-2 text-xs sm:grid-cols-3">
              <div><dt className="text-ink-3">Tokens de entrada / salida / total</dt><dd>{shown.usage.promptTokens ?? 'sin dato'} / {shown.usage.outputTokens ?? 'sin dato'} / {shown.usage.totalTokens ?? 'sin dato'}</dd></div>
              <div><dt className="text-ink-3">Latencia de generación</dt><dd>{shown.usage.latencyMs === null ? 'sin dato' : `${fmtNumber(shown.usage.latencyMs / 1000, 2)} s`}</dd></div>
              <div><dt className="text-ink-3">Costo de esta llamada</dt><dd>{shown.usage.costUsd === null ? 'sin dato monetario' : `${shown.usage.costUsd} USD`}</dd></div>
              <div className="sm:col-span-3"><dt className="sr-only">Alcance del reporte</dt><dd>{shown.usage.scope} · {shown.usage.costNote}</dd></div>
            </dl>}
            {shown.package.headlineOnlyNotice && (
              <p className="mt-2 text-sm font-medium" data-testid="draft-headline-notice">
                {shown.package.headlineOnlyNotice}
              </p>
            )}
          </Card>

          {isLatest ? (
            <DraftEditor key={caseView.caseId} detail={detail} draft={shown} caseView={caseView} reviewer={reviewer} />
          ) : (
            <Notice tone="info" title="Versión anterior (solo lectura)" testId="draft-readonly">
              Selecciona la versión vigente para editar. Brief: {shown.package.brief}
            </Notice>
          )}
          <ReviewPanel detail={detail} caseView={caseView} />
          <ExportPanel caseId={caseView.caseId} />
        </>
      )}
    </div>
  );
}

export function Drafts() {
  const { route } = useApp();
  const topicId = route.view === 'borradores' ? route.topicId : null;
  const q = useTopic(topicId);
  if (!topicId) return <TopicPicker />;
  if (q.isLoading) return <Loading label="Cargando ficha y borradores…" />;
  if (q.error)
    return (
      <div data-testid="draft-view">
        <ErrorBox error={q.error} onRetry={() => q.refetch()} />
        <p className="mt-2 text-sm text-ink-3">{describeError(q.error)}</p>
      </div>
    );
  if (!q.data) return null;
  return <DraftBody detail={q.data} />;
}
