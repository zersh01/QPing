# ping_manager.py
import socket
import subprocess
import re
import time as _time
import shutil
from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, pyqtSlot, QMetaObject, Q_ARG, Qt

_FPING_PATH = shutil.which("fping")


def has_fping():
    return _FPING_PATH is not None


class PingManager(QObject):
    # host, success, latency_ms
    ping_result = pyqtSignal(str, bool, float)

    def __init__(self, interval_ms, thread_pool):
        super().__init__()
        self.interval_ms = interval_ms
        self.thread_pool = thread_pool

    def ping_host(self, host, check_type='icmp', port=None):
        worker = PingWorker(host, self.interval_ms, check_type, port, self)
        self.thread_pool.start(worker)

    def ping_icmp_batch(self, hosts):
        """Один fping на весь список. Если fping недоступен — параллельные одиночные воркеры."""
        if not hosts:
            return
        if _FPING_PATH:
            worker = FpingBatchWorker(hosts, self.interval_ms, self)
            self.thread_pool.start(worker)
        else:
            for h in hosts:
                self.ping_host(h, 'icmp', None)

    def set_ping_interval(self, interval_ms):
        self.interval_ms = interval_ms

    @pyqtSlot(str, bool, float)
    def emit_result(self, host, success, latency):
        self.ping_result.emit(host, success, latency)


class PingWorker(QRunnable):
    def __init__(self, host, interval_ms, check_type, port, manager):
        super().__init__()
        self.host = host
        self.interval_ms = max(100, interval_ms)
        self.check_type = check_type
        self.port = port
        self.manager = manager

    @pyqtSlot()
    def run(self):
        success = False
        latency = -1.0
        timeout_sec = max(1.0, self.interval_ms / 1000.0)
        try:
            if self.check_type == 'icmp':
                success, latency = self._do_icmp(timeout_sec)
            elif self.check_type == 'tcp':
                success, latency = self._do_tcp(timeout_sec)
        except Exception:
            pass

        QMetaObject.invokeMethod(
            self.manager, "emit_result",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, self.host), Q_ARG(bool, success), Q_ARG(float, latency),
        )

    def _do_icmp(self, timeout_sec):
        if _FPING_PATH:
            timeout_ms = max(100, int(timeout_sec * 1000))
            cmd = [_FPING_PATH, "-c", "1", "-t", str(timeout_ms), self.host]
            try:
                result = subprocess.run(cmd, timeout=timeout_sec + 1.0,
                                        capture_output=True, text=True)
                out = (result.stdout or "") + "\n" + (result.stderr or "")
                alive_m = re.search(
                    r'^(\S+)\s*:\s*xmt/rcv/%loss\s*=\s*\d+/(\d+)/\d+%'
                    r'(?:.*?min/avg/max\s*=\s*[\d.]+/([\d.]+)/[\d.]+)?',
                    out, re.MULTILINE)
                if alive_m and int(alive_m.group(1)) > 0:
                    lat = float(alive_m.group(2)) if alive_m.group(2) else 0.0
                    return True, lat
                # Fallback default mode
                m = re.search(r'([\d.]+)\s*ms', out)
                if result.returncode == 0:
                    return True, float(m.group(1)) if m else 0.0
                return False, -1.0
            except Exception:
                pass
        cmd = ["ping", "-c", "1", "-W", str(int(timeout_sec)), self.host]
        try:
            result = subprocess.run(cmd, timeout=timeout_sec + 0.5,
                                    capture_output=True, text=True)
            if result.returncode == 0:
                m = re.search(r'time[=<]([\d.]+)\s*ms', result.stdout or "")
                return True, float(m.group(1)) if m else 0.0
        except Exception:
            pass
        return False, -1.0

    def _do_tcp(self, timeout_sec):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout_sec)
        start = _time.perf_counter()
        try:
            result = sock.connect_ex((self.host, self.port))
            elapsed_ms = (_time.perf_counter() - start) * 1000.0
            return (True, elapsed_ms) if result == 0 else (False, -1.0)
        except Exception:
            return False, -1.0
        finally:
            try:
                sock.close()
            except Exception:
                pass


class FpingBatchWorker(QRunnable):
    """Запускает один fping-процесс на пачку ICMP-хостов."""

    def __init__(self, hosts, interval_ms, manager):
        super().__init__()
        self.hosts = list(hosts)
        self.interval_ms = max(100, interval_ms)
        self.manager = manager

    @pyqtSlot()
    def run(self):
        timeout_sec = max(1.0, self.interval_ms / 1000.0)
        timeout_ms = max(100, int(timeout_sec * 1000))
        overall_timeout = timeout_sec + 3.0

        results = {h: (False, -1.0) for h in self.hosts}
        try:
            # -c 1 -t <ms> → count mode: одна проба, таймаут на пакет
            cmd = [_FPING_PATH, "-c", "1", "-t", str(timeout_ms)] + self.hosts
            result = subprocess.run(cmd, timeout=overall_timeout,
                                    capture_output=True, text=True)
            self._parse_lines(result.stdout or "", results)
            self._parse_lines(result.stderr or "", results)
        except Exception as e:
            print(f"[fping batch] {e}")

        for host, (success, latency) in results.items():
            QMetaObject.invokeMethod(
                self.manager, "emit_result",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, host), Q_ARG(bool, success), Q_ARG(float, latency),
            )

    def _parse_lines(self, text, results):
        """Поддерживает оба формата вывода fping:

        1) Count mode (используется с -c N):
             8.8.8.8 : xmt/rcv/%loss = 1/1/0%, min/avg/max = 20.8/20.8/20.8
             1.1.1.1 : xmt/rcv/%loss = 1/0/100%

        2) Default mode:
             8.8.8.8 is alive (12.4 ms)
             1.1.1.1 is unreachable
        """
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue

            # --- Count mode: сводка xmt/rcv/%loss ---
            m = re.match(
                r'^(\S+)\s*:\s*xmt/rcv/%loss\s*=\s*\d+/(\d+)/\d+%'
                r'(?:\s*,\s*min/avg/max\s*=\s*[\d.]+/([\d.]+)/[\d.]+)?',
                line)
            if m:
                host = m.group(1)
                rcv = int(m.group(2))
                if rcv > 0:
                    # group(3) может отсутствовать, если rcv=0 (тогда min/avg/max не выводятся)
                    latency = float(m.group(3)) if m.group(3) else 0.0
                    results[host] = (True, latency)
                else:
                    results[host] = (False, -1.0)
                continue

            # --- Default mode: alive ---
            m = re.match(r'^(\S+)\s+is\s+alive\s+\(([\d.]+)\s*ms\)', line)
            if m:
                results[m.group(1)] = (True, float(m.group(2)))
                continue

            # --- Default mode: unreachable ---
            m = re.match(r'^(\S+)\s+is\s+unreachable', line)
            if m:
                results[m.group(1)] = (False, -1.0)
                continue
