/* Front page extras: tonight's stakes, rivalry of the moment, what's coming up, records and monthly awards.
   All of it is light arithmetic over the current view in stats.json (games, head to head, stories, replays),
   so nothing here needs the build. app.js calls Home.html(ctx) for the markup and Home.draw(ctx) to wire it up. */
(function () {
  "use strict";

  const ranked = (c) => c.S.players.filter((p) => p.games > 0);
  const member = (c, pid) => !!(c.P[pid] && c.P[pid].games > 0);
  const nameOf = (c, pid) => (c.P[pid] ? c.P[pid].name : "a guest");
  const gameLink = (g, text) => `<a href="#/game/${encodeURIComponent(g.id)}">${text || `game ${g.number}`}</a>`;
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many || one + "s"}`;
  const chrono = (c) => c.S.games.slice().sort((a, b) => a.index - b.index); // S.games is newest first
  const andList = (xs) => (xs.length < 3 ? xs.join(" and ") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);
  const orList = (xs) => (xs.length < 3 ? xs.join(" or ") : `${xs.slice(0, -1).join(", ")} or ${xs[xs.length - 1]}`);
  const load = (k) => { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } };
  const save = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* storage blocked */ } };

  // Places after adding deltas to some totals. Ties keep today's order, standing in for the VP-share tiebreak.
  function places(rk, delta) {
    const v = rk.map((p) => ({ id: p.id, v: p.above_expected + (delta[p.id] || 0), r: p.leaderboard_rank }));
    v.sort((a, b) => (Math.abs(b.v - a.v) > 1e-9 ? b.v - a.v : a.r - b.r));
    const out = {};
    v.forEach((x, i) => (out[x.id] = { place: i + 1, v: x.v }));
    return out;
  }
  const move = (from, to) => (to < from ? `<span class="mv up">▲${from - to}</span>` : to > from ? `<span class="mv down">▼${to - from}</span>` : "");

  // ---- Tonight's table ----------------------------------------------------------------------------------
  // Pick who's playing; every seat shows what a win adds, what a loss costs and where it leaves them.
  const TKEY = "tonight";
  const MAX_GUESTS = 6;
  function tonightState(c) {
    const ids = new Set(ranked(c).map((p) => p.id));
    const saved = load(TKEY);
    if (saved && Array.isArray(saved.p)) {
      const p = saved.p.filter((id) => ids.has(id));
      if (p.length) return { p, g: Math.max(0, Math.min(MAX_GUESTS, +saved.g || 0)) };
    }
    const last = c.S.games[0]; // default: the same table as the latest game
    const p = last.players.map((r) => r.player).filter((id) => ids.has(id));
    return { p, g: last.players.length - p.length };
  }

  function stakesHtml(c, rk, sel, guests) {
    const n = sel.length + guests, win = 1 - 1 / n, loss = 1 / n;
    const winners = sel.map((p) => p.id).concat(guests ? [null] : []); // null: a guest or bot wins
    const by = new Map();
    for (const w of winners) {
      const d = {};
      for (const p of sel) d[p.id] = p.id === w ? win : -loss;
      by.set(w, places(rk, d));
    }
    const wname = (w) => (w === null ? "a guest" : c.esc(nameOf(c, w)));
    const rows = sel.map((p) => {
      const now = p.leaderboard_rank, w = by.get(p.id)[p.id];
      const lp = winners.filter((x) => x !== p.id).map((x) => by.get(x)[p.id].place);
      const lo = Math.min(...lp), hi = Math.max(...lp), lv = p.above_expected - loss;
      return { p, now, w, lo, hi, lv };
    });

    // A few sentences on what's actually at stake.
    const lines = [];
    const leader = rk[0];
    const takers = rows.filter((r) => r.w.place === 1 && r.now !== 1).map((r) => c.esc(r.p.name));
    const lead = rows.find((r) => r.p.id === leader.id);
    if (lead) {
      const dethrone = winners.filter((x) => x !== leader.id && by.get(x)[leader.id].place > 1).map(wname);
      lines.push(dethrone.length ? `First place is on the line: ${c.esc(leader.name)} drops out of first if ${orList(dethrone)} wins.`
        : `${c.esc(leader.name)} stays first whatever happens tonight.`);
    } else if (takers.length) {
      lines.push(`${c.esc(leader.name)} isn't playing, and a win puts ${orList(takers)} in first.`);
    } else {
      const chase = rows.slice().sort((a, b) => b.w.v - a.w.v)[0];
      lines.push(`${c.esc(leader.name)} isn't playing, and nobody here can reach first tonight. The closest is ${c.esc(chase.p.name)}, who would still be ${c.num(leader.above_expected - chase.w.v, 2)} behind with a win.`);
    }
    const climb = rows.map((r) => ({ r, d: r.now - r.w.place })).sort((a, b) => b.d - a.d)[0];
    if (climb && climb.d >= 2) lines.push(`${c.esc(climb.r.p.name)} has the most to gain: a win lifts them ${climb.d} places to ${c.ord(climb.r.w.place)}.`);
    // Only name someone as having the most to lose when they stand out; a three-way tie says nothing.
    const falls = rows.map((r) => ({ r, d: r.hi - r.now })).sort((a, b) => b.d - a.d);
    if (falls[0] && falls[0].d >= 1 && (falls.length === 1 || falls[0].d > falls[1].d)) {
      lines.push(`${c.esc(falls[0].r.p.name)} has the most to lose: a loss can drop them to ${c.ord(falls[0].r.hi)}.`);
    }
    const fire = (p) => (p.recent && p.recent.on_fire ? ` <span class="t-form fire">on fire</span>` : p.recent && p.recent.streak >= 2 ? ` <span class="t-form">${p.recent.streak} wins in a row</span>` : "");
    const place = (lo, hi) => (lo === hi ? c.ord(lo) : `${c.ord(lo)}–${c.ord(hi)}`);
    const tr = rows.map((r) => `<tr>
        <td><span class="name-cell">${c.who(r.p.id)}${fire(r.p)}</span></td>
        <td class="num"><span class="t-place">${c.ord(r.now)}</span> <span class="sub">${c.fmtSigned(r.p.above_expected, 1)}</span></td>
        <td class="num t-win"><span class="t-d up">+${c.num(win, 2)}</span> <span class="t-place">${c.ord(r.w.place)}</span>${move(r.now, r.w.place)}<div class="sub">${c.fmtSigned(r.w.v, 1)}</div></td>
        <td class="num t-loss"><span class="t-d down">−${c.num(loss, 2)}</span> <span class="t-place">${place(r.lo, r.hi)}</span>${move(r.now, r.hi)}<div class="sub">${c.fmtSigned(r.lv, 1)}</div></td>
      </tr>`).join("");
    return `<p class="t-lines">${lines.join(" ")}</p>
      <div class="table-wrap"><table class="tonight-table">
        <thead><tr><th>Player</th><th class="num">Now</th><th class="num">If they win</th><th class="num">If they lose</th></tr></thead>
        <tbody>${tr}</tbody></table></div>
      <p class="note">At ${plural(n, "seat")} a win is worth +${c.num(win, 2)} and a loss costs ${c.num(loss, 2)}. A loss can land in a range of places because it depends on who wins instead.${c.VIEW !== "all" ? " These count in the current game filter only." : ""}</p>`;
  }

  // How often the row player finished ahead of the column player, for tonight's players only.
  function h2hHtml(c, sel) {
    if (sel.length < 2) return "";
    const H = {};
    for (const r of c.S.head_to_head || []) H[r.player + "|" + r.opponent] = r;
    const cell = (a, b) => {
      if (a.id === b.id) return `<td class="h-self"></td>`;
      const r = H[a.id + "|" + b.id];
      if (!r || !r.games) return `<td class="num h-none">–</td>`;
      const rate = r.ahead / Math.max(1, r.ahead + r.behind), k = Math.round(Math.abs(rate - 0.5) * 2 * 55);
      const bg = rate === 0.5 ? "transparent" : `color-mix(in srgb, var(${rate > 0.5 ? "--div-pos" : "--div-neg"}) ${k}%, transparent)`;
      const tip = `<b>${c.esc(a.name)} vs ${c.esc(b.name)}</b><br>Finished ahead in ${r.ahead} of ${r.games} games together${r.tied ? `, tied ${r.tied}` : ""}`;
      return `<td class="num" style="background:${bg}" data-tip="${c.esc(tip)}">${r.ahead}–${r.behind}</td>`;
    };
    return `<h3 class="t-h3">Head to head at this table</h3>
      <p class="note">Each row player's record against each column player: times finished ahead, then behind.</p>
      <div class="table-wrap"><table class="h2h-mini">
        <thead><tr><th></th>${sel.map((p) => `<th class="num">${c.esc(p.name)}</th>`).join("")}</tr></thead>
        <tbody>${sel.map((a) => `<tr><th scope="row">${c.who(a.id, false)}</th>${sel.map((b) => cell(a, b)).join("")}</tr>`).join("")}</tbody>
      </table></div>`;
  }

  function drawTonight(c, box) {
    const rk = ranked(c);
    let st = tonightState(c);
    const render = (focusSel) => {
      const sel = rk.filter((p) => st.p.includes(p.id)); // in leaderboard order
      const n = sel.length + st.g;
      const pick = rk.map((p) => {
        const on = st.p.includes(p.id);
        return `<button type="button" class="seat${on ? " on" : ""}" data-pid="${c.esc(p.id)}" aria-pressed="${on}" style="--c:${c.color(p.id)}"><span class="hex" aria-hidden="true"></span>${c.esc(p.name)}</button>`;
      }).join("");
      const guests = `<span class="seat-g"><span class="k">Guests or bots</span>`
        + `<button type="button" class="step" data-g="-1" aria-label="One fewer guest"${st.g ? "" : " disabled"}>−</button>`
        + `<b aria-live="polite">${st.g}</b>`
        + `<button type="button" class="step" data-g="1" aria-label="One more guest"${st.g >= MAX_GUESTS ? " disabled" : ""}>+</button></span>`;
      const body = sel.length < 2 || n < 3
        ? `<p class="note">Pick who's playing. A game counts when it has at least 3 seats and 2 of them are from the group.</p>`
        : stakesHtml(c, rk, sel, st.g) + h2hHtml(c, sel);
      box.innerHTML = `<div class="seats" role="group" aria-label="Who is playing tonight">${pick}${guests}
        <button type="button" class="link-btn" data-reset>Same as last game</button></div>${body}`;
      if (focusSel) { const el = box.querySelector(focusSel); if (el) el.focus(); }
    };
    box.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b || !box.contains(b)) return;
      let focus = null;
      if (b.dataset.pid) {
        const i = st.p.indexOf(b.dataset.pid);
        if (i >= 0) st.p.splice(i, 1); else st.p.push(b.dataset.pid);
        save(TKEY, st);
        focus = `[data-pid="${CSS.escape(b.dataset.pid)}"]`;
      } else if (b.dataset.g) {
        st.g = Math.max(0, Math.min(MAX_GUESTS, st.g + +b.dataset.g));
        save(TKEY, st);
        focus = `[data-g="${b.dataset.g}"]`;
      } else if ("reset" in b.dataset) {
        save(TKEY, null);
        st = tonightState(c);
        focus = "[data-reset]";
      } else return;
      render(focus);
    });
    render();
  }

  // ---- Rivalry of the moment ----------------------------------------------------------------------------
  // Every pair of group members who sat at the same table, with who finished ahead each time.
  function meetings(c) {
    const pairs = {};
    for (const g of chrono(c)) {
      const rows = g.players.filter((r) => member(c, r.player));
      for (let i = 0; i < rows.length; i++) for (let j = i + 1; j < rows.length; j++) {
        const [x, y] = rows[i].player < rows[j].player ? [rows[i], rows[j]] : [rows[j], rows[i]];
        const k = x.player + "|" + y.player;
        (pairs[k] = pairs[k] || { a: x.player, b: y.player, m: [] }).m.push({ g, ahead: x.rank < y.rank ? x.player : y.rank < x.rank ? y.player : null });
      }
    }
    return Object.values(pairs).map((p) => {
      p.aw = p.m.filter((x) => x.ahead === p.a).length;
      p.bw = p.m.filter((x) => x.ahead === p.b).length;
      return p;
    });
  }
  const RECENT = 20;

  function rivalryHtml(c) {
    const all = meetings(c), games = chrono(c);
    if (!games.length) return "";
    const cutoff = games[Math.max(0, games.length - RECENT)].index;
    const pool = all.filter((p) => p.m.length >= 8);
    if (!pool.length) return "";
    for (const p of pool) p.recent = p.m.filter((x) => x.g.index >= cutoff);
    const even = (p) => Math.abs(p.aw - p.bw) / p.m.length;
    const top = pool.slice().sort((x, y) => (y.recent.length - x.recent.length) || (even(x) - even(y)) || (y.m.length - x.m.length))[0];
    // The side that leads goes first.
    const [L, R, lw, rw] = top.aw >= top.bw ? [top.a, top.b, top.aw, top.bw] : [top.b, top.a, top.bw, top.aw];
    const recentL = top.recent.filter((x) => x.ahead === L).length, recentR = top.recent.filter((x) => x.ahead === R).length;
    const last = top.m[top.m.length - 1];
    const strip = top.m.slice(-12).map((x) => {
      const col = x.ahead ? c.color(x.ahead) : "var(--axis)";
      const tip = `<b>Game ${x.g.number}, ${c.fmtDate(x.g.date)}</b><br>${x.ahead ? `${c.esc(nameOf(c, x.ahead))} finished ahead` : "Tied"}`;
      return `<a class="rv-dot" href="#/game/${encodeURIComponent(x.g.id)}" style="--c:${col}" data-tip="${c.esc(tip)}" aria-label="Game ${x.g.number}: ${x.ahead ? c.esc(nameOf(c, x.ahead)) + " ahead" : "tied"}"></a>`;
    }).join("");
    const recentLine = recentL === recentR ? `level at ${recentL}–${recentR}` : `${c.esc(nameOf(c, recentL > recentR ? L : R))} leading ${Math.max(recentL, recentR)}–${Math.min(recentL, recentR)}`;
    const others = pool.filter((p) => p !== top);
    const evenest = others.filter((p) => p.m.length >= 15).sort((x, y) => (even(x) - even(y)) || (y.m.length - x.m.length))[0];
    const lopsided = others.filter((p) => p.m.length >= 10).sort((x, y) => (even(y) - even(x)) || (y.m.length - x.m.length))[0];
    const pairLine = (p, label) => {
      if (!p) return "";
      const [a, b, aw, bw] = p.aw >= p.bw ? [p.a, p.b, p.aw, p.bw] : [p.b, p.a, p.bw, p.aw];
      return aw === bw
        ? `<li><span class="k">${label}</span> ${c.who(a)} and ${c.who(b)} level at ${aw}–${bw}</li>`
        : `<li><span class="k">${label}</span> ${c.who(a)} ahead of ${c.who(b)} ${aw}–${bw}</li>`;
    };
    return `<section class="block">
        <h2>Rivalry of the moment</h2>
        <p class="note">The two regulars who have met most in the group's last ${RECENT} games. The score counts who finished ahead of whom, not just wins.</p>
        <div class="panel rival">
          <div class="rv-score">
            <div class="rv-side">${c.who(L)}<b>${lw}</b></div>
            <span class="rv-vs">vs</span>
            <div class="rv-side r"><b>${rw}</b>${c.who(R)}</div>
          </div>
          <div class="rv-strip" role="list" aria-label="Last ${Math.min(12, top.m.length)} meetings, oldest first">${strip}</div>
          <p class="rv-line">${plural(top.m.length, "meeting")} in all. They've met ${plural(top.recent.length, "time")} in the group's last ${RECENT} games, ${recentLine}. Last time, in ${gameLink(last.g)}, ${last.ahead ? `${c.esc(nameOf(c, last.ahead))} finished ahead` : "they tied"}.</p>
          <ul class="rv-more">${pairLine(evenest, "Most even")}${pairLine(lopsided, "Most one-sided")}</ul>
        </div>
      </section>`;
  }

  // ---- Records and what's coming up -----------------------------------------------------------------
  function streaks(p) {
    let best = 0, bestEnd = -1, run = 0;
    const h = p.standing_history;
    h.forEach((x, i) => { run = x.won ? run + 1 : 0; if (run > best) { best = run; bestEnd = i; } });
    return { best, from: best ? h[bestEnd - best + 1] : null, to: best ? h[bestEnd] : null, current: run };
  }

  function recordsHtml(c) {
    const rk = ranked(c), games = chrono(c), R = c.ROOT, tiles = [];
    const tile = (label, value, holder, sub) => tiles.push(`<div class="rec"><div class="rec-k">${label}</div><div class="rec-v">${value}</div><div class="rec-who">${holder}</div><div class="rec-s">${sub}</div></div>`);
    // A record goes to whoever set it first; a later tie doesn't take it.
    const firstMax = (items, f) => items.reduce((best, x) => (f(x) > (best ? f(best) : -Infinity) ? x : best), null);

    const st = rk.map((p) => ({ p, s: streaks(p) })).filter((x) => x.s.best >= 2);
    const sBest = st.length ? Math.max(...st.map((x) => x.s.best)) : 0;
    if (sBest) {
      const holders = st.filter((x) => x.s.best === sBest).sort((a, b) => a.s.to.index - b.s.to.index);
      const h = holders[0];
      tile("Longest win streak", plural(sBest, "win"), c.who(h.p.id),
        `Games ${h.s.from.number} to ${h.s.to.number}${holders.length > 1 ? `. Matched by ${andList(holders.slice(1).map((x) => c.esc(x.p.name)))}` : ""}`);
    }
    const stories = games.filter((g) => member(c, g.winner) && R.stories && R.stories[g.id]);
    const cb = firstMax(stories, (g) => R.stories[g.id].deficit || 0);
    if (cb && R.stories[cb.id].deficit >= 3) {
      const w = cb.players.find((r) => r.rank === 1), s2 = cb.players.find((r) => r.rank === 2);
      tile("Biggest comeback", `${R.stories[cb.id].deficit} VP down`, c.who(cb.winner), `${gameLink(cb)}, won ${w.vp} to ${s2 ? s2.vp : "?"}`);
    }
    const lc = firstMax(games.filter((g) => R.stories && R.stories[g.id]), (g) => (R.stories[g.id].lead || {}).changes || 0);
    if (lc) tile("Most lead changes", plural(R.stories[lc.id].lead.changes, "change"), c.who(lc.winner), `Won ${gameLink(lc)} through all of them`);
    // Fastest win counts turns per VP needed, so 10 and 14 point games compare fairly.
    const fast = games.filter((g) => g.turns && member(c, g.winner))
      .reduce((b, g) => (!b || g.turns / (g.vp_to_win || 10) < b.turns / (b.vp_to_win || 10) ? g : b), null);
    if (fast) tile("Fastest win", `${fast.turns} turns`, c.who(fast.winner), `To ${fast.vp_to_win || 10} VP in ${gameLink(fast)}`);
    const rows = [];
    for (const g of games) for (const [pid, r] of Object.entries((R.game_replays || {})[g.id] || {})) if (member(c, pid)) rows.push({ g, pid, r });
    const dice = firstMax(rows, (x) => x.r.resources_from_dice || 0);
    if (dice) tile("Most cards from dice", plural(dice.r.resources_from_dice, "card"), c.who(dice.pid), `${gameLink(dice.g)}, against ${c.num(dice.r.expected_from_dice, 0)} expected`);
    const hand = firstMax(rows, (x) => x.r.max_hand || 0);
    if (hand) tile("Biggest hand", plural(hand.r.max_hand, "card"), c.who(hand.pid), `Held at once in ${gameLink(hand.g)}`);
    const road = firstMax(rows, (x) => x.r.longest_road_length || 0);
    if (road) tile("Longest road", plural(road.r.longest_road_length, "piece"), c.who(road.pid), `${gameLink(road.g)}, ${c.fmtDate(road.g.date)}`);
    const steal = firstMax(rows, (x) => x.r.steals || 0);
    if (steal) tile("Most steals in a game", plural(steal.r.steals, "steal"), c.who(steal.pid), `${gameLink(steal.g)}, ${c.fmtDate(steal.g.date)}`);
    if (!tiles.length) return "";
    return `<section class="block">
        <h2>Records</h2>
        <p class="note">The best ever in the games shown. A record belongs to whoever set it first.</p>
        <div class="rec-grid">${tiles.join("")}</div>
      </section>`;
  }

  function comingUpHtml(c) {
    const rk = ranked(c), items = [];
    const add = (pri, html) => items.push({ pri, html });
    const total = c.S.summary.games, next = total + 1;
    if (next % 100 === 0) add(0, `The next game is the group's <b>${c.ord(next)}</b>.`);
    else if (next % 25 === 0) add(1, `The next game is the group's ${c.ord(next)}.`);
    const st = rk.map((p) => ({ p, s: streaks(p) }));
    const record = Math.max(0, ...st.map((x) => x.s.best));
    for (const { p, s } of st) {
      if (s.current >= 2) {
        const then = s.current + 1 > record ? "One more sets the group record." : s.current + 1 === record ? `One more ties the group record of ${record}.` : `The record is ${record}.`;
        add(0, `${c.who(p.id)} has won ${s.current} in a row. ${then}`);
      }
    }
    for (const p of rk) {
      const d = 5 - (p.wins % 5);
      if (d <= 2 && p.wins + d >= 10) add(d, `${c.who(p.id)} is ${plural(d, "win")} from ${p.wins + d} wins.`);
      const g = p.games + 1;
      if (g % 25 === 0 || g === 10) add(2, `${c.who(p.id)} plays their ${c.ord(g)} game next.`);
    }
    // The tightest race between neighbors on the board.
    let race = null;
    for (let i = 1; i < rk.length; i++) {
      const gap = rk[i - 1].above_expected - rk[i].above_expected;
      if (!race || gap < race.gap) race = { gap, a: rk[i - 1], b: rk[i] };
    }
    if (race) add(1, `${c.who(race.b.id)} is ${c.num(race.gap, 2)} behind ${c.who(race.a.id)} for ${c.ord(race.a.leaderboard_rank)}, the closest race on the board.`);
    const climbers = rk.filter((p) => p.above_expected < 0 && p.above_expected > -0.67);
    for (const p of climbers) add(3, `A win at a 3-player table would put ${c.who(p.id)} above zero.`);
    if (!items.length) return "";
    items.sort((a, b) => a.pri - b.pri);
    return `<section class="block">
        <h2>Coming up</h2>
        <p class="note">Streaks, milestones and close races to watch next game.</p>
        <ul class="coming panel">${items.slice(0, 6).map((x) => `<li>${x.html}</li>`).join("")}</ul>
      </section>`;
  }

  // ---- Monthly awards -----------------------------------------------------------------------------------
  const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  const monthName = (ym) => `${MONTHS[+ym.slice(5) - 1]} ${ym.slice(0, 4)}`;

  function awardsFor(c, ym) {
    const games = c.S.games.filter((g) => g.date.slice(0, 7) === ym);
    const acc = {};
    for (const g of games) for (const r of g.players) {
      if (!member(c, r.player)) continue;
      const a = (acc[r.player] = acc[r.player] || { id: r.player, n: 0, wins: 0, above: 0, rn: 0, act: 0, exp: 0, steals: 0, stolen: 0, trades: 0, blocked: 0, hand: 0, handG: null });
      a.n++;
      if (g.winner === r.player) a.wins++;
      a.above += r.above_expected || 0;
      const rp = ((c.ROOT.game_replays || {})[g.id] || {})[r.player];
      if (!rp) continue;
      a.rn++;
      a.act += rp.resources_from_dice || 0; a.exp += rp.expected_from_dice || 0;
      a.steals += rp.steals || 0; a.stolen += rp.stolen_from || 0; a.trades += rp.trades || 0;
      a.blocked += rp.blocked_by_robber || 0;
      if ((rp.max_hand || 0) > a.hand) { a.hand = rp.max_hand; a.handG = g; }
    }
    const ps = Object.values(acc), withR = ps.filter((a) => a.rn >= 2);
    // The top value, with everyone tied on it.
    const best = (list, f, low = false) => {
      if (!list.length) return null;
      const vals = list.map(f), top = low ? Math.min(...vals) : Math.max(...vals);
      return { v: top, who: list.filter((_, i) => Math.abs(vals[i] - top) < 1e-9) };
    };
    const out = [];
    const award = (title, b, value, sub, ok = true) => { if (b && ok) out.push({ title, b, value: value(b.v), sub: sub(b) }); };
    const pm = best(ps.filter((a) => a.n >= 2), (a) => a.above);
    award("Player of the month", pm, (v) => `${c.fmtSigned(v, 1)}`, (b) => `above expected, ${plural(b.who[0].wins, "win")} in ${plural(b.who[0].n, "game")}`, pm && pm.v > 0);
    const luck = (a) => (a.exp ? a.act / a.exp - 1 : 0);
    const hot = best(withR, luck);
    award("Hot dice", hot, (v) => `+${Math.round(v * 100)}%`, () => "more cards from dice than average rolls give", hot && hot.v > 0);
    const cold = best(withR, luck, true);
    award("Cold dice", cold, (v) => `−${Math.round(-v * 100)}%`, () => "fewer cards from dice than average rolls give", cold && cold.v < 0);
    const per = (k) => (a) => a[k] / a.rn;
    const pick = best(withR, per("steals"));
    award("Pickpocket", pick, (v) => c.num(v, 1), () => "steals a game", pick && pick.v > 0);
    const mag = best(withR, per("stolen"));
    award("Robber's favorite", mag, (v) => c.num(v, 1), () => "times robbed a game", mag && mag.v > 0);
    const deal = best(withR, per("trades"));
    award("Wheeler-dealer", deal, (v) => c.num(v, 1), () => "trades with players a game", deal && deal.v > 0);
    const blk = best(withR, per("blocked"));
    award("Robber's shadow", blk, (v) => c.num(v, 1), () => "cards a game lost to the robber on their hexes", blk && blk.v > 0);
    const hoard = best(ps.filter((a) => a.rn >= 1), (a) => a.hand);
    award("Hoarder", hoard, (v) => plural(v, "card"), (b) => `held at once${b.who.length === 1 && b.who[0].handG ? ` in ${gameLink(b.who[0].handG)}` : ""}`, hoard && hoard.v >= 10);
    return { games, out };
  }

  function drawAwards(c, box) {
    const months = [...new Set(c.S.games.map((g) => g.date.slice(0, 7)))].sort();
    if (!months.length) return;
    let i = months.length - 1;
    const render = (focusSel) => {
      const ym = months[i], { games, out } = awardsFor(c, ym);
      const cards = out.map((a) => `<div class="award">
          <div class="aw-k">${a.title}</div>
          <div class="aw-who">${a.b.who.map((x) => c.who(x.id)).join(" ")}</div>
          <div class="aw-v"><b>${a.value}</b> ${a.sub}</div>
        </div>`).join("");
      box.innerHTML = `<div class="aw-nav">
          <button type="button" class="step" data-m="-1" aria-label="Previous month"${i ? "" : " disabled"}>‹</button>
          <h3 aria-live="polite">${monthName(ym)} <span class="sub">${plural(games.length, "game")}</span></h3>
          <button type="button" class="step" data-m="1" aria-label="Next month"${i < months.length - 1 ? "" : " disabled"}>›</button>
        </div>
        ${games.length < 3 ? `<p class="note">A quiet month, so these come from only ${plural(games.length, "game")}.</p>` : ""}
        ${cards ? `<div class="aw-grid">${cards}</div>` : `<p class="empty">Not enough games this month for awards.</p>`}`;
      if (focusSel) { const el = box.querySelector(focusSel); if (el && !el.disabled) el.focus(); }
    };
    box.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-m]");
      if (!b) return;
      i = Math.max(0, Math.min(months.length - 1, i + +b.dataset.m));
      render(`[data-m="${b.dataset.m}"]`);
    });
    render();
  }

  // ---- Entry points -------------------------------------------------------------------------------------
  window.Home = {
    tonight: () => `<section class="block" id="tonight-sec">
        <h2>Tonight's table</h2>
        <p class="note">Pick who's playing to see what each seat has riding on the next game. Your picks stay in this browser.</p>
        <div class="panel tonight" id="tonight"></div>
      </section>`,
    middle: (c) => {
      const riv = rivalryHtml(c), up = comingUpHtml(c);
      return riv && up ? `<div class="two-col">${riv}${up}</div>` : riv + up;
    },
    records: (c) => recordsHtml(c),
    awards: (c) => (c.S.games.length ? `<section class="block">
        <h2>Monthly awards</h2>
        <p class="note">Handed out from each month's games. Rates per game need at least 2 decoded games that month.</p>
        <div class="panel" id="awards"></div>
      </section>` : ""),
    draw: (c) => {
      const t = document.getElementById("tonight");
      if (t) drawTonight(c, t);
      const a = document.getElementById("awards");
      if (a) drawAwards(c, a);
    },
  };
})();
