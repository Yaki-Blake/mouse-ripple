#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
鼠标涟漪注入器 / Mouse Ripple Injector
====================================

用途
----
把本文件放到任意前端项目目录里，运行后：
  1. 自动扫描该目录（默认只扫当前层，加 -r 递归），把"能注入的前端文件"列成清单；
  2. 弹出 Windows 原生多选对话框，由你点选要处理的文件后按"确定"；
  3. 对选中的文件注入鼠标涟漪效果（WebGL 高度场 + 法线折射）。

注入策略（按格式分级，避免破坏源码）
------------------------------------
  HTML 类  .html .htm .h5 .shtml .xhtml .php .phtml .jsp .asp .aspx .ejs .hbs .twig .njk .erb .tpl
           在 </body> 前插入 <script>（引擎 + 初始化），无 </body> 则退到 </html>，再退到文件末尾。
  JS       .js        在文件末尾追加引擎 + 自执行初始化代码。
  组件     .jsx .tsx .ts   只追加注释形式的接入片段，标记"需手动接线"，不改行为。
  单文件组件 .vue .svelte  在 <script> 内追加注释形式的接入片段；无 <script> 块则跳过并提示。
  样式     .css .scss .sass .less .styl   不处理——CSS 无法承载指针驱动的涟漪，注入只会产生语法垃圾。

背景图
------
  注入时会在页面自带的 CSS（内联 <style>、style 属性、或同目录的 .css 文件）里找出背景图，
  取其中最大的那张（≤2 MB）内联为 data URI 一起写入。原因：用 file:// 双击打开时，浏览器会把
  本地图片视为跨域资源，WebGL 取纹理抛 SecurityError，表现就是"注了代码却没效果"。
  内联用的仍是该页原本那张图，不是外部塞进来的图；`--no-inline-bg` 可关闭该行为。

安全
----
  * 幂等：文件里已含 "mouse-ripple:injected" 标记则跳过，绝不重复叠加。
  * 备份：首次修改前生成同名 .bak；若 .bak 已存在则退化为 .bak.<时间戳>，不覆盖旧备份。
  * 只改文本，不删除任何原有内容，移除时删掉 <!-- mouse-ripple:injected ... --> 到 <!-- /mouse-ripple --> 之间即可。

用法
----
  python ripple-inject.py              # 扫描本文件所在目录
  python ripple-inject.py -r           # 递归扫描子目录
  python ripple-inject.py D:\\site -r   # 指定目录并递归
  python ripple-inject.py --no-inline-bg   # 关闭背景图内联（页面背景图较大或由 JS 动态设置时用）
"""

from __future__ import annotations

import os
import re
import sys
import time
import shutil
import base64
import unicodedata

VERSION = "v1"
MARKER = "mouse-ripple:injected"
ENGINE_SIGNATURE = "window.Ripples = Ripples"      # 引擎已存在
BOOT_SIGNATURE = "__MOUSE_RIPPLE_BOOTED__"        # 初始化已存在

# ---------------------------------------------------------------------------
# 引擎：WebGL 涟漪模拟（由 src/ripple-engine.js 内联，勿手改）
# ---------------------------------------------------------------------------
ENGINE_JS = r'''//**
 * ripple-engine.js —— 鼠标涟漪引擎（WebGL 波浪模拟）
 * 唯一真源：index.html 与 ripple-inject.py 都由本文件内联生成。
 *
 * 基于 jQuery Ripples v0.0.1 / https://github.com/sirxemic/jquery.ripples
 * MIT License, @author sirxemic / https://sirxemic.com/
 *
 * 与原库的差异（均为必要修复，行为不变）：
 *   1. 彻底移除 jQuery 依赖，改为原生 DOM（append / remove / style 操作）。
 *   2. translateBackgroundPosition 在 "center center" 这类双值写法下会 parseFloat('center') => NaN，已修正。
 *   3. computeTextureBoundaries 的 elementOffset 补上 width/height，否则 bottomRight 恒为 NaN 导致全黑。
 *   4. hideCssBackground / show / hide 中原 this.element[0]、canvas.show() 的 jQuery 写法已替换。
 *   5. computeTextureBoundaries 改读 getComputedStyle；原实现只读内联样式，背景写在 CSS 文件里时
 *      backgroundSize 为空串 => parseFloat('') => NaN => 整屏透明。这是"注入了却没效果"的头号原因。
 *   6. 画布尺寸改为逐帧同步（原库仅监听 resize），避免首帧测量早于布局稳定时画布小于视口、边缘留白。
 *
 * 核心机制（理解后便于调参）：
 *   dropProgram    —— 鼠标落点处写入一个余弦形波峰（振幅 = strength，半径 = radius）
 *   updateProgram  —— 每帧四点均值做离散波动方程积分，info.g 阻尼 0.985，info.r 累加得高度场
 *   renderProgram  —— 用高度场的梯度求法线，做法线扰动采样背景纹理，再叠一层高光
 *   关键参数：resolution 256（模拟网格）、dropRadius 20（波半径）、perturbance 0.03（折射强度）
 */
/**
 * jQuery Ripples plugin v0.0.1 / https://github.com/sirxemic/jquery.ripples
 * MIT License
 * @author sirxemic / https://sirxemic.com/
 */

(function (global, factory) {
	typeof exports === 'object' && typeof module !== 'undefined' ? factory() :
	typeof define === 'function' && define.amd ? define(factory) :
	(factory());
}(this, (function () { 'use strict';

var gl;

function isPercentage(str) {
	return str[str.length - 1] == '%';
}

/**
 *  Load a configuration of GL settings which the browser supports.
 *  For example:
 *  - not all browsers support WebGL
 *  - not all browsers support floating point textures
 *  - not all browsers support linear filtering for floating point textures
 *  - not all browsers support rendering to floating point textures
 *  - some browsers *do* support rendering to half-floating point textures instead.
 */
function loadConfig() {
	var canvas = document.createElement('canvas');
	gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');

	if (!gl) {
		// Browser does not support WebGL.
		return null;
	}

	// Load extensions
	var extensions = {};
	[
		'OES_texture_float',
		'OES_texture_half_float',
		'OES_texture_float_linear',
		'OES_texture_half_float_linear'
	].forEach(function(name) {
		var extension = gl.getExtension(name);
		if (extension) {
			extensions[name] = extension;
		}
	});

	// If no floating point extensions are supported we can bail out early.
	if (!extensions.OES_texture_float) {
		return null;
	}

	var configs = [];

	function createConfig(type, glType, arrayType) {
		var name = 'OES_texture_' + type,
				nameLinear = name + '_linear',
				linearSupport = nameLinear in extensions,
				configExtensions = [name];

		if (linearSupport) {
			configExtensions.push(nameLinear);
		}

		return {
			type: glType,
			arrayType: arrayType,
			linearSupport: linearSupport,
			extensions: configExtensions
		};
	}

	configs.push(
		createConfig('float', gl.FLOAT, Float32Array)
	);

	if (extensions.OES_texture_half_float) {
		configs.push(
			// Array type should be Uint16Array, but at least on iOS that breaks. In that case we
			// just initialize the textures with data=null, instead of data=new Uint16Array(...).
			// This makes initialization a tad slower, but it's still negligible.
			createConfig('half_float', extensions.OES_texture_half_float.HALF_FLOAT_OES, null)
		);
	}

	// Setup the texture and framebuffer
	var texture = gl.createTexture();
	var framebuffer = gl.createFramebuffer();

	gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
	gl.bindTexture(gl.TEXTURE_2D, texture);
	gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
	gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
	gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
	gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

	// Check for each supported texture type if rendering to it is supported
	var config = null;

	for (var i = 0; i < configs.length; i++) {
		gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 32, 32, 0, gl.RGBA, configs[i].type, null);

		gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0);
		if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE) {
			config = configs[i];
			break;
		}
	}

	return config;
}

function createImageData(width, height) {
	try {
		return new ImageData(width, height);
	}
	catch (e) {
		// Fallback for IE
		var canvas = document.createElement('canvas');
		return canvas.getContext('2d').createImageData(width, height);
	}
}

function translateBackgroundPosition(value) {
	var parts = value.split(' ');

	if (parts.length === 1) {
		switch (value) {
			case 'center':
				return ['50%', '50%'];
			case 'top':
				return ['50%', '0'];
			case 'bottom':
				return ['50%', '100%'];
			case 'left':
				return ['0', '50%'];
			case 'right':
				return ['100%', '50%'];
			default:
				return [value, '50%'];
		}
	}
	else {
		return parts.map(function(part) {
			// 原库这里写的是 switch (value)，导致 'center center' 这类写法无法转成百分比，
			// 后续 parseFloat('center') 得到 NaN。已改为 switch (part)。
			switch (part) {
				case 'center':
					return '50%';
				case 'top':
				case 'left':
					return '0';
				case 'right':
				case 'bottom':
					return '100%';
				default:
					return part;
			}
		});
	}
}

function createProgram(vertexSource, fragmentSource, uniformValues) {
	function compileSource(type, source) {
		var shader = gl.createShader(type);
		gl.shaderSource(shader, source);
		gl.compileShader(shader);
		if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
			throw new Error('compile error: ' + gl.getShaderInfoLog(shader));
		}
		return shader;
	}

	var program = {};

	program.id = gl.createProgram();
	gl.attachShader(program.id, compileSource(gl.VERTEX_SHADER, vertexSource));
	gl.attachShader(program.id, compileSource(gl.FRAGMENT_SHADER, fragmentSource));
	gl.linkProgram(program.id);
	if (!gl.getProgramParameter(program.id, gl.LINK_STATUS)) {
		throw new Error('link error: ' + gl.getProgramInfoLog(program.id));
	}

	// Fetch the uniform and attribute locations
	program.uniforms = {};
	program.locations = {};
	gl.useProgram(program.id);
	gl.enableVertexAttribArray(0);
	var match, name, regex = /uniform (\w+) (\w+)/g, shaderCode = vertexSource + fragmentSource;
	while ((match = regex.exec(shaderCode)) != null) {
		name = match[2];
		program.locations[name] = gl.getUniformLocation(program.id, name);
	}

	return program;
}

function bindTexture(texture, unit) {
	gl.activeTexture(gl.TEXTURE0 + (unit || 0));
	gl.bindTexture(gl.TEXTURE_2D, texture);
}

function extractUrl(value) {
	var urlMatch = /url\(["']?([^"']*)["']?\)/.exec(value);
	if (urlMatch == null) {
		return null;
	}

	return urlMatch[1];
}

function isDataUri(url) {
	return url.match(/^data:/);
}

var config = loadConfig();
var transparentPixels = createImageData(32, 32);

// Extend the css
var style = document.createElement('style');
style.innerHTML = ".webgl-ripples { position: relative; z-index: 0; }";
document.querySelector('head').append(style);

// RIPPLES CLASS DEFINITION
// =========================

var Ripples = function (el, options) {
	var that = this;

	this.element = typeof el == "string" ? document.querySelector(el) : el;

	// Init properties from options
	this.interactive = options.interactive;
	this.resolution = options.resolution;
	this.textureDelta = new Float32Array([1 / this.resolution, 1 / this.resolution]);

	this.perturbance = options.perturbance;
	this.dropRadius = options.dropRadius;

	this.crossOrigin = options.crossOrigin;
	this.imageUrl = options.imageUrl;

	// Init WebGL canvas
	var canvas = document.createElement('canvas');

    var rect = this.element.getBoundingClientRect();

	canvas.width = rect.width;
	canvas.height = rect.height;
	this.canvas = canvas;

	this.canvas.setAttribute("style", "position: absolute; top: 0; left: 0; right: 0; bottom: 0; z-index: -1;");

	this.element.classList.add("webgl-ripples");
	this.element.append(this.canvas);

	this.context = gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');

	// 没有 WebGL 时原实现会在下面的 gl.getExtension 处抛 TypeError，整段脚本静默失败，
	// 页面只剩一张静态背景 —— 看起来就是「涟漪坏了」。这里显式报错并留下标记，
	// 页面可用 html[data-ripples="unsupported"] 展示提示。
	if (!gl) {
		console.error('[ripples] 无法创建 WebGL 上下文：浏览器未启用硬件加速，或被显卡黑名单/企业策略禁用，涟漪无法渲染。');
		document.documentElement.setAttribute('data-ripples', 'unsupported');
		return;
	}

	// Load extensions
	config.extensions.forEach(function(name) {
		gl.getExtension(name);
	});

	// Auto-resize when window size changes.
	this.updateSize = this.updateSize.bind(this);
	window.addEventListener('resize', this.updateSize);

	// Init rendertargets for ripple data.
	this.textures = [];
	this.framebuffers = [];
	this.bufferWriteIndex = 0;
	this.bufferReadIndex = 1;

	var arrayType = config.arrayType;
	var textureData = arrayType ? new arrayType(this.resolution * this.resolution * 4) : null;

	for (var i = 0; i < 2; i++) {
		var texture = gl.createTexture();
		var framebuffer = gl.createFramebuffer();

		gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);

		gl.bindTexture(gl.TEXTURE_2D, texture);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, config.linearSupport ? gl.LINEAR : gl.NEAREST);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, config.linearSupport ? gl.LINEAR : gl.NEAREST);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
		gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, this.resolution, this.resolution, 0, gl.RGBA, config.type, textureData);

		gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0);

		this.textures.push(texture);
		this.framebuffers.push(framebuffer);
	}

	// Init GL stuff
	this.quad = gl.createBuffer();
	gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
	gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
		-1, -1,
		+1, -1,
		+1, +1,
		-1, +1
	]), gl.STATIC_DRAW);

	this.initShaders();
	this.initTexture();
	this.setTransparentTexture();

	// Load the image either from the options or CSS rules
	this.loadImage();

	// Set correct clear color and blend mode (regular alpha blending)
	gl.clearColor(0, 0, 0, 0);
	gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

	// Plugin is successfully initialized!
	this.visible = true;
	this.running = true;
	this.inited = true;
	this.destroyed = false;

	this.setupPointerEvents();

	// Init animation
	function step() {
		if (!that.destroyed) {
			that.step();

			requestAnimationFrame(step);
		}
	}

	requestAnimationFrame(step);
};

Ripples.DEFAULTS = {
	imageUrl: null,
	resolution: 256,
	dropRadius: 20,
	perturbance: 0.03,
	interactive: true,
	crossOrigin: ''
};

Ripples.prototype = {

	// Set up pointer (mouse + touch) events
	setupPointerEvents: function() {
		var that = this;

		function pointerEventsEnabled() {
			return that.visible && that.running && that.interactive;
		}

		function dropAtPointer(pointer, big) {
			if (pointerEventsEnabled()) {
				that.dropAtPointer(
					pointer,
					that.dropRadius * (big ? 1.5 : 1),
					(big ? 0.14 : 0.01)
				);
			}
		}

		// Start listening to pointer events
		this.element

			// Create regular, small ripples for mouse move and touch events...
			.addEventListener('mousemove', function(e) {
				dropAtPointer(e);
			});

		this.element
			.addEventListener('touchmove', function(e) {
				var touches = e.changedTouches;
				for (var i = 0; i < touches.length; i++) {
					dropAtPointer(touches[i]);
				}
			});

		this.element
			.addEventListener('touchstart', function(e) {
				var touches = e.changedTouches;
				for (var i = 0; i < touches.length; i++) {
					dropAtPointer(touches[i], true);
				}
			});

			// ...and only a big ripple on mouse down events.
			this.element
				.addEventListener('mousedown', function(e) {
				dropAtPointer(e, true);
			});
	},

	// Load the image either from the options or the element's CSS rules.
	loadImage: function() {
		var that = this;

		gl = this.context;

		var newImageSource = this.imageUrl ||
			extractUrl(this.originalCssBackgroundImage) ||
			extractUrl(this.element.style.backgroundImage);

		// If image source is unchanged, don't reload it.
		if (newImageSource == this.imageSource) {
			return;
		}

		this.imageSource = newImageSource;

		// Falsy source means no background.
		if (!this.imageSource) {
			this.setTransparentTexture();
			return;
		}

		// Load the texture from a new image.
		var image = new Image;
		image.onload = function() {
			gl = that.context;

			// Only textures with dimensions of powers of two can have repeat wrapping.
			function isPowerOfTwo(x) {
				return (x & (x - 1)) == 0;
			}

			var wrapping = (isPowerOfTwo(image.width) && isPowerOfTwo(image.height)) ? gl.REPEAT : gl.CLAMP_TO_EDGE;

			gl.bindTexture(gl.TEXTURE_2D, that.backgroundTexture);
			gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, wrapping);
			gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, wrapping);
			gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);

			that.backgroundWidth = image.width;
			that.backgroundHeight = image.height;

			// Hide the background that we're replacing.
			that.hideCssBackground();
		};

		// Fall back to a transparent texture when loading the image failed.
		image.onerror = function() {
			gl = that.context;

			that.setTransparentTexture();
		};

		// Disable CORS when the image source is a data URI.
		image.crossOrigin = isDataUri(this.imageSource) ? null : this.crossOrigin;

		image.src = this.imageSource;
	},

	step: function() {
		gl = this.context;

		if (!this.visible) {
			return;
		}

		// 逐帧同步画布尺寸。原库只在 window.resize 时同步，若首次测量早于布局稳定
		// （字体/图片加载引发回流、浏览器恢复窗口尺寸、无头截图等），画布会小于视口，
		// 表现为画面边缘留白、涟漪只覆盖一部分。改为逐帧比对，代价仅一次 rect 读取。
		this.updateSize();

		this.computeTextureBoundaries();

		if (this.running) {
			this.update();
		}

		this.render();
	},

	drawQuad: function() {
		gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
		gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
		gl.drawArrays(gl.TRIANGLE_FAN, 0, 4);
	},

	render: function() {
		gl.bindFramebuffer(gl.FRAMEBUFFER, null);

		gl.viewport(0, 0, this.canvas.width, this.canvas.height);

		gl.enable(gl.BLEND);
		gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

		gl.useProgram(this.renderProgram.id);

		bindTexture(this.backgroundTexture, 0);
		bindTexture(this.textures[0], 1);

		gl.uniform1f(this.renderProgram.locations.perturbance, this.perturbance);
		gl.uniform2fv(this.renderProgram.locations.topLeft, this.renderProgram.uniforms.topLeft);
		gl.uniform2fv(this.renderProgram.locations.bottomRight, this.renderProgram.uniforms.bottomRight);
		gl.uniform2fv(this.renderProgram.locations.containerRatio, this.renderProgram.uniforms.containerRatio);
		gl.uniform1i(this.renderProgram.locations.samplerBackground, 0);
		gl.uniform1i(this.renderProgram.locations.samplerRipples, 1);

		this.drawQuad();
		gl.disable(gl.BLEND);
	},

	update: function() {
		gl.viewport(0, 0, this.resolution, this.resolution);

		gl.bindFramebuffer(gl.FRAMEBUFFER, this.framebuffers[this.bufferWriteIndex]);
		bindTexture(this.textures[this.bufferReadIndex]);
		gl.useProgram(this.updateProgram.id);

		this.drawQuad();

		this.swapBufferIndices();
	},

	swapBufferIndices: function() {
		this.bufferWriteIndex = 1 - this.bufferWriteIndex;
		this.bufferReadIndex = 1 - this.bufferReadIndex;
	},

	computeTextureBoundaries: function() {
		// 原库只读内联样式（element.style.*）。当背景写在 <style> 或外链 CSS 里时这里取到空串，
		// 走到下面 else 分支执行 parseFloat('') => NaN，uniform 变 NaN 后渲染结果全透明（看起来像"没效果"）。
		// 改为读取计算样式，并只取多重背景中的第一层。
		var computed = window.getComputedStyle(this.element);
		var backgroundSize = (computed.backgroundSize || '').split(',')[0].trim();
		var backgroundAttachment = (computed.backgroundAttachment || '').split(',')[0].trim();
		var backgroundPosition = translateBackgroundPosition((computed.backgroundPosition || '50% 50%').split(',')[0].trim());

		if (!backgroundSize) {
			backgroundSize = 'auto auto';
		}

		// Here the 'container' is the element which the background adapts to
		// (either the chrome window or some element, depending on attachment)
		var container;
		if (backgroundAttachment == 'fixed') {
			container = { left: window.pageXOffset, top: window.pageYOffset };
			container.width = window.innerWidth;
			container.height = window.innerHeight;
		}
		else {
			var rect = this.element.getBoundingClientRect();
			container = {left: rect.left + window.scrollX, top: rect.top + window.scrollY};
			container.width = rect.width;
			container.height = rect.height;
		}

		// TODO: background-clip
		if (backgroundSize == 'cover') {
			var scale = Math.max(container.width / this.backgroundWidth, container.height / this.backgroundHeight);

			var backgroundWidth = this.backgroundWidth * scale;
			var backgroundHeight = this.backgroundHeight * scale;
		}
		else if (backgroundSize == 'contain') {
			var scale = Math.min(container.width / this.backgroundWidth, container.height / this.backgroundHeight);

			var backgroundWidth = this.backgroundWidth * scale;
			var backgroundHeight = this.backgroundHeight * scale;
		}
		else {
			backgroundSize = backgroundSize.split(' ');
			var backgroundWidth = backgroundSize[0] || '';
			var backgroundHeight = backgroundSize[1] || backgroundWidth;

			if (isPercentage(backgroundWidth)) {
				backgroundWidth = container.width * parseFloat(backgroundWidth) / 100;
			}
			else if (backgroundWidth != 'auto') {
				backgroundWidth = parseFloat(backgroundWidth);
			}

			if (isPercentage(backgroundHeight)) {
				backgroundHeight = container.height * parseFloat(backgroundHeight) / 100;
			}
			else if (backgroundHeight != 'auto') {
				backgroundHeight = parseFloat(backgroundHeight);
			}

			if (backgroundWidth == 'auto' && backgroundHeight == 'auto') {
				backgroundWidth = this.backgroundWidth;
				backgroundHeight = this.backgroundHeight;
			}
			else {
				if (backgroundWidth == 'auto') {
					backgroundWidth = this.backgroundWidth * (backgroundHeight / this.backgroundHeight);
				}

				if (backgroundHeight == 'auto') {
					backgroundHeight = this.backgroundHeight * (backgroundWidth / this.backgroundWidth);
				}
			}
		}

		// Compute backgroundX and backgroundY in page coordinates
		var backgroundX = backgroundPosition[0];
		var backgroundY = backgroundPosition[1];

		if (isPercentage(backgroundX)) {
			backgroundX = container.left + (container.width - backgroundWidth) * parseFloat(backgroundX) / 100;
		}
		else {
			backgroundX = container.left + parseFloat(backgroundX);
		}

		if (isPercentage(backgroundY)) {
			backgroundY = container.top + (container.height - backgroundHeight) * parseFloat(backgroundY) / 100;
		}
		else {
			backgroundY = container.top + parseFloat(backgroundY);
		}

		var elementOffset = (() => {
			var rect = this.element.getBoundingClientRect();

 			return {
                top: rect.top + window.scrollY,
                left: rect.left + window.scrollX,
                // 原库漏了这两个字段，下面算 bottomRight 时 undefined/数字 = NaN，导致画面全黑/不显示。
                width: rect.width,
                height: rect.height,
            };
		})();

		this.renderProgram.uniforms.topLeft = new Float32Array([
			(elementOffset.left - backgroundX) / backgroundWidth,
			(elementOffset.top - backgroundY) / backgroundHeight
		]);
		this.renderProgram.uniforms.bottomRight = new Float32Array([
			this.renderProgram.uniforms.topLeft[0] + elementOffset.width / backgroundWidth,
			this.renderProgram.uniforms.topLeft[1] + elementOffset.height / backgroundHeight
		]);

		var maxSide = Math.max(this.canvas.width, this.canvas.height);

		this.renderProgram.uniforms.containerRatio = new Float32Array([
			this.canvas.width / maxSide,
			this.canvas.height / maxSide
		]);
	},

	initShaders: function() {
		var vertexShader = [
			'attribute vec2 vertex;',
			'varying vec2 coord;',
			'void main() {',
				'coord = vertex * 0.5 + 0.5;',
				'gl_Position = vec4(vertex, 0.0, 1.0);',
			'}'
		].join('\n');

		this.dropProgram = createProgram(vertexShader, [
			'precision highp float;',

			'const float PI = 3.141592653589793;',
			'uniform sampler2D texture;',
			'uniform vec2 center;',
			'uniform float radius;',
			'uniform float strength;',

			'varying vec2 coord;',

			'void main() {',
				'vec4 info = texture2D(texture, coord);',

				'float drop = max(0.0, 1.0 - length(center * 0.5 + 0.5 - coord) / radius);',
				'drop = 0.5 - cos(drop * PI) * 0.5;',

				'info.r += drop * strength;',

				'gl_FragColor = info;',
			'}'
		].join('\n'));

		this.updateProgram = createProgram(vertexShader, [
			'precision highp float;',

			'uniform sampler2D texture;',
			'uniform vec2 delta;',

			'varying vec2 coord;',

			'void main() {',
				'vec4 info = texture2D(texture, coord);',

				'vec2 dx = vec2(delta.x, 0.0);',
				'vec2 dy = vec2(0.0, delta.y);',

				'float average = (',
					'texture2D(texture, coord - dx).r +',
					'texture2D(texture, coord - dy).r +',
					'texture2D(texture, coord + dx).r +',
					'texture2D(texture, coord + dy).r',
				') * 0.25;',

				'info.g += (average - info.r) * 2.0;',
				'info.g *= 0.985;',
				'info.r += info.g;',

				'gl_FragColor = info;',
			'}'
		].join('\n'));
		gl.uniform2fv(this.updateProgram.locations.delta, this.textureDelta);

		this.renderProgram = createProgram([
			'precision highp float;',

			'attribute vec2 vertex;',
			'uniform vec2 topLeft;',
			'uniform vec2 bottomRight;',
			'uniform vec2 containerRatio;',
			'varying vec2 ripplesCoord;',
			'varying vec2 backgroundCoord;',
			'void main() {',
				'backgroundCoord = mix(topLeft, bottomRight, vertex * 0.5 + 0.5);',
				'backgroundCoord.y = 1.0 - backgroundCoord.y;',
				'ripplesCoord = vec2(vertex.x, -vertex.y) * containerRatio * 0.5 + 0.5;',
				'gl_Position = vec4(vertex.x, -vertex.y, 0.0, 1.0);',
			'}'
		].join('\n'), [
			'precision highp float;',

			'uniform sampler2D samplerBackground;',
			'uniform sampler2D samplerRipples;',
			'uniform vec2 delta;',

			'uniform float perturbance;',
			'varying vec2 ripplesCoord;',
			'varying vec2 backgroundCoord;',

			'void main() {',
				'float height = texture2D(samplerRipples, ripplesCoord).r;',
				'float heightX = texture2D(samplerRipples, vec2(ripplesCoord.x + delta.x, ripplesCoord.y)).r;',
				'float heightY = texture2D(samplerRipples, vec2(ripplesCoord.x, ripplesCoord.y + delta.y)).r;',
				'float gx = heightX - height;',
				'float gy = heightY - height;',
				'vec3 dx = vec3(delta.x, gx, 0.0);',
				'vec3 dy = vec3(0.0, gy, delta.y);',
				'vec2 offset = -normalize(cross(dy, dx)).xz;',
				'float specular = pow(max(0.0, dot(offset, normalize(vec2(-0.6, 1.0)))), 4.0);',

				// 坡度 = 相邻纹理格的高度差，归一化到「每格」后与分辨率无关。
				// 纯折射（原实现）只在背景存在高频细节处产生可见差异：位移方向被 normalize
				// 成单位向量、幅度恒为 perturbance，落在纯色/深色区域时像素差为 0，
				// 表现为「点了没反应」。这里补一层随坡度增强的镜面提亮，让波峰在纯色区域也可见。
				'float slope = length(vec2(gx, gy)) / delta.x;',
				'float crest = 1.0 - exp(-slope * 0.28);',

				'vec3 color = texture2D(samplerBackground, backgroundCoord + offset * perturbance).rgb;',
				'color += specular * (0.30 + 0.70 * crest) + vec3(0.40, 0.55, 0.70) * crest * 0.55;',
				'gl_FragColor = vec4(color, 1.0);',
			'}'
		].join('\n'));
		gl.uniform2fv(this.renderProgram.locations.delta, this.textureDelta);
	},

	initTexture: function() {
		this.backgroundTexture = gl.createTexture();
		gl.bindTexture(gl.TEXTURE_2D, this.backgroundTexture);
		gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, 1);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
	},

	setTransparentTexture: function() {
		gl.bindTexture(gl.TEXTURE_2D, this.backgroundTexture);
		gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, transparentPixels);
	},

	hideCssBackground: function() {

		// Check whether we're changing inline CSS or overriding a global CSS rule.
		// 原库写作 this.element[0]（jQuery 集合），原生 DOM 下为 undefined 会抛错，已修正。
		var inlineCss = this.element.style.backgroundImage;

		if (inlineCss == 'none') {
			return;
		}

		this.originalInlineCss = inlineCss;

		this.originalCssBackgroundImage = this.element.style.backgroundImage;
		this.element.style.backgroundImage = 'none';
	},

	restoreCssBackground: function() {

		// Restore background by either changing the inline CSS rule to what it was, or
		// simply remove the inline CSS rule if it never was inlined.
		this.element.style.backgroundImage = this.originalInlineCss || '';
	},

	dropAtPointer: function(pointer, radius, strength) {
		var borderLeft = parseInt(this.element.style.borderLeftWidth) || 0,
				borderTop = parseInt(this.element.style.borderTopWidth) || 0;

		var elementOffset = (() => {
			var rect = this.element.getBoundingClientRect();

 			return {
                top: rect.top + window.scrollY,
                left: rect.left + window.scrollX,
            };
		})();

		this.drop(
			pointer.pageX - elementOffset.left - borderLeft,
			pointer.pageY - elementOffset.top - borderTop,
			radius,
			strength
		);
	},

	/**
	 *  Public methods
	 */
	drop: function(x, y, radius, strength) {
		gl = this.context;

		var rect = this.element.getBoundingClientRect();

		var elWidth = rect.width;
		var elHeight = rect.height;
		var longestSide = Math.max(elWidth, elHeight);

		radius = radius / longestSide;

		var dropPosition = new Float32Array([
			(2 * x - elWidth) / longestSide,
			(elHeight - 2 * y) / longestSide
		]);

		gl.viewport(0, 0, this.resolution, this.resolution);

		gl.bindFramebuffer(gl.FRAMEBUFFER, this.framebuffers[this.bufferWriteIndex]);
		bindTexture(this.textures[this.bufferReadIndex]);

		gl.useProgram(this.dropProgram.id);
		gl.uniform2fv(this.dropProgram.locations.center, dropPosition);
		gl.uniform1f(this.dropProgram.locations.radius, radius);
		gl.uniform1f(this.dropProgram.locations.strength, strength);

		this.drawQuad();

		this.swapBufferIndices();
	},

	updateSize: function() {

		var rect = this.element.getBoundingClientRect();

		var newWidth = rect.width,
				newHeight = rect.height;

		if (newWidth != this.canvas.width || newHeight != this.canvas.height) {
			this.canvas.width = newWidth;
			this.canvas.height = newHeight;
		}
	},

	destroy: function() {

		// TODO: use more effecient method to remove event listeners (with `removeEventListener`)
		// remove event listeners:
		var old_element = this.element;
		var new_element = old_element.cloneNode(true);
		old_element.parentNode.replaceChild(new_element, old_element);

		new_element.remove();

		this.canvas.remove();

		this.restoreCssBackground();

		this.destroyed = true;
	},

	show: function() {
		this.visible = true;

		// 原库调用 this.canvas.show()（jQuery），原生 DOM 下不存在，已改为标准样式操作。
		this.canvas.style.display = '';
		this.hideCssBackground();
	},

	hide: function() {
		this.visible = false;

		this.canvas.style.display = 'none';
		this.restoreCssBackground();
	},

	pause: function() {
		this.running = false;
	},

	play: function() {
		this.running = true;
	},

	set: function(property, value) {
		switch (property) {
			case 'dropRadius':
			case 'perturbance':
			case 'interactive':
			case 'crossOrigin':
				this[property] = value;
				break;
			case 'imageUrl':
				this.imageUrl = value;
				this.loadImage();
				break;
		}
	}
};

window.Ripples = Ripples;

})));
'''

# ---------------------------------------------------------------------------
# 初始化片段：全屏作用于 body，背景沿用目标页自身的背景图；没有则按用户要求不加背景
# ---------------------------------------------------------------------------
INIT_JS = r'''/* mouse-ripple:init —— 全屏 body + 沿用页面自身背景图 */
(function () {
  'use strict';

  if (window.__MOUSE_RIPPLE_BOOTED__) { return; }
  window.__MOUSE_RIPPLE_BOOTED__ = true;

  var OPTS = {
    resolution: 256,   /* 波动模拟网格边长，越大越细腻越吃 GPU */
    dropRadius: 20,    /* 单次涟漪半径 px；按下时按 1.5 倍放大 */
    perturbance: 0.03  /* 折射强度，即波峰波谷的视觉明显程度 */
  };

  function firstLayer(value) {
    return (value || '').split(',')[0].trim();
  }

  function urlOf(value) {
    var m = /url\(\s*["']?([^"')]+)["']?\s*\)/.exec(value || '');
    return m ? m[1] : null;
  }

  /* 取页面自身的背景图：优先 body，其次 html；都没有就返回 null（不强行加图） */
  function pickBackground() {
    var body = document.body;
    if (!body) { return null; }
    var bcs = window.getComputedStyle(body);
    var src = urlOf(bcs.backgroundImage);
    if (src) { return { src: src, cs: bcs }; }
    var hcs = window.getComputedStyle(document.documentElement);
    src = urlOf(hcs.backgroundImage);
    if (src) { return { src: src, cs: hcs }; }
    return null;
  }

  function boot() {
    var body = document.body;
    if (!body) { return; }
    if (typeof window.Ripples !== 'function') {
      console.warn('[mouse-ripple] 引擎未就绪，已跳过');
      return;
    }

    /* body 不足一屏时补足高度，否则页面下半屏无法触发涟漪 */
    if (body.getBoundingClientRect().height < window.innerHeight) {
      body.style.minHeight = '100vh';
    }

    var bg = pickBackground();

    /* 注入器若在构建期把该页自己的背景图内联成 data URI，优先用它：
       file:// 打开时浏览器把本地图片当跨域资源，WebGL 取图会抛 SecurityError，
       表现为"代码注入了但一点效果都没有"。data URI 与页面同源，不受此限。 */
    var forced = window.__MOUSE_RIPPLE_BG__ || null;
    if (forced) {
      bg = bg ? { src: forced, cs: bg.cs } : { src: forced, cs: window.getComputedStyle(body) };
    }

    if (bg) {
      /* 把背景几何参数固化到内联样式：引擎按 background-size / position 反算纹理 UV，
         若背景来自外链 CSS 而这里不固化，引擎拿不到尺寸就会算出 NaN 并整屏透明 */
      body.style.backgroundImage = 'url("' + bg.src + '")';
      body.style.backgroundSize = firstLayer(bg.cs.backgroundSize) || 'cover';
      body.style.backgroundPosition = firstLayer(bg.cs.backgroundPosition) || '50% 50%';
      body.style.backgroundRepeat = firstLayer(bg.cs.backgroundRepeat) || 'no-repeat';
    }

    try {
      window.__MOUSE_RIPPLE__ = new window.Ripples(body, {
        imageUrl: bg ? bg.src : null,
        resolution: OPTS.resolution,
        dropRadius: OPTS.dropRadius,
        perturbance: OPTS.perturbance,
        interactive: true,
        crossOrigin: ''
      });
    } catch (err) {
      console.warn('[mouse-ripple] 初始化失败：' + err.message);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();'''

# ---------------------------------------------------------------------------
# 文件格式分组
# ---------------------------------------------------------------------------
HTML_EXTS = {
    '.html', '.htm', '.h5', '.shtml', '.xhtml', '.php', '.phtml', '.jsp',
    '.asp', '.aspx', '.ejs', '.hbs', '.handlebars', '.twig', '.njk', '.erb', '.tpl',
}
JS_EXTS = {'.js'}
MANUAL_EXTS = {'.jsx', '.tsx', '.ts'}
SFC_EXTS = {'.vue', '.svelte'}
STYLE_EXTS = {'.css', '.scss', '.sass', '.less', '.styl'}

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.avif'}
MIME_TYPES = {
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
    '.gif': 'image/gif', '.webp': 'image/webp', '.bmp': 'image/bmp', '.avif': 'image/avif',
}
MAX_INLINE_BG = 2 * 1024 * 1024

ALL_EXTS = sorted(HTML_EXTS | JS_EXTS | MANUAL_EXTS | SFC_EXTS | STYLE_EXTS)

STATUS_INJECTED = "已注入"
STATUS_READY = "可注入"
STATUS_MANUAL = "需手动接线"
STATUS_SKIP = "不处理"


# ---------------------------------------------------------------------------
# 文本读写：保留原编码与换行风格
# ---------------------------------------------------------------------------
def read_text(path):
    """返回 (text, encoding, newline)。无法判定编码时抛 UnicodeDecodeError。"""
    with open(path, 'rb') as f:
        raw = f.read()
    if raw.startswith(b'\xef\xbb\xbf'):
        return raw[3:].decode('utf-8'), 'utf-8-sig', detect_newline(raw)
    for enc in ('utf-8', 'gb18030'):
        try:
            return raw.decode(enc), enc, detect_newline(raw)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError('unknown', b'', 0, 1, '既不是 UTF-8 也不是 GB18030')


def detect_newline(raw):
    return '\r\n' if b'\r\n' in raw else '\n'


def write_text(path, text, encoding):
    with open(path, 'w', encoding=encoding, newline='') as f:
        f.write(text)


def backup(path):
    """首次备份为 .bak；已存在则用时间戳，绝不覆盖旧备份。返回备份路径。"""
    target = path + '.bak'
    if os.path.exists(target):
        target = path + '.bak.' + time.strftime('%Y%m%d-%H%M%S')
    shutil.copy2(path, target)
    return target


# ---------------------------------------------------------------------------
# 注入片段
# ---------------------------------------------------------------------------
def html_block(nl, bg_uri=None):
    bg_script = ''
    if bg_uri:
        bg_script = (
            '<script>' + nl
            + '/* mouse-ripple:bg —— 该页原有背景图内联为 data URI，保证 file:// 下 WebGL 可取纹理 */' + nl
            + 'window.__MOUSE_RIPPLE_BG__ = "' + bg_uri + '";' + nl
            + '</script>' + nl
        )
    return (
        nl
        + '<!-- ' + MARKER + ' ' + VERSION + ' | 由 ripple-inject.py 自动插入，删除到 /mouse-ripple 为止即可移除 -->' + nl
        + bg_script
        + '<script>' + nl + ENGINE_JS + nl + '</script>' + nl
        + '<script>' + nl + INIT_JS + nl + '</script>' + nl
        + '<!-- /mouse-ripple -->' + nl
    )


def js_block(nl):
    return (
        nl + nl
        + '/* === ' + MARKER + ' ' + VERSION + ' | 由 ripple-inject.py 自动插入，删除本段到 /mouse-ripple 为止即可移除 === */' + nl
        + ENGINE_JS + nl
        + INIT_JS + nl
        + '/* === /mouse-ripple === */' + nl
    )


def manual_comment(nl):
    body = [
        '/* === ' + MARKER + ' ' + VERSION + ' · 仅注释，未生效，需手动接线 ===',
        '',
        '   1) 引入引擎：把 index.html 里的 <script>（window.Ripples = Ripples 之前的部分）',
        '      存成 ripple-engine.js 并 import，或在入口 HTML 里以 <script> 引入。',
        '   2) 组件挂载后调用（element 需有尺寸，且背景图来自自身或其祖先）：',
        '',
        '      new Ripples(document.body, {',
        '        imageUrl: null,        // 传背景图 URL；null 表示用元素自身的 CSS 背景',
        '        resolution: 256,',
        '        dropRadius: 20,',
        '        perturbance: 0.03,',
        '        interactive: true,',
        '        crossOrigin: \'\'',
        '      });',
        '',
        '      Vue  : onMounted(() => { ... });',
        '      React: useEffect(() => { ... }, []);',
        '      Svelte: onMount(() => { ... });',
        '',
        '   3) 卸载时调用实例的 destroy()，避免重复绑定与显存泄漏。',
        '',
        '=== /mouse-ripple === */',
    ]
    return nl + nl + nl.join(body) + nl


def sfc_comment_inside_script(nl):
    lines = manual_comment(nl).strip('\n').split('\n')
    return '\n' + '\n'.join('  ' + ln if ln.strip() else ln for ln in lines) + '\n'


# ---------------------------------------------------------------------------
# 背景图内联：只为解决 file:// 下 WebGL 无法取用本地图片的问题，用的仍是该页原本那张图
# ---------------------------------------------------------------------------
URL_RE = re.compile(r'url\(\s*["\']?([^"\')]+)["\']?\s*\)', re.I)
LINK_RE = re.compile(r'<link\b[^>]*>', re.I)
HREF_RE = re.compile(r'href\s*=\s*["\']([^"\']+)["\']', re.I)


def _add_candidate(candidates, url, base):
    url = (url or '').strip()
    if not url or url.startswith(('data:', 'http:', 'https:', '//', '#', 'blob:')):
        return
    clean = url.split('#')[0].split('?')[0].strip().replace('\\', '/')
    if os.path.splitext(clean)[1].lower() not in IMAGE_EXTS:
        return
    path = clean if os.path.isabs(clean) else os.path.normpath(os.path.join(base, clean))
    if not os.path.isfile(path):
        return
    try:
        size = os.path.getsize(path)
    except OSError:
        return
    if 0 < size <= MAX_INLINE_BG:
        candidates[path] = size


def find_local_background(html_path, text):
    """在页面自身的内联样式 / style 属性 / 同目录 CSS 里找背景图，取最大的那张内联。
    返回 (data_uri, 文件名, 字节数) 或 None。"""
    base = os.path.dirname(html_path)
    candidates = {}

    for m in URL_RE.finditer(text):
        _add_candidate(candidates, m.group(1), base)

    for tag in LINK_RE.finditer(text):
        chunk = tag.group(0)
        if 'stylesheet' not in chunk.lower():
            continue
        href = HREF_RE.search(chunk)
        if not href:
            continue
        css_url = href.group(1).strip()
        if css_url.startswith(('http:', 'https:', '//', 'data:')):
            continue
        css_path = os.path.normpath(os.path.join(base, css_url.split('?')[0].replace('\\', '/')))
        if not os.path.isfile(css_path):
            continue
        try:
            css_text = read_text(css_path)[0]
        except (UnicodeDecodeError, OSError):
            continue
        for m in URL_RE.finditer(css_text):
            _add_candidate(candidates, m.group(1), os.path.dirname(css_path))

    if not candidates:
        return None

    path, size = max(candidates.items(), key=lambda kv: kv[1])
    try:
        with open(path, 'rb') as f:
            raw = f.read()
    except OSError:
        return None
    mime = MIME_TYPES.get(os.path.splitext(path)[1].lower(), 'application/octet-stream')
    uri = 'data:' + mime + ';base64,' + base64.b64encode(raw).decode('ascii')
    return uri, os.path.basename(path), len(raw)


# ---------------------------------------------------------------------------
# 分类
# ---------------------------------------------------------------------------
def classify(path):
    """返回 (状态, 处理方式)。处理方式 ∈ html / js / manual / sfc / skip。"""
    ext = os.path.splitext(path)[1].lower()
    try:
        text, _, _ = read_text(path)
    except (UnicodeDecodeError, OSError):
        return "无法读取", 'skip'
    # 幂等判定：本项目注入过的（带标记），或任何已自带本引擎的文件（如 index.html），都不再重复注入
    if MARKER in text or ENGINE_SIGNATURE in text or BOOT_SIGNATURE in text:
        return STATUS_INJECTED, 'skip'
    if ext in HTML_EXTS:
        return STATUS_READY, 'html'
    if ext in JS_EXTS:
        return STATUS_READY, 'js'
    if ext in MANUAL_EXTS:
        return STATUS_MANUAL, 'manual'
    if ext in SFC_EXTS:
        return STATUS_MANUAL, 'sfc'
    if ext in STYLE_EXTS:
        return STATUS_SKIP, 'skip'
    return STATUS_SKIP, 'skip'


def scan(root, recursive):
    found = []
    exts = set(ALL_EXTS)
    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(('.', 'node_modules', '_ripple_backup'))]
            for name in sorted(filenames):
                if os.path.splitext(name)[1].lower() in exts:
                    found.append(os.path.join(dirpath, name))
    else:
        for name in sorted(os.listdir(root)):
            p = os.path.join(root, name)
            if os.path.isfile(p) and os.path.splitext(name)[1].lower() in exts:
                found.append(p)
    return found


# ---------------------------------------------------------------------------
# Windows 原生多选对话框
# ---------------------------------------------------------------------------
try:
    import ctypes
    from ctypes import wintypes

    class OPENFILENAMEW(ctypes.Structure):
        """与 Win32 OPENFILENAMEW 结构体逐字段对应，x64 下 sizeof 必须为 152。"""
        _fields_ = [
            ("lStructSize", wintypes.DWORD),
            ("hwndOwner", wintypes.HWND),
            ("hInstance", wintypes.HINSTANCE),
            ("lpstrFilter", wintypes.LPCWSTR),
            ("lpstrCustomFilter", wintypes.LPWSTR),
            ("nMaxCustFilter", wintypes.DWORD),
            ("nFilterIndex", wintypes.DWORD),
            ("lpstrFile", wintypes.LPWSTR),
            ("nMaxFile", wintypes.DWORD),
            ("lpstrFileTitle", wintypes.LPWSTR),
            ("nMaxFileTitle", wintypes.DWORD),
            ("lpstrInitialDir", wintypes.LPCWSTR),
            ("lpstrTitle", wintypes.LPCWSTR),
            ("Flags", wintypes.DWORD),
            ("nFileOffset", wintypes.WORD),
            ("nFileExtension", wintypes.WORD),
            ("lpstrDefExt", wintypes.LPCWSTR),
            ("lCustData", wintypes.LPARAM),
            ("lpfnHook", wintypes.LPVOID),
            ("lpTemplateName", wintypes.LPCWSTR),
            ("pvReserved", wintypes.LPVOID),
            ("dwReserved", wintypes.DWORD),
            ("flagsEx", wintypes.DWORD),
        ]
except ImportError:      # 非 Windows 平台：退回控制台编号选择
    ctypes = None

OFN_HIDEREADONLY = 0x00000004
OFN_NOCHANGEDIR = 0x00000008
OFN_ALLOWMULTISELECT = 0x00000200
OFN_PATHMUSTEXIST = 0x00000800
OFN_FILEMUSTEXIST = 0x00001000
OFN_EXPLORER = 0x00080000
OFN_DONTADDTORECENT = 0x02000000


def pick_files_windows(initial_dir):
    patterns = ';'.join('*' + e for e in ALL_EXTS)
    # 双 \0 结束的过滤器串
    filter_str = (
        '可注入的前端文件 (' + patterns + ')\0' + patterns + '\0'
        '网页文件 (*.html;*.htm;*.h5)\0*.html;*.htm;*.h5\0'
        '样式与脚本 (*.css;*.js;*.vue;*.tsx;*.jsx;*.svelte)\0*.css;*.js;*.vue;*.tsx;*.jsx;*.svelte\0'
        '所有文件 (*.*)\0*.*\0\0'
    )

    buf_size = 1024 * 64
    buf = ctypes.create_unicode_buffer(buf_size)

    ofn = OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
    ofn.hwndOwner = None
    ofn.lpstrFilter = filter_str
    ofn.nFilterIndex = 1
    ofn.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
    ofn.nMaxFile = buf_size
    ofn.lpstrInitialDir = initial_dir
    ofn.lpstrTitle = '选择要注入鼠标涟漪的文件（按住 Ctrl / Shift 可多选）'
    ofn.lpstrDefExt = 'html'
    ofn.Flags = (
        OFN_ALLOWMULTISELECT | OFN_EXPLORER | OFN_FILEMUSTEXIST
        | OFN_PATHMUSTEXIST | OFN_HIDEREADONLY | OFN_NOCHANGEDIR | OFN_DONTADDTORECENT
    )

    # 关闭对话框前把当前工作目录切到目标目录，避免部分系统版本默认落在家目录
    cwd = os.getcwd()
    try:
        os.chdir(initial_dir)
    except OSError:
        pass
    try:
        ok = ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(ofn))
    finally:
        os.chdir(cwd)

    if not ok:
        return []

    raw = ''.join(buf[:])
    return parse_multiselect(raw)


def parse_multiselect(raw):
    """解析 GetOpenFileNameW 的多选返回串。
    单文件：'C:\\a\\b.html'；多文件：'C:\\a\\0b.html\\0c.html\\0\\0'（目录 + 文件名列表）。"""
    parts = [p for p in raw.split('\x00') if p]
    if not parts:
        return []
    if len(parts) == 1:
        return [parts[0]]
    folder = parts[0]
    return [os.path.join(folder, name) for name in parts[1:]]


def pick_files_console(root):
    exts = set(ALL_EXTS)
    names = [n for n in sorted(os.listdir(root))
             if os.path.isfile(os.path.join(root, n)) and os.path.splitext(n)[1].lower() in exts]
    if not names:
        print('目录里没有可处理的候选文件。')
        return []
    for i, n in enumerate(names, 1):
        print('  %2d) %s' % (i, n))
    print()
    print(' 输入编号（逗号分隔，例如 1,3）后回车；直接回车取消：')
    line = input(' > ').strip()
    if not line:
        return []
    picked = []
    for token in line.replace('，', ',').split(','):
        token = token.strip()
        if token.isdigit() and 1 <= int(token) <= len(names):
            picked.append(os.path.join(root, names[int(token) - 1]))
    return picked


# ---------------------------------------------------------------------------
# 注入动作
# ---------------------------------------------------------------------------
def inject_html(text, nl, bg_uri=None):
    lowered = text.lower()
    idx = lowered.rfind('</body>')
    if idx != -1:
        return text[:idx] + html_block(nl, bg_uri) + text[idx:], '插在 </body> 前'
    idx = lowered.rfind('</html>')
    if idx != -1:
        return text[:idx] + html_block(nl, bg_uri) + text[idx:], '插在 </html> 前'
    return text + html_block(nl, bg_uri), '追加到文件末尾（未找到 </body>）'


def inject_sfc(text, nl):
    lowered = text.lower()
    idx = lowered.rfind('</script>')
    if idx == -1:
        return None, '没有 <script> 块，已跳过'
    return text[:idx] + sfc_comment_inside_script(nl) + text[idx:], '注释片段写入 <script> 末尾'


def process(path, mode, inline_bg=True):
    text, encoding, nl = read_text(path)
    bg_note = ''

    if mode == 'manual':
        new_text, note = text + manual_comment(nl), '追加注释片段（需手动接线）'
    elif mode == 'sfc':
        new_text, note = inject_sfc(text, nl)
        if new_text is None:
            return False, note, None, ''
    elif mode == 'js':
        new_text, note = text + js_block(nl), '追加引擎与自执行初始化'
    elif mode == 'html':
        bg_uri = None
        if inline_bg:
            found = find_local_background(path, text)
            if found:
                bg_uri, bg_name, bg_size = found
                bg_note = '内联背景图 %s（%s）' % (bg_name, human(bg_size))
            else:
                bg_note = '未找到本地背景图，改用页面运行时背景（无则不加背景）'
        new_text, note = inject_html(text, nl, bg_uri)
    else:
        return False, '不支持的类型', None, ''

    bak = backup(path)
    write_text(path, new_text, encoding)
    return True, note, bak, bg_note


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def human(size):
    for unit in ('B', 'KB', 'MB'):
        if size < 1024 or unit == 'MB':
            return ('%.0f %s' % (size, unit)) if unit == 'B' else ('%.1f %s' % (size, unit))
        size /= 1024.0
    return str(size)


def pad(text, width):
    """按终端显示宽度补空格：中文/全角字符占 2 列。"""
    used = 0
    for ch in text:
        used += 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
    return text + ' ' * max(0, width - used)


def main(argv):
    root = os.path.dirname(os.path.abspath(__file__))
    recursive = False
    inline_bg = True
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg in ('-r', '--recursive'):
            recursive = True
        elif arg == '--no-inline-bg':
            inline_bg = False
        elif arg in ('-h', '--help'):
            print(__doc__)
            return 0
        elif os.path.isdir(arg):
            root = os.path.abspath(arg)
        else:
            print('忽略无法识别的参数：%s' % arg)
        i += 1

    print('=' * 68)
    print(' 鼠标涟漪注入器 %s' % VERSION)
    print('=' * 68)
    print('扫描目录：%s' % root)
    print('扫描范围：%s' % ('递归子目录' if recursive else '仅当前目录（加 -r 递归）'))
    print()

    files = scan(root, recursive)
    if not files:
        print('没有发现候选文件。支持的格式：%s' % ' '.join(ALL_EXTS))
        return 1

    rows = []
    for p in files:
        status, mode = classify(p)
        rows.append((os.path.relpath(p, root), status, mode, os.path.getsize(p)))

    width = max(len(r[0]) for r in rows)
    print('  ' + pad('#', 5) + pad('状态', 14) + pad('大小', 10) + '文件')
    print('  ' + '-' * (width + 32))
    for idx, (rel, status, mode, size) in enumerate(rows, 1):
        print('  ' + pad(str(idx), 5) + pad(status, 14) + pad(human(size), 10) + rel)
    print()

    ready = [r for r in rows if r[1] == STATUS_READY]
    print('可注入 %d 个 · 已注入 %d 个 · 需手动接线 %d 个 · 不处理 %d 个' % (
        len(ready),
        sum(1 for r in rows if r[1] == STATUS_INJECTED),
        sum(1 for r in rows if r[1] == STATUS_MANUAL),
        sum(1 for r in rows if r[1] in (STATUS_SKIP, "无法读取")),
    ))
    print()

    if os.name == 'nt':
        print('即将弹出文件选择框：点选目标文件后按"确定"开始注入（取消则退出）。')
        picked = pick_files_windows(root)
    else:
        picked = pick_files_console(root)

    if not picked:
        print('未选择任何文件，已退出，未做任何修改。')
        return 0

    print()
    print('已选 %d 个文件，开始处理：' % len(picked))
    print('-' * 68)

    ok_count = 0
    for path in picked:
        if not os.path.isfile(path):
            print('  [跳过] 文件不存在：%s' % path)
            continue
        status, mode = classify(path)
        rel = os.path.relpath(path, root)
        if status == STATUS_INJECTED:
            print('  [跳过] %s —— 已注入过，避免重复叠加' % rel)
            continue
        if mode == 'skip':
            print('  [跳过] %s —— %s' % (rel, status if status != STATUS_SKIP else '该格式无法承载涟漪效果'))
            continue
        try:
            done, note, bak, bg_note = process(path, mode, inline_bg)
        except UnicodeDecodeError:
            print('  [失败] %s —— 编码无法识别（既非 UTF-8 也非 GB18030）' % rel)
            continue
        except OSError as err:
            print('  [失败] %s —— %s' % (rel, err))
            continue
        if done:
            ok_count += 1
            print('  [完成] %s —— %s' % (rel, note))
            if bg_note:
                print('         %s' % bg_note)
            print('         备份：%s' % os.path.basename(bak))
        else:
            print('  [跳过] %s —— %s' % (rel, note))

    print('-' * 68)
    print('处理结束：成功 %d 个，失败/跳过 %d 个。' % (ok_count, len(picked) - ok_count))
    print('提示：注入后直接双击用浏览器打开即可看到效果；如需撤除，删掉文件里的 mouse-ripple 注释段，或还原 .bak。')
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    code = main(sys.argv)
    if sys.stdin is not None and sys.stdin.isatty():
        try:
            input('\n按回车键关闭窗口...')
        except (EOFError, KeyboardInterrupt):
            pass
    sys.exit(code)
