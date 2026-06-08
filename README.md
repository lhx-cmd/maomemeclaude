# 🎬 爆款结构迁移引擎 — 猫meme视频AI创作平台

> 从爆款拆解、素材补全到视频重组的一站式 AI 创作平台

基于**豆包 Pro**（视觉+文本）和 **Seedream**（图像生成），将爆款短视频的"结构能力"（hook、节奏、包装、叙事弧线）迁移到新主题的猫 meme 视频创作中。提供完整 Web 向导界面，从输入主题到输出 MP4 视频只需 4 步。

## ✨ 核心特性

- **🔍 爆款结构分析** — 自动提取视频的叙事模式、情绪曲线、Hook类型、节奏曲线
- **📝 三版本剧本生成** — 并发生成 高点击版 / 高共鸣版 / 高节奏版 三种风格剧本（两阶段：简略→详细）
- **🎞️ 智能分镜脚本** — 逐镜头匹配猫动作素材 + 贴纸推荐 + 字幕设计
- **🖼️ 素材缺口自动补全** — 检测5类素材缺口，调用 Seedream 自动生成
- **💬 自然语言编辑** — 用中文自然语言调整分镜（"开头更抓人""把崩溃镜头提前"）
- **🎥 FFmpeg 视频合成** — 将分镜合成为 1080×1920 竖屏 MP4（9:16，适配抖音/快手）
- **🌐 Web 向导界面** — 4步向导 + SSE 实时进度 + 内嵌视频播放器

## 🏗️ 架构

```
用户输入（主题/视频/素材）
       │
       ▼
┌─────────────────────────────────────┐
│         Flask Web 服务              │
│  (SSE 实时推送 + 会话管理)           │
└──────────┬────────────┬─────────────┘
           │            │
     ┌─────▼─────┐ ┌───▼──────────┐
     │ 豆包 Pro   │ │  Seedream    │
     │ (视觉+文本) │ │  (图像生成)   │
     └─────┬─────┘ └───┬──────────┘
           │            │
     ┌─────▼────────────▼──────────┐
     │       资产层                  │
     │  • 26个猫动作素材             │
     │  • 500+贴纸 (10类)           │
     │  • 5个预分析爆款结构          │
     │  • Seedream生成图             │
     └──────────────────────────────┘
           │
     ┌─────▼──────┐
     │   FFmpeg    │
     │  视频合成   │
     └────────────┘
```

## 📁 项目结构

```
maomemeclaude/
├── server.py                          # Flask Web 服务（API + SSE）
├── templates/
│   └── index.html                     # 单页前端 (~1100行)
├── agent/
│   ├── config.py                      # 配置加载（.env）
│   ├── doubao_client.py               # 豆包 Pro API 客户端（视觉+文本+JSON模式）
│   ├── seedream_client.py             # Seedream 图像生成接口
│   ├── video_analyzer.py              # 视频帧提取 + 豆包视觉分析
│   ├── script_generator.py            # 剧本生成器（两阶段：简略→详细，3并发）
│   ├── storyboard_generator.py        # 分镜脚本生成
│   ├── material_matcher.py            # 素材匹配（猫动作+贴纸）
│   ├── gap_detector.py                # 素材缺口识别（5类）
│   ├── editor.py                      # 自然语言编辑引擎
│   ├── video_composer.py              # FFmpeg 视频合成器
│   └── utils.py                       # 公共工具（帧提取/文件I/O）
├── assets/
│   ├── cat-motions/                   # 26个猫动作素材 (MP4)
│   ├── stickers/                      # 500+贴纸 (PNG, 10类)
│   │   ├── emotion-effects/           # 情绪效果 (27)
│   │   ├── home-daily/                # 家居日常 (61)
│   │   ├── campus-study/              # 校园学习 (22)
│   │   ├── food-drinks/               # 食物饮料 (189)
│   │   ├── digital-communication/     # 数码通讯 (50)
│   │   ├── career-identity/           # 职场身份 (83)
│   │   ├── plot-conflict/             # 剧情冲突 (14)
│   │   ├── atmosphere-decor/          # 氛围装饰 (9)
│   │   ├── medical-emergency/         # 医疗急救 (26)
│   │   └── transport-travel/          # 交通出行 (39)
│   ├── baokuan/
│   │   ├── raw/                       # 5个爆款短视频
│   │   └── structure/                 # 预分析的结构JSON
│   └── generated/                     # 生成输出（视频 + Seedream图）
└── doc/                               # 课题文档
```

## 🚀 快速开始

### 环境要求

- **Python 3.9+**
- **FFmpeg**（用于帧提取和视频合成）
  ```bash
  # macOS
  brew install ffmpeg
  
  # Ubuntu/Debian
  sudo apt install ffmpeg
  ```

### 安装

```bash
# 1. 克隆项目
git clone <repo-url> maomemeclaude
cd maomemeclaude

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置 API Key
cp .env.example .env
# 编辑 .env，填入你的 ARK API Key
```

### 配置 `.env`

```bash
ARK_API_KEY=your-api-key-here
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
ARK_MODEL=doubao-seed-2-0-pro-260215
```

> 从[火山方舟 ARK](https://console.volcengine.com/ark) 获取 API Key。

### 启动

```bash
python server.py
```

打开浏览器访问 **http://localhost:8080**，开始创作。

## 📖 使用流程

### Step 1 — 输入主题
填写视频主题描述 + 可选上传参考视频/素材

### Step 2 — 选择剧本
AI 并发生成 3 个风格的**剧情概要**（20-35秒）→ 选择后自动展开为详细逐镜头剧本

### Step 3 — 分镜预览 & 调整
- 查看逐镜头分镜（猫动作 + 贴纸 + 字幕 + 情绪）
- 素材缺口自动标记并补全
- **自然语言调整**：用中文描述想要的改动
  - "开头更抓人一些"
  - "把崩溃镜头提前"
  - "加个奶茶贴纸"
  - "节奏再快一点"

### Step 4 — 生成视频 & 输出
- 🎬 一键合成最终视频（FFmpeg）
- 内嵌播放器预览 + 下载按钮
- 输出完整分镜方案 JSON

## 🔧 技术栈

| 层级 | 技术 |
|------|------|
| **LLM** | 豆包 Pro (`doubao-seed-2-0-pro-260215`) — 视觉分析 + 文本生成 |
| **图像生成** | Seedream 4.0 — 贴纸/背景/道具补全 |
| **后端** | Flask + SSE (Server-Sent Events) |
| **前端** | 原生 JS SPA（无框架依赖） |
| **并发** | Python `ThreadPoolExecutor`（3x 剧本生成加速） |
| **视频处理** | FFmpeg — 帧提取 + 视频合成（`h264_videotoolbox`） |

## 📊 资产清单

| 资产类型 | 数量 | 说明 |
|----------|------|------|
| 爆款视频 | 5 个 | 预分析的结构 JSON（叙事模式/情绪曲线/Hook类型） |
| 猫动作素材 | 26 个 | MP4 视频，含情绪/场景/动作标签 |
| 贴纸素材 | 500+ | PNG 格式，10个分类 |
| 生成输出 | `assets/generated/` | 视频 MP4 + Seedream 图片 |

## 📝 API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 健康检查 + 已加载结构列表 |
| `/api/session` | POST | 创建新会话 |
| `/api/state` | GET | 获取会话状态 |
| `/api/analyze` | POST | 分析主题 + 匹配爆款结构 |
| `/api/generate-scripts-stream` | GET | SSE 流式生成3个简略剧本 |
| `/api/select-script` | POST | 选择剧本 → 展开详细版 → 生成分镜 |
| `/api/edit` | POST | 自然语言编辑分镜 |
| `/api/finalize` | POST | 输出最终分镜方案 |
| `/api/generate-video-stream` | GET | SSE 流式合成视频 |
| `/api/reset` | POST | 重置会话 |

## ⚠️ 注意事项

- **API Key 安全**：`.env` 文件包含 API 密钥，已在 `.gitignore` 中排除，切勿提交到 GitHub
- **FFmpeg 编码器**：macOS 使用 `h264_videotoolbox` 硬件编码器，Linux 可改为 `libx264`（需自行编译 FFmpeg）
- **中文字体**：macOS 默认使用 `STHeiti Medium.ttc`，其他系统需调整 `FONT_PATH`
- **Python 版本**：要求 Python 3.9+，使用了 `from __future__ import annotations`

## 📄 License

MIT License
