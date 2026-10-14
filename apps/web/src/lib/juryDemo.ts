// Demostración para el jurado: unos pocos titulares REALES del corte provisional 20261007-e704e952 (7 de octubre de 2026).
// Solo se muestran al rol Jurado cuando no hay noticias vigentes; el resto de la aplicación queda vacía hasta que llegue
// un corte fresco. Son metadatos de titulares con su enlace original (sin cuerpos), tal como están en el snapshot; no se
// inventa nada y la pantalla los rotula como demostración con la fecha de su corte.

export const JURY_DEMO_SNAPSHOT = '20261007-e704e952';
export const JURY_DEMO_CUTOFF_UTC = '2026-10-07T08:14:34Z';

export interface JuryDemoItem {
  id: string;
  title: string;
  categoryLabel: string;
  outlet: string;
  url: string;
  /** Publicación original (UTC), tal como la declara la fuente. */
  publishedAt: string;
}

export const JURY_DEMO_ITEMS: readonly JuryDemoItem[] = [
  {
    id: 'evt_0fc2be4daea069a8',
    title: 'Sinaproc extiende vigilancia por lluvias, tormentas y vientos hasta el viernes',
    categoryLabel: 'Servicios públicos',
    outlet: 'TVN Panamá',
    url: 'https://www.tvn-2.com/nacionales/sinaproc-extiende-vigilancia-lluvias-tormentas_1_2264646.html',
    publishedAt: '2026-10-06T20:51:59Z',
  },
  {
    id: 'evt_39f64782bc12951d',
    title: 'Apoyo a la democracia cae nueve puntos en Panamá; 78% no se siente representado por la Asamblea Nacional',
    categoryLabel: 'Regulación',
    outlet: 'TVN Panamá',
    url: 'https://www.tvn-2.com/nacionales/apoyo-democracia-cae-nueve-puntos-panama-asamblea-nacional_1_2264617.html',
    publishedAt: '2026-10-06T22:11:48Z',
  },
  {
    id: 'evt_298857731d639d20',
    title: 'Aumentan enfermedades respiratorias entre menores en la comarca Ngäbe Buglé',
    categoryLabel: 'Servicios públicos',
    outlet: 'TVN Panamá',
    url: 'https://www.tvn-2.com/nacionales/aumentan-enfermedades-respiratorias-menores-comarca_1_2264708.html',
    publishedAt: '2026-10-07T00:17:42Z',
  },
  {
    id: 'evt_340bc1f6642b7bcf',
    title: 'Comisión de Presupuesto tramita traslados y créditos por casi $100 millones entre seis instituciones',
    categoryLabel: 'Economía',
    outlet: 'TVN Panamá',
    url: 'https://www.tvn-2.com/nacionales/comision-presupuesto-tramita-traslados-creditos_1_2264698.html',
    publishedAt: '2026-10-07T00:21:09Z',
  },
  {
    id: 'evt_735a54c778afb35e',
    title: 'Panama Canal Increases Daily Transits to 33 and Maximum Draft to 49 Feet .',
    categoryLabel: 'Logística / Canal',
    outlet: 'newsroompanama.com',
    url: 'https://newsroompanama.com/2026/09/28/panama-canal-increases-daily-transits-to-33-and-maximum-draft-to-49-feet/',
    publishedAt: '2026-09-28T00:00:00Z',
  },
];
