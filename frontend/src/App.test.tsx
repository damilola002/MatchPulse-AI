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
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes('/missing/')) return {
      ok: false, status: 404, json: async () => ({ error: { code: 'match_not_found', message: 'match was not found' } }),
    } as Response;
    let body: unknown;
    if (url.endsWith('/state')) body = state;
    else if (url.includes('/events?')) body = { events: [startEvent, goalEvent], next_after_sequence: 4 };
    else if (url.includes('/intelligence')) body = intelligence;
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
    fireEvent.change(screen.getByLabelText('Connect to a local match'), { target: { value: 'demo-match' } });
    fireEvent.click(screen.getByRole('button', { name: /connect/i }));
    expect(await screen.findByText('SYNTHETIC DATA')).toBeInTheDocument();
    expect((await screen.findAllByText('Northbridge')).length).toBeGreaterThan(0);
    expect(document.querySelector('.score')).toHaveTextContent('1:0');
    expect(screen.getByText('Score moved to 1–0')).toBeInTheDocument();
    expect(screen.getByText(goalEvent.event_id)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith('/narratives'))).toBe(false);
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: /generate match narrative/i }));
    expect(await screen.findByText('The home side scored, changing the score from 0–0 to 1–0.')).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input, init]) => String(input).endsWith('/narratives') && init?.method === 'POST')).toBe(true);
  });

  it('deduplicates replayed SSE events and reports reconnect state', async () => {
    setupNetwork();
    render(<App />);
    fireEvent.change(screen.getByLabelText('Connect to a local match'), { target: { value: 'demo-match' } });
    fireEvent.click(screen.getByRole('button', { name: /connect/i }));
    await screen.findByText('Live feed connected');
    latestSource.emit(goalEvent);
    latestSource.emit(goalEvent);
    await waitFor(() => expect(document.querySelectorAll('.timeline-item')).toHaveLength(1));
    expect(screen.getByText('Live feed connected')).toBeInTheDocument();
  });

  it('renders safe API failures and a terminal playback command', async () => {
    setupNetwork();
    render(<App />);
    expect(document.querySelector('.command-line')).toHaveTextContent('PYTHONPATH=src .venv/bin/python -m matchpulse_sim play --scenario balanced --seed 17 --speed 10');
    fireEvent.change(screen.getByLabelText('Connect to a local match'), { target: { value: 'missing' } });
    fireEvent.click(screen.getByRole('button', { name: /connect/i }));
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
  });
});
