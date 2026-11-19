/* Winning on cold dice (Luck page): one strip of dots per player, every decoded game in order, split by whether
   their dice paid at or above par or below it. A filled dot is a win. The same picture as the History tab's
   "needed good dice" beat, for everyone.
   Data: views[view].insights.cold_dice (scripts/insights.py cold_dice). */
(function () {
  "use strict";

  Object.assign(window.METHODS, {
    cold_dice: `<p><b>Par</b> is the number of cards a player's settlements and cities would have produced from the dice with average rolls, the expected count in "Dice luck: actual against expected": before every roll, each settlement adds 1 and each city 2 times the chance of each touching hex's number, skipping the hex under the robber. A game is on <b>cold dice</b> when the player got fewer cards from dice than that.</p>
      <p><b>Typical</b> is how many of those games the player would win at everyone else's rate: each game counts the share of games that all other seats in this view (guests and bots included) won on the same kind of dice, cold or at par, at the same table size. Cold dice lower everyone's chances, so this is a fairer yardstick than one win in n.</p>
      <p>The <b>range luck covers</b> is where the number of wins lands 95% of the time if each game is won at its typical chance. Wins outside it are more, or fewer, than luck explains.</p>
      <p>This question was asked after the History tab showed one player who had never won on cold dice, so it is exploratory. With every player compared in every view, some will land outside the range by luck alone.</p>`,
  });

  // How far a game's dice were from par. The side comes from the game's row, never from the sign of a rounded number.
  const parText = (g) => {
    const x = Math.abs(g.pct), side = g.cold ? "below" : "above";
    if (!g.cold && x === 0) return "at par";
    return x < 0.01 ? `less than 1% ${side} par` : `${Math.round(x * 100)}% ${side} par`;
  };
  const delta = (ctx, r, label) => {
    if (!r.games) return `${label}, no games yet.`;
    const d = r.wins - r.typical;
    const size = Math.abs(d) < 0.05 ? `${label}, right at typical` : `${label}, ${ctx.num(Math.abs(d), 1)} ${d > 0 ? "more" : "fewer"} wins than typical`;
    if (r.wins > r.hi) return `${size}: <b>more than luck explains</b>.`;
    if (r.wins < r.lo) return `${size}: <b>fewer than luck explains</b>.`;
    return `${size}.`;
  };

  function card(ctx, pid, r, gi) {
    const tip = (g) => {
      const x = gi[g.id];
      return `<b>${x ? `Game ${x.number}` : ctx.esc(g.id)}</b>${x ? `, ${ctx.fmtDate(x.date)}` : ""}<br>${g.won ? "Won" : "Lost"}. Dice ${parText(g)}.`;
    };
    const dots = (cold) => r.games.filter((g) => g.cold === cold).map((g, i, a) =>
      `<a class="cd-dot${g.won ? " won" : ""}" href="#/game/${encodeURIComponent(g.id)}" tabindex="-1" data-tip="${ctx.esc(tip(g))}" style="--o:${(i / Math.max(1, a.length)).toFixed(3)}"></a>`).join("");
    const row = (cold, label, part) => `<div class="cd-row"><span>${label}</span><span class="cd-n">${part.games ? `won <b>${part.wins}</b> of ${part.games} · typical ${ctx.num(part.typical, 1)}` : "no games"}</span></div>
        <div class="cd-dots" aria-hidden="true">${dots(cold)}</div>`;
    return `<div class="cd-card" style="--c:${ctx.color(pid)}">
        <div class="cd-head">${ctx.who(pid)}</div>
        ${row(false, "Dice at or above par", r.par)}
        ${row(true, "Dice below par", r.cold)}
        <p class="cd-foot">${delta(ctx, r.cold, "On cold dice")} ${delta(ctx, r.par, "With good dice")}</p>
      </div>`;
  }

  // Best on cold dice first: wins above typical on cold dice. Players with no cold-dice games yet go last.
  const coldEdge = (r) => r.cold.wins - r.cold.typical;
  function ranked(ctx, cd) {
    return ctx.S.players.map((p) => p.id).filter((id) => cd.players[id]).sort((a, b) => {
      const x = cd.players[a], y = cd.players[b];
      return (y.cold.games > 0) - (x.cold.games > 0) || coldEdge(y) - coldEdge(x) || y.cold.games - x.cold.games;
    });
  }

  (window.Hooks.findings = window.Hooks.findings || []).push({
    html(ctx) {
      const cd = (ctx.S.insights || {}).cold_dice;
      if (!cd) return null;
      const order = ranked(ctx, cd);
      if (!order.length) return null;
      const gi = Object.fromEntries(ctx.ROOT.views.all.games.map((g) => [g.id, g]));
      const link = (g) => { const x = gi[g.id]; return `<a href="#/game/${encodeURIComponent(g.id)}">${x ? x.number : ctx.esc(g.id)}</a>`; };
      const rows = order.map((id) => {
        const r = cd.players[id], wins = r.games.filter((g) => g.cold && g.won);
        return [ctx.who(id), r.cold.games, r.cold.wins, ctx.num(r.cold.typical, 1), r.par.games, r.par.wins, ctx.num(r.par.typical, 1),
          wins.length ? wins.map(link).join(", ") : "none"];
      });
      return `<section class="block">
        <h2>Winning on cold dice ${ctx.info("cold_dice", "Winning on cold dice")}</h2>
        <p class="note"><b>How to read:</b> one dot per game, oldest first. Each player's top row is the games where their dice paid at least par: the cards their settlements and cities should produce with average rolls. The bottom row is the games where the dice paid less, cold dice. A filled dot is a win and a ring is a loss. Typical is how many of those games they would win at the rate everyone else wins on the same kind of dice, at the same table size; cold dice make everyone win less. Point at a dot to see the game (tap it on a phone), and click it (tap again) to open the game. Best on cold dice first; players with at least ${cd.min_games} decoded games.</p>
        <div class="cd-grid" id="cd-grid">${order.map((id) => card(ctx, id, cd.players[id], gi)).join("")}</div>
        ${ctx.tableView([{ label: "Player" }, { label: "Cold games", num: 1 }, { label: "Cold wins", num: 1 }, { label: "Cold typical", num: 1 },
          { label: "Par games", num: 1 }, { label: "Par wins", num: 1 }, { label: "Par typical", num: 1 }, { label: "Games won on cold dice" }], rows, "Show as table, with links to the cold-dice wins")}
      </section>`;
    },
    draw(ctx) {
      // Touch: the first tap on a dot shows which game it is; a second tap on the same dot opens it.
      const grid = document.getElementById("cd-grid"), C = ctx.Charts;
      if (!grid || !C || !C.Tip) return;
      let touch = false, armed = null;
      grid.addEventListener("pointerdown", (e) => { touch = e.pointerType === "touch" || e.pointerType === "pen"; });
      grid.addEventListener("click", (e) => {
        const d = e.target.closest(".cd-dot");
        if (!d || !touch || armed === d) return;
        e.preventDefault();
        armed = d;
        const r = d.getBoundingClientRect();
        C.Tip.show(d.getAttribute("data-tip"), r.left + r.width / 2, r.top);
      });
    },
  });

  // topics.js ranks the same way for the heading, so the heading and the first card always agree.
  window.ColdDice = { ranked, coldEdge };
})();
