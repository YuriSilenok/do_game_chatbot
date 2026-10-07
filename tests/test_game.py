import time
import unittest

from game import Bonus, COMMANDS, Game, MAP_TEMPLATE, Room


class GameTests(unittest.TestCase):
    def setUp(self):
        self.game = Game()
        self.room = self.game.create_room("Тест")

    def begin_round(self, names=("Игрок",)):
        self.room.registrations.extend(names)
        self.game.start_round(self.room)

    def test_join_command_registers_in_correct_room(self):
        message = self.game.post_message(self.room, "Аня", " ВОЙТИ 1 Аня ")
        self.assertEqual(self.room.registrations, ["Аня"])
        self.assertEqual(self.room.phase, "countdown")
        self.assertFalse(message["is_command"])

    def test_join_command_rejects_other_room(self):
        with self.assertRaisesRegex(ValueError, "не совпадает"):
            self.game.post_message(self.room, "Аня", "войти 2 Аня")
        self.assertEqual(self.room.registrations, [])

    def test_room_limits_registrations_to_twenty(self):
        for number in range(20):
            self.game.join(self.room, f"Игрок {number}")
        with self.assertRaisesRegex(ValueError, "20 игроков"):
            self.game.join(self.room, "Двадцать первый")

    def test_all_twenty_spawns_have_no_direct_visibility(self):
        self.begin_round()
        self.assertEqual(len(self.room.tanks), 20)
        points = [(int(tank.x), int(tank.y)) for tank in self.room.tanks]
        self.assertEqual(len(set(points)), 20)
        self.assertTrue(
            all(
                not self.game._line_of_sight(self.room, first, second)
                for index, first in enumerate(points)
                for second in points[index + 1:]
            )
        )

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
        self.begin_round()
        now = time.monotonic()
        for tank in self.room.tanks:
            if tank.is_bot:
                tank.next_bot_command_at = now - 1
        self.game.tick(now)
        bot_messages = [message for message in self.room.messages if message["sender"].startswith("Бот ")]
        self.assertEqual(len(bot_messages), 19)
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

    def test_map_template_matches_documented_size(self):
        self.assertEqual(len(MAP_TEMPLATE), 13)
        self.assertTrue(all(len(row) == 13 for row in MAP_TEMPLATE))
        self.assertEqual(COMMANDS, {"вверх", "вниз", "влево", "вправо", "выстрел"})


if __name__ == "__main__":
    unittest.main()
