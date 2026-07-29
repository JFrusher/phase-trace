/* Momentum reconstruction from the raw-export action stream.

   The raw export drops phase_sequence, so we rebuild possession phases by
   grouping consecutive same-team movement actions, then derive a territory
   weight the same way tracer/translators/rugby.py does. Scores/discipline use
   the static weight table. Impulses are fed through the same exponential-decay +
   Gaussian-smoothing engine as core/engine.py.

   The weighting reproduces the phase_sequence chart: start_reason is stamped
   on each possession's first action, so origin_factor applies exactly as in
   rugby.py. The only remaining approximation is the time axis — trace pace and
   match clock are structurally unlinkable, so x is minutes-if-usable else
   play sequence. */
(function (MR) {
  "use strict";

  // translators/rugby_weights.json (inlined)
  var WEIGHTS = {
    try: 2.0, penalty_try: 2.3, conversion: 0.3, conversion_missed: 0.0,
    penalty_kick: 1.0, drop_goal: 1.1, turnover_won: 0.5, penalty_won: 0.6,
    _default: 0.4
  };
  var ORIGIN_FACTOR = {
    interception: 1.3, penalty: 1.25, lineout: 1.15, turnover_open: 1.1,
    scrum: 1.0, kick_return: 0.95, restart: 0.9, kickoff: 0.9, drop_out_22: 0.85
  };
  var SCORE_TYPES = { try: 1, penalty_try: 1, penalty_kick: 1, drop_goal: 1 };
  var CARD_TYPES = { sin_bin: 1, red_card: 1 };
  var MOVEMENT = { carry: 1, pass: 1, kick: 1 };
  var HALF_LIFE = 4.5, SMOOTH_SIGMA = 1.2, RESOLUTION = 6;

  // rugby.py _territory_weight. origin defaults to 1.0 (unknown start_reason,
  // or a pre-start_reason export).
  function territoryWeight(metres, endMFromLine, linebreaks, startReason) {
    // metres_gained / end_metres_from_line arrive SIGNED in the export (ground
    // lost is negative, past the try line is negative from it). Clamp here, the
    // same way translators/rugby.py does, or this reconstruction drifts from
    // the app's chart on any possession that went backwards.
    var territory = 1 - Math.min(100, Math.max(0, endMFromLine)) / 100;
    var base = 0.15 + 0.35 * Math.min(Math.max(0, metres) / 40, 1);
    var origin = ORIGIN_FACTOR[startReason] || 1.0;
    return Math.round(((base + 0.3 * territory) * (1 + 0.25 * linebreaks) * origin) * 100) / 100;
  }

  // Reflect-padded 1-D Gaussian blur — scipy.ndimage.gaussian_filter1d default.
  function gaussianBlur1d(y, sigma) {
    if (!sigma) return y.slice();
    var radius = Math.max(1, Math.ceil(4 * sigma));
    var kernel = [], sum = 0, i, k;
    for (i = -radius; i <= radius; i++) {
      var v = Math.exp(-(i * i) / (2 * sigma * sigma));
      kernel.push(v); sum += v;
    }
    for (i = 0; i < kernel.length; i++) kernel[i] /= sum;
    var n = y.length, out = new Array(n);
    for (i = 0; i < n; i++) {
      var acc = 0;
      for (k = -radius; k <= radius; k++) {
        var j = i + k;
        while (j < 0 || j >= n) {             // reflect (loop: radius may exceed n)
          if (j < 0) j = -j - 1;
          if (j >= n) j = 2 * n - j - 1;
        }
        acc += y[j] * kernel[k + radius];
      }
      out[i] = acc;
    }
    return out;
  }

  function teamSeries(impulses, team, t, lambda) {
    var y = new Array(t.length).fill(0);
    impulses.forEach(function (ev) {
      if (ev.team !== team || ev.weight === 0) return;
      for (var i = 0; i < t.length; i++) {
        var dt = t[i] - ev.t;
        if (dt >= 0) y[i] += ev.weight * Math.exp(-lambda * dt);
      }
    });
    return gaussianBlur1d(y, SMOOTH_SIGMA * RESOLUTION);
  }

  // Group the stream into impulses. Returns {impulses, markers}.
  function extractImpulses(actions, homeName, awayName) {
    var impulses = [], markers = [];
    var phase = null;
    function closePhase() {
      if (!phase) return;
      impulses.push({
        team: phase.team, t: phase.t,
        weight: territoryWeight(phase.metres, phase.endM, phase.linebreaks, phase.origin),
        kind: "pressure"
      });
      phase = null;
    }
    actions.forEach(function (a) {
      var team = a.team;
      if (MOVEMENT[a.type]) {
        // A team change is a sub-chain split (kick/interception); a start_reason
        // is a new possession's first action. Break on either so phases match
        // rugby.py's phase_sequences even when possession is retained (a tapped
        // penalty kept by the same team).
        if (phase && (phase.team !== team || a.start_reason != null)) closePhase();
        if (!phase) phase = { team: team, t: num(a.minute), metres: 0, endM: 50, linebreaks: 0, origin: a.start_reason };
        phase.metres += num(a.metres_gained);
        if (Number.isFinite(a.end_metres_from_line)) phase.endM = a.end_metres_from_line;
        if (a.linebreak) phase.linebreaks += 1;
      } else if (CARD_TYPES[a.type]) {
        closePhase();
        markers.push({ t: num(a.minute), seq: impulses.length, team: team, label: a.label || a.type, kind: "card" });
      } else if (a.type in WEIGHTS || a.type in SCORE_TYPES || a.type === "turnover_won" || a.type === "penalty_won") {
        closePhase();
        var w = WEIGHTS[a.type];
        if (w == null) w = WEIGHTS._default;
        impulses.push({ team: team, t: num(a.minute), weight: w, kind: a.type });
        if (SCORE_TYPES[a.type]) markers.push({ t: num(a.minute), seq: impulses.length - 1, team: team, label: a.label || a.type, kind: "score" });
      }
      // set_piece / error: no impulse, and they don't break a phase's continuity
    });
    closePhase();
    return { impulses: impulses, markers: markers };
  }

  function num(v) { return Number.isFinite(v) ? v : 0; }

  // Minutes are "usable" only if events actually span time. Real exports where
  // the clock never ran have every minute ~equal -> fall back to sequence index.
  function timeIsUsable(impulses) {
    if (impulses.length < 2) return false;
    var min = Infinity, max = -Infinity;
    impulses.forEach(function (e) { if (e.t < min) min = e.t; if (e.t > max) max = e.t; });
    return (max - min) >= 1.0;
  }

  function build(actions, homeName, awayName) {
    var ex = extractImpulses(actions, homeName, awayName);
    var impulses = ex.impulses, markers = ex.markers;
    if (impulses.length < 2) {
      return { usable: false, reason: "Not enough possession/scoring events to plot momentum." };
    }
    var timebase = timeIsUsable(impulses) ? "minute" : "sequence";
    if (timebase === "sequence") {
      // Reassign t = running ordinal so the curve reads left-to-right by play.
      // Markers point at the impulse index recorded when they were seen.
      impulses.forEach(function (e, i) { e.t = i; });
      markers.forEach(function (m) { m.t = Math.max(0, Math.min(impulses.length - 1, m.seq)); });
    }
    var maxT = 0;
    impulses.forEach(function (e) { if (e.t > maxT) maxT = e.t; });
    maxT = Math.max(maxT, 1) + (timebase === "minute" ? 2 : 1);   // small tail so the last impulse's decay shows

    var lambda = Math.log(2) / HALF_LIFE;
    var N = Math.max(2, Math.round(maxT * RESOLUTION) + 1);
    var t = new Array(N);
    for (var i = 0; i < N; i++) t[i] = (maxT * i) / (N - 1);

    var yHome = teamSeries(impulses, homeName, t, lambda);
    var yAway = teamSeries(impulses, awayName, t, lambda);
    var net = t.map(function (_, i) { return yHome[i] - yAway[i]; });
    var peak = net.reduce(function (m, v) { return Math.max(m, Math.abs(v)); }, 0);
    if (peak === 0) return { usable: false, reason: "No net threat difference to plot." };

    var home = net.map(function (v) { return v > 0 ? v / peak : 0; });
    var away = net.map(function (v) { return v < 0 ? -v / peak : 0; });
    return {
      usable: true, timebase: timebase, t: t, home: home, away: away,
      maxT: maxT, markers: markers, impulseCount: impulses.length
    };
  }

  MR.momentum = { build: build, territoryWeight: territoryWeight, gaussianBlur1d: gaussianBlur1d, WEIGHTS: WEIGHTS };
})(window.MR = window.MR || {});
