import asyncio
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
TICK_SECONDS = 1 / 15
COUNTDOWN_SECONDS = 15
BOT_COMMAND_SECONDS = 1
PLAYER_IDLE_SECONDS = 30
BONUS_TYPES = ("звезда", "шлем", "часы")

# Ограничения на количество танков.
MAX_PLAYERS = 8          # сколько игроков может зарегистрироваться
MAX_TANKS = 40           # общий лимит (игроки + боты)

# Расписание волн ботов: на старте 1, через 30 с — 2, через 60 с — 3,
# и так до 7 на 180-й секунде. После этого волн больше нет.
BOT_WAVE_SIZES = [1, 2, 3, 4, 5, 6, 7]
BOT_WAVE_INTERVAL_SECONDS = 30

# Предопределённые цвета танков игроков (названия буквами).
# Назначаются по порядку: первый вошедший — «красный», второй — «зелёный» и т.д.
TANK_COLORS = [
    "красный",
    "зелёный",
    "синий",
    "оранжевый",
    "фиолетовый",
    "маджента",
    "лайм",
    "голубой",
]
BOT_COLOR = "серый"

# Тайлы, блокирующие обзор и движение
BLOCKING_TILES = {1, 2, 4, 6}
# Проходимые тайлы: 0 — пусто, 3 — лёд, 5 — трава
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
    shell_limit: int = 1
    shells: list[Shell] = field(default_factory=list)
    shield_until: float = 0
    frozen_until: float = 0
    last_command_at: float = field(default_factory=time.monotonic)
    next_bot_command_at: float = 0


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
    phase: Literal["waiting", "countdown", "round"] = "waiting"
    registrations: list[str] = field(default_factory=list)
    countdown_ends_at: float | None = None
    next_countdown_message_at: int | None = None
    tiles: list[list[int]] = field(default_factory=list)
    brick_hp: dict[tuple[int, int], int] = field(default_factory=dict)
    tanks: list[Tank] = field(default_factory=list)
    bonuses: list[Bonus] = field(default_factory=list)
    messages: deque[dict] = field(default_factory=lambda: deque(maxlen=200))
    next_message_id: int = 1
    next_object_id: int = 1
    spawn_points: list[tuple[int, int]] = field(default_factory=list)
    wins: dict[str, int] = field(default_factory=dict)
    wins_awarded: bool = False
    updated_at: float = field(default_factory=time.time)
    # Счётчик выданных цветов, чтобы назначать их строго по порядку.
    color_counter: int = 0
    # Планирование волн ботов.
    bot_wave_index: int = 0                 # индекс следующей волны (0..len(BOT_WAVE_SIZES)-1)
    next_bot_wave_at: float | None = None   # wall-clock время следующей волны
    next_bot_index: int = 1                 # следующий номер для имени бота

    def object_id(self, prefix: str) -> str:
        result = f"{prefix}-{self.next_object_id}"
        self.next_object_id += 1
        return result


# ---------------------------------------------------------------------------
# Логика бота (перенесена из bot.py)
# ---------------------------------------------------------------------------
def _tile_at(tiles: list[list[int]], x: int, y: int) -> int | None:
    if 0 <= y < len(tiles) and 0 <= x < len(tiles[0]):
        return tiles[y][x]
    return None


def _line_of_sight(tiles: list[list[int]],
                   first: tuple[int, int],
                   second: tuple[int, int]) -> bool:
    """Проверяет, что между двумя клетками нет блокирующих тайлов."""
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


def _direction_between(src: tuple[int, int], dst: tuple[int, int]) -> str | None:
    """Возвращает направление, если клетки стоят на одной линии."""
    dx = dst[0] - src[0]
    dy = dst[1] - src[1]
    if dx == 0 and dy != 0:
        return "вниз" if dy > 0 else "вверх"
    if dy == 0 and dx != 0:
        return "вправо" if dx > 0 else "влево"
    return None


def _bfs_next_step(tiles: list[list[int]],
                   start: tuple[int, int],
                   goals: set[tuple[int, int]],
                   blocked: set[tuple[int, int]]) -> str | None:
    """
    Ищет кратчайший путь от start до любой клетки из goals.
    Возвращает первое направление шага или None, если пути нет.
    """
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
        self.rooms: dict[str, Room] = {}

    def create_room(self, name: str) -> Room:
        room_id = "1"
        while room_id in self.rooms:
            room_id = str(int(room_id) + 1)
        room = Room(id=room_id, name=name)
        self.rooms[room.id] = room
        return room

    def delete_room(self, room_id: str) -> bool:
        return self.rooms.pop(room_id, None) is not None

    def room_summary(self, room: Room) -> dict:
        return {
            "id": room.id,
            "name": room.name,
            "status": room.phase,
            "players": len(room.registrations) if room.phase != "round" else sum(
                not tank.is_bot and tank.alive for tank in room.tanks
            ),
            "tanks_alive": sum(tank.alive for tank in room.tanks),
            "countdown_ends_at": room.countdown_ends_at,
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
        """
        Назначает цвет по порядку из TANK_COLORS.
        Первый вошедший получает «красный», второй — «зелёный» и т.д.
        После восьмого цвета нумерация идёт по кругу.
        """
        color = TANK_COLORS[room.color_counter % len(TANK_COLORS)]
        room.color_counter += 1
        return color

    def join(self, room: Room, name: str) -> None:
        name = name.strip()
        if not name or len(name) > 40:
            raise ValueError("Имя должно содержать от 1 до 40 символов.")
        if room.phase == "round":
            raise ValueError("Раунд уже идёт. Регистрация откроется после его завершения.")
        if any(player.casefold() == name.casefold() for player in room.registrations):
            raise ValueError("Это имя уже зарегистрировано в комнате.")
        if len(room.registrations) >= MAX_PLAYERS:
            raise ValueError(f"В комнате уже зарегистрированы {MAX_PLAYERS} игроков.")

        room.registrations.append(name)
        self._ensure_map(room)

        spawn_points = self._spawn_points(room)
        used_cells = {(int(t.x), int(t.y)) for t in room.tanks}
        free_points = [p for p in spawn_points if p not in used_cells]
        if free_points:
            x, y = free_points[0]
        else:
            x, y = spawn_points[len(room.tanks) % len(spawn_points)]

        tank = Tank(
            id=room.object_id("tank"),
            name=name,
            is_bot=False,
            x=x + 0.5,
            y=y + 0.5,
            color=self._next_color(room),
        )
        room.tanks.append(tank)

        if room.phase == "waiting":
            room.phase = "countdown"
            room.countdown_ends_at = time.time() + COUNTDOWN_SECONDS
            room.next_countdown_message_at = COUNTDOWN_SECONDS
            room.wins_awarded = False
            self.post_message(room, "Комната", f"Раунд начнётся через {COUNTDOWN_SECONDS} с")
        room.updated_at = time.time()

    def post_message(self, room: Room, sender: str, text: str, *, is_bot: bool = False) -> dict:
        sender = sender.strip()
        text = text.strip()
        if not sender or len(sender) > 40:
            raise ValueError("Имя отправителя должно содержать от 1 до 40 символов.")
        if not text or len(text) > 500:
            raise ValueError("Сообщение должно содержать от 1 до 500 символов.")

        join_match = text.split(maxsplit=2)
        if len(join_match) == 3 and join_match[0].casefold() == "войти":
            if join_match[1] != room.id:
                raise ValueError("Номер комнаты в команде не совпадает.")
            if room.phase != "round":
                self.join(room, join_match[2])

        tank = next(
            (
                candidate
                for candidate in room.tanks
                if candidate.alive and candidate.is_bot == is_bot
                and candidate.name.casefold() == sender.casefold()
            ),
            None,
        )
        normalized = text.strip().casefold()
        highlighted = normalized in COMMANDS and tank is not None
        if tank is not None and normalized in COMMANDS:
            tank.last_command_at = time.monotonic()
            if room.phase != "round":
                pass
            elif tank.frozen_until <= time.monotonic():
                if normalized in DIRECTIONS:
                    if tank.direction == normalized:
                        self._move_tank_one_tile(room, tank, normalized)
                    else:
                        tank.direction = normalized
                elif normalized == "выстрел":
                    self.fire(room, tank)

        message = {
            "id": room.next_message_id,
            "sender": sender,
            "text": text,
            "is_command": highlighted,
            "timestamp": time.time(),
        }
        room.next_message_id += 1
        room.messages.append(message)
        room.updated_at = time.time()
        return message

    def post_game_message(self, room: Room, text: str) -> dict:
        """Служебное сообщение чата (например, «Старт! Раунд начался.»)."""
        message = {
            "id": room.next_message_id,
            "sender": "Комната",
            "text": text,
            "is_command": False,
            "timestamp": time.time(),
        }
        room.next_message_id += 1
        room.messages.append(message)
        room.updated_at = time.time()
        return message

    def _game_line_of_sight(self, room: Room, first: tuple[int, int], second: tuple[int, int]) -> bool:
        """Внутренняя проверка видимости (используется для точек появления)."""
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
        selected: list[tuple[int, int]] = []
        remaining: list[tuple[int, int]] = []
        for candidate in available:
            if len(selected) < MAX_TANKS and all(
                not self._game_line_of_sight(room, candidate, point)
                for point in selected
            ):
                selected.append(candidate)
            else:
                remaining.append(candidate)
        room.spawn_points = selected + remaining
        return room.spawn_points

    # ------------------------------------------------------------------
    # Боты: добавление волнами
    # ------------------------------------------------------------------
    def _free_spawn_cells(self, room: Room) -> list[tuple[int, int]]:
        """
        Свободные клетки для появления нового танка.
        Сначала — выделенные точки появления, затем — любые свободные
        проходимые клетки (если выделенных не хватило).
        """
        used_cells = {(int(t.x), int(t.y)) for t in room.tanks if t.alive}
        spawn_points = self._spawn_points(room)
        free = [p for p in spawn_points if p not in used_cells]
        if free:
            return free
        fallback: list[tuple[int, int]] = []
        for y, row in enumerate(room.tiles):
            for x, tile in enumerate(row):
                if tile in PASSABLE_TILES and (x, y) not in used_cells:
                    fallback.append((x, y))
        return fallback

    def _add_bot(self, room: Room) -> Tank | None:
        """Добавляет одного бота на свободную точку появления."""
        free_points = self._free_spawn_cells(room)
        if not free_points:
            return None
        x, y = free_points[0]

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
        )
        room.tanks.append(tank)
        return tank

    def _add_bot_wave(self, room: Room, count: int) -> int:
        """Добавляет count ботов (или сколько поместится). Возвращает число добавленных."""
        added = 0
        for _ in range(count):
            if len(room.tanks) >= MAX_TANKS:
                break
            if self._add_bot(room) is None:
                break
            added += 1
        return added

    def _schedule_next_bot_wave(self, room: Room) -> None:
        """Планирует следующую волну ботов или прекращает волны."""
        if room.bot_wave_index >= len(BOT_WAVE_SIZES):
            room.next_bot_wave_at = None
            return
        room.next_bot_wave_at = time.time() + BOT_WAVE_INTERVAL_SECONDS

    # ------------------------------------------------------------------
    # Запуск/перезапуск раунда
    # ------------------------------------------------------------------
    def start_round(self, room: Room) -> None:
        self._ensure_map(room)
        room.bonuses = []
        room.wins_awarded = False

        # Оставляем только живых игроков (максимум MAX_PLAYERS)
        room.tanks = [t for t in room.tanks if not t.is_bot and t.alive][:MAX_PLAYERS]

        # Волны ботов: первая волна сразу, следующая — через 30 с.
        room.next_bot_index = 1
        room.bot_wave_index = 0
        self._add_bot_wave(room, BOT_WAVE_SIZES[room.bot_wave_index])
        room.bot_wave_index += 1
        self._schedule_next_bot_wave(room)

        # Сброс параметров танков к началу раунда
        for tank in room.tanks:
            tank.alive = True
            tank.direction = "вверх"
            tank.level = 0
            tank.shell_limit = 1
            tank.shells.clear()
            tank.shield_until = 0
            tank.frozen_until = 0
            tank.last_command_at = time.monotonic()

        room.phase = "round"
        room.countdown_ends_at = None
        room.next_countdown_message_at = None
        room.updated_at = time.time()

    def fire(self, room: Room, tank: Tank) -> None:
        if tank.alive and len(tank.shells) < tank.shell_limit:
            tank.shells.append(
                Shell(
                    id=room.object_id("shell"),
                    owner_id=tank.id,
                    x=tank.x,
                    y=tank.y,
                    direction=tank.direction,
                    speed=5.0 + tank.level * 0.5,
                )
            )

    def _can_tank_occupy(self, room: Room, x: float, y: float, tank: Tank) -> bool:
        radius = 0.29
        for cx in (int(x - radius), int(x + radius)):
            for cy in (int(y - radius), int(y + radius)):
                if cy < 0 or cy >= MAP_HEIGHT or cx < 0 or cx >= MAP_WIDTH:
                    return False
                if room.tiles[cy][cx] in (1, 2, 6):
                    return False
        for other in room.tanks:
            if other is not tank and other.alive and abs(other.x - x) < 0.58 and abs(other.y - y) < 0.58:
                return False
        return True

    def _move_tank_one_tile(self, room: Room, tank: Tank, direction: str) -> bool:
        """Сдвигает танк ровно на одну клетку в заданном направлении."""
        dx, dy = DIRECTIONS[direction]
        nx = tank.x + dx
        ny = tank.y + dy
        if not self._can_tank_occupy(room, nx, ny, tank):
            return False
        tank.x = nx
        tank.y = ny
        return True

    def _move_shells(self, room: Room, dt: float) -> None:
        for tank in room.tanks:
            kept: list[Shell] = []
            for shell in tank.shells:
                dx, dy = DIRECTIONS[shell.direction]
                distance = shell.speed * dt
                steps = max(1, int(distance / 0.08))
                alive = True
                for _ in range(steps):
                    shell.x += dx * distance / steps
                    shell.y += dy * distance / steps
                    cx, cy = int(shell.x), int(shell.y)
                    if not (0 <= cx < MAP_WIDTH and 0 <= cy < MAP_HEIGHT):
                        alive = False
                        break
                    tile = room.tiles[cy][cx]
                    if tile == 1:
                        hp_key = (cx, cy)
                        room.brick_hp[hp_key] = room.brick_hp.get(hp_key, 2) - 1
                        if room.brick_hp[hp_key] <= 0:
                            room.tiles[cy][cx] = 0
                            room.brick_hp.pop(hp_key, None)
                        alive = False
                        break
                    if tile in (2, 6):
                        alive = False
                        break
                    for target in room.tanks:
                        if target.alive and target.id != shell.owner_id and abs(target.x - shell.x) < 0.38 and abs(target.y - shell.y) < 0.38:
                            if target.shield_until < time.monotonic():
                                target.alive = False
                                target.shells.clear()
                                if random.random() < 0.3:
                                    room.bonuses.append(
                                        Bonus(
                                            id=room.object_id("bonus"),
                                            kind=random.choice(BONUS_TYPES),
                                            x=cx,
                                            y=cy,
                                            expires_at=time.monotonic() + 20,
                                        )
                                    )
                            alive = False
                            break
                    if not alive:
                        break
                if alive:
                    kept.append(shell)
            tank.shells = kept

    def _collect_bonuses(self, room: Room) -> None:
        now = time.monotonic()
        kept = []
        for bonus in room.bonuses:
            collector = next(
                (
                    tank for tank in room.tanks
                    if tank.alive and int(tank.x) == bonus.x and int(tank.y) == bonus.y
                ),
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
    # Логика ботов
    # ------------------------------------------------------------------
    def _brick_command(self, room: Room,
                       tank: Tank,
                       my_cell: tuple[int, int],
                       blocked: set[tuple[int, int]]) -> str | None:
        """
        Если в одном из четырёх направлений по прямой виден кирпич (и путь до
        него не перекрыт сталью/водой/бетоном и другими танками), бот
        разворачивается в эту сторону и стреляет.
        """
        tiles = room.tiles
        best: tuple[int, str] | None = None  # (расстояние, направление)
        for direction, (dx, dy) in DIRECTIONS.items():
            x, y = my_cell
            dist = 0
            while True:
                x += dx
                y += dy
                dist += 1
                if not (0 <= x < MAP_WIDTH and 0 <= y < MAP_HEIGHT):
                    break
                tile = tiles[y][x]
                if tile == 1:
                    if best is None or dist < best[0]:
                        best = (dist, direction)
                    break
                if tile in (2, 4, 6):
                    break
                if (x, y) in blocked:
                    break

        if best is not None:
            direction = best[1]
            if tank.direction != direction:
                return direction
            return "выстрел"
        return None

    def _bot_command(self, room: Room, tank: Tank) -> str | None:
        """
        Логика бота:
          1. Если видит живого противника — разворачивается и стреляет.
          2. Иначе — если в каком-то направлении по прямой есть кирпич,
             разворачивается к нему и стреляет.
          3. Иначе — идёт (BFS) к клетке рядом с ближайшим противником.
        """
        targets = [other for other in room.tanks if other.alive and other.id != tank.id]
        if not targets:
            return None

        tiles = room.tiles
        my_cell = (int(tank.x), int(tank.y))
        blocked = {(int(t.x), int(t.y)) for t in room.tanks if t.alive}

        targets.sort(key=lambda other: (other.x - tank.x) ** 2 + (other.y - tank.y) ** 2)

        # 1. Видим противника — стреляем в него.
        for enemy in targets:
            enemy_cell = (int(enemy.x), int(enemy.y))
            if _line_of_sight(tiles, my_cell, enemy_cell):
                dir_name = _direction_between(my_cell, enemy_cell)
                if dir_name is not None:
                    if tank.direction != dir_name:
                        return dir_name
                    return "выстрел"

        # 2. Противника не видим — стреляем по кирпичам.
        brick_cmd = self._brick_command(room, tank, my_cell, blocked)
        if brick_cmd is not None:
            return brick_cmd

        # 3. Иначе — идём к ближайшему противнику.
        for enemy in targets:
            enemy_cell = (int(enemy.x), int(enemy.y))
            goals: set[tuple[int, int]] = set()
            for _, (dx, dy) in DIRECTIONS.items():
                cell = (enemy_cell[0] + dx, enemy_cell[1] + dy)
                tile = _tile_at(tiles, *cell)
                if tile in PASSABLE_TILES and cell not in blocked:
                    goals.add(cell)
            if not goals:
                continue
            step_dir = _bfs_next_step(tiles, my_cell, goals, blocked - {my_cell})
            if step_dir is not None:
                return step_dir

        return None

    def _award_wins(self, room: Room, winner: Tank) -> None:
        """Начисляет победу конкретному танку (один раз за раунд)."""
        if room.wins_awarded:
            return
        room.wins[winner.name] = room.wins.get(winner.name, 0) + 1
        room.wins_awarded = True
        self.post_game_message(room, f"Победитель: {winner.name}!")

    def _alive_players(self, room: Room) -> list[Tank]:
        return [t for t in room.tanks if t.alive and not t.is_bot]

    def _alive_all(self, room: Room) -> list[Tank]:
        return [t for t in room.tanks if t.alive]

    def _restart_round(self, room: Room) -> None:
        """Запускает новый отсчёт, убирая мёртвых игроков и всех ботов."""
        alive_players = self._alive_players(room)
        alive_names = {t.name.casefold() for t in alive_players}
        room.registrations = [n for n in room.registrations if n.casefold() in alive_names]

        # Оставляем только живых игроков — боты будут добавлены заново в start_round.
        room.tanks = alive_players

        for tank in room.tanks:
            tank.alive = True
            tank.direction = "вверх"
            tank.level = 0
            tank.shell_limit = 1
            tank.shells.clear()
            tank.shield_until = 0
            tank.frozen_until = 0
            tank.last_command_at = time.monotonic()

        room.phase = "countdown"
        room.countdown_ends_at = time.time() + COUNTDOWN_SECONDS
        room.next_countdown_message_at = COUNTDOWN_SECONDS
        room.wins_awarded = False
        room.bot_wave_index = 0
        room.next_bot_wave_at = None
        room.next_bot_index = 1
        self.post_message(room, "Комната", f"Новый раунд начнётся через {COUNTDOWN_SECONDS} с")

    def _finish_round(self, room: Room) -> None:
        """Полный сброс комнаты после завершения матча."""
        room.phase = "waiting"
        room.registrations.clear()
        room.countdown_ends_at = None
        room.next_countdown_message_at = None
        room.tanks.clear()
        room.bonuses.clear()
        room.spawn_points = []
        room.wins_awarded = False
        room.color_counter = 0
        room.bot_wave_index = 0
        room.next_bot_wave_at = None
        room.next_bot_index = 1

    def tick(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        wall_now = time.time()
        for room in self.rooms.values():
            if room.phase == "countdown":
                if room.countdown_ends_at is not None and wall_now >= room.countdown_ends_at:
                    self.start_round(room)
                    self.post_game_message(room, "Старт! Раунд начался.")
                    continue
                remaining = math.ceil(room.countdown_ends_at - wall_now) if room.countdown_ends_at is not None else 0
                if room.next_countdown_message_at is None:
                    room.next_countdown_message_at = 0
                if remaining > 0 and remaining != room.next_countdown_message_at:
                    if remaining in (3, 2, 1):
                        self.post_message(room, "Комната", f"Старт через {remaining} с")
                    elif remaining == 5:
                        self.post_message(room, "Комната", "Старт через 5 с")
                    room.next_countdown_message_at = remaining
                continue
            if room.phase != "round":
                continue

            # --- Волны ботов -------------------------------------------------
            if room.next_bot_wave_at is not None and wall_now >= room.next_bot_wave_at:
                if room.bot_wave_index < len(BOT_WAVE_SIZES):
                    size = BOT_WAVE_SIZES[room.bot_wave_index]
                    added = self._add_bot_wave(room, size)
                    if added:
                        self.post_game_message(
                            room,
                            f"Подкрепление: +{added} бот(ов). "
                            f"Всего танков: {len(room.tanks)}.",
                        )
                    room.bot_wave_index += 1
                self._schedule_next_bot_wave(room)

            # --- Логика танков ----------------------------------------------
            for tank in room.tanks:
                if not tank.alive:
                    continue
                if tank.frozen_until > now:
                    continue
                if not tank.is_bot and now - tank.last_command_at >= PLAYER_IDLE_SECONDS:
                    tank.is_bot = True
                    tank.next_bot_command_at = now
                if tank.is_bot and now >= tank.next_bot_command_at:
                    command = self._bot_command(room, tank)
                    if command is not None:
                        self.post_message(room, tank.name, command, is_bot=True)
                    tank.next_bot_command_at = now + BOT_COMMAND_SECONDS

            self._move_shells(room, TICK_SECONDS)
            self._collect_bonuses(room)

            alive_all = self._alive_all(room)
            alive_players = self._alive_players(room)

            # Победа: остался ровно один живой танк
            if len(alive_all) == 1:
                self._award_wins(room, alive_all[0])
                self._finish_round(room)
                continue

            # Все люди мертвы, но боты ещё живы — новый раунд с таймером
            if not alive_players and alive_all:
                self._restart_round(room)
                continue

            # Никого живого не осталось — полный сброс
            if not alive_all:
                self._finish_round(room)

            room.updated_at = wall_now

    def room_state(self, room: Room) -> dict:
        tiles = room.tiles or MAP_TEMPLATE
        return {
            **self.room_summary(room),
            "map": {"width": MAP_WIDTH, "height": MAP_HEIGHT, "tiles": tiles},
            "tanks": [
                {
                    "id": tank.id,
                    "name": tank.name,
                    "is_bot": tank.is_bot,
                    "x": tank.x,
                    "y": tank.y,
                    "direction": tank.direction,
                    "color": tank.color,
                    "alive": tank.alive,
                    "level": tank.level,
                    "shielded": tank.shield_until > time.monotonic(),
                    "frozen": tank.frozen_until > time.monotonic(),
                }
                for tank in room.tanks
            ],
            "shells": [
                {
                    "id": shell.id,
                    "owner_id": shell.owner_id,
                    "x": shell.x,
                    "y": shell.y,
                    "direction": shell.direction,
                }
                for tank in room.tanks
                for shell in tank.shells
            ],
            "blocks": [
                {"x": x, "y": y, "type": tile, "hp": room.brick_hp.get((x, y))}
                for y, row in enumerate(tiles)
                for x, tile in enumerate(row)
                if tile != 0
            ],
            "bonuses": [
                {"id": bonus.id, "type": bonus.kind, "x": bonus.x, "y": bonus.y}
                for bonus in room.bonuses
            ],
            "wins": dict(sorted(room.wins.items(), key=lambda item: -item[1])),
            "messages": list(room.messages),
            "server_time": time.time(),
        }


game = Game()