import sys
import json
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QLineEdit, QMessageBox, QSpacerItem, QSizePolicy, QDialog, QFormLayout, QSpinBox, QStackedWidget, QTabWidget,
    QListWidget, QInputDialog, QListWidgetItem, QGridLayout, QScrollArea, QColorDialog, QComboBox, QCheckBox, QFileDialog, QTextEdit, QSlider, QDialogButtonBox
)
from updater import UpdateManager, get_current_version
from update_settings_dialog import UpdateSettingsDialog
from PyQt5.QtCore import QTimer, Qt, pyqtSignal, QThread, pyqtSignal as QSignal, QSize
from PyQt5.QtGui import QIcon, QKeySequence, QClipboard, QPixmap, QPainter, QPen, QColor, QPalette, QFontDatabase
import keyboard
import os
import threading
from google_auth_oauthlib.flow import InstalledAppFlow
import requests
import asyncio
from aiohttp import web
import websockets
import datetime
import urllib.request
from io import BytesIO
import shutil
import base64
import secrets
import tempfile
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import subprocess

# Попробуем использовать Win32 API для глобальных хоткеев в .exe
try:
    import ctypes
    from ctypes import wintypes
    USE_WIN32 = True
    print("HOTKEY: Используем Win32 API")
except ImportError:
    USE_WIN32 = False
    print("HOTKEY: Win32 недоступен")

# Fallback к pynput и keyboard
try:
    from pynput import keyboard as pynput_keyboard
    USE_PYNPUT = True
    print("HOTKEY: pynput доступен как fallback")
except ImportError:
    USE_PYNPUT = False
    print("HOTKEY: pynput не найден")

# Win32 константы для хоткеев
if USE_WIN32:
    # Модификаторы для RegisterHotKey (не используется)
    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004  
    MOD_ALT = 0x0001
    MOD_WIN = 0x0008
    
    # Константы для SetWindowsHookEx
    WH_KEYBOARD_LL = 13
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    WM_SYSKEYDOWN = 0x0104
    WM_SYSKEYUP = 0x0105
    
    # Виртуальные коды клавиш
    VK_CONTROL = 0x11
    VK_SHIFT = 0x10
    VK_MENU = 0x12  # Alt
    VK_LWIN = 0x5B
    VK_RWIN = 0x5C
    
    # Виртуальные коды клавиш (русские буквы)
    VK_CODES = {
        'ctrl': MOD_CONTROL,
        'shift': MOD_SHIFT,
        'alt': MOD_ALT,
        'win': MOD_WIN,
        # Русские буквы
        'й': 0x51,  # Q
        'ц': 0x57,  # W  
        'у': 0x45,  # E
        'к': 0x52,  # R
        'е': 0x54,  # T
        'н': 0x59,  # Y
        'г': 0x55,  # U
        'ш': 0x49,  # I
        'щ': 0x4F,  # O
        'з': 0x50,  # P
        'ф': 0x41,  # A
        'ы': 0x53,  # S
        'в': 0x44,  # D
        'а': 0x46,  # F
        'п': 0x47,  # G
        'р': 0x48,  # H
        'о': 0x4A,  # J
        'л': 0x4B,  # K
        'д': 0x4C,  # L
        'я': 0x5A,  # Z
        'ч': 0x58,  # X
        'с': 0x43,  # C
        'м': 0x56,  # V
        'и': 0x42,  # B
        'т': 0x4E,  # N
        'ь': 0x4D,  # M
        # Английские буквы
        'a': 0x41, 'b': 0x42, 'c': 0x43, 'd': 0x44, 'e': 0x45,
        'f': 0x46, 'g': 0x47, 'h': 0x48, 'i': 0x49, 'j': 0x4A,
        'k': 0x4B, 'l': 0x4C, 'm': 0x4D, 'n': 0x4E, 'o': 0x4F,
        'p': 0x50, 'q': 0x51, 'r': 0x52, 's': 0x53, 't': 0x54,
        'u': 0x55, 'v': 0x56, 'w': 0x57, 'x': 0x58, 'y': 0x59, 'z': 0x5A,
        # Цифры
        '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34,
        '5': 0x35, '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
    }

    class Win32HotkeyListener:
        def __init__(self):
            self.hotkeys = {}  # {hotkey_string: callback}
            self.running = False
            self.hook = None
            self.active_modifiers = set()  # Активные клавиши-модификаторы
            self.active_key = None  # Активная основная клавиша
            
            # Определяем HOOKPROC тип для callback (исправленная версия для PyInstaller)
            try:
                self.HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
            except:
                # Fallback для PyInstaller
                self.HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
            
        def register_hotkey(self, hotkey_str, callback):
            """Регистрирует хоткей для перехвата через keyboard hook"""
            try:
                # Парсим хоткей для валидации
                parts = [p.strip().lower() for p in hotkey_str.split('+')]
                
                # Проверяем что все части понятны
                for part in parts:
                    if part not in ['ctrl', 'control', 'shift', 'alt', 'win'] and part not in VK_CODES:
                        print(f"HOTKEY: ⚠️ Неизвестная клавиша: {part}")
                        return False
                
                # Сохраняем хоткей
                self.hotkeys[hotkey_str.lower()] = callback
                print(f"HOTKEY: ✅ Win32 хоткей зарегистрирован для hook: {hotkey_str}")
                return True
                    
            except Exception as e:
                print(f"HOTKEY: ❌ Исключение при регистрации хоткея: {e}")
                return False
        
        def start_listening(self):
            """Запускает прослушивание хоткеев через SetWindowsHookEx"""
            if self.running:
                return
                
            self.running = True
            print("HOTKEY: 🚀 Запускаем Win32 keyboard hook...")
            
            try:
                # Создаем callback функцию для hook
                def keyboard_hook_proc(nCode, wParam, lParam):
                    try:
                        if nCode >= 0:  # HC_ACTION
                            # Определяем что произошло с клавишей
                            key_down = wParam in [WM_KEYDOWN, WM_SYSKEYDOWN]
                            key_up = wParam in [WM_KEYUP, WM_SYSKEYUP]
                            
                            if key_down or key_up:
                                # Получаем виртуальный код клавиши
                                vk_code = ctypes.cast(lParam, ctypes.POINTER(ctypes.c_ulong)).contents.value & 0xFF
                                
                                # Отслеживаем модификаторы
                                if vk_code == VK_CONTROL:
                                    if key_down:
                                        self.active_modifiers.add('ctrl')
                                    elif key_up:
                                        self.active_modifiers.discard('ctrl')
                                elif vk_code == VK_SHIFT:
                                    if key_down:
                                        self.active_modifiers.add('shift')
                                    elif key_up:
                                        self.active_modifiers.discard('shift')
                                elif vk_code == VK_MENU:  # Alt
                                    if key_down:
                                        self.active_modifiers.add('alt')
                                    elif key_up:
                                        self.active_modifiers.discard('alt')
                                elif vk_code in [VK_LWIN, VK_RWIN]:
                                    if key_down:
                                        self.active_modifiers.add('win')
                                    elif key_up:
                                        self.active_modifiers.discard('win')
                                
                                # Проверяем основные клавиши при нажатии
                                if key_down:
                                    # Ищем соответствие в VK_CODES
                                    key_char = None
                                    for char, code in VK_CODES.items():
                                        if isinstance(code, int) and code == vk_code:
                                            key_char = char
                                            break
                                    
                                    if key_char:
                                        self.active_key = key_char
                                        print(f"HOTKEY: 🎯 Нажата {key_char}, модификаторы: {self.active_modifiers}")
                                        
                                        # Проверяем совпадения с хоткеями
                                        self._check_hotkey_match()
                                
                                elif key_up and self.active_key:
                                    # Сбрасываем основную клавишу при отпускании
                                    if vk_code == VK_CODES.get(self.active_key, 0):
                                        self.active_key = None
                        
                        # ВАЖНО: всегда вызываем следующий hook
                        return ctypes.windll.user32.CallNextHookExW(self.hook, nCode, wParam, lParam)
                        
                    except Exception as e:
                        print(f"HOTKEY: ❌ Ошибка в keyboard_hook_proc: {e}")
                        # В случае ошибки все равно передаем дальше
                        return ctypes.windll.user32.CallNextHookExW(self.hook, nCode, wParam, lParam)
                
                # Сохраняем ссылку на callback (важно!)
                self.hook_proc = self.HOOKPROC(keyboard_hook_proc)
                
                # Устанавливаем hook
                self.hook = ctypes.windll.user32.SetWindowsHookExW(
                    WH_KEYBOARD_LL,
                    self.hook_proc,
                    ctypes.windll.kernel32.GetModuleHandleW(None),
                    0
                )
                
                if self.hook:
                    print(f"HOTKEY: ✅ Keyboard hook установлен: {self.hook}")
                else:
                    error = ctypes.windll.kernel32.GetLastError()
                    print(f"HOTKEY: ❌ Ошибка установки hook: {error}")
                    return False
                
                return True
                
            except Exception as e:
                print(f"HOTKEY: ❌ Исключение в start_listening: {e}")
                return False
        
        def _check_hotkey_match(self):
            """Проверяет совпадение текущего состояния с зарегистрированными хоткеями"""
            if not self.active_key:
                return
            
            for hotkey_str, callback in self.hotkeys.items():
                parts = [p.strip().lower() for p in hotkey_str.split('+')]
                
                # Разделяем на модификаторы и основную клавишу
                required_modifiers = set()
                required_key = None
                
                for part in parts:
                    if part in ['ctrl', 'control']:
                        required_modifiers.add('ctrl')
                    elif part == 'shift':
                        required_modifiers.add('shift')
                    elif part == 'alt':
                        required_modifiers.add('alt')
                    elif part == 'win':
                        required_modifiers.add('win')
                    else:
                        required_key = part
                
                # Проверяем совпадение
                if (required_key == self.active_key and 
                    required_modifiers == self.active_modifiers):
                    print(f"HOTKEY: ✅ СОВПАДЕНИЕ! Хоткей '{hotkey_str}' сработал")
                    
                    # Вызываем callback в отдельном потоке
                    import threading
                    def safe_callback():
                        try:
                            callback()
                        except Exception as e:
                            print(f"HOTKEY: ❌ Ошибка в callback: {e}")
                    threading.Thread(target=safe_callback, daemon=True).start()
                    
                    # Сбрасываем состояние чтобы избежать повторных срабатываний
                    self.active_key = None
                    return
        
        def stop_listening(self):
            """Останавливает прослушивание и освобождает keyboard hook"""
            self.running = False
            
            # Освобождаем keyboard hook
            if self.hook:
                try:
                    result = ctypes.windll.user32.UnhookWindowsHookExW(self.hook)
                    if result:
                        print("HOTKEY: 🧹 Keyboard hook освобожден")
                    else:
                        error = ctypes.windll.kernel32.GetLastError()
                        print(f"HOTKEY: ⚠️ Ошибка освобождения hook: {error}")
                except Exception as e:
                    print(f"HOTKEY: ❌ Исключение при освобождении hook: {e}")
                finally:
                    self.hook = None
            
            # Очищаем состояние
            self.hotkeys.clear()
            self.active_modifiers.clear()
            self.active_key = None
            
            print("HOTKEY: 🛑 Win32 keyboard hook остановлен")

# Класс для работы с хоткеями (совместимый с .exe)
class HotkeyListener:
    def __init__(self):
        print("DEBUG: HotkeyListener создан")
        self.active_keys = []
        self.hotkey_callbacks = {}
        self.valid_keys = []
        self.running = False
        self.listener = None
        
        # Приоритет: Win32 API > pynput > keyboard  
        if USE_WIN32:
            self.win32_listener = Win32HotkeyListener()
            self.method = "win32"
            print("HOTKEY: 🎯 Будем использовать Win32 API")
        else:
            self.win32_listener = None
            self.method = "fallback"
            print("HOTKEY: 🔄 Используем fallback методы")

    def add_hotkey(self, hotkey, callback_func):
        print(f"DEBUG: add_hotkey({hotkey})")
        """Добавляет хоткей"""
        print(f"HOTKEY: Добавляем хоткей '{hotkey}' ({self.method})")
        print(f"HOTKEY: Текущие зарегистрированные хоткеи ДО добавления: {list(self.hotkey_callbacks.keys())}")
        
        # ОЧИЩАЕМ ВСЕ старые хоткеи перед добавлением нового
        if self.hotkey_callbacks:
            print(f"HOTKEY: 🧹 Очищаем все старые хоткеи: {list(self.hotkey_callbacks.keys())}")
            # Для Win32 просто очищаем внутренний словарь (hook продолжает работать)
            if self.method == "win32" and self.win32_listener:
                self.win32_listener.hotkeys.clear()
            self.hotkey_callbacks.clear()
            self.valid_keys.clear()
        
        # Регистрируем хоткей
        if self.method == "win32" and self.win32_listener:
            # Используем Win32 API
            success = self.win32_listener.register_hotkey(hotkey, callback_func)
            if success:
                self.hotkey_callbacks[hotkey] = callback_func
                print(f"HOTKEY: ✅ Win32 хоткей зарегистрирован: '{hotkey}'")
            else:
                print(f"HOTKEY: ❌ Win32 не работает, переключаемся на fallback")
                # Переключаемся на fallback методы
                self.method = "fallback"
                self.hotkey_callbacks[hotkey] = callback_func
        else:
            # Fallback к старому методу
            self.hotkey_callbacks[hotkey] = callback_func
        # Добавляем все клавиши из хоткея в список валидных
        for key in hotkey.split('+'):
            if key not in self.valid_keys:
                self.valid_keys.append(key)
        print(f"HOTKEY: Валидные клавиши: {self.valid_keys}")
        print(f"HOTKEY: Зарегистрированные хоткеи ПОСЛЕ добавления: {list(self.hotkey_callbacks.keys())}")

    def start_listening(self):
        print("DEBUG: start_listening")
        """Запускает прослушивание клавиш"""
        if self.running:
            return
        self.running = True
        
        if self.method == "win32" and self.win32_listener:
            # Используем Win32 API
            print("HOTKEY: 🚀 Запускаем Win32 listener...")
            success = self.win32_listener.start_listening()
            if success:
                print("HOTKEY: ✅ Win32 listener запущен")
            else:
                print("HOTKEY: ❌ Не удалось запустить Win32 listener, переключаемся на fallback")
                self.method = "fallback"
                print("HOTKEY: 🔄 Запускаем fallback методы после ошибки Win32...")
                self._start_fallback_methods()
        elif self.method == "fallback":
            # Запускаем fallback методы
            print("HOTKEY: 🔄 Запускаем fallback методы...")
            self._start_fallback_methods()
        else:
            # Fallback к старым методам
            if USE_PYNPUT:
                print("HOTKEY: Пробуем запустить pynput listener...")
                try:
                    self._start_pynput_listener()
                    print("HOTKEY: pynput listener запущен")
                    # Тестируем что listener работает через 2 секунды
                    import threading
                    def test_listener():
                        import time
                        time.sleep(3)
                        if not hasattr(self, '_pynput_test_received'):
                            print("HOTKEY: ⚠️ pynput не получает события, переключаемся на keyboard")
                            self._fallback_to_keyboard()
                    threading.Thread(target=test_listener, daemon=True).start()
                except Exception as e:
                    print(f"HOTKEY: Ошибка запуска pynput: {e}, переключаемся на keyboard")
                    self._start_keyboard_listener()
            else:
                self._start_keyboard_listener()
        
        print("HOTKEY: Listener запущен")

    def stop_listening(self):
        self.running = False
        if self.method == "win32" and self.win32_listener:
            self.win32_listener.stop_listening()
        else:
            if self.listener:
                # Если это pynput Listener, у него есть stop()
                if USE_PYNPUT and hasattr(self.listener, 'stop'):
                    self.listener.stop()
                # Если это обычный поток, просто обнуляем ссылку
                self.listener = None
        print("HOTKEY: Listener остановлен")

    def _start_pynput_listener(self):
        """Запуск с pynput"""
        def on_press(key):
            try:
                # Отмечаем что pynput получает события
                self._pynput_test_received = True
                
                key_name = self._get_key_name(key).lower()
                print(f"HOTKEY: Нажата клавиша '{key_name}' (pynput)")
                
                # Добавляем клавишу в активные если её там нет
                if key_name not in self.active_keys:
                    self.active_keys.append(key_name)
                
                # Автоматическая очистка через 2 секунды (на случай залипания)
                def auto_clear():
                    import time
                    time.sleep(2)
                    if len(self.active_keys) > 0:
                        print(f"HOTKEY: Автоматическая очистка активных клавиш: {self.active_keys}")
                        self.active_keys.clear()
                
                threading.Thread(target=auto_clear, daemon=True).start()
                
                print(f"HOTKEY: Активные клавиши: {self.active_keys}")
                print(f"HOTKEY: Зарегистрированные хоткеи: {list(self.hotkey_callbacks.keys())}")
                
                # Проверяем каждый зарегистрированный хоткей
                for registered_hotkey, callback in self.hotkey_callbacks.items():
                    print(f"HOTKEY: Проверяем хоткей '{registered_hotkey}'")
                    
                    # Проверяем совпадение с активными клавишами
                    if self._matches_active_keys(registered_hotkey):
                        print(f"HOTKEY: ✅ СОВПАДЕНИЕ! Вызываем callback для '{registered_hotkey}'")
                        # Выполняем callback в отдельном потоке чтобы не блокировать события
                        import threading
                        def safe_callback():
                            try:
                                callback()
                            except Exception as e:
                                print(f"HOTKEY: Ошибка в callback: {e}")
                        threading.Thread(target=safe_callback, daemon=True).start()
                        # Очищаем активные клавиши после срабатывания
                        old_keys = self.active_keys.copy()
                        self.active_keys.clear()
                        print(f"HOTKEY: 🧹 Активные клавиши очищены после срабатывания: {old_keys} -> {self.active_keys}")
                        break
                
                print(f"HOTKEY: ❌ Не найдено совпадений для активных клавиш: {self.active_keys}")
                        
            except Exception as e:
                print(f"HOTKEY: Ошибка в on_press: {e}")

        def on_release(key):
            try:
                key_name = self._get_key_name(key).lower()
                if key_name in self.active_keys:
                    self.active_keys.remove(key_name)
                    print(f"HOTKEY: Отпущена клавиша '{key_name}', активные: {self.active_keys}")
                    
            except Exception as e:
                print(f"HOTKEY: Ошибка в on_release: {e}")
                
    def _matches_active_keys(self, registered_hotkey):
        """Проверяет соответствуют ли активные клавиши зарегистрированному хоткею"""
        hotkey_parts = [part.lower() for part in registered_hotkey.split('+')]
        print(f"HOTKEY: Сравниваем активные '{self.active_keys}' с хоткеем '{hotkey_parts}'")
        
        # Проверяем что все части хоткея присутствуют в активных клавишах
        for part in hotkey_parts:
            found = False
            
            # Проверяем прямое совпадение
            if part in self.active_keys:
                found = True
                print(f"HOTKEY: Найдена часть '{part}' в активных клавишах")
            else:
                # Проверяем варианты для русских букв
                russian_mapping = {
                    'й': ['й', '◄'],  # й может приходить как ◄
                    'ц': ['ц'],
                    'у': ['у'], 
                    'к': ['к'],
                    'е': ['е'],
                    'н': ['н'],
                    'г': ['г'],
                    'ш': ['ш'],
                    'щ': ['щ'],
                    'з': ['з'],
                    'х': ['х'],
                    'ъ': ['ъ'],
                    'р': ['р'],
                    'о': ['о'],
                    'л': ['л'],
                    'д': ['д'],
                    'ж': ['ж'],
                    'э': ['э'],
                    'я': ['я'],
                    'ч': ['ч'],
                    'с': ['с'],
                    'м': ['м'],
                    'и': ['и'],
                    'т': ['т'],
                    'ь': ['ь'],
                    'б': ['б'],
                    'ю': ['ю']
                }
                
                if part in russian_mapping:
                    for variant in russian_mapping[part]:
                        if variant in self.active_keys:
                            found = True
                            print(f"HOTKEY: Найден вариант '{variant}' для '{part}' в активных клавишах")
                            break
            
            if not found:
                print(f"HOTKEY: Не найдена часть '{part}' в активных клавишах")
                return False
        
        print(f"HOTKEY: ✅ Все части хоткея найдены!")
        return True
    
    def _fallback_to_keyboard(self):
        """Переключение на keyboard метод"""
        print("HOTKEY: Останавливаем pynput и переключаемся на keyboard")
        try:
            if self.listener and hasattr(self.listener, 'stop'):
                self.listener.stop()
                self.listener = None
        except Exception as e:
            print(f"HOTKEY: Ошибка при остановке pynput: {e}")
        self._start_keyboard_listener()

    def _get_key_name(self, key):
        """Получает имя клавиши для pynput"""
        try:
            if hasattr(key, 'char') and key.char:
                return key.char
            elif hasattr(key, 'name'):
                key_name = key.name
                # Маппинг специальных клавиш для совместимости
                key_mapping = {
                    'ctrl_l': 'ctrl',
                    'ctrl_r': 'ctrl', 
                    'shift': 'shift',
                    'shift_l': 'shift',
                    'shift_r': 'shift',
                    'alt_l': 'alt',
                    'alt_r': 'alt',
                    'cmd': 'cmd',
                    'cmd_l': 'cmd',
                    'cmd_r': 'cmd'
                }
                return key_mapping.get(key_name, key_name)
            else:
                return str(key).replace('Key.', '')
        except:
            return str(key)

    def _start_keyboard_listener(self):
        print("DEBUG: _start_keyboard_listener вызван")
        """Запуск с keyboard (fallback метод)"""
        def listen_loop():
            print("DEBUG: listen_loop стартует")
            while self.running:
                try:
                    event = keyboard.read_event()
                    if event.event_type == keyboard.KEY_DOWN:
                        key_name = event.name.lower()
                        print(f"HOTKEY: Нажата клавиша '{key_name}' (keyboard)")
                        # Добавляем клавишу в активные если её там нет
                        if key_name not in self.active_keys:
                            self.active_keys.append(key_name)
                        # Автоматическая очистка через 2 секунды (на случай залипания)
                        def auto_clear():
                            import time
                            time.sleep(2)
                            if len(self.active_keys) > 0:
                                print(f"HOTKEY: Автоматическая очистка активных клавиш: {self.active_keys}")
                                self.active_keys.clear()
                        threading.Thread(target=auto_clear, daemon=True).start()
                        print(f"HOTKEY: Активные клавиши: {self.active_keys}")
                        print(f"HOTKEY: Зарегистрированные хоткеи: {list(self.hotkey_callbacks.keys())}")
                        # Проверяем каждый зарегистрированный хоткей
                        for registered_hotkey, callback in self.hotkey_callbacks.items():
                            print(f"HOTKEY: Проверяем хоткей '{registered_hotkey}'")
                            # Проверяем совпадение с активными клавишами
                            if self._matches_active_keys(registered_hotkey):
                                print(f"HOTKEY: ✅ СОВПАДЕНИЕ! Вызываем callback для '{registered_hotkey}'")
                                # Выполняем callback в отдельном потоке чтобы не блокировать события
                                def safe_callback():
                                    try:
                                        callback()
                                    except Exception as e:
                                        print(f"HOTKEY: Ошибка в callback: {e}")
                                threading.Thread(target=safe_callback, daemon=True).start()
                                # Очищаем активные клавиши после срабатывания
                                old_keys = self.active_keys.copy()
                                self.active_keys.clear()
                                print(f"HOTKEY: 🧹 Активные клавиши очищены после срабатывания: {old_keys} -> {self.active_keys}")
                                break
                        print(f"HOTKEY: ❌ Не найдено совпадений для активных клавиш: {self.active_keys}")
                    elif event.event_type == keyboard.KEY_UP:
                        key_name = event.name.lower()
                        if key_name in self.active_keys:
                            self.active_keys.remove(key_name)
                            print(f"HOTKEY: Отпущена клавиша '{key_name}', активные: {self.active_keys}")
                except Exception as e:
                    print(f"HOTKEY: Ошибка в listen_loop: {e}")
                    break
        self.listener = threading.Thread(target=listen_loop, daemon=True)
        self.listener.start()
        print("HOTKEY: keyboard listener запущен")

    def _start_fallback_methods(self):
        # Пробуем pynput, если доступен
        if USE_PYNPUT:
            print("HOTKEY: Пробуем запустить pynput listener (fallback)...")
            try:
                self._start_pynput_listener()
                print("HOTKEY: pynput listener запущен (fallback)")
                # Тестируем что listener работает через 2 секунды
                import threading
                def test_listener():
                    import time
                    time.sleep(3)
                    if not hasattr(self, '_pynput_test_received'):
                        print("HOTKEY: ⚠️ pynput не получает события, переключаемся на keyboard (fallback)")
                        self._fallback_to_keyboard()
                threading.Thread(target=test_listener, daemon=True).start()
            except Exception as e:
                print(f"HOTKEY: Ошибка запуска pynput (fallback): {e}, переключаемся на keyboard")
                self._start_keyboard_listener()
        else:
            print("HOTKEY: pynput недоступен, запускаем keyboard listener (fallback)")
            self._start_keyboard_listener()

# Эти переменные будут инициализированы после выбора рабочей директории
SETTINGS_FILE = None
LOGO_FILE = None
HTML_TIMER_SETTINGS_FILE = None
LOGS_DIR = None
WORK_DIR = None
ENCRYPTED_CONFIG_FILE = None
encrypted_config = None

class EncryptedConfig:
    """Класс для работы с зашифрованной конфигурацией"""
    
    def __init__(self, config_file_path):
        self.config_file_path = config_file_path
        self.key = None
        self.fernet = None
        self._initialize_encryption()
    
    def _initialize_encryption(self):
        """Инициализирует ключ шифрования"""
        try:
            # Пытаемся загрузить существующий ключ
            if os.path.exists(self.config_file_path):
                with open(self.config_file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if 'encryption_key' in data:
                        key_hex = data['encryption_key']
                        self.key = bytes.fromhex(key_hex)
                        self.fernet = Fernet(base64.urlsafe_b64encode(self.key))
                        return
            
            # Создаем новый ключ
            self.key = secrets.token_bytes(32)
            self.fernet = Fernet(base64.urlsafe_b64encode(self.key))
            
        except Exception as e:
            print(f"Ошибка инициализации шифрования: {e}")
            # Fallback - создаем новый ключ
            self.key = secrets.token_bytes(32)
            self.fernet = Fernet(base64.urlsafe_b64encode(self.key))
    
    def encrypt_data(self, data):
        """Шифрует данные"""
        try:
            json_data = json.dumps(data, ensure_ascii=False)
            encrypted = self.fernet.encrypt(json_data.encode('utf-8'))
            return base64.b64encode(encrypted).decode('utf-8')
        except Exception as e:
            print(f"Ошибка шифрования: {e}")
            return None
    
    def decrypt_data(self, encrypted_data):
        """Дешифрует данные"""
        try:
            encrypted_bytes = base64.b64decode(encrypted_data)
            decrypted = self.fernet.decrypt(encrypted_bytes)
            return json.loads(decrypted.decode('utf-8'))
        except Exception as e:
            print(f"Ошибка дешифрования: {e}")
            return None
    
    def save_config(self, hotkey_settings=None, html_settings=None, client_secret=None):
        """Сохраняет зашифрованную конфигурацию"""
        try:
            config_data = {
                'encryption_key': self.key.hex(),
                'encrypted_data': {}
            }
            
            if hotkey_settings is not None:
                encrypted_hotkey = self.encrypt_data(hotkey_settings)
                if encrypted_hotkey:
                    config_data['encrypted_data']['hotkey_settings'] = encrypted_hotkey
            
            if html_settings is not None:
                encrypted_html = self.encrypt_data(html_settings)
                if encrypted_html:
                    config_data['encrypted_data']['html_timer_settings'] = encrypted_html
            
            if client_secret is not None:
                encrypted_client = self.encrypt_data(client_secret)
                if encrypted_client:
                    config_data['encrypted_data']['client_secret'] = encrypted_client
            
            # Если файл уже существует, загружаем и обновляем
            if os.path.exists(self.config_file_path):
                with open(self.config_file_path, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                    if 'encrypted_data' in existing_data:
                        # Обновляем существующие данные
                        for key, value in config_data['encrypted_data'].items():
                            existing_data['encrypted_data'][key] = value
                        config_data = existing_data
            
            with open(self.config_file_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)
                
            return True
            
        except Exception as e:
            print(f"Ошибка сохранения конфигурации: {e}")
            return False
    
    def load_config(self, config_type):
        """Загружает конкретный тип конфигурации"""
        try:
            if not os.path.exists(self.config_file_path):
                return None
                
            with open(self.config_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            if 'encrypted_data' not in data or config_type not in data['encrypted_data']:
                return None
                
            encrypted_data = data['encrypted_data'][config_type]
            return self.decrypt_data(encrypted_data)
            
        except Exception as e:
            print(f"Ошибка загрузки конфигурации {config_type}: {e}")
            return None
    
    def import_legacy_encrypted_files(self, work_dir):
        """Импортирует настройки из старых отдельных зашифрованных файлов"""
        try:
            # Пути к старым файлам
            key_file = os.path.join(work_dir, 'key.enc')
            hotkey_file = os.path.join(work_dir, 'hotkey_settings.enc')
            html_file = os.path.join(work_dir, 'html_timer_settings.enc')
            client_file = os.path.join(work_dir, 'client_secret.enc')
            
            # Проверяем, есть ли старые файлы
            if not os.path.exists(key_file):
                return False
            
            # Загружаем ключ
            with open(key_file, 'r', encoding='utf-8') as f:
                key_hex = f.read().strip()
                legacy_key = bytes.fromhex(key_hex)
                legacy_fernet = Fernet(base64.urlsafe_b64encode(legacy_key))
            
            imported_data = {}
            
            # Импортируем каждый файл
            for file_path, config_name in [
                (hotkey_file, 'hotkey_settings'),
                (html_file, 'html_timer_settings'), 
                (client_file, 'client_secret')
            ]:
                if os.path.exists(file_path):
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            encrypted_data = f.read().strip()
                        
                        # Дешифруем данные
                        encrypted_bytes = base64.b64decode(encrypted_data)
                        decrypted = legacy_fernet.decrypt(encrypted_bytes)
                        data = json.loads(decrypted.decode('utf-8'))
                        imported_data[config_name] = data
                        
                    except Exception as e:
                        print(f"Ошибка импорта {config_name}: {e}")
            
            # Сохраняем импортированные данные
            if imported_data:
                self.save_config(
                    imported_data.get('hotkey_settings'),
                    imported_data.get('html_timer_settings'),
                    imported_data.get('client_secret')
                )
                print(f"Импортировано {len(imported_data)} конфигураций из старых файлов")
                return True
                
        except Exception as e:
            print(f"Ошибка импорта старых файлов: {e}")
        
        return False

class UserAgreementDialog(QDialog):
    """Диалог пользовательского соглашения"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Пользовательское соглашение')
        self.setFixedSize(700, 600)
        self.setModal(True)
        
        self.setStyleSheet('''
            QDialog {
                background-color: #181f2a;
                color: #e6e6e6;
            }
            QLabel {
                color: #e6e6e6;
                font-size: 14px;
            }
            QPushButton {
                background-color: #232b3b;
                color: #e6e6e6;
                border: 1px solid #2e3950;
                border-radius: 5px;
                padding: 10px 20px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2e3950;
            }
            QPushButton#acceptBtn {
                background-color: #28a745;
                border-color: #28a745;
            }
            QPushButton#acceptBtn:hover {
                background-color: #34ce57;
            }
            QPushButton#rejectBtn {
                background-color: #dc3545;
                border-color: #dc3545;
            }
            QPushButton#rejectBtn:hover {
                background-color: #e74c3c;
            }
            QTextEdit {
                background-color: #232b3b;
                color: #e6e6e6;
                border: 1px solid #2e3950;
                border-radius: 5px;
                padding: 10px;
                font-size: 12px;
                line-height: 1.4;
            }
        ''')
        
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Заголовок
        title = QLabel('ПОЛЬЗОВАТЕЛЬСКОЕ СОГЛАШЕНИЕ')
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet('font-size: 18px; font-weight: bold; margin: 10px; color: #7b5cff;')
        layout.addWidget(title)
        
        subtitle = QLabel('для приложения "GameLeague Timer"')
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet('font-size: 14px; margin-bottom: 15px; color: #cccccc;')
        layout.addWidget(subtitle)
        
        # Текст соглашения в прокручиваемом поле
        agreement_text = self.get_agreement_text()
        
        text_edit = QTextEdit()
        text_edit.setPlainText(agreement_text)
        text_edit.setReadOnly(True)
        layout.addWidget(text_edit)
        
        # Уведомление
        notice = QLabel('Установка и использование приложения означают принятие условий соглашения')
        notice.setAlignment(Qt.AlignCenter)
        notice.setStyleSheet('color: #ffc107; font-size: 12px; margin: 10px; font-weight: bold;')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        
        # Кнопки
        btn_layout = QHBoxLayout()
        
        reject_btn = QPushButton('Отклоняю')
        reject_btn.setObjectName('rejectBtn')
        reject_btn.clicked.connect(self.reject)
        
        accept_btn = QPushButton('Принимаю')
        accept_btn.setObjectName('acceptBtn')
        accept_btn.clicked.connect(self.accept)
        accept_btn.setDefault(True)
        
        btn_layout.addWidget(reject_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(accept_btn)
        
        layout.addLayout(btn_layout)
        
    def get_agreement_text(self):
        return '''ПОЛЬЗОВАТЕЛЬСКОЕ СОГЛАШЕНИЕ
для приложения "TGL"

Настоящее Пользовательское соглашение (далее – «Соглашение») представляет собой юридически обязывающий договор между Разработчиком (владельцем прав на приложение «TGL») и Пользователем (физическим или юридическим лицом, использующим Приложение). Установка, запуск или иное использование Приложения означают безоговорочное принятие всех условий настоящего Соглашения. В случае несогласия с любым из положений Пользователь обязан немедленно прекратить использование Приложения.

1. Термины и определения
 1.1. Приложение – программное обеспечение под наименованием «Timer App», включая все обновления, модификации и сопутствующие сервисы.
 1.2. Пользователь – дееспособное физическое или юридическое лицо, осуществляющее использование Приложения на законных основаниях.
 1.3. Разработчик – правообладатель Приложения, указанный в официальных магазинах приложений.
 1.4. Контент – любые данные, включая тексты, графику, звуки, видео и иные материалы, доступные в рамках Приложения.
 1.5. Учетная запись – персонифицированный профиль Пользователя, созданный для доступа к расширенному функционалу Приложения (при наличии).

2. Предмет соглашения
 2.1. Разработчик предоставляет Пользователю ограниченную, неисключительную, непередаваемую, отзывную лицензию на использование Приложения в соответствии с его функциональным назначением и условиями настоящего Соглашения.
 2.2. Все права интеллектуальной собственности на Приложение, включая, но не ограничиваясь, исходным кодом, интерфейсом, алгоритмами и торговыми марками, остаются за Разработчиком.

3. Условия использования
 3.1. Пользователь соглашается:
    • Использовать Приложение исключительно в личных, некоммерческих целях.
    • Не воспроизводить, не распространять и не создавать производные произведения на основе Приложения без письменного согласия Разработчика
    • Не осуществлять реверс-инжиниринг, декомпиляцию или иные попытки извлечения исходного кода Приложения.
    • Не использовать Приложение в целях, нарушающих законодательство или права третьих лиц.

 3.2. Разработчик вправе:
    • В одностороннем порядке изменять функционал Приложения, включая добавление, удаление или модификацию функций.
    • Ограничивать доступ к Приложению в случае нарушения условий Соглашения.
    • Собирать и анализировать анонимные данные использования для улучшения работы Приложения.

4. Ограничения ответственности
 4.1. Приложение предоставляется на условиях «как есть» (AS IS). Разработчик не гарантирует бесперебойную работу Приложения, его совместимость со всеми устройствами или отсутствие ошибок.
 4.2. Разработчик не несет ответственности:
    • За косвенные, случайные или consequential damages, возникшие в результате использования Приложения.
    • За действия Пользователя, повлекшие ущерб третьим лицам.
    • За невозможность использования Приложения вследствие технических сбоев, действий интернет-провайдеров или иных форс-мажорных обстоятельств.
 4.3. Максимальная совокупная ответственность Разработчика ограничивается суммой, уплаченной Пользователем за использование Приложения в течение последних 6 (шести) месяцев.

5. Конфиденциальность и обработка данных
 5.1. Обработка персональных данных Пользователя осуществляется в соответствии с Политикой конфиденциальности, являющейся неотъемлемой частью настоящего Соглашения.
 5.2. Приложение может запрашивать доступ к следующим функциям устройства:
    • Уведомления (для оповещения о завершении таймера).
    • Фоновый режим (для продолжения работы таймера при закрытом приложении).
5.3. Разработчик применяет industry-standard меры защиты данных, однако не гарантирует абсолютную безопасность при передаче информации через интернет.

6. Платные услуги и подписки
 6.1. Некоторые функции Приложения могут предоставляться на платной основе (премиум-доступ, отключение рекламы и т.д.).
 6.2. Условия автоматического продления подписки:
    • Платежи списываются с привязанного аккаунта до момента отмены подписки. 
    • Отмена подписки должна быть произведена не менее чем за 24 часа до окончания текущего расчетного периода.
6.3. Возврат средств возможен только в случаях, предусмотренных правилами платформ распространения.

7. Заключительные положения
 7.1. Настоящее Соглашение регулируется законодательством [страна регистрации Разработчика]. Все споры подлежат разрешению в соответствующих судебных инстанциях.
 7.2. Разработчик оставляет за собой право уведомлять Пользователя об изменениях в Соглашении путем публикации обновленной версии в Приложении или на официальном сайте.
 7.3. Признание отдельных положений Соглашения недействительными не влечет недействительности остальных условий.'''

class WorkDirectoryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Выбор рабочей директории')
        self.setFixedSize(600, 450)  # Увеличиваем размер окна
        self.setModal(True)
        self.selected_dir = None
        
        self.setStyleSheet('''
            QDialog {
                background-color: #181f2a;
                color: #e6e6e6;
            }
            QLabel {
                color: #e6e6e6;
                font-size: 12px;
            }
            QPushButton {
                background-color: #232b3b;
                color: #e6e6e6;
                border: 1px solid #2e3950;
                border-radius: 5px;
                padding: 8px 15px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #2e3950;
            }
            QLineEdit {
                background-color: #232b3b;
                color: #e6e6e6;
                border: 1px solid #2e3950;
                border-radius: 5px;
                padding: 8px;
                font-size: 12px;
            }
        ''')
        
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Заголовок
        title = QLabel('Добро пожаловать в GameLeague Timer!')
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet('font-size: 16px; font-weight: bold; margin: 10px;')
        layout.addWidget(title)
        
        # Описание
        desc = QLabel('Выберите папку, где будут храниться настройки и логи таймера.\n'
                     'Рекомендуется создать отдельную папку для таймера.\n\n'
                     'При первом запуске будут созданы:\n'
                     '• Зашифрованный файл конфигурации \n'
                     '• Резервные файлы настроек \n'
                     '• Папка для логов игр \n'
                     '• Необходимые файлы ресурсов\n\n'
                     '• Файлы GDI эфектор и звуковых эффектов')
        desc.setAlignment(Qt.AlignLeft)  # Изменено с Center на Left для лучшей читаемости
        desc.setWordWrap(True)
        desc.setStyleSheet('color: #ffffff; font-size: 13px; margin: 15px; line-height: 1.4;')  # Улучшены стили
        layout.addWidget(desc)
        
        layout.addSpacing(15)
        
        # Выбор директории
        dir_layout = QHBoxLayout()
        self.dir_input = QLineEdit()
        self.dir_input.setPlaceholderText('Путь к рабочей директории...')
        self.dir_input.setReadOnly(True)
        
        browse_btn = QPushButton('Обзор...')
        browse_btn.clicked.connect(self.browse_directory)
        
        dir_layout.addWidget(self.dir_input)
        dir_layout.addWidget(browse_btn)
        layout.addLayout(dir_layout)
        
        layout.addSpacing(10)
        
        # Кнопка для создания новой папки
        create_btn = QPushButton('Создать новую папку для таймера')
        create_btn.clicked.connect(self.create_new_directory)
        create_btn.setStyleSheet('QPushButton { padding: 8px; font-size: 12px; }')
        layout.addWidget(create_btn)
        
        layout.addSpacing(25)
        
        # Кнопки
        btn_layout = QHBoxLayout()
        
        ok_btn = QPushButton('Продолжить')
        ok_btn.clicked.connect(self.accept_directory)
        ok_btn.setStyleSheet('QPushButton { padding: 10px 20px; font-size: 13px; font-weight: bold; }')
        ok_btn.setDefault(True)
        
        cancel_btn = QPushButton('Отмена')
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet('QPushButton { padding: 10px 20px; font-size: 13px; }')
        
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)
        
        # Предлагаем текущую директорию по умолчанию
        default_dir = os.path.join(os.getcwd(), 'TimerData')
        self.dir_input.setText(default_dir)
        self.selected_dir = default_dir
        
    def browse_directory(self):
        dir_path = QFileDialog.getExistingDirectory(self, 'Выберите папку для таймера')
        if dir_path:
            self.dir_input.setText(dir_path)
            self.selected_dir = dir_path
            
    def create_new_directory(self):
        dir_path = QFileDialog.getExistingDirectory(self, 'Выберите папку, где создать новую директорию')
        if dir_path:
            new_dir = os.path.join(dir_path, 'GameLeagueTimer')
            try:
                os.makedirs(new_dir, exist_ok=True)
                self.dir_input.setText(new_dir)
                self.selected_dir = new_dir
                QMessageBox.information(self, 'Успешно', f'Создана папка: {new_dir}')
            except Exception as e:
                QMessageBox.warning(self, 'Ошибка', f'Не удалось создать папку: {str(e)}')
                
    def accept_directory(self):
        if not self.selected_dir:
            QMessageBox.warning(self, 'Ошибка', 'Выберите директорию')
            return
            
        # Проверяем, существует ли директория, если нет - создаем
        try:
            os.makedirs(self.selected_dir, exist_ok=True)
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, 'Ошибка', f'Не удалось создать/получить доступ к директории: {str(e)}')

def init_work_directory():
    """Инициализирует рабочую директорию и пути к файлам"""
    global WORK_DIR, SETTINGS_FILE, LOGO_FILE, HTML_TIMER_SETTINGS_FILE, LOGS_DIR
    
    # Проверяем, есть ли уже сохраненная рабочая директория
    # Для exe файла ищем рядом с exe, для скрипта - в текущей папке
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        temp_settings_file = os.path.join(exe_dir, 'work_dir.json')
    else:
        temp_settings_file = os.path.join(os.getcwd(), 'work_dir.json')
    
    if os.path.exists(temp_settings_file):
        try:
            with open(temp_settings_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                WORK_DIR = data.get('work_dir')
                
            # Проверяем, что директория все еще существует
            if WORK_DIR and os.path.exists(WORK_DIR):
                _setup_paths()
                return True
        except:
            pass
    
    # Если нет сохраненной директории или она не существует - показываем диалоги
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    
    # Сначала показываем пользовательское соглашение
    agreement_dialog = UserAgreementDialog()
    if agreement_dialog.exec_() != QDialog.Accepted:
        # Пользователь отклонил соглашение - выходим
        return False
    
    # Если соглашение принято - показываем диалог выбора директории
    dialog = WorkDirectoryDialog()
    if dialog.exec_() == QDialog.Accepted:
        WORK_DIR = dialog.selected_dir
        
        # Сохраняем выбранную директорию в том же месте где искали
        try:
            with open(temp_settings_file, 'w', encoding='utf-8') as f:
                json.dump({'work_dir': WORK_DIR}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(None, 'Ошибка', f'Не удалось сохранить настройки: {str(e)}')
        
        _setup_paths()
        return True
    else:
        return False

def _setup_paths():
    """Настраивает все пути на основе рабочей директории"""
    global SETTINGS_FILE, LOGO_FILE, HTML_TIMER_SETTINGS_FILE, LOGS_DIR, ENCRYPTED_CONFIG_FILE, encrypted_config
    
    SETTINGS_FILE = os.path.join(WORK_DIR, 'hotkey_settings.json')
    LOGO_FILE = os.path.join(WORK_DIR, 'logo.png')
    HTML_TIMER_SETTINGS_FILE = os.path.join(WORK_DIR, 'html_timer_settings.json')
    LOGS_DIR = os.path.join(WORK_DIR, 'log')
    ENCRYPTED_CONFIG_FILE = os.path.join(WORK_DIR, 'timer_config.enc')
    
    # Инициализируем зашифрованную конфигурацию
    encrypted_config = EncryptedConfig(ENCRYPTED_CONFIG_FILE)
    
    # Создаем необходимые директории
    os.makedirs(LOGS_DIR, exist_ok=True)
    
    # Копируем logo.png в рабочую директорию, если его там нет
    current_dir_logo = os.path.join(os.path.dirname(__file__), 'logo.png')
    if os.path.exists(current_dir_logo) and not os.path.exists(LOGO_FILE):
        try:
            shutil.copy2(current_dir_logo, LOGO_FILE)
        except:
            pass
    
    # Если нет logo.png в директории скрипта, создаем пустой файл-заглушку
    if not os.path.exists(current_dir_logo):
        try:
            # Создаем минимальный PNG файл (1x1 прозрачный пиксель)
            png_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x00\x01\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
            with open(current_dir_logo, 'wb') as f:
                f.write(png_data)
        except Exception as e:
            print(f"Ошибка создания logo.png: {e}")
    
    # Создаем logo2.png если его нет
    current_dir_logo2 = os.path.join(os.path.dirname(__file__), 'logo2.png')
    if not os.path.exists(current_dir_logo2):
        try:
            # Копируем logo.png как logo2.png
            if os.path.exists(current_dir_logo):
                shutil.copy2(current_dir_logo, current_dir_logo2)
            else:
                # Создаем минимальный PNG файл
                png_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x00\x01\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
                with open(current_dir_logo2, 'wb') as f:
                    f.write(png_data)
        except Exception as e:
            print(f"Ошибка создания logo2.png: {e}")
    
    # Создаем заглушку client_secret.json в рабочей директории (НЕ в директории скрипта)
    work_client_secret_file = os.path.join(WORK_DIR, 'client_secret.json')
    if not os.path.exists(work_client_secret_file):
        try:
            # Создаем заглушку для client_secret.json (для справки пользователя)
            client_secret_stub = {
                "installed": {
                    "client_id": "your_client_id.apps.googleusercontent.com",
                    "project_id": "your_project_id",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    "client_secret": "your_client_secret",
                    "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
                    "_comment": "Это заглушка. Реальные данные OAuth хранятся в зашифрованном timer_config.enc"
                }
            }
            with open(work_client_secret_file, 'w', encoding='utf-8') as f:
                json.dump(client_secret_stub, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка создания client_secret.json: {e}")
    
    # Создаем зашифрованную конфигурацию с дефолтными настройками
    try:
        # Сначала пытаемся импортировать из старых зашифрованных файлов
        imported = encrypted_config.import_legacy_encrypted_files(WORK_DIR)
        if imported:
            print("Успешно импортированы настройки из старых зашифрованных файлов")
        
        # Проверяем, есть ли уже зашифрованные настройки
        hotkey_settings = encrypted_config.load_config('hotkey_settings')
        html_settings = encrypted_config.load_config('html_timer_settings')
        client_secret = encrypted_config.load_config('client_secret')
        
        # Создаем дефолтные настройки, если их нет
        if hotkey_settings is None:
            hotkey_settings = {
                'hotkey': None,
                'hotkey_display': None,
                'email': None,
                'ws_port': 8765
            }
        
        if html_settings is None:
            html_settings = {
                'font_family': 'Segoe UI',
                'font_size': 'medium',
                'show_game_name': False,
                'game_name_position': 'top',
                'bg_color': '#181f2a',
                'timer_color': '#ffffff',
                'timer_bg_color': '#232b3b',
                'opacity': 85,
                'border_radius': 36,
                'padding': 40,
                'shadow': True,
                'shadow_size': 32,
                'show_seconds': True,
                'show_hours': True,
                'outline': False,
                'outline_color': '#000000',
                'outline_width': 2
            }
        
        if client_secret is None:
            # Пытаемся загрузить реальные данные Google OAuth из файла в директории скрипта
            script_client_secret_file = os.path.join(os.path.dirname(__file__), 'client_secret.json')
            if os.path.exists(script_client_secret_file):
                try:
                    with open(script_client_secret_file, 'r', encoding='utf-8') as f:
                        client_secret = json.load(f)
                    print("Загружены реальные данные Google OAuth для шифрования")
                except Exception as e:
                    print(f"Ошибка загрузки client_secret.json: {e}")
                    client_secret = None
            
            # Если не удалось загрузить, создаем заглушку
            if client_secret is None:
                client_secret = {
                    "installed": {
                        "client_id": "your_client_id.apps.googleusercontent.com",
                        "project_id": "timer_project",
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                        "client_secret": "your_client_secret",
                        "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"]
                    }
                }
        
        # Сохраняем все настройки в зашифрованном виде
        encrypted_config.save_config(hotkey_settings, html_settings, client_secret)
        
        # Создаем обычные файлы для совместимости (если их нет)
        if not os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(hotkey_settings, f, ensure_ascii=False, indent=2)
        
        if not os.path.exists(HTML_TIMER_SETTINGS_FILE):
            with open(HTML_TIMER_SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(html_settings, f, ensure_ascii=False, indent=2)
        
    except Exception as e:
        print(f"Ошибка создания зашифрованной конфигурации: {e}")
        # Fallback - создаем обычные файлы
        if not os.path.exists(SETTINGS_FILE):
            try:
                default_settings = {
                    'hotkey': None,
                    'hotkey_display': None,
                    'email': None,
                    'ws_port': 8765
                }
                with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(default_settings, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"Ошибка создания файла настроек: {e}")
        
        if not os.path.exists(HTML_TIMER_SETTINGS_FILE):
            try:
                default_html_settings = {
                    'font_family': 'Segoe UI',
                    'font_size': 'medium',
                    'show_game_name': False,
                    'game_name_position': 'top',
                    'bg_color': '#181f2a',
                    'timer_color': '#ffffff',
                    'timer_bg_color': '#232b3b',
                    'opacity': 85,
                    'border_radius': 36,
                    'padding': 40,
                    'shadow': True,
                    'shadow_size': 32,
                    'show_seconds': True,
                    'show_hours': True,
                    'outline': False,
                    'outline_color': '#000000',
                    'outline_width': 2
                }
                with open(HTML_TIMER_SETTINGS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(default_html_settings, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"Ошибка создания файла настроек HTML таймера: {e}")

class CustomColorDialog(QDialog):
    def __init__(self, initial_color="#ffffff", parent=None):
        super().__init__(parent)
        self.setWindowTitle('Выберите цвет')
        self.setFixedSize(380, 320)
        self.setModal(True)
        self.initial_color = initial_color
        self.setStyleSheet('''
            QDialog {
                background-color: #181f2a;
                color: #e6e6e6;
                border-radius: 12px;
            }
            QLabel {
                color: #e6e6e6;
                font-size: 14px;
            }
            QLineEdit {
                background: #232b3b;
                color: #e6e6e6;
                border: 1px solid #2e3950;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 15px;
            }
            QSlider::groove:horizontal {
                border: 1px solid #2e3950;
                height: 8px;
                background: #232b3b;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #7b5cff;
                border: 1px solid #2e3950;
                width: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
            QPushButton {
                background-color: #232b3b;
                color: #e6e6e6;
                border: 1px solid #2e3950;
                border-radius: 8px;
                padding: 10px 24px;
                font-size: 15px;
                font-weight: bold;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #2e3950;
            }
            QPushButton#acceptBtn {
                background-color: #28a745;
                border-color: #28a745;
                color: #fff;
            }
            QPushButton#acceptBtn:hover {
                background-color: #34ce57;
            }
            QPushButton#rejectBtn {
                background-color: #dc3545;
                border-color: #dc3545;
                color: #fff;
            }
            QPushButton#rejectBtn:hover {
                background-color: #e74c3c;
            }
        ''')
        self.init_ui()

    def init_ui(self):
        from PyQt5.QtWidgets import QSlider, QLineEdit
        from PyQt5.QtGui import QColor
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        # Preview
        self.preview = QLabel()
        self.preview.setFixedSize(90, 90)
        self.preview.setStyleSheet(f"background: {self.initial_color}; border: 2px solid #7b5cff; border-radius: 12px;")
        layout.addWidget(self.preview, alignment=Qt.AlignHCenter)
        # HEX
        hex_layout = QHBoxLayout()
        hex_label = QLabel("HEX:")
        hex_label.setFixedWidth(36)
        self.hex_edit = QLineEdit(self.initial_color)
        self.hex_edit.setMaxLength(7)
        hex_layout.addWidget(hex_label)
        hex_layout.addWidget(self.hex_edit)
        layout.addLayout(hex_layout)
        # R, G, B sliders
        self.r_slider = QSlider(Qt.Horizontal)
        self.g_slider = QSlider(Qt.Horizontal)
        self.b_slider = QSlider(Qt.Horizontal)
        for s in (self.r_slider, self.g_slider, self.b_slider):
            s.setRange(0, 255)
            s.setSingleStep(1)
        color = QColor(self.initial_color)
        self.r_slider.setValue(color.red())
        self.g_slider.setValue(color.green())
        self.b_slider.setValue(color.blue())
        for name, slider in zip(["R", "G", "B"], [self.r_slider, self.g_slider, self.b_slider]):
            row = QHBoxLayout()
            label = QLabel(name + ":")
            label.setFixedWidth(18)
            row.addWidget(label)
            row.addWidget(slider)
            value_label = QLabel(str(slider.value()))
            value_label.setFixedWidth(28)
            row.addWidget(value_label)
            slider.valueChanged.connect(lambda val, l=value_label: l.setText(str(val)))
            layout.addLayout(row)
        layout.addSpacing(8)
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        reject_btn = QPushButton('Отмена')
        reject_btn.setObjectName('rejectBtn')
        reject_btn.clicked.connect(self.reject)
        accept_btn = QPushButton('Принять')
        accept_btn.setObjectName('acceptBtn')
        accept_btn.clicked.connect(self.accept)
        accept_btn.setDefault(True)
        btn_layout.addWidget(reject_btn)
        btn_layout.addWidget(accept_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        # Сигналы
        self.r_slider.valueChanged.connect(self.sync_rgb_to_hex)
        self.g_slider.valueChanged.connect(self.sync_rgb_to_hex)
        self.b_slider.valueChanged.connect(self.sync_rgb_to_hex)
        self.hex_edit.textChanged.connect(self.sync_hex_to_rgb)
        self.selected_color = self.initial_color

    def sync_rgb_to_hex(self):
        from PyQt5.QtGui import QColor
        r, g, b = self.r_slider.value(), self.g_slider.value(), self.b_slider.value()
        hex_color = f"#{r:02x}{g:02x}{b:02x}"
        self.hex_edit.setText(hex_color)
        self.preview.setStyleSheet(f"background: {hex_color}; border: 2px solid #7b5cff; border-radius: 12px;")
        self.selected_color = hex_color

    def sync_hex_to_rgb(self):
        from PyQt5.QtGui import QColor
        hex_val = self.hex_edit.text()
        if QColor(hex_val).isValid():
            color = QColor(hex_val)
            self.r_slider.setValue(color.red())
            self.g_slider.setValue(color.green())
            self.b_slider.setValue(color.blue())
            self.preview.setStyleSheet(f"background: {hex_val}; border: 2px solid #7b5cff; border-radius: 12px;")
            self.selected_color = hex_val

    def getColor(self):
        if self.exec_() == QDialog.Accepted:
            return self.selected_color
        return None

class HTMLTimerSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Настройки HTML таймера')
        self.setFixedSize(450, 600)
        self.setStyleSheet('''
            QDialog {
                background-color: #181f2a;
                color: #e6e6e6;
            }
            QLabel {
                color: #e6e6e6;
                font-size: 14px;
            }
            QPushButton {
                background-color: #232b3b;
                color: #e6e6e6;
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2e3950;
            }
            QPushButton:pressed {
                background-color: #1e2630;
            }
            QComboBox {
                background-color: #232b3b;
                color: #e6e6e6;
                border: 1px solid #2e3950;
                border-radius: 4px;
                padding: 6px;
                min-width: 120px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #e6e6e6;
            }
            QComboBox QAbstractItemView {
                background-color: #232b3b;
                color: #e6e6e6;
                border: 1px solid #2e3950;
                selection-background-color: #7b5cff;
            }
            QSpinBox {
                background-color: #232b3b;
                color: #e6e6e6;
                border: 1px solid #2e3950;
                border-radius: 4px;
                padding: 6px;
                min-width: 80px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #2e3950;
                border: none;
                border-radius: 2px;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #7b5cff;
            }
            QCheckBox {
                color: #e6e6e6;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 2px solid #2e3950;
                border-radius: 3px;
                background-color: #232b3b;
            }
            QCheckBox::indicator:checked {
                background-color: #7b5cff;
                border-color: #7b5cff;
            }
            QCheckBox::indicator:checked::after {
                content: "✓";
                color: white;
                font-weight: bold;
                font-size: 12px;
            }
        ''')
        self.init_ui()
        self.load_settings()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Создаем форму для настроек
        form_layout = QFormLayout()
        
        # Шрифт
        self.font_family_combo = QComboBox(self)
        # Загружаем список системных шрифтов
        font_db = QFontDatabase()
        font_families = font_db.families()
        # Добавляем стандартные шрифты в начало
        standard_fonts = ['Segoe UI', 'Arial', 'Helvetica', 'Times New Roman', 'Courier New']
        for font in standard_fonts:
            if font in font_families:
                font_families.remove(font)
        all_fonts = standard_fonts + sorted(font_families)
        self.font_family_combo.addItems(all_fonts)
        self.font_family_combo.setCurrentText('Segoe UI')
        form_layout.addRow('Шрифт:', self.font_family_combo)
        
        # Размер шрифта (убираем очень большие размеры)
        self.font_size_combo = QComboBox(self)
        self.font_size_combo.addItems(['Очень маленький', 'Маленький', 'Средний', 'Большой'])
        self.font_size_combo.setCurrentText('Средний')
        form_layout.addRow('Размер шрифта:', self.font_size_combo)
        
        # Показывать название игры
        self.show_game_name_checkbox = QCheckBox('Показывать название игры', self)
        self.show_game_name_checkbox.setChecked(False)
        form_layout.addRow('', self.show_game_name_checkbox)
        
        # Позиция названия игры
        self.game_name_position_combo = QComboBox(self)
        self.game_name_position_combo.addItems(['Сверху таймера', 'Снизу таймера'])
        self.game_name_position_combo.setCurrentText('Сверху таймера')
        form_layout.addRow('Позиция названия:', self.game_name_position_combo)
        
        # Цвет фона
        self.bg_color_btn = QPushButton('Выбрать цвет', self)
        self.bg_color_btn.clicked.connect(self.choose_bg_color)
        self.bg_color_preview = QLabel(self)
        self.bg_color_preview.setFixedSize(40, 25)
        self.bg_color_preview.setStyleSheet('background: #181f2a; border: 2px solid #7b5cff; border-radius: 4px;')
        bg_color_layout = QHBoxLayout()
        bg_color_layout.addWidget(self.bg_color_btn)
        bg_color_layout.addWidget(self.bg_color_preview)
        form_layout.addRow('Цвет фона:', bg_color_layout)
        
        # Цвет таймера
        self.timer_color_btn = QPushButton('Выбрать цвет', self)
        self.timer_color_btn.clicked.connect(self.choose_timer_color)
        self.timer_color_preview = QLabel(self)
        self.timer_color_preview.setFixedSize(40, 25)
        self.timer_color_preview.setStyleSheet('background: #fff; border: 2px solid #7b5cff; border-radius: 4px;')
        timer_color_layout = QHBoxLayout()
        timer_color_layout.addWidget(self.timer_color_btn)
        timer_color_layout.addWidget(self.timer_color_preview)
        form_layout.addRow('Цвет таймера:', timer_color_layout)
        
        # Цвет фона таймера
        self.timer_bg_color_btn = QPushButton('Выбрать цвет', self)
        self.timer_bg_color_btn.clicked.connect(self.choose_timer_bg_color)
        self.timer_bg_color_preview = QLabel(self)
        self.timer_bg_color_preview.setFixedSize(40, 25)
        self.timer_bg_color_preview.setStyleSheet('background: #232b3b; border: 2px solid #7b5cff; border-radius: 4px;')
        timer_bg_color_layout = QHBoxLayout()
        timer_bg_color_layout.addWidget(self.timer_bg_color_btn)
        timer_bg_color_layout.addWidget(self.timer_bg_color_preview)
        form_layout.addRow('Фон таймера:', timer_bg_color_layout)
        
        # Прозрачность фона
        self.opacity_spin = QSpinBox(self)
        self.opacity_spin.setRange(0, 100)
        self.opacity_spin.setValue(85)
        self.opacity_spin.setSuffix('%')
        form_layout.addRow('Прозрачность:', self.opacity_spin)
        
        # Скругление углов
        self.border_radius_spin = QSpinBox(self)
        self.border_radius_spin.setRange(0, 500)
        self.border_radius_spin.setValue(36)
        self.border_radius_spin.setSuffix('px')
        form_layout.addRow('Скругление углов:', self.border_radius_spin)
        
        # Отступы
        self.padding_spin = QSpinBox(self)
        self.padding_spin.setRange(10, 100)
        self.padding_spin.setValue(40)
        self.padding_spin.setSuffix('px')
        form_layout.addRow('Отступы:', self.padding_spin)
        

        
        # Показывать время в секундах
        self.show_seconds_checkbox = QCheckBox('Показывать секунды', self)
        self.show_seconds_checkbox.setChecked(True)
        form_layout.addRow('', self.show_seconds_checkbox)
        
        # Показывать часы
        self.show_hours_checkbox = QCheckBox('Показывать часы', self)
        self.show_hours_checkbox.setChecked(True)
        form_layout.addRow('', self.show_hours_checkbox)
        
        # Обводка цифр
        self.outline_checkbox = QCheckBox('Включить обводку цифр', self)
        self.outline_checkbox.setChecked(False)
        form_layout.addRow('', self.outline_checkbox)
        
        # Цвет обводки
        self.outline_color_btn = QPushButton('Выбрать цвет', self)
        self.outline_color_btn.clicked.connect(self.choose_outline_color)
        self.outline_color_preview = QLabel(self)
        self.outline_color_preview.setFixedSize(40, 25)
        self.outline_color_preview.setStyleSheet('background: #000000; border: 2px solid #7b5cff; border-radius: 4px;')
        outline_color_layout = QHBoxLayout()
        outline_color_layout.addWidget(self.outline_color_btn)
        outline_color_layout.addWidget(self.outline_color_preview)
        form_layout.addRow('Цвет обводки:', outline_color_layout)
        
        # Толщина обводки
        self.outline_width_spin = QSpinBox(self)
        self.outline_width_spin.setRange(1, 20)
        self.outline_width_spin.setValue(2)
        self.outline_width_spin.setSuffix('px')
        form_layout.addRow('Толщина обводки:', self.outline_width_spin)
        
        layout.addLayout(form_layout)
        
        # Кнопки
        buttons_layout = QHBoxLayout()
        save_btn = QPushButton('Сохранить', self)
        cancel_btn = QPushButton('Отмена', self)
        
        # Устанавливаем правильные роли кнопок
        save_btn.setDefault(True)  # Кнопка по умолчанию
        cancel_btn.setAutoDefault(False)   # НЕ авто-дефолтная
        
        save_btn.clicked.connect(self.save_settings)
        cancel_btn.clicked.connect(self.reject)
        
        buttons_layout.addStretch()
        buttons_layout.addWidget(cancel_btn)
        buttons_layout.addWidget(save_btn)
        
        layout.addLayout(buttons_layout)
        self.setLayout(layout)
    
    def choose_bg_color(self):
        color_dialog = CustomColorDialog(getattr(self, 'bg_color', '#181f2a'), self)
        color = color_dialog.getColor()
        if color:
            self.bg_color = color
            self.bg_color_preview.setStyleSheet(f'background: {self.bg_color}; border: 2px solid #7b5cff; border-radius: 4px;')
    
    def choose_timer_color(self):
        color_dialog = CustomColorDialog(getattr(self, 'timer_color', '#ffffff'), self)
        color = color_dialog.getColor()
        if color:
            self.timer_color = color
            self.timer_color_preview.setStyleSheet(f'background: {self.timer_color}; border: 2px solid #7b5cff; border-radius: 4px;')
    
    def choose_timer_bg_color(self):
        color_dialog = CustomColorDialog(getattr(self, 'timer_bg_color', '#232b3b'), self)
        color = color_dialog.getColor()
        if color:
            self.timer_bg_color = color
            self.timer_bg_color_preview.setStyleSheet(f'background: {self.timer_bg_color}; border: 2px solid #7b5cff; border-radius: 4px;')

    
    def choose_outline_color(self):
        color_dialog = CustomColorDialog(getattr(self, 'outline_color', '#000000'), self)
        color = color_dialog.getColor()
        if color:
            self.outline_color = color
            self.outline_color_preview.setStyleSheet(f'background: {self.outline_color}; border: 2px solid #7b5cff; border-radius: 4px;')

    
    def load_settings(self):
        try:
            # Сначала пытаемся загрузить из зашифрованного файла
            settings = None
            if encrypted_config:
                settings = encrypted_config.load_config('html_timer_settings')
            
            # Если не удалось, загружаем из обычного файла
            if settings is None:
                with open(HTML_TIMER_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
            
            # Применяем настройки к элементам интерфейса (независимо от источника)
            if settings is not None:
                font_size_map = {
                    'very_small': 'Очень маленький',
                    'small': 'Маленький', 
                    'medium': 'Средний',
                    'large': 'Большой'
                }
                
                # Загружаем семейство шрифта
                font_family = settings.get('font_family', 'Segoe UI')
                font_index = self.font_family_combo.findText(font_family)
                if font_index >= 0:
                    self.font_family_combo.setCurrentIndex(font_index)
                else:
                    self.font_family_combo.setCurrentText('Segoe UI')
                
                font_size = settings.get('font_size', 'medium')
                self.font_size_combo.setCurrentText(font_size_map.get(font_size, 'Средний'))
                
                # Настройки названия игры
                self.show_game_name_checkbox.setChecked(settings.get('show_game_name', False))
                game_name_position = settings.get('game_name_position', 'top')
                position_text = 'Сверху таймера' if game_name_position == 'top' else 'Снизу таймера'
                self.game_name_position_combo.setCurrentText(position_text)
                
                self.bg_color = settings.get('bg_color', '#181f2a')
                self.bg_color_preview.setStyleSheet(f'background: {self.bg_color}; border: 2px solid #7b5cff; border-radius: 4px;')
                
                self.timer_color = settings.get('timer_color', '#ffffff')
                self.timer_color_preview.setStyleSheet(f'background: {self.timer_color}; border: 2px solid #7b5cff; border-radius: 4px;')
                
                self.timer_bg_color = settings.get('timer_bg_color', '#232b3b')
                self.timer_bg_color_preview.setStyleSheet(f'background: {self.timer_bg_color}; border: 2px solid #7b5cff; border-radius: 4px;')

                
                self.opacity_spin.setValue(settings.get('opacity', 85))
                self.border_radius_spin.setValue(settings.get('border_radius', 36))
                self.padding_spin.setValue(settings.get('padding', 40))
                self.show_seconds_checkbox.setChecked(settings.get('show_seconds', True))
                self.show_hours_checkbox.setChecked(settings.get('show_hours', True))
                self.outline_checkbox.setChecked(settings.get('outline', False))
                self.outline_color = settings.get('outline_color', '#000000')
                self.outline_color_preview.setStyleSheet(f'background: {self.outline_color}; border: 2px solid #7b5cff; border-radius: 4px;')
                self.outline_width_spin.setValue(settings.get('outline_width', 2))
            else:
                # Значения по умолчанию если настройки не загрузились
                self.font_family_combo.setCurrentText('Segoe UI')
                self.font_size_combo.setCurrentText('Средний')
                self.show_game_name_checkbox.setChecked(False)
                self.game_name_position_combo.setCurrentText('Сверху таймера')
                self.bg_color = '#181f2a'
                self.bg_color_preview.setStyleSheet(f'background: {self.bg_color}; border: 2px solid #7b5cff; border-radius: 4px;')
                self.timer_color = '#ffffff'
                self.timer_color_preview.setStyleSheet(f'background: {self.timer_color}; border: 2px solid #7b5cff; border-radius: 4px;')
                self.timer_bg_color = '#232b3b'
                self.timer_bg_color_preview.setStyleSheet(f'background: {self.timer_bg_color}; border: 2px solid #7b5cff; border-radius: 4px;')
                self.outline_color = '#000000'
                self.outline_color_preview.setStyleSheet(f'background: {self.outline_color}; border: 2px solid #7b5cff; border-radius: 4px;')
                self.opacity_spin.setValue(85)
                self.border_radius_spin.setValue(36)
                self.padding_spin.setValue(40)
                self.show_seconds_checkbox.setChecked(True)
                self.show_hours_checkbox.setChecked(True)
                self.outline_checkbox.setChecked(False)
                self.outline_width_spin.setValue(2)
                
        except FileNotFoundError:
            # Значения по умолчанию если файл не найден
            self.font_family_combo.setCurrentText('Segoe UI')
            self.font_size_combo.setCurrentText('Средний')
            self.show_game_name_checkbox.setChecked(False)
            self.game_name_position_combo.setCurrentText('Сверху таймера')
            self.bg_color = '#181f2a'
            self.bg_color_preview.setStyleSheet(f'background: {self.bg_color}; border: 2px solid #7b5cff; border-radius: 4px;')
            self.timer_color = '#ffffff'
            self.timer_color_preview.setStyleSheet(f'background: {self.timer_color}; border: 2px solid #7b5cff; border-radius: 4px;')
            self.timer_bg_color = '#232b3b'
            self.timer_bg_color_preview.setStyleSheet(f'background: {self.timer_bg_color}; border: 2px solid #7b5cff; border-radius: 4px;')
            self.outline_color = '#000000'
            self.outline_color_preview.setStyleSheet(f'background: {self.outline_color}; border: 2px solid #7b5cff; border-radius: 4px;')
            self.opacity_spin.setValue(85)
            self.border_radius_spin.setValue(36)
            self.padding_spin.setValue(40)
            self.show_seconds_checkbox.setChecked(True)
            self.show_hours_checkbox.setChecked(True)
            self.outline_checkbox.setChecked(False)
            self.outline_width_spin.setValue(2)
    
    def save_settings(self):
        font_size_map = {
            'Очень маленький': 'very_small',
            'Маленький': 'small',
            'Средний': 'medium', 
            'Большой': 'large'
        }
        
        # Определяем позицию названия игры
        game_name_position = 'top' if self.game_name_position_combo.currentText() == 'Сверху таймера' else 'bottom'
        
        settings = {
            'font_family': self.font_family_combo.currentText(),
            'font_size': font_size_map.get(self.font_size_combo.currentText(), 'medium'),
            'show_game_name': self.show_game_name_checkbox.isChecked(),
            'game_name_position': game_name_position,
            'bg_color': getattr(self, 'bg_color', '#181f2a'),
            'timer_color': getattr(self, 'timer_color', '#ffffff'),
            'timer_bg_color': getattr(self, 'timer_bg_color', '#232b3b'),
            'opacity': self.opacity_spin.value(),
            'border_radius': self.border_radius_spin.value(),
            'padding': self.padding_spin.value(),
            'show_seconds': self.show_seconds_checkbox.isChecked(),
            'show_hours': self.show_hours_checkbox.isChecked(),
            'outline': self.outline_checkbox.isChecked(),
            'outline_color': getattr(self, 'outline_color', '#000000'),
            'outline_width': self.outline_width_spin.value()
        }
        

        
        # Сохраняем в зашифрованном файле
        if encrypted_config:
            encrypted_config.save_config(html_settings=settings)
        
        # Также сохраняем в обычном файле для совместимости
        with open(HTML_TIMER_SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        
        # Обновляем overlay таймер, если он существует
        if hasattr(self.parent(), 'overlay_timer'):
            self.parent().overlay_timer.refresh_settings()
            self.parent().overlay_timer.apply_html_settings()
        
        # Генерируем и сохраняем обновленный HTML для WebSocket
        self.update_live_html()
        
        QMessageBox.information(self, 'Сохранено', 'Настройки HTML таймера сохранены!\nОбновления автоматически отправлены в браузер.')
        self.accept()
    
    def update_live_html(self):
        """Генерирует и сохраняет HTML для автоматического обновления"""
        try:
            # Используем настройки которые только что сохранили
            font_size_map = {
                'Очень маленький': 'very_small',
                'Маленький': 'small',
                'Средний': 'medium', 
                'Большой': 'large'
            }
            
            game_name_position = 'top' if self.game_name_position_combo.currentText() == 'Сверху таймера' else 'bottom'
            
            settings = {
                'font_family': self.font_family_combo.currentText(),
                'font_size': font_size_map.get(self.font_size_combo.currentText(), 'medium'),
                'show_game_name': self.show_game_name_checkbox.isChecked(),
                'game_name_position': game_name_position,
                'bg_color': getattr(self, 'bg_color', '#181f2a'),
                'timer_color': getattr(self, 'timer_color', '#ffffff'),
                'timer_bg_color': getattr(self, 'timer_bg_color', '#232b3b'),
                'opacity': self.opacity_spin.value(),
                'border_radius': self.border_radius_spin.value(),
                'padding': self.padding_spin.value(),
                'show_seconds': self.show_seconds_checkbox.isChecked(),
                'show_hours': self.show_hours_checkbox.isChecked(),
                'outline': self.outline_checkbox.isChecked(),
                'outline_color': getattr(self, 'outline_color', '#000000'),
                'outline_width': self.outline_width_spin.value()
            }
            
            # Добавляем текущее время и игру из родительского приложения
            if hasattr(self.parent(), 'last_time_str'):
                settings['current_time'] = self.parent().last_time_str
            else:
                settings['current_time'] = '00:00:00'
                
            if hasattr(self.parent(), 'current_game') and self.parent().current_game:
                settings['current_game'] = self.parent().current_game
            else:
                settings['current_game'] = 'Timer'
            
            # Используем функцию generate_html_with_settings из родительского приложения
            if hasattr(self.parent(), 'generate_html_with_settings'):
                html = self.parent().generate_html_with_settings(settings)
            else:
                html = self.generate_html()  # Fallback на старую функцию
            
            # Сохраняем HTML файл для веб-сервера
            html_file_path = os.path.join(WORK_DIR, 'timer_live.html')
            with open(html_file_path, 'w', encoding='utf-8') as f:
                f.write(html)
            

                
        except Exception as e:
            print(f"Ошибка обновления live HTML: {e}")
    

    def generate_html(self):
        font_size_map = {
            'Очень маленький': 'min(12vw, 20vh)',
            'Маленький': 'min(16vw, 28vh)',
            'Средний': 'min(22vw, 40vh)',
            'Большой': 'min(28vw, 50vh)'
        }
        
        font_family = self.font_family_combo.currentText()
        font_size = font_size_map.get(self.font_size_combo.currentText(), 'min(22vw, 40vh)')
        show_game_name = self.show_game_name_checkbox.isChecked()
        game_name_position = 'top' if self.game_name_position_combo.currentText() == 'Сверху таймера' else 'bottom'
        bg_color = getattr(self, 'bg_color', '#181f2a')
        timer_color = getattr(self, 'timer_color', '#ffffff')
        timer_bg_color = getattr(self, 'timer_bg_color', '#232b3b')
        opacity = self.opacity_spin.value()
        border_radius = self.border_radius_spin.value()
        padding = self.padding_spin.value()
        show_seconds = self.show_seconds_checkbox.isChecked()
        show_hours = self.show_hours_checkbox.isChecked()
        outline = self.outline_checkbox.isChecked()
        outline_color = getattr(self, 'outline_color', '#000000')
        outline_width = self.outline_width_spin.value()
        
        # Создаем стиль обводки
        outline_style = ''
        if outline:
            # Создаем обводку с помощью text-shadow
            outline_shadows = []
            for i in range(-outline_width, outline_width + 1):
                for j in range(-outline_width, outline_width + 1):
                    if i != 0 or j != 0:  # Исключаем центральную точку
                        outline_shadows.append(f'{i}px {j}px 0 {outline_color}')
            outline_style = f'text-shadow: {", ".join(outline_shadows)};'
        
        time_format = 'HH:mm:ss' if show_hours and show_seconds else 'HH:mm' if show_hours else 'mm:ss' if show_seconds else 'mm'
        
        html = f'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>GameLeague Timer</title>
<style>
html, body {{
  height: 100%;
  margin: 0;
  padding: 0;
}}
body {{
  width: 100vw;
  height: 100vh;
  background: {bg_color};
  color: {timer_color};
  font-family: Segoe UI, Arial, sans-serif;
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  overflow: hidden;
}}
#timer-bg {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: {padding}px;
  background: {timer_bg_color};
  border-radius: {border_radius}px;
  {shadow_style}
}}
#timer {{
  display: block;
  margin: 0 auto;
  font-size: {font_size};
  font-weight: bold;
  text-align: center;
  user-select: none;
  letter-spacing: -0.05em;
  line-height: 1;
  transform: translate(-7px, -17px);
  {outline_style}
}}
@media (max-width: 900px) {{
  #timer {{ font-size: calc({font_size} * 0.7); }}
  #timer-bg {{ padding: calc({padding}px * 0.5); border-radius: calc({border_radius}px * 0.5); }}
}}
</style>
</head>
<body>
<div id="timer-bg"><div id="timer">00:00:00</div></div>
<script>
let ws = null;
function connect() {{
  ws = new WebSocket('ws://' + window.location.hostname + ':' + window.location.port + '/ws');
  ws.onmessage = function(e) {{
    let time = e.data;
    // Форматируем время согласно настройкам
    let parts = time.split(':');
    if (parts.length === 3) {{
      let hours = parts[0];
      let minutes = parts[1];
      let seconds = parts[2];
      
      if ('{time_format}' === 'HH:mm:ss') {{
        time = hours + ':' + minutes + ':' + seconds;
      }} else if ('{time_format}' === 'HH:mm') {{
        time = hours + ':' + minutes;
      }} else if ('{time_format}' === 'mm:ss') {{
        time = minutes + ':' + seconds;
      }} else {{
        time = minutes;
      }}
    }}
    document.getElementById('timer').textContent = time;
  }};
  ws.onclose = function() {{ setTimeout(connect, 1000); }};
}}
connect();
</script>
</body>
</html>'''
        
        return html

class ImageLoader(QThread):
    image_loaded = pyqtSignal(str, QPixmap)
    
    def __init__(self, url, game_name, target_size=(160, 120)):
        super().__init__()
        self.url = url
        self.game_name = game_name
        self.target_size = target_size
    
    def run(self):
        try:
            # Загружаем изображение по URL
            with urllib.request.urlopen(self.url, timeout=10) as response:
                image_data = response.read()
                pixmap = QPixmap()
                
                if pixmap.loadFromData(image_data):
                    # Масштабируем изображение до нужного размера с высоким качеством
                    scaled_pixmap = pixmap.scaled(
                        self.target_size[0], 
                        self.target_size[1], 
                        Qt.KeepAspectRatio, 
                        Qt.SmoothTransformation
                    )
                    self.image_loaded.emit(self.game_name, scaled_pixmap)
                else:
                    print(f"Не удалось загрузить изображение для {self.game_name}")
                    self.image_loaded.emit(self.game_name, self.create_placeholder())
                    
        except Exception as e:
            print(f"Ошибка загрузки изображения для {self.game_name}: {e}")
            # Отправляем placeholder изображение в случае ошибки
            self.image_loaded.emit(self.game_name, self.create_placeholder())
    
    def create_placeholder(self):
        """Создает placeholder изображение с иконкой игры"""
        # Создаем пустое изображение
        pixmap = QPixmap(self.target_size[0], self.target_size[1])
        pixmap.fill(Qt.transparent)
        
        # Создаем painter для рисования
        from PyQt5.QtGui import QPainter, QFont, QColor
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Рисуем фон
        painter.fillRect(0, 0, self.target_size[0], self.target_size[1], QColor('#232b3b'))
        
        # Рисуем иконку игры (простой символ)
        painter.setPen(QColor('#7b5cff'))
        painter.setFont(QFont('Arial', min(self.target_size[0], self.target_size[1]) // 4, QFont.Bold))
        
        # Центрируем текст
        text = "🎮"
        text_rect = painter.fontMetrics().boundingRect(text)
        x = (self.target_size[0] - text_rect.width()) // 2
        y = (self.target_size[1] + text_rect.height()) // 2
        painter.drawText(x, y, text)
        
        painter.end()
        return pixmap

class WebSocketSettingsDialog(QDialog):
    def __init__(self, parent=None, port=8765):
        super().__init__(parent)
        self.setWindowTitle('WebSocket настройки')
        self.setFixedSize(300, 100)
        layout = QFormLayout()
        self.port_spin = QSpinBox(self)
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(port)
        layout.addRow('Порт:', self.port_spin)
        btn = QPushButton('Сохранить', self)
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)
        self.setLayout(layout)
    def get_port(self):
        return self.port_spin.value()

class AddGameDialog(QDialog):
    def __init__(self, parent=None, is_editing=False):
        super().__init__(parent)
        self.is_editing = is_editing
        title = 'Редактировать игру' if is_editing else 'Добавить игру'
        self.setWindowTitle(title)
        self.setFixedSize(400, 250)
        self.init_ui()
    
    def init_ui(self):
        layout = QFormLayout()
        
        self.game_name_input = QLineEdit(self)
        self.game_name_input.setPlaceholderText('Введите название игры')
        layout.addRow('Название игры:', self.game_name_input)
        
        self.image_url_input = QLineEdit(self)
        self.image_url_input.setPlaceholderText('https://example.com/image.jpg')
        layout.addRow('Ссылка на изображение:', self.image_url_input)
        
        # Добавляем поле для времени прохождения
        self.time_to_beat_input = QSpinBox(self)
        self.time_to_beat_input.setRange(0, 9999)
        self.time_to_beat_input.setSuffix(' минут')
        self.time_to_beat_input.setToolTip('Среднее время прохождения игры в минутах')
        layout.addRow('Время прохождения:', self.time_to_beat_input)
        
        buttons = QHBoxLayout()
        ok_text = 'Сохранить' if self.is_editing else 'Добавить'
        ok_button = QPushButton(ok_text)
        cancel_button = QPushButton('Отмена')
        
        ok_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)
        
        buttons.addWidget(ok_button)
        buttons.addWidget(cancel_button)
        layout.addRow(buttons)
        
        self.setLayout(layout)
    
    def get_game_data(self):
        return {
            'name': self.game_name_input.text().strip(),
            'image_url': self.image_url_input.text().strip(),
            'time_to_beat_average': self.time_to_beat_input.value()
        }

class GameListItemWidget(QWidget):
    def __init__(self, game_name, pixmap=None, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(12)
        self.image_label = QLabel(self)
        self.image_label.setFixedSize(100, 100)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet('''
            border-radius: 10px; 
            background: #181f2a; 
            border: 2px solid #2e3950;
        ''')
        if pixmap and not pixmap.isNull():
            # Масштабируем изображение для списка
            scaled_pixmap = pixmap.scaled(100, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.image_label.setPixmap(scaled_pixmap)
        else:
            # Устанавливаем placeholder
            self.set_placeholder_image()
        layout.addWidget(self.image_label)
        self.name_label = QLabel(game_name, self)
        self.name_label.setStyleSheet('font-size: 20px; color: #e6e6e6;')
        layout.addWidget(self.name_label)
        layout.addStretch(1)
        self.setLayout(layout)
    
    def set_placeholder_image(self):
        """Устанавливает placeholder изображение для списка"""
        from PyQt5.QtGui import QPainter, QFont, QColor
        
        # Создаем пустое изображение
        pixmap = QPixmap(100, 100)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Рисуем фон
        painter.fillRect(0, 0, 100, 100, QColor('#181f2a'))
        
        # Рисуем иконку игры
        painter.setPen(QColor('#7b5cff'))
        painter.setFont(QFont('Arial', 24, QFont.Bold))
        
        # Центрируем текст
        text = "🎮"
        text_rect = painter.fontMetrics().boundingRect(text)
        x = (100 - text_rect.width()) // 2
        y = (100 + text_rect.height()) // 2
        painter.drawText(x, y, text)
        
        painter.end()
        self.image_label.setPixmap(pixmap)

class GameCardWidget(QWidget):
    def __init__(self, game_name, pixmap=None, selected=False, parent=None, idx=None, time_to_beat=None, current_time=0):
        super().__init__(parent)
        self.game_name = game_name
        self.selected = selected
        self.idx = idx
        self.time_to_beat = time_to_beat
        self.current_time = current_time
        self.setFixedSize(280, 360)  # Увеличиваем высоту для дополнительного времени
        self.setStyleSheet(self._get_style())
        # Убеждаемся, что виджет может получать события мыши
        self.setMouseTracking(True)
        
        # Вертикальный layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # Изображение сверху
        self.image_label = QLabel(self)
        self.image_label.setFixedSize(240, 240)  # Увеличиваем на 100% (было 120x120)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet('''
            border-radius: 12px; 
            background: #232b3b; 
            border: 2px solid #2e3950;
        ''')
        # Убеждаемся, что изображение не перехватывает события мыши
        self.image_label.setMouseTracking(False)
        if pixmap and not pixmap.isNull():
            # Масштабируем изображение для квадратного контейнера
            scaled_pixmap = pixmap.scaled(240, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.image_label.setPixmap(scaled_pixmap)
        else:
            # Устанавливаем placeholder если изображение не загружено
            self.set_placeholder_image()
        layout.addWidget(self.image_label)
        
        # Название под изображением
        self.name_label = QLabel(game_name, self)
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setWordWrap(True)  # Перенос слов
        self.name_label.setStyleSheet('''
            font-size: 18px; 
            color: #e6e6e6; 
            font-weight: bold;
            padding: 4px;
            background: transparent;
            border: none;
        ''')
        layout.addWidget(self.name_label)
        
        # Время прохождения под названием
        self.time_label = QLabel(self)
        self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setStyleSheet('''
            font-size: 14px; 
            color: #7b5cff; 
            font-weight: bold;
            padding: 2px;
            background: transparent;
            border: none;
        ''')
        if time_to_beat and time_to_beat > 0:
            hours = time_to_beat // 60
            minutes = time_to_beat % 60
            if hours > 0:
                time_text = f"Среднее время: {hours}ч {minutes}м"
            else:
                time_text = f"Среднее время: {minutes}м"
            self.time_label.setText(time_text)
        else:
            self.time_label.setText("Время не указано")
        layout.addWidget(self.time_label)
        
        # Текущее время пользователя под средним временем
        self.current_time_label = QLabel(self)
        self.current_time_label.setAlignment(Qt.AlignCenter)
        self.current_time_label.setStyleSheet('''
            font-size: 12px; 
            color: #e6e6e6; 
            font-weight: normal;
            padding: 2px;
            background: transparent;
            border: none;
        ''')
        # Форматируем текущее время
        if current_time > 0:
            hours = current_time // 3600
            minutes = (current_time % 3600) // 60
            seconds = current_time % 60
            if hours > 0:
                current_time_text = f"Ваше время: {hours}ч {minutes}м {seconds}с"
            elif minutes > 0:
                current_time_text = f"Ваше время: {minutes}м {seconds}с"
            else:
                current_time_text = f"Ваше время: {seconds}с"
        else:
            current_time_text = "Ваше время: 0с"
        self.current_time_label.setText(current_time_text)
        layout.addWidget(self.current_time_label)
        
        self.setLayout(layout)
    def set_selected(self, selected):
        self.selected = selected
        self.setStyleSheet(self._get_style())
    def set_pixmap(self, pixmap):
        if pixmap and not pixmap.isNull():
            # Масштабируем изображение для квадратного контейнера
            scaled_pixmap = pixmap.scaled(240, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.image_label.setPixmap(scaled_pixmap)
        else:
            self.set_placeholder_image()
    
    def update_current_time(self, current_time):
        """Обновляет отображение текущего времени пользователя"""
        self.current_time = current_time
        if current_time > 0:
            hours = current_time // 3600
            minutes = (current_time % 3600) // 60
            seconds = current_time % 60
            if hours > 0:
                current_time_text = f"Ваше время: {hours}ч {minutes}м {seconds}с"
            elif minutes > 0:
                current_time_text = f"Ваше время: {minutes}м {seconds}с"
            else:
                current_time_text = f"Ваше время: {seconds}с"
        else:
            current_time_text = "Ваше время: 0с"
        self.current_time_label.setText(current_time_text)
    
    def set_placeholder_image(self):
        """Устанавливает placeholder изображение"""
        from PyQt5.QtGui import QPainter, QFont, QColor
        
        # Создаем пустое изображение
        pixmap = QPixmap(240, 240)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Рисуем фон
        painter.fillRect(0, 0, 240, 240, QColor('#232b3b'))
        
        # Рисуем иконку игры
        painter.setPen(QColor('#7b5cff'))
        painter.setFont(QFont('Arial', 56, QFont.Bold))  # Увеличиваем размер шрифта
        
        # Центрируем текст
        text = "🎮"
        text_rect = painter.fontMetrics().boundingRect(text)
        x = (240 - text_rect.width()) // 2
        y = (240 + text_rect.height()) // 2
        painter.drawText(x, y, text)
        
        painter.end()
        self.image_label.setPixmap(pixmap)
    def _get_style(self):
        if self.selected:
            return 'background: #7b5cff; border-radius: 16px; border: 2px solid #fff;'
        else:
            return 'background: #232b3b; border-radius: 16px; border: 2px solid #232b3b;'
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and hasattr(self.parent(), 'on_card_clicked'):
            self.parent().on_card_clicked(self)
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and hasattr(self.parent(), 'on_card_double_clicked'):
            self.parent().on_card_double_clicked(self)
    
    def apply_theme(self, theme):
        """Применяет тему к карточке игры"""
        if not theme:
            return
        self.setStyleSheet(self._get_style(theme))
    
    def _get_style(self, theme=None):
        if not theme:
            # Дефолтные цвета
            bg_color = '#232b3b'
            border_color = '#2e3950'
            text_color = '#ffffff'
            selected_color = '#7b5cff'
        else:
            bg_color = theme['card_bg']
            border_color = theme['border_color']
            text_color = theme['text_color']
            selected_color = theme['accent_color']
        
        border = f'3px solid {selected_color}' if self.selected else f'1px solid {border_color}'
        return f'''
            QWidget {{
                background: {bg_color};
                border: {border};
                border-radius: 12px;
                color: {text_color};
            }}
            QWidget:hover {{
                border: 2px solid {selected_color};
            }}
        '''

class OverlayTimerLabel(QLabel):
    """Кастомный QLabel с поддержкой обводки текста"""
    
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.outline_enabled = False
        self.outline_color = '#000000'
        self.outline_width = 2
    
    def set_outline(self, enabled, color='#000000', width=2):
        self.outline_enabled = enabled
        self.outline_color = color
        self.outline_width = width
        self.update()
    
    def paintEvent(self, event):
        if not self.outline_enabled:
            super().paintEvent(event)
            return
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Получаем текст и его размеры
        text = self.text()
        font = self.font()
        painter.setFont(font)
        
        # Вычисляем позицию текста
        rect = self.rect()
        flags = self.alignment()
        
        # Рисуем обводку
        painter.setPen(QPen(QColor(self.outline_color), self.outline_width, Qt.SolidLine))
        
        # Рисуем обводку в нескольких направлениях
        for dx in range(-self.outline_width, self.outline_width + 1):
            for dy in range(-self.outline_width, self.outline_width + 1):
                if dx != 0 or dy != 0:  # Исключаем центральную точку
                    painter.drawText(rect.adjusted(dx, dy, dx, dy), flags, text)
        
        # Рисуем основной текст
        painter.setPen(self.palette().color(QPalette.WindowText))
        painter.drawText(rect, flags, text)

class OverlayTimerWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('GameLeague Timer - Поверх всех окон')
        self.setFixedSize(300, 150)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Загружаем настройки HTML таймера
        self.html_settings = self.load_html_settings()
        
        # Применяем настройки к окну
        self.apply_html_settings()
        
        self.init_ui()
        self.dragging = False
        self.offset = None
    
    def load_html_settings(self):
        """Загружает настройки HTML таймера"""
        try:
            # Сначала пытаемся загрузить из зашифрованного файла
            if encrypted_config:
                settings = encrypted_config.load_config('html_timer_settings')
                if settings is not None:
                    return settings
            
            # Если не удалось, загружаем из обычного файла
            with open(HTML_TIMER_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            # Настройки по умолчанию
            return {
                'font_size': 'medium',
                'bg_color': '#181f2a',
                'timer_color': '#ffffff',
                'timer_bg_color': '#232b3b',
                'opacity': 85,
                'border_radius': 36,
                'padding': 40,
                'shadow': True,
                'shadow_size': 32,
                'show_seconds': True,
                'show_hours': True,
                'outline': False,
                'outline_color': '#000000',
                'outline_width': 2
            }
    
    def apply_html_settings(self):
        """Применяет настройки HTML таймера к overlay окну"""
        settings = self.html_settings
        
        # Конвертируем цвета
        bg_color = settings.get('bg_color', '#181f2a')
        timer_color = settings.get('timer_color', '#ffffff')
        timer_bg_color = settings.get('timer_bg_color', '#232b3b')
        opacity = settings.get('opacity', 85)
        border_radius = settings.get('border_radius', 36)
        padding = settings.get('padding', 40)
        shadow = settings.get('shadow', True)
        shadow_size = settings.get('shadow_size', 32)
        outline = settings.get('outline', False)
        outline_color = settings.get('outline_color', '#000000')
        outline_width = settings.get('outline_width', 2)
        
        # Конвертируем HEX в RGB для прозрачности
        bg_r = int(bg_color[1:3], 16)
        bg_g = int(bg_color[3:5], 16)
        bg_b = int(bg_color[5:7], 16)
        bg_alpha = opacity / 100
        
        # Определяем размер шрифта
        font_size_map = {
            'very_small': 24,
            'small': 32,
            'medium': 36,
            'large': 48,
            'very_large': 56,
            'giant': 64
        }
        font_size = font_size_map.get(settings.get('font_size', 'medium'), 36)
        
        # Создаем стиль тени (Qt поддерживает только простые тени)
        shadow_style = ''
        if shadow:
            shadow_style = f'border: 2px solid rgba(0,0,0,0.2);'
        
        # Применяем стили
        self.setStyleSheet(f'''
            QWidget {{
                background-color: rgba({bg_r}, {bg_g}, {bg_b}, {bg_alpha});
                color: {timer_color};
                border-radius: {border_radius}px;
                border: none;
                {shadow_style}
            }}
            QLabel#timerLabel {{
                font-size: {font_size}px;
                font-weight: bold;
                color: {timer_color};
                background: {timer_bg_color};
                border: none;
                padding: {padding}px;
                border-radius: {border_radius}px;
            }}
        ''')
        
        # Обновляем размер окна в зависимости от настроек
        new_width = padding * 2 + font_size * 6  # Примерная ширина для времени
        new_height = padding * 2 + font_size * 1.5  # Примерная высота
        self.setFixedSize(int(new_width), int(new_height))
        
        # Сохраняем настройки обводки для использования в paintEvent
        self.outline_enabled = outline
        self.outline_color = outline_color
        self.outline_width = outline_width
        
        # Устанавливаем обводку для кастомного лейбла
        if hasattr(self, 'timer_label') and isinstance(self.timer_label, OverlayTimerLabel):
            self.timer_label.set_outline(outline, outline_color, outline_width)
    
    def refresh_settings(self):
        """Обновляет настройки overlay таймера"""
        self.html_settings = self.load_html_settings()
        self.apply_html_settings()
        
        # Обновляем обводку для кастомного лейбла
        if hasattr(self, 'timer_label') and isinstance(self.timer_label, OverlayTimerLabel):
            settings = self.html_settings
            outline = settings.get('outline', False)
            outline_color = settings.get('outline_color', '#000000')
            outline_width = settings.get('outline_width', 2)
            self.timer_label.set_outline(outline, outline_color, outline_width)
    
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Таймер с кастомной отрисовкой
        self.timer_label = OverlayTimerLabel('00:00:00', self)
        self.timer_label.setObjectName('timerLabel')
        self.timer_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.timer_label)
        
        self.setLayout(layout)
        
        # Устанавливаем обводку после создания лейбла
        if hasattr(self, 'outline_enabled'):
            self.timer_label.set_outline(self.outline_enabled, self.outline_color, self.outline_width)
    
    def update_time(self, time_str):
        """Обновляет время с учетом настроек отображения"""
        settings = self.html_settings
        
        # Парсим время
        parts = time_str.split(':')
        if len(parts) == 3:
            hours, minutes, seconds = parts
        elif len(parts) == 2:
            minutes, seconds = parts
            hours = '00'
        else:
            self.timer_label.setText(time_str)
            return
        
        # Форматируем время согласно настройкам
        show_hours = settings.get('show_hours', True)
        show_seconds = settings.get('show_seconds', True)
        
        if show_hours and show_seconds:
            formatted_time = f'{hours}:{minutes}:{seconds}'
        elif show_hours:
            formatted_time = f'{hours}:{minutes}'
        elif show_seconds:
            formatted_time = f'{minutes}:{seconds}'
        else:
            formatted_time = minutes
        
        self.timer_label.setText(formatted_time)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.offset = event.pos()
    
    def mouseMoveEvent(self, event):
        if self.dragging and self.offset:
            new_pos = self.mapToParent(event.pos() - self.offset)
            self.move(new_pos)
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = False
            self.offset = None
    
    def apply_theme(self, theme):
        """Применяет тему к окну поверх всех приложений"""
        # Перезагружаем настройки HTML таймера и применяем их
        self.html_settings = self.load_html_settings()
        self.apply_html_settings()

class GameGridWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid = QGridLayout(self)
        self.grid.setSpacing(6)
        self.grid.setContentsMargins(8, 8, 8, 8)
        self.cards = []
        self.selected_idx = None
        self.setLayout(self.grid)
    def set_games(self, games, images):
        for card in self.cards:
            card.setParent(None)
        self.cards = []
        cols = 2  # Возвращаем 2 колонки для больших карточек
        for idx, (game_name, game_info) in enumerate(games.items()):
            pixmap = images.get(game_name)
            time_to_beat = game_info.get('time_to_beat_average', 0) if isinstance(game_info, dict) else 0
            current_time = game_info.get('seconds', 0) if isinstance(game_info, dict) else 0
            card = GameCardWidget(game_name, pixmap, selected=(idx==self.selected_idx), parent=self, idx=idx, time_to_beat=time_to_beat, current_time=current_time)
            row, col = divmod(idx, cols)
            self.grid.addWidget(card, row, col)
            self.cards.append(card)
    def on_card_clicked(self, card_widget):
        idx = card_widget.idx
        if self.selected_idx is not None and 0 <= self.selected_idx < len(self.cards):
            self.cards[self.selected_idx].set_selected(False)
        self.selected_idx = idx
        self.cards[idx].set_selected(True)
    def get_selected_game(self, games):
        if self.selected_idx is not None and 0 <= self.selected_idx < len(self.cards):
            return list(games.keys())[self.selected_idx]
        return None
    def on_card_double_clicked(self, card_widget):
        # Ищем GameSelectionPage среди родителей
        parent = self.parent()
        while parent:
            if hasattr(parent, 'edit_game'):
                parent.edit_game(card_widget.game_name)
                return
            parent = parent.parent()
    
    def update_game_time(self, game_name, new_time):
        """Обновляет время для конкретной игры в карточке"""
        for card in self.cards:
            if card.game_name == game_name:
                card.update_current_time(new_time)
                break

class GameSelectionPage(QWidget):
    def __init__(self, parent=None, timer_app=None):
        super().__init__(parent)
        self.timer_app = timer_app  # Ссылка на основное приложение
        self.image_loaders = {}
        self.game_images = {}
        self.image_cache = {}  # Кэш для загруженных изображений
        self.init_ui()
        self.load_games()
    def init_ui(self):
        self.setStyleSheet("""
QScrollBar:vertical {
    background: #232b3b;
    width: 12px;
    border-radius: 6px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #7b5cff;
    border-radius: 6px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: #8b6cff;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
""")
        layout = QVBoxLayout()
        self.grid_widget = GameGridWidget(self)
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.NoFrame)
        self.scroll_area.setWidget(self.grid_widget)
        layout.addWidget(self.scroll_area)
        # Первая строка кнопок
        btn_layout1 = QHBoxLayout()
        btn_layout1.setSpacing(12)
        
        self.add_game_btn = QPushButton('Добавить игру')
        self.add_game_btn.setMinimumWidth(140)
        self.add_game_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.add_game_btn.clicked.connect(self.add_game)
        
        self.edit_game_btn = QPushButton('Редактировать')
        self.edit_game_btn.setMinimumWidth(140)
        self.edit_game_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.edit_game_btn.clicked.connect(self.edit_selected_game)
        
        self.remove_game_btn = QPushButton('Удалить игру')
        self.remove_game_btn.setMinimumWidth(140)
        self.remove_game_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.remove_game_btn.clicked.connect(self.remove_game)
        
        btn_layout1.addWidget(self.add_game_btn)
        btn_layout1.addWidget(self.edit_game_btn)
        btn_layout1.addWidget(self.remove_game_btn)
        layout.addLayout(btn_layout1)
        
        # Вторая строка кнопок
        btn_layout2 = QHBoxLayout()
        btn_layout2.setSpacing(12)
        
        # Добавляем кнопку для загрузки игр с GameLeague
        self.load_gameleague_btn = QPushButton('Загрузить с GameLeague')
        self.load_gameleague_btn.setMinimumWidth(200)
        self.load_gameleague_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.load_gameleague_btn.clicked.connect(self.load_gameleague_games)
        btn_layout2.addWidget(self.load_gameleague_btn)
        
        # Добавляем растягивающийся элемент для центрирования
        btn_layout2.addStretch()
        layout.addLayout(btn_layout2)
        nav_layout = QHBoxLayout()
        self.back_btn = QPushButton('← Назад')
        self.next_btn = QPushButton('Далее →')
        nav_layout.addWidget(self.back_btn)
        nav_layout.addWidget(self.next_btn)
        layout.addLayout(nav_layout)
        
        # Прижимаем футер к низу
        layout.addStretch()
        
        # Добавляем футер с версией и автором
        footer_layout = QHBoxLayout()
        self.version_label = QLabel(f'Версия: 1.1.11', self)
        self.version_label.setStyleSheet('color: #888888; font-size: 12px;')
        self.author_label = QLabel('by DeadKDV', self)
        self.author_label.setStyleSheet('color: #888888; font-size: 12px;')
        
        footer_layout.addWidget(self.version_label)
        footer_layout.addStretch()
        footer_layout.addWidget(self.author_label)
        layout.addLayout(footer_layout)
        
        self.setLayout(layout)
    

    def load_games(self):
        self.games_data = {}
        import glob
        log_files = glob.glob(os.path.join(LOGS_DIR, 'timer_log_*.json'))
        for log_file in log_files:
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    game_data = json.load(f)
                    game_name = game_data.get('game_name', '')
                    if game_name:
                        self.games_data[game_name] = {
                            'seconds': game_data.get('total_time_seconds', 0),
                            'image_url': game_data.get('image_url', ''),
                            'time_to_beat_average': game_data.get('time_to_beat_average', 0)
                        }
            except Exception:
                continue
        if not self.games_data:
            self.games_data = {
                'Это заглушка, просто создай игру': {'seconds': 0, 'image_url': '', 'time_to_beat_average': 0},
            }
        # Загружаем изображения
        for game_name, game_info in self.games_data.items():
            if game_info.get('image_url'):
                self.load_game_image(game_name, game_info['image_url'])
        self.update_grid()
    def update_grid(self):
        self.grid_widget.set_games(self.games_data, self.game_images)
    
    def update_game_time_in_grid(self, game_name, new_time):
        """Обновляет время для конкретной игры в сетке карточек"""
        # Обновляем данные
        if game_name in self.games_data:
            self.games_data[game_name]['seconds'] = new_time
        
        # Обновляем карточку
        self.grid_widget.update_game_time(game_name, new_time)
    def load_game_image(self, game_name, image_url):
        # Проверяем кэш
        if image_url in self.image_cache:
            self.game_images[game_name] = self.image_cache[image_url]
            self.update_grid()
            return
        
        # Используем размер 240x240 для больших квадратных изображений в карточках
        loader = ImageLoader(image_url, game_name, target_size=(240, 240))
        loader.image_loaded.connect(self.on_image_loaded)
        self.image_loaders[game_name] = loader
        loader.start()
    def on_image_loaded(self, game_name, pixmap):
        self.game_images[game_name] = pixmap
        self.update_grid()
    def get_selected_game(self):
        return self.grid_widget.get_selected_game(self.games_data)

    def add_game(self):
        dialog = AddGameDialog(self, is_editing=False)
        if dialog.exec_() == QDialog.Accepted:
            game_data = dialog.get_game_data()
            game_name = game_data['name']
            image_url = game_data['image_url']
            time_to_beat = game_data['time_to_beat_average']
            if game_name and game_name not in self.games_data:
                safe_game_name = "".join(c for c in game_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
                safe_game_name = safe_game_name.replace(' ', '_')
                fname = os.path.join(LOGS_DIR, f"timer_log_{safe_game_name}.json")
                game_data_json = {
                    'game_name': game_name,
                    'image_url': image_url,
                    'time_to_beat_average': time_to_beat,
                    'total_time_seconds': 0,
                    'total_time_str': '00:00:00',
                    'sessions': [],
                    'last_updated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                with open(fname, 'w', encoding='utf-8') as f:
                    json.dump(game_data_json, f, ensure_ascii=False, indent=2)
                self.load_games()

    def remove_game(self):
        import os
        selected_game = self.get_selected_game()
        if selected_game:
            reply = QMessageBox.question(self, 'Удаление игры',
                                         f'Вы уверены, что хотите удалить игру "{selected_game}"?\nВсе данные о времени будут удалены!',
                                         QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                safe_game_name = "".join(c for c in selected_game if c.isalnum() or c in (' ', '-', '_')).rstrip()
                safe_game_name = safe_game_name.replace(' ', '_')
                fname = os.path.join(LOGS_DIR, f"timer_log_{safe_game_name}.json")
                try:
                    os.remove(fname)
                except FileNotFoundError:
                    pass
                self.load_games()

    def edit_game(self, game_name):
        import os
        # Получаем текущие данные
        game_info = self.games_data.get(game_name, {})
        dialog = AddGameDialog(self, is_editing=True)
        dialog.game_name_input.setText(game_name)
        dialog.image_url_input.setText(game_info.get('image_url', ''))
        
        # Загружаем полные данные из файла для редактирования
        try:
            safe_game_name = "".join(c for c in game_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
            safe_game_name = safe_game_name.replace(' ', '_')
            fname = os.path.join(LOGS_DIR, f"timer_log_{safe_game_name}.json")
            
            if os.path.exists(fname):
                with open(fname, 'r', encoding='utf-8') as f:
                    full_data = json.load(f)
                    # Заполняем поле времени прохождения
                    time_to_beat = full_data.get('time_to_beat_average', 0)
                    dialog.time_to_beat_input.setValue(time_to_beat)
        except Exception as e:
            print(f"Ошибка при загрузке данных для редактирования: {e}")
        
        if dialog.exec_() == QDialog.Accepted:
            new_data = dialog.get_game_data()
            new_name = new_data['name']
            new_image_url = new_data['image_url']
            new_time_to_beat = new_data.get('time_to_beat_average', 0)
            
            if new_name:
                # Переименовать файл, если имя изменилось
                old_safe = "".join(c for c in game_name if c.isalnum() or c in (' ', '-', '_')).rstrip().replace(' ', '_')
                new_safe = "".join(c for c in new_name if c.isalnum() or c in (' ', '-', '_')).rstrip().replace(' ', '_')
                old_fname = os.path.join(LOGS_DIR, f"timer_log_{old_safe}.json")
                new_fname = os.path.join(LOGS_DIR, f"timer_log_{new_safe}.json")
                
                # Загружаем старые данные
                try:
                    with open(old_fname, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except Exception:
                    data = {}
                
                # Обновляем данные
                data['game_name'] = new_name
                data['image_url'] = new_image_url
                data['time_to_beat_average'] = new_time_to_beat
                
                # Сохраняем в новый файл
                with open(new_fname, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                
                # Удаляем старый файл, если имя изменилось
                if old_fname != new_fname:
                    try:
                        os.remove(old_fname)
                    except Exception:
                        pass
                
                self.load_games()

    def edit_selected_game(self):
        selected_game = self.get_selected_game()
        if not selected_game:
            QMessageBox.warning(self, 'Редактирование', 'Пожалуйста, выберите игру для редактирования!')
            return
        self.edit_game(selected_game)

    def load_gameleague_games(self):
        """Загружает игры с GameLeague API"""
        if not self.timer_app:
            QMessageBox.warning(self, 'Ошибка', 'Не удалось получить доступ к основному приложению')
            return
        
        # Получаем игры с API
        games, error = self.timer_app.get_gameleague_games()
        
        if error:
            # Проверяем, является ли ошибка связанной с отсутствием авторизации на GameLeague
            if "не авторизован на сайте GameLeague" in error or "не найден на сайте GameLeague" in error:
                QMessageBox.warning(self, 'Авторизация GameLeague', 
                                  f"{error}\n\nДля использования этой функции необходимо:\n"
                                  f"1. Зарегистрироваться на сайте GameLeague\n"
                                  f"2. Использовать авторизацию Gmail на сайте GameLeague")
            else:
                QMessageBox.warning(self, 'Ошибка загрузки', error)
            return
        
        if not games:
            QMessageBox.information(self, 'Нет игр', 'У вас нет активных игр на GameLeague')
            return
        
        # Добавляем игры в локальные данные
        added_count = 0
        for game in games:
            game_name = game['name']
            image_url = game['image_url']
            
            # Проверяем, не существует ли уже такая игра
            if game_name not in self.games_data:
                # Создаем безопасное имя файла
                safe_game_name = "".join(c for c in game_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
                safe_game_name = safe_game_name.replace(' ', '_')
                fname = os.path.join(LOGS_DIR, f"timer_log_{safe_game_name}.json")
                
                # Создаем данные игры
                game_data_json = {
                    'game_name': game_name,
                    'image_url': image_url,
                    'gameleague_id': game.get('game_id'),  # ID игры
                    'room_id': game.get('room_id'),  # ID комнаты (это то, что нужно для API)
                    'time_to_beat_average': game.get('time_to_beat_average', 0),
                    'total_time_seconds': 0,
                    'total_time_str': '00:00:00',
                    'sessions': [],
                    'last_updated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                
                # Сохраняем в файл
                with open(fname, 'w', encoding='utf-8') as f:
                    json.dump(game_data_json, f, ensure_ascii=False, indent=2)
                
                added_count += 1
        
        if added_count > 0:
            # Перезагружаем игры
            self.load_games()
            QMessageBox.information(self, 'Успех', f'Добавлено {added_count} новых игр с GameLeague!')
        else:
            QMessageBox.information(self, 'Информация', 'Все игры уже существуют в вашем списке')
    
    def apply_theme(self, theme):
        """Применяет тему к странице выбора игр"""
        if not theme:
            return
            
        self.setStyleSheet(f"""
QWidget {{
    background-color: {theme['bg_color']};
    color: {theme['text_color']};
}}
QScrollBar:vertical {{
    background: {theme['card_bg']};
    width: 12px;
    border-radius: 6px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {theme['accent_color']};
    border-radius: 6px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background: {theme['accent_color']};
    opacity: 0.8;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    border: none;
    background: none;
}}
QPushButton {{
    border-radius: 12px;
    padding: 10px 24px;
    font-size: 16px;
    font-weight: 500;
    background: {theme['button_bg']};
    color: {theme['text_color']};
    border: none;
}}
QPushButton:hover {{
    background: {theme['button_hover']};
}}
QLineEdit {{
    background: {theme['card_bg']};
    color: {theme['text_color']};
    border-radius: 10px;
    padding: 8px 12px;
    border: 1px solid {theme['border_color']};
    font-size: 14px;
}}
""")
        
        # Обновляем карточки игр
        if hasattr(self, 'grid_widget') and self.grid_widget.cards:
            for card in self.grid_widget.cards:
                card.apply_theme(theme)

class TimerApp(QWidget):
    hotkey_signal = pyqtSignal()

    def __init__(self):
        print("DEBUG: TimerApp.__init__ стартует")
        super().__init__()
        self.setWindowTitle('GameLeague Timer')
        self.setFixedSize(700, 600)
        self.setWindowIcon(QIcon(LOGO_FILE))
        
        # Инициализируем версию в самом начале
        self.current_version = get_current_version()
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_time)
        self.seconds = 0
        self.running = False
        self.hotkey = None
        self.hotkey_display = None
        self.listening_hotkey = False
        self.finish_timer = None
        self.recorded_keys = []
        
        # Новая система хоткеев по примеру
        self.hotkey_listener = HotkeyListener()
        print("DEBUG: HotkeyListener создан в TimerApp")
        self.hotkey_listener.main_window = self  # Передаем ссылку на главное окно
        self.hotkey_listener.start_listening()
        print("DEBUG: hotkey_listener.start_listening вызван в TimerApp")
        self.user_email = None
        self.oauth_token = None
        self.ws_port = 8765
        self.ws_server = None
        self.ws_thread = None
        self.current_game = None
        
        # Переменные для обратного отсчета
        self.countdown_mode = False
        self.countdown_seconds = 0
        self.original_seconds = 0  # Сохраняем оригинальное время для записи
        self.real_time_during_countdown = 0  # Реальное время, прошедшее во время обратного отсчета
        
        # Переменные для уведомления о неактивности
        self.idle_notification_timer = QTimer()
        self.idle_notification_timer.timeout.connect(self.show_idle_notification)
        self.idle_countdown_timer = QTimer()
        self.idle_countdown_timer.timeout.connect(self.update_idle_countdown)
        self.idle_seconds_remaining = 300  # 5 минут
        self.idle_notification_label = None
        
        # Инициализируем тему (должно быть до init_ui)
        self.current_theme = 'light'  # 'light' или 'neon'
        self.themes = {
            'light': {
                'bg_color': '#181f2a',
                'card_bg': '#232b3b',
                'text_color': '#e6e6e6',
                'accent_color': '#7b5cff',
                'accent_gradient': 'qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7b5cff, stop:1 #4e44ce)',
                'border_color': '#2e3950',
                'button_bg': '#232b3b',
                'button_hover': '#2e3950',
                'timer_bg': '#232b3b',
                'timer_color': '#ffffff',
                'reset_color': '#F83F42'
            },
            'neon': {
                'bg_color': '#000000',
                'card_bg': '#0a0a0a',
                'text_color': '#ff0000',
                'accent_color': '#ff0000',
                'accent_gradient': 'qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff0000, stop:1 #cc0000)',
                'border_color': '#ff0000',
                'button_bg': '#0a0a0a',
                'button_hover': '#1a1a1a',
                'timer_bg': '#0a0a0a',
                'timer_color': '#ff0000',
                'reset_color': '#ff0000'
            }
        }
        
        self.init_ui()
        self.load_settings()
        self.hotkey_signal.connect(self.toggle_timer)
        self.last_time_str = '00:00:00'
        self.last_time_lock = threading.Lock()
        self.timer_start_dt = None
        self.timer_stop_dt = None
        
        # Инициализируем окно таймера поверх всех приложений
        self.overlay_timer = OverlayTimerWindow()
        self.overlay_timer_visible = False
        
        # Инициализируем менеджер обновлений
        self.update_manager = UpdateManager(self, self.current_version)
        
        # Автоматическая проверка обновлений при запуске
        self.check_updates_on_startup()

    def init_ui(self):
        self.stacked = QStackedWidget(self)
        self.page1 = QWidget()
        self.page2 = GameSelectionPage(timer_app=self)
        self.page3 = QWidget()
        self.init_page1()
        self.page2.back_btn.clicked.connect(lambda: self.show_page(0))
        self.page2.next_btn.clicked.connect(self.start_game)
        self.init_page3()
        self.stacked.addWidget(self.page1)
        self.stacked.addWidget(self.page2)
        self.stacked.addWidget(self.page3)
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.stacked)
        self.setLayout(main_layout)
        
        # Создаем кнопку переключения темы (после создания layout)
        self.theme_btn = QPushButton(self)
        self.theme_btn.setFixedSize(40, 40)
        self.theme_btn.setIconSize(QSize(24, 24))
        self.theme_btn.setStyleSheet('''
            QPushButton {
                background-color: rgba(123, 92, 255, 0.8);
                border: none;
                border-radius: 20px;
            }
            QPushButton:hover {
                background-color: rgba(123, 92, 255, 1.0);
            }
        ''')
        self.theme_btn.clicked.connect(self.toggle_theme)
        
        # Позиционируем кнопку в правом верхнем углу
        self.theme_btn.move(self.width() - 50, 10)
        self.theme_btn.raise_()  # Поднимаем кнопку поверх других элементов
        
        # Обработчик изменения размера окна для перепозиционирования кнопки темы
        self.resizeEvent = self.on_resize
        
        # Применяем тему после создания всех элементов
        self.apply_theme()
        
        self.show_page(0)

    def show_page(self, idx):
        self.stacked.setCurrentIndex(idx)
        if idx == 2 and self.current_game:
            self.game_label.setText(self.current_game)
            self.update_time_display()

    def init_page1(self):
        layout = QVBoxLayout()
        self.google_btn = QPushButton('Войти через Google', self)
        self.google_btn.clicked.connect(self.google_login)
        self.email_label = QLabel('Не авторизовано', self)
        self.email_label.setAlignment(Qt.AlignCenter)
        self.ws_settings_btn = QPushButton('WebSocket настройки', self)
        self.ws_settings_btn.clicked.connect(self.open_ws_settings)
        self.ws_status_label = QLabel('WebSocket: выкл.', self)
        self.ws_status_label.setAlignment(Qt.AlignCenter)
        self.ws_link_label = QLineEdit(self)
        self.ws_link_label.setReadOnly(True)
        self.ws_link_label.setText(f'http://localhost:{self.ws_port}/')
        self.ws_link_label.hide()
        self.copy_link_btn = QPushButton('Копировать ссылку', self)
        self.copy_link_btn.clicked.connect(self.copy_ws_link)
        self.copy_link_btn.hide()
        self.ws_toggle_btn = QPushButton('Запустить сервер', self)
        self.ws_toggle_btn.clicked.connect(self.toggle_ws_server)
        self.html_timer_settings_btn = QPushButton('Настройки HTML таймера', self)
        self.html_timer_settings_btn.clicked.connect(self.open_html_timer_settings)
        

        
        # Показываем текущую рабочую директорию
        self.work_dir_label = QLabel(f'Рабочая папка: {WORK_DIR}', self)
        self.work_dir_label.setAlignment(Qt.AlignCenter)
        self.work_dir_label.setStyleSheet('color: #888888; font-size: 11px; margin: 5px;')
        self.work_dir_label.setWordWrap(True)
        
        self.next_btn = QPushButton('Далее →', self)
        self.next_btn.clicked.connect(lambda: self.show_page(1))
        layout.addWidget(self.google_btn)
        layout.addWidget(self.email_label)
        layout.addWidget(self.ws_settings_btn)
        layout.addWidget(self.ws_status_label)
        layout.addWidget(self.ws_link_label)
        layout.addWidget(self.copy_link_btn)
        layout.addWidget(self.ws_toggle_btn)
        layout.addWidget(self.html_timer_settings_btn)
        layout.addWidget(self.work_dir_label)
        layout.addWidget(self.next_btn)
        
        # Прижимаем футер к низу
        layout.addStretch()
        
        # Добавляем футер с версией и автором
        footer_layout = QHBoxLayout()
        self.version_label = QLabel(f'Версия: {self.current_version}', self)
        self.version_label.setStyleSheet('color: #888888; font-size: 12px;')
        self.author_label = QLabel('by DeadKDV', self)
        self.author_label.setStyleSheet('color: #888888; font-size: 12px;')
        
        footer_layout.addWidget(self.version_label)
        footer_layout.addStretch()
        footer_layout.addWidget(self.author_label)
        layout.addLayout(footer_layout)
        
        self.page1.setLayout(layout)

    def init_page3(self):
        layout = QVBoxLayout()
        
        # Добавляем метку с названием текущей игры
        self.game_label = QLabel('', self)
        self.game_label.setAlignment(Qt.AlignCenter)
        self.game_label.setStyleSheet('font-size: 24px; color: #7b5cff; margin-bottom: 10px;')
        layout.addWidget(self.game_label)
        
        self.time_label = QLabel('00:00:00', self)
        self.time_label.setObjectName('timerLabel')
        self.time_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.time_label)
        
        # Первая строка кнопок управления таймером
        btn_layout1 = QHBoxLayout()
        btn_layout1.setSpacing(12)
        
        self.start_btn = QPushButton('Старт')
        self.start_btn.setObjectName('startBtn')
        self.start_btn.setMinimumWidth(120)
        self.start_btn.clicked.connect(self.toggle_timer)
        btn_layout1.addWidget(self.start_btn)
        
        self.reset_btn = QPushButton('Сброс')
        self.reset_btn.setObjectName('resetBtn')
        self.reset_btn.setMinimumWidth(120)
        self.reset_btn.clicked.connect(self.reset_timer)
        btn_layout1.addWidget(self.reset_btn)
        
        # Добавляем кнопку редактирования времени
        self.edit_time_btn = QPushButton('Редактировать время')
        self.edit_time_btn.setMinimumWidth(140)
        self.edit_time_btn.clicked.connect(self.edit_time)
        btn_layout1.addWidget(self.edit_time_btn)
        
        layout.addLayout(btn_layout1)
        
        # Вторая строка кнопок - режим обратного отсчета
        btn_layout2 = QHBoxLayout()
        btn_layout2.setSpacing(12)
        
        self.countdown_btn = QPushButton('Обратный отсчет')
        self.countdown_btn.setMinimumWidth(140)
        self.countdown_btn.clicked.connect(self.toggle_countdown_mode)
        btn_layout2.addWidget(self.countdown_btn)
        
        # Добавляем растягивающийся элемент для центрирования
        btn_layout2.addStretch()
        layout.addLayout(btn_layout2)
        
        # Кнопка для показа таймера поверх всех окон
        self.overlay_btn = QPushButton('Показать поверх всех окон')
        self.overlay_btn.setStyleSheet('''
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7b5cff, stop:1 #4e44ce);
                color: #fff;
                border-radius: 12px;
                padding: 10px 24px;
                font-size: 16px;
                font-weight: 500;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8b6cff, stop:1 #5e54de);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6b4cff, stop:1 #3e34be);
            }
        ''')
        self.overlay_btn.clicked.connect(self.toggle_overlay_timer)
        layout.addWidget(self.overlay_btn)
        
        # Кнопка отправки результата
        self.send_result_btn = QPushButton('Отправить результат')
        self.send_result_btn.setStyleSheet('''
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #28a745, stop:1 #20c997);
                color: #fff;
                border-radius: 12px;
                padding: 10px 24px;
                font-size: 16px;
                font-weight: 500;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #38b745, stop:1 #30d997);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #18a745, stop:1 #10c997);
            }
        ''')
        self.send_result_btn.clicked.connect(self.send_final_result)
        layout.addWidget(self.send_result_btn)
        
        # Вторая строка - настройки хоткея
        hotkey_layout = QHBoxLayout()
        hotkey_layout.setSpacing(12)
        
        self.hotkey_input = QLineEdit(self)
        self.hotkey_input.setReadOnly(True)
        self.hotkey_input.setPlaceholderText('Комбинация не выбрана')
        self.hotkey_input.setMinimumWidth(200)
        hotkey_layout.addWidget(self.hotkey_input)
        
        self.set_hotkey_btn = QPushButton('Установить хоткей')
        self.set_hotkey_btn.setObjectName('hotkeyBtn')
        self.set_hotkey_btn.setMinimumWidth(150)
        self.set_hotkey_btn.clicked.connect(self.start_hotkey_listen)
        hotkey_layout.addWidget(self.set_hotkey_btn)
        
        # Добавляем кнопку отмены (скрыта по умолчанию)
        self.cancel_hotkey_btn = QPushButton('Отмена')
        self.cancel_hotkey_btn.setObjectName('hotkeyBtn')
        self.cancel_hotkey_btn.setMinimumWidth(100)
        self.cancel_hotkey_btn.clicked.connect(self.cancel_hotkey_listen)
        self.cancel_hotkey_btn.hide()  # Скрываем по умолчанию
        hotkey_layout.addWidget(self.cancel_hotkey_btn)
        
        # Добавляем растягивающийся элемент для центрирования
        hotkey_layout.addStretch()
        layout.addLayout(hotkey_layout)
        
        self.back_to_games_btn = QPushButton('← К выбору игры')
        self.back_to_games_btn.clicked.connect(self.back_to_games)
        layout.addWidget(self.back_to_games_btn)
        
        # Добавляем метку для уведомления о неактивности
        self.idle_notification_label = QLabel('', self)
        self.idle_notification_label.setAlignment(Qt.AlignCenter)
        self.idle_notification_label.setStyleSheet('''
            QLabel {
                color: #ff6b6b;
                font-size: 14px;
                font-weight: bold;
                padding: 8px;
                border-radius: 6px;
                background-color: rgba(255, 107, 107, 0.1);
                border: 1px solid rgba(255, 107, 107, 0.3);
            }
        ''')
        self.idle_notification_label.hide()
        layout.addWidget(self.idle_notification_label)
        
        # Прижимаем футер к низу
        layout.addStretch()
        
        # Добавляем футер с версией и автором
        footer_layout = QHBoxLayout()
        version_footer = QLabel(f'Версия: {self.current_version}', self)
        version_footer.setStyleSheet('color: #888888; font-size: 12px;')
        author_footer = QLabel('by DeadKDV', self)
        author_footer.setStyleSheet('color: #888888; font-size: 12px;')
        
        footer_layout.addWidget(version_footer)
        footer_layout.addStretch()
        footer_layout.addWidget(author_footer)
        layout.addLayout(footer_layout)
        
        self.page3.setLayout(layout)

    def copy_ws_link(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.ws_link_label.text())
        QMessageBox.information(self, 'Ссылка скопирована', 'Ссылка скопирована в буфер обмена!')

    def toggle_timer(self):
        print(f"HOTKEY: ⭐ toggle_timer НАЧАЛСЯ! running = {self.running}")
        try:
            if self.running:
                print(f"HOTKEY: Останавливаем таймер")
                self.timer.stop()
                self.start_btn.setText('Старт')
                self.running = False
                self.timer_stop_dt = datetime.datetime.now()
                if self.current_game:
                    self.update_game_log_file()
                self.save_timer_log()
                print(f"HOTKEY: Таймер остановлен успешно")
            else:
                print(f"HOTKEY: Запускаем таймер")
                # Останавливаем таймер уведомления при запуске основного таймера
                self.stop_idle_notification_timer()
                
                self.timer.start(1000)
                self.start_btn.setText('Пауза')
                self.running = True
                self.timer_start_dt = datetime.datetime.now()
                print(f"HOTKEY: Таймер запущен успешно")
                
            print(f"HOTKEY: ⭐ toggle_timer ЗАВЕРШИЛСЯ! running = {self.running}")
        except Exception as e:
            print(f"HOTKEY: ❌ ОШИБКА в toggle_timer: {e}")
            import traceback
            traceback.print_exc()

    def update_time(self):
        if self.countdown_mode:
            # Режим обратного отсчета
            if self.seconds > 0:
                self.seconds -= 1
                # Увеличиваем реальное время, прошедшее во время обратного отсчета
                self.real_time_during_countdown += 1
            else:
                # Время истекло
                self.timer.stop()
                self.running = False
                self.start_btn.setText('Старт')
                QMessageBox.information(self, 'Время истекло!', 
                                      f'Время прохождения игры "{self.current_game}" истекло!')
        else:
            # Обычный режим
            self.seconds += 1
        
        self.update_time_display()
        if self.current_game:
            self.update_game_log_file()
        # Отправляем новое значение всем WebSocket-клиентам
        if hasattr(self, 'ws_clients') and self.ws_clients:
            
            for ws in list(self.ws_clients):
                try:
                    if not ws.closed:
                        coro = ws.send_str(self.last_time_str)
                        if hasattr(self, '_ws_loop'):
                            asyncio.run_coroutine_threadsafe(coro, self._ws_loop)
                    else:
                        try:
                            self.ws_clients.remove(ws)
                        except:
                            pass
                except Exception as e:
                    try:
                        self.ws_clients.remove(ws)
                    except:
                        pass

    def reset_timer(self):
        reply = QMessageBox.question(self, 'Сброс таймера', 
                                   'Вы уверены, что хотите сбросить таймер?\nЭто действие нельзя отменить.',
                                   QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.timer.stop()
            self.seconds = 0
            self.original_seconds = 0
            self.real_time_during_countdown = 0
            self.countdown_mode = False
            self.countdown_btn.setText('Обратный отсчет')
            self.countdown_btn.setStyleSheet('')
            if self.current_game:
                self.update_game_log_file()
            self.update_time_display()
            self.start_btn.setText('Старт')
            self.running = False
    
    def toggle_countdown_mode(self):
        """Переключает режим обратного отсчета"""
        if self.countdown_mode:
            # Выключаем режим обратного отсчета
            self.countdown_mode = False
            self.countdown_btn.setText('Обратный отсчет')
            self.countdown_btn.setStyleSheet('')
            
            # Возвращаем обычный режим с учетом реального времени, прошедшего во время обратного отсчета
            total_real_time = self.original_seconds + self.real_time_during_countdown
            self.seconds = total_real_time
            
            # Сбрасываем счетчик реального времени
            self.real_time_during_countdown = 0
            
            self.update_time_display()
            QMessageBox.information(self, 'Режим изменен', 
                                  f'Переключено на обычный режим. Общее время: {total_real_time // 3600:02}:{(total_real_time % 3600) // 60:02}:{total_real_time % 60:02}')
        else:
            # Включаем режим обратного отсчета
            if not self.current_game:
                QMessageBox.warning(self, 'Ошибка', 'Сначала выберите игру!')
                return
            
            # Получаем время прохождения для текущей игры
            time_to_beat = self.get_game_time_to_beat()
            if not time_to_beat or time_to_beat <= 0:
                QMessageBox.warning(self, 'Ошибка', 'Для этой игры не указано среднее время прохождения!')
                return
            
            # Сохраняем текущее время
            self.original_seconds = self.seconds
            # Сбрасываем счетчик реального времени
            self.real_time_during_countdown = 0
            # Устанавливаем время для обратного отсчета (в секундах)
            # Вычитаем уже накопленное время из среднего времени прохождения
            self.countdown_seconds = (time_to_beat * 60) - self.seconds
            # Если время уже превысило среднее, устанавливаем 0
            if self.countdown_seconds < 0:
                self.countdown_seconds = 0
            self.seconds = self.countdown_seconds
            self.countdown_mode = True
            
            self.countdown_btn.setText('Обычный режим')
            self.countdown_btn.setStyleSheet('''
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff6b6b, stop:1 #ee5a52);
                    color: white;
                    border-radius: 8px;
                    padding: 8px 16px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff7b7b, stop:1 #ff6a62);
                }
            ''')
            
            self.update_time_display()
            
            # Форматируем оставшееся время для отображения
            remaining_minutes = self.countdown_seconds // 60
            remaining_seconds = self.countdown_seconds % 60
            
            if self.countdown_seconds > 0:
                QMessageBox.information(self, 'Обратный отсчет', 
                                      f'Установлен обратный отсчет: {remaining_minutes:02}:{remaining_seconds:02}\n'
                                      f'(Среднее время: {time_to_beat} мин, уже сыграно: {self.original_seconds // 60:02}:{self.original_seconds % 60:02})')
            else:
                QMessageBox.information(self, 'Обратный отсчет', 
                                      f'Время уже превысило среднее время прохождения!\n'
                                      f'(Среднее время: {time_to_beat} мин, уже сыграно: {self.original_seconds // 60:02}:{self.original_seconds % 60:02})')
    
    def get_game_time_to_beat(self):
        """Получает время прохождения для текущей игры"""
        if not self.current_game:
            return None
        
        try:
            # Создаем безопасное имя файла для игры
            safe_game_name = "".join(c for c in self.current_game if c.isalnum() or c in (' ', '-', '_')).rstrip()
            safe_game_name = safe_game_name.replace(' ', '_')
            fname = os.path.join(LOGS_DIR, f"timer_log_{safe_game_name}.json")
            
            if os.path.exists(fname):
                with open(fname, 'r', encoding='utf-8') as f:
                    game_data = json.load(f)
                    return game_data.get('time_to_beat_average', 0)
        except Exception as e:
            print(f"Ошибка при получении времени прохождения: {e}")
        
        return None

    def start_hotkey_listen(self):
        if self.listening_hotkey:
            return
        self.listening_hotkey = True
        self.hotkey_input.setText('Нажмите клавиши...')
        
        # Меняем кнопки
        self.set_hotkey_btn.setText('Установить')
        self.set_hotkey_btn.clicked.disconnect()
        self.set_hotkey_btn.clicked.connect(self.manual_finish_hotkey)
        self.cancel_hotkey_btn.show()  # Показываем кнопку отмены
        
        self.recorded_keys = []
        self.finish_timer = None
        
        # Начинаем запись с помощью keyboard
        try:
            keyboard.unhook_all()
            keyboard.hook(self.on_key_event)
        except Exception as e:
            QMessageBox.warning(self, 'Ошибка', f'Не удалось начать запись хоткея: {e}')
            self.cancel_hotkey_listen()

    def on_key_event(self, event):
        if not self.listening_hotkey:
            return
            
        # Переводим названия клавиш для лучшего отображения
        key_mappings = {
            'ctrl': 'Ctrl', 'alt': 'Alt', 'shift': 'Shift',
            'space': 'Пробел', 'enter': 'Enter', 'tab': 'Tab',
            'esc': 'Esc', 'backspace': 'Backspace', 'delete': 'Delete',
            'home': 'Home', 'end': 'End', 'page up': 'Page Up', 'page down': 'Page Down',
            'up': '↑', 'down': '↓', 'left': '←', 'right': '→',
            'f1': 'F1', 'f2': 'F2', 'f3': 'F3', 'f4': 'F4', 'f5': 'F5', 'f6': 'F6',
            'f7': 'F7', 'f8': 'F8', 'f9': 'F9', 'f10': 'F10', 'f11': 'F11', 'f12': 'F12',
            'caps lock': 'Caps Lock', 'num lock': 'Num Lock', 'scroll lock': 'Scroll Lock',
            'insert': 'Insert', 'pause': 'Pause', 'print screen': 'Print Screen'
        }
        
        key_name = event.name.lower()
        display_name = key_mappings.get(key_name, event.name)
        
        # Русские символы - сохраняем как есть
        if len(event.name) == 1 and ord(event.name) >= 1040:  # Русские символы
            display_name = event.name
        
        if event.event_type == keyboard.KEY_DOWN:
            if display_name not in self.recorded_keys:
                self.recorded_keys.append(display_name)
                
                # Обновляем отображение записанных клавиш
                current_text = '+'.join(self.recorded_keys)
                self.hotkey_input.setText(current_text)
                print(f"HOTKEY: Записана клавиша '{display_name}', текущий набор: {current_text}")
            
        # Убираем автоматическое завершение - теперь только ручное

    def update_hotkey_display(self):
        if self.recorded_keys:
            hotkey_str = '+'.join(self.recorded_keys)
            self.hotkey_input.setText(hotkey_str)

    def manual_finish_hotkey(self):
        """Устанавливает хоткей по нажатию кнопки пользователем"""
        if not self.listening_hotkey:
            return
            
        if not self.recorded_keys:
            QMessageBox.warning(self, 'Внимание', 'Сначала нажмите клавиши для хоткея!')
            return
        
        # Останавливаем запись
        try:
            keyboard.unhook_all()
        except:
            pass
            
        # Создаем строку хоткея для keyboard библиотеки
        keyboard_hotkey = '+'.join([key.lower() for key in self.recorded_keys])
        display_hotkey = '+'.join(self.recorded_keys)
        
        # Обрабатываем специальные символы для keyboard библиотеки
        keyboard_hotkey = keyboard_hotkey.replace('пробел', 'space')
        keyboard_hotkey = keyboard_hotkey.replace('←', 'left').replace('→', 'right')
        keyboard_hotkey = keyboard_hotkey.replace('↑', 'up').replace('↓', 'down')
        
        print(f"HOTKEY: Устанавливаем хоткей. recorded_keys={self.recorded_keys}")
        print(f"HOTKEY: keyboard_hotkey='{keyboard_hotkey}', display_hotkey='{display_hotkey}'")
        
        try:
            self.set_hotkey(keyboard_hotkey, display_hotkey)
        except Exception as e:
            QMessageBox.warning(self, 'Ошибка', f'Не удалось установить хоткей: {e}')
            self.cancel_hotkey_listen()



    def finish_hotkey_recording(self):
        if not self.listening_hotkey or not self.recorded_keys:
            return
        
        # Останавливаем таймер
        if hasattr(self, 'finish_timer') and self.finish_timer:
            self.finish_timer.stop()
            self.finish_timer = None
            
        # Создаем строку хоткея для keyboard библиотеки
        keyboard_hotkey = '+'.join([key.lower() for key in self.recorded_keys])
        
        # Обрабатываем специальные символы для keyboard библиотеки
        keyboard_hotkey = keyboard_hotkey.replace('пробел', 'space')
        keyboard_hotkey = keyboard_hotkey.replace('←', 'left').replace('→', 'right')
        keyboard_hotkey = keyboard_hotkey.replace('↑', 'up').replace('↓', 'down')
        
        try:
            keyboard.unhook_all()
            self.set_hotkey(keyboard_hotkey, '+'.join(self.recorded_keys))
            # После успешной установки cancel_hotkey_listen вызывается внутри set_hotkey
        except Exception as e:
            QMessageBox.warning(self, 'Ошибка', f'Не удалось установить хоткей: {e}')
            self.cancel_hotkey_listen()

    def cancel_hotkey_listen(self):
        self.listening_hotkey = False
        
        # Останавливаем таймер если есть
        if hasattr(self, 'finish_timer') and self.finish_timer:
            self.finish_timer.stop()
            self.finish_timer = None
            
        try:
            keyboard.unhook_all()
        except:
            pass
            
        # Восстанавливаем исходное состояние
        self.hotkey_input.setText(self.hotkey_display if hasattr(self, 'hotkey_display') and self.hotkey_display else 'Комбинация не выбрана')
        self.set_hotkey_btn.setText('Установить хоткей')
        self.set_hotkey_btn.clicked.disconnect()
        self.set_hotkey_btn.clicked.connect(self.start_hotkey_listen)
        self.cancel_hotkey_btn.hide()  # Скрываем кнопку отмены
        self.recorded_keys = []

    def keyPressEvent(self, event):
        # Больше не используем для записи хоткеев
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        # Больше не используем для записи хоткеев
        super().keyReleaseEvent(event)

    def set_hotkey(self, hotkey, display_hotkey=None):
        print(f"DEBUG: set_hotkey({hotkey}, {display_hotkey}) вызван")
        try:
            self.hotkey = hotkey
            self.hotkey_display = display_hotkey if display_hotkey else hotkey
            self.hotkey_input.setText(self.hotkey_display)
            self.save_settings()
            self._ignore_first_hotkey = True
            def hotkey_handler():
                print(f"DEBUG: hotkey_handler вызван для {self.hotkey_display}")
                if self._ignore_first_hotkey:
                    self._ignore_first_hotkey = False
                    print("HOTKEY: Первое нажатие игнорируется")
                    return
                print("HOTKEY: Отправляем сигнал toggle_timer")
                self.hotkey_signal.emit()
            # Останавливаем старый слушатель
            self.hotkey_listener.stop_listening()
            # Регистрируем новый хоткей
            self.hotkey_listener.add_hotkey(hotkey, hotkey_handler)
            # Запускаем слушатель заново
            self.hotkey_listener.start_listening()
            print(f"DEBUG: add_hotkey вызван из set_hotkey для {hotkey}")
            print(f"HOTKEY: Зарегистрирован хоткей '{hotkey}' (отображение: '{self.hotkey_display}')")
            QMessageBox.information(self, 'Успех', f'Хоткей "{self.hotkey_display}" установлен!')
            if self.listening_hotkey:
                self.cancel_hotkey_listen()
        except Exception as e:
            self.hotkey_input.setText('Комбинация не выбрана')
            QMessageBox.warning(self, 'Ошибка', f'Не удалось установить хоткей: {e}')
            if self.listening_hotkey:
                self.cancel_hotkey_listen()

    def google_login(self):
        SCOPES = ['openid', 'https://www.googleapis.com/auth/userinfo.email']
        try:
            # Загружаем client_secret из зашифрованного файла
            client_secret = None
            if encrypted_config:
                client_secret = encrypted_config.load_config('client_secret')
            
            # Если не удалось загрузить из зашифрованного файла, проверяем заглушку
            if client_secret is None:
                # Проверяем, не является ли это заглушкой
                script_client_secret = os.path.join(os.path.dirname(__file__), 'client_secret.json')
                if os.path.exists(script_client_secret):
                    with open(script_client_secret, 'r', encoding='utf-8') as f:
                        test_data = json.load(f)
                        if test_data.get('installed', {}).get('client_id', '').startswith('your_client_id'):
                            raise Exception('client_secret.json содержит тестовые данные. Нужны реальные OAuth данные.')
                    flow = InstalledAppFlow.from_client_secrets_file(script_client_secret, SCOPES)
                else:
                    raise Exception('Файл client_secret.json не найден.')
            else:
                # Проверяем, не является ли это заглушкой
                if client_secret.get('installed', {}).get('client_id', '').startswith('your_client_id'):
                    raise Exception('В зашифрованной конфигурации содержатся тестовые OAuth данные. Обновите конфигурацию с реальными данными.')
                
                # Создаем временный файл с client_secret
                import tempfile
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp_file:
                    json.dump(client_secret, tmp_file, ensure_ascii=False, indent=2)
                    temp_file_path = tmp_file.name
                
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(temp_file_path, SCOPES)
                finally:
                    # Удаляем временный файл
                    try:
                        os.unlink(temp_file_path)
                    except:
                        pass
            creds = flow.run_local_server(port=0)
            # Получаем e-mail пользователя (но не показываем)
            resp = requests.get('https://www.googleapis.com/oauth2/v2/userinfo',
                                headers={'Authorization': f'Bearer {creds.token}'})
            if resp.status_code == 200:
                user_info = resp.json()
                self.user_email = user_info.get('email')  # Сохраняем e-mail
                self.oauth_token = creds.token
                self.email_label.setText('Авторизация успешна')
                self.save_settings()
                QMessageBox.information(self, 'Google', 'Авторизация успешна!')
            else:
                self.email_label.setText('Авторизация не выполнена')
                QMessageBox.warning(self, 'Google', 'Не удалось получить e-mail пользователя!')
        except Exception as e:
            self.email_label.setText('Авторизация не выполнена')
            QMessageBox.critical(self, 'Google', f'Ошибка авторизации: {e}')

    def toggle_ws_server(self):
        if getattr(self, 'ws_server_running', False):
            self.stop_ws_server()
        else:
            self.start_ws_server()

    def start_ws_server(self):
        if getattr(self, 'ws_server_running', False):
            return
        self.ws_status_label.setText(f'WebSocket: порт {self.ws_port}')
        self.ws_thread = threading.Thread(target=self.run_ws_http_server, daemon=True)
        self.ws_thread.start()
        self.ws_server_running = True
        self.ws_toggle_btn.setText('Остановить сервер')
        self.ws_link_label.setText(f'http://localhost:{self.ws_port}/')
        self.ws_link_label.show()
        self.copy_link_btn.show()

    def stop_ws_server(self):
        if not getattr(self, 'ws_server_running', False):
            return
        # Корректно завершить сервер (грубое завершение через _ws_loop)
        try:
            if hasattr(self, '_ws_loop'):
                self._ws_loop.call_soon_threadsafe(self._ws_loop.stop)
        except Exception:
            pass
        self.ws_status_label.setText('WebSocket: выкл.')
        self.ws_toggle_btn.setText('Запустить сервер')
        self.ws_link_label.hide()
        self.copy_link_btn.hide()
        self.ws_server_running = False

    def run_ws_http_server(self):
        try:
            asyncio.set_event_loop(asyncio.new_event_loop())
            loop = asyncio.get_event_loop()
            app = web.Application()
            app.router.add_get('/', self.handle_html)
            app.router.add_get('/ws', self.handle_ws)
            self.ws_clients = set()
            self._ws_loop = loop
            runner = web.AppRunner(app)
            loop.run_until_complete(runner.setup())
            site = web.TCPSite(runner, '0.0.0.0', self.ws_port)
            loop.run_until_complete(site.start())
            print(f'HTTP/WebSocket сервер запущен на порту {self.ws_port}')
            loop.create_task(self.ws_broadcast_loop())
            loop.run_forever()
        except Exception as e:
            print(f'Ошибка запуска HTTP/WebSocket сервера: {e}')

    async def handle_html(self, request):
        # Сначала пытаемся загрузить live HTML файл
        live_html_path = os.path.join(WORK_DIR, 'timer_live.html')
        
        if os.path.exists(live_html_path):
            try:
                with open(live_html_path, 'r', encoding='utf-8') as f:
                    html = f.read()
                print("DEBUG: Используется live HTML файл")
                
                # Добавляем заголовки для предотвращения кэширования
                headers = {
                    'Cache-Control': 'no-cache, no-store, must-revalidate',
                    'Pragma': 'no-cache',
                    'Expires': '0'
                }
                return web.Response(text=html, content_type='text/html', headers=headers)
            except Exception as e:
                pass
        
        # Если live HTML нет - генерируем на лету
        settings = self.load_html_timer_settings()

        html = self.generate_html_with_settings(settings)
        
        # Сохраняем сгенерированный HTML как live версию
        try:
            with open(live_html_path, 'w', encoding='utf-8') as f:
                f.write(html)
        except Exception as e:
            pass
        
        # Добавляем заголовки для предотвращения кэширования
        headers = {
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0'
        }
        return web.Response(text=html, content_type='text/html', headers=headers)

    async def handle_ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.ws_clients.add(ws)

        try:
            async for _ in ws:
                pass
        finally:
            self.ws_clients.remove(ws)

        return ws

    async def ws_broadcast_loop(self):
        while True:
            await asyncio.sleep(1)
            with self.last_time_lock:
                time_str = self.last_time_str
            
            # Формируем JSON с временем и названием игры
            current_game = getattr(self, 'current_game', '')
            # Загружаем настройки HTML таймера чтобы знать, показывать ли название игры
            html_settings = self.load_html_timer_settings()
            show_game_name = html_settings.get('show_game_name', False)
            

            data = {
                'time': time_str,
                'game_name': current_game if show_game_name else '',
                'show_game_name': show_game_name
            }
            msg = json.dumps(data, ensure_ascii=False)
            
            for ws in list(self.ws_clients):
                if not ws.closed:
                    try:
                        await ws.send_str(msg)
                    except:
                        try:
                            self.ws_clients.remove(ws)
                        except:
                            pass
                else:
                    try:
                        self.ws_clients.remove(ws)
                    except:
                        pass

    def save_settings(self):
        data = {
            'hotkey': self.hotkey, 
            'hotkey_display': getattr(self, 'hotkey_display', self.hotkey),
            'email': self.user_email, 
            'ws_port': self.ws_port
        }
        # Сохраняем в зашифрованном файле
        if encrypted_config:
            encrypted_config.save_config(hotkey_settings=data)
        
        # Также сохраняем в обычном файле для совместимости
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f)
    def load_settings(self):
        # Сначала пытаемся загрузить из зашифрованного файла
        data = None
        if encrypted_config:
            data = encrypted_config.load_config('hotkey_settings')
        
        # Если не удалось, загружаем из обычного файла
        if data is None and os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        
        if data:
                self.hotkey = data.get('hotkey')
                self.hotkey_display = data.get('hotkey_display', self.hotkey)
                self.user_email = data.get('email')
                self.ws_port = data.get('ws_port', 8765)
                if hasattr(self, 'hotkey_input'):
                    if self.hotkey:
                        self.hotkey_input.setText(self.hotkey_display or self.hotkey)
                        try:
                            # Используем новый HotkeyListener
                            def hotkey_callback():
                                print(f"HOTKEY: Загруженный хоткей '{self.hotkey_display}' нажат!")
                                self.hotkey_signal.emit()
                            self.hotkey_listener.add_hotkey(self.hotkey, hotkey_callback)
                        except Exception:
                            self.hotkey_input.setText('Комбинация не выбрана')
                    else:
                        self.hotkey_input.setText('Комбинация не выбрана')
                if hasattr(self, 'email_label'):
                    if self.user_email:
                        self.email_label.setText('Авторизация успешна')
                    else:
                        self.email_label.setText('Не авторизовано')
                if hasattr(self, 'ws_link_label'):
                    self.ws_link_label.setText(f'http://localhost:{self.ws_port}/')
                    self.ws_link_label.hide()
                if hasattr(self, 'copy_link_btn'):
                    self.copy_link_btn.hide()
        else:
            if hasattr(self, 'email_label'):
                self.email_label.setText('Не авторизовано')
        self.ws_status_label.setText('WebSocket: выкл.')
        self.ws_toggle_btn.setText('Запустить сервер')
        self.ws_server_running = False

    def open_ws_settings(self):
        dlg = WebSocketSettingsDialog(self, self.ws_port)
        if dlg.exec_():
            self.ws_port = dlg.get_port()
            self.ws_link_label.setText(f'http://localhost:{self.ws_port}/')
            self.save_settings()
            if getattr(self, 'ws_server_running', False):
                self.stop_ws_server()
                self.start_ws_server()

    def open_html_timer_settings(self):
        dlg = HTMLTimerSettingsDialog(self)
        dlg.exec_()
    

    def check_for_updates(self):
        """Проверяет наличие обновлений"""
        try:
            # Показываем сообщение о проверке
            QMessageBox.information(self, "Проверка обновлений", 
                                  "Проверяем наличие обновлений...")
            
            # Запускаем проверку обновлений
            self.update_manager.check_updates()
            
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", 
                               f"Ошибка при проверке обновлений: {str(e)}")
    
    def check_updates_on_startup(self):
        """Проверяет обновления при запуске приложения"""
        try:
            # Проверяем, нужно ли автоматически проверять обновления
            if self.update_manager.should_check_updates():
                # Запускаем проверку в фоне
                import threading
                update_thread = threading.Thread(target=self._background_update_check)
                update_thread.daemon = True
                update_thread.start()
        except Exception as e:
            print(f"Ошибка при автоматической проверке обновлений: {str(e)}")
    
    def _background_update_check(self):
        """Выполняет проверку обновлений в фоновом режиме"""
        try:
            self.update_manager.check_updates()
        except Exception as e:
            print(f"Ошибка в фоновой проверке обновлений: {str(e)}")
    
    def open_update_settings(self):
        """Открывает диалог настроек обновлений"""
        dlg = UpdateSettingsDialog(self)
        if dlg.exec_():
            # Перезагружаем конфигурацию в менеджере обновлений
            self.update_manager.updater.config = dlg.config

    def get_gameleague_games(self):
        """Получает активные игры пользователя с GameLeague API"""
        if not self.user_email:
            return None, "Пользователь не авторизован через Gmail"
        
        try:
            url = f"https://back.gameleague.su/api/active-rooms/user?email={self.user_email}"
            response = requests.get(url, timeout=10)
            
            # Проверяем статус ответа
            if response.status_code == 200:
                try:
                    data = response.json()
                    
                    # Проверяем успешность запроса
                    if data.get('success'):
                        # Проверяем есть ли данные
                        if data.get('data'):
                            active_games = []
                            
                            for room in data['data']:
                                active_game = room.get('active_game')
                                if active_game:
                                    game_info = {
                                        'name': active_game.get('name', 'Неизвестная игра'),
                                        'image_url': active_game.get('image', ''),
                                        'game_id': active_game.get('id'),  # ID игры
                                        'room_id': room.get('id'),  # ID комнаты (это то, что нужно для API)
                                        'time_to_beat_average': active_game.get('time_to_beat_average', 0)
                                    }
                                    active_games.append(game_info)
                            
                            if active_games:
                                return active_games, None
                            else:
                                return None, "У вас нет активных игр"
                        else:
                            # Если данных нет, но запрос успешен - пользователь не найден
                            return None, f"Пользователь с email {self.user_email} не авторизован на сайте GameLeague"
                    else:
                        # Если запрос неуспешен, проверяем сообщение об ошибке
                        error_message = data.get('message', 'Неизвестная ошибка')
                        if 'not found' in error_message.lower() or 'не найден' in error_message.lower():
                            return None, f"Пользователь с email {self.user_email} не авторизован на сайте GameLeague"
                        else:
                            return None, f"Ошибка GameLeague: {error_message}"
                            
                except ValueError as e:
                    # Если не удалось распарсить JSON, значит пользователь не найден
                    return None, f"Мы не смогли найти вас на GameLeague, Проверьте авторизованы ли вы на сайте через google аккаунт"
                    
            elif response.status_code == 404:
                return None, f"Мы не смогли найти вас на GameLeague, Проверьте авторизованы ли вы на сайте через google аккаунт"
            elif response.status_code == 500:
                return None, f"Ошибка сервера GameLeague. Попробуйте позже."
            else:
                return None, f"Мы не смогли найти вас на GameLeague, Проверьте авторизованы ли вы на сайте через google аккаунт"
                
        except requests.exceptions.RequestException as e:
            return None, f"Ошибка сети: {str(e)}"
        except Exception as e:
            return None, f"Мы не смогли найти вас на GameLeague, Проверьте авторизованы ли вы на сайте через google аккаунт"

    def load_html_timer_settings(self):
        """Загружает настройки HTML таймера из файла"""
        try:
            # Сначала пытаемся загрузить из зашифрованного файла
            if encrypted_config:
                settings = encrypted_config.load_config('html_timer_settings')
                if settings is not None:
                    return settings
            
            # Если не удалось, загружаем из обычного файла
            with open(HTML_TIMER_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            # Возвращаем настройки по умолчанию
            return {
                'font_family': 'Segoe UI',
                'font_size': 'medium',
                'show_game_name': False,
                'game_name_position': 'top',
                'bg_color': '#181f2a',
                'timer_color': '#ffffff',
                'timer_bg_color': '#232b3b',
                'opacity': 85,
                'border_radius': 36,
                'padding': 40,
                'show_seconds': True,
                'show_hours': True,
                'outline': False,
                'outline_color': '#000000',
                'outline_width': 2
            }

    def hex_to_rgba(self, hex_color, opacity):
        """Конвертирует HEX цвет в RGBA с заданной прозрачностью"""
        # Убираем # если есть
        hex_color = hex_color.lstrip('#')
        
        # Конвертируем в RGB
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        
        # Конвертируем прозрачность из процентов в десятичную дробь
        alpha = opacity / 100
        
        return f'rgba({r}, {g}, {b}, {alpha})'

    def generate_html_with_settings(self, settings):
        """Генерирует HTML с учетом настроек"""
        font_size_map = {
            'very_small': 'min(12vw, 20vh)',
            'small': 'min(16vw, 28vh)',
            'medium': 'min(22vw, 40vh)',
            'large': 'min(28vw, 50vh)'
        }
        
        font_family = settings.get('font_family', 'Segoe UI')
        font_size = font_size_map.get(settings.get('font_size', 'medium'), 'min(22vw, 40vh)')
        show_game_name = settings.get('show_game_name', False)
        game_name_position = settings.get('game_name_position', 'top')
        bg_color = settings.get('bg_color', '#181f2a')
        timer_color = settings.get('timer_color', '#ffffff')
        timer_bg_color = settings.get('timer_bg_color', '#232b3b')
        opacity = settings.get('opacity', 85)
        border_radius = settings.get('border_radius', 36)
        padding = settings.get('padding', 40)
        show_seconds = settings.get('show_seconds', True)
        show_hours = settings.get('show_hours', True)
        outline = settings.get('outline', False)
        outline_color = settings.get('outline_color', '#000000')
        outline_width = settings.get('outline_width', 2)
        
        # Конвертируем цвет фона таймера в RGBA с учетом прозрачности
        timer_bg_rgba = f'rgba({int(timer_bg_color[1:3], 16)}, {int(timer_bg_color[3:5], 16)}, {int(timer_bg_color[5:7], 16)}, {opacity/100})'
        
        # Получаем текущее время (если передано) или используем дефолтное
        current_time = settings.get('current_time', '00:00:00')
        current_game_name = settings.get('current_game', 'Timer')
        
        # Отладочная информация
        print(f"DEBUG: timer_bg_color = {timer_bg_color}, opacity = {opacity}, rgba = {timer_bg_rgba}")
        print(f"DEBUG: current_time = {current_time}, current_game = {current_game_name}")
        
        # Создаем стиль обводки
        outline_style = ''
        if outline:
            # Создаем обводку с помощью text-shadow
            outline_shadows = []
            for i in range(-outline_width, outline_width + 1):
                for j in range(-outline_width, outline_width + 1):
                    if i != 0 or j != 0:  # Исключаем центральную точку
                        outline_shadows.append(f'{i}px {j}px 0 {outline_color}')
            outline_style = f'text-shadow: {", ".join(outline_shadows)};'
        
        time_format = 'HH:mm:ss' if show_hours and show_seconds else 'HH:mm' if show_hours else 'mm:ss' if show_seconds else 'mm'
        
        # Генерируем HTML для названия игры
        current_game_name = getattr(self, 'current_game', '')
        game_name_html = ''
        game_name_html_bottom = ''
        
        print(f"DEBUG: generate_html - show_game_name = {show_game_name}, current_game_name = '{current_game_name}'")
        
        if show_game_name and current_game_name:
            game_name_element = f'<div id="game-name">{current_game_name}</div>'
            if game_name_position == 'top':
                game_name_html = game_name_element
            else:
                game_name_html_bottom = game_name_element
            print(f"DEBUG: Добавлен элемент game-name: {game_name_element}")
        else:
            # Всегда добавляем пустой элемент для динамического обновления
            game_name_element = f'<div id="game-name" style="display: none;"></div>'
            if game_name_position == 'top':
                game_name_html = game_name_element
            else:
                game_name_html_bottom = game_name_element
            print(f"DEBUG: Добавлен скрытый элемент game-name")
        
        html = f'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>GameLeague Timer</title>
<style>
html, body {{
  height: 100%;
  margin: 0;
  padding: 0;
}}
body {{
  width: 100vw;
  height: 100vh;
  background: {bg_color};
  color: {timer_color};
  font-family: {font_family}, Arial, sans-serif;
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  overflow: hidden;
}}
#container {{
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}}
#game-name {{
  font-family: {font_family}, Arial, sans-serif;
  font-size: calc({font_size} * 0.4);
  font-weight: bold;
  text-align: center;
  margin: 0;
  {outline_style}
}}
#timer-bg {{
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: {padding}px;
  background: {timer_bg_rgba};
  border-radius: {border_radius}px;
  gap: calc({padding}px * 0.3);
}}
#timer {{
  display: block;
  margin: 0 auto;
  font-family: {font_family}, Arial, sans-serif;
  font-size: {font_size};
  font-weight: bold;
  text-align: center;
  user-select: none;
  letter-spacing: -0.05em;
  line-height: 1;
  {outline_style}
}}
@media (max-width: 900px) {{
  #timer {{ font-size: calc({font_size} * 0.7); }}
  #timer-bg {{ padding: calc({padding}px * 0.5); border-radius: calc({border_radius}px * 0.5); }}
  #game-name {{ font-size: calc({font_size} * 0.28); }}
}}
</style>
</head>
<body>
<div id="container">
  <div id="timer-bg">
    {game_name_html}
    <div id="timer">{current_time}</div>
    {game_name_html_bottom}
  </div>
</div>
<script>
let ws = null;
function connect() {{
  ws = new WebSocket('ws://' + window.location.hostname + ':' + window.location.port + '/ws');
  ws.onmessage = function(e) {{
    try {{
      // Пытаемся разобрать JSON данные
      let data = JSON.parse(e.data);
      let time = data.time;
      let gameName = data.game_name;
      let showGameName = data.show_game_name;
      
      // Обновляем название игры если элемент существует и настройка включена
      let gameNameElement = document.getElementById('game-name');
      if (gameNameElement) {{
        if (showGameName && gameName) {{
          gameNameElement.textContent = gameName;
          gameNameElement.style.display = 'block';
        }} else {{
          gameNameElement.style.display = 'none';
        }}
      }}
      
      // Форматируем время согласно настройкам
      let parts = time.split(':');
      if (parts.length === 3) {{
        let hours = parts[0];
        let minutes = parts[1];
        let seconds = parts[2];
        
        if ('{time_format}' === 'HH:mm:ss') {{
          time = hours + ':' + minutes + ':' + seconds;
        }} else if ('{time_format}' === 'HH:mm') {{
          time = hours + ':' + minutes;
        }} else if ('{time_format}' === 'mm:ss') {{
          time = minutes + ':' + seconds;
        }} else {{
          time = minutes;
        }}
      }}
      document.getElementById('timer').textContent = time;
    }} catch (err) {{
      // Если не JSON, обрабатываем как обычный текст (для совместимости)
      let time = e.data;
      let parts = time.split(':');
      if (parts.length === 3) {{
        let hours = parts[0];
        let minutes = parts[1];
        let seconds = parts[2];
        
        if ('{time_format}' === 'HH:mm:ss') {{
          time = hours + ':' + minutes + ':' + seconds;
        }} else if ('{time_format}' === 'HH:mm') {{
          time = hours + ':' + minutes;
        }} else if ('{time_format}' === 'mm:ss') {{
          time = minutes + ':' + seconds;
        }} else {{
          time = minutes;
        }}
      }}
      document.getElementById('timer').textContent = time;
    }}
  }};
  ws.onclose = function() {{ setTimeout(connect, 1000); }};
}}
connect();
</script>
</body>
</html>'''
        
        return html

    def save_timer_log(self):
        if not self.timer_start_dt or not self.timer_stop_dt or not self.current_game:
            return
        
        # Создаем безопасное имя файла для игры
        safe_game_name = "".join(c for c in self.current_game if c.isalnum() or c in (' ', '-', '_')).rstrip()
        safe_game_name = safe_game_name.replace(' ', '_')
        fname = os.path.join(LOGS_DIR, f"timer_log_{safe_game_name}.json")
        
        # Загружаем существующие данные или создаем новые
        try:
            with open(fname, 'r', encoding='utf-8') as f:
                game_data = json.load(f)
        except FileNotFoundError:
            game_data = {
                'game_name': self.current_game,
                'total_time_seconds': 0,
                'total_time_str': '00:00:00',
                'sessions': []
            }
        
        # Вычисляем время текущей сессии
        duration = (self.timer_stop_dt - self.timer_start_dt).total_seconds()
        duration_str = str(datetime.timedelta(seconds=int(duration)))
        
        # Добавляем новую сессию
        session_data = {
            'date': self.timer_stop_dt.strftime('%Y-%m-%d'),
            'start_time': self.timer_start_dt.strftime('%Y-%m-%d %H:%M:%S'),
            'stop_time': self.timer_stop_dt.strftime('%Y-%m-%d %H:%M:%S'),
            'duration_seconds': int(duration),
            'duration_str': duration_str
        }
        game_data['sessions'].append(session_data)
        
        # Обновляем общее время
        game_data['total_time_seconds'] = self.seconds
        game_data['total_time_str'] = str(datetime.timedelta(seconds=self.seconds))
        game_data['last_updated'] = self.timer_stop_dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # Сохраняем обновленные данные
        with open(fname, 'w', encoding='utf-8') as f:
            json.dump(game_data, f, ensure_ascii=False, indent=2)

    def edit_time(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Редактировать')
        layout = QFormLayout()
        
        hours = QSpinBox(dialog)
        minutes = QSpinBox(dialog)
        seconds = QSpinBox(dialog)
        
        hours.setRange(0, 999)
        minutes.setRange(0, 59)
        seconds.setRange(0, 59)
        
        current_hours = self.seconds // 3600
        current_minutes = (self.seconds % 3600) // 60
        current_seconds = self.seconds % 60
        
        hours.setValue(current_hours)
        minutes.setValue(current_minutes)
        seconds.setValue(current_seconds)
        
        layout.addRow('Часы:', hours)
        layout.addRow('Минуты:', minutes)
        layout.addRow('Секунды:', seconds)
        
        buttons = QHBoxLayout()
        ok_button = QPushButton('Сохранить')
        cancel_button = QPushButton('Отмена')
        
        buttons.addWidget(ok_button)
        buttons.addWidget(cancel_button)
        layout.addRow(buttons)
        
        dialog.setLayout(layout)
        
        ok_button.clicked.connect(dialog.accept)
        cancel_button.clicked.connect(dialog.reject)
        
        if dialog.exec_() == QDialog.Accepted:
            self.seconds = hours.value() * 3600 + minutes.value() * 60 + seconds.value()
            if self.current_game:
                # Обновляем файл логов
                self.update_game_log_file()
            self.update_time_display()

    def update_game_log_file(self):
        if not self.current_game:
            return
            
        # Создаем безопасное имя файла для игры
        safe_game_name = "".join(c for c in self.current_game if c.isalnum() or c in (' ', '-', '_')).rstrip()
        safe_game_name = safe_game_name.replace(' ', '_')
        fname = os.path.join(LOGS_DIR, f"timer_log_{safe_game_name}.json")
        
        # Загружаем существующие данные или создаем новые
        try:
            with open(fname, 'r', encoding='utf-8') as f:
                game_data = json.load(f)
        except FileNotFoundError:
            game_data = {
                'game_name': self.current_game,
                'image_url': '',
                'total_time_seconds': 0,
                'total_time_str': '00:00:00',
                'sessions': []
            }
        
        # Обновляем общее время с учетом реального времени во время обратного отсчета
        if self.countdown_mode:
            # Во время обратного отсчета сохраняем оригинальное время + реальное время, прошедшее во время обратного отсчета
            time_to_save = self.original_seconds + self.real_time_during_countdown
        else:
            # В обычном режиме используем текущее время
            time_to_save = self.seconds
            
        game_data['total_time_seconds'] = time_to_save
        game_data['total_time_str'] = str(datetime.timedelta(seconds=time_to_save))
        game_data['last_updated'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Сохраняем обновленные данные
        with open(fname, 'w', encoding='utf-8') as f:
            json.dump(game_data, f, ensure_ascii=False, indent=2)

    def start_game(self):
        game = self.page2.get_selected_game()
        if game:
            self.current_game = game
            # Загружаем время из файла логов, если он существует
            self.seconds = self.load_game_time_from_logs(game)
            self.update_time_display()
            self.show_page(2)
            
            # Запускаем таймер уведомления о неактивности (5 минут = 300 секунд)
            self.start_idle_notification_timer()
            
            # Проверяем, есть ли room_id для этой игры
            room_id = self.get_room_id_for_game(game)
            if room_id:
                print(f"DEBUG: Игра {game} имеет room_id: {room_id}")
            else:
                print(f"DEBUG: Игра {game} не имеет room_id (не загружена с GameLeague)")
                print(f"DEBUG: Для отправки результатов игра должна быть загружена с GameLeague")
        else:
            QMessageBox.warning(self, 'Выбор игры', 'Пожалуйста, выберите игру!')

    def load_game_time_from_logs(self, game_name):
        # Создаем безопасное имя файла для игры
        safe_game_name = "".join(c for c in game_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
        safe_game_name = safe_game_name.replace(' ', '_')
        fname = os.path.join(LOGS_DIR, f"timer_log_{safe_game_name}.json")
        
        try:
            with open(fname, 'r', encoding='utf-8') as f:
                game_data = json.load(f)
                return game_data.get('total_time_seconds', 0)
        except FileNotFoundError:
            # Если файл логов не найден, возвращаем 0
            return 0

    def update_time_display(self):
        h = self.seconds // 3600
        m = (self.seconds % 3600) // 60
        s = self.seconds % 60
        time_str = f'{h:02}:{m:02}:{s:02}'
        
        self.time_label.setText(time_str)
        
        # Обновляем время в окне поверх всех приложений
        if self.overlay_timer_visible:
            self.overlay_timer.update_time(time_str)
        
        with self.last_time_lock:
            self.last_time_str = time_str
        
        # Обновляем live HTML для браузера (только если WebSocket сервер запущен)
        if getattr(self, 'ws_server_running', False):
            self.update_live_html_timer(time_str)
    
    def update_live_html_timer(self, time_str):
        """Обновляет live HTML файл с новым временем"""
        try:
            settings = self.load_html_timer_settings()
            
            # Модифицируем настройки, добавляя текущее время
            settings['current_time'] = time_str
            settings['current_game'] = self.current_game if self.current_game else 'Timer'
            
            # Добавляем timestamp для принудительного обновления браузера
            import time
            settings['timestamp'] = int(time.time())
            
            print(f"DEBUG: Обновляем live HTML - время: {time_str}, игра: {settings['current_game']}")
            
            # Генерируем HTML с обновленным временем
            html = self.generate_html_with_settings(settings)
            
            # Сохраняем обновленный HTML
            live_html_path = os.path.join(WORK_DIR, 'timer_live.html')
            with open(live_html_path, 'w', encoding='utf-8') as f:
                f.write(html)
            
            print(f"DEBUG: Live HTML файл обновлен: {live_html_path}")
                
        except Exception as e:
            print(f"DEBUG: Ошибка обновления live HTML с временем: {e}")
    
    def toggle_overlay_timer(self):
        if self.overlay_timer_visible:
            self.overlay_timer.hide()
            self.overlay_timer_visible = False
            self.overlay_btn.setText('Показать поверх всех окон')
        else:
            # Обновляем настройки overlay таймера перед показом
            self.overlay_timer.refresh_settings()
            
            # Позиционируем окно в правом верхнем углу экрана
            screen = QApplication.primaryScreen().geometry()
            self.overlay_timer.move(screen.width() - self.overlay_timer.width() - 20, 20)
            self.overlay_timer.show()
            self.overlay_timer_visible = True
            self.overlay_btn.setText('Скрыть поверх всех окон')
            # Обновляем время в окне
            self.overlay_timer.update_time(self.time_label.text())
    
    def send_final_result(self):
        """Отправляет финальный результат на GameLeague API"""
        if not self.current_game:
            QMessageBox.warning(self, 'Ошибка', 'Не выбрана игра для отправки результата!')
            return
        
        if not self.user_email:
            QMessageBox.warning(self, 'Ошибка', 'Необходимо авторизоваться через Google!')
            return
        
        # Первое предупреждение
        reply1 = QMessageBox.question(self, 'Подтверждение отправки', 
                                     f'Вы уверены, что хотите отправить результат для игры "{self.current_game}"?\n\n'
                                     f'Текущее время: {self.time_label.text()}\n\n'
                                     f'Это действие нельзя будет отменить!',
                                     QMessageBox.Yes | QMessageBox.No)
        
        if reply1 != QMessageBox.Yes:
            return
        
        # Второе предупреждение
        reply2 = QMessageBox.question(self, 'Финальное подтверждение', 
                                     f'ПОСЛЕДНЕЕ ПРЕДУПРЕЖДЕНИЕ!\n\n'
                                     f'Вы действительно хотите отправить результат?\n'
                                     f'Игра: {self.current_game}\n'
                                     f'Время: {self.time_label.text()}\n\n'
                                     f'Это действие НЕЛЬЗЯ ОТМЕНИТЬ!',
                                     QMessageBox.Yes | QMessageBox.No)
        
        if reply2 != QMessageBox.Yes:
            return
        
        # Получаем room_id из файла логов
        room_id = self.get_room_id_for_game(self.current_game)
        if not room_id:
            QMessageBox.critical(self, 'Ошибка', 
                               f'Не удалось найти ID комнаты для игры "{self.current_game}".\n'
                               f'Убедитесь, что игра была загружена с GameLeague.')
            return
        
        # Отправляем результат
        try:
            url = f"https://back.gameleague.su/api/track-game-progress"
            params = {
                'email': self.user_email,
                'room_id': room_id,
                'final_time': self.seconds
            }
            
            print(f"DEBUG: Отправляем результат на {url}")
            print(f"DEBUG: Параметры: {params}")
            response = requests.post(url, params=params, timeout=10)
            print(f"DEBUG: Статус ответа: {response.status_code}")
            print(f"DEBUG: Текст ответа: {response.text}")
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    if data.get('success'):
                        QMessageBox.information(self, 'Успех', 
                                              f'Результат успешно отправлен!\n\n'
                                              f'Игра: {self.current_game}\n'
                                              f'Время: {self.time_label.text()}\n'
                                              f'Сервер: {data.get("message", "Результат принят")}')
                    else:
                        error_msg = data.get('message', 'Неизвестная ошибка')
                        QMessageBox.critical(self, 'Ошибка отправки', 
                                           f'Сервер вернул ошибку:\n{error_msg}')
                except ValueError:
                    QMessageBox.critical(self, 'Ошибка', 'Неверный ответ от сервера')
            else:
                QMessageBox.critical(self, 'Ошибка сети', 
                                   f'Ошибка HTTP {response.status_code}:\n{response.text}')
                
        except requests.exceptions.RequestException as e:
            QMessageBox.critical(self, 'Ошибка сети', f'Не удалось отправить результат:\n{str(e)}')
        except Exception as e:
            QMessageBox.critical(self, 'Ошибка', f'Неожиданная ошибка:\n{str(e)}')
    
    def get_room_id_for_game(self, game_name):
        """Получает room_id для указанной игры из файла логов"""
        try:
            # Создаем безопасное имя файла для игры
            safe_game_name = "".join(c for c in game_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
            safe_game_name = safe_game_name.replace(' ', '_')
            fname = os.path.join(LOGS_DIR, f"timer_log_{safe_game_name}.json")
            
            with open(fname, 'r', encoding='utf-8') as f:
                game_data = json.load(f)
                return game_data.get('room_id')  # Теперь ищем правильное поле room_id
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            return None
    
    def apply_theme(self):
        """Применяет текущую тему к приложению"""
        theme = self.themes[self.current_theme]
        
        # Обновляем иконку кнопки темы
        if self.current_theme == 'light':
            # Загружаем logo.png для светлой темы
            try:
                logo_path = os.path.join(os.path.dirname(__file__), 'logo.png')
                if os.path.exists(logo_path):
                    icon = QIcon(logo_path)
                    self.theme_btn.setIcon(icon)
                else:
                    # Fallback на эмодзи если файл не найден
                    self.theme_btn.setText('🌙')
            except Exception as e:
                print(f"Ошибка загрузки logo.png: {e}")
                self.theme_btn.setText('🌙')
            
            self.theme_btn.setStyleSheet(f'''
                QPushButton {{
                    background-color: rgba(123, 92, 255, 0.8);
                    border: none;
                    border-radius: 20px;
                }}
                QPushButton:hover {{
                    background-color: rgba(123, 92, 255, 1.0);
                }}
            ''')
        else:
            # Загружаем logo2.png для темной темы
            try:
                logo2_path = os.path.join(os.path.dirname(__file__), 'logo2.png')
                if os.path.exists(logo2_path):
                    icon = QIcon(logo2_path)
                    self.theme_btn.setIcon(icon)
                else:
                    # Fallback на эмодзи если файл не найден
                    self.theme_btn.setText('☀️')
            except Exception as e:
                print(f"Ошибка загрузки logo2.png: {e}")
                self.theme_btn.setText('☀️')
            
            self.theme_btn.setStyleSheet(f'''
                QPushButton {{
                    background-color: rgba(255, 0, 0, 0.8);
                    border: none;
                    border-radius: 20px;
                }}
                QPushButton:hover {{
                    background-color: rgba(255, 0, 0, 1.0);
                }}
            ''')
        
        # Применяем стили к основному окну
        self.setStyleSheet(f'''
            QWidget {{
                background-color: {theme['bg_color']};
                color: {theme['text_color']};
                font-family: Segoe UI, Arial, sans-serif;
                font-size: 16px;
            }}
            QLabel#timerLabel {{
                font-size: 56px;
                font-weight: bold;
                color: {theme['timer_color']};
                background: {theme['timer_bg']};
                border-radius: 18px;
                padding: 18px 0;
            }}
            QPushButton {{
                border-radius: 12px;
                padding: 10px 24px;
                font-size: 18px;
                font-weight: 500;
                background: {theme['button_bg']};
                color: {theme['text_color']};
                border: none;
            }}
            QPushButton#startBtn {{
                background: {theme['accent_gradient']};
                color: #fff;
            }}
            QPushButton#resetBtn {{
                background: {theme['reset_color']};
                color: #fff;
            }}
            QPushButton#hotkeyBtn {{
                background: {theme['button_bg']};
                color: {theme['accent_color']};
                border: 2px solid {theme['accent_color']};
            }}
            QLineEdit {{
                background: {theme['card_bg']};
                color: {theme['text_color']};
                border-radius: 10px;
                padding: 8px 12px;
                border: 1px solid {theme['border_color']};
                font-size: 16px;
            }}
            QLabel#footerLabel {{
                color: #888;
                font-size: 14px;
                margin-top: 10px;
                qproperty-alignment: AlignCenter;
            }}
        ''')
        
        # Обновляем стили для окна поверх всех приложений
        if hasattr(self, 'overlay_timer'):
            self.overlay_timer.apply_theme(theme)
        
        # Принудительно обновляем все виджеты
        self.update()
        self.repaint()
        
        # Обновляем GameSelectionPage если она создана
        if hasattr(self, 'page2'):
            self.page2.apply_theme(theme)
            self.page2.update()
            self.page2.repaint()
    
    def toggle_theme(self):
        """Переключает между темами"""
        self.current_theme = 'neon' if self.current_theme == 'light' else 'light'
        self.apply_theme()
    
    def on_resize(self, event):
        """Обработчик изменения размера окна"""
        # Перепозиционируем кнопку темы
        if hasattr(self, 'theme_btn'):
            self.theme_btn.move(self.width() - 50, 10)
        event.accept()
    
    def start_idle_notification_timer(self):
        """Запускает таймер уведомления о неактивности"""
        self.idle_seconds_remaining = 300  # 5 минут
        self.idle_notification_timer.start(300000)  # 5 минут = 300000 мс
        self.idle_countdown_timer.start(1000)  # Обновляем каждую секунду
        self.update_idle_countdown()
    
    def stop_idle_notification_timer(self):
        """Останавливает таймер уведомления о неактивности"""
        self.idle_notification_timer.stop()
        self.idle_countdown_timer.stop()
        if self.idle_notification_label:
            self.idle_notification_label.hide()
    
    def update_idle_countdown(self):
        """Обновляет визуальный отсчет до уведомления"""
        if self.idle_seconds_remaining > 0:
            self.idle_seconds_remaining -= 1
            minutes = self.idle_seconds_remaining // 60
            seconds = self.idle_seconds_remaining % 60
            
            if self.idle_notification_label:
                self.idle_notification_label.setText(
                    f"⏰ Запустите таймер! Уведомление через: {minutes:02d}:{seconds:02d}"
                )
                self.idle_notification_label.show()
        else:
            # Время истекло, скрываем метку
            if self.idle_notification_label:
                self.idle_notification_label.hide()
            self.idle_countdown_timer.stop()
    
    def show_idle_notification(self):
        """Показывает уведомление о том, что нужно запустить таймер"""
        if not self.running:  # Показываем только если таймер не запущен
            QMessageBox.information(self, 'Напоминание', 
                                  f'Вы выбрали игру "{self.current_game}", но не запустили таймер уже 5 минут.\n\n'
                                  f'Не забудьте нажать "Старт" чтобы начать отсчет времени!')
        
        # Останавливаем таймеры после показа уведомления
        self.stop_idle_notification_timer()

    def back_to_games(self):
        # Останавливаем таймер уведомления при возврате к играм
        self.stop_idle_notification_timer()
        
        if self.running:
            reply = QMessageBox.question(self, 'Таймер работает', 
                                       'Таймер сейчас работает. Вы уверены, что хотите вернуться к выбору игры?\nЭто остановит таймер.',
                                       QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                # Останавливаем таймер
                self.timer.stop()
                self.start_btn.setText('Старт')
                self.running = False
                self.timer_stop_dt = datetime.datetime.now()
                if self.current_game:
                    self.update_game_log_file()
                self.save_timer_log()
                # Возвращаемся к выбору игры
                self.show_page(1)
        else:
            # Если таймер не работает, просто возвращаемся к выбору игры
            self.show_page(1)

    def closeEvent(self, event):
        try:
            # Останавливаем новый HotkeyListener
            if hasattr(self, 'hotkey_listener'):
                self.hotkey_listener.stop_listening()
        except:
            pass  # Игнорируем ошибки при отключении хоткеев
        
        # Закрываем окно поверх всех приложений
        if self.overlay_timer_visible:
            self.overlay_timer.close()
        
        # Останавливаем все загрузчики изображений
        for loader in self.page2.image_loaders.values():
            if loader.isRunning():
                loader.quit()
                loader.wait()
        
        event.accept()

def create_desktop_shortcut(target_path, shortcut_name="TGL", description="TimerGL"):
    """Создает ярлык на рабочем столе без внешних зависимостей"""
    try:
        import win32com.client
        
        # Получаем путь к рабочему столу
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        shortcut_path = os.path.join(desktop, f"{shortcut_name}.lnk")
        
        # Создаем ярлык
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(shortcut_path)
        shortcut.Targetpath = target_path
        shortcut.WorkingDirectory = os.path.dirname(target_path)
        shortcut.Description = description
        shortcut.save()
        return True
    except ImportError:
        # Если win32com недоступен, создаем bat-файл для создания ярлыка
        try:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            bat_path = os.path.join(os.path.dirname(target_path), "create_shortcut.bat")
            
            bat_content = f'''@echo off
powershell "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('{desktop}\\{shortcut_name}.lnk'); $s.TargetPath = '{target_path}'; $s.WorkingDirectory = '{os.path.dirname(target_path)}'; $s.Description = '{description}'; $s.Save()"
del "%~f0"
'''
            
            with open(bat_path, 'w', encoding='cp1251') as f:
                f.write(bat_content)
            
            subprocess.run([bat_path], shell=True, check=True)
            return True
        except Exception:
            return False
    except Exception:
        return False

def install_to_work_dir(work_dir):
    """Устанавливает приложение в выбранную пользователем рабочую директорию"""
    import sys, os
    
    exe_path = sys.executable
    exe_name = os.path.basename(exe_path)
    exe_dir = os.path.dirname(exe_path)
    
    # Проверяем, нужна ли установка
    if '--installed' in sys.argv:
        return True  # Уже установлено
        
    # Проверяем, не находится ли exe уже в рабочей директории
    new_exe_path = os.path.join(work_dir, exe_name)
    if os.path.abspath(exe_path) == os.path.abspath(new_exe_path):
        return True  # Уже в нужной папке
    
    # Проверяем, есть ли уже exe в рабочей директории
    if os.path.exists(new_exe_path):
        # Запускаем уже установленную версию и завершаем текущую
        subprocess.Popen([new_exe_path, '--installed'])
        sys.exit(0)
        
    try:
        # Копируем exe в рабочую директорию
        shutil.copy2(exe_path, new_exe_path)
        print(f"Скопирован exe-файл в: {new_exe_path}")
        
        # Создаем work_dir.json в новой рабочей директории
        try:
            work_dir_file = os.path.join(work_dir, 'work_dir.json')
            with open(work_dir_file, 'w', encoding='utf-8') as f:
                json.dump({'work_dir': work_dir}, f, ensure_ascii=False, indent=2)
            print(f"Создан файл work_dir.json")
        except Exception as e:
            print(f"Ошибка создания work_dir.json: {e}")
        
        # Переносим важные файлы из исходной директории в рабочую директорию
        try:
            files_to_transfer = ['hotkey_settings.json', 'html_timer_settings.json', 'games.json']
            for file_to_transfer in files_to_transfer:
                source_path = os.path.join(exe_dir, file_to_transfer)
                if os.path.exists(source_path):
                    target_path = os.path.join(work_dir, file_to_transfer)
                    shutil.copy2(source_path, target_path)
                    print(f"Перенесен файл: {file_to_transfer}")
            
            # Переносим важные папки
            dirs_to_transfer = ['logs']
            for dir_to_transfer in dirs_to_transfer:
                source_dir_path = os.path.join(exe_dir, dir_to_transfer)
                if os.path.exists(source_dir_path):
                    target_dir_path = os.path.join(work_dir, dir_to_transfer)
                    if os.path.exists(target_dir_path):
                        shutil.rmtree(target_dir_path)  # Удаляем если уже существует
                    shutil.copytree(source_dir_path, target_dir_path)
                    print(f"Перенесена папка: {dir_to_transfer}")
        except Exception as e:
            print(f"Ошибка переноса файлов: {e}")
        
        # Создаем ярлык на рабочем столе
        if create_desktop_shortcut(new_exe_path):
            print("Ярлык создан на рабочем столе")
        
        # Запускаем новый exe с флагом --installed
        subprocess.Popen([new_exe_path, '--installed'], cwd=os.path.dirname(new_exe_path))
        print(f"Запущено приложение из рабочей директории: {work_dir}")
        
        # Удаляем исходные файлы и папки после переноса
        try:
            # Удаляем файлы которые перенесли + work_dir.json если был создан
            files_to_remove = ['work_dir.json', 'hotkey_settings.json', 'html_timer_settings.json', 'games.json']
            for file_to_remove in files_to_remove:
                source_path = os.path.join(exe_dir, file_to_remove)
                if os.path.exists(source_path):
                    os.remove(source_path)
                    print(f"Удален исходный файл: {file_to_remove}")
            
            # Удаляем папки которые перенесли
            dirs_to_remove = ['logs']
            for dir_to_remove in dirs_to_remove:
                source_dir_path = os.path.join(exe_dir, dir_to_remove)
                if os.path.exists(source_dir_path):
                    shutil.rmtree(source_dir_path)
                    print(f"Удалена исходная папка: {dir_to_remove}")
        except Exception as e:
            print(f"Ошибка при очистке исходных файлов: {e}")
            
        # Удаляем исходный exe
        os.remove(exe_path)
        print(f"Исходный файл удален: {exe_path}")
        print("Установка в рабочую директорию завершена успешно!")
        sys.exit(0)
    except Exception as e:
        print(f"Ошибка при установке: {e}")
        # Если не удалось скопировать - просто продолжаем работу из исходной папки
        return True
    return True

def is_installation_needed():
    """Проверяет, нужна ли установка"""
    import sys, os
    
    # Проверяем аргументы командной строки - если передан --installed, значит уже установлено
    if '--installed' in sys.argv:
        return False
    
    # Только для exe файлов проверяем установку
    if not getattr(sys, 'frozen', False):
        return False
    
    exe_path = sys.executable
    exe_dir = os.path.dirname(exe_path)
    
    # Проверяем, есть ли уже рабочая директория рядом с exe
    work_dir_file = os.path.join(exe_dir, 'work_dir.json')
    if os.path.exists(work_dir_file):
        return False  # Уже установлено
        
    # Если рядом есть папки logs, games.json и т.д. - тоже считаем установленным
    if (os.path.exists(os.path.join(exe_dir, 'logs')) or 
        os.path.exists(os.path.join(exe_dir, 'games.json'))):
        return False
    
    return True  # Нужна установка

def main():
    app = QApplication(sys.argv)
    
    # Проверяем, нужна ли установка ПЕРЕД созданием work_dir.json
    if getattr(sys, 'frozen', False) and is_installation_needed():  # Только для exe
        # Показываем пользовательское соглашение
        agreement_dialog = UserAgreementDialog()
        if agreement_dialog.exec_() != QDialog.Accepted:
            sys.exit(0)
        
        # Показываем диалог выбора директории для установки
        dialog = WorkDirectoryDialog()
        if dialog.exec_() == QDialog.Accepted:
            selected_work_dir = dialog.selected_dir
            install_to_work_dir(selected_work_dir)
            return  # Этот процесс завершится после установки
        else:
            sys.exit(0)
    
    # Инициализируем рабочую директорию перед созданием основного окна
    if not init_work_directory():
        # Если пользователь отменил выбор директории - выходим
        sys.exit(0)
    
    window = TimerApp()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main() 