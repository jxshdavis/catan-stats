/* Luck and momentum: the board VP race, play of the game, the production engine, cumulative dice luck and
   the dev card timeline on the game page; luck and production by game stage on player pages; the snowball
   test and friends on Findings. Data: stats.json "momentum" (all games) and views[view].momentum. */
(function () {
  "use strict";
  window.METHODS = window.METHODS || {};
  Object.assign(window.METHODS, {
    race: `<p><b>Board VP</b> is what everyone could see: VP minus VP cards still held. VP cards stay hidden until the end, so the final turn shows them as a jump labeled "revealed". <b>True VP</b> is the hindsight view with VP cards counted as soon as they are bought.</p>
      <p><b>Rate</b> is VP gained per round over a trailing window of exactly 3 rounds: r(t) = [Y(t) − Y(t − 3n)] / (min(t, 3n) / n), with n the number of seats, so every player has had exactly 3 turns in the window once t ≥ 3n. It never looks ahead, and levels are never smoothed. The table always shows raw values.</p>`,
    play: `<p><b>Play of the game</b>: the winner's position is their board VP margin over the best other seat, M = winner − best other, after every action. The unit is a whole turn of the winner's, after setup and before their final turn (the final turn always looks huge because the game stops there). Swing = M after the turn − M before it.</p>
      <p>A turn counts only if it is durable: M never falls back to its level before that turn, or lower, before the final turn. The pick is the largest durable swing of at least 2; ties go to a turn that took the lead, 2 or 3 ties are shown together with the earliest starred, and 4 or more mean no single standout. The best single action inside the turn is shown as detail. No win-probability model is used.</p>
      <p><b>Went ahead</b>: the last action that took M from 0 or less to above 0, with the end-of-game reveal of VP cards as its own event. A game is "led for good" when that happened before the final turn, a "board walk-off" when it happened on the final turn, and a "reveal finish" when hidden VP cards decided it.</p>`,
    engine: `<p>Expected cards per round from each player's buildings at that moment: E(t) = Σ over totals k ≠ 7 of dots(k)/36 × (cards owed on k), with the hex under the robber left out, times the number of seats. Settlements count 1 and cities 2, gold at face value. Hover for the gross line with the robber ignored; the gap is the robber tax. Summed over the game this is exactly the "expected" column. No smoothing.</p>`,
    luck_game: `<p>Cumulative dice luck L(t) = Σ (cards the dice owed − expected cards), roll by roll, before the bank-shortage rule. Each roll's variance is Σ P(k) f(k)² − E², so the variance V(t) adds up.</p>
      <p>For the chosen player: the flat band is ±2.241 √V(T), a 95% band for the whole path at once (a random walk observed at every step); the faint band is the pointwise ±1.96 √V(t), shown once V ≥ 4. A path outside the flat band would be unusual for fair dice.</p>`,
    dev_timeline: `<p>Every dev card bought (hollow marks: the card type was hidden at the table) and played (filled, with its type), by roll. A play before the player's own roll is marked "before roll".</p>`,
    luck_player: `<p><b>Game-centered dice luck</b>: per game, a player's luck L (cards from dice minus expected, before the bank-shortage rule) minus the table's average L in that game. Centering removes what everyone at the table shared, including the slight shortage of 7s across our games. In cards per game, with a 95% t interval from the spread over games.</p>
      <p>The funnel plot shows every player's average against games played, with 95% limits for pure chance using this view's spread per game (SD / √games). No flags: points outside the funnel are what you would expect now and then.</p>`,
    deciles: `<p>Production share R(t) = n E(t) / Σ<sub>j</sub> E<sub>j</sub>(t), the player's expected cards per roll against the table average (exactly 1 on average). Each game is cut into tenths by roll: decile d = ⌈10 t / T⌉. The line is the average over games of each decile's mean; the band is a 95% simultaneous (sup-t) band from 2,000 resamples of games.</p>
      <p>Δ = average over games of (mean R in deciles 8 to 10 − mean R in deciles 1 to 3). Descriptive only: it uses the final game length, and deciles 1 and 2 mostly reflect seat and opening.</p>`,
    snowball: `<p><b>Question</b>: is a card of dice luck early worth more toward winning than one later? Conditional logit stratified by game (Firth penalty): P(i wins) ∝ exp(b₁ L(rounds 1 to 4) + b₂ L(rounds 5 to 8) + b₃ L(round 9 to the end)). The tested contrast is D = b₁ − b₂, fit directly by rewriting the model with L₁ and L₁ + L₂ so D gets a profile likelihood interval. Every game completes 8 full rounds, so neither window touches the stopping move; b₃ does, since the winner's last round is lucky by construction.</p>
      <p>Pre-specified in the all-games view only. The test is weak: at 80% power it only detects D of about 2.8 SE, so a null is worded "not detected", not "absent". Sensitivity rows: 3 and 4 seat games only; adding pre-game skill μ (a different, skill-conditional question); and the full finishing order (exploded logit).</p>`,
    mechanism: `<p>Does early luck turn into lasting capacity? x = a seat's game-centered luck over rounds 1 to 4. Outcomes, each centered within the game and averaged over the turn ends in each round bin: capacity C (expected cards per round with the robber ignored), robber drag (the cards the robber keeps off per round) and board VP share (board VP ÷ target). A finished game keeps its final state, so games ending early don't drop out. Slopes are pooled least squares over every seat; intervals from 2,000 resamples of games.</p>
      <p>Return over rounds 5 to 8: the slope of the expected cards a seat collected in rounds 5 to 8. Compounding: the slope of capacity at the end of round 8 minus the slope at the end of round 5 (pre-specified).</p>`,
    luck_adjusted: `<p>Each game's win chances from a conditional logit (Firth) on dice luck over rounds 1 to 8, refit with that game left out. Wins above luck = Σ (won − p); luck part = Σ (p − 1/n), how many wins the dice alone handed the player; SE = √Σ p(1 − p).</p>`,
    leaks: `<p>Where do lucky cards go? Slopes, on game-centered luck over rounds 1 to 4, of cards each seat lost in rounds 5 and later: 7-discards, monopoly, the bank shortage rule (cards the dice owed that the bank could not pay) and steals. These are rule mechanics, not anyone's intent: a bigger hand loses more to 7s and is a better steal target. Pooled least squares with 2,000 game resamples.</p>`,
  });

  const RACE_KEY = "race";
  const readOpt = (k, dflt) => {
    const q = new URLSearchParams((location.hash.split("?")[1]) || "");
    if (q.get(k)) return q.get(k);
    try { return localStorage.getItem("opt-" + k) || dflt; } catch (e) { return dflt; }
  };
  const writeOpt = (k, v) => {
    const [path, query] = location.hash.split("?");
    const q = new URLSearchParams(query || "");
    q.set(k, v);
    history.replaceState(null, "", `${path}?${q.toString()}`);
    try { localStorage.setItem("opt-" + k, v); } catch (e) {}
  };
  const gm = (ctx, gid) => ((ctx.ROOT.momentum || {}).games || {})[gid];
  const lineColor = (ctx, pid) => (String(pid).startsWith("guest-") || String(pid).startsWith("bot-") ? "var(--muted)" : ctx.color(pid));
  const nameOf = (ctx, g, pid) => {
    if (String(pid).startsWith("bot-")) return "Bot";
    if (!String(pid).startsWith("guest-")) return ctx.P[pid] ? ctx.P[pid].name : pid;
    const r = g.players.find((x) => x.player === pid);
    return g.n_guests > 1 && r ? `Guest (${ctx.ord(r.rank)})` : "Guest";
  };
  const TYPE_LABEL = {
    settlement: "settlement", city: "city", road: "road", ship: "ship", move_ship: "ship move", dev: "dev card",
    longest_road_taken: "took Longest Road", largest_army_taken: "took Largest Army", island_bonus: "settled a new island",
    longest_road_lost: "broke a Longest Road",
  };
  function whatText(ctx, what, action) {
    const parts = (what || []).filter((w) => w.type !== "longest_road_lost").map((w) => {
      if ((w.type === "longest_road_taken" || w.type === "largest_army_taken") && w.from) return `${TYPE_LABEL[w.type]} from ${ctx.esc(nameOf(ctx, { players: [], n_guests: 0 }, w.from))}`;
      if (w.type === "island_bonus") return `${TYPE_LABEL[w.type]} (+${w.vp})`;
      return TYPE_LABEL[w.type] || w.type;
    });
    return parts.length ? parts.join(", ") : (TYPE_LABEL[action] || action);
  }
  const marg = (x) => (x > 0 ? "+" + x : x < 0 ? "−" + Math.abs(x) : "0");

  function playText(ctx, g, m) {
    const p = m.play;
    const n = m.n;
    const round = (t) => Math.floor(t / n) + 1;
    let out = "";
    if (p && p.pick) {
      const c = p.pick;
      const turnBits = c.actions.map((a) => whatText(ctx, a.what, a.action)).join(", ");
      out += `<p class="callout"><span class="star-ic" aria-hidden="true">★</span> <b>Play of the game</b>: round ${round(c.roll_index)}, ${ctx.esc(nameOf(ctx, g, g.winner))}'s turn took the margin from ${marg(c.from)} to ${marg(c.to)} and never gave it back (whole turn: ${marg(c.swing)}; ${ctx.esc(turnBits)}). Biggest single action: ${ctx.esc(whatText(ctx, c.best_action.what, c.best_action.action))}, ${marg(c.best_action.swing)}.`;
      if (p.co_plays && p.co_plays.length) out += ` Tied with ${p.co_plays.map((x) => `round ${round(x.roll_index)}`).join(" and ")}.`;
      out += "</p>";
    } else if (p && p.no_standout_ties) {
      out += `<p class="callout">No single standout: ${p.no_standout_ties} turns tied for the biggest swing.</p>`;
    } else if (p) {
      out += `<p class="callout">No standout play: built one point at a time.</p>`;
    }
    if (p && p.given_back) out += `<p class="note">A bigger swing (${marg(p.given_back.swing)}, round ${round(p.given_back.roll_index)}) was later given back.</p>`;
    const ga = m.go_ahead;
    if (ga) {
      const txt = ga.kind === "led" ? `Went ahead for good in round ${round(ga.roll_index)}, before the final turn.`
        : ga.kind === "walk_off" ? `A board walk-off: ${ctx.esc(nameOf(ctx, g, g.winner))} only went ahead on board VP on the final turn.`
          : `A reveal finish: on board VP ${ctx.esc(nameOf(ctx, g, g.winner))} was not ahead; hidden VP cards decided it.`;
      out += `<p class="note">${txt}</p>`;
    }
    return out;
  }

  // ---- Game page: the race and friends -----------------------------------------------------
  (window.Hooks["game-race"] = window.Hooks["game-race"] || []).push({
    html(ctx, g) {
      const m = gm(ctx, g.id);
      if (!m) return null;
      return `<section class="block">
        <h2>The race ${ctx.info("race", "Board VP race")} ${ctx.info("play", "Play of the game")}</h2>
        <p class="note">Victory points everyone could see at the end of every turn, replayed from TwoSheep's record of the game. Board VP leaves out VP cards still hidden in hand; switch to true VP to include them. Rate per round shows how fast each player was scoring instead of their total. The star marks the play of the game, the winner's turn that most widened their lead, and the vertical rule the moment they went ahead for good.</p>
        <div class="race-ctl"><span id="race-series"></span><span id="race-mode"></span></div>
        <div class="panel"><div class="chart" style="padding-bottom:0"><ul class="legend">${m.seats.map((pid) => `<li><span class="sw" style="--c:${lineColor(ctx, pid)}"></span>${ctx.esc(nameOf(ctx, g, pid))}</li>`).join("")}<li><span class="sw star" style="--c:var(--ink)"></span>Play of the game</li><li><span class="sw rule"></span>Went ahead</li></ul></div>
        <div class="chart" id="race"></div><div id="race-table"></div></div>
        ${playText(ctx, g, m)}
      </section>
      <section class="block">
        <h2>Production engine ${ctx.info("engine", "Production engine")}</h2>
        <p class="note"><b>How to read:</b> how many cards per round each player's settlements and cities would produce with average dice, robber included. A step up is a new settlement or city; a dip is usually the robber moving onto them. Hover for the total without the robber.</p>
        <div class="panel"><div class="chart" id="engine"></div><div id="engine-table"></div></div>
      </section>
      <section class="block">
        <h2>Dice luck through the game ${ctx.info("luck_game", "Cumulative dice luck")}</h2>
        <p class="note"><b>How to read:</b> each line is a running total of cards from dice minus what that player's buildings should have produced. Above 0 the dice were running hot for them, below 0 cold. Pick a player to shade the range fair dice would usually wander; a line leaving its band is unusually lucky or unlucky.</p>
        <div class="chips" id="luck-pick" role="group" aria-label="Show the chance band for">${m.seats.map((pid, i) => `<button type="button" class="chip" data-i="${i}" aria-pressed="false">${ctx.esc(nameOf(ctx, g, pid))}</button>`).join("")}</div>
        <div class="panel" style="margin-top:8px"><div class="chart" id="luckg"></div><div id="luckg-table"></div></div>
      </section>
      ${m.dev.length ? `<section class="block">
        <h2>Dev cards ${ctx.info("dev_timeline", "Dev card timeline")}</h2>
        <div class="panel"><div class="chart">${devStrip(ctx, g, m)}</div></div>
      </section>` : ""}`;
    },
    draw(ctx, g) {
      const m = gm(ctx, g.id);
      if (!m) return;
      const C = ctx.Charts;
      let series = readOpt("series", "board"), mode = readOpt(RACE_KEY, "level");
      const drawRace = () => {
        const src = series === "true" ? m.true_vp : m.board_vp;
        const names = m.seats.map((pid) => nameOf(ctx, g, pid));
        const lev = src.map((s) => s.map((v, t) => ({ x: t, y: v })));
        const pts = mode === "rate" ? lev.map((s) => C.rateSeries(s, m.n, (ctx.ROOT.momentum || {}).w_rate || 3)) : lev;
        const markers = [];
        const p = m.play;
        if (p && p.pick) markers.push({ x: p.pick.roll_index + 1, seriesId: g.winner, kind: "star", label: "Play of the game" });
        if (p && p.co_plays) p.co_plays.forEach((c) => markers.push({ x: c.roll_index + 1, seriesId: g.winner, kind: "star", label: "Tied play" }));
        if (m.go_ahead && m.go_ahead.kind === "led") markers.push({ x: m.go_ahead.roll_index + 1, kind: "rule", label: "Went ahead" });
        const cb = ((ctx.ROOT.classes || {}).games || {})[g.id];  // a comeback game: when the winner was furthest back
        if (cb && cb.t !== undefined && cb.t !== null) markers.push({ x: cb.t + 1, kind: "rule", label: `Comeback start: ${cb.gap} VP behind` });
        if (series === "board") {
          const last = src[0].length - 1;
          src.forEach((s, i) => { const hidden = m.true_vp[i][last] - s[last]; if (hidden > 0) markers.push({ x: last, seriesId: m.seats[i], kind: "rule", label: `+${hidden} revealed (${names[i]})` }); });
        }
        C.stepChart(document.getElementById("race"), {
          series: m.seats.map((pid, i) => ({ id: pid, name: names[i], color: lineColor(ctx, pid),
            points: pts[i].map((q) => ({ x: q.x, y: q.y, tip: mode === "rate" ? `${ctx.num(q.y, 2)} VP per round` : `${q.y} VP` })) })),
          markers: mode === "rate" ? [] : markers, height: 260, stepLabel: "turns",
          ariaLabel: `${series === "true" ? "True" : "Board"} VP ${mode === "rate" ? "gained per round" : ""} for each player after every turn`,
          xLabel: (x) => `<b>${x === 0 ? "After setup" : "Turn " + x}</b>`, xTickLabel: (x) => (x === 0 ? "setup" : x),
        });
        const T = src[0].length;
        const every = Math.max(1, Math.ceil(T / 40));
        document.getElementById("race-table").innerHTML = ctx.tableView(
          [{ label: "Turn" }].concat(names.map((nm) => ({ label: ctx.esc(nm), num: true }))),
          Array.from({ length: T }, (_, t) => t).filter((t) => t % every === 0 || t === T - 1)
            .map((t) => [t === 0 ? "After setup" : t].concat(src.map((s) => s[t]))),
          "Show as table (raw values)");
      };
      C.levelRate(document.getElementById("race-series"), { value: series === "true" ? "rate" : "level",
        labels: { level: "Board VP", rate: "True VP (hindsight)" }, ariaLabel: "Which VP to show",
        onChange: (v) => { series = v === "rate" ? "true" : "board"; writeOpt("series", series); drawRace(); } });
      C.levelRate(document.getElementById("race-mode"), { value: mode, labels: { level: "Level", rate: "Rate per round" },
        onChange: (v) => { mode = v; writeOpt(RACE_KEY, v); drawRace(); } });
      drawRace();

      const names = m.seats.map((pid) => nameOf(ctx, g, pid));
      C.stepChart(document.getElementById("engine"), {
        series: m.seats.map((pid, i) => ({ id: pid, name: names[i], color: lineColor(ctx, pid),
          points: m.engine[i].map((v, t) => ({ x: t + 1, y: v, tip: `${ctx.num(v, 1)} per round (${ctx.num(m.engine_gross[i][t], 1)} without the robber)` })) })),
        height: 220, stepLabel: "rolls", ariaLabel: "Expected cards per round for each player at every roll",
        xLabel: (x) => `<b>Roll ${x}</b>`,
      });
      const T = m.engine[0].length, every = Math.max(1, Math.ceil(T / 40));
      document.getElementById("engine-table").innerHTML = ctx.tableView(
        [{ label: "Roll" }].concat(names.map((nm) => ({ label: ctx.esc(nm), num: true }))),
        Array.from({ length: T }, (_, t) => t).filter((t) => t % every === 0 || t === T - 1)
          .map((t) => [t + 1].concat(m.engine.map((s) => ctx.num(s[t], 2)))));

      let pick = Math.max(0, m.seats.indexOf(g.winner));
      const drawLuck = () => {
        document.querySelectorAll("#luck-pick .chip").forEach((b) => {
          const on = +b.dataset.i === pick;
          b.classList.toggle("on", on);
          b.setAttribute("aria-pressed", String(on));
        });
        const VT = m.luck_var[pick][m.luck_var[pick].length - 1];
        const half = m.sim_band * Math.sqrt(VT);
        const pw = m.luck_var[pick].map((v, t) => ({ x: t + 1, v })).filter((q) => q.v >= 4)
          .map((q) => ({ x: q.x, lo: -1.96 * Math.sqrt(q.v), hi: 1.96 * Math.sqrt(q.v) }));
        C.stepChart(document.getElementById("luckg"), {
          series: m.seats.map((pid, i) => ({ id: pid, name: names[i], color: lineColor(ctx, pid),
            points: m.luck[i].map((v, t) => ({ x: t + 1, y: v, tip: `${ctx.fmtSigned(v, 1)} cards` })) })),
          bands: pw.length ? [{ seriesId: m.seats[pick], points: pw }] : [],
          flatBand: { lo: -half, hi: half }, yRef: 0, highlight: m.seats[pick], height: 240, stepLabel: "rolls",
          ariaLabel: "Cumulative dice luck for each player", xLabel: (x) => `<b>Roll ${x}</b>`,
        });
        document.getElementById("luckg-table").innerHTML = ctx.tableView(
          [{ label: "Player" }, { label: "Luck at the end", num: true }, { label: "Chance band (whole game)", num: true }],
          m.seats.map((pid, i) => { const v = m.luck_var[i][m.luck_var[i].length - 1]; return [ctx.esc(names[i]), ctx.fmtSigned(m.luck[i][m.luck[i].length - 1], 1), `±${ctx.num(m.sim_band * Math.sqrt(v), 1)}`]; }));
      };
      document.getElementById("luck-pick").addEventListener("click", (e) => {
        const b = e.target.closest("button[data-i]");
        if (b) { pick = +b.dataset.i; drawLuck(); }
      });
      drawLuck();
    },
  });

  const CARD = { knight: "K", monopoly: "M", road_building: "RB", year_of_plenty: "YP", victory_point: "VP" };
  function devStrip(ctx, g, m) {
    const T = m.rolls;
    const rows = m.seats.map((pid, i) => {
      const ev = m.dev.filter((d) => d.s === i + 1);
      if (!ev.length) return "";
      return `<div class="strip-row"><span class="strip-lab">${ctx.esc(nameOf(ctx, g, pid))}</span><div class="strip-track">${ev.map((d) => {
        const left = (Math.max(0, d.t) / Math.max(1, T - 1)) * 100;
        const tip = d.a === "buy" ? `Bought a dev card, roll ${d.t + 1}` : `Played ${d.c.replace(/_/g, " ")}, roll ${d.t + 1}${d.pre ? ", before rolling" : ""}`;
        return d.a === "buy" ? `<span class="dev-mk buy" style="left:${left}%" tabindex="0" data-tip="${ctx.esc(tip)}" aria-label="${ctx.esc(tip)}"></span>`
          : `<span class="dev-mk play" style="left:${left}%;--c:${lineColor(ctx, pid)}" tabindex="0" data-tip="${ctx.esc(tip)}" aria-label="${ctx.esc(tip)}">${CARD[d.c] || "?"}</span>`;
      }).join("")}</div></div>`;
    }).join("");
    return `<div class="strip">${rows}<div class="strip-axis"><span>roll 1</span><span>roll ${T}</span></div></div>
      <ul class="legend" style="margin-top:8px"><li><span class="dev-mk buy static"></span>Bought (type hidden)</li><li><span class="dev-mk play static" style="--c:var(--data)">K</span>Played: K knight, M monopoly, RB road building, YP year of plenty</li></ul>`;
  }

  // ---- Player page ---------------------------------------------------------------------------
  (window.Hooks.player = window.Hooks.player || []).push({
    html(ctx, pid) {
      const v = ctx.S.momentum;
      if (!v) return null;
      const L = (v.luck || {})[pid], D = (v.deciles || {})[pid], la = v.luck_adjusted && v.luck_adjusted.players[pid];
      if (!L && !D) return null;
      return `<section class="block">
        <h2>Luck and momentum</h2>
        <div class="tiles">
          ${L ? `<div class="tile"><div class="v">${ctx.fmtSigned(L.mean, 1)}</div><div class="k">Dice luck per game vs the table ${ctx.info("luck_player", "Game-centered dice luck")}</div><div class="s">cards; 95% interval ${ctx.fmtSigned(L.lo, 1)} to ${ctx.fmtSigned(L.hi, 1)}, ${L.games} games</div></div>` : ""}
          ${la ? `<div class="tile"><div class="v">${ctx.fmtSigned(la.above_luck, 1)}</div><div class="k">Wins above luck ${ctx.info("luck_adjusted", "Luck-adjusted wins")}</div><div class="s">${la.wins} wins, ${ctx.num(la.luck_expected, 1)} expected from the dice alone (SE ${ctx.num(la.se, 1)})</div></div>` : ""}
          ${D ? `<div class="tile"><div class="v">${ctx.fmtSigned(D.delta, 2)}</div><div class="k">Late minus early production share ${ctx.info("deciles", "Production share by game stage")}</div><div class="s">95% interval ${ctx.fmtSigned(D.delta_ci[0], 2)} to ${ctx.fmtSigned(D.delta_ci[1], 2)}</div></div>` : ""}
        </div>
        ${L ? `<h3 style="margin-top:20px">Dice luck against games played</h3><p class="note"><b>How to read:</b> each dot is one player: their average dice luck per game (cards above or below their tablemates) against how many games they have played. The funnel is the range fair dice would give, wide for few games and narrow for many. A dot inside the funnel is ordinary luck.</p><div class="panel"><div class="chart" id="p-funnel"></div></div>` : ""}
        ${D ? `<h3 style="margin-top:20px">Production share through the game</h3><p class="note"><b>How to read:</b> how much this player's buildings produce compared with their tablemates (1.00 is the table average), from the start of the game (1) to the end (10). Above 1 means out-producing the table at that stage; the band is the 95% interval. From ${Object.entries(D.sizes).map(([n, k]) => `${k} ${n}-player`).join(", ")} games.</p><div class="panel"><div class="chart" id="p-dec"></div></div>` : ""}
      </section>`;
    },
    draw(ctx, pid) {
      const v = ctx.S.momentum;
      if (!v) return;
      const C = ctx.Charts;
      const fun = document.getElementById("p-funnel");
      if (fun) {
        const pts = Object.entries(v.luck).filter(([, r]) => r.shown);
        const all = pts.map(([, r]) => r);
        const pooledSd = Math.sqrt(all.reduce((a, r) => a + r.sd * r.sd * (r.games - 1), 0) / Math.max(1, all.reduce((a, r) => a + r.games - 1, 0)));
        C.funnelPlot(fun, {
          points: pts.map(([id, r]) => ({ x: r.games, y: r.mean, label: ctx.P[id] ? ctx.P[id].name : id, color: id === pid ? ctx.color(id) : "var(--axis)",
            tip: `${ctx.esc(ctx.P[id] ? ctx.P[id].name : id)}: ${ctx.fmtSigned(r.mean, 2)} cards per game over ${r.games} games` })),
          se: { sd: pooledSd }, ref: 0, xTitle: "Games played", yTitle: "Cards per game vs the table", labels: true, height: 240,
          format: (y) => ctx.fmtSigned(y, 1), ariaLabel: "Average dice luck against games played, every player",
        });
      }
      const dec = document.getElementById("p-dec");
      if (dec) {
        const D = v.deciles[pid];
        C.lineChart(dec, {
          series: [{ id: pid, name: ctx.P[pid].name, color: ctx.color(pid), band: true,
            points: D.mean.map((y, k) => ({ x: k + 1, y, lo: D.lo[k], hi: D.hi[k], tip: `${ctx.num(y, 2)} (${ctx.num(D.lo[k], 2)} to ${ctx.num(D.hi[k], 2)})` })) },
          { id: "ref", name: "Table average", color: "var(--axis)", points: D.mean.map((_, k) => ({ x: k + 1, y: 1, tip: "1.00" })) }],
          directLabels: false, height: 220, stepLabel: "tenths of the game", ariaLabel: "Production share by tenth of the game",
          xLabel: (x) => `<b>Tenth ${x}</b> of the game`, xTickLabel: (x) => x,
        });
      }
    },
  });

  // ---- Findings --------------------------------------------------------------------------------
  (window.Hooks.findings = window.Hooks.findings || []).push({
    html(ctx) {
      const A = ctx.ROOT.momentum, v = ctx.S.momentum;
      if (!A || !A.snowball) return null;
      const s = A.snowball, mech = A.mechanism, lk = A.leaks;
      const la = v && v.luck_adjusted;
      const order = ctx.S.players.filter((p) => p.games > 0).map((p) => p.id);
      return `<section class="block">
        <h2>Does early luck snowball? ${ctx.info("snowball", "Snowball test")}</h2>
        <p class="note">The question: is a lucky card early in the game worth more than a lucky card later, because early cards get built into things that keep producing? We measure how much one card of dice luck (against the table) raises the odds of winning, separately for rounds 1 to 4 and rounds 5 to 8, and D is the difference. All games; this is one of the two questions chosen in advance.</p>
        <div class="tiles">
          <div class="tile"><div class="v">${s.detected ? "Detected" : "Not detected"}</div><div class="k">Are early lucky cards worth more?</div><div class="s">D = ${ctx.num(s.D, 3)}, 95% interval ${ctx.num(s.D_ci[0], 3)} to ${ctx.num(s.D_ci[1], 3)}, ${s.games} games</div></div>
          <div class="tile"><div class="v">${ctx.num(s.b1, 3)} vs ${ctx.num(s.b2, 3)}</div><div class="k">Effect of one lucky card, rounds 1 to 4 vs 5 to 8</div><div class="s">on the log odds of winning; bigger means it helps more</div></div>
          <div class="tile"><div class="v">${ctx.num(s.detectable_80, 2)}</div><div class="k">Smallest difference this many games can reliably find</div><div class="s">at 80% power; anything smaller could hide</div></div>
        </div>
        <p class="note">From round 9 to the end a lucky card is worth ${ctx.num(s.b3, 3)} (b₃), but that is inflated by how games stop: the game ends on a good turn for the winner, and over the final round the winner averaged ${ctx.fmtSigned(A.final_round.winner, 1)} cards of luck against ${ctx.fmtSigned(A.final_round.others, 1)} for everyone else. "Not detected" doesn't mean absent.</p>
        <p class="note" style="margin-top:12px"><b>How to read:</b> each row is D from a different version of the test. Right of 0 means early luck counts more; a line that crosses 0 means no clear difference.</p>
        <div class="panel" style="margin-top:6px"><div class="chart" id="f-snow"></div></div>
        ${mech ? `<h3 style="margin-top:20px">What early luck turns into ${ctx.info("mechanism", "Snowball mechanism")}</h3>
          <p class="note"><b>How to read:</b> for every extra card of dice luck in rounds 1 to 4, how much more a player had later, by stretch of the game. Capacity is cards per round their buildings make; robber drag is cards per round the robber blocks; board VP share is their share of the target. Right of 0 means early luck is still paying off at that point. In numbers: per lucky card, the return over rounds 5 to 8 is ${ctx.fmtSigned(mech.return.slope, 2)} expected cards (${ctx.fmtSigned(mech.return.ci[0], 2)} to ${ctx.fmtSigned(mech.return.ci[1], 2)}); compounding ${ctx.fmtSigned(mech.compounding.slope, 3)} (${ctx.fmtSigned(mech.compounding.ci[0], 3)} to ${ctx.fmtSigned(mech.compounding.ci[1], 3)}).</p>
          <div class="three-col">${[["C", "Capacity, cards per round"], ["drag", "Robber drag, cards per round"], ["share", "Board VP share"]].map(([k, t]) => `<div><h4>${t}</h4><div class="panel"><div class="chart" id="f-mech-${k}"></div></div></div>`).join("")}</div>
          <p class="note">Share of games already over: ${Object.entries(mech.finished_share).map(([b, x]) => `rounds ${b}: ${ctx.pct(x)}`).join(", ")}.</p>` : ""}
        ${lk ? `<h3 style="margin-top:20px">Where lucky cards leak ${ctx.info("leaks", "Where lucky cards leak")}</h3>
          <p class="note"><b>How to read:</b> for each extra card of dice luck in rounds 1 to 4, how many cards were lost in round 5 and later to 7-discards, steals, monopoly and the bank running out. Right of 0 means lucky players lose more that way, which is expected: bigger hands lose more to 7s and are better targets.</p>
          <div class="panel"><div class="chart" id="f-leak"></div></div>` : ""}
        ${la ? `<h3 style="margin-top:20px">Wins above luck ${ctx.info("luck_adjusted", "Luck-adjusted wins")}</h3>
          <p class="note"><b>How to read:</b> "From the dice alone" is how many wins each player would expect if only dice luck decided games. "Luck part" is how many of those the dice handed them beyond a fair share. "Above luck" is their actual wins minus the dice-alone number, with its 95% margin: positive means they won more than their dice explain.</p>
          <div class="panel table-wrap"><table><thead><tr><th>Player</th><th class="num">Games</th><th class="num">Wins</th><th class="num">From the dice alone</th><th class="num">Luck part</th><th class="num">Above luck</th></tr></thead><tbody>
          ${order.filter((id) => la.players[id]).map((id) => { const r = la.players[id]; return `<tr><td>${ctx.who(id)}</td><td class="num">${r.games}</td><td class="num">${r.wins}</td><td class="num">${ctx.num(r.luck_expected, 1)}</td><td class="num">${ctx.fmtSigned(r.luck_part, 1)}</td><td class="num">${ctx.fmtSigned(r.above_luck, 1)} <span class="sub">± ${ctx.num(1.96 * r.se, 1)}</span></td></tr>`; }).join("")}
          </tbody></table></div>` : ""}
        ${A.play_tally ? `<h3 style="margin-top:20px">What the plays of the game were ${ctx.info("play", "Play of the game")}</h3>
          <div class="panel table-wrap"><table><thead><tr><th>Biggest action in the play</th>${Object.keys(A.play_tally).map((k) => `<th class="num">${ctx.esc(k)}</th>`).join("")}</tr></thead><tbody>
          ${[...new Set(Object.values(A.play_tally).flatMap((d) => Object.keys(d)))].map((t) => `<tr><td>${ctx.esc(TYPE_LABEL[t] || t)}</td>${Object.keys(A.play_tally).map((k) => `<td class="num">${ctx.num(A.play_tally[k][t] || 0, 1)}</td>`).join("")}</tr>`).join("")}
          </tbody></table></div><p class="note">The play of the game is the winner's turn that most widened their board VP lead over the next best player (the star on each game's race chart). This counts what kind of action it was, by scenario. All games; ties split a game between the tied plays, and games with no standout play aren't counted.</p>` : ""}
      </section>`;
    },
    draw(ctx) {
      const A = ctx.ROOT.momentum;
      if (!A || !A.snowball) return;
      const C = ctx.Charts;
      const s = A.snowball;
      const el = document.getElementById("f-snow");
      if (el) C.coefPlot(el, {
        xTitle: "D = b₁ − b₂ (log odds per card)", leftLabel: "later cards worth more", rightLabel: "early cards worth more",
        rows: [{ label: "<b>All games</b> (tested)", b: s.D, lo: s.D_ci[0], hi: s.D_ci[1] }]
          .concat(s.sensitivity.map((r) => ({ label: ctx.esc(r.name), b: r.D, lo: r.D_ci ? r.D_ci[0] : undefined, hi: r.D_ci ? r.D_ci[1] : undefined, se: r.D_ci ? undefined : r.D_se }))),
      });
      const mech = A.mechanism;
      if (mech) {
        for (const k of ["C", "drag", "share"]) {
          const e = document.getElementById(`f-mech-${k}`);
          if (!e) continue;
          C.forestPlot(e, {
            ref: 0, legend: false, format: (v) => ctx.fmtSigned(v, k === "share" ? 3 : 2), rowHeight: 28,
            rows: Object.keys(mech.finished_share).map((b) => { const r = mech[`${k}|${b}`]; return { label: `Rounds ${b}`, est: r.slope, lo: r.ci[0], hi: r.ci[1], tip: `Rounds ${b}: ${ctx.fmtSigned(r.slope, 3)} (${ctx.fmtSigned(r.ci[0], 3)} to ${ctx.fmtSigned(r.ci[1], 3)}) per card of early luck` }; }),
          });
        }
      }
      const lk = A.leaks, le = document.getElementById("f-leak");
      if (lk && le) C.forestPlot(le, {
        ref: 0, legend: false, format: (v) => ctx.fmtSigned(v, 2), xTitle: "Cards lost later per card of early luck",
        rows: [["discarded", "7-discards"], ["stolen", "Steals"], ["monopoly", "Monopoly"], ["shortage", "Bank shortage"]].map(([k, l]) => ({
          label: l, est: lk[k].slope, lo: lk[k].ci[0], hi: lk[k].ci[1], tip: `${l}: ${ctx.fmtSigned(lk[k].slope, 3)} (${ctx.fmtSigned(lk[k].ci[0], 3)} to ${ctx.fmtSigned(lk[k].ci[1], 3)})` })),
      });
    },
  });
})();
