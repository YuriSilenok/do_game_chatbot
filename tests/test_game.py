import time
import unittest

from game import Bonus, COMMANDS, Game, MAP_HEIGHT, MAP_TEMPLATE, MAP_WIDTH, Room


class GameTests(unittest.TestCase):
    def setUp(self):
        self.game = Game()
        self.room = self.game.create_room("Тест")

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

    def test_join_command_registers_in_correct_room(self):
        message = self.game.post_message(self.room, "Аня", " ВОЙТИ 1 Аня ")
        self.assertEqual(self.room.registrations, ["Аня"])
        self.assertEqual(self.room.phase, "countdown")
        self.assertGreater(self.room.countdown_ends_at, time.time())
        self.assertFalse(message["is_command"])

    def test_first_join_starts_countdown_without_restarting_it_for_next_player(self):
        self.game.join(self.room, "Аня")
        countdown_ends_at = self.room.countdown_ends_at
        self.assertEqual(self.room.phase, "countdown")
        self.assertGreater(countdown_ends_at, time.time())

        self.game.join(self.room, "Борис")

        self.assertEqual(self.room.countdown_ends_at, countdown_ends_at)
        self.assertEqual(self.room.registrations, ["Аня", "Борис"])

    def test_join_command_rejects_other_room(self):
        with self.assertRaisesRegex(ValueError, "не совпадает"):
            self.game.post_message(self.room, "Аня", "войти 2 Аня")
        self.assertEqual(self.room.registrations, [])

    def test_room_limits_registrations_to_ten(self):
        for number in range(10):
            self.game.join(self.room, f"Игрок {number}")
        with self.assertRaisesRegex(ValueError, "10 игроков"):
            self.game.join(self.room, "Одиннадцатый")

    def test_round_starts_only_registered_tanks_no_bots(self):
        self.game.join(self.room, "Аня")
        self.room.countdown_ends_at = time.time() - 1
        self.game.tick()
        self.assertEqual(self.room.phase, "round")
        self.assertEqual([tank.name for tank in self.room.tanks], ["Аня"])
        self.assertTrue(all(not tank.is_bot for tank in self.room.tanks))

    def test_only_registered_tank_receives_command(self):
        self.begin_round()
        player = self.room.tanks[0]
        spectator = self.game.post_message(self.room, "Зритель", "вправо")
        self.assertFalse(spectator["is_command"])
        self.assertEqual(player.direction, "вверх")
        command = self.game.post_message(self.room, "Игрок", " ВЛЕВО ")
        self.assertTrue(command["is_command"])
        self.assertEqual(player.direction, "влево")

    def test_shot_limit_increases_after_star_bonus(self):
        self.begin_round()
        player = self.room.tanks[0]
        self.game.fire(self.room, player)
        self.game.fire(self.room, player)
        self.assertEqual(len(player.shells), 1)
        player.shell_limit = 2
        self.game.fire(self.room, player)
        self.assertEqual(len(player.shells), 2)

    def test_bot_takes_over_after_thirty_seconds_idle(self):
        self.begin_round()
        player = self.room.tanks[0]
        player.last_command_at = time.monotonic() - 31
        self.game.tick()
        self.assertTrue(player.is_bot)

    def test_bots_send_commands_as_chat_messages(self):
        self.begin_round_with_bots()
        now = time.monotonic()
        for tank in self.room.tanks:
            if tank.is_bot:
                tank.next_bot_command_at = now - 1
        self.game.tick(now)
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

    def test_countdown_posts_messages_to_chat_until_start(self):
        self.game.join(self.room, "Аня")
        self.assertIn(
            "Раунд начнётся через 15 с",
            [message["text"] for message in self.room.messages if message["sender"] == "Комната"],
        )
        self.room.countdown_ends_at = time.time() + 5
        self.room.next_countdown_message_at = None
        self.game.tick()
        self.assertIn(
            "Старт через 5 с",
            [message["text"] for message in self.room.messages if message["sender"] == "Комната"],
        )

    def test_map_template_matches_documented_size(self):
        self.assertEqual(MAP_WIDTH, 26)
        self.assertEqual(MAP_HEIGHT, 13)
        self.assertEqual(len(MAP_TEMPLATE), 13)
        self.assertTrue(all(len(row) == 26 for row in MAP_TEMPLATE))
        self.assertEqual(COMMANDS, {"вверх", "вниз", "влево", "вправо", "выстрел"})


if __name__ == "__main__":
    unittest.main()
