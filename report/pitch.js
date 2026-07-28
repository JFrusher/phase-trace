/* Pitch SVG + action overlay. Port of tracer/pitch.py — same fixed 1:1 scale,
   same markings, same palette. Field metres -> pixels via PX_PER_M; geometry
   is fixed, the <svg> carries width:100% so the render still adapts. */
(function (MR) {
  "use strict";

  // tracer/config.py pitch constants
  var PX_PER_M = 8;
  var PITCH_LENGTH_M = 100, PITCH_WIDTH_M = 70, IN_GOAL_DEPTH_M = 10;
  var POST_GAP_M = 5.6;

  var IMAGE_W = (PITCH_LENGTH_M + 2 * IN_GOAL_DEPTH_M) * PX_PER_M; // 960
  var IMAGE_H = PITCH_WIDTH_M * PX_PER_M;                          // 560
  var LEFT_TRY = IN_GOAL_DEPTH_M * PX_PER_M;
  var RIGHT_TRY = LEFT_TRY + PITCH_LENGTH_M * PX_PER_M;
  var HALFWAY = (LEFT_TRY + RIGHT_TRY) / 2;

  var GRASS = "#2e7d3a", IN_GOAL = "#276a32";
  var ACTION_COLORS = { carry: "#ffd54f", pass: "#64b5f6", kick: "#ef5350" };

  // field metre (0 = left try line) -> pixel x. Negative / >100 land in-goal,
  // which is exactly where kicks and grounded tries belong. No clamp.
  function xPx(m) { return LEFT_TRY + m * PX_PER_M; }
  function yPx(m) { return m * PX_PER_M; }

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function vline(x, color, width, dash, opacity) {
    var d = dash ? ' stroke-dasharray="' + dash + '"' : "";
    return '<line x1="' + x + '" y1="0" x2="' + x + '" y2="' + IMAGE_H + '" stroke="' +
      (color || "white") + '" stroke-width="' + (width || 2) + '" stroke-opacity="' +
      (opacity == null ? 1 : opacity) + '"' + d + " />";
  }
  function hline(y, x0, x1, width, dash, opacity) {
    var d = dash ? ' stroke-dasharray="' + dash + '"' : "";
    return '<line x1="' + x0 + '" y1="' + y + '" x2="' + x1 + '" y2="' + y +
      '" stroke="white" stroke-width="' + (width || 2) + '" stroke-opacity="' +
      (opacity == null ? 1 : opacity) + '"' + d + " />";
  }
  function label(x, y, text, size) {
    return '<text x="' + x + '" y="' + y + '" fill="white" font-size="' + (size || 11) +
      '" font-family="monospace" text-anchor="middle" opacity="0.75">' + esc(text) + "</text>";
  }
  function posts(x) {
    var half = POST_GAP_M / 2 * PX_PER_M, cy = IMAGE_H / 2, out = "";
    [-half, half].forEach(function (dy) {
      out += '<circle cx="' + x + '" cy="' + (cy + dy) + '" r="3.5" fill="white" />';
    });
    return out;
  }
  function endName(xc, name) {
    var cy = IMAGE_H / 2;
    return '<text x="' + xc + '" y="' + cy + '" fill="white" font-size="20" ' +
      'font-family="monospace" font-weight="bold" text-anchor="middle" opacity="0.5" ' +
      'transform="rotate(-90 ' + xc + " " + cy + ')">' + esc(name) + "</text>";
  }

  // The markings background. attackDirHome +1 => home attacks right, defends left.
  function pitchBackground(colors, names, attackDirHome) {
    colors = colors || { home: "#d32f2f", away: "#1565c0" };
    names = names || { home: "HOME", away: "AWAY" };
    var leftDef = attackDirHome > 0 ? "home" : "away";
    var rightDef = attackDirHome > 0 ? "away" : "home";
    var p = ['<rect x="0" y="0" width="' + IMAGE_W + '" height="' + IMAGE_H + '" fill="' + GRASS + '" />'];

    [[0, leftDef], [RIGHT_TRY, rightDef]].forEach(function (pair) {
      var x0 = pair[0], team = pair[1];
      p.push('<rect x="' + x0 + '" y="0" width="' + LEFT_TRY + '" height="' + IMAGE_H + '" fill="' + IN_GOAL + '" />');
      p.push('<rect x="' + x0 + '" y="0" width="' + LEFT_TRY + '" height="' + IMAGE_H + '" fill="' + colors[team] + '" opacity="0.6" />');
      p.push(endName(x0 + LEFT_TRY / 2, names[team]));
    });

    [5, 15].forEach(function (mIn) {
      [mIn * PX_PER_M, IMAGE_H - mIn * PX_PER_M].forEach(function (y) {
        p.push(hline(y, xPx(5), xPx(95), 1.5, "4,12", 0.55));
      });
    });

    p.push(vline(LEFT_TRY, "white", 3));
    p.push(vline(RIGHT_TRY, "white", 3));
    p.push(vline(HALFWAY));
    p.push(vline(xPx(22)));
    p.push(vline(xPx(78)));
    p.push(vline(xPx(40), "white", 1, "10,8", 0.8));
    p.push(vline(xPx(60), "white", 1, "10,8", 0.8));
    p.push(posts(LEFT_TRY));
    p.push(posts(RIGHT_TRY));

    [[22, "22"], [40, "10"], [50, "H"], [60, "10"], [78, "22"]].forEach(function (m) {
      p.push(label(xPx(m[0]), 18, m[1], 13));
    });
    p.push('<rect x="0" y="0" width="' + IMAGE_W + '" height="' + IMAGE_H + '" fill="none" stroke="white" stroke-width="2" />');
    return p.join("");
  }

  var COORD_KEYS = ["start_x_m", "start_y_m", "end_x_m", "end_y_m"];
  function hasCoords(a) {
    return COORD_KEYS.every(function (k) { return Number.isFinite(a[k]); });
  }

  // Action lines overlaid on the pitch. `filter(action) -> bool` decides what draws.
  function actionsOverlay(actions, filter) {
    var out = "";
    actions.forEach(function (a) {
      if (!ACTION_COLORS[a.type] || !hasCoords(a)) return;   // set_piece/try/error have no line
      if (filter && !filter(a)) return;
      var x1 = xPx(a.start_x_m), y1 = yPx(a.start_y_m), x2 = xPx(a.end_x_m), y2 = yPx(a.end_y_m);
      var color = ACTION_COLORS[a.type];
      var dash = a.intercepted ? ' stroke-dasharray="6,5"' : "";
      var w = a.linebreak ? 4 : 2.5;
      out += '<line x1="' + x1 + '" y1="' + y1 + '" x2="' + x2 + '" y2="' + y2 +
        '" stroke="' + color + '" stroke-width="' + w + '" stroke-linecap="round" stroke-opacity="0.9"' + dash + " />";
      out += '<circle cx="' + x2 + '" cy="' + y2 + '" r="2.6" fill="' + color + '" />'; // end dot = direction
    });
    return out;
  }

  MR.pitch = {
    IMAGE_W: IMAGE_W, IMAGE_H: IMAGE_H,
    ACTION_COLORS: ACTION_COLORS,
    xPx: xPx, yPx: yPx, hasCoords: hasCoords,
    background: pitchBackground,
    overlay: actionsOverlay,
    svg: function (actions, model, filter) {
      return '<svg viewBox="0 0 ' + IMAGE_W + " " + IMAGE_H + '" class="pitch-svg" ' +
        'preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg">' +
        pitchBackground(model.colors, { home: model.home, away: model.away }, model.attackDirHome) +
        actionsOverlay(actions, filter) + "</svg>";
    }
  };
})(window.MR = window.MR || {});
