"""Achievements: badges earned once per bot per group, announced the moment they're earned."""

from __future__ import annotations

from dataclasses import dataclass

from engine.theme import Text


@dataclass(frozen=True)
class Achievement:
    code: str
    emoji: str
    name: Text


ALL = [
    Achievement("streak_3", "🔥", {"en": "Three days in a row", "fa": "سه روز پشت سر هم"}),
    Achievement("streak_7", "🔥", {"en": "A whole week in a row", "fa": "یه هفته‌ی کامل پشت سر هم"}),
    Achievement("streak_30", "🏆", {"en": "A month without missing a day", "fa": "یه ماه بی‌وقفه"}),
    Achievement("jackpot", "✨", {"en": "First jackpot", "fa": "اولین جکپات"}),
    Achievement("disaster", "💥", {"en": "First disaster", "fa": "اولین فاجعه"}),
    Achievement("taarofed", "🙏", {"en": "Out-taarofed by the bot", "fa": "ربات تو تعارف شکستت داد"}),
    Achievement("lucky_hour", "🍀", {"en": "Lucky-hour hunter", "fa": "شکارچی ساعت شانس"}),
    Achievement("holiday", "🎉", {"en": "Played on a holiday", "fa": "بازی تو روز عید"}),
    Achievement("top", "👑", {"en": "Top of the group", "fa": "صدرنشین گروه"}),
    Achievement("plays_50", "🎯", {"en": "Fifty plays", "fa": "پنجاه بار بازی"}),
    Achievement("plays_200", "💯", {"en": "Two hundred plays", "fa": "دویست بار بازی"}),
    Achievement("duel_1", "⚔️", {"en": "First duel won", "fa": "اولین برد دوئل"}),
    Achievement("duel_5", "🗡️", {"en": "Five duels won", "fa": "پنج دوئل برده"}),
]
BY_CODE = {a.code: a for a in ALL}
HOLIDAYS = {"yalda", "chaharshanbe_suri", "nowruz", "sizdah_bedar"}


def after_play(*, streak: int, event: str | None, boosts: tuple[str, ...], rank: int, players: int,
               plays: int) -> list[str]:
    """Every achievement this play qualifies for; the database keeps only the new ones."""
    codes = []
    for days, code in ((3, "streak_3"), (7, "streak_7"), (30, "streak_30")):
        if streak >= days:
            codes.append(code)
    codes += {"good": ["jackpot"], "bad": ["disaster"], "lost_turn": ["taarofed"]}.get(event or "", [])
    if "lucky_hour" in boosts:
        codes.append("lucky_hour")
    if HOLIDAYS & set(boosts):
        codes.append("holiday")
    if rank == 1 and players >= 3:
        codes.append("top")
    for count, code in ((50, "plays_50"), (200, "plays_200")):
        if plays >= count:
            codes.append(code)
    return codes


def after_duel_win(wins: int) -> list[str]:
    return [code for count, code in ((1, "duel_1"), (5, "duel_5")) if wins >= count]
