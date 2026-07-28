"""Pitch SVG: programmatic markings at a fixed 1:1 scale.

World Rugby standard: 100m field-of-play + in-goal areas, 70m wide. No image
asset — the fixed PX_PER_M scale is what keeps the pixel<->metre calibration
trivial (geometry.py owns that math). The rendered size still adapts, because
the image carries max-width:100%; only the coordinate space is fixed.

Markings exist to be traced against, so the ones that matter are the ones you
judge position by: the 22s (which decide the kick-to-touch law), the 10m lines,
and the 5m/15m lines a lineout is formed on.
"""

from . import config

_M = config.PX_PER_M
IMAGE_W = (config.PITCH_LENGTH_M + 2 * config.IN_GOAL_DEPTH_M) * _M
IMAGE_H = config.PITCH_WIDTH_M * _M

_LEFT_TRY = config.IN_GOAL_DEPTH_M * _M
_RIGHT_TRY = _LEFT_TRY + config.PITCH_LENGTH_M * _M
_HALFWAY = (_LEFT_TRY + _RIGHT_TRY) / 2
_POST_GAP_M = 5.6

GRASS = "#2e7d3a"
IN_GOAL = "#276a32"


def _x(metres: float) -> float:
    """Pixel x for a distance in metres from the left try line."""
    return _LEFT_TRY + metres * _M


def _vline(x, color="white", width=2, dash="", opacity=1.0):
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{x}" y1="0" x2="{x}" y2="{IMAGE_H}" stroke="{color}" '
            f'stroke-width="{width}" stroke-opacity="{opacity}"{dash_attr} />')


def _hline(y, x0, x1, color="white", width=2, dash="", opacity=1.0):
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="{color}" '
            f'stroke-width="{width}" stroke-opacity="{opacity}"{dash_attr} />')


def _label(x, y, text, size=11, anchor="middle", opacity=0.75):
    return (f'<text x="{x}" y="{y}" fill="white" font-size="{size}" '
            f'font-family="monospace" text-anchor="{anchor}" '
            f'opacity="{opacity}">{text}</text>')


def _posts(x):
    """Goal posts, seen from above: two points on the try line."""
    half = _POST_GAP_M / 2 * _M
    cy = IMAGE_H / 2
    return "".join(
        f'<circle cx="{x}" cy="{cy + dy}" r="3.5" fill="white" />'
        for dy in (-half, half))


def _end_name(x_centre, name):
    """The defending team's name, written down its own in-goal.

    Traces do reach the in-goal — that is what a try looks like — but they
    cross it rather than live there, so a low-opacity label costs nothing. An
    on-pitch direction arrow would sit in the field of play and compete with
    the trace, and the status bar already carries one.
    """
    cy = IMAGE_H / 2
    return (f'<text x="{x_centre}" y="{cy}" fill="white" font-size="20" '
            f'font-family="monospace" font-weight="bold" text-anchor="middle" '
            f'opacity="0.5" transform="rotate(-90 {x_centre} {cy})">{name}</text>')


def pitch_svg(team_colors: dict = None, attack_dir_home: int = 1,
              team_names: dict = None) -> str:
    """Markings, optionally tinted by which end each team is defending."""
    colors = team_colors or config.TEAM_COLORS
    names = team_names or {"home": "HOME", "away": "AWAY"}
    # home attacking right (+1) defends the left in-goal, and vice versa
    left_defender = "home" if attack_dir_home > 0 else "away"
    right_defender = "away" if attack_dir_home > 0 else "home"

    parts = [f'<rect x="0" y="0" width="{IMAGE_W}" height="{IMAGE_H}" fill="{GRASS}" />']

    # in-goal areas, washed with the colour of the side defending them
    for x0, team in ((0, left_defender), (_RIGHT_TRY, right_defender)):
        parts.append(f'<rect x="{x0}" y="0" width="{_LEFT_TRY}" height="{IMAGE_H}" '
                     f'fill="{IN_GOAL}" />')
        # strong enough to read AS the team's colour: a light wash over grass
        # turns a red kit into mud and stops saying whose end it is
        parts.append(f'<rect x="{x0}" y="0" width="{_LEFT_TRY}" height="{IMAGE_H}" '
                     f'fill="{colors[team]}" opacity="0.6" />')
        parts.append(_end_name(x0 + _LEFT_TRY / 2, names[team]))

    # 5m and 15m lines: broken, running the length, what a lineout forms on
    for m_in in (5, 15):
        for y in (m_in * _M, IMAGE_H - m_in * _M):
            parts.append(_hline(y, _x(5), _x(95), dash="4,12", width=1.5,
                                opacity=0.55))

    parts += [
        _vline(_LEFT_TRY, width=3),
        _vline(_RIGHT_TRY, width=3),
        _vline(_HALFWAY),
        _vline(_x(22)),                          # the 22s are solid...
        _vline(_x(78)),
        _vline(_x(40), dash="10,8", opacity=0.8),  # ...the 10m lines are broken
        _vline(_x(60), dash="10,8", opacity=0.8),
        _posts(_LEFT_TRY),
        _posts(_RIGHT_TRY),
    ]

    for metres, text in ((22, "22"), (40, "10"), (50, "H"), (60, "10"), (78, "22")):
        parts.append(_label(_x(metres), 18, text, size=13))

    parts.append(f'<rect x="0" y="0" width="{IMAGE_W}" height="{IMAGE_H}" '
                 f'fill="none" stroke="white" stroke-width="2" />')
    return "".join(parts)
