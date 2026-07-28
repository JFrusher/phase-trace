/* Ingest an exported folder (or its files): read, sniff, parse, normalize.
   match.json is the source of truth (self-contained). CSVs are a fallback for
   when it's been removed. Everything is parsed client-side. */
(function (MR) {
  "use strict";

  var DEFAULT_COLORS = { home: "#d32f2f", away: "#1565c0" };

  // Colours flow straight into style="background:…" attributes and SVG fills
  // (views.js chips/bars/legend, pitch.js). Pin them to a hex literal at the
  // ingest boundary so a malicious value in a future colour-carrying export
  // (e.g. a session save's team_colors) can't break out into markup.
  function safeColor(c) { return /^#[0-9a-fA-F]{6}$/.test(c) ? c : "#888888"; }

  var ACTION_NUM = ["minute", "metres_gained", "start_x_m", "start_y_m", "end_x_m",
    "end_y_m", "end_metres_from_line", "attack_dir"];
  var TEAM_NUM = ["points", "possessions", "metres", "carries", "carry_metres", "kicks",
    "kick_metres", "linebreaks", "tries", "conversions", "conversions_missed", "penalty_kicks",
    "drop_goals", "penalty_tries", "turnovers_won", "lineouts_won", "lineouts_lost", "scrums_won",
    "scrums_lost", "penalties_won", "penalties_conceded", "errors", "sin_bins", "red_cards"];
  var PLAYER_NUM = ["number", "carries", "carry_metres", "linebreaks", "kicks", "kick_metres", "tries", "assists"];

  function readFile(file) {
    return (file.text ? file.text() : new Promise(function (res, rej) {
      var r = new FileReader();
      r.onload = function () { res(r.result); };
      r.onerror = function () { rej(r.error); };
      r.readAsText(file);
    })).then(function (text) {
      return { name: (file.name || "").toLowerCase(), path: file.webkitRelativePath || file.path || file.name || "", text: text };
    });
  }

  function readAll(fileList) {
    return Promise.all(Array.prototype.slice.call(fileList).map(readFile));
  }

  // ponytail: minimal CSV — split on newlines/commas, trim cells. No quoted-comma
  // handling; the tracer's numeric/short-token exports never need it. Upgrade only
  // if a team name ever contains a comma.
  function parseCsv(text, numericKeys) {
    var lines = text.replace(/\r/g, "").split("\n").filter(function (l) { return l.trim() !== ""; });
    if (!lines.length) return [];
    var header = lines[0].split(",").map(function (h) { return h.trim(); });
    var numSet = {};
    (numericKeys || []).forEach(function (k) { numSet[k] = 1; });
    return lines.slice(1).map(function (line) {
      var cells = line.split(",");
      var row = {};
      header.forEach(function (key, i) {
        var raw = (cells[i] == null ? "" : cells[i]).trim();
        if (numSet[key]) row[key] = raw === "" ? undefined : Number(raw);
        else row[key] = raw === "" ? undefined : raw;
      });
      return row;
    });
  }

  // "HOME_v_AWAY/team.csv" -> {home:"HOME", away:"AWAY"}
  function folderNames(files) {
    for (var i = 0; i < files.length; i++) {
      var seg = (files[i].path || "").split("/")[0];
      var m = seg && seg.match(/^(.+)_v_(.+)$/);
      if (m) return { home: m[1], away: m[2] };
    }
    return null;
  }

  function inferAttackDir(actions, homeName) {
    for (var i = 0; i < actions.length; i++) {
      var a = actions[i];
      if (a.team === homeName && Number.isFinite(a.attack_dir) && a.attack_dir !== 0) {
        return a.attack_dir > 0 ? 1 : -1;
      }
    }
    return 1;
  }

  function finalize(model) {
    var c = model.colors || DEFAULT_COLORS;
    model.colors = { home: safeColor(c.home), away: safeColor(c.away) };
    model.attackDirHome = inferAttackDir(model.actions, model.home);
    model.sideStats = {
      home: (model.teamStats && model.teamStats[model.home]) || null,
      away: (model.teamStats && model.teamStats[model.away]) || null
    };
    return model;
  }

  // --- shape sniffing -------------------------------------------------------
  function fromMatchJson(obj, warnings) {
    var meta = obj.meta || {};
    var teams = meta.teams || {};
    var home = teams.home, away = teams.away;
    var summary = obj.summary || {};
    if (!home || !away) {
      // fall back to the two names present in summary.team
      var names = Object.keys(summary.team || {});
      home = home || names[0]; away = away || names[1];
      if (!home || !away) throw new Error("match.json has no team names (meta.teams / summary.team both empty).");
      warnings.push("Team names taken from summary.team — meta.teams was empty.");
    }
    return finalize({
      home: home, away: away, colors: DEFAULT_COLORS,
      meta: { date: meta.date || "", competition: meta.competition || "" },
      actions: Array.isArray(obj.actions) ? obj.actions : [],
      teamStats: summary.team || {},
      players: Array.isArray(summary.players) ? summary.players : [],
      source: "match.json", warnings: warnings
    });
  }

  function fromCsv(byName, files, warnings) {
    var actions = byName["actions.csv"] ? parseCsv(byName["actions.csv"], ACTION_NUM) : [];
    var teamRows = byName["team.csv"] ? parseCsv(byName["team.csv"], TEAM_NUM) : [];
    var playerRows = byName["players.csv"] ? parseCsv(byName["players.csv"], PLAYER_NUM) : [];
    if (!actions.length && !teamRows.length) {
      throw new Error("No usable data: found neither match.json nor actions/team CSVs.");
    }
    var names = folderNames(files);
    var home, away;
    if (names) { home = names.home; away = names.away; }
    else if (teamRows.length >= 2) {
      home = teamRows[0].team; away = teamRows[1].team;
      warnings.push("No folder name to read sides from — assumed row order home, away in team.csv.");
    } else { throw new Error("Cannot determine home/away without match.json or a '<HOME>_v_<AWAY>' folder."); }

    var teamStats = {};
    teamRows.forEach(function (r) { if (r.team) teamStats[r.team] = r; });
    // Folder name and team.csv names normally agree (both from the same export).
    // If a renamed folder makes them diverge, trust the CSV rows (row order = home, away).
    if (teamRows.length >= 2 && (!teamStats[home] || !teamStats[away])) {
      home = teamRows[0].team; away = teamRows[1].team;
      warnings.push("Folder name didn't match team.csv — used team.csv row order for home/away.");
    }
    warnings.push("Read from CSVs (match.json absent): linebreak / interception / player tags are not in the CSV export.");
    return finalize({
      home: home, away: away, colors: DEFAULT_COLORS,
      meta: { date: "", competition: "" },
      actions: actions, teamStats: teamStats, players: playerRows,
      source: "csv", warnings: warnings
    });
  }

  // Main entry: returns Promise<model>. Rejects with a human-readable Error.
  function ingest(fileList) {
    return readAll(fileList).then(function (files) {
      if (!files.length) throw new Error("No files selected.");
      var byName = {};
      files.forEach(function (f) { byName[f.name] = f.text; });
      var warnings = [];

      if (byName["match.json"]) {
        var obj;
        try { obj = JSON.parse(byName["match.json"]); }
        catch (e) { throw new Error("match.json is not valid JSON: " + e.message); }
        if (obj && obj.meta && Array.isArray(obj.actions) && obj.summary) return fromMatchJson(obj, warnings);
        if (obj && Array.isArray(obj.events) && obj.teams) {
          throw new Error("This looks like an 'events' momentum file, not a raw export. Load an export folder containing match.json / actions.csv.");
        }
        if (obj && Array.isArray(obj.events) && obj.clock_seconds !== undefined) {
          throw new Error("This looks like a session save, not a raw export. Load an export folder (match.json + CSVs).");
        }
        warnings.push("match.json had an unexpected shape — falling back to CSVs.");
      }
      return fromCsv(byName, files, warnings);
    });
  }

  MR.ingest = { run: ingest, parseCsv: parseCsv, folderNames: folderNames, DEFAULT_COLORS: DEFAULT_COLORS };
})(window.MR = window.MR || {});
