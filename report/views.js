/* Views: match header, pitch action map (+filters), team comparison, player
   table, momentum chart. Reads only the normalized model from ingest.js. */
(function (MR) {
  "use strict";

  var POINTS = { try: 5, conversion: 2, penalty_kick: 3, drop_goal: 3, penalty_try: 7 };

  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function fmt(v) {
    if (v == null || v === "") return "0";
    return (typeof v === "number" && v % 1 !== 0) ? v.toFixed(1) : String(v);
  }
  function el(html) { var d = document.createElement("div"); d.innerHTML = html.trim(); return d.firstChild; }

  function score(model, side) {
    var stats = model.sideStats[side];
    if (stats && Number.isFinite(stats.points)) return stats.points;
    var name = model[side], pts = 0;
    model.actions.forEach(function (a) { if (a.team === name && POINTS[a.type]) pts += POINTS[a.type]; });
    return pts;
  }

  function matchHeader(model) {
    var meta = model.meta || {};
    var sub = [meta.competition, meta.date].filter(Boolean).join(" · ") ||
      (model.source === "csv" ? "from CSV export" : "from match.json");
    return '<div class="match-head">' +
      '<div class="teams">' +
        '<span class="chip" style="background:' + model.colors.home + '">' + esc(model.home) + '</span>' +
        '<span class="score">' + score(model, "home") + '</span>' +
        '<span class="dash">–</span>' +
        '<span class="score">' + score(model, "away") + '</span>' +
        '<span class="chip" style="background:' + model.colors.away + '">' + esc(model.away) + '</span>' +
      '</div>' +
      '<div class="sub">' + esc(sub) + '</div></div>';
  }

  // --- pitch view -----------------------------------------------------------
  function pitchView(model) {
    var wrap = el('<section class="view" data-view="pitch">' +
      '<div class="filters">' +
        '<span class="flabel">Teams</span>' +
        '<label class="tog"><input type="checkbox" data-team="home" checked> ' + esc(model.home) + '</label>' +
        '<label class="tog"><input type="checkbox" data-team="away" checked> ' + esc(model.away) + '</label>' +
        '<span class="flabel">Actions</span>' +
        '<label class="tog"><input type="checkbox" data-type="carry" checked><span class="sw" style="background:#ffd54f"></span>carry</label>' +
        '<label class="tog"><input type="checkbox" data-type="pass" checked><span class="sw" style="background:#64b5f6"></span>pass</label>' +
        '<label class="tog"><input type="checkbox" data-type="kick" checked><span class="sw" style="background:#ef5350"></span>kick</label>' +
      '</div>' +
      '<div class="pitch-holder"></div></section>');

    var state = { teams: { home: true, away: true }, types: { carry: true, pass: true, kick: true } };
    var holder = wrap.querySelector(".pitch-holder");
    function draw() {
      holder.innerHTML = MR.pitch.svg(model.actions, model, function (a) {
        var side = a.team === model.home ? "home" : "away";
        return state.teams[side] && state.types[a.type];
      });
    }
    wrap.querySelectorAll("input[data-team]").forEach(function (cb) {
      cb.addEventListener("change", function () { state.teams[cb.getAttribute("data-team")] = cb.checked; draw(); });
    });
    wrap.querySelectorAll("input[data-type]").forEach(function (cb) {
      cb.addEventListener("change", function () { state.types[cb.getAttribute("data-type")] = cb.checked; draw(); });
    });
    draw();
    return wrap;
  }

  // --- team comparison ------------------------------------------------------
  var CMP_ROWS = [
    ["points", "Points"], ["tries", "Tries"], ["possessions", "Possessions"],
    ["metres", "Metres"], ["carries", "Carries"], ["carry_metres", "Carry metres"],
    ["kicks", "Kicks"], ["kick_metres", "Kick metres"], ["linebreaks", "Linebreaks"],
    ["turnovers_won", "Turnovers won"], ["penalties_won", "Penalties won"],
    ["penalties_conceded", "Penalties conceded"], ["errors", "Errors"],
    ["sin_bins", "Sin bins"], ["red_cards", "Red cards"]
  ];
  function teamView(model) {
    var h = model.sideStats.home, a = model.sideStats.away;
    if (!h || !a) {
      return el('<section class="view" data-view="team"><p class="empty">No team summary in this export.</p></section>');
    }
    var rows = CMP_ROWS.map(function (r) {
      var key = r[0], hv = Number(h[key]) || 0, av = Number(a[key]) || 0;
      var mx = Math.max(hv, av) || 1;
      return '<div class="cmp-row">' +
        '<span class="cmp-val">' + fmt(hv) + '</span>' +
        '<div class="cmp-bars">' +
          '<div class="cmp-bar left"><span style="width:' + (hv / mx * 100) + '%;background:' + model.colors.home + '"></span></div>' +
          '<div class="cmp-label">' + esc(r[1]) + '</div>' +
          '<div class="cmp-bar right"><span style="width:' + (av / mx * 100) + '%;background:' + model.colors.away + '"></span></div>' +
        '</div>' +
        '<span class="cmp-val">' + fmt(av) + '</span></div>';
    }).join("");
    // penalty reasons breakdown, if present
    var reasons = breakdownLine("Penalty reasons", h.penalty_reasons, a.penalty_reasons);
    var errkinds = breakdownLine("Error kinds", h.error_kinds, a.error_kinds);
    return el('<section class="view" data-view="team"><div class="cmp">' + rows + '</div>' +
      reasons + errkinds + '</section>');
  }
  function breakdownLine(title, hObj, aObj) {
    function one(o) {
      if (!o || !Object.keys(o).length) return "—";
      return Object.keys(o).map(function (k) { return esc(k) + " " + esc(o[k]); }).join(", ");
    }
    if ((!hObj || !Object.keys(hObj).length) && (!aObj || !Object.keys(aObj).length)) return "";
    return '<div class="breakdown"><span>' + one(hObj) + '</span><b>' + esc(title) +
      '</b><span>' + one(aObj) + '</span></div>';
  }

  // --- player table ---------------------------------------------------------
  var PLAYER_COLS = [
    ["team", "Team"], ["number", "#"], ["carries", "Carries"], ["carry_metres", "Carry m"],
    ["linebreaks", "LB"], ["kicks", "Kicks"], ["kick_metres", "Kick m"], ["tries", "Tries"], ["assists", "Assists"]
  ];
  function playerView(model) {
    if (!model.players || !model.players.length) {
      return el('<section class="view" data-view="players"><p class="empty">' +
        'No per-player data in this export — jersey numbers were not tagged during capture.</p></section>');
    }
    var sortKey = "carry_metres", sortDir = -1;
    var wrap = el('<section class="view" data-view="players"><table class="ptable"><thead></thead><tbody></tbody></table></section>');
    var thead = wrap.querySelector("thead"), tbody = wrap.querySelector("tbody");
    thead.innerHTML = "<tr>" + PLAYER_COLS.map(function (c) {
      return '<th data-key="' + c[0] + '">' + esc(c[1]) + '</th>';
    }).join("") + "</tr>";
    function render() {
      var rows = model.players.slice().sort(function (x, y) {
        var xv = x[sortKey], yv = y[sortKey];
        if (typeof xv === "string" || typeof yv === "string") return String(xv).localeCompare(String(yv)) * sortDir;
        return ((Number(xv) || 0) - (Number(yv) || 0)) * sortDir;
      });
      tbody.innerHTML = rows.map(function (p) {
        return "<tr>" + PLAYER_COLS.map(function (c) { return "<td>" + esc(fmt(p[c[0]])) + "</td>"; }).join("") + "</tr>";
      }).join("");
      thead.querySelectorAll("th").forEach(function (th) {
        th.classList.toggle("sorted", th.getAttribute("data-key") === sortKey);
      });
    }
    thead.querySelectorAll("th").forEach(function (th) {
      th.addEventListener("click", function () {
        var k = th.getAttribute("data-key");
        if (k === sortKey) sortDir = -sortDir; else { sortKey = k; sortDir = -1; }
        render();
      });
    });
    render();
    return wrap;
  }

  // --- momentum chart -------------------------------------------------------
  function momentumView(model) {
    var m = MR.momentum.build(model.actions, model.home, model.away);
    if (!m.usable) {
      return el('<section class="view" data-view="momentum"><p class="empty">' + esc(m.reason) + '</p></section>');
    }
    var W = 900, H = 300, mid = H / 2, halfH = mid - 24, N = m.t.length;
    function px(i) { return (i / (N - 1)) * W; }
    var homePts = "0," + mid, awayPts = "0," + mid, i;
    for (i = 0; i < N; i++) homePts += " " + px(i).toFixed(1) + "," + (mid - m.home[i] * halfH).toFixed(1);
    homePts += " " + W + "," + mid;
    for (i = 0; i < N; i++) awayPts += " " + px(i).toFixed(1) + "," + (mid + m.away[i] * halfH).toFixed(1);
    awayPts += " " + W + "," + mid;

    var markers = "";
    m.markers.forEach(function (mk) {
      if (mk.kind !== "score") return;
      var x = px((mk.t / m.maxT) * (N - 1));
      var up = mk.team === model.home;
      markers += '<line x1="' + x.toFixed(1) + '" y1="' + mid + '" x2="' + x.toFixed(1) + '" y2="' +
        (up ? mid - halfH : mid + halfH) + '" stroke="' + (up ? model.colors.home : model.colors.away) +
        '" stroke-width="1.5" stroke-dasharray="3,3" opacity="0.8" />' +
        '<circle cx="' + x.toFixed(1) + '" cy="' + (up ? mid - halfH : mid + halfH) + '" r="3" fill="#f5c518" />';
    });

    var axis = "";
    if (m.timebase === "minute") {
      [0, 20, 40, 60, 80].forEach(function (min) {
        if (min > m.maxT) return;
        var x = (min / m.maxT) * W;
        axis += '<text x="' + x.toFixed(1) + '" y="' + (H - 4) + '" class="ax">' + (min === 40 ? "HT" : min + "'") + "</text>";
      });
    }
    var note = m.timebase === "sequence"
      ? "sequence, not time — clock wasn't started in this export"
      : "match minute";
    var svg = '<svg viewBox="0 0 ' + W + " " + H + '" class="mom-svg" preserveAspectRatio="none">' +
      '<line x1="0" y1="' + mid + '" x2="' + W + '" y2="' + mid + '" stroke="#c8c8c8" stroke-width="1" />' +
      '<polygon points="' + homePts + '" fill="' + model.colors.home + '" opacity="0.85" />' +
      '<polygon points="' + awayPts + '" fill="' + model.colors.away + '" opacity="0.85" />' +
      markers + axis + '</svg>';
    return el('<section class="view" data-view="momentum">' + svg +
      '<p class="mom-note"><b>' + esc(model.home) + '</b> above · <b>' + esc(model.away) + '</b> below · x-axis: ' +
      esc(note) + '. Reconstructed from the action stream (approximate).</p></section>');
  }

  // --- heatmap --------------------------------------------------------------
  function rgba(hex, a) {
    return "rgba(" + parseInt(hex.slice(1, 3), 16) + "," + parseInt(hex.slice(3, 5), 16) +
      "," + parseInt(hex.slice(5, 7), 16) + "," + a + ")";
  }
  function heatmapView(model) {
    var metrics = MR.heatmap.availableMetrics(model);
    if (!metrics.length) {
      return el('<section class="view" data-view="heatmap"><p class="empty">No located events to map.</p></section>');
    }
    var W = MR.pitch.IMAGE_W, H = MR.pitch.IMAGE_H;
    var state = { mode: "single", team: "both", metric: metrics[0], bandwidth: 4 };

    var metricOpts = metrics.map(function (k) {
      return '<option value="' + k + '">' + esc(MR.heatmap.METRICS[k].label) + "</option>";
    }).join("");
    var wrap = el('<section class="view" data-view="heatmap">' +
      '<div class="filters hm-controls">' +
        '<span class="flabel">Mode</span>' +
        '<div class="seg" data-group="mode">' +
          '<button data-mode="single" class="on">Single</button>' +
          '<button data-mode="diff">Differential</button></div>' +
        '<span class="flabel">Metric</span><select class="hm-metric">' + metricOpts + '</select>' +
        '<span class="flabel hm-teamlbl">Team</span>' +
        '<div class="seg hm-team" data-group="team">' +
          '<button data-team="home">' + esc(model.home) + '</button>' +
          '<button data-team="away">' + esc(model.away) + '</button>' +
          '<button data-team="both" class="on">Both</button></div>' +
        '<span class="flabel">Blur</span>' +
        '<input type="range" class="hm-band" min="1" max="12" step="1" value="4">' +
        '<span class="hm-bandval">4m</span>' +
      '</div>' +
      '<div class="pitch-holder"></div>' +
      '<div class="hm-legend"></div></section>');

    var holder = wrap.querySelector(".pitch-holder");
    var legendEl = wrap.querySelector(".hm-legend");
    var teamCtl = wrap.querySelector(".hm-team");
    var teamLbl = wrap.querySelector(".hm-teamlbl");

    function legend() {
      if (state.mode === "diff") {
        return '<div class="lg-bar" style="background:linear-gradient(90deg,' +
          rgba(model.colors.away, 0.85) + ',rgba(255,255,255,0) 50%,' + rgba(model.colors.home, 0.85) + ')"></div>' +
          '<div class="lg-ends"><span>' + esc(model.away) + '</span><span>even</span><span>' + esc(model.home) + '</span></div>';
      }
      var hue = state.team === "home" ? model.colors.home : state.team === "away" ? model.colors.away : "#f57c00";
      return '<div class="lg-bar" style="background:linear-gradient(90deg,rgba(255,255,255,0),' + rgba(hue, 0.85) + ')"></div>' +
        '<div class="lg-ends"><span>low</span><span>' + esc(MR.heatmap.METRICS[state.metric].label) + ' density</span><span>high</span></div>';
    }

    function draw() {
      var url = MR.heatmap.build(model, { mode: state.mode, team: state.team,
        metric: state.metric, bandwidth: state.bandwidth });
      var bg = MR.pitch.background(model.colors, { home: model.home, away: model.away }, model.attackDirHome);
      var overlay = url ? '<image href="' + url + '" x="0" y="0" width="' + W + '" height="' + H +
        '" style="image-rendering:auto" />' : "";
      var note = "";
      if (!url) {
        var total = MR.heatmap.count(model.actions, state.metric, null, false);
        var located = MR.heatmap.count(model.actions, state.metric, null, true);
        note = (total > 0 && located === 0)
          ? total + " " + MR.heatmap.METRICS[state.metric].label.toLowerCase() +
            " in this match, but none carry a pitch position — re-export with the updated tracer to map them."
          : "No located points for this selection.";
      }
      holder.innerHTML = '<svg viewBox="0 0 ' + W + " " + H + '" class="pitch-svg" preserveAspectRatio="xMidYMid meet">' +
        bg + overlay + "</svg>" +
        (url ? "" : '<p class="hm-none">' + esc(note) + "</p>");
      legendEl.innerHTML = legend();
      teamCtl.classList.toggle("hidden", state.mode === "diff");
      teamLbl.classList.toggle("hidden", state.mode === "diff");
    }

    wrap.querySelectorAll('[data-group="mode"] button').forEach(function (b) {
      b.addEventListener("click", function () {
        state.mode = b.getAttribute("data-mode");
        wrap.querySelectorAll('[data-group="mode"] button').forEach(function (x) { x.classList.toggle("on", x === b); });
        draw();
      });
    });
    wrap.querySelectorAll('[data-group="team"] button').forEach(function (b) {
      b.addEventListener("click", function () {
        state.team = b.getAttribute("data-team");
        wrap.querySelectorAll('[data-group="team"] button').forEach(function (x) { x.classList.toggle("on", x === b); });
        draw();
      });
    });
    wrap.querySelector(".hm-metric").addEventListener("change", function (e) { state.metric = e.target.value; draw(); });
    wrap.querySelector(".hm-band").addEventListener("input", function (e) {
      state.bandwidth = Number(e.target.value);
      wrap.querySelector(".hm-bandval").textContent = state.bandwidth + "m";
      draw();
    });
    draw();
    return wrap;
  }

  // --- orchestration --------------------------------------------------------
  var TABS = [["pitch", "Pitch map"], ["heatmap", "Heatmap"], ["team", "Team"], ["players", "Players"], ["momentum", "Momentum"]];
  function render(model, root) {
    root.innerHTML = "";
    root.appendChild(el(matchHeader(model)));
    if (model.warnings && model.warnings.length) {
      root.appendChild(el('<div class="warn">⚠ ' + model.warnings.map(esc).join("<br>⚠ ") + "</div>"));
    }
    var nav = el('<nav class="tabs">' + TABS.map(function (t, i) {
      return '<button data-tab="' + t[0] + '"' + (i === 0 ? ' class="active"' : "") + ">" + t[1] + "</button>";
    }).join("") + "</nav>");
    root.appendChild(nav);

    var views = {
      pitch: pitchView(model), heatmap: heatmapView(model), team: teamView(model),
      players: playerView(model), momentum: momentumView(model)
    };
    var body = el('<div class="views"></div>');
    TABS.forEach(function (t, i) {
      var v = views[t[0]];
      if (i !== 0) v.classList.add("hidden");
      body.appendChild(v);
    });
    root.appendChild(body);

    nav.querySelectorAll("button").forEach(function (b) {
      b.addEventListener("click", function () {
        nav.querySelectorAll("button").forEach(function (x) { x.classList.remove("active"); });
        b.classList.add("active");
        var tab = b.getAttribute("data-tab");
        TABS.forEach(function (t) { views[t[0]].classList.toggle("hidden", t[0] !== tab); });
      });
    });
  }

  MR.views = { render: render, score: score };
})(window.MR = window.MR || {});
