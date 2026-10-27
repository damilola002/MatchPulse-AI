import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { generateNarrative, mergeEvents, parseIntelligence, type IntelligenceResponse, type MatchEvent } from './api';

const state = {
  match_id: 'demo-match', simulation_run_id: 'a'.repeat(32), scenario_id: 'balanced', synthetic: true,
  status: 'in_progress', period: 'first_half', clock: { match_elapsed_ms: 600000, period_elapsed_ms: 600000 },
  score: { home: 1, away: 0 }, current_possession_team_id: 'home-x', shots: { home: 2, away: 1 },
  last_accepted_sequence: 4, last_finalized_sequence: 4, state_version: 4, transition_pending: false,
};
const startEvent: MatchEvent = {
  event_id: `${'a'.repeat(32)}:1`, match_id: 'demo-match', simulation_run_id: 'a'.repeat(32), sequence: 1,
  type: 'match_start', team_id: null, player_id: null, outcome: 'started',
  clock: { match_elapsed_ms: 0, period_elapsed_ms: 0, period: 'first_half' },
  data: { home_team: { team_id: 'home-x', name: 'Northbridge' }, away_team: { team_id: 'away-y', name: 'Harbor City' } },
  provenance: { synthetic: true },
};
const goalEvent: MatchEvent = {
  ...startEvent, event_id: `${'a'.repeat(32)}:4`, sequence: 4, type: 'goal', team_id: 'home-x', outcome: 'scored',
  clock: { match_elapsed_ms: 600000, period_elapsed_ms: 600000, period: 'first_half' }, data: {},
};
const passEvent: MatchEvent = {
  ...startEvent, event_id: `${'a'.repeat(32)}:2`, sequence: 2, type: 'pass', team_id: 'home-x', outcome: 'completed',
  clock: { match_elapsed_ms: 120000, period_elapsed_ms: 120000, period: 'first_half' }, data: {},
};
const shotEvent: MatchEvent = {
  ...startEvent, event_id: `${'a'.repeat(32)}:3`, sequence: 3, type: 'shot', team_id: 'away-y', outcome: 'saved',
  clock: { match_elapsed_ms: 300000, period_elapsed_ms: 300000, period: 'first_half' }, data: {},
};
const intelligence = {
  match_id: 'demo-match', simulation_run_id: 'a'.repeat(32), synthetic: true,
  as_of: { sequence: 4, event_id: goalEvent.event_id, match_elapsed_ms: 600000 },
  metric_snapshot: { schema_version: 1, match_id: 'demo-match', simulation_run_id: 'a'.repeat(32), synthetic: true, metric_definition_version: '1.0.0', teams: [
    { team_id: 'home-x', role: 'home', metrics: { goals: { value: 1, unit: 'goals', numerator: 1, denominator: 1 }, shots: { value: 2, unit: 'shots', numerator: 2, denominator: 1 }, goals_per_shot: { value: '0.5000', unit: 'ratio', numerator: 1, denominator: 2 }, logged_pressure_events: { value: 0, unit: 'events', numerator: 0, denominator: 1 }, shot_outcomes: { goal: { value: 1, unit: 'shots', numerator: 1, denominator: 1 }, saved: { value: 0, unit: 'shots', numerator: 0, denominator: 1 }, blocked: { value: 0, unit: 'shots', numerator: 0, denominator: 1 }, off_target: { value: 0, unit: 'shots', numerator: 0, denominator: 1 }, woodwork: { value: 0, unit: 'shots', numerator: 0, denominator: 1 } } } },
    { team_id: 'away-y', role: 'away', metrics: { goals: { value: 0, unit: 'goals', numerator: 0, denominator: 1 }, shots: { value: 1, unit: 'shots', numerator: 1, denominator: 1 }, goals_per_shot: { value: '0.0000', unit: 'ratio', numerator: 0, denominator: 1 }, logged_pressure_events: { value: 1, unit: 'events', numerator: 1, denominator: 1 }, shot_outcomes: { goal: { value: 0, unit: 'shots', numerator: 0, denominator: 1 }, saved: { value: 1, unit: 'shots', numerator: 1, denominator: 1 }, blocked: { value: 0, unit: 'shots', numerator: 0, denominator: 1 }, off_target: { value: 0, unit: 'shots', numerator: 0, denominator: 1 }, woodwork: { value: 0, unit: 'shots', numerator: 0, denominator: 1 } } } },
  ], as_of: { sequence: 4, event_id: goalEvent.event_id, match_elapsed_ms: 600000 } },
  insights: [{ schema_version: 1, insight_id: 'insight:v1:' + 'b'.repeat(64), match_id: 'demo-match', simulation_run_id: 'a'.repeat(32), synthetic: true,
    rule_id: 'score_change', rule_version: '1.0.0', team_id: 'home-x', period: 'first_half',
    clock: { match_elapsed_ms: 600000, period_elapsed_ms: 600000 }, trigger_event_id: goalEvent.event_id, trigger_sequence: 4,
    observed_facts: { score_before: { home: 0, away: 0 }, score_after: { home: 1, away: 0 } }, evidence_event_ids: [goalEvent.event_id] }],
  next_cursor: null,
};

class FakeEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  readyState = FakeEventSource.CONNECTING;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  listeners = new Map<string, EventListener>();
  close = vi.fn(() => { this.readyState = FakeEventSource.CLOSED; });
  addEventListener(type: string, listener: EventListener) { this.listeners.set(type, listener); }
  removeEventListener(type: string) { this.listeners.delete(type); }
  emit(value: MatchEvent) {
    const listener = this.listeners.get('match.event');
    listener?.(new MessageEvent('match.event', { data: JSON.stringify(value), lastEventId: value.event_id }));
  }
}

let latestSource: FakeEventSource;
function setupNetwork() {
  vi.stubGlobal('EventSource', class extends FakeEventSource {
    constructor() { super(); latestSource = this; queueMicrotask(() => { this.readyState = FakeEventSource.OPEN; this.onopen?.(); }); }
  });
  let demoScenario = 'balanced';
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const demoMatchId = `demo-${'e'.repeat(32)}`;
    const matchPath = url.split('/api/matches/')[1]?.split('/')[0];
    if (url.includes('/missing/')) return {
      ok: false, status: 404, json: async () => ({ error: { code: 'match_not_found', message: 'match was not found' } }),
    } as Response;
    if (url.endsWith('/api/demo/playbacks') && init?.method === 'POST') {
      const request = JSON.parse(String(init.body));
      demoScenario = request.scenario;
      return { ok: true, status: 202, json: async () => ({ request_id: request.request_id, match_id: demoMatchId, status: 'starting', duplicate: false, error: null }) } as Response;
    }
    if (url.includes('/api/demo/playbacks/')) {
      return { ok: true, status: 200, json: async () => ({ request_id: url.split('/').at(-1), match_id: demoMatchId, status: 'running', duplicate: false, error: null }) } as Response;
    }
    let body: unknown;
    if (url.endsWith('/state')) body = { ...state, match_id: matchPath, scenario_id: demoScenario };
    else if (url.includes('/events?')) body = { events: [startEvent, passEvent, shotEvent, goalEvent].map((event) => ({ ...event, match_id: matchPath })), next_after_sequence: 4 };
    else if (url.includes('/intelligence')) body = {
      ...intelligence,
      match_id: matchPath,
      metric_snapshot: { ...intelligence.metric_snapshot, match_id: matchPath },
      insights: intelligence.insights.map((insight) => ({ ...insight, match_id: matchPath })),
    };
    else if (url.endsWith('/narratives') && init?.method === 'POST') body = {
      schema_version: 1, narrative_id: 'narrative:v1:' + 'c'.repeat(64), narrative_kind: 'match_insight_explanation', language: 'en', match_id: 'demo-match',
      simulation_run_id: 'a'.repeat(32), synthetic: true, as_of: intelligence.as_of, provider: 'deterministic-fake', model: 'fake-v1',
      narrative_contract_version: '1.0.0', prompt_version: 'narrative-prompt-v1',
      blocks: [{ claim_ids: ['claim:v1:' + 'd'.repeat(64)], insight_ids: [intelligence.insights[0].insight_id], evidence_event_ids: [goalEvent.event_id], text: 'The home side scored, changing the score from 0–0 to 1–0.' }],
    };
    else throw new Error(`Unexpected request ${url}`);
    return { ok: true, status: 200, json: async () => body } as Response;
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe('dashboard', () => {
  it('validates API payload contracts and merges finalized SSE events by exact identity and sequence', () => {
    expect(parseIntelligence(intelligence).as_of.sequence).toBe(4);
    expect(() => parseIntelligence({ ...intelligence, synthetic: false })).toThrow('invalid');
    const duplicate = { ...goalEvent };
    expect(mergeEvents([startEvent], [goalEvent, duplicate], 4).map((event) => event.event_id)).toEqual([startEvent.event_id, goalEvent.event_id]);
    expect(mergeEvents([], [goalEvent], 3)).toEqual([]);
  });

  it('rejects narrative evidence that differs from the selected finalized insight', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        schema_version: 1,
        narrative_id: 'narrative:v1:' + 'c'.repeat(64),
        narrative_kind: 'match_insight_explanation',
        language: 'en',
        match_id: 'demo-match',
        simulation_run_id: 'a'.repeat(32),
        synthetic: true,
        as_of: intelligence.as_of,
        narrative_contract_version: '1.0.0',
        provider: 'deterministic-fake',
        model: 'fake-v1',
        prompt_version: 'narrative-prompt-v1',
        blocks: [{ claim_ids: ['claim:v1:' + 'd'.repeat(64)], insight_ids: [intelligence.insights[0].insight_id], evidence_event_ids: ['unrelated:9'], text: 'Unsupported reference' }],
      }),
    })));
    await expect(generateNarrative('demo-match', intelligence as unknown as IntelligenceResponse, [intelligence.insights[0].insight_id]))
      .rejects.toThrow('Narrative evidence does not match');
  });

  it('renders synthetic scoreboard, ordered timeline, metrics, and evidence; narrative is explicit', async () => {
    const fetchMock = setupNetwork();
    render(<App />);
    fireEvent.change(screen.getByLabelText('Connect to an existing local match'), { target: { value: 'demo-match' } });
    fireEvent.click(screen.getByRole('button', { name: /connect/i }));
    expect(await screen.findByText('SYNTHETIC DATA')).toBeInTheDocument();
    expect((await screen.findAllByText('Northbridge')).length).toBeGreaterThan(0);
    expect(document.querySelector('.score')).toHaveTextContent('1:0');
    expect(screen.getByText('Score moved to 1–0')).toBeInTheDocument();
    expect(screen.getByText(goalEvent.event_id)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith('/narratives'))).toBe(false);
    fireEvent.click(screen.getByRole('checkbox', { name: /Score moved to 1–0/ }));
    fireEvent.click(screen.getByRole('button', { name: /generate match narrative/i }));
    expect(await screen.findByText('The home side scored, changing the score from 0–0 to 1–0.')).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input, init]) => String(input).endsWith('/narratives') && init?.method === 'POST')).toBe(true);
  });

  it('deduplicates replayed SSE events and reports reconnect state', async () => {
    setupNetwork();
    render(<App />);
    fireEvent.change(screen.getByLabelText('Connect to an existing local match'), { target: { value: 'demo-match' } });
    fireEvent.click(screen.getByRole('button', { name: /connect/i }));
    await screen.findByText('Live feed connected');
    const earlierEvent = shotEvent;
    latestSource.emit(goalEvent);
    latestSource.emit(earlierEvent);
    latestSource.emit(goalEvent);
    await waitFor(() => expect(document.querySelectorAll('.timeline-item')).toHaveLength(3));
    expect([...document.querySelectorAll('.event-sequence')].map((node) => node.textContent)).toEqual(['004', '003', '002']);
    expect(screen.getByText('Live feed connected')).toBeInTheDocument();
  });

  it('merges paginated finalized history through the watermark before completing a 61-event timeline', async () => {
    const matchId = 'demo-match';
    const events = Array.from({ length: 62 }, (_, index) => {
      const sequence = index + 1;
      return {
        ...startEvent,
        event_id: `${'a'.repeat(32)}:${sequence}`,
        sequence,
        type: sequence === 1 ? 'match_start' : sequence === 62 ? 'full_time' : 'pass',
        outcome: sequence === 1 ? 'started' : sequence === 62 ? 'ended' : 'completed',
        clock: { match_elapsed_ms: sequence * 60_000, period_elapsed_ms: sequence * 60_000, period: 'second_half' },
        data: sequence === 1 ? startEvent.data : {},
      } satisfies MatchEvent;
    });
    const finalizedState = {
      ...state,
      match_id: matchId,
      status: 'ended',
      period: 'second_half',
      last_accepted_sequence: 62,
      last_finalized_sequence: 62,
      clock: { match_elapsed_ms: 62 * 60_000, period_elapsed_ms: 31 * 60_000 },
    };
    const finalSnapshot = { sequence: 62, event_id: events[61].event_id, match_elapsed_ms: 62 * 60_000 };
    const finalIntelligence = {
      ...intelligence,
      match_id: matchId,
      as_of: finalSnapshot,
      metric_snapshot: { ...intelligence.metric_snapshot, match_id: matchId, as_of: finalSnapshot },
      insights: intelligence.insights.map((insight) => ({ ...insight, match_id: matchId })),
    };
    let stateRequests = 0;
    const requestedCursors: number[] = [];
    vi.stubGlobal('EventSource', class extends FakeEventSource {
      constructor() { super(); latestSource = this; queueMicrotask(() => { this.readyState = FakeEventSource.OPEN; this.onopen?.(); }); }
    });
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname.endsWith('/state')) {
        stateRequests += 1;
        const body = stateRequests === 1
          ? { ...state, match_id: matchId, last_accepted_sequence: 2, last_finalized_sequence: 2 }
          : finalizedState;
        return { ok: true, status: 200, json: async () => body } as Response;
      }
      if (url.pathname.endsWith('/events')) {
        const after = Number(url.searchParams.get('after_sequence'));
        requestedCursors.push(after);
        const page = events.filter((event) => event.sequence > after).slice(0, 25);
        return { ok: true, status: 200, json: async () => ({
          events: page,
          next_after_sequence: page.at(-1)?.sequence ?? after,
        }) } as Response;
      }
      if (url.pathname.endsWith('/intelligence')) {
        return { ok: true, status: 200, json: async () => finalIntelligence } as Response;
      }
      throw new Error(`Unexpected request ${url.pathname}`);
    }));

    render(<App />);
    fireEvent.change(screen.getByLabelText('Connect to an existing local match'), { target: { value: matchId } });
    fireEvent.click(screen.getByRole('button', { name: /connect/i }));
    await screen.findByText('Live feed connected');
    await waitFor(() => expect(screen.getByText('1 events')).toBeInTheDocument());

    latestSource.emit(events[2]);
    await waitFor(() => expect(document.querySelectorAll('.timeline-item')).toHaveLength(2));
    latestSource.emit(events[61]);

    await waitFor(() => expect(screen.getByText('Match finalized')).toBeInTheDocument());
    expect(screen.getByText('61 events')).toBeInTheDocument();
    const sequences = [...document.querySelectorAll('.event-sequence')].map((node) => node.textContent);
    expect(sequences).toHaveLength(61);
    expect(sequences[0]).toBe('062');
    expect(sequences.at(-1)).toBe('002');
    expect(new Set(sequences).size).toBe(61);
    expect(requestedCursors).toEqual([0, 3, 28, 53]);
  });

  it('creates a match from the selected controls and connects the dashboard automatically', async () => {
    const fetchMock = setupNetwork();
    render(<App />);
    fireEvent.change(screen.getByLabelText('Scenario'), { target: { value: 'late_comeback' } });
    fireEvent.change(screen.getByLabelText('Seed'), { target: { value: '29' } });
    fireEvent.change(screen.getByLabelText('Playback speed (standard mode)'), { target: { value: '20' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create & Play Match' }));
    expect(await screen.findByText('Live feed connected')).toBeInTheDocument();
    const startCall = fetchMock.mock.calls.find(([input, init]) => String(input).endsWith('/api/demo/playbacks') && init?.method === 'POST');
    expect(startCall).toBeDefined();
    const body = JSON.parse(String(startCall?.[1]?.body));
    expect(body).toMatchObject({ scenario: 'late_comeback', seed: 29, speed: 20, fast_demo: true });
    expect(body.request_id).toMatch(/^[0-9a-f-]{36}$/);
    const matchId = `demo-${'e'.repeat(32)}`;
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).includes(`/api/matches/${matchId}/state`))).toBe(true));
    await waitFor(() => expect(document.querySelector('.scenario-chip')).toHaveTextContent('Late comeback'));
  });

  it('keeps standard playback speeds available when Demo Fast Playback is disabled', async () => {
    const fetchMock = setupNetwork();
    render(<App />);
    fireEvent.click(screen.getByLabelText(/Demo Fast Playback/i));
    fireEvent.change(screen.getByLabelText('Playback speed (standard mode)'), { target: { value: '5' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create & Play Match' }));
    await screen.findByText('Live feed connected');
    const startCall = fetchMock.mock.calls.find(([input, init]) => String(input).endsWith('/api/demo/playbacks') && init?.method === 'POST');
    expect(JSON.parse(String(startCall?.[1]?.body))).toMatchObject({ speed: 5, fast_demo: false });
  });

  it('shows a safe startup error and stays disconnected when playback capacity is full', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false,
      status: 409,
      json: async () => ({ error: { code: 'demo_playback_capacity', message: 'a synthetic demo playback is already active' } }),
    }) as unknown as Response));
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Create & Play Match' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('a synthetic demo playback is already active');
    expect(screen.getByText('AWAITING MATCH')).toBeInTheDocument();
  });

  it('renders safe API failures and a terminal playback command', async () => {
    setupNetwork();
    render(<App />);
    expect(document.querySelector('.command-line')).toHaveTextContent('PYTHONPATH=src .venv/bin/python -m matchpulse_sim play --scenario balanced --seed 17 --speed 10');
    fireEvent.change(screen.getByLabelText('Connect to an existing local match'), { target: { value: 'missing' } });
    fireEvent.click(screen.getByRole('button', { name: /connect/i }));
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
  });
});
