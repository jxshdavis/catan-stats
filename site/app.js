/* Catan Night front end. Renders dist/data/stats.json; computes nothing heavy. */
(function () {
  "use strict";
  const { lineChart, barChart, Tip, esc } = window.Charts;
  const main = document.getElementById("main");
  let ROOT = null;       // stats.json
  let VIEW = "all";      // current filter, kept in the URL as ?view=
  let S = null;          // the current view's stats, plus the shared fields from ROOT
  let P = {};            // player id -> player stats in the current view

  // ---- Formatting helpers ---------------------------------------------------
  const pct = (x, d = 0) => (x === null || x === undefined ? "n/a" : (x * 100).toFixed(d) + "%");
  const num = (x, d = 1) => (x === null || x === undefined ? "n/a" : Number(x).toFixed(d));
  const color = (pid) => `var(--p${(P[pid] && P[pid].color_slot) || 1})`;
  const ord = (n) => {
    const s = ["th", "st", "nd", "rd"], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
  };
  const fmtDate = (iso, opts) => new Date(iso + "T12:00:00").toLocaleDateString("en-US",
    opts || { month: "short", day: "numeric", year: "numeric" });
  const signed = (x, d = 1) => (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d);
  const isGuest = (pid) => String(pid).startsWith("guest-");
  const who = (pid, link = true) => {
    if (isGuest(pid)) return `<span class="who guest"><span class="hex" aria-hidden="true"></span><span>Guest</span></span>`;
    const p = P[pid];
    const name = p ? esc(p.name) : esc(pid);
    const inner = `<span class="hex" style="--c:${color(pid)}" aria-hidden="true"></span><span>${name}</span>`;
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
    const lo = Math.min(...ranked.map((p) => p.rating.mu - 2 * p.rating.sigma));
    const hi = Math.max(...ranked.map((p) => p.rating.mu + 2 * p.rating.sigma));
    const strip = (p) => {
      const W = 160, X = (v) => 6 + ((v - lo) / (hi - lo)) * (W - 12);
      const a = X(p.rating.mu - 2 * p.rating.sigma), b = X(p.rating.mu + 2 * p.rating.sigma), m = X(p.rating.mu);
      const base = X(S.rating_model.mu0);
      return `<svg viewBox="0 0 ${W} 18" preserveAspectRatio="none" aria-hidden="true">
        <line x1="${base}" x2="${base}" y1="1" y2="17" style="stroke:var(--axis)" stroke-width="1"/>
        <line x1="${a}" x2="${b}" y1="9" y2="9" style="stroke:${color(p.id)}" stroke-width="2" stroke-linecap="round"/>
        <circle cx="${m}" cy="9" r="4" style="fill:${color(p.id)};stroke:var(--surface)" stroke-width="2"/></svg>`;
    };
    const rows = ranked.map((p) => `<tr>
        <td class="rank">${p.leaderboard_rank}</td>
        <td>${who(p.id)}</td>
        <td class="num rating">${num(p.rating.ordinal)}${p.rating.provisional ? '<span class="provisional hide-sm">provisional</span>' : ""}</td>
        <td class="range hide-sm" title="Skill ${num(p.rating.mu)}, 95% range ${num(p.rating.mu - 2 * p.rating.sigma)} to ${num(p.rating.mu + 2 * p.rating.sigma)}">${strip(p)}</td>
        <td class="num hide-sm">${p.games}</td>
        <td class="num">${p.wins}</td>
        <td class="num">${pct(p.win_rate)}<div class="sub hide-sm">${pct(p.win_rate_ci[0])} to ${pct(p.win_rate_ci[1])}</div></td>
        <td class="num hide-sm">${num(p.avg_vp)}</td>
        <td class="num hide-sm">${pct(p.beat_rate)}</td>
      </tr>`).join("");

    const latest = S.games[0];
    main.innerHTML = `
      <h1>Leaderboard</h1>
      <p class="lede">${s.games} ${s.games === 1 ? "game" : "games"} played ${s.first_date === s.last_date ? "on " + fmtDate(s.first_date) : "from " + fmtDate(s.first_date) + " to " + fmtDate(s.last_date)}.
        Ranked by a conservative rating <span class="nowrap">(μ − 3σ)</span> from a Plackett-Luce model of every finishing order. <a href="#/about">How ratings work</a></p>
      ${filterBar()}
      <section class="block panel">
        <div class="table-wrap"><table class="board">
          <thead><tr>
            <th>#</th><th>Player</th><th class="num">Rating</th>
            <th class="hide-sm">Skill μ ± 2σ</th>
            <th class="num hide-sm">Games</th><th class="num">Wins</th><th class="num">Win rate</th>
            <th class="num hide-sm">Avg VP</th><th class="num hide-sm">Beat rate</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table></div>
      </section>
      <p class="note">Win rate shows a 95% interval underneath. Beat rate is the share of opponents a player finished ahead of. The skill strip marks the starting rating of ${S.rating_model.mu0} with a vertical line.</p>

      <section class="block">
        <h2>Skill over time</h2>
        <p class="note">Each player's skill estimate (μ) after every game, starting from ${S.rating_model.mu0}.</p>
        <div class="panel"><div class="chart" id="trend-legend"></div><div class="chart" id="trend"></div><div id="trend-table"></div></div>
      </section>

      <section class="block">
        <h2>Latest game</h2>
        <p class="note">${fmtDate(latest.date)}: ${who(latest.winner)} won with ${latest.players[0].vp} VP${latest.turns ? ` in ${latest.turns} turns` : ""}. <a href="#/game/${encodeURIComponent(latest.id)}">See the full game</a></p>
      </section>`;

    const series = ranked.map((p) => ({
      id: p.id, name: p.name, color: color(p.id),
      points: [{ x: 0, y: S.rating_model.mu0, tip: num(S.rating_model.mu0) }]
        .concat(p.rating_history.map((h) => ({ x: h.index, y: h.mu, tip: num(h.mu) }))),
    }));
    const legend = document.getElementById("trend-legend");
    legend.innerHTML = `<ul class="legend">${ranked.map((p) => `<li><span class="sw" style="--c:${color(p.id)}"></span>${esc(p.name)}</li>`).join("")}</ul>`;
    legend.style.paddingBottom = "0";
    const gi = gamesByIndex();
    lineChart(document.getElementById("trend"), {
      series, ariaLabel: "Skill estimate for each player after every game",
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
          <td class="num">${num(p.vp_sources_avg[k])}</td></tr>`).join("")}</tbody></table></div>`;
    })() : `<p class="empty">No VP breakdowns recorded yet.</p>`;

    const seats = Object.keys(p.by_seat);
    const seatHtml = seats.length ? `<div class="panel table-wrap"><table>
        <thead><tr><th>Seat</th><th class="num">Games</th><th class="num">Wins</th><th class="num">Win rate</th><th class="num">Avg finish</th></tr></thead>
        <tbody>${seats.map((k) => { const v = p.by_seat[k]; return `<tr><td>${ord(+k)} to play</td><td class="num">${v.games}</td><td class="num">${v.wins}</td><td class="num">${pct(v.win_rate)}</td><td class="num">${num(v.avg_rank)}</td></tr>`; }).join("")}</tbody></table></div>`
      : `<p class="empty">Seat order hasn't been recorded for ${esc(p.name)}'s games yet. Add a <code>seat</code> number for each player in <code>games.json</code> to fill this in.</p>`;

    const dc = p.dev_cards_bought;
    const devHtml = dc ? `<div class="panel table-wrap"><table><thead><tr><th>Card</th><th class="num">Bought</th><th class="num">Per game</th></tr></thead><tbody>
        ${[["knight", "Knight"], ["victory_point", "Victory point"], ["road_building", "Road building"], ["year_of_plenty", "Year of plenty"], ["monopoly", "Monopoly"]]
          .map(([k, l]) => `<tr><td>${l}</td><td class="num">${dc[k]}</td><td class="num">${num(dc[k] / dc.games, 2)}</td></tr>`).join("")}
      </tbody></table></div>` : `<p class="empty">No dev card purchases recorded yet.</p>`;

    main.innerHTML = `
      <a class="back" href="#/">Back to leaderboard</a>
      <div class="player-head"><span class="hex" style="--c:${color(pid)}" aria-hidden="true"></span><h1>${esc(p.name)}</h1></div>
      <p class="lede">Ranked ${ord(p.leaderboard_rank)} of ${active}. ${p.games} ${p.games === 1 ? "game" : "games"} recorded.${p.rating.provisional ? ` The rating is provisional until ${S.rating_model.provisional_below_games} games.` : ""}</p>      ${filterBar()}

      <div class="tiles">
        <div class="tile"><div class="v">${num(p.rating.ordinal)}</div><div class="k">Rating</div><div class="s">μ ${num(p.rating.mu)}, σ ${num(p.rating.sigma)}</div></div>
        <div class="tile"><div class="v">${pct(p.win_rate)}</div><div class="k">Win rate</div><div class="s">95% interval ${pct(p.win_rate_ci[0])} to ${pct(p.win_rate_ci[1])}</div></div>
        <div class="tile"><div class="v">${p.wins}</div><div class="k">Wins</div><div class="s">${num(p.expected_wins)} expected by chance</div></div>
        <div class="tile"><div class="v">${pct(p.beat_rate)}</div><div class="k">Beat rate</div><div class="s">Opponents finished ahead of</div></div>
        <div class="tile"><div class="v">${num(p.avg_vp)}</div><div class="k">Average VP</div><div class="s">${pct(p.avg_vp_share)} of the VP needed to win</div></div>
      </div>

      <section class="block">
        <h2>Skill over time</h2>
        <p class="note">Skill estimate (μ) after each game ${esc(p.name)} played, with the shaded band at ±2σ.</p>
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
        <p class="note">In games played together, how often ${esc(p.name)} finished ahead. Ties count as half.</p>
        <div class="panel table-wrap"><table>
          <thead><tr><th>Opponent</th><th class="num">Games</th><th class="num">Finished ahead</th><th class="num">${esc(p.name)} won</th><th class="num">They won</th></tr></thead>
          <tbody>${h2h.map((h) => `<tr><td>${who(h.opponent)}</td><td class="num">${h.games}</td><td class="num">${h.ahead + h.tied / 2} of ${h.games} <span class="sub">(${pct(h.ahead_rate)})</span></td><td class="num">${h.wins}</td><td class="num">${h.losses_to}</td></tr>`).join("")}</tbody>
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
          <thead><tr><th>Game</th><th class="num">Finish</th><th class="num">VP</th><th class="num">Skill change</th></tr></thead>
          <tbody>${myGames.map((g) => { const r = g.players.find((x) => x.player === pid); return `<tr>
            <td><a href="#/game/${encodeURIComponent(g.id)}">${esc(gameLabel(g))}</a></td>
            <td class="num">${ord(r.rank)} of ${g.n_players}</td><td class="num">${r.vp}</td>
            <td class="num ${r.rating_change > 0 ? "delta-up" : r.rating_change < 0 ? "delta-down" : ""}">${signed(r.rating_change)}</td></tr>`; }).join("")}</tbody>
        </table></div>
      </section>
      ${p.aliases && p.aliases.length ? `<details class="tv"><summary>TwoSheep usernames</summary><p class="note">${aliasList(p)}</p></details>` : ""}`;

    const pts = [{ x: 0, y: S.rating_model.mu0, lo: S.rating_model.mu0 - 2 * S.rating_model.sigma0, hi: S.rating_model.mu0 + 2 * S.rating_model.sigma0, tip: num(S.rating_model.mu0) }]
      .concat(p.rating_history.map((h) => ({ x: h.index, y: h.mu, lo: h.mu - 2 * h.sigma, hi: h.mu + 2 * h.sigma, tip: `${num(h.mu)} ± ${num(2 * h.sigma)}` })));
    lineChart(document.getElementById("p-trend"), {
      series: [{ id: pid, name: p.name, color: color(pid), points: pts, band: true }],
      directLabels: false, height: 240, ariaLabel: `Skill estimate for ${p.name} after each game`,
      xLabel: (x) => (x === 0 ? "<b>Start</b>" : `<b>${esc(gameLabel(gi[x]))}</b>`),
      xTickLabel: (x) => (x === 0 ? "start" : x),
    });
    document.getElementById("p-trend-table").innerHTML = tableView(
      [{ label: "Game" }, { label: "Skill μ", num: true }, { label: "σ", num: true }, { label: "Rating", num: true }],
      p.rating_history.map((h) => [esc(gameLabel(gi[h.index])), num(h.mu), num(h.sigma), num(h.ordinal)]));

    const places = Array.from({ length: maxRank }, (_, i) => i + 1);
    barChart(document.getElementById("p-finish"), {
      height: 200, color: color(pid), valueLabels: true, ariaLabel: `Finishing positions for ${p.name}`,
      bars: places.map((k) => { const c = p.finish_counts[k] || 0; return { label: ord(k), value: c, tip: `${c} ${c === 1 ? "game" : "games"}` }; }),
    });
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
    // Skill changes come from the current view's ratings; a game outside the filter uses all games.
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
    main.innerHTML = `
      <a class="back" href="#/games">Back to games</a>
      <h1>${fmtDate(g.date, { weekday: "long", month: "long", day: "numeric", year: "numeric" })}</h1>
      <p class="lede">${who(winner.player)} won with ${winner.vp} VP${g.turns ? ` in ${g.turns} turns` : ""}. ${esc(g.type_label)}, ${g.n_players} players${g.vp_to_win ? `, playing to ${g.vp_to_win}` : ""}. Game ${g.number} on record.</p>
      ${settings.notes ? `<p class="note">${esc(settings.notes)}</p>` : ""}

      <section class="block">
        <h2>Final scores</h2>
        <div class="panel table-wrap"><table>
          <thead><tr><th class="num">Finish</th><th>Player</th><th class="num">VP</th>
            ${hasVB ? vbKeys.map((k) => `<th class="num">${VP_SHORT[k]}</th>`).join("") : ""}
            <th class="num">Seat</th><th class="num">Skill change</th></tr></thead>
          <tbody>${g.players.map((r) => `<tr>
            <td class="num">${ord(r.rank)}</td><td>${who(r.player)}</td><td class="num"><b>${r.vp}</b></td>
            ${hasVB ? vbKeys.map((k) => `<td class="num">${vb(r, k)}</td>`).join("") : ""}
            <td class="num">${r.seat ?? '<span class="sub">n/a</span>'}</td>
            <td class="num ${r.rating_change > 0 ? "delta-up" : r.rating_change < 0 ? "delta-down" : ""}">${r.guest ? "" : signed(r.rating_change)}</td></tr>`).join("")}</tbody>
        </table></div>
        ${hasVB ? `<p class="note">Columns are victory points from each source, so cities count 2 each and the row adds up to the total.</p>` : ""}
        ${g.n_guests ? `<p class="note">Guests are players outside the group. They count as opponents but aren't rated or listed.</p>` : ""}
        ${g.twosheep_id ? `<p class="note"><a href="https://twosheep.io/replay/${encodeURIComponent(g.twosheep_id)}">Watch the replay on TwoSheep.io</a></p>` : ""}
      </section>

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
      </div>`;
    if (g.dice) diceChart(document.getElementById("dice-game"), g.dice, "Dice roll counts for this game, with expected counts");
  }

  function aboutPage() {
    const s = ROOT.views.all.summary, m = S.rating_model;
    main.innerHTML = `<div class="prose">
      <h1>How it works</h1>
      <h2>Ratings</h2>
      <p>Every game is treated as a full finishing order, not just a winner. A Plackett-Luce model reads that order as a sequence of choices: the winner beat everyone, second place beat everyone left, and so on. Each player has a skill estimate μ and an uncertainty σ. Everyone starts at μ = ${m.mu0} and σ = ${num(m.sigma0, 2)}, and both are updated after each game using the Weng-Lin Bayesian approximation (the openskill library).</p>
      <p>The leaderboard ranks by μ − 3σ, a conservative rating that only rises once the model is fairly sure. New players start near zero and climb as they play, so a lucky first win doesn't put someone on top. Ratings are marked provisional below ${m.provisional_below_games} games.</p>
      <p>The game type filter recomputes everything from only the games you pick, ratings included, so the Seafarers leaderboard only learns from Seafarers games and a scenario's leaderboard only from that scenario. "All games" pools every game into one rating. VP comparisons always use each game's own target.</p>
      <h2>Finishing order</h2>
      <p>The winner always finishes first. Everyone else is ordered by final VP, and players with equal VP share a place.</p>
      <h2>Guests</h2>
      <p>Anyone who isn't part of the group shows up as a guest. Guests count in the finishing order, so beating a guest helps your rating and losing to one hurts it, but each guest starts every game at the starting rating and never appears on the leaderboard. Only finished games with 3 or more players are recorded.</p>
      <h2>Other numbers</h2>
      <ul>
        <li><b>Win rate</b> comes with a 95% Wilson interval, which stays honest with small samples.</li>
        <li><b>Expected wins</b> adds up 1 ÷ (number of players) for every game played, so it reflects what pure chance would give.</li>
        <li><b>Beat rate</b> is the share of opponents a player finished ahead of, which compares fairly across 3, 4 and 5 player games.</li>
        <li><b>Production index</b> divides a player's resources from dice by the table average for that game.</li>
        <li><b>Dice tests</b> compare roll counts to the 2d6 distribution with a chi-square test.</li>
      </ul>
      <h2>What's recorded</h2>
      <p>${s.games} ${s.games === 1 ? "game" : "games"}. By type: ${Object.entries(s.games_by_type).map(([k, n]) => `${esc(k)} ${n}`).join(", ")}. Seat order is recorded for ${s.games_with_seats}, dice counts for ${s.games_with_dice}, and turn-by-turn logs for ${s.games_with_events}. ${s.games_with_guests} ${s.games_with_guests === 1 ? "game includes" : "games include"} guests.</p>
      <h2>Where the data comes from</h2>
      <p>Every game was played on <a href="https://twosheep.io">TwoSheep.io</a>, and its data is used here with the permission of Odd Stone Studios, who make it. Go play a game there.</p>
    </div>`;
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
    const navKey = { "": "leaderboard", player: "leaderboard", h2h: "h2h", games: "games", game: "games", about: "about" }[page];
    document.querySelectorAll("[data-nav]").forEach((a) => {
      if (a.dataset.nav === navKey) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    if (page === "") leaderboard();
    else if (page === "player") playerPage(parts[1]);
    else if (page === "h2h") h2hPage();
    else if (page === "games") gamesPage();
    else if (page === "game") gamePage(parts[1]);
    else if (page === "about") aboutPage();
    else notFound("That page doesn't exist.");
    scopeLinks(document);
    const title = S.site.title || "Catan Stats";
    const h1 = main.querySelector("h1");
    document.title = h1 && page !== "" ? `${h1.textContent} | ${title}` : title;
    window.scrollTo(0, 0);
  }

  function setView(key) {
    VIEW = key;
    S = Object.assign({}, ROOT.views[key], { rating_model: ROOT.rating_model, site: ROOT.site, generated_at: ROOT.generated_at });
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
