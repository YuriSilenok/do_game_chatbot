import json
import queue
import threading
import tkinter as tk
import urllib.error
import urllib.request


SERVER_URL = "http://193.124.115.164:8000"
COMMANDS = {
    # Стрелки
    "up": "вверх",
    "down": "вниз",
    "left": "влево",
    "right": "вправо",
    # WASD
    "w": "вверх",
    "s": "вниз",
    "a": "влево",
    "d": "вправо",
    # Огонь
    "space": "выстрел",
}

CONTROL_KEYS = {"up", "down", "left", "right", "w", "a", "s", "d", "space"}

# Русские названия цветов → CSS-цвета (совпадает с game.js).
TANK_COLOR_CSS = {
    "красный":    "#e6194b",
    "зелёный":    "#3cb44b",
    "синий":      "#4363d8",
    "оранжевый":  "#f58231",
    "фиолетовый": "#911eb4",
    "маджента":   "#f032e6",
    "лайм":       "#bfef45",
    "голубой":    "#42d4f4",
    "серый":      "#808080",
}

# Нейтральный фон до подключения / после смерти.
NEUTRAL_BG = "#f0f0f0"
# Цвет текста на цветном фоне.
DARK_TEXT = "#1a1a1a"


def tint(hex_color: str, factor: float = 0.75) -> str:
    """
    Смешивает цвет с белым: factor=0 — исходный, factor=1 — белый.
    Даёт пастельный фон, на котором читается тёмный текст.
    """
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    r = int(r + (255 - r) * factor)
    g = int(g + (255 - g) * factor)
    b = int(b + (255 - b) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


class TankClient:
    def __init__(self, root):
        self.root = root
        self.root.title("Танковый чат: управление")
        self.root.resizable(False, False)

        self.request_queue = queue.Queue()
        self.result_queue = queue.Queue()
        self.stop_worker = threading.Event()
        self.monitor_stop: threading.Event | None = None
        self.pressed_keys = set()
        self.player_name = ""
        self.player_tank_id: str | None = None
        self.connected = False

        # Список виджетов, у которых нужно менять фон.
        self._bg_widgets: list[tk.Widget] = []

        frame = tk.Frame(root, padx=18, pady=16)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="Имя игрока").grid(row=0, column=0, sticky="w")
        self.name_entry = tk.Entry(frame, width=28)
        self.name_entry.grid(row=1, column=0, padx=(0, 8), pady=(4, 12), sticky="ew")
        self.join_button = tk.Button(frame, text="Подключиться", command=self.join)
        self.join_button.grid(row=1, column=1, pady=(4, 12))

        self.control_label = tk.Label(
            frame,
            text="Управление: стрелки / WASD и пробел",
            anchor="w",
        )
        self.control_label.grid(row=2, column=0, columnspan=2, sticky="ew")

        self.status = tk.StringVar(value="Введите имя и подключитесь к общей комнате.")
        self.status_label = tk.Label(
            frame,
            textvariable=self.status,
            anchor="w",
            wraplength=330,
        )
        self.status_label.grid(row=3, column=0, columnspan=2, pady=(10, 0), sticky="ew")

        # Запоминаем все виджеты, фон которых надо красить.
        self._bg_widgets = [frame, self.control_label, self.status_label]

        self.root.bind_all("<KeyPress>", self.on_key_press)
        self.root.bind_all("<KeyRelease>", self.on_key_release)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.worker = threading.Thread(target=self.request_worker, daemon=True)
        self.worker.start()
        self.root.after(100, self.check_results)

    # ------------------------------------------------------------------
    # Фон
    # ------------------------------------------------------------------
    def _apply_background(self, bg: str, fg: str = DARK_TEXT) -> None:
        """Красит корень и все внутренние виджеты (кроме Entry — у него свой)."""
        self.root.configure(bg=bg)
        for widget in self._bg_widgets:
            try:
                widget.configure(bg=bg, fg=fg)
            except tk.TclError:
                pass
        # Entry и Button оставляем системного вида, но подкрашиваем кнопку.
        try:
            self.join_button.configure(
                bg=bg,
                activebackground=bg,
                fg=fg,
                activeforeground=fg,
            )
        except tk.TclError:
            pass

    def _set_color(self, russian_color: str | None) -> None:
        """Применяет пастельный фон под русское название цвета."""
        if russian_color is None:
            self._apply_background(NEUTRAL_BG, "#000000")
            return
        css = TANK_COLOR_CSS.get(russian_color)
        if css is None:
            self._apply_background(NEUTRAL_BG, "#000000")
            return
        self._apply_background(tint(css, factor=0.75), DARK_TEXT)

    # ------------------------------------------------------------------
    def join(self):
        name = self.name_entry.get().strip()
        if not name:
            self.status.set("Введите имя игрока.")
            return
        if len(name) > 40:
            self.status.set("Имя должно быть не длиннее 40 символов.")
            return

        self.player_name = name
        self.join_button.configure(state="disabled")
        self.status.set("Подключение...")
        self.request_queue.put(("join", {"name": name}))

    # ------------------------------------------------------------------
    def _stop_monitor(self):
        if self.monitor_stop is not None:
            self.monitor_stop.set()
            self.monitor_stop = None

    def request_worker(self):
        while not self.stop_worker.is_set():
            try:
                action, payload = self.request_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            endpoint = "/api/join" if action == "join" else "/api/commands"
            request = urllib.request.Request(
                f"{SERVER_URL}{endpoint}",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=6) as response:
                    body = response.read()
                details = json.loads(body.decode("utf-8")) if body else {}
                self.result_queue.put((action, True, details if action == "join" else ""))
            except urllib.error.HTTPError as error:
                body = error.read().decode("utf-8", errors="replace")
                try:
                    detail = json.loads(body).get("detail", body)
                except json.JSONDecodeError:
                    detail = body
                self.result_queue.put((action, False, detail or str(error)))
            except Exception as error:
                self.result_queue.put((action, False, str(error)))
            finally:
                self.request_queue.task_done()

    # ------------------------------------------------------------------
    def check_results(self):
        try:
            while True:
                action, success, detail = self.result_queue.get_nowait()
                if action == "join":
                    if success:
                        tank_id = detail.get("your_tank_id")
                        if not tank_id:
                            self.join_button.configure(state="normal")
                            self.status.set("Сервер не вернул идентификатор танка.")
                            continue
                        self._stop_monitor()
                        self.connected = True
                        self.player_tank_id = tank_id
                        self.name_entry.configure(state="disabled")
                        self.root.focus_set()
                        self.status.set(f"Подключено как {self.player_name}.")
                        # Меняем фон под цвет танка.
                        self._set_color(detail.get("your_color"))
                        self.monitor_stop = threading.Event()
                        threading.Thread(
                            target=self.watch_tank,
                            args=(tank_id, self.monitor_stop),
                            daemon=True,
                        ).start()
                    else:
                        self.join_button.configure(state="normal")
                        self.status.set(f"Не удалось подключиться: {detail}")
                elif action == "dead":
                    self.connected = False
                    self.player_tank_id = None
                    self.pressed_keys.clear()
                    self.name_entry.configure(state="normal")
                    self.join_button.configure(state="normal")
                    self.status.set(detail)
                    # Сбрасываем фон на нейтральный.
                    self._set_color(None)
                elif action == "sleeping":
                    self.status.set(detail)
                elif not success:
                    self.status.set(f"Ошибка отправки команды: {detail}")
        except queue.Empty:
            pass
        if not self.stop_worker.is_set():
            self.root.after(100, self.check_results)

    # ------------------------------------------------------------------
    def watch_tank(self, tank_id, stop_event):
        state_version = None
        missed = 0
        while not stop_event.is_set():
            after = "" if state_version is None else f"?after={state_version}"
            request = urllib.request.Request(f"{SERVER_URL}/api/state{after}")
            try:
                with urllib.request.urlopen(request, timeout=40) as response:
                    state = json.loads(response.read().decode("utf-8"))
                state_version = state["state_version"]
                tank = next(
                    (t for t in state["tanks"] if t["id"] == tank_id),
                    None,
                )
                if tank is None:
                    self.result_queue.put((
                        "dead",
                        True,
                        "Ваш танк уничтожен. Вы отключены от игры. Нажмите «Подключиться», чтобы войти снова.",
                    ))
                    return
                if tank["is_bot"] and self.connected:
                    self.result_queue.put((
                        "sleeping",
                        True,
                        "Вы не двигались 30 с — за вас играет бот. Нажмите любую клавишу управления, чтобы вернуть контроль.",
                    ))
                missed = 0
            except Exception:
                missed += 1
                if missed >= 5:
                    self.result_queue.put((
                        "dead",
                        True,
                        "Связь с сервером потеряна. Нажмите «Подключиться», чтобы войти снова.",
                    ))
                    return
                if stop_event.wait(1):
                    return

    # ------------------------------------------------------------------
    def on_key_press(self, event):
        key = event.keysym.lower()
        command = COMMANDS.get(key)
        if command is None:
            return
        if self.root.focus_get() == self.name_entry:
            return
        if not self.connected:
            return
        if key in self.pressed_keys:
            return "break"
        self.pressed_keys.add(key)
        self.request_queue.put((
            "command",
            {"sender": self.player_name, "command": command},
        ))
        return "break"

    def on_key_release(self, event):
        key = event.keysym.lower()
        if key in CONTROL_KEYS:
            self.pressed_keys.discard(key)
            return "break"

    # ------------------------------------------------------------------
    def close(self):
        self.stop_worker.set()
        self._stop_monitor()
        self.root.destroy()


def main():
    root = tk.Tk()
    TankClient(root)
    root.mainloop()


if __name__ == "__main__":
    main()