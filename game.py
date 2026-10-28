from __future__ import annotations

import math
import random
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Literal


MAP_TEMPLATE = [
    [2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2],
    [2, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 1, 0, 0, 2],
    [2, 0, 1, 1, 0, 2, 0, 1, 0, 1, 1, 0, 0, 0, 0, 1, 1, 0, 2, 0, 2, 0, 1, 1, 0, 2],
    [2, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 2],
    [2, 1, 0, 2, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0, 1, 0, 2, 0, 0, 0, 0, 0, 2, 0, 1, 2],
    [2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 2],
    [2, 0, 1, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0, 1, 2, 0, 2],
    [2, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 2],
    [2, 1, 0, 1, 0, 0, 0, 0, 0, 2, 0, 1, 0, 0, 1, 0, 2, 0, 0, 0, 0, 0, 2, 0, 1, 2],
    [2, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 2],
    [2, 0, 1, 1, 0, 2, 0, 2, 0, 1, 1, 0, 0, 0, 0, 1, 1, 0, 2, 0, 2, 0, 1, 1, 0, 2],
    [2, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 2],
    [2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2],
]

MAP_WIDTH = len(MAP_TEMPLATE[0])
MAP_HEIGHT = len(MAP_TEMPLATE)

COMMANDS = {"вверх", "вниз", "влево", "вправо", "выстрел"}
DIRECTIONS = {
    "вверх": (0, -1),
    "вниз": (0, 1),
    "влево": (-1, 0),
    "вправо": (1, 0),
}
TILE_SIZE = 32
BOT_COMMAND_SECONDS = 1
PLAYER_IDLE_SECONDS = 30
STATE_LONGPOLL_SECONDS = 25.0
SHELL_EVENT_SECONDS = 0.05
BONUS_TYPES = ("звезда", "шлем", "часы")

# Ровно 5 ботов в комнате, респавн через 5 секунд.
BOT_TARGET_COUNT = 5
BOT_RESPAWN_SECONDS = 5.0

TANK_COLORS = [
    "красный", "зелёный", "синий", "оранжевый",
    "фиолетовый", "маджента", "лайм", "голубой",
]
BOT_COLOR = "серый"

BLOCKING_TILES = {1, 2, 4, 6}
PASSABLE_TILES = {0, 3, 5}


@dataclass
class Shell:
    id: str
    owner_id: str
    x: float
    y: float
    direction: str
    speed: float = 5.0


@dataclass
class Tank:
    id: str
    name: str
    is_bot: bool
    x: float
    y: float
    color: str = BOT_COLOR
    direction: str = "вверх"
    alive: bool = True
    level: int = 0
    kills: int = 0
    shell_limit: int = 1
    shells: list[Shell] = field(default_factory=list)
    shield_until: float = 0
    frozen_until: float = 0
    last_command_at: float = field(default_factory=time.monotonic)
    next_bot_command_at: float = 0
    initially_bot: bool = False
    respawn_at: float = 0


@dataclass
class Bonus:
    id: str
    kind: str
    x: int
    y: int
    expires_at: float


@dataclass
class Room:
    id: str
    name: str
    phase: Literal["round"] = "round"
    registrations: list[str] = field(default_factory=list)
    tiles: list[list[int]] = field(default_factory=list)
    brick_hp: dict[tuple[int, int], int] = field(default_factory=dict)
    tanks: list[Tank] = field(default_factory=list)
    bonuses: list[Bonus] = field(default_factory=list)
    next_object_id: int = 1
    spawn_points: list[tuple[int, int]] = field(default_factory=list)
    state_version: int = 0
    last_simulated_at: float = field(default_factory=time.monotonic)
    updated_at: float = field(default_factory=time.time)
    color_counter: int = 0
    next_bot_index: int = 1

    def object_id(self, prefix: str) -> str:
        result = f"{prefix}-{self.next_object_id}"
        self.next_object_id += 1
        return result


# ---------------------------------------------------------------------------
# Bot helpers
# ---------------------------------------------------------------------------
def _tile_at(tiles: list[list[int]], x: int, y: int) -> int | None:
    if 0 <= y < len(tiles) and 0 <= x < len(tiles[0]):
        return tiles[y][x]
    return None


def _line_of_sight(tiles, first, second) -> bool:
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
        if _tile_at(tiles, x, y) in BLOCKING_TILES:
            return False
    return True


def _direction_between(src, dst) -> str | None:
    dx = dst[0] - src[0]
    dy = dst[1] - src[1]
    if dx == 0 and dy != 0:
        return "вниз" if dy > 0 else "вверх"
    if dy == 0 and dx != 0:
        return "вправо" if dx > 0 else "влево"
    return None


def _bfs_next_step(tiles, start, goals, blocked) -> str | None:
    if start in goals:
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
            tile = tiles[ny][nx]
            if tile not in PASSABLE_TILES:
                continue
            if (nx, ny) in goals:
                return first_dir or name
            visited.add((nx, ny))
            queue.append(((nx, ny), first_dir or name))
    return None


class Game:
    def __init__(self) -> None:
        self.room = Room(id="1", name="Общая")
        self.start_round(self.room)

    def room_summary(self, room: Room) -> dict:
        return {
            "id": room.id,
            "name": room.name,
            "status": room.phase,
            "players": sum(not tank.is_bot and tank.alive for tank in room.tanks),
            "tanks_alive": sum(tank.alive for tank in room.tanks),
        }

    def _ensure_map(self, room: Room) -> None:
        if room.tiles:
            return
        room.tiles = [row.copy() for row in MAP_TEMPLATE]
        room.brick_hp = {
            (x, y): 2
            for y, row in enumerate(room.tiles)
            for x, tile in enumerate(row)
            if tile == 1
        }

    def _next_color(self, room: Room) -> str:
        color = TANK_COLORS[room.color_counter % len(TANK_COLORS)]
        room.color_counter += 1
        return color

    def join(self, room: Room, name: str) -> None:
        name = name.strip()
        if not name or len(name) > 40:
            raise ValueError("Имя должно содержать от 1 до 40 символов.")
        if any(p.casefold() == name.casefold() for p in room.registrations):
            raise ValueError("Это имя уже зарегистрировано в комнате.")
        room.registrations.append(name)
        self._ensure_map(room)

        spawn_points = self._spawn_points(room)
        used_cells = {(int(t.x), int(t.y)) for t in room.tanks if t.alive}
        free_points = [p for p in spawn_points if p not in used_cells]
        if free_points:
            x, y = random.choice(free_points)
        else:
            x, y = random.choice(spawn_points)

        tank = Tank(
            id=room.object_id("tank"),
            name=name,
            is_bot=False,
            x=x + 0.5,
            y=y + 0.5,
            color=self._next_color(room),
            last_command_at=time.monotonic(),
        )
        room.tanks.append(tank)
        room.updated_at = time.time()

    def _game_line_of_sight(self, room, first, second) -> bool:
        x1, y1 = first
        x2, y2 = second
        if room.tiles[y1][x1] == 4 or room.tiles[y2][x2] == 4:
            return False
        x_start, y_start = x1 + 0.5, y1 + 0.5
        x_end, y_end = x2 + 0.5, y2 + 0.5
        samples = max(abs(x2 - x1), abs(y2 - y1)) * 20
        if samples == 0:
            return True
        for step in range(1, int(samples)):
            x = int(x_start + (x_end - x_start) * step / samples)
            y = int(y_start + (y_end - y_start) * step / samples)
            if room.tiles[y][x] in (1, 2, 4):
                return False
        return True

    def _spawn_points(self, room: Room) -> list[tuple[int, int]]:
        if room.spawn_points:
            return room.spawn_points
        available = [
            (x, y)
            for y, row in enumerate(room.tiles)
            for x, tile in enumerate(row)
            if tile in PASSABLE_TILES
        ]
        random.shuffle(available)
        selected, remaining = [], []
        for candidate in available:
            if all(
                not self._game_line_of_sight(room, candidate, point)
                for point in selected
            ):
                selected.append(candidate)
            else:
                remaining.append(candidate)
        room.spawn_points = selected + remaining
        return room.spawn_points

    # ------------------------------------------------------------------
    # Боты: ровно BOT_TARGET_COUNT, респавн через BOT_RESPAWN_SECONDS
    # ------------------------------------------------------------------
    def _free_spawn_cells(self, room: Room) -> list[tuple[int, int]]:
        used_cells = {(int(t.x), int(t.y)) for t in room.tanks if t.alive}
        spawn_points = self._spawn_points(room)
        free = [p for p in spawn_points if p not in used_cells]
        if free:
            return free
        fallback = []
        for y, row in enumerate(room.tiles):
            for x, tile in enumerate(row):
                if tile in PASSABLE_TILES and (x, y) not in used_cells:
                    fallback.append((x, y))
        return fallback

    def _random_free_cell(self, room: Room) -> tuple[int, int] | None:
        free = self._free_spawn_cells(room)
        if free:
            return random.choice(free)
        spawn_points = self._spawn_points(room)
        return random.choice(spawn_points) if spawn_points else None

    def _add_bot(self, room: Room) -> Tank | None:
        cell = self._random_free_cell(room)
        if cell is None:
            return None
        x, y = cell

        bot_name = f"Бот-{room.next_bot_index}"
        while any(t.name.casefold() == bot_name.casefold() for t in room.tanks):
            room.next_bot_index += 1
            bot_name = f"Бот-{room.next_bot_index}"
        room.next_bot_index += 1

        tank = Tank(
            id=room.object_id("tank"),
            name=bot_name,
            is_bot=True,
            x=x + 0.5,
            y=y + 0.5,
            color=BOT_COLOR,
            last_command_at=time.monotonic(),
            initially_bot=True,
        )
        room.tanks.append(tank)
        return tank

    def _ensure_bot_count(self, room: Room) -> None:
        alive_bots = sum(1 for t in room.tanks if t.alive and t.is_bot)
        need = BOT_TARGET_COUNT - alive_bots
        for _ in range(need):
            if self._add_bot(room) is None:
                break

    def _process_bot_respawns(self, room: Room, now: float) -> None:
        for tank in room.tanks:
            if not tank.is_bot or tank.alive:
                continue
            if tank.respawn_at == 0 or tank.respawn_at > now:
                continue
            cell = self._random_free_cell(room)
            if cell is None:
                continue
            x, y = cell
            tank.alive = True
            tank.x = x + 0.5
            tank.y = y + 0.5
            tank.direction = "вверх"
            tank.level = 0
            tank.shells.clear()
            tank.shield_until = 0
            tank.frozen_until = 0
            tank.last_command_at = now
            tank.next_bot_command_at = now
            tank.respawn_at = 0

    # ------------------------------------------------------------------
    # Раунд
    # ------------------------------------------------------------------
    def start_round(self, room: Room) -> None:
        self._ensure_map(room)
        room.bonuses = []
        room.tanks = [t for t in room.tanks if not t.is_bot and t.alive]
        room.next_bot_index = 1
        self._ensure_bot_count(room)

        for tank in room.tanks:
            tank.alive = True
            tank.direction = "вверх"
            tank.level = 0
            tank.kills = 0
            tank.shell_limit = 1
            tank.shells.clear()
            tank.shield_until = 0
            tank.frozen_until = 0
            tank.last_command_at = time.monotonic()
            tank.respawn_at = 0

        room.phase = "round"
        room.last_simulated_at = time.monotonic()
        room.updated_at = time.time()

    def fire(self, room: Room, tank: Tank) -> None:
        if tank.alive and len(tank.shells) < tank.shell_limit:
            tank.shells.append(
                Shell(
                    id=room.object_id("shell"),
                    owner_id=tank.id,
                    x=tank.x, y=tank.y,
                    direction=tank.direction,
                    speed=5.0 + tank.level * 0.5,
                )
            )

    def _can_tank_occupy(self, room: Room, x, y, tank) -> bool:
        radius = 0.29
        for cx in (int(x - radius), int(x + radius)):
            for cy in (int(y - radius), int(y + radius)):
                if cy < 0 or cy >= MAP_HEIGHT or cx < 0 or cx >= MAP_WIDTH:
                    return False
                if room.tiles[cy][cx] in (1, 2, 6):
                    return False
        for other in room.tanks:
            if (other is not tank and other.alive
                    and abs(other.x - x) < 0.58
                    and abs(other.y - y) < 0.58):
                return False
        return True

    def _move_tank_one_tile(self, room, tank, direction) -> bool:
        dx, dy = DIRECTIONS[direction]
        nx, ny = tank.x + dx, tank.y + dy
        if not self._can_tank_occupy(room, nx, ny, tank):
            return False
        tank.x, tank.y = nx, ny
        return True

    def apply_command(self, room: Room, tank: Tank, command: str) -> None:
        if not tank.alive or tank.frozen_until > time.monotonic():
            return
        if command in DIRECTIONS:
            if tank.direction == command:
                self._move_tank_one_tile(room, tank, command)
            else:
                tank.direction = command
        elif command == "выстрел":
            self.fire(room, tank)

    def _move_shells(self, room: Room, dt: float) -> None:
        shells = [s for t in room.tanks for s in t.shells]
        if not shells:
            return
        steps = max(1, math.ceil(max(s.speed for s in shells) * dt / 0.08))
        step_dt = dt / steps
        destroyed: set[str] = set()
        registered_names = {n.casefold() for n in room.registrations}

        for _ in range(steps):
            active = [s for s in shells if s.id not in destroyed]
            if not active:
                break
            for s in active:
                dx, dy = DIRECTIONS[s.direction]
                s.x += dx * s.speed * step_dt
                s.y += dy * s.speed * step_dt
            coll_d2 = 0.18 ** 2
            nearby: dict[tuple[int, int], list[Shell]] = {}
            for s in active:
                cell = (int(s.x), int(s.y))
                for cx in range(cell[0] - 1, cell[0] + 2):
                    for cy in range(cell[1] - 1, cell[1] + 2):
                        for other in nearby.get((cx, cy), []):
                            dx, dy = s.x - other.x, s.y - other.y
                            if dx * dx + dy * dy <= coll_d2:
                                destroyed.add(s.id); destroyed.add(other.id)
                nearby.setdefault(cell, []).append(s)

            for s in active:
                if s.id in destroyed:
                    continue
                cx, cy = int(s.x), int(s.y)
                if not (0 <= cx < MAP_WIDTH and 0 <= cy < MAP_HEIGHT):
                    destroyed.add(s.id); continue
                tile = room.tiles[cy][cx]
                if tile == 1:
                    key = (cx, cy)
                    room.brick_hp[key] = room.brick_hp.get(key, 2) - 1
                    if room.brick_hp[key] <= 0:
                        room.tiles[cy][cx] = 0
                        room.brick_hp.pop(key, None)
                    destroyed.add(s.id); continue
                if tile in (2, 6):
                    destroyed.add(s.id); continue
                target = next(
                    (t for t in room.tanks
                     if t.alive and t.id != s.owner_id
                     and abs(t.x - s.x) < 0.38
                     and abs(t.y - s.y) < 0.38),
                    None,
                )
                if target is None:
                    continue
                if target.shield_until < time.monotonic():
                    target.alive = False
                    destroyed.update(ss.id for ss in target.shells)
                    target.shells.clear()
                    owner = next((t for t in room.tanks if t.id == s.owner_id), None)
                    if owner is not None and owner.name.casefold() in registered_names:
                        owner.kills += 1
                    if target.is_bot:
                        target.respawn_at = time.monotonic() + BOT_RESPAWN_SECONDS
                    if random.random() < 0.3:
                        room.bonuses.append(Bonus(
                            id=room.object_id("bonus"),
                            kind=random.choice(BONUS_TYPES),
                            x=cx, y=cy,
                            expires_at=time.monotonic() + 20,
                        ))
                destroyed.add(s.id)

        for tank in room.tanks:
            tank.shells[:] = [s for s in tank.shells if s.id not in destroyed]

        dead_players = {
            t.name.casefold()
            for t in room.tanks
            if not t.alive and not t.is_bot and t.name.casefold() in registered_names
        }
        if dead_players:
            room.tanks[:] = [t for t in room.tanks if t.name.casefold() not in dead_players]
            room.registrations[:] = [
                n for n in room.registrations if n.casefold() not in dead_players
            ]

    def _collect_bonuses(self, room: Room) -> None:
        now = time.monotonic()
        kept = []
        for bonus in room.bonuses:
            collector = next(
                (t for t in room.tanks
                 if t.alive and int(t.x) == bonus.x and int(t.y) == bonus.y),
                None,
            )
            if collector is None and bonus.expires_at > now:
                kept.append(bonus)
            elif collector is not None:
                if bonus.kind == "звезда":
                    collector.level = min(3, collector.level + 1)
                    collector.shell_limit = 2
                elif bonus.kind == "шлем":
                    collector.shield_until = now + 8
                elif bonus.kind == "часы":
                    for enemy in room.tanks:
                        if enemy.id != collector.id:
                            enemy.frozen_until = max(enemy.frozen_until, now + 5)
        room.bonuses = kept

    # ------------------------------------------------------------------
    # Логика ботов: цель — лидер по убийствам, стрельба ТОЛЬКО по линии
    # ------------------------------------------------------------------
    def _bot_target(self, room: Room, tank: Tank) -> Tank | None:
        """Живой игрок с максимумом убийств; при равенстве — ближайший."""
        registered = {n.casefold() for n in room.registrations}
        candidates = [
            t for t in room.tanks
            if t.alive and not t.is_bot and t.name.casefold() in registered
        ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda t: (-t.kills, (t.x - tank.x) ** 2 + (t.y - tank.y) ** 2),
        )

    def _bot_command(self, room: Room, tank: Tank) -> str | None:
        """
        Бот стреляет ТОЛЬКО если цель на линии видимости (нет блокеров)
        и на одной оси. Иначе — BFS-шаг к клетке цели (без разрушения стен).
        """
        target = self._bot_target(room, tank)
        if target is None:
            return None

        tiles = room.tiles
        my_cell = (int(tank.x), int(tank.y))
        target_cell = (int(target.x), int(target.y))
        blocked = {(int(t.x), int(t.y)) for t in room.tanks if t.alive}

        # 1. Цель на линии видимости — разворот/выстрел.
        if _line_of_sight(tiles, my_cell, target_cell):
            d = _direction_between(my_cell, target_cell)
            if d is not None:
                return d if tank.direction != d else "выстрел"

        # 2. Не на линии — только идём к цели. Кирпичи НЕ трогаем.
        step = _bfs_next_step(tiles, my_cell, {target_cell}, blocked - {my_cell})
        if step is not None:
            return step

        # 3. Прямой путь к клетке цели закрыт — идём к соседним клеткам.
        goals = set()
        for _, (dx, dy) in DIRECTIONS.items():
            cell = (target_cell[0] + dx, target_cell[1] + dy)
            tile = _tile_at(tiles, *cell)
            if tile in PASSABLE_TILES and cell not in blocked:
                goals.add(cell)
        return _bfs_next_step(tiles, my_cell, goals, blocked - {my_cell})

    # ------------------------------------------------------------------
    # Главный тик
    # ------------------------------------------------------------------
    def next_room_event_delay(self, room: Room) -> float | None:
        mono = time.monotonic()
        delays = []
        if room.phase == "round":
            for tank in room.tanks:
                if tank.is_bot and not tank.alive:
                    if tank.respawn_at > 0:
                        delays.append(max(0.0, tank.respawn_at - mono))
                    continue
                if not tank.alive:
                    continue
                if tank.shield_until > mono:
                    delays.append(tank.shield_until - mono)
                if tank.frozen_until > mono:
                    delays.append(tank.frozen_until - mono)
                elif tank.is_bot:
                    delays.append(max(0, tank.next_bot_command_at - mono))
                else:
                    delays.append(max(0, tank.last_command_at + PLAYER_IDLE_SECONDS - mono))
            for bonus in room.bonuses:
                delays.append(max(0, bonus.expires_at - mono))
            if any(t.shells for t in room.tanks):
                delays.append(SHELL_EVENT_SECONDS)
        return min(delays) if delays else None

    def process_room_events(self, room: Room, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        wall = time.time()
        elapsed = max(0, now - room.last_simulated_at)
        room.last_simulated_at = now
        if room.phase != "round":
            return

        self._process_bot_respawns(room, now)
        self._ensure_bot_count(room)

        self._move_shells(room, elapsed)
        self._collect_bonuses(room)
        for tank in room.tanks:
            if not tank.alive:
                continue
            if (not tank.is_bot and not tank.initially_bot
                    and now - tank.last_command_at >= PLAYER_IDLE_SECONDS):
                tank.is_bot = True
                tank.next_bot_command_at = now
            if tank.frozen_until > now:
                continue
            if tank.is_bot and now >= tank.next_bot_command_at:
                cmd = self._bot_command(room, tank)
                if cmd is not None:
                    self.apply_command(room, tank, cmd)
                tank.next_bot_command_at = now + BOT_COMMAND_SECONDS
        self._collect_bonuses(room)
        room.updated_at = wall

    def room_state(self, room: Room) -> dict:
        tiles = room.tiles or [row.copy() for row in MAP_TEMPLATE]
        registered = {n.casefold() for n in room.registrations}
        return {
            **self.room_summary(room),
            "state_version": room.state_version,
            "map": {"width": MAP_WIDTH, "height": MAP_HEIGHT, "tiles": tiles},
            "tanks": [
                {
                    "id": t.id, "name": t.name, "is_bot": t.is_bot,
                    "x": t.x, "y": t.y, "direction": t.direction,
                    "color": t.color, "alive": t.alive, "level": t.level,
                    "shielded": t.shield_until > time.monotonic(),
                    "frozen": t.frozen_until > time.monotonic(),
                }
                for t in room.tanks
            ],
            "shells": [
                {"id": s.id, "owner_id": s.owner_id, "x": s.x, "y": s.y, "direction": s.direction}
                for t in room.tanks for s in t.shells
            ],
            "bonuses": [
                {"id": b.id, "type": b.kind, "x": b.x, "y": b.y}
                for b in room.bonuses
            ],
            "kills": dict(sorted(
                ((t.name, t.kills) for t in room.tanks if t.name.casefold() in registered),
                key=lambda item: -item[1],
            )),
            "server_time": time.time(),
        }


game = Game()