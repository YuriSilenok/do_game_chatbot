import json
import queue
import threading
import tkinter as tk
import urllib.error
import urllib.request


SERVER_URL = "http://193.124.115.164:8000"
COMMANDS = {
    "up": "вверх",
    "down": "вниз",
    "left": "влево",
    "right": "вправо",
    "space": "выстрел",
}


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

        frame = tk.Frame(root, padx=18, pady=16)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="Имя игрока").grid(row=0, column=0, sticky="w")
        self.name_entry = tk.Entry(frame, width=28)
        self.name_entry.grid(row=1, column=0, padx=(0, 8), pady=(4, 12), sticky="ew")
        self.join_button = tk.Button(frame, text="Подключиться", command=self.join)
        self.join_button.grid(row=1, column=1, pady=(4, 12))

        tk.Label(frame, text="Управление: стрелки и пробел", anchor="w").grid(
            row=2, column=0, columnspan=2, sticky="ew"
        )
        self.status = tk.StringVar(value="Введите имя и подключитесь к общей комнате.")
        tk.Label(frame, textvariable=self.status, anchor="w", wraplength=330).grid(
            row=3, column=0, columnspan=2, pady=(10, 0), sticky="ew"
        )

        self.root.bind_all("<KeyPress>", self.on_key_press)
        self.root.bind_all("<KeyRelease>", self.on_key_release)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.worker = threading.Thread(target=self.request_worker, daemon=True)
        self.worker.start()
        self.root.after(100, self.check_results)

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
                elif action == "sleeping":
                    # Игрок стал ботом по простою — не отключаем, только сообщаем.
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
                # Таймаут 40 с: сервер отпускает long-poll через 25 с,
                # но подстрахуемся на случай медленного канала.
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
                # Не спамим — при 5 подряд ошибках считаем связь потерянной.
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
        if command is None or not self.connected:
            return
        if self.root.focus_get() == self.name_entry:
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
        if key in COMMANDS:
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