import unittest

import de_en_coding as de

class ZipTests(unittest.TestCase):
    def test_zip_tank(self):
        tank = {
          "id": "tank-1",
          "name": "Бот-1",
          "is_bot": True,
          "x": 1.5,
          "y": 9.5,
          "direction": "вверх",
          "color": "серый",
          "alive": True,
          "level": 0,
          "shielded": False,
          "frozen": False
        }
        self.assertEqual(de.tanks_unzip(de.tanks_zip(tank)), tank)

    def test_zip_shell(self):
        shell = {
          "id": "shell-23",
          "owner_id": "tank-3",
          "x": 11.495106094993394,
          "y": 1.5,
          "direction": "влево"
        }
        self.assertEqual(de.shells_unzip(de.shells_zip(shell)), shell)

    def test_zip_bonus(self):
        bonus = {
          "id": "bonus-20",
          "type": "шлем",
          "x": 12,
          "y": 4
        }
        self.assertEqual(de.bonuses_unzip(de.bonuses_zip(bonus)), bonus)


if __name__ == '__main__':
    unittest.main()
