
def tanks_zip(tank: dict) -> list:
    return [
        tank["id"],
        tank["name"],
        tank["is_bot"],
        tank["x"],
        tank["y"],
        tank["direction"],
        tank["color"],
        tank["alive"],
        tank["level"],
        tank["shielded"],
        tank["frozen"]
    ]

def tanks_unzip(data: list) -> dict:
    keys = ["id", "name", "is_bot", "x", "y", "direction", "color", "alive", "level", "shielded", "frozen"]
    return dict(zip(keys, data))

def shells_zip(shell: dict) -> list:
    return [
        shell["id"],
        shell["owner_id"],
        shell["x"],
        shell["y"],
        shell["direction"]
    ]

def shells_unzip(data: list) -> dict:
    keys = ["id", "owner_id", "x", "y", "direction"]
    return dict(zip(keys, data))

def bonuses_zip(bonus: dict) -> list:
    return [
        bonus["id"],
        bonus["type"],
        bonus["x"],
        bonus["y"],
    ]

def bonuses_unzip(data: list) -> dict:
    keys = ["id", "type", "x", "y"]
    return dict(zip(keys, data))
