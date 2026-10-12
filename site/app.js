/* Catan Night front end. Renders dist/data/stats.json; computes nothing heavy. */
(function () {
  "use strict";
  const { lineChart, barChart, Tip, esc, forestPlot, coefPlot, nullBars, arrow, markerLegend, infoButton } = window.Charts;
  const M = window.METHODS || {};
  // Pages and page sections added by other scripts (site/network.js, site/classes.js, ...).
  // window.Pages[path] = {render(ctx)}; window.Hooks[page] = [{html(ctx, arg) -> string, draw(ctx, arg)}].
  const Pages = (window.Pages = window.Pages || {});
  const Hooks = (window.Hooks = window.Hooks || {});
  const hookList = (page) => Hooks[page] || [];
  // What a page or hook gets to work with: the current view and the shared helpers.
  const ctx = () => ({ main, ROOT, S, P, VIEW, who, color, info, esc, num, pct, signed, fmtSigned, ord, fmtDate,
    tableView, filterBar, gameLabel, mk, guardNote, Charts: window.Charts, M });
  const hooksHtml = (page, arg) => hookList(page).map((h) => (h.html ? h.html(ctx(), arg) || "" : "")).join("");
  const hooksDraw = (page, arg) => hookList(page).forEach((h) => h.draw && h.draw(ctx(), arg));
  const main = document.getElementById("main");
  let ROOT = null;       // stats.json
  let VIEW = "all";      // current filter, kept in the URL as ?view=
  let S = null;          // the current view's stats, plus the shared fields from ROOT
  let P = {};            // player id -> player stats in the current view

  // ---- Formatting helpers ---------------------------------------------------
  const pct = (x, d = 0) => (x === null || x === undefined ? "n/a" : (x * 100).toFixed(d) + "%");
  const num = (x, d = 1) => (x === null || x === undefined ? "n/a" : Number(x).toFixed(d));
  // Each player is drawn in the site's version of the TwoSheep color they use most (build.py player_colors).
  const color = (pid) => (P[pid] && P[pid].color ? `var(--tc-${P[pid].color})` : `var(--p${(P[pid] && P[pid].color_slot) || 1})`);
  const ord = (n) => {
    const s = ["th", "st", "nd", "rd"], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
  };
  const fmtDate = (iso, opts) => new Date(iso + "T12:00:00").toLocaleDateString("en-US",
    opts || { month: "short", day: "numeric", year: "numeric" });
  const signed = (x, d = 1) => (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d);
  const isGuest = (pid) => String(pid).startsWith("guest-");
  // Small inline graphics: a gold trophy on the leader's icon, and a flame for anyone on fire.
  const TROPHY = `<svg class="trophy" viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 3.5H1.8v1.2a3 3 0 0 0 3 3M12.5 3.5h1.7v1.2a3 3 0 0 1-3 3" fill="none" stroke="#c99a2e" stroke-width="1.4"/><path d="M4 1.5h8v4a4 4 0 0 1-8 0z" fill="#e3b23c"/><path d="M6.6 9.2h2.8l.4 2.6H6.2z" fill="#c99a2e"/><rect x="4.5" y="12" width="7" height="2.5" rx=".8" fill="#e3b23c"/><path d="M5.6 2.6h1.2v3.2a2 2 0 0 0 .6 1.4" fill="none" stroke="#fff3c9" stroke-width=".9" stroke-linecap="round"/></svg>`;
  const FLAME = `<svg class="flame" viewBox="0 0 16 20" aria-hidden="true"><path class="flame-out" d="M8 .5c1 4 6 6 6 11.5 0 4.4-2.7 7.5-6 7.5S2 16.4 2 12c0-3 1.9-5 3-7 .5 2.4 1.5 3.4 2.5 3.4C7 5.5 7.4 2.6 8 .5z"/><path class="flame-in" d="M8 8.8c1 2 3 3.4 3 6 0 2.4-1.3 3.9-3 3.9S5 17.4 5 15.3c0-2 1.5-3 2-4.5.3 1.2.8 1.7 1.3 1.7-.3-1.2-.5-2.4-.3-3.7z"/></svg>`;
  const onFire = (pid) => !!(P[pid] && P[pid].recent && P[pid].recent.on_fire);
  const who = (pid, link = true) => {
    if (isGuest(pid)) return `<span class="who guest"><span class="hex" aria-hidden="true"></span><span>Guest</span></span>`;
    const p = P[pid];
    const name = p ? esc(p.name) : esc(pid);
    const lead = p && p.leaderboard_rank === 1;
    const inner = `<span class="pmark${lead ? " lead" : ""}"${lead ? ' title="First on the leaderboard"' : ""}><span class="hex" style="--c:${color(pid)}" aria-hidden="true"></span>${lead ? TROPHY : ""}</span><span>${name}</span>`;
    return link ? `<a class="who" href="#/player/${encodeURIComponent(pid)}">${inner}</a>` : `<span class="who">${inner}</span>`;
  };
  const aliasList = (p) => p.aliases.map(esc).join(", ");
  const gameLabel = (g) => `Game ${g.number}, ${fmtDate(g.date)}`;
  const viewInfo = (key) => ROOT.view_list.find((v) => v.key === key);
  const viewLabel = (key) => { const v = viewInfo(key); return v ? (v.parent && v.parent !== "all" ? `${viewInfo(v.parent).label}: ${v.label}` : v.label) : key; };
  const VP_LABELS = { settlements: "Settlements", cities: "Cities", vp_cards: "VP cards", largest_army: "Largest army",
    longest_road: "Longest road", islands: "New islands", other: "Other VP" };
  const gamesByIndex = () => Object.fromEntries(S.games.map((g) => [g.index, g]));

  function tableView(headers, rows, summary = "Show as table") {
    const th = headers.map((h) => `<th class="${h.num ? "num" : ""}">${h.label}</th>`).join("");
    const tr = rows.map((r) => "<tr>" + r.map((c, i) => `<td class="${headers[i].num ? "num" : ""}">${c}</td>`).join("") + "</tr>").join("");
    return `<details class="tv"><summary>${summary}</summary><div class="table-wrap"><table><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div></details>`;
  }

  // A small bar centred on zero, for numbers that can be above or below expectation.
  function divBar(v, max) {
    const w = Math.min(50, (Math.abs(v) / (max || 1)) * 50);
    const x = v >= 0 ? 50 : 50 - w;
    return `<svg class="divbar" viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true">
      <line x1="50" x2="50" y1="0" y2="10" style="stroke:var(--axis)" stroke-width="1" vector-effect="non-scaling-stroke"/>
      <rect x="${x}" y="2" width="${w}" height="6" rx="1" style="fill:${v >= 0 ? "var(--div-pos)" : "var(--div-neg)"}"/></svg>`;
  }

  // ---- Method notes and "vs the table" markers --------------------------------
  let infoSeq = 0;
  const info = (key, title) => (M[key] ? infoButton(`info-${key}-${++infoSeq}`, title, M[key]) : "");
  const ins = () => S.insights || {};
  const fmtSigned = (x, d = 1) => (x === null || x === undefined ? "n/a" : signed(x, d));
  // Marker for one player's stat from the build's "vs the table" table, or "" when there is none.
  function mk(pid, key) {
    const m = ((ins().markers || {})[pid] || {})[key];
    if (!m) return "";
    const good = m.good === 1 ? "up" : m.good === -1 ? "down" : "neutral";
    if (key === "wins") {
      return arrow(m.z, { clear: m.clear, good, unit: "z", tip: `Wins against Σ 1/n over ${m.games} games: z = ${num(m.z, 2)}` });
    }
    if (key === "beat_rate") {
      return arrow(m.diff * 100, { clear: m.clear, good, unit: "pts", digits: 0,
        tip: `Beat rate minus 50%: ${fmtSigned(m.diff * 100, 1)} points (95% interval ${fmtSigned(m.lo * 100, 1)} to ${fmtSigned(m.hi * 100, 1)}), ${m.games} games` });
    }
    return arrow(Math.abs(m.delta) < 0.05 ? 0 : m.delta, { clear: m.clear, good,
      tip: `${fmtSigned(m.delta, 2)} SD vs the rest of the table over ${m.games} games (95% interval ${fmtSigned(m.lo, 2)} to ${fmtSigned(m.hi, 2)})` });
  }
  const hasMarkers = (pid) => Object.keys((ins().markers || {})[pid] || {}).length > 0;
  const guardNote = (n, need) => `<p class="empty">Needs ${need} games in this view (has ${n}).</p>`;

  // Replay numbers for one player in one game, from the shared copy in stats.json.
  const replayOf = (g, pid) => ((ROOT.game_replays || {})[g.id] || {})[pid];

  // ---- Coastline: one honeycomb strip in the standard tile mix --------------
  function drawCoast() {
    const svg = document.getElementById("coast");
    const tiles = { lumber: "#2f6b3a", grain: "#e3b23c", wool: "#93c15a", brick: "#b3532e", ore: "#7d858c", desert: "#d9c48f" };
    const bag = [].concat(Array(4).fill("lumber"), Array(4).fill("grain"), Array(4).fill("wool"),
      Array(3).fill("brick"), Array(3).fill("ore"), ["desert"]);
    let seed = 7;
    const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    const r = 11, w = Math.sqrt(3) * r;
    let html = "", k = 0, deck = [];
    const next = () => {
      if (!deck.length) deck = bag.slice().sort(() => rnd() - 0.5);
      return deck.pop();
    };
    for (let row = 0; row < 2; row++) {
      const cy = 10 + row * 1.5 * r, off = row ? w / 2 : 0;
      for (let i = -1; i * w < 2800; i++) {
        const cx = i * w + off;
        const pts = [0, 1, 2, 3, 4, 5].map((j) => {
          const a = Math.PI / 180 * (60 * j - 90);
          return (cx + (r - 1) * Math.cos(a)).toFixed(1) + "," + (cy + (r - 1) * Math.sin(a)).toFixed(1);
        }).join(" ");
        html += `<polygon points="${pts}" fill="${tiles[next()]}"/>`;
        k++;
      }
    }
    svg.innerHTML = html;
  }

  // ---- Game type filter ---------------------------------------------------------
  // One row of choices above the page; Seafarers scenarios appear as a second row.
  function filterBar() {
    const list = ROOT.view_list;
    if (list.length < 2) return "";
    const cur = viewInfo(VIEW) || list[0];
    const family = cur.parent && cur.parent !== "all" ? cur.parent : cur.key;
    const link = (v, text) => {
      const sel = v.key === VIEW;
      const within = !sel && v.key === family && VIEW !== family; // parent of the chosen scenario
      return `<a class="chip${sel ? " on" : within ? " within" : ""}" data-keep href="#/${PAGE_PATH}${v.key === "all" ? "" : "?view=" + encodeURIComponent(v.key)}"${sel ? ' aria-current="true"' : ""}>${esc(text)} <span class="n">${v.games}</span></a>`;
    };
    const top = list.filter((v) => v.key === "all" || v.parent === "all");
    const kids = family === "all" ? [] : list.filter((v) => v.parent === family);
    const fam = viewInfo(family);
    let html = `<nav class="filter" aria-label="Filter by game type"><div class="chips">${top.map((v) => link(v, v.label)).join("")}</div>`;
    if (kids.length) {
      html += `<div class="chips sub">${link(fam, "Any scenario")}${kids.map((v) => link(v, v.label)).join("")}</div>`;
    }
    if (fam && fam.unlabeled_scenarios) {
      html += `<p class="note">${fam.unlabeled_scenarios} ${fam.label} ${fam.unlabeled_scenarios === 1 ? "game has" : "games have"} no scenario recorded, so ${fam.unlabeled_scenarios === 1 ? "it only counts" : "they only count"} under ${esc(fam.label)}.</p>`;
    }
    return html + "</nav>";
  }
  let PAGE_PATH = "";

  // ---- Pages ------------------------------------------------------------------
  function leaderboard() {
    const ranked = S.players.filter((p) => p.games > 0);
    const s = S.summary;
    if (!ranked.length) {
      main.innerHTML = `<h1>Leaderboard</h1>${filterBar()}<p class="empty">No games recorded yet. Add one to <code>data/games.json</code> and rebuild.</p>`;
      return;
    }
    // Each strip shares one scale: a gray band for what luck alone covers 95% of the time, and the player's dot.
    const R = Math.max(...ranked.map((p) => Math.max(Math.abs(p.above_expected), ...p.luck_band.map(Math.abs)))) * 1.05;
    const strip = (p) => {
      const W = 160, X = (v) => W / 2 + (v / R) * (W / 2 - 6);
      return `<svg viewBox="0 0 ${W} 18" preserveAspectRatio="none" aria-hidden="true">
        <rect x="${X(p.luck_band[0])}" y="3" width="${X(p.luck_band[1]) - X(p.luck_band[0])}" height="12" rx="3" style="fill:var(--band)"/>
        <line x1="${X(0)}" x2="${X(0)}" y1="1" y2="17" style="stroke:var(--axis)" stroke-width="1"/>
        <circle cx="${X(p.above_expected)}" cy="9" r="4" style="fill:${color(p.id)};stroke:var(--surface)" stroke-width="2"/></svg>`;
    };
    const outside = ranked.filter((p) => p.above_expected < p.luck_band[0] || p.above_expected > p.luck_band[1]);
    const latestGame = S.games[0];
    const move = (now, before, since) => {
      if (before === null || before === undefined) return `<span class="mv new" title="First game ${since}">new</span>`;
      const d = before - now;
      if (!d) return `<span class="mv same" title="No change ${since}"><span class="sr">no change</span></span>`;
      return `<span class="mv ${d > 0 ? "up" : "down"}" title="${d > 0 ? "Up" : "Down"} ${Math.abs(d)} ${Math.abs(d) === 1 ? "place" : "places"} ${since}">${d > 0 ? "▲" : "▼"}${Math.abs(d)}</span>`;
    };
    const sinceLast = `since the last game (${fmtDate(latestGame.date)})`;
    const fireTag = (p) => (onFire(p.id) ? `<span class="fire-tag" title="On fire: ${fmtSigned(p.recent.above, 1)} wins above expected over their last ${S.ranking.recent_games} games">${FLAME}</span>` : "");
    const rows = ranked.map((p) => `<tr${onFire(p.id) ? ' class="hot"' : ""}>
        <td class="rank">${p.leaderboard_rank}${S.games.length > 1 ? move(p.leaderboard_rank, p.rank_prev, sinceLast) : ""}</td>
        <td><span class="name-cell">${who(p.id)}${fireTag(p)}</span></td>
        <td class="num score">${fmtSigned(p.above_expected, 1)}</td>
        <td class="range hide-sm" title="${fmtSigned(p.above_expected, 2)} wins above expected. Luck alone covers ${fmtSigned(p.luck_band[0], 1)} to ${fmtSigned(p.luck_band[1], 1)} 95% of the time.">${strip(p)}</td>
        <td class="num">${p.wins}</td>
        <td class="num hide-sm">${num(p.expected_wins)}</td>
        <td class="num hide-sm">${p.games}</td>
        <td class="num">${pct(p.win_rate)}<div class="sub hide-sm">${pct(p.win_rate_ci[0])} to ${pct(p.win_rate_ci[1])}</div></td>
        <td class="num hide-sm">${num(p.avg_vp)}</td>
        <td class="num hide-sm">${pct(p.beat_rate)}</td>
      </tr>`).join("");

    const latest = S.games[0];
    const RG = S.ranking.recent_games;
    const cards = ranked.filter((p) => p.recent).slice().sort((a, b) =>
      (b.recent.active - a.recent.active) || (b.recent.above - a.recent.above) || (a.leaderboard_rank - b.leaderboard_rank));
    const formDots = (p) => p.recent.games.map((h) => `<span class="fdot${h.won ? " w" : ""}" style="--c:${color(p.id)}" title="${fmtDate(h.date)}: ${h.won ? "won" : "lost"} (${signed(h.delta, 2)})"></span>`).join("");
    const card = (p) => {
      const r = p.recent, fire = r.on_fire;
      const d = p.rank_recent_ago === null || p.rank_recent_ago === undefined ? null : p.rank_recent_ago - p.leaderboard_rank;
      const rankLine = S.games.length <= RG ? "" : d === null ? `New on the board` : d ? `<span class="${d > 0 ? "up" : "down"}">${d > 0 ? "▲" : "▼"} ${Math.abs(d)} ${Math.abs(d) === 1 ? "place" : "places"}</span> in the last ${RG} games` : `Holding ${ord(p.leaderboard_rank)}`;
      return `<a class="hot-card${fire ? " fire" : ""}${r.active ? "" : " idle"}" href="#/player/${encodeURIComponent(p.id)}">
        <div class="hot-top">${who(p.id, false)}${fire ? `<span class="fire-badge">${FLAME}On fire</span>` : r.streak >= 2 ? `<span class="streak">${r.streak} wins in a row</span>` : ""}</div>
        <div class="form" role="img" aria-label="Last ${r.games.length} games: ${r.games.map((h) => (h.won ? "won" : "lost")).join(", ")}">${formDots(p)}</div>
        <div class="hot-num"><b>${fmtSigned(r.above, 1)}</b> vs expected</div>
        <div class="hot-rank">${r.active ? rankLine : `Last played ${fmtDate(r.games[r.games.length - 1].date)}`}</div>
      </a>`;
    };
    main.innerHTML = `
      <h1>Leaderboard</h1>
      <p class="lede">${s.games} ${s.games === 1 ? "game" : "games"} played ${s.first_date === s.last_date ? "on " + fmtDate(s.first_date) : "from " + fmtDate(s.first_date) + " to " + fmtDate(s.last_date)}.
        Ranked by wins above expected: a win counts 1, and every game counts your fair share of wins against you, 1 divided by the number of players. <a href="#/about">How the ranking works</a></p>
      ${filterBar()}
      <section class="block panel">
        <div class="table-wrap"><table class="board">
          <thead><tr>
            <th>#</th><th>Player</th><th class="num">Above expected</th>
            <th class="hide-sm">Against luck</th>
            <th class="num">Wins</th><th class="num hide-sm">Expected</th><th class="num hide-sm">Games</th><th class="num">Win rate</th>
            <th class="num hide-sm">Avg VP</th><th class="num hide-sm">Beat rate</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table></div>
      </section>
      <p class="note">Arrows show how each place changed since the last game (${fmtDate(latest.date)}). Expected is the number of wins chance alone would give. The gray band in each strip is the range luck alone covers 95% of the time. ${outside.length ? `${outside.map((p) => `${esc(p.name)} (${p.above_expected > 0 ? "above" : "below"})`).join(", ")} ${outside.length === 1 ? "is" : "are"} outside it so far.` : "Nobody is outside it yet, so the order could still be luck."} Ties go to the higher share of the table's VP. Win rate shows a 95% interval underneath. Beat rate is the share of opponents a player finished ahead of.</p>

      ${cards.length ? `<section class="block">
        <h2>Last ${RG} games</h2>
        <p class="note">Each player's own last ${RG} games, newest on the right, with wins above expected over just those games. On fire means at least ${num(S.ranking.fire_above, 0)} full win above expected across them. Places moved count the group's last ${RG} games.</p>
        <div class="hot-grid">${cards.map(card).join("")}</div>
      </section>` : ""}

      <section class="block">
        <h2>Wins above expected over time</h2>
        <p class="note">Each player's running total after every game they played. A win moves the line up by 1 minus their fair share, a loss moves it down by their fair share.</p>
        <div class="panel"><div class="chart" id="trend-legend"></div><div class="chart" id="trend"></div><div id="trend-table"></div></div>
      </section>

      <section class="block">
        <h2>Latest game</h2>
        <p class="note">${fmtDate(latest.date)}: ${who(latest.winner)} won with ${latest.players[0].vp} VP${latest.turns ? ` in ${latest.turns} turns` : ""}. <a href="#/game/${encodeURIComponent(latest.id)}">See the full game</a></p>
      </section>`;

    const series = ranked.map((p) => ({
      id: p.id, name: p.name, color: color(p.id),
      points: [{ x: 0, y: 0, tip: num(0, 2) }]
        .concat(p.standing_history.map((h) => ({ x: h.index, y: h.above_expected, tip: fmtSigned(h.above_expected, 2) }))),
    }));
    const legend = document.getElementById("trend-legend");
    legend.innerHTML = `<ul class="legend">${ranked.map((p) => `<li><span class="sw" style="--c:${color(p.id)}"></span>${esc(p.name)}</li>`).join("")}</ul>`;
    legend.style.paddingBottom = "0";
    const gi = gamesByIndex();
    lineChart(document.getElementById("trend"), {
      series, yRef: 0, ariaLabel: "Wins above expected for each player after every game",
      xLabel: (x) => (x === 0 ? "<b>Start</b>" : `<b>${esc(gameLabel(gi[x]))}</b>`),
      xTickLabel: (x) => (x === 0 ? "start" : x),
    });
    const xs = [...new Set(series.flatMap((s) => s.points.map((p) => p.x)))].sort((a, b) => a - b);
    document.getElementById("trend-table").innerHTML = tableView(
      [{ label: "Game" }].concat(ranked.map((p) => ({ label: esc(p.name), num: true }))),
      xs.map((x) => [x === 0 ? "Start" : esc(gameLabel(gi[x]))].concat(series.map((s) => {
        const pt = s.points.find((p) => p.x === x); return pt ? num(pt.y) : "";
      }))));
  }

  function playerPage(pid) {
    const p = P[pid];
    if (!p) return notFound(`There's no player with the id "${esc(pid)}".`);
    if (!p.games) {
      main.innerHTML = `<a class="back" href="#/">Back to leaderboard</a><h1>${esc(p.name)}</h1>${filterBar()}<p class="empty">${esc(p.name)} hasn't played ${VIEW === "all" ? "a recorded game" : `a recorded ${esc(viewLabel(VIEW))} game`} yet.</p>`;
      return;
    }
    const active = S.players.filter((x) => x.games > 0).length;
    const gi = gamesByIndex();
    const myGames = S.games.filter((g) => g.players.some((r) => r.player === pid));
    const h2h = S.head_to_head.filter((h) => h.player === pid)
      .sort((a, b) => (P[a.opponent].leaderboard_rank || 99) - (P[b.opponent].leaderboard_rank || 99));
    const maxRank = Math.max(...Object.keys(p.finish_counts).map(Number), ...myGames.map((g) => g.n_players));

    // Detail stats only exist for games typed in from the end screen, so say how many that is.
    const basedOn = (n, what) => (n && n < p.games
      ? ` Based on the ${n} of ${p.games} ${p.games === 1 ? "game" : "games"} with ${what} recorded.` : "");
    const vpNames = Object.fromEntries(Object.entries(VP_LABELS)
      .filter(([k]) => k !== "other" || (p.vp_sources_avg && p.vp_sources_avg.other)));
    const vpBars = p.vp_sources_avg ? (() => {
      const mx = Math.max(...Object.values(p.vp_sources_avg), 0.01);
      return `<div class="table-wrap"><table><tbody>${Object.entries(vpNames).map(([k, label]) => `
        <tr><td>${label}</td>
          <td style="width:55%"><svg width="100%" height="10" aria-hidden="true"><rect x="0" y="1" height="8" rx="2" width="${(p.vp_sources_avg[k] / mx) * 100}%" style="fill:var(--data)"/></svg></td>
          <td class="num">${num(p.vp_sources_avg[k])}</td><td class="num">${mk(pid, "vp_" + k)}</td></tr>`).join("")}</tbody></table></div>`;
    })() : `<p class="empty">No VP breakdowns recorded yet.</p>`;

    const colorRows = Object.entries(p.by_color || {});
    const colorMax = Math.max(1, ...colorRows.map(([, n]) => n));
    const colorHtml = colorRows.length ? `<div class="panel table-wrap"><table>
        <thead><tr><th>Color</th><th style="width:50%"></th><th class="num">Games</th><th class="num">Share</th></tr></thead>
        <tbody>${colorRows.map(([c, n]) => `<tr><td><span class="hex" style="--c:var(--tc-${esc(c)}, var(--muted))" aria-hidden="true"></span> ${esc(c[0].toUpperCase() + c.slice(1))}</td>
          <td><svg width="100%" height="10" aria-hidden="true"><rect x="0" y="1" height="8" rx="2" width="${(n / colorMax) * 100}%" style="fill:var(--tc-${esc(c)}, var(--muted))"/></svg></td>
          <td class="num">${n}</td><td class="num">${pct(n / p.games)}</td></tr>`).join("")}</tbody></table></div>`
      : `<p class="empty">No piece colors recorded for ${esc(p.name)}'s games yet.</p>`;

    const seats = Object.keys(p.by_seat);
    const seatHtml = seats.length ? `<div class="panel table-wrap"><table>
        <thead><tr><th>Seat</th><th class="num">Games</th><th class="num">Wins</th><th class="num">Win rate</th><th class="num">Avg finish</th></tr></thead>
        <tbody>${seats.map((k) => { const v = p.by_seat[k]; return `<tr><td>${ord(+k)} to play</td><td class="num">${v.games}</td><td class="num">${v.wins}</td><td class="num">${pct(v.win_rate)}</td><td class="num">${num(v.avg_rank)}</td></tr>`; }).join("")}</tbody></table></div>`
      : `<p class="empty">Seat order hasn't been recorded for ${esc(p.name)}'s games yet. Add a <code>seat</code> number for each player in <code>games.json</code> to fill this in.</p>`;

    const rp = p.replay;
    const hasSteals = h2h.some((h) => h.replay_games);
    const rpHtml = rp ? `<section class="block">
        <h2>From the replays</h2>
        <p class="note">Averages per game, read from TwoSheep's turn-by-turn record.${basedOn(rp.games, "a replay")} <a href="#/style">Compare everyone</a></p>
        <div class="tiles">
          <div class="tile"><div class="v">${num(rp.dice_ratio, 2)}×<span class="tile-mk">${mk(pid, "luck")}</span></div><div class="k">Dice luck</div><div class="s">${num(rp.avg_resources_from_dice)} cards from dice against ${num(rp.avg_expected_from_dice)} expected</div></div>
          <div class="tile"><div class="v">${num(rp.avg_opening_dots)}<span class="tile-mk">${mk(pid, "opening_dots")}</span></div><div class="k">Opening dots</div><div class="s">Number dots under the two starting settlements</div></div>
          <div class="tile"><div class="v">${num(rp.avg_steals)}<span class="tile-mk">${mk(pid, "steals")}</span></div><div class="k">Steals</div><div class="s">Robbed ${num(rp.avg_stolen_from)} times by others</div></div>
          <div class="tile"><div class="v">${num(rp.avg_cards_discarded)}<span class="tile-mk">${mk(pid, "cards_discarded")}</span></div><div class="k">Cards lost to 7s</div><div class="s">${num(rp.avg_blocked_by_robber)} more blocked by the robber</div></div>
          <div class="tile"><div class="v">${num(rp.avg_trades)}<span class="tile-mk">${mk(pid, "trades")}</span></div><div class="k">Player trades</div><div class="s">${num(rp.avg_bank_trades)} bank and port trades</div></div>
          <div class="tile"><div class="v">${num(rp.avg_built_city)}<span class="tile-mk">${mk(pid, "built_city")}</span></div><div class="k">Cities built</div><div class="s">${num(rp.avg_built_settlement)} settlements, ${num(rp.avg_built_road)} roads, ${num(rp.avg_built_ship)} ships</div></div>
        </div>
      </section>` : "";

    const dc = p.dev_cards_bought;
    const devHtml = dc ? `<div class="panel table-wrap"><table><thead><tr><th>Card</th><th class="num">Bought</th><th class="num">Per game</th></tr></thead><tbody>
        ${[["knight", "Knight"], ["victory_point", "Victory point"], ["road_building", "Road building"], ["year_of_plenty", "Year of plenty"], ["monopoly", "Monopoly"]]
          .map(([k, l]) => `<tr><td>${l}</td><td class="num">${dc[k]}</td><td class="num">${num(dc[k] / dc.games, 2)}</td></tr>`).join("")}
      </tbody></table></div>` : `<p class="empty">No dev card purchases recorded yet.</p>`;

    main.innerHTML = `
      <a class="back" href="#/">Back to leaderboard</a>
      <div class="player-head${p.leaderboard_rank === 1 ? " lead" : ""}"><span class="pmark"${p.leaderboard_rank === 1 ? ' title="First on the leaderboard"' : ""}><span class="hex" style="--c:${color(pid)}" aria-hidden="true"></span>${p.leaderboard_rank === 1 ? TROPHY : ""}</span><h1>${esc(p.name)}</h1></div>
      <p class="lede">Ranked ${ord(p.leaderboard_rank)} of ${active}. ${p.games} ${p.games === 1 ? "game" : "games"} recorded.</p>
      ${onFire(pid) ? `<p class="fire-line">${FLAME}<span><b>On fire.</b> ${fmtSigned(p.recent.above, 1)} wins above expected over ${esc(p.name)}'s last ${S.ranking.recent_games} games.</span></p>` : ""}      ${filterBar()}

      <div class="tiles">
        <div class="tile"><div class="v">${fmtSigned(p.above_expected, 1)}</div><div class="k">Wins above expected</div><div class="s">Luck alone lands between ${fmtSigned(p.luck_band[0], 1)} and ${fmtSigned(p.luck_band[1], 1)} 95% of the time</div></div>
        <div class="tile"><div class="v">${pct(p.win_rate)}</div><div class="k">Win rate</div><div class="s">95% interval ${pct(p.win_rate_ci[0])} to ${pct(p.win_rate_ci[1])}</div></div>
        <div class="tile"><div class="v">${p.wins}<span class="tile-mk">${mk(pid, "wins")}</span></div><div class="k">Wins</div><div class="s">${num(p.expected_wins)} expected by chance</div></div>
        <div class="tile"><div class="v">${pct(p.beat_rate)}<span class="tile-mk">${mk(pid, "beat_rate")}</span></div><div class="k">Beat rate</div><div class="s">Opponents finished ahead of</div></div>
        <div class="tile"><div class="v">${num(p.avg_vp)}<span class="tile-mk">${mk(pid, "vp")}</span></div><div class="k">Average VP</div><div class="s">${pct(p.avg_vp_share)} of the VP needed to win</div></div>
      </div>
      ${hasMarkers(pid) ? `<div class="mk-key">${markerLegend()}<span class="note">Markers compare ${esc(p.name)} with the rest of the same tables. ${info("markers", "vs the table markers")}</span></div>` : ""}

      <section class="block">
        <h2>Wins above expected over time</h2>
        <p class="note">${esc(p.name)}'s running total after each game. The shaded band is the range luck alone covers 95% of the time.</p>
        <div class="panel"><div class="chart" id="p-trend"></div><div id="p-trend-table"></div></div>
      </section>

      <div class="two-col">
        <section class="block">
          <h2>Finishing positions</h2>
          <p class="note">How often ${esc(p.name)} finished in each place.</p>
          <div class="panel"><div class="chart" id="p-finish"></div></div>
        </section>
        <section class="block">
          <h2>Where the points come from</h2>
          <p class="note">Average VP per game from each source.${basedOn(p.vp_sources_games, "a VP breakdown")}</p>
          <div class="panel">${vpBars}</div>
        </section>
      </div>

      <section class="block">
        <h2>Head to head</h2>
        <p class="note">In games played together, how often ${esc(p.name)} finished ahead. Ties count as half.${hasSteals ? " Steals count cards taken with the robber or pirate." : ""}</p>
        <div class="panel table-wrap"><table>
          <thead><tr><th>Opponent</th><th class="num">Games</th><th class="num">Finished ahead</th><th class="num">${esc(p.name)} won</th><th class="num">They won</th>${hasSteals ? `<th class="num">Stole from them</th><th class="num">They stole</th>` : ""}</tr></thead>
          <tbody>${h2h.map((h) => `<tr><td>${who(h.opponent)}</td><td class="num">${h.games}</td><td class="num">${h.ahead + h.tied / 2} of ${h.games} <span class="sub">(${pct(h.ahead_rate)})</span></td><td class="num">${h.wins}</td><td class="num">${h.losses_to}</td>${hasSteals ? `<td class="num">${h.replay_games ? h.steals : ""}</td><td class="num">${h.replay_games ? h.stolen_by : ""}</td>` : ""}</tr>`).join("")}</tbody>
        </table></div>
      </section>

      <section class="block">
        <h2>By game type</h2>
        <div class="panel table-wrap"><table>
          <thead><tr><th>Game type</th><th class="num">Games</th><th class="num">Wins</th><th class="num">Win rate</th><th class="num">Avg VP</th><th class="num">Beat rate</th></tr></thead>
          <tbody>${Object.entries(p.by_type).map(([k, v]) => `<tr><td>${esc(v.label)}</td><td class="num">${v.games}</td><td class="num">${v.wins}</td><td class="num">${pct(v.win_rate)}</td><td class="num">${num(v.avg_vp)}</td><td class="num">${pct(v.beat_rate)}</td></tr>`).join("")}</tbody>
        </table></div>
      </section>

      <div class="two-col">
        <section class="block">
          <h2>By player count</h2>
          <div class="panel table-wrap"><table>
            <thead><tr><th>Players</th><th class="num">Games</th><th class="num">Wins</th><th class="num">Win rate</th><th class="num">Fair share</th><th class="num">Avg VP</th></tr></thead>
            <tbody>${Object.entries(p.by_player_count).map(([n, v]) => `<tr><td>${n} players</td><td class="num">${v.games}</td><td class="num">${v.wins}</td><td class="num">${pct(v.win_rate)}</td><td class="num">${pct(1 / n)}</td><td class="num">${num(v.avg_vp)}</td></tr>`).join("")}</tbody>
          </table></div>
        </section>
        <section class="block">
          <h2>By seat</h2>
          ${seatHtml}
        </section>
      </div>

      <section class="block">
        <h2>Piece colors</h2>
        <p class="note">The TwoSheep color ${esc(p.name)} played in each game. ${p.color ? `Across the site ${esc(p.name)} is drawn in ${esc(p.color)}, their most used color over all games.` : ""}</p>
        ${colorHtml}
      </section>

      ${rpHtml}
      ${playerInsights(pid, p)}
      ${hooksHtml("player", pid)}

      <div class="two-col">
        <section class="block">
          <h2>Dice production</h2>
          ${p.production.games ? `<p class="note">Resources received from dice rolls. An index of 1.00 is the table average for that game.${basedOn(p.production.games, "production")}</p>
            <div class="tiles" style="margin-top:0">
              <div class="tile"><div class="v">${num(p.production.avg_from_dice)}</div><div class="k">Resources per game</div></div>
              <div class="tile"><div class="v">${num(p.production.avg_index, 2)}</div><div class="k">Production index</div></div>
            </div>` : `<p class="empty">No production data recorded yet.</p>`}
        </section>
        <section class="block">
          <h2>Development cards bought</h2>
          ${dc && dc.games < p.games ? `<p class="note">${basedOn(dc.games, "dev cards").trim()}</p>` : ""}
          ${devHtml}
        </section>
      </div>

      <section class="block">
        <h2>Games</h2>
        <div class="panel table-wrap"><table>
          <thead><tr><th>Game</th><th class="num">Finish</th><th class="num">VP</th><th class="num">Above expected</th></tr></thead>
          <tbody>${myGames.map((g) => { const r = g.players.find((x) => x.player === pid); return `<tr>
            <td><a href="#/game/${encodeURIComponent(g.id)}">${esc(gameLabel(g))}</a></td>
            <td class="num">${ord(r.rank)} of ${g.n_players}</td><td class="num">${r.vp}</td>
            <td class="num ${r.above_expected > 0 ? "delta-up" : "delta-down"}">${signed(r.above_expected, 2)}</td></tr>`; }).join("")}</tbody>
        </table></div>
      </section>
      ${p.aliases && p.aliases.length ? `<details class="tv"><summary>TwoSheep usernames</summary><p class="note">${aliasList(p)}</p></details>` : ""}`;

    const pts = [{ x: 0, y: 0, lo: 0, hi: 0, tip: num(0, 2) }]
      .concat(p.standing_history.map((h) => ({ x: h.index, y: h.above_expected, lo: h.luck_band[0], hi: h.luck_band[1],
        tip: `${fmtSigned(h.above_expected, 2)}, luck range ${fmtSigned(h.luck_band[0], 1)} to ${fmtSigned(h.luck_band[1], 1)}` })));
    lineChart(document.getElementById("p-trend"), {
      series: [{ id: pid, name: p.name, color: color(pid), points: pts, band: true }],
      directLabels: false, height: 240, yRef: 0, ariaLabel: `Wins above expected for ${p.name} after each game`,
      xLabel: (x) => (x === 0 ? "<b>Start</b>" : `<b>${esc(gameLabel(gi[x]))}</b>`),
      xTickLabel: (x) => (x === 0 ? "start" : x),
    });
    document.getElementById("p-trend-table").innerHTML = tableView(
      [{ label: "Game" }, { label: "Wins above expected", num: true }, { label: "Luck range (95%)", num: true }],
      p.standing_history.map((h) => [esc(gameLabel(gi[h.index])), fmtSigned(h.above_expected, 2), `${fmtSigned(h.luck_band[0], 2)} to ${fmtSigned(h.luck_band[1], 2)}`]));

    hooksDraw("player", pid);
    const places = Array.from({ length: maxRank }, (_, i) => i + 1);
    barChart(document.getElementById("p-finish"), {
      height: 200, color: color(pid), valueLabels: true, ariaLabel: `Finishing positions for ${p.name}`,
      bars: places.map((k) => { const c = p.finish_counts[k] || 0; return { label: ord(k), value: c, tip: `${c} ${c === 1 ? "game" : "games"}` }; }),
    });
  }

  // Per-player numbers from the group models, with the same method notes as the Findings page.
  function playerInsights(pid, p) {
    const I = ins();
    const op = (I.opening_by_player || {})[pid], ss = (I.steal_share || {})[pid], tb = (I.trade_bank || {})[pid];
    const wr = (I.win_recipe || {})[pid];
    if (!op && !ss && !tb && !wr) return "";
    const iv = (lo, hi, f) => (lo === null || lo === undefined ? "" : `95% interval ${f(lo)} to ${f(hi)}`);
    const tiles = [];
    if (op) tiles.push(`<div class="tile"><div class="v">${fmtSigned(op.adjusted.mean, 2)}</div><div class="k">Opening dots vs table, draft-adjusted ${info("opening_player", "Opening strength vs the table")}</div><div class="s">${iv(op.adjusted.lo, op.adjusted.hi, (x) => fmtSigned(x, 2))}; raw ${fmtSigned(op.raw.mean, 2)}</div></div>`);
    if (ss) tiles.push(`<div class="tile"><div class="v">${num(ss.ratio, 2)}×</div><div class="k">Robbed vs an even split ${info("steal_share", "Steal share vs an even split")}</div><div class="s">${ss.observed} cards against ${num(ss.expected, 1)}; ${ss.ci ? iv(ss.ci[0], ss.ci[1], (x) => num(x, 2)) : ""}</div></div>`);
    if (tb) tiles.push(`<div class="tile"><div class="v">${num(tb.trade_rr, 2)}×</div><div class="k">Player trades vs the table ${info("trade_bank", "Trade and bank profile")}</div><div class="s">${tb.trade_rr_ci ? iv(tb.trade_rr_ci[0], tb.trade_rr_ci[1], (x) => num(x, 2)) : ""}</div></div>`);
    if (tb) tiles.push(`<div class="tile"><div class="v">${fmtSigned(tb.bank_rd * 100, 1)} pts</div><div class="k">Bank share of cards received</div><div class="s">vs the table; port rate ${num(tb.port_rate, 2)} : 1</div></div>`);
    const recipe = wr ? `<div class="panel table-wrap" style="margin-top:12px"><table><thead><tr><th>Winning VP from ${info("recipe", "Win recipe")}</th><th class="num">Share</th><th class="num">Tilt vs comparable wins</th></tr></thead><tbody>
      ${[["buildings", "Buildings"], ["development", "Development"], ["bonuses", "Bonuses"]].map(([k, l]) => `<tr><td>${l}</td><td class="num">${pct(wr[k].share)}</td><td class="num">${fmtSigned(wr[k].tilt * 100, 1)} pts <span class="sub">(${fmtSigned(wr[k].ci[0] * 100, 0)} to ${fmtSigned(wr[k].ci[1] * 100, 0)})</span></td></tr>`).join("")}
      </tbody></table></div><p class="note">Over ${wr.wins} wins: where ${esc(p.name)}'s winning points came from, compared with other players' wins in the same kind of game.</p>` : "";
    return `<section class="block">
        <h2>Compared with the table</h2>
        <p class="note">From the group models on the <a href="#/findings">Findings</a> page. Intervals are 95%.</p>
        ${tiles.length ? `<div class="tiles">${tiles.join("")}</div>` : ""}
        ${recipe}
      </section>`;
  }

  function h2hPage() {
    const ranked = S.players.filter((p) => p.games > 0);
    const H = {};
    for (const h of S.head_to_head) H[h.player + "|" + h.opponent] = h;
    const fill = (r) => {
      const t = Math.min(1, Math.abs(r - 0.5) * 2) * 60;
      const pole = r >= 0.5 ? "var(--div-pos)" : "var(--div-neg)";
      return `color-mix(in oklab, ${pole} ${t.toFixed(0)}%, var(--div-mid))`;
    };
    const head = ranked.map((p) => `<th class="colh" scope="col">${who(p.id)}</th>`).join("");
    const body = ranked.map((a) => `<tr><th class="rowh" scope="row">${who(a.id)}</th>${ranked.map((b) => {
      if (a.id === b.id) return `<td><div class="cell self" aria-label="same player"></div></td>`;
      const h = H[a.id + "|" + b.id];
      if (!h) return `<td><div class="cell" style="--fill:transparent"><span>no games</span></div></td>`;
      return `<td><div class="cell" style="--fill:${fill(h.ahead_rate)}" title="${esc(a.name)} finished ahead of ${esc(b.name)} in ${h.ahead + h.tied / 2} of ${h.games} games"><b>${pct(h.ahead_rate)}</b><span>${h.ahead + h.tied / 2} of ${h.games}</span></div></td>`;
    }).join("")}</tr>`).join("");
    main.innerHTML = `
      <h1>Head to head</h1>
      <p class="lede">Read across a row: how often that player finished ahead of each opponent in the games they both played. Ties count as half.</p>
      ${filterBar()}
      <section class="block panel" style="padding:14px">
        <div class="table-wrap"><table class="matrix"><thead><tr><th></th>${head}</tr></thead><tbody>${body}</tbody></table></div>
        <div class="scale"><span>Usually behind</span><span class="bar" aria-hidden="true"></span><span>Usually ahead</span></div>
      </section>`;
  }

  function diceSentence(d) {
    const verdict = d.p_value < 0.01 ? "very unusual for fair dice" : d.p_value < 0.05 ? "unusual for fair dice"
      : "within normal luck for fair dice";
    return `${d.sevens} sevens rolled against ${num(d.sevens_expected)} expected. A chi-square test gives ${num(d.chi2)} on 10 degrees of freedom (p = ${d.p_value.toFixed(2)}), ${verdict}.`;
  }

  function diceChart(el, d, label) {
    barChart(el, {
      height: 220, ariaLabel: label,
      bars: Object.keys(d.counts).map((k) => ({
        label: k, value: d.counts[k], expected: d.expected[k],
        tipHtml: `<b>${k}</b> rolled ${d.counts[k]} ${d.counts[k] === 1 ? "time" : "times"}<br>${num(d.expected[k])} expected`,
      })),
    });
  }

  function gamesPage() {
    const d = S.dice_overall;
    main.innerHTML = `
      <h1>Games</h1>
      <p class="lede">${S.summary.games} ${S.summary.games === 1 ? "game" : "games"} recorded, newest first.</p>
      ${filterBar()}
      ${d ? `<section class="block">
        <h2>Dice across these games</h2>
        <p class="note">${d.rolls} rolls across ${S.summary.games_with_dice} ${S.summary.games_with_dice === 1 ? "game" : "games"}. ${diceSentence(d)}</p>
        <div class="panel"><div class="chart" style="padding-bottom:0"><ul class="legend"><li><span class="sw box" style="--c:var(--data)"></span>Rolled</li><li><span class="sw tick"></span>Expected with fair dice</li></ul></div>
        <div class="chart" id="dice-all"></div>
        ${tableView([{ label: "Roll" }, { label: "Rolled", num: true }, { label: "Expected", num: true }], Object.keys(d.counts).map((k) => [k, d.counts[k], num(d.expected[k])]))}</div>
      </section>` : ""}
      <section class="block">
        <div class="panel table-wrap"><table class="games-table">
          <thead><tr><th>Date</th><th>Finishing order</th><th class="num hide-sm">Turns</th></tr></thead>
          <tbody>${S.games.map((g) => `<tr>
            <td class="date"><a href="#/game/${encodeURIComponent(g.id)}">${fmtDate(g.date)}</a><div class="sub">Game ${g.number}, ${esc(g.type_label)}</div></td>
            <td><div class="order">${g.players.map((r) => `<span>${who(r.player).replace('class="who', `class="who${r.rank === 1 ? " win" : ""}`)} <span class="vp">${r.vp}</span></span>`).join("")}</div></td>
            <td class="num hide-sm">${g.turns ?? ""}</td></tr>`).join("")}</tbody>
        </table></div>
      </section>`;
    if (d) diceChart(document.getElementById("dice-all"), d, "Dice roll counts across these games, with expected counts");
  }

  function gamePage(gid) {
    // A game outside the current filter falls back to the all-games view.
    const g = S.games.find((x) => x.id === gid) || ROOT.views.all.games.find((x) => x.id === gid);
    if (!g) return notFound(`There's no game with the id "${esc(gid)}".`);
    const winner = g.players[0];
    const hasVB = g.players.some((r) => r.vp_breakdown);
    const vb = (r, k) => (r.vp_breakdown ? r.vp_breakdown[k] || "" : "");
    const VP_SHORT = { settlements: "Settlements", cities: "Cities", vp_cards: "VP cards", largest_army: "Army", longest_road: "Road", islands: "Islands", other: "Other" };
    // Island and other columns only appear when some player scored from them.
    const vbKeys = Object.keys(VP_SHORT).filter((k) => !["islands", "other"].includes(k)
      || g.players.some((r) => r.vp_breakdown && r.vp_breakdown[k]));
    const prodTotal = g.players.reduce((a, r) => a + (r.resources_from_dice || 0), 0);
    const hasProd = g.players.every((r) => r.resources_from_dice !== null && r.resources_from_dice !== undefined);
    const hasDev = g.players.some((r) => r.dev_cards_bought);
    const cards = [["knight", "Knight"], ["victory_point", "VP"], ["road_building", "Road building"], ["year_of_plenty", "Year of plenty"], ["monopoly", "Monopoly"]];
    const settings = g.settings || {};
    const tl = (ROOT.timelines || {})[g.id];
    const rps = g.players.map((r) => ({ r, x: replayOf(g, r.player) })).filter((o) => o.x);
    const lineColor = (pid) => (isGuest(pid) ? "var(--muted)" : color(pid));
    // With more than one guest, name each by finishing place so the chart, legend and tables agree.
    const name = (pid) => {
      if (!isGuest(pid)) return P[pid] ? P[pid].name : pid;
      return g.n_guests > 1 ? `Guest (${ord(g.players.find((x) => x.player === pid).rank)})` : "Guest";
    };
    const replayTable = rps.length ? `<section class="block">
        <h2>From the replay</h2>
        <p class="note">Expected is what each player's buildings would produce with average dice, robber included. Blocked counts cards the robber kept from them.</p>
        <div class="panel table-wrap"><table>
          <thead><tr><th>Player</th><th class="num">From dice</th><th class="num">Expected</th><th class="num">Blocked</th><th class="num">Robber moves</th><th class="num">Steals</th><th class="num">Robbed</th><th class="num">Lost to 7s</th><th class="num">Trades</th><th class="num">Bank trades</th><th class="num">Monopoly</th><th class="num">Longest road</th></tr></thead>
          <tbody>${rps.map(({ r, x }) => `<tr><td>${who(r.player)}</td><td class="num">${x.resources_from_dice}</td><td class="num">${num(x.expected_from_dice)}</td><td class="num">${x.blocked_by_robber}</td><td class="num">${x.robber_moves}</td><td class="num">${x.steals}</td><td class="num">${x.stolen_from}</td><td class="num">${x.cards_discarded}</td><td class="num">${x.trades}</td><td class="num">${x.bank_trades}</td><td class="num">${x.monopoly_cards || ""}</td><td class="num">${x.longest_road_length}</td></tr>`).join("")}</tbody>
        </table></div>
        <div class="panel table-wrap" style="margin-top:12px"><table>
          <thead><tr><th>Player</th><th class="num">Settlements</th><th class="num">Cities</th><th class="num">Roads</th><th class="num">Ships</th><th class="num">Knights played</th><th class="num">Rolls</th><th class="num">7s rolled</th><th class="num">Opening dots</th></tr></thead>
          <tbody>${rps.map(({ r, x }) => `<tr><td>${who(r.player)}</td><td class="num">${x.built.settlement}</td><td class="num">${x.built.city}</td><td class="num">${x.built.road}</td><td class="num">${x.built.ship || ""}</td><td class="num">${x.dev_cards_played.knight || ""}</td><td class="num">${x.rolls}</td><td class="num">${x.sevens_rolled}</td><td class="num">${x.opening_dots}</td></tr>`).join("")}</tbody>
        </table></div>
        <p class="note">Built counts pieces placed during the game, free Road Building roads included, so starting settlements and roads aren't in it, and a settlement later upgraded still counts.</p>
      </section>` : "";
    main.innerHTML = `
      <a class="back" href="#/games">Back to games</a>
      <h1>${fmtDate(g.date, { weekday: "long", month: "long", day: "numeric", year: "numeric" })}</h1>
      <p class="lede">${who(winner.player)} won with ${winner.vp} VP${g.turns ? ` in ${g.turns} turns` : ""}. ${esc(g.type_label)}, ${g.n_bots ? `${g.n_players - g.n_bots} players and ${g.n_bots === 1 ? "a TwoSheep bot" : g.n_bots + " TwoSheep bots"}` : `${g.n_players} players`}${g.vp_to_win ? `, playing to ${g.vp_to_win}` : ""}. Game ${g.number} on record.</p>
      ${settings.notes ? `<p class="note">${esc(settings.notes)}</p>` : ""}

      <section class="block">
        <h2>Final scores</h2>
        <div class="panel table-wrap"><table>
          <thead><tr><th class="num">Finish</th><th>Player</th><th class="num">VP</th>
            ${hasVB ? vbKeys.map((k) => `<th class="num">${VP_SHORT[k]}</th>`).join("") : ""}
            <th class="num">Seat</th><th class="num">Above expected</th></tr></thead>
          <tbody>${g.players.map((r) => `<tr>
            <td class="num">${ord(r.rank)}</td><td>${who(r.player)}</td><td class="num"><b>${r.vp}</b></td>
            ${hasVB ? vbKeys.map((k) => `<td class="num">${vb(r, k)}</td>`).join("") : ""}
            <td class="num">${r.seat ?? '<span class="sub">n/a</span>'}</td>
            <td class="num ${r.above_expected > 0 ? "delta-up" : "delta-down"}">${r.guest ? "" : signed(r.above_expected, 2)}</td></tr>`).join("")}</tbody>
        </table></div>
        ${hasVB ? `<p class="note">Columns are victory points from each source, so cities count 2 each and the row adds up to the total.</p>` : ""}
        ${g.n_bots ? `<p class="note">The bot isn't listed, but it counts as a seat: it is in the number of players behind expected wins and as an opponent in beat rate.</p>` : ""}
        ${g.n_guests ? `<p class="note">Guests are players outside the group. They count as seats and opponents but aren't ranked or listed.</p>` : ""}
        ${g.twosheep_id ? `<p class="note"><a href="https://twosheep.io/replay/${encodeURIComponent(g.twosheep_id)}">Watch the replay on TwoSheep.io</a></p>` : ""}
      </section>

      ${closenessTile(g)}
      ${hooksHtml("game-race", g)}
      ${tl && !raceHooked(g) ? `<section class="block">
        <h2>The race</h2>
        <p class="note">Victory points at the end of every turn, replayed from TwoSheep's record of the game.</p>
        <div class="panel"><div class="chart" style="padding-bottom:0"><ul class="legend">${g.players.map((r) => `<li><span class="sw" style="--c:${lineColor(r.player)}"></span>${esc(name(r.player))}</li>`).join("")}</ul></div>
        <div class="chart" id="race"></div><div id="race-table"></div></div>
      </section>` : ""}

      ${g.dice ? `<section class="block">
        <h2>Dice</h2>
        <p class="note">${g.dice.rolls} rolls. ${diceSentence(g.dice)}</p>
        <div class="panel"><div class="chart" style="padding-bottom:0"><ul class="legend"><li><span class="sw box" style="--c:var(--data)"></span>Rolled</li><li><span class="sw tick"></span>Expected with fair dice</li></ul></div>
        <div class="chart" id="dice-game"></div>
        ${tableView([{ label: "Roll" }, { label: "Rolled", num: true }, { label: "Expected", num: true }], Object.keys(g.dice.counts).map((k) => [k, g.dice.counts[k], num(g.dice.expected[k])]))}</div>
      </section>` : ""}

      <div class="two-col">
        ${hasProd ? `<section class="block">
          <h2>Dice production</h2>
          <p class="note">Resources each player received from rolls.</p>
          <div class="panel table-wrap"><table><thead><tr><th>Player</th><th class="num">Resources</th><th class="num">Share</th><th class="num">Index</th></tr></thead>
          <tbody>${[...g.players].sort((a, b) => b.resources_from_dice - a.resources_from_dice).map((r) => `<tr><td>${who(r.player)}</td><td class="num">${r.resources_from_dice}</td><td class="num">${pct(r.resources_from_dice / prodTotal)}</td><td class="num">${num(r.resources_from_dice / (prodTotal / g.n_players), 2)}</td></tr>`).join("")}</tbody></table></div>
        </section>` : ""}
        ${hasDev ? `<section class="block">
          <h2>Development cards bought</h2>
          <div class="panel table-wrap"><table><thead><tr><th>Player</th>${cards.map(([, l]) => `<th class="num">${l}</th>`).join("")}</tr></thead>
          <tbody>${g.players.map((r) => `<tr><td>${who(r.player)}</td>${cards.map(([k]) => `<td class="num">${r.dev_cards_bought ? r.dev_cards_bought[k] || "" : ""}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
        </section>` : ""}
      </div>

      ${replayTable}
      ${hooksHtml("game", g)}`;
    hooksDraw("game", g);
    hooksDraw("game-race", g);
    if (g.dice) diceChart(document.getElementById("dice-game"), g.dice, "Dice roll counts for this game, with expected counts");
    if (tl && !raceHooked(g)) {
      const series = g.players.map((r) => ({
        id: r.player, name: name(r.player), color: lineColor(r.player),
        points: tl.vp[r.player].map((v, t) => ({ x: t, y: v, tip: `${v} VP` })),
      }));
      lineChart(document.getElementById("race"), {
        series, height: 260, stepLabel: "turns", ariaLabel: "Victory points for each player after every turn",
        xLabel: (x) => `<b>${x === 0 ? "After setup" : "Turn " + x}</b>`,
        xTickLabel: (x) => (x === 0 ? "setup" : x),
      });
      const turns = tl.vp[g.players[0].player].length;
      const every = Math.max(1, Math.ceil(turns / 40));
      document.getElementById("race-table").innerHTML = tableView(
        [{ label: "Turn" }].concat(g.players.map((r) => ({ label: esc(name(r.player)), num: true }))),
        Array.from({ length: turns }, (_, t) => t).filter((t) => t % every === 0 || t === turns - 1)
          .map((t) => [t === 0 ? "After setup" : t].concat(g.players.map((r) => tl.vp[r.player][t]))));
    }
  }

  // The momentum module draws the board VP race when it has this game; otherwise the true VP timeline is used.
  const raceHooked = (g) => hookList("game-race").length > 0 && !!(((ROOT.momentum || {}).games || {})[g.id]);

  function closenessTile(g) {
    const r = ((ROOT.closeness || {}).games || {})[g.id];
    if (!r) return "";
    const n = ROOT.closeness.n;
    const head = r.closest_tier ? "In our closest tier" : r.one_sided_tier ? "Among our most one-sided games"
      : `Closeness rank ${r.rank_min === r.rank_max ? r.rank_min : `${r.rank_min} to ${r.rank_max}`} of ${n}`;
    return `<section class="block">
        <h2>How close was it? ${info("closeness", "Closeness index")}</h2>
        <div class="tiles"><div class="tile"><div class="v">${num(r.index, 0)}</div><div class="k">${head}</div><div class="s">Closeness index out of 100, on ${ROOT.closeness.hindsight ? "board VP" : "true VP (hindsight)"}</div></div>
          <div class="tile"><div class="v">${r.A} VP</div><div class="k">Runner-up still needed</div><div class="s">before the winner's final turn</div></div>
          <div class="tile"><div class="v">${r.lead_changes}</div><div class="k">Lead changes</div><div class="s">new sole leader, before the final turn</div></div>
          <div class="tile"><div class="v">${num(r.C * (r.target - 2), 1)} VP</div><div class="k">Average lead</div><div class="s">from when anyone reached half the target</div></div></div>
      </section>`;
  }

  // Game-centered dice luck from the momentum module: cards per game against the rest of the table.
  function luckSection() {
    const L = (S.momentum || {}).luck;
    if (!L) return "";
    const rows = S.players.filter((p) => p.games > 0 && L[p.id] && L[p.id].shown);
    if (!rows.length) return "";
    const mx = Math.max(...rows.map((p) => Math.max(Math.abs(L[p.id].lo), Math.abs(L[p.id].hi))));
    return `<section class="block">
        <h2>Dice luck ${info("luck_player", "Game-centered dice luck")}</h2>
        <p class="note">Cards from dice beyond what each player's buildings would produce on average, compared with the rest of the same table, per game. Positive means the dice favored them over the people they played with.</p>
        <div class="panel table-wrap"><table>
          <thead><tr><th>Player</th><th class="num">Games</th><th class="num">Luck per game</th><th class="num">95% interval</th><th class="num">z, all games</th><th class="hide-sm" style="width:28%"></th></tr></thead>
          <tbody>${rows.map((p) => { const r = L[p.id]; return `<tr><td>${who(p.id)}</td><td class="num">${r.games}</td><td class="num"><b>${fmtSigned(r.mean, 1)}</b></td><td class="num">${fmtSigned(r.lo, 1)} to ${fmtSigned(r.hi, 1)}</td><td class="num">${num(r.z, 2)}</td><td class="hide-sm">${divBar(r.mean, mx)}</td></tr>`; }).join("")}</tbody>
        </table></div>
        <p class="note">z is the player's total luck over all their games divided by its standard deviation under fair dice; about 95% of players would land between −2 and +2 by chance.</p>
      </section>`;
  }

  function stylePage() {
    const ranked = S.players.filter((p) => p.games > 0 && p.replay);
    if (!ranked.length) {
      main.innerHTML = `<h1>Play style</h1>${filterBar()}<p class="empty">No decoded replays in these games yet.</p>`;
      return;
    }
    const n = S.summary.games_with_replays;
    const by = (f) => [...ranked].sort((a, b) => f(b) - f(a));
    const lucky = by((p) => p.replay.dice_ratio);
    const maxLuck = Math.max(...ranked.map((p) => Math.abs(p.replay.dice_ratio - 1)));
    const row = (cells) => `<tr>${cells.join("")}</tr>`;
    const td = (v, d = 1) => `<td class="num">${num(v, d)}</td>`;
    const tdm = (v, pid, key, d = 1) => `<td class="num">${num(v, d)} <span class="cell-mk">${mk(pid, key)}</span></td>`;

    const H = {};
    for (const h of S.head_to_head) H[h.player + "|" + h.opponent] = h;
    const rates = ranked.flatMap((a) => ranked.map((b) => { const h = H[a.id + "|" + b.id]; return h && h.replay_games ? h.steals / h.replay_games : 0; }));
    const maxRate = Math.max(0.01, ...rates);
    const head = ranked.map((p) => `<th class="colh" scope="col">${who(p.id)}</th>`).join("");
    const body = ranked.map((a) => `<tr><th class="rowh" scope="row">${who(a.id)}</th>${ranked.map((b) => {
      if (a.id === b.id) return `<td><div class="cell self" aria-label="same player"></div></td>`;
      const h = H[a.id + "|" + b.id];
      if (!h || !h.replay_games) return `<td><div class="cell" style="--fill:transparent"><span>no games</span></div></td>`;
      const r = h.steals / h.replay_games;
      return `<td><div class="cell" style="--fill:color-mix(in oklab, var(--div-neg) ${((r / maxRate) * 60).toFixed(0)}%, var(--div-mid))" title="${esc(a.name)} stole ${h.steals} cards from ${esc(b.name)} in ${h.replay_games} games together"><b>${num(r, 2)}</b><span>${h.steals} in ${h.replay_games}</span></div></td>`;
    }).join("")}</tr>`).join("");

    main.innerHTML = `
      <h1>Play style</h1>
      <p class="lede">How everyone plays, from TwoSheep's turn-by-turn record of ${n} ${n === 1 ? "game" : "games"}. Numbers are per game unless they say otherwise.</p>
      ${filterBar()}
      <div class="mk-key">${markerLegend()}<span class="note">Each marker compares a player with the rest of the same tables, in SDs. ${info("markers", "vs the table markers")}</span></div>

      ${luckSection()}
      <section class="block">
        <h2>Dice luck: actual against expected</h2>
        <p class="note">Cards each player got from rolls, against what their settlements and cities would have produced with average dice at the moment of each roll. Above 1.00 means the dice ran hot for them. Placement shows up in the expected column; luck is the gap. Gold counts as one card.</p>
        <div class="panel table-wrap"><table>
          <thead><tr><th>Player</th><th class="num">Games</th><th class="num">From dice</th><th class="num">Expected</th><th class="num">Difference</th><th class="num">Luck</th><th class="hide-sm" style="width:28%"></th></tr></thead>
          <tbody>${lucky.map((p) => { const r = p.replay; return row([`<td>${who(p.id)}</td>`, `<td class="num">${r.games}</td>`, td(r.avg_resources_from_dice), td(r.avg_expected_from_dice),
            `<td class="num">${signed(r.avg_luck)} <span class="cell-mk">${mk(p.id, "luck")}</span></td>`, `<td class="num"><b>${num(r.dice_ratio, 2)}×</b></td>`, `<td class="hide-sm">${divBar(r.dice_ratio - 1, maxLuck)}</td>`]); }).join("")}</tbody>
        </table></div>
      </section>

      <section class="block">
        <h2>Robber</h2>
        <p class="note">Steals are cards taken with the robber or pirate. Blocked is production the robber sat on. 7s rolled is the share of a player's own rolls that came up 7; fair dice give 16.7%.</p>
        <div class="panel table-wrap"><table>
          <thead><tr><th>Player</th><th class="num">Robber moves</th><th class="num">Steals</th><th class="num">Robbed</th><th class="num">Lost to 7s</th><th class="num">Blocked</th><th class="num">Monopoly haul</th><th class="num">7s rolled</th></tr></thead>
          <tbody>${by((p) => p.replay.avg_steals).map((p) => { const r = p.replay; return row([`<td>${who(p.id)}</td>`, tdm(r.avg_robber_moves, p.id, "robber_moves"), tdm(r.avg_steals, p.id, "steals"), tdm(r.avg_stolen_from, p.id, "stolen_from"),
            tdm(r.avg_cards_discarded, p.id, "cards_discarded"), tdm(r.avg_blocked_by_robber, p.id, "blocked_by_robber"), tdm(r.avg_monopoly_cards, p.id, "monopoly_cards"), `<td class="num">${pct(r.seven_rate, 1)} <span class="sub">of ${r.rolls}</span></td>`]); }).join("")}</tbody>
        </table></div>
      </section>

      <section class="block">
        <h2>Who robs whom</h2>
        <p class="note">Read across a row: cards that player stole from each opponent per game played together.</p>
        <div class="panel" style="padding:14px"><div class="table-wrap"><table class="matrix"><thead><tr><th></th>${head}</tr></thead><tbody>${body}</tbody></table></div></div>
      </section>

      <section class="block">
        <h2>Building and trading</h2>
        <p class="note">Pieces placed during the game, free Road Building roads included (starting pieces aren't counted). Opening dots add up the number dots under both starting settlements: a 6 or 8 has 5, a 2 or 12 has 1.</p>
        <div class="panel table-wrap"><table>
          <thead><tr><th>Player</th><th class="num">Opening dots</th><th class="num">Settlements</th><th class="num">Cities</th><th class="num">Roads</th><th class="num">Ships</th><th class="num">Knights</th><th class="num">Longest road</th><th class="num">Player trades</th><th class="num">Bank trades</th><th class="num">Biggest hand</th></tr></thead>
          <tbody>${by((p) => p.replay.avg_opening_dots).map((p) => { const r = p.replay; return row([`<td>${who(p.id)}</td>`, tdm(r.avg_opening_dots, p.id, "opening_dots"), tdm(r.avg_built_settlement, p.id, "built_settlement"), tdm(r.avg_built_city, p.id, "built_city"),
            tdm(r.avg_built_road, p.id, "built_road"), tdm(r.avg_built_ship, p.id, "built_ship"), tdm(r.avg_knights, p.id, "knights"), tdm(r.avg_longest_road_length, p.id, "longest_road_length"), tdm(r.avg_trades, p.id, "trades"), tdm(r.avg_bank_trades, p.id, "bank_trades"), `<td class="num">${r.max_hand} <span class="cell-mk">${mk(p.id, "max_hand")}</span></td>`]); }).join("")}</tbody>
        </table></div>
        <p class="note">Longest road is the length of each player's longest route at the end of the game. Biggest hand is the most cards that player held at once in any of these games.</p>
      </section>
      ${hooksHtml("style")}`;
    hooksDraw("style");
  }

  // ---- Findings: group-level models and tests ------------------------------------------
  function findingsPage() {
    const I = ins();
    const order = S.players.filter((p) => p.games > 0).map((p) => p.id);  // leaderboard order, never re-sorted
    const rowsFor = (obj, f) => order.filter((pid) => obj && obj[pid]).map((pid) => f(pid, obj[pid]));
    const o = I.opening, bo = I.best_opener, rb = I.opening_robustness;
    const viewNote = o && o.source === "all games"
      ? `<p class="note">This view has ${o.view_games} games with replays, under the 30 a model needs, so the numbers are from all games.</p>` : "";
    const rob = rb ? `<div class="note">Spot or player? Refits give b = ${rb.map((r) => `${num(r.b, 2)} (${esc(r.name.toLowerCase())}, SE ${num(r.se, 2)})`).join(", ")}. The full table is on <a href="#/about">How it works</a>. ${info("robustness", "Robustness refits")}</div>` : "";
    const d = I.dice_calibration;
    const cl = ROOT.closeness;

    main.innerHTML = `
      <h1>Findings</h1>
      <p class="lede">What the games say as a group: openings, seats, the robber, trading, where winning points come from, the dice, and which games were closest. Every interval is 95%.</p>
      ${filterBar()}

      <section class="block">
        <h2>Openings ${info("opening", "Opening edge and win chance")}</h2>
        ${o ? `<p class="note">Opening dots are the number dots under a player's two starting settlements. Here they are measured against the table: dots minus the average of everyone in that game.</p>
        ${viewNote}
        <div class="tiles">
          <div class="tile"><div class="v">${pct(o.p2)}</div><div class="k">Win chance, 2 dots above the table</div><div class="s">against 3 equal opponents; 25% at an even table</div></div>
          <div class="tile"><div class="v">${num(o.or, 2)}×</div><div class="k">Odds per extra dot</div><div class="s">95% interval ${num(o.or_ci[0], 2)} to ${num(o.or_ci[1], 2)}</div></div>
          <div class="tile"><div class="v">${num(o.b, 3)}</div><div class="k">Coefficient b</div><div class="s">${o.games} games, profile interval ${num(o.ci[0], 3)} to ${num(o.ci[1], 3)}</div></div>
        </div>
        <p class="note" style="margin-top:12px">Win chance in percent for a player with that many more opening dots than each of three equal opponents. The band is the 95% interval.</p>
        <div class="panel" style="margin-top:6px"><div class="chart" id="f-pd"></div>
        ${tableView([{ label: "Dots above each opponent" }, { label: "Win chance", num: true }, { label: "95% interval", num: true }],
          o.curve.map((c) => [signed(c.d, 0), pct(c.p, 1), `${pct(c.lo, 1)} to ${pct(c.hi, 1)}`]))}</div>
        <p class="note">Most of the information comes from New Shores 3 and 4 player games.</p>
        ${rob}` : `<p class="empty">Needs 30 games with replays.</p>`}
      </section>

      ${bo ? `<section class="block">
        <h2>Best opener's wins ${info("best_opener", "Best opener's wins vs chance")}</h2>
        <p class="note">Wins by the seat with the most opening dots, the fewest, and everyone between, against chance. One-sided permutation p = ${num(bo.p_best, 3)} for the best opener; it asks the same question as the model above.${bo.dropped_all_tied ? ` ${bo.dropped_all_tied} ${bo.dropped_all_tied === 1 ? "game" : "games"} where every seat tied ${bo.dropped_all_tied === 1 ? "is" : "are"} left out.` : ""}</p>
        <div class="panel"><div class="chart" id="f-best"></div></div>
      </section>` : ""}

      <section class="block">
        <h2>Opening strength by player ${info("opening_player", "Opening strength vs the table")}</h2>
        <p class="note">Board and draft luck plus choice: how many dots above the table each player opened with, on average.</p>
        ${Object.keys(I.opening_by_player || {}).length ? `<div class="panel"><div class="chart" id="f-open"></div></div>` : guardNote(0, 10)}
      </section>

      <section class="block">
        <h2>Turn order ${info("seat", "Seat effect")}</h2>
        <p class="note">Wins by seat, 1 being first to play.</p>
        <div class="two-col">${["3", "4"].filter((n) => (I.seat_effect || {})[n]).map((n) => `<div><h3>${n} players <span class="sub">${I.seat_effect[n].games} games</span></h3><div class="panel" style="margin-top:8px"><div class="chart" id="f-seat-${n}"></div></div></div>`).join("") || `<p class="empty">No 3 or 4 player games with seats here.</p>`}</div>
      </section>

      <section class="block">
        <h2>Robbed vs an even split ${info("steal_share", "Steal share vs an even split")}</h2>
        <p class="note">Cards stolen from each player against an even split of everyone else's steals. This ignores the board, so robbing the leader counts as excess here.</p>
        ${Object.keys(I.steal_share || {}).length ? `<div class="panel"><div class="chart" id="f-steal"></div></div>` : guardNote(0, 10)}
      </section>

      <section class="block">
        <h2>Trading and the bank ${info("trade_bank", "Trade and bank profile")}</h2>
        <p class="note">How much each player trades with other players compared with the rest of the same table, and how much of what they receive comes from the bank or ports.</p>
        ${Object.keys(I.trade_bank || {}).length ? `<div class="two-col">
          <div><h3>Player trades, rate vs the table</h3><div class="panel" style="margin-top:8px"><div class="chart" id="f-trade"></div></div></div>
          <div><h3>Bank share of cards received, vs the table</h3><div class="panel" style="margin-top:8px"><div class="chart" id="f-bank"></div></div></div>
        </div>
        <div class="panel table-wrap" style="margin-top:12px"><table><thead><tr><th>Player</th><th class="num">Games</th><th class="num">Trade rate</th><th class="num">Bank share</th><th class="num">Port rate</th></tr></thead>
          <tbody>${rowsFor(I.trade_bank, (pid, t) => `<tr><td>${who(pid)}</td><td class="num">${t.games}</td><td class="num">${num(t.trade_rr, 2)}×</td><td class="num">${fmtSigned(t.bank_rd * 100, 1)} pts</td><td class="num">${num(t.port_rate, 2)} : 1</td></tr>`).join("")}</tbody></table></div>` : guardNote(0, 10)}
      </section>

      <section class="block">
        <h2>Where winning points came from ${info("recipe", "Win recipe")}</h2>
        <p class="note">Share of each win's VP from each source, compared with other players' wins in the same kind of game. Players with at least 10 wins.</p>
        ${Object.keys(I.win_recipe || {}).length ? `<div class="panel table-wrap"><table><thead><tr><th>Player</th><th class="num">Wins</th><th class="num">Buildings</th><th class="num">Development</th><th class="num">Bonuses</th></tr></thead>
          <tbody>${rowsFor(I.win_recipe, (pid, r) => `<tr><td>${who(pid)}</td><td class="num">${r.wins}</td>${["buildings", "development", "bonuses"].map((c) => `<td class="num">${recipeCell(r[c])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
          <p class="note">Each cell: the player's average share of winning VP, then the tilt against comparable wins in points, with its 95% interval. Bold tilts have intervals that exclude 0.</p>` : `<p class="empty">Nobody has 10 wins in this view yet.</p>`}
      </section>

      ${d ? `<section class="block">
        <h2>Are the dice fair? ${info("dice", "Dice calibration")}</h2>
        <div class="tiles">
          <div class="tile"><div class="v">${d.sevens}</div><div class="k">Sevens rolled</div><div class="s">${num(d.sevens_expected, 0)} expected; rate ${pct(d.seven_rate, 1)} (${pct(d.seven_rate_ci[0], 1)} to ${pct(d.seven_rate_ci[1], 1)}), z = ${num(d.seven_z, 1)}</div></div>
          <div class="tile"><div class="v">${num(d.chi2, 1)}</div><div class="k">χ² on ${d.chi2_df} df, all rolls</div><div class="s">p = ${num(d.chi2_p, 3)}, ${d.rolls} rolls</div></div>
          <div class="tile"><div class="v">${num(d.per_game_chi2, 0)}</div><div class="k">Summed per-game χ²</div><div class="s">on ${d.per_game_df} df (p = ${num(d.per_game_p, 2)}): rolls look independent within games</div></div>
          <div class="tile"><div class="v">${fmtSigned(d.drift * 100, 1)}%</div><div class="k">Drift</div><div class="s">extra cards a board with one settlement on every number would get</div></div>
        </div>
        <p class="note">Sevens came up less often than fair dice predict, so everyone looks slightly lucky in absolute terms. Comparing players within the same game removes most of this.</p>
      </section>` : ""}

      ${hooksHtml("findings")}
      ${cl ? closestSection(cl) : ""}`;
    hooksDraw("findings");

    if (o) {
      lineChart(document.getElementById("f-pd"), {
        series: [{ id: "p", name: "Win chance", color: "var(--data)", band: true,
          points: o.curve.map((c) => ({ x: c.d, y: c.p * 100, lo: c.lo * 100, hi: c.hi * 100, tip: `${pct(c.p, 1)} (${pct(c.lo, 0)} to ${pct(c.hi, 0)})` })) }],
        directLabels: false, height: 220, stepLabel: "dot differences", ariaLabel: "Win chance against dots above each of three equal opponents",
        xLabel: (x) => `<b>${signed(x, 0)} dots</b> above each opponent`, xTickLabel: (x) => signed(x, 0),
      });
    }
    if (bo) {
      nullBars(document.getElementById("f-best"), {
        legend: true, height: 220, format: (v) => num(v, 1),
        bars: bo.buckets.map((b, i) => ({ label: b.label, value: b.observed, expected: b.expected, lo: b.lo, hi: b.hi,
          note: i === 0 ? `p = ${num(bo.p_best, 3)}` : undefined,
          tip: `${num(b.observed, 1)} wins, ${num(b.expected, 1)} expected; chance range ${num(b.lo, 1)} to ${num(b.hi, 1)}` })),
      });
    }
    const op = I.opening_by_player || {};
    if (Object.keys(op).length) {
      forestPlot(document.getElementById("f-open"), {
        ref: 0, xTitle: "Opening dots above the table average", leftLabel: "weaker openings", rightLabel: "stronger openings",
        names: { est: "Draft-adjusted", hollow: "Raw" }, format: (v) => fmtSigned(v, 2),
        rows: rowsFor(op, (pid, r) => ({ label: who(pid, false), est: r.adjusted.mean, lo: r.adjusted.lo, hi: r.adjusted.hi, hollow: r.raw.mean, color: color(pid),
          tip: `${who(pid, false)}<br>Draft-adjusted ${fmtSigned(r.adjusted.mean, 2)} (${fmtSigned(r.adjusted.lo, 2)} to ${fmtSigned(r.adjusted.hi, 2)})<br>Raw ${fmtSigned(r.raw.mean, 2)}<br>${r.games} games${r.unadjusted_games ? `, ${r.unadjusted_games} with 5 or 6 seats left raw` : ""}` })),
      });
    }
    for (const n of ["3", "4"]) {
      const se = (I.seat_effect || {})[n];
      if (!se) continue;
      nullBars(document.getElementById(`f-seat-${n}`), {
        height: 180, legend: n === "3",
        bars: se.seats.map((b) => ({ label: ord(b.seat), value: b.wins, expected: b.expected, lo: b.lo, hi: b.hi,
          tip: `${b.wins} wins, ${num(b.expected, 1)} expected; chance range ${b.lo} to ${b.hi}` })),
      });
    }
    const st = I.steal_share || {};
    if (Object.keys(st).length) {
      forestPlot(document.getElementById("f-steal"), {
        ref: 1, log: true, xTitle: "Cards stolen ÷ even split", leftLabel: "robbed less", rightLabel: "robbed more",
        format: (v) => num(v, 2) + "×", legend: false,
        rows: rowsFor(st, (pid, r) => ({ label: who(pid, false), est: r.ratio, lo: r.ci && r.ci[0], hi: r.ci && r.ci[1], color: color(pid),
          tip: `${who(pid, false)}<br>${r.observed} cards stolen, ${num(r.expected, 1)} under an even split<br>${num(r.ratio, 2)}× (${r.ci ? num(r.ci[0], 2) + " to " + num(r.ci[1], 2) : "n/a"}), ${r.games} games` })),
      });
    }
    const tb = I.trade_bank || {};
    if (Object.keys(tb).length) {
      forestPlot(document.getElementById("f-trade"), {
        ref: 1, log: true, xTitle: "Rate ratio", leftLabel: "trades less", rightLabel: "trades more", format: (v) => num(v, 2) + "×", legend: false,
        rows: rowsFor(tb, (pid, r) => ({ label: who(pid, false), est: r.trade_rr, lo: r.trade_rr_ci && r.trade_rr_ci[0], hi: r.trade_rr_ci && r.trade_rr_ci[1], color: color(pid),
          tip: `${who(pid, false)}<br>${num(r.trade_rr, 2)}× the table's trade rate (${r.trade_rr_ci ? num(r.trade_rr_ci[0], 2) + " to " + num(r.trade_rr_ci[1], 2) : "n/a"})` })),
      });
      forestPlot(document.getElementById("f-bank"), {
        ref: 0, xTitle: "Difference in percentage points", leftLabel: "less from the bank", rightLabel: "more from the bank", format: (v) => fmtSigned(v, 1), legend: false,
        rows: rowsFor(tb, (pid, r) => ({ label: who(pid, false), est: r.bank_rd * 100, lo: r.bank_rd_ci && r.bank_rd_ci[0] * 100, hi: r.bank_rd_ci && r.bank_rd_ci[1] * 100, color: color(pid),
          tip: `${who(pid, false)}<br>${fmtSigned(r.bank_rd * 100, 1)} points (${r.bank_rd_ci ? fmtSigned(r.bank_rd_ci[0] * 100, 1) + " to " + fmtSigned(r.bank_rd_ci[1] * 100, 1) : "n/a"})<br>Port rate ${num(r.port_rate, 2)} : 1` })),
      });
    }
  }

  function recipeCell(c) {
    const clear = c.ci[0] > 0 || c.ci[1] < 0;
    return `${pct(c.share)} <span class="sub">${clear ? "<b>" : ""}${fmtSigned(c.tilt * 100, 1)}${clear ? "</b>" : ""} (${fmtSigned(c.ci[0] * 100, 0)} to ${fmtSigned(c.ci[1] * 100, 0)})</span>`;
  }

  // ---- Closest games ---------------------------------------------------------------------
  const gameById = (gid) => ROOT.views.all.games.find((g) => g.id === gid);
  function leadSpark(gid) {
    const mg = ((ROOT.momentum || {}).games || {})[gid], tl = (ROOT.timelines || {})[gid];
    if (!mg && !tl) return "";
    const series = mg ? mg.board_vp : Object.values(tl.vp);  // board VP, like the closeness index
    const T = series[0].length;
    const gaps = Array.from({ length: T - 1 }, (_, t) => { const v = series.map((s) => s[t]).sort((a, b) => b - a); return v[0] - v[1]; });
    const mx = Math.max(1, ...gaps);
    const pts = gaps.map((g, t) => `${((t / Math.max(1, gaps.length - 1)) * 100).toFixed(1)},${(22 - (g / mx) * 20).toFixed(1)}`).join(" ");
    return `<svg class="spark" viewBox="0 0 100 24" preserveAspectRatio="none" aria-hidden="true"><polyline points="${pts}" fill="none" style="stroke:var(--data)" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg>`;
  }
  function closenessChips(r) {
    return `<span class="chipline"><span class="mini">runner-up needed ${r.A} VP</span><span class="mini">${r.lead_changes} lead ${r.lead_changes === 1 ? "change" : "changes"}</span><span class="mini">avg lead ${num(r.C * (r.target - 2), 1)} VP</span></span>`;
  }
  function closestSection(cl0) {
    const board = !!cl0.hindsight;
    const cl = cl0;
    const inView = new Set(S.games.map((g) => g.id));
    const rows = Object.entries(cl.games).filter(([gid]) => inView.has(gid));
    const tier = rows.filter(([, r]) => r.closest_tier).sort((a, b) => a[1].rank - b[1].rank);
    const lop = rows.filter(([, r]) => r.one_sided_tier).sort((a, b) => b[1].rank - a[1].rank);
    const cls = (n) => (n < 5 ? `${n} players` : "5 and 6 players");
    const classes = ["3 players", "4 players", "5 and 6 players"].filter((c) => rows.some(([, r]) => cls(r.n_seats) === c));
    const strip = `<div class="strip" role="list" aria-label="Closeness index of every game">${classes.map((c) => `<div class="strip-row"><span class="strip-lab">${c}</span><div class="strip-track">${rows.filter(([, r]) => cls(r.n_seats) === c).map(([gid, r]) => {
      const g = gameById(gid);
      return `<a role="listitem" class="strip-dot${r.closest_tier ? " hot" : r.one_sided_tier ? " cold" : ""}" style="left:${r.index}%" href="#/game/${encodeURIComponent(gid)}" data-tip="${esc(`<b>${gameLabel(g)}</b><br>Closeness ${num(r.index, 0)}, rank ${r.rank} of ${cl.n}`)}" aria-label="${esc(gameLabel(g))}: closeness ${num(r.index, 0)}"></a>`;
    }).join("")}</div></div>`).join("")}<div class="strip-axis"><span>more one-sided</span><span>closer</span></div></div>`;
    const table = (list) => `<div class="panel table-wrap"><table><thead><tr><th>Game</th><th>Why</th><th class="num">Rank</th><th class="hide-sm">Lead margin</th></tr></thead><tbody>${list.map(([gid, r]) => {
      const g = gameById(gid);
      return `<tr><td><a href="#/game/${encodeURIComponent(gid)}">${esc(gameLabel(g))}</a><div class="sub">${who(g.winner, false)} won, ${g.n_players} players</div></td><td style="white-space:normal">${closenessChips(r)}</td><td class="num">${r.rank_min === r.rank_max ? r.rank_min : `${r.rank_min} to ${r.rank_max}`}</td><td class="hide-sm" style="width:120px">${leadSpark(gid)}</td></tr>`;
    }).join("")}</tbody></table></div>`;
    return `<section class="block">
        <h2>Closest games ${info("closeness", "Closeness index")}</h2>
        <p class="note">How close each game was, from the finish margin, lead changes and the size of the lead. ${board ? "Measured on board VP, what everyone could see; hidden VP cards are left out." : "<b>Hindsight</b> for now: this uses true VP, including VP cards nobody could see."} Ranks are among all ${cl.n} decoded games and don't change with the filter.</p>
        <div class="panel"><div class="chart">${strip}</div></div>
        <h3 style="margin-top:20px">The closest tier</h3>
        <p class="note">Games in the top quarter however the parts are combined. The rank shows how far each one moves.</p>
        ${tier.length ? table(tier) : `<p class="empty">No game in this view is in the closest tier.</p>`}
        <h3 style="margin-top:20px">The most one-sided</h3>
        ${lop.length ? table(lop) : `<p class="empty">No game in this view is in the one-sided tier.</p>`}
        ${board ? (() => {
          const h = Object.entries(cl0.hindsight.games).filter(([gid, r]) => inView.has(gid) && r.closest_tier).sort((a, b) => a[1].rank - b[1].rank);
          return `<details class="tv"><summary>Hindsight: the closest tier on true VP, VP cards included</summary>${h.length ? table(h) : `<p class="empty">None in this view.</p>`}</details>`;
        })() : ""}
      </section>`;
  }

  function aboutPage() {
    const s = ROOT.views.all.summary;
    main.innerHTML = `<div class="prose">
      <h1>How it works</h1>
      <h2>Ranking</h2>
      <p>In Catan you win or you don't, so the leaderboard only counts wins. Each win is worth 1. Each game also counts your fair share of wins against you: 1 divided by the number of players, since that is how often anyone would win if it were pure chance. The total is <b>wins above expected</b>: wins minus expected wins. Winning a 6-player game earns +0.83 and losing one costs 0.17, while a 3-player game earns +0.67 or costs 0.33, so a win counts for more at a bigger table and a loss there hurts less. Second place counts the same as last.</p>
      <p>This follows the CATAN World Championship, which ranks its preliminary round by number of wins. They can count raw wins because everyone plays the same number of 4-player games; we don't, so each game's expected share is taken off. Ties go to the higher average share of the table's VP, one of the championship's tiebreakers.</p>
      <p>Luck is large in Catan. If everyone were equally good, every game would be a 1-in-n draw, and a player's wins would follow a Poisson binomial distribution over their games, averaging their expected wins. The gray band on the leaderboard and player pages is the middle 95% of that distribution (at most 2.5% cut from each end, computed exactly, since a normal approximation is poor over a handful of games), shown as wins above expected. A player inside their band could be where they are by chance. The total grows with games played, so a regular who keeps winning a little more than their share climbs higher than someone with a hot start over a few games.</p>
      <p>We tried skill models first. Over our games, a Plackett-Luce skill model fit to winners only finds no clear differences between players, and neither the old full-finishing-order rating (openskill) nor the winner-only model predicted the next winner better than giving everyone an equal chance. Wins above expected says plainly what happened without claiming more than the data shows.</p>
      <p>The arrows beside each place show how it changed with the latest game. <b>Last ${ROOT.ranking.recent_games} games</b> adds up wins above expected over each player's own most recent games, and counts places moved over the group's last ${ROOT.ranking.recent_games} games. A player is <b>on fire</b> when those games come to at least ${ROOT.ranking.fire_above} full win above expected and they played in one of the group's last ${ROOT.ranking.active_window} games. Over just ${ROOT.ranking.recent_games} games that is mostly luck, which is part of the fun. The trophy marks whoever is first.</p>
      <p>The game type filter recomputes everything from only the games you pick, so the Seafarers leaderboard only counts Seafarers games and a scenario's leaderboard only that scenario. VP comparisons always use each game's own target.</p>
      <h2>Finishing order</h2>
      <p>The winner always finishes first. Everyone else is ordered by final VP, and players with equal VP share a place.</p>
      <h2>Guests</h2>
      <p>Anyone who isn't part of the group shows up as a guest. Guests count as seats, so a game with a guest has the same fair share as any other game of that size, and they count as opponents in beat rate and head to head, but they never appear on the leaderboard. TwoSheep bots count the same way. Only finished games with 3 or more players, at least 2 of them from the group, are recorded.</p>
      <h2>Other numbers</h2>
      <ul>
        <li><b>Win rate</b> comes with a 95% Wilson interval, which stays honest with small samples.</li>
        <li><b>Expected wins</b> adds up 1 ÷ (number of players) for every game played, so it reflects what pure chance would give.</li>
        <li><b>Beat rate</b> is the share of opponents a player finished ahead of, which compares fairly across 3, 4 and 5 player games.</li>
        <li><b>Production index</b> divides a player's resources from dice by the table average for that game.</li>
        <li><b>Dice tests</b> compare roll counts to the 2d6 distribution with a chi-square test.</li>
        <li><b>Dice luck</b> compares the cards a player got from rolls with the cards their buildings would produce on average. Before every roll, each settlement adds 1 and each city 2 times the chance of each touching hex's number (a 6 or 8 is 5 in 36), skipping the hex under the robber. Summed over the game, that is the expected count; luck is actual divided by expected, pooled over games.</li>
      </ul>
      <h2>Replays</h2>
      <p>TwoSheep keeps a record of every action in a game. Those records are replayed here move by move through the same rules TwoSheep uses, which gives the dice, production, robber, trading and building numbers and the turn-by-turn race. Each replay is checked as it runs: no hand ever goes negative, every discard on a 7 is half the hand, and every player's final VP matches TwoSheep's result. ${s.games_with_replays} of ${s.games} games have one.</p>
      <h2>What's recorded</h2>
      <p>${s.games} ${s.games === 1 ? "game" : "games"}. By type: ${Object.entries(s.games_by_type).map(([k, n]) => `${esc(k)} ${n}`).join(", ")}. Seat order is recorded for ${s.games_with_seats}, dice counts for ${s.games_with_dice}, and turn-by-turn replays for ${s.games_with_replays}. ${s.games_with_guests} ${s.games_with_guests === 1 ? "game includes" : "games include"} guests.</p>
      <h2>Models and intervals</h2>
      <p>Every interval on the site is 95%. Intervals come from a bootstrap that resamples whole games unless a note says otherwise. Only two effects are tested, both chosen in advance and only in the all-games view: the opening effect on the Findings page, and (once the decoder records each roll) whether early dice luck snowballs. Everything else is an estimate with an interval and no significance wording.</p>
      <p>Guards: a player needs 10 games in a view for a per-player row or a "vs the table" marker. A model needs 30 games; a smaller view reuses the all-games estimate and says so. Guests and bots never get a row, but they stay in every denominator and choice set.</p>
      ${ROOT.views.all.insights && ROOT.views.all.insights.opening_robustness ? `<h3>Opening effect: spot or player? ${info("robustness", "Robustness refits")}</h3>
      <p>The headline b (all games) next to four refits that control for who the player is, the seat, or use the full finishing order. Bars are b ± 1.96 SE.</p>
      <div class="panel"><div class="chart" id="about-rob"></div></div>` : ""}
      ${hooksHtml("about")}
      <h2>Where the data comes from</h2>
      <p>Every game was played on <a href="https://twosheep.io">TwoSheep.io</a>, and its data is used here with the permission of Odd Stone Studios, who make it. Go play a game there.</p>
    </div>`;
  }

  function drawAboutCharts() {
    hooksDraw("about");
    const el = document.getElementById("about-rob");
    if (!el) return;
    const I = ROOT.views.all.insights;
    coefPlot(el, {
      xTitle: "b, change in log odds of winning per opening dot above the table",
      rows: [{ label: "<b>Headline</b> (Firth, profile interval)", b: I.opening.b, lo: I.opening.ci[0], hi: I.opening.ci[1] }]
        .concat(I.opening_robustness.map((r) => ({ label: esc(r.name), b: r.b, se: r.se }))),
    });
  }

  function notFound(msg) {
    main.innerHTML = `<h1>Not found</h1><p class="lede">${msg} <a href="#/">Go to the leaderboard</a></p>`;
  }

  // ---- Router -------------------------------------------------------------------
  function route() {
    Tip.hide();
    const [path, query] = location.hash.replace(/^#\/?/, "").split("?");
    const want = new URLSearchParams(query || "").get("view") || "all";
    setView(ROOT.views[want] ? want : "all");
    PAGE_PATH = path || "";
    const parts = PAGE_PATH.split("/").map(decodeURIComponent);
    const page = parts[0] || "";
    const navKey = { "": "leaderboard", player: "leaderboard", h2h: "h2h", style: "style", findings: "findings", games: "games", game: "games", about: "about" }[page] || (Pages[page] && page);
    document.querySelectorAll("[data-nav]").forEach((a) => {
      if (a.dataset.nav === navKey) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    if (page === "") leaderboard();
    else if (page === "player") playerPage(parts[1]);
    else if (page === "h2h") h2hPage();
    else if (page === "style") stylePage();
    else if (page === "findings") findingsPage();
    else if (page === "games") gamesPage();
    else if (page === "game") gamePage(parts[1]);
    else if (page === "about") { aboutPage(); drawAboutCharts(); }
    else if (Pages[page]) Pages[page].render(ctx(), parts.slice(1));
    else notFound("That page doesn't exist.");
    scopeLinks(document);
    const title = S.site.title || "Catan Stats";
    const h1 = main.querySelector("h1");
    document.title = h1 && page !== "" ? `${h1.textContent} | ${title}` : title;
    window.scrollTo(0, 0);
  }

  function setView(key) {
    VIEW = key;
    S = Object.assign({}, ROOT.views[key], { ranking: ROOT.ranking, site: ROOT.site, generated_at: ROOT.generated_at });
    P = Object.fromEntries(ROOT.views.all.players.map((p) => [p.id, p])); // every known player
    for (const p of S.players) P[p.id] = p;                              // stats from this view
  }

  // Keep the chosen filter as people click around: add ?view= to every internal link.
  function scopeLinks(root) {
    root.querySelectorAll('a[href^="#/"]').forEach((a) => {
      if (a.hasAttribute("data-keep")) return;
      const base = a.getAttribute("href").split("?")[0];
      a.setAttribute("href", VIEW === "all" ? base : `${base}?view=${encodeURIComponent(VIEW)}`);
    });
  }

  function setupTheme() {
    const btn = document.getElementById("theme-btn");
    btn.addEventListener("click", () => {
      const root = document.documentElement;
      const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
      root.dataset.theme = dark ? "light" : "dark";
      try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
      route(); // charts read CSS variables at draw time
    });
  }

  async function init() {
    drawCoast();
    setupTheme();
    try {
      if (window.CATAN_STATS) {
        ROOT = window.CATAN_STATS; // loaded by data/stats.js, works even from file://
      } else {
        const res = await fetch("data/stats.json", { cache: "no-cache" });
        if (!res.ok) throw new Error(`data/stats.json returned ${res.status}`);
        ROOT = await res.json();
      }
    } catch (e) {
      main.innerHTML = `<div class="error-box"><h2>No stats to show yet</h2>
        <p>This page couldn't find its data file. That usually means this is the <code>site</code> folder, which holds only the page templates.
        Run <code>python scripts/build.py</code>, then open <code>dist/index.html</code> instead.</p>
        <p class="note">Details: ${esc(e.message)}</p></div>`;
      return;
    }
    setView("all");
    document.getElementById("site-title").textContent = S.site.title || "Catan Stats";
    document.getElementById("site-sub").textContent = S.site.subtitle || "";
    document.getElementById("built-at").textContent = `Updated ${new Date(S.generated_at).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })}.`;
    window.addEventListener("hashchange", route);
    route();
  }
  init();
})();
