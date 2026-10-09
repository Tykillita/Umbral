import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { PlugZap, Settings, Unplug } from 'lucide-react';
import type { ConnectorProvider, ReviewStatus, SlackNotificationPreferences } from '../lib/api/types';
import { REVIEW_LABEL } from '../lib/labels';
import { getThemePreference, persistThemePreference, type ThemePreference } from '../lib/themePreference';
import { useApp } from './context';
import { ConnectionsCard } from './EditorialSettings';
import { DesktopUpdateSettings } from './DesktopUpdateSettings';
import { Button, ErrorBox, Field, Loading, Notice, SectionTitle } from './ui';
import { Checkbox, Modal, MotionPreferenceSwitch, Select } from './ui/controls';

const REVIEW_STATES: ReviewStatus[] = ['en_revision', 'requiere_evidencia', 'aprobado_como_borrador', 'descartado'];

function PublicConnectors() {
  const { api, authMode, showToast } = useApp();
  const queryClient = useQueryClient();
  const isPublic = authMode === 'public';
  const [authorizationUrls, setAuthorizationUrls] = useState<Partial<Record<ConnectorProvider, string>>>({});
  const overview = useQuery({
    queryKey: ['connector-overview'],
    queryFn: () => api.connectorOverview!(),
    enabled: isPublic && api.kind === 'live' && !!api.connectorOverview,
    refetchOnWindowFocus: true,
    retry: false,
  });
  const pages = useQuery({
    queryKey: ['notion-pages'],
    queryFn: () => api.notionPages!(),
    enabled: isPublic && !!overview.data?.providers.notion.connected && !!api.notionPages,
    refetchOnWindowFocus: true,
    retry: false,
  });
  const channels = useQuery({
    queryKey: ['slack-channels'],
    queryFn: () => api.slackChannels!(),
    enabled: isPublic && !!overview.data?.providers.slack.connected && !!api.slackChannels,
    refetchOnWindowFocus: true,
    retry: false,
  });
  const [preferences, setPreferences] = useState<SlackNotificationPreferences>({ enabled: false, channelId: null, statuses: [] });
  useEffect(() => {
    if (overview.data) setPreferences({
      enabled: overview.data.slackNotifications.enabled,
      channelId: overview.data.providers.slack.channelId,
      statuses: [...overview.data.slackNotifications.statuses],
    });
  }, [overview.data]);

  const start = useMutation({
    mutationFn: (provider: ConnectorProvider) => api.startConnector!(provider),
    onSuccess: ({ authorizationUrl }, provider) => setAuthorizationUrls((current) => ({ ...current, [provider]: authorizationUrl })),
    onError: (error) => showToast({ tone: 'error', title: 'No se pudo iniciar la conexión', description: error instanceof Error ? error.message : 'Inténtalo de nuevo.' }),
  });
  const disconnect = useMutation({
    mutationFn: (provider: ConnectorProvider) => api.disconnectConnector!(provider),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ['connector-overview'] }); showToast({ tone: 'success', title: 'Conexión cerrada', description: 'Se eliminaron las credenciales guardadas en el servidor.' }); },
  });
  const chooseNotion = useMutation({
    mutationFn: (pageId: string) => api.chooseNotionDestination!(pageId),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ['connector-overview'] }); showToast({ tone: 'success', title: 'Destino de Notion guardado', description: 'Las próximas fichas se crearán en esa página.' }); },
  });
  const chooseChannel = useMutation({
    mutationFn: (channelId: string) => api.chooseSlackChannel!(channelId),
    onSuccess: async (_, channelId) => {
      setPreferences((current) => ({ ...current, channelId }));
      await queryClient.invalidateQueries({ queryKey: ['connector-overview'] });
      await queryClient.invalidateQueries({ queryKey: ['slack-channels'] });
    },
  });
  const savePreferences = useMutation({
    mutationFn: (value: SlackNotificationPreferences) => api.saveSlackNotificationPreferences!(value),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ['connector-overview'] }); showToast({ tone: 'success', title: 'Avisos de Slack guardados', description: 'La preferencia quedó asociada a esta identidad anónima.' }); },
  });

  const providerError = start.error ?? disconnect.error ?? chooseNotion.error ?? chooseChannel.error ?? savePreferences.error;
  const integrationMessage = useMemo(() => {
    if (!isPublic) return 'Notion y Slack se conectan en la web pública. ChatGPT y Claude conservan aquí sus conexiones locales.';
    if (overview.isLoading) return 'Consultando las conexiones protegidas de este navegador…';
    if (overview.error) return 'Para proteger las credenciales se requiere Firebase Auth anónima. Esta identidad no añade una cuenta visible.';
    return null;
  }, [isPublic, overview.error, overview.isLoading]);

  const updateStatus = (status: ReviewStatus, checked: boolean) => {
    const statuses = checked ? [...new Set([...preferences.statuses, status])] : preferences.statuses.filter((item) => item !== status);
    const next = { ...preferences, statuses, enabled: preferences.enabled && statuses.length > 0 };
    setPreferences(next);
    savePreferences.mutate(next);
  };

  const updateEnabled = (enabled: boolean) => {
    const next = { ...preferences, enabled: enabled && !!preferences.channelId && preferences.statuses.length > 0 };
    setPreferences(next);
    savePreferences.mutate(next);
  };

  return <div className="space-y-3" data-testid="public-connectors">
    <p className="text-xs text-ink-3">Las credenciales se cifran en el servidor y se separan por identidad anónima del navegador. Umbral no muestra ni guarda tokens en el dispositivo.</p>
    {integrationMessage && <Notice tone={overview.error ? 'warn' : 'info'} role={overview.error ? 'alert' : undefined}>{integrationMessage}</Notice>}
    {providerError && <ErrorBox error={providerError} />}
    {isPublic && overview.isLoading && <Loading label="Consultando conectores…" />}

    {(['notion', 'slack'] as const).map((provider) => {
      const state = overview.data?.providers[provider];
      const notionState = provider === 'notion' ? overview.data?.providers.notion : null;
      const slackState = provider === 'slack' ? overview.data?.providers.slack : null;
      const title = provider === 'notion' ? 'Notion' : 'Slack';
      return <section key={provider} className="space-y-3 border-t border-rule pt-3" data-testid={`connector-${provider}`}>
        <div className="settings-provider-row">
          <div className="settings-provider-copy">
            <strong>{title}</strong>
            <p>{!isPublic ? 'Conexión pública disponible en la web alojada.' : state?.connected ? `Conectado${state.workspaceName ? ` · ${state.workspaceName}` : ''}` : state?.available ? 'Aún no conectado' : 'No disponible en esta instalación'}</p>
          </div>
          {!isPublic ? <span className="text-xs text-ink-3">Web pública</span> : state?.connected ? (
            <Button variant="ghost" icon={Unplug} disabled={disconnect.isPending} onClick={() => disconnect.mutate(provider)}>Desconectar</Button>
          ) : (
            authorizationUrls[provider] ? <a className="comic-button inline-flex min-h-11 items-center gap-2 border border-ink bg-amber-300 px-3.5 py-2 text-sm font-semibold text-ink" href={authorizationUrls[provider]} target="_blank" rel="noopener noreferrer" onClick={() => setAuthorizationUrls((current) => ({ ...current, [provider]: undefined }))}>Autorizar en {title} ↗</a> :
              <Button icon={PlugZap} disabled={!state?.available || start.isPending} busy={start.isPending && start.variables === provider} onClick={() => start.mutate(provider)}>Conectar</Button>
          )}
        </div>
        {notionState?.connected && isPublic && <>
          {pages.isLoading ? <Loading label="Buscando páginas accesibles…" /> : pages.error ? <ErrorBox error={pages.error} onRetry={() => pages.refetch()} /> : pages.data?.length ? (
            <Field htmlFor="notion-destination" label="Página de destino">
              <Select id="notion-destination" testId="notion-destination" value={notionState.destinationId ?? ''} disabled={chooseNotion.isPending} placeholder="Elige una página compartida" onChange={(value) => chooseNotion.mutate(value)} options={pages.data.map((page) => ({ value: page.id, label: page.title }))} />
            </Field>
          ) : <Notice tone="info">No hay páginas accesibles para esta conexión. Vuelve a Notion y comparte una página con Umbral.</Notice>}
          {notionState.destinationTitle && <p className="text-xs text-ink-3">Destino actual: {notionState.destinationTitle}</p>}
        </>}
        {slackState?.connected && isPublic && <>
          {channels.isLoading ? <Loading label="Buscando canales accesibles…" /> : channels.error ? <ErrorBox error={channels.error} onRetry={() => channels.refetch()} /> : channels.data?.length ? (
            <Field htmlFor="slack-channel" label="Canal de avisos y compartir">
              <Select id="slack-channel" testId="slack-channel" value={preferences.channelId ?? slackState.channelId ?? ''} disabled={chooseChannel.isPending} placeholder="Elige un canal" onChange={(value) => chooseChannel.mutate(value)} options={channels.data.map((channel) => ({ value: channel.id, label: `${channel.isPrivate ? 'Privado · ' : ''}#${channel.name}` }))} />
            </Field>
          ) : <Notice tone="info">No hay canales accesibles. Añade Umbral al canal y actualiza la lista.</Notice>}
          <div className="space-y-2 border-t border-rule pt-3">
            <h4 className="font-semibold">Avisos automáticos de revisión</h4>
            <p className="text-xs text-ink-3">Desactivados hasta que elijas un canal y selecciones estados.</p>
            {REVIEW_STATES.map((status) => <Checkbox key={status} testId={`slack-status-${status}`} checked={preferences.statuses.includes(status)} disabled={!preferences.channelId || savePreferences.isPending} onChange={(checked) => updateStatus(status, checked)}>{REVIEW_LABEL[status]}</Checkbox>)}
            <Checkbox testId="slack-auto-notifications" checked={preferences.enabled} disabled={!preferences.channelId || preferences.statuses.length === 0 || savePreferences.isPending} onChange={updateEnabled}>Enviar avisos cuando cambie uno de esos estados</Checkbox>
          </div>
          <Button variant="ghost" disabled={channels.isFetching} onClick={() => channels.refetch()}>Actualizar canales</Button>
        </>}
      </section>;
    })}

    <section className="space-y-2 border-t border-rule pt-3" aria-label="Otros conectores">
      <h4 className="font-semibold">Otros conectores</h4>
      <div className="settings-provider-row"><div className="settings-provider-copy"><strong>Google Drive</strong><p>Sin conexión disponible todavía.</p></div><span className="text-xs text-ink-3">No disponible</span></div>
      <div className="settings-provider-row"><div className="settings-provider-copy"><strong>Microsoft Teams</strong><p>Sin conexión disponible todavía.</p></div><span className="text-xs text-ink-3">No disponible</span></div>
    </section>
  </div>;
}

export function SettingsPanel() {
  const { api } = useApp();
  const [theme, setTheme] = useState<ThemePreference>(() => getThemePreference());
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const returnFocus = useCallback(() => triggerRef.current, []);
  const changeTheme = (next: ThemePreference) => {
    setTheme(next);
    persistThemePreference(next);
  };
  return <>
    <button
      ref={triggerRef}
      type="button"
      className="settings-trigger"
      aria-label={open ? 'Cerrar configuración' : 'Abrir configuración'}
      aria-expanded={open}
      aria-controls={open ? 'settings-dialog' : undefined}
      data-testid="settings-toggle"
      onClick={() => setOpen(true)}
    >
      <Settings size={21} aria-hidden="true" />
    </button>
    <Modal
      open={open}
      title="Configuración"
      description="Preferencias y conexiones de Umbral."
      headerContent={
        <nav className="settings-section-nav" aria-label="Secciones de configuración">
          <button type="button" onClick={() => document.getElementById('settings-preferences')?.scrollIntoView({ block: 'start' })}>Preferencias</button>
          <button type="button" onClick={() => document.getElementById('settings-updates')?.scrollIntoView({ block: 'start' })}>Actualizaciones</button>
          <button type="button" onClick={() => document.getElementById('settings-connections')?.scrollIntoView({ block: 'start' })}>Conexiones</button>
        </nav>
      }
      onClose={() => setOpen(false)}
      testId="settings-dialog"
      dialogId="settings-dialog"
      placement="settings"
      returnFocus={returnFocus}
    >
      <section id="settings-preferences" className="mb-6 scroll-mt-16" aria-labelledby="settings-preferences-title">
        <SectionTitle id="settings-preferences-title" kicker="Interfaz">Preferencias</SectionTitle>
        <div className="mb-5 space-y-2">
          <h3 className="text-sm font-semibold">Apariencia</h3>
          <p className="text-xs text-ink-3">Elige los colores de Umbral. El cambio se aplica de inmediato y se guarda en este navegador.</p>
          <Field label="Tema" htmlFor="settings-theme">
            <Select
              id="settings-theme"
              testId="settings-theme"
              value={theme}
              onChange={changeTheme}
              options={[
                { value: 'original', label: 'Original', hint: 'La paleta actual de Umbral.' },
                { value: 'tvn', label: 'TVN Noticias', hint: 'Fondos claros con acentos azules.' },
              ]}
            />
          </Field>
        </div>
        <div className="space-y-2">
          <h3 className="text-sm font-semibold">Movimiento</h3>
          <p className="text-xs text-ink-3">Elige si Umbral sigue el sistema o reduce las animaciones.</p>
          <MotionPreferenceSwitch />
        </div>
      </section>
      <section id="settings-updates" className="mb-6 scroll-mt-16" aria-labelledby="settings-updates-title">
        <SectionTitle id="settings-updates-title" kicker="Aplicación">Actualizaciones</SectionTitle>
        <DesktopUpdateSettings />
      </section>
      <section id="settings-connections" className="scroll-mt-16" aria-labelledby="settings-connections-title">
        <SectionTitle id="settings-connections-title" kicker="Servicios">Conexiones</SectionTitle>
        {api.kind === 'mock' ? <Notice tone="warn">Las conexiones no están disponibles en la demostración.</Notice> : <>
          <PublicConnectors />
          <div className="mt-5 border-t-2 border-ink pt-4">
            <SectionTitle kicker="Cuentas personales">ChatGPT y Claude</SectionTitle>
            <p className="mb-3 text-xs text-ink-3">Estas conexiones usan las sesiones oficiales guardadas en este equipo. En la web pública siguen disponibles solo en el modo local.</p>
            <ConnectionsCard />
          </div>
        </>}
      </section>
    </Modal>
  </>;
}
