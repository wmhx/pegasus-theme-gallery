#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 data/themes.json 渲染成一份可直接在浏览器打开的画廊页面 docs/index.html"""

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THEMES = json.loads((ROOT / "data" / "themes.json").read_text(encoding="utf-8"))
OUT = ROOT / "docs" / "index.html"

themes = [t for t in THEMES if t.get("cover")]
missing = [t for t in THEMES if not t.get("cover")]

cards = []
for t in sorted(themes, key=lambda x: x["name"].lower()):
    src = t["cover"]
    # 本地 assets/ 路径在 docs/ 下需要上一级
    if src.startswith("assets/"):
        src = "../" + src
    shots = [("../" + s if s.startswith("assets/") else s) for s in (t["screenshots"] + t["remote"])]
    extra = "".join(f'<img src="{html.escape(s)}" loading="lazy" alt="">' for s in shots[1:])
    cards.append(f"""  <figure class="card">
    <a href="{html.escape(t['url'])}" target="_blank" rel="noopener">
      <img src="{html.escape(src)}" loading="lazy" alt="{html.escape(t['name'])}">
    </a>
    <figcaption>
      <a href="{html.escape(t['url'])}" target="_blank" rel="noopener">{html.escape(t['name'])}</a>
      <span>@{html.escape(t['owner'])}</span>
    </figcaption>
    {('<div class="extra">' + extra + '</div>') if extra else ''}
  </figure>""")

miss = "".join(
    f'<li><a href="https://github.com/{html.escape(t["slug"])}">{html.escape(t["slug"])}</a></li>'
    for t in missing
)

HTML = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pegasus 主题截图画廊</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ margin:0; background:#f7f8fa; color:#1f2328;
         font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif; }}
  header {{ padding:28px 24px 18px; background:#fff; border-bottom:1px solid #e5e7eb; }}
  h1 {{ margin:0 0 8px; font-size:22px; }}
  header p {{ margin:4px 0; color:#57606a; font-size:14px; }}
  main {{ padding:24px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:18px; }}
  .card {{ margin:0; background:#fff; border:1px solid #e5e7eb; border-radius:10px;
           overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,.04); }}
  .card img {{ display:block; width:100%; height:auto; background:#eee; }}
  .card figcaption {{ padding:10px 12px; font-size:14px; display:flex;
                      justify-content:space-between; gap:8px; align-items:baseline; }}
  .card figcaption a {{ color:#0969da; text-decoration:none; font-weight:600; }}
  .card figcaption span {{ color:#8b949e; font-size:12px; }}
  .extra {{ padding:0 12px 12px; display:flex; gap:6px; overflow-x:auto; }}
  .extra img {{ height:56px; width:auto; border-radius:4px; }}
  section.missing {{ margin-top:32px; color:#57606a; font-size:14px; }}
</style>
</head>
<body>
<header>
  <h1>Pegasus Frontend 主题截图画廊</h1>
  <p>共 {len(THEMES)} 个主题，{len(themes)} 个已取到截图 —— 数据来自
     <a href="https://github.com/mmatyas/pegasus-theme-gallery-db">pegasus-theme-gallery-db</a></p>
  <p>点击卡片跳转到原仓库。截图版权归各主题作者。</p>
</header>
<main>
  <div class="grid">
{chr(10).join(cards)}
  </div>
  <section class="missing">
    <h2>暂未取到截图（{len(missing)}）</h2>
    <ul>{miss}</ul>
  </section>
</main>
</body>
</html>
"""

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(HTML, encoding="utf-8")
print(f"生成 {OUT}（{len(themes)} 张卡片）")
