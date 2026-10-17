"""User-visible texts of the installer (raf_installer.py): German, Russian, English.

T(key, **kw) formats the text of the current language (set_lang); every key exists in all three
languages with the same placeholders (checked by tools/test_installer.py)."""

import ctypes
import os

LANGS = {"de": "Deutsch", "ru": "Русский", "en": "English"}
_lang = "en"


def detect_lang() -> str:
    """Windows UI language: Russian -> ru, German -> de, anything else -> en."""
    try:
        primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF if os.name == "nt" else 0
    except Exception:  # noqa: BLE001
        primary = 0
    return {0x19: "ru", 0x07: "de"}.get(primary, "en")


def set_lang(lang: str) -> None:
    global _lang
    _lang = lang if lang in LANGS else "en"


def get_lang() -> str:
    return _lang


def T(key: str, **kw) -> str:
    return TEXT[key][_lang].format(**kw)


TEXT = {
    "title": {"de": "{app} {ver} – Installation", "ru": "{app} {ver} – установка", "en": "{app} {ver} – Setup"},
    "intro": {
        "de": "Der Installer kopiert dein Rise and Fall in einen neuen Ordner und baut dort das Remaster aus "
              "deinen eigenen Spieldateien. Das Originalspiel wird nicht verändert. Unterstützt wird "
              "Rise and Fall {gv} (russische Version).",
        "ru": "Установщик копирует вашу игру Rise and Fall в новую папку и собирает там ремастер из ваших "
              "собственных файлов игры. Оригинальная игра не изменяется. Поддерживается Rise and Fall {gv} "
              "(русская версия).",
        "en": "The installer copies your Rise and Fall into a new folder and builds the remaster there from "
              "your own game files. The original game is not changed. Supported: Rise and Fall {gv} "
              "(Russian version)."},
    "lang": {"de": "Sprache:", "ru": "Язык:", "en": "Language:"},
    "lbl_src": {"de": "Originalspiel:", "ru": "Оригинальная игра:", "en": "Original game:"},
    "lbl_dst": {"de": "Zielordner:", "ru": "Папка установки:", "en": "Target folder:"},
    "browse": {"de": "Durchsuchen …", "ru": "Обзор …", "en": "Browse …"},
    "browse_src": {"de": "Ordner des Originalspiels wählen", "ru": "Выберите папку оригинальной игры",
                   "en": "Choose the original game folder"},
    "browse_dst": {"de": "Zielordner wählen", "ru": "Выберите папку установки", "en": "Choose the target folder"},
    "src_none": {"de": "Kein Originalspiel gefunden. Bitte den Ordner mit RiseAndFall.exe wählen.",
                 "ru": "Оригинальная игра не найдена. Выберите папку с RiseAndFall.exe.",
                 "en": "Original game not found. Please choose the folder with RiseAndFall.exe."},
    "checking": {"de": "Prüfe …", "ru": "Проверка …", "en": "Checking …"},
    "ok": {"de": "OK: {msg}", "ru": "OK: {msg}", "en": "OK: {msg}"},
    "error": {"de": "Fehler: {msg}", "ru": "Ошибка: {msg}", "en": "Error: {msg}"},
    "chk_exe_missing": {"de": "{exe} nicht gefunden.", "ru": "{exe} не найден.", "en": "{exe} not found."},
    "chk_is_remaster": {
        "de": "Das ist schon eine Remaster-Installation. Bitte den Ordner des Originalspiels wählen.",
        "ru": "Это уже установка ремастера. Выберите папку оригинальной игры.",
        "en": "This is already a remaster install. Please choose the original game folder."},
    "chk_bad_version": {
        "de": "{name} passt nicht zur unterstützten Version. Unterstützt wird nur Rise and Fall {gv} "
              "(russisch) ohne weitere Patches oder Mods. Andere Version? Bitte melde sie auf "
              "github.com/VlexWest/raf-remaster/issues.",
        "ru": "{name} не соответствует поддерживаемой версии. Поддерживается только Rise and Fall {gv} "
              "(русская версия) без других патчей и модов. Другая версия? Напишите о ней на "
              "github.com/VlexWest/raf-remaster/issues.",
        "en": "{name} does not match the supported version. Only Rise and Fall {gv} (Russian) without other "
              "patches or mods is supported. Another version? Please report it at "
              "github.com/VlexWest/raf-remaster/issues."},
    "chk_ok": {"de": "Rise and Fall {gv} erkannt.", "ru": "Найдена Rise and Fall {gv}.",
               "en": "Rise and Fall {gv} found."},
    "missing": {"de": "fehlt: {rel}", "ru": "отсутствует: {rel}", "en": "missing: {rel}"},
    "changed": {"de": "verändert: {rel}", "ru": "изменён: {rel}", "en": "changed: {rel}"},
    "extra": {"de": "zusätzliche Datei: {rel}", "ru": "лишний файл: {rel}", "en": "extra file: {rel}"},
    "space": {"de": "Benötigt etwa {need:.1f} GB, frei {free:.1f} GB ({mark}).",
              "ru": "Нужно около {need:.1f} ГБ, свободно {free:.1f} ГБ ({mark}).",
              "en": "Needs about {need:.1f} GB, {free:.1f} GB free ({mark})."},
    "space_ok": {"de": "ausreichend", "ru": "достаточно", "en": "enough"},
    "space_low": {"de": "ZU WENIG", "ru": "НЕДОСТАТОЧНО", "en": "NOT ENOUGH"},
    "drive_missing": {"de": "Laufwerk nicht gefunden.", "ru": "Диск не найден.", "en": "Drive not found."},
    "opt_hd": {"de": "HD-Texturen erzeugen (auf deiner Grafikkarte, je nach Karte 3 bis 20 Minuten)",
               "ru": "Создать HD-текстуры (на вашей видеокарте, от 3 до 20 минут)",
               "en": "Create HD textures (on your graphics card, 3 to 20 minutes depending on the card)"},
    "opt_desktop": {"de": "Verknüpfung auf dem Desktop", "ru": "Ярлык на рабочем столе", "en": "Desktop shortcut"},
    "opt_menu": {"de": "Einträge im Startmenü (Spielen, Hosten, Beitreten, Deinstallieren)",
                 "ru": "Пункты в меню «Пуск» (игра, создать игру, присоединиться, удаление)",
                 "en": "Start menu entries (play, host, join, uninstall)"},
    "btn_install": {"de": "Installieren", "ru": "Установить", "en": "Install"},
    "btn_close": {"de": "Schließen", "ru": "Закрыть", "en": "Close"},
    "btn_open": {"de": "Ordner öffnen", "ru": "Открыть папку", "en": "Open folder"},
    "btn_play": {"de": "Spiel starten", "ru": "Запустить игру", "en": "Start game"},
    "ready": {"de": "Bereit.", "ru": "Готово к установке.", "en": "Ready."},
    "aborted": {"de": "Abgebrochen.", "ru": "Прервано.", "en": "Cancelled."},
    "done_status": {"de": "Installation abgeschlossen.", "ru": "Установка завершена.",
                    "en": "Installation complete."},
    "gpu_probe": {"de": "Grafikkarte wird geprüft …", "ru": "Проверка видеокарты …",
                  "en": "Checking the graphics card …"},
    "gpu_dxvk": {"de": "Grafikkarte: {name} (Vulkan {api}). DXVK wird verwendet.",
                 "ru": "Видеокарта: {name} (Vulkan {api}). Будет использован DXVK.",
                 "en": "Graphics card: {name} (Vulkan {api}). DXVK will be used."},
    "gpu_native": {
        "de": "Grafikkarte: {name}. DXVK braucht Vulkan 1.3 mit aktuellem Treiber ({reason}). Das Remaster "
              "läuft deshalb mit dem normalen Direct3D 9 von Windows. Tipp: Grafiktreiber aktualisieren und "
              "den Installer neu starten.",
        "ru": "Видеокарта: {name}. Для DXVK нужен Vulkan 1.3 со свежим драйвером ({reason}). Поэтому ремастер "
              "будет работать через обычный Direct3D 9 Windows. Совет: обновите драйвер видеокарты и "
              "запустите установщик снова.",
        "en": "Graphics card: {name}. DXVK needs Vulkan 1.3 with a current driver ({reason}). The remaster "
              "will therefore use the normal Windows Direct3D 9. Tip: update the graphics driver and run the "
              "installer again."},
    "gpu_unknown": {"de": "nicht erkannt", "ru": "не определена", "en": "not detected"},
    "hd_off": {"de": "HD-Texturen brauchen eine Grafikkarte mit Vulkan; keine gefunden.",
               "ru": "Для HD-текстур нужна видеокарта с Vulkan; она не найдена.",
               "en": "HD textures need a graphics card with Vulkan; none found."},
    "step_check": {"de": "Prüfe das Originalspiel", "ru": "Проверка оригинальной игры",
                   "en": "Checking the original game"},
    "step_copy": {"de": "Kopiere Spieldateien ({done:.1f} von {total:.1f} GB)",
                  "ru": "Копирование файлов игры ({done:.1f} из {total:.1f} ГБ)",
                  "en": "Copying game files ({done:.1f} of {total:.1f} GB)"},
    "step_build": {"de": "Erzeuge {label} aus deinen Spieldateien ({i}/{n})",
                   "ru": "Создание: {label} из ваших файлов игры ({i}/{n})",
                   "en": "Building {label} from your game files ({i}/{n})"},
    "step_patch": {"de": "Patche die Kopie", "ru": "Применение патчей к копии", "en": "Patching the copy"},
    "step_done": {"de": "Fertig", "ru": "Готово", "en": "Done"},
    "err_nested": {"de": "Der Zielordner darf nicht im Originalordner liegen (und umgekehrt).",
                   "ru": "Папка установки не может находиться внутри папки оригинальной игры (и наоборот).",
                   "en": "The target folder must not be inside the original folder (or the other way round)."},
    "err_not_empty": {"de": "Der Zielordner ist nicht leer: {d}\nBitte einen neuen Ordner wählen.",
                      "ru": "Папка установки не пуста: {d}\nВыберите новую папку.",
                      "en": "The target folder is not empty: {d}\nPlease choose a new folder."},
    "err_space": {"de": "Zu wenig Speicherplatz: {need:.1f} GB nötig, {free:.1f} GB frei.",
                  "ru": "Недостаточно места: нужно {need:.1f} ГБ, свободно {free:.1f} ГБ.",
                  "en": "Not enough disk space: {need:.1f} GB needed, {free:.1f} GB free."},
    "err_stock": {"de": "Das Originalspiel weicht von der unterstützten Version ab:",
                  "ru": "Оригинальная игра отличается от поддерживаемой версии:",
                  "en": "The original game differs from the supported version:"},
    "err_choose_src": {"de": "Bitte zuerst den Ordner des Originalspiels wählen.",
                       "ru": "Сначала выберите папку оригинальной игры.",
                       "en": "Please choose the original game folder first."},
    "err_choose_dst": {"de": "Bitte einen Zielordner wählen.", "ru": "Выберите папку установки.",
                       "en": "Please choose a target folder."},
    "err_failed": {"de": "Die Installation ist fehlgeschlagen:\n\n{msg}\n\nProtokoll: {log}",
                   "ru": "Установка не удалась:\n\n{msg}\n\nЖурнал: {log}",
                   "en": "The installation failed:\n\n{msg}\n\nLog: {log}"},
    "err_path_chars": {"de": "Pfad mit % oder \" wird nicht unterstützt: {p}",
                       "ru": "Путь с % или \" не поддерживается: {p}",
                       "en": "Paths with % or \" are not supported: {p}"},
    "log_note": {"de": "Hinweis: {w}", "ru": "Примечание: {w}", "en": "Note: {w}"},
    "log_copied": {"de": "kopiert: {gb:.2f} GB nach {dst}", "ru": "скопировано: {gb:.2f} ГБ в {dst}",
                   "en": "copied: {gb:.2f} GB to {dst}"},
    "log_built": {"de": "{n}: gebaut in {s} s", "ru": "{n}: готово за {s} с", "en": "{n}: built in {s} s"},
    "log_hd_reused": {"de": "{n}: aus der bisherigen Installation übernommen ({s} s)",
                      "ru": "{n}: взято из прежней установки ({s} с)",
                      "en": "{n}: taken over from the previous install ({s} s)"},
    "log_hd_failed": {"de": "{n}: fehlgeschlagen ({msg}); HD-Texturen werden übersprungen.",
                      "ru": "{n}: ошибка ({msg}); HD-текстуры пропущены.",
                      "en": "{n}: failed ({msg}); HD textures are skipped."},
    "log_native": {
        "de": "DXVK nicht installiert (keine passende Vulkan-1.3-Grafikkarte): das Spiel nutzt Direct3D 9 von Windows.",
        "ru": "DXVK не установлен (нет подходящей видеокарты с Vulkan 1.3): игра использует Direct3D 9 Windows.",
        "en": "DXVK not installed (no suitable Vulkan 1.3 graphics card): the game uses the Windows Direct3D 9."},
    "log_removed": {"de": "Abgebrochen, {d} wieder entfernt.", "ru": "Прервано, {d} удалена.",
                    "en": "Cancelled, {d} removed again."},
    "log_reg_fail": {"de": "Registry konnte nicht zurückgesetzt werden: {msg}",
                     "ru": "Не удалось восстановить реестр: {msg}", "en": "Could not restore the registry: {msg}"},
    "fp_label": {"de": "Gameplay-Fingerabdruck:", "ru": "Отпечаток игровых данных:", "en": "Gameplay fingerprint:"},
    "fp_text": {
        "de": "Vergleiche diesen Fingerabdruck mit deinem Mitspieler. Nur wenn beide gleich sind, läuft ein "
              "Netzwerkspiel ohne Abbruch. Er steht auch in REMASTER.txt im Spielordner.",
        "ru": "Сравните этот отпечаток с отпечатком вашего напарника. Сетевая игра идёт без сбоев, только "
              "если они совпадают. Он также записан в REMASTER.txt в папке игры.",
        "en": "Compare this fingerprint with your friend's. A network game only runs without breaking off "
              "when both are the same. It is also in REMASTER.txt in the game folder."},
    "fp_mismatch": {
        "de": "ACHTUNG: erwartet war {exp}. Deine Spieldaten weichen ab; im Netzwerk mit anderen "
              "Remaster-Spielern gibt es wahrscheinlich Abbrüche.",
        "ru": "ВНИМАНИЕ: ожидался {exp}. Ваши данные игры отличаются; в сетевой игре с другими игроками "
              "ремастера, скорее всего, будут сбои.",
        "en": "WARNING: {exp} was expected. Your game data differs; network games with other remaster players "
              "will probably break off."},
    "fp_hd_failed": {"de": "HD-Texturen konnten nicht erzeugt werden. Das Spiel läuft ohne sie.",
                     "ru": "Не удалось создать HD-текстуры. Игра работает без них.",
                     "en": "HD textures could not be created. The game runs without them."},
    "fp_native": {"de": "Installiert ohne DXVK (Direct3D 9 von Windows), weil Vulkan 1.3 fehlt.",
                  "ru": "Установлено без DXVK (Direct3D 9 Windows), так как нет Vulkan 1.3.",
                  "en": "Installed without DXVK (Windows Direct3D 9) because Vulkan 1.3 is missing."},
    "lnk_host": {"de": "Netzwerkspiel hosten", "ru": "Создать сетевую игру", "en": "Host network game"},
    "lnk_join": {"de": "Netzwerkspiel beitreten", "ru": "Присоединиться к сетевой игре", "en": "Join network game"},
    "lnk_fp": {"de": "Fingerabdruck und Version", "ru": "Отпечаток и версия", "en": "Fingerprint and version"},
    "lnk_uninst": {"de": "{app} deinstallieren", "ru": "Удалить {app}", "en": "Uninstall {app}"},
    # Uninstall.bat (UTF-8, chcp 65001)
    "un_title": {"de": "{app} deinstallieren", "ru": "Удаление {app}", "en": "Uninstall {app}"},
    "un_info": {"de": "Der Remaster-Ordner wird gelöscht, das Originalspiel bleibt unverändert.",
                "ru": "Папка ремастера будет удалена, оригинальная игра не изменится.",
                "en": "The remaster folder will be deleted, the original game stays unchanged."},
    "un_folder": {"de": "Ordner:", "ru": "Папка:", "en": "Folder:"},
    "un_ask": {"de": "Wirklich deinstallieren", "ru": "Удалить? Y = да, N = нет", "en": "Really uninstall"},
    "un_keys": {"de": "JN", "ru": "YN", "en": "YN"},
    "un_done": {"de": "{app} wurde entfernt.", "ru": "{app} удалён.", "en": "{app} has been removed."},
    "un_running": {"de": "Bitte zuerst das Spiel schließen und dann erneut starten.",
                   "ru": "Сначала закройте игру, затем запустите удаление снова.",
                   "en": "Please close the game first, then run this again."},
    # launcher (raf_launcher.py)
    "upd_title": {"de": "{app}: Update", "ru": "{app}: обновление", "en": "{app}: update"},
    "upd_available": {"de": "Version {new} ist verfügbar (installiert: {cur}).",
                      "ru": "Доступна версия {new} (установлена: {cur}).",
                      "en": "Version {new} is available (installed: {cur})."},
    "upd_changes": {"de": "Neu in dieser Version:", "ru": "Что нового:", "en": "What's new:"},
    "upd_mp": {"de": "Installiert: {cur}, Gameplay-Fingerabdruck {fp}. Im Netzwerkspiel brauchen alle Spieler "
                     "dieselbe Version und denselben Fingerabdruck.",
               "ru": "Установлено: {cur}, отпечаток игровых данных {fp}. В сетевой игре у всех игроков должны "
                     "быть одинаковые версия и отпечаток.",
               "en": "Installed: {cur}, gameplay fingerprint {fp}. In a network game all players need the same "
                     "version and fingerprint."},
    "btn_update": {"de": "Jetzt aktualisieren", "ru": "Обновить сейчас", "en": "Update now"},
    "btn_later": {"de": "Später", "ru": "Позже", "en": "Later"},
    "btn_skip": {"de": "Diese Version überspringen", "ru": "Пропустить эту версию", "en": "Skip this version"},
    "btn_cancel": {"de": "Abbrechen", "ru": "Отмена", "en": "Cancel"},
    "upd_download": {"de": "Lade das Update herunter: {done:.0f} von {total:.0f} MB",
                     "ru": "Загрузка обновления: {done:.0f} из {total:.0f} МБ",
                     "en": "Downloading the update: {done:.0f} of {total:.0f} MB"},
    "upd_err_download": {"de": "Das Update konnte nicht geladen werden:\n{msg}\n\nDas Spiel startet mit der "
                               "installierten Version.",
                         "ru": "Не удалось загрузить обновление:\n{msg}\n\nИгра запустится с установленной "
                               "версией.",
                         "en": "The update could not be downloaded:\n{msg}\n\nThe game starts with the installed "
                               "version."},
    "upd_none": {"de": "Kein Update: {cur} ist die neueste Version.", "ru": "Обновлений нет: {cur} – последняя версия.",
                 "en": "No update: {cur} is the newest version."},
    "upd_check_failed": {"de": "Die Update-Prüfung ist fehlgeschlagen: {msg}",
                         "ru": "Не удалось проверить обновления: {msg}", "en": "The update check failed: {msg}"},
    # installer update mode (--update)
    "upd_setup_title": {"de": "{app}: Update auf {ver}", "ru": "{app}: обновление до {ver}",
                        "en": "{app}: update to {ver}"},
    "upd_running": {"de": "Das Spiel läuft noch aus {d}. Bitte schließen und dann „Wiederholen“ klicken.",
                    "ru": "Игра ещё запущена из {d}. Закройте её и нажмите «Повторить».",
                    "en": "The game is still running from {d}. Please close it, then click Retry."},
    "upd_stock_missing": {
        "de": "Das Originalspiel wurde unter {p} nicht gefunden oder passt nicht ({msg}). Bitte den Ordner des "
              "originalen Rise and Fall wählen.",
        "ru": "Оригинальная игра не найдена в {p} или не подходит ({msg}). Выберите папку оригинальной "
              "Rise and Fall.",
        "en": "The original game was not found at {p} or does not match ({msg}). Please choose the folder of "
              "the original Rise and Fall."},
    "upd_in_use": {"de": "Der Remaster-Ordner wird gerade benutzt ({msg}). Bitte Explorer-Fenster und Programme "
                         "in diesem Ordner schließen und „Wiederholen“ klicken.",
                   "ru": "Папка ремастера сейчас используется ({msg}). Закройте окна проводника и программы в этой "
                         "папке и нажмите «Повторить».",
                   "en": "The remaster folder is in use ({msg}). Please close Explorer windows and programs in that "
                         "folder, then click Retry."},
    "upd_no_info": {"de": "{d} ist keine Remaster-Installation.", "ru": "{d} – не установка ремастера.",
                    "en": "{d} is not a remaster install."},
    "step_swap": {"de": "Ersetze die alte Version", "ru": "Замена старой версии", "en": "Replacing the old version"},
    "step_carry": {"de": "Übernehme Spielstände und eigene Dateien", "ru": "Перенос сохранений и ваших файлов",
                   "en": "Taking over saves and your own files"},
    "upd_done": {"de": "Update auf {ver} fertig. Gameplay-Fingerabdruck: {fp}. Das Spiel startet.",
                 "ru": "Обновление до {ver} завершено. Отпечаток игровых данных: {fp}. Игра запускается.",
                 "en": "Update to {ver} complete. Gameplay fingerprint: {fp}. The game is starting."},
    "upd_fp_changed": {"de": "Der Fingerabdruck hat sich geändert ({old} -> {new}): alle Mitspieler brauchen "
                             "diese Version.",
                       "ru": "Отпечаток изменился ({old} -> {new}): всем игрокам нужна эта версия.",
                       "en": "The fingerprint changed ({old} -> {new}): all players need this version."},
    "upd_failed": {"de": "Das Update ist fehlgeschlagen, die bisherige Version ist unverändert:\n\n{msg}\n\n"
                         "Protokoll: {log}",
                   "ru": "Обновление не удалось, прежняя версия не изменена:\n\n{msg}\n\nЖурнал: {log}",
                   "en": "The update failed, the previous version is unchanged:\n\n{msg}\n\nLog: {log}"},
    # window layout (raf_ui)
    "sub_setup": {"de": "Installation · Version {ver}", "ru": "Установка · версия {ver}", "en": "Setup · version {ver}"},
    "sub_update": {"de": "Update", "ru": "Обновление", "en": "Update"},
    "sec_src": {"de": "ORIGINALSPIEL", "ru": "ОРИГИНАЛЬНАЯ ИГРА", "en": "ORIGINAL GAME"},
    "sec_dst": {"de": "ZIELORDNER", "ru": "ПАПКА УСТАНОВКИ", "en": "INSTALL TO"},
    "sec_opts": {"de": "OPTIONEN", "ru": "ПАРАМЕТРЫ", "en": "OPTIONS"},
    "details_show": {"de": "Details anzeigen", "ru": "Показать подробности", "en": "Show details"},
    "details_hide": {"de": "Details ausblenden", "ru": "Скрыть подробности", "en": "Hide details"},
    "done_title": {"de": "Das Remaster ist installiert.", "ru": "Ремастер установлен.",
                   "en": "The remaster is installed."},
    "done_where": {"de": "Ordner: {dst}", "ru": "Папка: {dst}", "en": "Folder: {dst}"},
    "upd_head": {"de": "Neue Version verfügbar", "ru": "Доступна новая версия", "en": "New version available"},
    "upd_dl_head": {"de": "Update wird geladen", "ru": "Загрузка обновления", "en": "Downloading the update"},
    # overlay names in progress messages
    "f_mips": {"de": "Mipmaps", "ru": "MIP-уровни текстур", "en": "mipmaps"},
    "f_hd-terrain": {"de": "HD-Geländetexturen (Grafikkarte)", "ru": "HD-текстуры местности (видеокарта)",
                     "en": "HD terrain textures (graphics card)"},
    "f_hd-units": {"de": "HD-Einheitentexturen (Grafikkarte)", "ru": "HD-текстуры юнитов (видеокарта)",
                   "en": "HD unit textures (graphics card)"},
    "f_shaders": {"de": "Shader", "ru": "шейдеры", "en": "shaders"},
    "f_ai-hard": {"de": "KI Schwer", "ru": "сложный ИИ", "en": "hard AI"},
    "f_ai-personalities": {"de": "KI-Persönlichkeiten", "ru": "характеры ИИ", "en": "AI personalities"},
    "f_unit-ai": {"de": "Einheiten-KI", "ru": "ИИ юнитов", "en": "unit AI"},
    "f_unit-limit": {"de": "Einheitenlimit", "ru": "лимит юнитов", "en": "unit limit"},
    "f_crossciv": {"de": "Ausbildung in fremden Kasernen", "ru": "найм в чужих казармах",
                   "en": "training in foreign barracks"},
    "f_survival": {"de": "Survival-Karten", "ru": "карты Survival", "en": "survival maps"},
    "f_coop-modes": {"de": "Koop-Karten", "ru": "кооперативные карты", "en": "co-op maps"},
    "f_zoom-setting": {"de": "Zoom-Regler", "ru": "ползунок отдаления камеры", "en": "zoom slider"},
    "f_target-priority": {"de": "Zielwahl: Belagerung zuerst", "ru": "выбор цели: осадные орудия первыми",
                          "en": "target choice: siege first"},
}
