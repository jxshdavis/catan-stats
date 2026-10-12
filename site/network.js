/* Network page (spec 1.2, 1.5, 1.8): who trades with and robs whom, overpunishment, trade and rob.
   Renders stats.json "robber" (all games, the shared models) and views[view].robber (per view sums).
   Also adds a section to the player page and to Findings. Computes nothing statistical itself. */
(function () {
  "use strict";
  const PAGE = "network";
  window.Hooks = window.Hooks || {};

  // The page's own stylesheet (asked to be linked in index.html; added here until it is).
  if (!document.querySelector('link[href="network.css"]')) {
    const l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = "network.css";
    document.head.appendChild(l);
  }

  // ---- Method notes -------------------------------------------------------------------------
  Object.assign(window.METHODS = window.METHODS || {}, {
    net_graph: `<p><b>What is drawn.</b> One node per player in this view, in leaderboard order around the circle. An edge needs at least 5 shared games: from 5 to 9 it is a grey dashed line with counts only, and from 10 shared games it is colored by a model estimate. Pairs under 5 shared games are not drawn. Guests and bots are never drawn, but they stay in every choice set and denominator.</p>
      <p><b>Influence flag.</b> An edge is flagged when a single game supplies more than 40% of its observed count O. There are no per-edge significance tests.</p>
      <p><b>Units.</b> Pair rates are per 100 shared rolls: rolls in games where both players sat.</p>`,
    net_trade: `<p><b>Model.</b> For every player trade t, the roller a picks a partner q from C<sub>t</sub>, the other seats holding at least 1 card just before the trade (the actual partner is always in C<sub>t</sub>). A conditional logit: P<sub>t</sub>(q) ∝ exp(π<sub>q</sub> + g<sub>1</sub> log(1 + h<sub>tq</sub>) + g<sub>2</sub> L<sub>tq</sub> + d<sub>1</sub> R<sub>tq</sub> + d<sub>2</sub> S<sub>tq</sub> + u<sub>aq</sub>), where π<sub>q</sub> is the responder's popularity (guests and bots pooled as one reference "other"), h<sub>tq</sub> is q's hand size, L<sub>tq</sub> = 1 if q is a public-VP leader among a's opponents (ties count; public VP from the board just before the trade), R<sub>tq</sub> = 1 if q stole from a in the last 2 rounds (2n rolls) and S<sub>tq</sub> = 1 if a stole from q in that window.</p>
      <p><b>Pair effect.</b> u<sub>ab</sub> = u<sub>ba</sub> ~ N(0, σ<sub>u</sub><sup>2</sup>) for every pair of regulars. For each σ<sub>u</sub> on the grid 0, 0.1, ..., 0.8, 1, 1.2, 1.5, 2 the model is fit by penalized Newton-Raphson (penalty Σu<sup>2</sup>/2σ<sub>u</sub><sup>2</sup>; a negligible ridge of 0.001 on π keeps it identified), and σ<sub>u</sub> is chosen by the Laplace approximation to the marginal likelihood with the other terms profiled: ℓ(θ̂, û) − |û|<sup>2</sup>/2σ<sub>u</sub><sup>2</sup> − ½ log|σ<sub>u</sub><sup>2</sup> I<sub>uu</sub> + 1|. The edge color is log<sub>2</sub> exp(û<sub>ab</sub>), clipped to ×0.5 to ×2, with a 95% Wald interval from the inverse penalized information.</p>
      <p><b>Panel.</b> O = trades between the pair (either one rolling). E = the expected number with u = 0 (popularity, hands, leader and grudges only). Width is proportional to √E. The node ring is π<sub>q</sub> centered on the regulars' average: how often a player is picked as a partner when available.</p>
      <p><b>Wording.</b> Only the roller can trade and offers are not recorded, so nobody can be called the initiator: pairs "trade together more or less than expected". Views with 30 or more games refit the model; smaller views reuse the all-games fit.</p>`,
    net_robber: `<p><b>Shared robber model</b>, fit once on all games. Pirate moves are left out and only counted. 7s and knights are fit as two separate models (no pooling), so every coefficient can differ by cause.</p>
      <p><b>Stage 1, hex choice.</b> One choice per robber move over every legal hex: land including the desert, not fog, not the hex the robber is on. With income of seat j on hex h = dots(h) × (settlements + 2 cities of j on h), in pips, and the leaders = the opponents with the most public VP (ties all count), the features are: x<sub>1</sub> leaders' income; x<sub>2</sub> other opponents' income; x<sub>3</sub> the mover's own income; x<sub>4</sub> opponents with a building and at least 1 card; x<sub>5</sub> the largest such hand; x<sub>5</sub>′ Σ log(1 + hand) over them; x<sub>0</sub> income of empty-handed opponents; x<sub>2v</sub> Σ over non-leaders of income × VP behind the leader; x<sub>6</sub> = 1 if the hex touches someone who stole from the mover in the last n rolls (one round).</p>
      <p><b>Stage 2, victim choice</b>, for moves with at least 2 opponents to steal from on the chosen hex: public VP minus the leading opponent's, hand size, and "stole from the mover in the last round".</p>
      <p><b>Expected counts.</b> For a move, P(steal from j) = Σ<sub>h</sub> P<sub>1</sub>(h) P<sub>2</sub>(j | h), with P<sub>2</sub> = 1 when j is the only opponent to steal from on h. E always uses leave-one-mover-out coefficients: each regular's moves are predicted from a fit without any of that player's moves (all guest and bot moves form one left-out group), so a player's own habits never set their own baseline.</p>
      <p><b>Arcs.</b> Two arcs per pair, one per direction, colored by the shrunk O/E of steals: log((O + 0.5)/(E + 0.5)) with SE 1/√(O + 0.5), shrunk normal-normal toward the REML mean of all colored directed pairs in the view, with the uncertainty in that mean included in the 95% interval. The panel also shows Stage 1 alone (placements touching the player) and Stage 2 alone (victim picks), each shrunk the same way. Coefficients are always from all games; views sum the expected counts of their own moves.</p>`,
    net_ledger: `<p>Cards one player cost another, per 100 shared rolls: steals (robber and pirate, one card each), plus the dice cards the victim did not get while the row player's robber sat on the victim's hex (nominal cards owed by the dice, from the decoder's blocked_by), plus cards the row player took from the victim with Monopoly. Self-blocks and the starting robber are not counted. The three parts stay separate in each bar; the number is their sum.</p>`,
    net_terms: `<p><b>Roller premium.</b> P<sub>a</sub> = Σ G / Σ R over the player trades a made as roller, G = cards a gave and R = cards a received. Shown against the field: (P<sub>a</sub>) / (Σ G / Σ R over every other roller's trades in the same games).</p>
      <p><b>Pair terms of trade.</b> ρ<sub>a|b</sub> = (G/R when a, rolling, trades with b) / (G/R when a trades with anyone else). Shown only when each direction has at least 20 trades over at least 10 shared games. Both use 95% game-cluster bootstrap percentile intervals (2,000 draws). The per-resource flow is descriptive only.</p>`,
    net_contention: `<p>C<sub>ab</sub> = Σ<sub>h</sub> min(w<sub>a</sub>(h), w<sub>b</sub>(h)) at the first roll, where w<sub>q</sub>(h) is the dots on hex h times the number of q's setup settlements touching it (no cities exist yet). Shown in dots (36 C, since a dot is 1/36 of a card per roll) as the average over shared games, with a 95% t interval. It measures how much of the same production two players started on.</p>`,
    op_leader: `<p><b>Leader tax.</b> From the shared robber model fit on 7s (knights shown beside it). <b>Per VP:</b> the Stage 2 odds ratio exp(β), "each 1 public VP closer to the lead multiplies the odds of being the one robbed by exp(β)", among moves with at least 2 opponents to steal from. <b>Leader premium:</b> β<sub>1</sub>/β<sub>2</sub> from Stage 1, how much one pip of the leader's income weighs against one pip of another opponent's, with a Fieller interval. <b>5 pips:</b> exp(5β<sub>1</sub>), the odds multiplier for a hex paying the leader 5 pips (a settlement on a 6 or 8).</p>
      <p><b>Base rate.</b> Share of robber placements touching a public-VP leader, against the share expected if every legal hex were equally likely (averaged over moves). The other Stage 1 terms (x<sub>2v</sub>, x<sub>5</sub>′, x<sub>0</sub>) stay in every fit. Intervals are 95% Wald from the model information unless stated.</p>`,
    op_target: `<p><b>Filled dot (headline, board-adjusted).</b> O<sub>i</sub> = cards stolen from player i by the robber after a 7 or a knight. E<sub>i</sub> = Σ over those moves of the model probability that i is the victim, from both stages with leave-one-mover-out coefficients. So E already allows for i's buildings, hand, VP and recent robbing of the mover. The ratio is shrunk: log((O + 0.5)/(E + 0.5)), SE 1/√(O + 0.5), normal-normal toward the REML mean of the players shown, interval including the uncertainty in that mean. Above 1: robbed more than the board explains.</p>
      <p><b>Hollow dot (even split, context).</b> The same O against E<sub>i</sub> = Σ<sub>e</sub> 1[i eligible on the chosen hex] / (number eligible), so leader-robbing and hand size count as "excess" here.</p>
      <p>Players need 10 games in the view. Pirate steals and 7-discards are not counted (pirates are listed separately). The coefficients always come from all games.</p>`,
    op_lost: `<p>Δ<sup>c</sup><sub>i</sub> = (1/G<sub>i</sub>) Σ<sub>g</sub> (X<sup>c</sup><sub>ig</sub> − mean<sub>j</sub> X<sup>c</sup><sub>jg</sub>), in cards per game, where the mean is over every seat in game g (bots and guests included) and c is cards stolen (robber and pirate), dice cards blocked by opponents' robbers, or cards lost to opponents' Monopoly. Monopoly is a separate component and never added in. Discards on 7s are left out. Self-blocks and the starting robber are excluded. 95% t interval over the player's games.</p>`,
    op_early: `<p><b>Exploratory.</b> For each seat, early excess = Σ<sub>e</sub> (1[robbed in move e] − P̂<sub>e</sub>(robbed)) over robber moves (7s and knights) before any player's public VP first reaches ⌈G/2⌉, with P̂ from the shared model (leave-one-mover-out). A conditional logit for the winner, stratified by game, with that excess, pre-game μ (from the chronological all-games rating pass) and opening dots minus the table mean, fit with the Firth penalty. γ is the log odds ratio per extra early card stolen beyond the model; the interval is the 95% profile penalized-likelihood interval. Reported as the range of effects the data cannot rule out, and only in views with at least 40 games.</p>`,
    op_pirate: `<p>Pirate moves (Seafarers) are left out of both robber models, because a ship has no hex income. They are counted here: moves made, and cards stolen from each player by a pirate.</p>`,
    tr_betrayal: `<p><b>Betrayal index</b> ρ, from Stage 1 of the 7s model with two extra terms: x<sub>8</sub> = income on the hex owned by non-leader opponents who traded with the mover in the last 2 rounds (2n rolls, strictly earlier by action), and x<sub>9</sub> = x<sub>2</sub> × 1[the move has such a partner], so β<sub>8</sub> is identified only by moves that hold both a partner and another trailing opponent. Then ρ = (β<sub>2</sub> + β<sub>9</sub> + β<sub>8</sub>) / (β<sub>2</sub> + β<sub>9</sub>): a recent partner's pip of income against the same pip owned by another trailing opponent in the same move. 1 = partners treated like anyone; below 1 = partners spared; above 1 = partners hit harder. 95% Fieller interval.</p>
      <p><b>Three bars</b>: the per-pip Stage 1 weights (log odds) for a leader (β<sub>1</sub>), another trailing opponent (β<sub>2</sub> + β<sub>9</sub>) and a recent partner (β<sub>2</sub> + β<sub>9</sub> + β<sub>8</sub>), 95% Wald intervals. "Good trades" means trade volume, not terms, because the roller usually overpays whatever the relationship.</p>
      <p><b>Wording.</b> The lag placebo uses partners from the 2 rounds before the window only. If its interval includes 1, the caption says "people you just traded with"; otherwise "people you trade with".</p>`,
    tr_sens: `<p>Every refit is shown whatever it says. <b>4 or more seats</b>: games with at least 4 seats. <b>Whose turn</b>: one fit with two partner terms, trades made on the mover's own turn and trades made on the partner's turn (a depletion check: a partner who just traded on their own turn may have spent their cards). <b>Lag placebo</b>: partners who traded with the mover 2 to 4 rounds back but not in the last 2 rounds. <b>Trades so far</b>: x<sub>8</sub> weights each partner's income by the number of trades with the mover so far in the game, so ρ is per trade. <b>Mover-specific</b>: one β<sub>8</sub> each for the four regulars with the most robber moves and one for everyone else. <b>Knights</b>: the same model fit on knight moves only.</p>`,
    tr_hit: `<p>For one mover, informative placements are 7s where the mover has a non-leader recent partner (last 2 rounds) and the legal hexes include some that touch a partner and some that do not. O = placements touching a partner. E = Σ Stage 1 probability of a hex touching a partner, from the model without the partner terms and with leave-one-mover-out coefficients. Shrunk toward the group ratio (REML, normal-normal). The Q gate: unless Cochran's Q rejects equal ratios at the 5% level, the page says no player differs from the group. Needs 10 games and 20 informative placements.</p>`,
    tr_balance: `<p>Net steals O<sub>ab</sub> − O<sub>ba</sub> between two players (robber after 7s and knights; pirates left out) split exactly into three parts, using the shared model's expected counts E (leave-one-mover-out):</p>
      <ul><li><b>Dice and position</b>: E<sub>ab</sub> − E<sub>ba</sub> with the retaliation terms set to 0. Who rolled 7s, played knights, and sat where.</li>
      <li><b>Reaction to earlier robberies</b>: (E<sub>full</sub> − E<sub>no retaliation</sub>) for a→b minus the same for b→a.</li>
      <li><b>Beyond the model</b>: (O<sub>ab</sub> − E<sub>ab</sub>) − (O<sub>ba</sub> − E<sub>ba</sub>).</li></ul>
      <p>The shaded band is the central 95% of the net under the fitted model: 2,000 redraws in which every move's victim is drawn from its model probabilities (history held as observed), placed at the end of the first two parts. A net tick outside the band means more lopsided than the model expects. Pairs with 10 or more shared games.</p>`,
    tr_grudge: `<p>From the trade partner model: odds ratios for picking a partner who stole from the roller in the last 2 rounds, and one the roller stole from in that window. With this many trades only an odds ratio below about 0.5 would be detectable, so an interval that includes 1 reads "not detected", not "absent". The leader term is the single home for "does the table stop trading with the leader?".</p>`,
  });

  // ---- Helpers ----------------------------------------------------------------------------------
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const fin = (v) => v !== null && v !== undefined && Number.isFinite(+v);
  const log2 = (x) => Math.log(x) / Math.LN2;
  const pairKey = (a, b) => [a, b].sort().join("|");
  // Diverging color around a neutral gray: t in [-1, 1].
  const dv = (t, pos, neg) => {
    if (!fin(t)) return "var(--axis)";
    const p = Math.round(Math.abs(clamp(t, -1, 1)) * 100);
    return `color-mix(in oklab, ${t >= 0 ? pos : neg} ${p}%, var(--muted))`;
  };
  const tradeColor = (r) => dv(fin(r) ? log2(r) : NaN, "var(--div-pos)", "var(--div-neg)");
  const robColor = (r) => dv(fin(r) ? log2(r) : NaN, "var(--div-neg)", "var(--div-pos)");
  const iv = (ctx, lo, hi, d = 2) => (fin(lo) && fin(hi) ? `${ctx.num(lo, d)} to ${ctx.num(hi, d)}` : "interval not bounded");
  const order = (ctx) => ctx.S.players.filter((p) => p.games > 0).map((p) => p.id);
  const nm = (ctx, pid) => (ctx.P[pid] ? ctx.P[pid].name : pid);
  const RV = (ctx) => ctx.S.robber;
  const RA = (ctx) => ctx.ROOT.robber;
  const sourceNote = (ctx) => (ctx.VIEW === "all" ? "" : ` Robber model coefficients come from all games; this view sums its own moves.`);

  // Tooltip on an SVG or HTML element.
  function tip(ctx, el, html) {
    const T = ctx.Charts.Tip;
    el.setAttribute("data-tipped", "");
    const show = (e) => {
      let x, y;
      if (e && e.clientX !== undefined) { x = e.clientX; y = e.clientY; } else { const r = el.getBoundingClientRect(); x = r.left + r.width / 2; y = r.top; }
      T.show(typeof html === "function" ? html() : html, x, y);
    };
    el.addEventListener("pointermove", show);
    el.addEventListener("pointerleave", (e) => { if (e.pointerType !== "touch") T.hide(); });
    el.addEventListener("focus", () => show());
    el.addEventListener("blur", () => T.hide());
  }

  function responsive(el, draw) {
    let last = 0;
    const run = () => {
      if (!el.isConnected) { if (ro) ro.disconnect(); return; }
      const w = Math.floor(el.clientWidth);
      if (w < 160 || w === last) return;
      last = w;
      el.innerHTML = "";
      draw(w);
    };
    const ro = "ResizeObserver" in window ? new ResizeObserver(run) : null;
    run();
    if (ro) ro.observe(el);
  }

  // ---- Side panel ----------------------------------------------------------------------------
  function dirBlock(ctx, a, b) {
    const d = RV(ctx).directed[`${a}>${b}`];
    if (!d) return `<p>${ctx.who(a, false)} never robbed ${ctx.who(b, false)} here.</p>`;
    const head = `<dt>${ctx.esc(nm(ctx, a))} robbed ${ctx.esc(nm(ctx, b))}</dt><dd>${d.O} cards (${ctx.num(d.per100, 2)} per 100 shared rolls)${d.influence ? `<span class="flag">one game &gt; 40%</span>` : ""}</dd>`;
    if (d.tier !== "color") return `<dl>${head}</dl>`;
    const st = (x) => (x && fin(x.shrunk) ? `${x.O} vs ${ctx.num(x.E, 1)}: ×${ctx.num(x.shrunk, 2)} (${iv(ctx, x.lo, x.hi)})` : x ? `${x.O} vs ${ctx.num(x.E, 1)}` : "n/a");
    return `<dl>${head}
      <dt>Steals vs the model</dt><dd>${d.O} vs ${ctx.num(d.E, 1)}: ×${ctx.num(d.shrunk, 2)} (${iv(ctx, d.lo, d.hi)})</dd>
      <dt>Hex choice (Stage 1)</dt><dd>${st(d.stage1)}</dd>
      <dt>Victim pick (Stage 2)</dt><dd>${st(d.stage2)}</dd></dl>`;
  }

  const RES = ["wood", "brick", "sheep", "wheat", "ore"];
  const RES_C = ["var(--p6)", "var(--p8)", "var(--p3)", "var(--p4)", "var(--muted)"];
  function flowBar(ctx, flow) {
    const tot = flow.reduce((s, v) => s + v, 0);
    if (!tot) return "";
    return `<div class="flowbar" role="img" aria-label="${RES.map((r, i) => `${r} ${flow[i]}`).join(", ")}">${flow.map((v, i) => (v ? `<span style="flex:${v};background:${RES_C[i]}" title="${RES[i]} ${v}"></span>` : "")).join("")}</div>`;
  }

  // With sigma_u = 0 the pair effects are fixed at 0, so there is no interval to show.
  const uText = (ctx, t) => (t.lo === t.hi ? `×${ctx.num(t.exp_u, 2)}: no pair effects (σ<sub>u</sub> = 0)` : `×${ctx.num(t.exp_u, 2)} (${iv(ctx, t.lo, t.hi)})`);

  function pairPanel(ctx, a, b) {
    const R = RV(ctx);
    const p = R.pairs[pairKey(a, b)];
    if (!p) return `<p>No shared games in this view.</p>`;
    const tr = p.trade;
    const grey = p.tier !== "color";
    let html = `<h3>${ctx.who(a)} <span class="sub">and</span> ${ctx.who(b)}</h3>
      <p>${p.games} shared games, ${p.rolls} shared rolls.${grey ? " Under 10 shared games, so counts only." : ""}</p>
      <h4>Trading ${ctx.info("net_trade", "Trade partner preference")}</h4><dl>
      <dt>Trades together</dt><dd>${tr.O} (${ctx.num(tr.per100, 2)} per 100 shared rolls)${tr.influence ? `<span class="flag">one game &gt; 40%</span>` : ""}</dd>`;
    if (!grey) {
      html += `<dt>Expected (no pair effect)</dt><dd>${ctx.num(tr.E, 1)}</dd>
        <dt>Pair effect exp(u)</dt><dd>${uText(ctx, tr)}</dd>`;
    }
    html += `</dl>`;
    const t = p.terms;
    if (t) {
      const tt = (x) => (x ? `×${ctx.num(x.rho, 2)} (${iv(ctx, x.lo, x.hi)})` : "needs 20 trades each way over 10 shared games");
      html += `<h4>Terms of trade ${ctx.info("net_terms", "Roller premium and terms of trade")}</h4><dl>
        <dt>${ctx.esc(nm(ctx, a))} rolling, with ${ctx.esc(nm(ctx, b))}</dt><dd>${t.n_ab} trades; ${tt(t.ab)}</dd>
        <dt>${ctx.esc(nm(ctx, b))} rolling, with ${ctx.esc(nm(ctx, a))}</dt><dd>${t.n_ba} trades; ${tt(t.ba)}</dd></dl>
        <p class="sub">Cards ${ctx.esc(nm(ctx, a))} gave ${ctx.esc(nm(ctx, b))} by resource (${RES.join(", ")}):</p>${flowBar(ctx, t.flow_ab)}
        <p class="sub">Cards ${ctx.esc(nm(ctx, b))} gave ${ctx.esc(nm(ctx, a))}:</p>${flowBar(ctx, t.flow_ba)}`;
    }
    html += `<h4>Robber ${ctx.info("net_robber", "Shared robber model")}</h4>${dirBlock(ctx, a, b)}${dirBlock(ctx, b, a)}`;
    const bal = p.balance;
    if (bal) {
      html += `<h4>Pair balance ${ctx.info("tr_balance", "Pair robbery balance")}</h4><dl>
        <dt>Net steals, ${ctx.esc(nm(ctx, bal.a))} minus ${ctx.esc(nm(ctx, bal.b))}</dt><dd>${ctx.fmtSigned(bal.net, 0)} (${bal.O_ab} vs ${bal.O_ba})</dd>
        <dt>Dice and position</dt><dd>${ctx.fmtSigned(bal.position, 1)}</dd>
        <dt>Reaction to earlier robberies</dt><dd>${ctx.fmtSigned(bal.retaliation, 1)}</dd>
        <dt>Beyond the model</dt><dd>${ctx.fmtSigned(bal.beyond, 1)} (model range ${ctx.fmtSigned(bal.band[0], 1)} to ${ctx.fmtSigned(bal.band[1], 1)})</dd></dl>`;
    }
    const L = R.ledger || {};
    const lr = (x, y) => { const l = L[`${x}>${y}`]; return l ? `${ctx.num(l.total100, 2)}: ${l.steals} stolen, ${l.blocked} blocked, ${l.monopoly} by Monopoly` : "0"; };
    html += `<h4>Cards cost per 100 shared rolls ${ctx.info("net_ledger", "Cards cost ledger")}</h4><dl>
      <dt>${ctx.esc(nm(ctx, a))} cost ${ctx.esc(nm(ctx, b))}</dt><dd>${lr(a, b)}</dd>
      <dt>${ctx.esc(nm(ctx, b))} cost ${ctx.esc(nm(ctx, a))}</dt><dd>${lr(b, a)}</dd></dl>`;
    if (p.contention) {
      html += `<h4>Setup contention ${ctx.info("net_contention", "Board contention at setup")}</h4>
        <p>${ctx.num(p.contention.mean, 1)} shared dots per game (${iv(ctx, p.contention.lo, p.contention.hi, 1)}).</p>`;
    }
    return html;
  }

  function playerPanel(ctx, pid) {
    const R = RV(ctx);
    const t = (R.targeting || {})[pid], n = (R.nodes || {})[pid], pr = (R.premium || {})[pid], pi = (R.pirate.by_player || {})[pid];
    let html = `<h3>${ctx.who(pid)}</h3><p>${n ? n.games : 0} games in this view. Select an edge to see a pair.</p><dl>`;
    if (t) html += `<dt>Robbed vs the board ${ctx.info("op_target", "Targeting beyond board state")}</dt><dd>×${ctx.num(t.shrunk, 2)} (${iv(ctx, t.lo, t.hi)}); ${t.O} cards vs ${ctx.num(t.E, 1)}</dd>`;
    if (n && fin(n.pi)) html += `<dt>Partner popularity π ${ctx.info("net_trade", "Trade partner preference")}</dt><dd>${ctx.fmtSigned(n.pi, 2)} (log odds vs the regulars' average)</dd>`;
    if (pr) html += `<dt>Roller premium ${ctx.info("net_terms", "Roller premium and terms of trade")}</dt><dd>gives ${ctx.num(pr.P, 2)} per card received; ×${ctx.num(pr.ratio, 2)} the field (${iv(ctx, pr.lo, pr.hi)})</dd>`;
    if (pi) html += `<dt>Pirate</dt><dd>${pi.moves} moves made, ${pi.stolen_from} cards lost to pirates</dd>`;
    return html + `</dl>`;
  }

  function defaultPanel(ctx, layer) {
    const R = RV(ctx), A = RA(ctx);
    const tm = R.trade_model || A.trade_model;
    if (layer === "trade") {
      return `<h3>Trade layer</h3><p>Each line joins two players who share games. Thicker lines: pairs who trade a lot. Color: whether a pair trades more (blue) or less (red) than their overall habits, hand sizes and the score predict. The ring around each player: how often others pick them as a trade partner.</p>
        <p>${tm && tm.sigma_u === 0 ? `<b>No pair stands out.</b> Once each player's overall popularity as a partner is allowed for, no two players trade with each other more than expected, so every colored line is ×1.00 (the model's best fit puts the spread between pairs, σ<sub>u</sub>, at 0).` : tm ? `σ<sub>u</sub> = ${ctx.num(tm.sigma_u, 1)}: pair effects are shrunk toward ×1.` : ""}</p>
        <p>Select a player or an edge for details.</p>`;
    }
    return `<h3>Robber layer</h3><p>One arrow per direction, pointing at the player robbed. Color: cards stolen compared with what the robber model expects, which already allows for the board, hands, score and recent robberies. Red means robbed more than expected, blue less; gray is about as expected.</p><p>Select a player or an arc for details.</p>`;
  }

  // ---- Circular graph -----------------------------------------------------------------------------
  function drawGraph(ctx, el, layer, nodes, onSelect, sel) {
    const R = RV(ctx);
    const svgEl = ctx.Charts.svgEl;
    responsive(el, (W) => {
      const S = Math.min(W - 16, 560), narrow = S < 420;
      const nodeR = narrow ? 11 : 14, cx = S / 2, cy = S / 2, rad = S / 2 - (narrow ? 44 : 50);
      const svg = svgEl("svg", { width: S, height: S, viewBox: `0 0 ${S} ${S}`, role: "group",
        "aria-label": `${layer === "trade" ? "Trade" : "Robber"} network of ${nodes.length} players. Each node and edge is focusable; press Enter for details.` }, el);
      const pos = {};
      nodes.forEach((pid, i) => {
        const a = -Math.PI / 2 + (2 * Math.PI * i) / nodes.length;
        pos[pid] = { x: cx + rad * Math.cos(a), y: cy + rad * Math.sin(a), a };
      });
      const gEdges = svgEl("g", {}, svg), gNodes = svgEl("g", {}, svg);
      const focusable = (g, label, fn) => {
        g.setAttribute("tabindex", "0");
        g.setAttribute("role", "button");
        g.setAttribute("aria-label", label);
        g.addEventListener("click", fn);
        g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fn(); } });
      };
      const pairs = Object.entries(R.pairs).filter(([k]) => { const [a, b] = k.split("|"); return pos[a] && pos[b]; });
      if (layer === "trade") {
        const Emax = Math.max(1, ...pairs.map(([, p]) => p.trade.E || 0));
        for (const [k, p] of pairs) {
          const [a, b] = k.split("|"), A = pos[a], B = pos[b];
          const col = p.tier === "color";
          const g = svgEl("g", { class: "edge" + (sel && sel.k === k ? " on" : "") }, gEdges);
          svgEl("line", { x1: A.x, y1: A.y, x2: B.x, y2: B.y, class: "hit", stroke: "var(--surface)", "stroke-opacity": 0, "stroke-width": 16, "stroke-linecap": "round" }, g);
          svgEl("line", { x1: A.x, y1: A.y, x2: B.x, y2: B.y, stroke: col ? tradeColor(p.trade.exp_u) : "var(--axis)",
            "stroke-width": col ? 1.5 + 7 * Math.sqrt((p.trade.E || 0) / Emax) : 1.5, "stroke-dasharray": col ? null : "5 4", "stroke-linecap": "round" }, g);
          const label = `${nm(ctx, a)} and ${nm(ctx, b)}: ${p.trade.O} trades in ${p.games} shared games` + (col ? `, ${ctx.num(p.trade.E, 1)} expected, pair effect ×${ctx.num(p.trade.exp_u, 2)}` : ", counts only");
          focusable(g, label, () => onSelect({ k, a, b }));
          tip(ctx, g, `<b>${ctx.esc(nm(ctx, a))} and ${ctx.esc(nm(ctx, b))}</b><div>${p.trade.O} trades, ${ctx.num(p.trade.per100, 2)} per 100 shared rolls</div>` +
            (col ? `<div>Expected ${ctx.num(p.trade.E, 1)}; pair effect ×${ctx.num(p.trade.exp_u, 2)}</div>` : `<div>${p.games} shared games: counts only</div>`));
        }
      } else {
        for (const [k, p] of pairs) {
          const [x, y] = k.split("|");
          for (const [a, b] of [[x, y], [y, x]]) {
            const d = R.directed[`${a}>${b}`];
            if (!d) continue;
            const A = pos[a], B = pos[b];
            const dx = B.x - A.x, dy = B.y - A.y, L = Math.hypot(dx, dy);
            const nx = -dy / L, ny = dx / L;
            const C = { x: (A.x + B.x) / 2 + nx * L * 0.16, y: (A.y + B.y) / 2 + ny * L * 0.16 };
            const toward = (P, Q, r) => { const vx = Q.x - P.x, vy = Q.y - P.y, l = Math.hypot(vx, vy); return { x: P.x + (vx / l) * r, y: P.y + (vy / l) * r }; };
            const s0 = toward(A, C, nodeR + 3), tipP = toward(B, C, nodeR + 3);
            const ux = tipP.x - C.x, uy = tipP.y - C.y, ul = Math.hypot(ux, uy);
            const base = { x: tipP.x - (ux / ul) * 8, y: tipP.y - (uy / ul) * 8 };
            const col = d.tier === "color" && fin(d.shrunk);
            const color = col ? robColor(d.shrunk) : "var(--axis)";
            const kk = `${a}>${b}`;
            const g = svgEl("g", { class: "edge" + (sel && sel.d === kk ? " on" : "") }, gEdges);
            const path = `M${s0.x},${s0.y} Q${C.x},${C.y} ${base.x},${base.y}`;
            svgEl("path", { d: path, class: "hit", fill: "none", stroke: "var(--surface)", "stroke-opacity": 0, "stroke-width": 14 }, g);
            svgEl("path", { d: path, fill: "none", stroke: color, "stroke-width": col ? 2.5 : 1.5, "stroke-dasharray": col ? null : "5 4" }, g);
            const px = -uy / ul, py = ux / ul;
            svgEl("path", { d: `M${tipP.x},${tipP.y} L${base.x + px * 4.5},${base.y + py * 4.5} L${base.x - px * 4.5},${base.y - py * 4.5} Z`, fill: color }, g);
            const label = `${nm(ctx, a)} robbed ${nm(ctx, b)}: ${d.O} cards` + (col ? `, ${ctx.num(d.E, 1)} expected, shrunk ratio ${ctx.num(d.shrunk, 2)}` : `, ${p.games} shared games, counts only`);
            focusable(g, label, () => onSelect({ k, a: x, b: y, d: kk }));
            tip(ctx, g, `<b>${ctx.esc(nm(ctx, a))} robbed ${ctx.esc(nm(ctx, b))}</b><div>${d.O} cards, ${ctx.num(d.per100, 2)} per 100 shared rolls</div>` +
              (col ? `<div>Expected ${ctx.num(d.E, 1)}: ×${ctx.num(d.shrunk, 2)} (${iv(ctx, d.lo, d.hi)})</div>` : `<div>${p.games} shared games: counts only</div>`));
          }
        }
      }
      const piMax = Math.max(0.25, ...nodes.map((p) => Math.abs((R.nodes[p] || {}).pi || 0)));
      for (const pid of nodes) {
        const P = pos[pid];
        const g = svgEl("g", { class: "node" + (sel && sel.p === pid ? " on" : "") }, gNodes);
        svgEl("circle", { cx: P.x, cy: P.y, r: nodeR + 6, class: "focus-ring", fill: "none", stroke: "transparent", "stroke-width": 2 }, g);
        if (layer === "trade") {
          const pi = (R.nodes[pid] || {}).pi;
          svgEl("circle", { cx: P.x, cy: P.y, r: nodeR + 2.5, fill: "none", stroke: fin(pi) ? dv(pi / piMax, "var(--div-pos)", "var(--div-neg)") : "var(--axis)", "stroke-width": 3.5 }, g);
        }
        svgEl("circle", { cx: P.x, cy: P.y, r: nodeR - (layer === "trade" ? 1 : 0), fill: ctx.color(pid), stroke: "var(--surface)", "stroke-width": 2 }, g);
        const lx = cx + (rad + nodeR + (narrow ? 14 : 18)) * Math.cos(P.a), ly = cy + (rad + nodeR + (narrow ? 14 : 18)) * Math.sin(P.a);
        const c = Math.cos(P.a);
        const t = svgEl("text", { x: lx, y: ly + 4, "text-anchor": Math.abs(c) < 0.3 ? "middle" : c > 0 ? "start" : "end" }, g);
        t.textContent = nm(ctx, pid);
        const n = R.nodes[pid] || {};
        focusable(g, `${nm(ctx, pid)}, ${n.games || 0} games`, () => onSelect({ p: pid }));
        tip(ctx, g, `<b>${ctx.esc(nm(ctx, pid))}</b><div>${n.games || 0} games here</div>` + (layer === "trade" && fin(n.pi) ? `<div>Partner popularity ${ctx.fmtSigned(n.pi, 2)}</div>` : ""));
      }
    });
  }

  function graphLegend(ctx, layer) {
    if (layer === "trade") {
      return `<ul class="net-legend">
        <li><span class="grad" style="background:linear-gradient(90deg, var(--div-neg), var(--muted), var(--div-pos))"></span>trade together less ← ×1 → more than expected</li>
        <li><span class="ln" style="--c:var(--muted)"></span>width: expected trades</li>
        <li><span class="ln dash" style="--c:var(--axis)"></span>5 to 9 shared games, counts only</li>
        <li><span class="ring" style="--c:var(--div-pos)"></span>ring: partner popularity</li></ul>`;
    }
    return `<ul class="net-legend">
      <li><span class="grad" style="background:linear-gradient(90deg, var(--div-pos), var(--muted), var(--div-neg))"></span>robs less ← ×1 → more than the model expects</li>
      <li><span class="ln dash" style="--c:var(--axis)"></span>5 to 9 shared games, counts only</li></ul>`;
  }

  function matrixFor(ctx, el, layer, nodes) {
    const R = RV(ctx);
    const H = ctx.Charts.heatMatrix;
    const lab = (id) => ctx.who(id, false);
    if (layer === "trade") {
      H(el, {
        rows: nodes, cols: nodes, label: lab, diverging: { min: -1, mid: 0, max: 1 },
        emptyText: "under 5 games",
        cell: (r, c) => {
          const p = R.pairs[pairKey(r, c)];
          if (!p) return null;
          const t = p.trade;
          if (p.tier !== "color") return { value: null, text: String(t.O), sub: "trades", tip: `<b>${ctx.esc(nm(ctx, r))} and ${ctx.esc(nm(ctx, c))}</b><div>${t.O} trades in ${p.games} shared games (counts only)</div>` };
          return { value: clamp(log2(t.exp_u), -1, 1), text: `×${ctx.num(t.exp_u, 2)}`, sub: `${t.O} vs ${ctx.num(t.E, 0)}`,
            tip: `<b>${ctx.esc(nm(ctx, r))} and ${ctx.esc(nm(ctx, c))}</b><div>${t.O} trades, ${ctx.num(t.E, 1)} expected</div><div>Pair effect ${uText(ctx, t)}</div>` };
        },
        scale: { low: "less than expected", high: "more" },
      });
    } else {
      H(el, {
        rows: nodes, cols: nodes, label: lab, directed: true, diverging: { min: -1, mid: 0, max: 1 },
        emptyText: "under 5 games",
        cell: (r, c) => {
          const d = R.directed[`${r}>${c}`];
          const p = R.pairs[pairKey(r, c)];
          if (!p) return null;
          if (!d) return { value: null, text: "0", sub: "steals", tip: `${ctx.esc(nm(ctx, r))} never robbed ${ctx.esc(nm(ctx, c))} here` };
          if (d.tier !== "color" || !fin(d.shrunk)) return { value: null, text: String(d.O), sub: "steals", tip: `<b>${ctx.esc(nm(ctx, r))} robbed ${ctx.esc(nm(ctx, c))}</b><div>${d.O} cards in ${p.games} shared games (counts only)</div>` };
          return { value: -clamp(log2(d.shrunk), -1, 1), text: `×${ctx.num(d.shrunk, 2)}`, sub: `${d.O} vs ${ctx.num(d.E, 0)}`,
            tip: `<b>${ctx.esc(nm(ctx, r))} robbed ${ctx.esc(nm(ctx, c))}</b><div>${d.O} cards, ${ctx.num(d.E, 1)} expected</div><div>Shrunk ×${ctx.num(d.shrunk, 2)} (${iv(ctx, d.lo, d.hi)}); raw ×${ctx.num(d.ratio, 2)}</div>` +
              `<div>Hex choice ${d.stage1.O} vs ${ctx.num(d.stage1.E, 1)}; victim pick ${d.stage2.O} vs ${ctx.num(d.stage2.E, 1)}</div>` };
        },
        scale: { low: "robs more than expected", high: "less" },
      });
    }
  }

  // ---- Cards ledger matrix ------------------------------------------------------------------------
  function ledgerHtml(ctx, nodes) {
    const L = RV(ctx).ledger || {};
    const max = Math.max(0.01, ...Object.values(L).map((l) => l.total100 || 0));
    const head = nodes.map((c) => `<th class="colh" scope="col">${ctx.who(c, false)}</th>`).join("");
    const body = nodes.map((r) => `<tr><th class="rowh" scope="row">${ctx.who(r, false)}</th>${nodes.map((c) => {
      if (r === c) return `<td><div class="cell self" aria-label="same player"></div></td>`;
      const l = L[`${r}>${c}`];
      if (!l) return `<td><div class="cell" style="--fill:transparent"><span>under 5 games</span></div></td>`;
      const w = (v) => Math.max(0, (v / max) * 64);
      const lab = `${nm(ctx, r)} cost ${nm(ctx, c)} ${ctx.num(l.total100, 2)} cards per 100 shared rolls: ${ctx.num(l.per100[0], 2)} stolen, ${ctx.num(l.per100[1], 2)} blocked, ${ctx.num(l.per100[2], 2)} by Monopoly`;
      return `<td><div class="cell" style="--fill:transparent" tabindex="0" role="img" aria-label="${ctx.esc(lab)}" data-tip="${ctx.esc(`<b>${ctx.esc(nm(ctx, r))} cost ${ctx.esc(nm(ctx, c))}</b><div>${l.steals} stolen, ${l.blocked} blocked, ${l.monopoly} by Monopoly</div><div>Per 100 shared rolls: ${ctx.num(l.per100[0], 2)} + ${ctx.num(l.per100[1], 2)} + ${ctx.num(l.per100[2], 2)}</div>`)}"><b>${ctx.num(l.total100, 1)}</b>
        <span class="stack" aria-hidden="true">${l.per100.map((v, i) => (v > 0 ? `<span class="${["sw-st", "sw-bl", "sw-mo"][i]}" style="width:${w(v).toFixed(1)}px;background:var(--c)"></span>` : "")).join("")}</span></div></td>`;
    }).join("")}</tr>`).join("");
    return `<div class="table-wrap"><table class="matrix directed ledger"><thead><tr><th class="corner"><span class="mx-corner">Row costs column</span></th>${head}</tr></thead><tbody>${body}</tbody></table></div>
      <ul class="legend" style="margin-top:10px"><li><span class="sw box sw-st"></span>Stolen</li><li><span class="sw box sw-bl"></span>Blocked by the robber</li><li><span class="sw box sw-mo"></span>Monopoly</li></ul>`;
  }

  // ---- Pair balance chart -----------------------------------------------------------------------
  const BAL_PARTS = [["position", "var(--data)"], ["retaliation", "var(--div-pos)"], ["beyond", "var(--ink)"]];
  function balanceChart(ctx, el, rows) {
    const svgEl = ctx.Charts.svgEl;
    responsive(el, (W) => {
      const narrow = W < 520, labW = narrow ? 76 : 110, rowH = 34;
      const m = { t: 6, r: 12, b: 28, l: labW };
      const iw = W - m.l - m.r, H = m.t + rows.length * rowH + m.b;
      let ext = 1;
      for (const b of rows) {
        const base = b.position + b.retaliation;
        const pos = BAL_PARTS.reduce((s, [k]) => s + Math.max(0, b[k]), 0), neg = BAL_PARTS.reduce((s, [k]) => s + Math.min(0, b[k]), 0);
        ext = Math.max(ext, pos, -neg, Math.abs(b.net), Math.abs(base + b.band[0]), Math.abs(base + b.band[1]));
      }
      const ticks = ctx.Charts.niceTicks(-ext, ext, narrow ? 4 : 6);
      const lo = ticks[0], hi = ticks[ticks.length - 1];
      const X = (v) => m.l + ((v - lo) / (hi - lo)) * iw;
      const svg = svgEl("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Pair robbery balance, three parts per pair with the model range" }, el);
      for (const t of ticks) {
        svgEl("line", { x1: X(t), x2: X(t), y1: m.t, y2: m.t + rows.length * rowH, stroke: t === 0 ? "var(--muted)" : "var(--hair)", "stroke-width": 1 }, svg);
        svgEl("text", { x: X(t), y: H - 10, "text-anchor": "middle" }, svg).textContent = (t < 0 ? "−" : t > 0 ? "+" : "") + Math.abs(t);
      }
      rows.forEach((b, i) => {
        const y = m.t + i * rowH, cy = y + rowH / 2;
        const g = svgEl("g", { tabindex: 0, role: "img", "aria-label": `${nm(ctx, b.a)} minus ${nm(ctx, b.b)}: net ${b.net}; dice and position ${b.position}; reaction ${b.retaliation}; beyond the model ${b.beyond}; model range ${b.band[0]} to ${b.band[1]}` }, svg);
        svgEl("rect", { class: "bg", x: 0, y, width: W, height: rowH, fill: "transparent", rx: 3 }, g);
        const t = svgEl("text", { x: m.l - 8, y: cy + 4, "text-anchor": "end", class: "lab" }, g);
        t.textContent = `${nm(ctx, b.a)} − ${nm(ctx, b.b)}`;
        const base = b.position + b.retaliation;
        svgEl("rect", { x: X(base + b.band[0]), y: cy - 11, width: Math.max(1, X(base + b.band[1]) - X(base + b.band[0])), height: 22, fill: "var(--band)", rx: 2 }, g);
        // Diverging stack: positive parts stack right of 0, negative parts left of 0, in a fixed order.
        let up = 0, down = 0;
        BAL_PARTS.forEach(([k, c]) => {
          const v = b[k];
          let a0, a1;
          if (v >= 0) { a0 = up; a1 = up + v; up = a1; } else { a0 = down + v; a1 = down; down = a0; }
          const x0 = X(a0), x1 = X(a1);
          if (x1 - x0 > 0.5) svgEl("rect", { x: x0 + (x1 - x0 > 3 ? 1 : 0), y: cy - 5, width: Math.max(0.5, x1 - x0 - (x1 - x0 > 3 ? 2 : 0)), height: 10, fill: c, rx: 1.5 }, g);
        });
        svgEl("line", { x1: X(b.net), x2: X(b.net), y1: cy - 10, y2: cy + 10, stroke: "var(--ink)", "stroke-width": 2, "stroke-linecap": "round" }, g);
        tip(ctx, g, `<b>${ctx.esc(nm(ctx, b.a))} robbed ${ctx.esc(nm(ctx, b.b))} ${b.O_ab}, the other way ${b.O_ba}</b><div>Net ${ctx.fmtSigned(b.net, 0)} = dice and position ${ctx.fmtSigned(b.position, 1)} + reaction ${ctx.fmtSigned(b.retaliation, 1)} + beyond the model ${ctx.fmtSigned(b.beyond, 1)}</div><div>Model range for the net: ${ctx.fmtSigned(base + b.band[0], 1)} to ${ctx.fmtSigned(base + b.band[1], 1)}</div>`);
      });
    });
  }

  // ---- Three-bar figure (leader, other opponent, recent partner) -------------------------------------
  function threeBars(ctx, el, bars) {
    const svgEl = ctx.Charts.svgEl;
    responsive(el, (W) => {
      const narrow = W < 480, labW = narrow ? 112 : 150, rowH = 36;
      const m = { t: 4, r: 16, b: 28, l: labW };
      const iw = W - m.l - m.r, H = m.t + bars.length * rowH + m.b;
      const ticks = ctx.Charts.niceTicks(0, Math.max(...bars.map((b) => b.hi)), narrow ? 3 : 5);
      const hi = ticks[ticks.length - 1];
      const X = (v) => m.l + (Math.max(0, v) / hi) * iw;
      const svg = svgEl("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Stage 1 weight per pip of income by owner" }, el);
      for (const t of ticks) {
        svgEl("line", { x1: X(t), x2: X(t), y1: m.t, y2: m.t + bars.length * rowH, stroke: "var(--hair)", "stroke-width": 1 }, svg);
        svgEl("text", { x: X(t), y: H - 10, "text-anchor": "middle" }, svg).textContent = String(+t.toFixed(3));
      }
      bars.forEach((b, i) => {
        const cy = m.t + i * rowH + rowH / 2;
        const g = svgEl("g", { tabindex: 0, role: "img", "aria-label": `${b.label}: ${b.w} per pip, 95% interval ${b.lo} to ${b.hi}` }, svg);
        svgEl("rect", { class: "bg", x: 0, y: cy - rowH / 2, width: W, height: rowH, fill: "transparent", rx: 3 }, g);
        svgEl("text", { x: m.l - 8, y: cy + 4, "text-anchor": "end", class: "lab" }, g).textContent = b.label;
        svgEl("rect", { x: m.l, y: cy - 7, width: Math.max(1, X(b.w) - m.l), height: 14, fill: i === 2 ? "var(--div-pos)" : "var(--data)", rx: 2 }, g);
        svgEl("line", { x1: X(b.lo), x2: X(b.hi), y1: cy, y2: cy, stroke: "var(--ink)", "stroke-width": 1.5 }, g);
        for (const v of [b.lo, b.hi]) svgEl("line", { x1: X(v), x2: X(v), y1: cy - 5, y2: cy + 5, stroke: "var(--ink)", "stroke-width": 1.5 }, g);
        tip(ctx, g, `<b>${ctx.esc(b.label)}</b><div>${ctx.num(b.w, 3)} log odds per pip (${ctx.num(b.lo, 3)} to ${ctx.num(b.hi, 3)})</div><div>A settlement on a 6 or 8 (5 pips): odds ×${ctx.num(Math.exp(5 * b.w), 2)}</div>`);
      });
    });
  }

  // ---- Sections ------------------------------------------------------------------------------------
  function overpunishHtml(ctx, nodes) {
    const A = RA(ctx), R = RV(ctx), L = A.leader, s7 = L.seven, kn = L.knight;
    const ee = R.early_excess || {};
    const lostRows = nodes.filter((p) => R.cards_lost[p]);
    const cell = (x) => `${ctx.fmtSigned(x.mean, 2)} <span class="sub">(${fin(x.lo) ? `${ctx.fmtSigned(x.lo, 2)} to ${ctx.fmtSigned(x.hi, 2)}` : "n/a"})</span>`;
    const pir = R.pirate;
    return `<section class="block" id="overpunishment">
      <h2>Overpunishment</h2>
      <p class="note">Who loses cards to deliberate opponent actions, and is anyone robbed more than their position explains? Robbing the leader or the best producer is good play, so the fair comparison is a model: fit on every robber move, it learns how likely each player was to be hit given the board, hands, the visible score and recent robberies. Each player's cards stolen are then compared with what the model expected (using a fit that never saw that mover's own choices). Monopoly is shown separately, discards on 7s are left out, and pirates are only counted.${sourceNote(ctx)}</p>
      <h3>Leader tax ${ctx.info("op_leader", "Leader tax")}</h3>
      <div class="tiles net-tiles">
        ${ctx.Charts.statTile({ value: `×${ctx.num(s7.stage2_vp.or, 2)}`, label: "Odds of being the victim, per public VP closer to the lead", sub: `after a 7; 95% interval ${ctx.num(s7.stage2_vp.or_lo, 2)} to ${ctx.num(s7.stage2_vp.or_hi, 2)}. Knights ×${ctx.num(kn.stage2_vp.or, 2)} (${ctx.num(kn.stage2_vp.or_lo, 2)} to ${ctx.num(kn.stage2_vp.or_hi, 2)})` })}
        ${ctx.Charts.statTile({ value: `×${ctx.num(s7.premium, 2)}`, label: "How much more a dot of the leader's income draws the robber", sub: `than a dot of another opponent's, when choosing the hex after a 7; 95% ${iv(ctx, s7.premium_lo, s7.premium_hi)}. Knights ×${ctx.num(kn.premium, 2)}` })}
        ${ctx.Charts.statTile({ value: ctx.pct(L.base_rate_all), label: "Robber placements touching a public-VP leader", sub: `${ctx.pct(L.uniform_rate_all)} if every legal hex were equally likely; ${A.counts.land_moves} placements` })}
      </div>
      <p class="note net-sec-note"><b>How to read:</b> what the robber model learned. The rows without "Victim" are about which hex the robber goes to; the "Victim" rows are about whom it steals from on that hex. Each dot is an odds ratio: above 1 makes that hex or victim more likely, below 1 less. "Per pip" means per dot of income on the hex. Lines are 95% intervals, some too narrow to see. 7s and knights are fit separately.</p>
      <div class="two-col" style="margin-top:12px">
        <div><h3>After a 7 <span class="sub">${A.stage1.seven.n} moves, ${A.stage2.seven.n} victim picks</span> ${ctx.info("net_robber", "Shared robber model")}</h3><div class="panel" style="margin-top:8px"><div class="chart" id="op-coef-7"></div>${coefTable(ctx, "seven")}</div></div>
        <div><h3>After a knight <span class="sub">${A.stage1.knight.n} moves, ${A.stage2.knight.n} victim picks</span></h3><div class="panel" style="margin-top:8px"><div class="chart" id="op-coef-k"></div>${coefTable(ctx, "knight")}</div></div>
      </div>
      <h3 style="margin-top:28px">Robbed beyond the board ${ctx.info("op_target", "Targeting beyond board state")}</h3>
      <p class="note"><b>How to read:</b> cards stolen from each player divided by what the robber model expected. ×1 means robbed exactly as much as their position explains; right of the line, targeted more. Filled dot: the model-based number, shrunk toward the group. Hollow ring: against a simple even split among the players who could be robbed on the chosen hex.${R.targeting_meta && !R.targeting_meta.gate_open ? " The players' ratios are not clearly different from one another (Cochran's Q p = " + ctx.num(R.targeting_meta.p, 2) + "), so the estimates are pulled hard toward the group." : ""}</p>
      ${Object.keys(R.targeting || {}).length ? `<div class="panel"><div class="chart" id="op-target"></div>
        ${ctx.tableView([{ label: "Player" }, { label: "Games", num: true }, { label: "Stolen", num: true }, { label: "Expected", num: true }, { label: "O − E cards", num: true }, { label: "Shrunk ratio", num: true }, { label: "95% interval", num: true }, { label: "Even split ratio", num: true }],
          nodes.filter((p) => R.targeting[p]).map((p) => { const t = R.targeting[p]; return [ctx.who(p), t.games, t.O, ctx.num(t.E, 1), ctx.fmtSigned(t.o_minus_e, 1), ctx.num(t.shrunk, 2), iv(ctx, t.lo, t.hi), ctx.num(t.even.ratio, 2)]; }))}</div>` : ctx.guardNote(0, 10)}
      <h3 style="margin-top:28px">Cards lost to opponents, vs the table ${ctx.info("op_lost", "Cards lost relative to the table")}</h3>
      <p class="note">Cards per game a player lost to opponents, above (+) or below (−) the average of their tablemates, with 95% intervals. Positive means they lost more than the people they played with. Monopoly is shown on its own and never added in.</p>
      ${lostRows.length ? `<div class="panel table-wrap"><table><thead><tr><th>Player</th><th class="num">Games</th><th class="num">Stolen</th><th class="num">Blocked by robbers</th><th class="num">Monopoly (separate)</th></tr></thead><tbody>
        ${lostRows.map((p) => { const x = R.cards_lost[p]; return `<tr><td>${ctx.who(p)}</td><td class="num">${x.games}</td><td class="num">${cell(x.stolen)}</td><td class="num">${cell(x.blocked)}</td><td class="num">${cell(x.monopoly)}</td></tr>`; }).join("")}</tbody></table></div>` : ctx.guardNote(0, 10)}
      <h3 style="margin-top:28px">Pirates ${ctx.info("op_pirate", "Pirate moves")}</h3>
      <p class="note">${pir.moves ? `${pir.moves} pirate moves stole ${pir.steals} cards in this view. They are not in the models. ${nodes.filter((p) => pir.by_player[p]).map((p) => `${ctx.esc(nm(ctx, p))} moved it ${pir.by_player[p].moves} times and lost ${pir.by_player[p].stolen_from}`).join("; ")}.` : "No pirate moves in this view."}</p>
      <h3 style="margin-top:28px">Early robbing and winning <span class="sub">exploratory</span> ${ctx.info("op_early", "Early excess targeting and winning")}</h3>
      ${fin(ee.gamma) ? `<div class="tiles net-tiles">${ctx.Charts.statTile({ value: `×${ctx.num(ee.or, 2)}`, label: "Odds of winning per extra early card stolen beyond the model", sub: `Below ×1 means players who robbed more than expected early went on to win less often. 95% ×${ctx.num(ee.or_lo, 2)} to ×${ctx.num(ee.or_hi, 2)} per card; ${ee.games} games, adjusted for pre-game skill and opening dots.` })}</div>
        <p class="note net-sec-note">Exploratory: chosen after looking at the data, so it is an estimate with an interval, not a test. Robbing early can be a reaction to a strong start, which this cannot separate.</p>` : ctx.guardNote(ee.has || 0, ee.needs || 40)}
    </section>`;
  }

  function coefTable(ctx, cause) {
    const A = RA(ctx);
    const rows = A.stage1[cause].coef.map((c) => [ctx.esc(c.label), ctx.fmtSigned(c.b, 3), ctx.num(c.se, 3), `×${ctx.num(c.or, 2)}`])
      .concat(A.stage2[cause] ? A.stage2[cause].coef.map((c) => [`Victim pick: ${ctx.esc(c.label)}`, ctx.fmtSigned(c.b, 3), ctx.num(c.se, 3), `×${ctx.num(c.or, 2)}`]) : []);
    return ctx.tableView([{ label: "Term" }, { label: "β", num: true }, { label: "SE", num: true }, { label: "Odds ratio", num: true }], rows);
  }

  function tradeRobHtml(ctx, nodes) {
    const A = RA(ctx), R = RV(ctx), P = A.partner;
    const who = P.caption === "just" ? "people you just traded with" : "people you trade with";
    const bal = Object.values(R.pairs).filter((p) => p.balance).map((p) => p.balance);
    const tm = A.trade_model;
    const hitRows = nodes.filter((p) => R.partner_hit[p]);
    return `<section class="block" id="trade-and-rob">
      <h2>Trade and rob</h2>
      <p class="note">Do we spare ${who}, or rob them anyway? "Recent" means a trade in the last 2 rounds. The betrayal index compares how strongly a recent partner's income draws the robber with another trailing opponent's: 1 means no difference, below 1 means partners are spared, above 1 means they get hit harder.</p>
      <div class="tiles net-tiles">
        ${ctx.Charts.statTile({ value: ctx.num(P.rho, 2), label: `Betrayal index ${ctx.info("tr_betrayal", "Betrayal index")}`, sub: `A recent partner's income counts ${ctx.num(P.rho, 2)}× as much as another trailing opponent's. 95% ${iv(ctx, P.lo, P.hi)}. 1 = no difference.` })}
        ${ctx.Charts.statTile({ value: `×${ctx.num(A.leader.seven.premium, 2)}`, label: `Leader tax, per pip ${ctx.info("op_leader", "Leader tax")}`, sub: "the leader's income against another opponent's, same model" })}
        ${ctx.Charts.statTile({ value: String(P.informative), label: "7s with a recent partner on the board", sub: `of ${P.moves} robber moves after a 7` })}
      </div>
      <h3 style="margin-top:20px">How much a pip of income draws the robber, by owner</h3>
      <p class="note"><b>How to read:</b> after a 7, how strongly one dot of income on a hex attracts the robber, depending on whose income it is. Longer bar means a more tempting target. Compare the blue bar (a recent trade partner's income) with "Other opponent": shorter means recent partners are spared. Bars are on the log odds scale with 95% intervals; a dot is one number dot under one settlement.</p>
      <div class="panel"><div class="chart tbar" id="tr-bars"></div>
        ${ctx.tableView([{ label: "Owner" }, { label: "Weight per pip", num: true }, { label: "95% interval", num: true }], P.bars.map((b) => [b.label, ctx.num(b.w, 3), `${ctx.num(b.lo, 3)} to ${ctx.num(b.hi, 3)}`]))}</div>
      <h3 style="margin-top:28px">Every refit ${ctx.info("tr_sens", "Betrayal index sensitivity rows")}</h3>
      <p class="note"><b>How to read:</b> the betrayal index recomputed many ways, including for each player as the robber. Left of 1: recent partners spared; right: hit harder. If most rows sit on the same side, the finding doesn't hinge on one modeling choice. The lag placebo row uses trades 2 to 4 rounds back instead; it ${P.caption === "just" ? "includes 1, so the effect belongs to recent partners: the wording is \"people you just traded with\"" : "does not include 1, so the wording is \"people you trade with\""}.</p>
      <div class="panel"><div class="chart" id="tr-sens"></div>
        ${ctx.tableView([{ label: "Fit" }, { label: "ρ", num: true }, { label: "95% interval", num: true }, { label: "Moves", num: true }], P.sensitivity.map((r) => [sensLabel(ctx, r), ctx.num(r.rho, 2), iv(ctx, r.lo, r.hi), r.n]))}</div>
      <h3 style="margin-top:28px">Partner hit ratio by player ${ctx.info("tr_hit", "Per-player partner hit ratio")}</h3>
      ${hitRows.length ? `<p class="note">${R.partner_hit_meta && R.partner_hit_meta.gate_open ? "Players differ (Cochran's Q p = " + ctx.num(R.partner_hit_meta.p, 3) + ")." : "<b>No player differs from the group yet.</b> The estimates below are pulled to the group ratio."} Players with 10 games and 20 informative placements, in leaderboard order.</p>
        <div class="panel"><div class="chart" id="tr-hit"></div>
        ${ctx.tableView([{ label: "Player" }, { label: "Placements", num: true }, { label: "Hit a partner", num: true }, { label: "Expected", num: true }, { label: "Shrunk ratio", num: true }, { label: "95% interval", num: true }],
          hitRows.map((p) => { const h = R.partner_hit[p]; return [ctx.who(p), h.placements, h.O, ctx.num(h.E, 1), ctx.num(h.shrunk, 2), iv(ctx, h.lo, h.hi)]; }))}</div>` : `<p class="empty">No player has 10 games and 20 informative placements in this view.</p>`}
      <h3 style="margin-top:28px">Pair robbery balance ${ctx.info("tr_balance", "Pair robbery balance")}</h3>
      <p class="note"><b>How to read:</b> each row is a pair, say A − B. The tick is the net: cards A stole from B minus cards B stole from A, over their shared games (pairs with 10 or more). The bars split that net into what the dice and board explain (gray), payback for earlier robberies (blue) and what is left over (dark). Positive parts stack right, negative left. The shaded band is where the model puts the net 95% of the time; a tick outside it is a grudge the board doesn't explain.</p>
      ${bal.length ? `<ul class="legend"><li><span class="sw box" style="--c:var(--data)"></span>Dice and position</li><li><span class="sw box" style="--c:var(--div-pos)"></span>Reaction to earlier robberies</li><li><span class="sw box" style="--c:var(--ink)"></span>Beyond the model</li><li><span class="sw box band"></span>Model range for the net</li><li><span class="sw vtick"></span>Net</li></ul>
        <div class="panel"><div class="chart bal" id="tr-bal"></div>
        ${ctx.tableView([{ label: "Pair" }, { label: "Net", num: true }, { label: "Dice and position", num: true }, { label: "Reaction", num: true }, { label: "Beyond", num: true }, { label: "Model range", num: true }],
          bal.map((b) => [`${ctx.who(b.a, false)} − ${ctx.who(b.b, false)}`, ctx.fmtSigned(b.net, 0), ctx.fmtSigned(b.position, 1), ctx.fmtSigned(b.retaliation, 1), ctx.fmtSigned(b.beyond, 1), `${ctx.fmtSigned(b.position + b.retaliation + b.band[0], 1)} to ${ctx.fmtSigned(b.position + b.retaliation + b.band[1], 1)}`]))}</div>` : `<p class="empty">No pair has 10 shared games in this view.</p>`}
      <h3 style="margin-top:28px">Grudges and the leader in trading ${ctx.info("tr_grudge", "Grudge terms")}</h3>
      <p class="note"><b>How to read:</b> what makes someone more likely to be picked as a trade partner, from ${tm.n_trades} trades. Above 1: more likely to be picked; below 1: less. Here, leading on visible VP makes a player ${tm.leader.b < 0 ? "less" : "more"} popular to trade with (×${ctx.num(Math.exp(tm.leader.b), 2)}), and holding more cards makes them ${tm.hand.b > 0 ? "more" : "less"} popular (that row is per step of log(1 + cards), roughly per doubling of the hand).</p>
      <div class="panel"><div class="chart" id="tr-grudge"></div></div>
    </section>`;
  }

  function sensLabel(ctx, r) {
    if (r.pid) return `${ctx.who(r.pid, false)} moving`;
    return ctx.esc(r.name);
  }

  function pairsHtml(ctx, nodes) {
    const R = RV(ctx);
    const pr = R.premium || {};
    const rows = nodes.filter((p) => pr[p]);
    const terms = Object.entries(R.pairs).filter(([, p]) => p.terms && (p.terms.ab || p.terms.ba));
    return `<section class="block" id="pairs">
      <h2>Trading terms and setup contention</h2>
      <h3>Roller premium ${ctx.info("net_terms", "Roller premium and terms of trade")}</h3>
      <p class="note"><b>How to read:</b> when trading on their own turn, how many cards a player gives per card they get, compared with everyone else, who give ${ctx.num((pr._field || {}).P, 2)} per card on average. ×1 is the usual price; left means they get better deals, right means they pay more.</p>
      ${rows.length ? `<div class="panel"><div class="chart" id="pr-prem"></div>
        ${ctx.tableView([{ label: "Player" }, { label: "Trades as roller", num: true }, { label: "Given per received", num: true }, { label: "vs the field", num: true }, { label: "95% interval", num: true }],
          rows.map((p) => [ctx.who(p), pr[p].trades, ctx.num(pr[p].P, 2), `×${ctx.num(pr[p].ratio, 2)}`, iv(ctx, pr[p].lo, pr[p].hi)]))}</div>` : ctx.guardNote(0, 10)}
      <p class="note">Pair terms of trade need 20 trades each way over 10 shared games. ${terms.length ? `${terms.length} ${terms.length === 1 ? "pair qualifies" : "pairs qualify"}; select an edge on the graph to see them.` : "No pair qualifies in this view."}</p>
      ${terms.length ? `<div class="panel table-wrap" style="margin-top:8px"><table><thead><tr><th>Roller</th><th>Partner</th><th class="num">Trades</th><th class="num">Terms vs other partners</th><th class="num">95% interval</th></tr></thead><tbody>
        ${terms.flatMap(([k, p]) => { const [a, b] = k.split("|"); return [[a, b, p.terms.n_ab, p.terms.ab], [b, a, p.terms.n_ba, p.terms.ba]]; }).filter((r) => r[3])
          .map(([a, b, n, t]) => `<tr><td>${ctx.who(a)}</td><td>${ctx.who(b)}</td><td class="num">${n}</td><td class="num">×${ctx.num(t.rho, 2)}</td><td class="num">${iv(ctx, t.lo, t.hi)}</td></tr>`).join("")}</tbody></table></div>
        <p class="note">Above 1: the roller gives more per card received when trading with that partner than with anyone else.</p>` : ""}
      <h3 style="margin-top:28px">Setup contention ${ctx.info("net_contention", "Board contention at setup")}</h3>
      <p class="note">How much two players' starting settlements compete: the number dots on hexes both of them touch at the first roll, per shared game. Darker means they tend to start on the same hexes and share the same numbers.</p>
      <div class="panel" style="padding:12px"><p class="note" style="margin:0 0 10px">Average shared dots at the first roll, per shared game.</p><div id="pr-cont"></div></div>
    </section>`;
  }

  // ---- Page --------------------------------------------------------------------------------------
  function render(ctx) {
    const R = RV(ctx), A = RA(ctx);
    if (!R || !A) {
      ctx.main.innerHTML = `<h1>Network</h1>${ctx.filterBar()}<p class="empty">No decoded replays in these games yet.</p>`;
      return;
    }
    const nodes = order(ctx).filter((p) => R.nodes[p]);
    let layer = "trade";
    try { layer = localStorage.getItem("net-layer") === "robber" ? "robber" : "trade"; } catch (e) { /* storage blocked */ }
    let sel = null;
    const tsrc = R.trade_source === "all games" ? " The trade model is from all games (this view has under 30)." : "";
    ctx.main.innerHTML = `
      <h1>Network</h1>
      <p class="lede">Who trades with whom, and who robs whom, beyond what each player's tendencies, the board and the score explain.</p>
      <p class="note">Most numbers here are ratios against a model's expectation: ×1.00 means exactly what the board, hands and score predict, ×1.20 means 20% more, ×0.80 20% less. Some estimates are "shrunk": pulled toward the group average so a player with few games can't look extreme by luck. Every interval is 95%.</p>
      ${ctx.filterBar()}
      <section class="block">
        <h2>Trades and robberies ${ctx.info("net_graph", "Network graph")}</h2>
        <div class="net-head"><div class="seg" role="group" aria-label="Layer">
          <button type="button" data-layer="trade" aria-pressed="${layer === "trade"}">Trade</button>
          <button type="button" data-layer="robber" aria-pressed="${layer === "robber"}">Robber</button></div>
          <span class="note" id="net-layer-info"></span></div>
        <div class="net-grid">
          <div class="panel net-graph"><div id="net-svg"></div><div id="net-legend"></div></div>
          <div class="panel net-panel" id="net-panel" aria-live="polite"></div>
        </div>
        <p class="note">${R.games} games, ${R.trades} trades, ${R.land_moves} robber moves on land.${tsrc}${sourceNote(ctx)}</p>
        <div class="panel" style="margin-top:14px;padding:12px"><p class="note" id="net-matrix-cap" style="margin:0 0 10px"></p><div id="net-matrix"></div></div>
      </section>
      <section class="block">
        <h2>Cards cost ledger ${ctx.info("net_ledger", "Cards cost ledger")}</h2>
        <p class="note"><b>How to read:</b> read across a row: the number is how many cards that player cost each opponent per 100 rolls they played together. The bar splits it into cards stolen, production blocked by the robber, and cards taken with Monopoly. Pairs with at least 5 shared games.</p>
        <div class="panel" style="padding:12px">${ledgerHtml(ctx, nodes)}</div>
      </section>
      ${overpunishHtml(ctx, nodes)}
      ${tradeRobHtml(ctx, nodes)}
      ${pairsHtml(ctx, nodes)}`;

    const panel = document.getElementById("net-panel");
    const setPanel = () => {
      panel.innerHTML = !sel ? defaultPanel(ctx, layer) : sel.p ? playerPanel(ctx, sel.p) : pairPanel(ctx, sel.a, sel.b);
    };
    const drawLayer = () => {
      ctx.main.querySelectorAll("[data-layer]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.layer === layer)));
      document.getElementById("net-layer-info").innerHTML = layer === "trade" ? ctx.info("net_trade", "Trade partner preference") : ctx.info("net_robber", "Shared robber model");
      document.getElementById("net-legend").innerHTML = graphLegend(ctx, layer);
      const svgBox = document.getElementById("net-svg");
      svgBox.innerHTML = "";
      drawGraph(ctx, svgBox, layer, nodes, (s) => { sel = s; setPanel(); redraw(); }, sel);
      document.getElementById("net-matrix-cap").textContent = layer === "trade"
        ? "How to read: each cell is how much more (above ×1) or less (below ×1) that pair trades together than their overall habits predict. Small text: trades seen vs expected. Uncolored cells have only 5 to 9 shared games, so they show counts only."
        : "How to read: read across a row. Each cell is cards the row player stole from the column player divided by what the robber model expected (shrunk toward ×1). Above ×1: robbed them more than the board explains. Small text: stolen vs expected. Uncolored cells have only 5 to 9 shared games, so they show counts only.";
      matrixFor(ctx, document.getElementById("net-matrix"), layer, nodes);
      setPanel();
    };
    const redraw = () => {
      // Keep the selection highlight without losing keyboard focus.
      const svgBox = document.getElementById("net-svg");
      svgBox.querySelectorAll(".edge, .node").forEach((g) => g.classList.remove("on"));
      const lab = document.activeElement && document.activeElement.getAttribute && document.activeElement.getAttribute("aria-label");
      svgBox.innerHTML = "";
      drawGraph(ctx, svgBox, layer, nodes, (s) => { sel = s; setPanel(); redraw(); }, sel);
      if (lab) { const again = [...svgBox.querySelectorAll("[aria-label]")].find((e) => e.getAttribute("aria-label") === lab); if (again) again.focus(); }
    };
    ctx.main.querySelectorAll("[data-layer]").forEach((b) => b.addEventListener("click", () => {
      layer = b.dataset.layer;
      try { localStorage.setItem("net-layer", layer); } catch (e) { /* storage blocked */ }
      drawLayer();
    }));
    drawLayer();
    drawCharts(ctx, nodes);
  }

  function drawCharts(ctx, nodes) {
    const A = RA(ctx), R = RV(ctx), C = ctx.Charts;
    const keyFeat = ["lead_inc", "other_inc", "own_inc", "gap_inc", "retal", "n_steal"];
    const SHORT = { lead_inc: "Leader's income, per pip", other_inc: "Other opponent's income, per pip", own_inc: "Own income, per pip",
      gap_inc: "Non-leader income × VP behind, per pip-VP", retal: "Touches a recent robber of the mover", n_steal: "Each opponent with cards to steal",
      vp_gap: "Victim: per VP closer to the lead", retal2: "Victim: robbed the mover recently" };
    for (const [cause, id] of [["seven", "op-coef-7"], ["knight", "op-coef-k"]]) {
      const el = document.getElementById(id);
      if (!el) continue;
      const rows = A.stage1[cause].coef.filter((c) => keyFeat.includes(c.key)).map((c) => ({ label: C.esc(SHORT[c.key]), b: c.b, se: c.se }))
        .concat(A.stage2[cause] ? A.stage2[cause].coef.filter((c) => c.key !== "hand").map((c) => ({ label: C.esc(SHORT[c.key === "retal" ? "retal2" : c.key]), b: c.b, se: c.se })) : []);
      C.coefPlot(el, { rows, exp: true, xTitle: "Odds ratio (log scale)", rowHeight: window.innerWidth < 520 ? 52 : 40 });
    }
    const tEl = document.getElementById("op-target");
    if (tEl) {
      C.forestPlot(tEl, {
        log: true, ref: 1, xTitle: "Cards stolen ÷ expected", leftLabel: "robbed less", rightLabel: "robbed more",
        names: { est: "Board-adjusted (shrunk)", hollow: "Even split", interval: "95% interval" },
        rows: nodes.filter((p) => R.targeting[p]).map((p) => { const t = R.targeting[p]; return { label: ctx.who(p, false), est: t.shrunk, lo: t.lo, hi: t.hi, hollow: t.even.ratio, color: ctx.color(p),
          note: `${t.O} cards vs ${ctx.num(t.E, 1)} expected (${ctx.fmtSigned(t.o_minus_e, 1)}); raw ×${ctx.num(t.ratio, 2)}` }; }),
      });
    }
    const bEl = document.getElementById("tr-bars");
    if (bEl) threeBars(ctx, bEl, A.partner.bars);
    const sEl = document.getElementById("tr-sens");
    if (sEl) {
      C.forestPlot(sEl, {
        log: true, ref: 1, xTitle: "Betrayal index ρ (log scale)", leftLabel: "partners spared", rightLabel: "partners hit harder",
        names: { est: "ρ", interval: "95% Fieller interval" }, legend: false, rowHeight: window.innerWidth < 520 ? 40 : 32,
        rows: A.partner.sensitivity.map((r) => ({ label: sensLabel(ctx, r), est: r.rho, lo: r.lo, hi: r.hi, color: r.pid ? ctx.color(r.pid) : r.key === "main" ? "var(--ink)" : "var(--data)",
          note: fin(r.lo) ? `${r.n} moves` : `${r.n} moves; the interval is not bounded` })),
      });
    }
    const hEl = document.getElementById("tr-hit");
    if (hEl) {
      C.forestPlot(hEl, {
        log: true, ref: 1, xTitle: "Placements touching a recent partner ÷ expected", leftLabel: "gives partners more slack", rightLabel: "treats partners like anyone else",
        names: { est: "Shrunk ratio", hollow: "Raw ratio", interval: "95% interval" },
        rows: order(ctx).filter((p) => R.partner_hit[p]).map((p) => { const h = R.partner_hit[p]; return { label: ctx.who(p, false), est: h.shrunk, lo: h.lo, hi: h.hi, hollow: h.ratio, color: ctx.color(p), note: `${h.O} of ${h.placements} placements vs ${ctx.num(h.E, 1)} expected` }; }),
      });
    }
    const balEl = document.getElementById("tr-bal");
    if (balEl) balanceChart(ctx, balEl, Object.values(R.pairs).filter((p) => p.balance).map((p) => p.balance));
    const gEl = document.getElementById("tr-grudge");
    if (gEl) {
      const tm = R.trade_model || A.trade_model;
      const row = (label, t) => ({ label, b: t.b, se: t.se });
      C.coefPlot(gEl, { exp: true, xTitle: "Odds ratio of being picked as partner (log scale)", rowHeight: window.innerWidth < 520 ? 44 : 32,
        rows: [row("Stole from the roller recently", tm.robbed_me), row("Roller stole from them recently", tm.i_robbed), row("Leads on public VP", tm.leader), row("Hand size, per log(1 + cards)", tm.hand)] });
    }
    const pEl = document.getElementById("pr-prem");
    if (pEl) {
      C.forestPlot(pEl, {
        log: true, ref: 1, xTitle: "Cards given per card received, ÷ the field", leftLabel: "gets better terms", rightLabel: "pays more",
        names: { est: "Ratio to the field", interval: "95% bootstrap interval" }, legend: false,
        rows: nodes.filter((p) => R.premium[p]).map((p) => { const x = R.premium[p]; return { label: ctx.who(p, false), est: x.ratio, lo: x.lo, hi: x.hi, color: ctx.color(p), note: `${x.trades} trades as roller: gave ${x.given}, got ${x.received}` }; }),
      });
    }
    const cEl = document.getElementById("pr-cont");
    if (cEl) {
      const vals = Object.values(R.pairs).map((p) => p.contention && p.contention.mean).filter(fin);
      C.heatMatrix(cEl, {
        rows: nodes, cols: nodes, label: (id) => ctx.who(id, false), sequential: { min: 0, max: Math.max(1, ...vals) },
        emptyText: "under 5 games",
        cell: (r, c) => {
          const p = R.pairs[pairKey(r, c)];
          if (!p || !p.contention) return null;
          return { value: p.contention.mean, text: ctx.num(p.contention.mean, 1), sub: `${p.games} games`,
            tip: `<b>${ctx.esc(nm(ctx, r))} and ${ctx.esc(nm(ctx, c))}</b><div>${ctx.num(p.contention.mean, 1)} shared dots per game (${iv(ctx, p.contention.lo, p.contention.hi, 1)})</div>` };
        },
        scale: { low: "0", high: "more shared" },
      });
    }
  }

  (window.Pages = window.Pages || {})[PAGE] = { render };

  // ---- Player page hook -------------------------------------------------------------------------
  (window.Hooks.player = window.Hooks.player || []).push({
    html(ctx, pid) {
      const R = RV(ctx);
      if (!R || !RA(ctx)) return "";
      const t = (R.targeting || {})[pid], h = (R.partner_hit || {})[pid], pr = (R.premium || {})[pid];
      const ord = order(ctx);
      const other = (k) => k.split("|").find((x) => x !== pid);
      const arcs = Object.entries(R.pairs).filter(([k, p]) => p.tier === "color" && k.split("|").includes(pid))
        .sort((x, y) => ord.indexOf(other(x[0])) - ord.indexOf(other(y[0])));
      if (!t && !arcs.length) return "";
      const tiles = [];
      if (t) tiles.push(ctx.Charts.statTile({ value: `×${ctx.num(t.shrunk, 2)}`, label: `Robbed vs the board ${ctx.info("op_target", "Targeting beyond board state")}`, sub: `${t.O} cards vs ${ctx.num(t.E, 1)} expected (${ctx.fmtSigned(t.o_minus_e, 1)}); 95% ${iv(ctx, t.lo, t.hi)}` }));
      if (h) tiles.push(ctx.Charts.statTile({ value: `×${ctx.num(h.shrunk, 2)}`, label: `Hits recent trade partners ${ctx.info("tr_hit", "Per-player partner hit ratio")}`, sub: `${h.O} of ${h.placements} placements vs ${ctx.num(h.E, 1)} expected${R.partner_hit_meta && !R.partner_hit_meta.gate_open ? "; no player differs from the group yet" : ""}` }));
      if (pr) tiles.push(ctx.Charts.statTile({ value: `×${ctx.num(pr.ratio, 2)}`, label: `Roller premium ${ctx.info("net_terms", "Roller premium and terms of trade")}`, sub: `gives ${ctx.num(pr.P, 2)} per card received on own turn; 95% ${iv(ctx, pr.lo, pr.hi)}` }));
      const rows = arcs.map(([k, p]) => {
        const o = k.split("|").find((x) => x !== pid);
        const out = R.directed[`${pid}>${o}`], inn = R.directed[`${o}>${pid}`];
        const f = (d) => (d && fin(d.shrunk) ? `×${ctx.num(d.shrunk, 2)} <span class="sub">${d.O} vs ${ctx.num(d.E, 0)}</span>` : "n/a");
        return `<tr><td>${ctx.who(o)}</td><td class="num">${p.games}</td><td class="num">${f(out)}</td><td class="num">${f(inn)}</td><td class="num">${p.trade.O} <span class="sub">${ctx.num(p.trade.per100, 1)} per 100 rolls</span></td></tr>`;
      }).join("");
      return `<section class="block"><h2>Robber and trades</h2>
        <p class="note">Against the shared robber model and the trade partner model. More on the <a href="#/network">Network</a> page.</p>
        ${tiles.length ? `<div class="tiles">${tiles.join("")}</div>` : ""}
        ${rows ? `<div class="panel table-wrap" style="margin-top:12px"><table><thead><tr><th>With</th><th class="num">Shared games</th><th class="num">Robs them ${ctx.info("net_robber", "Shared robber model")}</th><th class="num">Robbed by them</th><th class="num">Trades together</th></tr></thead><tbody>${rows}</tbody></table></div>
        <p class="note">Robbing columns: cards stolen divided by what the robber model expected, shrunk toward ×1 (small text: stolen vs expected). Above ×1 means more than the board explains. Pairs with 10 or more shared games.</p>` : ""}
      </section>`;
    },
  });

  // ---- Findings hook ------------------------------------------------------------------------------
  (window.Hooks.findings = window.Hooks.findings || []).push({
    html(ctx) {
      const A = RA(ctx);
      if (!A) return "";
      const s7 = A.leader.seven, P = A.partner;
      return `<section class="block"><h2>The robber, the leader and trade partners</h2>
        <p class="note">From the shared robber model on all games (${A.counts.land_moves} robber moves, 7s and knights fit separately). Details, per-player and per-pair numbers are on the <a href="#/network">Network</a> page.</p>
        <div class="tiles">
          ${ctx.Charts.statTile({ value: `×${ctx.num(s7.stage2_vp.or, 2)}`, label: `Leader tax, per public VP ${ctx.info("op_leader", "Leader tax")}`, sub: `after a 7, each visible VP closer to the lead multiplies the odds of being the one robbed by this much; 95% ${ctx.num(s7.stage2_vp.or_lo, 2)} to ${ctx.num(s7.stage2_vp.or_hi, 2)}` })}
          ${ctx.Charts.statTile({ value: ctx.pct(A.leader.base_rate_all), label: "Robber placements touching the leader", sub: `against ${ctx.pct(A.leader.uniform_rate_all)} if it went on a random legal hex` })}
          ${ctx.Charts.statTile({ value: ctx.num(P.rho, 2), label: `Betrayal index ${ctx.info("tr_betrayal", "Betrayal index")}`, sub: `when choosing where to put the robber, a recent trade partner's income counts ${ctx.num(P.rho, 2)}× as much as another trailing opponent's (1 = no difference, below 1 = partners spared); 95% ${iv(ctx, P.lo, P.hi)}` })}
        </div></section>`;
    },
  });
})();
