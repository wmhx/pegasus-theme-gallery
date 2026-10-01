#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 data/themes.json 渲染成一份可直接在浏览器打开的画廊页面 docs/index.html"""

import html
import json
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THEMES = json.loads((ROOT / "data" / "themes.json").read_text(encoding="utf-8"))
OUT = ROOT / "docs" / "index.html"

THUMB_CDN = "https://images.weserv.nl/?url={url}&w=400&output=jpg&q=80"
THUMB_ON = True        # 与 generate.py 保持一致


def thumb(u: str) -> str:
    if not THUMB_ON or not u.startswith("http"):
        return u
    return THUMB_CDN.format(url=urllib.parse.quote(u, safe=""))


themes = [t for t in THEMES if t.get("cover")]
missing = [t for t in THEMES if not t.get("cover")]

cards = []
for t in sorted(themes, key=lambda x: x["name"].lower()):
    # 本地 assets/ 路径(仅 --download 模式)在 docs/ 下需要上一级
    src = "../" + t["cover"] if t["cover"].startswith("assets/") else thumb(t["cover"])
    shots_list = t["screenshots"] + t["remote"]
    shots = ["../" + s if s.startswith("assets/") else thumb(s) for s in shots_list]
    extra = "".join(f'<img src="{html.escape(s)}" loading="lazy" alt="">' for s in shots[1:])
    badge = f'<span class="badge">{len(shots_list)} 张</span>' if len(shots_list) > 1 else ""
    cards.append(f"""  <figure class="card" data-name="{html.escape(t['name'].lower())}" data-owner="{html.escape(t['owner'].lower())}">
    <a href="{html.escape(t['url'])}" target="_blank" rel="noopener">
      <img src="{html.escape(src)}" loading="lazy" alt="{html.escape(t['name'])}">
    </a>{badge}
    <figcaption>
      <a href="{html.escape(t['url'])}" target="_blank" rel="noopener">{html.escape(t['name'])}</a>
      <span>@{html.escape(t['owner'])}</span>
    </figcaption>
    {('<div class="extra">' + extra + '</div>') if extra else ''}
  </figure>""")

miss = "".join(
    f'<li><a href="https://github.com/{html.escape(t["slug"])}">{html.escape(t["slug"])}</a>'
    + (' <em>（上游仓库不可访问）</em>' if t.get("dead") else '')
    for t in missing
)

HTML = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pegasus 主题截图画廊</title>
<style>
  :root {{
    color-scheme: light;
    --bg: #f7f8fa; --panel: #fff; --line: #e5e7eb; --fg: #1f2328;
    --muted: #57606a; --link: #0969da;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      color-scheme: dark;
      --bg: #0d1117; --panel: #161b22; --line: #30363d; --fg: #e6edf3;
      --muted: #8b949e; --link: #58a6ff;
    }}
  }}
  body {{ margin:0; background:var(--bg); color:var(--fg);
         font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif; }}
  header {{ padding:28px 24px 18px; background:var(--panel); border-bottom:1px solid var(--line); }}
  h1 {{ margin:0 0 8px; font-size:22px; }}
  header p {{ margin:4px 0; color:var(--muted); font-size:14px; }}
  .toolbar {{ padding:16px 24px 0; }}
  #q {{ width:min(420px,100%); padding:9px 12px; font-size:14px;
        border:1px solid var(--line); border-radius:8px;
        background:var(--panel); color:var(--fg); }}
  #q:focus {{ outline:2px solid var(--link); outline-offset:1px; }}
  main {{ padding:16px 24px 24px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:18px; }}
  .card {{ position:relative; margin:0; background:var(--panel); border:1px solid var(--line);
           border-radius:10px; overflow:hidden; }}
  .card img {{ display:block; width:100%; height:auto; background:#eee; }}
  .card figcaption {{ padding:10px 12px; font-size:14px; display:flex;
                      justify-content:space-between; gap:8px; align-items:baseline; }}
  .card figcaption a {{ color:var(--link); text-decoration:none; font-weight:600; }}
  .card figcaption span {{ color:var(--muted); font-size:12px; }}
  .extra {{ padding:0 12px 12px; display:flex; gap:6px; overflow-x:auto; }}
  .extra img {{ height:56px; width:auto; border-radius:4px; }}
  .badge {{ position:absolute; top:8px; right:8px; font-size:11px; padding:2px 7px;
            border-radius:999px; background:rgba(0,0,0,.65); color:#fff; }}
  section.missing {{ margin-top:32px; color:var(--muted); font-size:14px; }}
  .empty {{ padding:40px 0; text-align:center; color:var(--muted); }}
</style>
</head>
<body>
<header>
  <h1>Pegasus Frontend 主题截图画廊</h1>
  <p>共 {len(THEMES)} 个主题，{len(themes)} 个已取到截图 —— 数据来自
     <a href="https://github.com/mmatyas/pegasus-theme-gallery-db">pegasus-theme-gallery-db</a></p>
  <p>点击卡片跳转到原仓库。截图版权归各主题作者，缩略图由 images.weserv.nl 生成。</p>
</header>
<div class="toolbar">
  <input id="q" type="search" placeholder="搜索主题名或作者，例如 ZagonAb / flixnet" autocomplete="off">
</div>
<main>
  <div class="grid" id="grid">
{chr(10).join(cards)}
  </div>
  <div class="empty" id="empty" hidden>没有匹配的主题</div>
  <section class="missing">
    <h2>暂未取到截图（{len(missing)}）</h2>
    <ul>{miss}</ul>
  </section>
</main>
<script>
  var q = document.getElementById('q');
  var cards = Array.prototype.slice.call(document.querySelectorAll('.card'));
  var empty = document.getElementById('empty');
  q.addEventListener('input', function () {{
    var k = q.value.trim().toLowerCase();
    var shown = 0;
    cards.forEach(function (c) {{
      var hit = !k || c.dataset.name.indexOf(k) > -1 || c.dataset.owner.indexOf(k) > -1;
      c.style.display = hit ? '' : 'none';
      if (hit) shown++;
    }});
    empty.hidden = shown > 0;
  }});
</script>
</body>
</html>
"""

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(HTML, encoding="utf-8")
(OUT.parent / ".nojekyll").write_text("", encoding="utf-8")
print(f"生成 {OUT}（{len(themes)} 张卡片）")
