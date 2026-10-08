import { useEffect, useId, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useApp } from './context';
import { useHealth, useRules, useUpdateRules } from '../lib/hooks';
import { ApiError } from '../lib/api/client';
import type { Rules } from '../lib/api/types';
import { fmtDateTime } from '../lib/format';
import { Button, Card, ErrorBox, Field, Loading, Notice, SectionTitle, inputCls } from './ui';
import { Disclosure, NumberField, Select } from './ui/controls';

const COMPONENTS = [['R', 'Relevancia'], ['I', 'Impacto'], ['U', 'Urgencia'], ['N', 'Novedad'], ['E', 'Evidencia']] as const;

function RulesForm({ rules }: { rules: Rules }) {
  const { api, reviewer } = useApp();
  const query = useRules();
  const mutation = useUpdateRules();
  const id = useId();
  // El formulario conserva la versión leída. Una actualización concurrente requiere recarga explícita.
  const [base, setBase] = useState(rules);
  const [weights, setWeights] = useState<Record<string, number>>({ ...rules.weights });
  const [author, setAuthor] = useState(reviewer);
  const [reason, setReason] = useState('');
  const [saved, setSaved] = useState<string | null>(null);
  const sum = COMPONENTS.reduce((n, [key]) => n + (weights[key] ?? NaN), 0);
  const valid = sum === 100 && COMPONENTS.every(([key]) => { const value = weights[key] ?? NaN; return Number.isInteger(value) && value >= 0 && value <= 100; });
  const disabled = api.kind === 'mock' || mutation.isPending;
  const reload = async () => {
    const result = await query.refetch();
    if (result.data) { setBase(result.data); setWeights({ ...result.data.weights }); mutation.reset(); setSaved(null); }
  };
  return (
    <form noValidate data-testid="rules-editor" className="space-y-3" onSubmit={async (event) => {
      event.preventDefault(); setSaved(null);
      try {
        const result = await mutation.mutateAsync({ expectedVersion: base.version, weights, author: author.trim(), reason: reason.trim() });
        setBase(result); setWeights({ ...result.weights }); setReason(''); setSaved(`Política guardada: ${result.rulesVersion}. La agenda se ha actualizado.`);
      } catch { /* La mutación muestra el fallo; mantiene los valores para que el usuario los revise. */ }
    }}>
      <p className="text-sm text-ink-2">Ajusta qué merece atención. Cada cambio conserva su responsable, motivo y versión; las categorías y la evidencia mantienen sus reglas.</p>
      {api.kind === 'mock' && <Notice tone="warn" title="Edición no disponible en demostración" />}
      <div data-testid="rules-weight-grid" className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {COMPONENTS.map(([key, label]) => <Field key={key} htmlFor={`${id}-${key}`} label={`${key} · ${label}`}>
          <NumberField id={`${id}-${key}`} testId={`rules-weight-${key}`} disabled={disabled} value={weights[key] ?? Number.NaN} onValueChange={(n) => { setWeights({ ...weights, [key]: n }); setSaved(null); }} />
        </Field>)}
      </div>
      <p data-testid="rules-sum" className={`text-sm font-semibold ${valid ? 'text-ok' : 'text-bad'}`}>Suma: {Number.isFinite(sum) ? sum : '—'} / 100</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field htmlFor={`${id}-author`} label="Responsable"><input id={`${id}-author`} data-testid="rules-author" value={author} onChange={(e) => setAuthor(e.target.value)} aria-required="true" maxLength={120} disabled={disabled} className={inputCls} /></Field>
        <Field htmlFor={`${id}-reason`} label="Motivo del cambio"><input id={`${id}-reason`} data-testid="rules-reason" value={reason} onChange={(e) => setReason(e.target.value)} aria-required="true" maxLength={2000} disabled={disabled} className={inputCls} /></Field>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant="primary" busy={mutation.isPending} disabled={disabled || !valid || !author.trim() || !reason.trim()} data-testid="rules-save">Guardar pesos</Button>
        <Button onClick={reload} busy={query.isFetching} disabled={mutation.isPending}>Recargar política vigente</Button>
      </div>
      {mutation.error && <ErrorBox error={mutation.error} />}
      {mutation.error instanceof ApiError && mutation.error.isConflict && <Notice tone="warn" title="La política cambió mientras editabas">Recarga la política vigente antes de enviar otra versión. Tus cambios no se sobrescribieron.</Notice>}
      {saved && <Notice tone="ok" role="status" testId="rules-saved" stamp>{saved}</Notice>}
      <p className="text-xs text-ink-3">Versión del formulario: {base.rulesVersion} · {base.version}. Los casos ya guardados conservan la política de su último cambio.</p>
      <Disclosure testId="rules-history" summary={<span className="text-sm font-semibold">Historial de pesos ({rules.history.length})</span>}>
        <ol className="mt-2 space-y-2 text-sm">
          {rules.history.map((revision) => <li key={revision.version} className="border-l-2 border-rule-strong pl-3"><strong>{revision.rulesVersion}</strong> · {revision.author} · {fmtDateTime(revision.at)}<p>{revision.reason}</p><p className="font-mono text-xs">{COMPONENTS.map(([key]) => `${key}=${revision.weights[key]}`).join(' · ')}</p></li>)}
        </ol>
      </Disclosure>
    </form>
  );
}

export function RulesEditor() {
  const query = useRules();
  return <Card data-testid="rules-editor-card"><SectionTitle kicker="Decisión editorial">Pesos e historial del ranking</SectionTitle>
    {query.isLoading ? <Loading /> : query.error ? <ErrorBox error={query.error} onRetry={() => query.refetch()} /> : query.data && <RulesForm rules={query.data} />}
  </Card>;
}

function LocalConnections({ offline }: { offline: boolean }) {
  const { api } = useApp();
  const qc = useQueryClient();
  const [label, setLabel] = useState('Cuenta ChatGPT');
  const [authorizationUrl, setAuthorizationUrl] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [oauthPending, setOauthPending] = useState(false);
  const oauthFingerprint = useRef('');
  const oauthTimer = useRef<number | undefined>(undefined);
  const status = useQuery({
    queryKey: ['chatgpt-connections'],
    queryFn: () => api.connections(),
    refetchInterval: oauthPending ? 1500 : false,
  });
  const models = useQuery({ queryKey: ['chatgpt-models', status.data?.activeProfileId], queryFn: () => api.connectionModels(), enabled: !offline && Boolean(status.data?.activeProfileId), retry: false });
  const refresh = async () => { await Promise.all([qc.invalidateQueries({ queryKey: ['chatgpt-connections'] }), qc.invalidateQueries({ queryKey: ['chatgpt-models'] }), qc.invalidateQueries({ queryKey: ['health'] })]); };
  useEffect(() => {
    if (!oauthPending || !status.data) return;
    const fingerprint = JSON.stringify(status.data.profiles.map((p) => [p.profileId, p.connected, p.active]));
    if (fingerprint !== oauthFingerprint.current && status.data.profiles.some((p) => p.active && p.connected)) {
      setOauthPending(false);
      window.clearTimeout(oauthTimer.current);
      setNotice('Sesión de ChatGPT reconocida en este equipo.');
      void qc.invalidateQueries({ queryKey: ['health'] });
    }
  }, [oauthPending, status.data, qc]);
  useEffect(() => () => window.clearTimeout(oauthTimer.current), []);
  const change = useMutation({ mutationFn: async (action: { kind: 'start' | 'select' | 'model' | 'disconnect'; value: string }) => {
    setNotice(null);
    if (action.kind === 'start') {
      oauthFingerprint.current = JSON.stringify(status.data?.profiles.map((p) => [p.profileId, p.connected, p.active]) ?? []);
      setOauthPending(true);
      const result = await api.startConnection({ label: action.value });
      const url = new URL(result.authorizationUrl);
      if (url.protocol !== 'https:' || url.hostname !== 'auth.openai.com' || url.username || url.password) throw new Error('El servicio devolvió una dirección de autenticación inesperada.');
      setAuthorizationUrl(url.href); setNotice(`Enlace preparado. Inicia sesión antes de ${fmtDateTime(result.expiresIn ? new Date(Date.now() + result.expiresIn * 1000).toISOString() : null)}.`);
      window.clearTimeout(oauthTimer.current);
      oauthTimer.current = window.setTimeout(() => {
        setOauthPending(false);
        setNotice('El inicio OAuth expiró. Puedes volver a iniciarlo.');
      }, Math.max(1, result.expiresIn ?? 600) * 1000);
    } else if (action.kind === 'select') { await api.selectConnection(action.value); await refresh(); }
    else if (action.kind === 'model') { await api.selectConnectionModel(action.value); await refresh(); }
    else { const result = await api.disconnect(action.value); setNotice(result.note); setAuthorizationUrl(null); setOauthPending(false); window.clearTimeout(oauthTimer.current); await refresh(); }
  }, onError: () => setOauthPending(false) });
  if (status.isLoading) return <Loading label="Consultando conexiones locales…" />;
  return <div className="space-y-3" data-testid="local-connections">
    <p className="text-sm text-ink-2">La conexión usa tu cuenta personal. Los perfiles y tokens se guardan en este equipo; el catálogo corresponde a la cuenta elegida.</p>
    {offline && <Notice tone="info" title="Modo sin conexión">Los perfiles guardados siguen visibles. Inicia sesión, consulta modelos o cierra la sesión cuando vuelvas a habilitar la conexión.</Notice>}
    {status.error && <ErrorBox error={status.error} onRetry={() => status.refetch()} />}
    {status.data?.reason && <p className="text-sm text-ink-3">{status.data.reason}</p>}
    <div className="flex flex-wrap items-end gap-2">
      <Field htmlFor="chatgpt-profile-label" label="Nombre del perfil"><input id="chatgpt-profile-label" className={inputCls} value={label} maxLength={120} onChange={(e) => setLabel(e.target.value)} disabled={offline || change.isPending} /></Field>
      <Button disabled={offline || change.isPending || !label.trim()} onClick={() => change.mutate({ kind: 'start', value: label.trim() })}>Iniciar sesión con ChatGPT</Button>
      <Button onClick={refresh} disabled={change.isPending}>Actualizar conexión</Button>
    </div>
    {oauthPending && <p role="status" className="text-sm text-ink-2">Esperando la confirmación OAuth de ChatGPT…</p>}
    {authorizationUrl && <a href={authorizationUrl} target="_blank" rel="noreferrer noopener" className="inline-block font-semibold underline underline-offset-4" data-testid="chatgpt-login-link">Abrir inicio de sesión de ChatGPT ↗</a>}
    <ul className="space-y-2">
      {status.data?.profiles.map((profile) => <li key={profile.profileId} className="flex flex-wrap items-center justify-between gap-2 border border-rule p-3 text-sm"><div><strong>{profile.label}</strong> {profile.active ? '· activo' : ''}<p>{profile.email ?? 'Cuenta sin correo disponible'} · {profile.connected ? 'Credenciales guardadas' : 'Desconectado'}</p>{profile.model && <p>Modelo: {profile.model}</p>}</div><div className="flex flex-wrap gap-2"><Button disabled={offline || change.isPending || profile.active || !profile.connected} onClick={() => change.mutate({ kind: 'select', value: profile.profileId })}>Seleccionar</Button><Button disabled={offline || change.isPending || !profile.connected} onClick={() => change.mutate({ kind: 'disconnect', value: profile.profileId })}>Cerrar sesión</Button></div></li>)}
    </ul>
    {models.isFetching && <Loading label="Consultando catálogo de la cuenta…" />}
    {models.error && <ErrorBox error={models.error} onRetry={() => models.refetch()} />}
    {models.data && <Field htmlFor="chatgpt-model" label="Modelo de la cuenta activa"><Select id="chatgpt-model" testId="chatgpt-model" value={models.data.selectedModel ?? ''} disabled={offline || change.isPending} placeholder="Selecciona un modelo" onChange={(value) => change.mutate({ kind: 'model', value })} options={models.data.models.map((model) => ({ value: model.slug, label: model.displayName }))} /></Field>}
    {change.error && <ErrorBox error={change.error} />}
    {notice && <Notice tone="info" role="status">{notice}</Notice>}
  </div>;
}

function LocalClaudeConnection({ offline }: { offline: boolean }) {
  const { api } = useApp();
  const qc = useQueryClient();
  const [notice, setNotice] = useState<string | null>(null);
  const status = useQuery({
    queryKey: ['claude-connection'],
    queryFn: () => api.claudeConnection(),
    refetchInterval: (query) => query.state.data?.loginPending ? 1500 : false,
  });
  const refresh = async () => { await Promise.all([qc.invalidateQueries({ queryKey: ['claude-connection'] }), qc.invalidateQueries({ queryKey: ['health'] })]); };
  useEffect(() => { if (status.data?.loggedIn) void qc.invalidateQueries({ queryKey: ['health'] }); }, [qc, status.data?.loggedIn]);
  const action = useMutation({
    mutationFn: (kind: 'login' | 'logout') => kind === 'login' ? api.startClaudeLogin() : api.claudeLogout(),
    onSuccess: async (connection) => {
      setNotice(connection.loggedIn ? 'Sesión de Claude reconocida en este equipo.' : connection.loginPending ? 'Claude abrió el inicio de sesión oficial; esperando la confirmación…' : connection.reason ?? 'Estado de Claude actualizado.');
      await refresh();
    },
  });
  const command = status.data?.loginCommand ?? 'claude auth login --claudeai';
  async function copyCommand() {
    try {
      await navigator.clipboard.writeText(command);
      setNotice('Comando copiado. Ejecútalo en una terminal de este equipo y actualiza la sesión después.');
    } catch { setNotice(`Ejecuta este comando en una terminal de este equipo: ${command}`); }
  }
  const commandFromError = action.error instanceof ApiError ? action.error.details?.command : null;
  return <div className="space-y-3" data-testid="claude-connection">
    <p className="text-sm text-ink-2">Umbral reconoce la sesión del CLI oficial de Claude. No importa credenciales ni sesiones de otras aplicaciones; solo usa tu suscripción, nunca una clave de API.</p>
    {status.isLoading && <Loading label="Consultando sesión local de Claude…" />}
    {status.error && <ErrorBox error={status.error} onRetry={() => status.refetch()} />}
    {status.data?.reason && <p className="text-sm text-ink-3" data-testid="claude-connection-reason">{status.data.reason}</p>}
    {status.data?.loggedIn && <p className="text-sm" data-testid="claude-connection-account">Sesión abierta{status.data.account ? ` · ${status.data.account}` : ''}{status.data.authMethod ? ` · ${status.data.authMethod}` : ''}</p>}
    {status.data?.loginPending && <p className="text-sm text-ink-2" role="status">Esperando la confirmación en el navegador…</p>}
    <div className="flex flex-wrap gap-2">
      <Button disabled={offline || action.isPending || !status.data?.installed || status.data.loggedIn || status.data.loginPending} busy={action.isPending && !status.data?.loggedIn} onClick={() => action.mutate('login')}>Iniciar sesión con Claude</Button>
      {status.data?.loggedIn && <Button disabled={offline || action.isPending} onClick={() => action.mutate('logout')}>Cerrar sesión de Claude</Button>}
      <Button variant="ghost" disabled={action.isPending} onClick={refresh}>Actualizar sesión</Button>
    </div>
    {status.data && !status.data.loggedIn && !status.data.loginPending && <div className="flex flex-wrap items-center gap-2"><p className="text-xs text-ink-3">Si el inicio automático no abrió el navegador, ejecuta:</p><code className="rounded border border-rule bg-sunk px-2 py-1 text-sm">{command}</code><Button variant="ghost" onClick={() => void copyCommand()}>Copiar comando</Button></div>}
    {typeof commandFromError === 'string' && <div className="flex flex-wrap items-center gap-2"><code className="rounded border border-rule bg-sunk px-2 py-1 text-sm">{commandFromError}</code><Button variant="ghost" onClick={() => void copyCommand()}>Copiar comando</Button></div>}
    {action.error && <ErrorBox error={action.error} />}
    {notice && <Notice tone="info" role="status">{notice}</Notice>}
  </div>;
}

export function ConnectionsCard() {
  const { api, authMode } = useApp();
  const health = useHealth();
  const eligible = api.kind === 'live' && authMode === 'local' && health.data?.localMode && health.data.authMode === 'local';
  const unavailable = <Notice title="Disponible en la aplicación local">Abre Umbral en localhost con su API local para conectar una cuenta personal.</Notice>;
  return <div data-testid="connections-card" className="space-y-4">
    <Card><SectionTitle kicker="Opcional · OAuth local">Conexión ChatGPT</SectionTitle>
      {health.isLoading ? <Loading /> : eligible ? <LocalConnections offline={health.data?.offline ?? true} /> : unavailable}
    </Card>
    <Card><SectionTitle kicker="Opcional · sesión del CLI oficial">Conexión Claude</SectionTitle>
      {health.isLoading ? <Loading /> : eligible ? <LocalClaudeConnection offline={health.data?.offline ?? true} /> : unavailable}
    </Card>
  </div>;
}
