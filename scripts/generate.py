#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pegasus Theme Gallery - 截图抓取 & README 生成脚本

流程:
  1. 读取 data/repos.txt (来自 mmatyas/pegasus-theme-gallery-db)
  2. 对每个主题仓库探测截图:
       a. 官方约定 .meta/screenshots/screenN.png
       b. README 中引用的图片 (自动剔除 badge)
       c. 常见文件名兜底 (screenshot.png / preview.jpg ...)
  3. 下载截图到 assets/ (可选压缩, 需要 Pillow)
  4. 生成 data/themes.json 与 根目录 README.md (图片网格)

用法:
  python scripts/generate.py            # 增量 (复用 themes.json)
  python scripts/generate.py --force    # 全量重抓
  python scripts/generate.py --no-download  # 只外链, 不落盘图片
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ASSETS = ROOT / "assets"
REPOS_TXT = DATA / "repos.txt"
THEMES_JSON = DATA / "themes.json"
README = ROOT / "README.md"

UA = "Mozilla/5.0 (compatible; pegasus-theme-gallery-bot)"
RAW = "https://raw.githubusercontent.com/{repo}/{ref}/{path}"

# 明显不是截图的图片 (徽章 / 图标 / 捐赠按钮)
BADGE_PAT = re.compile(
    r"shields\.io|badge|travis|circleci|appveyor|codecov|codeclimate|coveralls"
    r"|github\.com/.*/actions/workflows|buy.?me.?a.?coffee|paypal|ko-fi|kofi"
    r"|patreon|discord|twitter|telegram|reddit|license|stars|forks|issues"
    r"|last-commit|repo-size|code-size|contributors|made-with|built-with"
    r"|forthebadge|img\.shields|badgen\.net|static\.badgen"
    r"|creativecommons|88x31|licence|opensource|osi-?approved",
    re.I,
)
# 不适合当主题名的 README 标题
BAD_TITLE = re.compile(
    r"(?i)(screenshot|install|how to|readme|licen[cs]e|music player|sounds? and"
    r"|table of contents|changelog|todo|credits?|thanks|welcome|overview|features?$|demo)"
)
IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")

# 兜底探测路径 (相对仓库根目录)
CANDIDATES = [
    ".meta/screenshots/screen0.png",
    ".meta/screenshots/screen1.png",
    ".meta/screenshots/screen0.jpg",
    ".meta/screenshot.png",
    "screenshot.png",
    "screenshot.jpg",
    "screenshot.jpeg",
    "screenshot.webp",
    "screen.png",
    "screen.jpg",
    "preview.png",
    "preview.jpg",
    "preview.jpeg",
    "cover.png",
    "cover.jpg",
    "thumbnail.png",
    "demo.png",
    "demo.jpg",
    "assets/screenshot.png",
    "assets/preview.png",
    "images/screenshot.png",
    "images/preview.png",
    ".github/screenshot.png",
    ".github/preview.png",
    "docs/screenshot.png",
    "screenshot1.png",
    "screenshot_1.png",
]

MAX_SHOTS = 3          # 每个主题最多保留几张截图
MAX_WORKERS = 6
MAX_IMAGE_BYTES = 12 * 1024 * 1024
THUMB_WIDTH = 640      # 压缩后的最大宽度

# 展示用缩略图 CDN (避免直接拉原图: 实测平均 573KB/张, 全量约 35MB)
THUMB_CDN = "https://images.weserv.nl/?url={url}&w=400&output=jpg&q=80"
THUMB_ON = True        # --no-thumb 时关闭, 直接引用原图
VERIFY_DAYS = 7        # 外链校验周期(天)
DEAD_RETRY_DAYS = 30   # 标记为 dead 的仓库多久后重试一次
PAGES_URL = "https://wmhx.github.io/pegasus-theme-gallery/"


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
socket.setdefaulttimeout(20)        # 兜底: 防止个别请求把整个流程拖死


def http_get(url: str, timeout: int = 20, retries: int = 2, head: bool = False):
    """返回 (status_code, bytes, headers) ; 失败返回 (0, b'', {})"""
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            req.get_method = lambda: "HEAD" if head else "GET"  # type: ignore
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                time.sleep(2 + i * 2)
                continue
            return e.code, b"", {}
        except Exception:
            time.sleep(1 + i)
    return 0, b"", {}


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------
def parse_repos(text: str) -> list[str]:
    out, seen = [], set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"https?://github\.com/([^/\s]+)/([^/\s]+)", line)
        if not m:
            continue
        owner, name = m.group(1), m.group(2).removesuffix(".git")
        slug = f"{owner}/{name}"
        if slug.lower() not in seen:
            seen.add(slug.lower())
            out.append(slug)
    return out


def normalize_url(url: str, slug: str) -> str | None:
    """把 README 里的图片地址统一成可直接访问的绝对地址"""
    url = url.strip().strip("<>").strip()
    if not url or url.startswith("data:"):
        return None
    url = url.split(" ")[0]
    # 去掉 markdown 的 title 部分: ](img.png "title")
    url = re.split(r'\s+"', url)[0]

    if url.startswith("//"):
        url = "https:" + url

    # github blob / raw 页面地址 -> raw.githubusercontent
    m = re.match(r"https?://(?:www\.)?github\.com/([^/]+)/([^/]+)/(blob|raw)/([^/]+)/(.+)$", url)
    if m:
        url = RAW.format(repo=f"{m.group(1)}/{m.group(2)}", ref=m.group(4), path=m.group(5))
    elif "/assets/" in url and re.match(r"https?://(?:www\.)?github\.com/", url):
        # user 上传的 assets 链接, 可直接取图
        pass
    elif re.match(r"https?://(?:www\.)?github\.com/", url):
        return None

    if url.startswith("http"):
        # 去掉查询串里无用的参数, 保留 token 类
        base, _, query = url.partition("?")
        if query and not re.search(r"(token|sig|X-Amz)", query, re.I):
            url = base
        return url

    # 相对路径 (注意: 只去掉开头的 ./ 或 /, 不能吃掉 .meta 这种隐藏目录的点)
    if url.startswith("./"):
        url = url[2:]
    elif url.startswith("/"):
        url = url[1:]
    return RAW.format(repo=slug, ref="HEAD", path=urllib.parse.quote(url, safe="/%:@"))


def is_image_url(url: str) -> bool:
    low = url.lower().split("?")[0]
    if BADGE_PAT.search(url):
        return False
    if "user-images.githubusercontent.com" in low or "user-attachments" in low:
        return True
    # github 用户上传的 /assets/<uuid> 形式 (无扩展名)
    if re.search(r"github\.com/[^/]+/[^/]+/assets/", low):
        return True
    return low.endswith(IMG_EXT)


MD_IMG = re.compile(r"!\[([^\]]*)\]\(\s*([^)\s]+)")
HTML_IMG = re.compile(r"<img[^>]+src\s*=\s*[\"']([^\"']+)[\"']", re.I)


def extract_images(md: str) -> list[str]:
    found = []
    for alt, url in MD_IMG.findall(md):
        if BADGE_PAT.search(alt) or BADGE_PAT.search(url):
            continue
        found.append(url)
    if not found:
        for url in HTML_IMG.findall(md):
            found.append(url)
    return found


STRICT_ALIVE = False   # --strict-alive (CI 用): 只有 200 才算存活


def url_alive(u: str) -> bool:
    """链接是否可用。本地网络错误(status 0)默认算存活; 严格模式下只有 200 算"""
    st, _, _ = http_get(u, timeout=15, retries=1, head=True)
    if st == 200:
        return True
    return (not STRICT_ALIVE) and st == 0


def probe_parallel(urls: list[str], workers: int = 8) -> list[tuple[str, int]]:
    """并行 HEAD 探测, 返回 [(url, status), ...] (保持输入顺序)"""
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=min(workers, len(urls))) as ex:
        statuses = list(ex.map(lambda u: http_get(u, timeout=15, retries=1, head=True)[0], urls))
    return list(zip(urls, statuses))


def alive_parallel(urls: list[str]) -> list[str]:
    """过滤出可用的外链"""
    return [u for u, st in probe_parallel(urls) if st == 200 or ((not STRICT_ALIVE) and st == 0)]


def thumb(u: str) -> str:
    """展示用的缩略图地址 (关闭时返回原图)"""
    if not THUMB_ON or not u.startswith("http"):
        return u
    return THUMB_CDN.format(url=urllib.parse.quote(u, safe=""))


def days_since(date_str: str | None) -> int:
    """距给定日期过去了多少天; 无日期视为很久以前"""
    if not date_str:
        return 10 ** 6
    try:
        return (time.time() - time.mktime(time.strptime(date_str, "%Y-%m-%d"))) // 86400
    except Exception:
        return 10 ** 6


def prettify(name: str) -> str:
    n = re.sub(r"^pegasus-theme-", "", name, flags=re.I)
    n = n.replace("-", " ").replace("_", " ").strip()
    return n if n else name


def pick_name(h1: str, repo: str) -> str:
    """README 标题可用就用, 否则退回仓库名"""
    h1 = (h1 or "").strip()
    if not h1 or len(h1) > 45 or h1.endswith(":") or BAD_TITLE.search(h1):
        return prettify(repo)
    return h1


def save_image(data: bytes, dest: Path) -> bool:
    """保存图片 (有 Pillow 时压缩到 THUMB_WIDTH); 尺寸过小视为图标, 返回 False"""
    try:
        from PIL import Image  # type: ignore
    except Exception:
        dest.write_bytes(data)
        return True
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
        if im.width < 300:          # logo / 图标, 不是截图
            return False
        if im.width > THUMB_WIDTH:
            h = round(im.height * THUMB_WIDTH / im.width)
            im = im.resize((THUMB_WIDTH, h), Image.LANCZOS)
        if im.mode in ("RGBA", "LA", "P") and "transparency" in im.info:
            im = im.convert("RGBA")
            bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
            im = Image.alpha_composite(bg, im).convert("RGB")
        elif im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        im.save(dest, "JPEG", quality=82, optimize=True)
        return True
    except Exception as e:
        print(f"    ! 压缩失败 {dest.name}: {e}", file=sys.stderr)
        try:
            dest.write_bytes(data)
            return True
        except Exception:
            return False


# --------------------------------------------------------------------------
# 单个仓库
# --------------------------------------------------------------------------
def find_shots(slug: str) -> tuple[list[str], str]:
    """返回 (图片绝对地址列表, 主题名)"""
    urls: list[str] = []
    title = ""

    # 1) README 里引用的图片 (覆盖绝大多数主题); 引用失效则继续往下找
    for fname in ("README.md", "readme.md", "README.MD", "docs/README.md", "README.rst"):
        st, body, _ = http_get(RAW.format(repo=slug, ref="HEAD", path=fname), timeout=25, retries=3)
        if st != 200:
            continue
        md = body.decode("utf-8", "ignore")
        m = re.search(r"^#\s+(.+)$", md, re.M)
        if m:
            title = m.group(1).strip()
        for raw in extract_images(md):
            u = normalize_url(raw, slug)
            if u and is_image_url(u) and u not in urls:
                urls.append(u)
            if len(urls) >= MAX_SHOTS:
                break
        urls = alive_parallel(urls)
        break

    # 2) 官方 .meta/screenshots 约定
    if not urls:
        probes = [RAW.format(repo=slug, ref="HEAD", path=f".meta/screenshots/screen{i}.png")
                  for i in range(MAX_SHOTS)]
        urls.extend(u for u, st in probe_parallel(probes) if st == 200)

    # 3) 常见文件名兜底 (并行探测, 按顺序取第一个命中的)
    if not urls:
        probes = [RAW.format(repo=slug, ref="HEAD", path=p) for p in CANDIDATES]
        hits = {u: st for u, st in probe_parallel(probes)}
        for u in probes:
            if hits.get(u) == 200 and is_image_url(u):
                urls.append(u)
                break

    return urls[:MAX_SHOTS], title


def process(slug: str, download: bool = False) -> dict:
    owner, name = slug.split("/")
    shots, title = find_shots(slug)

    today = time.strftime("%Y-%m-%d", time.gmtime())
    entry = {
        "slug": slug,
        "owner": owner,
        "repo": name,
        "name": pick_name(title, name),
        "url": f"https://github.com/{slug}",
        "screenshots": [],   # 本地 assets 路径 (仅 --download 时才有)
        "remote": [],        # 外链地址 (默认模式)
        "verified_at": today,
        "dead": False,
        "dead_since": None,
    }

    if not download:
        # 默认模式: 直接用外链, 不落盘图片 (find_shots 已校验过链接可用性)
        entry["remote"] = list(shots)
        entry["cover"] = (entry["remote"] or [None])[0]
        if not entry["cover"]:
            entry["dead"] = True
            entry["dead_since"] = today
        print(f"  [{slug}] cover={entry['cover']}")
        return entry

    n_saved = 0
    for u in shots:
        rel = None
        if download:
            st, data, _ = http_get(u, timeout=60, retries=3)
            is_bin = data[:4] != b"%PDF" and not data.lstrip()[:15].lower().startswith(b"<!doctype")
            if st == 200 and 1024 < len(data) < MAX_IMAGE_BYTES and is_bin:
                rel = f"assets/{owner}--{name}{'' if n_saved == 0 else f'_{n_saved}'}.jpg"
                if save_image(data, ROOT / rel):
                    entry["screenshots"].append(rel)
                    n_saved += 1
                else:
                    rel = None      # 图标类小图, 直接丢弃
        if rel is None and url_alive(u):
            # 下载失败(多为本地网络/限流)时退回外链, 链接本身确认可用
            entry["remote"].append(u)

    entry["cover"] = (entry["screenshots"] or entry["remote"] or [None])[0]
    print(f"  [{slug}] cover={entry['cover']}")
    return entry


# --------------------------------------------------------------------------
# README 生成
# --------------------------------------------------------------------------
def build_readme(themes: list[dict], missing: list[str]) -> str:
    ok = [t for t in themes if t.get("cover")]
    cols = 3
    now = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

    L = []
    L.append("# Pegasus Frontend 主题截图画廊")
    L.append("")
    L.append(
        "把 [pegasus-theme-gallery-db](https://github.com/mmatyas/pegasus-theme-gallery-db) 里 "
        f"**全部 {len(themes)} 个 Pegasus 前端主题**的截图直接铺在 README 里，打开即可预览，不用一个个点进仓库。"
    )
    L.append("")
    L.append(f"- 主题总数：**{len(themes)}**（成功取到截图 **{len(ok)}**）")
    L.append("- 图片来源：各主题仓库的 `.meta/screenshots/`、`README.md` 引用图或常见预览图"
             "（**外链直引，本仓库不存图片**）")
    L.append(f"- 在线画廊：{PAGES_URL}（可搜索、可放大，比 README 好翻）")
    L.append(f"- 最近更新：{now}")
    L.append("")
    L.append("> 截图版权归各主题作者所有，这里仅作预览展示。点击图片可跳转到原仓库。")
    if THUMB_ON:
        L.append("> 网格里是 400px 缩略图（约 4 MB 全量），原图链接见每个主题的仓库。")
    L.append("")

    # 目录
    L.append("## 目录")
    L.append("")
    lines = []
    for t in sorted(ok, key=lambda x: x["name"].lower()):
        lines.append(f"[{t['name']}]({t['url']}) · @{t['owner']}")
    L.append("<p>")
    L.append(" · ".join(lines))
    L.append("</p>")
    L.append("")

    # 图片网格
    L.append("## 截图预览")
    L.append("")
    L.append("<table>")
    for i in range(0, len(ok), cols):
        row = ok[i:i + cols]
        L.append("  <tr>")
        for t in row:
            src = thumb(t["cover"])
            L.append('    <td align="center" valign="top" width="%d%%">' % (100 // cols))
            L.append(f'      <a href="{t["url"]}"><img src="{src}" alt="{t["name"]}" width="300"></a>')
            L.append("      <br><br>")
            L.append(f'      <b><a href="{t["url"]}">{t["name"]}</a></b><br>')
            L.append(f'      <sub>@{t["owner"]}</sub>')
            L.append("    </td>")
        for _ in range(cols - len(row)):
            L.append('    <td width="%d%%"></td>' % (100 // cols))
        L.append("  </tr>")
    L.append("</table>")
    L.append("")

    # 多截图主题
    extra = [t for t in ok if len(t["screenshots"]) + len(t["remote"]) > 1]
    if extra:
        L.append("## 更多截图")
        L.append("")
        for t in extra:
            imgs = t["screenshots"] + t["remote"]
            L.append(f'<details><summary><b>{t["name"]}</b> (@{t["owner"]}) — {len(imgs)} 张</summary>')
            L.append("")
            L.append("<p>")
            for s in imgs:
                L.append(f'  <img src="{thumb(s)}" width="420" alt="{t["name"]}">')
            L.append("</p>")
            L.append("")
            L.append("</details>")
            L.append("")

    if missing:
        L.append("## 暂未取到截图")
        L.append("")
        L.append("以下主题没有可用截图（已标记为失效的仓库每 30 天复查一次）：")
        L.append("")
        for t in missing:
            tag = " — 上游仓库不可访问" if t.get("dead") else ""
            L.append(f"- [{t['slug']}](https://github.com/{t['slug']}){tag}")
        L.append("")

    L.append("## 重新生成")
    L.append("")
    L.append("```bash")
    L.append("python scripts/generate.py            # 增量更新（默认外链，不落盘图片）")
    L.append("python scripts/generate.py --force    # 全量重抓")
    L.append("python scripts/generate.py --download # 可选：把截图下载压缩到 assets/ 本地保存")
    L.append("python scripts/preview.py             # 生成 docs/index.html 网页版画廊")
    L.append("```")
    L.append("")
    L.append("> 默认只保存图片的外链地址（仓库里没有图片文件），仓库很小；")
    L.append("> 但上游仓库改名/删文件时外链会失效，想要长期存档就加 `--download`。")
    L.append("")
    L.append("主题列表同步自 `data/repos.txt`（上游：mmatyas/pegasus-theme-gallery-db）。")
    L.append("")
    return "\n".join(L)


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="忽略缓存，全部重抓")
    ap.add_argument("--download", action="store_true",
                    help="可选: 把截图下载压缩到 assets/ (默认只用外链, 不落盘)")
    ap.add_argument("--no-download", action="store_true", help="已废弃, 现在默认就是外链模式")
    ap.add_argument("--readme-only", action="store_true", help="只按 themes.json 重新生成 README")
    ap.add_argument("--no-prune", action="store_true", help="保留 assets 里已不再引用的旧图")
    ap.add_argument("--verify", action="store_true", help="校验已有外链是否还活着, 失效的重新抓")
    ap.add_argument("--strict-alive", action="store_true", help="CI 用: 非 200 一律视为失效")
    ap.add_argument("--no-thumb", action="store_true", help="不使用缩略图 CDN, 直接引用原图")
    args = ap.parse_args()

    global STRICT_ALIVE, THUMB_ON
    STRICT_ALIVE = args.strict_alive
    THUMB_ON = not args.no_thumb

    ASSETS.mkdir(exist_ok=True)
    repos = parse_repos(REPOS_TXT.read_text(encoding="utf-8"))
    print(f"共 {len(repos)} 个主题仓库")

    cache = {}
    if THEMES_JSON.exists() and not args.force:
        try:
            cache = {t["slug"]: t for t in json.loads(THEMES_JSON.read_text(encoding="utf-8"))}
        except Exception:
            cache = {}

    def done(r: str) -> bool:
        t = cache.get(r)
        if not t:
            return False
        if not t.get("cover"):
            # 已确认失效的仓库: 30 天内不再重试, 省掉无效探测
            return bool(t.get("dead")) and days_since(t.get("dead_since")) < DEAD_RETRY_DAYS
        if args.verify and days_since(t.get("verified_at")) >= VERIFY_DAYS:
            return False                # 到期的外链要重新校验
        # 有截图但没落到本地的, 再试一次
        return not (args.download and not t.get("screenshots"))

    def needs_verify(t: dict) -> bool:
        return bool(t.get("cover")) and days_since(t.get("verified_at")) >= VERIFY_DAYS

    todo = [] if args.readme_only else [r for r in repos if args.force or not done(r)]
    print(f"需抓取 {len(todo)} 个，复用缓存 {len(repos) - len(todo)} 个")

    # --verify: 先批量 HEAD 校验已有外链, 只重抓失效的那些
    if args.verify and not args.force:
        stale = [cache[r] for r in repos if r in cache and needs_verify(cache[r])]
        if stale:
            print(f"校验 {len(stale)} 个外链 ...")
            checked = {u: st for u, st in probe_parallel([t["cover"] for t in stale])}
            broken = [t for t in stale
                      if not (checked.get(t["cover"]) == 200
                              or ((not STRICT_ALIVE) and checked.get(t["cover"]) == 0))]
            print(f"失效 {len(broken)} 个 -> 重新抓取")
            for t in broken:
                todo.append(t["slug"])
        fresh = [t for t in stale if t["slug"] not in todo]
        for t in fresh:                  # 校验通过的刷新一下时间
            t["verified_at"] = time.strftime("%Y-%m-%d", time.gmtime())

    results: dict[str, dict] = {}
    if todo:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = {ex.submit(process, r, args.download): r for r in todo}
            for f in as_completed(futs):
                slug = futs[f]
                try:
                    results[slug] = f.result()
                except Exception as e:
                    print(f"  !! {slug}: {e}", file=sys.stderr)
                    results[slug] = {"slug": slug, "owner": slug.split("/")[0],
                                     "repo": slug.split("/")[1], "name": prettify(slug.split("/")[1]),
                                     "url": f"https://github.com/{slug}", "screenshots": [],
                                     "remote": [], "cover": None}

    themes = [results.get(r) or cache[r] for r in repos]

    # 清理不再被引用的旧截图 (主题被上游移除 / 索引变化后残留)
    if not args.no_prune:
        used = {s.rsplit("/", 1)[-1] for t in themes for s in t.get("screenshots", [])}
        if len(used) > 20:          # 安全阀: 引用数异常时不删
            removed = 0
            for f in ASSETS.iterdir():
                if f.is_file() and f.name not in used:
                    f.unlink()
                    removed += 1
            if removed:
                print(f"清理旧图 {removed} 张")

    THEMES_JSON.write_text(
        json.dumps(themes, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # A7: 内容没实质变化时不要重写文件, 避免"最近更新"时间戳造成空转提交
    missing = [t for t in themes if not t.get("cover")]
    old_txt = README.read_text(encoding="utf-8") if README.exists() else ""
    stamp = re.compile(r"^- 最近更新：.*$", re.M)
    new_txt = build_readme(themes, missing)
    if old_txt and stamp.sub("", old_txt).strip() == stamp.sub("", new_txt).strip():
        print("README 内容无变化, 保持原样")
    else:
        README.write_text(new_txt, encoding="utf-8")
    print(f"\n完成: {len(themes) - len(missing)}/{len(themes)} 有截图 -> README.md")
    if missing:
        print("缺失: " + ", ".join(t["slug"] for t in missing))


if __name__ == "__main__":
    main()
