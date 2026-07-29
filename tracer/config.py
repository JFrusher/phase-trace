"""All tunable constants for the tracer, in one place.

Every recognizer threshold and weight is empirical, tuned against the 39
synthetic scenarios in fixtures.py (replayed by tests/test_corpus.py) plus the
narrower path cases in tests/test_segmentation.py. None of it has been tuned
against a real hand-traced match; TUNING.md has the loop for that, and no tool
in this repo writes this file.

Units are metres/seconds where physical, milliseconds where a name ends *_MS,
degrees for angles. Nothing the classifier reads may be a time or a speed
(test_pace_invariance.py enforces it).
"""

# --- pitch / calibration -------------------------------------------------
PX_PER_M = 8                # fixed 1:1 scale, no responsive resize (MVP)
PITCH_LENGTH_M = 100        # try line to try line
PITCH_WIDTH_M = 70
IN_GOAL_DEPTH_M = 10
GOAL_WIDTH_M = 5.6          # gap between the posts, centred on the pitch width;
                            # decides whether an at-goal penalty kick went over
TWENTY_TWO_M = 22           # the 22 line, which decides the kick-to-touch law
TOUCH_MARGIN_M = 2.0        # a trace finishing this close to a touchline counts
                            # as out: the browser stops reporting mousemove once
                            # the cursor leaves the image, so a ball kicked out
                            # is a path that STOPS at the edge, never one that
                            # visibly crosses it
SNAP_TOLERANCE_M = 10.0     # a new possession's press snaps onto an INFERRED start
                            # mark (lineout, scrum, turnover, penalty) only if it
                            # lands within this radius; a press further out is taken
                            # at face value — a deliberate free start — so one wild
                            # click can't drag the whole trace onto a guessed mark.
                            # Centre-spot restarts (CENTRE_SPOT_REASONS) are a hard
                            # law and always snap, tolerance or not. The mark is
                            # drawn as a target (chips._target) so operators aim in.

# --- segmentation thresholds (the tunable heart of Live Trace) -----------
# Spacing/windows are in METRES OF TRACED PATH, not milliseconds: the line is
# read from its geometry, with no assumption about how fast it was drawn.
RESAMPLE_STEP_M = 0.5       # re-space points uniformly by arc-length first, so
                            # point density (and thus every point-count window)
                            # is identical however fast the line was drawn
SMOOTH_WINDOW_PTS = 5       # sliding-average window to cut mouse jitter
HEADING_WINDOW_M = 1.5      # arc-length each side of a candidate for heading est.
BOUNDARY_GROUP_M = 1.5      # candidates within this arc-length = one turn
MIN_SEGMENT_M = 4.0         # boundaries closer than this arc-length: keep stronger
LATERAL_FWD_PENALTY = 3.0   # each forward metre cancels this many lateral metres
                            # of PASS evidence — a pass never gains ground, so
                            # forward progress vetoes a lateral/square pass call
MIN_MOVEMENT_PX = 6         # smaller total displacement = accidental click

# --- boundary evidence scoring (Layer 1) ----------------------------------
# A point is a boundary iff its combined evidence score clears BOUNDARY_ACCEPT.
# Evidence is measured against THIS path's own baseline (median angle/ratio),
# so a wobbly hand raises the bar and a clean hand lowers it.
BOUNDARY_ANGLE_FLOOR_DEG = 8.0   # baseline never below this much wobble
BOUNDARY_ANGLE_BASE_MULT = 2.0   # evidence starts this far above path median
BOUNDARY_ANGLE_SCALE_DEG = 45.0  # tanh scale for angle excess
BOUNDARY_RATIO_FLOOR = 1.2
BOUNDARY_RATIO_BASE_MULT = 1.5
BOUNDARY_RATIO_SCALE = 1.0
W_BOUNDARY_ANGLE = 1.0
W_BOUNDARY_SPEED = 1.0
BOUNDARY_ACCEPT = 0.75           # single accept threshold on the combined score
                                 # (sweep 2026-07-20: 0.65-0.85 all-pass; 0.75 =
                                 # band center; genuine turns >=0.92, release
                                 # wobble <=0.73 on noisy corpus)

# --- classification feature squashing (Layer 2) ---------------------------
# Each feature is tanh((raw - center)/scale); backward/lateral/dist are
# rectified (max(0, .) before tanh) so absence of evidence is 0, never
# negative. Every feature is purely spatial — positions only, never time.
F_BACK_SCALE_M = 0.5             # sharp: near-step at fwd=0 (rugby law edge)
F_LAT_SCALE_M = 1.5
F_STRAIGHT_CENTER = 0.85         # net/path-length above this reads deliberate
F_STRAIGHT_SCALE = 0.10
F_DIST_SCALE_M = 28.0            # kicks travel far; carries rarely > ~24m
# Bentness: rectified penalty, positive only when a stroke's straightness falls
# below F_BENT_CENTER. A real kick is near-straight (~0.95+), so this stays 0
# for genuine kicks AND for straight long carries (leaving the distance
# threshold untouched) and only bites a long BENT running break misread as a
# kick — see W_KICK_BENT.
F_BENT_CENTER = 0.90
F_BENT_SCALE = 0.06

# --- classification weights: score_c = B_c + sum(W_c_f * feature_f) -------
# CARRY is the fixed reference class (score 0, no constants here). KICK is
# geometry-only (long + straight); ambiguous ~20-30m strokes lean CARRY (a
# false kick would wrongly flip possession — K-hint / Review promotes a real
# short kick). zeros are trainer headroom — python -m tracer.fit proposes.
B_PASS = -0.2
W_PASS_BACKWARD = 8.0
W_PASS_LATERAL = 7.0
W_PASS_STRAIGHT = 0.0
W_PASS_DIST = 0.0
W_PASS_BENT = 0.0
B_KICK = -6.4               # geometric kick threshold ~27m; shorter strokes stay
W_KICK_BACKWARD = 0.0       # CARRY (distance is the necessary kick signal)
W_KICK_LATERAL = 0.0
W_KICK_STRAIGHT = 0.5
W_KICK_DIST = 8.0
W_KICK_BENT = -6.0          # a kick must be STRAIGHT, not merely long: a bent
                            # 32m running break can't clear the distance bias
# ponytail: F_BENT_CENTER / W_KICK_BENT set by hand to stop long bent runs
# reading as kicks; validate against a real trace corpus (Phase 5, tracer.fit /
# tracer.sweep) before treating them as settled.

# Below this classification confidence (top prob - second), a GEOMETRIC kick
# does not flip attack direction / possession: a near-tie kick shouldn't
# silently invert the frame for every segment after it — the same "ambiguous
# leans CARRY" principle B_KICK already encodes, applied to the flip decision.
# Kept LOW on purpose: a genuine ~30m kick's confidence is only ~0.14 (KICK
# barely clears its bias by design), so an aggressive gate would suppress real
# kick flips. The phantom BENT kick is stopped upstream by W_KICK_BENT instead.
# Forced kicks (kickoff/restart) and manual K-hint / reclassify kicks always flip.
KICK_FLIP_MIN_CONF = 0.05

# --- tap correlation ------------------------------------------------------
DIGIT_BURST_MS = 400        # sequential digit taps within this = one number
TYPE_HINT_GRACE_MS = 250    # late K/P/R tap still applies to just-ended segment
CONVERSION_LISTEN_S = 90    # after a Try tap, C/M within this = its conversion

# --- key vocabulary --------------------------------------------------------
TYPE_HINT_KEYS = {"k": "KICK", "p": "PASS", "r": "CARRY"}
LINEBREAK_KEY = "l"
TEAM_KEYS = {"z": "home", "x": "away"}
TEAM_COLORS = {"home": "#d32f2f", "away": "#1565c0"}   # setup form overrides
END_CHAIN_KEYS = {"a", " "}
DISCRETE_EVENT_KEYS = {
    "t": "try",
    "y": "penalty_try",   # awarded 7, and takes no conversion
    "n": "penalty_kick",
    "g": "drop_goal",
    "v": "turnover_won",
    "b": "sin_bin",       # a sin bin IS the yellow card; no separate name needed
    "d": "red_card",
}
CARD_TYPES = ("sin_bin", "red_card")   # marker-only: never fed into the decay sum
CONVERSION_KEYS = {"c": "conversion", "m": "conversion_missed"}

# Discrete rows whose recorded position is where the thing actually happened.
# Everything else a key can log -- a conversion, a card -- would be stamped
# wherever the pointer happened to be at the keystroke, which is not a location
# of anything, so it gets no coordinates at all (match_state._stamp). Mirrors
# radl.config.LOCATED_EVENT_TYPES; tests/test_vocab_parity.py holds them equal.
LOCATED_EVENT_TYPES = ("set_piece", "error", "try", "penalty_try",
                       "penalty_won", "turnover_won", "penalty_kick",
                       "drop_goal")

# --- how a possession begins ----------------------------------------------
# Type is never something the user corrects: it is either geometrically
# certain (a kick finishing at a touchline is a lineout, a score is a restart)
# or explicitly tapped. Only the TEAM is ambiguous, and the chip flips that.
# The momentum VALUE of each reason lives in translators/rugby_weights.json —
# the tracer says what happened, the translator says what it is worth.
START_REASONS = ("kickoff", "restart", "drop_out_22", "scrum", "lineout",
                 "penalty", "turnover_open", "interception", "kick_return")
# Taken from the centre spot, always as a drop kick. Both facts are certain
# before the trace exists, so the start point is snapped there and the first
# segment is a KICK whatever its shape — a restart tapped short would
# otherwise read as a carry and hand the ball to the wrong side.
CENTRE_SPOT_REASONS = ("kickoff", "restart")
# Reasons whose first stroke is inherently a drop kick, so it is forced to KICK
# however it was drawn (a short 22 drop-out would otherwise read as a carry).
# Superset of CENTRE_SPOT_REASONS: those two snap to halfway as well, this only
# forces the class. drop_out_22 has its own mark, so it snaps to that instead.
KICK_START_REASONS = ("kickoff", "restart", "drop_out_22")
CHIP_CLEARANCE_M = 9        # how far a chip sits off a mark you must press on
TAPPED_START_REASONS = {"s": "scrum", "f": "penalty"}
PENALTY_WON_TYPE = "penalty_won"   # the discrete event an F tap also logs
PENALTY_OPTIONS = ("kick_to_touch", "at_goal", "tap_and_go", "scrum")
PENALTY_DEFAULT_OPTION = "kick_to_touch"
# Penalty options whose ensuing stroke is a kick: picking one forces the next
# segment to KICK (a penalty to touch / at goal is a kick, not open play).
KICK_ARMED_ACTIONS = ("kick_to_touch", "kick_at_goal")
# What a trace ending over a try line meant. Grounding is the one thing a line
# genuinely cannot show, so this is a chooser like the penalty options: the
# geometry picks the likely one, ignoring the chip accepts it.
IN_GOAL_OUTCOMES = ("try", "held_up", "drop_out")

# Start reasons that are set pieces: their win/loss is inferred from who fed
# the ball vs who came away with it (events.set_piece_record).
SET_PIECE_REASONS = ("scrum", "lineout")

# --- discipline / errors --------------------------------------------------
# The penalty reason is a thing a traced line cannot show, so it is a chooser
# chip like the penalty options — absent until picked (missing pieces allowed).
PENALTY_REASONS = ("offside", "high", "ruck", "scrum", "foul", "other")
# Errors are pure data annotations: the turnover they cause is already inferred
# at chain end, so tapping one only records what went wrong and against whom.
# Tap while tracing the action that erred — the erring team is who holds the ball.
ERROR_KEYS = {"e": "knock_on", "w": "forward_pass", "h": "handling"}

# --- scoring (rugby union point values) -----------------------------------
# ponytail: union only; swap this map for another code's values if needed.
# penalty_kick counts as a penalty GOAL (3); a penalty kicked to touch isn't
# a penalty_kick event, so it scores nothing here.
POINTS = {"try": 5, "conversion": 2, "penalty_kick": 3, "drop_goal": 3,
          "penalty_try": 7}
