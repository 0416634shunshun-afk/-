#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
デモ用の入力一式（誌面PDF・原本フォルダ・リンク一覧CSV）を作る。

実案件では
  誌面PDF   … InDesign等から書き出したもの
  原本       … 誌面に配置した .psd/.ai などのリンク元
  リンク一覧 … InDesignの「リンク」パネルから書き出した対応表
を用意するが、ここでは架空ブランドの資料を丸ごと生成して、
build_catalog.py が動く状態を再現できるようにしている。
"""
from __future__ import annotations

import csv
import math
import random
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path("demo_src")
ASSETS = OUT / "assets"
NAVY, BLUE, GREEN, INK = (13, 43, 107), (0, 102, 204), (0, 176, 80), (26, 26, 46)
FONT_PATH = "/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf"
random.seed(20260220)


def font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except OSError:
        return ImageFont.load_default()


def save(im: Image.Image, name: str) -> str:
    ASSETS.mkdir(parents=True, exist_ok=True)
    p = ASSETS / name
    im.save(p)
    return name


# ---------------------------------------------------------------- 素材づくり
def ring_light(size: int, color: tuple[int, int, int], lows: bool = False) -> Image.Image:
    """リング照明の製品CG風。透明背景（当たり判定を形どおりにするため）。"""
    s = size * 2
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    outer, inner = s * 0.47, s * 0.24
    cx = cy = s / 2
    for i in range(60):
        t = i / 59
        r = outer - (outer - inner) * t
        shade = int(210 - 90 * t) if not lows else int(190 - 70 * t)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(shade, shade + 4, shade + 10, 255))
    d.ellipse([cx - inner, cy - inner, cx + inner, cy + inner], fill=(0, 0, 0, 0))
    n = 28 if not lows else 36
    for i in range(n):
        a = 2 * math.pi * i / n
        rr = (outer + inner) / 2
        x, y = cx + rr * math.cos(a), cy + rr * math.sin(a)
        led = size * 0.045
        d.ellipse([x - led, y - led, x + led, y + led],
                  fill=color + (255,), outline=(255, 255, 255, 200))
    glow = im.filter(ImageFilter.GaussianBlur(s * 0.012))
    im = Image.alpha_composite(glow, im)
    return im.resize((size, size), Image.LANCZOS)


def spectral_chart(w: int, h: int) -> Image.Image:
    im = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(im)
    m = 54
    d.rectangle([m, 14, w - 14, h - m], outline=(210, 216, 228))
    for i in range(1, 5):
        y = 14 + (h - m - 14) * i / 5
        d.line([m, y, w - 14, y], fill=(233, 237, 245))
    curves = [((214, 60, 60), 630, 22, "赤色 630 nm"),
              ((60, 170, 90), 525, 26, "緑色 525 nm"),
              ((60, 110, 220), 470, 20, "青色 470 nm")]
    for color, peak, width, _ in curves:
        pts = []
        for px in range(m, w - 14):
            nm = 350 + (px - m) / (w - 14 - m) * 450
            v = math.exp(-((nm - peak) ** 2) / (2 * width ** 2))
            pts.append((px, (h - m) - v * (h - m - 24)))
        d.line(pts, fill=color, width=3)
    f = font(15)
    for i, nm in enumerate(range(350, 801, 150)):
        x = m + (nm - 350) / 450 * (w - 14 - m)
        d.text((x - 14, h - m + 6), str(nm), font=f, fill=(107, 114, 128))
    d.text((w / 2 - 40, h - 26), "波長（nm）", font=f, fill=(107, 114, 128))
    d.text((8, 20), "相対放射強度", font=f, fill=(107, 114, 128))
    return im


def directivity_chart(w: int, h: int, wide: bool = False) -> Image.Image:
    im = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(im)
    cx, cy, r = w / 2, h * 0.9, min(w / 2, h * 0.8) - 16
    for k in (0.25, 0.5, 0.75, 1.0):
        d.arc([cx - r * k, cy - r * k, cx + r * k, cy + r * k], 180, 360, fill=(220, 226, 238))
    for deg in range(-90, 91, 30):
        a = math.radians(deg - 90)
        d.line([cx, cy, cx + r * math.cos(a), cy + r * math.sin(a)], fill=(228, 233, 243))
    pts = []
    spread = 55 if wide else 28
    for deg in range(-90, 91):
        v = math.exp(-(deg ** 2) / (2 * spread ** 2))
        a = math.radians(deg - 90)
        pts.append((cx + r * v * math.cos(a), cy + r * v * math.sin(a)))
    d.line(pts, fill=BLUE, width=3)
    f = font(13)
    for deg in (-90, -45, 0, 45, 90):
        a = math.radians(deg - 90)
        d.text((cx + (r + 6) * math.cos(a) - 12, cy + (r + 6) * math.sin(a) - 8),
               f"{deg:+d}°".replace("+0", "0"), font=f, fill=(107, 114, 128))
    return im


def dimension_drawing(w: int, h: int, label: str) -> Image.Image:
    im = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(im)
    cx, cy = w / 2, h / 2
    ro, ri = min(w, h) * 0.34, min(w, h) * 0.17
    d.ellipse([cx - ro, cy - ro, cx + ro, cy + ro], outline=INK, width=3)
    d.ellipse([cx - ri, cy - ri, cx + ri, cy + ri], outline=INK, width=2)
    for i in range(4):
        a = math.radians(45 + 90 * i)
        x, y = cx + (ro + ri) / 2 * math.cos(a), cy + (ro + ri) / 2 * math.sin(a)
        d.ellipse([x - 5, y - 5, x + 5, y + 5], outline=INK, width=2)
    d.line([cx - ro, cy + ro + 26, cx + ro, cy + ro + 26], fill=INK, width=2)
    for sx in (cx - ro, cx + ro):
        d.line([sx, cy + ro + 18, sx, cy + ro + 34], fill=INK, width=2)
    f = font(19)
    d.text((cx - 26, cy + ro + 32), label, font=f, fill=INK)
    d.text((cx - ri + 6, cy - 12), "Ø30", font=font(16), fill=INK)
    d.text((14, 12), "4-M3深4（取付用）", font=font(15), fill=(107, 114, 128))
    return im


def structure_diagram(w: int, h: int) -> Image.Image:
    im = Image.new("RGB", (w, h), (250, 251, 254))
    d = ImageDraw.Draw(im)
    d.rectangle([w * 0.12, h * 0.30, w * 0.88, h * 0.52], fill=(196, 202, 214), outline=INK)
    d.rectangle([w * 0.14, h * 0.52, w * 0.86, h * 0.60], fill=(235, 148, 60), outline=INK)
    d.rectangle([w * 0.16, h * 0.60, w * 0.84, h * 0.68], fill=(70, 90, 130), outline=INK)
    for i in range(9):
        x = w * (0.20 + 0.075 * i)
        d.polygon([(x, h * 0.68), (x + 12, h * 0.68), (x + 6, h * 0.80)], fill=(214, 60, 60))
    f = font(16)
    d.text((w * 0.06, h * 0.36), "アルミ筐体", font=f, fill=INK)
    d.text((w * 0.06, h * 0.53), "放熱材", font=f, fill=INK)
    d.text((w * 0.06, h * 0.61), "実装基板", font=f, fill=INK)
    d.text((w * 0.62, h * 0.84), "砲弾型LED", font=f, fill=INK)
    return im


def sample_shot(w: int, h: int, good: bool) -> Image.Image:
    """撮像例（良い例／悪い例）。刻印文字入りの金属ワーク風。"""
    im = Image.new("RGB", (w, h), (24, 24, 28) if good else (58, 58, 64))
    d = ImageDraw.Draw(im)
    for _ in range(2600):
        x, y = random.randrange(w), random.randrange(h)
        v = random.randint(0, 40)
        d.point((x, y), fill=(v + 20, v + 20, v + 24))
    cx, cy, r = w / 2, h / 2, min(w, h) * 0.36
    for i in range(40):
        t = i / 39
        rr = r * (1 - t * 0.02)
        base = (150 if good else 96) - int(60 * t)
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=(base, base, base + 4), width=3)
    txt = "LDX-90"
    f = font(int(r * 0.42))
    tw = d.textlength(txt, font=f)
    fill = (245, 245, 245) if good else (110, 110, 116)
    d.text((cx - tw / 2, cy - r * 0.24), txt, font=f, fill=fill)
    if not good:
        im = im.filter(ImageFilter.GaussianBlur(1.4))
    return im


def work_photo(w: int, h: int) -> Image.Image:
    im = Image.new("RGB", (w, h), (238, 240, 246))
    d = ImageDraw.Draw(im)
    cx, cy, r = w / 2, h / 2, min(w, h) * 0.33
    for i in range(50):
        t = i / 49
        rr = r * (1 - t * 0.5)
        v = 200 - int(70 * t)
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=(v, v, v + 6))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(120, 122, 130), width=3)
    d.text((cx - 44, cy - 12), "LDX-90", font=font(24), fill=(90, 92, 100))
    return im


def header_band(w: int, h: int) -> Image.Image:
    im = Image.new("RGB", (w, h), NAVY)
    d = ImageDraw.Draw(im)
    for x in range(w):
        d.line([x, 0, x, h], fill=(NAVY[0] + int(40 * x / w), NAVY[1] + int(30 * x / w),
                                   NAVY[2] + int(20 * x / w)))
    d.rectangle([0, h - 6, w, h], fill=GREEN)
    return im


def logo_mark(size: int) -> Image.Image:
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([2, 2, size - 3, size - 3], outline=GREEN + (255,), width=int(size * 0.09))
    d.ellipse([size * 0.3, size * 0.3, size * 0.7, size * 0.7], fill=BLUE + (255,))
    return im


def qr_dummy(size: int) -> Image.Image:
    im = Image.new("RGB", (size, size), "white")
    d = ImageDraw.Draw(im)
    n, cell = 21, size / 25
    off = cell * 2
    for y in range(n):
        for x in range(n):
            if random.random() < 0.45:
                d.rectangle([off + x * cell, off + y * cell,
                             off + (x + 1) * cell, off + (y + 1) * cell], fill="black")
    for ox, oy in ((0, 0), (n - 7, 0), (0, n - 7)):
        d.rectangle([off + ox * cell, off + oy * cell,
                     off + (ox + 7) * cell, off + (oy + 7) * cell], fill="white")
        d.rectangle([off + ox * cell, off + oy * cell,
                     off + (ox + 7) * cell, off + (oy + 7) * cell], outline="black",
                    width=int(cell))
        d.rectangle([off + (ox + 2) * cell, off + (oy + 2) * cell,
                     off + (ox + 5) * cell, off + (oy + 5) * cell], fill="black")
    return im


def build_assets() -> dict[str, str]:
    """{識別名: ファイル名} を返す。サイズは全て別々にして、後で照合できるようにする。"""
    a = {}
    a["ring_red"] = save(ring_light(900, (226, 60, 60)), "ring_light_red.png")
    a["ring_white"] = save(ring_light(880, (245, 245, 235)), "ring_light_white.png")
    a["ring_blue"] = save(ring_light(860, (70, 130, 240)), "ring_light_blue.png")
    a["ring_low"] = save(ring_light(840, (226, 60, 60), lows=True), "lowangle_ring_red.png")
    a["spectral"] = save(spectral_chart(1180, 700), "chart_spectral.png")
    a["directivity_n"] = save(directivity_chart(760, 520), "chart_directivity_narrow.png")
    a["directivity_w"] = save(directivity_chart(740, 500, wide=True), "chart_directivity_wide.png")
    a["dim_a"] = save(dimension_drawing(820, 640, "Ø56"), "dimensions_ldx56.png")
    a["dim_b"] = save(dimension_drawing(800, 620, "Ø90"), "dimensions_ldx90.png")
    a["structure"] = save(structure_diagram(1000, 660), "structure_section.png")
    a["shot_ng"] = save(sample_shot(1024, 768, good=False), "sample_before_ringlight.png")
    a["shot_ok"] = save(sample_shot(1000, 750, good=True), "sample_after_ldx90.png")
    a["work"] = save(work_photo(960, 720), "work_metal_part.png")
    a["header"] = save(header_band(1400, 90), "header_band.png")
    a["logo"] = save(logo_mark(320), "logo_mark.png")
    a["qr"] = save(qr_dummy(300), "qr_contact.png")
    return a


# ---------------------------------------------------------------- 誌面づくり
JP = "japan"


def text(page, xy, s, size=10.5, color=INK, font_name=JP):
    page.insert_text(xy, s, fontname=font_name, fontsize=size,
                     color=tuple(c / 255 for c in color))


def band(page, title, sub=""):
    page.insert_image(pymupdf.Rect(0, 0, 595, 38), filename=str(ASSETS / "header_band.png"))
    text(page, (32, 25), title, 13, (255, 255, 255))
    if sub:
        text(page, (400, 25), sub, 9, (215, 225, 240))


def footer(page, n, note="架空のデモ資料です（実在の製品・企業とは関係ありません）"):
    text(page, (32, 812), note, 7.5, (140, 145, 158))
    text(page, (545, 812), f"{n}", 11, NAVY)


def make_pdf(a: dict[str, str]) -> Path:
    doc = pymupdf.open()
    A = lambda k: str(ASSETS / a[k])
    R = pymupdf.Rect

    # P1 表紙
    p = doc.new_page(width=595, height=842)
    p.draw_rect(R(0, 0, 595, 842), color=None, fill=(0.05, 0.17, 0.42))
    p.insert_image(R(60, 60, 130, 130), filename=A("logo"))
    text(p, (60, 200), "アカガネ光学工業", 22, (255, 255, 255))
    text(p, (60, 240), "LED照明 総合カタログ 2026", 30, (200, 240, 160))
    text(p, (60, 275), "リング照明 LDX シリーズ / ローアングル LDX-LA シリーズ", 12, (200, 214, 238))
    p.insert_image(R(150, 330, 450, 630), filename=A("ring_red"))
    text(p, (60, 700), "直射光・拡散光・同軸落射 — マシンビジョン用照明の総合ラインアップ", 11, (200, 214, 238))
    text(p, (60, 730), "※ 本資料は、ビューア動作確認用に自動生成した架空カタログです。", 9, (150, 170, 200))

    # P2 特長
    p = doc.new_page(width=595, height=842)
    band(p, "リング照明 LDX シリーズ｜特長", "直射光")
    text(p, (32, 80), "角度のある発光部から直射光を照射", 17, NAVY)
    for i, s in enumerate([
        "フレキシブル基板を用いることで、リング照明に求められる機能を実現しました。",
        "ワークに対して角度をつけた照射が可能で、ワーク全体に光を届けます。",
        "わずかな位置ズレや傾きを吸収し、安定した撮像を可能にします。",
    ]):
        text(p, (32, 110 + i * 20), s, 10.5)
    p.insert_image(R(32, 190, 292, 362), filename=A("structure"))
    text(p, (32, 380), "LDX-90 の断面構造イメージ", 9.5, (107, 114, 128))
    p.insert_image(R(320, 180, 560, 420), filename=A("ring_white"))
    text(p, (320, 440), "LDX-90SW（白色）", 9.5, (107, 114, 128))
    text(p, (32, 470), "用途例", 13, NAVY)
    text(p, (32, 495), "各種文字認識 ／ 外観検査 ／ キズ・汚れ検査 ／ 2次元コード読み取り ／ 基板上の部品検査", 10)
    text(p, (32, 540), "LEDの温度上昇を大幅に抑制", 13, NAVY)
    text(p, (32, 565), "基板とアルミ筐体の間に放熱材を密着させ、LEDから発生する熱を吸収します。", 10)
    p.insert_image(R(320, 590, 560, 760), filename=A("ring_blue"))
    text(p, (320, 778), "LDX-90BL（青色）", 9.5, (107, 114, 128))
    footer(p, 2)

    # P3 撮像例
    p = doc.new_page(width=595, height=842)
    band(p, "リング照明 LDX シリーズ｜撮像例", "金属部品の刻印文字")
    text(p, (32, 80), "撮像例 ： 金属部品の刻印文字撮像", 15, NAVY)
    p.insert_image(R(32, 110, 205, 240), filename=A("work"))
    text(p, (32, 255), "ワーク画像", 10, (107, 114, 128))
    p.insert_image(R(215, 110, 388, 240), filename=A("shot_ng"))
    text(p, (215, 255), "従来のリング照明", 10, (107, 114, 128))
    text(p, (215, 272), "梨地面の反射に埋もれ、文字の判別が困難。", 9, (107, 114, 128))
    p.insert_image(R(398, 110, 563, 234), filename=A("shot_ok"))
    text(p, (398, 255), "LDX-90RD", 10, (107, 114, 128))
    text(p, (398, 272), "文字のエッジを強調して撮像できる。", 9, (107, 114, 128))
    text(p, (32, 330), "データ ： 相対放射照度グラフ／均一度（代表例）", 13, NAVY)
    p.insert_image(R(32, 360, 330, 537), filename=A("spectral"))
    text(p, (32, 555), "分光分布（代表例）", 9.5, (107, 114, 128))
    text(p, (32, 600), "掲載しているデータは参考値です。製品の品質を保証するものではありません。", 9, (107, 114, 128))
    footer(p, 3)

    # P4 LED特性
    p = doc.new_page(width=595, height=842)
    band(p, "リング照明 LDX シリーズ｜LED特性", "指向特性")
    text(p, (32, 80), "指向特性", 15, NAVY)
    p.insert_image(R(32, 110, 292, 288), filename=A("directivity_n"))
    text(p, (32, 305), "ナロータイプ（型式末尾なし）", 10, (107, 114, 128))
    p.insert_image(R(310, 110, 563, 281), filename=A("directivity_w"))
    text(p, (310, 305), "ワイドタイプ（型式末尾 -WD）", 10, (107, 114, 128))
    text(p, (32, 360), "ラインアップ一覧", 15, NAVY)
    rows = [("LDX-32RD", "赤色", "24 V / 1.6 W", "630 nm", "30 g"),
            ("LDX-50SW", "白色", "24 V / 3.8 W", "5,500 K", "50 g"),
            ("LDX-70BL", "青色", "24 V / 7.6 W", "470 nm", "120 g"),
            ("LDX-90RD", "赤色", "24 V / 11 W", "630 nm", "170 g"),
            ("LDX-120GR", "緑色", "24 V / 26 W", "525 nm", "500 g")]
    heads = ("型式名", "LED発光色", "消費電力", "ピーク発光波長", "質量")
    xs = (32, 150, 240, 350, 480)
    for x, hd in zip(xs, heads):
        text(p, (x, 392), hd, 10, NAVY)
    p.draw_line(pymupdf.Point(32, 398), pymupdf.Point(563, 398), color=(0.8, 0.85, 0.92))
    for i, row in enumerate(rows):
        for x, v in zip(xs, row):
            text(p, (x, 418 + i * 22), v, 10)
    text(p, (32, 560), "ご使用に際しては、製品に添付の取扱説明書を必ずお読みください。", 9.5, (107, 114, 128))
    footer(p, 4)

    # P5 寸法図
    p = doc.new_page(width=595, height=842)
    band(p, "リング照明 LDX シリーズ｜外形寸法図", "mm")
    text(p, (32, 80), "外形寸法図（mm）", 15, NAVY)
    p.insert_image(R(32, 110, 285, 308), filename=A("dim_a"))
    text(p, (32, 325), "LDX-56RD / SW / BL / GR", 10, (107, 114, 128))
    p.insert_image(R(310, 110, 558, 302), filename=A("dim_b"))
    text(p, (310, 325), "LDX-90RD / SW / BL / GR", 10, (107, 114, 128))
    text(p, (32, 380), "オプション", 15, NAVY)
    text(p, (32, 405), "拡散板 ／ 偏光板 ／ アダプター ／ レンズ取付リング をご用意しています。", 10)
    footer(p, 5)

    # P6 ローアングル
    p = doc.new_page(width=595, height=842)
    band(p, "ローアングル照明 LDX-LA シリーズ", "直射光")
    text(p, (32, 80), "ローアングルから中心部へ直射光を照射", 17, NAVY)
    text(p, (32, 110), "大きく傾斜をつけた基板にLEDを実装し、低い位置から集光照射します。", 10.5)
    text(p, (32, 132), "凹凸のあるキズや刻印を抽出する用途に適しています。", 10.5)
    p.insert_image(R(170, 170, 430, 430), filename=A("ring_low"))
    text(p, (170, 448), "LDX-100RD-LA", 10, (107, 114, 128))
    text(p, (32, 500), "用途例", 13, NAVY)
    text(p, (32, 525), "金属表面の刻印・キズ・汚れ検査 ／ 各種エッジ抽出 ／ ガラス端面のキズ検査", 10)
    footer(p, 6)

    # P7 特注
    p = doc.new_page(width=595, height=842)
    band(p, "特注対応", "サイズ・波長・形状")
    text(p, (32, 80), "特注製作いたします", 17, NAVY)
    for i, s in enumerate(["外径・内径の変更", "波長・色温度の変更", "高出力化",
                           "ケーブル長・コネクタ形状の変更", "照射角度・形状・材質の変更"]):
        text(p, (44, 115 + i * 24), "・" + s, 11)
    p.insert_image(R(330, 110, 545, 325), filename=A("ring_white"))
    text(p, (32, 280), "ハーフカット品、多段リング照明などの製作実績もございます。", 10.5)
    footer(p, 7)

    # P8 お問い合わせ
    p = doc.new_page(width=595, height=842)
    band(p, "お問い合わせ", "")
    text(p, (32, 90), "各種資料をご用意しております", 15, NAVY)
    text(p, (32, 120), "PDF図面 ／ DXF図面 ／ 3D CAD ／ 取扱説明書 ／ 撮像サンプル ／ デジタルカタログ", 10.5)
    p.insert_image(R(32, 160, 132, 260), filename=A("qr"))
    text(p, (150, 200), "Webサイトからのお問い合わせはこちら", 11, NAVY)
    text(p, (150, 222), "https://example.invalid/contact/", 10, BLUE)
    text(p, (32, 320), "照明選定のご相談、貸出機のお申し込み、お見積りを承ります。", 10.5)
    p.insert_image(R(430, 700, 500, 770), filename=A("logo"))
    footer(p, 8)

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "demo_catalog.pdf"
    doc.save(path, deflate=True)
    doc.close()
    return path


def write_links_csv(pdf: Path, a: dict[str, str]):
    """PDF内の画像の並び順と原本ファイルを、画像サイズで突き合わせてCSVにする。

    実案件ではInDesignの「リンク」パネルから書き出した一覧がこれにあたる。
    """
    size_to_name: dict[tuple[int, int], str] = {}
    for name in a.values():
        with Image.open(ASSETS / name) as im:
            size_to_name[im.size] = name
    doc = pymupdf.open(pdf)
    rows = []
    for pno, page in enumerate(doc, start=1):
        for order, info in enumerate(page.get_images(full=True), start=1):
            w, h = info[2], info[3]
            name = size_to_name.get((w, h))
            if name:
                rows.append({"page": pno, "order": order, "filename": name})
    doc.close()
    with open(OUT / "links.csv", "w", newline="", encoding="utf-8") as f:
        wcsv = csv.DictWriter(f, fieldnames=["page", "order", "filename"])
        wcsv.writeheader()
        wcsv.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    assets = build_assets()
    pdf = make_pdf(assets)
    n = write_links_csv(pdf, assets)
    print(f"生成しました: {pdf}（原本 {len(assets)} 点 / リンク {n} 行）")
