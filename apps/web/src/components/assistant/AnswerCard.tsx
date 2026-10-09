import { Fragment, useEffect, useRef, useState } from 'react';
import { useQueries } from '@tanstack/react-query';
import { Bot, Copy, ExternalLink, Sparkles, TriangleAlert, X } from 'lucide-react';
import type { ComposeProvider, QueryResponse } from '../../lib/api/types';
import { fmtDateTime } from '../../lib/format';
import type { AssistantTurn } from '../../lib/api/assistantHistory';
import { ANSWER_LABEL, COMPOSE_PROVIDER_HELP, COMPOSE_PROVIDER_LABEL } from '../../lib/labels';
import { useApp } from '../context';
import { Button, Notice, Pill, type Tone } from '../ui';
import { Disclosure } from '../ui/controls';
import { RichText } from '../ui/RichText';
import { foldText } from './shared';

const STATUS_TONE: Record<QueryResponse['answerStatus'], Tone> = {
  respondida: 'ok', parcial: 'warn', contradiccion: 'bad', abstencion: 'neutral',
};

function RelatedTopics({ response, titles, onTitles, onNavigate }: {
  response: QueryResponse;
  titles?: Record<string, string>;
  onTitles: (titles: Record<string, string>) => void;
  onNavigate: (topicId: string) => void;
}) {
  const { api } = useApp();
  const queries = useQueries({ queries: response.relatedTopicIds.map((topicId) => ({
    queryKey: ['topic', topicId, api.kind], queryFn: () => api.topic(topicId), staleTime: 60_000,
  })) });
  useEffect(() => {
    const next: Record<string, string> = {};
    response.relatedTopicIds.forEach((topicId, index) => {
      const title = queries[index]?.data?.summary.title;
      if (title) next[topicId] = title;
    });
    if (Object.keys(next).length) onTitles(next);
  // The callback is stable for a conversation and only fetched titles should update storage.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [response.relatedTopicIds.join('|'), queries.map((query) => query.data?.summary.title ?? '').join('|')]);
  if (!response.relatedTopicIds.length) return null;
  return (
    <div className="assistant-related" data-testid="assistant-related-topics">
      <p className="font-semibold">Temas relacionados</p>
      <div className="mt-1 grid gap-1.5">
        {response.relatedTopicIds.map((topicId, index) => {
          const title = queries[index]?.data?.summary.title ?? titles?.[topicId] ?? 'Abrir tema relacionado';
          return <button key={topicId} type="button" className="assistant-related-link" onClick={() => onNavigate(topicId)}>{title}</button>;
        })}
      </div>
    </div>
  );
}

const FIELD_LABEL: Record<string, string> = { title: 'Titular', value: 'Valor', year: 'Año', magnitude:'Magnitud', timePanama:'Hora de Panamá', place:'Ubicación reportada', depth:'Profundidad' };

/** Resalta en el pasaje los términos que la recuperación hizo coincidir (comparación sin tildes y por prefijo; es una guía, no una prueba). */
function Highlighted({ text, terms }: { text: string; terms: string[] }) {
  const needles = terms.map(foldText).filter((term) => term.length >= 3);
  if (!needles.length) return <>{text}</>;
  return <>{text.split(/([\p{L}\p{N}]+)/u).map((part, index) => {
    const folded = foldText(part);
    const hit = folded.length >= 3 && needles.some((needle) => folded.startsWith(needle) || needle.startsWith(folded));
    return hit ? <mark key={index} className="assistant-mark">{part}</mark> : <Fragment key={index}>{part}</Fragment>;
  })}</>;
}

function CitationGroup({ index, evidenceId, citations, response }: {
  index: number;
  evidenceId: string;
  citations: QueryResponse['citations'];
  response: QueryResponse;
}) {
  const first = citations[0];
  const hit = response.hits.find((item) => item.evidenceId === evidenceId);
  const untrusted = Boolean(hit?.suspiciousInstructions);
  const label = first?.title ?? hit?.title ?? 'Fuente';
  const passages = citations.filter((item) => item.passage);
  return (
    <li className="assistant-source" data-evidence-id={evidenceId} data-source-index={index} tabIndex={-1}>
      <div className="font-semibold">
        <span className="cite-number" aria-hidden="true">[{index}]</span>
        {untrusted
          ? <span data-testid="assistant-citation" data-evidence-id={evidenceId}>Fuente no confiable: texto omitido</span>
          : first?.url && /^https?:\/\//.test(first.url)
            ? <a href={first.url} target="_blank" rel="noopener noreferrer nofollow" data-testid="assistant-citation" data-evidence-id={evidenceId} className="text-info underline underline-offset-2"><span className="sr-only">Fuente {index}: </span>{label}<ExternalLink size={12} className="ml-1 inline" aria-hidden="true" /><span className="sr-only"> (se abre en otra pestaña)</span></a>
            : <span data-testid="assistant-citation" data-evidence-id={evidenceId}><span className="sr-only">Fuente {index}: </span>{label}</span>}
      </div>
      {untrusted && <p className="text-xs text-warn">Contiene texto con forma de instrucción. Se trató como contenido no confiable y no se usó como evidencia.</p>}
      {(hit?.outlet || hit?.publishedAt) && <p className="text-xs text-ink-3">{[hit.outlet, hit.publishedAt ? fmtDateTime(hit.publishedAt) : null].filter(Boolean).join(' · ')}</p>}
      {!untrusted && passages.length > 0 && (
        <Disclosure summary="Pasaje citado" testId="assistant-passage" triggerClassName="assistant-passage-trigger">
          <ul className="assistant-passages">
            {passages.map((item) => (
              <li key={`${item.field}:${item.passage}`}>
                <span className="assistant-passage-field">{FIELD_LABEL[item.field] ?? item.field}</span>
                <q><Highlighted text={item.passage ?? ''} terms={hit?.kind === 'articulo' && item.field === 'title' ? response.retrieval.matchedTerms : []} /></q>
              </li>
            ))}
          </ul>
        </Disclosure>
      )}
      {!untrusted && hit?.retrievalOrigin === 'semantic_neighbor' && <p className="mt-1 text-xs text-ink-3">Fuente encontrada por relación semántica. La similitud no demuestra que respalde la afirmación; revisa la cita.</p>}
    </li>
  );
}

export function Answer({ turn, onCopy, onRelatedTitles, onNavigate, composing, canCompose, composeProvider, onCompose, onCancelCompose }: {
  turn: AssistantTurn;
  /** Se está redactando esta respuesta con IA. */
  composing: boolean;
  /** Gemini disponible; si no, el motivo para mostrarlo. */
  canCompose: { ok: boolean; reason?: string | null };
  composeProvider: ComposeProvider;
  onCompose: () => void;
  onCancelCompose: () => void;
  onCopy: (turn: AssistantTurn) => void;
  onRelatedTitles: (titles: Record<string, string>) => void;
  onNavigate: (topicId: string) => void;
}) {
  const result = turn.result;
  const articleRef = useRef<HTMLElement>(null);
  const [moreOpen, setMoreOpen] = useState(false);
  if (!result) return null;
  const abstentionReason = result.abstentionReason?.trim();
  const showAbstentionReason = Boolean(abstentionReason && !result.answer.includes(abstentionReason));
  const grouped = [...result.citations.reduce((groups, citation) => {
    const group = groups.get(citation.evidenceId) ?? [];
    group.push(citation);
    groups.set(citation.evidenceId, group);
    return groups;
  }, new Map<string, QueryResponse['citations']>()).entries()];
  const visibleGroups = grouped.slice(0, 2);
  const remainingGroups = grouped.slice(2);
  const citedIds = new Set(grouped.map(([evidenceId]) => evidenceId));
  const searchMode = result.searchMode ?? 'snapshot';
  const composable = turn.state === 'complete' && searchMode === 'snapshot' && (result.answerStatus === 'respondida' || result.answerStatus === 'parcial') && result.citations.length > 0;
  const excluded = [...new Map(result.hits.filter((hit) => hit.suspiciousInstructions && !citedIds.has(hit.evidenceId)).map((hit) => [hit.evidenceId, hit])).values()];
  function focusSource(index: number) {
    if (index > visibleGroups.length) setMoreOpen(true);
    requestAnimationFrame(() => {
      const target = articleRef.current?.querySelector<HTMLElement>(`[data-source-index="${index}"]`);
      target?.scrollIntoView({ block: 'nearest' });
      target?.focus({ preventScroll: true });
    });
  }
  return (
    <article ref={articleRef} data-testid="assistant-answer" data-status={result.answerStatus} className="comic-answer assistant-answer">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="grid gap-1">
          <Pill tone={STATUS_TONE[result.answerStatus]} icon={result.answerStatus === 'contradiccion' ? TriangleAlert : Bot}>{ANSWER_LABEL[result.answerStatus]}</Pill>
          <span className="assistant-mode" data-testid="assistant-mode" data-mode={turn.answerMode === 'modelo' ? 'modelo' : 'reglas'}>
            {turn.answerMode === 'modelo' ? `Redactada con IA (${turn.composedBy ?? 'modelo'}) · verificada por código contra las fuentes` : 'Reglas y fuentes · sin modelo de IA'}
          </span>
          <span className="assistant-mode" data-testid="assistant-search-source">
            {searchMode === 'live' ? 'Búsqueda en vivo' : searchMode === 'hybrid' ? 'Fuentes en vivo + snapshot' : 'Snapshot verificado'}
            {result.liveCheckedAt ? ` · consultado ${fmtDateTime(result.liveCheckedAt)}` : ''}
          </span>
        </div>
        <Button variant="ghost" icon={Copy} onClick={() => onCopy(turn)} data-testid="assistant-copy">Copiar respuesta con fuentes</Button>
      </div>
      {composing && (
        <div className="assistant-pending">
          <p role="status"><span className="assistant-spinner" aria-hidden="true" />Redactando y verificando contra las fuentes…</p>
          <Button variant="ghost" icon={X} onClick={onCancelCompose} data-testid="assistant-compose-cancel">Cancelar</Button>
        </div>
      )}
      {result.resolvedQuestion && <p className="assistant-resolved" data-testid="assistant-resolved">Entendí tu pregunta como: «{result.resolvedQuestion}»</p>}
      <RichText text={result.answer} testId="assistant-answer-text" className="assistant-answer-copy" citing={{ count: grouped.length, onCite: focusSource }} />
      {turn.answerMode === 'modelo' && turn.rulesAnswer && (
        <Disclosure summary="Ver la respuesta por reglas" testId="assistant-rules-answer">
          <RichText text={turn.rulesAnswer} className="assistant-answer-copy" />
        </Disclosure>
      )}
      {turn.composeNote && <Notice tone="warn" role="status" testId="assistant-compose-note" title="Se conservó la respuesta por reglas">No se redactó con IA: {turn.composeNote}.</Notice>}
      {canCompose.ok === false && turn.answerMode !== 'modelo' && composable && <p className="text-xs text-ink-3" data-testid="assistant-compose-unavailable">Redactar con IA no está disponible: {canCompose.reason ?? 'proveedor no conectado'}.</p>}
      {composable && canCompose.ok && !composing && turn.answerMode !== 'modelo' && (
        <div className="assistant-compose">
          <Button variant="secondary" icon={Sparkles} onClick={onCompose} data-testid="assistant-compose">Redactar con {COMPOSE_PROVIDER_LABEL[composeProvider]}</Button>
          <p className="assistant-input-help">Un modelo reescribe esta respuesta usando solo estas fuentes y el código la verifica (citas, pasajes y cifras). {COMPOSE_PROVIDER_HELP[composeProvider]}</p>
        </div>
      )}
      {showAbstentionReason && <Notice tone="neutral" title="Motivo de abstención" testId="assistant-abstention" animate={false}><p>{abstentionReason}</p></Notice>}
      {result.missing.length > 0 && <section data-testid="assistant-missing"><h3 className="font-semibold">Falta verificar</h3><ul className="list-disc pl-5">{result.missing.map((item) => <li key={item}>{item}</li>)}</ul></section>}
      {result.contradictions.length > 0 && <section data-testid="assistant-contradictions" className="space-y-2"><h3 className="font-semibold text-bad">Versiones en contradicción</h3>{result.contradictions.map((item) => <div key={item.id} className="rounded border border-bad/50 bg-bad-bg/40 p-2"><p className="font-semibold">{item.description}</p><ul className="mt-1 space-y-1">{item.versions.map((version) => <li key={version.evidenceId}>«{version.statement}» <span className="text-xs text-ink-3">— {version.outlet}, {version.publishedAt ? fmtDateTime(version.publishedAt) : `detectada: ${fmtDateTime(version.detectedAt)}`}</span>{version.url && /^https?:\/\//.test(version.url) && <a className="comic-link ml-1 text-xs underline" href={version.url} target="_blank" rel="noopener noreferrer">Abrir fuente</a>}</li>)}</ul><p className="mt-1 text-xs">Pendiente: {item.pendingVerification}</p></div>)}</section>}
      {visibleGroups.length > 0 && <section><h3 className="font-semibold">Fuentes usadas</h3><ul className="mt-1 grid gap-2" data-testid="assistant-citations">{visibleGroups.map(([evidenceId, citations], position) => <CitationGroup key={evidenceId} index={position + 1} evidenceId={evidenceId} citations={citations} response={result} />)}</ul>{remainingGroups.length > 0 && <Disclosure summary={`Ver ${remainingGroups.length} fuentes más`} testId="assistant-more-sources" open={moreOpen} onOpenChange={setMoreOpen}><ul className="grid gap-2">{remainingGroups.map(([evidenceId, citations], position) => <CitationGroup key={evidenceId} index={visibleGroups.length + position + 1} evidenceId={evidenceId} citations={citations} response={result} />)}</ul></Disclosure>}</section>}
      {excluded.length > 0 && (
        <Notice tone="warn" testId="assistant-untrusted" title="Fuentes excluidas">
          <p className="text-xs">Contienen texto con forma de instrucción dirigida a un agente. Se trataron como contenido no confiable: su texto no se muestra ni se usó.</p>
          <ul className="mt-1 grid gap-1 text-xs">{excluded.map((hit) => <li key={hit.evidenceId}>{[hit.outlet ?? 'Fuente', hit.publishedAt ? fmtDateTime(hit.publishedAt) : null].filter(Boolean).join(' · ')}</li>)}</ul>
        </Notice>
      )}
      <RelatedTopics response={result} titles={turn.relatedTitles} onTitles={onRelatedTitles} onNavigate={onNavigate} />
      {result.warnings.length > 0 && <Notice tone="warn" title="Advertencias de la consulta" testId="assistant-result-warnings"><ul className="list-disc pl-5">{result.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></Notice>}
      <Disclosure summary="Datos de la consulta" testId="assistant-query-data">
        <dl className="assistant-query-data">
          <div><dt>Consulta</dt><dd>{result.queryId}</dd></div><div><dt>Intención</dt><dd>{result.intent}</dd></div>
          <div><dt>Recuperación</dt><dd>{result.retrieval.method}</dd></div><div><dt>Cobertura de términos</dt><dd>{Math.round(result.retrieval.coverage * 100)} % (indicador técnico, no confianza editorial)</dd></div>
          {result.retrieval.semanticExpansion && <div><dt>Ampliación semántica</dt><dd>{result.retrieval.semanticModel} · RRF k={result.retrieval.rrfK}</dd></div>}
          <div><dt>Corpus y tiempo</dt><dd>{result.retrieval.corpusSize} elementos · {result.retrieval.tookMs.toFixed(0)} ms</dd></div>
          <div><dt>Snapshot y reglas</dt><dd>{result.snapshotId} · {result.rulesVersion}</dd></div>
          {grouped.length > 0 && <div><dt>Correspondencia de evidencias</dt><dd>{grouped.map(([evidenceId, citations], position) => `[${position + 1}] ${evidenceId}: ${citations.map((citation) => citation.field).join(', ')}`).join(' · ')}</dd></div>}
        </dl>
      </Disclosure>
    </article>
  );
}
