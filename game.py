import asyncio
import random
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Literal


MAP_TEMPLATE = [
    [2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2],
    [2, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 2],
    [2, 0, 1, 1, 0, 2, 0, 2, 0, 1, 1, 0, 2],
    [2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2],
    [2, 1, 0, 2, 0, 4, 4, 4, 0, 2, 0, 1, 2],
    [2, 0, 0, 0, 0, 4, 3, 4, 0, 0, 0, 0, 2],
    [2, 0, 2, 0, 0, 4, 3, 4, 0, 0, 2, 0, 2],
    [2, 0, 0, 0, 0, 4, 4, 4, 0, 0, 0, 0, 2],
    [2, 1, 0, 2, 0, 0, 0, 0, 0, 2, 0, 1, 2],
    [2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2],
    [2, 0, 1, 1, 0, 2, 0, 2, 0, 1, 1, 0, 2],
    [2, 0, 0, 1, 0, 0, 5, 0, 0, 1, 0, 0, 2],
    [2, 2, 2, 2, 2, 2, 6, 2, 2, 2, 2, 2, 2],
]

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
    tiles: list[list[int]] = field(default_factory=list)
    brick_hp: dict[tuple[int, int], int] = field(default_factory=dict)
    tanks: list[Tank] = field(default_factory=list)
    bonuses: list[Bonus] = field(default_factory=list)
    messages: deque[dict] = field(default_factory=lambda: deque(maxlen=200))
    next_message_id: int = 1
    next_object_id: int = 1
    updated_at: float = field(default_factory=time.time)

    def object_id(self, prefix: str) -> str:
        result = f"{prefix}-{self.next_object_id}"
        self.next_object_id += 1
        return result


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

    def join(self, room: Room, name: str) -> None:
        name = name.strip()
        if not name or len(name) > 40:
            raise ValueError("Имя должно содержать от 1 до 40 символов.")
        if room.phase == "round":
            raise ValueError("Раунд уже идёт. Регистрация откроется после его завершения.")
        if any(player.casefold() == name.casefold() for player in room.registrations):
            raise ValueError("Это имя уже зарегистрировано в комнате.")
        if len(room.registrations) >= 20:
            raise ValueError("В комнате уже зарегистрированы 20 игроков.")
        room.registrations.append(name)
        if room.phase == "waiting":
            room.phase = "countdown"
            room.countdown_ends_at = time.time() + COUNTDOWN_SECONDS
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
            if tank.frozen_until <= time.monotonic():
                if normalized in DIRECTIONS:
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

    def _line_of_sight(self, room: Room, first: tuple[int, int], second: tuple[int, int]) -> bool:
        x1, y1 = first
        x2, y2 = second
        if room.tiles[y1][x1] == 4 or room.tiles[y2][x2] == 4:
            return False
        x_start, y_start = x1 + 0.5, y1 + 0.5
        x_end, y_end = x2 + 0.5, y2 + 0.5
        samples = max(abs(x2 - x1), abs(y2 - y1)) * 20
        for step in range(1, int(samples)):
            x = int(x_start + (x_end - x_start) * step / samples)
            y = int(y_start + (y_end - y_start) * step / samples)
            if room.tiles[y][x] in (1, 2, 4):
                return False
        return True

    def _spawn_points(self, room: Room) -> list[tuple[int, int]]:
        available = [
            (x, y)
            for y, row in enumerate(room.tiles)
            for x, tile in enumerate(row)
            if tile in (0, 4)
        ]
        random.Random(42).shuffle(available)
        selected: list[tuple[int, int]] = []
        for candidate in available:
            if all(not self._line_of_sight(room, candidate, point) for point in selected):
                selected.append(candidate)
                if len(selected) == 20:
                    return selected
        raise RuntimeError("На карте недостаточно безопасных точек появления для 20 танков.")

    def start_round(self, room: Room) -> None:
        room.tiles = [row.copy() for row in MAP_TEMPLATE]
        room.brick_hp = {
            (x, y): 2
            for y, row in enumerate(room.tiles)
            for x, tile in enumerate(row)
            if tile == 1
        }
        room.bonuses = []
        room.tanks = []
        for index, (x, y) in enumerate(self._spawn_points(room)):
            is_bot = index >= len(room.registrations)
            tank = Tank(
                id=room.object_id("tank"),
                name=room.registrations[index] if not is_bot else f"Бот {index - len(room.registrations) + 1}",
                is_bot=is_bot,
                x=x + 0.5,
                y=y + 0.5,
                next_bot_command_at=time.monotonic() + random.uniform(0.2, 1.0),
            )
            room.tanks.append(tank)
        room.phase = "round"
        room.countdown_ends_at = None
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
                if cy < 0 or cy >= 13 or cx < 0 or cx >= 13:
                    return False
                if room.tiles[cy][cx] in (1, 2, 3, 6):
                    return False
        for other in room.tanks:
            if other is not tank and other.alive and abs(other.x - x) < 0.58 and abs(other.y - y) < 0.58:
                return False
        return True

    def _move_tanks(self, room: Room, dt: float) -> None:
        vectors = {direction: vector for direction, vector in DIRECTIONS.items()}
        for tank in room.tanks:
            if not tank.alive or tank.frozen_until > time.monotonic() or tank.direction not in vectors:
                continue
            dx, dy = vectors[tank.direction]
            speed = 1.3 + tank.level * 0.2
            distance = speed * dt
            steps = max(1, int(distance / 0.08))
            for _ in range(steps):
                nx = tank.x + dx * distance / steps
                ny = tank.y + dy * distance / steps
                if self._can_tank_occupy(room, nx, ny, tank):
                    tank.x, tank.y = nx, ny
                else:
                    break
                if room.tiles[int(tank.y)][int(tank.x)] == 5:
                    nx = tank.x + dx * speed * dt * 0.5
                    ny = tank.y + dy * speed * dt * 0.5
                    if self._can_tank_occupy(room, nx, ny, tank):
                        tank.x, tank.y = nx, ny

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
                    if not (0 <= cx < 13 and 0 <= cy < 13):
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

    def _bot_command(self, room: Room, tank: Tank) -> str:
        targets = [
            other for other in room.tanks
            if other.alive and other.id != tank.id
        ]
        if not targets:
            return "выстрел"
        target = min(targets, key=lambda other: (other.x - tank.x) ** 2 + (other.y - tank.y) ** 2)
        if abs(target.x - tank.x) < 0.55:
            return "выстрел" if target.y < tank.y else "вверх" if target.y > tank.y else "вниз"
        if abs(target.y - tank.y) < 0.55:
            return "выстрел" if target.x < tank.x else "влево" if target.x > tank.x else "вправо"

        start = (int(tank.x), int(tank.y))
        destination = (int(target.x), int(target.y))
        queue = deque([(start, None)])
        visited = {start}
        while queue:
            (x, y), first_direction = queue.popleft()
            if (x, y) == destination:
                return first_direction or "выстрел"
            for direction, (dx, dy) in DIRECTIONS.items():
                point = (x + dx, y + dy)
                px, py = point
                if point in visited or not (0 <= px < 13 and 0 <= py < 13):
                    continue
                if room.tiles[py][px] in (1, 2, 3, 6):
                    continue
                visited.add(point)
                queue.append((point, first_direction or direction))
        return random.choice(tuple(DIRECTIONS))

    def tick(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        wall_now = time.time()
        for room in self.rooms.values():
            if room.phase == "countdown":
                if room.countdown_ends_at is not None and wall_now >= room.countdown_ends_at:
                    self.start_round(room)
                continue
            if room.phase != "round":
                continue

            for tank in room.tanks:
                if not tank.alive:
                    continue
                if tank.frozen_until > now:
                    continue
                if not tank.is_bot and now - tank.last_command_at >= PLAYER_IDLE_SECONDS:
                    tank.is_bot = True
                    tank.next_bot_command_at = now
                if tank.is_bot and now >= tank.next_bot_command_at:
                    self.post_message(room, tank.name, self._bot_command(room, tank), is_bot=True)
                    tank.next_bot_command_at = now + BOT_COMMAND_SECONDS

            self._move_tanks(room, TICK_SECONDS)
            self._move_shells(room, TICK_SECONDS)
            self._collect_bonuses(room)
            if not any(tank.alive for tank in room.tanks):
                room.phase = "waiting"
                room.registrations.clear()
                room.countdown_ends_at = None
                room.tanks.clear()
                room.bonuses.clear()
            room.updated_at = wall_now

    def room_state(self, room: Room) -> dict:
        tiles = room.tiles or MAP_TEMPLATE
        return {
            **self.room_summary(room),
            "map": {"width": 13, "height": 13, "tiles": tiles},
            "tanks": [
                {
                    "id": tank.id,
                    "name": tank.name,
                    "is_bot": tank.is_bot,
                    "x": tank.x,
                    "y": tank.y,
                    "direction": tank.direction,
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
            "messages": list(room.messages),
            "server_time": time.time(),
        }


game = Game()
