# -*- coding: utf-8 -*-
"""Build a Neo4j/PIKG-style HTML visualization from a WITNESS TKG case.

Reads entity2id / relation2id / test.txt quadruples (s, r, o, t) and writes
an interactive D3 HTML (MATCH bar, legends, zoom, drag, click-to-focus).

Example:
  python build_tkg_html.py ^
    --root D:\\UniDiag_WiFi\\EntityEmbedding\\data\\WITNESS_TKG_t_Ab1N\\h2h ^
    --out  D:\\UniDiag_WiFi\\Visualizer\\out\\WITNESS_TKG_t_Ab1N_h2h_Normal.html
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

NODE_COLORS = {
    "Case": "#C990C0",
    "STA": "#4C8EDA",
    "AP": "#57C7E3",
    "Gateway": "#F16667",
    "IperfMetric": "#8DCC93",
    "FlowStat": "#FFC454",
    "Warning": "#F79767",
    "LogTemplate": "#D9C8AE",
    "Other": "#A5ABB6",
}
NODE_RADIUS = {
    "Case": 22.0,
    "STA": 18.0,
    "AP": 20.0,
    "Gateway": 18.0,
    "IperfMetric": 11.4,
    "FlowStat": 11.2,
    "Warning": 12.2,
    "LogTemplate": 11.0,
    "Other": 11.0,
}
REL_COLORS = {
    "deploys_at": "#68BDF6",
    "communicates_with": "#A5ABB6",
    "has_metric": "#8DCC93",
    "has_flow_stat": "#FFC454",
    "emits_warning": "#F79767",
    "emits_log": "#B0B0B0",
    "includes": "#C990C0",
    "comm_formed": "#57C7E3",
    "comm_dissolved": "#F16667",
    "comm_down": "#DA7194",
    "deploy_lost": "#FF756E",
    "deploy_down": "#D9C8AE",
    "went_dark": "#4C8EDA",
    "warning_onset": "#F79767",
    "co_associated": "#569480",
    "associated_but_silent": "#604A0E",
}
SATELLITE_RELS = {
    "has_metric",
    "has_flow_stat",
    "emits_warning",
    "emits_log",
}


def load_id_map(path: Path) -> dict[int, str]:
    out: dict[int, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        out[int(parts[1])] = parts[0]
    return out


def entity_type(name: str) -> str:
    if name == "case":
        return "Case"
    if name == "gateway":
        return "Gateway"
    if name.startswith("AP_"):
        return "AP"
    if name.startswith("node_"):
        return "STA"
    if name.startswith("iperf_"):
        return "IperfMetric"
    if name.startswith("flow_"):
        return "FlowStat"
    if name.startswith("warning_code_"):
        return "Warning"
    if len(name) == 8 and all(c in "0123456789abcdefABCDEF" for c in name):
        return "LogTemplate"
    return "Other"


def display_label(name: str, etype: str) -> str:
    if etype == "STA" and name.startswith("node_"):
        return "STA " + name.split("_", 1)[1]
    if etype == "AP" and name.startswith("AP_"):
        return "AP " + name.split("_", 1)[1]
    if etype == "IperfMetric":
        return name.replace("iperf_", "")
    if etype == "FlowStat":
        return name.replace("flow_", "")
    if etype == "Warning" and name.startswith("warning_code_"):
        return "W" + name.split("_")[-1]
    if etype == "LogTemplate":
        return name[:6]
    return name


def parse_quads(test_txt: Path) -> list[tuple[int, int, int, str]]:
    quads = []
    for line in test_txt.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        p = line.split("\t")
        quads.append((int(p[0]), int(p[1]), int(p[2]), p[3]))
    return quads


def find_default_case(root: Path) -> Path:
    normal = root / "normal"
    if not normal.is_dir():
        normal = root / "Normal"
    if normal.is_dir():
        cases = sorted(p for p in normal.iterdir() if p.is_dir() and (p / "test.txt").exists())
        if cases:
            return cases[0]
    for p in sorted(root.rglob("test.txt")):
        if "_schema" in p.parts:
            continue
        return p.parent
    raise FileNotFoundError("no case test.txt under " + str(root))


def layout_positions(
    names: dict[int, str],
    types: dict[int, str],
    edges: list[tuple[int, str, int]],
) -> dict[int, tuple[float, float]]:
    cx, cy = 700.0, 540.0
    pos: dict[int, tuple[float, float]] = {}

    ap_of: dict[int, int] = {}
    parent: dict[int, int] = {}
    for s, rel, o in edges:
        if rel == "deploys_at" and types.get(s) == "STA" and types.get(o) == "AP":
            ap_of[s] = o
        if rel in SATELLITE_RELS and types.get(s) == "STA":
            parent[o] = s

    by_type: dict[str, list[int]] = defaultdict(list)
    for nid, t in types.items():
        by_type[t].append(nid)
    for t in by_type:
        by_type[t].sort(key=lambda i: names[i])

    if by_type["Case"]:
        pos[by_type["Case"][0]] = (cx, cy - 310)
    if by_type["Gateway"]:
        pos[by_type["Gateway"][0]] = (cx, cy + 290)

    aps = by_type["AP"]
    if len(aps) == 1:
        pos[aps[0]] = (cx, cy + 90)
    else:
        span = 260.0
        for i, ap in enumerate(aps):
            pos[ap] = (cx + (i - (len(aps) - 1) / 2.0) * span, cy + 90)

    groups: dict[int, list[int]] = defaultdict(list)
    orphan_stas: list[int] = []
    for sta in by_type["STA"]:
        if sta in ap_of:
            groups[ap_of[sta]].append(sta)
        else:
            orphan_stas.append(sta)
    if orphan_stas:
        groups[-1] = orphan_stas

    for ap, members in groups.items():
        ax, ay = pos.get(ap, (cx, cy))
        n = len(members)
        radius = 175.0 if n > 3 else 155.0
        for i, sta in enumerate(members):
            ang = -math.pi / 2.0 + (2.0 * math.pi * i / max(n, 1))
            pos[sta] = (ax + radius * math.cos(ang), ay + radius * math.sin(ang) - 20.0)

    kids: dict[int, list[int]] = defaultdict(list)
    for nid, sta in parent.items():
        kids[sta].append(nid)
    for sta, children in kids.items():
        sx, sy = pos.get(sta, (cx, cy))
        children.sort(key=lambda i: (types[i], names[i]))
        k = len(children)
        rsat = 52.0 + min(48.0, k * 1.8)
        for i, c in enumerate(children):
            ang = 2.0 * math.pi * i / max(k, 1) - math.pi / 2.0
            pos[c] = (sx + rsat * math.cos(ang), sy + rsat * math.sin(ang))

    leftover = [nid for nid in names if nid not in pos]
    leftover.sort(key=lambda i: names[i])
    for i, nid in enumerate(leftover):
        col = i % 8
        row = i // 8
        pos[nid] = (cx + 420.0 + col * 36.0, cy - 240.0 + row * 36.0)
    return pos


def pack_nodes(
    nids: list[int],
    names: dict[int, str],
    types: dict[int, str],
    pos: dict[int, tuple[float, float]],
    degrees: dict[int, int],
) -> list[dict]:
    nodes = []
    for nid in nids:
        et = types[nid]
        x, y = pos[nid]
        deg = degrees.get(nid, 1)
        r = NODE_RADIUS[et] + min(4.0, 0.35 * max(0, deg - 2))
        nodes.append(
            {
                "id": names[nid],
                "label": display_label(names[nid], et),
                "type": et,
                "x": x,
                "y": y,
                "r": r,
                "color": NODE_COLORS[et],
                "degree": deg,
            }
        )
    return nodes


def pack_edges(triples: list[tuple[int, str, int]], names: dict[int, str]) -> list[dict]:
    out = []
    seen = set()
    for s, rel, o in triples:
        key = (s, rel, o)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "source": names[s],
                "target": names[o],
                "relation": rel,
                "color": REL_COLORS.get(rel, "#A5ABB6"),
            }
        )
    return out


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>__TITLE__</title>
<style>
  html, body {
    margin: 0; padding: 0; height: 100%; width: 100%; overflow: hidden;
    font-family: "Times New Roman", Times, serif;
    background: #fff; color: #333;
  }
  .shell { display: flex; flex-direction: column; height: 100vh; width: 100vw; overflow: hidden; }
  .query-bar {
    flex: 0 0 auto; background: #f7f7f7; border-bottom: 1px solid #ddd;
    padding: 12px 20px; font-size: 16px; color: #555;
    font-family: "Times New Roman", Times, serif;
    display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px;
  }
  .kw { color: #018BFF; font-weight: 600; }
  .muted { color: #999; }
  select {
    font-family: inherit; font-size: 14px; padding: 3px 8px;
    border: 1px solid #ccc; border-radius: 6px; background: #fff; color: #333;
  }
  .legend-bar {
    flex: 0 0 auto; display: flex; flex-wrap: wrap; align-items: center; gap: 10px 16px;
    padding: 12px 20px; border-bottom: 1px solid #ececec; background: #fff; font-size: 15px;
  }
  .legend-section { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
  .legend-title {
    color: #8a8a8a; font-size: 13px; text-transform: uppercase;
    letter-spacing: 0.04em; font-weight: 600; margin-right: 4px;
  }
  .legend-item {
    display: inline-flex; align-items: center; gap: 8px;
    padding: 4px 11px 4px 7px; border-radius: 999px;
    background: #f4f4f4; border: 1px solid #e6e6e6;
  }
  .legend-item .dot { width: 16px; height: 16px; border-radius: 50%; border: 1px solid rgba(0,0,0,.06); }
  .legend-item .bar { width: 22px; height: 8px; border-radius: 2px; }
  .sep { width: 1px; height: 22px; background: #ddd; margin: 0 6px; }
  #graph {
    flex: 1 1 auto; min-height: 0; height: 0; width: 100%;
    position: relative; background: #ffffff; overflow: hidden;
  }
  #graph svg { width: 100%; height: 100%; display: block; cursor: grab; }
  #graph svg:active { cursor: grabbing; }
  .link { fill: none; stroke-opacity: 0.72; }
  .link-label {
    font-size: 11.5px; fill: #666; pointer-events: none;
    paint-order: stroke; stroke: #fff; stroke-width: 4.5px;
  }
  .node circle { stroke: rgba(0,0,0,0.12); stroke-width: 1.65px; cursor: pointer; }
  .node text {
    font-family: "Times New Roman", Times, serif;
    font-weight: 600; pointer-events: none; text-anchor: middle;
    dominant-baseline: central; fill: #1a1a1a;
  }
  .node.dimmed { opacity: 0.16; }
  .link.dimmed, .link-label.dimmed { opacity: 0.06; }
  .badge {
    position: absolute; z-index: 5; pointer-events: none;
    background: rgba(255,255,255,.95); border: 1px solid #e2e2e2;
    border-radius: 8px; padding: 8px 14px; font-size: 14px; color: #666;
  }
  .status { left: 16px; bottom: 16px; }
</style>
</head>
<body>
<div class="shell">
  <div class="query-bar">
    <span><span class="kw">MATCH</span> p=()--&gt;() <span class="kw">WHERE</span> case='__CASE__' <span class="kw">AND</span> t=</span>
    <select id="tsel"></select>
    <span><span class="kw">RETURN</span> p</span>
    <span class="muted" id="meta"></span>
  </div>
  <div class="legend-bar">
    <div class="legend-section"><span class="legend-title">Node labels</span>__NODE_LEGEND__</div>
    <div class="sep"></div>
    <div class="legend-section"><span class="legend-title">Relationship types</span>__REL_LEGEND__</div>
  </div>
  <div id="graph"><div class="badge status" id="status"></div></div>
</div>
<script src="vendor/d3.v7.min.js"></script>
<script>
(function () {
  var VISUAL_SCALE = 1.28;
  var LAYOUT_CX = 700;
  var LAYOUT_CY = 540;
  var payload = __PAYLOAD__;
  var snapshots = payload.snapshots;
  var times = payload.times;
  var defaultT = payload.default_t;

  var container = document.getElementById('graph');
  var statusEl = document.getElementById('status');
  var metaEl = document.getElementById('meta');
  var sel = document.getElementById('tsel');
  times.forEach(function (t) {
    var opt = document.createElement('option');
    opt.value = t; opt.textContent = t;
    if (t === defaultT) opt.selected = true;
    sel.appendChild(opt);
  });

  var width = container.clientWidth || 1200;
  var height = container.clientHeight || 800;
  var svg = d3.select('#graph').append('svg').attr('width', width).attr('height', height);
  var zoom = d3.zoom().scaleExtent([0.12, 6]);
  svg.call(zoom);
  var rootG = svg.append('g');
  zoom.on('zoom', function (event) { rootG.attr('transform', event.transform); });

  function wrapLabel(textSel, radius) {
    textSel.each(function (d) {
      var text = d3.select(this);
      var label = String(d.label);
      if (label.length <= 10 && label.indexOf(' ') < 0) {
        text.text(label);
        var fs = Math.min(15.5, Math.max(9.5, radius * 0.72));
        if (label.length >= 8) fs = Math.min(fs, 12);
        text.attr('font-size', fs);
        return;
      }
      text.text(null);
      var maxChars = Math.max(4, Math.floor(radius / 3.0));
      var lines = [];
      if (label.indexOf(' ') < 0) {
        var s = label;
        while (s.length > maxChars) { lines.push(s.slice(0, maxChars)); s = s.slice(maxChars); }
        if (s) lines.push(s);
      } else {
        var words = label.split(/\s+/), line = '';
        words.forEach(function (w) {
          if ((line + ' ' + w).trim().length <= maxChars) line = (line + ' ' + w).trim();
          else { if (line) lines.push(line); line = w; }
        });
        if (line) lines.push(line);
      }
      lines = lines.slice(0, 3);
      var fs = Math.min(14.0, Math.max(9.0, radius * 0.52));
      var lh = fs * 1.05;
      var start = -((lines.length - 1) * lh) / 2;
      lines.forEach(function (ln, i) {
        text.append('tspan').attr('x', 0).attr('y', start + i * lh).attr('dy', '0.35em').text(ln);
      });
      text.attr('font-size', fs);
    });
  }

  function render(t) {
    var data = snapshots[t];
    data.nodes.forEach(function (n) {
      n.r = n._r0 * VISUAL_SCALE;
      n.x = (n._x0 - LAYOUT_CX) * VISUAL_SCALE + LAYOUT_CX;
      n.y = (n._y0 - LAYOUT_CY) * VISUAL_SCALE + LAYOUT_CY;
    });
    rootG.selectAll('*').remove();
    var defs = rootG.append('defs');
    var colors = Array.from(new Set(data.edges.map(function (e) { return e.color; })));
    colors.forEach(function (c, i) {
      defs.append('marker')
        .attr('id', 'arrow-' + i)
        .attr('viewBox', '0 -4 8 8')
        .attr('refX', 10).attr('refY', 0)
        .attr('markerWidth', 7).attr('markerHeight', 7)
        .attr('orient', 'auto')
        .append('path').attr('d', 'M0,-4.5L10,0L0,4.5').attr('fill', c);
    });
    var colorToMarker = {};
    colors.forEach(function (c, i) { colorToMarker[c] = 'url(#arrow-' + i + ')'; });

    var g = rootG.append('g');
    var nodeById = {};
    data.nodes.forEach(function (n) { nodeById[n.id] = n; });

    var link = g.append('g').selectAll('path')
      .data(data.edges).enter().append('path')
      .attr('class', 'link')
      .attr('stroke', function (d) { return d.color; })
      .attr('stroke-width', 1.65)
      .attr('marker-end', function (d) { return colorToMarker[d.color]; });

    var linkLabel = g.append('g').selectAll('text')
      .data(data.edges).enter().append('text')
      .attr('class', 'link-label')
      .text(function (d) { return d.relation; });

    var node = g.append('g').selectAll('g')
      .data(data.nodes).enter().append('g')
      .attr('class', 'node')
      .attr('transform', function (d) { return 'translate(' + d.x + ',' + d.y + ')'; });

    node.append('circle')
      .attr('r', function (d) { return d.r; })
      .attr('fill', function (d) { return d.color; });
    node.append('text').each(function (d) { wrapLabel(d3.select(this), d.r); });

    function edgeGeom(d) {
      var s = nodeById[d.source], tgt = nodeById[d.target];
      var dx = tgt.x - s.x, dy = tgt.y - s.y;
      var dist = Math.hypot(dx, dy) || 1;
      var x1 = s.x + dx / dist * s.r;
      var y1 = s.y + dy / dist * s.r;
      var x2 = tgt.x - dx / dist * (tgt.r + 6);
      var y2 = tgt.y - dy / dist * (tgt.r + 6);
      var mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
      var nx = -dy / dist, ny = dx / dist;
      var curve = Math.min(11, dist * 0.03);
      return {
        x1: x1, y1: y1, x2: x2, y2: y2,
        cx: mx + nx * curve, cy: my + ny * curve,
        mx: mx + nx * curve * 0.5, my: my + ny * curve * 0.5
      };
    }
    function drawEdges() {
      link.attr('d', function (d) {
        var eg = edgeGeom(d);
        return 'M' + eg.x1 + ',' + eg.y1 + ' Q' + eg.cx + ',' + eg.cy + ' ' + eg.x2 + ',' + eg.y2;
      });
      linkLabel
        .attr('x', function (d) { return edgeGeom(d).mx; })
        .attr('y', function (d) { return edgeGeom(d).my; });
    }
    drawEdges();

    var xExtent = d3.extent(data.nodes, function (d) { return d.x; });
    var yExtent = d3.extent(data.nodes, function (d) { return d.y; });
    var bw = (xExtent[1] - xExtent[0]) + 80;
    var bh = (yExtent[1] - yExtent[0]) + 80;
    var sc = Math.min(width / bw, height / bh) * 0.88;
    var tx = width / 2 - sc * (xExtent[0] + xExtent[1]) / 2;
    var ty = height / 2 - sc * (yExtent[0] + yExtent[1]) / 2;
    svg.call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(sc));

    var linked = {};
    data.edges.forEach(function (e) {
      linked[e.source] = linked[e.source] || new Set();
      linked[e.target] = linked[e.target] || new Set();
      linked[e.source].add(e.target);
      linked[e.target].add(e.source);
    });
    node.on('click', function (event, d) {
      event.stopPropagation();
      var keep = new Set([d.id]);
      (linked[d.id] || new Set()).forEach(function (x) { keep.add(x); });
      node.classed('dimmed', function (n) { return !keep.has(n.id); });
      link.classed('dimmed', function (e) { return !(e.source === d.id || e.target === d.id); });
      linkLabel.classed('dimmed', function (e) { return !(e.source === d.id || e.target === d.id); });
    });
    svg.on('click', function () {
      node.classed('dimmed', false);
      link.classed('dimmed', false);
      linkLabel.classed('dimmed', false);
    });
    node.call(d3.drag().on('drag', function (event, d) {
      d.x = event.x; d.y = event.y;
      d3.select(this).attr('transform', 'translate(' + d.x + ',' + d.y + ')');
      drawEdges();
    }));

    statusEl.textContent = payload.dataset + ' · ' + payload.case_name + ' · t=' + t
      + ' · ' + data.nodes.length + ' nodes · ' + data.edges.length + ' edges';
    metaEl.textContent = '// ' + data.nodes.length + ' nodes, ' + data.edges.length + ' rels';
  }

  snapshots[defaultT].nodes.forEach(function freeze(n) { n._x0 = n.x; n._y0 = n.y; n._r0 = n.r; });
  times.forEach(function (t) {
    snapshots[t].nodes.forEach(function (n) { n._x0 = n.x; n._y0 = n.y; n._r0 = n.r; });
  });
  render(defaultT);
  sel.addEventListener('change', function () { render(sel.value); });
  window.addEventListener('resize', function () {
    width = container.clientWidth; height = container.clientHeight;
    svg.attr('width', width).attr('height', height);
    render(sel.value);
  });
})();
</script>
</body>
</html>
"""


def legend_nodes_html(types_present: list[str]) -> str:
    bits = []
    for t in types_present:
        bits.append(
            f'<span class="legend-item"><span class="dot" style="background:{NODE_COLORS[t]}"></span>{t}</span>'
        )
    return "".join(bits)


def legend_rels_html(rels_present: list[str]) -> str:
    bits = []
    for r in rels_present:
        c = REL_COLORS.get(r, "#A5ABB6")
        bits.append(
            f'<span class="legend-item"><span class="bar" style="background:{c}"></span>{r}</span>'
        )
    return "".join(bits)


def pick_default_t(by_t: dict[str, list[tuple[int, str, int]]]) -> str:
    best_t = None
    best = (-1, -1)
    for t, edges in by_t.items():
        nrel = len({e[1] for e in edges})
        score = (nrel, len(edges))
        if score > best:
            best = score
            best_t = t
    return best_t


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="TKG scene root, e.g. ...\\WITNESS_TKG_t_Ab1N\\h2h")
    ap.add_argument("--case", default="", help="case directory name; default first Normal case")
    ap.add_argument("--out", required=True, help="output HTML path")
    ap.add_argument("--title", default="")
    ap.add_argument(
        "--mode",
        choices=("timeline", "union", "both"),
        default="both",
        help="timeline: one snapshot per t; union: unique (s,r,o) over the case (paper view)",
    )
    args = ap.parse_args()

    root = Path(args.root)
    schema = root / "_schema"
    ent = load_id_map(schema / "entity2id.txt")
    rel = load_id_map(schema / "relation2id.txt")

    if args.case:
        case_dir = Path(args.case)
        if not case_dir.is_absolute():
            cand = root / "normal" / args.case
            if not cand.exists():
                cand = root / args.case
            case_dir = cand
    else:
        case_dir = find_default_case(root)

    quads = parse_quads(case_dir / "test.txt")
    by_t: dict[str, list[tuple[int, str, int]]] = defaultdict(list)
    union_edges: list[tuple[int, str, int]] = []
    used_ids: set[int] = set()
    for s, r, o, t in quads:
        rn = rel[r]
        by_t[t].append((s, rn, o))
        union_edges.append((s, rn, o))
        used_ids.add(s)
        used_ids.add(o)

    names = {i: ent[i] for i in used_ids}
    types = {i: entity_type(ent[i]) for i in used_ids}
    pos = layout_positions(names, types, union_edges)

    times = sorted(by_t.keys(), key=lambda x: int(x) if str(x).lstrip("-").isdigit() else x)
    default_t = pick_default_t(by_t)

    snapshots = {}
    all_types: set[str] = set()
    all_rels: set[str] = set()
    for t in times:
        edges = by_t[t]
        nids = sorted({s for s, _, _ in edges} | {o for _, _, o in edges})
        deg: dict[int, int] = Counter()
        for s, _, o in edges:
            deg[s] += 1
            deg[o] += 1
        nodes = pack_nodes(nids, names, types, pos, deg)
        elist = pack_edges(edges, names)
        snapshots[t] = {"nodes": nodes, "edges": elist}
        all_types.update(types[i] for i in nids)
        all_rels.update(e[1] for e in edges)

    type_order = [
        "Case",
        "STA",
        "AP",
        "Gateway",
        "IperfMetric",
        "FlowStat",
        "Warning",
        "LogTemplate",
        "Other",
    ]
    rel_order = list(REL_COLORS.keys())
    types_present = [t for t in type_order if t in all_types]
    rels_present = [r for r in rel_order if r in all_rels]

    def write_html(out_path: Path, times_list, default, snaps, case_label: str, title: str) -> None:
        payload = {
            "dataset": root.parent.name + "/" + root.name,
            "case_name": case_dir.name,
            "times": times_list,
            "default_t": default,
            "snapshots": snaps,
        }
        html = (
            HTML_TEMPLATE.replace("__TITLE__", title)
            .replace("__CASE__", case_label)
            .replace("__NODE_LEGEND__", legend_nodes_html(types_present))
            .replace("__REL_LEGEND__", legend_rels_html(rels_present))
            .replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html, encoding="utf-8")
        print("wrote", out_path)

    out = Path(args.out)
    title_base = args.title or f"WITNESS TKG · {root.parent.name}/{root.name} · {case_dir.name}"
    if args.mode in ("timeline", "both"):
        write_html(
            out,
            times,
            default_t,
            snapshots,
            case_dir.name,
            title_base,
        )
    if args.mode in ("union", "both"):
        nids = sorted(used_ids)
        deg: dict[int, int] = Counter()
        for s, _, o in union_edges:
            deg[s] += 1
            deg[o] += 1
        union_nodes = pack_nodes(nids, names, types, pos, deg)
        union_elist = pack_edges(union_edges, names)
        union_snaps = {"union": {"nodes": union_nodes, "edges": union_elist}}
        union_out = out
        if args.mode == "both":
            union_out = out.with_name(out.stem + "_union" + out.suffix)
        write_html(
            union_out,
            ["union"],
            "union",
            union_snaps,
            case_dir.name + " UNION",
            title_base + " (unique triples)",
        )
        print("union unique nodes", len(union_nodes), "edges", len(union_elist))
    print("case", case_dir)
    print("times", len(times), "default_t", default_t)
    print("raw_quads", len(union_edges), "union_nodes", len(used_ids))
    snap = snapshots[default_t]
    print("default snapshot nodes", len(snap["nodes"]), "edges", len(snap["edges"]))
    print("types", types_present)
    print("rels", rels_present)


if __name__ == "__main__":
    main()
