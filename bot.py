# bot.py
"""
Агрессивный ИИ-бот: охотится за ЛИДЕРОМ по убийствам.

Логика:
  * Цель — живой ИГРОК с максимальным kills.
  * При равенстве kills — ближайший к боту.
  * Если живых игроков нет — бот стоит.
  * Игрок на линии видимости → разворот и выстрел.
  * Иначе — кирпич на прямой → пробиваем.
  * Иначе — BFS прямо к клетке цели.
  * Если путь к клетке цели закрыт (например, другим ботом) —
    идём к соседней с целью клетке.

Технически:
  * /api/state без after — мгновенный ответ, без long-poll.
  * Команды в отдельной корутине, отправка не блокирует принятие решений.
  * Оптимистичное применение команды к локальной копии — не ждём сервера.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque

import aiohttp


BASE_URL = "http://0.0.0.0:8080"
BOT_NAME = "Бот-Охотник"

# Защита от дублирования в одном такте. Меньше — быстрее реакция.
COMMAND_COOLDOWN = 0.03


DIRECTIONS = {
    "вверх": (0, -1),
    "вниз": (0, 1),
    "влево": (-1, 0),
    "вправо": (1, 0),
}

BLOCKING_TILES = {1, 2, 4, 6}
PASSABLE_TILES = {0, 3, 5}
BRICK_TILE = 1


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------
def tile_at(tiles, x: int, y: int):
    if 0 <= y < len(tiles) and 0 <= x < len(tiles[0]):
        return tiles[y][x]
    return None


def line_of_sight(tiles, first, second) -> bool:
    x1, y1 = first
    x2, y2 = second
    x_start, y_start = x1 + 0.5, y1 + 0.5
    x_end, y_end = x2 + 0.5, y2 + 0.5
    samples = max(abs(x2 - x1), abs(y2 - y1)) * 20
    if samples == 0:
        return True
    for step in range(1, int(samples)):
        x = int(x_start + (x_end - x_start) * step / samples)
        y = int(y_start + (y_end - y_start) * step / samples)
        if tile_at(tiles, x, y) in BLOCKING_TILES:
            return False
    return True


def direction_between(src, dst):
    dx = dst[0] - src[0]
    dy = dst[1] - src[1]
    if dx == 0 and dy != 0:
        return "вниз" if dy > 0 else "вверх"
    if dy == 0 and dx != 0:
        return "вправо" if dx > 0 else "влево"
    return None


def shoot_direction(tiles, src, dst):
    """Направление выстрела, если цель на линии и видна."""
    if not line_of_sight(tiles, src, dst):
        return None
    return direction_between(src, dst)


def bfs_path(tiles, start, goal, blocked):
    """
    BFS от start до goal. Возвращает первое направление шага или None.
    Кирпичи в blocked не входят — их можно пробивать.
    """
    if start == goal:
        return None
    height = len(tiles)
    width = len(tiles[0])
    queue = deque([(start, None)])
    visited = {start}
    while queue:
        (x, y), first_dir = queue.popleft()
        for name, (dx, dy) in DIRECTIONS.items():
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            if (nx, ny) in visited:
                continue
            if (nx, ny) in blocked:
                continue
            if tiles[ny][nx] not in PASSABLE_TILES:
                continue
            if (nx, ny) == goal:
                return first_dir or name
            visited.add((nx, ny))
            queue.append(((nx, ny), first_dir or name))
    return None


def bfs_next_step_any(tiles, start, goals, blocked):
    """BFS до любой из goals. Возвращает (step, reached)."""
    if not goals:
        return None, False
    if start in goals:
        return None, True
    height = len(tiles)
    width = len(tiles[0])
    queue = deque([(start, None)])
    visited = {start}
    while queue:
        (x, y), first_dir = queue.popleft()
        for name, (dx, dy) in DIRECTIONS.items():
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            if (nx, ny) in visited or (nx, ny) in blocked:
                continue
            if tiles[ny][nx] not in PASSABLE_TILES:
                continue
            if (nx, ny) in goals:
                return first_dir or name, True
            visited.add((nx, ny))
            queue.append(((nx, ny), first_dir or name))
    return None, False


def dist2(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


# ---------------------------------------------------------------------------
# Локальная модель состояния
# ---------------------------------------------------------------------------
class LocalState:
    __slots__ = ("raw", "me", "enemies", "tiles", "blocked", "my_id",
                 "last_server_version", "kills_map")

    def __init__(self):
        self.raw = None
        self.me = None
        self.enemies = []          # ТОЛЬКО живые игроки (не боты)
        self.tiles = []
        self.blocked = set()       # все живые танки (кроме меня)
        self.my_id: str | None = None
        self.last_server_version = None
        self.kills_map: dict[str, int] = {}

    def update_from_server(self, state: dict, my_name: str) -> None:
        self.raw = state
        self.last_server_version = state.get("state_version")
        map_info = state.get("map") or {}
        self.tiles = map_info.get("tiles") or []

        # Карта убийств {name: kills} — сервер уже отдаёт только игроков.
        self.kills_map = dict(state.get("kills") or {})

        tanks = state.get("tanks") or []
        me = next(
            (t for t in tanks
             if t.get("alive") and t.get("name") == my_name),
            None,
        )
        self.me = dict(me) if me is not None else None
        self.my_id = self.me["id"] if self.me else None

        # ЦЕЛИ: только живые ИГРОКИ. Боты и «уснувшие» игроки игнорируются.
        enemies = []
        for t in tanks:
            if not t.get("alive"):
                continue
            if t.get("id") == self.my_id:
                continue
            if t.get("is_bot"):
                continue
            copy = dict(t)
            copy["kills"] = self.kills_map.get(t.get("name"), 0)
            enemies.append(copy)
        self.enemies = enemies

        # Препятствия для BFS: все живые танки, кроме меня.
        self.blocked = {
            (int(t["x"]), int(t["y"]))
            for t in tanks
            if t.get("alive") and t.get("id") != self.my_id
        }

    def apply_command(self, command: str) -> None:
        """Оптимистично применяем свою команду к локальной копии."""
        me = self.me
        if me is None:
            return
        if command in DIRECTIONS:
            if me["direction"] != command:
                me["direction"] = command
            else:
                dx, dy = DIRECTIONS[command]
                nx, ny = me["x"] + dx, me["y"] + dy
                if self._can_occupy(nx, ny):
                    me["x"] = nx
                    me["y"] = ny
        # "выстрел" не моделируем.

    def _can_occupy(self, x: float, y: float) -> bool:
        radius = 0.29
        for cx in (int(x - radius), int(x + radius)):
            for cy in (int(y - radius), int(y + radius)):
                if not (0 <= cx < len(self.tiles[0])
                        and 0 <= cy < len(self.tiles)):
                    return False
                if self.tiles[cy][cx] in (1, 2, 6):
                    return False
        for other in self.raw.get("tanks", []):
            if not other.get("alive") or other.get("id") == self.my_id:
                continue
            if abs(other["x"] - x) < 0.58 and abs(other["y"] - y) < 0.58:
                return False
        return True


# ---------------------------------------------------------------------------
# Клиент игры
# ---------------------------------------------------------------------------
class BotClient:
    def __init__(self, base_url: str, name: str):
        self.base_url = base_url.rstrip("/")
        self.name = name
        self.session: aiohttp.ClientSession | None = None
        self.state = LocalState()

        self._command_queue: asyncio.Queue[str] = asyncio.Queue()
        self._last_command_at = 0.0
        self._last_command: str | None = None

    async def __aenter__(self):
        connector = aiohttp.TCPConnector(limit=8, ttl_dns_cache=300)
        self.session = aiohttp.ClientSession(connector=connector)
        return self

    async def __aexit__(self, *exc_info):
        if self.session:
            await self.session.close()

    # -- HTTP ------------------------------------------------------------
    async def _fetch_state(self) -> dict | None:
        try:
            async with self.session.get(
                f"{self.base_url}/api/state",
                headers={"Accept": "application/json"},
            ) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()
        except Exception:
            return None

    async def _post_command(self, command: str) -> bool:
        payload = {"sender": self.name, "command": command}
        try:
            async with self.session.post(
                f"{self.base_url}/api/commands", json=payload
            ) as resp:
                return resp.status in (200, 201)
        except Exception:
            return False

    async def _join(self) -> bool:
        try:
            async with self.session.post(
                f"{self.base_url}/api/join", json={"name": self.name}
            ) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                self.state.my_id = data.get("your_tank_id")
                return bool(self.state.my_id)
        except Exception:
            return False

    # -- корутины ---------------------------------------------------------
    async def _state_loop(self):
        while True:
            state = await self._fetch_state()
            if state is not None:
                self.state.update_from_server(state, self.name)
            await asyncio.sleep(0)

    async def _command_loop(self):
        while True:
            command = await self._command_queue.get()
            try:
                if await self._post_command(command):
                    self._last_command_at = time.monotonic()
                    self._last_command = command
            finally:
                self._command_queue.task_done()

    # -- принятие решений ------------------------------------------------
    def _target(self):
        """
        Цель — живой игрок с максимумом убийств.
        При равенстве kills — ближайший к боту.
        """
        me = self.state.me
        if me is None or not self.state.enemies:
            return None
        mx, my = me["x"], me["y"]
        return min(
            self.state.enemies,
            key=lambda e: (-int(e.get("kills", 0)),
                           (e["x"] - mx) ** 2 + (e["y"] - my) ** 2),
        )

    def _shoot_at(self, target_cell) -> str | None:
        me = self.state.me
        if me is None:
            return None
        my_cell = (int(me["x"]), int(me["y"]))
        shoot_dir = shoot_direction(self.state.tiles, my_cell, target_cell)
        if shoot_dir is None:
            return None
        if me["direction"] != shoot_dir:
            return shoot_dir
        return "выстрел"

    def _blocking_brick_toward(self, enemy_cell) -> str | None:
        """
        Если между мной и целью по оси стоит кирпич — вернуть направление
        для выстрела в него. Иначе None.
        """
        me = self.state.me
        if me is None:
            return None
        my_cell = (int(me["x"]), int(me["y"]))
        tiles = self.state.tiles

        for direction, (dx, dy) in DIRECTIONS.items():
            x, y = my_cell
            while True:
                x += dx
                y += dy
                if not (0 <= x < len(tiles[0]) and 0 <= y < len(tiles)):
                    break
                tile = tiles[y][x]
                if tile == BRICK_TILE:
                    ex, ey = enemy_cell
                    if (dx > 0 and ex > x) or (dx < 0 and ex < x) \
                            or (dy > 0 and ey > y) or (dy < 0 and ey < y):
                        if me["direction"] != direction:
                            return direction
                        return "выстрел"
                    break
                if tile in BLOCKING_TILES - {BRICK_TILE}:
                    break
        return None

    def _choose_command(self) -> str | None:
        me = self.state.me
        if me is None or not self.state.tiles:
            return None

        tiles = self.state.tiles
        my_cell = (int(me["x"]), int(me["y"]))

        enemy = self._target()
        if enemy is None:
            # Нет живых игроков — стоим.
            return None

        enemy_cell = (int(enemy["x"]), int(enemy["y"]))

        # 1. Цель на линии — стреляем.
        cmd = self._shoot_at(enemy_cell)
        if cmd is not None:
            return cmd

        # 2. Кирпич на прямой к цели — пробиваем.
        cmd = self._blocking_brick_toward(enemy_cell)
        if cmd is not None:
            return cmd

        # 3. Идём к цели напрямую.
        blocked = self.state.blocked - {my_cell}
        step = bfs_path(tiles, my_cell, enemy_cell, blocked)
        if step is not None:
            return step

        # 4. Прямой путь закрыт — идём к клетке рядом с целью.
        goals = set()
        for _, (dx, dy) in DIRECTIONS.items():
            cell = (enemy_cell[0] + dx, enemy_cell[1] + dy)
            if tile_at(tiles, *cell) in PASSABLE_TILES and cell not in blocked:
                goals.add(cell)
        step, _ = bfs_next_step_any(tiles, my_cell, goals, blocked)
        return step

    def _decide(self):
        now = time.monotonic()
        if now - self._last_command_at < COMMAND_COOLDOWN:
            return
        me = self.state.me
        if me is None or me.get("frozen"):
            return
        if not self.state.enemies:
            return

        command = self._choose_command()
        if command is None:
            return
        if command == self._last_command and command != "выстрел":
            return

        self.state.apply_command(command)
        self._last_command = command
        if self._command_queue.qsize() < 8:
            self._command_queue.put_nowait(command)

    async def _decision_loop(self):
        while True:
            try:
                self._decide()
            except Exception as exc:
                print(f"[bot] decide error: {exc}")
            await asyncio.sleep(0)

    # -- регистрация -----------------------------------------------------
    async def _join_loop(self):
        while True:
            if await self._join():
                print(f"[bot] Зарегистрирован как {self.name}")
                return
            print("[bot] Регистрация не удалась, повтор через 1 с")
            await asyncio.sleep(1)

    # -- запуск ----------------------------------------------------------
    async def run(self):
        await self._join_loop()
        await asyncio.gather(
            self._state_loop(),
            self._command_loop(),
            self._decision_loop(),
        )


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------
async def main():
    async with BotClient(BASE_URL, BOT_NAME) as bot:
        await bot.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[bot] Остановлен.")