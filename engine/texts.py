"""Everything the bots say, in Farsi and English.

Theme copy (gain messages, titles, ...) lives in the theme files; this module holds
the engine's own lines and puts the pieces together. Each render function builds
the message once per language the theme uses and joins them.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from html import escape, unescape

from engine import game
from engine.db import Player
from engine.service import Board, DuelClosed, DuelOffer, DuelRefused, DuelResult, Played, Stats
from engine.theme import Lang, Theme

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
# Keeps "+9" reading left to right inside a Farsi sentence.
_LTR_START, _LTR_END = "⁦", "⁩"

STRINGS: dict[Lang, dict[str, str]] = {
    "en": {
        "rare_good": "✨ Rare event! ",
        "rare_bad": "💥 Rare event! ",
        "streak_bonus": "🔥 {days}-day streak: {bonus} included",
        "next_try": "⏳ Next try in {time}",
        "cooldown": "⏳ {name}, not yet! Next try in {time}.",
        "group_only": "Add me to a group and send /play there. Every group has its own leaderboard.",
        "not_played": "{name}, you haven't played yet. Send /play!",
        "empty_top": "Nobody has played yet. Send /play to start!",
        "rank": "🏅 Rank: #{rank} of {count}",
        "title": "🎽 Title: {title}",
        "streak": "🔥 Streak: {days} days ({bonus} per roll)",
        "streak_none": "🔥 Streak: none yet. Play on consecutive days to build one",
        "next_now": "⏳ Next try: now!",
        "next_in": "⏳ Next try in {time}",
        "you": "You",
        "help": (
            "/play: roll once every {hours} hours\n"
            "/me: your score, rank, title and streak\n"
            "/top: this group's leaderboard\n"
            "/duel @user &lt;stake&gt;: bet points against someone, 50/50 "
            "(or reply to their message with /duel &lt;stake&gt;)\n"
            "/help: this message\n\n"
            "Play on consecutive days for a streak bonus. "
            "Rare events can swing your score a lot, either way. "
            "One duel every {duel_hours} hours; it doesn't use your /play turn."
        ),
        "duel_usage": (
            "⚔️ /duel @user &lt;stake&gt;, or reply to someone's message with /duel &lt;stake&gt;. "
            "The stake is a whole number."
        ),
        "duel_offer": (
            "⚔️ <b>{challenger}</b> challenges <b>{target}</b> to a duel for <b>{stake}</b>!\n"
            "50/50, winner takes the stake. {target}, you have {minutes} minutes to answer."
        ),
        "duel_accept": "⚔️ Accept",
        "duel_decline": "🏳️ Decline",
        "duel_won": "⚔️ <b>{winner}</b> beat <b>{loser}</b> and takes <b>{stake}</b>!",
        "duel_score": "{name}: <b>{score}</b> ({delta}) · {title}",
        "duel_declined": "🏳️ {target} declined {challenger}'s duel.",
        "duel_expired": "⌛ {challenger}'s duel with {target} expired. Nobody answered in time.",
        "duel_self": "{name}, you can't duel yourself.",
        "duel_bot": "Bots don't duel. Challenge a person!",
        "duel_unknown": "I don't know {name} in this group yet. They need to /play here first.",
        "duel_not_played": "{name} hasn't played here yet. Send /play first.",
        "duel_short": "{name} can stake at most {max}.",
        "duel_cooldown": "⏳ {name} dueled recently. Next duel in {time}.",
        "duel_pending": "{name}, you already have an open challenge. Wait for an answer or for it to expire.",
        "duel_not_yours": "This duel isn't for you.",
        "duel_gone": "This duel is already over.",
        "hours_minutes": "{h}h {m}m",
        "hours": "{h}h",
        "minutes": "{m}m",
        "under_minute": "less than a minute",
    },
    "fa": {
        "rare_good": "✨ اتفاق نادر! ",
        "rare_bad": "💥 اتفاق نادر! ",
        "streak_bonus": "🔥 {days} روز پشت سر هم: {bonus} جایزه حساب شد",
        "next_try": "⏳ نوبت بعدی: {time} دیگه",
        "cooldown": "⏳ {name}، هنوز نوبتت نشده! {time} دیگه دوباره امتحان کن.",
        "group_only": "منو به یه گروه اضافه کن و اونجا /play بفرست. هر گروه جدول خودش رو داره.",
        "not_played": "{name}، هنوز بازی نکردی. /play بفرست!",
        "empty_top": "هنوز کسی بازی نکرده. با /play شروع کن!",
        "rank": "🏅 رتبه: {rank} از {count}",
        "title": "🎽 لقب: {title}",
        "streak": "🔥 {days} روز پشت سر هم ({bonus} جایزه در هر بازی)",
        "streak_none": "🔥 هنوز روزهای پشت سر هم نداری. هر روز بازی کن تا جایزه بگیری",
        "next_now": "⏳ نوبت بعدی: همین الان!",
        "next_in": "⏳ نوبت بعدی: {time} دیگه",
        "you": "تو",
        "help": (
            "/play: هر {hours} ساعت یه بار بازی کن\n"
            "/me: امتیاز، رتبه، لقب و روزهای پشت سر همت\n"
            "/top: جدول این گروه\n"
            "/duel @user &lt;امتیاز&gt;: سر امتیاز با یکی دوئل کن، پنجاه‌پنجاه "
            "(یا روی پیامش ریپلای کن و بنویس /duel &lt;امتیاز&gt;)\n"
            "/help: همین راهنما\n\n"
            "اگه چند روز پشت سر هم بازی کنی جایزه می‌گیری. "
            "اتفاق‌های نادر می‌تونن امتیازت رو حسابی بالا یا پایین ببرن. "
            "هر {duel_hours} ساعت یه دوئل می‌تونی بکنی و نوبت /play رو نمی‌سوزونه."
        ),
        "duel_usage": (
            "⚔️ بنویس /duel @user &lt;امتیاز&gt;، یا روی پیام یکی ریپلای کن و بنویس /duel &lt;امتیاز&gt;. "
            "امتیاز باید یه عدد صحیح باشه."
        ),
        "duel_offer": (
            "⚔️ <b>{challenger}</b>، <b>{target}</b> رو سر <b>{stake}</b> به دوئل دعوت کرد!\n"
            "پنجاه‌پنجاهه و برنده همه‌ش رو می‌بره. {target}، {minutes} دقیقه وقت داری جواب بدی."
        ),
        "duel_accept": "⚔️ قبول",
        "duel_decline": "🏳️ نه، مرسی",
        "duel_won": "⚔️ <b>{winner}</b> از <b>{loser}</b> برد و <b>{stake}</b> رو گرفت!",
        "duel_score": "{name}: <b>{score}</b> ({delta}) · {title}",
        "duel_declined": "🏳️ {target} دوئل {challenger} رو قبول نکرد.",
        "duel_expired": "⌛ وقت دوئل {challenger} با {target} تموم شد. کسی به‌موقع جواب نداد.",
        "duel_self": "{name}، با خودت که نمی‌تونی دوئل کنی.",
        "duel_bot": "ربات‌ها دوئل نمی‌کنن. یه آدم رو دعوت کن!",
        "duel_unknown": "{name} رو تو این گروه نمی‌شناسم. اول باید اینجا /play بفرسته.",
        "duel_not_played": "{name} هنوز اینجا بازی نکرده. اول /play بفرسته.",
        "duel_short": "{name} حداکثر می‌تونه {max} بذاره وسط.",
        "duel_cooldown": "⏳ {name} تازه دوئل کرده. دوئل بعدی: {time} دیگه.",
        "duel_pending": "{name}، یه دعوت باز داری. صبر کن جواب بدن یا وقتش تموم شه.",
        "duel_not_yours": "این دوئل مال تو نیست.",
        "duel_gone": "این دوئل تموم شده.",
        "hours_minutes": "{h} ساعت و {m} دقیقه",
        "hours": "{h} ساعت",
        "minutes": "{m} دقیقه",
        "under_minute": "کمتر از یه دقیقه",
    },
}

_MEDALS = ("🥇", "🥈", "🥉")


def _join(theme: Theme, build: Callable[[Lang], str]) -> str:
    return "\n\n".join(build(lang) for lang in theme.langs)


def num(n: int, lang: Lang) -> str:
    text = f"{abs(n):,}"
    if lang == "fa":
        text = text.replace(",", "٬").translate(_FA_DIGITS)
    return f"−{text}" if n < 0 else text


def amount(theme: Theme, n: int, lang: Lang, signed: bool = False) -> str:
    """A score value with its unit, e.g. '120 g', or '+9 g' when signed."""
    text = num(n, lang)
    if signed and n > 0:
        text = f"+{text}"
    if lang == "fa":
        text = f"{_LTR_START}{text}{_LTR_END}"
    return f"{text} {theme.score.unit[lang]}"


def duration(left: timedelta, lang: Lang) -> str:
    # Round up, so "1 minute left" never shows while the cooldown is still 1m30s.
    minutes = -(-int(left.total_seconds()) // 60)
    s = STRINGS[lang]
    if minutes < 1:
        return s["under_minute"]
    h, m = divmod(minutes, 60)
    if h == 0:
        return s["minutes"].format(m=num(m, lang))
    if m == 0:
        return s["hours"].format(h=num(h, lang))
    return s["hours_minutes"].format(h=num(h, lang), m=num(m, lang))


def display_name(first_name: str | None, username: str | None) -> str:
    return escape(first_name or (f"@{username}" if username else "?"))


def play_result(theme: Theme, name: str, r: Played) -> str:
    def build(lang: Lang) -> str:
        s = STRINGS[lang]
        lines = [f"{theme.emoji} <b>{name}</b>"]
        if r.roll.event == "lost_turn":
            # The hook's message is the whole joke: no "+0" after it.
            lines.append(f"🙏 {escape(r.roll.message[lang])}")
        else:
            prefix = {"good": s["rare_good"], "bad": s["rare_bad"]}.get(r.roll.event, "")
            lines.append(
                f"{prefix}{escape(r.roll.message[lang])}: <b>{amount(theme, r.delta, lang, signed=True)}</b>"
            )
        if r.roll.bonus:
            bonus = amount(theme, game.score_delta(theme, r.roll.bonus), lang, signed=True)
            lines.append(s["streak_bonus"].format(days=num(r.streak, lang), bonus=bonus))
        title = game.title_for(theme, r.score).name[lang]
        lines.append(
            f"{theme.score.name[lang]}: <b>{amount(theme, r.score, lang)}</b> · #{num(r.rank, lang)} · {title}"
        )
        lines.append(s["next_try"].format(time=duration(r.cooldown, lang)))
        return "\n".join(lines)

    return _join(theme, build)


def cooldown(theme: Theme, name: str, left: timedelta) -> str:
    return _join(theme, lambda lang: STRINGS[lang]["cooldown"].format(name=name, time=duration(left, lang)))


def me(theme: Theme, name: str, st: Stats) -> str:
    def build(lang: Lang) -> str:
        s = STRINGS[lang]
        p = st.player
        lines = [
            f"{theme.emoji} <b>{name}</b>",
            f"{theme.score.name[lang]}: <b>{amount(theme, p.score, lang)}</b>",
            s["rank"].format(rank=num(st.rank, lang), count=num(st.players, lang)),
            s["title"].format(title=game.title_for(theme, p.score).name[lang]),
        ]
        if p.streak:
            bonus = amount(theme, game.score_delta(theme, game.streak_bonus(p.streak)), lang, signed=True)
            lines.append(s["streak"].format(days=num(p.streak, lang), bonus=bonus))
        else:
            lines.append(s["streak_none"])
        if st.cooldown_left > timedelta(0):
            lines.append(s["next_in"].format(time=duration(st.cooldown_left, lang)))
        else:
            lines.append(s["next_now"])
        return "\n".join(lines)

    return _join(theme, build)


def top(theme: Theme, b: Board) -> str:
    if not b.top:
        return _join(theme, lambda lang: STRINGS[lang]["empty_top"])

    def row(lang: Lang, rank: int, p: Player, you: bool = False) -> str:
        badge = _MEDALS[rank - 1] if rank <= len(_MEDALS) else f"{num(rank, lang)}."
        name = display_name(p.first_name, p.username)
        if you:
            name = f"{STRINGS[lang]['you']} ({name})"
        title = game.title_for(theme, p.score).name[lang]
        return f"{badge} {name}: <b>{amount(theme, p.score, lang)}</b> · {title}"

    def build(lang: Lang) -> str:
        lines = [f"🏆 <b>{theme.leaderboard_title[lang]}</b>", ""]
        # Ties share a rank, like rank_of() in the database.
        rank = 0
        for i, p in enumerate(b.top):
            if i == 0 or p.score != b.top[i - 1].score:
                rank = i + 1
            lines.append(row(lang, rank, p))
        if b.me is not None:
            lines += ["…", row(lang, b.my_rank, b.me, you=True)]
        return "\n".join(lines)

    return _join(theme, build)


def help_text(theme: Theme) -> str:
    def build(lang: Lang) -> str:
        body = STRINGS[lang]["help"].format(
            hours=num(game.DEFAULT_COOLDOWN_HOURS, lang), duel_hours=num(game.DUEL_COOLDOWN_HOURS, lang)
        )
        return f"{theme.emoji} <b>{theme.bot_name[lang]}</b>\n{theme.tagline[lang]}\n\n{body}"

    return _join(theme, build)


def group_only(theme: Theme) -> str:
    return _join(theme, lambda lang: STRINGS[lang]["group_only"])


def not_played(theme: Theme, name: str) -> str:
    return _join(theme, lambda lang: STRINGS[lang]["not_played"].format(name=name))


def _player_name(p: Player) -> str:
    return display_name(p.first_name, p.username)


def duel_usage(theme: Theme) -> str:
    return _join(theme, lambda lang: STRINGS[lang]["duel_usage"])


def duel_offer(theme: Theme, o: DuelOffer) -> str:
    def build(lang: Lang) -> str:
        return STRINGS[lang]["duel_offer"].format(
            challenger=_player_name(o.challenger),
            target=_player_name(o.target),
            stake=amount(theme, o.stake, lang),
            minutes=num(int(game.DUEL_EXPIRY.total_seconds() // 60), lang),
        )

    return _join(theme, build)


def duel_buttons(theme: Theme) -> tuple[str, str]:
    """Accept and Decline labels; a "both" theme shows both languages on each button."""
    def label(key: str) -> str:
        return " / ".join(STRINGS[lang][key] for lang in theme.langs)

    return label("duel_accept"), label("duel_decline")


def duel_result(theme: Theme, r: DuelResult) -> str:
    def build(lang: Lang) -> str:
        s = STRINGS[lang]
        stake = amount(theme, r.stake, lang)
        lines = [s["duel_won"].format(winner=_player_name(r.winner), loser=_player_name(r.loser), stake=stake)]
        for p, delta in ((r.winner, r.winner_delta), (r.loser, -r.winner_delta)):
            lines.append(s["duel_score"].format(
                name=_player_name(p),
                score=amount(theme, p.score, lang),
                delta=amount(theme, delta, lang, signed=True),
                title=game.title_for(theme, p.score).name[lang],
            ))
        return "\n".join(lines)

    return _join(theme, build)


def duel_closed(theme: Theme, c: DuelClosed) -> str:
    key = "duel_declined" if c.status == "declined" else "duel_expired"
    challenger, target = _player_name(c.challenger), _player_name(c.target)
    return _join(theme, lambda lang: STRINGS[lang][key].format(challenger=challenger, target=target))


def duel_refused(theme: Theme, r: DuelRefused) -> str:
    def build(lang: Lang) -> str:
        values = {"name": display_name(r.first_name, r.username)}
        if r.max_stake is not None:
            values["max"] = amount(theme, r.max_stake, lang)
        if r.left is not None:
            values["time"] = duration(r.left, lang)
        return STRINGS[lang][f"duel_{r.reason}"].format(**values)

    return _join(theme, build)


def popup(text: str) -> str:
    """A button pop-up can't show HTML: strip the tags and keep it short."""
    return unescape(text.replace("<b>", "").replace("</b>", "")).replace("\n\n", "\n")[:200]


def duel_popup(theme: Theme, key: str) -> str:
    return popup(_join(theme, lambda lang: STRINGS[lang][key]))
