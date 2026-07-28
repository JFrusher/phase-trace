"""Pixel<->metre calibration + territory field math. Pure.

Isolated from pitch.py so a real pitch image can replace the placeholder
later without touching this math. x runs along the pitch's length; the
field-of-play spans [left_try_line_px, left_try_line_px + 100m].
"""

from dataclasses import dataclass

from . import config


@dataclass(frozen=True)
class PitchCalibration:
    px_per_m: float = config.PX_PER_M
    left_try_line_px: float = config.IN_GOAL_DEPTH_M * config.PX_PER_M
    width_px: float = config.PITCH_WIDTH_M * config.PX_PER_M

    def field_x_m(self, x_px: float) -> float:
        """Metres from the left try line (0 = left try line, 100 = right)."""
        return (x_px - self.left_try_line_px) / self.px_per_m

    def field_y_m(self, y_px: float) -> float:
        """Metres across the pitch from the top touchline (0..width)."""
        return y_px / self.px_per_m

    def metres_gained(self, x0_px: float, x1_px: float, attack_dir: int) -> float:
        """Net forward displacement along the attack axis, clamped >= 0."""
        return max(0.0, round(attack_dir * (x1_px - x0_px) / self.px_per_m, 1))

    def metres_from_line(self, x_px: float, attack_dir: int) -> float:
        """Distance from the attacking try line, clamped to [0, 100]."""
        fx = self.field_x_m(x_px)
        dist = (config.PITCH_LENGTH_M - fx) if attack_dir > 0 else fx
        return round(min(100.0, max(0.0, dist)), 1)

    def end_metres_from_line(self, x_px: float, attack_dir: int) -> float:
        """Same measurement, under the name the exported field uses."""
        return self.metres_from_line(x_px, attack_dir)

    def ends_in_touch(self, y_px: float) -> bool:
        """Did a path finish at a touchline?

        Proximity, not crossing: a kick traced without pointer capture stops
        at the image edge rather than passing through it. Kept for kicks only
        — a carry runs within this margin all game without going out, so the
        carry case tests crossed_touch() instead.
        """
        margin = config.TOUCH_MARGIN_M * self.px_per_m
        return y_px <= margin or y_px >= self.width_px - margin

    def crossed_touch(self, y_px: float) -> bool:
        """Is this point beyond a touchline — the ball actually out of play?"""
        return y_px <= 0 or y_px >= self.width_px

    def in_goal(self, x_px: float) -> bool:
        """Is this point past a try line, in either in-goal area?"""
        fx = self.field_x_m(x_px)
        return fx < 0 or fx > config.PITCH_LENGTH_M

    def crossed_dead_ball(self, x_px: float) -> bool:
        """Is this point past a dead-ball line, out the back of an in-goal?"""
        fx = self.field_x_m(x_px)
        return (fx <= -config.IN_GOAL_DEPTH_M
                or fx >= config.PITCH_LENGTH_M + config.IN_GOAL_DEPTH_M)

    def is_left_end(self, x_px: float) -> bool:
        """Which half of the pitch — i.e. which end's in-goal this point is at."""
        return self.field_x_m(x_px) < config.PITCH_LENGTH_M / 2

    def goal_line_px(self, attack_dir: int) -> float:
        """x of the try line a team attacking this way is kicking at."""
        return (self.left_try_line_px + config.PITCH_LENGTH_M * self.px_per_m
                if attack_dir > 0 else self.left_try_line_px)

    def between_posts(self, y_px: float) -> bool:
        """Is this y within the posts — the width test for a kick at goal?

        Height over the bar is invisible in a top-down trace, so a line whose
        crossing of the goal line falls between the uprights is taken as good.
        """
        half = config.GOAL_WIDTH_M / 2 * self.px_per_m
        return abs(y_px - self.width_px / 2) <= half

    def own_in_goal(self, x_px: float, attack_dir: int) -> bool:
        """Is this the in-goal a team attacking this way is defending?"""
        return self.is_left_end(x_px) == (attack_dir > 0)

    def drop_out_mark_x(self, left_end: bool) -> float:
        """The 22 a drop-out is taken from, for the in-goal at this end."""
        m = (config.TWENTY_TWO_M if left_end
             else config.PITCH_LENGTH_M - config.TWENTY_TWO_M)
        return self.left_try_line_px + m * self.px_per_m

    def five_m_mark_x(self, left_end: bool) -> float:
        """The 5m scrum mark in front of the in-goal at this end."""
        m = 5.0 if left_end else config.PITCH_LENGTH_M - 5.0
        return self.left_try_line_px + m * self.px_per_m

    def in_own_22(self, x_px: float, attack_dir: int) -> bool:
        """Is this point inside the 22 the attacking team is defending?"""
        return self.metres_from_line(x_px, attack_dir) >= (
            config.PITCH_LENGTH_M - config.TWENTY_TWO_M)

    def lineout_mark_x(self, kick_start_x_px: float, exit_x_px: float,
                       attack_dir: int) -> float:
        """Where the lineout is taken, per the kick-to-touch-on-the-full law.

        From inside your own 22 the ball may be kicked directly into touch and
        the ground is gained. From outside it, a direct kick to touch returns
        to the mark. The tool cannot see a bounce, so outside the 22 it assumes
        the ball went out on the full — the chip is clickable to say otherwise.
        """
        if self.in_own_22(kick_start_x_px, attack_dir):
            return exit_x_px
        return kick_start_x_px


def canonical_xy(field_x_m: float, field_y_m: float, flip: bool) -> tuple:
    """Fold a position into the first-half frame.

    Swapping ends at halftime is a 180-degree rotation of the pitch about its
    centre, so a second-half position maps (x, y) -> (LENGTH - x, WIDTH - y).
    Applying this to every exported coordinate keeps the whole match in one
    orientation: a team's attacking half, its heatmap, its penalty positions
    all aggregate across both halves instead of splitting to opposite ends.
    Metres-based fields (metres_gained, end_metres_from_line) are already
    orientation-independent — they read attack_dir — so only x/y need folding.
    """
    if not flip:
        return field_x_m, field_y_m
    return (config.PITCH_LENGTH_M - field_x_m, config.PITCH_WIDTH_M - field_y_m)
