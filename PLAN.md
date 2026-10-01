# 修复方案 v1（待审核）

> 生成时间：2026-10-01 · 仅方案，不改代码；你确认后我再动手，按 A1 → A2 → A3 → A4 → A5/A6 顺序执行并单独提交。

## 0. 现状快照

| 项 | 值 |
|---|---|
| 主题总数 / 有截图 | 71 / 67（缺的 4 个上游仓库已删除） |
| 图片模式 | 纯外链，仓库内 0 张图 |
| README | 982 行，204 个 `<img>` |
| docs/index.html | 714 行，响应式网格 |
| 外链域名分布 | raw.githubusercontent.com 54 · i.imgur.com 10 · user-images.githubusercontent.com 1 · github.com/user-attachments 1 · img.youtube.com 1 |
| **实测体积** | 抽样 48 张 = 26.8 MB，平均 **573 KB/张** → 全量 204 张约 **35 MB** |
| 每轮抓取耗时 | 约 8 分钟（并行探测版） |
| 缺失门面 | 无 LICENSE、无 description、无 topics |
| 悬空 tag | `v0.1` 指向旧的带图 commit `215ce4a` |

---

## A1 · 外链失效自愈（P0，真缺陷）

**问题**：`scripts/generate.py:484` 的 `done()` 只判断「有没有 cover」，有就跳过。上游一旦改名/删图，这条记录**永远不会被重新抓取**，README 里就是一张永久裂图。现在每周跑的 Action 对这类情况完全无感。

**方案**：
1. `data/themes.json` 每个条目新增 `verified_at`（ISO 日期，记录上次 HEAD 校验时间）。
2. `generate.py` 新增参数：
   - `--verify`：只做「校验 + 补抓」，不动正常条目。流程 = 并行 HEAD 所有 cover → 失效的清空 cover 后重跑 `find_shots` → 仍失败标 `dead`。
   - `--strict-alive`：CI 专用。本机网络会把连接失败（status 0）当「存活」，CI 上网络正常，应判定为失效（现在 `url_alive()` 在 `scripts/generate.py:210` 把 0 当存活，会放过坏链）。
3. `done()` 增加判定：`--verify` 模式下 `verified_at` 早于 7 天前的条目也要重校验。
4. README 顶部增加一行「外链上次校验：YYYY-MM-DD」；失效并修复的数量写进 commit message。
5. workflow：每周任务里在 generate 之后追加 `python scripts/generate.py --verify --strict-alive`。

**验收**：手动把某个条目的 cover 改成一个不存在的 URL → `--verify` 后该条目被重新抓取或标记 dead，README 不再出现该坏链。

**风险**：低。只增加字段与一个只读校验流程，不改变正常抓取逻辑。67 次 HEAD 约 30 秒。

---

## A2 · README 体积（P0，35 MB → 约 4 MB）

**问题**：`width="300"` 只改显示尺寸，浏览器仍要下载完整原图（平均 573 KB，最大单张 1.52 MB）。

三个方案，**请你选一个**（我个人推荐 ③）：

| 方案 | 做法 | 首屏体积 | 代价 |
|---|---|---|---|
| ① 缩略图 CDN | 所有 `<img src>` 前置一层 `https://images.weserv.nl/?url=<原图>&w=400` | ~4 MB | 多一个第三方服务依赖（可用性/隐私） |
| ② README 瘦身 | README 只保留目录 + 精选 24 张，完整画廊交给 Pages | ~6 MB | README 不再是「全量画廊」，与最初目标有出入 |
| ③ 混合（推荐） | README 与 docs 都用 CDN 缩略图，点击卡片看原图；README 顶部放 Pages 在线画廊链接 | ~4 MB | 同 ①，但体验最好 |

配套：加 `--no-thumb` 开关，任何时候可以退回直连原图；缩略图 URL 只在生成阶段拼装，`themes.json` 仍存原图地址，不丢数据。

**验收**：用浏览器 DevTools 打开 README，Network 面板图片总下载量从 ~35 MB 降到个位数 MB。

**风险**：①/③ 依赖 images.weserv.nl（免费公共 CDN，无 SLA）。若你不想依赖第三方，选 ②。

---

## A3 · 开 Pages + 画廊加交互（P1）

**问题**：`docs/index.html` 已经是可用的响应式画廊，但没部署、没有筛选能力，71 个主题只能肉眼翻。

**方案**：
1. **Pages 开启需要你在仓库 Settings → Pages → Source 选 `main` / 目录 `/docs`**（这步我改不了，需要你点一下）。
2. `scripts/preview.py` 生成的页面加约 60 行纯前端代码：
   - 顶部搜索框：按主题名 / 作者实时过滤
   - 暗色模式（跟随系统 `prefers-color-scheme`）
   - 点击图片放大（lightbox）
   - 卡片显示「N 张截图」角标（数据已在 themes.json 里）
3. README 顶部加一行在线画廊链接（Pages 地址）。

**验收**：打开 Pages 地址，输入作者名能立刻过滤；点击图片放大。

**风险**：低，纯前端，不影响抓取逻辑。

---

## A4 · 死库跳过（P1，省时间）

**问题**：`ElectronicRave/ES-Simple-Clean`、`ElectronicRave/RP-Launcher`、`ZagonAb/Limbo-Theme`、`ZagonAb/FlixNet_Plus` 上游已删除。现在每轮仍要跑完「README 探测 → .meta 探测 → 25 条候选路径」才放弃，白耗时间。

**方案**：
1. themes.json 加 `dead: true` 与 `dead_since` 日期。
2. `main()` 的 `done()`：若条目 `dead` 且 `dead_since` 未超过 30 天 → 直接跳过本轮抓取。
3. README「暂未取到截图」区块对 dead 条目标注「（上游仓库不可访问）」，跟「暂时没图」区分开。

**验收**：手工把某条目标成 dead，再跑一次，日志显示该条目被跳过；30 天边界到期后会重新尝试。

**风险**：低。最坏情况是仓库恢复后最多延迟 30 天被重新发现。

---

## A5 · 门面补齐（P2）

1. **LICENSE**：脚本用 MIT；README 增加声明——代码 MIT，截图版权归各主题作者所有，仅作预览。
2. **description**：`Pegasus Frontend 主题截图画廊 · 71 themes preview`
3. **topics**：`pegasus-frontend` · `theme-gallery` · `retro-gaming` · `launcher` · `screenshots`

**风险**：无。要不要 LICENSE 由你定（不加的话别人默认不能复用你的脚本）。

---

## A6 · 数据字段与历史清理（P2）

1. themes.json 补字段：`updated_at`（本条最后更新时间）、`shots_count`、`aspect`（宽高比，用于瀑布流布局）、`source`（截图来源：meta/readme/candidate）。
2. **tag 清理**：删除指向带图旧 commit 的 `v0.1`；是否把 `v1.0` 重打到最新 commit，由你定。
3. **小瑕疵**：`TigraTT-Driver/shinretro` 的封面是 YouTube 视频缩略图（`img.youtube.com`），不是真截图——建议标注或降级为「无截图」。

**风险**：删 tag 是不可逆操作，需要你明确点头我才做。

---

## A7 · 避免空转提交（P1，刚发现的新问题）

**问题**：今天手动跑了两轮，两轮都成功 push，但 diff 对比（`c4a94ca` vs `1224acf`）显示只有 6 处插入 / 16 处删除，其中绝大部分是 README 里的「最近更新：02:57 → 02:59」时间戳。也就是说**内容没变也会产生一个 commit**，历史会被每周的「chore: refresh gallery」刷屏。

**方案**：
1. 「最近更新」改为只在**内容真发生变化时**才刷新（先生成到内存，与旧 README 去掉时间戳行后比对，有差异才写新时间戳）。
2. workflow 的提交判定加强：`git diff --cached` 之前先做一次「忽略时间戳行」的比较，一致就 `no changes` 退出。
3. themes.json 保持稳定的键顺序与缩进，避免无意义 diff。

**验收**：连续跑两次 Action，第二次输出 `no changes`，不产生新 commit。

**风险**：低。

---

## 执行顺序与影响

```
A1 外链自愈      → 改 generate.py + workflow，新增 2 个参数，约 60 行改动
A2 体积优化      → 改 generate.py 的 README 生成 + preview.py，约 30 行改动（取决于选哪个方案）
A3 Pages + 交互  → 改 preview.py，约 60 行；Pages 开关需你在网页点一下
A4 死库跳过      → 改 generate.py，约 15 行
A7 空转提交      → 改 generate.py 时间戳逻辑 + workflow 提交判定，约 20 行
A5 门面          → 新增 LICENSE，README 加声明
A6 数据/清理     → 改 generate.py 字段，tag 操作
```

已顺带验证：push 前的 `fetch + rebase` 修复生效，今天的两轮 Action 都推成功了（不再 rejected）。

预计 A1+A2+A3+A4 一起做完约 1 小时（不含我这边重跑抓取的时间），每次单独一个 commit，方便你逐条 review 和回退。

## 不做的事（避免范围蔓延）

- 不改成需要登录/GitHub API 的方案（本机 API 不可达）
- 不引入前端构建工具，docs 保持单文件纯静态
- 不重写抓取脚本架构（536 行还能维护，先补功能）

---

## 需要你拍板的 3 件事

1. **A2 选哪个方案**：① CDN 缩略图 / ② README 瘦身 / ③ 混合（推荐）
2. **A5 是否加 LICENSE**：MIT（推荐）/ 不加
3. **A6 是否动 tag**：删 `v0.1` 并把 `v1.0` 重打到最新 / 只删 `v0.1` / 都不动

回我一句话（比如「按方案③，加 MIT，只删 v0.1」），我就开工。
