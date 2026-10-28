**简体中文** | [English](README_EN.md)

# 鼠标涟漪 / Mouse Ripples

可以一键让你的鼠标在前端活动时加上涟漪效果

WebGL 实时水面涟漪：指针划过的位置生成波峰，波纹向外扩散、折射背景、留下镜面高光。

**在线预览：<https://yaki-blake.github.io/mouse-ripple/>**

## 1. 文件结构

```
mouse-ripple/
├── index.html             演示页（内联引擎 + 背景图），也是 Pages 首页
├── ripple-inject.py       注入器：扫描 → 手选 → 写入目标项目
├── 双击注入.bat           Windows 启动器
├── src/ripple-engine.js   引擎源码，958 行（唯一真源）
├── LICENSE                引擎上游 sirxemic 的 MIT 许可
└── .nojekyll              告诉 Pages 不要跑 Jekyll，原样发布
```

## 2. 有什么用

- **看效果**：双击 `index.html`。全屏铺图，鼠标移动起微波、按下起大波。零依赖，可单文件发给别人；仓库开了 Pages 后，根地址打开的就是它。
- **给别人用**：把注入器拷进任意前端项目，选中页面即可批量获得同一效果。

## 3. 怎么用（三步）

1. 把 `ripple-inject.py` 和 `双击注入.bat` 一起拷到目标项目目录。
2. 双击 `双击注入.bat` → 控制台列候选 → 弹窗里选择文件 → 确定。

补充：操作后会自动生成备份文件——`.bak` ，复制回去即撤销。

## 4. 代码逻辑

**引擎**——高度场波动模拟，每帧在 GPU 上跑三遍：

1. `dropProgram`：在指针处写入余弦形波峰（振幅 = strength，半径 = radius）。
2. `updateProgram`：取上下左右四点均值做离散波动方程积分，速度每帧乘 0.985 衰减。
3. `renderProgram`：用高度场梯度求法线，偏移背景纹理的采样位置得到折射，再叠一层镜面高光；
   高光强度随波峰坡度增长，保证涟漪在纯色、深色区域同样看得见（纯折射只在背景有细节处产生差异）。

高度场是 256×256 浮点纹理，双缓冲交替读写；画布尺寸与背景 UV 由 `background-size / position` 反算。

**注入器**——扫描目录后按扩展名分级：HTML 类插在 `</body>` 前，`.js` 追加自执行代码，`.jsx/.tsx/.vue/.svelte` 只写注释片段，`.css` 跳过。用 ctypes 调 Win32 多选对话框选文件；注入前留 `.bak`，文件里已有标记则跳过（幂等）。另外把页面自带背景图内联成 data URI，规避 `file://` 下 WebGL 取本地图片的 `SecurityError`。
