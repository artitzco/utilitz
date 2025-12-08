
from pynput import keyboard, mouse
from datetime import datetime
import pyautogui
import time


class MonitorActivity:
    """
    MonitorActivity
    ----------------
    Class responsible for listening to keyboard and mouse events via pynput.

    Attributes
    ----------
    last_activity_time : float
        Timestamp of the last detected user activity.

    Methods
    -------
    start():
        Starts the keyboard and mouse listeners.
    stop():
        Stops the listeners.

    Internal Use
    ------------
    This class is used by monitor_keep_alive to determine the amount of time
    that has passed without any user interaction.
    """

    def __init__(self):
        self.last_activity_time = time.time()
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
        self.last_activity_time = time.time()

    def _on_mouse_event(self, *args, **kwargs):
        self.last_activity_time = time.time()

    def start(self):
        self._keyboard_listener.start()
        self._mouse_listener.start()

    def stop(self):
        self._keyboard_listener.stop()
        self._mouse_listener.stop()


def monitor_keep_alive(seconds, key='ctrl', verbose=1):
    """
    monitor_keep_alive
    -------------------
    Continuously monitors user activity and triggers an automatic key press
    when no keyboard or mouse events occur within the specified interval.

    Parameters
    ----------
    seconds : int or float
        Base interval in seconds to evaluate user activity.
    key : str, optional
        The key to press when inactivity is detected.
        Examples: 'ctrl', 'shift', 'space', 'enter', 'f15', etc.
    verbose : int, optional
        Controls console logging:
            0 → silent
            1 → prints only when the user status changes (Active/Inactive)
            2 → prints extended debug information (timings, cycle details)

    Behavior
    --------
    - Starts a real-time activity monitor (keyboard + mouse).
    - Every `seconds` seconds, checks whether activity occurred.
    - If activity occurred → does nothing.
    - If NO activity occurred → presses the configured key.
    - Dynamically adjusts sleep intervals based on the last activity time.

    Examples
    --------
    # Keep session alive by pressing CTRL every 3 seconds of inactivity
    monitor_keep_alive(3)

    # Use SHIFT instead of CTRL
    monitor_keep_alive(5, key='shift')

    # Verbose debug mode
    monitor_keep_alive(10, verbose=2)

    Notes
    -----
    - The function runs indefinitely; stop it manually when needed.
    - pyautogui may require accessibility permissions on macOS.
    - pynput listeners run on background threads.

    Warning
    -------
    This script simulates human activity. It may violate rules in certain
    applications, organizations, or platforms. Use at your own risk.
    """

    monitor = MonitorActivity()
    monitor.start()
    status = '==START=='
    sleep_start_time = time.time()
    time.sleep(seconds)
    if verbose:
        print(datetime.fromtimestamp(sleep_end_time).strftime("%Y-%m-%d %H:%M:%S"), status)
    while True:
        sleep_end_time = time.time()
        ####
        last_activity_time = monitor.last_activity_time
        is_active = (last_activity_time - 0.001 > sleep_start_time
                     and last_activity_time < sleep_end_time)
        inactive_time = sleep_end_time-last_activity_time
        if is_active:
            last_status = status
            status = '==ACTIVE=='
            sleep_time = seconds - inactive_time
        else:
            last_status = status
            status = '==INACTIVE=='
            sleep_time = seconds
            pyautogui.press(key)
        if verbose == 1 and status != last_status:
            print(datetime.fromtimestamp(sleep_end_time).strftime(
                "%Y-%m-%d %H:%M:%S"), status)
        elif verbose == 2:
            print(datetime.fromtimestamp(sleep_end_time).strftime("%Y-%m-%d %H:%M:%S"), status,
                  '\n\tInactive Time:',  f'{inactive_time:.03f}', 'Sleep Time:', f'{sleep_time:.03f}')

        sleep_start_time = time.time()
        time.sleep(sleep_time)
