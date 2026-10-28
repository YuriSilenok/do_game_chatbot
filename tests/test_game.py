import time
import unittest

from game import Bonus, COMMANDS, Game, MAP_HEIGHT, MAP_TEMPLATE, MAP_WIDTH, Shell, Tank


class GameTests(unittest.TestCase):
    def setUp(self):
        self.game = Game()
        self.room = self.game.room

    def begin_round_with_bots(self, names=("Игрок",)):
        """Быстрый старт раунда с ботами (как в игровом цикле)."""
        self.room.registrations.extend(names)
        self.game.start_round(self.room)
        count = len(self.room.registrations)
        for index in range(count, 10):
            self.room.tanks.append(
                type(self.room.tanks[0])(
                    id=self.room.object_id("tank"),
                    name=f"Бот {index - count + 1}",
                    is_bot=True,
                    x=index + 0.5,
                    y=index + 0.5,
                )
            )

    def begin_round(self, names=("Игрок",)):
        self.room.registrations.extend(names)
        self.game.start_round(self.room)
        player = self.room.tanks[0]
        x, y = int(player.x), int(player.y)
        for index in range(1, 10):
            self.room.tanks.append(
                type(player)(
                    id=self.room.object_id("enemy"),
                    name=f"Бот {index}",
                    is_bot=True,
                    x=x + index,
                    y=y + index,
                )
            )

    def test_join_command_registers_in_shared_room(self):
        message = self.game.post_message(self.room, "Аня", " ВОЙТИ Аня ")
        self.assertEqual(self.room.registrations, ["Аня"])
        self.assertEqual(self.room.phase, "round")
        self.assertTrue(any(tank.name == "Аня" for tank in self.room.tanks))
        self.assertFalse(message["is_command"])

    def test_players_can_join_during_active_round(self):
        self.game.join(self.room, "Аня")
        self.game.join(self.room, "Борис")

        self.assertEqual(self.room.phase, "round")
        self.assertEqual(self.room.registrations, ["Аня", "Борис"])

    def test_registration_has_no_player_limit(self):
        for number in range(100):
            self.game.join(self.room, f"Игрок {number}")
        self.assertEqual(len(self.room.registrations), 100)

    def test_round_is_active_when_game_is_created(self):
        self.assertEqual(self.room.phase, "round")
        self.assertTrue(self.room.tanks)
        self.assertTrue(self.room.tanks[0].is_bot)

    def test_only_registered_tank_receives_command(self):
        self.begin_round()
        player = self.room.tanks[0]
        player.is_bot = False
        player.name = "Игрок"
        spectator = self.game.post_message(self.room, "Зритель", "вправо")
        self.assertFalse(spectator["is_command"])
        self.assertEqual(player.direction, "вверх")
        command = self.game.post_message(self.room, "Игрок", " ВЛЕВО ")
        self.assertTrue(command["is_command"])
        self.assertEqual(player.direction, "влево")

    def test_commands_apply_immediately_in_order(self):
        self.begin_round()
        player = self.room.tanks[0]
        player.is_bot = False
        player.name = "Игрок"
        for tank in self.room.tanks[1:]:
            tank.next_bot_command_at = time.monotonic() + 10
        start_position = (player.x, player.y)

        self.game.post_message(self.room, "Игрок", "вправо")
        self.assertEqual(player.direction, "вправо")
        self.game.post_message(self.room, "Игрок", "вниз")

        self.assertEqual(player.direction, "вниз")
        self.assertEqual((player.x, player.y), start_position)

    def test_shot_limit_increases_after_star_bonus(self):
        self.begin_round()
        player = self.room.tanks[0]
        self.game.fire(self.room, player)
        self.game.fire(self.room, player)
        self.assertEqual(len(player.shells), 1)
        player.shell_limit = 2
        self.game.fire(self.room, player)
        self.assertEqual(len(player.shells), 2)

    def test_shells_destroy_each_other_on_collision(self):
        first = self.room.tanks[0]
        second = Tank(
            id=self.room.object_id("tank"),
            name="Второй",
            is_bot=False,
            x=3.5,
            y=3.5,
        )
        first.x = 2.5
        first.y = 2.5
        first.shells.append(Shell("shell-a", first.id, 5.0, 5.5, "вправо"))
        second.shells.append(Shell("shell-b", second.id, 6.0, 5.5, "влево"))
        self.room.tanks.append(second)

        self.game._move_shells(self.room, 0.1)

        self.assertEqual(first.shells, [])
        self.assertEqual(second.shells, [])
        self.assertEqual(first.kills, 0)
        self.assertEqual(second.kills, 0)

    def test_bot_takes_over_after_thirty_seconds_idle(self):
        self.begin_round()
        player = self.room.tanks[0]
        player.last_command_at = time.monotonic() - 31
        self.game.process_room_events(self.room)
        self.assertTrue(player.is_bot)

    def test_bots_send_commands_as_chat_messages(self):
        self.begin_round_with_bots()
        now = time.monotonic()
        for tank in self.room.tanks:
            if tank.is_bot:
                tank.next_bot_command_at = now - 1
        self.game.process_room_events(self.room, now)
        bot_messages = [message for message in self.room.messages if message["sender"].startswith("Бот ")]
        self.assertEqual(len(bot_messages), 9)
        self.assertTrue(all(message["is_command"] for message in bot_messages))

    def test_bonuses_apply_tank_upgrade_shield_and_freeze(self):
        self.begin_round()
        player, enemy = self.room.tanks[:2]
        x, y = int(player.x), int(player.y)
        self.room.bonuses = [
            Bonus("star", "звезда", x, y, time.monotonic() + 20),
            Bonus("helmet", "шлем", x, y, time.monotonic() + 20),
            Bonus("clock", "часы", x, y, time.monotonic() + 20),
        ]
        self.game._collect_bonuses(self.room)
        self.assertEqual(player.shell_limit, 2)
        self.assertGreater(player.shield_until, time.monotonic())
        self.assertGreater(enemy.frozen_until, time.monotonic())

    def test_kill_is_counted_and_last_tank_does_not_end_round(self):
        attacker = self.room.tanks[0]
        attacker.name = "Игрок"
        attacker.is_bot = False
        self.room.registrations.append(attacker.name)
        attacker.x = 5.5
        attacker.y = 5.5
        target = Tank(
            id=self.room.object_id("tank"),
            name="Цель",
            is_bot=False,
            x=6.5,
            y=5.5,
        )
        self.room.registrations.append(target.name)
        attacker.shells.append(Shell("shell-1", attacker.id, 6.0, 5.5, "вправо"))
        self.room.tanks.append(target)

        self.game._move_shells(self.room, 0.1)
        self.game.process_room_events(self.room)

        self.assertFalse(target.alive)
        self.assertEqual(attacker.kills, 1)
        self.assertEqual(self.room.phase, "round")
        self.assertIn(attacker, self.room.tanks)
        self.assertNotIn(target, self.room.tanks)
        self.assertNotIn("Цель", self.room.registrations)
        state = self.game.room_state()
        self.assertEqual(state["kills"]["Игрок"], 1)
        self.assertNotIn("Цель", state["kills"])
        self.assertNotIn("wins", state)

        self.game.join(self.room, "Цель")
        self.assertTrue(any(tank.name == "Цель" for tank in self.room.tanks))
        self.game.join(self.room, "Поздний игрок")
        self.assertTrue(any(tank.name == "Поздний игрок" for tank in self.room.tanks))

    def test_kill_stats_only_include_registered_players(self):
        bot = self.room.tanks[0]
        bot.kills = 9
        player = Tank(
            id=self.room.object_id("tank"),
            name="Игрок",
            is_bot=True,
            x=2.5,
            y=2.5,
            kills=3,
        )
        unregistered_tank = Tank(
            id=self.room.object_id("tank"),
            name="Не зарегистрирован",
            is_bot=False,
            x=3.5,
            y=3.5,
            kills=12,
        )
        self.room.tanks.extend((player, unregistered_tank))
        self.room.registrations.append(player.name)

        self.assertEqual(self.game.room_state()["kills"], {"Игрок": 3})

    def test_map_template_matches_documented_size(self):
        self.assertEqual(MAP_WIDTH, 26)
        self.assertEqual(MAP_HEIGHT, 13)
        self.assertEqual(len(MAP_TEMPLATE), 13)
        self.assertTrue(all(len(row) == 26 for row in MAP_TEMPLATE))
        self.assertEqual(COMMANDS, {"вверх", "вниз", "влево", "вправо", "выстрел"})


if __name__ == "__main__":
    unittest.main()
