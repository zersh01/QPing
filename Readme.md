# QPing Readme

- [Русский](#русский)
- [English](#english)

---

## Русский

### Описание проекта

**QPing** — GUI приложение для мониторинга доступности сетевых хостов по ICMP или TCP-портов.
Оно предоставляет визуальное отображение статуса хостов в виде графиков,
поддерживает категоризацию хостов, локализацию интерфейса и уведомления через системный трей.
Написан на Python с использованием библиотеки PyQt6.

Screenshot:
![QPing screenshot](https://github.com/zersh01/QPing/raw/main/images/Screenshot.png "QPing")

#### Основные возможности:

- Мониторинг хостов через ICMP или TCP-проверки.
- Визуализация результатов пинга в виде графиков с масштабируемой временной шкалой.
- Поддержка категорий для группировки хостов.
- Фильтрация хостов по статусу (показ только недоступных).
- Уведомления в системном трее при недоступности хоста.
- Локализация интерфейса (русский и английский по умолчанию).
- Импорт хостов из текстового файла.
- Перетаскивание хостов для изменения порядка.
- Сохранение истории проверок и настроек.

### Установка

#### Способ 1: PPA (Ubuntu 22.04+)

Для пользователей Ubuntu 22.04, 24.04 и новее доступна установка через PPA с автоматическими обновлениями:

```bash
sudo add-apt-repository ppa:zersh01/qping
sudo apt update
sudo apt install qping
```

Запуск: `qping` из терминала или через меню приложений.

Удаление:

```bash
sudo apt remove qping
sudo add-apt-repository --remove ppa:zersh01/qping
```

Для работы batch-режима ICMP рекомендуется установить `fping`:

```bash
sudo apt install fping
```

#### Способ 2: Из исходников через git

1. Клонировать репозиторий:

   ```bash
   git clone https://github.com/zersh01/QPing.git
   cd QPing
   ```

2. Установить зависимости:

   ```bash
   sudo apt install python3 python3-pyqt6
   # опционально — для batch-режима
   sudo apt install fping
   ```

3. Установить ярлык в меню и на рабочий стол:

   ```bash
   chmod +x install.sh uninstall.sh run.sh
   ./install.sh
   ```

После этого QPing появится в меню приложений и на рабочем столе.

Удаление ярлыков:

```bash
./uninstall.sh
```

#### Способ 3: Ручной запуск без установки

1. Установить зависимости (см. выше).
2. Запустить приложение напрямую:

   ```bash
   ./qping.py
   ```

   или

   ```bash
   python3 qping.py
   ```

### Требования

- Python 3.10+
- PyQt6
- Операционная система: Linux (Ubuntu 22.04+ рекомендуется), Windows, macOS

### Использование

1. Запустить приложение.
2. Добавить хост через поле ввода или импортировать из файла.
3. Настроить интервал проверки с помощью ползунка.
4. Использовать контекстное меню для редактирования, удаления или изменения типа проверки хоста.
5. Дважды щелкнуть по графику хоста, чтобы приоритизировать его проверку.
6. Использовать временную шкалу для масштабирования истории пингов.

### 🌍 Локализация на другие языки

1. Создать шаблон `.pot`:

   ```bash
   xgettext -L Python --output=translations/qping.pot *.py
   ```

2. Создать `.po` файл для нового языка (например, французский):

   ```bash
   msginit -i translations/qping.pot -l fr -o translations/fr/LC_MESSAGES/qping.po
   ```

3. Заполнить переводы в `.po` файле с помощью редактора, например, Poedit, или вручную.

4. Скомпилировать `.po` в `.mo`:

   ```bash
   msgfmt translations/fr/LC_MESSAGES/qping.po -o translations/fr/LC_MESSAGES/qping.mo
   ```

5. Добавить язык в приложение — отредактировать метод `setup_ui` в `main.py`, добавив новое действие в меню `Language`:

   ```python
   fr_action = QAction("Français", self)
   fr_action.triggered.connect(lambda: self.change_language("fr"))
   self.menu_lang.addAction(fr_action)
   ```

   И не забудьте добавить аналогичную строку в `retranslate_ui`.

6. Перезапустить приложение и выбрать новый язык в меню "Language".

### Сборка в бинарный файл с PyInstaller

1. Установить PyInstaller:

   ```bash
   pip install pyinstaller
   ```

2. Выполнить сборку:

   ```bash
   pyinstaller --noconsole --onefile --name qping \
       --add-data "translations/ru/LC_MESSAGES/qping.mo:translations/ru/LC_MESSAGES" \
       --add-data "translations/en/LC_MESSAGES/qping.mo:translations/en/LC_MESSAGES" \
       qping.py
   ```

3. Найти исполняемый файл в папке `dist/qping`.

### Лицензия

MIT License

---

## English

### Project Description

**QPing** is a desktop application for monitoring the availability of network hosts using ICMP pings or TCP port checks.
It provides a visual representation of host status through graphs, supports host categorization,
interface localization, and system tray notifications. The application is built with Python using the PyQt6 library.

Screenshot:
![QPing screenshot](https://github.com/zersh01/QPing/raw/main/images/Screenshot.png "QPing")

#### Key Features:

- Monitor hosts via ICMP or TCP checks.
- Visualize ping results with graphs and a scalable timeline.
- Categorize hosts for better organization.
- Filter hosts by status (show only failed hosts).
- System tray notifications for host unavailability.
- Interface localization (Russian and English by default).
- Import hosts from a text file.
- Drag-and-drop reordering of hosts.
- Persistent history and settings storage.

### Installation

#### Option 1: PPA (Ubuntu 22.04+)

For Ubuntu 22.04, 24.04 and newer, install via PPA with automatic updates:

```bash
sudo add-apt-repository ppa:zersh01/qping
sudo apt update
sudo apt install qping
```

Launch: `qping` from terminal or via the applications menu.

Uninstall:

```bash
sudo apt remove qping
sudo add-apt-repository --remove ppa:zersh01/qping
```

For ICMP batch mode, install `fping`:

```bash
sudo apt install fping
```

#### Option 2: From source via git

1. Clone the repository:

   ```bash
   git clone https://github.com/zersh01/QPing.git
   cd QPing
   ```

2. Install dependencies:

   ```bash
   sudo apt install python3 python3-pyqt6
   # optional — for batch mode
   sudo apt install fping
   ```

3. Install menu/desktop shortcuts:

   ```bash
   chmod +x install.sh uninstall.sh run.sh
   ./install.sh
   ```

QPing will appear in the applications menu and on the desktop.

Remove shortcuts:

```bash
./uninstall.sh
```

#### Option 3: Manual run without installation

1. Install dependencies (see above).
2. Run the application directly:

   ```bash
   ./qping.py
   ```

   or

   ```bash
   python3 qping.py
   ```

### Requirements

- Python 3.10+
- PyQt6
- Operating System: Linux (Ubuntu 22.04+ recommended), Windows, macOS

### Usage

1. Launch the application.
2. Add a host via the input field or import from a file.
3. Adjust the check interval using the slider.
4. Use the context menu to edit, delete, or change the check type for a host.
5. Double-click a host's graph to prioritize its check.
6. Use the timeline to zoom in/out on ping history.

### 🌍 Localization to Other Languages

1. Create a `.pot` template:

   ```bash
   xgettext -L Python --output=translations/qping.pot *.py
   ```

2. Create a `.po` file for the new language (e.g., French):

   ```bash
   msginit -i translations/qping.pot -l fr -o translations/fr/LC_MESSAGES/qping.po
   ```

3. Fill in translations in the `.po` file using a tool like Poedit or manually.

4. Compile `.po` to `.mo`:

   ```bash
   msgfmt translations/fr/LC_MESSAGES/qping.po -o translations/fr/LC_MESSAGES/qping.mo
   ```

5. Add the language to the application — edit the `setup_ui` method in `main.py`, adding a new action to the `Language` menu:

   ```python
   fr_action = QAction("Français", self)
   fr_action.triggered.connect(lambda: self.change_language("fr"))
   self.menu_lang.addAction(fr_action)
   ```

   Also add a matching line in `retranslate_ui`.

6. Restart the application and select the new language from the "Language" menu.

### Building a Binary with PyInstaller

1. Install PyInstaller:

   ```bash
   pip install pyinstaller
   ```

2. Build the binary:

   ```bash
   pyinstaller --noconsole --onefile --name qping \
       --add-data "translations/ru/LC_MESSAGES/qping.mo:translations/ru/LC_MESSAGES" \
       --add-data "translations/en/LC_MESSAGES/qping.mo:translations/en/LC_MESSAGES" \
       qping.py
   ```

3. Find the executable in the `dist/qping` folder.

### License

MIT License
