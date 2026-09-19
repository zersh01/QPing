# utils.py
"""
Утилиты и константы QPing.

Никаких зависимостей от PyQt6 — чистые функции и stdlib.
Можно импортировать из тестов, CLI-скриптов и т.п.
"""
import os
import re
import hashlib
import gettext
import json
from datetime import datetime, timedelta


# --- Пути ---
CONFIG_DIR = os.environ.get("QPING_CONFIG_DIR") or os.path.expanduser("~/.config/QPing")
HISTORY_DIR = os.path.join(CONFIG_DIR, "history")
HOOKS_DIR_DEFAULT = os.path.join(CONFIG_DIR, "hooks")

# Старый путь истории (для миграции)
OLD_HISTORY_FILE = os.path.expanduser("~/.ping_monitor_history.json")


# --- Локализация ---

def setup_localization(lang):
    localedir = os.path.join(os.path.dirname(__file__), 'translations')
    translation = gettext.translation('qping', localedir, languages=[lang], fallback=True)
    translation.install()
    return translation.gettext


# --- QSettings helpers ---

def read_bool_setting(settings, key, default):
    val = settings.value(key, default)
    if isinstance(val, str):
        return val.strip().lower() in ('true', '1', 'yes', 'on')
    return bool(val)


def read_int_setting(settings, key, default):
    try:
        return int(settings.value(key, default))
    except (TypeError, ValueError):
        return default


# --- Хосты ---

def host_safe_name(host):
    h = hashlib.sha1(host.encode('utf-8')).hexdigest()[:8]
    safe = re.sub(r'[^A-Za-z0-9._-]', '_', host)[:60]
    if not safe:
        safe = "host"
    return f"{safe}_{h}"


# --- Статистика ---

def percentile(sorted_vals, p):
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    k = max(0, min(n - 1, int(round(p / 100.0 * (n - 1)))))
    return sorted_vals[k]


def compute_latency_stats(history):
    """history: list of (datetime, success, latency_ms). Возвращает dict или None."""
    lats = [lat for (_, s, lat) in history if s and lat is not None and lat >= 0]
    if not lats:
        return None
    lats_sorted = sorted(lats)
    n = len(lats_sorted)
    mean = sum(lats_sorted) / n
    # Population standard deviation — стандартная аппроксимация jitter.
    variance = sum((x - mean) ** 2 for x in lats_sorted) / n if n > 0 else 0.0
    stdev = variance ** 0.5
    return {
        'count': n,
        'min': lats_sorted[0],
        'max': lats_sorted[-1],
        'avg': mean,
        'median': percentile(lats_sorted, 50),
        'p95': percentile(lats_sorted, 95),
        'stdev': stdev,
    }

def compute_recent_stats(history, minutes=5):
    """Статистика за последние `minutes` минут. Возвращает dict или None."""
    cutoff = datetime.now() - timedelta(minutes=minutes)
    recent = [(t, s, lat) for (t, s, lat) in history if t >= cutoff]
    return compute_latency_stats(recent)

# --- Ansible inventory ---

def parse_ansible_ini(content):
    """Ansible INI inventory. Возвращает {group: [host, ...]}.
    Использует ПЕРВОЕ поле как имя хоста."""
    groups = {}
    current_group = None
    for raw_line in content.splitlines():
        line = raw_line.split('#', 1)[0].strip()
        if not line:
            continue
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1].strip()
            if ':' in section:
                section = section.split(':', 1)[0]
            current_group = section or "all"
            groups.setdefault(current_group, [])
            continue
        if current_group is None:
            current_group = "all"
            groups.setdefault(current_group, [])
        tokens = line.split()
        if not tokens:
            continue
        hostname = tokens[0]
        groups[current_group].append(hostname)
    return groups


def parse_ansible_yaml(content):
    """YAML-инвентарь (требует PyYAML). Возвращает dict или None."""
    try:
        import yaml
    except ImportError:
        return None
    try:
        data = yaml.safe_load(content)
    except Exception:
        return None

    groups = {}

    def walk(node, group_name):
        if not isinstance(node, dict):
            return
        hosts = node.get('hosts')
        if isinstance(hosts, dict):
            for hname, hdata in hosts.items():
                h = hname
                if isinstance(hdata, dict) and 'ansible_host' in hdata:
                    h = hdata['ansible_host']
                groups.setdefault(group_name, []).append(h)
        elif isinstance(hosts, list):
            for h in hosts:
                groups.setdefault(group_name, []).append(h)
        children = node.get('children')
        if isinstance(children, dict):
            for cname, cnode in children.items():
                walk(cnode, cname)

    walk(data, "all")
    return groups

# ---------- Парсеры импорта ----------

def _looks_like_ip(s):
    """Грубая проверка: строка похожа на IPv4 или IPv6."""
    parts = s.split('.')
    if len(parts) == 4:
        try:
            if all(0 <= int(p) <= 255 for p in parts):
                return True
        except ValueError:
            pass
    if ':' in s and all(c in '0123456789abcdefABCDEF:' for c in s):
        return True
    return False


def parse_hosts_file(content):
    """Формат /etc/hosts: 'IP hostname [aliases...]'.
    Берём ВТОРОЕ поле — имя хоста. Все хосты идут в группу Default."""
    hosts = []
    for raw_line in content.splitlines():
        line = raw_line.split('#', 1)[0].strip()
        if not line:
            continue
        tokens = line.split()
        if len(tokens) < 2:
            continue
        hostname = tokens[1]
        hosts.append(hostname)
    return {"Default": hosts}


def parse_plain_list(content):
    """Построчный список: одна строка — одно имя хоста."""
    hosts = []
    for raw_line in content.splitlines():
        line = raw_line.split('#', 1)[0].strip()
        if line:
            hosts.append(line)
    return {"Default": hosts}


def parse_backup(content):
    """QPing backup JSON. Возвращает {host: {category, check_type, port, disabled}} или None."""
    try:
        data = json.loads(content)
    except Exception:
        return None
    if not isinstance(data, dict) or data.get('format') != 'qping-backup':
        return None
    result = {}
    for h in data.get('hosts', []):
        if not isinstance(h, dict):
            continue
        name = h.get('host')
        if not name:
            continue
        result[name] = {
            'category': h.get('category', 'Default'),
            'check_type': h.get('check_type', 'icmp'),
            'port': h.get('port'),
            'disabled': bool(h.get('disabled', False)),
        }
    return result


def build_backup(hosts_data):
    """hosts_data: list of dicts с ключами host, category, check_type, port, disabled."""
    return {
        'format': 'qping-backup',
        'version': 1,
        'created': datetime.now().isoformat(),
        'hosts': hosts_data,
    }


def detect_import_format(filename, content):
    """Определяет формат файла: 'backup', 'ansible_ini', 'ansible_yaml', 'hosts', 'plain'."""
    base = os.path.basename(filename).lower()
    ext = os.path.splitext(filename)[1].lower()

    # QPing backup
    if base.endswith('.qping.json') or ext == '.qping':
        return 'backup'

    # По расширению
    if ext == '.ini':
        return 'ansible_ini'
    if ext in ('.yml', '.yaml'):
        return 'ansible_yaml'

    # /etc/hosts — файл без расширения с именем "hosts" или "hosts.*"
    if base == 'hosts' or base.startswith('hosts.'):
        return 'hosts'

    # Автодетект содержимого: JSON-бэкап
    stripped = content.lstrip()
    if stripped.startswith('{'):
        try:
            data = json.loads(content)
            if isinstance(data, dict) and data.get('format') == 'qping-backup':
                return 'backup'
        except Exception:
            pass

    # Секции [xxx] → ansible ini
    for line in content.splitlines()[:50]:
        s = line.strip()
        if s.startswith('[') and s.endswith(']'):
            return 'ansible_ini'

    # YAML-признаки
    if re.search(r'^\s*(all|children)\s*:', content, re.MULTILINE):
        return 'ansible_yaml'

    # /etc/hosts-подобное: строки "IP hostname [aliases]"
    ip_count = 0
    line_count = 0
    for line in content.splitlines()[:20]:
        s = line.split('#', 1)[0].strip()
        if not s:
            continue
        line_count += 1
        tokens = s.split()
        if len(tokens) >= 2 and _looks_like_ip(tokens[0]):
            ip_count += 1
    if line_count > 0 and ip_count == line_count:
        return 'hosts'

    return 'plain'
