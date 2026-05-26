try:
    from pynput import keyboard, mouse
    import pyautogui
    HAS_GUI = True
except ImportError:
    HAS_GUI = False

def _check_gui():
    if not HAS_GUI:
        raise ImportError(
            "The 'pyautogui' and 'pynput' libraries are required for GUI utilities. "
            "Install them with: pip install utilitz[gui]"
        )

from datetime import datetime
import time


class MonitorActivity:

    def __init__(self):
        _check_gui()
        self.last_activity_time = time.monotonic()
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_keyboard_event,
            on_release=self._on_keyboard_event,
        )
        self._mouse_listener = mouse.Listener(
            on_move=self._on_mouse_event,
            on_click=self._on_mouse_event,
            on_scroll=self._on_mouse_event,
        )

    def _on_keyboard_event(self, *args, **kwargs):
        self.last_activity_time = time.monotonic()

    def _on_mouse_event(self, *args, **kwargs):
        self.last_activity_time = time.monotonic()

    def start(self):
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_keyboard_event,
            on_release=self._on_keyboard_event,
        )
        self._mouse_listener = mouse.Listener(
            on_move=self._on_mouse_event,
            on_click=self._on_mouse_event,
            on_scroll=self._on_mouse_event,
        )
        self._keyboard_listener.start()
        self._mouse_listener.start()

    def stop(self):
        self._keyboard_listener.stop()
        self._mouse_listener.stop()

    @property
    def inactive_seconds(self):
        return time.monotonic() - self.last_activity_time

    def __repr__(self):
        return f"MonitorActivity(inactive_seconds={self.inactive_seconds:.3f})"

    def __str__(self):
        return (
            "MonitorActivity\n"
            f"  inactive_seconds: {self.inactive_seconds:.3f}\n"
            f"  keyboard_listener: {type(self._keyboard_listener).__name__}\n"
            f"  mouse_listener: {type(self._mouse_listener).__name__}"
        )


def monitor_keep_alive(seconds, key='ctrl', verbose=1, tolerance=0.1):
    _check_gui()
    def time_format(ts):
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    original_failsafe = pyautogui.FAILSAFE
    pyautogui.FAILSAFE = False

    monitor = MonitorActivity()
    monitor.start()
    status = '==START=='
    if verbose:
        print(time_format(time.time()), status)
    time.sleep(seconds)
    try:
        while True:
            sleep_end_time = time.monotonic()
            last_activity_time = monitor.last_activity_time

            inactive_time = sleep_end_time - last_activity_time
            is_active = inactive_time < seconds

            if is_active:
                last_status = status
                status = '==ACTIVE=='
                sleep_time = max(tolerance, seconds -
                                 inactive_time - tolerance)
            else:
                last_status = status
                status = '==INACTIVE=='
                sleep_time = max(tolerance, seconds - tolerance)
                try:
                    pyautogui.press(key)
                except pyautogui.FailSafeException:
                    pass
            if verbose == 1 and status != last_status:
                print(time_format(time.time()), status)
            elif verbose == 2:
                print(time_format(time.time()), status,
                      '\n\tinactive_time:',  f'{inactive_time:.03f}', 'sleep_time:', f'{sleep_time:.03f}')
            time.sleep(sleep_time)
    finally:
        pyautogui.FAILSAFE = original_failsafe
        monitor.stop()
