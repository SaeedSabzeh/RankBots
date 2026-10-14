"""Draw the bots' profile pictures as SVG files in assets/avatars/.

Every avatar shares one style: a bold background, a lighter halo, and a cute
character with the same eyes, blush and smile, so the eight bots read as a family.
Telegram crops profile pictures to a circle, so everything stays within ~210px of
the centre of the 512px canvas.

    python scripts/make_avatars.py
Then render the PNGs (640px) to upload with BotFather's /setuserpic.
"""

from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "assets" / "avatars"
INK = "#2B2118"


def frame(bg: str, halo: str, body: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">\n'
        f'<rect width="512" height="512" fill="{bg}"/>\n'
        f'<circle cx="256" cy="256" r="212" fill="{halo}"/>\n'
        f"{body}\n</svg>\n"
    )


def eyes(x1: float, x2: float, y: float, r: float = 14) -> str:
    out = ""
    for x in (x1, x2):
        out += f'<ellipse cx="{x}" cy="{y}" rx="{r * 0.85}" ry="{r}" fill="{INK}"/>'
        out += f'<circle cx="{x - r * 0.3}" cy="{y - r * 0.4}" r="{r * 0.35}" fill="#fff"/>'
    return out


def happy_eyes(x1: float, x2: float, y: float, w: float = 14) -> str:
    """Closed, smiling ^^ eyes."""
    return "".join(
        f'<path d="M{x - w} {y + 4} Q{x} {y - w} {x + w} {y + 4}" '
        f'stroke="{INK}" stroke-width="7" fill="none" stroke-linecap="round"/>'
        for x in (x1, x2)
    )


def blush(x1: float, x2: float, y: float, r: float = 15) -> str:
    return "".join(
        f'<ellipse cx="{x}" cy="{y}" rx="{r}" ry="{r * 0.6}" fill="#FF7A93" opacity="0.55"/>' for x in (x1, x2)
    )


def smile(x: float, y: float, w: float = 16) -> str:
    return (
        f'<path d="M{x - w} {y} Q{x} {y + w * 0.9} {x + w} {y}" '
        f'stroke="{INK}" stroke-width="7" fill="none" stroke-linecap="round"/>'
    )


def sparkle(x: float, y: float, s: float, fill: str = "#FFF6C7") -> str:
    return (
        f'<path d="M{x} {y - s} Q{x + s * 0.15} {y - s * 0.15} {x + s} {y} '
        f'Q{x + s * 0.15} {y + s * 0.15} {x} {y + s} Q{x - s * 0.15} {y + s * 0.15} {x - s} {y} '
        f'Q{x - s * 0.15} {y - s * 0.15} {x} {y - s} Z" fill="{fill}"/>'
    )


def heart(x: float, y: float, s: float, fill: str) -> str:
    return (
        f'<path d="M{x} {y + s * 0.9} C{x - s * 1.4} {y - s * 0.1} {x - s * 0.7} {y - s * 1.1} {x} {y - s * 0.35} '
        f'C{x + s * 0.7} {y - s * 1.1} {x + s * 1.4} {y - s * 0.1} {x} {y + s * 0.9} Z" fill="{fill}"/>'
    )


def cat() -> str:
    fur, light, ear = "#F4A259", "#FBD3A8", "#F7B7A3"
    fluff = "".join(
        f'<circle cx="{256 + 142 * c:.1f}" cy="{282 + 142 * s:.1f}" r="30" fill="{fur}"/>'
        for c, s in [(x, y) for x, y in (
            (1, 0), (0.87, 0.5), (0.5, 0.87), (0, 1), (-0.5, 0.87), (-0.87, 0.5), (-1, 0),
            (-0.94, -0.34), (0.94, -0.34),
        )]
    )
    body = f"""
<ellipse cx="256" cy="452" rx="150" ry="18" fill="#000" opacity="0.08"/>
<polygon points="128,214 150,72 254,160" fill="{fur}"/>
<polygon points="384,214 362,72 258,160" fill="{fur}"/>
<polygon points="152,190 162,108 222,160" fill="{ear}"/>
<polygon points="360,190 350,108 290,160" fill="{ear}"/>
{fluff}
<circle cx="256" cy="282" r="150" fill="{fur}"/>
<path d="M224 150 Q230 164 236 172 M256 144 L256 170 M288 150 Q282 164 276 172" stroke="#E07A2E" stroke-width="9" fill="none" stroke-linecap="round"/>
<ellipse cx="256" cy="330" rx="62" ry="44" fill="{light}"/>
{eyes(200, 312, 278, 18)}
{blush(176, 336, 320, 18)}
<path d="M244 312 L268 312 L256 326 Z" fill="#E5677C"/>
<path d="M234 334 Q245 348 256 334 Q267 348 278 334" stroke="{INK}" stroke-width="6" fill="none" stroke-linecap="round"/>
<path d="M172 312 L104 300 M172 328 L106 336 M340 312 L408 300 M340 328 L406 336" stroke="{INK}" stroke-width="4" stroke-linecap="round" opacity="0.7"/>
<polygon points="256,424 196,396 196,452" fill="#E63946"/>
<polygon points="256,424 316,396 316,452" fill="#E63946"/>
<circle cx="256" cy="424" r="16" fill="#C1121F"/>
{sparkle(108, 150, 18)}{sparkle(410, 168, 12)}
"""
    return frame("#8ECAE6", "#BFE2F2", body)


def tahdig() -> str:
    grains = "".join(
        f'<ellipse cx="{x}" cy="{y}" rx="9" ry="4" fill="#F9D67A" transform="rotate({r} {x} {y})"/>'
        for x, y, r in (
            (150, 236, 20), (178, 214, -30), (330, 214, 35), (360, 238, -15), (172, 268, 60),
            (342, 270, -50), (214, 202, 10), (296, 200, -20), (390, 252, 40), (124, 254, -35),
            (256, 196, 75), (210, 290, -10), (304, 292, 25),
        )
    )
    body = f"""
<ellipse cx="256" cy="340" rx="202" ry="74" fill="#F1FAEE"/>
<ellipse cx="256" cy="336" rx="182" ry="62" fill="none" stroke="#457B9D" stroke-width="7"/>
<ellipse cx="256" cy="336" rx="160" ry="52" fill="none" stroke="#457B9D" stroke-width="3" stroke-dasharray="10 8"/>
<ellipse cx="256" cy="300" rx="168" ry="62" fill="#9C4A14"/>
<rect x="88" y="244" width="336" height="56" fill="#9C4A14"/>
<path d="M88 270 Q130 290 172 270 T256 270 T340 270 T424 270 L424 300 L88 300 Z" fill="#B5651D"/>
<ellipse cx="256" cy="244" rx="168" ry="62" fill="#EDA93A"/>
<ellipse cx="256" cy="240" rx="150" ry="52" fill="#F2B544"/>
{grains}
<circle cx="140" cy="240" r="9" fill="#D98A1F"/><circle cx="372" cy="232" r="7" fill="#D98A1F"/>
{eyes(220, 292, 236, 14)}
{blush(196, 316, 260, 14)}
{smile(256, 258, 16)}
{sparkle(118, 150, 20)}{sparkle(396, 132, 26)}{sparkle(410, 196, 12)}
"""
    return frame("#2A9D8F", "#5DBDB0", body)


def chai() -> str:
    glass = (
        "M176 140 C176 214 208 236 208 284 C208 330 186 350 186 386 "
        "L326 386 C326 350 304 330 304 284 C304 236 336 214 336 140 Z"
    )
    body = f"""
<defs>
  <clipPath id="g"><path d="{glass}"/></clipPath>
  <linearGradient id="tea" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#E26D2C"/><stop offset="1" stop-color="#9E2A12"/>
  </linearGradient>
</defs>
<path d="M214 118 C196 96 232 84 214 60 M256 118 C238 96 274 84 256 56 M298 118 C280 96 316 84 298 60" stroke="#fff" stroke-width="9" fill="none" stroke-linecap="round" opacity="0.7"/>
<ellipse cx="256" cy="398" rx="160" ry="36" fill="#F1FAEE"/>
<ellipse cx="256" cy="394" rx="116" ry="22" fill="#D7E3EA"/>
<ellipse cx="256" cy="398" rx="160" ry="36" fill="none" stroke="#E9C46A" stroke-width="6"/>
<path d="{glass}" fill="#FFFFFF" opacity="0.28"/>
<rect x="150" y="176" width="210" height="220" fill="url(#tea)" clip-path="url(#g)"/>
<ellipse cx="256" cy="178" rx="74" ry="9" fill="#F08A4B" clip-path="url(#g)"/>
<path d="{glass}" fill="none" stroke="#EAF4F4" stroke-width="7"/>
<path d="M192 166 C194 212 220 236 222 282" stroke="#fff" stroke-width="8" fill="none" stroke-linecap="round" opacity="0.55"/>
<line x1="176" y1="140" x2="336" y2="140" stroke="#E9C46A" stroke-width="9" stroke-linecap="round"/>
{eyes(230, 284, 290, 13)}
{blush(212, 302, 314, 12)}
{smile(257, 312, 14)}
<g transform="rotate(-12 372 360)">
  <rect x="348" y="336" width="48" height="44" rx="6" fill="#FFFFFF"/>
  <rect x="348" y="336" width="48" height="12" rx="6" fill="#E9EEF2"/>
</g>
{sparkle(126, 190, 16)}{sparkle(396, 220, 12)}
"""
    return frame("#264653", "#36606F", body)


def taarof() -> str:
    """A sweets dish held out with a bashful cream puff: "befarmaid!"."""
    body = f"""
<ellipse cx="256" cy="436" rx="110" ry="14" fill="#000" opacity="0.08"/>
<path d="M86 300 Q116 376 200 384 L312 384 Q396 376 426 300 Z" fill="#DEE2E6"/>
<rect x="234" y="382" width="44" height="30" fill="#CED4DA"/>
<ellipse cx="256" cy="418" rx="76" ry="16" fill="#CED4DA"/>
<ellipse cx="256" cy="300" rx="170" ry="40" fill="#C9CFD5"/>
<circle cx="160" cy="262" r="50" fill="#E9A23B"/>
<circle cx="160" cy="262" r="31" fill="none" stroke="#C97C1C" stroke-width="5" stroke-dasharray="6 7"/>
<circle cx="160" cy="262" r="8" fill="#C97C1C"/>
<g transform="rotate(45 352 262)">
  <rect x="310" y="220" width="84" height="84" rx="10" fill="#D4A373"/>
  <rect x="322" y="232" width="60" height="60" rx="6" fill="#C08552"/>
</g>
<circle cx="342" cy="248" r="6" fill="#90BE6D"/><circle cx="364" cy="264" r="5" fill="#90BE6D"/><circle cx="348" cy="278" r="5" fill="#90BE6D"/>
<circle cx="256" cy="228" r="78" fill="#F4D19B"/>
<path d="M186 206 Q256 126 326 206 Q302 178 256 178 Q210 178 186 206 Z" fill="#FFFFFF"/>
<circle cx="214" cy="186" r="4" fill="#fff"/><circle cx="300" cy="188" r="4" fill="#fff"/><circle cx="256" cy="166" r="4" fill="#fff"/>
{happy_eyes(228, 284, 232, 13)}
{blush(204, 308, 254, 14)}
{smile(256, 256, 13)}
<path d="M86 300 A170 40 0 0 0 426 300 L426 312 A170 40 0 0 1 86 312 Z" fill="#E9ECEF"/>
<path d="M86 300 A170 40 0 0 0 426 300" fill="none" stroke="#F8F9FA" stroke-width="6"/>
{heart(124, 156, 20, "#FF7A93")}{heart(392, 140, 16, "#FF7A93")}{heart(410, 204, 10, "#FF7A93")}
"""
    return frame("#B392C9", "#D3BCE2", body)


def sekkeh() -> str:
    stack = ""
    for i, (y, dx) in enumerate([(404, 0), (384, -6), (364, 5), (344, -3), (324, 4)]):
        cx = 336 + dx
        stack += (
            f'<ellipse cx="{cx}" cy="{y + 16}" rx="72" ry="22" fill="#B8860B"/>'
            f'<rect x="{cx - 72}" y="{y}" width="144" height="16" fill="#B8860B"/>'
            f'<ellipse cx="{cx}" cy="{y}" rx="72" ry="22" fill="#FFD166"/>'
            f'<ellipse cx="{cx}" cy="{y}" rx="52" ry="14" fill="none" stroke="#E0A800" stroke-width="4"/>'
        )
    body = f"""
<ellipse cx="270" cy="440" rx="170" ry="16" fill="#000" opacity="0.15"/>
{stack}
<circle cx="214" cy="284" r="128" fill="#D4A017"/>
<circle cx="206" cy="276" r="124" fill="#FFD166"/>
<circle cx="206" cy="276" r="98" fill="none" stroke="#E0A800" stroke-width="8"/>
<path d="M120 230 A100 100 0 0 1 200 170" stroke="#fff" stroke-width="10" fill="none" stroke-linecap="round" opacity="0.6"/>
{eyes(176, 238, 270, 15)}
{blush(152, 262, 298, 15)}
{smile(207, 296, 17)}
{sparkle(110, 140, 22)}{sparkle(380, 150, 30)}{sparkle(418, 228, 14)}{sparkle(330, 96, 12)}
"""
    return frame("#9D0208", "#B71C25", body)


def mom() -> str:
    scallops = "".join(
        f'<circle cx="{256 + 128 * c:.1f}" cy="{230 + 128 * s:.1f}" r="30" fill="#E63946"/>'
        for c, s in (
            (1, 0), (0.92, 0.38), (0.71, 0.71), (0.38, 0.92), (0, 1), (-0.38, 0.92), (-0.71, 0.71),
            (-0.92, 0.38), (-1, 0), (-0.92, -0.38), (-0.71, -0.71), (-0.38, -0.92), (0, -1),
            (0.38, -0.92), (0.71, -0.71), (0.92, -0.38),
        )
    )
    body = f"""
<polygon points="206,300 168,452 204,432 228,460 252,318" fill="#457B9D"/>
<polygon points="306,300 344,452 308,432 284,460 260,318" fill="#457B9D"/>
<polygon points="216,316 192,420 212,410 236,320" fill="#5E95BA"/>
{scallops}
<circle cx="256" cy="230" r="128" fill="#E63946"/>
<circle cx="256" cy="230" r="100" fill="#FFD166"/>
<circle cx="256" cy="230" r="86" fill="none" stroke="#F4A261" stroke-width="6"/>
{heart(256, 168, 18, "#E63946")}
{eyes(224, 288, 226, 15)}
{blush(200, 312, 254, 15)}
<path d="M226 254 Q256 296 286 254 Z" fill="#7A2E2E"/>
<path d="M240 270 Q256 286 272 270 Q256 262 240 270 Z" fill="#FF7A93"/>
{heart(110, 120, 18, "#FF7A93")}{heart(410, 112, 14, "#FF7A93")}{heart(424, 330, 12, "#FF7A93")}{heart(92, 340, 10, "#FF7A93")}
"""
    return frame("#FF9EBB", "#FFC8D9", body)


def konkur() -> str:
    bubbles = ""
    for row in range(5):
        y = 248 + row * 28
        filled = (row * 3 + 1) % 4
        for col in range(4):
            x = 196 + col * 40
            if col == filled:
                bubbles += f'<circle cx="{x}" cy="{y}" r="10" fill="{INK}"/>'
            else:
                bubbles += f'<circle cx="{x}" cy="{y}" r="10" fill="none" stroke="#ADB5BD" stroke-width="3"/>'
    body = f"""
<ellipse cx="256" cy="430" rx="130" ry="14" fill="#000" opacity="0.12"/>
<g transform="rotate(-6 256 256)">
  <rect x="146" y="112" width="220" height="296" rx="18" fill="#FFFFFF"/>
  <rect x="146" y="112" width="220" height="40" rx="18" fill="#FFBE0B"/>
  <rect x="146" y="134" width="220" height="18" fill="#FFBE0B"/>
  {eyes(222, 290, 186, 15)}
  <path d="M232 222 Q244 212 256 222 Q268 232 280 222" stroke="{INK}" stroke-width="6" fill="none" stroke-linecap="round"/>
  <path d="M206 164 L236 170 M306 164 L276 170" stroke="{INK}" stroke-width="5" stroke-linecap="round"/>
  {bubbles}
</g>
<path d="M352 150 Q366 172 352 182 Q338 172 352 150 Z" fill="#BDE0FE"/>
<g transform="rotate(-45 360 360)">
  <rect x="300" y="344" width="130" height="32" fill="#FFBE0B"/>
  <rect x="300" y="354" width="130" height="10" fill="#F4A100"/>
  <rect x="430" y="344" width="22" height="32" fill="#ADB5BD"/>
  <rect x="452" y="344" width="22" height="32" rx="8" fill="#FF8FA3"/>
  <polygon points="300,344 300,376 262,360" fill="#F4D19B"/>
  <polygon points="276,354 276,366 262,360" fill="{INK}"/>
</g>
<g transform="rotate(-10 150 120)">
  <polygon points="150,84 214,112 150,140 86,112" fill="#212529"/>
  <path d="M118 124 L118 150 Q150 166 182 150 L182 124 Z" fill="#212529"/>
  <path d="M150 112 L196 128 L196 160" stroke="#FFBE0B" stroke-width="5" fill="none"/>
  <circle cx="196" cy="164" r="7" fill="#FFBE0B"/>
</g>
{sparkle(406, 140, 18)}{sparkle(110, 300, 12)}
"""
    return frame("#3A86FF", "#6AA4FF", body)


def terafik() -> str:
    body = f"""
<rect x="368" y="96" width="44" height="112" rx="14" fill="#212529"/>
<circle cx="390" cy="122" r="12" fill="#E63946"/>
<circle cx="390" cy="152" r="12" fill="#5C4400"/>
<circle cx="390" cy="182" r="12" fill="#1B4332"/>
<path d="M92 214 L68 196 M92 240 L62 240 M92 266 L68 284" stroke="#fff" stroke-width="8" stroke-linecap="round" opacity="0.8"/>
<ellipse cx="256" cy="428" rx="170" ry="16" fill="#000" opacity="0.12"/>
<rect x="138" y="352" width="46" height="62" rx="12" fill="#212529"/>
<rect x="328" y="352" width="46" height="62" rx="12" fill="#212529"/>
<path d="M162 238 L192 152 L320 152 L350 238 Z" fill="#F1FAEE"/>
<path d="M180 232 L204 166 L308 166 L332 232 Z" fill="#8ECAE6"/>
<path d="M196 226 L214 176 L236 176 L214 226 Z" fill="#fff" opacity="0.35"/>
<rect x="112" y="230" width="288" height="134" rx="30" fill="#F1FAEE"/>
<rect x="96" y="232" width="26" height="18" rx="6" fill="#ADB5BD"/>
<rect x="390" y="232" width="26" height="18" rx="6" fill="#ADB5BD"/>
{eyes(232, 280, 206, 13)}
<path d="M214 182 L244 190 M298 182 L268 190" stroke="{INK}" stroke-width="5" stroke-linecap="round"/>
<circle cx="162" cy="284" r="26" fill="#FFE066"/><circle cx="162" cy="284" r="14" fill="#FFF6C7"/>
<circle cx="350" cy="284" r="26" fill="#FFE066"/><circle cx="350" cy="284" r="14" fill="#FFF6C7"/>
<rect x="204" y="266" width="104" height="42" rx="10" fill="#FFFFFF" stroke="{INK}" stroke-width="5"/>
<path d="M230 266 L230 308 M256 266 L256 308 M282 266 L282 308 M204 287 L308 287" stroke="{INK}" stroke-width="4"/>
<rect x="104" y="330" width="304" height="26" rx="12" fill="#6C757D"/>
<rect x="226" y="334" width="60" height="18" rx="4" fill="#F8F9FA"/>
<path d="M346 148 Q360 170 346 180 Q332 170 346 148 Z" fill="#BDE0FE"/>
<path d="M372 196 Q382 212 372 220 Q362 212 372 196 Z" fill="#BDE0FE"/>
"""
    return frame("#FB8500", "#FFA436", body)


AVATARS = {
    "cat": cat, "tahdig": tahdig, "chai": chai, "taarof": taarof,
    "khastegari": sekkeh, "mom": mom, "konkur": konkur, "traffic": terafik,
}


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, draw in AVATARS.items():
        (OUT / f"{name}.svg").write_text(draw(), encoding="utf-8")
        print("wrote", OUT / f"{name}.svg")
