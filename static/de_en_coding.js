export const tanksZip = (tank) => [
    tank.id,
    tank.name,
    tank.is_bot,
    tank.x,
    tank.y,
    tank.direction,
    tank.color,
    tank.alive,
    tank.level,
    tank.shielded,
    tank.frozen
];

export const tanksUnzip = (data) => {
    const keys = ["id", "name", "is_bot", "x", "y", "direction", "color", "alive", "level", "shielded", "frozen"];
    return keys.reduce((obj, key, i) => {
        obj[key] = data[i];
        return obj;
    }, {});
};

export const shellsZip = (shell) => [
    shell.id,
    shell.owner_id,
    shell.x,
    shell.y,
    shell.direction
];

export const shellsUnzip = (data) => {
    const keys = ["id", "owner_id", "x", "y", "direction"];
    return keys.reduce((obj, key, i) => {
        obj[key] = data[i];
        return obj;
    }, {});
};

export const bonusesZip = (bonus) => [
    bonus.id,
    bonus.type,
    bonus.x,
    bonus.y
];

export const bonusesUnzip = (data) => {
    const keys = ["id", "type", "x", "y"];
    return keys.reduce((obj, key, i) => {
        obj[key] = data[i];
        return obj;
    }, {});
};
