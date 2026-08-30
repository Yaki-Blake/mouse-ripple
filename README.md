# shuibo

基于 WebGL 的网页实时水波纹背景特效。鼠标移动 / 点击、手指滑动会在背景图上激起扩散的涟漪。

**零依赖、零构建**：纯原生 JavaScript，不依赖 jQuery，不需要 npm 或打包工具，复制两个 `<script>` 标签即可用。

## 目录结构

```
shuibo/
├── webgl-ripples.js   # 核心库（改造自 jQuery Ripples v0.0.1，已去除 jQuery 依赖）
├── bg-datauri.js      # 自动生成的背景图 data URI（desktop / mobile 两张 JPEG）
├── demo.html          # 最小可运行示例
├── README.md
└── LICENSE
```

## 快速开始

```html
<div id="ripple" style="width:100%; height:100vh;"></div>

<script src="bg-datauri.js"></script>
<script src="webgl-ripples.js"></script>
<script>
  var bg = window.innerWidth < 768
    ? window.__RIPPLE_BG__.mobile
    : window.__RIPPLE_BG__.desktop;

  new Ripples('#ripple', {
    imageUrl: bg,
    resolution: 256,
    dropRadius: 20,
    perturbance: 0.03,
    interactive: true
  });
</script>
```

通过 `http(s)://` 访问时，可省略 `bg-datauri.js`，直接把 `imageUrl` 指向普通图片路径。

## 配置参数

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `imageUrl` | string | `null` | 背景图地址；留空则读取元素自身的 CSS `background-image` |
| `resolution` | number | `256` | 水波模拟网格分辨率，越大越细腻、越耗性能 |
| `dropRadius` | number | `20` | 水滴半径（像素） |
| `perturbance` | number | `0.03` | 折射扰动强度，越大背景扭曲越明显 |
| `interactive` | boolean | `true` | 是否响应鼠标 / 触摸 |
| `crossOrigin` | string | `''` | 图片的 `crossOrigin` 属性 |

## 实例方法

| 方法 | 说明 |
| --- | --- |
| `drop(x, y, radius, strength)` | 在指定像素坐标生成一滴水（`strength` 为强度，通常 0.01 ~ 0.14） |
| `play()` / `pause()` | 继续 / 暂停动画循环 |
| `show()` / `hide()` | 显示 / 隐藏特效画布（隐藏时自动还原 CSS 静态背景） |
| `set(prop, value)` | 动态修改 `dropRadius`、`perturbance`、`interactive`、`crossOrigin`、`imageUrl` |
| `updateSize()` | 重算画布尺寸（已自动监听 `resize`，一般无需手动调用） |
| `destroy()` | 销毁实例，移除 canvas 与事件监听 |

## 浏览器兼容

依赖 **WebGL** 与 **`OES_texture_float`** 扩展。现代 Chrome、Edge、Firefox、Safari 均支持；不支持的环境会直接跳过初始化，页面退化为静态背景，不会报错。

## 为什么背景图要转成 data URI

双击本地 HTML（`file://` 协议）打开时，浏览器把本地图片视作跨域资源，WebGL 用它做纹理会抛 `SecurityError`；data URI 属于同源，因此可正常工作。这是 `bg-datauri.js` 存在的唯一原因——若你的页面部署在服务器上，直接用普通图片路径即可。

## 许可

[MIT](./LICENSE)。原始实现版权归 [sirxemic](https://github.com/sirxemic/jquery.ripples) 所有，本仓库为其去 jQuery 改造版。
