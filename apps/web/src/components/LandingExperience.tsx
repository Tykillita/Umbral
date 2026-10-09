import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { ArrowLeft, ArrowRight, Database, GripVertical } from 'lucide-react';
import { Disclosure } from './ui/controls';
import { getAuthToken } from '../lib/auth';
import { HttpApi } from '../lib/api/client';
import type { Health } from '../lib/api/types';
import { config } from '../lib/config';
import { resolvePublicApiUrl } from '../lib/publicConfig';

const STEPS = [
  {
    title: 'Escucha',
    description: 'Reúne titulares públicos de TVN y otros medios, indicadores oficiales y registros de sismos del USGS en cortes con fecha y huella verificable.',
  },
  {
    title: 'Agrupa',
    description: 'Junta las notas que cuentan el mismo hecho. Si varios medios publican la misma historia, Umbral las presenta como un solo tema con sus fuentes.',
  },
  {
    title: 'Prioriza',
    description: 'Ordena los temas por cinco criterios visibles: relevancia para Panamá, impacto, urgencia, novedad y evidencia disponible.',
  },
  {
    title: 'Explica',
    description: 'Cada tema tiene su ficha: quién lo reporta, desde cuándo, qué versiones se contradicen y qué falta comprobar antes de salir al aire.',
  },
  {
    title: 'Propone',
    description: 'Prepara resúmenes, guiones y textos para redes con la fuente de cada afirmación. Una persona revisa y decide qué hacer con cada borrador.',
  },
];

const PROMISES = [
  {
    id: 'cita-datos',
    title: 'Cita cada dato',
    yes: 'Cada afirmación del borrador lleva su fuente para que la puedas revisar.',
    limit: 'No inventa cifras, declaraciones ni fuentes. Si falta evidencia, lo dice y explica qué haría falta comprobar.',
  },
  {
    id: 'ordena-atencion',
    title: 'Ordena la atención',
    yes: 'Muestra qué temas pueden merecer una primera mirada y por qué.',
    limit: 'El puntaje no decide qué es verdad. Aprobar un borrador no significa publicarlo.',
  },
  {
    id: 'lee-fuentes',
    title: 'Lee las fuentes como datos',
    yes: 'Las noticias y preguntas se analizan como contenido que debe comprobarse.',
    limit: 'No obedece instrucciones escondidas en una noticia ni en una pregunta.',
  },
  {
    id: 'muestra-procedencia',
    title: 'Muestra de dónde viene todo',
    yes: 'Conserva la procedencia y las fechas de la información que presenta.',
    limit: 'No esconde versiones distintas ni límites del corte: cuando hay desacuerdos, los señala.',
  },
] as const;

type PromiseId = (typeof PROMISES)[number]['id'];
type PromiseDrag = {
  from: number;
  id: PromiseId;
  pointerId: number;
  startX: number;
  startY: number;
  card: HTMLElement;
  dropTarget: HTMLElement | null;
};
const PROMISE_ORDER_KEY = 'umbral.landing-promises.order.v1';
const CATEGORIES = ['Canal de Panamá', 'Turismo', 'Economía', 'Servicios públicos', 'Eventos naturales', 'Regulación'];
const TICKER_SPEED_PX_PER_SECOND = 52;

const FAQ = [
  {
    question: '¿Qué hace Umbral en la mañana de una redacción?',
    answer: 'Presenta cinco temas que pueden merecer revisión y explica por qué aparecen en la agenda. Desde allí puedes abrir la ficha de evidencia o preparar un borrador para revisión humana.',
  },
  {
    question: '¿Qué encuentro en la ficha de un tema?',
    answer: 'Las noticias agrupadas con sus medios y fechas, el contexto oficial disponible, las versiones que no coinciden y los puntos que todavía necesitan verificación.',
  },
  {
    question: '¿Puede escribir la nota por mí?',
    answer: 'Puede preparar un resumen, un guion y textos para redes con fuentes por afirmación. Una persona puede editar el borrador, aprobarlo como borrador, pedir evidencia o descartarlo. Umbral no publica.',
  },
  {
    question: '¿Y si le pregunto algo que no está en las fuentes?',
    answer: 'El Asistente de evidencia puede abstenerse cuando el material disponible no respalda una respuesta. Indica qué falta en lugar de presentar una cifra como comprobada.',
  },
  {
    question: '¿Cómo decide qué tema va primero?',
    answer: 'Aplica cinco criterios editoriales visibles: relevancia para Panamá, impacto, urgencia, novedad y evidencia. Sus pesos se pueden ajustar desde la configuración editorial dejando un motivo. El orden sirve para orientar la atención, no mide la verdad.',
  },
  {
    question: '¿Con qué datos trabaja hoy?',
    answer: 'La portada consulta el snapshot disponible: allí ves el total de titulares y metadatos, los temas de las seis categorías, la fecha de corte, su identificador y su estado. En Fuentes puedes revisar el detalle del corte y las fuentes incluidas.',
  },
  {
    question: '¿Es un producto oficial de TVN?',
    answer: 'No. Umbral es un prototipo creado para el hackIAthon Panamá 2026, en el reto propuesto por TVN Media.',
  },
];

type LandingData = { health: Health; articles: number | null; topics: number };

function countLabel(value: number | null | undefined, loading: boolean): string {
  if (loading) return 'Cargando…';
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'No disponible';
  return new Intl.NumberFormat('es-PA').format(value);
}

function cutoffLabel(cutoffUtc: string): string {
  const date = new Date(cutoffUtc);
  if (Number.isNaN(date.getTime())) return 'fecha no disponible';
  return new Intl.DateTimeFormat('es-PA', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'America/Panama',
  }).format(date);
}

function snapshotStatus(health: Health): string {
  const labels = [
    health.containsFixtures ? 'incluye datos de prueba' : health.provisional ? 'provisional' : 'corte disponible',
    health.offline ? 'sin conexión externa' : null,
    health.snapshotStale ? 'corte anterior' : null,
    health.integrity.manifestVerified ? 'manifest verificado' : 'integridad por confirmar',
  ].filter((label): label is string => Boolean(label));
  return labels.join(' · ');
}

function shouldReduceMotion(): boolean {
  if (typeof window === 'undefined') return true;
  const preference = document.documentElement.dataset.motionPreference;
  return preference === 'reduced' || (preference !== 'full' && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
}

export default function LandingExperience() {
  const [data, setData] = useState<LandingData | null>(null);
  const [statsFailed, setStatsFailed] = useState(false);
  const [loadingStats, setLoadingStats] = useState(true);
  const stepsRef = useRef<HTMLDivElement>(null);
  const tickerRef = useRef<HTMLElement>(null);
  const tickerTrackRef = useRef<HTMLDivElement>(null);
  const tickerCopyRef = useRef<HTMLDivElement>(null);
  const tickerMeasureRef = useRef<HTMLUListElement>(null);
  const [tickerRepetitions, setTickerRepetitions] = useState(1);
  const [tickerReady, setTickerReady] = useState(false);
  const [promiseOrder, setPromiseOrder] = useState<PromiseId[]>(PROMISES.map((promise) => promise.id));
  const [flipped, setFlipped] = useState<PromiseId | null>(null);
  const dragState = useRef<PromiseDrag | null>(null);
  const previousPromiseRects = useRef<Map<PromiseId, DOMRect> | null>(null);
  const [dragging, setDragging] = useState<PromiseId | null>(null);
  const [orderAnnouncement, setOrderAnnouncement] = useState('');
  const [openFaq, setOpenFaq] = useState<number | null>(null);

  useLayoutEffect(() => {
    const viewport = tickerRef.current;
    const track = tickerTrackRef.current;
    const measure = tickerMeasureRef.current;
    if (!viewport || !track || !measure) return;

    const updateTicker = () => {
      const viewportWidth = viewport.clientWidth;
      const sequenceWidth = measure.getBoundingClientRect().width;
      if (viewportWidth <= 0 || sequenceWidth <= 0) return;

      const repetitions = Math.max(1, Math.ceil(viewportWidth / sequenceWidth));
      const copy = tickerCopyRef.current;
      const groupWidth = copy?.getBoundingClientRect().width || sequenceWidth * repetitions;
      const renderedItems = copy?.querySelectorAll('li').length ?? 0;
      const durationSeconds = Math.max(11, groupWidth / TICKER_SPEED_PX_PER_SECOND);
      track.style.setProperty('--landing-marquee-duration', `${durationSeconds}s`);
      setTickerRepetitions((current) => current === repetitions ? current : repetitions);
      const isLoopReady = renderedItems === repetitions * CATEGORIES.length && groupWidth >= viewportWidth - 1;
      setTickerReady(isLoopReady);
    };

    const observer = new ResizeObserver(updateTicker);
    observer.observe(viewport);
    observer.observe(measure);
    if (tickerCopyRef.current) observer.observe(tickerCopyRef.current);
    updateTicker();
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const baseUrl = config.authMode === 'public' ? await resolvePublicApiUrl(controller.signal) : config.apiUrl;
        if (controller.signal.aborted) return;
        const api = new HttpApi(baseUrl, config.authMode === 'public' ? async () => null : getAuthToken);
        const [health, topics] = await Promise.all([
          api.health(),
          api.topics({ limit: 1, scope: 'in_scope' }),
        ]);
        if (controller.signal.aborted) return;
        if (health.snapshotId !== topics.snapshotId) throw new Error('Los datos corresponden a cortes distintos.');
        const articles = health.counts.articles;
        setData({ health, articles: typeof articles === 'number' ? articles : null, topics: topics.total });
      } catch {
        if (!controller.signal.aborted) setStatsFailed(true);
      } finally {
        if (!controller.signal.aborted) setLoadingStats(false);
      }
    })();
    return () => controller.abort();
  }, []);

  useLayoutEffect(() => {
    const previous = previousPromiseRects.current;
    previousPromiseRects.current = null;
    if (!previous) return;

    const moved: HTMLElement[] = [];
    document.querySelectorAll<HTMLElement>('.landing-promise-card[data-promise-id]').forEach((card) => {
      const id = card.dataset.promiseId as PromiseId | undefined;
      const before = id ? previous.get(id) : undefined;
      if (!before) return;
      const after = card.getBoundingClientRect();
      const x = before.left - after.left;
      const y = before.top - after.top;
      if (Math.abs(x) < 1 && Math.abs(y) < 1) return;
      card.style.transition = 'none';
      card.style.transform = `translate3d(${x}px, ${y}px, 0)`;
      moved.push(card);
    });

    if (!moved.length) return;
    void moved[0]?.getBoundingClientRect();
    const frame = window.requestAnimationFrame(() => {
      moved.forEach((card) => {
        card.style.removeProperty('transition');
        card.style.removeProperty('transform');
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [promiseOrder]);

  useEffect(() => {
    try {
      const stored = JSON.parse(window.localStorage.getItem(PROMISE_ORDER_KEY) ?? 'null') as unknown;
      if (!Array.isArray(stored)) return;
      const valid = stored.filter((value): value is PromiseId => PROMISES.some((promise) => promise.id === value));
      const merged = [...new Set(valid)];
      for (const promise of PROMISES) if (!merged.includes(promise.id)) merged.push(promise.id);
      setPromiseOrder(merged);
    } catch {
      // El orden predeterminado sigue disponible si el navegador bloquea o daña el almacenamiento local.
    }
  }, []);

  const scrollSteps = (direction: -1 | 1) => {
    const track = stepsRef.current;
    if (!track) return;
    track.scrollBy({ left: direction * Math.max(250, track.clientWidth * 0.78), behavior: shouldReduceMotion() ? 'auto' : 'smooth' });
  };

  const handleStepsKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      scrollSteps(event.key === 'ArrowLeft' ? -1 : 1);
    }
  };

  const movePromise = (from: number, to: number) => {
    if (from === to || from < 0 || to < 0 || from >= promiseOrder.length || to >= promiseOrder.length) return;
    previousPromiseRects.current = new Map(
      [...document.querySelectorAll<HTMLElement>('.landing-promise-card[data-promise-id]')]
        .map((card) => [card.dataset.promiseId as PromiseId, card.getBoundingClientRect()] as const),
    );
    const next = [...promiseOrder];
    const [moved] = next.splice(from, 1);
    if (!moved) return;
    next.splice(to, 0, moved);
    setPromiseOrder(next);
    try {
      window.localStorage.setItem(PROMISE_ORDER_KEY, JSON.stringify(next));
      setOrderAnnouncement(`${PROMISES.find((promise) => promise.id === moved)?.title ?? 'Tarjeta'} ahora ocupa la posición ${to + 1} de ${next.length}.`);
    } catch {
      setOrderAnnouncement('El orden cambió, pero no se pudo guardar en este navegador.');
    }
  };

  const startPromiseDrag = (event: ReactPointerEvent<HTMLButtonElement>, index: number, id: PromiseId) => {
    if (event.button !== 0) return;
    const card = event.currentTarget.closest<HTMLElement>('[data-promise-id]');
    if (!card) return;
    dragState.current = {
      from: index,
      id,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      card,
      dropTarget: null,
    };
    card.style.setProperty('--drag-x', '0px');
    card.style.setProperty('--drag-y', '0px');
    setDragging(id);
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const movePromiseDrag = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const drag = dragState.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    drag.card.style.setProperty('--drag-x', `${event.clientX - drag.startX}px`);
    drag.card.style.setProperty('--drag-y', `${event.clientY - drag.startY}px`);

    const target = document.elementsFromPoint(event.clientX, event.clientY)
      .map((element) => element.closest<HTMLElement>('[data-promise-id]'))
      .find((card): card is HTMLElement => Boolean(card && card.dataset.promiseId !== drag.id)) ?? null;
    if (drag.dropTarget !== target) {
      drag.dropTarget?.removeAttribute('data-drop-target');
      target?.setAttribute('data-drop-target', 'true');
      drag.dropTarget = target;
    }
  };

  const finishPromiseDrag = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const drag = dragState.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const dropTarget = document.elementsFromPoint(event.clientX, event.clientY)
      .map((element) => element.closest<HTMLElement>('[data-promise-id]'))
      .find((card): card is HTMLElement => Boolean(card && card.dataset.promiseId !== drag.id)) ?? drag.dropTarget;
    const targetId = dropTarget?.dataset.promiseId as PromiseId | undefined;
    const targetIndex = targetId ? promiseOrder.indexOf(targetId) : -1;
    let destination = -1;
    if (dropTarget && targetIndex >= 0) {
      const grid = dropTarget.parentElement;
      const columns = grid ? getComputedStyle(grid).gridTemplateColumns.split(/\s+/).filter(Boolean).length : 1;
      const targetBounds = dropTarget.getBoundingClientRect();
      const sameRow = Math.floor(drag.from / columns) === Math.floor(targetIndex / columns);
      const droppedAfter = sameRow
        ? event.clientX > targetBounds.left + targetBounds.width / 2
        : event.clientY > targetBounds.top + targetBounds.height / 2;
      destination = targetIndex + (droppedAfter ? 1 : 0);
      if (drag.from < destination) destination -= 1;
    }

    drag.dropTarget?.removeAttribute('data-drop-target');
    drag.card.classList.remove('is-dragging');
    drag.card.style.removeProperty('--drag-x');
    drag.card.style.removeProperty('--drag-y');
    dragState.current = null;
    setDragging(null);
    if (destination >= 0) movePromise(drag.from, destination);
  };

  const cancelPromiseDrag = () => {
    const drag = dragState.current;
    drag?.dropTarget?.removeAttribute('data-drop-target');
    drag?.card.classList.remove('is-dragging');
    drag?.card.style.removeProperty('--drag-x');
    drag?.card.style.removeProperty('--drag-y');
    dragState.current = null;
    setDragging(null);
  };

  const handlePromiseKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>, index: number) => {
    if (!event.altKey || (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight')) return;
    event.preventDefault();
    movePromise(index, index + (event.key === 'ArrowRight' ? 1 : -1));
  };

  const promiseById = new Map(PROMISES.map((promise) => [promise.id, promise]));

  return (
    <>
      <header className="landing-header comic-masthead">
        <div className="landing-header-inner">
          <a href="/" className="comic-brand" aria-label="Umbral, inicio">Umbral<span>.</span></a>
          <a href="/app/" className="landing-button landing-button-primary landing-header-cta">Abrir la aplicación</a>
        </div>
      </header>

      <main id="contenido" className="landing-main">
        <section className="landing-hero" aria-labelledby="landing-title">
          <div className="landing-hero-copy">
            <p className="landing-kicker"><span aria-hidden="true">●</span> Reto TVN Media · Copiloto de inteligencia informativa</p>
            <h1 id="landing-title" className="font-display">¿Qué cinco temas merecen revisión para la agenda de Panamá, y por qué?</h1>
            <p className="landing-intro">
              Umbral convierte noticias públicas e indicadores oficiales en una agenda priorizada, fichas de evidencia con procedencia y borradores para revisión humana. Ayuda a encontrar qué vale la pena mirar y deja claro qué falta comprobar; todavía no se ha medido cuánto tiempo ahorra.
            </p>
            <div className="comic-landing-actions landing-actions">
              <a href="/app/" className="landing-button landing-button-primary">Ver la agenda de hoy</a>
              <a href="#preguntas" className="landing-button landing-button-secondary">Preguntas frecuentes</a>
            </div>
          </div>

          <aside className="landing-stats" aria-label="Resumen del snapshot actual" aria-live="polite" aria-busy={loadingStats}>
            <div className="landing-stat">
              <strong>{countLabel(data?.articles, loadingStats)}</strong>
              <span>titulares y metadatos</span>
            </div>
            <div className="landing-stat landing-stat-offset">
              <strong>{countLabel(data?.topics, loadingStats)}</strong>
              <span>temas en las 6 categorías</span>
            </div>
            <div className="landing-stat landing-stat-featured">
              <strong>5</strong>
              <span>para revisar hoy, con su porqué</span>
            </div>
            <p className="landing-snapshot" data-testid="landing-snapshot-status">
              <Database size={16} aria-hidden="true" />
              {data ? (
                <span>
                  Corte <strong>{data.health.snapshotId}</strong> · {cutoffLabel(data.health.cutoffUtc)} · {snapshotStatus(data.health)}
                </span>
              ) : statsFailed ? (
                <span>Datos del snapshot no disponibles ahora.</span>
              ) : (
                <span>Consultando el snapshot activo…</span>
              )}
            </p>
          </aside>
        </section>

        <section ref={tickerRef} className="landing-ticker" aria-label="Categorías temáticas">
          <div ref={tickerTrackRef} className="landing-ticker-track" data-ready={tickerReady}>
            {[0, 1].map((copy) => (
              <div ref={copy === 0 ? tickerCopyRef : undefined} className="landing-ticker-copy" key={copy} aria-hidden={copy === 1}>
                <ul className="landing-ticker-list">
                  {Array.from({ length: tickerRepetitions }, (_, repetition) => CATEGORIES.map((category) => (
                    <li key={`${repetition}-${category}`}><span aria-hidden="true">●</span>{category}</li>
                  )))}
                </ul>
              </div>
            ))}
          </div>
          <ul ref={tickerMeasureRef} className="landing-ticker-list landing-ticker-measure" aria-hidden="true">
            {CATEGORIES.map((category) => <li key={category}><span aria-hidden="true">●</span>{category}</li>)}
          </ul>
        </section>

        <section className="landing-section landing-steps" aria-labelledby="landing-steps-title">
          <div className="landing-section-heading">
            <div>
              <p className="kicker">Cómo funciona</p>
              <h2 id="landing-steps-title" className="font-display">De la señal a la decisión, en cinco pasos</h2>
              <p className="landing-section-hint">Desplázate por las tarjetas o usa las flechas.</p>
            </div>
            <div className="landing-carousel-controls" aria-label="Controles de los pasos">
              <button type="button" className="landing-arrow" aria-label="Pasos anteriores" aria-controls="landing-steps-track" onClick={() => scrollSteps(-1)}>
                <ArrowLeft size={20} aria-hidden="true" />
              </button>
              <button type="button" className="landing-arrow" aria-label="Pasos siguientes" aria-controls="landing-steps-track" onClick={() => scrollSteps(1)}>
                <ArrowRight size={20} aria-hidden="true" />
              </button>
            </div>
          </div>
          <div
            id="landing-steps-track"
            className="landing-step-track"
            ref={stepsRef}
            role="region"
            aria-label="Cinco pasos de Umbral"
            tabIndex={0}
            onKeyDown={handleStepsKeyDown}
            data-testid="landing-steps-track"
          >
            <ol className="landing-step-list">
              {STEPS.map((step, index) => (
                <li className="landing-step comic-panel" key={step.title} data-testid={`landing-step-${index + 1}`}>
                  <span className="landing-step-number">{String(index + 1).padStart(2, '0')}</span>
                  <h3 className="font-display">{step.title}</h3>
                  <p>{step.description}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="landing-promise-section" aria-labelledby="landing-promises-title">
          <div className="landing-section landing-promise-content">
            <p className="kicker">Lo que Umbral promete, y lo que no</p>
            <h2 id="landing-promises-title" className="font-display">Confianza que se puede comprobar</h2>
            <p className="landing-section-hint">Voltea una tarjeta para ver su límite. Usa el asa para arrastrarla o pulsa Alt + flechas para reordenar.</p>
            <div className="landing-promise-grid" data-testid="landing-promise-grid">
              {promiseOrder.map((id, index) => {
                const promise = promiseById.get(id)!;
                const isFlipped = flipped === id;
                return (
                  <article
                    className={`landing-promise-card${dragging === id ? ' is-dragging' : ''}`}
                    key={id}
                    data-promise-id={id}
                    data-order={index + 1}
                    data-testid={`landing-promise-${id}`}
                  >
                    <div className="landing-promise-plane" data-flipped={isFlipped}>
                      <button
                        type="button"
                        className="landing-promise-flip"
                        aria-label={`${isFlipped ? 'Mostrar promesa' : 'Mostrar límite'}: ${promise.title}`}
                        aria-pressed={isFlipped}
                        onClick={() => setFlipped(isFlipped ? null : id)}
                      >
                        <span className="landing-promise-face landing-promise-front" aria-hidden={isFlipped}>
                          <span className="landing-promise-label">Sí</span>
                          <strong className="font-display">{promise.title}</strong>
                          <span className="landing-promise-copy">{promise.yes}</span>
                          <span className="landing-promise-hint">Voltea para ver el límite ↻</span>
                        </span>
                        <span className="landing-promise-face landing-promise-back" aria-hidden={!isFlipped}>
                          <span className="landing-promise-label">Hasta aquí</span>
                          <strong className="font-display">{promise.title}</strong>
                          <span className="landing-promise-copy">{promise.limit}</span>
                          <span className="landing-promise-hint">Voltea para ver la promesa ↻</span>
                        </span>
                      </button>
                    </div>
                    <button
                      type="button"
                      className="landing-promise-handle"
                      aria-label={`Mover ${promise.title}. Usa Alt y las flechas izquierda o derecha para cambiar su orden.`}
                      onKeyDown={(event) => handlePromiseKeyDown(event, index)}
                      onPointerDown={(event) => startPromiseDrag(event, index, id)}
                      onPointerMove={movePromiseDrag}
                      onPointerUp={finishPromiseDrag}
                      onPointerCancel={cancelPromiseDrag}
                      data-testid={`landing-promise-handle-${id}`}
                    >
                      <GripVertical size={20} aria-hidden="true" />
                    </button>
                  </article>
                );
              })}
            </div>
            <p className="sr-only" role="status" aria-live="polite">{orderAnnouncement}</p>
          </div>
        </section>

        <section id="preguntas" className="landing-section landing-faq" aria-labelledby="landing-faq-title">
          <p className="kicker">Preguntas frecuentes</p>
          <h2 id="landing-faq-title" className="font-display">Lo que pregunta una mesa editorial</h2>
          <div className="landing-faq-list">
            {FAQ.map((item, index) => (
              <Disclosure
                key={item.question}
                summary={item.question}
                open={openFaq === index}
                onOpenChange={(next) => setOpenFaq(next ? index : null)}
                testId={`landing-faq-${index + 1}`}
                className="landing-faq-item"
                triggerClassName="landing-faq-trigger"
              >
                <p>{item.answer}</p>
              </Disclosure>
            ))}
          </div>
          <div className="landing-final-cta">
            <h2 className="font-display">¿Listo para ver la agenda de hoy?</h2>
            <a href="/app/" className="landing-button landing-button-primary">Entrar a Umbral</a>
          </div>
        </section>
      </main>

      <footer className="landing-footer">
        <div className="landing-footer-inner mx-auto max-w-5xl px-4 py-7">
          <section className="jury-links" aria-labelledby="jury-links-title">
            <div className="jury-links-heading">
              <p className="kicker">Para el jurado</p>
              <h2 id="jury-links-title" className="font-display text-2xl font-bold">Umbral, por dentro y en contexto</h2>
              <p className="text-sm">Tres lecturas para recorrer la solución, su experiencia y la propuesta.</p>
            </div>
            <nav className="jury-links-grid" aria-label="Documentos de Umbral para el jurado">
              <a className="jury-link-card" href="/jurado/documentacion-tecnica/">
                <span className="jury-link-number" aria-hidden="true">01</span>
                <span><strong>Documentación técnica</strong><small>Arquitectura, datos y trazabilidad</small></span>
                <span className="jury-link-arrow" aria-hidden="true">↗</span>
              </a>
              <a className="jury-link-card" href="/jurado/documentacion-funcional/">
                <span className="jury-link-number" aria-hidden="true">02</span>
                <span><strong>Documentación funcional</strong><small>Flujo editorial y decisiones humanas</small></span>
                <span className="jury-link-arrow" aria-hidden="true">↗</span>
              </a>
              <a className="jury-link-card" href="/jurado/pitch-day/">
                <span className="jury-link-number" aria-hidden="true">03</span>
                <span><strong>Presentación Pitch Day</strong><small>Recorrido, guion y preguntas del jurado</small></span>
                <span className="jury-link-arrow" aria-hidden="true">↗</span>
              </a>
            </nav>
          </section>
          <p className="landing-footer-note">
          Prototipo creado para el hackIAthon Panamá 2026, en el reto propuesto por TVN Media. No es un producto oficial de TVN. Licencia MIT. Los resultados son borradores y señales para revisión humana; Umbral no publica nada de forma automática.
          </p>
        </div>
      </footer>
    </>
  );
}
