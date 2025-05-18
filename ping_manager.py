# ping_manager.py
import socket
from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, pyqtSlot, QThreadPool
import subprocess

class PingSignals(QObject):
    ping_result = pyqtSignal(str, bool)

class PingWorker(QRunnable):
    def __init__(self, host, interval_ms, check_type='icmp', port=None):
        super().__init__()
        self.host = host
        self.interval_ms = interval_ms
        self.check_type = check_type
        self.port = port
        self.signals = PingSignals()
    
    @pyqtSlot()
    def run(self):
        success = False
        try:
            if self.check_type == 'icmp':
                result = subprocess.run(
                    ["ping", "-c", "1", "-W", str(self.interval_ms // 1000), self.host],
                    timeout=self.interval_ms / 1000,
                    capture_output=True,
                    text=True
                )
                success = result.returncode == 0
            elif self.check_type == 'tcp':
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(self.interval_ms / 1000)
                result = sock.connect_ex((self.host, self.port))
                success = result == 0
                sock.close()
        except Exception:
            success = False
        self.signals.ping_result.emit(self.host, success)

class PingManager(QObject):
    ping_result = pyqtSignal(str, bool)
    
    def __init__(self, interval_ms):
        super().__init__()
        self.interval_ms = interval_ms
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(10)

    def ping_host(self, host, check_type='icmp', port=None):
        worker = PingWorker(host, self.interval_ms, check_type, port)
        worker.signals.ping_result.connect(self.ping_result)
        self.thread_pool.start(worker)

    def set_ping_interval(self, interval_ms):
        self.interval_ms = interval_ms
