/* Small hand-rolled SVG charts. No dependencies.
   Every chart re-renders on resize so text stays at real pixel sizes, has a
   hover and keyboard tooltip, and is paired with a table view by the caller. */
(function () {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";

  function svgEl(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    let style = "";
    for (const k in attrs) {
      const v = attrs[k];
      if (v === undefined || v === null) continue;
      // var() is not reliable inside SVG presentation attributes in every browser, so route it through style.
      if ((k === "fill" || k === "stroke") && String(v).includes("var(")) style += `${k}:${v};`;
      else e.setAttribute(k, v);
    }
    if (style) e.setAttribute("style", style + (e.getAttribute("style") || ""));
    if (parent) parent.appendChild(e);
    return e;
  }

  // ---- Tooltip ------------------------------------------------------------
  const Tip = {
    node: null,
    show(html, clientX, clientY) {
      if (!this.node) this.node = document.getElementById("tip");
      const t = this.node;
      t.innerHTML = html;
      t.hidden = false;
      const pad = 14, w = t.offsetWidth, h = t.offsetHeight;
      let x = clientX + pad, y = clientY - h - pad;
      if (x + w > window.innerWidth - 8) x = clientX - w - pad;
      if (x < 8) x = 8;
      if (y < 8) y = clientY + pad;
      t.style.left = x + "px";
      t.style.top = y + "px";
    },
    hide() { if (this.node) this.node.hidden = true; },
  };

  function niceTicks(min, max, count) {
    if (min === max) { min -= 1; max += 1; }
    const span = max - min;
    const step0 = span / Math.max(1, count);
    const mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const norm = step0 / mag;
    const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
    const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
    const ticks = [];
    for (let v = lo; v <= hi + step / 2; v += step) ticks.push(+v.toFixed(10));
    return ticks;
  }

  function responsive(container, draw) {
    // Redrawing into the same container (for example after a Level | Rate switch) retires the old observer.
    if (container.__chartStop) container.__chartStop();
    let lastW = 0, ro = null, dead = false;
    container.__chartStop = () => { dead = true; if (ro) ro.disconnect(); else window.removeEventListener("resize", run); };
    const run = () => {
      if (dead) return;
      if (!container.isConnected) { if (ro) ro.disconnect(); return; }
      const cs = getComputedStyle(container);
      const w = Math.floor(container.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight));
      if (w < 160 || w === lastW) return; // detached or not laid out yet
      lastW = w;
      container.innerHTML = "";
      draw(w);
    };
    run();
    if ("ResizeObserver" in window) { ro = new ResizeObserver(run); ro.observe(container); }
    else window.addEventListener("resize", run);
  }

  // Rounded-top bar path: 4px radius on the data end, square on the baseline.
  function barPath(x, y, w, h, r) {
    r = Math.min(r, w / 2, h);
    if (h <= 0) return "";
    return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
  }

  // ---- Line chart -----------------------------------------------------------
  // opts: { series: [{id, name, color, points: [{x, y, tip}]}], xLabel(x), yTitle,
  //         height, highlight (series id), directLabels (bool), xTickLabel(x), yRef (dashed reference line) }
  function lineChart(container, opts) {
    responsive(container, (W) => {
      const all = opts.series.flatMap((s) => s.points);
      if (!all.length) return;
      const narrow = W < 520;
      const labels = opts.directLabels !== false && !narrow && opts.series.length <= 6;
      const H = opts.height || 280;
      const m = { t: 12, r: labels ? 110 : 14, b: 34, l: 40 };
      const iw = W - m.l - m.r, ih = H - m.t - m.b;
      const xs = [...new Set(all.map((p) => p.x))].sort((a, b) => a - b);
      const xmin = xs[0], xmax = xs[xs.length - 1];
      let ymin = Math.min(...all.map((p) => (p.lo !== undefined ? p.lo : p.y)));
      let ymax = Math.max(...all.map((p) => (p.hi !== undefined ? p.hi : p.y)));
      if (fin(opts.yRef)) { ymin = Math.min(ymin, opts.yRef); ymax = Math.max(ymax, opts.yRef); }
      const yt = niceTicks(ymin, ymax, 4);
      ymin = yt[0]; ymax = yt[yt.length - 1];
      const X = (x) => m.l + (xmax === xmin ? iw / 2 : ((x - xmin) / (xmax - xmin)) * iw);
      const Y = (y) => m.t + ih - ((y - ymin) / (ymax - ymin)) * ih;

      const svg = svgEl("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img",
        "aria-label": opts.ariaLabel || "Line chart" }, container);
      for (const t of yt) {
        svgEl("line", { x1: m.l, x2: m.l + iw, y1: Y(t), y2: Y(t), stroke: "var(--hair)", "stroke-width": 1 }, svg);
        svgEl("text", { x: m.l - 8, y: Y(t) + 4, "text-anchor": "end" }, svg).textContent = t;
      }
      svgEl("line", { x1: m.l, x2: m.l + iw, y1: m.t + ih, y2: m.t + ih, stroke: "var(--axis)", "stroke-width": 1 }, svg);
      if (fin(opts.yRef)) svgEl("line", { x1: m.l, x2: m.l + iw, y1: Y(opts.yRef), y2: Y(opts.yRef), stroke: "var(--ink-2)", "stroke-width": 1, "stroke-dasharray": "4 3" }, svg);
      const xticks = xs.length <= 12 ? xs : niceTicks(xmin, xmax, narrow ? 4 : 8).filter((v) => v >= xmin && v <= xmax);
      for (const t of xticks) {
        svgEl("text", { x: X(t), y: m.t + ih + 18, "text-anchor": "middle" }, svg).textContent =
          opts.xTickLabel ? opts.xTickLabel(t) : t;
      }
      const ordered = [...opts.series].sort((a, b) => (a.id === opts.highlight) - (b.id === opts.highlight));
      for (const s of ordered) {
        const dim = opts.highlight && s.id !== opts.highlight;
        const color = dim ? "var(--axis)" : s.color;
        const pts = s.points;
        if (s.band && pts.length > 1) {
          const up = pts.map((p) => `${X(p.x)},${Y(p.hi)}`).join(" L");
          const dn = [...pts].reverse().map((p) => `${X(p.x)},${Y(p.lo)}`).join(" L");
          svgEl("path", { d: `M${up} L${dn}Z`, fill: s.color, "fill-opacity": 0.14 }, svg);
        }
        if (pts.length > 1) {
          svgEl("path", { d: "M" + pts.map((p) => `${X(p.x)},${Y(p.y)}`).join(" L"), fill: "none",
            stroke: color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
        }
        if (pts.length <= 40 || pts.length === 1) {
          for (const p of pts) {
            svgEl("circle", { cx: X(p.x), cy: Y(p.y), r: 4, fill: color, stroke: "var(--surface)", "stroke-width": 2 }, svg);
          }
        }
      }

      // Direct labels at each line's end, nudged apart so they never collide.
      if (labels) {
        // Only lines that reach the latest game get a label at the edge; the legend names the rest.
        const ends = opts.series.filter((s) => s.points.length && s.points[s.points.length - 1].x === xmax)
          .map((s) => ({ s, y: Y(s.points[s.points.length - 1].y) }))
          .sort((a, b) => a.y - b.y);
        const gap = 15;
        for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < gap) ends[i].y = ends[i - 1].y + gap;
        const over = ends.length ? ends[ends.length - 1].y - (m.t + ih) : 0;
        if (over > 0) ends.forEach((e) => (e.y -= over));
        for (const e of ends) {
          const dim = opts.highlight && e.s.id !== opts.highlight;
          const t = svgEl("text", { x: m.l + iw + 10, y: e.y + 4, class: "lbl" }, svg);
          t.textContent = e.s.name;
          if (dim) t.setAttribute("style", "fill: var(--muted); font-weight: 400");
        }
      }

      // Crosshair + tooltip, by pointer and by keyboard.
      const cross = svgEl("line", { y1: m.t, y2: m.t + ih, stroke: "var(--ink-2)", "stroke-width": 1, visibility: "hidden" }, svg);
      const hit = svgEl("rect", { x: m.l - 6, y: m.t, width: iw + 12, height: ih, fill: "transparent", tabindex: 0,
        "aria-label": `Chart data: use left and right arrow keys to step through ${opts.stepLabel || "games"}` }, svg);
      let cur = xs.length - 1;
      const showAt = (i, cx, cy) => {
        cur = Math.max(0, Math.min(xs.length - 1, i));
        const x = xs[cur];
        cross.setAttribute("x1", X(x)); cross.setAttribute("x2", X(x));
        cross.setAttribute("visibility", "visible");
        const rows = opts.series.map((s) => ({ s, p: s.points.find((p) => p.x === x) }))
          .filter((r) => r.p).sort((a, b) => b.p.y - a.p.y);
        const head = opts.xLabel ? opts.xLabel(x, rows[0] && rows[0].p) : `x = ${x}`;
        const body = rows.map((r) => `<div class="row"><span class="hex" style="--c:${r.s.color}"></span>${esc(r.s.name)} <b>${r.p.tip || r.p.y}</b></div>`).join("");
        if (cx === undefined) {
          const box = svg.getBoundingClientRect();
          cx = box.left + X(x); cy = box.top + m.t + 20;
        }
        Tip.show(`<div>${head}</div>${body}`, cx, cy);
      };
      const nearest = (clientX) => {
        const box = svg.getBoundingClientRect();
        const px = clientX - box.left;
        let best = 0, bd = Infinity;
        xs.forEach((x, i) => { const d = Math.abs(X(x) - px); if (d < bd) { bd = d; best = i; } });
        return best;
      };
      const hide = () => { cross.setAttribute("visibility", "hidden"); Tip.hide(); };
      hit.addEventListener("pointermove", (e) => showAt(nearest(e.clientX), e.clientX, e.clientY));
      hit.addEventListener("pointerleave", hide);
      hit.addEventListener("focus", () => showAt(cur));
      hit.addEventListener("blur", hide);
      hit.addEventListener("keydown", (e) => {
        if (e.key === "ArrowRight") { showAt(cur + 1); e.preventDefault(); }
        if (e.key === "ArrowLeft") { showAt(cur - 1); e.preventDefault(); }
        if (e.key === "Escape") hide();
      });
    });
  }

  // ---- Vertical bar chart ---------------------------------------------------
  // opts: { bars: [{label, value, expected?, tip}], color, height, ariaLabel }
  function barChart(container, opts) {
    responsive(container, (W) => {
      const H = opts.height || 220;
      const m = { t: 18, r: 8, b: 26, l: 34 };
      const iw = W - m.l - m.r, ih = H - m.t - m.b;
      const maxV = Math.max(1, ...opts.bars.map((b) => Math.max(b.value, b.expected || 0)));
      let yt = niceTicks(0, maxV, 4);
      if (opts.bars.every((b) => Number.isInteger(b.value)) && yt.some((t) => !Number.isInteger(t))) {
        yt = Array.from({ length: Math.ceil(maxV) + 1 }, (_, i) => i); // counts never get fractional ticks
      }
      const ymax = yt[yt.length - 1];
      const Y = (v) => m.t + ih - (v / ymax) * ih;
      const n = opts.bars.length;
      const slot = iw / n, bw = Math.max(4, Math.min(36, slot * 0.62));
      const svg = svgEl("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img",
        "aria-label": opts.ariaLabel || "Bar chart" }, container);
      for (const t of yt) {
        svgEl("line", { x1: m.l, x2: m.l + iw, y1: Y(t), y2: Y(t), stroke: "var(--hair)", "stroke-width": 1 }, svg);
        svgEl("text", { x: m.l - 8, y: Y(t) + 4, "text-anchor": "end" }, svg).textContent = t;
      }
      opts.bars.forEach((b, i) => {
        const cx = m.l + slot * i + slot / 2;
        const x = cx - bw / 2;
        const g = svgEl("g", { tabindex: 0, role: "img", "aria-label": `${b.label}: ${b.tip || b.value}` }, svg);
        svgEl("rect", { x: m.l + slot * i, y: m.t, width: slot, height: ih, fill: "transparent" }, g);
        if (b.value > 0) svgEl("path", { d: barPath(x, Y(b.value), bw, Y(0) - Y(b.value), 4), fill: b.color || opts.color || "var(--data)" }, g);
        if (b.expected !== undefined) {
          svgEl("line", { x1: x - 2, x2: x + bw + 2, y1: Y(b.expected), y2: Y(b.expected), stroke: "var(--ink)", "stroke-width": 2, "stroke-linecap": "round" }, g);
        }
        if (opts.valueLabels) {
          svgEl("text", { x: cx, y: Y(b.value) - 5, "text-anchor": "middle", class: "lbl" }, g).textContent = b.value;
        }
        svgEl("text", { x: cx, y: m.t + ih + 17, "text-anchor": "middle" }, svg).textContent = b.label;
        const show = (e) => {
          let cx2, cy2;
          if (e && e.clientX !== undefined) { cx2 = e.clientX; cy2 = e.clientY; }
          else { const r = g.getBoundingClientRect(); cx2 = r.left + r.width / 2; cy2 = r.top; }
          Tip.show(b.tipHtml || `<b>${esc(b.label)}</b>: ${b.tip || b.value}`, cx2, cy2);
        };
        g.addEventListener("pointermove", show);
        g.addEventListener("pointerleave", () => Tip.hide());
        g.addEventListener("focus", () => show());
        g.addEventListener("blur", () => Tip.hide());
      });
      svgEl("line", { x1: m.l, x2: m.l + iw, y1: Y(0), y2: Y(0), stroke: "var(--axis)", "stroke-width": 1 }, svg);
    });
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // =========================================================================
  // Stats primitives (proposal section 2, row H). Same rules as above: SVG
  // drawn at real pixel width, a hover and keyboard tooltip on every mark,
  // text in text tokens, color only on marks. Styles live in charts.css.
  // =========================================================================

  const MINUS = "−";
  const fin = (v) => v !== null && v !== undefined && Number.isFinite(+v);
  const signed = (x, d = 1) => (x > 0 ? "+" : x < 0 ? MINUS : "") + Math.abs(x).toFixed(d);
  const fmt2 = (x) => (fin(x) ? (x < 0 ? MINUS : "") + Math.abs(x).toFixed(2) : "n/a");
  const tickText = (t) => (t < 0 ? MINUS : "") + +Math.abs(t).toFixed(6);
  // Plain text from an HTML label, for aria-labels. Parsed in an inert document so nothing loads or runs.
  let inert = null;
  function plain(html) {
    if (!inert) inert = document.implementation.createHTMLDocument("");
    const d = inert.createElement("div");
    d.innerHTML = String(html === undefined || html === null ? "" : html);
    return d.textContent.replace(/\s+/g, " ").trim();
  }

  // Hover, focus and touch tooltip on one focusable element (SVG group or HTML).
  function hoverTip(el, html, onOn, onOff) {
    el.setAttribute("data-tipped", "");
    const show = (e) => {
      let x, y;
      if (e && e.clientX !== undefined) { x = e.clientX; y = e.clientY; }
      else { const r = el.getBoundingClientRect(); x = r.left + r.width / 2; y = r.top; }
      Tip.show(typeof html === "function" ? html() : html, x, y);
      if (onOn) onOn();
    };
    const hide = () => { Tip.hide(); if (onOff) onOff(); };
    el.addEventListener("pointermove", show);
    el.addEventListener("pointerdown", show);
    el.addEventListener("pointerleave", (e) => { if (e.pointerType !== "touch") hide(); else if (onOff) onOff(); });
    el.addEventListener("focus", () => show());
    el.addEventListener("blur", hide);
  }

  // Greedy tick thinning: keep ticks in priority order while they sit at least gap px apart.
  function spaced(ticks, X, gap, prio) {
    const order = [...ticks].sort((a, b) => (prio ? prio(a) - prio(b) : 0));
    const kept = [];
    for (const t of order) if (kept.every((k) => Math.abs(X(k) - X(t)) >= gap)) kept.push(t);
    return kept.sort((a, b) => a - b);
  }

  function logTicks(min, max) {
    const out = [];
    for (let e = Math.floor(Math.log10(min)) - 1; e <= Math.ceil(Math.log10(max)) + 1; e++) {
      for (const m of [1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 8]) {
        const v = +(m * Math.pow(10, e)).toPrecision(6);
        if (v >= min && v <= max) out.push(v);
      }
    }
    return out;
  }
  const logPrio = (v) => {
    if (v === 1) return 0;
    const m = +(v / Math.pow(10, Math.floor(Math.log10(v)))).toPrecision(4);
    return m === 1 || m === 2 || m === 5 ? 1 : m === 2.5 || m === 1.5 ? 2 : 3;
  };

  // Inverse standard normal CDF (Acklam), for interval levels.
  function probit(p) {
    const a = [-39.6968302866538, 220.946098424521, -275.928510446969, 138.357751867269, -30.6647980661472, 2.50662827745924];
    const b = [-54.4760987982241, 161.585836858041, -155.698979859887, 66.8013118877197, -13.2806815528857];
    const c = [-0.00778489400243029, -0.322396458041136, -2.40075827716184, -2.54973253934373, 4.37466414146497, 2.93816398269878];
    const d = [0.00778469570904146, 0.32246712907004, 2.445134137143, 3.75440866190742];
    const lo = 0.02425;
    if (p < lo) { const q = Math.sqrt(-2 * Math.log(p)); return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
    if (p > 1 - lo) return -probit(1 - p);
    const q = p - 0.5, r = q * q;
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
  }

  function legendHtml(items) {
    return `<ul class="legend">${items.map((i) => `<li>${i.sw}${esc(i.label)}</li>`).join("")}</ul>`;
  }

  // ---- 1. Forest plot (dot and whisker) -------------------------------------
  // opts: { rows: [{label (html), est, lo, hi, hollow?, small?, color?, tip? (html), note? (html), aria?}],
  //         ref, log, xTitle, leftLabel, rightLabel, format(x), tickFormat(x), domain: [lo, hi],
  //         names: {est, hollow, small, interval}, legend (default: shown when hollow or small exist),
  //         rowHeight, ariaLabel }
  function forestPlot(container, opts) {
    const rows = opts.rows || [];
    const log = !!opts.log;
    const ok = (v) => fin(v) && (!log || v > 0);
    const tf = log ? Math.log : (v) => +v;
    const fmt = opts.format || (log ? (x) => (+x).toFixed(2) : fmt2);
    const names = Object.assign({ est: "Estimate", hollow: "Raw", small: "Other", interval: "95% interval" }, opts.names || {});
    const hasHollow = rows.some((r) => ok(r.hollow)), hasSmall = rows.some((r) => ok(r.small));
    const showLegend = opts.legend !== undefined ? opts.legend : hasHollow || hasSmall;
    responsive(container, (W) => {
      if (!rows.length) return;
      const narrow = W < 520;
      const rowH = opts.rowHeight || 32;
      if (showLegend) {
        const items = [{ sw: `<span class="sw dot" style="--c:var(--ink-2)"></span>`, label: names.est }];
        if (hasHollow) items.push({ sw: `<span class="sw ring" style="--c:var(--ink-2)"></span>`, label: names.hollow });
        if (hasSmall) items.push({ sw: `<span class="sw vtick"></span>`, label: names.small });
        items.push({ sw: `<span class="sw" style="--c:var(--ink-2)"></span>`, label: names.interval });
        container.insertAdjacentHTML("beforeend", legendHtml(items));
      }
      const wrap = document.createElement("div");
      wrap.className = "fp";
      const labs = document.createElement("div");
      labs.className = "fp-labels";
      labs.style.maxWidth = narrow ? "42%" : "34%";
      const m = { t: 4, r: 14, b: 26, l: 12 };
      labs.style.paddingTop = m.t + "px";
      const labEls = rows.map((r) => {
        const d = document.createElement("div");
        d.className = "fp-lab";
        d.style.height = rowH + "px";
        d.innerHTML = `<span class="fp-lab-in">${r.label}</span>`;
        labs.appendChild(d);
        return d;
      });
      const plot = document.createElement("div");
      plot.className = "fp-plot";
      wrap.append(labs, plot);
      container.appendChild(wrap);
      const pw = Math.max(120, Math.floor(plot.getBoundingClientRect().width));
      const iw = pw - m.l - m.r, ih = rows.length * rowH, H = m.t + ih + m.b;

      const vals = [];
      for (const r of rows) for (const v of [r.est, r.lo, r.hi, r.hollow, r.small]) if (ok(v)) vals.push(tf(v));
      if (ok(opts.ref)) vals.push(tf(opts.ref));
      let lo = Math.min(...vals), hi = Math.max(...vals);
      if (opts.domain) { lo = tf(opts.domain[0]); hi = tf(opts.domain[1]); }
      let ticks;
      if (log) {
        const pad = (hi - lo) * 0.06 || 0.1;
        lo -= pad; hi += pad;
        ticks = logTicks(Math.exp(lo), Math.exp(hi));
      } else {
        ticks = niceTicks(lo, hi, Math.max(2, Math.floor(iw / (narrow ? 60 : 80))));
        if (!opts.domain) { lo = ticks[0]; hi = ticks[ticks.length - 1]; }
        if (lo === hi) { lo -= 1; hi += 1; }
      }
      const Xt = (t) => m.l + ((t - lo) / (hi - lo)) * iw;
      const X = (v) => Xt(Math.min(hi, Math.max(lo, tf(v))));
      ticks = spaced(ticks.filter((t) => tf(t) >= lo - 1e-9 && tf(t) <= hi + 1e-9), X, narrow ? 40 : 52, log ? logPrio : null);
      const tickFmt = opts.tickFormat || (log ? (t) => String(+t.toPrecision(3)) : tickText);

      const svg = svgEl("svg", { width: pw, height: H, viewBox: `0 0 ${pw} ${H}`, role: "img",
        "aria-label": opts.ariaLabel || "Dot and whisker chart" }, plot);
      for (const t of ticks) {
        svgEl("line", { x1: X(t), x2: X(t), y1: m.t, y2: m.t + ih, stroke: "var(--hair)", "stroke-width": 1 }, svg);
        svgEl("text", { x: X(t), y: m.t + ih + 17, "text-anchor": "middle" }, svg).textContent = tickFmt(t);
      }
      if (ok(opts.ref)) svgEl("line", { x1: X(opts.ref), x2: X(opts.ref), y1: m.t, y2: m.t + ih, stroke: "var(--muted)", "stroke-width": 1 }, svg);
      svgEl("line", { x1: m.l, x2: m.l + iw, y1: m.t + ih, y2: m.t + ih, stroke: "var(--axis)", "stroke-width": 1 }, svg);

      rows.forEach((r, i) => {
        const cy = m.t + i * rowH + rowH / 2;
        const color = r.color || "var(--data)";
        const ival = ok(r.lo) && ok(r.hi) ? ` (${fmt(r.lo)} to ${fmt(r.hi)})` : "";
        const aria = r.aria || `${plain(r.label)}: ${names.est} ${plain(fmt(r.est))}${ival ? `, ${names.interval} ${plain(fmt(r.lo))} to ${plain(fmt(r.hi))}` : ""}` +
          (ok(r.hollow) ? `, ${names.hollow} ${plain(fmt(r.hollow))}` : "") + (ok(r.small) ? `, ${names.small} ${plain(fmt(r.small))}` : "");
        const g = svgEl("g", { tabindex: 0, role: "img", "aria-label": aria }, svg);
        const bg = svgEl("rect", { x: 0, y: cy - rowH / 2, width: pw, height: rowH, fill: "transparent", rx: 3 }, g);
        if (ok(r.lo) && ok(r.hi)) {
          svgEl("line", { x1: X(r.lo), x2: X(r.hi), y1: cy, y2: cy, stroke: color, "stroke-width": 2, "stroke-linecap": "round" }, g);
        }
        if (ok(r.hollow)) svgEl("circle", { cx: X(r.hollow), cy, r: 4, fill: "var(--surface)", stroke: color, "stroke-width": 2 }, g);
        if (ok(r.small)) svgEl("line", { x1: X(r.small), x2: X(r.small), y1: cy - 6, y2: cy + 6, stroke: "var(--ink)", "stroke-width": 2, "stroke-linecap": "round" }, g);
        if (ok(r.est)) svgEl("circle", { cx: X(r.est), cy, r: 5, fill: color, stroke: "var(--surface)", "stroke-width": 2 }, g);
        const tip = r.tip || (`<div><b>${r.label}</b></div><div>${esc(names.est)} <b>${fmt(r.est)}</b>${ival}</div>` +
          (ok(r.hollow) ? `<div>${esc(names.hollow)} <b>${fmt(r.hollow)}</b></div>` : "") +
          (ok(r.small) ? `<div>${esc(names.small)} <b>${fmt(r.small)}</b></div>` : "") + (r.note ? `<div>${r.note}</div>` : ""));
        hoverTip(g, tip,
          () => { bg.setAttribute("style", "fill:var(--wash)"); labEls[i].classList.add("on"); },
          () => { bg.setAttribute("style", "fill:transparent"); labEls[i].classList.remove("on"); });
      });

      if (opts.leftLabel || opts.rightLabel) {
        plot.insertAdjacentHTML("beforeend", `<div class="fp-ends" style="padding:0 ${m.r}px 0 ${m.l}px"><span>${opts.leftLabel || ""}</span><span>${opts.rightLabel || ""}</span></div>`);
      }
      if (opts.xTitle) plot.insertAdjacentHTML("beforeend", `<div class="fp-title" style="padding:0 ${m.r}px 0 ${m.l}px">${opts.xTitle}</div>`);
    });
  }

  // ---- 2. Coefficient plot ----------------------------------------------------
  // opts: forestPlot opts, but rows are [{label, b, lo?, hi?, se?, tip?, note?}]. Missing lo/hi come
  // from b +/- z*se (z = opts.z or 1.96). exp: true plots exp(b) (odds ratios) on a log axis around 1.
  function coefPlot(container, opts) {
    const z = opts.z || 1.96, ex = !!opts.exp;
    const t = ex ? Math.exp : (v) => v;
    const rows = opts.rows.map((r) => {
      const lo = fin(r.lo) ? r.lo : fin(r.se) ? r.b - z * r.se : undefined;
      const hi = fin(r.hi) ? r.hi : fin(r.se) ? r.b + z * r.se : undefined;
      return Object.assign({}, r, { est: t(r.b), lo: lo === undefined ? undefined : t(lo), hi: hi === undefined ? undefined : t(hi),
        note: r.note || (fin(r.se) ? `SE ${(+r.se).toFixed(3)}` : undefined) });
    });
    return forestPlot(container, Object.assign({
      ref: ex ? 1 : 0, log: ex,
      format: ex ? (v) => (+v).toFixed(2) : (v) => signed(v, 2),
      names: { est: ex ? "Odds ratio" : "Coefficient", interval: "95% interval" },
      legend: false,
    }, opts, { rows }));
  }

  // ---- 3. Stat tile -------------------------------------------------------------
  // statTile({value, label, sub, info, marker, cls}) -> HTML string. statTile(el, {...}) also appends it.
  // value, label, sub and marker are trusted HTML. info: html string, or {id, title, html}.
  let infoSeq = 0;
  // Keep the info button on the same line as the label's last word.
  function withInfo(label, info) {
    if (!info) return label;
    const m = /^([\s\S]*?)([^\s<>]+)$/.exec(String(label));
    return m ? `${m[1]}<span class="nowrap">${m[2]}${info}</span>` : label + info;
  }
  function statTile(a, b) {
    const el = a && a.nodeType === 1 ? a : null;
    const o = el ? b : a;
    let info = "";
    if (o.info) {
      const i = typeof o.info === "string" ? { html: o.info } : o.info;
      info = infoButton(i.id || `info-${++infoSeq}`, i.title || plain(o.label), i.html);
    }
    const html = `<div class="tile${o.cls ? " " + o.cls : ""}"><div class="v">${o.value}${o.marker ? ` <span class="tile-mk">${o.marker}</span>` : ""}</div>` +
      `<div class="k">${withInfo(o.label, info)}</div>${o.sub ? `<div class="s">${o.sub}</div>` : ""}</div>`;
    if (el) el.insertAdjacentHTML("beforeend", html);
    return html;
  }

  // ---- 4. Bars with a null band -------------------------------------------------
  // opts: { bars: [{label, value, expected?, lo?, hi?, tip?, note?, color?}], height, color, format(v),
  //         names: {value, expected, band}, legend (bool), ariaLabel }
  function nullBars(container, opts) {
    const fmt = opts.format || ((v) => (Number.isInteger(+v) ? String(v) : (+v).toFixed(1)));
    const names = Object.assign({ value: "Observed", expected: "Expected by chance", band: "Range under chance" }, opts.names || {});
    responsive(container, (W) => {
      const bars = opts.bars || [];
      if (!bars.length) return;
      if (opts.legend) {
        const items = [{ sw: `<span class="sw box" style="--c:${opts.color || "var(--data)"}"></span>`, label: names.value }];
        if (bars.some((b) => fin(b.expected))) items.push({ sw: `<span class="sw tick"></span>`, label: names.expected });
        if (bars.some((b) => fin(b.lo) && fin(b.hi))) items.push({ sw: `<span class="sw box band"></span>`, label: names.band });
        container.insertAdjacentHTML("beforeend", legendHtml(items));
      }
      const H = opts.height || 220;
      const m = { t: bars.some((b) => b.note) ? 26 : 14, r: 8, b: 26, l: 38 };
      const iw = W - m.l - m.r, ih = H - m.t - m.b;
      const maxV = Math.max(1e-9, ...bars.flatMap((b) => [b.value, b.expected, b.hi].filter(fin)));
      const yt = niceTicks(0, maxV, 4), ymax = yt[yt.length - 1];
      const Y = (v) => m.t + ih - (v / ymax) * ih;
      const n = bars.length, slot = iw / n;
      const bw = Math.max(6, Math.min(24, slot * 0.4)), bandW = Math.min(slot * 0.8, bw + 28);
      const svg = svgEl("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img",
        "aria-label": opts.ariaLabel || "Bar chart with a chance band" }, container);
      for (const t of yt) {
        svgEl("line", { x1: m.l, x2: m.l + iw, y1: Y(t), y2: Y(t), stroke: "var(--hair)", "stroke-width": 1 }, svg);
        svgEl("text", { x: m.l - 8, y: Y(t) + 4, "text-anchor": "end" }, svg).textContent = tickText(t);
      }
      bars.forEach((b, i) => {
        const cx = m.l + slot * i + slot / 2;
        const band = fin(b.lo) && fin(b.hi);
        const aria = `${b.label}: ${names.value} ${fmt(b.value)}` + (fin(b.expected) ? `, ${names.expected} ${fmt(b.expected)}` : "") +
          (band ? `, ${names.band} ${fmt(b.lo)} to ${fmt(b.hi)}` : "") + (b.note ? `, ${plain(b.note)}` : "");
        const g = svgEl("g", { tabindex: 0, role: "img", "aria-label": aria, class: "nb-g" }, svg);
        svgEl("rect", { x: m.l + slot * i, y: m.t, width: slot, height: ih, fill: "transparent" }, g);
        if (band) svgEl("rect", { x: cx - bandW / 2, y: Y(b.hi), width: bandW, height: Math.max(1, Y(b.lo) - Y(b.hi)), fill: "var(--band)", rx: 2 }, g);
        if (b.value > 0) svgEl("path", { d: barPath(cx - bw / 2, Y(b.value), bw, Y(0) - Y(b.value), 4), fill: b.color || opts.color || "var(--data)", class: "nb-bar" }, g);
        if (fin(b.expected)) svgEl("line", { x1: cx - bandW / 2, x2: cx + bandW / 2, y1: Y(b.expected), y2: Y(b.expected), stroke: "var(--ink)", "stroke-width": 2, "stroke-linecap": "round" }, g);
        if (b.note) {
          const top = Math.min(Y(Math.max(0, b.value)), fin(b.hi) ? Y(b.hi) : Infinity, fin(b.expected) ? Y(b.expected) : Infinity);
          svgEl("text", { x: cx, y: top - 7, "text-anchor": "middle", class: "lbl" }, g).textContent = plain(b.note);
        }
        svgEl("text", { x: cx, y: m.t + ih + 17, "text-anchor": "middle" }, svg).textContent = b.label;
        const tip = b.tip || (`<div><b>${esc(b.label)}</b></div><div>${esc(names.value)} <b>${fmt(b.value)}</b></div>` +
          (fin(b.expected) ? `<div>${esc(names.expected)} ${fmt(b.expected)}</div>` : "") +
          (band ? `<div>${esc(names.band)} ${fmt(b.lo)} to ${fmt(b.hi)}</div>` : "") + (b.note ? `<div>${b.note}</div>` : ""));
        hoverTip(g, tip);
      });
      svgEl("line", { x1: m.l, x2: m.l + iw, y1: Y(0), y2: Y(0), stroke: "var(--axis)", "stroke-width": 1 }, svg);
    });
  }

  // ---- 5. Step chart with event markers and bands -----------------------------
  // opts: { series: [{id, name, color, points: [{x, y, tip?}]}],
  //         markers: [{x, label, seriesId?, kind: "star" | "rule"}],
  //         bands: [{seriesId, points: [{x, lo, hi}]}], flatBand: {lo, hi, color?}, yRef,
  //         height, xLabel(x), xTickLabel(x), yFormat(y), stepLabel, highlight, directLabels, ariaLabel }
  function lastAtOrBefore(pts, x) {
    let lo = 0, hi = pts.length - 1, ans = -1;
    while (lo <= hi) { const mid = (lo + hi) >> 1; if (pts[mid].x <= x) { ans = mid; lo = mid + 1; } else hi = mid - 1; }
    return ans < 0 ? null : pts[ans];
  }
  function starPath(cx, cy, R) {
    const r = R * 0.45;
    let d = "";
    for (let k = 0; k < 10; k++) {
      const a = -Math.PI / 2 + (k * Math.PI) / 5, rr = k % 2 ? r : R;
      d += (k ? "L" : "M") + (cx + rr * Math.cos(a)).toFixed(2) + "," + (cy + rr * Math.sin(a)).toFixed(2);
    }
    return d + "Z";
  }
  function stepChart(container, opts) {
    responsive(container, (W) => {
      const series = (opts.series || []).map((s) => Object.assign({}, s, {
        points: s.points.filter((p) => fin(p.y)).sort((a, b) => a.x - b.x) })).filter((s) => s.points.length);
      if (!series.length) return;
      const byId = Object.fromEntries(series.map((s) => [s.id, s]));
      const markers = opts.markers || [], bands = opts.bands || [], fb = opts.flatBand;
      const yFmt = opts.yFormat || ((y) => (Number.isInteger(+y) ? String(y) : (+y).toFixed(1)));
      const narrow = W < 520;
      const labels = opts.directLabels !== false && !narrow && series.length <= 6;
      const H = opts.height || 280;
      const m = { t: 12, r: labels ? 110 : 14, b: 34, l: 42 };
      const iw = W - m.l - m.r;
      const xsSet = new Set();
      for (const s of series) for (const p of s.points) xsSet.add(p.x);
      for (const k of markers) xsSet.add(k.x);
      const xs = [...xsSet].sort((a, b) => a - b);
      const xmin = xs[0], xmax = xs[xs.length - 1];
      const X = (x) => m.l + (xmax === xmin ? iw / 2 : ((x - xmin) / (xmax - xmin)) * iw);

      // Rule labels go in lanes above the plot so they never collide.
      const rules = markers.filter((k) => k.kind === "rule").sort((a, b) => a.x - b.x);
      const laneEnds = [];
      const placed = rules.map((k) => {
        const w = String(k.label || "").length * 6.4 + 4, x0 = X(k.x);
        const right = x0 + w <= m.l + iw + m.r;
        const span = right ? [x0, x0 + w] : [x0 - w, x0];
        let lane = laneEnds.findIndex((e) => e < span[0] - 6);
        if (lane < 0) { lane = laneEnds.length; laneEnds.push(span[1]); } else laneEnds[lane] = span[1];
        return { k, lane, right };
      });
      m.t += laneEnds.length * 15;
      const ih = H - m.t - m.b;

      const ys = [];
      for (const s of series) for (const p of s.points) ys.push(p.y);
      for (const b of bands) for (const p of b.points) { if (fin(p.lo)) ys.push(p.lo); if (fin(p.hi)) ys.push(p.hi); }
      if (fb) ys.push(fb.lo, fb.hi);
      if (fin(opts.yRef)) ys.push(opts.yRef);
      const yt = niceTicks(Math.min(...ys), Math.max(...ys), 4);
      const ymin = yt[0], ymax = yt[yt.length - 1];
      const Y = (y) => m.t + ih - ((y - ymin) / (ymax - ymin)) * ih;

      const svg = svgEl("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img",
        "aria-label": opts.ariaLabel || "Step chart" }, container);
      for (const t of yt) {
        svgEl("line", { x1: m.l, x2: m.l + iw, y1: Y(t), y2: Y(t), stroke: "var(--hair)", "stroke-width": 1 }, svg);
        svgEl("text", { x: m.l - 8, y: Y(t) + 4, "text-anchor": "end" }, svg).textContent = tickText(t);
      }
      svgEl("line", { x1: m.l, x2: m.l + iw, y1: m.t + ih, y2: m.t + ih, stroke: "var(--axis)", "stroke-width": 1 }, svg);
      const xt = spaced(niceTicks(xmin, xmax, narrow ? 4 : 8).filter((v) => v >= xmin && v <= xmax && Number.isInteger(v)), X, narrow ? 44 : 56);
      for (const t of xt) {
        svgEl("text", { x: X(t), y: m.t + ih + 18, "text-anchor": "middle" }, svg).textContent = opts.xTickLabel ? opts.xTickLabel(t) : t;
      }
      if (fb && fin(fb.lo) && fin(fb.hi)) {
        svgEl("rect", { x: m.l, y: Y(fb.hi), width: iw, height: Math.max(1, Y(fb.lo) - Y(fb.hi)), fill: fb.color || "var(--data)", "fill-opacity": 0.12 }, svg);
      }
      for (const b of bands) {
        const s = byId[b.seriesId];
        const pts = b.points.filter((p) => fin(p.lo) && fin(p.hi)).sort((a, c) => a.x - c.x);
        if (pts.length < 2) continue;
        let d = `M${X(pts[0].x)},${Y(pts[0].hi)}`;
        for (let i = 1; i < pts.length; i++) d += `H${X(pts[i].x)}V${Y(pts[i].hi)}`;
        d += `L${X(pts[pts.length - 1].x)},${Y(pts[pts.length - 1].lo)}`;
        for (let i = pts.length - 2; i >= 0; i--) d += `V${Y(pts[i].lo)}H${X(pts[i].x)}`;
        svgEl("path", { d: d + "Z", fill: (s && s.color) || b.color || "var(--data)", "fill-opacity": 0.12 }, svg);
      }
      if (fin(opts.yRef)) svgEl("line", { x1: m.l, x2: m.l + iw, y1: Y(opts.yRef), y2: Y(opts.yRef), stroke: "var(--muted)", "stroke-width": 1 }, svg);

      for (const p of placed) {
        const x0 = X(p.k.x), ly = m.t - 6 - (laneEnds.length - 1 - p.lane) * 15;
        svgEl("line", { x1: x0, x2: x0, y1: ly + 3, y2: m.t + ih, stroke: "var(--muted)", "stroke-width": 1 }, svg);
        svgEl("text", { x: p.right ? x0 + 4 : x0 - 4, y: ly, "text-anchor": p.right ? "start" : "end" }, svg).textContent = p.k.label || "";
      }
      const ordered = [...series].sort((a, b) => (a.id === opts.highlight) - (b.id === opts.highlight));
      for (const s of ordered) {
        const dim = opts.highlight && s.id !== opts.highlight;
        const color = dim ? "var(--axis)" : s.color;
        const pts = s.points;
        let d = `M${X(pts[0].x)},${Y(pts[0].y)}`;
        for (let i = 1; i < pts.length; i++) d += `H${X(pts[i].x)}V${Y(pts[i].y)}`;
        if (pts.length > 1) svgEl("path", { d, fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
        const last = pts[pts.length - 1];
        svgEl("circle", { cx: X(last.x), cy: Y(last.y), r: 4, fill: color, stroke: "var(--surface)", "stroke-width": 2 }, svg);
      }
      for (const k of markers.filter((k) => k.kind !== "rule")) {
        const s = byId[k.seriesId];
        const p = s ? lastAtOrBefore(s.points, k.x) : null;
        const cy = p ? Y(p.y) : m.t + 8;
        svgEl("path", { d: starPath(X(k.x), cy, 7), fill: s ? s.color : "var(--ink-2)", stroke: "var(--surface)", "stroke-width": 1.5, "stroke-linejoin": "round" }, svg);
      }
      if (labels) {
        const ends = series.filter((s) => s.points[s.points.length - 1].x === xmax)
          .map((s) => ({ s, y: Y(s.points[s.points.length - 1].y) })).sort((a, b) => a.y - b.y);
        for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 15) ends[i].y = ends[i - 1].y + 15;
        const over = ends.length ? ends[ends.length - 1].y - (m.t + ih) : 0;
        if (over > 0) ends.forEach((e) => (e.y -= over));
        for (const e of ends) {
          const t = svgEl("text", { x: m.l + iw + 10, y: e.y + 4, class: "lbl" }, svg);
          t.textContent = e.s.name;
          if (opts.highlight && e.s.id !== opts.highlight) t.setAttribute("style", "fill: var(--muted); font-weight: 400");
        }
      }

      // Crosshair + tooltip, by pointer and by keyboard.
      const cross = svgEl("line", { y1: m.t, y2: m.t + ih, stroke: "var(--ink-2)", "stroke-width": 1, visibility: "hidden" }, svg);
      const hit = svgEl("rect", { x: m.l - 6, y: m.t, width: iw + 12, height: ih, fill: "transparent", tabindex: 0, "data-tipped": "",
        "aria-label": `Chart data: use the arrow keys to step through ${opts.stepLabel || "rolls"}; hold Shift for 10 at a time` }, svg);
      let cur = xs.length - 1;
      const showAt = (i, cx, cy) => {
        cur = Math.max(0, Math.min(xs.length - 1, i));
        const x = xs[cur];
        cross.setAttribute("x1", X(x)); cross.setAttribute("x2", X(x));
        cross.setAttribute("visibility", "visible");
        const rows = series.map((s) => ({ s, p: x >= s.points[0].x && x <= s.points[s.points.length - 1].x ? lastAtOrBefore(s.points, x) : null }))
          .filter((r) => r.p).sort((a, b) => b.p.y - a.p.y);
        const head = opts.xLabel ? opts.xLabel(x) : `${esc(opts.stepLabel || "x")} ${x}`;
        const body = rows.map((r) => `<div class="row"><span class="hex" style="--c:${r.s.color}"></span>${esc(r.s.name)} <b>${r.p.tip || yFmt(r.p.y)}</b></div>`).join("");
        const ev = markers.filter((k) => k.x === x).map((k) => `<div class="row">${k.kind === "rule" ? "|" : "★"} ${esc(k.label || "")}</div>`).join("");
        if (cx === undefined) {
          const box = svg.getBoundingClientRect();
          cx = box.left + X(x); cy = box.top + m.t + 20;
        }
        Tip.show(`<div>${head}</div>${body}${ev}`, cx, cy);
      };
      const nearest = (clientX) => {
        const box = svg.getBoundingClientRect(), px = clientX - box.left;
        let lo = 0, hi = xs.length - 1;
        while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (X(xs[mid]) < px) lo = mid; else hi = mid; }
        return Math.abs(X(xs[lo]) - px) <= Math.abs(X(xs[hi]) - px) ? lo : hi;
      };
      const hide = () => { cross.setAttribute("visibility", "hidden"); Tip.hide(); };
      hit.addEventListener("pointermove", (e) => showAt(nearest(e.clientX), e.clientX, e.clientY));
      hit.addEventListener("pointerdown", (e) => showAt(nearest(e.clientX), e.clientX, e.clientY));
      hit.addEventListener("pointerleave", (e) => { if (e.pointerType !== "touch") hide(); });
      hit.addEventListener("focus", () => showAt(cur));
      hit.addEventListener("blur", hide);
      hit.addEventListener("keydown", (e) => {
        const step = e.shiftKey ? 10 : 1;
        if (e.key === "ArrowRight" || e.key === "ArrowUp") { showAt(cur + step); e.preventDefault(); }
        else if (e.key === "ArrowLeft" || e.key === "ArrowDown") { showAt(cur - step); e.preventDefault(); }
        else if (e.key === "Home") { showAt(0); e.preventDefault(); }
        else if (e.key === "End") { showAt(xs.length - 1); e.preventDefault(); }
        else if (e.key === "Escape") hide();
      });
    });
  }

  // ---- 6. Heat matrix ------------------------------------------------------------
  // opts: { rows: [ids], cols: [ids], label(id, "row" | "col") -> html, cell(r, c) -> {value, text, sub?, tip?} | null,
  //         diverging: {min, mid, max}, or sequential: {min, max, color?}, directed, corner (html),
  //         emptyText, selfText, scale: {low, high} (captions for the color key), caption (sr-only) }
  // Builds the same table markup as the head to head page (.matrix .cell with --fill).
  function heatMatrix(container, opts) {
    const rows = opts.rows || [], cols = opts.cols || [];
    const lab = opts.label || ((id) => esc(id));
    const seqColor = (opts.sequential && opts.sequential.color) || "var(--div-pos)";
    const fill = (v) => {
      if (!fin(v)) return "transparent";
      if (opts.diverging) {
        const { min, mid, max } = Object.assign({ mid: 0 }, opts.diverging);
        const t = v >= mid ? (max === mid ? 0 : (v - mid) / (max - mid)) : (mid === min ? 0 : (mid - v) / (mid - min));
        const pole = v >= mid ? "var(--div-pos)" : "var(--div-neg)";
        return `color-mix(in oklab, ${pole} ${(Math.min(1, Math.max(0, t)) * 60).toFixed(0)}%, var(--div-mid))`;
      }
      const s = opts.sequential || { min: 0, max: 1 };
      const t = s.max === s.min ? 0 : (v - s.min) / (s.max - s.min);
      return `color-mix(in oklab, ${seqColor} ${(Math.min(1, Math.max(0, t)) * 60).toFixed(0)}%, var(--div-mid))`;
    };
    const tips = [];
    const corner = opts.corner !== undefined ? opts.corner
      : opts.directed ? `<span class="mx-corner">Row acts on column</span>` : "";
    const head = cols.map((c) => `<th class="colh" scope="col">${lab(c, "col")}</th>`).join("");
    const body = rows.map((r) => `<tr><th class="rowh" scope="row">${lab(r, "row")}</th>${cols.map((c) => {
      if (r === c && !opts.allowSelf) return `<td><div class="cell self" aria-label="${esc(opts.selfText || "same player")}"></div></td>`;
      const k = opts.cell(r, c);
      if (!k) return `<td><div class="cell" style="--fill:transparent"><span>${esc(opts.emptyText || "no games")}</span></div></td>`;
      const i = tips.push(k.tip || `<b>${k.text !== undefined ? k.text : k.value}</b>`) - 1;
      const text = k.text !== undefined ? k.text : esc(String(k.value));
      return `<td><div class="cell" tabindex="0" data-mx="${i}" style="--fill:${fill(k.value)}"><b>${text}</b>${k.sub ? `<span>${k.sub}</span>` : ""}</div></td>`;
    }).join("")}</tr>`).join("");
    let scale = "";
    if (opts.scale) {
      const grad = opts.diverging ? "" : ` style="background:linear-gradient(90deg, var(--div-mid), color-mix(in oklab, ${seqColor} 60%, var(--div-mid)))"`;
      scale = `<div class="scale"><span>${opts.scale.low || ""}</span><span class="bar"${grad} aria-hidden="true"></span><span>${opts.scale.high || ""}</span></div>`;
    }
    container.innerHTML = `<div class="table-wrap"><table class="matrix${opts.directed ? " directed" : ""}">` +
      (opts.caption ? `<caption class="mx-cap">${opts.caption}</caption>` : "") +
      `<thead><tr><th class="corner">${corner}</th>${head}</tr></thead><tbody>${body}</tbody></table></div>${scale}`;
    const table = container.querySelector("table");
    const cellOf = (e) => e.target.closest && e.target.closest(".cell[data-mx]");
    const show = (c, e) => {
      let x, y;
      if (e && e.clientX !== undefined) { x = e.clientX; y = e.clientY; }
      else { const r = c.getBoundingClientRect(); x = r.left + r.width / 2; y = r.top; }
      Tip.show(tips[+c.dataset.mx], x, y);
    };
    table.setAttribute("data-tipped", "");
    table.addEventListener("pointermove", (e) => { const c = cellOf(e); if (c) show(c, e); else Tip.hide(); });
    table.addEventListener("pointerdown", (e) => { const c = cellOf(e); if (c) show(c, e); });
    table.addEventListener("pointerleave", (e) => { if (e.pointerType !== "touch") Tip.hide(); });
    table.addEventListener("focusin", (e) => { const c = cellOf(e); if (c) show(c); });
    table.addEventListener("focusout", () => Tip.hide());
  }

  // ---- 7. Funnel plot ------------------------------------------------------------
  // opts: { points: [{x (games), y (mean), label, color, tip?}], se: (x) => SE | {sd}, ref (default 0),
  //         level (default 0.95), xTitle, yTitle, format(y), labels (bool), height, ariaLabel, limitLabel }
  function funnelPlot(container, opts) {
    const level = opts.level || 0.95;
    const z = probit(1 - (1 - level) / 2);
    const ref = fin(opts.ref) ? opts.ref : 0;
    const se = typeof opts.se === "function" ? opts.se : (x) => opts.se.sd / Math.sqrt(x);
    const fmt = opts.format || fmt2;
    responsive(container, (W) => {
      const pts = (opts.points || []).filter((p) => fin(p.x) && fin(p.y) && p.x > 0);
      if (!pts.length) return;
      const narrow = W < 520;
      const H = opts.height || 300;
      const m = { t: opts.yTitle ? 24 : 12, r: 16, b: opts.xTitle ? 46 : 30, l: 46 };
      const iw = W - m.l - m.r, ih = H - m.t - m.b;
      const minX = Math.min(...pts.map((p) => p.x)), maxX = Math.max(...pts.map((p) => p.x));
      const xt = niceTicks(0, maxX, narrow ? 4 : 6), xmax = xt[xt.length - 1];
      const hw0 = z * se(minX);
      const ys = pts.map((p) => p.y).concat([ref + hw0, ref - hw0]);
      const yt = niceTicks(Math.min(...ys), Math.max(...ys), 5);
      const ymin = yt[0], ymax = yt[yt.length - 1];
      const X = (x) => m.l + (x / xmax) * iw;
      const Y = (y) => m.t + ih - ((y - ymin) / (ymax - ymin)) * ih;
      const svg = svgEl("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img",
        "aria-label": opts.ariaLabel || `Funnel plot with ${Math.round(level * 100)}% limits` }, container);
      const clipId = "fpclip" + Math.random().toString(36).slice(2, 8);
      const defs = svgEl("defs", {}, svg);
      svgEl("rect", { x: m.l, y: m.t, width: iw, height: ih }, svgEl("clipPath", { id: clipId }, defs));
      for (const t of yt) {
        svgEl("line", { x1: m.l, x2: m.l + iw, y1: Y(t), y2: Y(t), stroke: "var(--hair)", "stroke-width": 1 }, svg);
        svgEl("text", { x: m.l - 8, y: Y(t) + 4, "text-anchor": "end" }, svg).textContent = tickText(t);
      }
      for (const t of xt) svgEl("text", { x: X(t), y: m.t + ih + 18, "text-anchor": "middle" }, svg).textContent = t;
      svgEl("line", { x1: m.l, x2: m.l + iw, y1: m.t + ih, y2: m.t + ih, stroke: "var(--axis)", "stroke-width": 1 }, svg);
      if (opts.xTitle) svgEl("text", { x: m.l + iw / 2, y: H - 6, "text-anchor": "middle" }, svg).textContent = opts.xTitle;
      if (opts.yTitle) svgEl("text", { x: m.l - 40, y: 12 }, svg).textContent = opts.yTitle;

      // Start the funnel well left of the first point (geometric spacing) so it leaves the plot through the top and bottom.
      const x0 = Math.max(1e-6, minX / 50), N = 120;
      const xsF = Array.from({ length: N + 1 }, (_, i) => x0 * Math.pow(xmax / x0, i / N));
      const up = xsF.map((x) => `${X(x).toFixed(1)},${Y(ref + z * se(x)).toFixed(1)}`);
      const dn = xsF.map((x) => `${X(x).toFixed(1)},${Y(ref - z * se(x)).toFixed(1)}`);
      const g0 = svgEl("g", { "clip-path": `url(#${clipId})` }, svg);
      svgEl("path", { d: `M${up.join("L")}L${[...dn].reverse().join("L")}Z`, fill: "var(--data)", "fill-opacity": 0.1 }, g0);
      svgEl("path", { d: `M${up.join("L")}`, fill: "none", stroke: "var(--muted)", "stroke-width": 1 }, g0);
      svgEl("path", { d: `M${dn.join("L")}`, fill: "none", stroke: "var(--muted)", "stroke-width": 1 }, g0);
      svgEl("line", { x1: m.l, x2: m.l + iw, y1: Y(ref), y2: Y(ref), stroke: "var(--ink-2)", "stroke-width": 1 }, svg);
      const lim = opts.limitLabel || `${Math.round(level * 100)}% limits`;
      svgEl("text", { x: m.l + iw, y: Y(ref + z * se(xmax)) - 6, "text-anchor": "end" }, svg).textContent = lim;

      // Points: 24px hit circles, 10px dots with a surface ring, labels that dodge each other.
      const boxes = [];
      const sorted = [...pts].sort((a, b) => b.y - a.y);
      for (const p of sorted) {
        const cx = X(p.x), cy = Y(p.y);
        const g = svgEl("g", { tabindex: 0, role: "img", "aria-label": `${plain(p.label)}: ${plain(fmt(p.y))} over ${p.x} games` }, svg);
        svgEl("circle", { cx, cy, r: 12, fill: "transparent" }, g);
        const dot = svgEl("circle", { cx, cy, r: 5, fill: p.color || "var(--data)", stroke: "var(--surface)", "stroke-width": 2 }, g);
        if (opts.labels !== false && p.label) {
          const txt = plain(p.label), w = txt.length * 7 + 2, h = 14;
          const cands = [[cx + 9, cy + 4, "start"], [cx - 9, cy + 4, "end"], [cx + 9, cy - 9, "start"], [cx + 9, cy + 16, "start"], [cx - 9, cy - 9, "end"], [cx - 9, cy + 16, "end"]];
          let pick = null;
          for (const [lx, ly, an] of cands) {
            const bx = an === "start" ? lx : lx - w, by = ly - 11;
            const inside = bx >= m.l && bx + w <= m.l + iw + m.r && by >= 0 && by + h <= m.t + ih;
            const hits = boxes.some((b) => bx < b.x + b.w && bx + w > b.x && by < b.y + b.h && by + h > b.y);
            if (inside && !hits) { pick = { lx, ly, an, bx, by }; break; }
          }
          if (pick) {
            boxes.push({ x: pick.bx, y: pick.by, w, h });
            svgEl("text", { x: pick.lx, y: pick.ly, "text-anchor": pick.an, class: "lbl" }, g).textContent = txt;
          }
        }
        boxes.push({ x: cx - 6, y: cy - 6, w: 12, h: 12 });
        const lo = ref - z * se(p.x), hi = ref + z * se(p.x);
        const tip = p.tip || `<div><b>${p.label}</b></div><div>Mean <b>${fmt(p.y)}</b> over ${p.x} games</div><div>${Math.round(level * 100)}% limits ${fmt(lo)} to ${fmt(hi)}</div>`;
        hoverTip(g, tip, () => dot.setAttribute("r", 6), () => dot.setAttribute("r", 5));
      }
    });
  }

  // ---- 8. Level | Rate switch and the trailing rate --------------------------------
  // levelRate(container, {value: "level" | "rate", onChange(value), labels: {level, rate}, ariaLabel})
  // Replaces the container's content with the switch. Returns {el, value (getter), set(value)}.
  function levelRate(container, opts) {
    opts = opts || {};
    let value = opts.value === "rate" ? "rate" : "level";
    const labels = Object.assign({ level: "Level", rate: "Rate" }, opts.labels || {});
    const el = document.createElement("div");
    el.className = "seg";
    el.setAttribute("role", "group");
    el.setAttribute("aria-label", opts.ariaLabel || "Show the running total or the rate per round");
    el.innerHTML = ["level", "rate"].map((v) => `<button type="button" data-v="${v}" aria-pressed="${v === value}">${esc(labels[v])}</button>`).join("");
    const set = (v) => {
      value = v === "rate" ? "rate" : "level";
      el.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === value)));
    };
    el.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-v]");
      if (!b || b.dataset.v === value) return;
      set(b.dataset.v);
      if (opts.onChange) opts.onChange(value);
    });
    container.innerHTML = "";
    container.appendChild(el);
    return { el, set, get value() { return value; } };
  }

  // r(t) = [Y(t) - Y(max(0, t - w*n))] / (min(t, w*n) / n), per round, for integer roll index t >= 1.
  // points: [{x: t, y}] dense from t = 0 (a sparse series is read as a step function). Returns [{x, y, level}].
  function rateSeries(points, n, w) {
    if (w === undefined) w = 3;
    const pts = (points || []).filter((p) => p && fin(p.x) && fin(p.y)).sort((a, b) => a.x - b.x);
    const win = w * n, out = [];
    for (const p of pts) {
      const t = p.x;
      if (t <= 0) continue;
      const base = lastAtOrBefore(pts, Math.max(0, t - win));
      if (!base) continue;
      out.push({ x: t, y: (p.y - base.y) / (Math.min(t, win) / n), level: p.y });
    }
    return out;
  }

  // ---- 9. "vs the table" marker ------------------------------------------------------
  // arrow(delta, {clear, good: "up" | "down" | "neutral" (or true/false), digits, unit, tip, label}) -> HTML
  const ARROW_UP = "M5 .8 9.4 5.6H6.4V11.2H3.6V5.6H.6Z", ARROW_DN = "M5 11.2 9.4 6.4H6.4V.8H3.6V6.4H.6Z";
  const arrowSvg = (dir) => `<svg class="vt-ic" viewBox="0 0 10 12" width="9" height="11" aria-hidden="true" focusable="false">` +
    (dir ? `<path d="${dir > 0 ? ARROW_UP : ARROW_DN}"/>` : `<circle cx="5" cy="6" r="2.4"/>`) + `</svg>`;
  function arrow(delta, o) {
    o = o || {};
    const d = fin(o.digits) ? o.digits : 1, unit = o.unit !== undefined ? o.unit : "SD";
    const goodDir = o.good === true || o.good === "up" ? 1 : o.good === false || o.good === "down" ? -1 : 0;
    const v = +delta, sign = v > 0 ? 1 : v < 0 ? -1 : 0;
    const clear = !!o.clear && sign !== 0;
    const tone = !goodDir || !clear ? "flat" : sign === goodDir ? "good" : "bad";
    const txt = signed(v, d) + (unit ? " " + unit : "");
    const where = sign > 0 ? "above the table" : sign < 0 ? "below the table" : "level with the table";
    const why = tone === "good" ? "better for the player" : tone === "bad" ? "worse for the player"
      : !goodDir ? "neutral stat" : "within noise";
    const label = o.label || `${txt.replace(MINUS, "minus ")}, ${where}, ${why}` + (o.tip ? `. ${plain(o.tip)}` : "");
    const tipAttr = o.tip ? ` tabindex="0" data-tip="${esc(o.tip)}"` : "";
    return `<span class="vt vt-${tone}" role="img" aria-label="${esc(label)}"${tipAttr}>${arrowSvg(sign)}<span class="vt-t" aria-hidden="true">${txt}</span></span>`;
  }
  function markerLegend() {
    const pair = (tone) => `<span class="vt vt-${tone}" aria-hidden="true">${arrowSvg(1)}${arrowSvg(-1)}</span>`;
    return `<ul class="legend vt-legend">` +
      `<li>${pair("good")}Better than the table for this player</li>` +
      `<li>${pair("bad")}Worse than the table</li>` +
      `<li>${pair("flat")}Within noise (the 95% interval includes 0) or a neutral stat</li>` +
      `<li class="vt-dir">Arrow up: above the table. Arrow down: below it.</li></ul>`;
  }

  // ---- 10. Info button and popover ------------------------------------------------------
  // infoButton(id, title, html) -> HTML. bindInfo() wires every one on the page (idempotent; also runs on load).
  function infoButton(id, title, html) {
    const t = plain(title);
    return `<span class="info"><button type="button" class="info-btn" aria-expanded="false" aria-controls="${esc(id)}" aria-label="About ${esc(t)}">` +
      `<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false"><circle cx="8" cy="8" r="7.2" fill="none" stroke="currentColor" stroke-width="1.3"/>` +
      `<circle cx="8" cy="4.8" r="1.05" fill="currentColor"/><rect x="7.15" y="6.7" width="1.7" height="5.2" rx=".6" fill="currentColor"/></svg></button>` +
      `<span class="info-pop" id="${esc(id)}" hidden><span class="info-h">${esc(t)}</span><span class="info-b">${html}</span></span></span>`;
  }
  let openBtn = null, infoBound = false;
  function placeInfo() {
    if (!openBtn) return;
    const pop = document.getElementById(openBtn.getAttribute("aria-controls"));
    if (!pop || !openBtn.isConnected) { openBtn = null; return; }
    const r = openBtn.getBoundingClientRect();
    const vw = document.documentElement.clientWidth, vh = window.innerHeight;
    const w = pop.offsetWidth, h = pop.offsetHeight;
    const left = Math.max(8, Math.min(r.left - 10, vw - w - 8));
    let top = r.bottom + 6;
    if (top + h > vh - 8 && r.top - h - 6 >= 8) top = r.top - h - 6;
    pop.style.left = left + "px";
    pop.style.top = top + "px";
  }
  function closeInfo(refocus) {
    if (!openBtn) return;
    const btn = openBtn, pop = document.getElementById(btn.getAttribute("aria-controls"));
    openBtn = null;
    if (pop) pop.hidden = true;
    btn.setAttribute("aria-expanded", "false");
    if (refocus && btn.isConnected) btn.focus();
  }
  function openInfo(btn) {
    closeInfo();
    const pop = document.getElementById(btn.getAttribute("aria-controls"));
    if (!pop) return;
    Tip.hide();
    pop.hidden = false;
    btn.setAttribute("aria-expanded", "true");
    openBtn = btn;
    placeInfo();
  }
  function bindInfo() {
    if (infoBound) return;
    infoBound = true;
    document.addEventListener("click", (e) => {
      const t = e.target;
      const btn = t.closest && t.closest(".info-btn");
      if (btn) { if (btn === openBtn) closeInfo(); else openInfo(btn); return; }
      if (openBtn && !(t.closest && t.closest(".info-pop"))) closeInfo();
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && openBtn) closeInfo(true); });
    window.addEventListener("scroll", placeInfo, { passive: true, capture: true });
    window.addEventListener("resize", placeInfo);
    // Generic tooltips for HTML bits that carry data-tip (the "vs the table" markers).
    const tipOf = (e) => e.target.closest && e.target.closest("[data-tip]");
    const showTip = (el, e) => {
      let x, y;
      if (e && e.clientX !== undefined) { x = e.clientX; y = e.clientY; }
      else { const r = el.getBoundingClientRect(); x = r.left + r.width / 2; y = r.top; }
      Tip.show(el.getAttribute("data-tip"), x, y);
    };
    document.addEventListener("pointerover", (e) => { const el = tipOf(e); if (el) showTip(el, e); });
    document.addEventListener("pointerout", (e) => { const el = tipOf(e); if (el && !el.contains(e.relatedTarget) && e.pointerType !== "touch") Tip.hide(); });
    document.addEventListener("focusin", (e) => { const el = tipOf(e); if (el) showTip(el); });
    document.addEventListener("focusout", (e) => { if (tipOf(e)) Tip.hide(); });
    // A tap anywhere else clears a tooltip left open by touch.
    document.addEventListener("pointerdown", (e) => {
      const t = e.target;
      if (!(t.closest && (t.closest("[data-tipped]") || t.closest("[data-tip]")))) Tip.hide();
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bindInfo);
  else bindInfo();

  window.Charts = {
    lineChart, barChart, Tip, svgEl, esc, niceTicks,
    forestPlot, coefPlot, statTile, nullBars, stepChart, heatMatrix, funnelPlot,
    levelRate, rateSeries, arrow, markerLegend, infoButton, bindInfo,
  };
})();
