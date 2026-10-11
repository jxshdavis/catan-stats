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
    let lastW = 0, ro = null;
    const run = () => {
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
  //         height, highlight (series id), directLabels (bool), xTickLabel(x) }
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
        "aria-label": "Chart data: use left and right arrow keys to step through games" }, svg);
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

  window.Charts = { lineChart, barChart, Tip, svgEl, esc, niceTicks };
})();
