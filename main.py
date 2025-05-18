# main.py
import sys
import json
import os
import gettext
from datetime import datetime, timedelta
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QTreeWidget, QTreeWidgetItem, QLineEdit,
                             QLabel, QMessageBox, QInputDialog, QSlider, QScrollArea, 
                             QFrame, QToolButton, QMenu, QPushButton, QSystemTrayIcon, 
                             QFileDialog, QDialog, QComboBox, QDialogButtonBox, QTextEdit)
from PyQt6.QtCore import Qt, QRect, QSettings, QPoint, QTimer, QThreadPool, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPainter, QColor, QFont, QIcon, QPixmap, QAction
from ping_manager import PingManager, PingWorker
from PyQt6.QtWidgets import QGraphicsOpacityEffect

def setup_localization(lang):
    """Настройка локализации приложения"""
    localedir = os.path.join(os.path.dirname(__file__), 'translations')
    translation = gettext.translation('qping', localedir, languages=[lang], fallback=True)
    translation.install()
    return translation.gettext

class TimeScaleWidget(QWidget):
    """Виджет временной шкалы для графиков"""
    
    def __init__(self, parent=None):
        """Инициализация временной шкалы"""
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
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.reset_zoom()
        
    def reset_zoom(self):
        """Сброс масштаба к значениям по умолчанию"""
        current_time = datetime.now()
        self.start_time = current_time - timedelta(minutes=30)
        self.end_time = current_time + timedelta(minutes=30)
        self.zoom_start = None
        self.zoom_end = None
        self.zoom_periods = []
        self.is_setting_zoom_start = True
        self.indicator_pos = None
        self.zoom_factor = 1.0
        self.update()
        parent = self.parent()
        if parent and hasattr(parent, 'update_all_graphs') and hasattr(parent, 'host_widgets'):
            parent.update_all_graphs()
        
    def add_zoom_period(self, start, end):
        """Добавление периода масштабирования"""
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
            parent = self.parent()
            if parent and hasattr(parent, 'update_all_graphs') and hasattr(parent, 'host_widgets'):
                parent.update_all_graphs()
    
    def wheelEvent(self, event):
        """Обработка масштабирования колесом мыши"""
        pos_x = event.position().x()
        width = self.width()
        
        if self.zoom_periods:
            current_start, current_end = self.zoom_periods[-1]
        else:
            current_start, current_end = self.start_time, self.end_time
        
        total_seconds = (current_end - current_start).total_seconds()
        cursor_time = current_start + timedelta(seconds=pos_x / width * total_seconds)
        
        zoom_direction = 1 if event.angleDelta().y() > 0 else -1
        self.zoom_factor *= 1.1 if zoom_direction > 0 else 0.9
        self.zoom_factor = max(0.1, min(10.0, self.zoom_factor))
        
        current_duration = total_seconds
        new_duration = current_duration / self.zoom_factor
        
        time_ratio = (cursor_time - current_start).total_seconds() / current_duration
        new_start = cursor_time - timedelta(seconds=new_duration * time_ratio)
        new_end = new_start + timedelta(seconds=new_duration)
        
        if self.zoom_periods:
            self.zoom_periods[-1] = (new_start, new_end)
        else:
            self.zoom_periods.append((new_start, new_end))
        self.zoom_start, self.zoom_end = new_start, new_end
        self.update()
        
        parent = self.parent()
        if parent and hasattr(parent, 'update_all_graphs') and hasattr(parent, 'host_widgets'):
            parent.update_all_graphs()
        
    def mousePressEvent(self, event):
        """Обработка нажатий мыши для установки масштаба"""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().x()
            time_pos = self.pos_to_time(pos)
            if self.is_setting_zoom_start:
                self.zoom_start = time_pos
                self.zoom_end = None
                self.indicator_pos = pos
                self.is_setting_zoom_start = False
            else:
                self.add_zoom_period(self.zoom_start, time_pos)
                self.is_setting_zoom_start = True
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self.reset_zoom()
            
    def mouseMoveEvent(self, event):
        """Обработка перемещения мыши"""
        pass
            
    def pos_to_time(self, pos_x):
        """Преобразование позиции в шкале во время"""
        width = self.width()
        if self.zoom_start and self.zoom_end and self.zoom_periods:
            total_seconds = (self.zoom_end - self.zoom_start).total_seconds()
            return self.zoom_start + timedelta(seconds=pos_x / width * total_seconds)
        else:
            total_seconds = (self.end_time - self.start_time).total_seconds()
            return self.start_time + timedelta(seconds=pos_x / width * total_seconds)
        
    def paintEvent(self, event):
        """Отрисовка временной шкалы"""
        painter = QPainter(self)
        width = self.width()
        painter.setPen(QColor(Qt.GlobalColor.black))
        font = QFont("Arial", 8)
        painter.setFont(font)
        
        if self.zoom_periods:
            self.zoom_start, self.zoom_end = self.zoom_periods[-1]
            visible_seconds = (self.zoom_end - self.zoom_start).total_seconds()
            if visible_seconds <= 0:
                return
                
            pixels_per_second = width / visible_seconds
            
            if visible_seconds <= 10:
                step = 1
                format_str = "%H:%M:%S"
                label_step = 5
            elif visible_seconds <= 60:
                step = 5
                format_str = "%H:%M:%S"
                label_step = 15
            elif visible_seconds <= 300:
                step = 15
                format_str = "%H:%M:%S"
                label_step = 60
            elif visible_seconds <= 1800:
                step = 60
                format_str = "%H:%M"
                label_step = 300
            elif visible_seconds <= 7200:
                step = 600
                format_str = "%H:%M"
                label_step = 600
            else:
                step = 3600
                format_str = "%H:%M"
                label_step = 3600
                
            current = self.zoom_start.replace(microsecond=0)
            if step < 60:
                current = current.replace(second=(current.second // step) * step)
            elif step < 3600:
                current = current.replace(minute=(current.minute // (step//60)) * (step//60), second=0)
            else:
                current = current.replace(hour=(current.hour // (step//3600)) * (step//3600), minute=0, second=0)
                
            while current <= self.zoom_end:
                pos = int((current - self.zoom_start).total_seconds() * pixels_per_second)
                if 0 <= pos <= width:
                    line_height = 15 if (step < 60 and current.second % label_step == 0) or \
                                     (step >= 60 and step < 3600 and (current.minute * 60 + current.second) % label_step == 0) or \
                                     (step >= 3600 and (current.hour * 3600 + current.minute * 60 + current.second) % label_step == 0) else 5
                    painter.drawLine(pos, 0, pos, line_height)
                    
                    if (step < 60 and current.second % label_step == 0) or \
                       (step >= 60 and step < 3600 and (current.minute * 60 + current.second) % label_step == 0) or \
                       (step >= 3600 and (current.hour * 3600 + current.minute * 60 + current.second) % label_step == 0):
                        text_rect = QRect(pos - 50, 20, 100, 20)
                        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, current.strftime(format_str))
                current += timedelta(seconds=step)
        else:
            total_seconds = (self.end_time - self.start_time).total_seconds()
            pixels_per_second = width / total_seconds
            
            step = 600
            current = self.start_time.replace(microsecond=0, second=0)
            current = current.replace(minute=(current.minute // 10) * 10)
            
            while current <= self.end_time:
                pos = int((current - self.start_time).total_seconds() * pixels_per_second)
                if 0 <= pos <= width:
                    painter.drawLine(pos, 0, pos, 15)
                    text_rect = QRect(pos - 25, 20, 50, 20)
                    painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, current.strftime("%H:%M"))
                current += timedelta(minutes=10)
        
        if self.indicator_pos is not None:
            painter.setPen(QColor("blue"))
            painter.drawLine(int(self.indicator_pos), 0, int(self.indicator_pos), self.height())
            
class PingGraphWidget(QWidget):
    """Виджет для отображения графика ping"""
    
    BAR_WIDTH = 4
    
    def __init__(self, time_scale, host, parent=None):
        """Инициализация графика"""
        super().__init__(parent)
        self.time_scale = time_scale
        self.host = host
        self.setMinimumHeight(60)
        self.history = []
        self.session_success_count = 0
        self.session_failure_count = 0
        self.app_start_time = None
        
    def update_history(self, history, session_success_count, session_failure_count, app_start_time):
        """Обновление данных истории и статистики"""
        self.history = history
        self.session_success_count = session_success_count
        self.session_failure_count = session_failure_count
        self.app_start_time = app_start_time
        
        total_checks = self.session_success_count + self.session_failure_count
        failure_rate = (self.session_failure_count / total_checks * 100) if total_checks > 0 else 0
        tooltip = (
            f"Время запуска: {self.app_start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Успешные проверки: {self.session_success_count}\n"
            f"Проваленные проверки: {self.session_failure_count}\n"
            f"Процент провалов: {failure_rate:.1f}%"
        )
        self.setToolTip(tooltip)
        self.update()
        
    def mouseDoubleClickEvent(self, event):
        """Обработка двойного клика на графике"""
        if event.button() == Qt.MouseButton.LeftButton:
            parent = self.parent()
            while parent and not isinstance(parent, HostWidget):
                parent = parent.parent()
            if parent:
                main_window = parent.parent()
                while main_window and not isinstance(main_window, PingMonitor):
                    main_window = main_window.parent()
                if main_window:
                    main_window.move_host_to_queue_start(self.host)
        
    def paintEvent(self, event):
        """Отрисовка графика"""
        if not self.history or not self.time_scale.start_time:
            return
            
        painter = QPainter(self)
        width = self.width()
        height = self.height()
        
        if self.time_scale.zoom_periods:
            visible_start, visible_end = self.time_scale.zoom_periods[-1]
            visible_seconds = (visible_end - visible_start).total_seconds()
            if visible_seconds <= 0:
                return
            pixels_per_second = width / visible_seconds
            
            for timestamp, success in self.history:
                if timestamp < visible_start or timestamp > visible_end:
                    continue
                    
                pos = int((timestamp - visible_start).total_seconds() * pixels_per_second)
                color = QColor("#4CAF50" if success else "#F44336")
                bar_width = max(1, min(self.BAR_WIDTH, int(pixels_per_second * 1)))
                painter.fillRect(QRect(pos - bar_width//2, 0, bar_width, height), color)
        else:
            total_seconds = (self.time_scale.end_time - self.time_scale.start_time).total_seconds()
            pixels_per_second = width / total_seconds
            
            for timestamp, success in self.history:
                pos = int((timestamp - self.time_scale.start_time).total_seconds() * pixels_per_second)
                color = QColor("#4CAF50" if success else "#F44336")
                painter.fillRect(QRect(pos - self.BAR_WIDTH//2, 0, self.BAR_WIDTH, height), color)

class HostWidget(QWidget):
    """Виджет для отображения информации о хосте"""
    
    def __init__(self, host, time_scale, app_start_time, category="Default"):
        """Инициализация виджета хоста"""
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
        
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        self.host_label = QLabel(host)
        self.host_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.graph_widget = PingGraphWidget(time_scale, host, self)
        self.graph_widget.update_history(
            self.ping_history, self.session_success_count, self.session_failure_count, self.app_start_time
        )
        
        layout.addWidget(self.host_label)
        layout.addWidget(self.graph_widget)

    def update_status(self, success, current_time):
        """Обновление статуса хоста"""
        if not success:
            self.consecutive_failures += 1
            self.session_failure_count += 1
        else:
            self.consecutive_failures = 0
            self.session_success_count += 1
            
        self.ping_history.append((current_time, success))
        cutoff_time = current_time - timedelta(hours=48)
        self.ping_history = [h for h in self.ping_history if h[0] > cutoff_time]
        self.graph_widget.update_history(
            self.ping_history, self.session_success_count, self.session_failure_count, self.app_start_time
        )
        
        return self.consecutive_failures

class PingMonitor(QMainWindow):
    """Главное окно приложения Ping Monitor"""
    
    def __init__(self):
        """Инициализация главного окна"""
        super().__init__()
        self.settings = QSettings("PingMonitor", "AppSettings")
        self.language = self.settings.value("language", "ru")
        self._ = setup_localization(self.language)
        self.setWindowTitle(self._("Ping Monitor"))
        self.setGeometry(100, 100, 1200, 700)
        
        self.app_start_time = datetime.now()
        self.notifications_enabled = self.settings.value("notifications_enabled", True, type=bool)
        self.is_quitting = False
        self.filter_failed = self.settings.value("filter_failed", False, type=bool)
        
        self.green_icon = self.create_icon("#4CAF50")
        self.yellow_icon = self.create_icon("#FFEB3B")
        self.red_icon = self.create_icon("#F44336")
        self.setWindowIcon(self.green_icon)
        
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.green_icon)
        self.tray_icon.setVisible(True)
        
        tray_menu = QMenu()
        restore_action = QAction(self._("Restore"), self)
        restore_action.triggered.connect(self.restore_window)
        quit_action = QAction(self._("Quit"), self)
        quit_action.triggered.connect(self.quit_application)
        tray_menu.addAction(restore_action)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        
        self.tray_icon.activated.connect(self.tray_icon_activated)
        
        # Устанавливаем только необходимые флаги для кнопок минимизации и закрытия
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowMinimizeButtonHint | Qt.WindowType.WindowCloseButtonHint)
        
        self.time_scale = TimeScaleWidget(self)
        self.host_list = QTreeWidget()
        self.host_list.setHeaderHidden(True)
        self.host_list.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
        self.host_list.setSelectionMode(QTreeWidget.SelectionMode.MultiSelection)
        self.host_list.setDragEnabled(True)
        self.host_list.setAcceptDrops(True)
        self.host_list.setDropIndicatorShown(True)
        self.host_list.itemDoubleClicked.connect(self.scroll_to_host_widget)
        self.host_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.host_list.customContextMenuRequested.connect(self.show_host_context_menu)
        self.host_list.model().rowsMoved.connect(self.handle_host_moved)
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        
        self.host_widgets = {}
        self.current_pinging_host = None
        self.host_queue = []
        self.current_host_index = 0
        self.host_check_types = {}
        self.highlight_animation = None
        
        saved_interval = self.settings.value("interval", 500, type=int)
        
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(10)
        
        self.ping_manager = PingManager(saved_interval)
        self.ping_manager.ping_result.connect(self.handle_ping_result)
        
        self.ping_timer = QTimer()
        self.ping_timer.timeout.connect(self.ping_next_host)
        
        self.setup_ui()
        self.load_data()
        self.interval_slider.setValue(saved_interval)
        self.update_interval(saved_interval)
        self.time_scale.reset_zoom()
        
        if self.host_widgets:
            self.start_pinging()

    def create_icon(self, color):
        """Создание иконки указанного цвета"""
        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor(color))
        return QIcon(pixmap)

    def quit_application(self):
        """Обработка выхода из приложения"""
        self.is_quitting = True
        QApplication.quit()

    def closeEvent(self, event):
        """Обработка закрытия окна"""
        if not self.is_quitting:
            event.ignore()
            self.hide()
        else:
            event.accept()

    def restore_window(self):
        """Восстановление окна из трея"""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def tray_icon_activated(self, reason):
        """Обработка действий с иконкой в трее"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.restore_window()

    def scroll_to_host_widget(self, item, column):
        """Прокрутка к виджету хоста и запуск анимации выделения"""
        host = item.data(0, Qt.ItemDataRole.UserRole)
        if host and host in self.host_widgets:
            widget = self.host_widgets[host]
            self.scroll_area.ensureWidgetVisible(widget)
            self.start_highlight_animation(widget)

    def start_highlight_animation(self, widget):
        """Запуск анимации выделения виджета хоста"""
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
        """Обработка перемещения хоста в списке"""
        self.update_host_queue()
        self.reorder_graphs()
        self.save_data()

    def add_category_separator(self, category):
        """Добавление разделителя категории в right_panel_layout"""
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        
        label = QLabel(f"[{category}]")
        label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        label.setStyleSheet("padding: 5px;")
        
        container = QWidget()
        container_layout = QHBoxLayout()
        container_layout.addWidget(label)
        container_layout.addWidget(separator)
        container.setLayout(container_layout)
        
        return container

    def reorder_graphs(self):
        """Переупорядочивание виджетов графиков с разделением по категориям"""
        for i in reversed(range(self.right_panel_layout.count())):
            widget = self.right_panel_layout.itemAt(i).widget()
            if widget:
                self.right_panel_layout.removeWidget(widget)
                widget.setParent(None)
        
        categories = sorted(set(widget.category for widget in self.host_widgets.values()))
        for category in categories:
            separator = self.add_category_separator(category)
            self.right_panel_layout.addWidget(separator)
            def traverse_items(parent_item):
                for i in range(parent_item.childCount()):
                    child = parent_item.child(i)
                    host = child.data(0, Qt.ItemDataRole.UserRole)
                    if host and host in self.host_widgets and self.host_widgets[host].category == category:
                        self.right_panel_layout.addWidget(self.host_widgets[host])
            
            for i in range(self.host_list.topLevelItemCount()):
                category_item = self.host_list.topLevelItem(i)
                if category_item.data(0, Qt.ItemDataRole.UserRole) == category:
                    traverse_items(category_item)

    def move_host_to_queue_start(self, host):
        """Временное перемещение хоста в начало очереди проверки без изменения порядка списка"""
        if host not in self.host_queue:
            return
        self.host_queue.remove(host)
        self.host_queue.insert(0, host)
        self.current_host_index = 0
        self.ping_next_host()

    def setup_ui(self):
        """Настройка пользовательского интерфейса"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout()
        central_widget.setLayout(layout)
        
        menu_bar = self.menuBar()
        help_menu = menu_bar.addMenu(self._("Help"))
        help_action = QAction(self._("User Guide"), self)
        help_action.triggered.connect(self.show_help)
        help_menu.addAction(help_action)
        
        language_menu = menu_bar.addMenu(self._("Language"))
        ru_action = QAction("Русский", self)
        en_action = QAction("English", self)
        ru_action.triggered.connect(lambda: self.change_language("ru"))
        en_action.triggered.connect(lambda: self.change_language("en"))
        language_menu.addAction(ru_action)
        language_menu.addAction(en_action)
        
        control_panel = QWidget()
        control_layout = QHBoxLayout()
        control_panel.setLayout(control_layout)
        
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
            self._("Notifications: On" if self.notifications_enabled else "Notifications: Off")
        )
        self.mute_button.clicked.connect(self.toggle_notifications)
        
        self.filter_button = QPushButton(
            self._("Show Failed Hosts" if not self.filter_failed else "Show All Hosts")
        )
        self.filter_button.clicked.connect(self.toggle_filter)
        
        control_layout.addWidget(self.host_input)
        control_layout.addWidget(self.add_button)
        control_layout.addWidget(self.import_button)
        control_layout.addWidget(QLabel(self._("Interval:")))
        control_layout.addWidget(self.interval_slider)
        control_layout.addWidget(self.interval_label)
        control_layout.addWidget(self.mute_button)
        control_layout.addWidget(self.filter_button)
        
        main_panel = QHBoxLayout()
        
        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_panel.setLayout(left_layout)
        
        left_layout.addWidget(QLabel(self._("Monitored Hosts:")))
        left_layout.addWidget(self.host_list)
        
        right_panel = QWidget()
        right_layout = QVBoxLayout()
        right_panel.setLayout(right_layout)
        
        right_layout.addWidget(self.time_scale)
        right_layout.addWidget(self.scroll_area)
        
        scroll_content = QWidget()
        self.right_panel_layout = QVBoxLayout()
        scroll_content.setLayout(self.right_panel_layout)
        self.scroll_area.setWidget(scroll_content)
        
        main_panel.addWidget(left_panel, 25)
        main_panel.addWidget(right_panel, 75)
        
        layout.addWidget(control_panel)
        layout.addLayout(main_panel)

    def toggle_notifications(self):
        """Переключение уведомлений"""
        self.notifications_enabled = not self.notifications_enabled
        self.mute_button.setText(
            self._("Notifications: On" if self.notifications_enabled else "Notifications: Off")
        )
        self.settings.setValue("notifications_enabled", self.notifications_enabled)

    def toggle_filter(self):
        """Переключение режима фильтрации"""
        self.filter_failed = not self.filter_failed
        self.filter_button.setText(
            self._("Show Failed Hosts" if not self.filter_failed else "Show All Hosts")
        )
        self.settings.setValue("filter_failed", self.filter_failed)
        self.apply_filter()

    def apply_filter(self):
        """Применение фильтра для отображения хостов"""
        for i in range(self.host_list.topLevelItemCount()):
            category_item = self.host_list.topLevelItem(i)
            visible_hosts = 0
            for j in range(category_item.childCount()):
                host_item = category_item.child(j)
                host = host_item.data(0, Qt.ItemDataRole.UserRole)
                widget = self.host_widgets.get(host)
                if not widget:
                    continue
                should_show = True
                if self.filter_failed:
                    should_show = (len(widget.ping_history) > 0 and not widget.ping_history[-1][1])
                host_item.setHidden(not should_show)
                widget.setVisible(should_show)
                if should_show:
                    visible_hosts += 1
            category_item.setText(0, f"[{category_item.data(0, Qt.ItemDataRole.UserRole)}] ({visible_hosts})")
            category_item.setHidden(visible_hosts == 0)

    def show_help(self):
        """Показать прокручиваемое руководство пользователя"""
        help_text = (
            self._("<h2>Ping Monitor User Guide</h2>") +
            self._("<p>Ping Monitor is a tool for monitoring the availability of network hosts using ICMP ping or TCP port checks.</p>") +
            self._("<h3>Getting Started</h3>") +
            self._("<ul>"
                   "<li><b>Add a host</b>: Enter an IP address or domain in the input field and click 'Add Host' or press Enter.</li>"
                   "<li><b>Import hosts</b>: Use 'Import from File' to add multiple hosts from a text file (one host per line).</li>"
                   "<li><b>Monitor hosts</b>: The application automatically starts pinging hosts once added.</li>"
                   "</ul>") +
            self._("<h3>Host Management</h3>") +
            self._("<ul>"
                   "<li><b>Edit host</b>: Right-click a host in the list and select 'Edit' to change its address (available for a single host).</li>"
                   "<li><b>Delete host</b>: Select one or more hosts, right-click, and select 'Delete' to remove them.</li>"
                   "<li><b>Change check type</b>: Right-click a host, select 'Check Type', and choose 'ICMP Ping' or 'TCP Port'. For TCP, specify a port number (1–65535). Available for a single host.</li>"
                   "<li><b>Reorder hosts</b>: Drag and drop hosts within or between categories to change their order.</li>"
                   "<li><b>Group hosts</b>: Select one or more hosts, right-click, and select 'Set Category' to assign them to an existing category or create a new one. Categories are collapsible and show the number of hosts in parentheses. Graphs are grouped by categories with separators.</li>"
                   "<li><b>Navigate to graph</b>: Double-click a host in the list to scroll to its graph.</li>"
                   "<li><b>Filter hosts</b>: Click 'Show Failed Hosts' to display only hosts with a failed last check. Click 'Show All Hosts' to return to the full list.</li>"
                   "<li><b>Prioritize host check</b>: Double-click a host's graph to temporarily prioritize its check, ensuring it is checked next without changing its position in the list or graph order.</li>"
                   "</ul>") +
            self._("<h3>Time Scale</h3>") +
            self._("<ul>"
                   "<li><b>Zoom</b>: Click on the time scale to set start and end points for zooming. Right-click to reset to default (1 hour centered on current time).</li>"
                   "<li><b>Scroll zoom</b>: Use the mouse wheel to zoom in/out while maintaining the cursor's time position.</li>"
                   "<li><b>View history</b>: The graph shows ping results as green (success) or red (failure) bars.</li>"
                   "</ul>") +
            self._("<h3>System Tray</h3>") +
            self._("<ul>"
                   "<li><b>Minimize</b>: Closing the window minimizes the application to the system tray.</li>"
                   "<li><b>Restore</b>: Double-click the tray icon or select 'Restore' from the tray menu to show the window.</li>"
                   "<li><b>Quit</b>: Select 'Quit' from the tray menu to close the application.</li>"
                   "</ul>")
        )
        
        # Создаем кастомный диалог для прокручиваемого текста
        help_dialog = QDialog(self)
        help_dialog.setWindowTitle(self._("User Guide"))
        help_dialog.resize(600, 400)  # Устанавливаем размер диалога
        
        layout = QVBoxLayout()
        
        # Создаем QTextEdit для отображения HTML-текста
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setHtml(help_text)
        
        # Помещаем QTextEdit в QScrollArea
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(text_edit)
        
        # Добавляем QScrollArea в layout
        layout.addWidget(scroll_area)
        
        # Добавляем кнопку OK
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        button_box.accepted.connect(help_dialog.accept)
        layout.addWidget(button_box)
        
        help_dialog.setLayout(layout)
        help_dialog.exec()

    def change_language(self, lang):
        """Изменение языка интерфейса"""
        self.language = lang
        self._ = setup_localization(lang)
        self.settings.setValue("language", lang)
        self.retranslate_ui()

    def retranslate_ui(self):
        """Обновление текстов интерфейса при смене языка"""
        self.setWindowTitle(self._("Ping Monitor"))
        self.host_input.setPlaceholderText(self._("Enter IP/domain"))
        self.add_button.setText(self._("Add Host"))
        self.import_button.setText(self._("Import from File"))
        self.interval_label.setText(self._("Interval: {}ms").format(self.interval_slider.value()))
        self.mute_button.setText(
            self._("Notifications: On" if self.notifications_enabled else "Notifications: Off")
        )
        self.filter_button.setText(
            self._("Show Failed Hosts" if not self.filter_failed else "Show All Hosts")
        )
        menu_bar = self.menuBar()
        menu_bar.clear()
        help_menu = menu_bar.addMenu(self._("Help"))
        help_action = QAction(self._("User Guide"), self)
        help_action.triggered.connect(self.show_help)
        help_menu.addAction(help_action)
        language_menu = menu_bar.addMenu(self._("Language"))
        ru_action = QAction("Русский", self)
        en_action = QAction("English", self)
        ru_action.triggered.connect(lambda: self.change_language("ru"))
        en_action.triggered.connect(lambda: self.change_language("en"))
        language_menu.addAction(ru_action)
        language_menu.addAction(en_action)
        self.tray_icon.setContextMenu(None)
        tray_menu = QMenu()
        restore_action = QAction(self._("Restore"), self)
        restore_action.triggered.connect(self.restore_window)
        quit_action = QAction(self._("Quit"), self)
        quit_action.triggered.connect(self.quit_application)
        tray_menu.addAction(restore_action)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.update_host_list_display()

    def show_host_context_menu(self, position):
        """Показать контекстное меню для хоста"""
        selected_items = self.host_list.selectedItems()
        menu = QMenu()
        
        selected_hosts = [item.data(0, Qt.ItemDataRole.UserRole) for item in selected_items 
                         if item.data(0, Qt.ItemDataRole.UserRole)]
        
        if selected_hosts:
            edit_action = QAction(self._("Edit"), self)
            edit_action.triggered.connect(lambda: self.edit_host(selected_hosts[0]))
            edit_action.setEnabled(len(selected_hosts) == 1)
            
            delete_action = QAction(self._("Delete"), self)
            delete_action.triggered.connect(lambda: self.delete_hosts(selected_hosts))
            
            check_type_menu = QMenu(self._("Check Type"), self)
            icmp_action = QAction(self._("ICMP Ping"), self)
            tcp_action = QAction(self._("TCP Port"), self)
            
            icmp_action.triggered.connect(lambda: self.set_check_type(selected_hosts[0], 'icmp'))
            tcp_action.triggered.connect(lambda: self.set_check_type(selected_hosts[0], 'tcp'))
            check_type_menu.addAction(icmp_action)
            check_type_menu.addAction(tcp_action)
            check_type_menu.setEnabled(len(selected_hosts) == 1)
            
            set_category_action = QAction(self._("Set Category"), self)
            set_category_action.triggered.connect(lambda: self.set_host_category(selected_hosts))
            
            menu.addAction(edit_action)
            menu.addAction(delete_action)
            menu.addMenu(check_type_menu)
            menu.addAction(set_category_action)
        else:
            import_action = QAction(self._("Import from File"), self)
            import_action.triggered.connect(self.import_hosts_from_file)
            menu.addAction(import_action)
        
        menu.exec(self.host_list.mapToGlobal(position))

    def set_check_type(self, host, check_type):
        """Установка типа проверки для хоста"""
        if check_type == 'tcp':
            port, ok = QInputDialog.getInt(
                self, self._("TCP Port"), self._("Enter port number (1-65535):"),
                value=80, min=1, max=65535
            )
            if not ok:
                return
            self.host_check_types[host] = {'type': 'tcp', 'port': port}
        else:
            self.host_check_types[host] = {'type': 'icmp', 'port': None}
        self.save_data()
        self.apply_filter()

    def set_host_category(self, hosts):
        """Установка категории для одного или нескольких хостов"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QComboBox, QLineEdit, QDialogButtonBox
        
        class CategoryDialog(QDialog):
            def __init__(self, parent, existing_categories):
                super().__init__(parent)
                self.setWindowTitle(parent._("Set Category"))
                layout = QVBoxLayout(self)
                
                self.combo = QComboBox()
                # Сначала добавляем "Default" как категорию по умолчанию
                self.combo.addItem("Default")
                # Затем добавляем остальные существующие категории
                self.combo.addItems(sorted([cat for cat in existing_categories if cat != "Default"]))
                # В конце добавляем "New Category"
                self.combo.addItem(parent._("New Category"))
                layout.addWidget(self.combo)
                
                self.text_input = QLineEdit()
                self.text_input.setPlaceholderText(parent._("Enter new category name"))
                self.text_input.setVisible(False)
                layout.addWidget(self.text_input)
                
                self.combo.currentIndexChanged.connect(self.toggle_text_input)
                
                button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
                button_box.accepted.connect(self.accept)
                button_box.rejected.connect(self.reject)
                layout.addWidget(button_box)
            
            def toggle_text_input(self, index):
                # Показываем поле ввода только если выбрана "New Category"
                self.text_input.setVisible(self.combo.currentText() == self.parent()._("New Category"))
            
            def get_category(self):
                if self.combo.currentText() == self.parent()._("New Category"):
                    return self.text_input.text().strip()
                return self.combo.currentText()
        
        # Получаем существующие категории, включая "Default"
        existing_categories = sorted(set(widget.category for widget in self.host_widgets.values()))
        if "Default" not in existing_categories:
            existing_categories.append("Default")
        dialog = CategoryDialog(self, existing_categories)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            category = dialog.get_category()
            if category:
                for host in hosts:
                    if host in self.host_widgets:
                        self.host_widgets[host].category = category
                self.update_host_list_display()
                self.reorder_graphs()
                self.save_data()
                self.apply_filter()

    def delete_hosts(self, hosts):
        """Удаление нескольких хостов из мониторинга"""
        reply = QMessageBox.question(
            self, self._("Delete"), self._("Delete {} hosts?").format(len(hosts)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            for host in hosts:
                if host in self.host_widgets:
                    self.host_widgets[host].deleteLater()
                    del self.host_widgets[host]
            self.update_host_list_display()
            self.reorder_graphs()
            self.save_data()
            self.apply_filter()
            self.update_host_queue()
            
            if not self.host_widgets:
                self.ping_timer.stop()

    def update_host_list_display(self):
        """Обновление отображения дерева хостов с категориями"""
        self.host_list.clear()
        categories = sorted(set(widget.category for widget in self.host_widgets.values()))
        for category in categories:
            category_item = QTreeWidgetItem(self.host_list)
            category_item.setText(0, f"[{category}] (0)")
            category_item.setData(0, Qt.ItemDataRole.UserRole, category)
            category_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsDropEnabled)
            category_item.setBackground(0, QColor("#E0E0E0"))
            category_item.setExpanded(True)
            self.host_list.addTopLevelItem(category_item)
        
        for host, widget in sorted(self.host_widgets.items()):
            for i in range(self.host_list.topLevelItemCount()):
                category_item = self.host_list.topLevelItem(i)
                if category_item.data(0, Qt.ItemDataRole.UserRole) == widget.category:
                    host_item = QTreeWidgetItem(category_item)
                    host_item.setText(0, host)
                    host_item.setData(0, Qt.ItemDataRole.UserRole, host)
                    host_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | 
                                     Qt.ItemFlag.ItemIsDragEnabled)
                    category_item.addChild(host_item)
        
        for i in range(self.host_list.topLevelItemCount()):
            category_item = self.host_list.topLevelItem(i)
            visible_hosts = sum(1 for j in range(category_item.childCount()) if not category_item.child(j).isHidden())
            category_item.setText(0, f"[{category_item.data(0, Qt.ItemDataRole.UserRole)}] ({visible_hosts})")

    def import_hosts_from_file(self):
        """Импорт списка хостов из файла"""
        file_name, _ = QFileDialog.getOpenFileName(
            self, self._("Select host file"), "", self._("Text files (*.txt);;All files (*)"))
        
        if file_name:
            try:
                with open(file_name, 'r') as f:
                    hosts = [line.strip() for line in f if line.strip()]
                    added = 0
                    for host in hosts:
                        if host and host not in self.host_widgets:
                            widget = HostWidget(host, self.time_scale, self.app_start_time)
                            self.host_widgets[host] = widget
                            added += 1
                    
                    if added > 0:
                        self.update_host_list_display()
                        self.reorder_graphs()
                        self.save_data()
                        self.apply_filter()
                        if not self.ping_timer.isActive():
                            self.start_pinging()
                        else:
                            self.update_host_queue()
                        
                        QMessageBox.information(
                            self, self._("Import completed"), 
                            self._("Successfully added {} hosts from file.").format(added))
                    else:
                        QMessageBox.warning(
                            self, self._("Import failed"), 
                            self._("No new hosts added (they may already exist)."))
            except Exception as e:
                QMessageBox.critical(
                    self, self._("Import error"), 
                    self._("Failed to read file: {}").format(str(e)))

    def update_app_icon(self):
        """Обновление иконки приложения в зависимости от статуса хостов"""
        has_red = any(
            len(w.ping_history) >= 2 and 
            not w.ping_history[-1][1] and 
            not w.ping_history[-2][1]
            for w in self.host_widgets.values())
        has_yellow = any(
            len(w.ping_history) >= 1 and 
            not w.ping_history[-1][1] and 
            (len(w.ping_history) == 1 or w.ping_history[-2][1])
            for w in self.host_widgets.values())
        
        if has_red:
            self.setWindowIcon(self.red_icon)
            self.tray_icon.setIcon(self.red_icon)
        elif has_yellow:
            self.setWindowIcon(self.yellow_icon)
            self.tray_icon.setIcon(self.yellow_icon)
        else:
            self.setWindowIcon(self.green_icon)
            self.tray_icon.setIcon(self.green_icon)

    def update_host_queue(self):
        """Обновление очереди проверяемых хостов"""
        self.host_queue = []
        def traverse_items(parent_item):
            for i in range(parent_item.childCount()):
                child = parent_item.child(i)
                host = child.data(0, Qt.ItemDataRole.UserRole)
                if host:
                    self.host_queue.append(host)
        
        for i in range(self.host_list.topLevelItemCount()):
            category_item = self.host_list.topLevelItem(i)
            traverse_items(category_item)
        self.current_host_index = 0

    def start_pinging(self):
        """Запуск периодической проверки хостов"""
        if self.host_widgets:
            self.update_host_queue()
            if not self.ping_timer.isActive():
                self.ping_timer.start(self.interval_slider.value())

    def ping_next_host(self):
        """Проверка следующего хоста в очереди"""
        if not self.host_queue:
            return
            
        current_time = datetime.now()
        
        if self.current_pinging_host:
            for i in range(self.host_list.topLevelItemCount()):
                category_item = self.host_list.topLevelItem(i)
                for j in range(category_item.childCount()):
                    host_item = category_item.child(j)
                    if host_item.data(0, Qt.ItemDataRole.UserRole) == self.current_pinging_host:
                        host_item.setBackground(0, QColor("white"))
                        break
        
        host = self.host_queue[self.current_host_index]
        self.current_pinging_host = host
        
        for i in range(self.host_list.topLevelItemCount()):
            category_item = self.host_list.topLevelItem(i)
            for j in range(category_item.childCount()):
                host_item = category_item.child(j)
                if host_item.data(0, Qt.ItemDataRole.UserRole) == host:
                    host_item.setBackground(0, QColor("#ADD8E6"))
                    break
        
        check_info = self.host_check_types.get(host, {'type': 'icmp', 'port': None})
        
        self.ping_manager.ping_host(
            host,
            check_type=check_info['type'],
            port=check_info['port'])
        
        self.current_host_index = (self.current_host_index + 1) % len(self.host_queue)

    def handle_ping_result(self, host, success):
        """Обработка результата ping проверки"""
        current_time = datetime.now()
        if host in self.host_widgets:
            consecutive_failures = self.host_widgets[host].update_status(success, current_time)
            if consecutive_failures == 2 and self.notifications_enabled:
                self.tray_icon.showMessage(
                    self._("Host unavailable"),
                    self._("Host {} is not responding to check").format(host),
                    QSystemTrayIcon.MessageIcon.Warning,
                    5000)
        
        self.update_app_icon()
        self.save_data()
        self.apply_filter()

    def add_host(self):
        """Добавление нового хоста для мониторинга"""
        host = self.host_input.text().strip()
        if host and host not in self.host_widgets:
            widget = HostWidget(host, self.time_scale, self.app_start_time)
            self.host_widgets[host] = widget
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
        """Обновление интервала проверки"""
        self.interval_label.setText(self._("Interval: {}ms").format(interval))
        self.ping_manager.set_ping_interval(interval)
        self.settings.setValue("interval", interval)
        
        if self.ping_timer.isActive():
            self.ping_timer.start(interval)

    def edit_host(self, host):
        """Редактирование имени хоста"""
        new_host, ok = QInputDialog.getText(
            self, self._("Edit"), self._("New host name:"), text=host)
        
        if ok and new_host and new_host != host:
            widget = self.host_widgets[host]
            widget.host_label.setText(new_host)
            widget.host = new_host
            widget.graph_widget.host = new_host
            self.host_widgets[new_host] = self.host_widgets.pop(host)
            if host in self.host_check_types:
                self.host_check_types[new_host] = self.host_check_types.pop(host)
            self.update_host_list_display()
            self.reorder_graphs()
            self.save_data()
            self.apply_filter()
            self.update_host_queue()

    def save_data(self):
        """Сохранение данных приложения"""
        hosts = []
        def traverse_items(parent_item):
            for i in range(parent_item.childCount()):
                child = parent_item.child(i)
                host = child.data(0, Qt.ItemDataRole.UserRole)
                if host and host in self.host_widgets:
                    hosts.append([host, self.host_widgets[host].category])
        
        for i in range(self.host_list.topLevelItemCount()):
            category_item = self.host_list.topLevelItem(i)
            traverse_items(category_item)
        
        self.settings.setValue("hosts", hosts)
        self.settings.setValue("filter_failed", self.filter_failed)
        
        history = {}
        for host, widget in self.host_widgets.items():
            history[host] = {
                'records': [(t.isoformat(), s) for t, s in widget.ping_history],
                'check_type': self.host_check_types.get(host, {'type': 'icmp', 'port': None})}
        
        history_file = os.path.expanduser("~/.ping_monitor_history.json")
        try:
            os.makedirs(os.path.dirname(history_file), exist_ok=True)
            with open(history_file, 'w') as f:
                json.dump(history, f, indent=2)
        except PermissionError as e:
            print(f"Permission error saving history to {history_file}: {e}")
        except Exception as e:
            print(f"Error saving history to {history_file}: {e}")

    def load_data(self):
        """Загрузка сохраненных данных приложения"""
        hosts = self.settings.value("hosts", [], type=list)
        for host_data in hosts:
            if isinstance(host_data, (list, tuple)) and len(host_data) == 2:
                host, category = host_data
            else:
                host = host_data if isinstance(host_data, str) else str(host_data)
                category = "Default"
            if isinstance(host, str) and host:
                widget = HostWidget(host, self.time_scale, self.app_start_time, category)
                self.host_widgets[host] = widget
        
        self.update_host_list_display()
        self.reorder_graphs()
        
        history_file = os.path.expanduser("~/.ping_monitor_history.json")
        try:
            with open(history_file, 'r') as f:
                history = json.load(f)
                
                for host, data in history.items():
                    if host in self.host_widgets:
                        widget = self.host_widgets[host]
                        try:
                            widget.ping_history = [
                                (datetime.fromisoformat(t), s) for t, s in data['records']]
                            widget.graph_widget.update_history(
                                widget.ping_history, widget.session_success_count,
                                widget.session_failure_count, self.app_start_time
                            )
                            self.host_check_types[host] = data.get('check_type', {'type': 'icmp', 'port': None})
                            print(f"Loaded {len(widget.ping_history)} records for {host}")
                        except Exception as e:
                            print(f"Error loading history for {host}: {e}")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"No history file found or invalid JSON at {history_file}: {e}")
        except Exception as e:
            print(f"Unexpected error loading history from {history_file}: {e}")
        
        self.apply_filter()

    def update_all_graphs(self):
        """Обновление всех графиков"""
        for widget in self.host_widgets.values():
            widget.graph_widget.update()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PingMonitor()
    window.show()
    sys.exit(app.exec())
