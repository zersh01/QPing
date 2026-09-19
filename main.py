# main.py
"""
QPing — главное окно. Запуск приложения.

"""
APP_VERSION = "2.0"

import sys
import json
import os
import subprocess

from datetime import datetime, timedelta
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget,
    QTreeWidgetItem, QLineEdit, QLabel, QMessageBox, QInputDialog, QSlider,
    QScrollArea, QFrame, QMenu, QPushButton, QSystemTrayIcon,
    QFileDialog, QDialog, QComboBox, QDialogButtonBox, QTextEdit,
    QSpinBox, QFormLayout, QCheckBox, QTabWidget, QGraphicsOpacityEffect
)
from PyQt6.QtCore import (
    Qt, QSettings, QTimer, QThreadPool, QPropertyAnimation,
    QEasingCurve, pyqtSignal, pyqtSlot, QObject, QRunnable
)
from PyQt6.QtGui import QColor, QFont, QIcon, QPixmap, QAction, QKeySequence, QPainter

from ping_manager import PingManager, PingWorker, has_fping
from ping_widgets import TimeScaleWidget, HostWidget
from utils import (
    CONFIG_DIR, HISTORY_DIR, HOOKS_DIR_DEFAULT, OLD_HISTORY_FILE,
    setup_localization, read_bool_setting, read_int_setting, host_safe_name,
    detect_import_format, parse_ansible_ini, parse_ansible_yaml,
    parse_hosts_file, parse_plain_list, parse_backup, build_backup,
)


# ---------- Асинхронное сохранение ----------

class _SaveSignals(QObject):
    finished = pyqtSignal(dict)


class SaveWorker(QRunnable):
    def __init__(self, snapshot):
        super().__init__()
        self.snapshot = snapshot
        self.signals = _SaveSignals()

    @pyqtSlot()
    def run(self):
        result = {}
        for host, data in self.snapshot.items():
            latest = None
            try:
                host_dir = data['dir']
                os.makedirs(host_dir, exist_ok=True)
                with open(os.path.join(host_dir, "meta.json"), 'w') as mf:
                    json.dump(data['meta'], mf, indent=2)
                by_day = {}
                for t, s, lat in data['records']:
                    key = t.strftime("%Y-%m-%d")
                    by_day.setdefault(key, []).append((t, s, lat))
                    if latest is None or t > latest:
                        latest = t
                for day, recs in by_day.items():
                    path = os.path.join(host_dir, f"{day}.jsonl")
                    with open(path, 'a') as f:
                        for t, s, lat in recs:
                            f.write(json.dumps([t.isoformat(), s, lat]) + "\n")
                result[host] = latest
            except Exception as e:
                print(f"[save] error for {host}: {e}")
                result[host] = None
        self.signals.finished.emit(result)


# ---------- Хуки ----------

class HookWorker(QRunnable):
    def __init__(self, script_path, env_vars):
        super().__init__()
        self.script_path = script_path
        self.env_vars = env_vars

    @pyqtSlot()
    def run(self):
        try:
            env = os.environ.copy()
            env.update(self.env_vars)
            subprocess.run(
                [self.script_path],
                timeout=30,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception as e:
            print(f"[hook] {self.script_path}: {e}")


# ---------- Фоновый загрузчик истории ----------

class _LoadSignals(QObject):
    finished = pyqtSignal(dict)   # {host: {'records': [...], 'latest_time': datetime|None}}


def read_history_files(host_dir, hours_limit=None):
    """Читает все .jsonl в host_dir. hours_limit=None → без ограничения.
    Возвращает (records, latest_time). Не зависит от self, пригодна для потока."""
    if hours_limit is None:
        cutoff = None
    else:
        cutoff = datetime.now() - timedelta(hours=hours_limit)

    records = []
    latest_time = None
    try:
        entries = os.listdir(host_dir)
    except Exception as e:
        print(f"Error listing {host_dir}: {e}")
        return records, latest_time

    for fname in entries:
        if not fname.endswith(".jsonl"):
            continue
        day_str = fname[:-6]
        try:
            d = datetime.strptime(day_str, "%Y-%m-%d")
        except ValueError:
            continue
        if cutoff is not None and d + timedelta(days=1) < cutoff:
            continue
        path = os.path.join(host_dir, fname)
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                        t = datetime.fromisoformat(parsed[0])
                        s = bool(parsed[1])
                        lat = float(parsed[2]) if len(parsed) > 2 else (-1.0 if not s else 0.0)
                    except Exception:
                        continue
                    if cutoff is not None and t < cutoff:
                        continue
                    records.append((t, s, lat))
                    if latest_time is None or t > latest_time:
                        latest_time = t
        except Exception as e:
            print(f"Error reading {path}: {e}")

    records.sort(key=lambda x: x[0])
    return records, latest_time


class HistoryLoadWorker(QRunnable):
    """Фоновая загрузка полной истории для всех хостов."""

    def __init__(self, host_dirs, retention_hours):
        super().__init__()
        self.host_dirs = dict(host_dirs)         # {host: host_dir}
        self.retention_hours = retention_hours
        self.signals = _LoadSignals()

    @pyqtSlot()
    def run(self):
        result = {}
        for host, hd in self.host_dirs.items():
            records, latest = read_history_files(hd, hours_limit=self.retention_hours)
            result[host] = {'records': records, 'latest_time': latest}
        self.signals.finished.emit(result)

# ---------- Главное окно ----------

class PingMonitor(QMainWindow):
    def __init__(self):
        super().__init__()
        os.makedirs(CONFIG_DIR, exist_ok=True)
        os.makedirs(HISTORY_DIR, exist_ok=True)
        os.makedirs(HOOKS_DIR_DEFAULT, exist_ok=True)

        self.settings = QSettings("QPing", "QPing")
        self._migrate_history_if_needed()

        self.language = self.settings.value("language", "ru")
        self._ = setup_localization(self.language)
        self.setWindowTitle(self._("QPing Monitor"))
        self.setGeometry(100, 100, 1200, 700)

        self.app_start_time = datetime.now()
        self.notifications_enabled = read_bool_setting(self.settings, "notifications_enabled", True)
        self.is_quitting = False
        self.filter_failed = read_bool_setting(self.settings, "filter_failed", False)
        self.minimize_on_escape = read_bool_setting(self.settings, "minimize_on_escape", True)

        self.retention_hours = max(1, read_int_setting(self.settings, "retention_hours", 48))

        self.alerts_after_failures = max(1, read_int_setting(self.settings, "alerts_after_failures", 2))
        self.alert_reminder_minutes = max(1, read_int_setting(self.settings, "alert_reminder_minutes", 5))
        self.notify_on_recovery = read_bool_setting(self.settings, "notify_on_recovery", True)

        self.cleanup_enabled = read_bool_setting(self.settings, "cleanup_enabled", False)
        self.cleanup_days = max(1, read_int_setting(self.settings, "cleanup_days", 30))

        self.hooks_enabled = read_bool_setting(self.settings, "hooks_enabled", False)
        self.hooks_dir = self.settings.value("hooks_dir", HOOKS_DIR_DEFAULT, type=str) or HOOKS_DIR_DEFAULT
        os.makedirs(self.hooks_dir, exist_ok=True)

        self.fping_batch_size = max(1, read_int_setting(self.settings, "fping_batch_size", 5))

        self.search_text = ""

        self.categories_list = self.settings.value("categories", ["Default"], type=list)
        if "Default" not in self.categories_list:
            self.categories_list.append("Default")

        self.green_icon = self.create_icon("#4CAF50")
        self.yellow_icon = self.create_icon("#FFEB3B")
        self.red_icon = self.create_icon("#F44336")
        self.setWindowIcon(self.green_icon)
        self._current_icon = self.green_icon

        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.green_icon)
        self.tray_icon.setVisible(True)
        self.tray_icon.activated.connect(self.tray_icon_activated)

        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowMinimizeButtonHint | Qt.WindowType.WindowCloseButtonHint)

        self.host_widgets = {}
        self.host_check_types = {}
        self.highlight_animation = None

        self.icmp_queue = []
        self.tcp_queue = []
        self.icmp_idx = 0
        self.tcp_idx = 0
        self._highlighted_hosts = []

        self.parking_widget = QWidget()
        self.parking_widget.hide()

        self.time_scale = TimeScaleWidget(self)
        self.time_scale.zoom_changed.connect(self.update_all_graphs)
        self.time_scale.zoom_changed.connect(self.on_zoom_changed)

        self.host_list = QTreeWidget()
        self.host_list.setHeaderHidden(True)
        self.host_list.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
        self.host_list.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.host_list.setDragEnabled(True)
        self.host_list.setAcceptDrops(True)
        self.host_list.setDropIndicatorShown(True)
        self.host_list.itemDoubleClicked.connect(self.scroll_to_host_widget)
        self.host_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.host_list.customContextMenuRequested.connect(self.show_host_context_menu)
        self.host_list.model().rowsMoved.connect(self.handle_host_moved)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)

        saved_interval = read_int_setting(self.settings, "interval", 500)

        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(10)
        self.hook_pool = QThreadPool()
        self.hook_pool.setMaxThreadCount(2)

        self._save_in_progress = False
        self._history_fully_loaded = False
        self._history_loading_in_progress = False

        self.ping_manager = PingManager(saved_interval, self.thread_pool)
        self.ping_manager.ping_result.connect(self.handle_ping_result)

        self.ping_timer = QTimer()
        self.ping_timer.timeout.connect(self.ping_tick)

        self.autosave_timer = QTimer()
        self.autosave_timer.timeout.connect(self.save_data)
        self.autosave_timer.start(60000)

        self.slide_timer = QTimer()
        self.slide_timer.timeout.connect(self.time_scale.auto_slide)
        self.slide_timer.start(1000)

        self.cleanup_timer = QTimer()
        self.cleanup_timer.timeout.connect(self.run_auto_cleanup)
        self.cleanup_timer.start(24 * 60 * 60 * 1000)

        self.setup_ui()
        # Окно показывается сразу, данные догружаются после запуска event-loop.
        QTimer.singleShot(0, self.load_data)
        self.interval_slider.setValue(saved_interval)
        self.update_interval(saved_interval)
        self.time_scale.reset_zoom()

        if self.cleanup_enabled:
            QTimer.singleShot(5000, self.run_auto_cleanup)

    # ---------- Клавиши ----------

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        if key == Qt.Key.Key_Escape:
            fw = QApplication.focusWidget()
            # Если фокус в текстовом поле и там есть текст — очищаем поле
            if isinstance(fw, QLineEdit) and fw.text():
                fw.clear()
                event.accept()
                return
            if self.minimize_on_escape:
                self.hide()
                event.accept()
                return
        if key == Qt.Key.Key_Delete:
            self._on_delete_shortcut()
            event.accept()
            return
        if key == Qt.Key.Key_F2:
            self._on_f2_shortcut()
            event.accept()
            return
        if key == Qt.Key.Key_N and (mods & Qt.KeyboardModifier.ControlModifier):
            self.host_input.setFocus()
            self.host_input.selectAll()
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_delete_shortcut(self):
        sel = [i for i in self.host_list.selectedItems() if i.parent() is not None]
        hosts = [i.data(0, Qt.ItemDataRole.UserRole) for i in sel]
        if hosts:
            self.delete_hosts(hosts)

    def _on_f2_shortcut(self):
        sel = [i for i in self.host_list.selectedItems() if i.parent() is not None]
        if len(sel) == 1:
            self.edit_host(sel[0].data(0, Qt.ItemDataRole.UserRole))

    # ---------- Миграция ----------

    def _migrate_history_if_needed(self):
        if not os.path.exists(OLD_HISTORY_FILE):
            return
        try:
            with open(OLD_HISTORY_FILE, 'r') as f:
                old_hist = json.load(f)
            for host, data in old_hist.items():
                host_dir = os.path.join(HISTORY_DIR, host_safe_name(host))
                os.makedirs(host_dir, exist_ok=True)
                meta = {"host": host,
                        "check_type": data.get('check_type', {'type': 'icmp', 'port': None})}
                with open(os.path.join(host_dir, "meta.json"), 'w') as mf:
                    json.dump(meta, mf, indent=2)
                by_day = {}
                for item in data.get('records', []):
                    try:
                        t = datetime.fromisoformat(item[0])
                        s = bool(item[1])
                        lat = float(item[2]) if len(item) > 2 else (-1.0 if not s else 0.0)
                    except Exception:
                        continue
                    key = t.strftime("%Y-%m-%d")
                    by_day.setdefault(key, []).append((t, s, lat))
                for day, recs in by_day.items():
                    path = os.path.join(host_dir, f"{day}.jsonl")
                    with open(path, 'w') as jf:
                        for t, s, lat in recs:
                            jf.write(json.dumps([t.isoformat(), s, lat]) + "\n")
            try:
                os.rename(OLD_HISTORY_FILE, OLD_HISTORY_FILE + ".migrated")
            except OSError:
                pass
            print(f"[migrate] History migrated from {OLD_HISTORY_FILE}")
        except Exception as e:
            print(f"[migrate] History migration failed: {e}")

    def _host_dir(self, host):
        return os.path.join(HISTORY_DIR, host_safe_name(host))

    def create_icon(self, color):
        """Иконка трея: через QPainter."""
        icon = QIcon()
        for size in (16, 22, 24, 32, 48, 64, 128, 256):
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            margin = max(1, size // 16)
            painter.setBrush(QColor(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(margin, margin,
                                size - 2 * margin, size - 2 * margin)
            if size >= 22:
                painter.setPen(QColor("white"))
                font = QFont("Arial", int(size * 0.6), QFont.Weight.Bold)
                painter.setFont(font)
                painter.drawText(pixmap.rect(),
                                 Qt.AlignmentFlag.AlignCenter, "Q")
            painter.end()
            icon.addPixmap(pixmap)
        return icon

    # ---------- Окно ----------

    def quit_application(self):
        self.is_quitting = True
        self._save_data_sync()
        QApplication.quit()

    def closeEvent(self, event):
        if self.is_quitting:
            event.accept()
        else:
            self.save_data()
            event.ignore()
            self.hide()

    def restore_window(self):
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.setWindowState(
            (self.windowState() & ~Qt.WindowState.WindowMinimized)
            | Qt.WindowState.WindowActive
        )
        self.raise_()
        self.activateWindow()

    def tray_icon_activated(self, reason):
        # На разных DE приходит либо Trigger (одиночный клик), либо DoubleClick.
        if reason in (QSystemTrayIcon.ActivationReason.DoubleClick,
                      QSystemTrayIcon.ActivationReason.Trigger):
            self.restore_window()

    # ---------- Навигация / drag ----------

    def scroll_to_host_widget(self, item, column):
        host = item.data(0, Qt.ItemDataRole.UserRole)
        if host and host in self.host_widgets:
            widget = self.host_widgets[host]
            self.scroll_area.ensureWidgetVisible(widget)
            self.start_highlight_animation(widget)

    def start_highlight_animation(self, widget):
        if self.highlight_animation:
            self.highlight_animation.stop()
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        self.highlight_animation = QPropertyAnimation(effect, b"opacity")
        self.highlight_animation.setDuration(1000)
        self.highlight_animation.setLoopCount(2)
        self.highlight_animation.setStartValue(0.3)
        self.highlight_animation.setEndValue(1.0)
        self.highlight_animation.setEasingCurve(QEasingCurve.Type.OutQuad)
        self.highlight_animation.start()

        def cleanup():
            widget.setGraphicsEffect(None)
            self.highlight_animation = None
        self.highlight_animation.finished.connect(cleanup)

    def handle_host_moved(self, parent, start, end, destination, row):
        QTimer.singleShot(0, self._finalize_host_moved)

    def _finalize_host_moved(self):
        # 1. Обновляем категории.
        for i in range(self.host_list.topLevelItemCount()):
            cat_item = self.host_list.topLevelItem(i)
            cat_name = cat_item.data(0, Qt.ItemDataRole.UserRole)
            for j in range(cat_item.childCount()):
                child_item = cat_item.child(j)
                host_name = child_item.data(0, Qt.ItemDataRole.UserRole)
                if host_name in self.host_widgets:
                    self.host_widgets[host_name].category = cat_name

        # 2. Пересобираем self.host_widgets в порядке дерева.
        new_order = {}
        for i in range(self.host_list.topLevelItemCount()):
            cat_item = self.host_list.topLevelItem(i)
            for j in range(cat_item.childCount()):
                child_item = cat_item.child(j)
                h = child_item.data(0, Qt.ItemDataRole.UserRole)
                if h and h in self.host_widgets:
                    new_order[h] = self.host_widgets[h]
        for h, w in self.host_widgets.items():
            if h not in new_order:
                new_order[h] = w
        self.host_widgets = new_order

        self.update_host_queue()
        self.reorder_graphs()
        self.save_data()
        self.apply_filter()

    # ---------- Раскладка ----------

    def add_category_separator(self, category):
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        label = QLabel(f"[{category}]")
        label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        label.setStyleSheet("padding: 5px;")
        c = QWidget()
        cl = QHBoxLayout()
        cl.addWidget(label)
        cl.addWidget(sep)
        c.setLayout(cl)
        return c

    def reorder_graphs(self):
        while self.right_panel_layout.count() > 0:
            item = self.right_panel_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(self.parking_widget)
        for category in self.sorted_categories():
            cat_widgets = [w for w in self.host_widgets.values() if w.category == category]
            has_visible = False
            if self.filter_failed:
                has_visible = any((len(w.ping_history) > 0 and not w.ping_history[-1][1]) for w in cat_widgets)
            else:
                has_visible = True
            if not has_visible:
                continue
            self.right_panel_layout.addWidget(self.add_category_separator(category))

            def traverse(parent_item):
                for i in range(parent_item.childCount()):
                    child = parent_item.child(i)
                    host = child.data(0, Qt.ItemDataRole.UserRole)
                    if host and host in self.host_widgets and self.host_widgets[host].category == category:
                        w = self.host_widgets[host]
                        if self.filter_failed:
                            if len(w.ping_history) > 0 and not w.ping_history[-1][1]:
                                self.right_panel_layout.addWidget(w)
                        else:
                            self.right_panel_layout.addWidget(w)
            for i in range(self.host_list.topLevelItemCount()):
                ci = self.host_list.topLevelItem(i)
                if ci.data(0, Qt.ItemDataRole.UserRole) == category:
                    traverse(ci)

    def move_host_to_queue_start(self, host):
        if host in self.icmp_queue:
            self.icmp_queue.remove(host)
            self.icmp_queue.insert(0, host)
            self.icmp_idx = 0
        elif host in self.tcp_queue:
            self.tcp_queue.remove(host)
            self.tcp_queue.insert(0, host)
            self.tcp_idx = 0
        self.ping_tick()

    # ---------- UI ----------

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout()
        central.setLayout(layout)

        menu_bar = self.menuBar()

        # --- Application ---
        self.menu_app = menu_bar.addMenu(self._("Application"))

        self.action_settings = QAction(self._("Settings..."), self)
        self.action_settings.triggered.connect(self.show_settings_dialog)
        self.menu_app.addAction(self.action_settings)

        self.action_export = QAction(self._("Export Hosts..."), self)
        self.action_export.triggered.connect(self.export_hosts_to_file)
        self.menu_app.addAction(self.action_export)

        self.action_import = QAction(self._("Import Hosts..."), self)
        self.action_import.triggered.connect(self.import_hosts_from_file)
        self.menu_app.addAction(self.action_import)

        self.menu_app.addSeparator()

        self.action_close = QAction(self._("Close"), self)
        self.action_close.setShortcut(QKeySequence("Ctrl+W"))
        self.action_close.triggered.connect(self.close)
        self.menu_app.addAction(self.action_close)

        self.menu_app.addSeparator()

        self.action_quit = QAction(self._("Quit"), self)
        self.action_quit.setShortcut(QKeySequence("Ctrl+Q"))
        self.action_quit.triggered.connect(self.quit_application)
        self.menu_app.addAction(self.action_quit)

        # --- Help ---
        self.menu_help = menu_bar.addMenu(self._("Help"))
        self.action_help = QAction(self._("User Guide"), self)
        self.action_help.triggered.connect(self.show_help)
        self.menu_help.addAction(self.action_help)

        # --- Language ---
        self.menu_lang = menu_bar.addMenu(self._("Language"))
        self.action_lang_ru = QAction("Русский", self)
        self.action_lang_ru.triggered.connect(lambda: self.change_language("ru"))
        self.menu_lang.addAction(self.action_lang_ru)
        self.action_lang_en = QAction("English", self)
        self.action_lang_en.triggered.connect(lambda: self.change_language("en"))
        self.menu_lang.addAction(self.action_lang_en)

        # --- Tray menu ---
        self.tray_menu = QMenu()
        self.tray_action_restore = QAction(self._("Restore"), self)
        self.tray_action_restore.triggered.connect(self.restore_window)
        self.tray_menu.addAction(self.tray_action_restore)
        self.tray_action_quit = QAction(self._("Quit"), self)
        self.tray_action_quit.triggered.connect(self.quit_application)
        self.tray_menu.addAction(self.tray_action_quit)
        self.tray_icon.setContextMenu(self.tray_menu)

        # --- Control panel ---
        control_panel = QWidget()
        cl = QHBoxLayout()
        control_panel.setLayout(cl)
        self.host_input = QLineEdit(placeholderText=self._("Enter IP/domain"))
        self.host_input.returnPressed.connect(self.add_host)
        self.add_button = QPushButton(self._("Add Host"))
        self.add_button.clicked.connect(self.add_host)
        self.import_button = QPushButton(self._("Import from File"))
        self.import_button.clicked.connect(self.import_hosts_from_file)
        self.interval_slider = QSlider(Qt.Orientation.Horizontal)
        self.interval_slider.setRange(100, 5000)
        self.interval_slider.setTickInterval(100)
        self.interval_slider.valueChanged.connect(self.update_interval)
        self.interval_label = QLabel(self._("Interval: {}ms").format(self.interval_slider.value()))
        self.mute_button = QPushButton(
            self._("Notifications: On") if self.notifications_enabled
            else self._("Notifications: Off")
        )
        self.mute_button.clicked.connect(self.toggle_notifications)
        self.filter_button = QPushButton(
            self._("Show Failed Hosts") if not self.filter_failed
            else self._("Show All Hosts")
        )
        self.filter_button.clicked.connect(self.toggle_filter)
        self.interval_caption = QLabel(self._("Interval:"))
        cl.addWidget(self.host_input)
        cl.addWidget(self.add_button)
        cl.addWidget(self.import_button)
        cl.addWidget(self.interval_caption)
        cl.addWidget(self.interval_slider)
        cl.addWidget(self.interval_label)
        cl.addWidget(self.mute_button)
        cl.addWidget(self.filter_button)

        # --- Summary panel ---
        summary_panel = QFrame()
        summary_panel.setFrameShape(QFrame.Shape.StyledPanel)
        sl = QHBoxLayout()
        sl.setContentsMargins(6, 2, 6, 2)
        summary_panel.setLayout(sl)
        self.lbl_total = QLabel("Total: 0")
        self.lbl_ok = QLabel("OK: 0"); self.lbl_ok.setStyleSheet("color: #2E7D32; font-weight: bold;")
        self.lbl_warn = QLabel("Warn: 0"); self.lbl_warn.setStyleSheet("color: #F9A825; font-weight: bold;")
        self.lbl_down = QLabel("Down: 0"); self.lbl_down.setStyleSheet("color: #C62828; font-weight: bold;")
        self.lbl_disabled = QLabel("Disabled: 0"); self.lbl_disabled.setStyleSheet("color: gray;")
        self.lbl_loss = QLabel("Loss: 0.0%")
        if has_fping():
            self.lbl_engine = QLabel(f"Engine: fping (batch {self.fping_batch_size})")
        else:
            self.lbl_engine = QLabel("Engine: ping")
        self.lbl_engine.setStyleSheet("color: #666;")
        for w in (self.lbl_total, self.lbl_ok, self.lbl_warn, self.lbl_down, self.lbl_disabled, self.lbl_loss):
            sl.addWidget(w)
            sl.addWidget(QLabel("|"))
        sl.addWidget(self.lbl_engine)
        sl.addStretch()

        main_panel = QHBoxLayout()

        left = QWidget()
        ll = QVBoxLayout()
        left.setLayout(ll)
        self.hosts_caption = QLabel(self._("Monitored Hosts:"))
        ll.addWidget(self.hosts_caption)

        search_row = QWidget()
        sr = QHBoxLayout()
        sr.setContentsMargins(0, 0, 0, 0)
        search_row.setLayout(sr)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self._("Search host..."))
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self.on_search_changed)
        sr.addWidget(self.search_input, 1)

        self.expand_all_btn = QPushButton("＋")
        self.expand_all_btn.setToolTip(self._("Expand all groups"))
        self.expand_all_btn.setFixedWidth(30)
        self.expand_all_btn.clicked.connect(self.expand_all_groups)
        sr.addWidget(self.expand_all_btn)

        self.collapse_all_btn = QPushButton("−")
        self.collapse_all_btn.setToolTip(self._("Collapse all groups"))
        self.collapse_all_btn.setFixedWidth(30)
        self.collapse_all_btn.clicked.connect(self.collapse_all_groups)
        sr.addWidget(self.collapse_all_btn)

        ll.addWidget(search_row)
        ll.addWidget(self.host_list)

        right = QWidget()
        rl = QVBoxLayout()
        right.setLayout(rl)
        rl.addWidget(self.time_scale)
        rl.addWidget(self.scroll_area)
        scroll_content = QWidget()
        self.right_panel_layout = QVBoxLayout()
        scroll_content.setLayout(self.right_panel_layout)
        self.scroll_area.setWidget(scroll_content)

        main_panel.addWidget(left, 25)
        main_panel.addWidget(right, 75)

        layout.addWidget(control_panel)
        layout.addWidget(summary_panel)
        layout.addLayout(main_panel)

    # ---------- Поиск ----------

    def on_search_changed(self, text):
        self.search_text = text.strip().lower()
        self.apply_filter()

    def expand_all_groups(self):
        for i in range(self.host_list.topLevelItemCount()):
            self.host_list.topLevelItem(i).setExpanded(True)

    def collapse_all_groups(self):
        for i in range(self.host_list.topLevelItemCount()):
            self.host_list.topLevelItem(i).setExpanded(False)

    def _host_should_show(self, widget, host):
        if self.search_text and self.search_text not in host.lower():
            return False
        if widget.disabled:
            return not self.filter_failed
        if self.filter_failed:
            return len(widget.ping_history) > 0 and not widget.ping_history[-1][1]
        return True

    # ---------- Сводка ----------

    def update_status_panel(self):
        total = len(self.host_widgets)
        ok = warn = down = disabled = 0
        tot_ok = tot_fail = 0
        for w in self.host_widgets.values():
            if w.disabled:
                disabled += 1
                continue
            cf = w.consecutive_failures
            if cf >= self.alerts_after_failures:
                down += 1
            elif cf >= 1:
                warn += 1
            else:
                ok += 1
            tot_ok += w.session_success_count
            tot_fail += w.session_failure_count
        checks = tot_ok + tot_fail
        loss = (tot_fail / checks * 100) if checks > 0 else 0.0
        self.lbl_total.setText(f"Total: {total}")
        self.lbl_ok.setText(f"OK: {ok}")
        self.lbl_warn.setText(f"Warn: {warn}")
        self.lbl_down.setText(f"Down: {down}")
        self.lbl_disabled.setText(f"Disabled: {disabled}")
        self.lbl_loss.setText(f"Loss: {loss:.1f}%")

    # ---------- Настройки ----------

    def show_settings_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(self._("Settings"))
        dialog.resize(520, 460)
        layout = QVBoxLayout(dialog)
        tabs = QTabWidget()

        general = QWidget()
        gl = QFormLayout(general)
        retention_spin = QSpinBox(); retention_spin.setRange(1, 365 * 24)
        if self.retention_hours % 24 == 0 and self.retention_hours >= 24:
            retention_spin.setValue(self.retention_hours // 24); unit_init = 1
        else:
            retention_spin.setValue(self.retention_hours); unit_init = 0
        retention_unit = QComboBox(); retention_unit.addItems([self._("hours"), self._("days")])
        retention_unit.setCurrentIndex(unit_init)
        row = QWidget(); rl = QHBoxLayout(); rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(retention_spin, 1); rl.addWidget(retention_unit, 1); row.setLayout(rl)
        gl.addRow(self._("Keep history for:"), row)
        esc_check = QCheckBox(self._("Minimize to tray on Escape"))
        esc_check.setChecked(self.minimize_on_escape)
        gl.addRow("", esc_check)

        batch_spin = QSpinBox()
        batch_spin.setRange(1, 100)
        batch_spin.setValue(self.fping_batch_size)
        batch_spin.setEnabled(has_fping())
        gl.addRow(self._("fping batch size (hosts per call):"), batch_spin)
        if not has_fping():
            fping_hint = QLabel(self._("fping not found — batch size has no effect."))
            fping_hint.setStyleSheet("color: #666; font-size: 10px;")
            gl.addRow("", fping_hint)
        tabs.addTab(general, self._("General"))

        alerts = QWidget()
        al = QFormLayout(alerts)
        alert_after = QSpinBox(); alert_after.setRange(1, 100)
        alert_after.setValue(self.alerts_after_failures)
        al.addRow(self._("Alert after N consecutive failures:"), alert_after)
        reminder = QSpinBox(); reminder.setRange(1, 1440)
        reminder.setValue(self.alert_reminder_minutes)
        reminder.setSuffix(" min")
        al.addRow(self._("Remind every:"), reminder)
        recovery_check = QCheckBox(self._("Notify when host recovers"))
        recovery_check.setChecked(self.notify_on_recovery)
        al.addRow("", recovery_check)
        tabs.addTab(alerts, self._("Alerts"))

        storage = QWidget()
        st = QFormLayout(storage)
        cleanup_check = QCheckBox(self._("Auto-cleanup old history files"))
        cleanup_check.setChecked(self.cleanup_enabled)
        st.addRow("", cleanup_check)
        cleanup_days = QSpinBox(); cleanup_days.setRange(1, 3650)
        cleanup_days.setValue(self.cleanup_days)
        cleanup_days.setSuffix(" days")
        st.addRow(self._("Delete archives older than:"), cleanup_days)
        info = QLabel(self._("Files are deleted from ~/.config/QPing/history/. This cannot be undone."))
        info.setWordWrap(True); info.setStyleSheet("color: #666; font-size: 10px;")
        st.addRow(info)
        tabs.addTab(storage, self._("Storage"))

        hooks = QWidget()
        hl = QFormLayout(hooks)
        hooks_check = QCheckBox(self._("Enable event hooks"))
        hooks_check.setChecked(self.hooks_enabled)
        hl.addRow("", hooks_check)
        hooks_path_lbl = QLabel(self.hooks_dir)
        hooks_path_lbl.setWordWrap(True)
        hooks_path_lbl.setStyleSheet("color: #666;")
        choose_btn = QPushButton(self._("Choose directory..."))
        def choose_hooks_dir():
            d = QFileDialog.getExistingDirectory(self, self._("Hooks directory"), self.hooks_dir)
            if d:
                hooks_path_lbl.setText(d)
        choose_btn.clicked.connect(choose_hooks_dir)
        hl.addRow(self._("Hooks directory:"), hooks_path_lbl)
        hl.addRow("", choose_btn)
        hint = QLabel(self._(
            "Scripts: on_host_down.sh and on_host_up.sh (must be executable).\n"
            "Environment variables: QPING_HOST, QPING_STATUS (down/up), QPING_FAILURES, QPING_TIMESTAMP."
        ))
        hint.setWordWrap(True); hint.setStyleSheet("color: #666; font-size: 10px;")
        hl.addRow(hint)
        tabs.addTab(hooks, self._("Hooks"))

        layout.addWidget(tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            value = retention_spin.value()
            new_hours = value * 24 if retention_unit.currentIndex() == 1 else value
            new_hours = max(1, new_hours)
            self.retention_hours = new_hours
            self.settings.setValue("retention_hours", new_hours)
            for w in self.host_widgets.values():
                w.retention_hours = new_hours
                w.prune_to_retention()

            self.minimize_on_escape = esc_check.isChecked()
            self.settings.setValue("minimize_on_escape", self.minimize_on_escape)

            new_batch = batch_spin.value()
            self.fping_batch_size = max(1, new_batch)
            self.settings.setValue("fping_batch_size", self.fping_batch_size)
            if has_fping():
                self.lbl_engine.setText(f"Engine: fping (batch {self.fping_batch_size})")

            self.alerts_after_failures = alert_after.value()
            self.alert_reminder_minutes = reminder.value()
            self.notify_on_recovery = recovery_check.isChecked()
            self.settings.setValue("alerts_after_failures", self.alerts_after_failures)
            self.settings.setValue("alert_reminder_minutes", self.alert_reminder_minutes)
            self.settings.setValue("notify_on_recovery", self.notify_on_recovery)

            self.cleanup_enabled = cleanup_check.isChecked()
            self.cleanup_days = cleanup_days.value()
            self.settings.setValue("cleanup_enabled", self.cleanup_enabled)
            self.settings.setValue("cleanup_days", self.cleanup_days)

            self.hooks_enabled = hooks_check.isChecked()
            self.hooks_dir = hooks_path_lbl.text()
            os.makedirs(self.hooks_dir, exist_ok=True)
            self.settings.setValue("hooks_enabled", self.hooks_enabled)
            self.settings.setValue("hooks_dir", self.hooks_dir)

            self.update_all_graphs()
            self.update_status_panel()

    # ---------- Хуки ----------

    def fire_hook(self, event, host, failures=0):
        if not self.hooks_enabled:
            return
        script = os.path.join(self.hooks_dir, f"on_host_{event}.sh")
        if not os.path.isfile(script) or not os.access(script, os.X_OK):
            return
        env = {
            "QPING_HOST": host,
            "QPING_STATUS": event,
            "QPING_FAILURES": str(failures),
            "QPING_TIMESTAMP": datetime.now().isoformat(),
        }
        worker = HookWorker(script, env)
        self.hook_pool.start(worker)

    # ---------- Автоочистка ----------

    def run_auto_cleanup(self):
        if not self.cleanup_enabled:
            return
        cutoff_date = datetime.now() - timedelta(days=self.cleanup_days)
        removed = 0
        try:
            for host_dir_name in os.listdir(HISTORY_DIR):
                host_dir = os.path.join(HISTORY_DIR, host_dir_name)
                if not os.path.isdir(host_dir):
                    continue
                for fname in os.listdir(host_dir):
                    if not fname.endswith(".jsonl"):
                        continue
                    day_str = fname[:-6]
                    try:
                        d = datetime.strptime(day_str, "%Y-%m-%d")
                    except ValueError:
                        continue
                    if d < cutoff_date:
                        try:
                            os.remove(os.path.join(host_dir, fname))
                            removed += 1
                        except OSError as e:
                            print(f"[cleanup] {fname}: {e}")
        except Exception as e:
            print(f"[cleanup] {e}")
        if removed:
            print(f"[cleanup] Removed {removed} old history files")

    # ---------- Уведомления / фильтр ----------

    def toggle_notifications(self):
        self.notifications_enabled = not self.notifications_enabled
        self.mute_button.setText(
            self._("Notifications: On") if self.notifications_enabled
            else self._("Notifications: Off")
        )
        self.settings.setValue("notifications_enabled", self.notifications_enabled)

    def toggle_filter(self):
        self.filter_failed = not self.filter_failed
        self.filter_button.setText(
            self._("Show Failed Hosts") if not self.filter_failed
            else self._("Show All Hosts")
        )
        self.settings.setValue("filter_failed", self.filter_failed)
        self.apply_filter()
        self.reorder_graphs()

    def apply_filter(self):
        for i in range(self.host_list.topLevelItemCount()):
            ci = self.host_list.topLevelItem(i)
            visible = 0
            total = 0
            for j in range(ci.childCount()):
                hi = ci.child(j)
                host = hi.data(0, Qt.ItemDataRole.UserRole)
                w = self.host_widgets.get(host)
                if not w:
                    continue
                total += 1
                show = self._host_should_show(w, host)
                hi.setHidden(not show)
                w.setVisible(show)
                if show:
                    visible += 1
            cat_name = ci.data(0, Qt.ItemDataRole.UserRole)
            if self.filter_failed or self.search_text:
                ci.setText(0, f"[{cat_name}] ({visible}/{total})")
                ci.setHidden(visible == 0)
            else:
                ci.setText(0, f"[{cat_name}] ({total})")
                ci.setHidden(False)
        self.update_status_panel()

    # ---------- Help ----------

    def show_help(self):
        from help import build_help_html
        dlg = QDialog(self)
        dlg.setWindowTitle(self._("User Guide"))
        dlg.resize(700, 560)
        layout = QVBoxLayout()
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setHtml(build_help_html(self._))
        layout.addWidget(text_edit)
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        button_box.accepted.connect(dlg.accept)
        layout.addWidget(button_box)
        dlg.setLayout(layout)
        dlg.exec()

    # ---------- Локализация ----------

    def change_language(self, lang):
        self.language = lang
        self._ = setup_localization(lang)
        self.settings.setValue("language", lang)
        # Меню больше не пересоздаётся — можно вызывать напрямую.
        self.retranslate_ui()

    def retranslate_ui(self):
        if not hasattr(self, 'host_list') or self.host_list is None:
            return
        self.setWindowTitle(f"{self._('QPing Monitor')} {APP_VERSION}")
        self.host_input.setPlaceholderText(self._("Enter IP/domain"))
        self.search_input.setPlaceholderText(self._("Search host..."))
        self.add_button.setText(self._("Add Host"))
        self.import_button.setText(self._("Import from File"))
        self.interval_label.setText(self._("Interval: {}ms").format(self.interval_slider.value()))
        self.mute_button.setText(
            self._("Notifications: On") if self.notifications_enabled
            else self._("Notifications: Off")
        )
        self.filter_button.setText(
            self._("Show Failed Hosts") if not self.filter_failed
            else self._("Show All Hosts")
        )
        if hasattr(self, 'interval_caption'):
            self.interval_caption.setText(self._("Interval:"))
        if hasattr(self, 'hosts_caption'):
            self.hosts_caption.setText(self._("Monitored Hosts:"))

        # --- Меню: только обновляем текст, ничего не удаляем ---
        self.menu_app.setTitle(self._("Application"))
        self.action_settings.setText(self._("Settings..."))
        self.action_export.setText(self._("Export Hosts..."))
        self.action_import.setText(self._("Import Hosts..."))
        self.action_close.setText(self._("Close"))
        self.action_quit.setText(self._("Quit"))

        self.menu_help.setTitle(self._("Help"))
        self.action_help.setText(self._("User Guide"))

        self.menu_lang.setTitle(self._("Language"))
        # Названия языков не переводим — они всегда "Русский" / "English"

        # --- Tray menu ---
        if hasattr(self, 'tray_action_restore'):
            self.tray_action_restore.setText(self._("Restore"))
            self.tray_action_quit.setText(self._("Quit"))

        # --- Обновление списка хостов и tooltip'ов ---
        self.update_host_list_display()
        self.update_all_graphs()

    # ---------- Контекстное меню ----------

    def show_host_context_menu(self, position):
        sel = self.host_list.selectedItems()
        menu = QMenu()
        clicked = self.host_list.itemAt(position)

        if clicked and clicked.parent() is None:
            cat = clicked.data(0, Qt.ItemDataRole.UserRole)
            act = QAction(self._("Delete Category '{}'").format(cat), self)
            act.triggered.connect(lambda: self.delete_category(cat))
            act.setEnabled(cat != "Default")
            menu.addAction(act)
            menu.exec(self.host_list.mapToGlobal(position))
            return

        hosts = [i.data(0, Qt.ItemDataRole.UserRole) for i in sel
                 if i.parent() is not None and i.data(0, Qt.ItemDataRole.UserRole)]

        if hosts:
            edit_action = QAction(self._("Edit (F2)"), self)
            edit_action.triggered.connect(lambda: self.edit_host(hosts[0]))
            edit_action.setEnabled(len(hosts) == 1)

            delete_action = QAction(self._("Delete (Del)"), self)
            delete_action.triggered.connect(lambda: self.delete_hosts(hosts))

            ping_now_action = QAction(self._("Ping now"), self)
            ping_now_action.triggered.connect(lambda: self.ping_now(hosts))

            any_disabled = all(self.host_widgets[h].disabled for h in hosts if h in self.host_widgets)
            disable_label = self._("Enable monitoring") if any_disabled else self._("Disable monitoring")
            disable_action = QAction(disable_label, self)
            disable_action.triggered.connect(lambda: self.toggle_disabled(hosts))

            check_type_menu = QMenu(self._("Check Type"), self)
            icmp_a = QAction(self._("ICMP Ping"), self)
            tcp_a = QAction(self._("TCP Port"), self)
            icmp_a.triggered.connect(lambda: self.set_check_type(hosts, 'icmp'))
            tcp_a.triggered.connect(lambda: self.set_check_type(hosts, 'tcp'))
            check_type_menu.addAction(icmp_a); check_type_menu.addAction(tcp_a)
            check_type_menu.setEnabled(len(hosts) == 1)

            cat_action = QAction(self._("Set Category"), self)
            cat_action.triggered.connect(lambda: self.set_host_category(hosts))

            clear_action = QAction(self._("Clear History"), self)
            clear_action.triggered.connect(lambda: self.clear_host_history(hosts))

            load_action = QAction(self._("Load Full History"), self)
            load_action.triggered.connect(lambda: self.load_full_history(hosts))

            menu.addAction(edit_action)
            menu.addAction(delete_action)
            menu.addAction(ping_now_action)
            menu.addAction(disable_action)
            menu.addSeparator()
            menu.addMenu(check_type_menu)
            menu.addAction(cat_action)
            menu.addSeparator()
            menu.addAction(clear_action)
            menu.addAction(load_action)
        else:
            imp = QAction(self._("Import from File"), self)
            imp.triggered.connect(self.import_hosts_from_file)
            menu.addAction(imp)

        menu.exec(self.host_list.mapToGlobal(position))

    # ---------- Ping now / Disable ----------

    def ping_now(self, hosts):
        for host in reversed(hosts):
            if host in self.icmp_queue:
                self.icmp_queue.remove(host)
                self.icmp_queue.insert(0, host)
            elif host in self.tcp_queue:
                self.tcp_queue.remove(host)
                self.tcp_queue.insert(0, host)
        self.icmp_idx = 0
        self.tcp_idx = 0
        self.ping_tick()

    def toggle_disabled(self, hosts):
        for h in hosts:
            if h in self.host_widgets:
                self.host_widgets[h].set_disabled(not self.host_widgets[h].disabled)
        self.update_host_list_display()
        self.update_host_queue()
        self.reorder_graphs()
        self.apply_filter()
        self.save_data()

    # ---------- Категории ----------

    def delete_category(self, category_name):
        if category_name == "Default":
            return
        hosts_in_cat = [h for h, w in self.host_widgets.items() if w.category == category_name]
        if hosts_in_cat:
            mb = QMessageBox(self)
            mb.setWindowTitle(self._("Delete Category"))
            mb.setText(self._("Category '{}' contains {} hosts. What would you like to do?").format(category_name, len(hosts_in_cat)))
            move_btn = mb.addButton(self._("Move hosts to Default"), QMessageBox.ButtonRole.ActionRole)
            delete_btn = mb.addButton(self._("Delete all hosts"), QMessageBox.ButtonRole.DestructiveRole)
            mb.addButton(QMessageBox.StandardButton.Cancel)
            mb.exec()
            if mb.clickedButton() == move_btn:
                for h in hosts_in_cat:
                    self.host_widgets[h].category = "Default"
            elif mb.clickedButton() == delete_btn:
                for h in hosts_in_cat:
                    self.host_widgets[h].deleteLater()
                    del self.host_widgets[h]
            else:
                return
        else:
            r = QMessageBox.question(self, self._("Delete Category"),
                                     self._("Delete empty category '{}'?").format(category_name),
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                return
        if category_name in self.categories_list:
            self.categories_list.remove(category_name)
        self.update_host_list_display()
        self.reorder_graphs()
        self.save_data()
        self.apply_filter()
        self.update_host_queue()

    def set_host_category(self, hosts):
        class CategoryDialog(QDialog):
            def __init__(self, parent, existing):
                super().__init__(parent)
                self.setWindowTitle(parent._("Set Category"))
                lay = QVBoxLayout(self)
                self.combo = QComboBox()
                self.combo.addItem("Default")
                self.combo.addItems(sorted([c for c in existing if c != "Default"]))
                self.combo.addItem(parent._("New Category"))
                lay.addWidget(self.combo)
                self.text_input = QLineEdit()
                self.text_input.setPlaceholderText(parent._("Enter new category name"))
                self.text_input.setVisible(False)
                lay.addWidget(self.text_input)
                self.combo.currentIndexChanged.connect(self.toggle)
                bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
                bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
                lay.addWidget(bb)
            def toggle(self, idx):
                self.text_input.setVisible(self.combo.currentText() == self.parent()._("New Category"))
            def get_category(self):
                if self.combo.currentText() == self.parent()._("New Category"):
                    return self.text_input.text().strip()
                return self.combo.currentText()
        d = CategoryDialog(self, self.categories_list)
        if d.exec() == QDialog.DialogCode.Accepted:
            cat = d.get_category()
            if cat:
                if cat not in self.categories_list:
                    self.categories_list.append(cat)
                for h in hosts:
                    if h in self.host_widgets:
                        self.host_widgets[h].category = cat
                self.update_host_list_display()
                self.reorder_graphs()
                self.save_data()
                self.apply_filter()

    # ---------- Тип проверки ----------

    def set_check_type(self, hosts, check_type):
        if not hosts:
            return
        host = hosts[0] if isinstance(hosts, list) else hosts
        if check_type == 'tcp':
            port, ok = QInputDialog.getInt(self, self._("TCP Port"),
                                           self._("Enter port number (1-65535):"),
                                           value=80, min=1, max=65535)
            if not ok:
                return
            self.host_check_types[host] = {'type': 'tcp', 'port': port}
            if host in self.host_widgets:
                self.host_widgets[host].set_check_type('tcp', port)
        else:
            self.host_check_types[host] = {'type': 'icmp', 'port': None}
            if host in self.host_widgets:
                self.host_widgets[host].set_check_type('icmp', None)
        self.update_host_item_text(host)
        self.save_data()
        self.apply_filter()
        self.update_host_queue()

    def get_host_check_tag(self, host):
        info = self.host_check_types.get(host, {'type': 'icmp', 'port': None})
        if info.get('type') == 'tcp' and info.get('port') is not None:
            return f"[p:{info['port']}]"
        return "[i]"

    def update_host_item_text(self, host):
        if host not in self.host_widgets:
            return
        text = f"{host} {self.get_host_check_tag(host)}"
        for i in range(self.host_list.topLevelItemCount()):
            ci = self.host_list.topLevelItem(i)
            for j in range(ci.childCount()):
                c = ci.child(j)
                if c.data(0, Qt.ItemDataRole.UserRole) == host:
                    c.setText(0, text)
                    return

    # ---------- Удаление ----------

    def delete_hosts(self, hosts):
        r = QMessageBox.question(self, self._("Delete"),
                                 self._("Delete {} hosts?").format(len(hosts)),
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r == QMessageBox.StandardButton.Yes:
            for h in hosts:
                if h in self.host_widgets:
                    self.host_widgets[h].deleteLater()
                    del self.host_widgets[h]
            self.update_host_list_display()
            self.reorder_graphs()
            self.save_data()
            self.apply_filter()
            self.update_host_queue()
            if not self.host_widgets:
                self.ping_timer.stop()

    # ---------- Очистка / загрузка истории ----------

    def clear_host_history(self, hosts):
        if not hosts:
            return
        r = QMessageBox.question(
            self, self._("Clear History"),
            self._("Delete all history for {} host(s)?\n\n"
                   "This erases in-memory records and deletes all saved files "
                   "in ~/.config/QPing/history/ for the selected host(s).").format(len(hosts)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r != QMessageBox.StandardButton.Yes:
            return
        import shutil
        for h in hosts:
            if h not in self.host_widgets:
                continue
            w = self.host_widgets[h]
            w.ping_history.clear()
            w.session_success_count = 0
            w.session_failure_count = 0
            w.consecutive_failures = 0
            w.last_notified = None
            w.last_saved_time = None
            w.was_down = False
            w.graph_widget.update_history(w.ping_history, 0, 0, self.app_start_time)
            hd = self._host_dir(h)
            if os.path.isdir(hd):
                try:
                    shutil.rmtree(hd)
                except Exception as e:
                    print(f"Failed to remove {hd}: {e}")
        self.apply_filter()
        self.reorder_graphs()

    def load_full_history(self, hosts):
        if not hosts:
            return
        total = 0
        for h in hosts:
            if h not in self.host_widgets:
                continue
            w = self.host_widgets[h]
            loaded = self._load_single_host_history(h, w, full=True)
            total += loaded
            if loaded == 0:
                QMessageBox.information(self, self._("Load Full History"),
                                        self._("No history files found for host {}.").format(h))
            w.graph_widget.update_history(w.ping_history, w.session_success_count,
                                          w.session_failure_count, self.app_start_time)
        self.apply_filter()
        self.update_all_graphs()
        if total > 0:
            QMessageBox.information(self, self._("Load Full History"),
                                    self._("History loaded ({} records). Zoom out to see older data.").format(total))

    # ---------- Список ----------

    def sorted_categories(self):
        """Default всегда первым, остальные — по алфавиту."""
        others = sorted(c for c in self.categories_list if c != "Default")
        return ["Default"] + others

    def update_host_list_display(self):
        self.host_list.clear()
        for category in self.sorted_categories():
            ci = QTreeWidgetItem(self.host_list)
            ci.setText(0, f"[{category}] (0)")
            ci.setData(0, Qt.ItemDataRole.UserRole, category)
            ci.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsDropEnabled)
            ci.setBackground(0, QColor("#E0E0E0"))
            ci.setExpanded(True)
            self.host_list.addTopLevelItem(ci)
        # Порядок хостов внутри категорий — сохранённый (см. self.host_widgets)
        for host, w in self.host_widgets.items():
            if w.category not in self.categories_list:
                w.category = "Default"
            for i in range(self.host_list.topLevelItemCount()):
                ci = self.host_list.topLevelItem(i)
                if ci.data(0, Qt.ItemDataRole.UserRole) == w.category:
                    hi = QTreeWidgetItem(ci)
                    hi.setText(0, f"{host} {self.get_host_check_tag(host)}")
                    hi.setData(0, Qt.ItemDataRole.UserRole, host)
                    hi.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable |
                                Qt.ItemFlag.ItemIsDragEnabled)
                    hi.setForeground(0, self._host_color(w))
                    ci.addChild(hi)
        for i in range(self.host_list.topLevelItemCount()):
            ci = self.host_list.topLevelItem(i)
            if self.filter_failed:
                vh = sum(1 for j in range(ci.childCount()) if not ci.child(j).isHidden())
                ci.setText(0, f"[{ci.data(0, Qt.ItemDataRole.UserRole)}] ({vh})")
            else:
                ci.setText(0, f"[{ci.data(0, Qt.ItemDataRole.UserRole)}] ({ci.childCount()})")

    # ---------- Импорт ----------

    def import_hosts_from_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, self._("Import hosts"), "",
            self._("Supported (*.ini *.yml *.yaml *.txt *.qping.json hosts);;"
                   "Ansible INI (*.ini);;Ansible YAML (*.yml *.yaml);;"
                   "Hosts file (hosts);;Text list (*.txt);;"
                   "QPing backup (*.qping.json);;All files (*)"))
        if not file_name:
            return
        try:
            with open(file_name, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            QMessageBox.critical(self, self._("Import error"), str(e))
            return

        fmt = detect_import_format(file_name, content)
        print(f"[import] file={file_name} format={fmt}")

        # Бэкап — отдельная логика
        if fmt == 'backup':
            self._restore_backup(content)
            return

        # Остальные форматы дают {group: [host, ...]}
        if fmt == 'ansible_ini':
            groups = parse_ansible_ini(content)
        elif fmt == 'ansible_yaml':
            groups = parse_ansible_yaml(content)
            if groups is None:
                QMessageBox.warning(self, self._("Import"),
                    self._("YAML parsing requires PyYAML. Install with: pip install pyyaml"))
                return
        elif fmt == 'hosts':
            groups = parse_hosts_file(content)
        else:
            groups = parse_plain_list(content)

        if not groups:
            QMessageBox.warning(self, self._("Import"), self._("No hosts found."))
            return

        self._add_hosts_from_groups(groups)

    def _add_hosts_from_groups(self, groups):
        """groups: {group_name: [host, ...]}. Добавляет хостов, автосоздаёт категории,
        пропускает дубликаты."""
        added = 0
        for group, hosts_list in groups.items():
            cat = group if group else "Default"
            if cat not in self.categories_list:
                self.categories_list.append(cat)
            for h in hosts_list:
                h = h.strip()
                if not h or h in self.host_widgets:
                    continue
                w = HostWidget(h, self.time_scale, self.app_start_time, cat)
                w.retention_hours = self.retention_hours
                self.host_widgets[h] = w
                self._load_single_host_history(h, w, hours_limit=1)
                added += 1

        if added > 0:
            self.update_host_list_display()
            self.reorder_graphs()
            self.save_data()
            self.apply_filter()
            self.update_host_queue()
            if not self.ping_timer.isActive():
                self.start_pinging()
            QMessageBox.information(self, self._("Import completed"),
                                    self._("Successfully added {} hosts.").format(added))
        else:
            QMessageBox.warning(self, self._("Import"), self._("No new hosts added."))

    def _restore_backup(self, content):
        """Восстанавливает список хостов из QPing-бэкапа."""
        data = parse_backup(content)
        if data is None:
            QMessageBox.warning(self, self._("Restore"),
                                self._("Invalid QPing backup file."))
            return

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self._("Restore from backup"))
        msg_box.setText(self._("Backup contains {} host(s).\n\n"
                               "What would you like to do?").format(len(data)))
        replace_btn = msg_box.addButton(self._("Replace current list"),
                                        QMessageBox.ButtonRole.DestructiveRole)
        merge_btn = msg_box.addButton(self._("Merge with current"),
                                      QMessageBox.ButtonRole.ActionRole)
        cancel_btn = msg_box.addButton(QMessageBox.StandardButton.Cancel)
        msg_box.exec()

        if msg_box.clickedButton() == cancel_btn:
            return

        if msg_box.clickedButton() == replace_btn:
            for h in list(self.host_widgets.keys()):
                self.host_widgets[h].deleteLater()
                del self.host_widgets[h]
            self.host_check_types.clear()
            self.categories_list = ["Default"]

        added = 0
        for host, info in data.items():
            cat = info['category']
            if cat not in self.categories_list:
                self.categories_list.append(cat)

            if host not in self.host_widgets:
                w = HostWidget(host, self.time_scale, self.app_start_time, cat)
                w.retention_hours = self.retention_hours
                self.host_widgets[host] = w
                self._load_single_host_history(host, w, full=False)
            else:
                w = self.host_widgets[host]
                w.category = cat

            ct = info.get('check_type', 'icmp')
            port = info.get('port')
            self.host_check_types[host] = {'type': ct, 'port': port}
            w.set_check_type(ct, port)
            w.set_disabled(info.get('disabled', False))
            added += 1

        self.update_host_list_display()
        self.reorder_graphs()
        self.save_data()
        self.apply_filter()
        self.update_host_queue()
        if self.host_widgets and not self.ping_timer.isActive():
            self.start_pinging()
        QMessageBox.information(self, self._("Restore completed"),
                                self._("Restored {} hosts.").format(added))

    def export_hosts_to_file(self):
        """Сохраняет список хостов в QPing-бэкап."""
        file_name, _ = QFileDialog.getSaveFileName(
            self, self._("Export hosts"),
            os.path.join(os.path.expanduser("~"), "qping_backup.qping.json"),
            self._("QPing backup (*.qping.json);;JSON (*.json);;All files (*)"))
        if not file_name:
            return
        if not (file_name.endswith('.qping.json') or file_name.endswith('.json')):
            file_name += '.qping.json'

        hosts_data = []

        def traverse(pi):
            for i in range(pi.childCount()):
                c = pi.child(i)
                h = c.data(0, Qt.ItemDataRole.UserRole)
                if h and h in self.host_widgets:
                    w = self.host_widgets[h]
                    info = self.host_check_types.get(h, {'type': 'icmp', 'port': None})
                    hosts_data.append({
                        'host': h,
                        'category': w.category,
                        'check_type': info.get('type', 'icmp'),
                        'port': info.get('port'),
                        'disabled': bool(w.disabled),
                    })

        for i in range(self.host_list.topLevelItemCount()):
            traverse(self.host_list.topLevelItem(i))

        backup = build_backup(hosts_data)
        try:
            with open(file_name, 'w', encoding='utf-8') as f:
                json.dump(backup, f, indent=2, ensure_ascii=False)
        except Exception as e:
            QMessageBox.critical(self, self._("Export error"), str(e))
            return

        QMessageBox.information(self, self._("Export completed"),
                                self._("Exported {} hosts to:\n{}").format(len(hosts_data), file_name))


    # ---------- Иконка трея ----------

    def update_app_icon(self):
        has_red = any(w.consecutive_failures >= self.alerts_after_failures
                      for w in self.host_widgets.values() if not w.disabled)
        has_yellow = any(w.consecutive_failures == 1
                         for w in self.host_widgets.values() if not w.disabled)
        if has_red:
            new_icon = self.red_icon
        elif has_yellow:
            new_icon = self.yellow_icon
        else:
            new_icon = self.green_icon
        # Обновляем только при реальной смене — иначе DE мерцает при каждом setIcon.
        if new_icon is not self._current_icon:
            self._current_icon = new_icon
            self.setWindowIcon(new_icon)
            self.tray_icon.setIcon(new_icon)

    # ---------- Очереди ----------

    def update_host_queue(self):
        self.icmp_queue = []
        self.tcp_queue = []

        def traverse(pi):
            for i in range(pi.childCount()):
                c = pi.child(i)
                host = c.data(0, Qt.ItemDataRole.UserRole)
                if not host or host not in self.host_widgets:
                    continue
                w = self.host_widgets[host]
                if w.disabled:
                    continue
                info = self.host_check_types.get(host, {'type': 'icmp', 'port': None})
                if info.get('type') == 'tcp':
                    self.tcp_queue.append(host)
                else:
                    self.icmp_queue.append(host)

        for i in range(self.host_list.topLevelItemCount()):
            traverse(self.host_list.topLevelItem(i))

        self.icmp_idx = 0
        self.tcp_idx = 0

    def start_pinging(self):
        if self.host_widgets:
            self.update_host_queue()
            if not self.ping_timer.isActive():
                self.ping_timer.start(self.interval_slider.value())

    # ---------- Подсветка ----------

    def _clear_highlight(self):
        for h in self._highlighted_hosts:
            self._set_host_bg(h, QColor("white"))
        self._highlighted_hosts = []

    def _set_host_bg(self, host, color):
        for i in range(self.host_list.topLevelItemCount()):
            ci = self.host_list.topLevelItem(i)
            for j in range(ci.childCount()):
                hi = ci.child(j)
                if hi.data(0, Qt.ItemDataRole.UserRole) == host:
                    hi.setBackground(0, color)
                    return

    def _host_color(self, widget):
        """Цвет текста хоста в дереве."""
        if widget.disabled:
            return QColor("gray")
        if widget.consecutive_failures >= self.alerts_after_failures:
            return QColor("#C62828")   # красный
        if widget.consecutive_failures >= 1:
            return QColor("#EF6C00")   # оранжевый для «warning»
        return QColor(Qt.GlobalColor.black)

    def _set_host_color(self, host):
        """Обновляет цвет текста хоста в дереве."""
        w = self.host_widgets.get(host)
        if not w:
            return
        color = self._host_color(w)
        for i in range(self.host_list.topLevelItemCount()):
            ci = self.host_list.topLevelItem(i)
            for j in range(ci.childCount()):
                hi = ci.child(j)
                if hi.data(0, Qt.ItemDataRole.UserRole) == host:
                    hi.setForeground(0, color)
                    return

    def _take_next_icmp_batch(self):
        if not self.icmp_queue:
            return []
        n = min(self.fping_batch_size, len(self.icmp_queue))
        batch = []
        for _ in range(n):
            if self.icmp_idx >= len(self.icmp_queue):
                self.icmp_idx = 0
            h = self.icmp_queue[self.icmp_idx]
            self.icmp_idx = (self.icmp_idx + 1) % len(self.icmp_queue)
            if h not in batch:
                batch.append(h)
            if len(batch) >= len(self.icmp_queue):
                break
        return batch

    def _take_next_tcp(self):
        if not self.tcp_queue:
            return None
        if self.tcp_idx >= len(self.tcp_queue):
            self.tcp_idx = 0
        h = self.tcp_queue[self.tcp_idx]
        self.tcp_idx = (self.tcp_idx + 1) % len(self.tcp_queue)
        return h

    # ---------- Тик ----------

    def ping_tick(self):
        if not self.host_widgets:
            return
        self._clear_highlight()
        scheduled = []

        if self.icmp_queue:
            if has_fping():
                batch = self._take_next_icmp_batch()
                if batch:
                    self.ping_manager.ping_icmp_batch(batch)
                    scheduled.extend(batch)
            else:
                if self.icmp_idx >= len(self.icmp_queue):
                    self.icmp_idx = 0
                h = self.icmp_queue[self.icmp_idx]
                self.icmp_idx = (self.icmp_idx + 1) % len(self.icmp_queue)
                self.ping_manager.ping_host(h, 'icmp', None)
                scheduled.append(h)

        h_tcp = self._take_next_tcp()
        if h_tcp is not None:
            info = self.host_check_types.get(h_tcp, {'type': 'tcp', 'port': None})
            self.ping_manager.ping_host(h_tcp, 'tcp', info.get('port'))
            scheduled.append(h_tcp)

        for h in scheduled:
            self._set_host_bg(h, QColor("#ADD8E6"))
        self._highlighted_hosts = scheduled

    # ---------- Результат ping ----------

    def handle_ping_result(self, host, success, latency):
        current_time = datetime.now()
        if host in self.host_widgets:
            w = self.host_widgets[host]
            if w.disabled:
                return
            consecutive = w.update_status(success, latency, current_time)

            if success:
                if w.was_down:
                    w.was_down = False
                    self.fire_hook("up", host, failures=0)
                    if self.notify_on_recovery and self.notifications_enabled:
                        if not self.tray_icon.isVisible():
                            self.tray_icon.setVisible(True)
                        self.tray_icon.showMessage(
                            self._("Host recovered"),
                            self._("Host {} is responding again").format(host),
                            QSystemTrayIcon.MessageIcon.Information,
                            5000)
                w.last_notified = None
            else:
                if consecutive >= self.alerts_after_failures:
                    if not w.was_down:
                        w.was_down = True
                        self.fire_hook("down", host, failures=consecutive)
                    if self.notifications_enabled:
                        last = w.last_notified
                        if last is None or (current_time - last).total_seconds() >= self.alert_reminder_minutes * 60:
                            w.last_notified = current_time
                            if not self.tray_icon.isVisible():
                                self.tray_icon.setVisible(True)
                            print(f"[notify] host={host} fails={consecutive}")
                            self.tray_icon.showMessage(
                                self._("Host unavailable"),
                                self._("Host {} is not responding ({} failures)").format(host, consecutive),
                                QSystemTrayIcon.MessageIcon.Warning,
                                5000)

        self.update_app_icon()
        if host in self.host_widgets:
            self._set_host_color(host)
        self.apply_filter()

    # ---------- Добавление / редактирование ----------

    def add_host(self):
        host = self.host_input.text().strip()
        if host and host not in self.host_widgets:
            w = HostWidget(host, self.time_scale, self.app_start_time, "Default")
            w.retention_hours = self.retention_hours
            self.host_widgets[host] = w
            self._load_single_host_history(host, w, hours_limit=1)
            self.update_host_list_display()
            self.reorder_graphs()
            self.host_input.clear()
            self.save_data()
            self.apply_filter()
            if not self.ping_timer.isActive():
                self.start_pinging()
            else:
                self.update_host_queue()

    def update_interval(self, interval):
        self.interval_label.setText(self._("Interval: {}ms").format(interval))
        self.ping_manager.set_ping_interval(interval)
        self.settings.setValue("interval", interval)
        if self.ping_timer.isActive():
            self.ping_timer.start(interval)

    def edit_host(self, host):
        if not host:
            return
        new_host, ok = QInputDialog.getText(self, self._("Edit"), self._("New host name:"), text=host)
        if ok and new_host and new_host != host:
            w = self.host_widgets[host]
            w.host = new_host
            w.graph_widget.host = new_host
            w.update_host_label()
            # Сохраняем позицию в словаре: пересобираем с сохранением порядка.
            new_widgets = {}
            for h, w in self.host_widgets.items():
                if h == host:
                    new_widgets[new_host] = w
                else:
                    new_widgets[h] = w
            self.host_widgets = new_widgets

            if host in self.host_check_types:
                self.host_check_types[new_host] = self.host_check_types.pop(host)
            self.update_host_list_display()
            self.reorder_graphs()
            self.save_data()
            self.apply_filter()
            self.update_host_queue()

    # ---------- Save ----------

    def _build_snapshot(self):
        snap = {}
        for host, w in self.host_widgets.items():
            last_saved = w.last_saved_time
            new = [(t, s, lat) for (t, s, lat) in w.ping_history
                   if last_saved is None or t > last_saved]
            snap[host] = {
                'dir': self._host_dir(host),
                'records': new,
                'meta': {
                    'host': host,
                    'check_type': self.host_check_types.get(host, {'type': 'icmp', 'port': None})
                },
            }
        return snap

    def save_data(self):
        hosts = []
        def traverse(pi):
            cat_name = pi.data(0, Qt.ItemDataRole.UserRole)
            for i in range(pi.childCount()):
                c = pi.child(i)
                h = c.data(0, Qt.ItemDataRole.UserRole)
                if h and h in self.host_widgets:
                    w = self.host_widgets[h]
                    if cat_name:
                        w.category = cat_name
                    hosts.append([h, w.category, bool(w.disabled)])
        for i in range(self.host_list.topLevelItemCount()):
            traverse(self.host_list.topLevelItem(i))
        self.settings.setValue("hosts", hosts)
        self.settings.setValue("filter_failed", self.filter_failed)
        self.settings.setValue("categories", self.categories_list)
        self.settings.setValue("retention_hours", self.retention_hours)
        self.settings.setValue("minimize_on_escape", self.minimize_on_escape)
        self.settings.setValue("alerts_after_failures", self.alerts_after_failures)
        self.settings.setValue("alert_reminder_minutes", self.alert_reminder_minutes)
        self.settings.setValue("notify_on_recovery", self.notify_on_recovery)
        self.settings.setValue("cleanup_enabled", self.cleanup_enabled)
        self.settings.setValue("cleanup_days", self.cleanup_days)
        self.settings.setValue("hooks_enabled", self.hooks_enabled)
        self.settings.setValue("hooks_dir", self.hooks_dir)
        self.settings.setValue("fping_batch_size", self.fping_batch_size)

        if self._save_in_progress:
            return
        snap = self._build_snapshot()
        self._save_in_progress = True
        worker = SaveWorker(snap)
        worker.signals.finished.connect(self._on_save_finished)
        self.thread_pool.start(worker)

    def _save_data_sync(self):
        self.save_data()
        self.thread_pool.waitForDone(3000)
        for host, w in self.host_widgets.items():
            last_saved = w.last_saved_time
            new = [(t, s, lat) for (t, s, lat) in w.ping_history
                   if last_saved is None or t > last_saved]
            if not new:
                continue
            try:
                hd = self._host_dir(host)
                os.makedirs(hd, exist_ok=True)
                with open(os.path.join(hd, "meta.json"), 'w') as mf:
                    json.dump({
                        'host': host,
                        'check_type': self.host_check_types.get(host, {'type': 'icmp', 'port': None})
                    }, mf, indent=2)
                by_day = {}
                for t, s, lat in new:
                    key = t.strftime("%Y-%m-%d")
                    by_day.setdefault(key, []).append((t, s, lat))
                for day, recs in by_day.items():
                    path = os.path.join(hd, f"{day}.jsonl")
                    with open(path, 'a') as f:
                        for t, s, lat in recs:
                            f.write(json.dumps([t.isoformat(), s, lat]) + "\n")
                w.last_saved_time = max(t for t, _, _ in new)
            except Exception as e:
                print(f"[save-sync] {host}: {e}")

    @pyqtSlot(dict)
    def _on_save_finished(self, result):
        for host, latest in result.items():
            if host in self.host_widgets and latest is not None:
                self.host_widgets[host].last_saved_time = latest
        self._save_in_progress = False

    # ---------- Load ----------

    def _load_single_host_history(self, host, widget, full=False, hours_limit=None):
        """full=True — вся история; hours_limit=N — последние N часов;
        иначе — retention_hours."""
        host_dir = self._host_dir(host)
        if not os.path.isdir(host_dir):
            return 0

        meta_path = os.path.join(host_dir, "meta.json")
        check_info = {'type': 'icmp', 'port': None}
        if os.path.exists(meta_path):
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                check_info = meta.get('check_type', check_info)
            except Exception as e:
                print(f"Error reading meta for {host}: {e}")
        self.host_check_types[host] = check_info
        widget.set_check_type(check_info['type'], check_info.get('port'))

        if full:
            limit = None
        elif hours_limit is not None:
            limit = hours_limit
        else:
            limit = self.retention_hours

        records, latest_time = read_history_files(host_dir, hours_limit=limit)

        widget.ping_history = records
        widget.last_saved_time = latest_time

        failures = 0
        for _, s, _ in reversed(records):
            if not s:
                failures += 1
            else:
                break
        widget.consecutive_failures = failures

        widget.graph_widget.update_history(
            widget.ping_history, widget.session_success_count,
            widget.session_failure_count, self.app_start_time)
        return len(records)


    def load_data(self):
        hosts = self.settings.value("hosts", [], type=list)
        for hd in hosts:
            disabled = False
            if isinstance(hd, (list, tuple)) and len(hd) >= 2:
                host, category = hd[0], hd[1]
                disabled = bool(hd[2]) if len(hd) > 2 else False
            else:
                host = hd if isinstance(hd, str) else str(hd)
                category = "Default"
            if isinstance(host, str) and host:
                if category not in self.categories_list:
                    self.categories_list.append(category)
                w = HostWidget(host, self.time_scale, self.app_start_time, category)
                w.retention_hours = self.retention_hours
                w.set_disabled(disabled)
                self.host_widgets[host] = w

        # По умолчанию загружаем только последний час.
        # Полная история подтянется при прокрутке шкалы в прошлое (см. on_zoom_changed).
        for host, w in self.host_widgets.items():
            loaded = self._load_single_host_history(host, w, hours_limit=1)
            if loaded:
                print(f"[load] Loaded {loaded} records for {host}")

        self.update_host_list_display()
        self.reorder_graphs()
        self.apply_filter()
        self.update_host_queue()

        if self.host_widgets:
            self.start_pinging()

    def on_zoom_changed(self):
        """Реагирует на изменение временного окна.
        Если пользователь ушёл назад дальше загруженного — подгружает полную историю."""
        if self._history_fully_loaded or self._history_loading_in_progress:
            return
        if not self.host_widgets:
            return

        if self.time_scale.zoom_periods:
            visible_start = self.time_scale.zoom_periods[-1][0]
        else:
            visible_start = self.time_scale.start_time
        if visible_start is None:
            return

        # Порог: дефолт 1 час + небольшой запас
        threshold = datetime.now() - timedelta(hours=1, minutes=5)
        if visible_start < threshold:
            self.start_full_history_load()

    def start_full_history_load(self):
        self._history_loading_in_progress = True
        print("[history] Loading full history in background...")
        host_dirs = {host: self._host_dir(host) for host in self.host_widgets}
        worker = HistoryLoadWorker(host_dirs, self.retention_hours)
        worker.signals.finished.connect(self._on_full_history_loaded)
        self.thread_pool.start(worker)

    @pyqtSlot(dict)
    def _on_full_history_loaded(self, result):
        self._history_loading_in_progress = False
        self._history_fully_loaded = True
        merged_count = 0
        for host, data in result.items():
            if host not in self.host_widgets:
                continue
            w = self.host_widgets[host]
            file_records = data.get('records', [])
            file_latest = data.get('latest_time')

            # Записи, пришедшие в память пока шла загрузка (новее файловых)
            if file_latest is not None:
                memory_new = [r for r in w.ping_history if r[0] > file_latest]
            else:
                memory_new = list(w.ping_history)

            merged = file_records + memory_new
            merged.sort(key=lambda x: x[0])
            w.ping_history = merged
            if file_latest is not None:
                w.last_saved_time = file_latest
            merged_count += len(merged)

            failures = 0
            for _, s, _ in reversed(merged):
                if not s:
                    failures += 1
                else:
                    break
            w.consecutive_failures = failures

            w.graph_widget.update_history(
                w.ping_history, w.session_success_count,
                w.session_failure_count, self.app_start_time)

        print(f"[history] Full history loaded ({merged_count} records total)")
        self.update_all_graphs()
        self.apply_filter()

    def update_all_graphs(self):
        for w in self.host_widgets.values():
            w.graph_widget.update_history(
                w.ping_history, w.session_success_count,
                w.session_failure_count, self.app_start_time)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PingMonitor()
    window.show()
    sys.exit(app.exec())
