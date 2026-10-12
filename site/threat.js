/* Threat index: who looks most dangerous from what the table can see (Findings, game pages), and the badges
   built on it: trading with the tyrant, Coward and Groveler (Findings, player pages).
   Data: stats.json "threat" (the model, all games) and views[view].threat (scripts/threat.py). */
(function () {
  "use strict";

  Object.assign(window.METHODS, {
    threat_model: `<p><b>Features.</b> At every turn end, for every seat, only what the whole table can see: board VP (VP cards still hidden are left out), dice income (expected cards per roll, the robber's hex excluded), reach (dots on the open settlement spots within 2 new roads or ships), dev cards in hand, resource cards in hand, and how close the seat is to Longest Road and to Largest Army (segments or knights short of taking it, capped).</p>
      <p><b>Model.</b> A conditional logit with one choice per turn end: P(i goes on to win) = e<sup>x<sub>i</sub>b</sup> / Σ<sub>j</sub> e<sup>x<sub>j</sub>b</sup>, every seat in the choice set (guests and bots too). Each feature is divided by its spread within a turn, so the weights are per standard deviation and comparable. The top threat is the seat with the highest probability.</p>
      <p><b>Intervals.</b> One game gives dozens of turn ends that share a winner, so they are not independent. The 95% intervals use a sandwich estimator clustered by game, which counts each game as one piece of evidence.</p>
      <p><b>No peeking.</b> Games are split into 5 groups, and each group is scored by a model fit on the other 4. Every threat number on the site, including the badges, comes from a model that never saw that game's winner.</p>`,
    threat_check: `<p>Both versions are scored on games they were not fit on. <b>Equal weights</b> adds up each feature's z-score within the turn (so a dev card counts as much as a VP, per standard deviation), with one fitted scale. <b>Log loss</b> is the average of −log P(the eventual winner); lower is better, and chance (1/n) is the floor to beat. <b>Hit rate</b> is the share of turn ends where the top threat went on to win. The interval for the log loss gap is a 95% game-cluster bootstrap (2,000 draws). If the fitted weights only fit noise in 89 games, equal weights would do as well or better out of sample.</p>`,
    threat_players: `<p><b>Top threat.</b> Turn ends where the player had the highest win probability, against chance (each turn end 1/n). O/E above 1 means the table had more reason to fear them than their seat count alone. 95% game bootstrap interval.</p>
      <p><b>Average rank</b>: 1 is the top threat; chance is (n + 1)/2 averaged over their turns. <b>Hidden threat wins</b>: wins where someone else was the top threat at the last turn end before the winning turn.</p>`,
    tyrant: `<p>Player trades with the <b>tyrant</b>, against what the trading pattern alone would give.</p>
      <p><b>Ex ante</b>: the tyrant is the top threat after that turn's roll. <b>Hindsight</b>: the tyrant is the eventual winner, and each trade counts (roll + 1) / rolls, so a trade near the end counts fully and one at the start barely counts.</p>
      <p><b>Whose turn it is matters.</b> Only the player whose turn it is can trade. On your own turn you could trade with any of the n − 1 others, so chance is 1/(n − 1) per trade. On someone else's turn your partner is whoever is rolling, so chance spreads your off-turn trades over the other players' turns and counts the share that were the tyrant's. Turns where you are the tyrant (ex ante) and games you won (hindsight) are left out.</p>
      <p>O/E with a 95% game bootstrap interval; 1 means no lean toward or away from the tyrant.</p>`,
    coward: `<p>Robber moves that spare the <b>top threat</b> among the mover's opponents. Two decisions per land move, each counted when there was a real choice:</p>
      <p><b>The hex</b>, when some legal hexes touch the threat and some don't. Sparing means the chosen hex doesn't touch them. Expected comes from a hex-choice model that ignores who is winning (opponents' dots on the hex, your own dots, how many opponents you could steal from), fit without the mover's own moves. <b>The victim</b>, when the threat and someone else could both be robbed. Sparing means robbing someone else; expected is 1 − 1/eligible.</p>
      <p>O/E of 1 is a player who robs as if they didn't know the score. Everyone here goes after the leader more than that, so the badge compares each player with <b>everyone else at the same tables</b>: their O/E divided by the table's. Above 1 with a 95% game bootstrap interval clear of 1 earns Coward.</p>`,
    groveler: `<p>In player trades with the <b>current top threat</b> (after that turn's roll): cards given minus cards received, per trade. The active player usually pays a premium, so each trade is compared with the rest of the table's average in the same role (the one rolling, or the partner). Above 0 means handing the leader extra cards. 95% game bootstrap interval; players with 10 or more such trades. Clear above 0 earns Groveler.</p>`,
  });

  const T = (ctx) => ctx.ROOT.threat || {};
  const V = (ctx) => ctx.S.threat || {};
  const anon = (pid) => String(pid).startsWith("guest-") || String(pid).startsWith("bot-");
  const times = (ctx, x) => `×${ctx.num(x, 2)}`;
  const iv = (ctx, r, f) => `${f(r.lo)} to ${f(r.hi)}`;
  // good: true or false says which side of 1 is better for the player; null leaves the number uncolored.
  const ratioCell = (ctx, r, good) => {
    if (!r) return `<span class="sub">n/a</span>`;
    const tone = !r.clear || good === null ? "" : (r.ratio > 1) === good ? ' style="color:var(--vt-good)"' : ' style="color:var(--vt-bad)"';
    return `<b${tone}>${times(ctx, r.ratio)}</b><div class="sub">${iv(ctx, r, (x) => ctx.num(x, 2))}</div>`;
  };
  const badgesOf = (r) => {
    const out = [];
    if ((r.tyrant_ante && r.tyrant_ante.clear && r.tyrant_ante.ratio > 1) || (r.tyrant_hind && r.tyrant_hind.clear && r.tyrant_hind.ratio > 1)) out.push("Feeds the tyrant");
    if (r.coward && r.coward.vs_table && r.coward.vs_table.clear && r.coward.vs_table.ratio > 1) out.push("Coward");
    if (r.groveler && r.groveler.clear && r.groveler.est > 0) out.push("Groveler");
    return out;
  };

  // ---- Findings ----------------------------------------------------------------------------------
  (window.Hooks.findings = window.Hooks.findings || []).push({
    html(ctx) {
      const m = T(ctx).model, v = V(ctx);
      if (!m || !v.players) return null;
      const pct = (x) => ctx.pct(x);
      const c = m.check, h = v.hidden, last = c.thirds[2];
      const order = ctx.S.players.filter((p) => v.players[p.id]).map((p) => p.id);
      const gap = c.equal_minus_fitted;
      const rows = order.map((pid) => {
        const r = v.players[pid];
        return `<tr><td>${ctx.who(pid)}</td><td class="num">${r.games}</td><td class="num">${ratioCell(ctx, r.top, null)}</td>
          <td class="num">${ctx.num(r.rank, 2)} <span class="sub">chance ${ctx.num(r.rank_chance, 2)}</span></td>
          <td class="num">${r.hidden_wins} of ${r.wins}</td></tr>`;
      }).join("");
      const badgeRows = order.map((pid) => {
        const r = v.players[pid], b = badgesOf(r);
        const gr = r.groveler;
        return `<tr><td>${ctx.who(pid)}</td>
          <td class="num">${ratioCell(ctx, r.tyrant_ante, false)}</td><td class="num">${ratioCell(ctx, r.tyrant_hind, false)}</td>
          <td class="num">${r.coward && r.coward.vs_table ? ratioCell(ctx, r.coward.vs_table, false) : `<span class="sub">n/a</span>`}</td>
          <td class="num">${gr ? `<b${gr.clear ? ` style="color:var(${gr.est > 0 ? "--vt-bad" : "--vt-good"})"` : ""}>${ctx.fmtSigned(gr.est, 2)}</b><div class="sub">${ctx.fmtSigned(gr.lo, 2)} to ${ctx.fmtSigned(gr.hi, 2)}, ${gr.n} trades</div>` : `<span class="sub">n/a</span>`}</td>
          <td><div class="chipline">${b.map((x) => `<span class="mini"><b>${x}</b></span>`).join("") || `<span class="sub">none</span>`}</div></td></tr>`;
      }).join("");
      return `<section class="block">
        <h2>Threat index ${ctx.info("threat_model", "Threat index")}</h2>
        <p class="note">Who looked most dangerous at each moment, using only what everyone at the table could see. The weights come from asking which visible signs actually predicted the winner, and every game is scored by a model that never saw how it ended.</p>
        <div class="tiles">
          <div class="tile"><div class="v">${pct(last.acc)}</div><div class="k">Top threat goes on to win</div><div class="s">in the last third of a game; ${pct(c.acc)} over the whole game, ${pct(c.acc_chance)} by chance</div></div>
          <div class="tile"><div class="v">${h.top_won} of ${h.games}</div><div class="k">Won by the top threat going into the final turn</div><div class="s">the model expected ${ctx.num(h.expected, 1)}, chance ${ctx.num(h.chance, 1)}; the rest were hidden threats</div></div>
          <div class="tile"><div class="v">${gap.lo > 0 ? "Fitted" : "A tie"}</div><div class="k">Fitted weights vs equal weights ${ctx.info("threat_check", "Fitted vs equal weights")}</div><div class="s">${gap.lo > 0 ? "fitted calls the winner better, out of sample: " : ""}log loss ${ctx.num(c.logloss, 3)} vs ${ctx.num(c.logloss_equal, 3)} (chance ${ctx.num(c.logloss_chance, 3)}); gap 95% ${ctx.num(gap.lo, 3)} to ${ctx.num(gap.hi, 3)}</div></div>
        </div>
        <h3 style="margin-top:20px">What makes a threat</h3>
        <p class="note"><b>How to read:</b> how much one standard deviation more of each visible sign raises a player's odds of going on to win, holding the others fixed. 1× is no effect. Lines are 95% intervals that count each game once.</p>
        <div class="panel" style="margin-top:6px"><div class="chart" id="th-coef"></div></div>
        <h3 style="margin-top:24px">How well it calls the winner</h3>
        <p class="note">Share of turn ends where the top threat went on to win, scored only on games each model wasn't fit on.</p>
        <div class="panel table-wrap"><table><thead><tr><th>Part of the game</th><th class="num">Turn ends</th><th class="num">Fitted</th><th class="num">Equal weights</th><th class="num">Chance</th><th class="num">Agree on the top threat</th></tr></thead><tbody>
          ${["First third", "Middle third", "Last third"].map((lab, i) => { const t = c.thirds[i]; return t ? `<tr><td>${lab}</td><td class="num">${t.states}</td><td class="num"><b>${pct(t.acc)}</b></td><td class="num">${pct(t.acc_equal)}</td><td class="num">${pct(t.acc_chance)}</td><td class="num">${pct(t.agree)}</td></tr>` : ""; }).join("")}
          <tr><td><b>Whole game</b></td><td class="num">${c.states}</td><td class="num"><b>${pct(c.acc)}</b></td><td class="num">${pct(c.acc_equal)}</td><td class="num">${pct(c.acc_chance)}</td><td class="num">${pct(c.agree)}</td></tr>
        </tbody></table></div>
        <h3 style="margin-top:24px">Who the table should fear ${ctx.info("threat_players", "Top threat and hidden threats")}</h3>
        <p class="note"><b>How to read:</b> ×1.20 means a player was the top threat 20% more often than their seats alone would give; the second line is the 95% interval.</p>
        <div class="panel table-wrap"><table><thead><tr><th>Player</th><th class="num">Games</th><th class="num">Top threat vs chance</th><th class="num">Average rank</th><th class="num">Hidden threat wins</th></tr></thead><tbody>${rows}</tbody></table></div>
        <h3 style="margin-top:24px">Table politics</h3>
        <div class="note"><b>Feeds the tyrant</b> ${ctx.info("tyrant", "Trading with the tyrant")}: trades with the top threat (ex ante) or the eventual winner (hindsight), against chance. <b>Coward</b> ${ctx.info("coward", "Coward")}: how often their robber spares the top threat, against everyone else at the same tables. <b>Groveler</b> ${ctx.info("groveler", "Groveler")}: extra cards handed to the top threat per trade, against the table. Each badge needs its interval clear of no effect; red marks the direction that earns it.</div>
        <div class="panel table-wrap"><table><thead><tr><th>Player</th><th class="num">Tyrant, ex ante</th><th class="num">Tyrant, hindsight</th><th class="num">Spares the threat vs table</th><th class="num">Extra cards to the threat</th><th>Badges</th></tr></thead><tbody>${badgeRows}</tbody></table></div>
      </section>`;
    },
    draw(ctx) {
      const m = T(ctx).model;
      const el = document.getElementById("th-coef");
      if (!m || !el) return;
      ctx.Charts.forestPlot(el, {
        ref: 1, log: true, legend: false, xTitle: "Odds multiplier per standard deviation", leftLabel: "less of a threat", rightLabel: "more of a threat",
        format: (x) => "×" + ctx.num(x, 2),
        rows: m.feats.map((f, i) => ({ label: m.labels[f].replace(" (per SD)", ""), est: Math.exp(m.beta[i]),
          lo: m.ci[i] ? Math.exp(m.ci[i][0]) : undefined, hi: m.ci[i] ? Math.exp(m.ci[i][1]) : undefined, color: "var(--data)",
          tip: `${m.labels[f]}: ×${ctx.num(Math.exp(m.beta[i]), 2)}${m.ci[i] ? ` (${ctx.num(Math.exp(m.ci[i][0]), 2)} to ${ctx.num(Math.exp(m.ci[i][1]), 2)})` : ""}` })),
      });
    },
  });

  // ---- Player page -------------------------------------------------------------------------------
  (window.Hooks.player = window.Hooks.player || []).push({
    html(ctx, pid) {
      const r = (V(ctx).players || {})[pid];
      if (!r) return null;
      const name = ctx.esc(ctx.P[pid].name), b = badgesOf(r);
      const tile = (v, k, s) => `<div class="tile"><div class="v">${v}</div><div class="k">${k}</div><div class="s">${s}</div></div>`;
      const ta = r.tyrant_ante, cw = r.coward && r.coward.vs_table, gr = r.groveler;
      return `<section class="block">
        <h2>Threat and table politics ${ctx.info("threat_model", "Threat index")}</h2>
        <p class="note">How dangerous ${name} looked to the table, and how they treat whoever looks most dangerous.${b.length ? ` Badges: <b>${b.join(", ")}</b>.` : ""}</p>
        <div class="tiles">
          ${tile(r.top ? times(ctx, r.top.ratio) : "n/a", `Top threat vs chance ${ctx.info("threat_players", "Top threat")}`, r.top ? `95% ${iv(ctx, r.top, (x) => ctx.num(x, 2))}; average rank ${ctx.num(r.rank, 2)} (chance ${ctx.num(r.rank_chance, 2)})` : "")}
          ${tile(`${r.hidden_wins} of ${r.wins}`, "Hidden threat wins", "wins where someone else was the top threat going into the final turn")}
          ${tile(ta ? times(ctx, ta.ratio) : "n/a", `Trades with the tyrant ${ctx.info("tyrant", "Trading with the tyrant")}`, ta ? `ex ante, against chance; 95% ${iv(ctx, ta, (x) => ctx.num(x, 2))}${r.tyrant_hind ? `; hindsight ${times(ctx, r.tyrant_hind.ratio)}` : ""}` : "")}
          ${tile(cw ? times(ctx, cw.ratio) : "n/a", `Spares the threat ${ctx.info("coward", "Coward")}`, cw ? `with the robber, against the rest of the table; 95% ${iv(ctx, cw, (x) => ctx.num(x, 2))}` : "not enough robber moves")}
          ${tile(gr ? ctx.fmtSigned(gr.est, 2) : "n/a", `Extra cards to the threat ${ctx.info("groveler", "Groveler")}`, gr ? `per trade, against the table; 95% ${ctx.fmtSigned(gr.lo, 2)} to ${ctx.fmtSigned(gr.hi, 2)}` : "fewer than 10 trades with the top threat")}
        </div>
      </section>`;
    },
  });

  // ---- Game page ---------------------------------------------------------------------------------
  (window.Hooks.game = window.Hooks.game || []).push({
    html(ctx, g) {
      const tl = (T(ctx).timelines || {})[g.id];
      if (!tl) return null;
      return `<section class="block">
        <h2>Threat through the game ${ctx.info("threat_model", "Threat index")}</h2>
        <p class="note"><b>How to read:</b> after every turn, each player's chance of winning judged only from what the table could see (board VP, income, reach, cards and dev cards in hand, closeness to the titles). Hidden VP cards don't count, which is how a hidden threat sneaks through. The model never saw this game's result.</p>
        <div class="panel"><div class="chart" id="th-game"></div></div>
      </section>`;
    },
    draw(ctx, g) {
      const tl = (T(ctx).timelines || {})[g.id], el = document.getElementById("th-game");
      if (!tl || !el) return;
      const name = (pid) => (String(pid).startsWith("bot-") ? "Bot" : anon(pid) ? "Guest" : ctx.P[pid] ? ctx.P[pid].name : pid);
      ctx.Charts.lineChart(el, {
        series: tl.seats.map((pid, i) => ({ id: pid, name: name(pid), color: anon(pid) ? "var(--muted)" : ctx.color(pid),
          points: tl.turn.map((t, k) => ({ x: t, y: Math.round(tl.p[i][k] * 100), tip: `${Math.round(tl.p[i][k] * 100)}%` })) })),
        height: 240, stepLabel: "turns", ariaLabel: "Each player's chance of winning from the visible board after every turn",
        xLabel: (x) => `<b>After turn ${x}</b>`,
      });
    },
  });
})();
