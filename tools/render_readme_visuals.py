"""Render consistent Chinese copy onto the public README visual assets.

The source images are AI-generated and intentionally contain no text.  This
script overlays deterministic, reviewable Chinese copy using local fonts so
the README never relies on image-model typography.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "readme" / "assets"
FONT_REGULAR = Path(r"C:\Windows\Fonts\msyh.ttc")
FONT_BOLD = Path(r"C:\Windows\Fonts\msyhbd.ttc")
CORAL = "#e95b62"
TEXT = "#4d3635"
MUTED = "#9a7473"
WHITE = (255, 255, 255, 235)


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_BOLD if bold else FONT_REGULAR), size)


def panel(image: Image.Image, box: tuple[int, int, int, int], radius: int = 42) -> None:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rounded_rectangle(box, radius=radius, fill=WHITE)
    image.alpha_composite(overlay)


def center_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
                text_font: ImageFont.FreeTypeFont, fill: str) -> None:
    box = draw.textbbox((0, 0), text, font=text_font)
    draw.text((xy[0] - (box[2] - box[0]) / 2, xy[1]), text, font=text_font, fill=fill)


def render_hero() -> None:
    image = Image.open(ASSETS / "hero-cover.png").convert("RGBA")
    panel(image, (548, 260, 1124, 647), radius=58)
    draw = ImageDraw.Draw(image)
    center_text(draw, (836, 322), "LoveMentor", font(54, bold=True), CORAL)
    center_text(draw, (836, 411), "认真了解一段关系", font(42, bold=True), TEXT)
    center_text(draw, (836, 476), "从看见互动开始", font(28), MUTED)
    panel(image, (656, 548, 1016, 604), radius=28)
    center_text(draw, (836, 560), "本地优先 · 隐私留在自己手里", font(18, bold=True), CORAL)
    image.convert("RGB").save(ASSETS / "hero-cover-captioned.png", quality=95)


def render_overview() -> None:
    image = Image.open(ASSETS / "relationship-overview.png").convert("RGBA")
    panel(image, (152, 680, 1608, 854), radius=34)
    draw = ImageDraw.Draw(image)
    draw.text((204, 716), "关于这段互动", font=font(35, bold=True), fill=CORAL)
    draw.text((204, 772), "看见节奏、回应与真实生活里的细微变化", font=font(27, bold=True), fill=TEXT)
    draw.text((204, 818), "指标只帮助回顾模式；理解和决定，始终留给你自己。", font=font(19), fill=MUTED)
    image.convert("RGB").save(ASSETS / "relationship-overview-captioned.png", quality=95)


def render_journey() -> None:
    image = Image.open(ASSETS / "relationship-journey.png").convert("RGBA")
    draw = ImageDraw.Draw(image)
    labels = ((248, "回顾互动"), (713, "发现变化"), (1181, "理解彼此"), (1644, "审慎行动"))
    for x, label in labels:
        panel(image, (x - 112, 708, x + 112, 766), radius=29)
        center_text(draw, (x, 721), label, font(23, bold=True), CORAL)
    image.convert("RGB").save(ASSETS / "relationship-journey-captioned.png", quality=95)


def main() -> int:
    render_hero()
    render_overview()
    render_journey()
    print("Rendered captioned README visuals.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
