import { Fragment, type ReactNode } from 'react';

/**
 * Texto con estructura para respuestas del asistente: párrafos, listas numeradas o con viñetas, **negritas** y `código`.
 * Se construye con nodos de React (nunca HTML en crudo), así que el texto de una fuente no puede inyectar marcado.
 */

export type Block = { kind: 'p'; lines: string[] } | { kind: 'ol' | 'ul'; items: string[] };

const ORDERED = /^\s*\d{1,2}[.)]\s+(.*)$/;
const BULLET = /^\s*[-•*]\s+(.*)$/;

export function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  let afterBlank = true;
  for (const raw of text.replace(/\r\n?/g, '\n').split('\n')) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      blocks.push({ kind: 'p', lines: [] }); // separador: cierra el bloque actual
      afterBlank = true;
      continue;
    }
    const wasBlank = afterBlank;
    afterBlank = false;
    const ordered = ORDERED.exec(line);
    const bullet = ordered ? null : BULLET.exec(line);
    const kind = ordered ? 'ol' : bullet ? 'ul' : 'p';
    const body = (ordered ?? bullet)?.[1] ?? line.trim();
    const last = blocks[blocks.length - 1];
    if (kind === 'p') {
      if (last && last.kind !== 'p' && !wasBlank) {
        // Línea suelta justo después de un ítem: continúa ese ítem (p. ej. el puntaje bajo el titular).
        last.items[last.items.length - 1] += '\n' + body;
      } else if (last && last.kind === 'p' && last.lines.length > 0) {
        last.lines.push(body);
      } else if (last && last.kind === 'p') {
        last.lines = [body];
      } else {
        blocks.push({ kind: 'p', lines: [body] });
      }
    } else if (last && last.kind === kind && !wasBlank) {
      last.items.push(body);
    } else if (last && last.kind === kind) {
      last.items.push(body);
    } else {
      blocks.push({ kind, items: [body] });
    }
  }
  return blocks.filter((b) => (b.kind === 'p' ? b.lines.length > 0 : b.items.length > 0));
}

const INLINE = /(\*\*[^*\n]+\*\*|`[^`\n]+`)/g;
const MARKER = /(\[\d{1,2}\])/g;

/** Marcadores [n] fuera de «comillas»: dentro de una cita literal de una fuente un «[3]» es texto de la fuente, no una referencia. */
function Markers({ text, citeCount, onCite }: { text: string; citeCount: number; onCite: (index: number) => void }): ReactNode {
  let quoted = false;
  return text.split(MARKER).map((part, i) => {
    const match = /^\[(\d{1,2})\]$/.exec(part);
    const index = match ? Number(match[1]) : 0;
    const isMarker = !quoted && index >= 1 && index <= citeCount;
    if (!match) for (const ch of part) { if (ch === '«') quoted = true; else if (ch === '»') quoted = false; }
    if (!isMarker) return <Fragment key={i}>{part}</Fragment>;
    return (
      <button key={i} type="button" className="cite-marker" data-testid="assistant-cite-marker" data-cite-index={index}
        aria-label={`Ver la fuente ${index}`} onClick={() => onCite(index)}>{index}</button>
    );
  });
}

export type Citing = { count: number; onCite: (index: number) => void };

export function Inline({ text, citing }: { text: string; citing?: Citing }): ReactNode {
  const plain = (value: string) => (citing && citing.count > 0 ? <Markers text={value} citeCount={citing.count} onCite={citing.onCite} /> : value);
  return text.split(INLINE).map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return (
        <strong key={i} className="font-bold text-ink">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      return (
        <code key={i} className="whitespace-nowrap rounded border border-rule bg-sunk px-1 py-px font-mono text-[0.85em]">
          {part.slice(1, -1)}
        </code>
      );
    }
    return <Fragment key={i}>{plain(part)}</Fragment>;
  });
}

function Lines({ lines, citing }: { lines: string[]; citing?: Citing }) {
  return (
    <>
      {lines.map((l, i) => (
        <Fragment key={i}>
          {i > 0 && <br />}
          <Inline text={l} citing={citing} />
        </Fragment>
      ))}
    </>
  );
}

export function RichText({ text, className = '', testId, citing }: { text: string; className?: string; testId?: string; citing?: Citing }) {
  const blocks = parseBlocks(text);
  return (
    <div className={`rich-text space-y-3 ${className}`} data-testid={testId}>
      {blocks.map((b, i) => {
        if (b.kind === 'p') {
          return (
            <p key={i} className="leading-relaxed">
              <Lines lines={b.lines} citing={citing} />
            </p>
          );
        }
        const Tag = b.kind === 'ol' ? 'ol' : 'ul';
        return (
          <Tag key={i} className={`rich-list ${b.kind === 'ol' ? 'rich-list-ol' : 'rich-list-ul'}`}>
            {b.items.map((it, j) => (
              <li key={j} className="leading-snug">
                <Lines lines={it.split('\n')} citing={citing} />
              </li>
            ))}
          </Tag>
        );
      })}
    </div>
  );
}
