/* Player classes (stats proposal 1.4) and the Phase 7 extras: spending and trading profile, badges,
   comeback gallery, first-to-c conversion, draft-order grid and pick percentile, Kaplan-Meier timings,
   dev draw luck. Data: stats.json "classes" (all games) and views[view].classes. */
(function () {
  "use strict";
  // Styles live in classes.css; add the link here if index.html does not have it yet.
  if (!document.querySelector('link[href="classes.css"]')) {
    const l = document.createElement("link");
    l.rel = "stylesheet"; l.href = "classes.css";
    document.head.appendChild(l);
  }

  Object.assign(window.METHODS, {
    cls_profile: `<p><b>Spending mix.</b> For each game the decoder adds up the cards each seat paid for purchases (free Road Building pieces and setup pieces left out): N = dev cards + cities + settlements + roads + ships. Three shares: dev cards, cities, and expansion (settlements + paid roads + paid ships). They add to 1, so only two are free (2 df).</p>
      <p><b>Against the table.</b> A Mantel-Haenszel risk difference stratified by game, against everyone else at the same table (guests and bots included): RD = Σ w (y<sub>i</sub>/N<sub>i</sub> − y<sub>rest</sub>/N<sub>rest</sub>) / Σ w, w = N<sub>i</sub>N<sub>rest</sub>/(N<sub>i</sub> + N<sub>rest</sub>). Shown in percentage points. <b>Player trades</b> use the Mantel-Haenszel rate ratio of player-trade cards (each seat one unit of exposure) and <b>bank reliance</b> the risk difference in the share of received cards that came from the bank or a port; received cards are dice, player trades, bank, steals, monopoly and free picks (Year of Plenty, gold at setup, fog; gold from dice is already in dice).</p>
      <p><b>Marks.</b> Hollow ring: the raw estimate. Filled dot: the shrunk estimate θ = μ + B(y − μ), B = τ²/(τ² + s²), with τ² by REML over the players shown and s the game-cluster bootstrap SE (2,000 draws). The trade axis is shrunk on the log scale. Whisker: 95% percentile interval of θ from the same bootstrap, re-estimating every player and re-fitting τ² in each draw. Small tick: the estimate from the player's losses only. When τ² is 0 every player shrinks to the table mean.</p>
      <p>Views under 30 games keep the all-games τ² and say so. Players need 10 games in the view. Navigator (Seafarers views only, no badge): ships as a share of settlement, road and ship spending, same risk difference.</p>`,
    cls_badges: `<p><b>Style badges, all games only.</b> Five axes were fixed in advance: Scientist (dev share), Empire Builder (city share), Expander (settlement, road and ship share), Ambassador (player-trade rate) and Merchant (bank reliance).</p>
      <p>An axis can award badges only if the players differ beyond noise: REML τ² &gt; 0 and Cochran's Q p &lt; 0.10. A player earns the badge when (1) the 95% bootstrap interval of their shrunk estimate lies above the table value (0 points, or a ratio of 1), (2) the estimate from their losses alone points the same way, so the lean is not just what winning looks like, and (3) they have at least 15 games. At most 2 badges, keeping the largest θ divided by its bootstrap SD. Otherwise: "No clear lean yet".</p>
      <p><b>Stability</b>: the share of the 2,000 game-cluster resamples in which the same rule holds, with the shrinkage posterior interval θ ± 1.96 √B s in place of the bootstrap interval: the gate passes in that resample, the interval is above 0 and the losses-only estimate is positive.</p>
      <p>The win recipe beside the badges says where a player's winning points came from (see its own note). Badges describe style; the recipe describes how wins happened.</p>`,
    cls_comeback: `<p><b>Board VP</b> is VP minus VP cards still held: what the table could see (TwoSheep shows public VP). For each game, t* is the first moment (state after a roll or at the end of a turn) when anyone's board VP reaches G − 3, where G is the VP target. The winner's deficit there is gap = (leader's board VP − winner's board VP), and d = gap / G.</p>
      <p>A game enters the gallery at d ≥ 0.2; because that line is arbitrary the counts are also shown at absolute gaps of 2, 3 and 4 VP. The record is the largest d. The last column is how many VP cards the winner was still holding when the game ended, which is part of why a comeback can look sudden. Descriptive only, no model.</p>`,
    cls_first: `<p>τ<sub>c</sub> is the first state where anyone's board VP reaches 2 + c (G − 2), for c = 0.5 and 0.75; the seats at or above that line then are "first", sharing it 1/k when k reach it together. Games where nobody reaches it on board VP before the end are left out and counted.</p>
      <p><b>Group</b>: the share of games won by whoever got there first, with a 95% Wilson interval, against the mean of 1/n (n = seats, bots included). <b>Per player</b> (10+ games): conversion = P(win | first) and comeback = P(win | not first), counting shared firsts fractionally, each with a 95% Wilson interval and compared with the mean of 1/n over that player's own games. No tests.</p>`,
    cls_draft: `<p>At each opening settlement, L<sub>t</sub> is the set of corners still open on the start region (unoccupied, distance rule), and b<sub>t</sub> is the most pips (number dots touching the corner; gold at face value, desert 0) available in L<sub>t</sub>. Each cell is the mean b<sub>t</sub> for that seat and settlement over 3 or 4 seat games; the small line is the mean pips actually chosen.</p>
      <p><b>Start region.</b> The decoder lists every open corner that touches non-sea land, islands included, so it is restricted here. The land is read from the robber logs (every 7 or knight lists every land hex the robber could go to) and split into islands by hex adjacency. Base: the whole board. New Shores: the main island. Through the Desert: the mainland; the desert separates it from the land beyond, which counts as islands. This reproduces the decoder's own island map in every decoded game, and every opening was on the region. Four Islands and Fog Islands are left out because their start region can only be guessed from where people opened.</p>`,
    cls_pick: `<p>The percentile of the chosen corner among L<sub>t</sub> by pips, by mid-rank: (corners with fewer pips + half of those tied) / |L<sub>t</sub>|. 1.0 would be a unique best spot; picking among tied best spots gives a bit less. Pooled over every opening settlement in base, New Shores and Through the Desert games, all seat counts.</p>
      <p>Per player: mean percentile with a 95% t interval over their picks, and how often the top pip spot was taken (chosen pips = b<sub>t</sub>) with a 95% Wilson interval. Pips are not everything (resource mix, ports and the second settlement's partner all matter), so a lower share is a different priority, not a mistake.</p>`,
    cls_km: `<p>Kaplan-Meier curves in the player's own turns (turn 1 = their first roll). <b>First dev card</b>: the own turn of the first purchase; seats that never bought are censored at their last turn. <b>First city</b> (the Rusher column): the own turn of the first city. <b>Knight hold time</b> (Ambusher): own turns from buying a knight to playing it, matching plays to the oldest unplayed knight first; knights never played are censored at the end. Guests and bots count in the pooled curves.</p>
      <p>Bands are 95% Greenwood intervals on the log(−log) scale. Curves stop where fewer than 5 are still at risk. Knight hold time needs at least 20 knights bought in the view (per player too). Medians: the first turn the curve reaches 50%; their intervals are where the band's edges cross 50% ("not reached" when they never do).</p>`,
    cls_devluck: `<p>The dev deck order is fixed when the game starts, but nobody knows it, so every purchase is a draw from what is left. For each purchase, p<sub>t</sub> = VP cards (or knights) still in the deck ÷ cards still in the deck, knowing every earlier purchase. O = cards of that kind drawn, E = Σ p<sub>t</sub>, and O − E has variance Σ p<sub>t</sub>(1 − p<sub>t</sub>) (a martingale), giving the 95% interval O − E ± 1.96 √V. In cards.</p>
      <p><b>The deck.</b> The starting composition comes from each replay: 25 cards (14 knights, 5 VP, 2 each of the rest) or, with the 5 to 6 player extension, 34 (20, 5, 3, 3, 3). Every purchase in every game counts.</p>`,
    cls_columns: `<p>Per player, 10+ games in the view. <b>Rusher</b>: Kaplan-Meier median own turns to the first city. <b>First dev card</b>: the same for the first dev card purchase. <b>Ambusher</b>: median own turns a knight is held before it is played (20+ knights bought). Intervals: where the 95% log(−log) band crosses 50%. Profile columns only, no badges (axes were fixed in advance).</p>
      <p><b>Hoarder</b>: the share of a player's 7-discards that were avoidable. For each discard, look at the cards in their hand at the end of their previous turn (or their previous build phase in a 5 to 6 player game): a discard was avoidable if they could then afford a city (2 grain, 3 ore) while owning a settlement and fewer than 4 cities, or a dev card (wool, grain, ore) while the deck still had cards. Settlements and cities owned are counted from the replay's building log; cards left in the deck are the starting deck minus purchases so far. 95% Wilson interval, compared with the share over every discard in the view (guests and bots included). It ignores what else the cards were being saved for, such as a settlement spot or a trade.</p>`,
  });

  const AXIS_SHORT = { dev: "Dev cards", city: "Cities", expansion: "Expansion", trade: "Player trades", bank: "Bank reliance", navigator: "Ships (Navigator)" };
  const AXIS_UNIT = { trade: "ratio" };
  // What each axis measures, in plain words: a short caption under the chart title, and the full text on hover.
  const AXIS_DESC = {
    dev: ["Share of spending on dev cards",
      "Of all the cards a player paid for purchases, the share spent on dev cards, compared with the rest of the same tables. +5 means 5 percentage points more of their spending went to dev cards than the others' did in the same games."],
    city: ["Share of spending on cities",
      "Of all the cards a player paid for purchases, the share spent upgrading settlements to cities, compared with the rest of the same tables, in percentage points."],
    expansion: ["Share of spending on settlements, roads and ships",
      "Of all the cards a player paid for purchases, the share spent on new settlements, roads and ships (free Road Building pieces don't count), compared with the rest of the same tables, in percentage points. Dev cards, cities and expansion add to 100%, so leaning one way means leaning away from the others."],
    trade: ["How much they trade with other players",
      "Cards moved in trades with other players (given plus received), as a rate against the rest of the same tables. 1.20× means 20% more trading than the table, 0.80× means 20% less."],
    bank: ["Share of cards received from the bank",
      "Of all the cards a player received (dice, trades, bank and ports, steals, monopoly, free picks), the share that came from bank or port trades, compared with the rest of the same tables, in percentage points."],
    navigator: ["Share of expansion spent on ships",
      "Of the cards spent on settlements, roads and ships, the share that went on ships, compared with the rest of the same tables, in percentage points. Seafarers views only; shown, never a badge."],
  };
  const axisTitle = (ctx, a) => `<span class="cls-ax" tabindex="0" data-tip="${ctx.esc(`<b>${AXIS_SHORT[a]}</b><br>${AXIS_DESC[a][1]}`)}">${AXIS_SHORT[a]}</span>`;
  const C = (ctx) => (ctx.S && ctx.S.classes) || null;
  const CA = (ctx) => (ctx.ROOT && ctx.ROOT.classes) || null;
  const order = (ctx) => ctx.S.players.filter((p) => p.games > 0).map((p) => p.id);
  const isAnon = (pid) => /^(guest|bot)-/.test(String(pid));
  const nameOf = (ctx, pid) => (ctx.P[pid] && !isAnon(pid) ? ctx.esc(ctx.P[pid].name) : String(pid).startsWith("bot-") ? "Bot" : "Guest");
  const chip = (ctx, pid) => (isAnon(pid) ? `<span class="who guest"><span class="hex" aria-hidden="true"></span><span>${nameOf(ctx, pid)}</span></span>` : ctx.who(pid));
  const gameById = (ctx, gid) => (ctx.ROOT.views.all.games || []).find((g) => g.id === gid);
  const fin = (v) => v !== null && v !== undefined && Number.isFinite(+v);
  // Display value for an axis: percentage points, or a ratio for the trade axis (stored on the log scale).
  const disp = (axis, v) => (!fin(v) ? null : axis === "trade" ? Math.exp(v) : v * 100);
  // Signed number that never prints "−0.0".
  const sgn = (ctx, x, d = 1) => (!fin(x) ? "n/a" : Math.abs(x) < 0.5 * Math.pow(10, -d) ? (0).toFixed(d) : ctx.fmtSigned(x, d));
  const fmtAxis = (ctx, axis, v) => (!fin(v) ? "n/a" : axis === "trade" ? ctx.num(Math.exp(v), 2) + "×" : sgn(ctx, v * 100, 1));
  const cnt = (ctx, x) => (Number.isInteger(+x) ? String(x) : ctx.num(x, 1));
  // A stat tile whose info button stays on the same line as the label's last word.
  const tile = (ctx, value, label, sub, key, title) => ctx.Charts.statTile({ value, label, sub, info: key && ctx.M[key] ? { id: uid("i"), title, html: ctx.M[key] } : undefined });
  const ival = (ctx, axis, ci) => (ci && fin(ci[0]) && fin(ci[1]) ? `${fmtAxis(ctx, axis, ci[0])} to ${fmtAxis(ctx, axis, ci[1])}` : "n/a");
  const turns = (v) => (fin(v) ? String(v) : "not reached");
  const hoardCell = (ctx, h) => (!h || !fin(h.share) ? `<span class="sub">no discards</span>` : `${ctx.pct(h.share)} <span class="sub">${h.avoidable} of ${h.checked} (${ctx.pct(h.ci[0])} to ${ctx.pct(h.ci[1])})</span>`);
  const medCell = (ctx, m) => (!m || !fin(m.median) ? `<span class="sub">n/a</span>` : `${m.median} <span class="sub">(${turns(m.ci && m.ci[0])} to ${turns(m.ci && m.ci[1])})</span>`);
  let seq = 0;
  const uid = (p) => `cls-${p}-${++seq}`;

  // ---------------------------------------------------------------------------------------------
  // Play style page: profile matrix, class columns and Kaplan-Meier curves
  // ---------------------------------------------------------------------------------------------
  function profileAxes(c) {
    const prof = c && c.profile;
    if (!prof) return [];
    return ["dev", "city", "expansion", "trade", "bank", "navigator"].filter((a) => prof.axes[a] && Object.keys(prof.axes[a].players || {}).length);
  }

  function styleHtml(ctx) {
    const c = C(ctx);
    if (!c) return "";
    const axes = profileAxes(c);
    const ids = {};
    let html = `<section class="block">
        <h2>Spending and trading mix ${ctx.info("cls_profile", "Spending and trading profile")}</h2>
        <p class="note">What each player leans on compared with the rest of the same tables. Spending shares are of cards paid for purchases, in percentage points against the table; the three shares add to 100%, so a lean toward one is a lean away from the others. Dot: shrunk estimate with its 95% interval; ring: raw; tick: losses only.${c.profile && c.profile.tau2_source === "all games" ? " This view has under 30 games, so the amount of shrinkage comes from all games." : ""}</p>`;
    if (!axes.length) {
      html += ctx.guardNote(0, 10) + `</section>`;
    } else {
      html += `<div class="cls-grid">${axes.map((a) => { ids[a] = uid("pf-" + a); return `<div class="panel cls-cell"><h3>${axisTitle(ctx, a)}</h3><p class="cls-cap">${AXIS_DESC[a][0]}</p><div class="chart" id="${ids[a]}"></div></div>`; }).join("")}</div>
        <div id="cls-pf-legend"></div>
        ${profileTable(ctx, c, axes)}
      </section>`;
    }
    const km = c.km || {};
    const cols = km.players || {};
    const pl = order(ctx).filter((p) => cols[p]);
    const hdAll = c.hoarder || null;
    const hd = (hdAll && hdAll.players) || {};
    ids.kmDev = uid("km-dev"); ids.kmCity = uid("km-city"); ids.kmKn = uid("km-kn");
    html += `<section class="block">
        <h2>Timing columns ${ctx.info("cls_columns", "Class columns")}</h2>
        <p class="note">Median own turns until each player's first city (Rusher) and first dev card, how long they hold a knight before playing it (Ambusher), and how many of their 7-discards were avoidable (Hoarder). 95% intervals in brackets.</p>
        ${pl.length ? `<div class="panel table-wrap"><table><thead><tr><th>Player</th><th class="num">Games</th><th class="num">Rusher: first city</th><th class="num">First dev card</th><th class="num">Ambusher: knight held</th><th class="num">Hoarder: avoidable discards</th></tr></thead><tbody>
          ${pl.map((p) => { const r = cols[p]; return `<tr><td>${ctx.who(p)}</td><td class="num">${r.games}</td><td class="num">${medCell(ctx, r.city)}</td><td class="num">${medCell(ctx, r.dev)}</td><td class="num">${r.knight && fin(r.knight.median) ? medCell(ctx, r.knight) : `<span class="sub">${r.knight ? r.knight.bought : 0} knights, needs 20</span>`}</td><td class="num">${hoardCell(ctx, hd[p])}</td></tr>`; }).join("")}
        </tbody></table></div>` : ctx.guardNote(0, 10)}
        ${hdAll && fin(hdAll.share) ? `<p class="note">Hoarder: share of 7-discards that could have been avoided by buying a city or a dev card at the end of the player's previous turn. Across everyone in this view, ${hdAll.avoidable} of ${hdAll.checked} discards (${ctx.pct(hdAll.share)}).</p>` : ""}
      </section>
      <section class="block">
        <h2>How long until ${ctx.info("cls_km", "Kaplan-Meier timings")}</h2>
        <p class="note">Percent of player-games still waiting, by the player's own turn, everyone pooled. Bands are 95%; curves stop where fewer than 5 are still waiting.</p>
        <div class="three-col">
          <div><h3>First dev card <span class="sub">${km.dev ? `${km.dev.events} of ${km.dev.n}` : ""}</span></h3><div class="panel" style="margin-top:8px"><div class="chart" id="${ids.kmDev}"></div></div></div>
          <div><h3>First city <span class="sub">${km.city ? `${km.city.events} of ${km.city.n}` : ""}</span></h3><div class="panel" style="margin-top:8px"><div class="chart" id="${ids.kmCity}"></div></div></div>
          <div><h3>Knight held <span class="sub">${km.knight ? `${km.knight.bought} knights` : ""}</span></h3><div class="panel" style="margin-top:8px">${km.knight && km.knight.shown ? `<div class="chart" id="${ids.kmKn}"></div>` : `<p class="empty" style="margin:12px">Needs 20 knights bought in this view (has ${km.knight ? km.knight.bought : 0}).</p>`}</div></div>
        </div>
        ${kmTable(ctx, km)}
      </section>`;
    styleHtml.ids = ids;
    return html;
  }

  function profileTable(ctx, c, axes) {
    const prof = c.profile;
    const rows = [];
    for (const p of order(ctx)) {
      if (!prof.players[p]) continue;
      for (const a of axes) {
        const r = prof.axes[a].players[p];
        if (!r) continue;
        rows.push([chip(ctx, p), axisTitle(ctx, a), fmtAxis(ctx, a, r.raw), ival(ctx, a, r.raw_ci), fin(r.theta) ? fmtAxis(ctx, a, r.theta) : "n/a",
          ival(ctx, a, r.theta_ci), fmtAxis(ctx, a, r.loss), String(prof.players[p])]);
      }
    }
    const fits = axes.map((a) => { const x = prof.axes[a]; return fin(x.tau2) ? `${AXIS_SHORT[a]}: τ² ${x.tau2_source === "all games" ? "(all games) " : ""}${a === "trade" ? ctx.num(x.tau2, 4) + " (log scale)" : ctx.num(x.tau2 * 1e4, 1) + " pts²"}${fin(x.p) ? `, Q = ${ctx.num(x.Q, 1)} on ${x.df} df, p = ${ctx.num(x.p, 3)}` : ""}` : ""; }).filter(Boolean);
    return ctx.tableView([{ label: "Player" }, { label: "Axis" }, { label: "Raw", num: true }, { label: "Raw 95%", num: true }, { label: "Shrunk", num: true },
      { label: "Shrunk 95%", num: true }, { label: "Losses only", num: true }, { label: "Games", num: true }], rows) +
      (fits.length ? `<p class="note">Between-player spread: ${fits.join("; ")}.</p>` : "");
  }

  function kmTable(ctx, km) {
    const rows = [];
    for (const [k, label] of [["dev", "First dev card"], ["city", "First city"], ["knight", "Knight held"]]) {
      const x = km[k];
      if (!x || !x.t) continue;
      x.t.forEach((t, i) => rows.push([label, t, x.risk[i], ctx.pct(x.s[i], 1), fin(x.lo[i]) ? `${ctx.pct(x.lo[i], 1)} to ${ctx.pct(x.hi[i], 1)}` : "n/a"]));
    }
    return ctx.tableView([{ label: "Curve" }, { label: "Own turn", num: true }, { label: "At risk", num: true }, { label: "Still waiting", num: true }, { label: "95% interval", num: true }], rows);
  }

  function drawKM(ctx, el, x, name) {
    if (!el || !x || !x.t || !x.t.length) { if (el) el.innerHTML = `<p class="empty">No events in this view.</p>`; return; }
    const pts = [{ x: 0, y: 100, tip: "100%" }].concat(x.t.map((t, i) => ({ x: t, y: x.s[i] * 100, tip: `${ctx.pct(x.s[i], 0)} (${x.risk[i]} at risk)` })));
    const band = [{ x: 0, lo: 100, hi: 100 }].concat(x.t.map((t, i) => ({ x: t, lo: fin(x.lo[i]) ? x.lo[i] * 100 : null, hi: fin(x.hi[i]) ? x.hi[i] * 100 : null })));
    ctx.Charts.stepChart(el, {
      series: [{ id: "km", name, color: "var(--data)", points: pts }], bands: [{ seriesId: "km", points: band }],
      height: 200, directLabels: false, stepLabel: "own turns", yRef: 50, yFormat: (y) => Math.round(y) + "%",
      xLabel: (t) => `<b>Own turn ${t}</b>`, ariaLabel: `${name}: share still waiting by own turn`,
      markers: fin(x.median) ? [{ x: x.median, kind: "rule", label: `median ${x.median}` }] : [],
    });
  }

  function styleDraw(ctx) {
    const c = C(ctx);
    if (!c) return;
    const ids = styleHtml.ids || {};
    const axes = profileAxes(c);
    const prof = c.profile;
    axes.forEach((a, k) => {
      const el = document.getElementById(ids[a]);
      if (!el) return;
      const rows = order(ctx).filter((p) => prof.axes[a].players[p]).map((p) => {
        const r = prof.axes[a].players[p];
        const shrunk = fin(r.theta);
        const ci = shrunk ? r.theta_ci : r.raw_ci;
        return { label: nameOf(ctx, p), color: ctx.color(p), est: disp(a, shrunk ? r.theta : r.raw), lo: disp(a, ci && ci[0]), hi: disp(a, ci && ci[1]),
          hollow: shrunk ? disp(a, r.raw) : undefined, small: disp(a, r.loss),
          tip: `<b>${nameOf(ctx, p)}</b>, ${AXIS_SHORT[a]}<br>Shrunk ${fmtAxis(ctx, a, r.theta)} (${ival(ctx, a, r.theta_ci)})<br>Raw ${fmtAxis(ctx, a, r.raw)} (${ival(ctx, a, r.raw_ci)})<br>Losses only ${fmtAxis(ctx, a, r.loss)}<br>${prof.players[p]} games, ${prof.losses[p]} losses` };
      });
      ctx.Charts.forestPlot(el, {
        rows, ref: a === "trade" ? 1 : 0, log: a === "trade", legend: false, rowHeight: 28,
        format: a === "trade" ? (v) => ctx.num(v, 2) + "×" : (v) => ctx.fmtSigned(v, 1),
        xTitle: a === "trade" ? "Rate vs the table (1× = same as the table)" : "Percentage points vs the table",
        names: { est: "Shrunk", hollow: "Raw", small: "Losses only" }, ariaLabel: `${AXIS_SHORT[a]} against the rest of the table`,
      });
    });
    const lg = document.getElementById("cls-pf-legend");
    if (lg) lg.innerHTML = `<ul class="legend" style="margin-top:10px"><li><span class="sw dot" style="--c:var(--ink-2)"></span>Shrunk estimate</li><li><span class="sw ring" style="--c:var(--ink-2)"></span>Raw</li><li><span class="sw vtick"></span>Losses only</li><li><span class="sw" style="--c:var(--ink-2)"></span>95% interval</li></ul>`;
    const km = c.km || {};
    drawKM(ctx, document.getElementById(ids.kmDev), km.dev, "First dev card");
    drawKM(ctx, document.getElementById(ids.kmCity), km.city, "First city");
    if (km.knight && km.knight.shown) drawKM(ctx, document.getElementById(ids.kmKn), km.knight, "Knight held");
  }

  // ---------------------------------------------------------------------------------------------
  // Player page: badge header and the player's rows
  // ---------------------------------------------------------------------------------------------
  function badgeBlock(ctx, pid) {
    const ca = CA(ctx);
    const b = ca && ca.badges && ca.badges[pid];
    const axes = Object.fromEntries(((ca && ca.axes) || []).map((a) => [a.key, a]));
    const p = ctx.P[pid];
    const recipe = ((ctx.ROOT.views.all.insights || {}).win_recipe || {})[pid];
    let body;
    if (!b) body = `<p class="empty">Badges need 15 games and are given from all games.</p>`;
    else if (!b.eligible) body = `<p class="empty">Badges need 15 games (has ${b.games}).</p>`;
    else if (!b.badges.length) body = `<p class="cls-lean">No clear lean yet <span class="sub">(${b.games} games)</span></p>`;
    else {
      body = `<div class="cls-badges">${b.badges.map((x) => `<div class="cls-badge"><div class="cls-badge-name">${ctx.esc(x.name)}</div>
        <div class="sub">${ctx.esc((axes[x.axis] || {}).label || x.axis)}: ${fmtAxis(ctx, x.axis, x.theta)}${x.axis === "trade" ? "" : " pts"} (95% ${ival(ctx, x.axis, x.ci)}); losses only ${fmtAxis(ctx, x.axis, x.loss)}</div>
        <div class="sub">Holds in ${ctx.pct(x.stability, 0)} of resamples</div></div>`).join("")}</div>`;
    }
    const rec = recipe ? `<div class="cls-recipe"><div class="sub">Where winning points came from ${ctx.info("recipe", "Win recipe")}</div>
        <div class="chipline">${[["buildings", "Buildings"], ["development", "Development"], ["bonuses", "Bonuses"]].map(([k, l]) => `<span class="mini">${l} ${ctx.pct(recipe[k].share)} <b>${sgn(ctx, recipe[k].tilt * 100, 0)}</b></span>`).join("")}</div>
        <div class="sub">over ${recipe.wins} wins; tilt in points vs comparable wins</div></div>`
      : `<div class="cls-recipe"><div class="sub">Win recipe needs 10 wins${p ? ` (${ctx.esc(p.name)} has ${(ctx.ROOT.views.all.players.find((x) => x.id === pid) || {}).wins || 0})` : ""}.</div></div>`;
    return `<div class="panel cls-head"><div><div class="sub">Style badges, all games ${ctx.info("cls_badges", "Badge rule")}</div>${body}</div>${rec}</div>`;
  }

  function playerHtml(ctx, pid) {
    const c = C(ctx);
    const ca = CA(ctx);
    if (!c || !ca) return "";
    const prof = c.profile;
    const rows = [];
    if (prof && prof.players[pid]) {
      for (const a of profileAxes(c)) {
        const r = prof.axes[a].players[pid];
        if (r) rows.push(`<tr><td>${AXIS_SHORT[a]}</td><td class="num">${fmtAxis(ctx, a, r.raw)}</td><td class="num"><b>${fin(r.theta) ? fmtAxis(ctx, a, r.theta) : "n/a"}</b> <span class="sub">(${ival(ctx, a, r.theta_ci)})</span></td><td class="num">${fmtAxis(ctx, a, r.loss)}</td></tr>`);
      }
    }
    const col = ((c.km || {}).players || {})[pid];
    const pick = ((c.draft || {}).players || {})[pid];
    const f75 = ((c.first_to || {})["0.75"] || {}).players || {};
    const ft = f75[pid];
    const dl = ((c.dev_luck || {}).players || {})[pid];
    const tiles = [];
    if (col) {
      tiles.push(tile(ctx, fin(col.city.median) ? col.city.median : "n/a", "Rusher: own turns to first city", `95% ${turns(col.city.ci[0])} to ${turns(col.city.ci[1])}; first dev card ${fin(col.dev.median) ? col.dev.median : "n/a"}`, "cls_columns", "Class columns"));
      tiles.push(tile(ctx, col.knight && fin(col.knight.median) ? col.knight.median : "n/a", "Ambusher: own turns a knight is held", `${col.knight && fin(col.knight.median) ? `95% ${turns(col.knight.ci[0])} to ${turns(col.knight.ci[1])}, ` : "needs 20 knights, "}${col.knight ? col.knight.bought : 0} knights bought`, "cls_km", "Kaplan-Meier timings"));
    }
    const hd = ((c.hoarder || {}).players || {})[pid];
    if (hd && fin(hd.share)) tiles.push(tile(ctx, ctx.pct(hd.share), "Hoarder: avoidable 7-discards", `${hd.avoidable} of ${hd.checked} discards (95% ${ctx.pct(hd.ci[0])} to ${ctx.pct(hd.ci[1])}); everyone ${ctx.pct(c.hoarder.share)}`, "cls_columns", "Class columns"));
    if (pick) tiles.push(tile(ctx, ctx.pct(pick.top), "How often the top pip spot was taken", `${pick.picks} opening picks; mean percentile ${ctx.num(pick.mean_pct * 100, 0)}`, "cls_pick", "Pick percentile"));
    if (ft && fin(ft.conv)) tiles.push(tile(ctx, ctx.pct(ft.conv), "Won when first to 75% of the way", `of ${cnt(ctx, ft.first)} games; ${ctx.pct(ft.comeback)} when not first; fair share ${ctx.pct(ft.base)}`, "cls_first", "First-to-c conversion"));
    if (dl) tiles.push(tile(ctx, sgn(ctx, dl.vp.diff, 1), "VP cards drawn vs expected", `${dl.vp.O} drawn, ${ctx.num(dl.vp.E, 1)} expected in ${dl.buys} buys; knights ${sgn(ctx, dl.knight.diff, 1)}`, "cls_devluck", "Dev draw luck"));
    return `<section class="block">
        <h2>Style</h2>
        <p class="note">How ${ctx.esc((ctx.P[pid] || {}).name || pid)} spends and trades compared with the rest of the same tables, and what that adds up to.</p>
        ${badgeBlock(ctx, pid)}
        ${rows.length ? `<div class="panel table-wrap" style="margin-top:12px"><table><thead><tr><th>Against the table ${ctx.info("cls_profile", "Spending and trading profile")}</th><th class="num">Raw</th><th class="num">Shrunk (95%)</th><th class="num">Losses only</th></tr></thead><tbody>${rows.join("")}</tbody></table></div>
          <p class="note">Spending shares in percentage points against the table; player trades as a rate ratio. ${VIEWNOTE(ctx)}</p>` : ""}
        ${tiles.length ? `<div class="tiles">${tiles.join("")}</div>` : ""}
      </section>`;
  }
  const VIEWNOTE = (ctx) => (ctx.VIEW === "all" ? "" : "Rows use this view's games; badges always use all games.");

  // ---------------------------------------------------------------------------------------------
  // Findings: comebacks, first-to-c, draft grid and pick percentile, dev draw luck
  // ---------------------------------------------------------------------------------------------
  function findingsHtml(ctx) {
    const c = C(ctx), ca = CA(ctx);
    if (!c || !ca) return "";
    const ids = (findingsHtml.ids = {});
    const cb = c.comebacks || {};
    const G = ca.games || {};
    const games = (cb.gallery || []).map((id) => ({ id, r: G[id], g: gameById(ctx, id) })).filter((x) => x.r && x.g);
    const rec = (cb.record || []).map((id) => ({ id, r: G[id], g: gameById(ctx, id) })).filter((x) => x.r && x.g);
    const thr = [["d20", "d ≥ 0.2"], ["gap2", "2+ VP behind"], ["gap3", "3+ VP behind"], ["gap4", "4+ VP behind"]];
    let html = `<section class="block">
        <h2>Comebacks ${ctx.info("cls_comeback", "Comeback gallery")}</h2>
        <p class="note">Games the winner won from behind. When anyone first reached 3 VP short of the target on the board (t*), how far back was the eventual winner? Board VP leaves out VP cards still in hand, so it is what the table could see.</p>
        <div class="tiles">${thr.map(([k, l]) => `<div class="tile"><div class="v">${(cb.counts || {})[k] || 0}</div><div class="k">${l} at t*</div><div class="s">of ${cb.with_t_star || 0} games</div></div>`).join("")}
          ${rec.length ? `<div class="tile"><div class="v">${rec[0].r.gap} VP</div><div class="k">Biggest comeback</div><div class="s">${rec.map((x) => `${chip(ctx, x.r.winner)} in <a href="#/game/${encodeURIComponent(x.id)}">${ctx.esc(ctx.gameLabel(x.g))}</a>`).join(", ")}; d = ${ctx.num(rec[0].r.d, 2)}</div></div>` : ""}</div>
        ${games.length ? `<div class="panel table-wrap" style="margin-top:12px"><table><thead><tr><th>Game</th><th>Winner</th><th class="num">Behind at t*</th><th class="num">d</th><th>Leader at t*</th><th class="num">t*</th><th class="num">VP cards held at the end</th></tr></thead><tbody>
          ${games.map((x) => `<tr><td><a href="#/game/${encodeURIComponent(x.id)}">${ctx.esc(ctx.gameLabel(x.g))}</a></td><td>${chip(ctx, x.r.winner)}</td><td class="num"><b>${x.r.gap}</b> <span class="sub">${x.r.winner_bvp} vs ${x.r.max_bvp} of ${x.r.G}</span></td><td class="num">${ctx.num(x.r.d, 2)}</td><td>${(x.r.leaders || []).map((p) => chip(ctx, p)).join(" ")}</td><td class="num">turn ${x.r.t + 1}</td><td class="num">${x.r.vp_cards}</td></tr>`).join("")}
        </tbody></table></div><p class="note">Games where the winner was 2 or more board VP behind at t*, largest d first.</p>` : `<p class="empty">No game in this view was won from 2 or more VP behind at t*.</p>`}
      </section>`;

    const ft = c.first_to || {};
    const g5 = (ft["0.5"] || {}).group, g75 = (ft["0.75"] || {}).group;
    ids.ftConv = uid("ft-conv"); ids.ftBack = uid("ft-back"); ids.ftCtl = uid("ft-ctl");
    html += `<section class="block">
        <h2>First to get close ${ctx.info("cls_first", "First-to-c conversion")}</h2>
        <p class="note">How often the first player to reach half, or three quarters, of the way to the target on board VP went on to win.</p>
        <div class="tiles">${[["0.5", "half", g5], ["0.75", "three quarters", g75]].filter((x) => x[2]).map(([k, l, g]) => `<div class="tile"><div class="v">${ctx.pct(g.p)}</div><div class="k">First to ${l} of the way won</div><div class="s">95% ${ctx.pct(g.ci[0])} to ${ctx.pct(g.ci[1])}; ${g.games} games; fair share ${ctx.pct(g.base)}${ft[k].skipped ? `; ${ft[k].skipped} left out` : ""}</div></div>`).join("")}</div>
        <div class="race-ctl" id="${ids.ftCtl}" style="margin-top:14px"><span class="chips"><button type="button" class="chip on" data-c="0.75">75% of the way</button><button type="button" class="chip" data-c="0.5">Halfway</button></span></div>
        <div class="two-col">
          <div><h3>Won when first</h3><div class="panel" style="margin-top:8px"><div class="chart" id="${ids.ftConv}"></div></div></div>
          <div><h3>Won when not first</h3><div class="panel" style="margin-top:8px"><div class="chart" id="${ids.ftBack}"></div></div></div>
        </div>
        <div id="${ids.ftConv}-t"></div>
        <p class="note">Vertical line: the fair share (mean of 1/n) over this view's games; each player's own fair share is in the table.</p>
      </section>`;

    const d = c.draft || {};
    ids.dHist = uid("d-hist"); ids.dPl = uid("d-pl");
    const grid = d.grid || {};
    html += `<section class="block">
        <h2>Draft order ${ctx.info("cls_draft", "Draft-order grid")}</h2>
        ${d.games ? `<p class="note">The best spot (most pips) still open when each seat placed each starting settlement, averaged over ${d.games} base, New Shores and Through the Desert games. Seat 1 places first; the second round runs in reverse. Underneath: the pips actually chosen.</p>
        <div class="two-col">${["3", "4"].filter((n) => grid[n]).map((n) => { ids["grid" + n] = uid("grid-" + n); return `<div><h3>${n} players <span class="sub">${grid[n].games} games</span></h3><div class="panel" style="margin-top:8px;padding:12px"><div id="${ids["grid" + n]}"></div></div></div>`; }).join("")}</div>
        <p class="note">Open corners outside the start region (islands, land beyond the desert) were removed from the decoder's list first: ${ctx.num(d.dropped_per_pick, 1)} per pick on average.</p>` : `<p class="empty">No base, New Shores or Through the Desert games in this view.</p>`}
      </section>`;
    if (d.games) {
      html += `<section class="block">
        <h2>Pick percentile ${ctx.info("cls_pick", "Pick percentile")}</h2>
        <p class="note">Where each starting settlement ranked by pips among the open spots. The top pip spot was taken in ${ctx.pct(d.top)} of ${d.picks} picks; the mean percentile is ${ctx.num(d.mean_pct * 100, 0)}.</p>
        <div class="two-col">
          <div><h3>All picks</h3><div class="panel" style="margin-top:8px"><div class="chart" id="${ids.dHist}"></div></div>
            ${ctx.tableView([{ label: "Percentile" }, { label: "Picks", num: true }], d.hist.map((v, i) => [`${i * 10} to ${i * 10 + 10}`, v]))}</div>
          <div><h3>Mean percentile by player</h3><div class="panel" style="margin-top:8px">${Object.keys(d.players || {}).length ? `<div class="chart" id="${ids.dPl}"></div>` : ctx.guardNote(0, 10)}</div></div>
        </div>
        ${Object.keys(d.players || {}).length ? `<div class="panel table-wrap" style="margin-top:12px"><table><thead><tr><th>Player</th><th class="num">Picks</th><th class="num">How often the top pip spot was taken</th><th class="num">Mean percentile</th></tr></thead><tbody>
          ${order(ctx).filter((p) => d.players[p]).map((p) => { const r = d.players[p]; return `<tr><td>${ctx.who(p)}</td><td class="num">${r.picks}</td><td class="num">${ctx.pct(r.top)} <span class="sub">(${ctx.pct(r.top_ci[0])} to ${ctx.pct(r.top_ci[1])})</span></td><td class="num">${ctx.num(r.mean_pct * 100, 1)} <span class="sub">(${ctx.num(r.ci[0] * 100, 1)} to ${ctx.num(r.ci[1] * 100, 1)})</span></td></tr>`; }).join("")}
        </tbody></table></div>` : ""}
      </section>`;
    }

    const dl = c.dev_luck || {};
    ids.dlVp = uid("dl-vp"); ids.dlKn = uid("dl-kn");
    const dlp = order(ctx).filter((p) => (dl.players || {})[p]);
    html += `<section class="block">
        <h2>Dev card draw luck ${ctx.info("cls_devluck", "Dev draw luck")}</h2>
        ${dl.games ? `<p class="note">VP cards and knights drawn against what the cards left in the deck made likely at each purchase, in cards. ${dl.buys} purchases in ${dl.games} games${dl.excluded && dl.excluded.length ? `; ${dl.excluded.length} without a recorded deck left out` : ""}. As a group: VP cards ${ctx.fmtSigned(dl.group.vp.diff, 1)} (${dl.group.vp.O} drawn), knights ${ctx.fmtSigned(dl.group.knight.diff, 1)} (${dl.group.knight.O}).</p>
        ${dlp.length ? `<div class="two-col">
          <div><h3>VP cards</h3><div class="panel" style="margin-top:8px"><div class="chart" id="${ids.dlVp}"></div></div></div>
          <div><h3>Knights</h3><div class="panel" style="margin-top:8px"><div class="chart" id="${ids.dlKn}"></div></div></div>
        </div>
        ${ctx.tableView([{ label: "Player" }, { label: "Buys", num: true }, { label: "VP drawn", num: true }, { label: "VP expected", num: true }, { label: "VP O − E (95%)", num: true }, { label: "Knights drawn", num: true }, { label: "Knights expected", num: true }, { label: "Knights O − E (95%)", num: true }],
          dlp.map((p) => { const r = dl.players[p]; return [chip(ctx, p), r.buys, r.vp.O, ctx.num(r.vp.E, 1), `${ctx.fmtSigned(r.vp.diff, 1)} (${ctx.fmtSigned(r.vp.lo, 1)} to ${ctx.fmtSigned(r.vp.hi, 1)})`, r.knight.O, ctx.num(r.knight.E, 1), `${ctx.fmtSigned(r.knight.diff, 1)} (${ctx.fmtSigned(r.knight.lo, 1)} to ${ctx.fmtSigned(r.knight.hi, 1)})`]; }))}` : ctx.guardNote(0, 10)}`
        : `<p class="empty">No games in this view with a known dev deck.</p>`}
      </section>`;
    return html;
  }

  function drawFirst(ctx, c, key) {
    const ids = findingsHtml.ids;
    const f = (c.first_to || {})[key];
    const el1 = document.getElementById(ids.ftConv), el2 = document.getElementById(ids.ftBack), t = document.getElementById(ids.ftConv + "-t");
    if (!el1 || !el2) return;
    el1.innerHTML = ""; el2.innerHTML = "";
    const pl = order(ctx).filter((p) => f && f.players[p]);
    if (!pl.length) { el1.innerHTML = el2.innerHTML = ctx.guardNote(0, 10); return; }
    const base = f.group ? f.group.base : 0.25;
    const mk = (getter, label) => pl.map((p) => { const r = f.players[p]; const v = getter(r); return {
      label: nameOf(ctx, p), color: ctx.color(p), est: fin(v[0]) ? v[0] * 100 : null, lo: v[1] ? v[1][0] * 100 : null, hi: v[1] ? v[1][1] * 100 : null,
      tip: `<b>${nameOf(ctx, p)}</b>, ${label}<br>${fin(v[0]) ? ctx.pct(v[0], 0) : "n/a"} (${v[1] ? `${ctx.pct(v[1][0], 0)} to ${ctx.pct(v[1][1], 0)}` : "n/a"})<br>${cnt(ctx, v[2])} wins in ${cnt(ctx, v[3])} games<br>Fair share ${ctx.pct(r.base, 0)}` }; });
    const opts = { ref: base * 100, legend: false, domain: [0, 100], format: (v) => Math.round(v) + "%", xTitle: "Win rate", rowHeight: 28 };
    ctx.Charts.forestPlot(el1, Object.assign({ rows: mk((r) => [r.conv, r.conv_ci, r.first_wins, r.first], "won when first"), ariaLabel: "Win rate when first to the line" }, opts));
    ctx.Charts.forestPlot(el2, Object.assign({ rows: mk((r) => [r.comeback, r.comeback_ci, r.not_first_wins, r.not_first], "won when not first"), ariaLabel: "Win rate when not first to the line" }, opts));
    if (t) t.innerHTML = ctx.tableView([{ label: "Player" }, { label: "Games", num: true }, { label: "First (games)", num: true }, { label: "Won when first", num: true }, { label: "Won when not first", num: true }, { label: "Fair share", num: true }],
      pl.map((p) => { const r = f.players[p]; return [chip(ctx, p), r.games, cnt(ctx, r.first), fin(r.conv) ? `${ctx.pct(r.conv)} (${ctx.pct(r.conv_ci[0])} to ${ctx.pct(r.conv_ci[1])})` : "n/a",
        fin(r.comeback) ? `${ctx.pct(r.comeback)} (${ctx.pct(r.comeback_ci[0])} to ${ctx.pct(r.comeback_ci[1])})` : "n/a", ctx.pct(r.base)]; }));
  }

  function findingsDraw(ctx) {
    const c = C(ctx);
    if (!c) return;
    const ids = findingsHtml.ids || {};
    const ctl = document.getElementById(ids.ftCtl);
    if (ctl) {
      ctl.querySelectorAll("button[data-c]").forEach((b) => b.addEventListener("click", () => {
        ctl.querySelectorAll("button[data-c]").forEach((x) => x.classList.toggle("on", x === b));
        drawFirst(ctx, c, b.dataset.c);
      }));
    }
    drawFirst(ctx, c, "0.75");

    const d = c.draft || {};
    const grid = d.grid || {};
    const all = Object.values(grid).flatMap((g) => g.cells.map((x) => x.b));
    const lo = Math.min(...all), hi = Math.max(...all);
    for (const n of ["3", "4"]) {
      const el = document.getElementById(ids["grid" + n]);
      if (!el || !grid[n]) continue;
      const cell = Object.fromEntries(grid[n].cells.map((x) => [`${x.seat}|${x.pick}`, x]));
      const seats = [...new Set(grid[n].cells.map((x) => x.seat))];
      ctx.Charts.heatMatrix(el, {
        rows: seats, cols: [1, 2], allowSelf: true, sequential: { min: lo, max: hi },
        label: (id, kind) => (kind === "row" ? `Seat ${id}` : id === 1 ? "1st settlement" : "2nd settlement"),
        corner: `<span class="mx-corner">Best spot left, pips</span>`,
        cell: (s, k) => { const x = cell[`${s}|${k}`]; return x ? { value: x.b, text: ctx.num(x.b, 1), sub: `chose ${ctx.num(x.chosen, 1)}`,
          tip: `<b>Seat ${s}, ${k === 1 ? "first" : "second"} settlement</b> (pick ${x.order + 1})<br>Best spot left: ${ctx.num(x.b, 1)} pips on average<br>Chosen: ${ctx.num(x.chosen, 1)} pips<br>Top spot taken ${ctx.pct(x.top, 0)}<br>${ctx.num(x.L, 0)} open spots, ${x.n} games` } : null; },
        scale: { low: `${ctx.num(lo, 1)} pips`, high: `${ctx.num(hi, 1)} pips` },
      });
    }
    const hEl = document.getElementById(ids.dHist);
    if (hEl && d.hist) {
      ctx.Charts.barChart(hEl, { height: 200, ariaLabel: "Opening picks by percentile among the open spots",
        bars: d.hist.map((v, i) => ({ label: i === 9 ? "90+" : String(i * 10), value: v, tip: `${v} picks between the ${i * 10}th and ${i * 10 + 10}th percentile` })) });
    }
    const pEl = document.getElementById(ids.dPl);
    if (pEl && d.players) {
      ctx.Charts.forestPlot(pEl, { legend: false, rowHeight: 28, format: (v) => ctx.num(v, 0), xTitle: "Mean percentile of the chosen spot",
        rows: order(ctx).filter((p) => d.players[p]).map((p) => { const r = d.players[p]; return { label: nameOf(ctx, p), color: ctx.color(p), est: r.mean_pct * 100, lo: r.ci[0] * 100, hi: r.ci[1] * 100,
          tip: `<b>${nameOf(ctx, p)}</b><br>Mean percentile ${ctx.num(r.mean_pct * 100, 1)} (${ctx.num(r.ci[0] * 100, 1)} to ${ctx.num(r.ci[1] * 100, 1)})<br>Top pip spot taken ${ctx.pct(r.top, 0)} of ${r.picks} picks` }; }) });
    }
    const dl = c.dev_luck || {};
    for (const [k, id, label] of [["vp", ids.dlVp, "VP cards"], ["knight", ids.dlKn, "Knights"]]) {
      const el = document.getElementById(id);
      if (!el) continue;
      ctx.Charts.forestPlot(el, { ref: 0, legend: false, rowHeight: 28, format: (v) => ctx.fmtSigned(v, 1), xTitle: `${label} drawn minus expected`, leftLabel: "unlucky", rightLabel: "lucky",
        rows: order(ctx).filter((p) => (dl.players || {})[p]).map((p) => { const r = dl.players[p][k]; return { label: nameOf(ctx, p), color: ctx.color(p), est: r.diff, lo: r.lo, hi: r.hi,
          tip: `<b>${nameOf(ctx, p)}</b>, ${label}<br>${r.O} drawn, ${ctx.num(r.E, 1)} expected<br>${ctx.fmtSigned(r.diff, 1)} (${ctx.fmtSigned(r.lo, 1)} to ${ctx.fmtSigned(r.hi, 1)})<br>${dl.players[p].buys} purchases` }; }) });
    }
  }

  // ---------------------------------------------------------------------------------------------
  // Game page: t* on comeback games
  // ---------------------------------------------------------------------------------------------
  function gameHtml(ctx, g) {
    const ca = CA(ctx);
    const r = ca && ca.games && ca.games[g.id];
    if (!r || !fin(r.gap) || r.gap < 2) return "";
    const lead = (r.leaders || []).map((p) => nameOf(ctx, p)).join(" and ");
    return `<section class="block">
        <h2>A comeback ${ctx.info("cls_comeback", "Comeback gallery")}</h2>
        <p class="note">t* is when anyone first reached ${r.G - 3} board VP, 3 short of ${r.G}. Board VP leaves out VP cards still in hand. See the race above, Board VP view, at turn ${r.t + 1}.</p>
        <div class="tiles">
          <div class="tile"><div class="v">${r.gap} VP</div><div class="k">${nameOf(ctx, r.winner)} behind at t*</div><div class="s">${r.winner_bvp} against ${lead}'s ${r.max_bvp}; d = ${ctx.num(r.d, 2)}</div></div>
          <div class="tile"><div class="v">Turn ${r.t + 1}</div><div class="k">t*</div><div class="s">end of that turn</div></div>
          <div class="tile"><div class="v">${r.vp_cards}</div><div class="k">VP cards ${nameOf(ctx, r.winner)} held at the end</div><div class="s">hidden until the game ended</div></div>
        </div>
      </section>`;
  }

  const hook = (page, h) => (window.Hooks[page] = window.Hooks[page] || []).push(h);
  window.Hooks = window.Hooks || {};
  hook("style", { html: styleHtml, draw: styleDraw });
  hook("player", { html: playerHtml, draw: () => {} });
  hook("findings", { html: findingsHtml, draw: findingsDraw });
  hook("game", { html: gameHtml });
})();
