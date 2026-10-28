# bot.py
"""
Максимально агрессивный ИИ-бот на A*.

Принципы:
  1. Цель — живой игрок с максимумом убийств (лидер). Если лидер умер —
     мгновенное переключение на следующего.
  2. Если цель в зоне видимости — разворот и выстрел, БЕЗ ходьбы.
  3. Иначе — A* до клетки цели. Кирпичи включены в граф со штрафом:
     A* сам решит, пробивать стену или обойти.
  4. Если A* вернул шаг в стену — бот разворачивается и стреляет.
  5. Если шаг не меняет клетку (застрял) — повторный A* с более
     высоким штрафом за кирпичи принудительно ищет обход.
  6. Все команды идут через очередь; состояние обновляется непрерывно.
"""

from __future__ import annotations

import asyncio
import heapq
import time
from typing import Optional

import aiohttp


BASE_URL = "http://0.0.0.0:8080"
BOT_NAME = "Бот-Охотник"

# Минимальная защита от дублирования. Чем меньше — тем быстрее реакция.
COMMAND_COOLDOWN = 0.02
# Штраф за проход через клетку с кирпичом в A*.
BRICK_COST = 6
# Дополнительный штраф, если бот «застрял» (шаг не изменил клетку).
STUCK_EXTRA_BRICK_COST = 20


DIRECTIONS = {
    "вверх": (0, -1),
    "вниз": (0, 1),
    "влево": (-1, 0),
    "вправо": (1, 0),
}

BLOCKING_TILES = {1, 2, 4, 6}     # блокируют обзор и движение
PASSABLE_TILES = {0, 3, 5}        # обычные проходимые
BRICK_TILE = 1
WATER_TILE = 4
STEEL_TILE = 2
CONCRETE_TILE = 6


# ---------------------------------------------------------------------------
# Базовые помощники
# ---------------------------------------------------------------------------
def tile_at(tiles, x: int, y: int) -> Optional[int]:
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


def direction_between(src, dst) -> Optional[str]:
    dx = dst[0] - src[0]
    dy = dst[1] - src[1]
    if dx == 0 and dy != 0:
        return "вниз" if dy > 0 else "вверх"
    if dy == 0 and dx != 0:
        return "вправо" if dx > 0 else "влево"
    return None


def shoot_direction(tiles, src, dst) -> Optional[str]:
    if not line_of_sight(tiles, src, dst):
        return None
    return direction_between(src, dst)


def manhattan(a, b) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


# ---------------------------------------------------------------------------
# A* поиск пути
# ---------------------------------------------------------------------------
def a_star_next_step(
    tiles,
    start: tuple[int, int],
    goal: tuple[int, int],
    blocked: set[tuple[int, int]],
    brick_cost: int = BRICK_COST,
    max_nodes: int = 2000,
) -> Optional[str]:
    """
    A* от start до goal.

    Проходимые клетки: 0, 3, 5 — стоимость 1.
    Кирпич (1) — проходим за brick_cost (по умолчанию 6).
    Сталь (2), вода (4), бетон (6) — непроходимы.
    Клетки из blocked (другие танки) — непроходимы (обход).
    start/goal исключаются из blocked на стороне вызова.

    Возвращает первое направление шага или None.
    """
    if start == goal:
        return None

    h = len(tiles)
    w = len(tiles[0])

    # Очередь: (f, tie, g, cell, first_dir)
    open_heap: list[tuple[int, int, int, tuple[int, int], Optional[str]]] = []
    counter = 0
    g_score: dict[tuple[int, int], int] = {start: 0}
    heapq.heappush(
        open_heap,
        (manhattan(start, goal), counter, 0, start, None),
    )

    closed: set[tuple[int, int]] = set()
    nodes = 0

    while open_heap:
        f, _, g, cell, first_dir = heapq.heappop(open_heap)
        if cell == goal:
            return first_dir
        if cell in closed:
            continue
        closed.add(cell)
        nodes += 1
        if nodes > max_nodes:
            return None

        x, y = cell
        for name, (dx, dy) in DIRECTIONS.items():
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            if (nx, ny) in closed:
                continue

            tile = tiles[ny][nx]
            # Непроходимые
            if tile in (STEEL_TILE, WATER_TILE, CONCRETE_TILE):
                continue
            # Другие танки
            if (nx, ny) in blocked and (nx, ny) != goal:
                continue

            # Стоимость входа в клетку
            if tile == BRICK_TILE:
                step_cost = brick_cost
            elif tile in PASSABLE_TILES:
                step_cost = 1
            else:
                continue

            tentative_g = g + step_cost
            if tentative_g < g_score.get((nx, ny), 10 ** 9):
                g_score[(nx, ny)] = tentative_g
                counter += 1
                f = tentative_g + manhattan((nx, ny), goal)
                next_first = first_dir if first_dir is not None else name
                heapq.heappush(
                    open_heap,
                    (f, counter, tentative_g, (nx, ny), next_first),
                )
    return None


# ---------------------------------------------------------------------------
# Локальная модель
# ---------------------------------------------------------------------------
class LocalState:
    __slots__ = ("raw", "me", "enemies", "tiles", "blocked", "my_id",
                 "last_server_version", "kills_map")

    def __init__(self):
        self.raw = None
        self.me = None
        self.enemies = []
        self.tiles: list[list[int]] = []
        self.blocked: set[tuple[int, int]] = set()
        self.my_id: Optional[str] = None
        self.last_server_version = None
        self.kills_map: dict[str, int] = {}

    def update_from_server(self, state: dict, my_name: str) -> None:
        self.raw = state
        self.last_server_version = state.get("state_version")
        self.tiles = (state.get("map") or {}).get("tiles") or []
        self.kills_map = dict(state.get("kills") or {})

        tanks = state.get("tanks") or []
        me = next(
            (t for t in tanks if t.get("alive") and t.get("name") == my_name),
            None,
        )
        self.me = dict(me) if me is not None else None
        self.my_id = self.me["id"] if self.me else None

        enemies = []
        for t in tanks:
            if not t.get("alive") or t.get("id") == self.my_id or t.get("is_bot"):
                continue
            copy = dict(t)
            copy["kills"] = self.kills_map.get(t.get("name"), 0)
            enemies.append(copy)
        self.enemies = enemies

        self.blocked = {
            (int(t["x"]), int(t["y"]))
            for t in tanks
            if t.get("alive") and t.get("id") != self.my_id
        }

    def apply_command(self, command: str) -> None:
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
                    me["x"], me["y"] = nx, ny

    def _can_occupy(self, x: float, y: float) -> bool:
        radius = 0.29
        for cx in (int(x - radius), int(x + radius)):
            for cy in (int(y - radius), int(y + radius)):
                if not (0 <= cx < len(self.tiles[0]) and 0 <= cy < len(self.tiles)):
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
# Клиент
# ---------------------------------------------------------------------------
class BotClient:
    def __init__(self, base_url: str, name: str):
        self.base_url = base_url.rstrip("/")
        self.name = name
        self.session: Optional[aiohttp.ClientSession] = None
        self.state = LocalState()

        self._command_queue: asyncio.Queue[str] = asyncio.Queue()
        self._last_command_at = 0.0
        self._last_command: Optional[str] = None
        # Запоминаем, в какой клетке стояли в прошлом такте — для детекта «застрял».
        self._last_cell: Optional[tuple[int, int]] = None
        # Текущая цель (name игрока) — чтобы не переключаться из-за кадров.
        self._sticky_target_name: Optional[str] = None
        # Счётчик подряд застрявших шагов.
        self._stuck: int = 0

    async def __aenter__(self):
        connector = aiohttp.TCPConnector(limit=8, ttl_dns_cache=300)
        self.session = aiohttp.ClientSession(connector=connector)
        return self

    async def __aexit__(self, *exc_info):
        if self.session:
            await self.session.close()

    # -- HTTP ------------------------------------------------------------
    async def _fetch_state(self):
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
        try:
            async with self.session.post(
                f"{self.base_url}/api/commands",
                json={"sender": self.name, "command": command},
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

    # -- выбор цели ------------------------------------------------------
    def _pick_target(self):
        """Лидер по убийствам; при равенстве — ближайший. Sticky."""
        if not self.state.enemies:
            self._sticky_target_name = None
            return None
        me = self.state.me
        if me is None:
            return None

        # Если sticky-цель жива и всё ещё лидер — оставляем её.
        if self._sticky_target_name is not None:
            same = [e for e in self.state.enemies
                    if e["name"] == self._sticky_target_name]
            if same:
                # проверяем, что никто не обогнал по kills
                max_kills = max(int(e.get("kills", 0)) for e in self.state.enemies)
                if int(same[0].get("kills", 0)) >= max_kills:
                    return same[0]

        mx, my = me["x"], me["y"]
        target = min(
            self.state.enemies,
            key=lambda e: (
                -int(e.get("kills", 0)),
                (e["x"] - mx) ** 2 + (e["y"] - my) ** 2,
            ),
        )
        self._sticky_target_name = target["name"]
        return target

    # -- проверка линии видимости ---------------------------------------
    def _shoot_at(self, target_cell):
        me = self.state.me
        if me is None:
            return None
        my_cell = (int(me["x"]), int(me["y"]))
        d = shoot_direction(self.state.tiles, my_cell, target_cell)
        if d is None:
            return None
        if me["direction"] != d:
            return d
        return "выстрел"

    # -- путь -----------------------------------------------------------
    def _path_step(self, target_cell):
        me = self.state.me
        if me is None:
            return None
        my_cell = (int(me["x"]), int(me["y"]))
        blocked = self.state.blocked - {my_cell}

        # Обычный A*: кирпичи можно ломать, но с штрафом.
        step = a_star_next_step(
            self.state.tiles,
            my_cell,
            target_cell,
            blocked,
            brick_cost=BRICK_COST,
        )
        if step is not None:
            return step

        # Если A* не нашёл маршрут — принудительно обходить стены.
        # Увеличиваем штраф, чтобы A* искал длинный, но проходимый путь.
        step = a_star_next_step(
            self.state.tiles,
            my_cell,
            target_cell,
            blocked,
            brick_cost=STUCK_EXTRA_BRICK_COST,
            max_nodes=3000,
        )
        return step

    def _should_shoot_brick(self, step: str, target_cell) -> bool:
        """
        Если A* вернул шаг, но соседняя клетка — кирпич, выгоднее
        выстрелить в него, а не биться. Возвращает True, если шаг
        ведёт в кирпич.
        """
        me = self.state.me
        if me is None:
            return False
        dx, dy = DIRECTIONS[step]
        nx, ny = int(me["x"]) + dx, int(me["y"]) + dy
        tile = tile_at(self.state.tiles, nx, ny)
        return tile == BRICK_TILE

    # -- главное решение ------------------------------------------------
    def _choose_command(self) -> Optional[str]:
        me = self.state.me
        if me is None or not self.state.tiles:
            return None

        target = self._pick_target()
        if target is None:
            return None

        target_cell = (int(target["x"]), int(target["y"]))
        my_cell = (int(me["x"]), int(me["y"]))

        # 1. Линия видимости — поворот/выстрел без ходьбы.
        cmd = self._shoot_at(target_cell)
        if cmd is not None:
            return cmd

        # 2. Стоим рядом с целью, но не на линии — пробуем шагнуть на линию.
        if my_cell == target_cell:
            # Стоим буквально на клетке цели (танк на танке) — выстрел
            # в сторону ближайшей свободной линии.
            for direction in DIRECTIONS:
                dx, dy = DIRECTIONS[direction]
                if tile_at(self.state.tiles, target_cell[0] + dx, target_cell[1] + dy) in PASSABLE_TILES:
                    return direction
            return "выстрел"

        # 3. A* до клетки цели.
        step = self._path_step(target_cell)

        # 4. Если шаг ведёт в кирпич — стреляем в него.
        if step is not None and self._should_shoot_brick(step, target_cell):
            if me["direction"] != step:
                return step
            return "выстрел"

        if step is not None:
            return step

        # 5. Совсем нет маршрута — палим в ближайшую стену по оси цели.
        for direction, (dx, dy) in DIRECTIONS.items():
            x, y = my_cell
            while True:
                x += dx
                y += dy
                if not (0 <= x < len(self.state.tiles[0]) and 0 <= y < len(self.state.tiles)):
                    break
                tile = self.state.tiles[y][x]
                if tile == BRICK_TILE:
                    return direction if me["direction"] != direction else "выстрел"
                if tile in (STEEL_TILE, WATER_TILE, CONCRETE_TILE):
                    break
        return None

    # -- основной шаг ----------------------------------------------------
    def _decide(self):
        now = time.monotonic()
        if now - self._last_command_at < COMMAND_COOLDOWN:
            return
        me = self.state.me
        if me is None or me.get("frozen"):
            return
        if not self.state.enemies:
            return

        # Детект «застрял»: если в прошлом такте клетка не изменилась.
        cur_cell = (int(me["x"]), int(me["y"]))
        if self._last_cell is not None and cur_cell == self._last_cell:
            self._stuck += 1
        else:
            self._stuck = 0
        self._last_cell = cur_cell

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