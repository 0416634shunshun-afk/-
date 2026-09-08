#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
誌面ビューア + 素材ブラウザ を PDF から生成するビルドツール。

入力
  ・誌面PDF（InDesign等から書き出したもの。文字は「テキストのまま」書き出すと紙面検索が効く）
  ・（任意）原本フォルダ … 誌面に配置した .psd/.ai/.eps などのリンク元ファイル
  ・（任意）リンク一覧CSV … 「どのページの何番目の画像が、どの原本か」の対応表

出力（--out で指定したフォルダ）
  index.html          … ビューア本体（データを埋め込んだ完成品。単体で配布できる）
  pages/page-NN.jpg   … 誌面画像
  thumbs/mNNNN.jpg    … 一覧用サムネイル
  light/mNNNN.jpg     … 画面表示・資料貼付用の軽量JPG
  assets/…            … ダウンロードさせる原本
  ツールを開く.bat / ツールを開く.command … ローカルHTTPで開くための起動スクリプト

当たり判定（誌面のどこをクリックするとどの素材か）は、PDF内の画像の配置矩形から
ページごとに1枚のPNGを作って表現する。ピクセルの R + (G<<8) が素材IDになっている。
透明部分（アルファ）を持つ画像は、その形どおりに当たり判定を作る。

使い方の例:
  python3 tools/build_catalog.py --pdf catalog.pdf --out demo \
      --title "総合カタログ2026" --assets-dir links/ --links links.csv
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFont

VECTOR_EXTS = {"ai", "eps", "pdf", "svg", "indd"}
# 型番らしい文字列（WBT-N3030SB(W) / LPT-301N（W） / No.3302-0 など）。
# リンク一覧が無いカタログで、写真の近くにある型番を素材名に採用するために使う。
MODEL_RE = re.compile(r"^[A-Z][A-Z0-9]{1,}[-‐‑–][A-Z0-9][A-Z0-9\-]*[A-Z0-9]?(?:[（(][^）)]{1,4}[）)])?$")
NG_NAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')
# 一覧のサムネイルを画像から作れない形式（Illustrator等）は、代わりに
# 拡張子を大きく書いた「ダミーの表紙」を描く。何のファイルかは一目で分かる。
PLACEHOLDER_FONTS = [
    "/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf",
    "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

THUMB_W, THUMB_H = 240, 184          # 一覧サムネイル（表示は60x46）
LIGHT_MAX = 1600                     # 軽量JPGの長辺


def human_size(n: int) -> str:
    if n >= 1048576:
        return f"{n / 1048576:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


def find_font(size: int) -> ImageFont.FreeTypeFont:
    for f in PLACEHOLDER_FONTS:
        if Path(f).exists():
            try:
                return ImageFont.truetype(f, size)
            except OSError:
                pass
    return ImageFont.load_default()


@dataclass
class Material:
    id: int
    name: str                    # 表示名（= ダウンロード時のファイル名）
    ext: str
    src_bytes: bytes | None = None      # PDFから取り出した画像の実体
    src_path: Path | None = None        # 原本フォルダにある実ファイル
    width: int = 0
    height: int = 0
    pages: list[int] = field(default_factory=list)
    placements: list[tuple[int, pymupdf.Rect]] = field(default_factory=list)
    alpha: Image.Image | None = None     # 形どおりの当たり判定用
    preview: Image.Image | None = None   # サムネ・軽量JPGの元
    hotspot: bool = True

    @property
    def is_vector(self) -> bool:
        return self.ext.lower() in VECTOR_EXTS


def parse_pages(spec: str | None, total: int) -> list[int]:
    """"21-34" や "1,5,10-12" のような指定を、0始まりのページ番号の並びにする。"""
    if not spec:
        return list(range(total))
    out: list[int] = []
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            lo = int(a) if a else 1
            hi = int(b) if b else total
        else:
            lo = hi = int(part)
        for n in range(lo, hi + 1):
            if 1 <= n <= total and (n - 1) not in out:
                out.append(n - 1)
    if not out:
        raise SystemExit(f"--pages '{spec}' に該当するページがありません（全{total}ページ）")
    return out


class Builder:
    def __init__(self, args):
        self.args = args
        self.out = Path(args.out)
        self.doc = pymupdf.open(args.pdf)
        # 誌面の一部だけを切り出して作れるようにする（元カタログの章単位で配るケース）。
        # self.page_indices[i] = ビューアのi番目に対応する、PDF内の0始まりページ番号。
        self.page_indices = parse_pages(args.pages, len(self.doc))
        self.scale = args.dpi / 72.0
        self.materials: list[Material] = []
        self.by_key: dict[str, Material] = {}
        self.links = self._load_links(args.links)
        self.assets_dir = Path(args.assets_dir) if args.assets_dir else None
        self.used_assets: set[Path] = set()

    # ---------- 入力 ----------
    @staticmethod
    def _load_links(path: str | None) -> dict[tuple[int, int], str]:
        """リンク一覧CSV（page,order,filename）を読む。1始まりで指定する。"""
        if not path:
            return {}
        out: dict[tuple[int, int], str] = {}
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                key = (int(row["page"]), int(row["order"]))
                out[key] = row["filename"].strip()
        return out

    def _asset_file(self, name: str) -> Path | None:
        if not self.assets_dir or not name:
            return None
        p = self.assets_dir / name
        if p.exists():
            return p
        hits = list(self.assets_dir.rglob(name))
        return hits[0] if hits else None

    # ---------- 素材の収集 ----------
    def collect(self):
        for pos, src_pno in enumerate(self.page_indices):
            page = self.doc[src_pno]
            for order, info in enumerate(page.get_images(full=True), start=1):
                xref, smask = info[0], info[1]
                rects = page.get_image_rects(xref)
                if not rects:
                    continue
                m = self._material_for(xref, smask, src_pno, order, rects[0])
                if m is None:
                    continue
                if pos not in m.pages:
                    m.pages.append(pos)
                for r in rects:
                    m.placements.append((pos, r))

        if self.assets_dir and self.args.include_unplaced:
            self._collect_unplaced_assets()

    def _material_for(self, xref: int, smask: int, pno: int, order: int,
                      rect_hint: pymupdf.Rect | None = None) -> Material | None:
        try:
            info = self.doc.extract_image(xref)
        except Exception as e:                                  # 壊れた画像は飛ばす
            print(f"  ! p{pno + 1} の画像(xref={xref})を取り出せません: {e}", file=sys.stderr)
            return None
        data, ext = info["image"], info["ext"]
        key = hashlib.md5(data).hexdigest()                     # 同じ画像は1素材にまとめる
        if key in self.by_key:
            return self.by_key[key]

        linked = self.links.get((pno + 1, order))
        asset_path = self._asset_file(linked) if linked else None
        if asset_path:
            self.used_assets.add(asset_path)
            name, real_ext = asset_path.name, asset_path.suffix.lstrip(".").lower()
        else:
            # リンク一覧が無い場合の自動命名。誌面のページ番号で振っておくと、
            # 「p.12の3番目の写真」と口頭でも指し示せる。さらに、写真の近くに
            # 型番などの文字があれば名前に含め、型番でも検索できるようにする。
            stem = f"p{pno + 1 + self.args.page_offset:02d}_{order:02d}"
            if not linked and not self.args.no_name_hints:
                hint = self._label_near(self.doc[pno], rect_hint) if rect_hint else None
                if hint:
                    stem = f"{stem}_{hint}"
            name = linked or f"{stem}.{ext}"
            real_ext = Path(name).suffix.lstrip(".").lower() or ext

        m = Material(id=len(self.materials) + 1, name=name, ext=real_ext,
                     src_bytes=data, src_path=asset_path,
                     width=info["width"], height=info["height"])
        m.preview = self._safe_open(io.BytesIO(data))
        m.alpha = self._alpha_of(xref, smask)
        # 原本が別ファイルなら、寸法もその原本のものを表示する（誌面用に縮小した
        # PDF内の画像ではなく、手元に落ちてくるファイルの実寸を知りたいため）。
        if asset_path:
            im = self._safe_open(asset_path)
            if im is not None:
                m.width, m.height = im.size
                m.preview = im
            elif m.is_vector:
                m.width = m.height = 0
        self.by_key[key] = m
        self.materials.append(m)
        return m

    def _label_near(self, page, rect) -> str | None:
        """画像のすぐ下（無ければ内側・すぐ上）にある文字から、素材名の手がかりを拾う。

        カタログ紙面では写真の直下に型番が置かれることが多い。リンク一覧が
        無い場合でも「p12_03_WBT-N3030SB」のような名前になり、型番で検索できる。
        """
        cands: list[tuple[float, bool, str]] = []
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    t = span["text"].strip()
                    if not t or len(t) > 30:
                        continue
                    x0, y0, x1, y1 = span["bbox"]
                    # 横方向に重なっている文字だけを候補にする
                    if min(x1, rect.x1) - max(x0, rect.x0) < (rect.width * 0.25):
                        continue
                    if y0 >= rect.y1:                      # 画像の下
                        dist = y0 - rect.y1
                    elif y1 <= rect.y0:                    # 画像の上
                        dist = (rect.y0 - y1) * 1.6        # 下より優先度を落とす
                    else:                                  # 画像に重なっている
                        dist = 0.0
                    if dist > 60:
                        continue
                    cands.append((dist, bool(MODEL_RE.match(t)), t))
        if not cands:
            return None
        # 型番らしいものを最優先。次に近いもの。
        cands.sort(key=lambda c: (not c[1], c[0]))
        best = cands[0][2]
        best = NG_NAME_CHARS.sub("", best).replace(" ", "_").strip("._")
        return best[:28] or None

    @staticmethod
    def _safe_open(src) -> Image.Image | None:
        try:
            im = Image.open(src)
            im.load()
            return im
        except Exception:
            return None

    def _alpha_of(self, xref: int, smask: int) -> Image.Image | None:
        """透明情報（ソフトマスク）があれば、当たり判定を画像の形どおりにする。"""
        if not smask:
            return None
        try:
            pm = pymupdf.Pixmap(self.doc, smask)
            im = Image.frombytes("L" if pm.n == 1 else "RGB", (pm.width, pm.height), pm.samples)
            return im.convert("L")
        except Exception:
            return None

    def _collect_unplaced_assets(self):
        """原本フォルダにあるが誌面に配置されていないファイルも一覧に載せる。"""
        for p in sorted(self.assets_dir.rglob("*")):
            if not p.is_file() or p in self.used_assets or p.name.startswith("."):
                continue
            im = self._safe_open(p)
            m = Material(id=len(self.materials) + 1, name=p.name,
                         ext=p.suffix.lstrip(".").lower(), src_path=p,
                         width=im.size[0] if im else 0, height=im.size[1] if im else 0,
                         preview=im, hotspot=False)
            self.materials.append(m)

    # ---------- 出力 ----------
    def render_pages(self) -> list[dict]:
        pages_dir = self.out / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        pages: list[dict] = []
        n_total = len(self.page_indices)
        for pos, src_pno in enumerate(self.page_indices):
            page = self.doc[src_pno]
            pm = page.get_pixmap(matrix=pymupdf.Matrix(self.scale, self.scale), alpha=False)
            img = Image.frombytes("RGB", (pm.width, pm.height), pm.samples)
            rel = f"pages/page-{src_pno + 1:03d}.jpg"
            img.save(self.out / rel, "JPEG", quality=self.args.jpeg_quality, optimize=True)
            pages.append({
                # ラベルは元PDFのページ番号。抜粋して作っても、誌面の実ページと
                # 突き合わせられるようにするため。
                "label": self.args.page_label.format(n=src_pno + 1 + self.args.page_offset),
                "src": rel,
                "map": self._hitmap_uri(pos, pm.width, pm.height),
                "mapW": pm.width, "mapH": pm.height,
                "text": self._page_text(page),
            })
            print(f"  ページ {pos + 1}/{n_total}（元PDF p.{src_pno + 1}）書き出し ({pm.width}x{pm.height})")
        return pages

    def _hitmap_uri(self, pos: int, w: int, h: int) -> str:
        """R+(G<<8)=素材ID の当たり判定マップを作り、data URIとして返す。"""
        buf = np.zeros((h, w, 3), dtype=np.uint8)
        # 大きい配置から先に塗り、小さい配置を上に重ねる（小さいものが埋もれないように）
        items = [(m, r) for m in self.materials for (p, r) in m.placements if p == pos]
        items.sort(key=lambda t: abs(t[1].get_area()), reverse=True)
        for m, rect in items:
            x0 = max(0, int(rect.x0 * self.scale))
            y0 = max(0, int(rect.y0 * self.scale))
            x1 = min(w, int(round(rect.x1 * self.scale)))
            y1 = min(h, int(round(rect.y1 * self.scale)))
            if x1 <= x0 or y1 <= y0:
                continue
            r_val, g_val = m.id & 0xFF, (m.id >> 8) & 0xFF
            if m.alpha is not None:
                a = np.asarray(m.alpha.resize((x1 - x0, y1 - y0), Image.NEAREST))
                mask = a > 16
                buf[y0:y1, x0:x1, 0] = np.where(mask, r_val, buf[y0:y1, x0:x1, 0])
                buf[y0:y1, x0:x1, 1] = np.where(mask, g_val, buf[y0:y1, x0:x1, 1])
            else:
                buf[y0:y1, x0:x1, 0] = r_val
                buf[y0:y1, x0:x1, 1] = g_val
        bio = io.BytesIO()
        Image.fromarray(buf).save(bio, "PNG", optimize=True)
        import base64
        return "data:image/png;base64," + base64.b64encode(bio.getvalue()).decode("ascii")

    def _page_text(self, page) -> list[dict]:
        """紙面に印刷されている文字と、その位置（当たり判定マップと同じ座標系）。"""
        out = []
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    t = span["text"].strip()
                    if not t:
                        continue
                    b = span["bbox"]
                    out.append({"t": t, "b": [round(b[0] * self.scale), round(b[1] * self.scale),
                                              round(b[2] * self.scale), round(b[3] * self.scale)]})
        return out

    def write_materials(self) -> list[dict]:
        for d in ("thumbs", "light", "assets"):
            (self.out / d).mkdir(parents=True, exist_ok=True)
        rows = []
        for m in self.materials:
            asset_rel = self._write_asset(m)
            thumb_rel = self._write_thumb(m)
            light_rel = self._write_light(m)
            size_bytes = (self.out / asset_rel).stat().st_size
            rows.append({
                "id": m.id,
                "name": m.name,
                "ext": m.ext,
                "dim": f"{m.width} × {m.height}" if m.width and m.height else "-",
                "size": human_size(size_bytes),
                "bytes": size_bytes,
                "is_vector": m.is_vector,
                "hotspot": m.hotspot,
                "thumb": thumb_rel,
                "light": light_rel,
                "asset": asset_rel,
                "pages": sorted(m.pages),
            })
        return rows

    def _write_asset(self, m: Material) -> str:
        # ファイル名の重複や日本語・記号による事故を避けるため、実体は連番で置き、
        # ダウンロード時のファイル名だけ元の名前に戻す（ビューア側のdownload属性）。
        rel = f"assets/m{m.id:04d}_{m.name}"
        dst = self.out / rel
        if m.src_path and m.src_path.exists():
            shutil.copy2(m.src_path, dst)
        else:
            dst.write_bytes(m.src_bytes or b"")
        return rel

    def _write_thumb(self, m: Material) -> str:
        rel = f"thumbs/m{m.id:04d}.jpg"
        im = m.preview
        if im is None:
            im = self._placeholder(m)
        else:
            im = self._flatten(im).copy()
            im.thumbnail((THUMB_W, THUMB_H), Image.LANCZOS)
            canvas = Image.new("RGB", (THUMB_W, THUMB_H), (240, 242, 247))
            canvas.paste(im, ((THUMB_W - im.width) // 2, (THUMB_H - im.height) // 2))
            im = canvas
        im.save(self.out / rel, "JPEG", quality=78, optimize=True)
        return rel

    def _write_light(self, m: Material) -> str:
        rel = f"light/m{m.id:04d}.jpg"
        im = m.preview
        im = self._placeholder(m) if im is None else self._flatten(im).copy()
        if max(im.size) > LIGHT_MAX:
            im.thumbnail((LIGHT_MAX, LIGHT_MAX), Image.LANCZOS)
        im.save(self.out / rel, "JPEG", quality=85, optimize=True)
        return rel

    @staticmethod
    def _flatten(im: Image.Image) -> Image.Image:
        """透明・CMYK・16bitなど、そのままではJPEGにできない画像を白背景のRGBにする。"""
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            return bg
        return im.convert("RGB") if im.mode != "RGB" else im

    def _placeholder(self, m: Material) -> Image.Image:
        im = Image.new("RGB", (THUMB_W, THUMB_H), (250, 246, 238))
        d = ImageDraw.Draw(im)
        d.rectangle([2, 2, THUMB_W - 3, THUMB_H - 3], outline=(240, 217, 181), width=2)
        label = m.ext.upper() or "FILE"
        f = find_font(52)
        w = d.textlength(label, font=f)
        d.text(((THUMB_W - w) / 2, THUMB_H / 2 - 42), label, font=f, fill=(168, 91, 0))
        f2 = find_font(15)
        name = m.name if len(m.name) <= 22 else m.name[:20] + "…"
        w2 = d.textlength(name, font=f2)
        d.text(((THUMB_W - w2) / 2, THUMB_H / 2 + 26), name, font=f2, fill=(120, 110, 95))
        return im

    def spreads(self) -> list[dict]:
        idx = list(range(len(self.page_indices)))
        out = []
        if self.args.cover:               # 表紙を単独ページとして扱う
            out.append({"l": None, "r": 0})
            idx = idx[1:]
        for i in range(0, len(idx), 2):
            pair = idx[i:i + 2]
            out.append({"l": pair[0], "r": pair[1] if len(pair) > 1 else None})
        return out

    def write_index(self, data: dict):
        tpl = Path(self.args.template).read_text(encoding="utf-8")
        page_ratio = self.doc[0].rect
        aspect = f"{page_ratio.width:.0f} / {page_ratio.height:.0f}"
        html = (tpl.replace("__CATALOG_DATA__",
                            json.dumps(data, ensure_ascii=False, separators=(",", ":")))
                   .replace("__TITLE__", data["title"])
                   .replace("__ASPECT__", aspect))
        (self.out / "index.html").write_text(html, encoding="utf-8")

    def write_launchers(self):
        bat = (
            "@echo off\r\n"
            "rem このツールをローカルのWebサーバー経由で開きます。\r\n"
            "rem （index.htmlを直接ダブルクリックすると、ブラウザの安全上の制限で\r\n"
            "rem   画像の保存やZIPまとめDLができないため）\r\n"
            "cd /d \"%~dp0\"\r\n"
            "set PORT=8765\r\n"
            "where python >nul 2>&1 && (\r\n"
            "  start \"\" http://localhost:%PORT%/\r\n"
            "  python -m http.server %PORT%\r\n"
            ") || (\r\n"
            "  where py >nul 2>&1 && (\r\n"
            "    start \"\" http://localhost:%PORT%/\r\n"
            "    py -m http.server %PORT%\r\n"
            "  ) || (\r\n"
            "    echo Python が見つかりません。\r\n"
            "    echo https://www.python.org/downloads/ からインストールするか、\r\n"
            "    echo 社内のWebサーバーに丸ごとアップロードしてご利用ください。\r\n"
            "    pause\r\n"
            "  )\r\n"
            ")\r\n"
        )
        (self.out / "ツールを開く.bat").write_text(bat, encoding="cp932", errors="replace")
        cmd = (
            "#!/bin/sh\n"
            "# macOS / Linux 用。ダブルクリック（または sh ./ツールを開く.command）で起動。\n"
            "cd \"$(dirname \"$0\")\" || exit 1\n"
            "PORT=8765\n"
            "(sleep 1; (open \"http://localhost:$PORT/\" 2>/dev/null || xdg-open \"http://localhost:$PORT/\" 2>/dev/null)) &\n"
            "python3 -m http.server $PORT\n"
        )
        f = self.out / "ツールを開く.command"
        f.write_text(cmd, encoding="utf-8")
        f.chmod(0o755)

    def run(self):
        self.out.mkdir(parents=True, exist_ok=True)
        sel = len(self.page_indices)
        rng = "" if sel == len(self.doc) else f" → {sel}ページを抜粋（元PDF p.{self.page_indices[0] + 1}〜p.{self.page_indices[-1] + 1}）"
        print(f"PDF: {self.args.pdf}（全{len(self.doc)}ページ）{rng}")
        self.collect()
        print(f"素材 {len(self.materials)} 点を検出")
        pages = self.render_pages()
        materials = self.write_materials()
        data = {
            "title": self.args.title,
            "pages": pages,
            "spreads": self.spreads(),
            "materials": materials,
        }
        self.write_index(data)
        self.write_launchers()
        total = sum(m["bytes"] for m in materials)
        print(f"完了: {self.out}/index.html")
        print(f"  ページ {len(pages)} / 素材 {len(materials)} 点 / 原本合計 {human_size(total)}")


def main():
    ap = argparse.ArgumentParser(description="誌面PDFから、めくれるビューア＋素材ブラウザを生成します。")
    ap.add_argument("--pdf", required=True, help="誌面PDF")
    ap.add_argument("--out", required=True, help="出力フォルダ")
    ap.add_argument("--title", default="誌面ビューア", help="ページ上部に出すタイトル")
    ap.add_argument("--assets-dir", help="原本（.psd/.ai等）が入ったフォルダ")
    ap.add_argument("--links", help="リンク一覧CSV（列: page,order,filename／1始まり）")
    ap.add_argument("--dpi", type=int, default=150, help="誌面画像の解像度（既定150）")
    ap.add_argument("--jpeg-quality", type=int, default=82, help="誌面画像のJPEG品質（既定82）")
    ap.add_argument("--pages", help="作る範囲。例 '21-34' や '1,5,10-12'（元PDFのページ番号・1始まり）")
    ap.add_argument("--cover", action="store_true", help="先頭ページを表紙（単独ページ）として扱う")
    ap.add_argument("--page-label", default="P.{n}", help="ページ表示名の書式。{n}は元PDFのページ番号（既定 'P.{n}'）")
    ap.add_argument("--page-offset", type=int, default=0,
                    help="ページ表示名の番号のズレ補正。誌面のノンブルとPDFのページ番号が違うときに指定")
    ap.add_argument("--no-name-hints", action="store_true",
                    help="リンク一覧が無いとき、誌面の近くの文字（型番など）を素材名に使わない")
    ap.add_argument("--include-unplaced", action="store_true",
                    help="原本フォルダにあるが誌面に配置されていないファイルも一覧に載せる")
    ap.add_argument("--template", default=str(Path(__file__).with_name("viewer_template.html")),
                    help="ビューアのテンプレートHTML")
    args = ap.parse_args()
    Builder(args).run()


if __name__ == "__main__":
    main()
