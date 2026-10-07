<div align="center">

# ⚡ Firestorm WoW Automated Account Register
### ⚡ Firestorm 魔兽世界 自动账号注册与管理工具

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/Framework-DrissionPage-FF6F00?style=for-the-badge&logo=googlechrome&logoColor=white)](https://github.com/g1879/DrissionPage)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/fun3588/Firestorm-Game-Account-Register)
[![Release](https://img.shields.io/github/v/release/fun3588/Firestorm-Game-Account-Register?style=for-the-badge&color=green)](https://github.com/fun3588/Firestorm-Game-Account-Register/releases)
[![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)](README.md)

[**中文文档**](#-中文说明) | [**English Docs**](#-english-documentation) | [**下载 Release EXE**](https://github.com/fun3588/Firestorm-Game-Account-Register/releases)

---

<p align="left">
针对 Firestorm WoW 注册页定制的自动化工具。内置 Cloudflare Turnstile 拟人化打钩校验、全域隔离 Session 清理与原生 Tkinter 图形化管理界面。
</p>

</div>

---

## 目录 / Table of Contents

- [🇨🇳 中文说明](#-中文说明)
  - [特性亮点](#-特性亮点)
  - [Cloudflare 校验机制与排查](#-cloudflare-校验机制与排查)
  - [快速上手 (GUI \& CLI)](#-快速上手-gui--cli)
  - [目录结构](#-目录结构)
  - [自检测试](#-自检测试)
- [🇺🇸 English Documentation](#-english-documentation)
  - [Features](#-features)
  - [Cloudflare Turnstile Handling](#-cloudflare-turnstile-handling)
  - [Quick Start](#-quick-start)
  - [Project Layout](#-project-layout)

---

## 🇨🇳 中文说明

### ✨ 特性亮点

| 模块 | 功能说明 | 核心技术方案 |
| :--- | :--- | :--- |
| 🛡️ **拟人反检测** | 模拟人类鼠标贝塞尔曲线轨迹平滑移动至勾选框 | CDP `Input.dispatchMouseEvent` + 悬停 1.5s 后点击 |
| 🎯 **双层定位保底** | DOM 坐标无效时自动捕获屏幕图像搜索复选框 | PIL 图像处理 + 距离权重降权算法 |
| 🧹 **定向域名清理** | 启动时仅清理 `firestorm-servers.com` 会话数据 | 保持浏览器中其他网站登录态与 Cookie 绝对不受影响 |
| 🖥️ **原生 GUI 面板** | 可视化管理面板，在线增删改配置、实时输出黑底彩色日志 | Tkinter + ttk，按键级修改保留 `config.json` 原始格式 |
| 📝 **防重账号记录** | 智能递增邮箱序号与随机生成合规用户名 | 自动去重并追加保存至 `accounts.txt` |

---

### ⚠️ Cloudflare 校验机制与排查

> [!CAUTION]
> **遇到验证码不出现时，改代码无效，必须更换网络 IP！**

| 页面现象 | 诊断结论 | 解决方案 |
| :--- | :--- | :--- |
| **容器空白 / 勾选框未出现** | Cloudflare 服务端因出口 IP 信誉偏低而**静默拒绝挑战** | 切换手机热点、更换 VPN 节点或重启路由器 |
| **勾选框出现但定位偏离** | DOM 结构微调或视口坐标偏差 | 脚本会自动降级至 CDP 模拟与 PIL 视觉截图定位 |

---

### 🚀 快速上手 (GUI & CLI)

#### 1. 图形界面方式 (推荐)
双击运行根目录下的 **`启动注册工具.cmd`**，或直接从 [Releases 页面](https://github.com/fun3588/Firestorm-Game-Account-Register/releases) 下载打包好的单独 `.exe`。

#### 2. 命令行方式
```powershell
# 1. 安装依赖
pip install DrissionPage Pillow numpy

# 2. 启动注册主流程
python register.py
```

#### 3. 配置文件 (`config.json`)
```json
{
    "email_prefix": "user",
    "email_domain": "@example.com",
    "username_prefix": "myuser",
    "username_random_len": 4,
    "password": "CHANGE_ME_PASSWORD",
    "start_index": 1,
    "headless": false,
    "keep_alive": true,
    "cf_timeout": 60
}
```

---

### 📁 目录结构

```text
E:\code\Firestorm-Game-Account-Register\
├── 启动注册工具.cmd      ← 启动图形界面
├── firestorm_gui.py       GUI 界面控制逻辑
├── register.py           注册核心脚本
├── vision_locate.py      视觉定位模块 (PIL 图像分析)
├── config_edit.py        配置文件读写与校验模块
├── _test.py              自检回归脚本
├── config.json           当前配置文件
├── config.example.json   配置模版示例
├── accounts.example.txt  账号保存格式示例
├── .gitignore            Git 忽略规则
└── README.md             中文 / 英文项目说明
```

---

### 🧪 自检测试

```powershell
python _test.py --static   # 运行静态语法与解析测试（秒级）
python _test.py            # 运行端到端模拟测试（运行至 CF 验证阶段）
```

---

## 🇺🇸 English Documentation

### ✨ Features

| Feature | Description | Implementation |
| :--- | :--- | :--- |
| 🛡️ **Stealth Anti-Detection** | Simulates realistic human mouse trajectories with hover delays | CDP `Input.dispatchMouseEvent` + 1.5s hover delay |
| 🎯 **Dual-Layer Solver** | Falls back to PIL computer vision if DOM coordinates fail | Image analysis + distance-weighted bounding box search |
| 🧹 **Isolated Domain Reset** | Clears session cookies specifically for `firestorm-servers.com` | Preserves cookies and sessions for all other websites |
| 🖥️ **Native GUI** | Full control dashboard with live streaming logs & account views | Tkinter UI with non-destructive `config.json` edit support |
| 📝 **Account Logging** | Automatically auto-increments emails and generates safe usernames | De-duplicates history and appends to `accounts.txt` |

---

### ⚠️ Cloudflare Turnstile Handling

> [!WARNING]
> **If the checkbox frame is blank, modifying code will NOT resolve it. Change your IP!**

| Symptom | Cause | Resolution |
| :--- | :--- | :--- |
| **Blank Challenge Container** | Cloudflare backend **silently blocks** challenge generation due to IP risk score | Change network / IP (mobile hotspot, proxy, or VPN) |
| **Unclickable Checkbox** | Frame offset or dynamic DOM change | Automatically solved via CDP mouse dispatch & PIL visual search |

---

### 🚀 Quick Start

#### 1. GUI Mode (Recommended)
Double-click **`启动注册工具.cmd`** or download `FirestormAccountRegister.exe` from [GitHub Releases](https://github.com/fun3588/Firestorm-Game-Account-Register/releases).

#### 2. CLI Mode
```powershell
# Install requirements
pip install DrissionPage Pillow numpy

# Run registration
python register.py
```

---

### 🧪 Testing

```powershell
python _test.py --static   # Static regression test suite
python _test.py            # End-to-end simulation up to Turnstile step
```

---

## 📜 License

Distributed under the MIT License. See `README.md` for more information.
