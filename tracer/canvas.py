"""ui.interactive_image wiring: path capture + live preview + classified redraw.

Timestamps are stamped server-side (time.monotonic()) on event arrival —
MouseEventArguments carries no client timestamp. Fine for local use; WAN
latency jitter would degrade segmentation timing.
"""

import time

from nicegui import ui

from . import config
from .pitch import IMAGE_W, IMAGE_H, pitch_svg

ACTION_COLORS = {"CARRY": "#ffd54f", "PASS": "#64b5f6", "KICK": "#ef5350"}
CLICK_RADIUS_PX = 14        # how near a click must land to claim a segment


def segment_style(seg):
    """(colour, dash) for one classified segment. Interception is dashed.

    Segments are deliberately NOT shaded by classifier confidence. CARRY is
    the reference class scoring a flat 0, so a textbook carry wins only by
    PASS's small bias (-0.2) and reads as a 0.09 margin, while a genuinely
    borderline 25-30m stroke reads higher. The margin measures the bias
    constant, not doubt, so shading by it marks the safest calls as the least
    certain. Per-segment scores stay in the dev drawer, where the full feature
    table gives them the context that makes them mean something.
    """
    return ACTION_COLORS.get(seg.action, "white"), "dash" if seg.intercepted else ""


def _polyline(points, color, width=3, dash="", opacity=1.0):
    if len(points) < 2:
        return ""
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    dash_attr = ' stroke-dasharray="6,5"' if dash else ""
    return (f'<polyline points="{pts}" fill="none" stroke="{color}" '
            f'stroke-width="{width}" stroke-linecap="round" '
            f'stroke-opacity="{opacity}"{dash_attr} />')


class TraceCanvas:
    """Owns the interactive image; forwards raw gestures, renders paths back."""

    def __init__(self, *, on_down, on_move, on_up, on_segment_click=None,
                 base_svg: str = None):
        self._on_down, self._on_move, self._on_up = on_down, on_move, on_up
        self._on_segment_click = on_segment_click
        self._base = base_svg or pitch_svg()
        self._live: list[tuple[float, float]] = []
        self._overlay = ""
        self._segments: list = []
        self._down_at = None
        self._dragging = False
        self._suspended = False
        # the WRAPPER carries the sizing, not the image: with max-width on the
        # image instead, it resolves against a wrapper that is itself sized by
        # its content, so the pitch stops shrinking and overflows the window
        with ui.element("div").classes("relative").style(
                f"width:{IMAGE_W}px;max-width:100%"):
            self.image = ui.interactive_image(
                size=(IMAGE_W, IMAGE_H),
                content=self._base,
                on_mouse=self._mouse,
                events=["mousedown", "mousemove", "mouseup"],
                cross=True,
            ).style("width:100%")  # size= sets only aspect-ratio, not CSS width
            # The image edge IS the touchline, so tracing a ball out of play
            # takes the cursor off the element — and an uncaptured mouseup
            # lands on the document, never here, leaving the chain unfinished
            # and the line white forever. Capture pins both to the image;
            # offsetX/offsetY then run past the edge, which is what makes a
            # real crossing (rather than mere proximity) visible at all.
            self.image.on("pointerdown",
                          js_handler="(e) => e.target.setPointerCapture?.(e.pointerId)")
            # chips sit above the image. The layer ignores pointer events so
            # drags still reach the canvas; each chip re-enables its own.
            self.chip_layer = ui.element("div").classes(
                "absolute inset-0 pointer-events-none")

    def _mouse(self, e):
        t = time.monotonic()
        if e.type == "mousedown":
            self._handle_down(e, t)
        elif self._suspended:
            # the chain already committed (ball out of play, or an A tap
            # mid-drag) but the button is still down: keep the classified
            # drawing rather than painting a stray white tail over it
            return
        elif e.type == "mousemove" and e.buttons:
            self._handle_move(e, t)
        elif e.type == "mouseup":
            self._handle_up(e, t)

    def _handle_down(self, e, t):
        # the handler may move the start (a restart is taken from the centre
        # spot); draw from where it actually recorded, so a press off the mark
        # shows as the leg it will be recorded as
        start = self._on_down(e.image_x, e.image_y, t) or (e.image_x, e.image_y)
        self._live = [start]
        self._down_at = (e.image_x, e.image_y)
        self._dragging = False
        self._suspended = False

    def _handle_move(self, e, t):
        at = self._on_move(e.image_x, e.image_y, t) or (e.image_x, e.image_y)
        self._live.append(at)
        if not self._dragging and self._moved_far(e.image_x, e.image_y):
            # only a real drag replaces the last drawing — a click has to
            # leave it on screen, since the click is aimed AT it
            self._dragging = True
            self._overlay, self._segments = "", []
        if len(self._live) % 3 == 0:  # ponytail: redraw every 3rd point; virtual-canvas diffing if it lags
            self._redraw()

    def _handle_up(self, e, t):
        if self._dragging:
            self._on_up(t)
        else:
            # a click is not the end of a trace. Routing it through on_up would
            # run end_chain, which clears last_chain on a rejected sub-threshold
            # movement (fixtures.py reads that None as "this trace was
            # rejected") — and re-classifying needs that chain.
            self._click(e.image_x, e.image_y)
        self._down_at = None

    def _moved_far(self, x, y) -> bool:
        dx, dy = x - self._down_at[0], y - self._down_at[1]
        return dx * dx + dy * dy > config.MIN_MOVEMENT_PX ** 2

    def _click(self, x, y):
        """A click, not a drag: re-classify the segment under the cursor."""
        self._live = []
        self._redraw()
        if not (self._segments and self._on_segment_click):
            return
        best, best_d = None, CLICK_RADIUS_PX ** 2
        for i, seg in enumerate(self._segments):
            for p in seg.points:
                d = (p.x - x) ** 2 + (p.y - y) ** 2
                if d < best_d:
                    best, best_d = i, d
        if best is not None:
            self._on_segment_click(best)

    def render_segments(self, segments):
        """Replace the raw live line with the classified, color-coded result."""
        self._segments = list(segments)
        self._suspended = True
        parts = []
        for seg in segments:
            color, dash = segment_style(seg)
            parts.append(_polyline([(p.x, p.y) for p in seg.points], color,
                                   width=4, dash=dash))
        for seg in segments[:-1]:  # white dot at each picked boundary joint
            p = seg.points[-1]
            parts.append(f'<circle cx="{p.x:.1f}" cy="{p.y:.1f}" r="4" '
                         f'fill="white" stroke="#333" stroke-width="1.5" />')
        self._overlay = "".join(parts)
        self._live = []
        self._redraw()

    def set_pitch(self, svg: str):
        """Swap the markings — the in-goal tints and arrows flip at halftime."""
        self._base = svg
        self._redraw()

    def _redraw(self):
        self.image.content = (self._base + self._overlay
                              + _polyline(self._live, "white", width=2))
