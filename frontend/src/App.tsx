import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ApiError,
  fetchEventHistory,
  fetchIntelligence,
  fetchMatchState,
  generateNarrative,
  mergeEvents,
  parseEvent,
  type IntelligenceResponse,
  type MatchEvent,
  type MatchState,
  type NarrativeResponse,
} from './api';

type Connection = 'idle' | 'connecting' | 'live' | 'reconnecting' | 'disconnected' | 'finalized';
const scenarioLabels: Record<string, string> = {
  balanced: 'Balanced', late_comeback: 'Late comeback', sustained_pressure: 'Sustained pressure', low_event_defensive: 'Low-event defense',
};

function formatClock(milliseconds: number | null | undefined): string {
  if (milliseconds == null) return '—';
  const totalMinutes = Math.floor(milliseconds / 60_000);
  const seconds = Math.floor(milliseconds / 1_000) % 60;
  return `${totalMinutes}:${String(seconds).padStart(2, '0')}`;
}

function teamNames(events: MatchEvent[], state: MatchState | null): Record<string, string> {
  const start = events.find((event) => event.type === 'match_start');
  const data = start?.data;
  const home = data && typeof data.home_team === 'object' && data.home_team !== null ? data.home_team as Record<string, unknown> : undefined;
  const away = data && typeof data.away_team === 'object' && data.away_team !== null ? data.away_team as Record<string, unknown> : undefined;
  const homeId = typeof home?.team_id === 'string' ? home.team_id : undefined;
  const awayId = typeof away?.team_id === 'string' ? away.team_id : undefined;
  return {
    ...(homeId ? { [homeId]: typeof home?.name === 'string' ? home.name : 'Home' } : {}),
    ...(awayId ? { [awayId]: typeof away?.name === 'string' ? away.name : 'Away' } : {}),
    ...(state?.current_possession_team_id ? {} : {}),
  };
}

function connectionText(status: Connection): string {
  return ({ idle: 'Not connected', connecting: 'Connecting', live: 'Live feed connected', reconnecting: 'Reconnecting', disconnected: 'Disconnected', finalized: 'Match finalized' })[status];
}

function metricValue(value: number | string | null | undefined): string {
  return value === null || value === undefined ? '—' : String(value);
}

export function App() {
  const [matchInput, setMatchInput] = useState('');
  const [matchId, setMatchId] = useState('');
  const [connection, setConnection] = useState<Connection>('idle');
  const [state, setState] = useState<MatchState | null>(null);
  const [events, setEvents] = useState<MatchEvent[]>([]);
  const [intelligence, setIntelligence] = useState<IntelligenceResponse | null>(null);
  const [selectedInsights, setSelectedInsights] = useState<string[]>([]);
  const [narrative, setNarrative] = useState<NarrativeResponse | null>(null);
  const [narrativeLoading, setNarrativeLoading] = useState(false);
  const [error, setError] = useState('');
  const [scenario, setScenario] = useState('balanced');
  const [seed, setSeed] = useState(17);
  const [speed, setSpeed] = useState(10);
  const [copied, setCopied] = useState(false);
  const refreshVersion = useRef(0);

  const labels = useMemo(() => teamNames(events, state), [events, state]);
  const timelineEvents = events.filter((event) => event.type !== 'match_start');
  const teams = intelligence?.metric_snapshot.teams ?? [];
  const command = `PYTHONPATH=src .venv/bin/python -m matchpulse_sim play --scenario ${scenario} --seed ${seed} --speed ${speed}`;

  useEffect(() => {
    if (!matchId) return undefined;
    const currentMatchId = matchId;
    const controller = new AbortController();
    let source: EventSource | undefined;
    let finalized = false;
    let active = true;
    setState(null);
    setEvents([]);
    setIntelligence(null);
    setNarrative(null);
    setSelectedInsights([]);
    setError('');
    setConnection('connecting');

    const refresh = async (includeHistory = true) => {
      const version = ++refreshVersion.current;
      try {
        const nextState = await fetchMatchState(currentMatchId, controller.signal);
        const [history, nextIntelligence] = includeHistory
          ? await Promise.all([
            fetchEventHistory(currentMatchId, nextState.last_finalized_sequence, controller.signal),
            fetchIntelligence(currentMatchId, controller.signal),
          ])
          : [[], await fetchIntelligence(currentMatchId, controller.signal)] as [MatchEvent[], IntelligenceResponse];
        if (!active || controller.signal.aborted || version !== refreshVersion.current) return;
        setState(nextState);
        setEvents((previous) => mergeEvents(previous, history, Math.max(nextState.last_finalized_sequence, ...previous.map((event) => event.sequence), 0)));
        setIntelligence(nextIntelligence);
        setSelectedInsights((previous) => previous.filter((id) => nextIntelligence.insights.some((insight) => insight.insight_id === id)));
        if (nextState.status === 'ended') {
          finalized = true;
          setConnection('finalized');
          source?.close();
        }
        setError('');
      } catch (caught) {
        if (!active || controller.signal.aborted) return;
        setError(caught instanceof Error ? caught.message : 'Match data could not be loaded.');
        if (!source) setConnection('disconnected');
      }
    };

    source = new EventSource(`/api/matches/${encodeURIComponent(currentMatchId)}/stream`);
    source.onopen = () => { if (active && !finalized) setConnection('live'); };
    source.onerror = () => {
      if (!active || finalized) return;
      setConnection(source?.readyState === EventSource.CLOSED ? 'disconnected' : 'reconnecting');
    };
    const onMatchEvent = (raw: Event) => {
      if (!active) return;
      try {
        const message = raw as MessageEvent<string>;
        const event = parseEvent(JSON.parse(message.data));
        if (event.match_id !== currentMatchId || (message.lastEventId && message.lastEventId !== event.event_id)) return;
        setEvents((previous) => mergeEvents(previous, [event], Math.max(event.sequence, state?.last_finalized_sequence ?? 0)));
        if (event.type === 'full_time') {
          finalized = true;
          setConnection('finalized');
          source?.close();
        }
        void refresh(false);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : 'The live event stream returned invalid data.');
      }
    };
    source.addEventListener('match.event', onMatchEvent);
    void refresh();

    return () => {
      active = false;
      controller.abort();
      source?.removeEventListener('match.event', onMatchEvent);
      source?.close();
    };
  }, [matchId]);

  const connect = () => {
    const value = matchInput.trim();
    if (!value) { setError('Enter a match ID from the local playback output.'); return; }
    setMatchId(value);
  };

  const generate = async () => {
    if (!matchId || !intelligence || selectedInsights.length === 0) return;
    setNarrativeLoading(true);
    setNarrative(null);
    setError('');
    try {
      setNarrative(await generateNarrative(matchId, intelligence, selectedInsights));
    } catch (caught) {
      setError(caught instanceof ApiError ? `${caught.message} (${caught.code})` : caught instanceof Error ? caught.message : 'Narrative generation failed.');
    } finally {
      setNarrativeLoading(false);
    }
  };

  const copyCommand = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setError('Clipboard access is unavailable. Copy the command shown in the demo controls.');
    }
  };

  const selected = teams.find((team) => team.role === 'home');
  const away = teams.find((team) => team.role === 'away');
  const clock = state?.clock.match_elapsed_ms ?? intelligence?.as_of.match_elapsed_ms;

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="MatchPulse AI home"><span className="brand-mark">MP</span><span>MatchPulse<span className="brand-ai"> AI</span></span></a>
        <div className="topbar-right"><span className="synthetic-pill"><span className="pulse-dot" /> SYNTHETIC DATA</span><span className="edition-label">MATCH INTELLIGENCE / LOCAL DEMO</span></div>
      </header>

      <section className="hero" id="top">
        <div className="hero-copy"><p className="eyebrow">THE GAME, MADE EXPLAINABLE</p><h1>Every moment.<br /><em>More meaning.</em></h1><p className="hero-subtitle">A live intelligence layer for fictional football matches. Follow the evidence from event to insight to narrative.</p></div>
        <div className="connect-card">
          <label htmlFor="match-id">Connect to a local match</label>
          <div className="connect-row"><input id="match-id" value={matchInput} onChange={(event) => setMatchInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') connect(); }} placeholder="Paste match ID" /><button className="button button-primary" onClick={connect}>Connect <span aria-hidden="true">↗</span></button></div>
          <p>Start playback in a terminal, then connect with the match ID.</p>
        </div>
      </section>

      <section className="match-board" aria-label="Match scoreboard">
        <div className="board-topline"><span className="live-label"><span className={`status-dot status-${connection}`} />{connectionText(connection)}</span><span className="scenario-chip">{state?.scenario_id ? scenarioLabels[state.scenario_id] ?? state.scenario_id : 'AWAITING MATCH'}</span><span className="clock-label">{state?.period?.replace('_', ' ').toUpperCase() ?? (state?.status === 'ended' ? 'FULL TIME' : 'MATCH CLOCK')} <b>{formatClock(clock)}</b></span></div>
        <div className="scoreboard"><div className="team-block team-home"><span className="team-role">HOME</span><strong>{state ? labels[stateTeamId(events, 'home')] ?? 'Home' : 'Home team'}</strong></div><div className="score-center"><div className="score"><span>{state?.score.home ?? '—'}</span><i>:</i><span>{state?.score.away ?? '—'}</span></div><span className="score-caption">{state?.status === 'ended' ? 'FINAL SCORE' : state ? 'LIVE SCORE' : 'NO MATCH CONNECTED'}</span></div><div className="team-block team-away"><span className="team-role">AWAY</span><strong>{state ? labels[stateTeamId(events, 'away')] ?? 'Away' : 'Away team'}</strong></div></div>
        <div className="board-footer"><span><span className="mini-icon">◉</span> {state?.match_id ?? 'Connect to a match to begin'}</span><span>{state ? `FINALIZED ${state.last_finalized_sequence} / ACCEPTED ${state.last_accepted_sequence}` : 'LOCAL SYNTHETIC FEED'}</span></div>
      </section>

      {error && <div className="error-banner" role="alert"><span>!</span><div><strong>Something needs attention</strong><p>{error}</p></div><button aria-label="Dismiss error" onClick={() => setError('')}>×</button></div>}

      <section className="dashboard-grid">
        <article className="panel timeline-panel">
          <div className="panel-heading"><div><p className="eyebrow">MATCH FLOW</p><h2>Event timeline</h2></div><span className="count-badge">{events.filter((event) => event.type !== 'match_start').length} events</span></div>
          {!matchId ? <EmptyState title="Your match, in sequence" body="Connect to a local match to follow finalized events as they happen." /> : timelineEvents.length === 0 ? <EmptyState title="Waiting for finalized events" body="The feed will appear here as the reducer finalizes each transition." /> : <ol className="timeline">{timelineEvents.slice(-60).reverse().map((event) => <li className={`timeline-item ${event.type === 'goal' ? 'timeline-goal' : ''}`} key={event.event_id}><span className="timeline-marker">{eventIcon(event.type)}</span><time>{formatClock(event.clock.match_elapsed_ms)}</time><div className="timeline-copy"><strong>{eventTitle(event.type)}</strong><span>{event.team_id ? labels[event.team_id] ?? event.team_id : eventDetail(event)}</span></div><span className="event-sequence">{String(event.sequence).padStart(3, '0')}</span></li>)}</ol>}
          <div className="panel-footnote"><span className="legend-dot" /> Finalized events only <span className="footnote-sep">·</span> Ordered by sequence{timelineEvents.length > 60 ? ' · Latest 60 shown' : ''}</div>
        </article>

        <div className="right-column">
          <article className="panel stats-panel">
            <div className="panel-heading"><div><p className="eyebrow">THE NUMBERS</p><h2>Match statistics</h2></div><span className="asof-label">AS OF {intelligence ? `#${intelligence.as_of.sequence}` : '—'}</span></div>
            {!intelligence ? <EmptyState title="Statistics are warming up" body="Finalized match events will populate the supported metrics." compact /> : <div className="stats-table"><div className="stats-row stats-header"><span>METRIC</span><span>{selected ? labels[selected.team_id] ?? 'Home' : 'Home'}</span><span>{away ? labels[away.team_id] ?? 'Away' : 'Away'}</span></div><StatRow label="Goals" home={selected?.metrics.goals.value} away={away?.metrics.goals.value} strong /><StatRow label="Shots" home={selected?.metrics.shots.value} away={away?.metrics.shots.value} /><StatRow label="Goals / shot" home={selected?.metrics.goals_per_shot.value} away={away?.metrics.goals_per_shot.value} /><StatRow label="Logged pressure" home={selected?.metrics.logged_pressure_events.value} away={away?.metrics.logged_pressure_events.value} /><div className="outcomes"><span>SHOT OUTCOMES · HOME</span><div>{Object.entries(selected?.metrics.shot_outcomes ?? {}).map(([name, metric]) => <span key={name}>{titleCase(name)} <b>{metricValue(metric.value)}</b></span>)}</div><span>SHOT OUTCOMES · AWAY</span><div>{Object.entries(away?.metrics.shot_outcomes ?? {}).map(([name, metric]) => <span key={name}>{titleCase(name)} <b>{metricValue(metric.value)}</b></span>)}</div></div></div>}
          </article>

          <article className="panel insights-panel">
            <div className="panel-heading"><div><p className="eyebrow">EVIDENCE-LED</p><h2>Match insights</h2></div><span className="count-badge count-accent">{intelligence?.insights.length ?? 0}</span></div>
            {!intelligence || intelligence.insights.length === 0 ? <EmptyState title="No triggered insights yet" body="Rules run only on finalized evidence. New developments will appear here." compact /> : <div className="insight-list">{intelligence.insights.slice(0, 10).map((insight) => <label className="insight-card" key={insight.insight_id}><input type="checkbox" checked={selectedInsights.includes(insight.insight_id)} onChange={(event) => setSelectedInsights((previous) => event.target.checked ? [...previous, insight.insight_id].slice(-10) : previous.filter((id) => id !== insight.insight_id))} /><span className="insight-content"><span className="insight-kicker">{insight.rule_id.replaceAll('_', ' ')} <b>·</b> {formatClock(insight.clock.match_elapsed_ms)}</span><strong>{insightTitle(insight)}</strong><span className="evidence-ref">{insight.evidence_event_ids.length} evidence event{insight.evidence_event_ids.length === 1 ? '' : 's'} · finalized through #{intelligence.as_of.sequence}</span><span className="evidence-ids">{insight.evidence_event_ids.join(' · ')}</span></span></label>)}</div>}
            {intelligence?.next_cursor && <p className="panel-footnote">Showing the first 10 insights from the pinned snapshot.</p>}
          </article>
        </div>
      </section>

      <section className="narrative-section">
        <div className="narrative-intro"><p className="eyebrow">FROM EVIDENCE TO EXPLANATION</p><h2>A clearer read<br />of the match.</h2><p>Select one or more finalized insights to generate concise, evidence-linked demo narration. It uses application-approved wording.</p><button className="button button-primary narrative-button" disabled={!intelligence || selectedInsights.length === 0 || narrativeLoading} onClick={() => void generate()}>{narrativeLoading ? <><span className="spinner" /> Generating…</> : <>Generate Match Narrative <span aria-hidden="true">↗</span></>}</button><span className="provider-note">Deterministic demo narration · No live Azure call by default</span></div>
        <div className="narrative-output">{narrativeLoading ? <div className="narrative-placeholder"><span className="spinner spinner-large" /><strong>Grounding the selected insights</strong><span>Resolving claims against the finalized snapshot…</span></div> : narrative ? <><div className="narrative-top"><span className="narrative-tag">SYNTHETIC · DEMO NARRATION</span><span className="provider-tag">{narrative.provider}</span></div><div className="narrative-blocks">{narrative.blocks.map((block, index) => <blockquote key={block.claim_ids[0]}><span className="quote-index">0{index + 1}</span><p>{block.text}</p><footer>Insight {block.insight_ids[0].slice(-8)} <span>·</span> Evidence {block.evidence_event_ids.join(', ')}</footer></blockquote>)}</div></> : <div className="narrative-placeholder"><span className="quote-mark">“</span><strong>Insight-led storytelling, with receipts.</strong><span>Your selected claims stay tied to the events that support them.</span></div>}</div>
      </section>

      <section className="demo-controls panel"><div className="demo-heading"><div><p className="eyebrow">REPEATABLE DEMO</p><h2>Run a synthetic scenario</h2></div><span className="demo-label">LOCAL TERMINAL PLAYBACK</span></div><div className="demo-control-row"><label>Scenario<select value={scenario} onChange={(event) => setScenario(event.target.value)}>{Object.entries(scenarioLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label><label>Seed<input type="number" min="0" value={seed} onChange={(event) => setSeed(Number(event.target.value))} /></label><label>Playback speed<select value={speed} onChange={(event) => setSpeed(Number(event.target.value))}><option value={1}>1×</option><option value={5}>5×</option><option value={10}>10×</option><option value={20}>20×</option></select></label><button className="button button-outline" onClick={() => void copyCommand()}>{copied ? 'Copied command ✓' : 'Copy playback command'}</button></div><code className="command-line">{command}</code><p className="demo-help">Run the command in the project terminal, then paste its match ID above. Replay/reset starts a fresh match ID; this browser never launches a shell or creates ingestion requests.</p></section>

      <footer className="site-footer"><span>MatchPulse AI <b>·</b> Fictional match intelligence</span><span>All match data is synthetic and not official Premier League data.</span></footer>
    </main>
  );
}

function stateTeamId(events: MatchEvent[], role: 'home' | 'away'): string {
  const start = events.find((event) => event.type === 'match_start');
  const key = role === 'home' ? 'home_team' : 'away_team';
  const team = start?.data[key];
  if (typeof team === 'object' && team !== null && 'team_id' in team && typeof team.team_id === 'string') return team.team_id;
  return role === 'home' ? 'home' : 'away';
}

function eventIcon(type: string): string {
  return ({ goal: '⚽', shot: '↗', pressure: '⌁', foul: '!', half_time: 'Ⅱ', full_time: '■', match_start: '▶' })[type] ?? '·';
}
function eventTitle(type: string): string { return type.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()); }
function eventDetail(event: MatchEvent): string { return event.outcome ? eventTitle(event.outcome) : event.type === 'half_time' ? 'Interval' : 'Match event'; }
function titleCase(value: string): string { return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()); }
function insightTitle(insight: IntelligenceResponse['insights'][number]): string {
  const facts = insight.observed_facts;
  if (insight.rule_id === 'score_change' && 'score_after' in facts) {
    const score = facts.score_after as { home: number; away: number };
    return `Score moved to ${score.home}–${score.away}`;
  }
  if (insight.rule_id === 'shot_activity' && 'qualifying_shot_count' in facts) return `${facts.qualifying_shot_count} shots in the rolling window`;
  if ('qualifying_pressure_event_count' in facts) return `${facts.qualifying_pressure_event_count} logged pressure events`;
  return eventTitle(insight.rule_id);
}

function EmptyState({ title, body, compact = false }: { title: string; body: string; compact?: boolean }) {
  return <div className={`empty-state ${compact ? 'empty-compact' : ''}`}><span className="empty-icon">◌</span><strong>{title}</strong><p>{body}</p></div>;
}

function StatRow({ label, home, away, strong = false }: { label: string; home: number | string | null | undefined; away: number | string | null | undefined; strong?: boolean }) {
  return <div className={`stats-row ${strong ? 'stats-strong' : ''}`}><span>{label}</span><b>{metricValue(home)}</b><b>{metricValue(away)}</b></div>;
}
