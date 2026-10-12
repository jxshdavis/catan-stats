/* Resources: which resources the starting settlements sit on and whether that predicts the winner (Findings),
   each player's favorite resource (player page) and everyone's resource mix (Play style).
   Data: stats.json "resources" (all games) and views[view].resources (scripts/resources.py). */
(function () {
  "use strict";
  if (!document.querySelector('link[href="resources.css"]')) {
    const l = document.createElement("link");
    l.rel = "stylesheet"; l.href = "resources.css";
    document.head.appendChild(l);
  }

  const RES = ["wood", "brick", "sheep", "wheat", "ore"];
  const LABEL = { wood: "Wood", brick: "Brick", sheep: "Sheep", wheat: "Wheat", ore: "Ore" };
  const sw = (r) => `<span class="res-sw" style="--c:var(--res-${r})" aria-hidden="true"></span>`;
  const resName = (r) => `<span class="res-name">${sw(r)}${LABEL[r]}</span>`;
  const pts = (ctx, x, d = 1) => `${ctx.fmtSigned(x * 100, d)} pts`;

  Object.assign(window.METHODS, {
    res_win: `<p><b>Data.</b> For each seat, the number dots under its two starting settlements split by resource at the moment each was placed (a corner on a wheat 6 and an ore 9 is 5 wheat dots and 4 ore dots). Fog, desert and sea count 0. No opening has touched gold so far, so gold is left out.</p>
      <p><b>Model.</b> A conditional logit stratified by game, every seat in the choice set (guests and bots too): P(i wins) ∝ exp(Σ<sub>r</sub> b<sub>r</sub> x<sub>ir</sub>), where x<sub>ir</sub> is the seat's dots on resource r minus the table mean. Firth penalty, 95% profile penalized-likelihood intervals. The chart shows e<sup>b</sup>, the odds multiplier per extra dot.</p>
      <p><b>Does the mix matter?</b> A likelihood ratio test of the five-coefficient model against one shared coefficient on total dots, both fit by maximum likelihood, 4 degrees of freedom. The bottom row of the chart is that shared coefficient.</p>
      <p><b>Exploratory.</b> This question was added after the two tested questions were fixed, and it makes five comparisons, so read single p values near 0.05 with care. Views under 30 games reuse the all-games numbers.</p>`,
    res_missing: `<p>Seats whose two starting settlements touched none of a resource. <b>Expected by chance</b>: Σ k<sub>g</sub>/n<sub>g</sub>, with k<sub>g</sub> such seats in a game of n<sub>g</sub>. The band is the central 95% of the exact Poisson-binomial distribution of wins, and p is the exact two-sided p value.</p>
      <p><b>Expected from their dots</b> uses the total-dots model instead: each seat's win chance is e<sup>b·x</sup> / Σ e<sup>b·x</sup>, with x its total opening dots minus the table mean. If the shortfall is about missing the resource and not just fewer dots, wins stay below this number too.</p>`,
    res_mix: `<p><b>Share.</b> Pooled over the player's games: their dots (or cards) on each resource divided by their total. <b>Table</b>: the same for everyone else at those tables, guests and bots included. The difference is in percentage points; the five differences add to 0, so leaning toward one resource is leaning away from the others.</p>
      <p><b>Opening dots</b> are the two starting settlements (the choice that is most clearly the player's). <b>Cards from dice</b> are every card rolled over the whole game, so they also reflect later settlements and cities, the robber and luck. Gold is left out.</p>
      <p><b>Intervals.</b> 95% game-cluster bootstrap (2,000 draws). The <b>favorite resource</b> is the one with the largest opening difference; it is called clear when its interval excludes 0. Players with 10 or more games.</p>`,
  });

  const viewRes = (ctx) => ctx.S.resources;

  // ---- Findings: starting resources and winning ------------------------------------------------
  (window.Hooks["findings-openings"] = window.Hooks["findings-openings"] || []).push({
    html(ctx) {
      const v = viewRes(ctx);
      const W = v && v.winning;
      if (!W) return null;
      const m = W.model;
      const best = RES.reduce((a, r) => (m.per[r].or > m.per[a].or ? r : a), RES[0]);
      const miss = RES.filter((r) => W.missing[r]).reduce((a, r) => (W.missing[r].p < W.missing[a].p ? r : a), RES[0]);
      const ms = W.missing[miss];
      const mixMatters = m.lr.p < 0.05;
      return `<section class="block">
        <h2>Starting resources ${ctx.info("res_win", "Starting resources and winning")}</h2>
        <p class="note">Does it matter <i>which</i> resources your two starting settlements sit on, or only how many dots they have? Each opening is split by resource and compared with the rest of the table.${v.winning_source === "all games" ? ` This view has ${v.view_games} games, under the 30 a model needs, so these numbers are from all games.` : ""}</p>
        <div class="tiles">
          <div class="tile"><div class="v">${LABEL[best]}</div><div class="k">Worth the most per dot</div><div class="s">each extra ${best} dot: ×${ctx.num(m.per[best].or, 2)} odds of winning (95% ${ctx.num(m.per[best].or_ci[0], 2)} to ${ctx.num(m.per[best].or_ci[1], 2)}); any dot: ×${ctx.num(m.total.or, 2)}</div></div>
          <div class="tile"><div class="v">${mixMatters ? "Yes" : "Not detected"}</div><div class="k">Does the mix matter beyond total dots?</div><div class="s">p = ${ctx.num(m.lr.p, 2)}; ${mixMatters ? "some resources are worth more than others" : `every resource's dots help about the same, as far as ${m.games} games can tell`}</div></div>
          <div class="tile"><div class="v">${ms.wins} vs ${ctx.num(ms.expected, 1)}</div><div class="k">Wins by openings with no ${miss}</div><div class="s">against chance, p = ${ctx.num(ms.p, 3)}; ${ctx.num(ms.expected_dots, 1)} expected given their dots (p = ${ctx.num(ms.p_dots, 3)})</div></div>
        </div>
        <h3 style="margin-top:20px">Odds of winning per extra dot, by resource</h3>
        <p class="note"><b>How to read:</b> each dot is how much one more opening dot on that resource (compared with the table) multiplies the odds of winning. 1× means no effect; further right means it helps more. The lines are 95% intervals. The bottom row counts every dot the same, for comparison. Overlapping rows mean the data can't tell those resources apart.</p>
        <div class="panel" style="margin-top:6px"><div class="chart" id="res-or"></div></div>
        <h3 style="margin-top:24px">Openings that miss a resource ${ctx.info("res_missing", "Openings that miss a resource")}</h3>
        <p class="note"><b>How to read:</b> each bar is the wins by players whose two starting settlements touched none of that resource. The tick is what chance gives, the gray box the range chance covers 95% of the time. A bar below its box won less than luck explains. Fewer dots overall can also explain a shortfall, so the table adds what their dot totals predict.</p>
        <div class="panel" style="margin-top:6px"><div class="chart" id="res-miss"></div></div>
        <div class="panel table-wrap" style="margin-top:12px"><table><thead><tr><th>Opening with no</th><th class="num">Seats</th><th class="num">Wins</th><th class="num">Expected by chance</th><th class="num">Expected from their dots</th></tr></thead><tbody>
          ${RES.filter((r) => W.missing[r]).map((r) => { const x = W.missing[r]; return `<tr><td>${resName(r)}</td><td class="num">${x.seats}</td><td class="num"><b>${x.wins}</b></td><td class="num">${ctx.num(x.expected, 1)} <span class="sub">p = ${ctx.num(x.p, 2)}</span></td><td class="num">${ctx.num(x.expected_dots, 1)} <span class="sub">p = ${ctx.num(x.p_dots, 2)}</span></td></tr>`; }).join("")}
        </tbody></table></div>
        <h3 style="margin-top:24px">How many different resources the opening touches</h3>
        <p class="note">Same reading as above, grouped by how many of the five resources the two starting settlements reach.</p>
        <div class="panel" style="margin-top:6px"><div class="chart" id="res-distinct"></div></div>
        <p class="note">Exploratory: this wasn't one of the two questions fixed in advance, and five resources means five chances for a fluke.</p>
      </section>`;
    },
    draw(ctx) {
      const v = viewRes(ctx);
      const W = v && v.winning;
      if (!W) return;
      const C = ctx.Charts, m = W.model;
      const el = document.getElementById("res-or");
      if (el) C.forestPlot(el, {
        ref: 1, log: true, legend: false, xTitle: "Odds multiplier per extra opening dot", leftLabel: "hurts", rightLabel: "helps",
        format: (x) => "×" + ctx.num(x, 2),
        rows: RES.map((r) => ({ label: resName(r), est: m.per[r].or, lo: m.per[r].or_ci[0], hi: m.per[r].or_ci[1], color: `var(--res-${r})`,
          tip: `${LABEL[r]}: ×${ctx.num(m.per[r].or, 2)} per dot (${ctx.num(m.per[r].or_ci[0], 2)} to ${ctx.num(m.per[r].or_ci[1], 2)})` }))
          .concat([{ label: "<b>Any dot</b>", est: m.total.or, lo: m.total.or_ci[0], hi: m.total.or_ci[1], color: "var(--data)",
            tip: `Every dot counted the same: ×${ctx.num(m.total.or, 2)} (${ctx.num(m.total.or_ci[0], 2)} to ${ctx.num(m.total.or_ci[1], 2)})` }]),
      });
      const bars = (obj, keys, lab) => keys.filter((k) => obj[k]).map((k) => { const x = obj[k]; return {
        label: lab(k), value: x.wins, expected: x.expected, lo: x.lo, hi: x.hi,
        tip: `${x.wins} wins from ${x.seats} seats; ${ctx.num(x.expected, 1)} expected by chance (range ${x.lo} to ${x.hi}); ${ctx.num(x.expected_dots, 1)} from their dots` }; });
      const mi = document.getElementById("res-miss");
      if (mi) C.nullBars(mi, { legend: true, height: 220, format: (x) => ctx.num(x, 1), names: { value: "Wins" },
        bars: bars(W.missing, RES, (r) => "No " + r), ariaLabel: "Wins by openings that miss each resource, against chance" });
      const di = document.getElementById("res-distinct");
      if (di) C.nullBars(di, { legend: true, height: 200, format: (x) => ctx.num(x, 1), names: { value: "Wins" },
        bars: bars(W.distinct, ["1", "2", "3", "4", "5"], (c) => `${c} ${c === "1" ? "resource" : "resources"}`),
        ariaLabel: "Wins by number of different resources at the opening, against chance" });
    },
  });

  // ---- Resource mix table, shared by the player page and Play style ------------------------------
  function mixCells(ctx, mix, maxAbs, favK = -1) {
    return RES.map((r, k) => {
      const d = mix.diff[k], clear = mix.lo[k] > 0 || mix.hi[k] < 0;
      const t = d > 0 ? Math.min(1, d / maxAbs) : 0;
      const tip = `${ctx.pct(mix.share[k], 1)} of theirs, ${ctx.pct(mix.table[k], 1)} for the rest of the table; ${pts(ctx, d)} (95% ${pts(ctx, mix.lo[k])} to ${pts(ctx, mix.hi[k])})`;
      return `<td><div class="cell res-cell${clear ? " clear" : ""}" style="--rc:var(--res-${r});--t:${t.toFixed(2)}" title="${ctx.esc(tip)}"><b>${k === favK ? `<span class="fav-star" title="Favorite">★</span> ` : ""}${ctx.pct(mix.share[k])}</b><span>${clear ? "<strong>" : ""}${pts(ctx, d)}${clear ? "</strong>" : ""}</span></div></td>`;
    }).join("");
  }

  // ---- Player page -----------------------------------------------------------------------------
  (window.Hooks["player-head"] = window.Hooks["player-head"] || []).push({
    html(ctx, pid) {
      const v = viewRes(ctx), pr = v && v.players[pid];
      if (!pr) return null;
      const f = pr.favorite;
      return `<p class="fav-line">${sw(f.resource)}<span>Favorite resource: <b>${LABEL[f.resource]}</b>. ${ctx.pct(f.share)} of ${ctx.esc(ctx.P[pid].name)}'s opening dots are on ${f.resource}, against ${ctx.pct(f.table)} for the people they play with${f.clear ? "" : " (a lean within noise)"}.</span></p>`;
    },
  });
  (window.Hooks.player = window.Hooks.player || []).unshift({
    html(ctx, pid) {
      const v = viewRes(ctx), pr = v && v.players[pid];
      if (!pr) return null;
      const name = ctx.esc(ctx.P[pid].name);
      const rows = [["Opening dots", pr.opening, pr.favorite], ["Cards from dice", pr.dice, pr.dice_favorite]].filter((x) => x[1]);
      const maxAbs = Math.max(0.02, ...rows.flatMap(([, m]) => m.diff.map(Math.abs)));
      const f = pr.favorite, df = pr.dice_favorite;
      return `<section class="block" id="res-section">
        <h2>Resources ${ctx.info("res_mix", "Resource mix vs the table")}</h2>
        <div class="tiles">
          <div class="tile"><div class="v res-v">${sw(f.resource)}${LABEL[f.resource]}</div><div class="k">Favorite resource</div><div class="s">${pts(ctx, f.diff)} of opening dots vs the table (95% ${pts(ctx, f.lo)} to ${pts(ctx, f.hi)})${f.clear ? "" : "; within noise"}</div></div>
          ${df ? `<div class="tile"><div class="v res-v">${sw(df.resource)}${LABEL[df.resource]}</div><div class="k">Collects the most of, vs the table</div><div class="s">${pts(ctx, df.diff)} of cards from dice (95% ${pts(ctx, df.lo)} to ${pts(ctx, df.hi)})</div></div>` : ""}
        </div>
        <p class="note" style="margin-top:12px"><b>How to read:</b> the big number is the share of ${name}'s opening dots (or dice cards) on each resource; underneath, how many percentage points that is above or below everyone else at the same tables. Darker cells lean more toward that resource; bold differences are clear of noise. Over ${pr.opening.games} games.</p>
        <div class="panel res-panel" style="padding:14px"><div class="table-wrap"><table class="matrix res-matrix"><thead><tr><th></th>${RES.map((r) => `<th class="colh" scope="col">${resName(r)}</th>`).join("")}</tr></thead>
          <tbody>${rows.map(([l, m, fv]) => `<tr><th class="rowh" scope="row">${l}</th>${mixCells(ctx, m, maxAbs, fv ? RES.indexOf(fv.resource) : -1)}</tr>`).join("")}</tbody></table></div></div>
      </section>`;
    },
  });

  // ---- Play style --------------------------------------------------------------------------------
  (window.Hooks.style = window.Hooks.style || []).push({
    html(ctx) {
      const v = viewRes(ctx);
      if (!v || !Object.keys(v.players).length) return null;
      return `<section class="block">
        <h2>Resource mix ${ctx.info("res_mix", "Resource mix vs the table")}</h2>
        <p class="note">Which resources each player builds around. The big number is the share of their opening dots (or cards from dice) on that resource; underneath, how many percentage points that is above or below the rest of the same tables. Darker cells lean harder toward that resource, and bold differences are clear of noise. The ★ marks each player's favorite.</p>
        <div class="race-ctl" id="res-ctl" style="margin-top:12px"><span class="chips"><button type="button" class="chip on" data-k="opening">Opening dots</button><button type="button" class="chip" data-k="dice">Cards from dice</button></span></div>
        <div class="panel res-panel" style="padding:14px;margin-top:8px"><div class="table-wrap" id="res-mix"></div></div>
        <p class="note" id="res-mix-foot"></p>
      </section>`;
    },
    draw(ctx) {
      const v = viewRes(ctx), box = document.getElementById("res-mix");
      if (!v || !box) return;
      const order = ctx.S.players.filter((p) => v.players[p.id]).map((p) => p.id);
      const draw = (key) => {
        const mixes = order.map((id) => [id, v.players[id][key]]).filter(([, m]) => m);
        const maxAbs = Math.max(0.02, ...mixes.flatMap(([, m]) => m.diff.map(Math.abs)));
        const t = v.table[key];
        box.innerHTML = `<table class="matrix res-matrix"><thead><tr><th></th>${RES.map((r) => `<th class="colh" scope="col">${resName(r)}</th>`).join("")}</tr></thead><tbody>
          ${mixes.map(([id, m]) => { const fav = v.players[id][key === "opening" ? "favorite" : "dice_favorite"]; return `<tr><th class="rowh" scope="row">${ctx.who(id)}</th>${mixCells(ctx, m, maxAbs, fav ? RES.indexOf(fav.resource) : -1)}</tr>`; }).join("")}
          ${t ? `<tr class="res-all"><th class="rowh" scope="row">Every seat</th>${t.map((x) => `<td><div class="cell res-cell"><b>${ctx.pct(x)}</b><span>board mix</span></div></td>`).join("")}</tr>` : ""}
        </tbody></table>`;
        document.getElementById("res-mix-foot").textContent = key === "opening"
          ? `Opening dots from ${v.games.opening} games. The last row is every seat pooled, which mostly reflects the boards: a base board has 3 brick and 3 ore hexes and 4 of each of the others.`
          : `Cards from dice over ${v.games.dice} games, whole game. This also reflects later cities, the robber and luck. The last row is every seat pooled.`;
      };
      const ctl = document.getElementById("res-ctl");
      ctl.querySelectorAll("button[data-k]").forEach((b) => b.addEventListener("click", () => {
        ctl.querySelectorAll("button[data-k]").forEach((x) => x.classList.toggle("on", x === b));
        draw(b.dataset.k);
      }));
      draw("opening");
    },
  });
})();
