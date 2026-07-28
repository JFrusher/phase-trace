/* Pitch heatmap: Gaussian KDE of any located events over the pitch.

   Method: bin points into a 1m metre-grid (covering in-goal too), separable
   Gaussian-blur the grid (reusing momentum.gaussianBlur1d), normalize, colour
   each cell, and overlay the small grid as one <image> the SVG scales smoothly.

   Colour follows dataviz: single-team = one sequential hue (that team's colour,
   alpha ramped so the pitch shows through cool zones); differential = diverging
   home(red) <- transparent -> away(blue), neutral/transparent midpoint. */
(function (MR) {
  "use strict";

  // grid covers the full pitch including both in-goals: x -10..110m, y 0..70m,
  // 1 cell per metre. x origin is the back of the left in-goal (-10m).
  var X0 = -10, GW = 120, GH = 70;
  var LINE_TYPES = { carry: 1, pass: 1, kick: 1 };

  function hexRgb(h) {
    return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
  }
  function mix(a, b, t) { return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]; }

  function col(xm) { var c = Math.floor(xm - X0); return c < 0 ? 0 : c >= GW ? GW - 1 : c; }
  function row(ym) { var r = Math.floor(ym); return r < 0 ? 0 : r >= GH ? GH - 1 : r; }

  function blankGrid() {
    var g = new Array(GH);
    for (var r = 0; r < GH; r++) g[r] = new Array(GW).fill(0);
    return g;
  }

  // Which located points a metric contributes. Lines are sampled along their
  // whole path (1 sample/metre); discrete events are a single point.
  var METRICS = {
    all: { label: "All actions", line: function (a) { return LINE_TYPES[a.type]; } },
    carry: { label: "Carries", line: function (a) { return a.type === "carry"; } },
    pass: { label: "Passes", line: function (a) { return a.type === "pass"; } },
    kick: { label: "Kicks", line: function (a) { return a.type === "kick"; } },
    linebreak: { label: "Linebreaks", line: function (a) { return LINE_TYPES[a.type] && a.linebreak; } },
    try: { label: "Tries", point: function (a) { return a.type === "try"; } },
    penalty_won: { label: "Penalties won", point: function (a) { return a.type === "penalty_won"; } },
    // attributed to the side that GAVE IT AWAY, so a team's map is its own
    // discipline — where it was penalised. Needs conceded_by from the export.
    penalties_conceded: { label: "Penalties conceded", teamField: "conceded_by",
      point: function (a) { return a.type === "penalty_won" && a.conceded_by != null; } },
    turnover_won: { label: "Turnovers", point: function (a) { return a.type === "turnover_won"; } },
    error: { label: "Errors", point: function (a) { return a.type === "error"; } },
    card: { label: "Cards", point: function (a) { return a.type === "sin_bin" || a.type === "red_card"; } },
    set_piece: { label: "Set pieces", point: function (a) { return a.type === "set_piece"; } }
  };
  var METRIC_ORDER = ["all", "carry", "pass", "kick", "linebreak", "try",
    "penalty_won", "penalties_conceded", "turnover_won", "error", "card", "set_piece"];

  function hasStart(a) { return Number.isFinite(a.x_m != null ? a.x_m : a.start_x_m) && Number.isFinite(a.y_m != null ? a.y_m : a.start_y_m); }
  function ptX(a) { return a.x_m != null ? a.x_m : a.start_x_m; }
  function ptY(a) { return a.y_m != null ? a.y_m : a.start_y_m; }

  // accumulate one metric's points for one team-filter into a grid
  function accumulate(grid, actions, metric, teamName) {
    var m = METRICS[metric], tf = m.teamField || "team";
    actions.forEach(function (a) {
      if (teamName && a[tf] !== teamName) return;
      if (m.line && m.line(a)) {
        if (!(Number.isFinite(a.start_x_m) && Number.isFinite(a.end_x_m))) return;
        var len = Math.hypot(a.end_x_m - a.start_x_m, a.end_y_m - a.start_y_m);
        var n = Math.max(2, Math.round(len));           // ~1 sample per metre
        for (var i = 0; i < n; i++) {
          var f = i / (n - 1);
          grid[row(a.start_y_m + (a.end_y_m - a.start_y_m) * f)][col(a.start_x_m + (a.end_x_m - a.start_x_m) * f)] += 1;
        }
      } else if (m.point && m.point(a) && hasStart(a)) {
        grid[row(ptY(a))][col(ptX(a))] += 1;
      }
    });
  }

  // requirePos=false counts matching events even without a position, so a
  // metric whose events exist but were exported before position capture is
  // still offered (with a "re-export" note) rather than silently hidden.
  function count(actions, metric, teamName, requirePos) {
    if (requirePos === undefined) requirePos = true;
    var m = METRICS[metric], tf = m.teamField || "team", n = 0;
    actions.forEach(function (a) {
      if (teamName && a[tf] !== teamName) return;
      if (m.line && m.line(a) && Number.isFinite(a.start_x_m)) n++;
      else if (m.point && m.point(a) && (!requirePos || hasStart(a))) n++;
    });
    return n;
  }

  function blur2d(grid, sigma) {
    var r, c;
    for (r = 0; r < GH; r++) grid[r] = MR.momentum.gaussianBlur1d(grid[r], sigma);
    for (c = 0; c < GW; c++) {
      var colArr = new Array(GH);
      for (r = 0; r < GH; r++) colArr[r] = grid[r][c];
      colArr = MR.momentum.gaussianBlur1d(colArr, sigma);
      for (r = 0; r < GH; r++) grid[r][c] = colArr[r];
    }
    return grid;
  }

  var WHITE = [255, 255, 255];
  function paint(canvas, field, peak, mode, colors) {
    var ctx = canvas.getContext("2d");
    var img = ctx.createImageData(GW, GH);
    var homeRgb = hexRgb(colors.home), awayRgb = hexRgb(colors.away);
    var neutral = hexRgb("#f57c00"); // "both" single-mode heat hue
    for (var r = 0; r < GH; r++) {
      for (var c = 0; c < GW; c++) {
        var v = field[r][c], rgb, a;
        if (mode === "diff") {
          var mag = Math.min(1, Math.abs(v) / (peak || 1));
          rgb = v >= 0 ? homeRgb : awayRgb;
          a = Math.pow(mag, 0.6) * 0.85;
        } else {
          var val = Math.min(1, v / (peak || 1));
          rgb = mode === "home" ? homeRgb : mode === "away" ? awayRgb : neutral;
          a = Math.pow(val, 0.65) * 0.85;
        }
        rgb = mix(rgb, WHITE, 0.18 * (a / 0.85)); // brighten the hot core a touch
        var idx = (r * GW + c) * 4;
        img.data[idx] = rgb[0]; img.data[idx + 1] = rgb[1]; img.data[idx + 2] = rgb[2];
        img.data[idx + 3] = Math.round(a * 255);
      }
    }
    ctx.putImageData(img, 0, 0);
    return canvas.toDataURL();
  }

  // Build the heatmap image (data URL) for current settings, or null if no data.
  function build(model, opts) {
    var canvas = document.createElement("canvas");
    canvas.width = GW; canvas.height = GH;
    var sigma = opts.bandwidth;
    if (opts.mode === "diff") {
      var gh = blur2d(blankGrid_accum(model, opts.metric, model.home), sigma);
      var ga = blur2d(blankGrid_accum(model, opts.metric, model.away), sigma);
      var field = blankGrid(), peak = 0;
      for (var r = 0; r < GH; r++) for (var c = 0; c < GW; c++) {
        field[r][c] = gh[r][c] - ga[r][c];
        if (Math.abs(field[r][c]) > peak) peak = Math.abs(field[r][c]);
      }
      if (peak === 0) return null;
      return paint(canvas, field, peak, "diff", model.colors);
    }
    var teamName = opts.team === "home" ? model.home : opts.team === "away" ? model.away : null;
    var grid = blur2d(blankGrid_accum(model, opts.metric, teamName), sigma);
    var pk = 0;
    for (var rr = 0; rr < GH; rr++) for (var cc = 0; cc < GW; cc++) if (grid[rr][cc] > pk) pk = grid[rr][cc];
    if (pk === 0) return null;
    return paint(canvas, grid, pk, opts.team, model.colors);
  }
  function blankGrid_accum(model, metric, teamName) {
    var g = blankGrid();
    accumulate(g, model.actions, metric, teamName);
    return g;
  }

  // available metrics = those whose events exist at all (positioned or not), so
  // a metric is never silently missing; the view notes when none are located.
  function availableMetrics(model) {
    return METRIC_ORDER.filter(function (k) {
      return count(model.actions, k, null, false) > 0;
    });
  }

  MR.heatmap = {
    METRICS: METRICS,
    availableMetrics: availableMetrics,
    build: build,
    count: count
  };
})(window.MR = window.MR || {});
