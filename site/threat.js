/* Threat index: who looks most dangerous from what the table can see (Findings, game pages), and the badges
   built on it: trading with the tyrant, Coward and Groveler (Findings, player pages).
   Data: stats.json "threat" (the model, all games) and views[view].threat (scripts/threat.py). */
(function () {
  "use strict";

  Object.assign(window.METHODS, {
    threat_model: `<p><b>Features.</b> At every turn end, for every seat, only what the whole table can see: board VP (VP cards still hidden are left out); dice income on the five resources (expected cards per roll, the robber's hex excluded) and, separately, income from gold hexes; reach (dots on the open settlement spots within 2 new roads or ships), with the gold among those spots, a new island bonus within reach and new port types within reach each counted as their own sign; ports held (a 3:1 port, and 2:1 ports weighted by how much of that resource the seat produces); dev cards in hand, resource cards in hand, and how close the seat is to Longest Road and to Largest Army (segments or knights short of taking it, capped).</p>
      <p><b>Model.</b> A conditional logit with one choice per turn end: P(i goes on to win) = e<sup>x<sub>i</sub>b</sup> / Σ<sub>j</sub> e<sup>x<sub>j</sub>b</sup>, every seat in the choice set (guests and bots too). Each feature is divided by its spread within a turn, so the weights are per standard deviation and comparable. The top threat is the seat with the highest probability.</p>
      <p><b>Stage of the game.</b> Each weight changes in a straight line with how far the game has gone: the leader's board VP as a share of the VP target (capped at 1), which everyone can see. A weight is reported at three points: early (the leader has a fifth of the points needed), middle (half) and late (four-fifths).</p>
      <p><b>Penalty.</b> With 13 signs, each with its own weight and its own change over the game, and only one winner per game, an unrestrained fit chases noise. The fit is penalized (ridge): weights, and changes in weights, are pulled toward zero and only move away from it when the games clearly back them up. How hard to pull (450 for the weights, 150 for their changes) was set on 26 Nov 2026 by checking which strength best predicted games left out of the fit, and is fixed since.</p>
      <p><b>Intervals.</b> One game gives dozens of turn ends that share a winner, so they are not independent. The 95% intervals use a sandwich estimator clustered by game, which counts each game as one piece of evidence. They show how much the penalized weights would vary from sample to sample; the weights themselves are pulled toward zero on purpose.</p>
      <p><b>No peeking.</b> Games are split into 5 groups, and each group is scored by a model fit on the other 4. Every threat number on the site, including the badges, comes from a model that never saw that game's winner.</p>`,
    threat_check: `<p>Both versions are scored on games they were not fit on. <b>Equal weights</b> adds up each feature's z-score within the turn (so a dev card counts as much as a VP, per standard deviation), with one fitted scale. <b>Log loss</b> is the average of −log P(the eventual winner); lower is better, and chance (1/n) is the floor to beat. <b>Hit rate</b> is the share of turn ends where the top threat went on to win. The interval for the log loss gap is a 95% game-cluster bootstrap (2,000 draws). If the fitted weights only fit noise, equal weights would do as well or better out of sample.</p>
      <p><b>Constant weights</b> is the model used before 26 Nov 2026: the same signs, one weight each for the whole game, no penalty. It is still fit and scored the same way. On the games that were used to choose the new model the comparison flatters the new one a little, so the forward check counts only games played after the switch.</p>`,
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

  // ---- The model, written out (under the weights chart, and folded under each game's threat chart) ------
  const SIGNS = {
    board_vp: "Victory points on the board. VP cards still hidden in a hand are left out.",
    income: "Expected cards per roll from wood, brick, sheep, wheat and ore: the number dots under the player's settlements and cities (a city counts twice) divided by 36, skipping the hex the robber is on.",
    income_gold: "The same, from gold hexes only. Each gold card is a free pick, so it is kept apart from ordinary income.",
    reach: "How good the open settlement spots are within 2 new roads or ships of the player's network: the number dots on those spots, gold hexes left out.",
    reach_gold: "The dots on gold hexes among those spots.",
    reach_island: "The island bonus (in VP) the player would earn for their next new island, when one of those spots is on an island that would count. Zero otherwise.",
    reach_port: "How many port types the player does not hold yet have a port corner among those spots.",
    port_31: "Whether the player has a settlement or city on a 3:1 port.",
    port_21: "For each 2:1 port the player holds, their income per roll in that port's resource. A wheat port with no wheat production counts as zero.",
    dev_held: "Development cards in hand, bought and not yet played. The count is public even though the cards are not.",
    hand: "Resource cards in hand.",
    road_close: "How few road or ship segments the player is short of taking Longest Road: 5 are needed, or one more than the current holder. The holder scores the maximum.",
    army_close: "How few knights the player is short of taking Largest Army: 3 are needed, or one more than the current holder. The holder scores the maximum.",
  };
  const STAGES = ["Early", "Middle", "Late"];
  const clearW = (w, j) => w.lo[j] != null && w.hi[j] != null && (w.lo[j] > 0 || w.hi[j] < 0);
  // The forward check: the stage model against the constant-weight model it replaced, on games played since.
  function forwardText(ctx, fw) {
    if (!fw) return "";
    if (!fw.games) return "A forward check on games played after the switch, which had no part in choosing it, starts with the next game.";
    const g = fw.constant_minus_fitted, better = fw.logloss < fw.logloss_constant;
    return `On the ${fw.games} game${fw.games === 1 ? "" : "s"} played since the switch, which had no part in choosing it, log loss is ${ctx.num(fw.logloss, 3)} against ${ctx.num(fw.logloss_constant, 3)} for constant weights (${better ? "the new model ahead" : "the old model ahead"}${g && g.lo != null ? `; gap 95% ${ctx.num(g.lo, 3)} to ${ctx.num(g.hi, 3)}` : ""}).`;
  }
  function describeModel(ctx) {
    const m = T(ctx).model;
    if (!m) return "";
    const c = m.check, last = c.thirds[2], first = c.thirds[0], gap = c.equal_minus_fitted, h = V(ctx).hidden;
    const pct = (x) => ctx.pct(x), x2 = (b) => "×" + ctx.num(Math.exp(b), 2);
    const W = m.weights, pts = m.stage.points;
    const nClear = W.reduce((s, w) => s + STAGES.filter((_, j) => clearW(w, j)).length, 0);
    const cell = (w, j) => `<td class="num">${clearW(w, j) ? `<b>${x2(w.est[j])}</b>` : x2(w.est[j])}<div class="sub">${w.lo[j] != null ? `${ctx.num(Math.exp(w.lo[j]), 2)} to ${ctx.num(Math.exp(w.hi[j]), 2)}` : ""}</div></td>`;
    const rows = m.feats.map((f, i) => `<tr><td style="white-space:normal"><b>${ctx.esc(m.labels[f].replace(" (per SD)", ""))}</b><div class="sub" style="white-space:normal">${SIGNS[f] || ""}</div></td>
      ${STAGES.map((_, j) => cell(W[i], j)).join("")}</tr>`).join("");
    const head = STAGES.map((s, j) => `<th class="num">${s}<div class="sub">leader at ${Math.round(pts[j] * 100)}%</div></th>`).join("");
    const cg = c.constant_minus_fitted;
    const vsConstant = c.logloss_constant != null ? ` The constant-weight model it replaced (one weight per sign for the whole game, no penalty) gets ${pct(c.acc_constant)} and log loss ${ctx.num(c.logloss_constant, 3)}${cg && cg.lo != null ? ` (gap 95% ${ctx.num(cg.lo, 3)} to ${ctx.num(cg.hi, 3)})` : ""}, on the same games that were used to choose the new one. ${forwardText(ctx, c.forward)}` : "";
    return `<div class="model-desc">
      <p><b>What it is.</b> At the end of every turn the model gives each player a chance of going on to win, using only what the whole table can see. The top threat is whoever has the highest chance at that moment. It is fit on ${m.games} games and ${m.states.toLocaleString("en-US")} turn ends.</p>
      <p><b>What it looks at.</b> ${m.feats.length} signs per player. Each is compared with the other players at the same moment, so what counts is being ahead of the table, not the raw number. How much each sign counts changes as the game goes on.</p>
      <div class="panel table-wrap"><table><thead><tr><th>Sign</th>${head}</tr></thead><tbody>${rows}</tbody></table></div>
      <p class="note">Weight: how much one standard deviation more of that sign multiplies a player's odds of winning, with the others held fixed, early in the game (the leader has ${Math.round(pts[0] * 100)}% of the points needed), in the middle (${Math.round(pts[1] * 100)}%) and late (${Math.round(pts[2] * 100)}%), each with its 95% interval. ×1 is no effect. Bold weights are clear of no effect (${nClear} of ${W.length * STAGES.length}); the rest cannot be told apart from zero with this many games, which is not the same as not mattering.</p>
      <p><b>How the weights are set.</b> Nobody chose them. Each turn end is treated as a choice among the seats in which the eventual winner is the one chosen, and the weights are the ones that make the real winners most likely (a conditional logit: a player's chance is e<sup>score</sup> divided by the sum of e<sup>score</sup> over the table, where the score is the weighted sum of their signs). Each weight can change in a straight line with how close the leader is to the target. The fit is cautious on purpose: a weight, or a change in a weight, is pulled toward zero and only moves away from it when the past games clearly back it up. Guests and bots are seats like anyone else.</p>
      <p><b>How it is kept honest.</b> The games are split into 5 groups, and each group is scored by a model fit only on the other 4, so no game is ever judged by a model that saw how it ended. Every threat number on the site, the badges included, uses those out-of-sample scores. The dozens of turn ends in one game share a winner, so the intervals count each game as one piece of evidence, not each turn.</p>
      <p><b>How well it works.</b> On games it was not fit on, the top threat goes on to win ${pct(c.acc)} of the time, against ${pct(c.acc_chance)} by chance: ${pct(first.acc)} in the first third of a game, rising to ${pct(last.acc)} in the last third. A simpler version that weighs every sign equally gets ${pct(c.acc_equal)}${gap.lo > 0 ? ", and the fitted weights beat it clearly" : ", which the fitted weights do not clearly beat"} (log loss ${ctx.num(c.logloss, 3)} against ${ctx.num(c.logloss_equal, 3)}; chance is ${ctx.num(c.logloss_chance, 3)}).${vsConstant}${h ? ` Going into the final turn, the top threat won ${h.top_won} of ${h.games} games in this view; the rest were hidden threats.` : ""}</p>
      <p><b>What it cannot see.</b> Hidden VP cards, which is how a hidden threat gets through. Which dev cards a player holds, only how many. Trades being negotiated, and anything said at the table. Spots more than 2 roads or ships away.</p>
      <p><b>What was tried and left out.</b> Weights that change over the game were first tried without the penalty, and predicted unseen games worse than one fixed set of weights: with this many games the changes were mostly noise. With the penalty they did better, mostly by being less sure of themselves early in the game, where fixed weights were overconfident; they are now a little too cautious late. Separate models for 3-player and for 4-or-more-player games did clearly worse, since each had half the games to learn from. Counting points as a share of the target, or by how many are still needed, made no difference. A separate count of 2:1 ports, and a penalty for a 2:1 port with no matching production, also made no detectable difference.</p>
      <p><b>How ports are known.</b> Port positions are read from each game's board, and the reading was checked against every 2:1 and 3:1 bank trade in the games: each was made by a player sitting on the matching port. On base-game boards, 2 of the 9 port positions never had a trade to confirm them and follow from the regular spacing of ports around the coast.</p>
    </div>`;
  }

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
        <p class="note"><b>How to read:</b> how much one standard deviation more of each visible sign raises a player's odds of going on to win, holding the others fixed. 1× is no effect. The dot is the middle of the game (the leader has half the points needed), with its 95% interval counting each game once; the ring is early (a fifth) and the tick late (four-fifths).</p>
        <div class="panel" style="margin-top:6px"><div class="chart" id="th-coef"></div></div>
        ${describeModel(ctx)}
        <h3 style="margin-top:24px">How well it calls the winner</h3>
        <p class="note">Share of turn ends where the top threat went on to win, scored only on games each model wasn't fit on. Constant weights is the model used before 26 Nov 2026 ${ctx.info("threat_check", "Fitted vs equal and constant weights")}.</p>
        <div class="panel table-wrap"><table><thead><tr><th>Part of the game</th><th class="num">Turn ends</th><th class="num">Fitted</th><th class="num">Constant weights</th><th class="num">Equal weights</th><th class="num">Chance</th><th class="num">Agree on the top threat</th></tr></thead><tbody>
          ${["First third", "Middle third", "Last third"].map((lab, i) => { const t = c.thirds[i]; return t ? `<tr><td>${lab}</td><td class="num">${t.states}</td><td class="num"><b>${pct(t.acc)}</b></td><td class="num">${t.acc_constant != null ? pct(t.acc_constant) : "n/a"}</td><td class="num">${pct(t.acc_equal)}</td><td class="num">${pct(t.acc_chance)}</td><td class="num">${pct(t.agree)}</td></tr>` : ""; }).join("")}
          <tr><td><b>Whole game</b></td><td class="num">${c.states}</td><td class="num"><b>${pct(c.acc)}</b></td><td class="num">${c.acc_constant != null ? pct(c.acc_constant) : "n/a"}</td><td class="num">${pct(c.acc_equal)}</td><td class="num">${pct(c.acc_chance)}</td><td class="num">${pct(c.agree)}</td></tr>
        </tbody></table></div>
        ${c.forward ? `<p class="note">${forwardText(ctx, c.forward)}</p>` : ""}
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
      const ex = (v) => (v == null ? undefined : Math.exp(v));
      const x2 = (v) => "×" + ctx.num(Math.exp(v), 2);
      ctx.Charts.forestPlot(el, {
        ref: 1, log: true, xTitle: "Odds multiplier per standard deviation", leftLabel: "less of a threat", rightLabel: "more of a threat",
        format: (x) => "×" + ctx.num(x, 2),
        names: { est: "Middle of the game", hollow: "Early", small: "Late", interval: "95% interval, middle" },
        rows: m.feats.map((f, i) => {
          const w = m.weights[i];
          return { label: m.labels[f].replace(" (per SD)", ""), est: ex(w.est[1]), lo: ex(w.lo[1]), hi: ex(w.hi[1]),
            hollow: ex(w.est[0]), small: ex(w.est[2]), color: "var(--data)",
            tip: `<div><b>${ctx.esc(m.labels[f])}</b></div>` + STAGES.map((s, j) => `<div>${s} <b>${x2(w.est[j])}</b>${w.lo[j] != null ? ` (${ctx.num(Math.exp(w.lo[j]), 2)} to ${ctx.num(Math.exp(w.hi[j]), 2)})` : ""}</div>`).join("") };
        }),
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
        <p class="note"><b>How to read:</b> after every turn, each player's chance of winning judged only from what the table could see (board VP, income, ports, reach, cards and dev cards in hand, closeness to the titles). Hidden VP cards don't count, which is how a hidden threat sneaks through. The model never saw this game's result.</p>
        <div class="panel"><div class="chart" id="th-game"></div></div>
        <details class="tv"><summary>How the threat model works</summary>${describeModel(ctx)}</details>
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
