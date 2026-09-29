# ping_widgets.py
"""
QPing widgets: TimeScaleWidget, PingGraphWidget, HostWidget.

Require PyQt6 and, for HostWidget.graph_widget, helpers from utils.
"""
import bisect
import builtins
from datetime import datetime, timedelta
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QSizePolicy
from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QPainterPath

from utils import compute_latency_stats, compute_recent_stats
from theme import palette


def _t(s):
    """Localization. Uses the current `_` from builtins (installed by
    setup_localization). If no translation is found, returns the source string."""
    f = getattr(builtins, '_', None)
    return f(s) if f is not None else s


# ---------- Y-axis helpers ----------

def _nice_scale_max(v):
    """Rounded-up upper bound of the Y axis. Small steps for LAN (< 10 ms)."""
    if v <= 0:
        return 10.0
    for c in (0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500,
              1000, 2000, 5000, 10000, 20000, 50000):
        if v <= c:
            return float(c)
    return float(int(v * 1.2))


def _pick_ymax(lats):
    """Y upper bound from the 95th percentile: single spikes do not stretch the scale."""
    if not lats:
        return 100.0
    s = sorted(lats)
    idx = max(0, min(len(s) - 1, int(round(len(s) * 0.95)) - 1))
    return _nice_scale_max(s[idx] * 1.15)


def _grid_values(ymax, density="normal"):
    """Grid line values.
    density: 'compact' — 2 lines, 'normal' — 3-5, 'expanded' — 6."""
    if ymax <= 0:
        return []
    if density == "compact":
        return [0.0, ymax]
    if density == "expanded":
        n = 6
        return [ymax * i / (n - 1) for i in range(n)]
    # normal
    if ymax <= 50:
        return [0.0, ymax / 2.0, ymax]
    if ymax <= 500:
        return [0.0, ymax / 4.0, ymax / 2.0, 3 * ymax / 4.0, ymax]
    return [0.0, ymax / 2.0, ymax]


def _format_ms(v):
    """Human-readable Y-axis label."""
    if v >= 1000:
        return f"{v / 1000:.1f}s"
    if v >= 10:
        return f"{int(round(v))}ms"
    if v >= 1:
        return f"{v:.1f}ms"
    return f"{v:.2f}ms"


# ---------- Time scale ----------

class TimeScaleWidget(QWidget):
    """Time scale widget for the graphs."""

    zoom_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setAutoFillBackground(True)
        self.start_time = None
        self.end_time = None
        self.zoom_start = None
        self.zoom_end = None
        self.is_setting_zoom_start = True
        self.zoom_periods = []
        self.indicator_pos = None
        self.zoom_factor = 1.0
        self._dragging = False
        self._drag_start_pos = None
        self._drag_current_pos = None
        self.left_gutter = 0
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.reset_zoom()

    def set_left_gutter(self, g):
        """Synchronize the left padding with PingGraphWidget.LEFT_GUTTER so
        that time labels sit exactly under the graph columns."""
        g = max(0, int(g))
        if g != self.left_gutter:
            self.left_gutter = g
            self.update()

    def reset_zoom(self):
        current_time = datetime.now()
        self.start_time = current_time - timedelta(hours=1)
        self.end_time = current_time
        self.zoom_start = None
        self.zoom_end = None
        self.zoom_periods = []
        self.is_setting_zoom_start = True
        self.indicator_pos = None
        self.zoom_factor = 1.0
        self.update()
        self.zoom_changed.emit()

    def auto_slide(self):
        now = datetime.now()
        follow_threshold = timedelta(seconds=5)
        if self.zoom_periods:
            last_start, last_end = self.zoom_periods[-1]
            if last_end < now - follow_threshold:
                return
            duration = last_end - last_start
            new_start = now - duration
            new_end = now
            self.zoom_periods[-1] = (new_start, new_end)
            self.zoom_start, self.zoom_end = new_start, new_end
        else:
            if self.end_time is None or self.start_time is None:
                return
            if self.end_time < now - follow_threshold:
                return
            duration = self.end_time - self.start_time
            self.start_time = now - duration
            self.end_time = now
        self.update()
        self.zoom_changed.emit()

    def add_zoom_period(self, start, end):
        if start and end:
            if start > end:
                start, end = end, start
            min_zoom_seconds = 5
            if (end - start).total_seconds() < min_zoom_seconds:
                end = start + timedelta(seconds=min_zoom_seconds)
            self.zoom_periods.append((start, end))
            self.zoom_start = start
            self.zoom_end = end
            self.indicator_pos = None
            self.update()
            self.zoom_changed.emit()

    def _plot_geometry(self):
        """Return (plot_x, plot_w) taking left_gutter into account."""
        w = self.width()
        px = self.left_gutter
        pw = max(1, w - self.left_gutter)
        return px, pw

    def wheelEvent(self, event):
        pos_x = event.position().x()
        plot_x, plot_w = self._plot_geometry()
        if plot_w <= 0:
            return
        rel_x = max(0, min(plot_w, pos_x - plot_x))
        if self.zoom_periods:
            current_start, current_end = self.zoom_periods[-1]
        else:
            current_start, current_end = self.start_time, self.end_time
        total_seconds = (current_end - current_start).total_seconds()
        cursor_time = current_start + timedelta(seconds=rel_x / plot_w * total_seconds)
        zoom_direction = 1 if event.angleDelta().y() > 0 else -1
        zoom_scale = 1.1 if zoom_direction > 0 else 0.9
        new_duration = total_seconds / zoom_scale
        new_duration = max(5.0, min(3600.0 * 24 * 30, new_duration))
        time_ratio = (cursor_time - current_start).total_seconds() / total_seconds
        new_start = cursor_time - timedelta(seconds=new_duration * time_ratio)
        new_end = new_start + timedelta(seconds=new_duration)
        if self.zoom_periods:
            self.zoom_periods[-1] = (new_start, new_end)
        else:
            self.zoom_periods.append((new_start, new_end))
        self.zoom_start, self.zoom_end = new_start, new_end
        self.update()
        self.zoom_changed.emit()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().x()
            self._dragging = True
            self._drag_start_pos = pos
            self._drag_current_pos = pos
            self.zoom_start = self.pos_to_time(pos)
            self.zoom_end = None
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self.reset_zoom()

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._drag_current_pos = event.position().x()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            end_pos = event.position().x()
            if self._drag_start_pos is None or abs(end_pos - self._drag_start_pos) < 3:
                self.zoom_start = None
                self.zoom_end = None
                self._drag_start_pos = None
                self._drag_current_pos = None
                self.update()
                return
            start_time = self.pos_to_time(self._drag_start_pos)
            end_time = self.pos_to_time(end_pos)
            self._drag_start_pos = None
            self._drag_current_pos = None
            self.zoom_start = None
            self.add_zoom_period(start_time, end_time)

    def pos_to_time(self, pos_x):
        plot_x, plot_w = self._plot_geometry()
        rel_x = max(0, min(plot_w, pos_x - plot_x))
        if self.zoom_start and self.zoom_end and self.zoom_periods:
            total_seconds = (self.zoom_end - self.zoom_start).total_seconds()
            return self.zoom_start + timedelta(seconds=rel_x / plot_w * total_seconds)
        else:
            total_seconds = (self.end_time - self.start_time).total_seconds()
            return self.start_time + timedelta(seconds=rel_x / plot_w * total_seconds)

    def paintEvent(self, event):
        p = palette()
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), p.clear_bg)

            plot_x, plot_w = self._plot_geometry()
            if plot_w <= 0:
                return

            if self.zoom_periods:
                visible_start, visible_end = self.zoom_periods[-1]
            else:
                visible_start, visible_end = self.start_time, self.end_time
            visible_seconds = (visible_end - visible_start).total_seconds()
            if visible_seconds <= 0:
                return

            pixels_per_second = plot_w / visible_seconds

            if visible_seconds <= 60:
                step = 5; format_str = "%H:%M:%S"
            elif visible_seconds <= 300:
                step = 15; format_str = "%H:%M:%S"
            elif visible_seconds <= 1800:
                step = 60; format_str = "%H:%M"
            elif visible_seconds <= 3600:
                step = 300; format_str = "%H:%M"
            elif visible_seconds <= 7200:
                step = 600; format_str = "%H:%M"
            elif visible_seconds <= 14400:
                step = 1800; format_str = "%H:%M"
            elif visible_seconds <= 28800:
                step = 3600; format_str = "%H:%M"
            elif visible_seconds <= 86400:
                step = 7200; format_str = "%H:%M"
            elif visible_seconds <= 172800:
                step = 10800; format_str = "%d.%m %H:%M"
            elif visible_seconds <= 86400 * 7:
                step = 21600; format_str = "%d.%m %H:%M"
            elif visible_seconds <= 86400 * 30:
                step = 86400; format_str = "%d.%m"
            else:
                step = 86400 * 3; format_str = "%d.%m"

            current = visible_start.replace(microsecond=0)
            if step < 60:
                current = current.replace(second=(current.second // step) * step)
            elif step < 3600:
                current = current.replace(minute=(current.minute // (step // 60)) * (step // 60), second=0)
            elif step < 86400:
                hours_step = step // 3600
                current = current.replace(hour=(current.hour // hours_step) * hours_step, minute=0, second=0)
            else:
                current = current.replace(hour=0, minute=0, second=0)

            painter.setFont(QFont("Arial", 8))
            while current <= visible_end:
                pos = plot_x + int((current - visible_start).total_seconds() * pixels_per_second)
                if plot_x <= pos <= self.width():
                    painter.setPen(p.time_axis)
                    painter.drawLine(pos, 0, pos, 15)
                    painter.drawText(QRect(pos - 50, 20, 100, 20),
                                     Qt.AlignmentFlag.AlignCenter,
                                     current.strftime(format_str))
                current += timedelta(seconds=step)

            if self._dragging and self._drag_start_pos is not None and self._drag_current_pos is not None:
                x1 = min(self._drag_start_pos, self._drag_current_pos)
                x2 = max(self._drag_start_pos, self._drag_current_pos)
                if x2 - x1 >= 1:
                    painter.setBrush(p.drag_fill)
                    painter.setPen(p.drag_stroke)
                    painter.drawRect(int(x1), 0, int(x2 - x1), self.height())
        finally:
            painter.end()


# ---------- Graph ----------

class PingGraphWidget(QWidget):
    """Ping graph: solid bars filling the space between checks,
    with a latency line on top. Long pauses are left blank."""

    context_menu_requested = pyqtSignal(str, QPoint)   # host, global_pos

    LEFT_GUTTER = 46
    TOP_MARGIN = 4
    BOTTOM_MARGIN = 2
    MIN_BAR_W = 3

    # Graph height presets
    HEIGHTS = {
        "compact": 50,
        "normal": 80,
        "expanded": 200,
    }

    def __init__(self, time_scale, host, parent=None):
        super().__init__(parent)
        self.time_scale = time_scale
        self.host = host
        self.setMouseTracking(True)
        self.history = []
        self.session_success_count = 0
        self.session_failure_count = 0
        self.app_start_time = None
        self._times_cache = []
        self._hover_pos = None
        self.recent_window_minutes = 5
        self.show_latency = True
        self._current_ymax = 100.0
        self.check_interval_ms = 1000
        self.height_mode = "normal"            # 'compact' | 'normal' | 'expanded'
        self._apply_height()

    def set_show_latency(self, on):
        self.show_latency = bool(on)
        self._apply_height()
        self.update()

    def set_graph_height_mode(self, mode):
        """Apply height mode: 'compact' | 'normal' | 'expanded'."""
        if mode not in self.HEIGHTS:
            mode = "normal"
        if mode != self.height_mode:
            self.height_mode = mode
            self._apply_height()
            self.update()

    def _apply_height(self):
        """Compute and set the minimum height.
        Compact without latency is even shorter (45)."""
        h = self.HEIGHTS.get(self.height_mode, 80)
        if self.height_mode == "compact" and not self.show_latency:
            h = 45
        self.setMinimumHeight(h)

    def set_check_interval(self, ms):
        ms = max(100, int(ms))
        if ms != self.check_interval_ms:
            self.check_interval_ms = ms
            self.update()

    def update_history(self, history, session_success_count, session_failure_count, app_start_time):
        self.history = history
        self.session_success_count = session_success_count
        self.session_failure_count = session_failure_count
        self.app_start_time = app_start_time
        self._times_cache = [t for t, _, _ in history]
        self._update_tooltip()
        self.repaint()

    def _update_tooltip(self):
        if self.app_start_time is None:
            return
        total_checks = self.session_success_count + self.session_failure_count
        failure_rate = (self.session_failure_count / total_checks * 100) if total_checks > 0 else 0
        stats = compute_latency_stats(self.history)
        recent = compute_recent_stats(self.history, minutes=self.recent_window_minutes)

        header = []
        if self._hover_pos is not None:
            point = self._point_at_x(self._hover_pos)
            if point is not None:
                ts, succ, lat = point
                status = _t("OK") if succ else _t("FAIL")
                if succ and lat is not None and lat >= 0:
                    lat_str = f"{lat:.1f} ms"
                else:
                    lat_str = "—"
                header.append(f"<b>{ts.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}</b>")
                header.append(_t("Status: <b>{}</b>   Latency: <b>{}</b>").format(status, lat_str))
                header.append("")

        lines = header + [
            _t("Start time: {}").format(self.app_start_time.strftime('%Y-%m-%d %H:%M:%S')),
            _t("Successful checks: {}").format(self.session_success_count),
            _t("Failed checks: {}").format(self.session_failure_count),
            _t("Failure rate: {:.1f}%").format(failure_rate),
            _t("Records in memory: {}").format(len(self.history)),
        ]

        if stats:
            lines.append(_t("--- Latency all time (ms) ---"))
            lines.append(f"Min: {stats['min']:.1f}   Avg: {stats['avg']:.1f}   Max: {stats['max']:.1f}")
            lines.append(f"Median: {stats['median']:.1f}   95th: {stats['p95']:.1f}")
            lines.append(_t("Jitter: {:.2f}").format(stats['stdev']))

        if recent:
            lines.append(_t("--- Last {} min (n={}) ---").format(
                self.recent_window_minutes, recent['count']))
            lines.append(f"Min: {recent['min']:.1f}   Avg: {recent['avg']:.1f}   Max: {recent['max']:.1f}")
            lines.append(_t("Jitter: {:.2f}").format(recent['stdev']))
        elif self.history:
            lines.append(_t("--- Last {} min ---").format(self.recent_window_minutes))
            lines.append(_t("No data"))

        self.setToolTip("<br>".join(lines))

    def _point_at_x(self, x):
        if not self.history or not self._times_cache:
            return None
        if self.time_scale.zoom_periods:
            visible_start, visible_end = self.time_scale.zoom_periods[-1]
        else:
            visible_start, visible_end = self.time_scale.start_time, self.time_scale.end_time
        visible_seconds = (visible_end - visible_start).total_seconds()
        width = self.width()
        if visible_seconds <= 0 or width <= 0:
            return None
        plot_x = self.LEFT_GUTTER if self.show_latency else 0
        plot_w = max(1, width - plot_x)
        rel_x = max(0, min(plot_w, x - plot_x))
        cursor_time = visible_start + timedelta(seconds=rel_x / plot_w * visible_seconds)
        times = self._times_cache
        idx = bisect.bisect_left(times, cursor_time)
        if idx == 0:
            return self.history[0]
        if idx >= len(times):
            return self.history[-1]
        before = self.history[idx - 1]
        after = self.history[idx]
        d_before = abs((before[0] - cursor_time).total_seconds())
        d_after = abs((after[0] - cursor_time).total_seconds())
        return before if d_before <= d_after else after

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            parent = self.parent()
            while parent and not isinstance(parent, HostWidget):
                parent = parent.parent()
            if parent:
                main_window = parent.parent()
                while main_window and not hasattr(main_window, 'move_host_to_queue_start'):
                    main_window = main_window.parent()
                if main_window:
                    main_window.move_host_to_queue_start(self.host)

    def mouseMoveEvent(self, event):
        pos_x = int(event.position().x())
        if self._hover_pos != pos_x:
            self._hover_pos = pos_x
            self._update_tooltip()
            self.update()

    def leaveEvent(self, event):
        if self._hover_pos is not None:
            self._hover_pos = None
            self._update_tooltip()
            self.update()
        super().leaveEvent(event)

    def contextMenuEvent(self, event):
        self.context_menu_requested.emit(self.host, event.globalPos())
        event.accept()

    def paintEvent(self, event):
        if not self.history or not self.time_scale.start_time:
            return

        p = palette()
        painter = QPainter(self)
        try:
            width = self.width()
            height = self.height()
            if width <= 4 or height <= 4:
                return

            # --- Visible window ---
            if self.time_scale.zoom_periods:
                visible_start, visible_end = self.time_scale.zoom_periods[-1]
            else:
                visible_start, visible_end = self.time_scale.start_time, self.time_scale.end_time
            visible_seconds = (visible_end - visible_start).total_seconds()
            if visible_seconds <= 0:
                return

            # --- Geometry ---
            if self.show_latency:
                plot_x = self.LEFT_GUTTER
                plot_y = self.TOP_MARGIN
                plot_w = max(1, width - self.LEFT_GUTTER)
                plot_h = max(1, height - self.TOP_MARGIN - self.BOTTOM_MARGIN)
            else:
                plot_x = 0
                plot_y = 0
                plot_w = width
                plot_h = height

            bottom_y = plot_y + plot_h
            pixels_per_second = plot_w / visible_seconds

            # --- Graph background (so empty regions are visibly distinct from bars) ---
            painter.fillRect(plot_x, plot_y, plot_w, plot_h, p.graph_bg)

            # --- Indices of visible records ---
            visible_idx = [i for i, rec in enumerate(self.history)
                           if visible_start <= rec[0] <= visible_end]
            if not visible_idx:
                return

            # --- Gap threshold ---
            # Estimate the per-host cadence from the MOST RECENT records,
            # not from the whole visible window. Otherwise, when the user has
            # changed the interval or added many hosts mid-session, the median
            # is dominated by the dense old history and recent sparse checks
            # are drawn as isolated bars ("gaps") even though monitoring ran
            # continuously.
            interval_s = max(0.1, self.check_interval_ms / 1000.0)
            recent = self.history[-30:]
            if len(recent) > 1:
                dts = []
                for k in range(1, len(recent)):
                    dt = (recent[k][0] - recent[k - 1][0]).total_seconds()
                    if dt > 0.01:
                        dts.append(dt)
                recent_median = sorted(dts)[len(dts) // 2] if dts else interval_s
            else:
                recent_median = interval_s
            # Threshold: a gap is real if it exceeds 4× the recent typical
            # interval. Floors: at least 5× the configured interval and 3 s.
            gap_threshold_s = max(4.0 * recent_median, 5.0 * interval_s, 3.0)

            def x_of(i):
                ts = self.history[i][0]
                return plot_x + int((ts - visible_start).total_seconds() * pixels_per_second)

            def dt_to(i, j):
                return abs((self.history[i][0] - self.history[j][0]).total_seconds())

            # --- Y axis (grid + labels) ---
            ymax = None
            if self.show_latency:
                lats = [self.history[i][2] for i in visible_idx
                        if self.history[i][1]
                        and self.history[i][2] is not None
                        and self.history[i][2] >= 0]
                ymax = _pick_ymax(lats)
                self._current_ymax = ymax

                painter.setFont(QFont("Arial", 7))
                for val in _grid_values(ymax, density=self.height_mode):
                    y = bottom_y - int(val / ymax * plot_h)
                    painter.setPen(QPen(p.graph_grid, 1, Qt.PenStyle.DotLine))
                    painter.drawLine(plot_x, y, width, y)
                    painter.setPen(p.text_dim)
                    painter.drawText(0, y - 8, plot_x - 6, 16,
                                     Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                                     _format_ms(val))

            # --- Full-height bars, "spliced" between adjacent checks ---
            success_rects = []
            failure_rects = []
            n_vis = len(visible_idx)

            for k, idx in enumerate(visible_idx):
                ts, succ, lat = self.history[idx]
                x_center = x_of(idx)

                # Left edge: midpoint with the previous record, if the gap is small.
                if k > 0:
                    prev_idx = visible_idx[k - 1]
                    if dt_to(idx, prev_idx) <= gap_threshold_s:
                        x_left = (x_of(prev_idx) + x_center) // 2
                    else:
                        x_left = x_center - self.MIN_BAR_W // 2
                else:
                    # Look at the previous record outside the window
                    if idx > 0 and dt_to(idx, idx - 1) <= gap_threshold_s:
                        x_left = plot_x
                    else:
                        x_left = x_center - self.MIN_BAR_W // 2

                # Right edge
                if k < n_vis - 1:
                    next_idx = visible_idx[k + 1]
                    if dt_to(idx, next_idx) <= gap_threshold_s:
                        x_right = (x_center + x_of(next_idx)) // 2
                    else:
                        x_right = x_center + self.MIN_BAR_W // 2 + 1
                else:
                    if idx < len(self.history) - 1 and dt_to(idx, idx + 1) <= gap_threshold_s:
                        x_right = plot_x + plot_w
                    else:
                        x_right = x_center + self.MIN_BAR_W // 2 + 1

                bw = max(1, x_right - x_left)
                rect = QRect(x_left, plot_y, bw, plot_h)
                if succ:
                    success_rects.append(rect)
                else:
                    failure_rects.append(rect)

            if success_rects:
                painter.setBrush(p.graph_ok)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRects(success_rects)
            if failure_rects:
                painter.setBrush(p.graph_fail)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRects(failure_rects)

            # --- Latency line on top of the bars, with breaks ---
            if self.show_latency and ymax:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(p.graph_avg, 1))
                path = QPainterPath()
                started = False
                prev_idx = None
                for idx in visible_idx:
                    ts, succ, lat = self.history[idx]
                    if not succ or lat is None or lat < 0:
                        if started:
                            painter.drawPath(path)
                            path = QPainterPath()
                            started = False
                        prev_idx = None
                        continue
                    x = x_of(idx)
                    y = bottom_y - int(min(lat, ymax) / ymax * plot_h)

                    if prev_idx is not None and dt_to(idx, prev_idx) > gap_threshold_s:
                        # Real gap
                        if started:
                            painter.drawPath(path)
                        path = QPainterPath()
                        path.moveTo(x, y)
                        started = True
                    elif not started:
                        path.moveTo(x, y)
                        started = True
                    else:
                        path.lineTo(x, y)
                    prev_idx = idx
                if started:
                    painter.drawPath(path)

            # --- Hover line ---
            if self._hover_pos is not None:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(p.graph_hover)
                painter.drawLine(self._hover_pos, 0, self._hover_pos, height)
        finally:
            painter.end()


# ---------- Host widget ----------

class HostWidget(QWidget):
    """Widget that displays information about a single host."""

    context_menu_requested = pyqtSignal(str, QPoint)   # host, global_pos

    def __init__(self, host, time_scale, app_start_time, category="Default"):
        super().__init__()
        self.host = host
        self.time_scale = time_scale
        self.category = category
        self.ping_history = []
        self.loaded_days = set()
        self.consecutive_failures = 0
        self.check_type = 'icmp'
        self.port = None
        self.session_success_count = 0
        self.session_failure_count = 0
        self.app_start_time = app_start_time
        self.retention_hours = 48
        self.last_saved_time = None
        self.last_notified = None
        self.was_down = False
        self.disabled = False
        self.muted = False
        self._last_prune = None
        self._prune_interval_sec = 300

        layout = QVBoxLayout()
        self.setLayout(layout)
        self.host_label = QLabel()
        self.host_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.update_host_label()
        self.graph_widget = PingGraphWidget(time_scale, host, self)
        self.graph_widget.update_history(
            self.ping_history, self.session_success_count, self.session_failure_count, self.app_start_time
        )
        self.graph_widget.context_menu_requested.connect(self.context_menu_requested)
        layout.addWidget(self.host_label)
        layout.addWidget(self.graph_widget)

    def get_check_tag(self):
        if self.check_type == 'tcp' and self.port is not None:
            return f"[p:{self.port}]"
        return "[i]"

    def update_host_label(self):
        p = palette()
        txt = f"{self.host} {self.get_check_tag()}"
        if self.disabled:
            self.host_label.setText(f"{txt}  [disabled]")
            self.host_label.setStyleSheet(f"color: {p.text_disabled.name()};")
        elif self.muted:
            self.host_label.setText(f"{txt}  [muted]")
            self.host_label.setStyleSheet(f"color: {p.text_muted.name()};")
        else:
            self.host_label.setText(txt)
            self.host_label.setStyleSheet("")

    def set_check_type(self, check_type, port=None):
        self.check_type = check_type
        self.port = port
        self.update_host_label()

    def set_disabled(self, disabled):
        self.disabled = disabled
        self.update_host_label()

    def set_muted(self, muted):
        self.muted = bool(muted)
        self.update_host_label()

    def update_status(self, success, latency, current_time):
        if not success:
            self.consecutive_failures += 1
            self.session_failure_count += 1
        else:
            self.consecutive_failures = 0
            self.session_success_count += 1
        self.ping_history.append((current_time, success, float(latency)))

        if (self._last_prune is None
                or (current_time - self._last_prune).total_seconds() >= self._prune_interval_sec):
            cutoff_time = current_time - timedelta(hours=self.retention_hours)
            self.ping_history = [h for h in self.ping_history if h[0] > cutoff_time]
            self._last_prune = current_time

        self.graph_widget.update_history(
            self.ping_history, self.session_success_count,
            self.session_failure_count, self.app_start_time
        )
        return self.consecutive_failures

    def prune_to_retention(self):
        if not self.ping_history:
            return
        cutoff = datetime.now() - timedelta(hours=self.retention_hours)
        self.ping_history = [h for h in self.ping_history if h[0] > cutoff]
        self._last_prune = datetime.now()
        self.graph_widget.update_history(
            self.ping_history, self.session_success_count,
            self.session_failure_count, self.app_start_time
        )
