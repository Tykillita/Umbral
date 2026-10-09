// Alias legibles sobre los tipos generados desde apps/api/openapi.json (`pnpm gen:api`).
import type { components } from './schema';

type S = components['schemas'];

export type Category = S['Category'];
export type EvidenceStatus = S['EvidenceStatus'];
export type ReviewStatus = S['ReviewStatus'];
export type ScoreBand = S['ScoreBand'];
export type GenerationMode = S['GenerationMode'];
export type ClaimType = S['ClaimType'];
export type AnswerStatus = S['AnswerStatus'];
export type DataMode = S['DataMode'];
export type ImpactLevel = S['ImpactLevel'];
export type FallbackReason = S['FallbackReason'];
export type DraftProviderChoice = S['DraftProviderChoice'];

export type Health = S['HealthResponse'];
export type Rules = S['RulesResponse-Output'];
export type RulesRequest = S['RulesRequest'];
export type Connections = S['ConnectionsResponse'];
export type ConnectionStart = S['ConnectionStart'];
export type Authorization = S['AuthorizationResponse'];
export type Models = S['ModelsResponse'];
export type Disconnect = S['DisconnectResponse'];
export type SnapshotInfo = S['SnapshotInfoResponse'];
export type TopicsResponse = S['TopicsResponse'];
export type TopicSummary = S['TopicSummary-Output'];
export type TopicDetail = S['TopicDetail-Output'];
export type ScoreComponent = S['ScoreComponent-Output'];
export type ScoreDetail = S['ScoreDetail-Output'];
export type EvidenceArticle = S['EvidenceArticle-Output'];
export type IndicatorPoint = S['IndicatorPoint-Output'];
export type Claim = S['Claim-Output'];
export type ClaimInput = S['ClaimInput'];
export type Contradiction = S['Contradiction-Output'];
export type CaseView = S['CaseView-Output'];
export type CaseEvent = S['CaseEvent-Output'];
export type DraftRecord = S['DraftRecord-Output'];
export type DraftResponse = S['DraftResponse'];
export type EditorialPackage = S['EditorialPackage-Output'];
export type ValidationReport = S['ValidationReport-Output'];
export type QueryResponse = S['QueryResponse'];
export type QueryContext = S['QueryContext-Output'];
export type ComposeResponse = S['ComposeResponse'];
export type ComposeProvider = 'gemini' | 'chatgpt' | 'claude';
export type ClaudeConnection = S['ClaudeConnection'];
/** Cuerpo de una consulta; `followUp` es el `followUpContext` de la respuesta anterior (solo identificadores, nunca texto). */
export type QueryRequestBody = { question: string; topicId?: string | null; limit?: number; followUp?: S['QueryContext-Input'] | null };
export type ComposeRequestBody = QueryRequestBody & { provider?: ComposeProvider };
export type QueryCitation = S['QueryCitation'];
export type QueryHit = S['QueryHit'];
export type ExportResponse = S['ExportResponse'];
export type NotionStatusResponse = S['NotionStatusResponse'];
export type NotionExportResponse = S['NotionExportResponse'];
export type ConnectorProvider = 'notion' | 'slack';
export type ConnectorAuthorization = { authorizationUrl: string };
export type ConnectorOverview = {
  configured: boolean;
  providers: {
    notion: { available: boolean; connected: boolean; workspaceName: string | null; destinationId: string | null; destinationTitle: string | null };
    slack: { available: boolean; connected: boolean; workspaceName: string | null; channelId: string | null; channelName: string | null };
  };
  slackNotifications: { enabled: boolean; statuses: ReviewStatus[] };
};
export type ConnectorPage = { id: string; title: string; url: string };
export type ConnectorChannel = { id: string; name: string; isPrivate: boolean };
export type SlackNotificationPreferences = { enabled: boolean; channelId: string | null; statuses: ReviewStatus[] };
export type SlackShareRequest = { eventId: string; caseId: string; caseVersion: number; title: string; status: ReviewStatus; snapshotId: string };
export type SlackNotificationResult = { sent: boolean; duplicate: boolean; skippedReason: string | null };
export type ErrorBody = S['ErrorResponse'];
export type ProviderStatus = S['ProviderStatus'];
export type ImpactRequest = S['ImpactRequest'];
export type ReviewRequest = S['ReviewRequest'];
export type DraftEditRequest = S['DraftEditRequest'];

export interface TopicFilters {
  scope?: 'in_scope' | 'all';
  category?: Category | '';
  evidence?: EvidenceStatus | '';
  band?: ScoreBand | '';
  reviewStatus?: ReviewStatus | '';
  q?: string;
  limit?: number;
  tvnGap?: boolean;
}

export type PublicContext = S['PublicContext'];
export type PublicDraftResponse = S['PublicDraftResponse'];
export type PublicValidationResponse = S['PublicValidationResponse'];
export type ArchivedEvidence = S['ArchivedEvidence-Output'];

export type ImpactAssignment = S['ImpactAssignment-Output'];
