# 网页水波纹注入工具 · Web Ripple Injector

语言 / Language: **[中文](#中文)** | **[English](#english)**

---

## 中文

### 这是什么

把 WebGL 实时水波纹特效**一键注入**任意本地 HTML 页面：注入后双击打开网页，鼠标划过泛起涟漪、点击溅起水花、触屏滑动同样支持，无人交互时每 3 秒自动落一滴水。不依赖 jQuery、不需要 npm 或打包，原页面代码一个字符都不动，随时可完整还原。

### 文件清单

| 文件 | 作用 |
| --- | --- |
| `inject.py` | 注入工具（必须）：图形界面 + 命令行，纯 Python 标准库，零依赖 |
| `webgl-ripples.js` | 核心库（必须）：jQuery Ripples 去 jQuery 改造版，支持传播速度 / 衰减等参数 |
| `bg-datauri.js` | 内置背景图（可选）：页面没有可用背景图时运行时自动启用 |
| `inject.bat` | 双击运行入口（可选）：命令行方式可以不用它 |
| `index.html` | 在线 demo，也是全部参数的默认效果标准 |

### 快速开始（务必先复制，再运行）

1. 把 `inject.py`、`webgl-ripples.js` 复制到**目标 HTML 所在的文件夹**（页面没有背景图时连同 `bg-datauri.js` 一起复制）。
2. 双击 `inject.bat`（或运行 `python inject.py`）→ 弹出窗口自动列出该目录下所有 HTML 及状态（已注入 / 未注入）→ 勾选目标文件 → 点击「Start injection」。
3. 双击目标网页，鼠标划过即见水波。

### 命令行方式（批量 / 自动化）

```bash
python inject.py --cli index.html              # 注入（自动判定背景）
python inject.py --cli index.html --bg builtin # 运行时强制使用内置背景图
python inject.py --cli index.html --remove     # 卸载还原（逐字节校验）
```

### 涟漪参数调节

默认参数与 `index.html` 的效果完全一致；修改后一键可恢复默认。

| 参数 | 含义 | 默认值 | 建议范围 |
| --- | --- | --- | --- |
| `speed` | 传播速度：波纹扩散的快慢 | 2 | 0.1 – 10 |
| `damping` | 衰减保留率：越接近 1 波纹存续越久（衰减越慢） | 0.985 | 0.5 – 0.999 |
| `perturbance` | 波峰波谷高度：画面折射扭曲的强度 | 0.03 | 0 – 0.5 |
| `dropRadius` | 波纹半径 / 波距：初始水滴大小，决定波纹间距 | 20 | 1 – 200 |
| `resolution` | 模拟网格分辨率：波纹细腻度与性能开销 | 256 | 32 – 2048 |

三种修改方式：

- **图形界面**：窗口下方「Ripple parameters」区直接改数值，点击「Start injection」即以当前参数注入并记住；「Restore defaults」一键恢复默认。
- **命令行注入时指定**（可重复，只影响本次并保存）：
  ```bash
  python inject.py --cli index.html --set speed=3 --set damping=0.99 --set dropRadius=30
  ```
- **只保存参数不注入**（供下次 GUI / 注入使用）：
  ```bash
  python inject.py --set speed=3
  ```

一键恢复默认：

```bash
python inject.py --reset-defaults    # 恢复全部参数为 index.html 标准
```

自定义参数保存在工具目录的 `shuibo-params.json`（仅在实际修改后才会生成；恢复默认时自动删除）。

### 工作原理（使用者需要知道的五点）

1. **只改一处**：注入内容整体插到 `</body>` 之前，包在 `<!-- SHUIBO-INJECT:START/END -->` 标记内，页面原有代码一个字符都不动。
2. **幂等 + 可完整还原**：重复注入内容不变；卸载（`--remove` 或界面「Remove injection」）剥离标记块后与首次备份 `.bak` 逐字节比对验证。
3. **背景图运行时三级自动判定**：优先用页面当前生效的背景图（含外部 CSS，注入前预载验证）；`file://` 双击打开时本地图必然被 WebGL 拒绝，自动跳过并降级；随后用内置 data URI 背景图；都没有则按页面背景色动态生成噪点纹理兜底。每一级失败都有下一级接住。
4. **编码自动识别，宁可拒绝不写坏**：BOM → `<meta charset>` 声明 → UTF-8 严格解码 → GBK 严格解码，四级全部失败则拒绝注入；注入内容纯 ASCII，任何编码下都不会引入乱码。
5. **不影响页面交互**：水波层位于 `z-index:-1` 底层且 `pointer-events:none`，事件在 `window` 上监听后转发给水波，强度与库原生一致（移动 0.01 / 按下 0.14）。

### 常见问题

- **注入后看不到波纹？** 按顺序排查：① 目标文件夹里有没有 `webgl-ripples.js`（缺库工具会直接拒绝注入，不会产生死链）；② 浏览器是否支持 WebGL；③ 页面背景是否为纯色（会自动使用噪点兜底，波纹仍可见，只是没有背景图好看）。
- **如何完整还原页面？** `python inject.py --cli 页面.html --remove`，或在界面勾选后点「Remove injection」。还原结果与注入前逐字节一致。
- **可以注入哪些页面？** 同目录扫描所有 `.html` / `.htm`；没有 `</body>` 的文件会在末尾追加注入块。
- **参数改坏了想重来？** `python inject.py --reset-defaults`，或界面点「Restore defaults」，再重新注入即可。

### 浏览器要求

依赖 WebGL 与 `OES_texture_float` 扩展，现代 Chrome / Edge / Firefox / Safari 均支持；不支持的环境自动退化为静态背景，页面不报错。

### 许可

[MIT](./LICENSE)。原始实现版权归 [sirxemic](https://github.com/sirxemic/jquery.ripples) 所有，本仓库为其去 jQuery 改造版及注入工具。

---

## English

### What is this

One-click injection of a real-time WebGL ripple effect into any local HTML page. After injection, just double-click the page: moving the mouse creates ripples, clicking makes splashes, touch works the same, and an ambient drop falls every 3 seconds. No jQuery, no npm, no build step — the original page code is never touched and can be fully restored at any time.

### Files

| File | Purpose |
| --- | --- |
| `inject.py` | Injector (required): GUI + CLI, pure Python standard library, zero dependencies |
| `webgl-ripples.js` | Core library (required): de-jQuery port of jQuery Ripples, with speed / damping parameters |
| `bg-datauri.js` | Builtin background (optional): auto-enabled at runtime when the page has no usable background image |
| `inject.bat` | Double-click launcher (optional): not needed for CLI usage |
| `index.html` | Online demo; also the reference standard for all default parameters |

### Quick start (copy first, then run)

1. Copy `inject.py` and `webgl-ripples.js` into the **folder of the target HTML** (also copy `bg-datauri.js` if the page has no background image).
2. Double-click `inject.bat` (or run `python inject.py`) → the window lists all HTML files in that folder with their status (injected / clean) → check the target file → click "Start injection".
3. Double-click the page — move the mouse and watch the ripples.

### Command line (batch / automation)

```bash
python inject.py --cli index.html              # inject (auto background)
python inject.py --cli index.html --bg builtin # force builtin background at runtime
python inject.py --cli index.html --remove     # remove injection (byte-verified)
```

### Ripple parameters

Defaults are identical to the `index.html` demo; restoring them takes one click.

| Parameter | Meaning | Default | Suggested range |
| --- | --- | --- | --- |
| `speed` | Propagation speed: how fast ripples spread | 2 | 0.1 – 10 |
| `damping` | Decay retention: closer to 1 means ripples last longer | 0.985 | 0.5 – 0.999 |
| `perturbance` | Wave height: refraction / distortion intensity | 0.03 | 0 – 0.5 |
| `dropRadius` | Ripple size / spacing: initial drop radius in px | 20 | 1 – 200 |
| `resolution` | Simulation grid resolution: detail vs. performance | 256 | 32 – 2048 |

Three ways to change them:

- **GUI**: edit the values in the "Ripple parameters" panel and click "Start injection" (values are remembered); "Restore defaults" resets them in one click.
- **Per injection on the CLI** (repeatable, also saved):
  ```bash
  python inject.py --cli index.html --set speed=3 --set damping=0.99 --set dropRadius=30
  ```
- **Save parameters only** (used by the next GUI session / injection):
  ```bash
  python inject.py --set speed=3
  ```

One-click restore:

```bash
python inject.py --reset-defaults    # restore all parameters to index.html standard
```

Custom parameters are stored in `shuibo-params.json` next to the tool (created only after an actual change; removed automatically when defaults are restored).

### How it works (five things worth knowing)

1. **One touch point**: the whole block is inserted right before `</body>`, wrapped in `<!-- SHUIBO-INJECT:START/END -->` markers; not a single character of the original code is modified.
2. **Idempotent + fully restorable**: repeated injections produce identical output; removal strips the markers and is byte-compared against the automatic `.bak` backup.
3. **Runtime three-tier background fallback**: prefer the page's effective background image (external CSS included, preloaded before use); under `file://` local images are always rejected by WebGL, so that tier is skipped automatically; next comes the builtin data-URI background; finally a noise texture tinted with the page background color. Every failure has a next tier.
4. **Encoding auto-detection, refuse rather than corrupt**: BOM → `<meta charset>` → strict UTF-8 → strict GBK; if all four fail, the file is refused. Injected content is pure ASCII and can never introduce mojibake.
5. **Page interaction untouched**: the ripple layer sits at `z-index:-1` with `pointer-events:none`; events are captured on `window` and forwarded with the library's native strengths (move 0.01 / press 0.14).

### FAQ

- **No ripples after injection?** Check in order: ① is `webgl-ripples.js` in the target folder (the tool refuses to inject without it — no dead links); ② does the browser support WebGL; ③ is the page background a flat color (a noise fallback keeps ripples visible, just less pretty than a photo).
- **How to fully restore a page?** `python inject.py --cli page.html --remove`, or select it in the GUI and click "Remove injection". The result is byte-identical to the original.
- **Which pages can be injected?** All `.html` / `.htm` files in the folder; files without `</body>` get the block appended at the end.
- **Mess up the parameters?** `python inject.py --reset-defaults`, or click "Restore defaults" in the GUI, then re-inject.

### Browser support

Requires WebGL and the `OES_texture_float` extension — supported by all modern Chrome / Edge / Firefox / Safari. Unsupported environments degrade to a static background without errors.

### License

[MIT](./LICENSE). The original implementation is copyright [sirxemic](https://github.com/sirxemic/jquery.ripples); this repository is a de-jQuery port plus the injection tool.
