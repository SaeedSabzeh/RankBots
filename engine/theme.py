"""Theme files: everything that makes one bot different from another.

A theme is a YAML file in themes/. The engine reads only these fields, so a new
bot is a new YAML file plus a token. Every theme is validated at startup, so a
typo fails loudly instead of in the middle of a group chat.
"""

from __future__ import annotations

import re
from pathlib import Path
from datetime import timedelta
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Lang = Literal["fa", "en"]
# A piece of copy in one or more languages, e.g. {"en": "Kitten", "fa": "بچه‌گربه"}.
Text = dict[Lang, str]

THEMES_DIR = Path(__file__).resolve().parent.parent / "themes"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Score(_Strict):
    name: Text
    unit: Text
    start: int = 0
    direction: Literal["higher", "lower"] = "higher"
    # Every rolled point is multiplied by this (konkur: 1000, so ranks move in thousands).
    scale: int = Field(1, ge=1)
    # The score can never go past this bound (0 for most themes, 1 for a konkur rank).
    min: int = 0


class Title(_Strict):
    # Reached when the score is at or past `at` in the theme's direction.
    at: int
    name: Text


class Events(_Strict):
    good: list[Text] = Field(min_length=1)
    bad: list[Text] = Field(min_length=1)


class LostTurnHook(_Strict):
    """Taarof: the bot sometimes taarofs back and the turn is lost.

    The cooldown is used and the play is logged, but the score doesn't move.
    """

    kind: Literal["lost_turn"]
    chance: float = Field(gt=0, lt=1)
    messages: list[Text] = Field(min_length=1)


# The optional special mechanic, at most one per theme so the engine stays generic.
# A new kind becomes another model with its own `kind`, joined here as a union.
Hook = LostTurnHook


class Theme(_Strict):
    name: str
    emoji: str
    language: Literal["fa", "en", "both"]
    # Time between two /play turns, chosen to match the theme (a glass of tea vs. a cat nap).
    cooldown_minutes: int = Field(12 * 60, ge=1, le=7 * 24 * 60)
    bot_name: Text
    tagline: Text
    leaderboard_title: Text
    score: Score
    gains: list[Text] = Field(min_length=1)
    losses: list[Text] = Field(min_length=1)
    neutral: list[Text] = Field(default_factory=list)
    events: Events
    titles: list[Title] = Field(min_length=1)
    hook: Hook | None = None

    @field_validator("name")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", v):
            raise ValueError("name must be a lowercase slug like 'cat' or 'konkur'")
        return v

    @property
    def langs(self) -> tuple[Lang, ...]:
        """Languages every message is rendered in, primary first."""
        return ("fa", "en") if self.language == "both" else (self.language,)

    @property
    def cooldown(self) -> timedelta:
        return timedelta(minutes=self.cooldown_minutes)

    @property
    def higher_is_better(self) -> bool:
        return self.score.direction == "higher"

    @property
    def token_env(self) -> str:
        return f"BOT_TOKEN_{self.name.upper()}"

    @model_validator(mode="after")
    def _check(self) -> Theme:
        self._check_texts()
        self._check_titles()
        if self.score.start < self.score.min:
            raise ValueError("score.start is below score.min")
        return self

    def _check_texts(self) -> None:
        texts: list[tuple[str, Text]] = [
            ("bot_name", self.bot_name),
            ("tagline", self.tagline),
            ("leaderboard_title", self.leaderboard_title),
            ("score.name", self.score.name),
        ]
        # The unit may be empty (a konkur rank is just a number), but every language must list it.
        for lang in self.langs:
            if lang not in self.score.unit:
                raise ValueError(f"score.unit is missing its '{lang}' text")
        for field in ("gains", "losses", "neutral"):
            texts += [(f"{field}[{i}]", t) for i, t in enumerate(getattr(self, field))]
        texts += [(f"events.good[{i}]", t) for i, t in enumerate(self.events.good)]
        texts += [(f"events.bad[{i}]", t) for i, t in enumerate(self.events.bad)]
        texts += [(f"titles[{i}].name", t.name) for i, t in enumerate(self.titles)]
        if self.hook is not None:
            texts += [(f"hook.messages[{i}]", t) for i, t in enumerate(self.hook.messages)]
        for where, text in texts:
            for lang in self.langs:
                if not text.get(lang, "").strip():
                    raise ValueError(f"{where} is missing its '{lang}' text")

    def _check_titles(self) -> None:
        ats = [t.at for t in self.titles]
        expected = sorted(ats) if self.higher_is_better else sorted(ats, reverse=True)
        if ats != expected or len(set(ats)) != len(ats):
            order = "increasing" if self.higher_is_better else "decreasing"
            raise ValueError(f"titles must be in strictly {order} order of 'at'")
        if not self.reaches(self.score.start, self.titles[0].at):
            raise ValueError("the first title must already be reached at score.start")

    def reaches(self, score: int, threshold: int) -> bool:
        return score >= threshold if self.higher_is_better else score <= threshold


def load_theme(path: Path) -> Theme:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    try:
        theme = Theme.model_validate(data)
    except ValueError as e:
        raise ValueError(f"Invalid theme {path.name}: {e}") from e
    if theme.name != path.stem:
        raise ValueError(f"Invalid theme {path.name}: name '{theme.name}' must match the file name")
    return theme


def load_themes(directory: Path = THEMES_DIR) -> dict[str, Theme]:
    """Load and validate every theme file. Raises on the first invalid one."""
    themes = {}
    for path in sorted(directory.glob("*.yaml")):
        theme = load_theme(path)
        themes[theme.name] = theme
    if not themes:
        raise ValueError(f"No theme files found in {directory}")
    return themes
