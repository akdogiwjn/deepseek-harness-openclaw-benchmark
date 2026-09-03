function drawChart(el, spec) {
  const NS = "http://www.w3.org/2000/svg", W = 620, H = 260;
  const P = {l: 66, r: spec.rightAxis ? 62 : 24, t: 30, b: 58};
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", spec.title);
  const add = (name, attrs, text) => {
    const node = document.createElementNS(NS, name);
    Object.entries(attrs || {}).forEach(([key, value]) => node.setAttribute(key, value));
    if (text !== undefined) node.textContent = text;
    svg.appendChild(node); return node;
  };
  const fmt = value => {
    const n = Number(value);
    if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
    if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
    if (Math.abs(n) >= 100) return n.toFixed(0);
    if (Math.abs(n) >= 10) return n.toFixed(1);
    return n.toFixed(2);
  };
  const all = spec.series.flatMap(item => item.points);
  const categories = spec.x.scale === "category" ? [...new Set(all.map(point => String(point.x)))] : [];
  const tx = value => spec.x.scale === "log" ? Math.log10(Number(value))
    : spec.x.scale === "log1p" ? Math.log10(Number(value) + 1) : Number(value);
  const xValues = spec.x.scale === "category" ? categories.map((_, index) => index) : all.map(point => tx(point.x));
  const xMin = Math.min(...xValues), xMax = Math.max(...xValues);
  const sx = value => {
    const transformed = spec.x.scale === "category" ? categories.indexOf(String(value)) : tx(value);
    return P.l + ((transformed - xMin) / (xMax - xMin || 1)) * (W - P.l - P.r);
  };
  const leftPoints = spec.series.filter(item => item.axis !== "right").flatMap(item => item.points);
  const rightPoints = spec.series.filter(item => item.axis === "right").flatMap(item => item.points);
  const extent = (values, fixed) => {
    const high = fixed?.max ?? Math.max(...values.flatMap(point => [point.y, point.high ?? point.y]), 0);
    const low = fixed?.min ?? Math.min(...values.flatMap(point => [point.y, point.low ?? point.y]), 0);
    return [Math.min(0, low), high || 1];
  };
  const [yMin, yMax] = extent(leftPoints);
  const [rMin, rMax] = rightPoints.length ? extent(rightPoints, spec.rightAxis) : [0, 1];
  const sy = (value, axis) => {
    const [min, max] = axis === "right" ? [rMin, rMax] : [yMin, yMax];
    return H - P.b - ((value - min) / (max - min || 1)) * (H - P.t - P.b);
  };
  for (let index = 0; index <= 4; index++) {
    const y = P.t + index * (H - P.t - P.b) / 4;
    add("line", {x1: P.l, y1: y, x2: W - P.r, y2: y, stroke: "#dce5df"});
    add("text", {x: P.l - 9, y: y + 4, "text-anchor": "end", class: "axis-label"}, fmt(yMax - index * (yMax - yMin) / 4));
    if (rightPoints.length) add("text", {x: W - P.r + 9, y: y + 4, class: "axis-label"}, fmt(rMax - index * (rMax - rMin) / 4));
  }
  const xTicks = spec.x.scale === "category" ? categories : [...new Set(all.map(point => point.x))];
  const stride = Math.max(1, Math.ceil(xTicks.length / 7));
  xTicks.forEach((value, index) => {
    if (index % stride && index !== xTicks.length - 1) return;
    const x = sx(value);
    add("line", {x1: x, y1: H - P.b, x2: x, y2: H - P.b + 5, stroke: "#82939a"});
    add("text", {x, y: H - P.b + 19, "text-anchor": "middle", class: "axis-label"}, spec.x.scale === "category" ? value : fmt(value));
  });
  add("line", {x1: P.l, y1: H - P.b, x2: W - P.r, y2: H - P.b, stroke: "#82939a"});
  add("line", {x1: P.l, y1: P.t, x2: P.l, y2: H - P.b, stroke: "#82939a"});

  if (spec.type === "bar") {
    const slot = (W - P.l - P.r) / Math.max(1, categories.length);
    const width = Math.min(50, slot * .62 / spec.series.length);
    spec.series.forEach((item, seriesIndex) => item.points.forEach(point => {
      const x = sx(point.x) - width * spec.series.length / 2 + seriesIndex * width;
      const y = sy(point.y, item.axis);
      const rect = add("rect", {x, y, width: width - 2, height: H - P.b - y, rx: 3, fill: item.color});
      add("title", {}, `${item.name} · ${point.x}: ${fmt(point.y)} ${spec.y.unit}`);
      rect.appendChild(svg.lastChild);
    }));
  } else {
    spec.series.forEach(item => {
      const path = item.points.map((point, index) => `${index ? "L" : "M"}${sx(point.x).toFixed(1)} ${sy(point.y, item.axis).toFixed(1)}`).join(" ");
      add("path", {d: path, fill: "none", stroke: item.color, "stroke-width": 3, "stroke-linejoin": "round"});
      item.points.forEach(point => {
        const x = sx(point.x), y = sy(point.y, item.axis);
        if (point.low !== undefined && point.high !== undefined) {
          add("line", {x1: x, y1: sy(point.low, item.axis), x2: x, y2: sy(point.high, item.axis), stroke: item.color, "stroke-opacity": .42});
        }
        const circle = add("circle", {cx: x, cy: y, r: 4, fill: item.color});
        const range = point.low === undefined ? "" : ` · range ${fmt(point.low)}–${fmt(point.high)}`;
        const unit = item.axis === "right" ? spec.rightAxis.unit : spec.y.unit;
        const title = document.createElementNS(NS, "title");
        title.textContent = `${item.name} · x=${point.x}: ${fmt(point.y)} ${unit}${range}`;
        circle.appendChild(title);
      });
    });
  }
  add("text", {x: (P.l + W - P.r) / 2, y: H - 8, "text-anchor": "middle", class: "axis-title"}, spec.x.label);
  add("text", {x: 15, y: 15, class: "axis-title"}, `${spec.y.label} (${spec.y.unit})`);
  if (spec.rightAxis) add("text", {x: W - 6, y: 15, "text-anchor": "end", class: "axis-title"}, `${spec.rightAxis.label} (${spec.rightAxis.unit})`);
  const legend = document.createElement("div"); legend.className = "legend";
  spec.series.forEach(item => { const entry = document.createElement("span"); entry.innerHTML = `<i style="background:${item.color}"></i>${item.name}`; legend.appendChild(entry); });
  el.replaceChildren(svg, legend);
}
