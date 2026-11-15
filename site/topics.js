/* Topic pages and the questions index.
   The charts are still drawn by the original renderers (app.js style and findings blocks, network.js and the
   hook modules). This file only says where each section lives now, what question it answers, and how to state
   the answer in one line from the numbers in stats.json.

   A section entry:
     topic    which topic page it sits on (order in this list is the order on the page)
     src      which renderer draws it: "style", "findings" or "network"
     match    the section's original <h2> text, used to find it in the rendered output
     id       slug for links: #/<topic>/<id>
     title    short name for the section menu and search
     q        the question, shown as a kicker above the heading and on the questions index
     answer   (c) -> { tag, head, text } or null when the view has no data.
              tag is "clear" (interval clear of no effect), "none" (cannot tell from luck), "explore"
              (chosen after looking at the data) or "desc" (a description, nothing tested).
              head is the short conclusion used as the heading; text is one sentence with the numbers.
     fold     index of the first <h3> part that starts collapsed (parts before it stay open)
     subs     collapsed parts that answer their own question: { match (<h3> text), id, q, answer }
     rel      related sections as "topic/id"
*/
(function () {
  "use strict";

  const TOPICS = [
    { key: "openings", nav: "Openings", title: "Openings and turn order", sources: ["findings", "style", "network"],
      lede: "What a strong start is worth, who gets one, and whether seat order matters." },
    { key: "luck", nav: "Luck", title: "Dice and luck", sources: ["findings", "style"],
      lede: "Whether the dice are fair, who they favor, and how much of winning they explain." },
    { key: "robber", nav: "Robber", title: "The robber", sources: ["findings", "style", "network"],
      lede: "Who gets robbed, by whom, and whether it goes beyond what the board and the score explain." },
    { key: "trading", nav: "Trading", title: "Trading", sources: ["findings", "network"],
      lede: "Who trades, with whom, and on what terms." },
    { key: "winning", nav: "Winning", title: "Building and winning", sources: ["findings", "style"],
      lede: "How each player builds, where winning points come from, and how games are decided." },
  ];

  const TAGS = {
    clear: { label: "Clear signal", tip: "The 95% interval is clear of no effect." },
    none: { label: "No clear signal", tip: "The games so far cannot tell this apart from luck." },
    explore: { label: "Exploratory", tip: "Chosen after looking at the data, so an estimate and not a test." },
    desc: { label: "Descriptive", tip: "A description of what happened. Nothing is tested." },
  };

  // ---- Small helpers for the answers ---------------------------------------------------------------
  const nm = (c, pid) => (c.P[pid] ? c.P[pid].name : String(pid));
  const join = (a) => (a.length <= 1 ? a.join("") : a.slice(0, -1).join(", ") + " and " + a[a.length - 1]);
  const ins = (c) => c.S.insights || {};
  const ids = (c) => c.S.players.filter((p) => p.games > 0).map((p) => p.id);
  const has = (o) => o && Object.keys(o).length > 0;
  const x2 = (c, v) => "×" + c.num(v, 2);
  const range = (c, lo, hi, d = 2) => `95% ${c.num(lo, d)} to ${c.num(hi, d)}`;
  // Players (in leaderboard order) whose interval [lo, hi] excludes ref.
  const clearOf = (c, obj, get, ref) => ids(c).filter((p) => obj[p]).map((p) => ({ p, r: get(obj[p]) }))
    .filter(({ r }) => r && r.lo !== null && r.lo !== undefined && r.hi !== null && r.hi !== undefined && (r.lo > ref || r.hi < ref));
  const best = (list, f) => list.reduce((a, b) => (a === null || f(b) > f(a) ? b : a), null);
  const gameOf = (c, gid) => c.ROOT.views.all.games.find((g) => g.id === gid);

  const SECTIONS = [
    // ================================ Openings ================================
    { topic: "openings", src: "findings", match: "Openings", id: "dots", title: "Opening dots",
      q: "Do better starting spots win more?", rel: ["openings/best-opener", "openings/resources", "luck/snowball"],
      answer(c) {
        const o = ins(c).opening;
        if (!o) return null;
        const clear = o.or_ci[0] > 1 || o.or_ci[1] < 1;
        return { tag: clear ? "clear" : "none", head: clear ? (o.or > 1 ? "Better starting spots win more" : "Better starting spots win less") : "Starting spots show no clear effect on winning",
          text: `Each opening dot above the table multiplies the odds of winning by ${c.num(o.or, 2)} (${range(c, o.or_ci[0], o.or_ci[1])}). Two dots up is about a ${c.pct(o.p2)} win chance against three equal opponents.` };
      } },
    { topic: "openings", src: "findings", match: "Best opener's wins", id: "best-opener", title: "Best opener's wins",
      q: "Does the best opener at the table win more than their share?", rel: ["openings/dots", "openings/by-player"],
      answer(c) {
        const bo = ins(c).best_opener;
        if (!bo) return null;
        const b = bo.buckets[0], clear = bo.p_best < 0.05;
        return { tag: clear ? "clear" : "none", head: clear ? "The best opener wins more than their share" : "Best openers win a bit more, but luck could do that",
          text: `Best openers won ${c.num(b.observed, 1)} games against ${c.num(b.expected, 1)} expected (one-sided p = ${c.num(bo.p_best, 3)}).` };
      } },
    { topic: "openings", src: "findings", match: "Opening strength by player", id: "by-player", title: "Opening strength by player",
      q: "Who starts on the strongest spots?", rel: ["openings/picks", "openings/draft"],
      answer(c) {
        const op = ins(c).opening_by_player;
        if (!has(op)) return null;
        const cl = clearOf(c, op, (r) => r.adjusted, 0);
        if (!cl.length) return { tag: "none", head: "Nobody's openings clearly differ from the table", text: "Every player's interval crosses zero once draft position is allowed for." };
        const ph = cl.map(({ p, r }) => `${nm(c, p)} opens ${r.mean > 0 ? "stronger" : "weaker"} (${c.fmtSigned(r.mean, 2)} dots)`);
        return { tag: "clear", head: cl.length === 1 ? `${nm(c, cl[0].p)} opens ${cl[0].r.mean > 0 ? "stronger" : "weaker"} than the table` : "Opening strength differs by player",
          text: `${join(ph)}, after adjusting for draft position. Everyone else is within noise.` };
      } },
    { topic: "openings", src: "findings", match: "Starting resources", id: "resources", title: "Starting resources", fold: 1,
      q: "Does it matter which resources you start on?", rel: ["openings/dots", "openings/mix"],
      answer(c) {
        const w = (c.S.resources || {}).winning;
        if (!w || !w.model) return null;
        const p = w.model.lr.p, clear = p < 0.05;
        const miss = Object.entries(w.missing || {}).filter(([, m]) => m.p_dots < 0.05).map(([r, m]) =>
          `Openings with no ${r} won ${m.wins} against ${c.num(m.expected_dots, 1)} expected from their dots.`);
        return { tag: clear ? "clear" : "none", head: clear ? "Some resources are worth more at the start" : "Dots matter, the resource under them mostly does not",
          text: `A dot on any resource helps about the same (likelihood ratio p = ${c.num(p, 2)}).${miss.length ? " " + miss.join(" ") : ""}` };
      } },
    { topic: "openings", src: "style", match: "Resource mix", id: "mix", title: "Resource mix by player",
      q: "Which resources does each player build around?", rel: ["openings/resources", "winning/spending"],
      answer(c) {
        const v = (c.S.resources || {}).players, names = (c.ROOT.resources || {}).resources || [];
        if (!has(v)) return null;
        const ph = [];
        for (const p of ids(c)) {
          const o = v[p] && v[p].opening;
          if (!o) continue;
          let k = -1;
          o.diff.forEach((d, i) => { if (o.lo[i] > 0 && (k < 0 || d > o.diff[k])) k = i; });
          if (k >= 0) ph.push(`${nm(c, p)} leans ${names[k]} (${c.fmtSigned(o.diff[k] * 100, 1)} pts)`);
        }
        return { tag: "desc", head: "What each player builds around",
          text: ph.length ? `In opening dots against the table: ${join(ph.slice(0, 4))}.` : "No player's opening mix is clearly different from the table's." };
      } },
    { topic: "openings", src: "findings", match: "Draft order", id: "draft", title: "Draft order",
      q: "What is left to pick from at each draft seat?", rel: ["openings/turn-order", "openings/picks"],
      answer(c) {
        const d = (c.S.classes || {}).draft, g = d && d.grid && (d.grid["4"] || d.grid["3"]);
        if (!g) return null;
        const n = d.grid["4"] ? 4 : 3;
        const cell = (seat, pick) => g.cells.find((x) => x.seat === seat && x.pick === pick);
        const a = cell(1, 1), z = cell(n, 1);
        if (!a || !z) return null;
        return { tag: "desc", head: "What each draft seat has left to choose from",
          text: `In ${n} player games the first seat's best open spot averages ${c.num(a.b, 1)} dots; by the last seat's first pick it is ${c.num(z.b, 1)}.` };
      } },
    { topic: "openings", src: "findings", match: "Pick percentile", id: "picks", title: "Pick percentile",
      q: "How often do we take the best spot on the board?", rel: ["openings/by-player", "openings/draft"],
      answer(c) {
        const d = (c.S.classes || {}).draft;
        if (!d || !d.picks) return null;
        return { tag: "desc", head: `We take the top spot ${c.pct(d.top)} of the time`,
          text: `The spot with the most dots was taken in ${c.pct(d.top)} of ${d.picks} picks, and the average pick sits at the ${c.num(d.mean_pct * 100, 0)}th percentile of what was open.` };
      } },
    { topic: "openings", src: "findings", match: "Turn order", id: "turn-order", title: "Turn order",
      q: "Does going first matter?", rel: ["openings/draft"],
      answer(c) {
        const se = ins(c).seat_effect;
        if (!has(se)) return null;
        const out = [];
        for (const n of ["3", "4"]) for (const b of (se[n] || {}).seats || []) {
          if (b.wins < b.lo || b.wins > b.hi) out.push(`${c.ord(b.seat)} of ${n} won ${b.wins > b.hi ? "more" : "less"} than luck explains (${b.wins} against ${c.num(b.expected, 1)} expected)`);
        }
        return out.length ? { tag: "clear", head: "Turn order matters", text: join(out) + "." }
          : { tag: "none", head: "No seat has a clear edge", text: "Wins by seat all sit inside the range luck allows, in both 3 and 4 player games." };
      } },
    { topic: "openings", src: "network", match: "Setup contention", id: "contention", title: "Setup contention",
      q: "Who fights over the same hexes at setup?", rel: ["openings/mix", "robber/ledger"],
      answer(c) {
        const R = c.S.robber;
        if (!R || !R.pairs) return null;
        const b = best(Object.entries(R.pairs).filter(([, p]) => p.tier === "color" && p.contention), ([, p]) => p.contention.mean);
        if (!b) return null;
        const [x, y] = b[0].split("|");
        return { tag: "desc", head: "Who fights over the same hexes",
          text: `${nm(c, x)} and ${nm(c, y)} overlap the most at setup: ${c.num(b[1].contention.mean, 1)} shared dots per game.` };
      } },

    // ================================ Dice and luck ================================
    { topic: "luck", src: "findings", match: "Are the dice fair?", id: "fair", title: "Are the dice fair?",
      q: "Are the dice fair?", rel: ["luck/who", "luck/actual"],
      answer(c) {
        const d = ins(c).dice_calibration;
        if (!d) return null;
        const fair = d.chi2_p >= 0.05;
        const sev = d.seven_z < -2 ? "low" : d.seven_z > 2 ? "high" : "";
        return { tag: fair ? "none" : "clear", head: fair ? (sev ? `Fair overall, though sevens run ${sev}` : "The dice look fair") : "The dice look off",
          text: `${d.rolls.toLocaleString("en-US")} rolls ${fair ? "match" : "do not match"} fair dice (p = ${c.num(d.chi2_p, 2)}). Sevens came up ${d.sevens.toLocaleString("en-US")} times against ${Math.round(d.sevens_expected).toLocaleString("en-US")} expected.` };
      } },
    { topic: "luck", src: "style", match: "Dice luck", id: "who", title: "Dice luck by player",
      q: "Who do the dice favor?", rel: ["luck/actual", "luck/above-luck"],
      answer(c) {
        const L = (c.S.momentum || {}).luck;
        if (!has(L)) return null;
        const shown = ids(c).filter((p) => L[p] && L[p].shown);
        if (!shown.length) return null;
        const cl = shown.filter((p) => L[p].lo > 0 || L[p].hi < 0);
        const top = best(shown, (p) => L[p].mean);
        if (!cl.length) return { tag: "none", head: "Nobody is clearly luckier than their table",
          text: `Every player's interval includes zero. ${nm(c, top)} is highest at ${c.fmtSigned(L[top].mean, 1)} cards a game.` };
        return { tag: "clear", head: "The dice have had favorites",
          text: `${join(cl.map((p) => `${nm(c, p)} ${c.fmtSigned(L[p].mean, 1)} cards a game`))} against their tablemates, clear of zero.` };
      } },
    { topic: "luck", src: "style", match: "Dice luck: actual against expected", id: "actual", title: "Actual against expected",
      q: "Who got more cards than their board should produce?", rel: ["luck/who", "luck/fair"],
      answer(c) {
        const ps = c.S.players.filter((p) => p.games > 0 && p.replay);
        if (!ps.length) return null;
        const hi = best(ps, (p) => p.replay.dice_ratio), lo = best(ps, (p) => -p.replay.dice_ratio);
        const dev = Math.max(...ps.map((p) => Math.abs(p.replay.dice_ratio - 1)));
        return { tag: "desc", head: `Everyone's dice land within ${Math.max(1, Math.ceil(dev * 100 - 1e-9))}% of expected`,
          text: `${hi.name} ran hottest at ${c.num(hi.replay.dice_ratio, 2)}× expected and ${lo.name} coldest at ${c.num(lo.replay.dice_ratio, 2)}×.` };
      } },
    { topic: "luck", src: "findings", match: "Does early luck snowball?", id: "snowball", title: "Does early luck snowball?", fold: 1,
      q: "Does early luck snowball?", rel: ["openings/dots", "luck/who"],
      subs: [{ match: "Wins above luck", id: "above-luck", q: "Who wins more than their dice explain?",
        answer(c) {
          const la = (c.S.momentum || {}).luck_adjusted;
          if (!la || !has(la.players)) return null;
          const ps = ids(c).filter((p) => la.players[p]);
          const hi = best(ps, (p) => la.players[p].above_luck), lo = best(ps, (p) => -la.players[p].above_luck);
          return { tag: "desc", text: `${nm(c, hi)} has ${c.fmtSigned(la.players[hi].above_luck, 1)} wins beyond what the dice predict, the most; ${nm(c, lo)} is lowest at ${c.fmtSigned(la.players[lo].above_luck, 1)}.` };
        } }],
      answer(c) {
        const s = (c.ROOT.momentum || {}).snowball;
        if (!s || !(c.S.momentum || {}).luck) return null;
        return { tag: s.detected ? "clear" : "none", head: s.detected ? "Early luck snowballs" : "No detectable snowball from early luck",
          text: `Early luck is worth ${c.fmtSigned(s.D, 2)} more than later luck on the log odds of winning (95% ${c.fmtSigned(s.D_ci[0], 2)} to ${c.fmtSigned(s.D_ci[1], 2)}). A gap under ${c.num(s.detectable_80, 2)} would likely be missed.` };
      } },
    { topic: "luck", src: "findings", match: "Dev card draw luck", id: "dev-draws", title: "Dev card draw luck",
      q: "Who draws the best dev cards?", rel: ["luck/who", "winning/recipe"],
      answer(c) {
        const dl = (c.S.classes || {}).dev_luck;
        if (!dl || !dl.games) return null;
        const cl = ids(c).filter((p) => (dl.players || {})[p]).filter((p) => { const v = dl.players[p].vp; return v.lo > 0 || v.hi < 0; });
        const grp = `As a group we drew ${dl.group.vp.O} VP cards against ${c.num(dl.group.vp.E, 1)} expected from the decks.`;
        if (!cl.length) return { tag: "none", head: "Nobody's dev card draws stand out", text: grp };
        return { tag: "clear", head: "Some dev card draws stand out",
          text: `${join(cl.map((p) => `${nm(c, p)} drew ${c.fmtSigned(dl.players[p].vp.diff, 1)} VP cards against expectation`))}. ${grp}` };
      } },

    // ================================ Robber ================================
    { topic: "robber", src: "network", match: "Overpunishment", id: "leader-tax", title: "The leader tax", fold: 1,
      q: "Does the robber go after the leader?", rel: ["robber/betrayal", "winning/threat", "robber/even-split"],
      subs: [
        { match: "Robbed beyond the board", id: "over-robbed", q: "Who gets robbed more than their position explains?",
          answer(c) {
            const t = (c.S.robber || {}).targeting;
            if (!has(t)) return null;
            const cl = clearOf(c, t, (r) => r, 1);
            if (!cl.length) return { tag: "none", text: "No player is robbed clearly more or less than the board, hands and score predict." };
            return { tag: "clear", text: `Against what the board, hands and score predict: ${join(cl.map(({ p, r }) => `${nm(c, p)} ${x2(c, r.shrunk)}`))}. Above ×1 is robbed more.` };
          } },
        { match: "Early robbing and winning", id: "early-robbing", q: "Does getting robbed early cost you the game?",
          answer(c) {
            const e = (c.S.robber || {}).early_excess;
            if (!e) return null;
            return { tag: "explore", text: `Each extra early card stolen beyond the model goes with ${x2(c, e.or)} the odds of winning (${range(c, e.or_lo, e.or_hi)}). Robbing early can itself be a reaction to a strong start.` };
          } },
      ],
      answer(c) {
        const A = c.ROOT.robber;
        if (!A || !c.S.robber) return null;
        const s = A.leader.seven.stage2_vp, clear = s.or_lo > 1 || s.or_hi < 1;
        return { tag: clear ? "clear" : "none", head: clear ? "The robber goes after the leader" : "No clear leader tax",
          text: `After a 7, each visible VP closer to the lead multiplies the odds of being the one robbed by ${c.num(s.or, 2)} (${range(c, s.or_lo, s.or_hi)}). ${c.pct(A.leader.base_rate_all)} of placements touch the leader, against ${c.pct(A.leader.uniform_rate_all)} at random.` };
      } },
    { topic: "robber", src: "network", match: "Trade and rob", id: "betrayal", title: "Betrayal index", fold: 1,
      q: "Do we spare the people we just traded with?", rel: ["trading/graph", "robber/leader-tax"],
      answer(c) {
        const A = c.ROOT.robber;
        if (!A || !A.partner || !c.S.robber) return null;
        const P = A.partner;
        const head = P.hi < 1 ? "We spare recent trade partners" : P.lo > 1 ? "We turn on recent trade partners" : "No clear mercy for recent trade partners";
        return { tag: P.hi < 1 || P.lo > 1 ? "clear" : "none", head,
          text: `A recent partner's income draws the robber ${c.num(P.rho, 2)}× as much as another trailing opponent's (${range(c, P.lo, P.hi)}). 1 would be no difference.` };
      } },
    { topic: "robber", src: "findings", match: "Robbed vs an even split", id: "even-split", title: "Robbed vs an even split",
      q: "Who loses more than a fair share of stolen cards?", rel: ["robber/over-robbed", "robber/table"],
      answer(c) {
        const ss = ins(c).steal_share;
        if (!has(ss)) return null;
        const cl = clearOf(c, ss, (r) => (r.ci ? { lo: r.ci[0], hi: r.ci[1], ratio: r.ratio } : null), 1);
        if (!cl.length) return { tag: "none", head: "Stolen cards are spread about evenly", text: "Every player's share of stolen cards is within noise of an even split. This ignores the board." };
        return { tag: "clear", head: "Stolen cards are not spread evenly",
          text: `Against an even split: ${join(cl.map(({ p, r }) => `${nm(c, p)} ${x2(c, r.ratio)}`))}. This ignores the board, so a leader can be robbed more for good reason.` };
      } },
    { topic: "robber", src: "style", match: "Robber", id: "table", title: "Robber numbers per game",
      q: "Who steals the most, and who pays for it?", rel: ["robber/who-robs-whom", "robber/even-split"],
      answer(c) {
        const ps = c.S.players.filter((p) => p.games >= 10 && p.replay);
        if (!ps.length) return null;
        const a = best(ps, (p) => p.replay.avg_steals), b = best(ps, (p) => p.replay.avg_stolen_from);
        return { tag: "desc", head: "Who steals and who gets robbed",
          text: `${a.name} steals the most (${c.num(a.replay.avg_steals)} cards a game) and ${b.name} is robbed the most (${c.num(b.replay.avg_stolen_from)}).` };
      } },
    { topic: "robber", src: "style", match: "Who robs whom", id: "who-robs-whom", title: "Who robs whom",
      q: "Who robs whom?", rel: ["robber/graph", "robber/ledger"],
      answer(c) {
        const b = best(c.S.head_to_head.filter((h) => h.replay_games >= 10), (h) => h.steals / h.replay_games);
        if (!b) return null;
        return { tag: "desc", head: `${nm(c, b.player)} takes the most from ${nm(c, b.opponent)}`,
          text: `${nm(c, b.player)} takes ${c.num(b.steals / b.replay_games, 2)} cards a game from ${nm(c, b.opponent)} over ${b.replay_games} games together, the heaviest pairing with 10 or more shared games.` };
      } },
    { topic: "robber", src: "network", match: "Trades and robberies", id: "graph", title: "Robber network", layer: "robber",
      q: "Does anyone single out one opponent?", rel: ["robber/who-robs-whom", "trading/graph"],
      answer(c) {
        const D = (c.S.robber || {}).directed;
        if (!has(D)) return null;
        const cl = Object.entries(D).filter(([, d]) => d.tier === "color" && d.lo > 1).sort((a, b) => b[1].shrunk - a[1].shrunk);
        if (!cl.length) return { tag: "none", head: "Nobody singles out an opponent beyond the board",
          text: "Once the board, hands and score are allowed for, no robber pairing is clearly above ×1." };
        return { tag: "clear", head: "Some pairings go beyond the board",
          text: join(cl.slice(0, 3).map(([k, d]) => { const [a, b] = k.split(">"); return `${nm(c, a)} robs ${nm(c, b)} ${x2(c, d.shrunk)} what the model expects`; })) + "." };
      } },
    { topic: "robber", src: "network", match: "Cards cost ledger", id: "ledger", title: "Cards cost ledger",
      q: "Who costs whom the most cards?", rel: ["robber/who-robs-whom", "openings/contention"],
      answer(c) {
        const R = c.S.robber;
        if (!R || !has(R.ledger)) return null;
        const games = (k) => { const [a, b] = k.split(">"); const p = R.pairs[`${a}|${b}`] || R.pairs[`${b}|${a}`]; return p ? p.games : 0; };
        const b = best(Object.entries(R.ledger).filter(([k]) => games(k) >= 10), ([, v]) => v.total100);
        if (!b) return null;
        const [x, y] = b[0].split(">");
        return { tag: "desc", head: `${nm(c, x)} costs ${nm(c, y)} the most cards`,
          text: `${nm(c, x)} costs ${nm(c, y)} ${c.num(b[1].total100, 1)} cards per 100 rolls together, counting steals, blocked production and Monopoly: the most of any pairing with 10 or more shared games.` };
      } },

    // ================================ Trading ================================
    { topic: "trading", src: "findings", match: "Trading and the bank", id: "rates", title: "Trading and the bank",
      q: "Who trades the most, and who leans on the bank?", rel: ["trading/terms", "winning/spending"],
      answer(c) {
        const tb = ins(c).trade_bank;
        if (!has(tb)) return null;
        const cl = clearOf(c, tb, (r) => (r.trade_rr_ci ? { lo: r.trade_rr_ci[0], hi: r.trade_rr_ci[1], rr: r.trade_rr } : null), 1);
        if (!cl.length) return { tag: "none", head: "Nobody trades clearly more or less than their table", text: "Every player's trade rate is within noise of their tablemates'." };
        return { tag: "clear", head: "Some of us trade more than others",
          text: `Player trades against tablemates: ${join(cl.map(({ p, r }) => `${nm(c, p)} ${x2(c, r.rr)}`))}. Everyone else is within noise of ×1.` };
      } },
    { topic: "trading", src: "network", match: "Trades and robberies", id: "graph", title: "Trade network", layer: "trade",
      q: "Do some pairs trade together more than others?", rel: ["robber/betrayal", "robber/graph"],
      answer(c) {
        const R = c.S.robber, A = c.ROOT.robber;
        if (!R || !A) return null;
        const tm = R.trade_model || A.trade_model;
        if (!tm) return null;
        return tm.sigma_u > 0
          ? { tag: "clear", head: "Some pairs trade together more than their habits predict", text: `The model's best fit puts the spread between pairs at ${c.num(tm.sigma_u, 2)} on the log scale, above zero.` }
          : { tag: "none", head: "No pair trades together more than their habits predict", text: "Once each player's overall appetite for trading is allowed for, the best fit puts the spread between pairs at zero." };
      } },
    { topic: "trading", src: "network", match: "Trading terms", id: "terms", title: "Roller premium",
      q: "Who overpays when trading on their own turn?", rel: ["trading/rates", "winning/politics"],
      answer(c) {
        const pr = (c.S.robber || {}).premium;
        if (!has(pr)) return null;
        const ps = ids(c).filter((p) => pr[p]);
        if (!ps.length) return null;
        const cl = ps.filter((p) => pr[p].lo > 1 || pr[p].hi < 1);
        const top = best(ps, (p) => pr[p].ratio);
        if (!cl.length) return { tag: "none", head: "Nobody clearly overpays on their own turn",
          text: `${nm(c, top)} pays the most at ${x2(c, pr[top].ratio)} the usual price (${range(c, pr[top].lo, pr[top].hi)}), which is still within noise.` };
        return { tag: "clear", head: "Trade prices differ by player",
          text: `Cards given per card received, against the field: ${join(cl.map((p) => `${nm(c, p)} ${x2(c, pr[p].ratio)}`))}.` };
      } },

    // ================================ Building and winning ================================
    { topic: "winning", src: "findings", match: "Where winning points came from", id: "recipe", title: "Win recipe",
      q: "Where do winning points come from?", rel: ["winning/spending", "luck/dev-draws"],
      answer(c) {
        const wr = ins(c).win_recipe;
        if (!has(wr)) return null;
        const lab = { buildings: "buildings", development: "development", bonuses: "bonuses" };
        const ph = [];
        for (const p of ids(c).filter((x) => wr[x])) {
          const cl = Object.keys(lab).filter((k) => wr[p][k].ci[0] > 0 || wr[p][k].ci[1] < 0);
          if (cl.length) ph.push(`${nm(c, p)} (${cl.map((k) => `${c.fmtSigned(wr[p][k].tilt * 100, 0)} pts ${lab[k]}`).join(", ")})`);
        }
        return ph.length ? { tag: "clear", head: "We do not all win the same way", text: `Share of winning points against comparable wins: ${join(ph)}.` }
          : { tag: "none", head: "Winning recipes look alike", text: "No player's mix of buildings, development and bonuses is clearly different from other players' wins." };
      } },
    { topic: "winning", src: "style", match: "Spending and trading mix", id: "spending", title: "Spending and trading mix",
      q: "How does each player spend their cards?", rel: ["winning/recipe", "trading/rates", "openings/mix"],
      answer(c) {
        const B = (c.ROOT.classes || {}).badges;
        if (!B || !(c.S.classes || {}).profile) return null;
        const an = (s) => (/^[aeiou]/i.test(s) ? "an" : "a");
        const ph = ids(c).filter((p) => B[p] && B[p].badges.length).map((p) => `${nm(c, p)} is ${B[p].badges.map((b) => `${an(b.name)} ${b.name}`).join(" and ")}`);
        return { tag: "desc", head: "Who spends on what",
          text: ph.length ? `Style badges over all games: ${join(ph)}.` : "No style badge is clear of noise yet." };
      } },
    { topic: "winning", src: "style", match: "Building and trading", id: "building", title: "Building and trading per game",
      q: "Who builds what in a typical game?", rel: ["winning/spending", "winning/timing"],
      answer(c) {
        const ps = c.S.players.filter((p) => p.games >= 10 && p.replay);
        if (!ps.length) return null;
        const a = best(ps, (p) => p.replay.avg_built_city), b = best(ps, (p) => p.replay.avg_built_settlement), t = best(ps, (p) => p.replay.avg_trades);
        return { tag: "desc", head: "What a typical game looks like for each player",
          text: `${a.name} builds the most cities (${c.num(a.replay.avg_built_city)} a game), ${b.name} the most settlements (${c.num(b.replay.avg_built_settlement)}), and ${t.name} makes the most player trades (${c.num(t.replay.avg_trades)}).` };
      } },
    { topic: "winning", src: "style", match: "Timing columns", id: "timing", title: "Timing by player",
      q: "Who gets going fastest?", rel: ["winning/how-long", "winning/building"],
      answer(c) {
        const C = c.S.classes || {}, km = (C.km || {}).players;
        if (!has(km)) return null;
        const ps = ids(c).filter((p) => km[p] && km[p].city && km[p].dev);
        if (!ps.length) return null;
        const a = best(ps, (p) => -km[p].city.median), b = best(ps, (p) => -km[p].dev.median);
        const hd = C.hoarder && C.hoarder.share !== undefined ? ` ${c.pct(C.hoarder.share)} of 7-discards could have been avoided by building first.` : "";
        return { tag: "desc", head: "Who gets going fastest",
          text: `${nm(c, a)} reaches a first city soonest (their turn ${km[a].city.median}) and ${nm(c, b)} a first dev card (turn ${km[b].dev.median}).${hd}` };
      } },
    { topic: "winning", src: "style", match: "How long until", id: "how-long", title: "How long until",
      q: "How long until the first dev card and the first city?", rel: ["winning/timing"],
      answer(c) {
        const km = (c.S.classes || {}).km;
        if (!km || !km.dev || !km.city) return null;
        return { tag: "desc", head: `First dev card by turn ${km.dev.median}, first city by turn ${km.city.median}`,
          text: `Half of all players have bought a dev card by their own turn ${km.dev.median} and built a city by turn ${km.city.median}.` };
      } },
    { topic: "winning", src: "findings", match: "First to get close", id: "first-close", title: "First to get close",
      q: "If you get close first, do you win?", rel: ["winning/comebacks", "winning/threat"],
      answer(c) {
        const ft = ((c.S.classes || {}).first_to || {})["0.75"];
        if (!ft || !ft.group) return null;
        const g = ft.group, clear = g.ci[0] > g.base;
        return { tag: clear ? "clear" : "none", head: clear ? "Getting close first usually wins" : "Getting close first is no guarantee",
          text: `The first player three quarters of the way to the target won ${c.pct(g.p)} of games (95% ${c.pct(g.ci[0])} to ${c.pct(g.ci[1])}), against a fair share of ${c.pct(g.base)}.` };
      } },
    { topic: "winning", src: "findings", match: "Comebacks", id: "comebacks", title: "Comebacks",
      q: "How often does someone win from behind?", rel: ["winning/first-close", "winning/closest"],
      answer(c) {
        const cb = (c.S.classes || {}).comebacks;
        if (!cb || !cb.with_t_star) return null;
        return { tag: "desc", head: `${cb.counts.gap3 || 0} of ${cb.with_t_star} games were won from 3 or more VP behind`,
          text: `In ${cb.counts.gap3 || 0} of ${cb.with_t_star} games the winner was 3 or more board VP behind when someone first got within 3 VP of the target.` };
      } },
    { topic: "winning", src: "findings", match: "Threat index", id: "threat", title: "Threat index", fold: 1,
      q: "Can the table see the winner coming?", rel: ["robber/leader-tax", "winning/first-close"],
      subs: [{ match: "Table politics", id: "politics", q: "Who feeds the leader?",
        answer(c) {
          const v = (c.S.threat || {}).players;
          if (!has(v)) return null;
          const cl = ids(c).filter((p) => v[p] && v[p].tyrant_ante && v[p].tyrant_ante.clear);
          if (!cl.length) return { tag: "none", text: "Nobody trades with the top threat clearly more or less than chance." };
          return { tag: "clear", text: `Trades with the top threat, against chance: ${join(cl.map((p) => `${nm(c, p)} ${x2(c, v[p].tyrant_ante.ratio)}`))}. Below ×1 means steering clear of the leader.` };
        } }],
      answer(c) {
        const h = (c.S.threat || {}).hidden;
        if (!h || !(c.ROOT.threat || {}).model) return null;
        return { tag: "desc", head: "The table can usually see the winner coming",
          text: `The top threat going into the final turn won ${h.top_won} of ${h.games} games; chance would give ${c.num(h.chance, 0)}. The other ${h.games - h.top_won} were hidden threats.` };
      } },
    { topic: "winning", src: "findings", match: "Closest games", id: "closest", title: "Closest games",
      q: "Which games were the closest?", rel: ["winning/comebacks"],
      answer(c) {
        const cl = c.ROOT.closeness;
        if (!cl) return null;
        const inView = new Set(c.S.games.map((g) => g.id));
        const rows = Object.entries(cl.games).filter(([gid]) => inView.has(gid));
        const b = best(rows, ([, r]) => -r.rank);
        if (!b || !gameOf(c, b[0])) return null;
        const tier = rows.filter(([, r]) => r.closest_tier).length;
        return { tag: "desc", head: "The closest and the most one-sided games",
          text: `${c.gameLabel(gameOf(c, b[0]))} is the closest here, with a closeness index of ${c.num(b[1].index, 0)} out of 100. ${tier} ${tier === 1 ? "game makes" : "games make"} the closest tier.` };
      } },
  ];

  // Old page links, kept working.
  const REDIRECTS = { findings: "questions", style: "questions", network: "robber" };

  const safe = (f, c) => { try { return f ? f(c) : null; } catch (e) { if (window.console) console.warn("answer failed", e); return null; } };
  const topic = (key) => TOPICS.find((t) => t.key === key);
  const sectionsOf = (key) => SECTIONS.filter((s) => s.topic === key);
  // Every question on the site, sections and collapsed parts alike, with its answer for the current view.
  function questions(c) {
    const out = [];
    for (const s of SECTIONS) {
      out.push({ topic: s.topic, id: s.id, title: s.title, q: s.q, a: safe(s.answer, c) });
      for (const u of s.subs || []) out.push({ topic: s.topic, id: u.id, title: u.match, q: u.q, a: safe(u.answer, c), sub: true });
    }
    return out;
  }
  // "topic/id" -> the title to show in a link.
  function titleOf(ref) {
    const [t, id] = ref.split("/");
    for (const s of SECTIONS) {
      if (s.topic !== t) continue;
      if (s.id === id) return s.title;
      const u = (s.subs || []).find((x) => x.id === id);
      if (u) return u.match;
    }
    return null;
  }

  window.Topics = { TOPICS, SECTIONS, TAGS, REDIRECTS, topic, sectionsOf, questions, titleOf, answer: safe };
})();
