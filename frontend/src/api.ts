export type MatchState = {
  match_id: string;
  simulation_run_id: string;
  scenario_id: string;
  synthetic: boolean;
  status: 'not_started' | 'in_progress' | 'ended' | string;
  period: string | null;
  clock: { match_elapsed_ms: number; period_elapsed_ms: number };
  score: { home: number; away: number };
  current_possession_team_id: string | null;
  shots: Record<string, number>;
  last_accepted_sequence: number;
  last_finalized_sequence: number;
  last_finalized_event_id: string | null;
  state_version: number;
  transition_pending: boolean;
};

export type MatchEvent = {
  event_id: string;
  match_id: string;
  simulation_run_id: string;
  sequence: number;
  type: string;
  team_id: string | null;
  player_id: string | null;
  outcome: string | null;
  clock: { match_elapsed_ms: number; period_elapsed_ms: number; period: string };
  data: Record<string, unknown>;
  provenance: { synthetic: boolean };
};

export type Metric = { value: number | string | null; unit: string; numerator: number; denominator: number };
export type IntelligenceTeam = {
  team_id: string;
  role: 'home' | 'away';
  metrics: {
    goals: Metric;
    shots: Metric;
    shot_outcomes: Record<string, Metric>;
    logged_pressure_events: Metric;
    goals_per_shot: Metric;
  };
};
export type Insight = {
  schema_version: 1;
  insight_id: string;
  match_id: string;
  simulation_run_id: string;
  synthetic: true;
  rule_id: 'score_change' | 'shot_activity' | 'pressure_activity';
  rule_version: string;
  team_id: string;
  period: string;
  clock: { match_elapsed_ms: number; period_elapsed_ms: number };
  trigger_event_id: string;
  trigger_sequence: number;
  observed_facts: Record<string, unknown>;
  evidence_event_ids: string[];
};
export type IntelligenceResponse = {
  match_id: string;
  simulation_run_id: string;
  synthetic: true;
  as_of: { sequence: number; event_id: string | null; match_elapsed_ms: number | null };
  metric_snapshot: { teams: IntelligenceTeam[]; as_of: IntelligenceResponse['as_of'] };
  insights: Insight[];
  next_cursor: string | null;
};
export type NarrativeResponse = {
  schema_version: 1;
  narrative_id: string;
  narrative_kind: string;
  language: string;
  match_id: string;
  simulation_run_id: string;
  synthetic: true;
  as_of: IntelligenceResponse['as_of'];
  provider: string;
  model: string;
  blocks: { claim_ids: string[]; insight_ids: string[]; evidence_event_ids: string[]; text: string }[];
};

export type DemoPlayback = {
  request_id: string;
  match_id: string;
  status: 'starting' | 'running' | 'completed' | 'failed';
  duplicate: boolean;
  error: string | null;
};

export class ApiError extends Error {
  constructor(message: string, readonly code: string, readonly status: number) { super(message); }
}

async function request<T>(path: string, signal?: AbortSignal, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, signal, headers: { Accept: 'application/json', ...init?.headers } });
  const body = await response.json().catch(() => null) as unknown;
  if (!response.ok) {
    const error = body && typeof body === 'object' && 'error' in body ? (body as { error: { code?: string; message?: string } }).error : undefined;
    throw new ApiError(error?.message ?? `Request failed (${response.status})`, error?.code ?? 'request_failed', response.status);
  }
  return body as T;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function parseMatchState(value: unknown): MatchState {
  if (!isObject(value) || typeof value.match_id !== 'string' || typeof value.simulation_run_id !== 'string'
    || value.synthetic !== true || typeof value.scenario_id !== 'string' || typeof value.status !== 'string'
    || !isObject(value.score) || !Number.isSafeInteger(value.score.home) || !Number.isSafeInteger(value.score.away)
    || !isObject(value.clock) || !Number.isSafeInteger(value.clock.match_elapsed_ms)
    || !Number.isSafeInteger(value.last_finalized_sequence) || !Number.isSafeInteger(value.last_accepted_sequence)) {
    throw new ApiError('Match state response is invalid or not synthetic', 'invalid_response', 502);
  }
  return value as MatchState;
}

export function parseEvent(value: unknown): MatchEvent {
  if (!isObject(value) || typeof value.event_id !== 'string' || typeof value.match_id !== 'string'
    || typeof value.simulation_run_id !== 'string' || !Number.isSafeInteger(value.sequence) || typeof value.type !== 'string'
    || !isObject(value.clock) || !Number.isSafeInteger(value.clock.match_elapsed_ms)
    || !Number.isSafeInteger(value.clock.period_elapsed_ms) || typeof value.clock.period !== 'string'
    || !isObject(value.data) || !isObject(value.provenance) || value.provenance.synthetic !== true) {
    throw new ApiError('Event response is invalid or is not synthetic', 'invalid_response', 502);
  }
  return value as MatchEvent;
}

export function parseIntelligence(value: unknown): IntelligenceResponse {
  if (!isObject(value) || value.synthetic !== true || typeof value.match_id !== 'string'
    || typeof value.simulation_run_id !== 'string' || !isObject(value.as_of) || !isObject(value.metric_snapshot)
    || !Number.isSafeInteger(value.as_of.sequence) || !Array.isArray(value.insights)
    || !Array.isArray(value.metric_snapshot.teams) || value.metric_snapshot.match_id !== value.match_id
    || value.metric_snapshot.simulation_run_id !== value.simulation_run_id || value.metric_snapshot.synthetic !== true
    || !isObject(value.metric_snapshot.as_of) || value.metric_snapshot.as_of.sequence !== value.as_of.sequence
    || (value.next_cursor !== null && typeof value.next_cursor !== 'string')) {
    throw new ApiError('Intelligence response is invalid', 'invalid_response', 502);
  }
  for (const team of value.metric_snapshot.teams) {
    if (!isObject(team) || typeof team.team_id !== 'string' || (team.role !== 'home' && team.role !== 'away')
      || !isObject(team.metrics)) throw new ApiError('Intelligence team response is invalid', 'invalid_response', 502);
    for (const metricName of ['goals', 'shots', 'goals_per_shot', 'logged_pressure_events']) {
      const metric = team.metrics[metricName];
      if (!isObject(metric) || !(metric.value === null || typeof metric.value === 'string' || Number.isSafeInteger(metric.value))) {
        throw new ApiError('Intelligence metric response is invalid', 'invalid_response', 502);
      }
    }
    if (!isObject(team.metrics.shot_outcomes)) throw new ApiError('Shot outcome response is invalid', 'invalid_response', 502);
  }
  for (const insight of value.insights) {
    if (!isObject(insight) || insight.synthetic !== true || typeof insight.insight_id !== 'string'
      || typeof insight.rule_id !== 'string' || typeof insight.team_id !== 'string'
      || !Array.isArray(insight.evidence_event_ids) || !insight.evidence_event_ids.every((id) => typeof id === 'string')) {
      throw new ApiError('Intelligence insight response is invalid', 'invalid_response', 502);
    }
  }
  return value as unknown as IntelligenceResponse;
}

export function mergeEvents(existing: MatchEvent[], incoming: MatchEvent[], finalizedSequence: number): MatchEvent[] {
  const byId = new Map<string, MatchEvent>();
  for (const item of [...existing, ...incoming]) {
    if (item.sequence <= finalizedSequence) byId.set(item.event_id, item);
  }
  return [...byId.values()].sort((left, right) => left.sequence - right.sequence);
}

export async function fetchMatchState(matchId: string, signal?: AbortSignal): Promise<MatchState> {
  return parseMatchState(await request<unknown>(`/api/matches/${encodeURIComponent(matchId)}/state`, signal));
}

export async function fetchEventHistory(
  matchId: string,
  finalizedSequence: number,
  signal?: AbortSignal,
  afterSequence = 0,
): Promise<MatchEvent[]> {
  if (!Number.isSafeInteger(finalizedSequence) || finalizedSequence < 0
    || !Number.isSafeInteger(afterSequence) || afterSequence < 0 || afterSequence > finalizedSequence) {
    throw new ApiError('Finalized event history bounds are invalid', 'invalid_event_history_bounds', 502);
  }
  const found: MatchEvent[] = [];
  let after = afterSequence;
  for (let page = 0; page < 100 && after < finalizedSequence; page += 1) {
    const result = await request<{ events: unknown[]; next_after_sequence: number }>(
      `/api/matches/${encodeURIComponent(matchId)}/events?after_sequence=${after}&limit=100`, signal,
    );
    const events = result.events.map(parseEvent).filter((event) => event.sequence <= finalizedSequence);
    found.push(...events);
    if (result.next_after_sequence <= after || result.events.length === 0) break;
    after = result.next_after_sequence;
  }
  const expectedCount = finalizedSequence - afterSequence;
  if (after < finalizedSequence || found.length !== expectedCount
    || found.some((event, index) => event.sequence !== afterSequence + index + 1)) {
    throw new ApiError(
      'Finalized event history did not reach the requested sequence watermark',
      'incomplete_event_history',
      502,
    );
  }
  return mergeEvents([], found, finalizedSequence);
}

export async function fetchIntelligence(matchId: string, signal?: AbortSignal): Promise<IntelligenceResponse> {
  return parseIntelligence(await request<unknown>(`/api/matches/${encodeURIComponent(matchId)}/intelligence?limit=100`, signal));
}

function parseDemoPlayback(value: unknown): DemoPlayback {
  if (!isObject(value) || typeof value.request_id !== 'string'
    || typeof value.match_id !== 'string' || !/^demo-[0-9a-f]{32}$/.test(value.match_id)
    || !['starting', 'running', 'completed', 'failed'].includes(String(value.status))
    || typeof value.duplicate !== 'boolean'
    || !(value.error === null || typeof value.error === 'string')) {
    throw new ApiError('Demo playback response is invalid', 'invalid_response', 502);
  }
  return value as unknown as DemoPlayback;
}

export async function createDemoPlayback(
  options: { request_id: string; scenario: string; seed: number; speed: number; fast_demo: boolean }, signal?: AbortSignal,
): Promise<DemoPlayback> {
  return parseDemoPlayback(await request<unknown>('/api/demo/playbacks', signal, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(options),
  }));
}

export async function fetchDemoPlayback(requestId: string, signal?: AbortSignal): Promise<DemoPlayback> {
  return parseDemoPlayback(await request<unknown>(`/api/demo/playbacks/${encodeURIComponent(requestId)}`, signal));
}

export async function generateNarrative(matchId: string, intelligence: IntelligenceResponse, insightIds: string[], signal?: AbortSignal): Promise<NarrativeResponse> {
  const result = await request<unknown>(`/api/matches/${encodeURIComponent(matchId)}/narratives`, signal, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ simulation_run_id: intelligence.simulation_run_id, as_of: intelligence.as_of, insight_ids: insightIds }),
  });
  if (!isObject(result) || result.schema_version !== 1 || result.narrative_kind !== 'match_insight_explanation'
    || result.language !== 'en' || result.synthetic !== true || result.match_id !== matchId
    || result.simulation_run_id !== intelligence.simulation_run_id || !Array.isArray(result.blocks)
    || !isObject(result.as_of) || result.as_of.sequence !== intelligence.as_of.sequence
    || result.as_of.event_id !== intelligence.as_of.event_id
    || result.as_of.match_elapsed_ms !== intelligence.as_of.match_elapsed_ms
    || typeof result.narrative_id !== 'string' || !/^narrative:v1:[0-9a-f]{64}$/.test(result.narrative_id)
    || result.narrative_contract_version !== '1.0.0' || result.prompt_version !== 'narrative-prompt-v1'
    || typeof result.provider !== 'string' || typeof result.model !== 'string') {
    throw new ApiError('Narrative response does not match the selected snapshot', 'invalid_response', 502);
  }
  const selected = new Set(insightIds);
  const seenInsights = new Set<string>();
  for (const block of result.blocks) {
    if (!isObject(block) || typeof block.text !== 'string' || block.text.length < 1 || block.text.length > 500
      || !Array.isArray(block.claim_ids) || block.claim_ids.length !== 1
      || typeof block.claim_ids[0] !== 'string' || !/^claim:v1:[0-9a-f]{64}$/.test(block.claim_ids[0])
      || !Array.isArray(block.insight_ids) || block.insight_ids.length !== 1
      || typeof block.insight_ids[0] !== 'string' || !selected.has(block.insight_ids[0])
      || seenInsights.has(block.insight_ids[0])
      || !Array.isArray(block.evidence_event_ids) || !block.evidence_event_ids.every((id) => typeof id === 'string')) {
      throw new ApiError('Narrative block references are invalid', 'invalid_response', 502);
    }
    const insightId = block.insight_ids[0] as string;
    const evidenceIds = block.evidence_event_ids as string[];
    const source = intelligence.insights.find((insight) => insight.insight_id === insightId);
    if (!source || evidenceIds.length !== source.evidence_event_ids.length
      || evidenceIds.some((id, index) => id !== source.evidence_event_ids[index])) {
      throw new ApiError('Narrative evidence does not match its selected insight', 'invalid_response', 502);
    }
    seenInsights.add(insightId);
  }
  if (seenInsights.size !== selected.size || [...selected].some((id) => !seenInsights.has(id))) {
    throw new ApiError('Narrative response does not cover the selected insights', 'invalid_response', 502);
  }
  return result as unknown as NarrativeResponse;
}
