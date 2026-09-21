# 资源来源

本工程复用本仓库 `client/res/live2d/models/luo`、`client/res/live2d/backgrounds/bg2.jpg`、`client/res/gui/tianyi_icon.png`、`user_icon.png` 及 `client/config/live2d_interface_config.json`，基线 `79ae2c0`，不修改旧端资源。

应用图标复用 `client/res/gui/icon.svg` 与 `icon.ico`，对应Godot的`assets/ui/app_icon.svg`和`app_icon.ico`，内容保持逐字节一致。

`assets/ui/login_portrait.png`由同一Live2D模型在normal表情、双眼睁开、视线居中状态下离线渲染生成（800×800透明画面，截取(90,20)至(710,640)，缩至384×384）；仅作为登录静态头像，不改变模型许可。SHA-256：`37479b0a0af896a435596ab15e3db8d0f4d64ebe4a772ac4e5d9d23d67f23ef1`。

模型来源及用途说明见仓库 `client/README.md`「关于 AI 生成内容的声明」第 3 项：火爆鸡王发布的洛天依 Live2D 模型，非商业用途免费使用。背景及 Logo 沿用原项目声明，不因程序使用 MIT 许可证而改变素材的使用条件。

gd_cubism 为非官方插件，版本 v0.9.1，源码 https://github.com/MizunagiKB/gd_cubism ，commit `60e9c61ed20d08ec19b2cb80fb492ce6344927c6`。本地编译的 Windows x64 release 动态库用于编辑器和导出包。

附带 Cubism SDK、Core、NOTICE、gd_cubism 及 godot-cpp 的原始许可说明；分发时保留这些文件。
