# bot.py
"""
ИИ-бот для танковой игры без задержек.

Отличия от первой версии:
  * команды шлются на /api/commands с полем "command" (как у tkinter-клиента);
  * /api/state запрашивается БЕЗ after — мгновенный ответ, без long-poll'а;
  * отправка команд и получение состояния идут в двух независимых корутинах;
  * бот применяет свои команды к локальной копии состояния (оптимистично),
    поэтому не ждёт ответа сервера, чтобы принять следующее решение;
  * cooldown между командами снижен до минимальной защиты от дублирования.

Алгоритм:
  1. Ближайший противник — если до него есть путь, идём/стреляем в него.
  2. Иначе — ближайший кирпич: к нему или в него.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Iterable

import aiohttp


BASE_URL = "http://0.0.0.0:8080"
BOT_NAME = "Бот-Разведчик"

# Минимальная защита от двух одинаковых команд в одном такте.
COMMAND_COOLDOWN = 0.05
# Верхняя граница сна между итерациями, если сервер очень медленный.
MAX_SLEEP = 0.20


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
    if not line_of_sight(tiles, src, dst):
        return None
    return direction_between(src, dst)


def bfs_next_step(tiles, start, goals, blocked):
    if start in goals or not goals:
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
            if (nx, ny) in visited or (nx, ny) in blocked:
                continue
            if tiles[ny][nx] not in PASSABLE_TILES:
                continue
            if (nx, ny) in goals:
                return first_dir or name
            visited.add((nx, ny))
            queue.append(((nx, ny), first_dir or name))
    return None


def nearest_enemy(me, enemies):
    if not enemies:
        return None
    mx, my = me["x"], me["y"]
    return min(enemies, key=lambda e: (e["x"] - mx) ** 2 + (e["y"] - my) ** 2)


def cells_next_to(target_cell, tiles, blocked, exclude=None) -> set:
    result = set()
    tx, ty = target_cell
    for _, (dx, dy) in DIRECTIONS.items():
        cell = (tx + dx, ty + dy)
        if exclude is not None and cell == exclude:
            continue
        if tile_at(tiles, *cell) in PASSABLE_TILES and cell not in blocked:
            result.add(cell)
    return result


def cells_on_line_with(target_cell, tiles, blocked, exclude=None) -> set:
    """
    Проходимые клетки, с которых target_cell виден по оси.
    Останавливаемся на первом блокере — это и есть естественная граница видимости.
    """
    result = set()
    tx, ty = target_cell
    height = len(tiles)
    width = len(tiles[0])
    for _, (dx, dy) in DIRECTIONS.items():
        x, y = tx + dx, ty + dy
        while 0 <= x < width and 0 <= y < height:
            tile = tiles[y][x]
            if tile in BLOCKING_TILES:
                break
            if tile in PASSABLE_TILES and (x, y) not in blocked:
                if exclude is None or (x, y) != exclude:
                    result.add((x, y))
            x += dx
            y += dy
    return result


def path_to_any_goal(tiles, start, goals, blocked):
    if not goals:
        return False, None
    if start in goals:
        return True, None
    step = bfs_next_step(tiles, start, goals, blocked - {start})
    if step is None:
        return False, None
    return True, step


# ---------------------------------------------------------------------------
# Локальная модель состояния
# ---------------------------------------------------------------------------
class LocalState:
    """
    Копия серверного состояния + учёт ещё не подтверждённых команд.
    Позволяет боту принимать решения без ожидания ответа сервера.
    """

    __slots__ = ("raw", "me", "enemies", "tiles", "blocked", "bricks",
                 "last_server_version", "my_id")

    def __init__(self):
        self.raw = None
        self.me = None
        self.enemies: list = []
        self.tiles: list = []
        self.blocked: set = set()
        self.bricks: list = []
        self.last_server_version = None
        self.my_id: str | None = None

    # ---- подтягиваем с сервера ----------------------------------------
    def update_from_server(self, state: dict, my_name: str) -> None:
        self.raw = state
        self.last_server_version = state.get("state_version")
        map_info = state.get("map") or {}
        self.tiles = map_info.get("tiles") or []

        tanks = state.get("tanks") or []
        me = next(
            (t for t in tanks if t.get("alive") and t.get("name") == my_name),
            None,
        )
        # Если сервер вернул «меня» — используем серверную копию.
        self.me = dict(me) if me is not None else None
        self.my_id = self.me["id"] if self.me else None
        self.enemies = [
            dict(t) for t in tanks
            if t.get("alive") and t.get("id") != self.my_id
        ]
        self.blocked = {
            (int(t["x"]), int(t["y"])) for t in tanks if t.get("alive")
        }
        self.bricks = [
            (x, y)
            for y, row in enumerate(self.tiles)
            for x, tile in enumerate(row)
            if tile == BRICK_TILE
        ]

    # ---- оптимистично применяем свою команду --------------------------
    def apply_command(self, command: str) -> None:
        me = self.me
        if me is None:
            return

        if command in DIRECTIONS:
            if me["direction"] != command:
                me["direction"] = command
            else:
                # Та же логика, что в game.py: если направление совпадает —
                # пробуем сдвинуться на клетку.
                dx, dy = DIRECTIONS[command]
                nx = me["x"] + dx
                ny = me["y"] + dy
                if self._can_occupy(nx, ny, me):
                    me["x"] = nx
                    me["y"] = ny
        elif command == "выстрел":
            # Снаряд не моделируем — сервер пришлёт его в следующем state.
            pass

    def _can_occupy(self, x: float, y: float, me: dict) -> bool:
        radius = 0.29
        for cx in (int(x - radius), int(x + radius)):
            for cy in (int(y - radius), int(y + radius)):
                if not (0 <= cx < len(self.tiles[0])
                        and 0 <= cy < len(self.tiles)):
                    return False
                if self.tiles[cy][cx] in (1, 2, 6):
                    return False
        for other in self.enemies:
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
        self._joined = False

    async def __aenter__(self):
        # Держим одно TCP-соединение; keep-alive по умолчанию.
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
        """Непрерывно тянет состояние с сервера и обновляет локальную копию."""
        while True:
            state = await self._fetch_state()
            if state is not None:
                self.state.update_from_server(state, self.name)
                if not self._joined and self.state.me is not None:
                    self._joined = True
            # Чем быстрее сервер отвечает, тем быстрее цикл.
            await asyncio.sleep(0)

    async def _command_loop(self):
        """Выгребает очередь команд и шлёт их на сервер пачками по одной."""
        while True:
            command = await self._command_queue.get()
            try:
                ok = await self._post_command(command)
                if ok:
                    self._last_command_at = time.monotonic()
                    self._last_command = command
            finally:
                self._command_queue.task_done()

    # -- принятие решений ------------------------------------------------
    def _turn_or_shoot(self, target_cell) -> str | None:
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

    def _choose_command(self) -> str | None:
        me = self.state.me
        if me is None or not self.state.tiles:
            return None

        tiles = self.state.tiles
        my_cell = (int(me["x"]), int(me["y"]))
        blocked = self.state.blocked - {my_cell}

        # ----- 1. Ближайший противник ----------------------------------
        enemy = nearest_enemy(me, self.state.enemies)
        if enemy is not None:
            enemy_cell = (int(enemy["x"]), int(enemy["y"]))
            goals = (
                cells_next_to(enemy_cell, tiles, blocked, exclude=my_cell)
                | cells_on_line_with(enemy_cell, tiles, blocked, exclude=my_cell)
            )
            has_path, step = path_to_any_goal(tiles, my_cell, goals, blocked)
            if has_path:
                cmd = self._turn_or_shoot(enemy_cell)
                if cmd is not None:
                    return cmd
                if step is not None:
                    return step
                # Стоим в goals, но стрелять нельзя — шаг на линию.
                side_goals = cells_on_line_with(
                    enemy_cell, tiles, blocked, exclude=my_cell
                )
                if side_goals:
                    side = bfs_next_step(tiles, my_cell, side_goals, blocked)
                    if side is not None:
                        return side
                return None

        # ----- 2. Ближайший кирпич --------------------------------------
        if not self.state.bricks:
            return None
        brick = min(
            self.state.bricks,
            key=lambda b: abs(b[0] - my_cell[0]) + abs(b[1] - my_cell[1]),
        )
        goals = (
            cells_next_to(brick, tiles, blocked, exclude=my_cell)
            | cells_on_line_with(brick, tiles, blocked, exclude=my_cell)
        )
        has_path, step = path_to_any_goal(tiles, my_cell, goals, blocked)
        if not has_path:
            return None
        cmd = self._turn_or_shoot(brick)
        if cmd is not None:
            return cmd
        if step is not None:
            return step
        side_goals = cells_on_line_with(brick, tiles, blocked, exclude=my_cell)
        if side_goals:
            side = bfs_next_step(tiles, my_cell, side_goals, blocked)
            if side is not None:
                return side
        return None

    def _decide(self):
        """Вызывается синхронно каждый оборот event loop'а."""
        now = time.monotonic()
        if now - self._last_command_at < COMMAND_COOLDOWN:
            return
        if self.state.me is None or self.state.me.get("frozen"):
            return

        command = self._choose_command()
        if command is None:
            return
        # Не дублируем ту же команду в соседних тактах — это ничего не даёт.
        if command == self._last_command and command != "выстрел":
            return

        # Оптимистично применяем к локальной копии СРАЗУ, чтобы следующая
        # итерация принимала решение уже с новым положением/направлением.
        self.state.apply_command(command)
        self._last_command = command
        # Защита от переполнения очереди, если сервер тормозит.
        if self._command_queue.qsize() < 8:
            self._command_queue.put_nowait(command)

    async def _decision_loop(self):
        """Крутится без сна: одна итерация — один шанс на команду."""
        while True:
            try:
                self._decide()
            except Exception as exc:  # никогда не падаем в цикле
                print(f"[bot] decide error: {exc}")
            await asyncio.sleep(0)

    # -- регистрация -----------------------------------------------------
    async def _join_loop(self):
        """Пытается зарегистрироваться, пока не получится (сервер может лежать)."""
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