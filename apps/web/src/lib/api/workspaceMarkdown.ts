import type { TopicDetail } from './types';
import { fmtDateTime } from '../format';
const cell = (value: unknown): string => String(value ?? '—').replaceAll('|', '\\|').replaceAll('\n', ' ');
export function exportMarkdown(detail: TopicDetail): string {
  const s = detail.summary, c = detail.case, d = c.currentDraft;
  const lines = ['# Ficha: ' + s.title, '', '- **ID del tema:** ' + s.id + ' · **Caso:** ' + c.caseId,
    '- **Snapshot:** ' + detail.snapshotId + ' (' + detail.dataMode + ') · **Reglas:** ' + c.rulesVersion,
    '- **Categoría:** ' + s.categoryLabel + ' · **Puntaje:** ' + s.score + ' (' + s.band + ')',
    '- **Evidencia:** ' + detail.evidence.statusLabel + ' · **Revisión:** ' + c.statusLabel,
    '- **Responsable:** ' + (c.reviewer ?? '—') + ' · **Versión:** ' + c.version, '',
    '> Basado únicamente en titular/metadatos. El puntaje ordena la atención; no habilita publicación.',
    ...(detail.dataMode === 'fixture' ? ['> Datos de fixture: solo para demostración.'] : []),
    '', ...detail.warnings.map((warning) => '> ' + warning), '', '## Qué se reporta', detail.whatIsReported, '', '## Quién lo reporta y procedencia',
    '| Medio | Procedencia | Rol | Fuentes |', '|---|---|---|---|',
    ...detail.reporters.map((r) => '| ' + [r.outlet,r.origin,r.role,r.evidenceIds.join(', ')].map(cell).join(' | ') + ' |'),
    '', '## Noticias agrupadas', '| ID | Titular | Medio | Publicación | Detección | Extracción | URL |', '|---|---|---|---|---|---|---|',
    ...detail.articles.map((a) => '| ' + [a.id,a.title + (a.suspiciousInstructions ? ' (fuente con instrucciones excluida)' : ''),a.outlet,fmtDateTime(a.publishedAt),fmtDateTime(a.detectedAt),fmtDateTime(a.extractedAt),a.url].map(cell).join(' | ') + ' |'),
    '', '## Puntaje desglosado', detail.score.formula, '| Componente | Peso | Valor | Puntos | Regla y justificación | Límites |', '|---|---|---|---|---|---|',
    ...detail.score.components.map((p) => '| ' + [p.key + ' · ' + p.label,p.weight,p.value,p.points,p.rule + ': ' + p.justification,p.limits.join('; ')].map(cell).join(' | ') + ' |'),
    '', '## Estado de evidencia', detail.evidence.statusLabel + ' — ' + detail.evidence.rationale,
    ...(c.evidenceConfirmed !== null ? ['Confirmación humana: ' + c.evidenceConfirmed + ' · ' + (c.evidenceConfirmedBy ?? '—')] : []),
    ...detail.evidence.gaps.map((g) => '- ' + g.message),
    '', '## Contexto oficial', detail.officialContext.relationRationale, '| País | Indicador | Año | Valor | Unidad | URL |', '|---|---|---|---|---|---|',
    ...detail.officialContext.indicators.map((p) => '| ' + [p.countryName ?? p.countryIso3,p.indicatorName,p.year,p.value,p.unit,p.sourceUrl].map(cell).join(' | ') + ' |'),
    ...detail.officialContext.limitations.map((l) => '- ' + l), '', '## Contradicciones',
    ...detail.contradictions.flatMap((ct) => ['- ' + ct.description, ...ct.versions.map((v) => '  - ' + v.outlet + ': ' + v.statement + ' (' + v.evidenceId + ')'), '  - Pendiente: ' + ct.pendingVerification]),
    '', '## Afirmaciones respaldadas', ...detail.supportedClaims.map((cl) => '- [' + cl.type + '] ' + cl.text + ' (' + cl.citations.map((ct) => ct.evidenceId + ' · ' + ct.field + (ct.passage ? ': ' + ct.passage : '')).join('; ') + ')'),
    '', '## Verificaciones pendientes', ...detail.pendingVerifications.map((p) => '- [ ] ' + p),
    '', '## Acción recomendada', detail.recommendedAction, '', '## Impacto',
    detail.impact.level + ' (' + detail.impact.origin + '): ' + detail.impact.justification,
    ...(detail.impact.reason ? ['Motivo: ' + detail.impact.reason + ' · ' + detail.impact.author] : []), '', '## Borrador'];
  if (d) {
    const p = d.package;
    lines.push(d.generationLabel + ' · proveedor ' + d.provider + ' · #' + d.number, ...(d.fallbackReason ? ['Motivo de respaldo: ' + d.fallbackReason + ' — ' + (d.fallbackDetail ?? '')] : []),
      '', '### ' + p.proposedTitle, ...(p.headlineOnlyNotice ? ['> ' + p.headlineOnlyNotice] : []), '', '**Enfoque de interés público.** ' + p.publicInterestAngle,
      '', '**Brief**',p.brief,'','**Preguntas de investigación**',...p.researchQuestions.map((q,i) => (i+1) + '. ' + q),
      '', '**Verificaciones pendientes**', ...p.pendingVerifications.map((q) => '- [ ] ' + q), '', '**Guion (≈' + d.validation.scriptSecondsEstimate + ' s)**',p.script,'','**Copy digital**',p.socialCopy,
      '', '**Afirmaciones y citas**', '| ID | Tipo | Afirmación | Citas |', '|---|---|---|---|', ...p.claims.map((cl) => '| ' + [cl.id,cl.type,cl.text,cl.citations.map((ct) => ct.evidenceId + ' · ' + ct.field + (ct.passage ? ': ' + ct.passage : '')).join('; ')].map(cell).join(' | ') + ' |'),
      '', 'Validación: ' + (d.validation.ok ? 'correcta' : 'con errores') + '. ' + d.validation.note);
  } else lines.push('_Aún no se ha generado un borrador._');
  lines.push('', '## Historial de revisión', ...c.history.map((event) => '- v' + event.version + ' · ' + fmtDateTime(event.at) + ' · ' + event.kind + ' · ' + event.actor + (event.toStatus ? ' · ' + event.fromStatus + ' → ' + event.toStatus : '') + (event.comment ? ' — ' + event.comment : '') + ' · reglas ' + event.rulesVersion), '');
  return lines.join('\n');
}
