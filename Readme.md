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
![alt text](https://github.com/zersh01/QPing/raw/main/qping.png "QPing")

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

#### Требования
- Python 3.8+
- PyQt6
- Операционная система: Windows, macOS или Linux

#### Установка зависимостей
1. Проверить, установлен ли Python:
   $ python --version
2. Установить PyQt6:
   $ pip install PyQt6

#### Запуск приложения
1. Клонировать репозиторий или скачать исходный код:
   $ git clone <repository_url>
   $ cd ping-monitor
2. Запустить приложение:
   $ python qping.py
или бинарный файл:
   $ dist/qping


### Сборка в бинарный файл с PyInstaller

1. Установить PyInstaller:
   $ pip install pyinstaller
2. Выполнить сборку:
   $ pyinstaller --noconsole --onefile --name qping \
    --add-data "translations/ru/LC_MESSAGES/qping.mo:translations/ru/LC_MESSAGES" \
    --add-data "translations/en/LC_MESSAGES/qping.mo:translations/en/LC_MESSAGES" qping.py
3. Найти исполняемый файл в папке `dist/qping`.

### 🌍 Локализация на другие языки

1. Создать шаблон .pot:
   $ xgettext -L Python --output=translations/qping.pot *.py
2. Создать .po файл для нового языка (например, французский):
   $ msginit -i translations/qping.pot -l fr -o translations/fr/LC_MESSAGES/qping.po
3. Заполнить переводы в .po файле с помощью редактора, например, Poedit, или вручную.
4. Скомпилировать .po в .mo:
   $ msgfmt translations/fr/LC_MESSAGES/qping.po -o translations/fr/LC_MESSAGES/qping.mo
5. Добавить язык в приложение:
   - Отредактировать метод `setup_ui` в `main.py`, добавив новое действие в меню `language_menu`:
   
     fr_action = QAction("Français", self)
     fr_action.triggered.connect(lambda: self.change_language("fr"))
     language_menu.addAction(fr_action)
   
6. Перезапустить приложение и выбрать новый язык в меню "Язык".

### Использование
1. Запустить приложение.
2. Добавить хост через поле ввода или импортировать из файла.
3. Настроить интервал проверки с помощью ползунка.
4. Использовать контекстное меню для редактирования, удаления или изменения типа проверки хоста.
5. Дважды щелкнуть по графику хоста, чтобы приоритизировать его проверку.
6. Использовать временную шкалу для масштабирования истории пингов.

### Лицензия
MIT License

---

## English

### Project Description

**QPing** is a desktop application for monitoring the availability of network hosts using ICMP pings or TCP port checks. 
It provides a visual representation of host status through graphs, supports host categorization, 
interface localization, and system tray notifications. The application is built with Python using the PyQt6 library.

Screenshot:
![alt text](https://github.com/zersh01/QPing/raw/main/qping.png "QPing")

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

#### Requirements
- Python 3.8+
- PyQt6
- Operating System: Windows, macOS, or Linux

#### Installing Dependencies
1. Check if Python is installed:
   $ python --version
2. Install PyQt6:
   $ pip install PyQt6

#### Running the Application
1. Clone the repository or download the source code:
   $ git clone <repository_url>
   $ cd ping-monitor
2. Run the application:
   $ python qping.py
or run binary file:
   $ dist/qping

### Building a Binary with PyInstaller

1. Install PyInstaller:
   $ pip install pyinstaller
2. Build the binary:
   $ pyinstaller --noconsole --onefile --name qping \
    --add-data "translations/ru/LC_MESSAGES/qping.mo:translations/ru/LC_MESSAGES" \
    --add-data "translations/en/LC_MESSAGES/qping.mo:translations/en/LC_MESSAGES" qping.py
3. Find the executable in the `dist/qping` folder.


### 🌍 Localization to Other Languages

1. Create a .pot template:
   $ xgettext -L Python --output=translations/qping.pot *.py
2. Create a .po file for the new language (e.g., French):
   $ msginit -i translations/qping.pot -l fr -o translations/fr/LC_MESSAGES/qping.po
3. Fill in translations in the .po file using a tool like Poedit or manually.
4. Compile .po to .mo:
   $ msgfmt translations/fr/LC_MESSAGES/qping.po -o translations/fr/LC_MESSAGES/qping.mo
5. Add the language to the application:
   - Edit the `setup_ui` method in `main.py` to add a new action to the `language_menu`:
   
     fr_action = QAction("Français", self)
     fr_action.triggered.connect(lambda: self.change_language("fr"))
     language_menu.addAction(fr_action)
   
6. Restart the application and select the new language from the "Language" menu.

### Usage
1. Launch the application.
2. Add a host via the input field or import from a file.
3. Adjust the check interval using the slider.
4. Use the context menu to edit, delete, or change the check type for a host.
5. Double-click a host’s graph to prioritize its check.
6. Use the timeline to zoom in/out on ping history.

### License
MIT License
