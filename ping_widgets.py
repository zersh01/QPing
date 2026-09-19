# ping_widgets.py
"""
Виджеты QPing: TimeScaleWidget, PingGraphWidget, HostWidget.

Требуют PyQt6 и, для HostWidget.graph_widget, функций из utils.
"""
import bisect
import builtins
from datetime import datetime, timedelta
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt6.QtCore import Qt, QRect, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QFont

from utils import compute_latency_stats, compute_recent_stats

def _t(s):
    """Локализация. Берёт актуальный `_` из builtins (установлен setup_localization).
    Если перевода нет — возвращает исходную строку."""
    f = getattr(builtins, '_', None)
    return f(s) if f is not None else s

class TimeScaleWidget(QWidget):
    """Виджет временной шкалы для графиков."""

    zoom_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.setMouseTracking(True)
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
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.reset_zoom()

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

    def wheelEvent(self, event):
        pos_x = event.position().x()
        width = self.width()
        if self.zoom_periods:
            current_start, current_end = self.zoom_periods[-1]
        else:
            current_start, current_end = self.start_time, self.end_time
        total_seconds = (current_end - current_start).total_seconds()
        cursor_time = current_start + timedelta(seconds=pos_x / width * total_seconds)
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
            # Если пользователь почти не двигал мышь — считаем это кликом и отменяем.
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
        width = self.width()
        if self.zoom_start and self.zoom_end and self.zoom_periods:
            total_seconds = (self.zoom_end - self.zoom_start).total_seconds()
            return self.zoom_start + timedelta(seconds=pos_x / width * total_seconds)
        else:
            total_seconds = (self.end_time - self.start_time).total_seconds()
            return self.start_time + timedelta(seconds=pos_x / width * total_seconds)

    def paintEvent(self, event):
        painter = QPainter(self)
        width = self.width()
        painter.setPen(QColor(Qt.GlobalColor.black))
        painter.setFont(QFont("Arial", 8))
        if self.zoom_periods:
            visible_start, visible_end = self.zoom_periods[-1]
        else:
            visible_start, visible_end = self.start_time, self.end_time
        visible_seconds = (visible_end - visible_start).total_seconds()
        if visible_seconds <= 0:
            return
        pixels_per_second = width / visible_seconds

        if visible_seconds <= 60:                # до 1 мин
            step = 5; format_str = "%H:%M:%S"
        elif visible_seconds <= 300:             # до 5 мин
            step = 15; format_str = "%H:%M:%S"
        elif visible_seconds <= 1800:            # до 30 мин
            step = 60; format_str = "%H:%M"
        elif visible_seconds <= 3600:            # до 1 часа
            step = 300; format_str = "%H:%M"
        elif visible_seconds <= 7200:            # до 2 часов
            step = 600; format_str = "%H:%M"
        elif visible_seconds <= 14400:           # до 4 часов
            step = 1800; format_str = "%H:%M"
        elif visible_seconds <= 28800:           # до 8 часов
            step = 3600; format_str = "%H:%M"
        elif visible_seconds <= 86400:           # до 24 часов
            step = 7200; format_str = "%H:%M"
        elif visible_seconds <= 172800:          # до 48 часов
            step = 10800; format_str = "%d.%m %H:%M"
        elif visible_seconds <= 86400 * 7:       # до недели
            step = 21600; format_str = "%d.%m %H:%M"
        elif visible_seconds <= 86400 * 30:      # до месяца
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

        while current <= visible_end:
            pos = int((current - visible_start).total_seconds() * pixels_per_second)
            if 0 <= pos <= width:
                painter.drawLine(pos, 0, pos, 15)
                painter.drawText(QRect(pos - 50, 20, 100, 20),
                                 Qt.AlignmentFlag.AlignCenter,
                                 current.strftime(format_str))
            current += timedelta(seconds=step)

        # Выделение при перетаскивании
        if self._dragging and self._drag_start_pos is not None and self._drag_current_pos is not None:
            x1 = min(self._drag_start_pos, self._drag_current_pos)
            x2 = max(self._drag_start_pos, self._drag_current_pos)
            if x2 - x1 >= 1:
                painter.setBrush(QColor(30, 120, 200, 60))
                painter.setPen(QColor(30, 120, 200, 200))
                painter.drawRect(int(x1), 0, int(x2 - x1), self.height())


class PingGraphWidget(QWidget):
    """Виджет для отображения графика ping."""

    BAR_WIDTH = 4

    def __init__(self, time_scale, host, parent=None):
        super().__init__(parent)
        self.time_scale = time_scale
        self.host = host
        self.setMinimumHeight(60)
        self.setMouseTracking(True)          # нужно для hover без нажатия
        self.history = []
        self.session_success_count = 0
        self.session_failure_count = 0
        self.app_start_time = None
        self._times_cache = []               # кэш времён для бинарного поиска
        self._hover_pos = None               # X-координата курсора или None
        self.recent_window_minutes = 5       # скользящее окно для jitter

    def update_history(self, history, session_success_count, session_failure_count, app_start_time):
        self.history = history
        self.session_success_count = session_success_count
        self.session_failure_count = session_failure_count
        self.app_start_time = app_start_time
        # Кэш времён — для быстрого поиска ближайшей точки при hover.
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
        """Возвращает (timestamp, success, latency) ближайшей записи к X-координате
        или None, если истории нет."""
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
        # X → time
        cursor_time = visible_start + timedelta(seconds=x / width * visible_seconds)
        # Бинарный поиск ближайшей записи
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
            # Ищем HostWidget (класс ниже в этом же файле)
            parent = self.parent()
            while parent and not isinstance(parent, HostWidget):
                parent = parent.parent()
            if parent:
                # Ищем главное окно (PingMonitor) — по наличию метода,
                # чтобы не тянуть импорт из main.py (иначе цикл).
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


    def paintEvent(self, event):
        if not self.history or not self.time_scale.start_time:
            return
        painter = QPainter(self)
        width = self.width()
        height = self.height()
        if self.time_scale.zoom_periods:
            visible_start, visible_end = self.time_scale.zoom_periods[-1]
        else:
            visible_start, visible_end = self.time_scale.start_time, self.time_scale.end_time
        visible_seconds = (visible_end - visible_start).total_seconds()
        if visible_seconds <= 0:
            return
        pixels_per_second = width / visible_seconds
        bar_width = max(1, min(self.BAR_WIDTH, int(pixels_per_second * 1)))
        success_rects = []
        failure_rects = []
        last_success_pos = -1
        last_failure_pos = -1
        for ts, succ, _lat in self.history:
            if ts < visible_start or ts > visible_end:
                continue
            pos = int((ts - visible_start).total_seconds() * pixels_per_second)
            if succ:
                if pos == last_success_pos:
                    continue
                last_success_pos = pos
                success_rects.append(QRect(pos - bar_width // 2, 0, bar_width, height))
            else:
                if pos == last_failure_pos:
                    continue
                last_failure_pos = pos
                failure_rects.append(QRect(pos - bar_width // 2, 0, bar_width, height))
        if success_rects:
            painter.setBrush(QColor("#4CAF50"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRects(success_rects)
        if failure_rects:
            painter.setBrush(QColor("#F44336"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRects(failure_rects)
        if self._hover_pos is not None:
            painter.setPen(QColor(60, 60, 60, 160))
            painter.drawLine(self._hover_pos, 0, self._hover_pos, height)


class HostWidget(QWidget):
    """Виджет для отображения информации о хосте."""

    def __init__(self, host, time_scale, app_start_time, category="Default"):
        super().__init__()
        self.host = host
        self.time_scale = time_scale
        self.category = category
        self.ping_history = []
        self.consecutive_failures = 0
        self.check_type = 'icmp'
        self.port = None
        self.session_success_count = 0
        self.session_failure_count = 0
        self.app_start_time = app_start_time
        self.retention_hours = 48       # обрезать старше часов
        self.last_saved_time = None
        self.last_notified = None
        self.was_down = False
        self.disabled = False
        self._last_prune = None          
        self._prune_interval_sec = 300   # обрезать раз в 5 минут

        layout = QVBoxLayout()
        self.setLayout(layout)
        self.host_label = QLabel()
        self.host_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.update_host_label()
        self.graph_widget = PingGraphWidget(time_scale, host, self)
        self.graph_widget.update_history(
            self.ping_history, self.session_success_count, self.session_failure_count, self.app_start_time
        )
        layout.addWidget(self.host_label)
        layout.addWidget(self.graph_widget)

    def get_check_tag(self):
        if self.check_type == 'tcp' and self.port is not None:
            return f"[p:{self.port}]"
        return "[i]"

    def update_host_label(self):
        txt = f"{self.host} {self.get_check_tag()}"
        if self.disabled:
            self.host_label.setText(f"{txt}  [disabled]")
            self.host_label.setStyleSheet("color: gray;")
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
