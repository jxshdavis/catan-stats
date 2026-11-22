/* Catan Night front end. Renders dist/data/stats.json; computes nothing heavy. */
(function () {
  "use strict";
  const { lineChart, barChart, Tip, esc, forestPlot, coefPlot, nullBars, markHist, arrow, markerLegend, infoButton } = window.Charts;
  const fin = (v) => v !== null && v !== undefined && Number.isFinite(+v);
  const M = window.METHODS || {};
  // Pages and page sections added by other scripts (site/network.js, site/classes.js, ...).
  // window.Pages[path] = {render(ctx)}; window.Hooks[page] = [{html(ctx, arg) -> string, draw(ctx, arg)}].
  const Pages = (window.Pages = window.Pages || {});
  const Hooks = (window.Hooks = window.Hooks || {});
  const hookList = (page) => Hooks[page] || [];
  // Front page extras (site/home.js). The page still works without them.
  const Home = window.Home || { tonight: () => "", middle: () => "", awards: () => "", records: () => "", draw: () => {} };
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
  // A value that rounds to zero gets no sign, so a tiny negative never shows as "−0.0".
  const signed = (x, d = 1) => { const a = Math.abs(x).toFixed(d); return (+a === 0 ? "" : x > 0 ? "+" : "−") + a; };
  const isGuest = (pid) => String(pid).startsWith("guest-");
  // A flame for anyone on fire.
  const FLAME = `<svg class="flame" viewBox="0 0 16 20" aria-hidden="true"><path class="flame-out" d="M8 .5c1 4 6 6 6 11.5 0 4.4-2.7 7.5-6 7.5S2 16.4 2 12c0-3 1.9-5 3-7 .5 2.4 1.5 3.4 2.5 3.4C7 5.5 7.4 2.6 8 .5z"/><path class="flame-in" d="M8 8.8c1 2 3 3.4 3 6 0 2.4-1.3 3.9-3 3.9S5 17.4 5 15.3c0-2 1.5-3 2-4.5.3 1.2.8 1.7 1.3 1.7-.3-1.2-.5-2.4-.3-3.7z"/></svg>`;
  const onFire = (pid) => !!(P[pid] && P[pid].recent && P[pid].recent.on_fire);
  const who = (pid, link = true) => {
    if (isGuest(pid)) return `<span class="who guest"><span class="hex" aria-hidden="true"></span><span>Guest</span></span>`;
    const p = P[pid];
    const name = p ? esc(p.name) : esc(pid);
    const lead = p && p.leaderboard_rank === 1;
    const inner = `<span class="pmark${lead ? " lead" : ""}"${lead ? ' title="First on the leaderboard"' : ""}><span class="hex" style="--c:${color(pid)}" aria-hidden="true"></span></span><span>${name}</span>`;
    const tag = `class="who" data-pid="${esc(pid)}"`;
    return link ? `<a ${tag} href="#/player/${encodeURIComponent(pid)}">${inner}</a>` : `<span ${tag}>${inner}</span>`;
  };
  const aliasList = (p) => p.aliases.map(esc).join(", ");
  const gameLabel = (g) => `Game ${g.number}, ${fmtDate(g.date)}`;
  const viewInfo = (key) => ROOT.view_list.find((v) => v.key === key);
  // A view is a game type ("all", "seafarers", "seafarers/new_shores", ...) and optionally a table size, keyed
  // "<type>+<size>" ("3p" = 3 seats, "4p" = 4 or more). The URL carries them as ?view=<type>&players=<size>.
  const SIZE_LABELS = { "3p": "3 players", "4p": "4+ players" };
  const viewKey = (type, size) => (size ? `${type}+${size}` : type);
  const viewQuery = (key) => {
    const v = viewInfo(key), q = [];
    if (v && v.type !== "all") q.push("view=" + encodeURIComponent(v.type));
    if (v && v.size) q.push("players=" + v.size);
    return q.length ? "?" + q.join("&") : "";
  };
  const viewLabel = (key) => {
    const v = viewInfo(key);
    if (!v) return key;
    const type = v.parent && v.parent !== "all" ? `${viewInfo(v.parent).label}: ${v.label}` : v.label;
    return v.size ? `${v.type === "all" ? "" : type + ", "}${SIZE_LABELS[v.size]}` : type;
  };
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

  // ---- Masthead: dateline, and on the home page a line about the latest game --------
  // The game gets a label from its final score and the VP-by-turn timeline. Thresholds scale with the VP target
  // so 10 and 14 point games read the same:
  //   comeback: the winner trailed the best opponent by at least 35% of the target (3 VP or more) after the first
  //             quarter of the game (timelines show visible VP, so hidden VP cards can make a deficit look bigger)
  //   close:    won by 1 VP or less
  //   blowout:  won by at least 40% of the target
  function gameStory(g) {
    const target = g.vp_to_win || 10;
    const ps = g.players.slice().sort((a, b) => a.rank - b.rank);
    const win = ps[0], top2 = ps[1].vp, margin = win.vp - top2;
    const name = (pid) => (isGuest(pid) ? "a guest" : P[pid] ? esc(P[pid].name) : esc(pid));
    const runners = ps.filter((r) => r.player !== g.winner && r.vp === top2).map((r) => name(r.player)).join(" and ");
    const delta = typeof win.above_expected === "number"
      ? `<span class="lead-delta" title="Wins above expected from this game">▲ +${num(win.above_expected, 1)}</span>` : "";
    const winner = `${who(g.winner)}${delta}`;
    const when = `<a href="#/game/${encodeURIComponent(g.id)}">game ${g.number}</a> on ${fmtDate(g.date, { month: "long", day: "numeric" })}`;
    const score = `${win.vp} to ${top2}`;
    const tl = ((ROOT.timelines || {})[g.id] || {}).vp || {};
    let deficit = 0;
    if (tl[g.winner]) {
      const mine = tl[g.winner], others = Object.keys(tl).filter((k) => k !== g.winner);
      for (let i = Math.floor(mine.length / 4); i < mine.length; i++) {
        deficit = Math.max(deficit, Math.max(...others.map((k) => tl[k][i])) - mine[i]);
      }
    }
    if (deficit >= Math.max(3, Math.round(0.35 * target))) {
      return { tag: "Comeback", text: `${winner} came back from ${deficit} points down to take ${when}, ${score} over ${runners}${margin <= 1 ? ", holding on by a single point" : ""}.` };
    }
    if (margin <= 1) return { tag: "Close game", text: `${winner} edged out ${runners} in ${when}, ${score}: a one point finish.` };
    if (margin >= 0.4 * target) return { tag: "Blowout", text: `${winner} ran away with ${when}, beating ${runners} ${score}.` };
    return { tag: "Solid win", text: `${winner} took ${when}, ${score} over ${runners}.` };
  }

  function drawMasthead() {
    const s = S.summary, games = S.games;
    const set = (id, html) => { document.getElementById(id).innerHTML = html; };
    set("mast-date", new Date(S.generated_at).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" }));
    if (!games.length) { set("mast-lead", esc(S.site.subtitle || "")); return; }
    const last = games.reduce((a, g) => (g.index > a.index ? g : a));
    const leader = S.players.find((p) => p.leaderboard_rank === 1);
    set("mast-issue", `No. ${last.number}`);
    set("mast-meta", `${s.players_active} players · since ${fmtDate(s.first_date, { month: "long", year: "numeric" })}`);
    const story = gameStory(last);
    const lv = `+${num(leader.above_expected, 1)} wins above expected`;
    const lead = leader.rank_prev === 1 ? `${esc(leader.name)} still leads the table at ${lv}.` : `${esc(leader.name)} takes over first place at ${lv}.`;
    set("mast-kicker", story.tag);
    set("mast-lead", `${story.text} ${lead}`);
  }

  // ---- Game type filter ---------------------------------------------------------
  // One row of choices above the page; Seafarers scenarios appear as a second row.
  function filterBar() {
    const list = ROOT.view_list;
    if (list.length < 2) return "";
    const cur = viewInfo(VIEW) || list[0];
    const type = cur.type || cur.key, size = cur.size || null;
    const tinfo = viewInfo(type);
    const family = tinfo.parent && tinfo.parent !== "all" ? tinfo.parent : type;
    // A type chip keeps the chosen table size; a size chip keeps the chosen type. No games there: a dead chip.
    const link = (t, s, text, within = false) => {
      const key = viewKey(t, s), v = viewInfo(key), sel = key === VIEW;
      if (!v) return `<span class="chip off" aria-disabled="true">${esc(text)} <span class="n">0</span></span>`;
      return `<a class="chip${sel ? " on" : within ? " within" : ""}" data-keep href="#/${PAGE_PATH}${viewQuery(key)}"${sel ? ' aria-current="true"' : ""}>${esc(text)} <span class="n">${v.games}</span></a>`;
    };
    const types = list.filter((v) => !v.size);
    const top = types.filter((v) => v.key === "all" || v.parent === "all");
    const kids = family === "all" ? [] : types.filter((v) => v.parent === family);
    const fam = viewInfo(family);
    let html = `<nav class="filter" aria-label="Filter by game type and table size"><div class="chips">${top.map((v) =>
      link(v.key, size, v.label, v.key === family && type !== family)).join("")}</div>`;
    if (kids.length) {
      html += `<div class="chips sub">${link(family, size, "Any scenario")}${kids.map((v) => link(v.key, size, v.label)).join("")}</div>`;
    }
    html += `<div class="chips size"><span class="chips-k">Table size</span>${link(type, null, "Any")}${Object.keys(SIZE_LABELS).map((s) => link(type, s, SIZE_LABELS[s])).join("")}</div>`;
    if (fam && fam.unlabeled_scenarios) {
      html += `<p class="note">${fam.unlabeled_scenarios} ${fam.label} ${fam.unlabeled_scenarios === 1 ? "game has" : "games have"} no scenario recorded, so ${fam.unlabeled_scenarios === 1 ? "it only counts" : "they only count"} under ${esc(fam.label)}.</p>`;
    }
    return html + "</nav>";
  }
  let PAGE_PATH = "";

  // ---- Pages ------------------------------------------------------------------
  // ---- Game-night calendar ------------------------------------------------------
  // One grid per year, newest first: a column per week (Sunday on top), a square per day. A day with games is
  // filled in the winner's color; with several winners it is split into stripes, wider for more wins.
  const winColor = (pid) => (isGuest(pid) ? "var(--muted)" : color(pid));
  const gamesOnDays = (games) => {
    const by = {};
    for (const g of games) (by[g.date] = by[g.date] || []).push(g);
    for (const d in by) by[d].sort((a, b) => a.number - b.number);
    return by;
  };
  function calendarHtml(games) {
    const byDay = gamesOnDays(games);
    const days = Object.keys(byDay);
    if (!days.length) return "";
    const CELL = 11, STEP = 14, LEFT = 30, TOP = 16, DAY = 864e5;
    const iso = (t) => new Date(t).toISOString().slice(0, 10);
    const now = new Date(), today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
    const years = [...new Set(days.map((d) => +d.slice(0, 4)))].sort((a, b) => b - a);
    const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const grid = (y) => {
      const jan1 = Date.UTC(y, 0, 1), off = new Date(jan1).getUTCDay();
      const col = (t) => Math.floor((Math.round((t - jan1) / DAY) + off) / 7);
      const weeks = col(Date.UTC(y, 11, 31)) + 1;
      const W = LEFT + weeks * STEP, H = TOP + 7 * STEP;
      let cells = "", nGames = 0, nDays = 0;
      for (let t = jan1; t <= Date.UTC(y, 11, 31); t += DAY) {
        const d = iso(t), x = LEFT + col(t) * STEP, yy = TOP + new Date(t).getUTCDay() * STEP;
        const gs = byDay[d];
        if (!gs) { cells += `<rect x="${x}" y="${yy}" width="${CELL}" height="${CELL}" rx="2" class="cal-off${t > today ? " cal-future" : ""}"/>`; continue; }
        nGames += gs.length; nDays++;
        const wins = {};
        for (const g of gs) wins[g.winner] = (wins[g.winner] || 0) + 1;
        let sx = x;
        const stripes = Object.entries(wins).map(([pid, n]) => {
          const w = (CELL * n) / gs.length, r = `<rect x="${sx}" y="${yy}" width="${w}" height="${CELL}" style="fill:${winColor(pid)}"/>`;
          sx += w;
          return r;
        }).join("");
        const tip = `<b>${fmtDate(d, { weekday: "short", month: "short", day: "numeric", year: "numeric" })}</b>`
          + gs.map((g) => `<div class="row">Game ${g.number}: ${who(g.winner, false)} won</div>`).join("");
        const label = `${fmtDate(d)}: ${gs.map((g) => `game ${g.number}, ${isGuest(g.winner) ? "a guest" : (P[g.winner] ? P[g.winner].name : g.winner)} won`).join("; ")}`;
        cells += `<a href="#/day/${d}" class="cal-day" data-tip="${esc(tip)}" aria-label="${esc(label)}">`
          + `<g clip-path="url(#cal-clip)">${stripes}</g><rect x="${x - 0.5}" y="${yy - 0.5}" width="${CELL + 1}" height="${CELL + 1}" rx="2.5" class="cal-ring"/></a>`;
      }
      let months = "";
      for (let m = 0; m < 12; m++) {
        const t = Date.UTC(y, m, 1);
        const c = col(t) + (new Date(t).getUTCDay() ? 1 : 0); // label the first full week of the month
        if (c < weeks - 1) months += `<text x="${LEFT + c * STEP}" y="${TOP - 5}">${MONTHS[m]}</text>`;
      }
      const wd = [[1, "Mon"], [3, "Wed"], [5, "Fri"]].map(([r, s]) => `<text x="${LEFT - 6}" y="${TOP + r * STEP + CELL - 2}" text-anchor="end">${s}</text>`).join("");
      return `<div class="cal-year"><h3>${y} <span class="sub">${nGames} ${nGames === 1 ? "game" : "games"} on ${nDays} ${nDays === 1 ? "day" : "days"}</span></h3>
        <div class="table-wrap cal-scroll" data-end="${((LEFT + (col(Math.min(today, Date.UTC(y, 11, 31))) + 1) * STEP + 4) / W).toFixed(4)}"><svg class="cal" viewBox="0 0 ${W} ${H}" style="min-width:${Math.round(W * 0.85)}px" role="group" aria-label="Game days in ${y}">${months}${wd}${cells}</svg></div></div>`;
    };
    const winners = Object.entries(games.reduce((a, g) => ((a[g.winner] = (a[g.winner] || 0) + 1), a), {}))
      .sort((a, b) => b[1] - a[1]);
    const legend = `<ul class="legend">${winners.map(([pid, n]) => `<li><span class="sw box" style="--c:${winColor(pid)}"></span>${isGuest(pid) ? "Guest" : esc(P[pid] ? P[pid].name : pid)} <span class="sub">${n}</span></li>`).join("")}</ul>`;
    return `<svg width="0" height="0" style="position:absolute" aria-hidden="true"><clipPath id="cal-clip" clipPathUnits="objectBoundingBox"><rect width="1" height="1" rx="0.18"/></clipPath></svg>
      <div class="chart">${legend}${years.map(grid).join("")}</div>`;
  }
  // On narrow screens, start each calendar scrolled so today (or the end of a past year) is at the right edge.
  const scrollCalendars = () => main.querySelectorAll(".cal-scroll").forEach((el) => {
    el.scrollLeft = Math.max(0, el.dataset.end * el.scrollWidth - el.clientWidth);
  });

  function dayPage(date) {
    const pick = (games) => games.filter((g) => g.date === date).sort((a, b) => a.number - b.number);
    let gs = pick(S.games);
    const inView = gs.length > 0;
    if (!inView) gs = pick(ROOT.views.all.games); // a day outside the current filter falls back to all games
    if (!gs.length) return notFound(`No games were recorded on ${esc(date)}.`);
    const dates = Object.keys(gamesOnDays(inView ? S.games : ROOT.views.all.games)).sort();
    const i = dates.indexOf(date), prev = dates[i - 1], next = dates[i + 1];
    const wins = {};
    for (const g of gs) wins[g.winner] = (wins[g.winner] || 0) + 1;
    const winLine = Object.entries(wins).sort((a, b) => b[1] - a[1])
      .map(([pid, n]) => `${who(pid)} won ${n === 1 ? (gs.length === 1 ? "it" : "1") : n}`).join(", ");
    main.innerHTML = `
      <a class="back" href="#/">Back to leaderboard</a>
      <h1>${fmtDate(date, { weekday: "long", month: "long", day: "numeric", year: "numeric" })}</h1>
      <p class="lede">${gs.length === 1 ? "One game" : `${gs.length} games`}. ${winLine}.</p>
      ${!inView ? `<p class="note">None of these are ${esc(viewLabel(VIEW))} games, so this shows all games that day.</p>` : ""}
      <section class="block">
        <div class="panel table-wrap"><table class="games-table">
          <thead><tr><th>Game</th><th>Finishing order</th><th class="num hide-sm">Turns</th></tr></thead>
          <tbody>${gs.map((g) => `<tr>
            <td class="date"><a href="#/game/${encodeURIComponent(g.id)}">Game ${g.number}</a><div class="sub">${esc(g.type_label)}</div></td>
            <td><div class="order">${g.players.map((r) => `<span>${who(r.player).replace('class="who', `class="who${r.rank === 1 ? " win" : ""}`)} <span class="vp">${r.vp}</span></span>`).join("")}</div></td>
            <td class="num hide-sm">${g.turns ?? ""}</td></tr>`).join("")}</tbody>
        </table></div>
      </section>
      <nav class="day-nav">
        ${prev ? `<a href="#/day/${prev}">Previous game day: ${fmtDate(prev)}</a>` : "<span></span>"}
        ${next ? `<a href="#/day/${next}">Next game day: ${fmtDate(next)}</a>` : "<span></span>"}
      </nav>`;
  }

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
    const rowHtml = (p) => `<tr${onFire(p.id) ? ' class="hot"' : ""}>
        <td class="rank">${p.leaderboard_rank}${S.games.length > 1 ? move(p.leaderboard_rank, p.rank_prev, sinceLast) : ""}</td>
        <td><span class="name-cell">${who(p.id)}${fireTag(p)}</span></td>
        <td class="num score">${fmtSigned(p.above_expected, 1)}</td>
        <td class="range hide-sm" title="${fmtSigned(p.above_expected, 2)} wins above expected. Luck alone covers ${fmtSigned(p.luck_band[0], 1)} to ${fmtSigned(p.luck_band[1], 1)} 95% of the time.">${strip(p)}</td>
        <td class="num">${p.wins}</td>
        <td class="num hide-sm">${num(p.expected_wins)}</td>
        <td class="num hide-sm">${p.games}</td>
        <td class="num" data-tip="${esc(`<b>${esc(p.name)}: ${pct(p.win_rate)}</b><br>${p.wins} of ${p.games} games. 95% interval ${pct(p.win_rate_ci[0])} to ${pct(p.win_rate_ci[1])}`)}">${pct(p.win_rate)}</td>
        <td class="num hide-sm">${num(p.avg_vp)}</td>
        <td class="num hide-sm">${pct(p.beat_rate)}</td>
      </tr>`;
    const rows = ranked.map(rowHtml).join("");

    const RG = S.ranking.recent_games;
    // Players who sat out the group's last RG games get a line under the cards instead of a faded card.
    const withForm = ranked.filter((p) => p.recent);
    const cards = withForm.filter((p) => p.recent.active).sort((a, b) =>
      (b.recent.above - a.recent.above) || (a.leaderboard_rank - b.leaderboard_rank));
    const idle = withForm.filter((p) => !p.recent.active);
    const lastPlayed = (p) => p.recent.games[p.recent.games.length - 1].date;
    const idleLine = idle.length ? `<p class="note">Not in the group's last ${RG} games: ${idle.map((p) =>
      `${who(p.id)} <span class="sub">(last played ${fmtDate(lastPlayed(p))})</span>`).join(", ")}.</p>` : "";
    // Column headers explain themselves on hover or focus, so the note under the table can stay short.
    // A heading with a sort key is a button: the first click puts the best first, the next one reverses it.
    const SORT = {
      rank: { f: (p) => p.leaderboard_rank, desc: false }, name: { f: (p) => p.name.toLowerCase(), desc: false },
      above: { f: (p) => p.above_expected, desc: true }, wins: { f: (p) => p.wins, desc: true },
      expected: { f: (p) => p.expected_wins, desc: true }, games: { f: (p) => p.games, desc: true },
      winrate: { f: (p) => p.win_rate, desc: true }, vp: { f: (p) => p.avg_vp, desc: true }, beat: { f: (p) => p.beat_rate, desc: true },
    };
    const th = (label, tip, cls = "", k = null) => k
      ? `<th${cls ? ` class="${cls}"` : ""} data-k="${k}" aria-sort="${k === "rank" ? "ascending" : "none"}"${tip ? ` data-tip="${esc(tip)}"` : ""}><button type="button" class="sort-btn">${label}</button></th>`
      : `<th${cls ? ` class="${cls}"` : ""} data-tip="${esc(tip)}" tabindex="0">${label}</th>`;
    const head = [
      th("#", `<b>Place</b><br>Arrows show the change since the last game (${fmtDate(latestGame.date)}).`, "", "rank"),
      th("Player", "", "", "name"),
      th("Above expected", "<b>Wins above expected</b><br>Wins minus expected wins. Ties go to the higher share of the table's VP.", "num", "above"),
      th("Against luck", "<b>Against luck</b><br>The gray band is where luck alone would put a player 95% of the time. The dot is where they are, the line is zero.", "hide-sm"),
      th("Wins", "<b>Wins</b>", "num", "wins"),
      th("Expected", "<b>Expected wins</b><br>What chance alone would give: 1 divided by the number of players, added up over every game played.", "num hide-sm", "expected"),
      th("Games", "<b>Games played</b>", "num hide-sm", "games"),
      th("Win rate", "<b>Win rate</b><br>Share of games won. Hover a value for its 95% interval.", "num", "winrate"),
      th("Avg VP", "<b>Average final VP</b>", "num hide-sm", "vp"),
      th("Beat rate", "<b>Beat rate</b><br>Share of opponents a player finished ahead of.", "num hide-sm", "beat"),
    ].join("");
    // Plain-text standings for the group chat.
    const standingsText = () => {
      const g = latestGame, ps = g.players.slice().sort((a, b) => a.rank - b.rank);
      const nm = (pid) => (P[pid] ? P[pid].name : "a guest");
      const lines = [`Catan Night standings after game ${g.number} (${fmtDate(g.date)})${VIEW !== "all" ? `, ${viewLabel(VIEW)}` : ""}`, ""];
      for (const p of ranked) {
        const d = p.rank_prev === null || p.rank_prev === undefined ? 0 : p.rank_prev - p.leaderboard_rank;
        lines.push(`${p.leaderboard_rank}. ${p.name}  ${fmtSigned(p.above_expected, 1)}  (${p.wins} ${p.wins === 1 ? "win" : "wins"} in ${p.games})`
          + `${d ? `  ${d > 0 ? "▲" : "▼"}${Math.abs(d)}` : ""}${onFire(p.id) ? "  🔥" : ""}`);
      }
      lines.push("", `Last game: ${nm(g.winner)} won game ${g.number}, ${ps[0].vp} to ${ps[1] ? ps[1].vp : "?"}.`, location.origin + location.pathname);
      return lines.join("\n");
    };
    const copyText = async (text) => {
      try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* fall back below */ }
      const ta = document.createElement("textarea");
      ta.value = text; ta.setAttribute("readonly", ""); ta.style.cssText = "position:fixed;opacity:0";
      document.body.appendChild(ta); ta.select();
      let ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      ta.remove();
      return ok;
    };
    const formDots = (p) => p.recent.games.map((h) => `<span class="fdot${h.won ? " w" : ""}" style="--c:${color(p.id)}" title="${fmtDate(h.date)}: ${h.won ? "won" : "lost"} (${signed(h.delta, 2)})"></span>`).join("");
    const card = (p) => {
      const r = p.recent, fire = r.on_fire;
      const d = p.rank_recent_ago === null || p.rank_recent_ago === undefined ? null : p.rank_recent_ago - p.leaderboard_rank;
      const rankLine = S.games.length <= RG ? "" : d === null ? `New on the board` : d ? `<span class="${d > 0 ? "up" : "down"}">${d > 0 ? "▲" : "▼"} ${Math.abs(d)} ${Math.abs(d) === 1 ? "place" : "places"}</span> to ${ord(p.leaderboard_rank)}` : `Holding ${ord(p.leaderboard_rank)}`;
      return `<a class="hot-card${fire ? " fire" : ""}${r.active ? "" : " idle"}" href="#/player/${encodeURIComponent(p.id)}">
        <div class="hot-top">${who(p.id, false)}${fire ? `<span class="fire-badge">${FLAME}On fire</span>` : r.streak >= 2 ? `<span class="streak">${r.streak} wins in a row</span>` : ""}</div>
        <div class="form" role="img" aria-label="Last ${r.games.length} games: ${r.games.map((h) => (h.won ? "won" : "lost")).join(", ")}">${formDots(p)}</div>
        <div class="hot-num"><b>${fmtSigned(r.above, 1)}</b> vs expected</div>
        <div class="hot-rank">${r.active ? rankLine : `Last played ${fmtDate(r.games[r.games.length - 1].date)}`}</div>
      </a>`;
    };
    main.innerHTML = `
      <h1>Leaderboard</h1>
      <p class="lede">${s.games} ${s.games === 1 ? "game" : "games"} ${s.first_date === s.last_date ? "on " + fmtDate(s.first_date) : "since " + fmtDate(s.first_date, { month: "long", year: "numeric" })}, ranked by wins above expected. <a href="#/about">How the ranking works</a></p>
      ${filterBar()}
      <section class="block panel">
        <div class="table-wrap"><table class="board">
          <thead><tr>${head}</tr></thead>
          <tbody>${rows}</tbody>
        </table></div>
      </section>
      <div class="board-foot">
        <p class="note">${outside.length ? `${outside.map((p) => `${esc(p.name)} (${p.above_expected > 0 ? "above" : "below"})`).join(", ")} ${outside.length === 1 ? "is" : "are"} outside the range luck alone covers so far.` : "Every dot is still inside its gray band, so the order could still be luck."} Hover a column heading to see what it means, click one to sort.</p>
        <button type="button" class="pill-btn" id="copy-standings"><svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><rect x="5" y="5" width="9" height="9" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M11 3.5V3a1 1 0 0 0-1-1H3a1 1 0 0 0-1 1v7a1 1 0 0 0 1 1h.5" fill="none" stroke="currentColor" stroke-width="1.5"/></svg><span>Copy standings</span></button>
      </div>

      ${Home.tonight()}

      ${cards.length || idle.length ? `<section class="block">
        <h2>Last ${RG} games</h2>
        <p class="note">Each player's own last ${RG} games, newest on the right, with wins above expected over just those games. On fire means at least ${num(S.ranking.fire_above, 0)} full win above expected across them. Places moved count the group's last ${RG} games.</p>
        ${cards.length ? `<div class="hot-grid">${cards.map(card).join("")}</div>` : ""}
        ${idleLine}
      </section>` : ""}

      ${Home.middle(ctx())}
      ${Home.awards(ctx())}
      ${Home.records(ctx())}

      ${answersTeaser()}

      <section class="block">
        <h2>Wins above expected over time</h2>
        <p class="note">Each player's running total after every game they played. A win moves the line up by 1 minus their fair share, a loss moves it down by their fair share.</p>
        <div class="panel"><div class="chart" id="trend-legend"></div><div class="chart" id="trend"></div><div id="trend-table"></div></div>
      </section>

      <section class="block">
        <h2>Game days</h2>
        <p class="note">Each square is a day, colored by who won. A day with more than one game is split by winner, wider for more wins. Click a day to see its games.</p>
        <div class="panel">${calendarHtml(S.games)}</div>
      </section>`;

    Home.draw(ctx());
    const board = main.querySelector("table.board");
    let sortK = "rank", sortDir = 1; // 1: the column's natural order, -1: reversed
    board.tHead.addEventListener("click", (e) => {
      const b = e.target.closest("button.sort-btn");
      if (!b) return;
      const k = b.closest("th").dataset.k, spec = SORT[k];
      if (k === sortK) sortDir = -sortDir; else { sortK = k; sortDir = 1; }
      const cmp = (x, y) => {
        const a = spec.f(x), c2 = spec.f(y);
        const base = (a < c2 ? -1 : a > c2 ? 1 : 0) * (spec.desc ? -1 : 1) * sortDir;
        return base || x.leaderboard_rank - y.leaderboard_rank;
      };
      board.tBodies[0].innerHTML = ranked.slice().sort(cmp).map(rowHtml).join("");
      const ascending = spec.desc ? sortDir === -1 : sortDir === 1;
      board.querySelectorAll("th[data-k]").forEach((h) => h.setAttribute("aria-sort", h.dataset.k === sortK ? (ascending ? "ascending" : "descending") : "none"));
    });
    const copyBtn = document.getElementById("copy-standings");
    copyBtn.addEventListener("click", async () => {
      const ok = await copyText(standingsText());
      const label = copyBtn.querySelector("span");
      label.textContent = ok ? "Copied" : "Couldn't copy";
      copyBtn.classList.toggle("done", ok);
      clearTimeout(copyBtn._t);
      copyBtn._t = setTimeout(() => { label.textContent = "Copy standings"; copyBtn.classList.remove("done"); }, 2000);
    });

    // A player's total only moves when they play, so each line is carried flat to the latest game. That puts
    // every name at the right edge where it can be labelled; the carried point gets no dot and no tooltip row.
    const lastX = Math.max(...ranked.flatMap((p) => p.standing_history.map((h) => h.index)));
    const series = ranked.map((p) => {
      const points = [{ x: 0, y: 0, tip: num(0, 2) }]
        .concat(p.standing_history.map((h) => ({ x: h.index, y: h.above_expected, tip: fmtSigned(h.above_expected, 2) })));
      const end = points[points.length - 1];
      if (end.x < lastX) points.push({ x: lastX, y: end.y, carry: true });
      return { id: p.id, name: p.name, color: color(p.id), points };
    });
    scrollCalendars();
    const legend = document.getElementById("trend-legend");
    legend.innerHTML = `<ul class="legend focus-legend">${ranked.map((p) => `<li data-sid="${esc(p.id)}" tabindex="0"><span class="sw" style="--c:${color(p.id)}"></span>${esc(p.name)}</li>`).join("")}</ul>`;
    legend.style.paddingBottom = "0";
    const gi = gamesByIndex();
    const trend = document.getElementById("trend");
    lineChart(trend, {
      series, yRef: 0, highlight: hlIn(ranked), directLabels: true, ariaLabel: "Wins above expected for each player after every game",
      xLabel: (x) => (x === 0 ? "<b>Start</b>" : `<b>${esc(gameLabel(gi[x]))}</b>`),
      xTickLabel: (x) => (x === 0 ? "start" : x),
    });
    // Pointing at a name in the legend or at a line's end label brings that line forward and fades the rest.
    const focusLine = (sid) => {
      const svg = trend.querySelector("svg");
      if (!svg) return;
      svg.classList.toggle("focusing", !!sid);
      svg.querySelectorAll("[data-sid]").forEach((el) => el.classList.toggle("on", el.dataset.sid === sid));
      legend.querySelectorAll("[data-sid]").forEach((el) => el.classList.toggle("on", el.dataset.sid === sid));
    };
    const sidOf = (e) => { const el = e.target.closest && e.target.closest("[data-sid]"); return el ? el.dataset.sid : null; };
    for (const box of [legend, trend]) {
      box.addEventListener("pointerover", (e) => { const sid = sidOf(e); if (sid) focusLine(sid); });
      box.addEventListener("pointerout", (e) => { if (sidOf(e)) focusLine(null); });
      box.addEventListener("focusin", (e) => { const sid = sidOf(e); if (sid) focusLine(sid); });
      box.addEventListener("focusout", () => focusLine(null));
    }
    const xs = [...new Set(series.flatMap((s) => s.points.filter((p) => !p.carry).map((p) => p.x)))].sort((a, b) => a - b);
    document.getElementById("trend-table").innerHTML = tableView(
      [{ label: "Game" }].concat(ranked.map((p) => ({ label: esc(p.name), num: true }))),
      xs.map((x) => [x === 0 ? "Start" : esc(gameLabel(gi[x]))].concat(series.map((s) => {
        const pt = s.points.find((p) => p.x === x && !p.carry); return pt ? num(pt.y) : "";
      }))));
  }

  function playerPage(pid) {
    const p = P[pid];
    if (!p) return notFound(`There's no player with the id "${esc(pid)}".`);
    if (!p.games) {
      main.innerHTML = `${playerSwitch(pid)}<h1>${esc(p.name)}</h1>${filterBar()}<p class="empty">${esc(p.name)} hasn't played ${VIEW === "all" ? "a recorded game" : `a recorded ${esc(viewLabel(VIEW))} game`} yet.</p>`;
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
        <p class="note">Averages per game, read from TwoSheep's turn-by-turn record.${basedOn(rp.games, "a replay")} <a href="#/players">All players</a></p>
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
      ${playerSwitch(pid)}
      <div class="player-head"><span class="pmark${p.leaderboard_rank === 1 ? " lead" : ""}"${p.leaderboard_rank === 1 ? ' title="First on the leaderboard"' : ""}><span class="hex" style="--c:${color(pid)}" aria-hidden="true"></span></span><h1>${esc(p.name)}</h1></div>
      <p class="lede">Ranked ${ord(p.leaderboard_rank)} of ${active}. ${p.games} ${p.games === 1 ? "game" : "games"} recorded.</p>
      ${hooksHtml("player-head", pid)}
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
    autoRail(`#/player/${encodeURIComponent(pid)}`);
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
        <p class="note">From the group models behind the <a href="#/questions">Questions</a>, each comparing ${esc(p.name)} with the people at the same tables. Intervals are 95%; one that crosses the "no difference" value (0, or 1×) means the games so far can't tell.</p>
        ${tiles.length ? `<div class="tiles">${tiles.join("")}</div>` : ""}
        ${recipe}
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

  // The Games tab has two views: the list (a table, newest first) and the book, which reads through every
  // game's headline in order. The choice and the book's reading order are remembered on this device.
  const stored = (k, d) => { try { return localStorage.getItem(k) || d; } catch (e) { return d; } };
  const store = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* storage blocked */ } };
  const gameHeadline = (g) => {
    const rc = (ROOT.recaps || {})[g.id];
    if (rc && rc.headline) return esc(rc.headline);
    const ps = g.players.slice().sort((a, b) => a.rank - b.rank);
    const wname = isGuest(g.winner) ? "A guest" : P[g.winner] ? P[g.winner].name : g.winner;
    return `${esc(wname)} wins, ${ps[0].vp} to ${ps[1] ? ps[1].vp : 0}`;
  };
  const orderLine = (g) => `<div class="order">${g.players.map((r) => `<span>${who(r.player).replace('class="who', `class="who${r.rank === 1 ? " win" : ""}`)} <span class="vp">${r.vp}</span></span>`).join("")}</div>`;
  function bookHtml(order) {
    const games = S.games.slice().sort((a, b) => (order === "new" ? b.number - a.number : a.number - b.number));
    let month = "", out = "";
    for (const g of games) {
      const m = g.date.slice(0, 7);
      if (m !== month) {
        if (month) out += `</ol>`;
        month = m;
        const n = games.filter((x) => x.date.slice(0, 7) === m).length;
        out += `<h2 class="book-month">${fmtDate(m + "-01", { month: "long", year: "numeric" })} <span class="sub">${n} ${n === 1 ? "game" : "games"}</span></h2><ol class="book-list">`;
      }
      out += `<li class="book-entry">
        <div class="book-no">Game ${g.number}<span class="dot" aria-hidden="true"> · </span>${fmtDate(g.date, { weekday: "short", month: "short", day: "numeric" })}</div>
        <h3 class="book-head"><a href="#/game/${encodeURIComponent(g.id)}">${gameHeadline(g)}</a></h3>
        <div class="book-meta"><span class="book-map">${esc(g.type_label)}</span>${orderLine(g)}</div>
      </li>`;
    }
    return `<div class="book">${out}${month ? "</ol>" : ""}</div>`;
  }

  function gamesPage() {
    const d = S.dice_overall;
    const mode = stored("games-view", "book") === "list" ? "list" : "book";
    const order = stored("book-order", "old") === "new" ? "new" : "old";
    const n = S.summary.games;
    const sw = (key, val, cur, text) => `<button type="button" class="chip${val === cur ? " on" : ""}" data-set="${key}" data-val="${val}" aria-pressed="${val === cur}">${text}</button>`;
    main.innerHTML = `
      <h1>Games</h1>
      <p class="lede">${n} ${n === 1 ? "game" : "games"} recorded${mode === "book" ? `, one headline each, ${order === "new" ? "newest" : "oldest"} first` : ", newest first"}.</p>
      ${filterBar()}
      <div class="chips size games-view" role="group" aria-label="How to show the games"><span class="chips-k">Show as</span>${sw("games-view", "book", mode, "Book")}${sw("games-view", "list", mode, "List")}${mode === "book" ? `<span class="chips-k book-order-k">Read</span>${sw("book-order", "old", order, "Oldest first")}${sw("book-order", "new", order, "Newest first")}` : ""}</div>
      ${mode === "book" ? (n ? bookHtml(order) : `<p class="empty">No games in this view.</p>`) : `
      <p class="note" style="margin-top:14px">Looking for a particular kind of game? See the <a href="#/winning/closest">closest and most one-sided games</a> and the <a href="#/winning/comebacks">comebacks</a>.</p>
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
            <td>${orderLine(g)}</td>
            <td class="num hide-sm">${g.turns ?? ""}</td></tr>`).join("")}</tbody>
        </table></div>
      </section>`}`;
    main.querySelectorAll(".games-view [data-set]").forEach((b) => b.addEventListener("click", () => {
      store(b.dataset.set, b.dataset.val);
      const y = window.scrollY;
      gamesPage();
      scopeLinks(main);
      window.scrollTo(0, y);
      const again = main.querySelector(`.games-view [data-set="${b.dataset.set}"][data-val="${b.dataset.val}"]`);
      if (again) again.focus({ preventScroll: true });
    }));
    if (d && mode === "list") diceChart(document.getElementById("dice-all"), d, "Dice roll counts across these games, with expected counts");
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
    const devTable = hasDev ? `<div class="panel table-wrap" style="margin-top:12px"><table><thead><tr><th>Dev cards bought</th>${cards.map(([, l]) => `<th class="num">${l}</th>`).join("")}</tr></thead>
          <tbody>${g.players.map((r) => `<tr><td>${who(r.player)}</td>${cards.map(([k]) => `<td class="num">${r.dev_cards_bought ? r.dev_cards_bought[k] || "" : ""}</td>`).join("")}</tr>`).join("")}</tbody></table></div>` : "";
    const replayTable = rps.length ? `<section class="block">
        <h2>Player numbers</h2>
        <p class="note">Expected is what each player's buildings would produce with average dice, robber included. Blocked counts cards the robber kept from them.</p>
        <div class="panel table-wrap"><table>
          <thead><tr><th>Player</th><th class="num">From dice</th><th class="num">Expected</th><th class="num">Blocked</th><th class="num">Robber moves</th><th class="num">Steals</th><th class="num">Robbed</th><th class="num">Lost to 7s</th><th class="num">Trades</th><th class="num">Bank trades</th><th class="num">Monopoly</th><th class="num">Longest road</th></tr></thead>
          <tbody>${rps.map(({ r, x }) => `<tr><td>${who(r.player)}</td><td class="num">${x.resources_from_dice}</td><td class="num">${num(x.expected_from_dice)}</td><td class="num">${x.blocked_by_robber}</td><td class="num">${x.robber_moves}</td><td class="num">${x.steals}</td><td class="num">${x.stolen_from}</td><td class="num">${x.cards_discarded}</td><td class="num">${x.trades}</td><td class="num">${x.bank_trades}</td><td class="num">${x.monopoly_cards || ""}</td><td class="num">${x.longest_road_length}</td></tr>`).join("")}</tbody>
        </table></div>
        <details class="tv"><summary>Building and development cards</summary>
        <div class="panel table-wrap" style="margin-top:12px"><table>
          <thead><tr><th>Player</th><th class="num">Settlements</th><th class="num">Cities</th><th class="num">Roads</th><th class="num">Ships</th><th class="num">Knights played</th><th class="num">Rolls</th><th class="num">7s rolled</th><th class="num">Opening dots</th></tr></thead>
          <tbody>${rps.map(({ r, x }) => `<tr><td>${who(r.player)}</td><td class="num">${x.built.settlement}</td><td class="num">${x.built.city}</td><td class="num">${x.built.road}</td><td class="num">${x.built.ship || ""}</td><td class="num">${x.dev_cards_played.knight || ""}</td><td class="num">${x.rolls}</td><td class="num">${x.sevens_rolled}</td><td class="num">${x.opening_dots}</td></tr>`).join("")}</tbody>
        </table></div>
        <p class="note">Built counts pieces placed during the game, free Road Building roads included, so starting settlements and roads aren't in it, and a settlement later upgraded still counts.</p>
        ${devTable}</details>
      </section>` : "";
    const all = ROOT.views.all.games.slice().sort((a, b) => a.number - b.number);
    const at = all.findIndex((x) => x.id === g.id), prevG = all[at - 1], nextG = all[at + 1];
    main.innerHTML = `
      <a class="back" href="#/games">Back to games</a>
      <h1>${fmtDate(g.date, { weekday: "long", month: "long", day: "numeric", year: "numeric" })}</h1>
      <p class="lede">${who(winner.player)} won with ${winner.vp} VP${g.turns ? ` in ${g.turns} turns` : ""}. ${esc(g.type_label)}, ${g.n_bots ? `${g.n_players - g.n_bots} players and ${g.n_bots === 1 ? "a TwoSheep bot" : g.n_bots + " TwoSheep bots"}` : `${g.n_players} players`}${g.vp_to_win ? `, playing to ${g.vp_to_win}` : ""}. Game ${g.number} on record.</p>
      ${settings.notes ? `<p class="note">${esc(settings.notes)}</p>` : ""}

      ${gameSummary(g)}

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

      ${rps.length ? "" : `<div class="two-col">
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
      </div>`}

      ${replayTable}
      ${hooksHtml("game", g)}
      <nav class="day-nav">
        ${prevG ? `<a href="#/game/${encodeURIComponent(prevG.id)}">Previous: game ${prevG.number}, ${fmtDate(prevG.date)}</a>` : "<span></span>"}
        ${nextG ? `<a href="#/game/${encodeURIComponent(nextG.id)}">Next: game ${nextG.number}, ${fmtDate(nextG.date)}</a>` : "<span></span>"}
      </nav>`;
    hooksDraw("game", g);
    hooksDraw("game-race", g);
    drawClosenessHists(g);
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
    autoRail(`#/game/${encodeURIComponent(g.id)}`);
  }

  // The momentum module draws the board VP race when it has this game; otherwise the true VP timeline is used.
  const raceHooked = (g) => hookList("game-race").length > 0 && !!(((ROOT.momentum || {}).games || {})[g.id]);

  // ---- Game summary: label, written recap, a line per player, turning points (scripts/story.py, recaps.py) ----
  const TAG_LABELS = { comeback: "Comeback", close: "Close game", blowout: "Blowout", solid: "Solid win" };
  const POINT_LABELS = { lead: "Lead", title: "Title", play: "Play of the game", reach: "In reach", win: "Finish" };
  // Story text names other players as {pid}; swap in their chips.
  const fillTokens = (text) => esc(text).replace(/\{([\w-]+)\}/g, (_, pid) => who(pid));
  // The recap is plain text; turn this game's player names into their chips.
  function linkNames(text, g) {
    let html = esc(text);
    for (const r of g.players) {
      const p = P[r.player];
      if (isGuest(r.player) || !p || !p.name) continue;
      const re = new RegExp(`(^|[^\\w>])${p.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![\\w<])`, "g");
      html = html.replace(re, (_, pre) => pre + who(r.player));
    }
    return html;
  }
  function gameSummary(g) {
    const st = (ROOT.stories || {})[g.id], rc = (ROOT.recaps || {})[g.id];
    if (!st) return "";
    const ps = g.players.slice().sort((a, b) => a.rank - b.rank);
    const wname = isGuest(g.winner) ? "A guest" : P[g.winner] ? P[g.winner].name : g.winner;
    const lines = ps.map((r) => `<tr><td>${who(r.player)}</td><td class="num">${ord(r.rank)}, ${r.vp} VP</td>
      <td class="recap-notes">${(st.notes[r.player] || []).map(esc).join('<span class="dot" aria-hidden="true"> · </span>') || '<span class="sub">nothing out of the ordinary</span>'}</td></tr>`).join("");
    const points = st.points.map((p) => `<li class="tp-${p.kind}"><span class="tp-t">Turn ${p.t}</span><span class="tp-k">${POINT_LABELS[p.kind] || ""}</span><span class="tp-x">${who(p.who)} ${fillTokens(p.text)}</span></li>`).join("");
    return `<section class="block recap" data-title="Summary">
        <div class="sec-kicker"><span class="sec-q">${TAG_LABELS[st.tag] || "Summary"}</span>${st.closeness && st.closeness.closest_tier ? `<span class="tag tag-desc">Closest tier</span>` : ""}${st.hidden_threat ? `<span class="tag tag-desc" title="Going into the last turn, the threat index rated someone else more likely to win.">Hidden threat</span>` : ""}</div>
        <h2>${rc ? esc(rc.headline) : `${esc(wname)} wins, ${ps[0].vp} to ${ps[1].vp}`}</h2>
        ${rc ? `<div class="verdict recap-text">${linkNames(rc.recap, g)}</div>
        <p class="note">Recap written by Claude from the numbers on this page, and checked against them.</p>` : `<div class="verdict recap-text">${gameStory(g).text}</div>`}
        <h3>Player by player</h3>
        <div class="panel table-wrap"><table><tbody>${lines}</tbody></table></div>
        <h3>Turning points</h3>
        <p class="note">${st.lead.changes} lead ${st.lead.changes === 1 ? "change" : "changes"} over ${st.turns} turns, on the points everyone could see. Turn numbers match the race chart below.</p>
        <ol class="tp">${points}</ol>
      </section>`;
  }

  function closenessTile(g) {
    const r = ((ROOT.closeness || {}).games || {})[g.id];
    if (!r) return "";
    const n = ROOT.closeness.n;
    const head = r.closest_tier ? "In our closest tier" : r.one_sided_tier ? "Among our most one-sided games"
      : `Closeness rank ${r.rank_min === r.rank_max ? r.rank_min : `${r.rank_min} to ${r.rank_max}`} of ${n}`;
    const parts = closenessParts(r);
    const all = Object.values(ROOT.closeness.games);
    const median = (xs) => { const s = [...xs].sort((a, b) => a - b), k = s.length >> 1; return s.length % 2 ? s[k] : (s[k - 1] + s[k]) / 2; };
    const hists = parts.length ? `
        <div class="cl-hists">${parts.map((p) => `<div class="cl-hist">
          <h3>${p.title}</h3>
          <div class="chart" id="cl-h-${p.key}"></div>
          ${fin(r["p" + p.key]) ? `<p class="cl-cap">Closer than ${num(100 * r["p" + p.key], 0)}% of games on this part</p>` : ""}
        </div>`).join("")}</div>
        <p class="note">Each chart counts all ${n} decoded games; the dark bar is this game. Ranks adjust lead changes and the lead for the VP target; the charts show the plain numbers. A tie counts as half closer.</p>
        ${tableView([{ label: "Part" }, { label: "This game", num: true }, { label: "Median game", num: true }, { label: "Closer than", num: true }],
          parts.map((p) => [p.title, p.fmt(p.val(r)), p.fmt(median(all.map(p.val).filter(fin))), fin(r["p" + p.key]) ? `${num(100 * r["p" + p.key], 0)}%` : ""]),
          "Show as table")}` : "";
    const size = r.n_seats < 5 ? `${r.n_seats} player games` : "5 and 6 player games";
    const inClass = r.index_in_class != null ? `. Among ${size}: ${num(r.index_in_class, 0)}` : "";
    return `<section class="block">
        <h2>How close was it? ${info("closeness", "Closeness index")}</h2>
        <div class="tiles"><div class="tile"><div class="v">${num(r.index, 0)}</div><div class="k">${head}</div><div class="s">Closeness index out of 100, on ${ROOT.closeness.hindsight ? "board VP" : "true VP (hindsight)"}${inClass}</div></div>
          <div class="tile"><div class="v">${r.A} VP</div><div class="k">Runner-up still needed</div><div class="s">before the winner's final turn</div></div>
          <div class="tile"><div class="v">${r.lead_changes}</div><div class="k">Lead changes</div><div class="s">new sole leader, before the final turn</div></div>
          <div class="tile"><div class="v">${num(r.C * (r.target - 2), 1)} VP</div><div class="k">Average lead</div><div class="s">from when anyone reached half the target</div></div>
          ${r.D != null ? `<div class="tile"><div class="v">${num(r.D, 1)}</div><div class="k">Players in contention</div><div class="s">on average, from each player's chance of winning</div></div>` : ""}</div>
        ${hists}
      </section>`;
  }

  // The closeness parts as the game page shows them: plain units, and which end of the scale is closer.
  function closenessParts(r) {
    const vp = (v) => `${num(v, 1)} VP`;
    const out = [
      { key: "A", title: "Runner-up still needed", val: (x) => x.A, discrete: true, closer: "left", fmt: (v) => `${num(v, v % 1 ? 1 : 0)} VP`, unit: (v) => `${v} VP` },
      { key: "B", title: "Lead changes", val: (x) => x.lead_changes, discrete: true, closer: "right", fmt: (v) => num(v, v % 1 ? 1 : 0),
        unit: (v) => `${v} lead ${v === 1 ? "change" : "changes"}` },
      { key: "C", title: "Average lead", val: (x) => x.C * (x.target - 2), width: 0.5, closer: "left", fmt: vp, unit: (a, b) => `${num(a, 1)} to ${num(b, 1)} VP` },
    ];
    if (fin(r.D)) out.push({ key: "D", title: "Players in contention", val: (x) => x.D, width: 0.25, closer: "right", fmt: (v) => num(v, 1),
      unit: (a, b) => `${num(a, 2)} to ${num(b, 2)} in contention` });
    return out;
  }

  function drawClosenessHists(g) {
    const r = ((ROOT.closeness || {}).games || {})[g.id];
    if (!r) return;
    const all = Object.values(ROOT.closeness.games);
    const games = (k) => `${k} ${k === 1 ? "game" : "games"}`;
    for (const p of closenessParts(r)) {
      const el = document.getElementById(`cl-h-${p.key}`);
      const vals = all.map(p.val).filter(fin), mine = p.val(r);
      if (!el || !vals.length || !fin(mine)) continue;
      let bins, mark, edges = null;
      if (p.discrete) {
        const lo = Math.min(...vals), hi = Math.max(...vals);
        bins = [];
        for (let v = lo; v <= hi; v++) {
          const k = vals.filter((x) => x === v).length;
          bins.push({ count: k, label: String(v), tip: `<b>${esc(p.unit(v))}</b><br>${games(k)}${v === mine ? "<br>Includes this game" : ""}` });
        }
        mark = mine - lo;
      } else {
        const w = p.width, idx = (v) => Math.floor(v / w + 1e-9);
        const i0 = idx(Math.min(...vals)), i1 = idx(Math.max(...vals));
        bins = [];
        edges = [];
        for (let i = i0; i <= i1; i++) {
          const k = vals.filter((x) => idx(x) === i).length;
          bins.push({ count: k, label: "", tip: `<b>${esc(p.unit(i * w, (i + 1) * w))}</b><br>${games(k)}${idx(mine) === i ? "<br>Includes this game" : ""}` });
          edges.push(+(i * w).toFixed(4));
        }
        edges.push(+((i1 + 1) * w).toFixed(4));
        mark = idx(mine) - i0;
      }
      markHist(el, { bins, mark, edges, discrete: p.discrete, closer: p.closer, height: 128,
        ariaLabel: `${p.title} across all ${vals.length} decoded games. This game: ${p.fmt(mine)}.` });
    }
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

  function stylePage(into) {
    const out = into || main;
    const ranked = S.players.filter((p) => p.games > 0 && p.replay);
    if (!ranked.length) {
      out.innerHTML = `<h1>Play style</h1>${filterBar()}<p class="empty">No decoded replays in these games yet.</p>`;
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

    out.innerHTML = `
      <h1>Play style</h1>
      <p class="lede">How everyone plays, from TwoSheep's turn-by-turn record of ${n} ${n === 1 ? "game" : "games"}. Numbers are per game unless they say otherwise.</p>
      ${filterBar()}
      <div class="mk-key">${markerLegend()}<span class="note">The small arrows compare a player with the people at the same tables: +0.5 SD means a typical game puts them half a standard deviation above their tablemates on that stat. Colored arrows are clear of noise. ${info("markers", "vs the table markers")}</span></div>

      ${luckSection()}
      <section class="block">
        <h2>Dice luck: actual against expected</h2>
        <p class="note">A second way to measure luck: cards each player got from rolls against what their own settlements and cities would have produced with average dice at the moment of each roll, robber included. Above 1.00× means the dice ran hot for them. Good placement shows up in the expected column; luck is the gap. Gold counts as one card. Unlike dice luck by player, this is not compared with tablemates, so dice that favored the whole table lift everyone.</p>
        <div class="panel table-wrap"><table>
          <thead><tr><th>Player</th><th class="num">Games</th><th class="num">From dice</th><th class="num">Expected</th><th class="num">Difference</th><th class="num">Luck</th><th class="hide-sm" style="width:28%"></th></tr></thead>
          <tbody>${lucky.map((p) => { const r = p.replay; return row([`<td>${who(p.id)}</td>`, `<td class="num">${r.games}</td>`, td(r.avg_resources_from_dice), td(r.avg_expected_from_dice),
            `<td class="num">${signed(r.avg_luck)} <span class="cell-mk">${mk(p.id, "luck")}</span></td>`, `<td class="num"><b>${num(r.dice_ratio, 2)}×</b></td>`, `<td class="hide-sm">${divBar(r.dice_ratio - 1, maxLuck)}</td>`]); }).join("")}</tbody>
        </table></div>
      </section>

      <section class="block">
        <h2>Robber</h2>
        <p class="note">Per game. Robber moves counts 7s and knights. Steals are cards taken with the robber or pirate, and robbed is cards taken from them. Lost to 7s is cards discarded for holding too many. Blocked is production the robber sat on. 7s rolled is the share of a player's own rolls that came up 7; fair dice give 16.7%.</p>
        <div class="panel table-wrap"><table>
          <thead><tr><th>Player</th><th class="num">Robber moves</th><th class="num">Steals</th><th class="num">Robbed</th><th class="num">Lost to 7s</th><th class="num">Blocked</th><th class="num">Monopoly haul</th><th class="num">7s rolled</th></tr></thead>
          <tbody>${by((p) => p.replay.avg_steals).map((p) => { const r = p.replay; return row([`<td>${who(p.id)}</td>`, tdm(r.avg_robber_moves, p.id, "robber_moves"), tdm(r.avg_steals, p.id, "steals"), tdm(r.avg_stolen_from, p.id, "stolen_from"),
            tdm(r.avg_cards_discarded, p.id, "cards_discarded"), tdm(r.avg_blocked_by_robber, p.id, "blocked_by_robber"), tdm(r.avg_monopoly_cards, p.id, "monopoly_cards"), `<td class="num">${pct(r.seven_rate, 1)} <span class="sub">of ${r.rolls}</span></td>`]); }).join("")}</tbody>
        </table></div>
      </section>

      <section class="block">
        <h2>Who robs whom</h2>
        <p class="note"><b>How to read:</b> read across a row: the big number is cards that player stole from each opponent per game played together; the small text is the total over how many games. Darker red means more.</p>
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

  // One plain sentence on whether any seat's wins fall outside the chance band.
  function seatVerdict(se) {
    const out = [];
    for (const n of ["3", "4"]) {
      for (const b of ((se || {})[n] || {}).seats || []) {
        if (b.wins < b.lo || b.wins > b.hi) out.push(`${ord(b.seat)} of ${n} won ${b.wins > b.hi ? "more" : "less"} than luck explains`);
      }
    }
    return out.length ? out.join("; ") + "." : "Every bar sits inside its box, so no seat has a clear edge so far.";
  }

  // ---- Findings: group-level models and tests ------------------------------------------
  function findingsPage(into) {
    const out = into || main;
    const I = ins();
    const order = S.players.filter((p) => p.games > 0).map((p) => p.id);  // leaderboard order, never re-sorted
    const rowsFor = (obj, f) => order.filter((pid) => obj && obj[pid]).map((pid) => f(pid, obj[pid]));
    const o = I.opening, bo = I.best_opener, rb = I.opening_robustness;
    const viewNote = o && o.source === "all games"
      ? `<p class="note">This view has ${o.view_games} games with replays, under the 30 a model needs, so the numbers are from all games.</p>` : "";
    const rbOf = (name) => (rb || []).find((r) => r.name === name);
    const rbW = rbOf("Mundlak, within player"), rbF = rbOf("Player fixed effects");
    const rob = rb ? `<div class="note"><b>Is it the spot or the player?</b> If stronger players simply open better, dots could be standing in for skill. Comparing each player only with their own other games still gives b = ${rbW ? num(rbW.b, 2) : "n/a"}, and adding a term for each player gives ${rbF ? num(rbF.b, 2) : "n/a"}, against ${num(o.b, 2)} for the headline${rbW && rbF && rbW.b > 0 && rbF.b > 0 ? ", so the dots themselves seem to matter, not just who gets them" : ""}. All refits are on <a href="#/about">How it works</a>. ${info("robustness", "Robustness refits")}</div>` : "";
    const d = I.dice_calibration;
    const cl = ROOT.closeness;

    out.innerHTML = `
      <h1>Findings</h1>
      <p class="lede">What the games say as a group: openings, seats, the robber, trading, where winning points come from, the dice, and which games were closest.</p>
      <p class="note">Most charts here put a number next to what pure luck would give. Lines through dots are 95% intervals: the range the true value most likely sits in. When an interval crosses the "no effect" line, the games so far can't tell that effect apart from luck.</p>
      ${filterBar()}

      <section class="block">
        <h2>Openings ${info("opening", "Opening edge and win chance")}</h2>
        ${o ? `<p class="note">Every number token has dots printed under it: 5 on a 6 or 8, 4 on a 5 or 9, down to 1 on a 2 or 12. More dots means that number comes up more often. A player's opening dots add up the dots on every hex their two starting settlements touch, and here they are measured against the table: dots minus the average of everyone in that game.</p>
        ${viewNote}
        <div class="tiles">
          <div class="tile"><div class="v">${pct(o.p2)}</div><div class="k">Win chance, 2 dots above the table</div><div class="s">against 3 equal opponents; 25% at an even table</div></div>
          <div class="tile"><div class="v">${num(o.or, 2)}×</div><div class="k">Odds per extra dot</div><div class="s">95% interval ${num(o.or_ci[0], 2)} to ${num(o.or_ci[1], 2)}</div></div>
          <div class="tile"><div class="v">${o.games}</div><div class="k">Games in the model</div><div class="s">coefficient b = ${num(o.b, 3)} on the log odds scale, 95% ${num(o.ci[0], 3)} to ${num(o.ci[1], 3)}</div></div>
        </div>
        <p class="note" style="margin-top:12px"><b>How to read:</b> find how many more opening dots you had than each of three otherwise equal opponents on the bottom axis; the line gives your chance of winning, in percent. At 0 everyone has 25%. The shaded band is the 95% interval for the curve.</p>
        <div class="panel" style="margin-top:6px"><div class="chart" id="f-pd"></div>
        ${tableView([{ label: "Dots above each opponent" }, { label: "Win chance", num: true }, { label: "95% interval", num: true }],
          o.curve.map((c) => [signed(c.d, 0), pct(c.p, 1), `${pct(c.lo, 1)} to ${pct(c.hi, 1)}`]))}</div>
        <p class="note">Most of the information comes from New Shores 3 and 4 player games.</p>
        ${rob}` : `<p class="empty">Needs 30 games with replays.</p>`}
      </section>

      ${bo ? `<section class="block">
        <h2>Best opener's wins ${info("best_opener", "Best opener's wins vs chance")}</h2>
        <p class="note"><b>How to read:</b> in every game, the seat with the most opening dots is the best opener and the seat with the fewest the worst; everyone else is the middle. Bars are how many games each group won. The tick is what they would win if dots didn't matter, and the gray box is the range luck alone covers 95% of the time. Best openers won ${num(bo.buckets[0].observed, 1)} against ${num(bo.buckets[0].expected, 1)} expected (one-sided permutation p = ${num(bo.p_best, 3)}).${bo.dropped_all_tied ? ` ${bo.dropped_all_tied} ${bo.dropped_all_tied === 1 ? "game" : "games"} where every seat tied ${bo.dropped_all_tied === 1 ? "is" : "are"} left out.` : ""}</p>
        <div class="panel"><div class="chart" id="f-best"></div></div>
      </section>` : ""}

      <section class="block">
        <h2>Opening strength by player ${info("opening_player", "Opening strength vs the table")}</h2>
        <p class="note"><b>How to read:</b> how many more dots than the table average each player's opening sat on, per game. Right of the 0 line means stronger openings than the people they play with. This mixes board luck, draft position and choice. The filled dot adjusts for draft position (picking last in a 4 player game is a handicap); the hollow ring is the raw number. A line that crosses 0 means no clear difference.</p>
        ${Object.keys(I.opening_by_player || {}).length ? `<div class="panel"><div class="chart" id="f-open"></div></div>` : guardNote(0, 10)}
      </section>
      ${hooksHtml("findings-openings")}

      <section class="block">
        <h2>Turn order ${info("seat", "Seat effect")}</h2>
        <p class="note"><b>How to read:</b> wins by turn order (1st places first and rolls first), in 3 and 4 player games. The tick is a fair share of the wins and the gray box the range luck alone covers 95% of the time. ${seatVerdict(I.seat_effect)}</p>
        <div class="two-col">${["3", "4"].filter((n) => (I.seat_effect || {})[n]).map((n) => `<div><h3>${n} players <span class="sub">${I.seat_effect[n].games} games</span></h3><div class="panel" style="margin-top:8px"><div class="chart" id="f-seat-${n}"></div></div></div>`).join("") || `<p class="empty">No 3 or 4 player games with seats here.</p>`}</div>
      </section>

      <section class="block">
        <h2>Robbed vs an even split ${info("steal_share", "Steal share vs an even split")}</h2>
        <p class="note"><b>How to read:</b> 1× means a player lost exactly their fair share of stolen cards, if everyone else's steals were split evenly among their possible victims. Right of the line: robbed more; left: robbed less. This ignores the board, so a player who leads or has the best production can be robbed more for good reasons. <a href="#/robber/over-robbed">Robbed beyond the board</a> has a version that allows for that.</p>
        ${Object.keys(I.steal_share || {}).length ? `<div class="panel"><div class="chart" id="f-steal"></div></div>` : guardNote(0, 10)}
      </section>

      <section class="block">
        <h2>Trading and the bank ${info("trade_bank", "Trade and bank profile")}</h2>
        <p class="note"><b>How to read:</b> the left chart is how much each player trades with other players, as a multiple of their tablemates (1× the same, 1.2× trading 20% more). The right chart is the share of the cards they receive that comes from the bank or ports, in percentage points above or below their tablemates. In the table, port rate is cards handed to the bank per card back: 4 means always 4:1, 2 means always a 2:1 port.</p>
        ${Object.keys(I.trade_bank || {}).length ? `<div class="two-col">
          <div><h3>Player trades, rate vs the table</h3><div class="panel" style="margin-top:8px"><div class="chart" id="f-trade"></div></div></div>
          <div><h3>Bank share of cards received, vs the table</h3><div class="panel" style="margin-top:8px"><div class="chart" id="f-bank"></div></div></div>
        </div>
        <div class="panel table-wrap" style="margin-top:12px"><table><thead><tr><th>Player</th><th class="num">Games</th><th class="num">Trade rate</th><th class="num">Bank share</th><th class="num">Port rate</th></tr></thead>
          <tbody>${rowsFor(I.trade_bank, (pid, t) => `<tr><td>${who(pid)}</td><td class="num">${t.games}</td><td class="num">${num(t.trade_rr, 2)}×</td><td class="num">${fmtSigned(t.bank_rd * 100, 1)} pts</td><td class="num">${num(t.port_rate, 2)} : 1</td></tr>`).join("")}</tbody></table></div>` : guardNote(0, 10)}
      </section>

      <section class="block">
        <h2>Where winning points came from ${info("recipe", "Win recipe")}</h2>
        <p class="note"><b>How to read:</b> for each player's wins, the share of their points from buildings (settlements and cities), development (VP cards and Largest Army) and bonuses (Longest Road and islands). Players with at least 10 wins.</p>
        ${Object.keys(I.win_recipe || {}).length ? `<div class="panel table-wrap"><table><thead><tr><th>Player</th><th class="num">Wins</th><th class="num">Buildings</th><th class="num">Development</th><th class="num">Bonuses</th></tr></thead>
          <tbody>${rowsFor(I.win_recipe, (pid, r) => `<tr><td>${who(pid)}</td><td class="num">${r.wins}</td>${["buildings", "development", "bonuses"].map((c) => `<td class="num">${recipeCell(r[c])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
          <p class="note">Each cell: the share of the player's winning points from that source, then how many percentage points that is above (+) or below (−) other players' wins in the same kind of game, with its 95% interval. A +8 under development means dev cards made up 8 points more of their winning totals than usual. Bold numbers are clear of noise.</p>` : `<p class="empty">Nobody has 10 wins in this view yet.</p>`}
      </section>

      ${d ? `<section class="block">
        <h2>Are the dice fair? ${info("dice", "Dice calibration")}</h2>
        <div class="tiles">
          <div class="tile"><div class="v">${d.sevens}</div><div class="k">Sevens rolled</div><div class="s">${num(d.sevens_expected, 0)} expected; rate ${pct(d.seven_rate, 1)} (${pct(d.seven_rate_ci[0], 1)} to ${pct(d.seven_rate_ci[1], 1)}), z = ${num(d.seven_z, 1)}</div></div>
          <div class="tile"><div class="v">${d.chi2_p < 0.05 ? "Off" : "Fair"}</div><div class="k">Do all rolls match fair dice?</div><div class="s">p = ${num(d.chi2_p, 3)} over ${d.rolls} rolls (χ² ${num(d.chi2, 1)} on ${d.chi2_df} df); below 0.05 would be a warning sign</div></div>
          <div class="tile"><div class="v">${d.per_game_p < 0.05 ? "No" : "Yes"}</div><div class="k">Do rolls look independent within games?</div><div class="s">summed per-game χ² ${num(d.per_game_chi2, 0)} on ${d.per_game_df} df, p = ${num(d.per_game_p, 2)}</div></div>
          <div class="tile"><div class="v">${fmtSigned(d.drift * 100, 1)}%</div><div class="k">Extra cards from these dice</div><div class="s">how many more cards a board with one settlement on every number got than fair dice would give</div></div>
        </div>
        <p class="note">${d.seven_z < -2 ? "Sevens came up less often than fair dice predict, so everyone looks slightly lucky in absolute terms. " : d.seven_z > 2 ? "Sevens came up more often than fair dice predict, so everyone looks slightly unlucky in absolute terms. " : ""}Everyone at a table shares the same dice, so comparing players within the same game, as most of this site does, removes it.</p>
      </section>` : ""}

      ${hooksHtml("findings")}
      ${cl ? closestSection(cl) : ""}`;
    hooksDraw("findings-openings");
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
    return `<span class="chipline"><span class="mini">runner-up needed ${r.A} VP</span><span class="mini">${r.lead_changes} lead ${r.lead_changes === 1 ? "change" : "changes"}</span><span class="mini">avg lead ${num(r.C * (r.target - 2), 1)} VP</span>${r.D != null ? `<span class="mini">${num(r.D, 1)} in contention</span>` : ""}</span>`;
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
        <p class="note"><b>How to read:</b> each dot is a game, placed by its closeness index (0 to 100) from how far back the runner-up was, how often the lead changed, how big the lead usually was${cl.parts === "ABCD" ? " and how many players were in contention" : ""}. Right is closer; blue dots are the closest tier, red the most one-sided. Click a dot to open the game. ${board ? "Measured on board VP, what everyone could see; hidden VP cards are left out." : "<b>Hindsight</b> for now: this uses true VP, including VP cards nobody could see."} Ranks are among all ${cl.n} decoded games and don't change with the filter.</p>
        <div class="panel"><div class="chart">${strip}</div></div>
        <h3 style="margin-top:20px">The closest tier</h3>
        <p class="note">Games that land in the top quarter however the parts are weighed. Rank is out of every decoded game, shown as a range because it moves with the weighting. The sparkline is the leader's margin through the game: flat and low means a tight race.</p>
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
      <p>Every interval on the site is 95%. Intervals come from a bootstrap that resamples whole games unless a note says otherwise. Only two effects are tested, both chosen in advance and only in the all-games view: the opening effect on the Openings page, and (once the decoder records each roll) whether early dice luck snowballs. Everything else is an estimate with an interval and no significance wording.</p>
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

  // ---- Head to head (a block on the Players page) -------------------------------------------------
  function h2hBlock() {
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
    return `<section class="block" id="sec-h2h">
        <h2>Head to head</h2>
        <p class="note">Read across a row: how often that player finished ahead of each opponent in the games they both played. Ties count as half.</p>
        <div class="panel" style="padding:14px">
          <div class="table-wrap"><table class="matrix"><thead><tr><th></th>${head}</tr></thead><tbody>${body}</tbody></table></div>
          <div class="scale"><span>Usually behind</span><span class="bar" aria-hidden="true"></span><span>Usually ahead</span></div>
        </div>
      </section>`;
  }

  // ---- Players: everyone at a glance, then head to head ---------------------------------------------
  function playersPage() {
    const ranked = S.players.filter((p) => p.games > 0);
    if (!ranked.length) {
      main.innerHTML = `<h1>Players</h1>${filterBar()}<p class="empty">No games recorded in this view yet.</p>`;
      return;
    }
    const B = (ROOT.classes || {}).badges || {};
    const card = (p) => {
      const bs = ((B[p.id] || {}).badges || []).map((b) => b.name);
      return `<a class="p-card" href="#/player/${encodeURIComponent(p.id)}">
        <div class="hot-top">${who(p.id, false)}${onFire(p.id) ? `<span class="fire-badge">${FLAME}On fire</span>` : ""}</div>
        <div class="p-rank">Ranked ${ord(p.leaderboard_rank)}, ${p.games} ${p.games === 1 ? "game" : "games"}</div>
        <dl><dd>${fmtSigned(p.above_expected, 1)}</dd><dt>Above expected</dt><dd>${pct(p.win_rate)}</dd><dt>Win rate</dt><dd>${p.wins}</dd><dt>Wins</dt></dl>
        ${bs.length ? `<div class="chipline">${bs.map((b) => `<span class="mini"><b>${esc(b)}</b></span>`).join("")}</div>` : ""}
      </a>`;
    };
    main.innerHTML = `
      <h1>Players</h1>
      <p class="lede">Pick a player for their full page: record, luck, robber, trading and style. Badges are style labels that are clear of noise over all games.</p>
      ${filterBar()}
      <div class="p-grid">${ranked.map(card).join("")}</div>
      ${h2hBlock()}`;
  }

  const playerSwitch = (pid) => `<nav class="p-switch" aria-label="Players"><a class="p-all" href="#/players">All players</a>${
    S.players.filter((p) => p.games > 0 || p.id === pid).map((p) => who(p.id).replace('class="who"', `class="who"${p.id === pid ? ' aria-current="page"' : ""}`)).join("")}</nav>`;

  // ---- Topic pages ----------------------------------------------------------------------------------
  // A topic page draws the original style, findings and network blocks into holding boxes, then keeps only
  // the sections Topics assigns to it, in its order, with the question, answer and confidence tag on top.
  const TP = window.Topics;
  const SRC = {
    style: (el) => stylePage(el),
    findings: (el) => findingsPage(el),
    network: (el) => { if (Pages.network) Pages.network.render(Object.assign(ctx(), { main: el })); },
  };
  const slugOf = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  const headText = (h) => {
    const c = h.cloneNode(true);
    c.querySelectorAll(".info, .sub").forEach((x) => x.remove());
    return c.textContent.replace(/\s+/g, " ").trim();
  };
  const tagHtml = (tag) => (TP.TAGS[tag] ? `<span class="tag tag-${tag}" title="${esc(TP.TAGS[tag].tip)}">${TP.TAGS[tag].label}</span>` : "");
  const tagKey = () => `<p class="note key-note">${Object.keys(TP.TAGS).map(tagHtml).join("")}<span>Tags say how sure each answer is. Every interval is 95%. <a href="#/about">How it works</a></span></p>`;
  const qRow = (q) => `<a class="q-row" data-tag="${q.a ? q.a.tag : ""}" href="#/${q.topic}/${q.id}"><span class="q-q">${esc(q.q)}</span>`
    + (q.a ? `<span class="q-a">${tagHtml(q.a.tag)}${esc(q.a.text)}</span>` : `<span class="q-a empty">Not enough games in this view yet.</span>`) + `</a>`;

  // "How to read" paragraphs fold away; the answer line above the chart carries the result.
  function foldHowTo(root) {
    root.querySelectorAll(".note").forEach((n) => {
      const b = n.firstChild;
      if (!b || b.nodeType !== 1 || b.tagName !== "B" || !/^How to read/.test(b.textContent)) return;
      b.remove();
      const d = document.createElement("details"), body = document.createElement("div");
      d.className = "howto";
      d.innerHTML = "<summary>How to read this</summary>";
      body.className = "note";
      body.append(...n.childNodes);
      d.append(body);
      n.replaceWith(d);
    });
  }
  // The <h3> parts of a long section from index `from` on start collapsed, each under its own title or question.
  function foldParts(sec, e, c) {
    [...sec.querySelectorAll(":scope > h3")].slice(e.fold).forEach((h3) => {
      const title = headText(h3);
      const sub = (e.subs || []).find((u) => u.match === title);
      const a = sub ? TP.answer(sub.answer, c) : null;
      const d = document.createElement("details"), sm = document.createElement("summary");
      d.className = "part";
      if (sub) d.id = "sec-" + sub.id;
      sm.innerHTML = `<span class="part-t">${esc(sub ? sub.q : title)}</span>${a ? tagHtml(a.tag) : ""}${a && a.text ? `<span class="part-a">${esc(a.text)}</span>` : ""}`;
      const rest = [];
      for (let n = h3.nextSibling; n && !(n.nodeType === 1 && n.tagName === "H3"); n = n.nextSibling) rest.push(n);
      h3.replaceWith(d);
      h3.removeAttribute("style");
      let top = h3;
      if (sub) h3.className = "part-h";
      else {
        // The summary already carries the title; keep only the method note button.
        const infos = [...h3.querySelectorAll(":scope > .info")];
        top = infos.length ? document.createElement("div") : null;
        if (top) { top.className = "part-about"; top.append("About this part ", ...infos); }
      }
      d.append(sm, ...(top ? [top] : []), ...rest);
    });
  }
  function decorate(sec, e, c) {
    const a = TP.answer(e.answer, c);
    sec.id = "sec-" + e.id;
    const h2 = sec.querySelector(":scope > h2");
    const infos = [...h2.querySelectorAll(":scope > .info")];
    h2.textContent = (a && a.head) || e.title;
    infos.forEach((i) => h2.append(" ", i));
    h2.insertAdjacentHTML("beforebegin", `<div class="sec-kicker"><span class="sec-q">${esc(e.q)}</span>${a ? tagHtml(a.tag) : ""}<a class="sec-link" href="#/${e.topic}/${e.id}" title="Link to this section" aria-label="Link to this section">#</a></div>`);
    if (a && a.text) h2.insertAdjacentHTML("afterend", `<div class="verdict">${esc(a.text)}</div>`);
    foldHowTo(sec);
    if (e.fold !== undefined) foldParts(sec, e, c);
    const rel = (e.rel || []).map((r) => [r, TP.titleOf(r)]).filter((r) => r[1]);
    if (rel.length) sec.insertAdjacentHTML("beforeend", `<div class="related">Related:${rel.map(([r, t]) => `<a href="#/${r}">${esc(t)}</a>`).join("")}</div>`);
  }

  function topicPage(key) {
    const T = TP.topic(key), secs = TP.sectionsOf(key);
    // The shared trade and robber graph opens on the layer this topic is about.
    const layer = (secs.find((s) => s.layer) || {}).layer;
    if (layer) { try { localStorage.setItem("net-layer", layer); } catch (e) { /* storage blocked */ } }
    main.innerHTML = `<h1>${esc(T.title)}</h1><p class="lede">${esc(T.lede)}</p>${filterBar()}${tagKey()}
      <div id="topic-body">${T.sources.map((s) => `<div data-src="${s}"></div>`).join("")}</div>`;
    const body = document.getElementById("topic-body");
    for (const s of T.sources) SRC[s](body.querySelector(`[data-src="${s}"]`));
    const found = [];
    for (const e of secs) {
      const box = body.querySelector(`[data-src="${e.src}"]`);
      const sec = [...box.querySelectorAll("section.block")].find((s) => {
        const h = s.querySelector(":scope > h2");
        return h && headText(h) === e.match;
      });
      if (sec) found.push({ e, sec });
    }
    if (!found.length) {
      body.innerHTML = `<p class="empty">No decoded replays in these games yet.</p>`;
      return;
    }
    const c = ctx();
    found.forEach(({ e, sec }) => decorate(sec, e, c));
    body.replaceChildren(...found.map((f) => f.sec));
    layoutWithRail(found.map(({ e }) => ({ id: "sec-" + e.id, slug: e.id, title: e.title })), "#/" + key);
  }

  // ---- Questions: every question with its short answer ------------------------------------------------
  function questionsPage() {
    const qs = TP.questions(ctx());
    const count = (t) => qs.filter((q) => q.a && q.a.tag === t).length;
    main.innerHTML = `
      <h1>Questions</h1>
      <p class="lede">Everything this site tries to answer, with the short answer from the games so far. Pick a question to see the chart behind it.</p>
      ${filterBar()}
      <div class="chips q-filter" role="group" aria-label="Filter by confidence"><span class="chips-k">Show</span>
        <button type="button" class="chip on" data-tag="" aria-pressed="true">All <span class="n">${qs.length}</span></button>
        ${Object.keys(TP.TAGS).map((t) => `<button type="button" class="chip" data-tag="${t}" aria-pressed="false" title="${esc(TP.TAGS[t].tip)}">${TP.TAGS[t].label} <span class="n">${count(t)}</span></button>`).join("")}</div>
      ${TP.TOPICS.map((t) => `<section class="block q-topic">
        <h2><a href="#/${t.key}">${esc(t.title)}</a></h2>
        <p class="note">${esc(t.lede)}</p>
        <div class="q-list">${qs.filter((q) => q.topic === t.key).map(qRow).join("")}</div>
      </section>`).join("")}`;
    const btns = [...main.querySelectorAll(".q-filter button")];
    btns.forEach((b) => b.addEventListener("click", () => {
      btns.forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-pressed", String(x === b)); });
      main.querySelectorAll(".q-row").forEach((r) => { r.hidden = !!b.dataset.tag && r.dataset.tag !== b.dataset.tag; });
      main.querySelectorAll(".q-topic").forEach((s) => { s.hidden = !s.querySelector(".q-row:not([hidden])"); });
    }));
  }
  // On the home page: the answers that are clear of luck so far.
  function answersTeaser() {
    const all = TP.questions(ctx());
    const qs = all.filter((q) => q.a && q.a.tag === "clear").slice(0, 6);
    if (!qs.length) return "";
    return `<section class="block">
        <h2>What the games say</h2>
        <p class="note">The answers that are clear of luck so far. <a href="#/questions">All ${all.length} questions</a></p>
        <div class="q-list">${qs.map(qRow).join("")}</div>
      </section>`;
  }

  // ---- Section menu: a rail on wide screens, a jump list in the sticky bar on narrow ones -------------
  let spyOff = null;
  function layoutWithRail(items, base) {
    const lay = document.createElement("div"), rail = document.createElement("nav"), col = document.createElement("div");
    lay.className = "rail-layout"; rail.className = "rail"; col.className = "rail-body";
    rail.setAttribute("aria-label", "On this page");
    rail.innerHTML = `<div class="rail-h">On this page</div><ol>${items.map((i) => `<li><a href="${base}/${i.slug}">${esc(i.title)}</a></li>`).join("")}</ol>`;
    col.append(...main.childNodes);
    lay.append(rail, col);
    main.append(lay);
    document.body.classList.add("has-rail");
    const jump = document.getElementById("sec-jump");
    jump.innerHTML = `<option value="">Jump to a section</option>${items.map((i) => `<option value="${esc(i.slug)}">${esc(i.title)}</option>`).join("")}`;
    jump.dataset.base = base;
    const links = [...rail.querySelectorAll("a")], els = items.map((i) => document.getElementById(i.id));
    let tick = false;
    const spy = () => {
      tick = false;
      let k = -1;
      els.forEach((el, i) => { if (el && el.getBoundingClientRect().top < 150) k = i; });
      links.forEach((a, i) => a.classList.toggle("on", i === k));
      if (document.activeElement !== jump) jump.value = k >= 0 ? items[k].slug : "";
    };
    const on = () => { if (!tick) { tick = true; requestAnimationFrame(spy); } };
    window.addEventListener("scroll", on, { passive: true });
    spyOff = () => window.removeEventListener("scroll", on);
    spy();
  }
  // Player and game pages get the same menu from their own headings.
  function autoRail(base) {
    foldHowTo(main);
    const items = [];
    main.querySelectorAll("section.block").forEach((s) => {
      const h = s.querySelector(":scope > h2");
      if (!h) return;
      const title = s.dataset.title || headText(h), slug = slugOf(title);
      if (!slug || items.some((i) => i.slug === slug)) return;
      s.id = "sec-" + slug;
      items.push({ id: s.id, slug, title });
    });
    if (items.length >= 4) layoutWithRail(items, base);
  }
  function scrollToSec(id) {
    const go = () => {
      const el = document.getElementById("sec-" + id);
      if (!el) return false;
      if (el.tagName === "DETAILS") el.open = true;
      const part = el.closest("details.part");
      if (part) part.open = true;
      el.scrollIntoView();
      return true;
    };
    if (!go()) { window.scrollTo(0, 0); return; }
    // Charts above the target redraw once the page settles, which moves it; land on it again.
    requestAnimationFrame(() => requestAnimationFrame(go));
    setTimeout(go, 350);
  }

  // ---- Highlight one player everywhere ----------------------------------------------------------------
  let HL = "";
  try { HL = localStorage.getItem("hl") || ""; } catch (e) { /* storage blocked */ }
  const hlIn = (players) => (HL && players.some((p) => p.id === HL) ? HL : undefined);
  function applyHL() {
    let st = document.getElementById("hl-style");
    if (!st) { st = document.createElement("style"); st.id = "hl-style"; document.head.appendChild(st); }
    if (!P[HL] || !/^[\w-]+$/.test(HL)) HL = "";
    const q = HL ? `.who[data-pid="${HL}"]` : "";
    st.textContent = !q ? "" : `
      ${q} { outline: 1.5px solid var(--ink); outline-offset: 3px; border-radius: 3px; }
      table:not(.games-table):not(.matrix) tbody tr:has(> :nth-child(-n+2) ${q}) > * { background: var(--hl-row); }
      table.matrix tr:has(> th.rowh ${q}) > th.rowh, table.matrix th.colh:has(${q}) { background: var(--hl-row); }
      .fp-lab:has(${q}), .p-card:has(${q}), .hot-card:has(${q}) { background: var(--hl-row); }`;
    const sel = document.getElementById("hl-select"), link = document.getElementById("hl-link");
    sel.value = HL;
    link.hidden = !HL;
    if (HL) link.setAttribute("href", `#/player/${encodeURIComponent(HL)}`);
  }

  // ---- Sticky bar: which games are showing, highlight, section jump ---------------------------------------
  function updateBar() {
    document.getElementById("view-label").textContent = viewLabel(VIEW);
    document.getElementById("view-pill").classList.toggle("filtered", VIEW !== "all");
    closeViewPop();
  }
  function closeViewPop() {
    document.getElementById("view-pop").hidden = true;
    document.getElementById("view-pill").setAttribute("aria-expanded", "false");
  }
  function setupBar() {
    const pill = document.getElementById("view-pill"), pop = document.getElementById("view-pop");
    pill.addEventListener("click", () => {
      if (!pop.hidden) return closeViewPop();
      pop.innerHTML = filterBar() || `<p class="note">Only one kind of game is recorded so far.</p>`;
      pop.hidden = false;
      pill.setAttribute("aria-expanded", "true");
    });
    document.addEventListener("click", (e) => { if (!pop.hidden && !pop.contains(e.target) && !pill.contains(e.target)) closeViewPop(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !pop.hidden) { closeViewPop(); pill.focus(); } });
    const sel = document.getElementById("hl-select");
    sel.insertAdjacentHTML("beforeend", ROOT.views.all.players.filter((p) => p.games > 0).map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join(""));
    sel.addEventListener("change", () => {
      HL = sel.value;
      try { localStorage.setItem("hl", HL); } catch (e) { /* storage blocked */ }
      applyHL();
      route(true); // some charts dim the other players
    });
    const jump = document.getElementById("sec-jump");
    jump.addEventListener("change", () => { if (jump.value) location.hash = `${jump.dataset.base}/${jump.value}${viewQuery(VIEW)}`; jump.blur(); });
  }

  // ---- Search: pages, questions, players and games -----------------------------------------------------------
  function searchIndex() {
    const out = [];
    const add = (label, hint, href, extra, top) => out.push({ label, hint, href, top: !!top, low: label.toLowerCase(), text: `${label} ${hint} ${extra || ""}`.toLowerCase() });
    add("Leaderboard", "Page", "#/", "home ranking", true);
    add("Questions", "Page", "#/questions", "findings answers index", true);
    for (const t of TP.TOPICS) add(t.title, "Topic", "#/" + t.key, t.lede, true);
    add("Players", "Page", "#/players", "head to head", true);
    add("Head to head", "Players", "#/players/h2h", "matrix");
    add("Games", "Page", "#/games", "list dice", true);
    add("History", "Page", "history.html", "timeline story eras milestones", true);
    add("How it works", "Page", "#/about", "methods ranking about", true);
    for (const p of ROOT.views.all.players.filter((x) => x.games > 0)) add(p.name, "Player", `#/player/${encodeURIComponent(p.id)}`, (p.aliases || []).join(" "), true);
    for (const q of TP.questions(ctx())) add(q.q, `${TP.topic(q.topic).nav}: ${q.title}`, `#/${q.topic}/${q.id}`, q.a ? `${q.a.head || ""} ${q.a.text || ""}` : "");
    for (const g of ROOT.views.all.games) {
      const w = isGuest(g.winner) ? "a guest" : (P[g.winner] ? P[g.winner].name : g.winner);
      add(`Game ${g.number}, ${fmtDate(g.date)}`, `${w} won`, `#/game/${encodeURIComponent(g.id)}`, `${g.type_label} ${g.date} ${fmtDate(g.date, { month: "long", day: "numeric", year: "numeric" })}`);
    }
    return out;
  }
  // Pages inside this app keep the chosen view; the History page is its own file.
  const palHref = (i) => (i.href.startsWith("#") ? i.href + viewQuery(VIEW) : i.href);
  function setupSearch() {
    const pal = document.getElementById("pal"), input = document.getElementById("pal-in"), list = document.getElementById("pal-list");
    let items = [], shown = [], cur = 0, back = null;
    const mark = () => {
      [...list.children].forEach((li, i) => li.setAttribute("aria-selected", String(i === cur)));
      const li = list.children[cur];
      if (li) { input.setAttribute("aria-activedescendant", li.id); li.scrollIntoView({ block: "nearest" }); }
    };
    const render = () => {
      const q = input.value.trim().toLowerCase(), toks = q.split(/\s+/).filter(Boolean);
      const score = (i) => (i.low.startsWith(q) ? 0 : toks.every((t) => i.low.includes(t)) ? 1 : 2);
      shown = (toks.length ? items.filter((i) => toks.every((t) => i.text.includes(t))).sort((a, b) => score(a) - score(b)) : items.filter((i) => i.top)).slice(0, toks.length ? 12 : 20);
      cur = 0;
      list.innerHTML = shown.length
        ? shown.map((i, k) => `<li role="option" id="pal-o-${k}"><a data-keep href="${esc(palHref(i))}" tabindex="-1"><span>${esc(i.label)}</span><span class="pal-hint-r">${esc(i.hint)}</span></a></li>`).join("")
        : `<li><p class="pal-empty">Nothing matches.</p></li>`;
      mark();
    };
    const close = (refocus) => { pal.hidden = true; if (refocus && back && back.focus) back.focus(); };
    const open = () => {
      if (!ROOT) return;
      items = searchIndex();
      back = document.activeElement;
      pal.hidden = false;
      input.value = "";
      render();
      input.focus();
    };
    document.getElementById("search-btn").addEventListener("click", open);
    input.addEventListener("input", render);
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (shown.length) { cur = (cur + (e.key === "ArrowDown" ? 1 : shown.length - 1)) % shown.length; mark(); }
      } else if (e.key === "Enter" && shown[cur]) {
        e.preventDefault();
        close(false);
        const h = palHref(shown[cur]);
        if (h.startsWith("#")) location.hash = h.slice(1); else location.href = h;
      }
    });
    list.addEventListener("click", (e) => { if (e.target.closest("a")) close(false); });
    pal.addEventListener("mousedown", (e) => { if (e.target === pal) close(true); });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !pal.hidden) { close(true); return; }
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((e.target && e.target.tagName) || "") || (e.target && e.target.isContentEditable);
      if (((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey)) || (e.key === "/" && !typing && !e.metaKey && !e.ctrlKey && !e.altKey)) {
        e.preventDefault();
        if (pal.hidden) open(); else input.focus();
      }
    });
  }

  // ---- Router -------------------------------------------------------------------
  // #/<page>[/<id>][/<section>]?view=..&players=..  A link to another section of the page already on screen
  // only scrolls; everything else renders the page again.
  let RENDERED = null;
  const NAV_KEYS = { "": "leaderboard", day: "leaderboard", questions: "questions", players: "players", player: "players", h2h: "players",
    games: "games", game: "games", about: "about" };
  function route(force) {
    Tip.hide();
    const [path, query] = location.hash.replace(/^#\/?/, "").split("?");
    const qs = new URLSearchParams(query || "");
    const want = viewKey(qs.get("view") || "all", qs.get("players"));
    const view = ROOT.views[want] ? want : ROOT.views[qs.get("view")] ? qs.get("view") : "all";
    const parts = (path || "").split("/").map(decodeURIComponent);
    const page = parts[0] || "";
    if (TP.REDIRECTS[page]) { location.replace(`#/${TP.REDIRECTS[page]}${query ? "?" + query : ""}`); return; }
    const topic = TP.topic(page);
    // How many path parts pick the page; one more picks a section on it.
    const n = topic || page === "players" ? 1 : page === "player" || page === "game" ? 2 : parts.length;
    const sec = page === "h2h" ? "h2h" : parts[n];
    const key = `${page === "h2h" ? "players" : parts.slice(0, n).join("/")}|${view}`;
    PAGE_PATH = path || "";
    if (force !== true && key === RENDERED) {
      if (sec) scrollToSec(sec); else window.scrollTo(0, 0);
      scopeLinks(document);
      return;
    }
    const keepY = force === true ? window.scrollY : null;
    setView(view);
    if (spyOff) { spyOff(); spyOff = null; }
    document.body.classList.remove("has-rail");
    const navKey = topic ? page : NAV_KEYS[page] || (Pages[page] && page);
    document.querySelectorAll("[data-nav]").forEach((a) => {
      if (a.dataset.nav === navKey) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    document.body.classList.toggle("is-home", page === "");
    if (page === "") leaderboard();
    else if (topic) topicPage(page);
    else if (page === "questions") questionsPage();
    else if (page === "players" || page === "h2h") playersPage();
    else if (page === "player") playerPage(parts[1]);
    else if (page === "day") dayPage(parts[1]);
    else if (page === "games") gamesPage();
    else if (page === "game") gamePage(parts[1]);
    else if (page === "about") { aboutPage(); drawAboutCharts(); }
    else if (Pages[page]) Pages[page].render(ctx(), parts.slice(1));
    else notFound("That page doesn't exist.");
    scopeLinks(document);
    const title = S.site.title || "Catan Stats";
    const h1 = main.querySelector("h1");
    document.title = h1 && page !== "" ? `${h1.textContent} | ${title}` : title;
    RENDERED = key;
    updateBar();
    const cur = document.querySelector('.nav [aria-current="page"]');
    if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: "nearest", inline: "nearest" });
    if (keepY !== null) window.scrollTo(0, keepY);
    else if (sec) scrollToSec(sec);
    else window.scrollTo(0, 0);
  }

  function setView(key) {
    VIEW = key;
    S = Object.assign({}, ROOT.views[key], { ranking: ROOT.ranking, site: ROOT.site, generated_at: ROOT.generated_at });
    P = Object.fromEntries(ROOT.views.all.players.map((p) => [p.id, p])); // every known player
    for (const p of S.players) P[p.id] = p;                              // stats from this view
  }

  // Keep the chosen filter as people click around: add ?view= and ?players= to every internal link.
  function scopeLinks(root) {
    const q = viewQuery(VIEW);
    root.querySelectorAll('a[href^="#/"]').forEach((a) => {
      if (a.hasAttribute("data-keep")) return;
      a.setAttribute("href", a.getAttribute("href").split("?")[0] + q);
    });
  }

  function setupTheme() {
    const btn = document.getElementById("theme-btn");
    btn.addEventListener("click", () => {
      const root = document.documentElement;
      const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
      root.dataset.theme = dark ? "light" : "dark";
      try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
      route(true); // charts read CSS variables at draw time
    });
  }

  async function init() {
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
    drawMasthead();
    document.getElementById("built-at").textContent = `Updated ${new Date(S.generated_at).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })}.`;
    setupBar();
    setupSearch();
    applyHL();
    window.addEventListener("hashchange", () => route());
    route();
  }
  init();
})();
