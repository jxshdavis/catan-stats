/* Dev cards page (#/devcards): what comes out of the deck, who buys and plays what, and whether it changes
   who wins. Renders stats.json "devcards" (scripts/devcards.py, all games only). Every heading, tag and
   sentence is worked out from the numbers, so the page stays right as games are added. */
(function () {
  "use strict";
  const CARD = { knight: "Knight", victory_point: "Victory point", road_building: "Road building", monopoly: "Monopoly", year_of_plenty: "Year of plenty" };
  const SHORT = { knight: "Knight", victory_point: "VP", road_building: "Road b.", monopoly: "Monopoly", year_of_plenty: "Y. of plenty" };
  const ORDER = ["knight", "victory_point", "road_building", "monopoly", "year_of_plenty"];
  const CARD_COLOR = { knight: "var(--p1)", victory_point: "var(--p2)", road_building: "var(--p3)", monopoly: "var(--p4)", year_of_plenty: "var(--p5)" };
  const RES_LABEL = { wood: "Wood", brick: "Brick", sheep: "Sheep", wheat: "Wheat", ore: "Ore" };
  const PH = [["early", "First third"], ["middle", "Middle third"], ["late", "Last third"]];
  const MIN_MARK = 10; // games a player needs for a table marker (statlib GUARDS player_rows)

  const sum = (a) => a.reduce((s, v) => s + v, 0);
  const pct = (x, d = 0) => (x === null || x === undefined ? "n/a" : (x * 100).toFixed(d) + "%");
  const signed = (x, d = 1) => { const a = Math.abs(x).toFixed(d); return (+a === 0 ? "" : x > 0 ? "+" : "−") + a; };
  const pts = (x, d = 1) => (x === null || x === undefined ? "n/a" : signed(x * 100, d));
  const ci = (c, d = 1) => (c ? `${pts(c[0], d)} to ${pts(c[1], d)}` : "no interval");
  const isClear = (c, ref = 0) => !!c && (c[0] > ref || c[1] < ref);
  const join = (a) => (a.length <= 1 ? a.join("") : a.slice(0, -1).join(", ") + " and " + a[a.length - 1]);
  const legend = (esc, items) => `<ul class="legend">${items.map(([c, l]) => `<li><span class="sw box" style="--c:${c}"></span>${esc(l)}</li>`).join("")}</ul>`;

  // Stacked bars in charts.js's look: 2px gaps between segments, rounded top, hover tooltip per bar.
  function stacked(C, container, opts) {
    container.insertAdjacentHTML("beforeend", legend(C.esc, opts.keys.map((k) => [opts.color(k), opts.name(k)])));
    const host = document.createElement("div");
    container.appendChild(host);
    let lastW = 0;
    const draw = () => {
      const W = Math.floor(host.clientWidth);
      if (W < 160 || W === lastW) return;
      lastW = W; host.innerHTML = "";
      const H = opts.height || 240, m = { t: 14, r: 8, b: 26, l: 38 }, iw = W - m.l - m.r, ih = H - m.t - m.b;
      const totals = opts.bars.map((b) => sum(opts.keys.map((k) => b.values[k] || 0)));
      const yt = C.niceTicks(0, Math.max(...totals, 1), 4), ymax = yt[yt.length - 1];
      const Y = (v) => m.t + ih - (v / ymax) * ih;
      const slot = iw / opts.bars.length, bw = Math.max(6, Math.min(40, slot * 0.62));
      const svg = C.svgEl("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.ariaLabel }, host);
      for (const t of yt) {
        C.svgEl("line", { x1: m.l, x2: m.l + iw, y1: Y(t), y2: Y(t), stroke: "var(--hair)", "stroke-width": 1 }, svg);
        C.svgEl("text", { x: m.l - 8, y: Y(t) + 4, "text-anchor": "end" }, svg).textContent = t;
      }
      opts.bars.forEach((b, i) => {
        const cx = m.l + slot * i + slot / 2, x = cx - bw / 2;
        const g = C.svgEl("g", { tabindex: 0, role: "img", "aria-label": `${b.label}: ${opts.keys.map((k) => `${opts.name(k)} ${opts.fmt(b.values[k] || 0)}`).join(", ")}` }, svg);
        C.svgEl("rect", { x: m.l + slot * i, y: m.t, width: slot, height: ih, fill: "transparent" }, g);
        let acc = 0;
        const live = opts.keys.filter((k) => (b.values[k] || 0) > 0);
        live.forEach((k, j) => {
          const v = b.values[k], y0 = Y(acc), y1 = Y(acc + v), top = j === live.length - 1;
          const h = Math.max(0, y0 - y1 - (j ? 2 : 0)), r = Math.min(4, h);
          if (h > 0) C.svgEl("path", { class: "stk-seg", fill: opts.color(k),
            d: top ? `M${x},${y1 + h}V${y1 + r}Q${x},${y1} ${x + r},${y1}H${x + bw - r}Q${x + bw},${y1} ${x + bw},${y1 + r}V${y1 + h}Z`
              : `M${x},${y1}H${x + bw}V${y1 + h}H${x}Z` }, g);
          acc += v;
        });
        if (opts.total) C.svgEl("text", { x: cx, y: Y(acc) - 5, "text-anchor": "middle", class: "lbl" }, g).textContent = opts.total(acc, b);
        C.svgEl("text", { x: cx, y: m.t + ih + 17, "text-anchor": "middle" }, svg).textContent = b.label;
        const show = (e) => {
          let px, py;
          if (e && e.clientX !== undefined) { px = e.clientX; py = e.clientY; } else { const rc = g.getBoundingClientRect(); px = rc.left + rc.width / 2; py = rc.top; }
          C.Tip.show(`<div><b>${C.esc(b.title || b.label)}</b></div>` + opts.keys.slice().reverse().map((k) => `<div class="row"><span class="hex" style="--c:${opts.color(k)}"></span>${C.esc(opts.name(k))} <b>${opts.fmt(b.values[k] || 0)}</b></div>`).join("") + (b.foot ? `<div>${b.foot}</div>` : ""), px, py);
        };
        g.addEventListener("pointermove", show); g.addEventListener("pointerleave", () => C.Tip.hide());
        g.addEventListener("focus", () => show()); g.addEventListener("blur", () => C.Tip.hide());
      });
      C.svgEl("line", { x1: m.l, x2: m.l + iw, y1: Y(0), y2: Y(0), stroke: "var(--axis)", "stroke-width": 1 }, svg);
    };
    draw();
    if ("ResizeObserver" in window) new ResizeObserver(draw).observe(host); else window.addEventListener("resize", draw);
  }

  function render(c) {
    const C = c.Charts, esc = c.esc, D = c.ROOT.devcards, main = c.main;
    if (!D || !D.draw) {
      main.innerHTML = `<h1>Dev cards</h1><p class="empty">Not enough decoded replays yet.</p>`;
      return;
    }
    const $ = (id) => document.getElementById(id);
    const P = c.ROOT.views.all.players.reduce((o, p) => ((o[p.id] = p), o), {});
    const pname = (pid) => (P[pid] ? P[pid].name : String(pid));
    const EXP = D.expected_all;
    const players = D.players.slice().sort((a, b) => b.games - a.games);
    const regulars = players.filter((p) => p.games >= MIN_MARK);
    const dr = D.draw, la = D.largest_army, mono = D.monopoly, rt = D.robber_threat;

    // ---- Words that depend on the numbers -------------------------------------------------------------------
    const W = {};
    { // Which card
      const clr = ORDER.filter((k) => isClear(dr[k].ci));
      const zs = (k) => { const d = dr[k]; return d.ci ? Math.abs(d.effect) / ((d.ci[1] - d.ci[0]) / 2 || 1) : 0; };
      const top = ORDER.slice().sort((a, b) => zs(b) - zs(a))[0];
      W.draw = clr.length
        ? { tag: "clear", head: clr.length === 1 ? `${CARD[clr[0]]} draws do clearly ${dr[clr[0]].effect > 0 ? "better" : "worse"} than other cards` : `${join(clr.map((k) => CARD[k]))} stand out from the other cards`,
          text: `Buying a dev card is a choice, but which card comes out is luck, so a gap here is the card itself. Against every other card bought at the same point in the game: ${join(clr.map((k) => `${CARD[k]} ${pts(dr[k].effect)} points (${ci(dr[k].ci)})`))}.` }
        : { tag: "none", head: "It barely matters which card comes out",
          text: `Buying a dev card is a choice, but which card comes out is luck. Against every other card bought at the same point in the game, no card's 95% interval is clear of zero. ${CARD[top]} comes closest, at ${pts(dr[top].effect)} points.` };
      const v = dr.victory_point, wt = sum(Object.values(D.final_turn_buys));
      const part = v.effect > 0 && v.effect_nwt < v.effect / 2 ? ", so most of its edge is the card that ends the game" : v.effect > 0 && v.effect_nwt < v.effect ? ", so part of its edge is the card that ends the game" : "";
      W.drawNote = `The hollow dot skips the ${wt} cards bought on the turn the game was won. Victory point moves from ${pts(v.effect)} to ${pts(v.effect_nwt)} points${part}.`;
      const cells = [];
      ORDER.forEach((k) => PH.forEach(([p, lab]) => { const d = dr[k].phases[p]; if (isClear(d.ci)) cells.push(`${CARD[k]} bought in the ${lab.toLowerCase()}, where ${Math.round(d.win * d.n)} of its ${d.n} holders won (${pts(d.diff)} points, ${ci(d.ci)})`); }));
      W.phaseNote = (cells.length ? `● marks ${cells.length === 1 ? "the one cell" : `${cells.length} cells`} clear of zero: ${join(cells)}.` : "No cell is clear of zero.")
        + " With 15 cells, about one can clear zero by chance alone, so read these as leads, not findings.";
    }
    { // VP
      const vb = D.vp_by_buys, v5 = vb[vb.length - 1].cells;
      W.vp = { head: `Heavy buyers who drew two VP cards won ${pct(v5[2].win)}; with none, ${pct(v5[0].win)}`,
        text: `Among players who bought five or more dev cards, those who drew no VP cards won ${pct(v5[0].win)}, one VP card ${pct(v5[1].win)}, and two or more ${pct(v5[2].win)}. A VP card counts the same whenever it arrives; late in the game, it matters most when it's the winning point.` };
      const L = D.vp_luck;
      W.vpNote = L && L.diff !== null ? `Across everyone who bought a card, drawing at least half a VP card more than the deck predicted went with ${pts(L.diff)} points of win rate against drawing at least half a card fewer (${ci(L.ci)}), ${isClear(L.ci) ? "clear of noise" : "so the luck of the VP draw alone is not yet clear of noise"}. The 2+ VP group with 1–2 cards bought is only ${vb[0].cells[2].n} player-games.` : "";
    }
    { // Spending
      const hm = D.heavy_minus_light, g = D.spend_grid.rows;
      const rowWin = (r) => { const cs = r.cells.filter((x) => x.n); return sum(cs.map((x) => x.win * x.n)) / sum(cs.map((x) => x.n)); };
      const lo = rowWin(g[0]), hi = rowWin(g[2]), clr = isClear(hm.ci);
      W.spend = { tag: clr ? "clear" : "none",
        head: clr ? `Heavy dev buyers win ${hm.v > 0 ? "more" : "less"}, even at the same dice income` : hi > 2 * lo ? "Dice income decides games; dev cards ride along" : "Dev spending doesn't clearly change who wins",
        text: `Players in the bottom third of dice income won ${pct(lo)} of their games and the top third ${pct(hi)}. At the same income, heavy dev buyers did ${Math.abs(hm.v * 100).toFixed(1)} points ${hm.v >= 0 ? "better" : "worse"} than light ones (${ci(hm.ci)}). On average a player puts ${pct(D.avg_dev_share)} of their spending into dev cards.` };
      const b7 = D.by_buys[D.by_buys.length - 1], f0 = D.first_buy[0], fn = D.first_buy[D.first_buy.length - 1], cut = D.spend_grid.prod_cuts;
      W.spendNote = `${b7.k === 7 ? "Seven or more" : b7.k} cards won ${pct(b7.win)}, with ${b7.prod.toFixed(2)}× the table's dice income${b7.prod > 1.15 ? ": buying lots of dev cards is mostly a sign of having lots of cards" : ""}. A first card by turn 5 won ${pct(f0.win)} (income ${f0.prod === null ? "n/a" : f0.prod.toFixed(2) + "×"}) and never buying one ${pct(fn.win)} (${fn.prod === null ? "n/a" : fn.prod.toFixed(2) + "×"}). Income splits at ${cut[0].toFixed(2)}× and ${cut[1].toFixed(2)}× the table average.`;
    }
    { // When
      const bt = D.buy_timing, lastFifth = sum(D.buy_hist.slice(8).map((b) => sum(Object.values(b)))) / D.n_buys;
      W.when = { head: `${pct(bt.late)} of dev cards are bought in the last third of the game`,
        text: `${pct(bt.early)} of dev cards are bought in the first third of a game, ${pct(bt.middle)} in the middle and ${pct(bt.late)} in the last, with ${pct(lastFifth)} in the final fifth alone.${bt.late > 0.5 ? " Dev cards are where spare cards go once the board is built." : ""} ${D.deck.emptied ? `The deck ran out in ${D.deck.emptied} game${D.deck.emptied === 1 ? "" : "s"}.` : "The deck never ran out."}` };
    }
    if (la) { // Largest Army
      const kp = D.knights_played, k2 = kp.find((r) => r.k === 2), k3 = kp.find((r) => r.k === 3);
      const late = sum(D.la_first_hist.slice(8)) / la.awarded;
      W.army = { head: `The Largest Army holder wins ${pct(la.holder_win_rate)} of games, against ${pct(la.expected)} expected`,
        text: `${k2 && k3 ? `Two knights won ${pct(k2.win)} of the time; three, the number it takes to claim Largest Army, won ${pct(k3.win)}. ` : ""}The army comes late (${pct(late)} of first claims happen in the last fifth of the game) and changed hands in ${la.changed} of the ${la.awarded} games where someone claimed it.` };
    }
    if (rt) { // Robber
      const k = rt.knight, s = rt.seven, kc = isClear(k.ci, 1), sc = isClear(s.ci, 1), dc = isClear(rt.diff.ci);
      const verb = (x) => (x.ratio > 1 ? "go after" : "steer clear of");
      W.rob = { tag: kc || sc ? "clear" : "none",
        head: kc && sc && (k.ratio > 1) === (s.ratio > 1) ? `Knights and 7s both ${verb(k)} the top threat` : kc ? `Knights ${verb(k)} the top threat` : sc ? `7s ${verb(s)} the top threat` : "Robbers don't clearly pick on the top threat",
        text: `When there was a choice, knights robbed the top threat ${pct(k.rate)} of the time and 7s ${pct(s.rate)}, against ${pct(k.chance)} for a random pick. ${kc && sc ? "Both are clear of chance" : kc ? "Knights are clear of chance, 7s are not" : sc ? "7s are clear of chance, knights are not" : "Neither is clear of chance"}; the gap between them is ${dc ? "clear too" : "not"}.` };
    }
    if (mono) { // Monopoly
      const byN = Object.entries(mono.by_n), res = Object.entries(mono.by_res);
      const most = res.slice().sort((a, b) => b[1].n - a[1].n)[0][0], least = res.slice().sort((a, b) => a[1].mean - b[1].mean)[0][0];
      const g = c.ROOT.views.all.games.find((x) => x.id === mono.best.g);
      W.mono = { head: `A Monopoly takes ${mono.mean.toFixed(1)} cards${byN.length > 1 && byN[byN.length - 1][1].mean > byN[0][1].mean ? ", more at bigger tables" : ""}`,
        html: esc(`${mono.big} of ${mono.n} took six or more and ${mono.zero} came up empty. ${RES_LABEL[most]} is called most${most === least ? " and pays least" : `; ${RES_LABEL[least]} pays least`}. The biggest haul was `) + c.who(mono.best.p)
          + esc(`'s ${mono.best.take} ${mono.best.res} in `) + (g ? `<a href="#/game/${encodeURIComponent(g.id)}">game ${g.number}</a>` : "one game") + esc(`, which ${mono.best.win ? "they won" : "they still lost"}.`) };
    }
    { // Holding
      const hd = D.hold, kn = hd.knight || {}, rb = hd.road_building || {};
      const pre = regulars.filter((p) => p.pre !== null).sort((a, b) => b.pre - a.pre)[0];
      W.hold = { head: kn.next > 0.5 && rb.next > 0.5 ? "Most cards get played the first turn they can be" : `${pct(kn.next)} of knights are played as soon as the rules allow`,
        html: esc(`${pct(kn.next)} of knights and ${pct(rb.next)} of Road buildings are played on the next turn after buying. Only ${pct(D.knight_pre_roll)} of knights are played before rolling`) + (pre ? esc(", most often by ") + c.who(pre.p) + esc(` (${pct(pre.pre)})`) : "") + esc(`. And ${pct(D.unplayed.share)} of action cards never get played at all.`),
        pre };
    }
    if (regulars.length >= 2) { // Players
      const by = regulars.slice().sort((a, b) => b.buys - a.buys), most = by[0], least = by[by.length - 1];
      const bestRec = regulars.slice().sort((a, b) => b.wae - a.wae)[0];
      const mb = regulars.filter((p) => p.mono_n >= 10).sort((a, b) => b.mono_avg - a.mono_avg)[0];
      W.players = { head: `${pname(most.p)} buys the most dev cards, ${pname(least.p)} the fewest`,
        html: c.who(most.p) + esc(` buys ${most.buys.toFixed(1)} a game and puts ${pct(most.share)} of spending into them; `) + c.who(least.p)
          + esc(` buys ${least.buys.toFixed(1)}${least.first !== null ? `, usually starting around turn ${least.first}` : ""}${bestRec.p === least.p ? ", and has the best record of the regulars" : ""}. `)
          + (mb ? c.who(mb.p) + esc(` calls the best Monopolies, at ${mb.mono_avg.toFixed(1)} cards each.`) : "") };
    }

    // ---- Page --------------------------------------------------------------------------------------------
    const secs = [];
    const sec = (id, title, q, tag, head, verdict, body) => {
      secs.push({ id: "sec-" + id, slug: id, title });
      return `<section class="block" id="sec-${id}"><div class="sec-kicker"><span class="sec-q">${esc(q)}</span>${tag ? c.tagHtml(tag) : ""}<a class="sec-link" href="#/devcards/${id}" title="Link to this section" aria-label="Link to this section">#</a></div>
        <h2>${esc(head)}</h2>${verdict ? `<div class="verdict">${verdict}</div>` : ""}${body}</section>`;
    };
    const hid = D.winner_hidden_vp;
    const filtered = c.VIEW !== "all" ? `<p class="note">This page always counts every game with a replay; the Games filter doesn't change it.</p>` : "";
    main.innerHTML = `<div class="dc">
      <h1>Dev cards</h1>
      <p class="lede">Every game with a replay, played back card by card: ${D.n_buys.toLocaleString()} dev cards bought and ${D.n_plays.toLocaleString()} played. Who buys them, when, what comes out of the deck, and whether any of it changes who wins.</p>
      ${filtered}${c.tagKey()}
      <div class="tiles page-tiles" id="dc-tiles"></div>
      ${sec("draw", "Which card", "Which dev card do you want to pull?", W.draw.tag, W.draw.head, esc(W.draw.text), `
        <div class="chart" id="dc-forest"></div><p class="note">${esc(W.drawNote)}</p>
        <h3>By when the card was bought ${c.tagHtml("explore")}</h3>
        <p class="chart-sub">Win rate after drawing the card minus win rate after drawing anything else in the same third of the game, in percentage points. ● marks a cell whose 95% interval is clear of zero.</p>
        <div class="chart" id="dc-phase"></div><p class="note">${esc(W.phaseNote)}</p>`)}
      ${sec("vp", "Victory points", "What is a victory point card worth?", "desc", W.vp.head, esc(W.vp.text), `
        <p class="chart-sub">Win rate by VP cards drawn, for players who bought the same number of dev cards. The tick is the win rate expected from table size.</p>
        <div class="three-col" id="dc-vp"></div>
        <div class="two-col">
          <div><h3>Hidden points in the winner's hand</h3><p class="chart-sub">Games by how many VP cards the winner was still holding when the game ended.</p><div class="chart" id="dc-hidden"></div></div>
          <div><h3>Cards bought on the winning turn</h3><p class="chart-sub">Every dev card the winner bought on the turn they won.</p><div class="chart" id="dc-wt"></div></div>
        </div>${W.vpNote ? `<p class="note">${esc(W.vpNote)}</p>` : ""}`)}
      ${sec("spending", "Spending", "Does buying more dev cards win games?", W.spend.tag, W.spend.head, esc(W.spend.text), `
        <h3>Win rate by dev cards bought in the game</h3>
        <p class="chart-sub">The tick is the win rate expected from table size. The label above each bar is those players' dice income, relative to the table.</p>
        <div class="chart" id="dc-buys"></div>
        <h3>Win rate by dice income and share of spending on dev cards</h3>
        <p class="chart-sub">Every player in every game, split into thirds twice: by cards from dice relative to the table, and by the share of their spending that went to dev cards.</p>
        <div class="chart" id="dc-grid"></div>
        <h3>Win rate by the turn of the first dev card</h3>
        <p class="chart-sub">Own turns. The label above each bar is those players' dice income, relative to the table.</p>
        <div class="chart" id="dc-first"></div><p class="note">${esc(W.spendNote)}</p>`)}
      ${sec("timing", "When they're bought", "When does the group buy dev cards?", "desc", W.when.head, esc(W.when.text), `
        <p class="chart-sub">Every dev card bought, by how far through its game it was bought (tenths of the game's dice rolls), split by the card that came out.</p>
        <div class="chart" id="dc-when"></div>`)}
      ${W.army ? sec("army", "Largest Army", "How much is Largest Army worth?", "desc", W.army.head, esc(W.army.text), `
        <div class="tiles flush" id="dc-army-tiles"></div>
        <div class="two-col">
          <div><h3>Win rate by knights played</h3><p class="chart-sub">The label above each bar is the share holding Largest Army when the game ended. The tick: expected from table size.</p><div class="chart" id="dc-knights"></div></div>
          <div><h3>When Largest Army is first claimed</h3><p class="chart-sub">Games, by how far through the game someone first reached three knights.</p><div class="chart" id="dc-lafirst"></div><p class="chart-sub axis-cap">% through the game</p></div>
        </div>`) : ""}
      ${W.rob ? sec("robber", "Knights and the threat", "Do knights go after the leader?", W.rob.tag, W.rob.head, esc(W.rob.text), `
        <p class="chart-sub">Share of robberies that took from the top threat, when the threat and someone else could both be robbed. The tick is the share you'd get picking a victim at random.</p>
        <div class="chart" id="dc-rob"></div>
        <p class="note">The top threat is the opponent the <a href="#/winning">threat index</a> rates most likely to win at that moment, from what the table can see: board points, dice income, reach, ports, cards in hand and closeness to Longest Road and Largest Army. Knights: ${rt.knight.ratio.toFixed(2)}× chance (${rt.knight.ci[0].toFixed(2)} to ${rt.knight.ci[1].toFixed(2)}). 7s: ${rt.seven.ratio.toFixed(2)}× (${rt.seven.ci[0].toFixed(2)} to ${rt.seven.ci[1].toFixed(2)}).</p>`) : ""}
      ${W.mono ? sec("monopoly", "Monopoly", "What does a Monopoly take?", "desc", W.mono.head, W.mono.html, `
        <div class="three-col">
          <div><h3>By resource called</h3><p class="chart-sub">Average cards taken.</p><div class="chart" id="dc-mono-res"></div></div>
          <div><h3>By table size</h3><p class="chart-sub">Average cards taken.</p><div class="chart" id="dc-mono-n"></div></div>
          <div><h3>Every Monopoly</h3><p class="chart-sub">Monopolies by cards taken.</p><div class="chart" id="dc-mono-dist"></div></div>
        </div>`) : ""}
      ${sec("holding", "Holding cards", "How long do people sit on their cards?", "desc", W.hold.head, W.hold.html, `
        <div class="tiles flush" id="dc-hold-tiles"></div>
        <p class="chart-sub" style="margin-top:18px">Cards played, by own turns between buying and playing (one turn is the earliest the rules allow).</p>
        <div class="sm-grid" id="dc-hold"></div>`)}
      ${sec("players", "Players", "Who plays dev cards how?", "desc", W.players ? W.players.head : "Each player's dev card habits", W.players ? W.players.html : "", `
        <div class="two-col">
          <div><h3>Dev cards bought per game</h3><p class="chart-sub">Bar split by the cards that came out.</p><div class="chart" id="dc-pmix"></div></div>
          <div><h3>Share of spending on dev cards</h3><p class="chart-sub">Cards paid for dev cards over all cards paid.</p><div class="chart" id="dc-pshare"></div></div>
        </div>
        <h3>Every habit, side by side</h3>
        <div class="panel table-wrap" id="dc-table"></div>
        <div class="mk-key">${C.markerLegend()}<span class="note">The small arrows compare a player with the people at the same tables: +0.5 SD means a typical game puts them half a standard deviation above their tablemates on that stat. Colored arrows are clear of noise. Win vs expected uses z, wins against Σ 1/n. Players need ${MIN_MARK} games for a marker.</span></div>
        <p class="note">Hold is own turns between buying and playing a card. Unplayed counts action cards still in hand when the game ended. Monopoly cards counts every card taken with Monopoly, per game.</p>`)}
      ${sec("method", "Method", "How was this worked out?", "", "Method and limits", "", `<div class="prose"><ul id="dc-method"></ul></div>`)}
    </div>`;

    // ---- Tiles ---------------------------------------------------------------------------------------------
    $("dc-tiles").innerHTML = [
      { value: D.deck.avg_buys.toFixed(1), label: "Dev cards bought per game", sub: `of ${D.deck.size} in the deck; most in one game ${D.deck.max_buys}` },
      la ? { value: pct(la.holder_win_rate), label: "Largest Army holder's win rate", sub: `${pct(la.expected)} expected from table size` } : null,
      { value: D.games_won_on_final_turn_vp, label: "Games won by a VP card", sub: "bought on the winner's final turn" },
      { value: pct(1 - (hid["0"] || 0) / sum(Object.values(hid))), label: "Winners hiding a VP card", sub: `${hid["3"] || 0} were hiding three or more` },
      mono ? { value: mono.mean.toFixed(1), label: "Cards per Monopoly", sub: `${mono.zero} of ${mono.n} came up empty` } : null,
      { value: pct(D.unplayed.share), label: "Action cards never played", sub: `${D.unplayed.cards} cards, about ${D.unplayed.cards * 3} resources` },
    ].filter(Boolean).map(C.statTile).join("");

    // ---- Which card ------------------------------------------------------------------------------------------
    const span = Math.max(20, Math.ceil(Math.max(...ORDER.flatMap((k) => (dr[k].ci || [0, 0]).map((v) => Math.abs(v * 100)))) / 5) * 5);
    C.forestPlot($("dc-forest"), {
      rows: ORDER.map((k) => {
        const d = dr[k];
        return { label: CARD[k], est: d.effect * 100, lo: d.ci ? d.ci[0] * 100 : d.effect * 100, hi: d.ci ? d.ci[1] * 100 : d.effect * 100, hollow: d.effect_nwt * 100,
          color: isClear(d.ci) ? (d.effect > 0 ? "var(--vt-good)" : "var(--vt-bad)") : "var(--data)",
          tip: `<div><b>${CARD[k]}</b>, ${d.n} drawn</div><div>Holder won <b>${pct(d.win)}</b></div><div>Gap to other cards <b>${pts(d.effect)}</b> pts (${ci(d.ci)})</div><div>Skipping winning turns ${pts(d.effect_nwt)} pts (${ci(d.ci_nwt)})</div>` };
      }),
      ref: 0, format: (v) => signed(v, 1), domain: [-span, span],
      names: { est: "All buys", hollow: "Skipping buys on the winning turn", interval: "95% interval" },
      leftLabel: "Worse than other cards", rightLabel: "Better", xTitle: "Win rate, percentage points", rowHeight: 36,
      ariaLabel: "Win rate after drawing each dev card compared with other cards",
    });
    C.heatMatrix($("dc-phase"), {
      rows: ORDER, cols: PH.map((p) => p[0]), allowSelf: true,
      label: (id, kind) => (kind === "row" ? esc(CARD[id]) : esc(PH.find((p) => p[0] === id)[1])),
      corner: `<span class="mx-corner">Card drawn</span>`,
      diverging: { min: -0.3, mid: 0, max: 0.3 },
      cell: (k, p) => {
        const d = dr[k].phases[p], lab = PH.find((x) => x[0] === p)[1].toLowerCase();
        if (d.diff === null) return { value: 0, text: "–", sub: `${d.n} drawn`, tip: `${CARD[k]}, ${lab}: too few cards` };
        return { value: d.diff, text: (isClear(d.ci) ? "● " : "") + pts(d.diff), sub: `${d.n} drawn`,
          tip: `<div><b>${CARD[k]}, ${lab}</b></div><div>${d.n} drawn, holder won <b>${pct(d.win)}</b></div><div>Other cards then: ${pct(d.other_win)}</div><div>Gap ${pts(d.diff)} pts (${ci(d.ci)})</div>` };
      },
      scale: { low: "Worse than other cards", high: "Better" },
    });

    // ---- VP --------------------------------------------------------------------------------------------------
    D.vp_by_buys.forEach((r) => {
      const box = document.createElement("div");
      box.innerHTML = `<p class="chart-h">Bought ${r.label} dev cards<span class="sub">${sum(r.cells.map((x) => x.n))} player-games</span></p><div class="chart"></div>`;
      $("dc-vp").appendChild(box);
      C.nullBars(box.querySelector(".chart"), {
        bars: r.cells.map((x) => ({ label: `${x.k} VP`, value: (x.win || 0) * 100, expected: EXP * 100, note: `n=${x.n}`,
          tip: `<div><b>${x.k} VP cards</b>, bought ${r.label}</div><div>${x.n} player-games, won <b>${pct(x.win)}</b></div><div>Expected ${pct(EXP)}</div>` })),
        height: 190, format: (v) => v.toFixed(0) + "%", ariaLabel: `Win rate by VP cards drawn, for players who bought ${r.label} dev cards`,
      });
    });
    const nHid = sum(Object.values(hid));
    C.barChart($("dc-hidden"), {
      bars: [0, 1, 2, 3].map((k) => ({ label: k === 3 ? "3+ VP" : `${k} VP`, value: hid[String(k)] || 0, tip: `${hid[String(k)] || 0} games (${pct((hid[String(k)] || 0) / nHid)})` })),
      valueLabels: true, height: 190, ariaLabel: "Games by VP cards the winner held at the end",
    });
    C.barChart($("dc-wt"), {
      bars: ORDER.map((k) => ({ label: SHORT[k], value: D.final_turn_buys[k] || 0, color: CARD_COLOR[k], tip: `${D.final_turn_buys[k] || 0} ${CARD[k]} cards bought on a winning turn` })),
      valueLabels: true, height: 190, ariaLabel: "Dev cards bought on the winning turn",
    });

    // ---- Spending ----------------------------------------------------------------------------------------------
    C.nullBars($("dc-buys"), {
      bars: D.by_buys.map((r) => ({ label: r.k === 7 ? "7+" : String(r.k), value: r.win * 100, expected: r.exp * 100, note: `${r.prod.toFixed(2)}×`,
        tip: `<div><b>${r.k === 7 ? "7 or more" : r.k} dev cards bought</b></div><div>${r.n} player-games, won <b>${pct(r.win)}</b></div><div>Expected ${pct(r.exp)}</div><div>Dice income ${r.prod.toFixed(2)}× the table</div>` })),
      height: 230, format: (v) => v.toFixed(0) + "%", ariaLabel: "Win rate by dev cards bought",
    });
    const sg = D.spend_grid, INC = ["Low income", "Average income", "High income"], SH = ["Little on dev", "Some", "Heavy"];
    const gmax = Math.max(...sg.rows.flatMap((r) => r.cells.map((x) => x.win || 0)));
    C.heatMatrix($("dc-grid"), {
      rows: [0, 1, 2], cols: [0, 1, 2], allowSelf: true,
      label: (i, kind) => (kind === "row" ? INC[i] : `${SH[i]}<br><span class="sub">${i === 0 ? `under ${pct(sg.share_cuts[0])}` : i === 1 ? `${pct(sg.share_cuts[0])}–${pct(sg.share_cuts[1])}` : `over ${pct(sg.share_cuts[1])}`}</span>`),
      corner: `<span class="mx-corner">Dice income × share spent on dev</span>`,
      sequential: { min: 0, max: Math.ceil(gmax * 20) / 20 },
      cell: (r, k) => { const x = sg.rows[r].cells[k]; return { value: x.win || 0, text: pct(x.win), sub: `${x.n} player-games`,
        tip: `<div><b>${INC[r]}, ${SH[k].toLowerCase()}</b></div><div>${x.n} player-games, won <b>${pct(x.win)}</b></div><div>${pts(x.wae)} pts against table size</div>` }; },
      scale: { low: "Rarely wins", high: "Often wins" },
    });
    C.nullBars($("dc-first"), {
      bars: D.first_buy.filter((r) => r.n).map((r) => ({ label: r.label, value: r.win * 100, expected: (r.win - r.wae) * 100, note: `${r.prod.toFixed(2)}×`,
        tip: `<div><b>First dev card: ${r.label === "never" ? "never" : "turn " + r.label}</b></div><div>${r.n} player-games, won <b>${pct(r.win)}</b></div><div>Expected ${pct(r.win - r.wae)}</div><div>Dice income ${r.prod.toFixed(2)}× the table</div>` })),
      height: 210, format: (v) => v.toFixed(0) + "%", ariaLabel: "Win rate by turn of first dev card",
    });

    // ---- When --------------------------------------------------------------------------------------------------
    stacked(C, $("dc-when"), {
      keys: ORDER, color: (k) => CARD_COLOR[k], name: (k) => CARD[k], fmt: (v) => v,
      bars: D.buy_hist.map((b, i) => ({ label: `${i * 10}–${i * 10 + 10}%`, title: `${i * 10}–${i * 10 + 10}% through the game`, values: b, foot: `${sum(Object.values(b))} cards` })),
      total: (v) => v, height: 260, ariaLabel: "Dev cards bought by how far through the game",
    });

    // ---- Largest Army --------------------------------------------------------------------------------------------
    if (la) {
      $("dc-army-tiles").innerHTML = [
        { value: pct(la.holder_win_rate), label: "Holder's win rate", sub: `${la.holder_won} of ${la.awarded} games; ${pct(la.expected)} expected` },
        { value: `${la.awarded}<small> / ${la.games}</small>`, label: "Games where anyone claimed it", sub: "the rest never saw three knights" },
        { value: pct(la.first_frac), label: "Typical first claim", sub: "of the way through the game (median)" },
        { value: la.changed, label: "Games it changed hands", sub: "a second player took it" },
      ].map(C.statTile).join("");
      C.nullBars($("dc-knights"), {
        bars: D.knights_played.map((r) => ({ label: r.k === 5 ? "5+" : String(r.k), value: r.win * 100, expected: (r.win - r.wae) * 100, note: r.la ? `LA ${pct(r.la)}` : "",
          tip: `<div><b>${r.k === 5 ? "5 or more" : r.k} knights played</b></div><div>${r.n} player-games, won <b>${pct(r.win)}</b></div><div>Held Largest Army at the end ${pct(r.la)}</div>` })),
        height: 230, format: (v) => v.toFixed(0) + "%", ariaLabel: "Win rate by knights played",
      });
      C.barChart($("dc-lafirst"), {
        bars: D.la_first_hist.map((v, i) => ({ label: `${i * 10}`, value: v, tip: `${v} games first claimed ${i * 10}–${i * 10 + 10}% through` })),
        height: 230, ariaLabel: "When Largest Army is first claimed", valueLabels: false,
      });
    }

    // ---- Robber ---------------------------------------------------------------------------------------------------
    if (rt) C.nullBars($("dc-rob"), {
      bars: [["knight", "Knight"], ["seven", "Rolled 7"]].map(([k, l]) => ({ label: l, value: rt[k].rate * 100, expected: rt[k].chance * 100, note: `${rt[k].ratio.toFixed(2)}×`,
        tip: `<div><b>${l}</b>, ${rt[k].n} robberies</div><div>Robbed the top threat <b>${pct(rt[k].rate)}</b></div><div>Random pick ${pct(rt[k].chance)}</div><div>${rt[k].ratio.toFixed(2)}× chance (${rt[k].ci[0].toFixed(2)} to ${rt[k].ci[1].toFixed(2)})</div>` })),
      height: 210, format: (v) => v.toFixed(0) + "%", ariaLabel: "Share of robberies that took from the top threat",
    });

    // ---- Monopoly ---------------------------------------------------------------------------------------------------
    if (mono) {
      C.barChart($("dc-mono-res"), {
        bars: Object.entries(mono.by_res).sort((a, b) => b[1].mean - a[1].mean).map(([r, d]) => ({ label: RES_LABEL[r] || r, value: d.mean.toFixed(1), color: `var(--res-${r})`, tip: `called ${d.n} times, ${d.mean.toFixed(1)} cards on average` })),
        valueLabels: true, height: 200, ariaLabel: "Average Monopoly haul by resource",
      });
      C.barChart($("dc-mono-n"), {
        bars: Object.entries(mono.by_n).map(([n, d]) => ({ label: `${n} players`, value: d.mean.toFixed(1), tip: `${d.n} Monopolies, ${d.mean.toFixed(1)} cards on average` })),
        valueLabels: true, height: 200, ariaLabel: "Average Monopoly haul by table size",
      });
      C.barChart($("dc-mono-dist"), {
        bars: Array.from({ length: 11 }, (_, k) => ({ label: k === 10 ? "10+" : String(k), value: mono.dist[String(k)] || 0, tip: `${mono.dist[String(k)] || 0} Monopolies took ${k === 10 ? "10 or more" : k} cards` })),
        height: 200, ariaLabel: "Monopolies by cards taken",
      });
    }

    // ---- Holding ----------------------------------------------------------------------------------------------------
    const kh = D.hold.knight;
    $("dc-hold-tiles").innerHTML = [
      { value: pct(D.knight_pre_roll), label: "Knights played before the roll", sub: W.hold.pre ? `${esc(pname(W.hold.pre.p))}: ${pct(W.hold.pre.pre)}` : "" },
      kh ? { value: kh.mean.toFixed(1), label: "Turns a knight is held", sub: `average; the median is ${kh.median}` } : null,
      { value: pct(D.unplayed.share), label: "Action cards never played", sub: `${D.unplayed.winners} of ${D.unplayed.cards} in the winner's hand` },
    ].filter(Boolean).map(C.statTile).join("");
    Object.entries(D.hold_hist).forEach(([k, h]) => {
      const box = document.createElement("div");
      box.innerHTML = `<p class="chart-h">${CARD[k]}<span class="sub">${sum(h)} played</span></p><div class="chart"></div>`;
      $("dc-hold").appendChild(box);
      C.barChart(box.querySelector(".chart"), {
        bars: h.map((v, i) => ({ label: i === 4 ? "5+" : String(i + 1), value: v, color: CARD_COLOR[k], tip: `${v} played ${i === 4 ? "5 or more turns" : i === 0 ? "1 turn" : `${i + 1} turns`} after buying (${pct(v / sum(h))})` })),
        height: 150, ariaLabel: `${CARD[k]} hold times`,
      });
    });

    // ---- Players ------------------------------------------------------------------------------------------------------
    stacked(C, $("dc-pmix"), {
      keys: ORDER, color: (k) => CARD_COLOR[k], name: (k) => CARD[k], fmt: (v) => v.toFixed(2), height: 240,
      bars: players.map((p) => ({ label: pname(p.p), title: `${pname(p.p)}, ${p.games} games`, values: Object.fromEntries(ORDER.map((k) => [k, (p.cards[k] || 0) / p.games])), foot: `${p.buys.toFixed(1)} a game` })),
      total: (v) => v.toFixed(1), ariaLabel: "Dev cards bought per game by player",
    });
    C.barChart($("dc-pshare"), {
      bars: players.map((p) => ({ label: pname(p.p), value: Math.round(p.share * 100), color: c.color(p.p), tip: `${pct(p.share)} of cards spent went to dev cards` })),
      valueLabels: true, height: 240, ariaLabel: "Share of spending on dev cards by player",
    });
    const MK = D.markers || {};
    const mk = (pid, key) => {
      const m = (MK[pid] || {})[key];
      if (!m) return "";
      const good = m.good === 1 ? "up" : m.good === -1 ? "down" : "neutral";
      if (key === "wins") return C.arrow(m.z, { clear: m.clear, good, unit: "z", tip: `Wins against Σ 1/n over ${m.games} games: z = ${m.z.toFixed(2)}` });
      return C.arrow(Math.abs(m.delta) < 0.05 ? 0 : m.delta, { clear: m.clear, good,
        tip: `${signed(m.delta, 2)} SD vs the rest of the table over ${m.games} games (95% interval ${signed(m.lo, 2)} to ${signed(m.hi, 2)})` });
    };
    const tdm = (v, pid, key) => `<td class="num">${v} <span class="cell-mk">${mk(pid, key)}</span></td>`;
    const opt = (v, f) => (v === null || v === undefined ? "–" : f(v));
    const cols = [
      ["Player", (p) => `<td>${c.who(p.p)}${p.games < MIN_MARK ? ' <span class="sub">few games</span>' : ""}</td>`],
      ["Games", (p) => `<td class="num">${p.games}</td>`],
      ["Win vs expected", (p) => tdm(`${pts(p.wae)} pts`, p.p, "wins")],
      ["Cards a game", (p) => tdm(p.buys.toFixed(1), p.p, "buys")],
      ["Spend on dev", (p) => tdm(pct(p.share), p.p, "share")],
      ["First buy, turn", (p) => tdm(opt(p.first, (v) => v), p.p, "first")],
      ["Knights a game", (p) => tdm(p.knights.toFixed(1), p.p, "knights")],
      ["Largest Army", (p) => tdm(pct(p.la), p.p, "la")],
      ["Knights before roll", (p) => tdm(opt(p.pre, (v) => pct(v)), p.p, "pre")],
      ["Hold, turns", (p) => tdm(opt(p.hold, (v) => v.toFixed(1)), p.p, "hold")],
      ["Unplayed a game", (p) => tdm(p.unplayed.toFixed(2), p.p, "unplayed")],
      ["Monopoly cards a game", (p) => tdm(p.mono_pg.toFixed(1), p.p, "mono")],
    ];
    $("dc-table").innerHTML = `<table><thead><tr>${cols.map((col, i) => `<th${i ? ' class="num"' : ""}>${col[0]}</th>`).join("")}</tr></thead><tbody>`
      + players.map((p) => `<tr>${cols.map((col) => col[1](p)).join("")}</tr>`).join("") + `</tbody></table>`;

    // ---- Method ---------------------------------------------------------------------------------------------------------
    const fd = (d) => c.fmtDate(d, { month: "short", day: "numeric", year: "numeric" });
    $("dc-method").innerHTML = [
      `TwoSheep replays played back move by move by the site's replay script: ${D.games} games from ${fd(D.first_date)} to ${fd(D.last_date)}. This page always uses all of them, whatever the Games filter says.`,
      `Expected win rate is 1 over the number of players in each game, so a 3-player win and a 5-player win count fairly. Across all games it is ${pct(EXP)}.`,
      `Card comparisons treat each purchase as one data point and compare the card that came out with every other card bought in the same third of the game. Since the card is luck, these measure the card itself.`,
      `Intervals are 95%, from 2,000 bootstrap resamples of whole games, because cards within one game are not independent. Robber targets use the site's threat index with out-of-fold probabilities, so no game is scored by a model that saw its own winner.`,
      `Expected VP draws use the deck as it stood at each purchase: 14 knights, 5 VP and 2 of each progress card (a bigger deck in 5–6 player games).`,
      `Table markers are the site's within-game comparison: each stat minus the average of the player's tablemates in that game, averaged over games and divided by the pooled within-game SD, with a t interval.`,
      `Hold times match plays to purchases first in, first out per card type, so they are approximate when a player holds two of the same card.`,
      `Sections tagged Descriptive compare choices people made, so better players can explain a gap. Only the card-draw comparisons isolate luck.`,
    ].map((s) => `<li>${esc(s)}</li>`).join("");

    c.layoutWithRail(secs, "#/devcards");
  }

  (window.Pages = window.Pages || {}).devcards = { render, sections: true };
})();
