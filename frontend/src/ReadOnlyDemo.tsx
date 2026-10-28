import fixtureJson from './demo-fixture.json';
import {
  parseEvent,
  parseIntelligence,
  parseMatchState,
  type IntelligenceResponse,
  type MatchEvent,
  type NarrativeResponse,
} from './api';

const fixture = loadFixture();

function loadFixture() {
  const state = parseMatchState(fixtureJson.state);
  const events = fixtureJson.events.map(parseEvent).sort((left, right) => left.sequence - right.sequence);
  const intelligence = parseIntelligence(fixtureJson.intelligence);
  const narrative = fixtureJson.narrative as NarrativeResponse;
  const eventIds = new Set(events.map((event) => event.event_id));
  const insightById = new Map(intelligence.insights.map((insight) => [insight.insight_id, insight]));

  if (state.status !== 'ended' || state.synthetic !== true
    || state.match_id !== intelligence.match_id
    || state.simulation_run_id !== intelligence.simulation_run_id
    || events.length !== state.last_finalized_sequence
    || events.some((event, index) => event.sequence !== index + 1
      || event.match_id !== state.match_id
      || event.simulation_run_id !== state.simulation_run_id)
    || events.at(-1)?.event_id !== state.last_finalized_event_id
    || intelligence.as_of.sequence !== state.last_finalized_sequence
    || intelligence.insights.some((insight) => insight.evidence_event_ids.length === 0
      || insight.evidence_event_ids.some((id) => !eventIds.has(id)))
    || narrative.schema_version !== 1
    || narrative.narrative_kind !== 'match_insight_explanation'
    || narrative.provider !== 'deterministic-fake'
    || narrative.match_id !== state.match_id
    || narrative.simulation_run_id !== state.simulation_run_id
    || narrative.synthetic !== true
    || narrative.blocks.length === 0
    || narrative.blocks.some((block) => block.insight_ids.length !== 1
      || block.claim_ids.length !== 1
      || block.insight_ids.some((id) => !insightById.has(id))
      || block.evidence_event_ids.length === 0
      || block.evidence_event_ids.some((id) => !eventIds.has(id)
        || !insightById.get(block.insight_ids[0])?.evidence_event_ids.includes(id)))) {
    throw new Error('The static synthetic match fixture is incomplete or inconsistent.');
  }

  return { state, events, intelligence, narrative };
}

function formatClock(milliseconds: number | null | undefined): string {
  if (milliseconds == null) return '—';
  const totalMinutes = Math.floor(milliseconds / 60_000);
  const seconds = Math.floor(milliseconds / 1_000) % 60;
  return `${totalMinutes}:${String(seconds).padStart(2, '0')}`;
}

function titleCase(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function eventIcon(type: string): string {
  return ({ goal: '⚽', shot: '↗', pressure: '⌁', foul: '!', half_time: 'Ⅱ', full_time: '■', match_start: '▶' })[type] ?? '·';
}

function eventDetail(event: MatchEvent, labels: Record<string, string>): string {
  if (event.team_id) return labels[event.team_id] ?? event.team_id;
  if (event.type === 'match_start') return 'Kick-off';
  return event.outcome ? titleCase(event.outcome) : 'Match event';
}

export function ReadOnlyDemo() {
  const start = fixture.events[0];
  const home = start.data.home_team as { team_id: string; name: string };
  const away = start.data.away_team as { team_id: string; name: string };
  const labels = { [home.team_id]: home.name, [away.team_id]: away.name };
  const homeStats = fixture.intelligence.metric_snapshot.teams.find((team) => team.role === 'home');
  const awayStats = fixture.intelligence.metric_snapshot.teams.find((team) => team.role === 'away');
  const timelineEvents = fixture.events;

  return (
    <main className="app-shell" id="top">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="MatchPulse AI home"><span className="brand-mark">MP</span><span>MatchPulse<span className="brand-ai"> AI</span></span></a>
        <span className="synthetic-pill"><span className="pulse-dot" /> SYNTHETIC DATA</span>
      </header>

      <p className="readonly-banner" role="note">Read-only synthetic demo · Completed match snapshot · Not live or official Premier League data</p>

      <section className="hero">
        <div className="hero-copy"><p className="eyebrow">THE GAME, MADE EXPLAINABLE</p><h1>Every moment.<br /><em>More meaning.</em></h1><p className="hero-subtitle">A completed fictional match, with every insight tied back to the events that support it.</p></div>
      </section>

      <section className="match-board" aria-label="Completed synthetic match scoreboard">
        <div className="board-topline"><span className="live-label"><span className="status-dot" />FULL TIME · READ ONLY</span><span className="scenario-chip">{titleCase(fixture.state.scenario_id)}</span><span className="clock-label">FULL TIME <b>{formatClock(fixture.state.clock.match_elapsed_ms)}</b></span></div>
        <div className="scoreboard"><div className="team-block team-home"><span className="team-role">HOME</span><strong>{home.name}</strong></div><div className="score-center"><div className="score"><span>{fixture.state.score.home}</span><i>:</i><span>{fixture.state.score.away}</span></div><span className="score-caption">FINAL SCORE</span></div><div className="team-block team-away"><span className="team-role">AWAY</span><strong>{away.name}</strong></div></div>
        <div className="board-footer"><span><span className="mini-icon">◉</span> {fixture.state.match_id}</span><span>FINALIZED {fixture.state.last_finalized_sequence} / {fixture.state.last_finalized_sequence} EVENTS</span></div>
      </section>

      <section className="dashboard-grid">
        <article className="panel timeline-panel">
          <div className="panel-heading"><div><p className="eyebrow">MATCH FLOW</p><h2>Complete event timeline</h2></div><span className="count-badge">{timelineEvents.length} events · chronological</span></div>
          <ol className="timeline" aria-label="Complete chronological synthetic event timeline">{timelineEvents.map((event) => <li className={`timeline-item ${event.type === 'goal' ? 'timeline-goal' : ''}`} key={event.event_id} data-sequence={event.sequence}><span className="timeline-marker">{eventIcon(event.type)}</span><time>{formatClock(event.clock.match_elapsed_ms)}</time><div className="timeline-copy"><strong>{titleCase(event.type)}</strong><span>{eventDetail(event, labels)}{event.player_id ? ` · ${event.player_id}` : ''}</span></div><span className="event-sequence">{String(event.sequence).padStart(3, '0')}</span></li>)}</ol>
          <div className="panel-footnote"><span className="legend-dot" /> Complete finalized snapshot <span className="footnote-sep">·</span> Ordered by event sequence</div>
        </article>

        <div className="right-column">
          <article className="panel stats-panel">
            <div className="panel-heading"><div><p className="eyebrow">THE NUMBERS</p><h2>Match statistics</h2></div><span className="asof-label">FINAL · #{fixture.intelligence.as_of.sequence}</span></div>
            <div className="stats-table"><div className="stats-row stats-header"><span>METRIC</span><span>{home.name}</span><span>{away.name}</span></div><StatRow label="Goals" home={homeStats?.metrics.goals.value} away={awayStats?.metrics.goals.value} strong /><StatRow label="Shots" home={homeStats?.metrics.shots.value} away={awayStats?.metrics.shots.value} /><StatRow label="Goals / shot" home={homeStats?.metrics.goals_per_shot.value} away={awayStats?.metrics.goals_per_shot.value} /><StatRow label="Logged pressure" home={homeStats?.metrics.logged_pressure_events.value} away={awayStats?.metrics.logged_pressure_events.value} /><div className="outcomes"><span>SHOT OUTCOMES · HOME</span><div>{Object.entries(homeStats?.metrics.shot_outcomes ?? {}).map(([name, metric]) => <span key={name}>{titleCase(name)} <b>{metricValue(metric.value)}</b></span>)}</div><span>SHOT OUTCOMES · AWAY</span><div>{Object.entries(awayStats?.metrics.shot_outcomes ?? {}).map(([name, metric]) => <span key={name}>{titleCase(name)} <b>{metricValue(metric.value)}</b></span>)}</div></div></div>
          </article>

          <article className="panel insights-panel">
            <div className="panel-heading"><div><p className="eyebrow">EVIDENCE-LED</p><h2>Match insights</h2></div><span className="count-badge count-accent">{fixture.intelligence.insights.length}</span></div>
            <div className="insight-list">{fixture.intelligence.insights.map((insight) => <article className="insight-card readonly-insight" key={insight.insight_id}><span className="insight-content"><span className="insight-kicker">{insight.rule_id.replaceAll('_', ' ')} <b>·</b> {formatClock(insight.clock.match_elapsed_ms)}</span><strong>{insightTitle(insight)}</strong><span className="evidence-ref">Evidence events · {insight.evidence_event_ids.length} · trigger #{insight.trigger_sequence}</span><span className="evidence-ids">{insight.evidence_event_ids.map((id) => <span key={id}>{id}</span>)}</span></span></article>)}</div>
          </article>
        </div>
      </section>

      <section className="narrative-section">
        <div className="narrative-intro"><p className="eyebrow">FROM EVIDENCE TO EXPLANATION</p><h2>A clearer read<br />of the match.</h2><p>This fixed explanation was generated from finalized synthetic insights using the deterministic demo provider.</p><span className="provider-note">PRE-GENERATED · DETERMINISTIC-FAKE · NO LIVE AI REQUEST</span></div>
        <div className="narrative-output"><div className="narrative-top"><span className="narrative-tag">PRE-GENERATED SYNTHETIC NARRATIVE</span><span className="provider-tag">{fixture.narrative.provider}</span></div><div className="narrative-blocks">{fixture.narrative.blocks.map((block, index) => <blockquote key={block.claim_ids[0]}><span className="quote-index">{String(index + 1).padStart(2, '0')}</span><p>{block.text}</p><footer>Insight {block.insight_ids[0].slice(-8)} <span>·</span> Supporting events: {block.evidence_event_ids.join(', ')}</footer></blockquote>)}</div></div>
      </section>

      <footer className="site-footer"><span>MatchPulse AI <b>·</b> Fictional match intelligence</span><span>Read-only snapshot · All match data is synthetic and not official Premier League data.</span></footer>
    </main>
  );
}

function insightTitle(insight: IntelligenceResponse['insights'][number]): string {
  const facts = insight.observed_facts;
  if (insight.rule_id === 'score_change' && 'score_after' in facts) {
    const score = facts.score_after as { home: number; away: number };
    return `Score moved to ${score.home}–${score.away}`;
  }
  if (insight.rule_id === 'shot_activity' && 'qualifying_shot_count' in facts) return `${facts.qualifying_shot_count} shots in the rolling window`;
  if ('qualifying_pressure_event_count' in facts) return `${facts.qualifying_pressure_event_count} logged pressure events`;
  return titleCase(insight.rule_id);
}

function StatRow({ label, home, away, strong = false }: { label: string; home: number | string | null | undefined; away: number | string | null | undefined; strong?: boolean }) {
  return <div className={`stats-row ${strong ? 'stats-strong' : ''}`}><span>{label}</span><b>{metricValue(home)}</b><b>{metricValue(away)}</b></div>;
}

function metricValue(value: number | string | null | undefined): string {
  return value === null || value === undefined ? '—' : String(value);
}
