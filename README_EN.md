[简体中文](README.md) | **English**

# Mouse Ripples

Add a water-ripple effect to the mouse cursor on any front-end page with a single injection.

Real-time WebGL water ripples: wave crests form wherever the pointer passes; the ripples spread outward, refract the background, and leave specular highlights behind.

**Live demo: <https://yaki-blake.github.io/mouse-ripple/>**

## 1. File Structure

```
mouse-ripple/
├── index.html             Demo page (inlined engine + background image); also the Pages landing page
├── ripple-inject.py       Injector: scan → pick files manually → write into the target project
├── 双击注入.bat           Windows launcher
├── src/ripple-engine.js   Engine source, 958 lines (the single source of truth)
├── LICENSE                MIT license of the upstream engine, sirxemic
└── .nojekyll              Tells Pages not to run Jekyll, publishing files as-is
```

## 2. What It Does

- **See it in action**: double-click `index.html`. The image fills the screen; moving the mouse creates small waves, clicking creates large ones. Zero dependencies, so it can be shared as a single file; once Pages is enabled for the repository, this page is what the root URL serves.
- **Hand it to others**: copy the injector into any front-end project, select the pages you want, and they all get the same effect in bulk.

## 3. How to Use (Three Steps)

1. Copy `ripple-inject.py` and `双击注入.bat` together into the target project directory.
2. Double-click `双击注入.bat` → the console lists the candidates → select files in the dialog → confirm.

Note: the operation automatically produces backup files — `.bak`. Copy them back to revert.

## 4. How the Code Works

**Engine** — a height-field wave simulation, run three times per frame on the GPU:

1. `dropProgram`: writes a cosine-shaped crest at the pointer position (amplitude = `strength`, radius = `radius`).
2. `updateProgram`: integrates the discrete wave equation by averaging the four neighbouring samples (up, down, left, right); velocity is multiplied by 0.985 each frame to decay.
3. `renderProgram`: derives normals from the height-field gradient, offsets the background texture sampling coordinates to produce refraction, then overlays a specular highlight.
   Highlight intensity scales with crest slope, so ripples stay visible over flat or dark areas (pure refraction only differs where the background has detail).

The height field is a 256×256 floating-point texture with double buffering for alternating read and write; the canvas size and background UVs are back-calculated from `background-size / position`.

**Injector** — after scanning the directory it grades files by extension: HTML-like files get the snippet inserted before `</body>`, `.js` files get the self-executing code appended, `.jsx/.tsx/.vue/.svelte` receive a comment fragment only, and `.css` is skipped. It uses ctypes to call the Win32 multi-select dialog for choosing files; a `.bak` is kept before injection, and files already containing the marker are skipped (idempotent). In addition, a page's own background image is inlined as a data URI, avoiding the `SecurityError` raised when WebGL tries to load a local image under `file://`.
