# 爆款结构迁移引擎 - 猫 Meme 视频 AI 创作平台

从爆款视频结构分析、猫 meme 剧本生成、HyperFrames 分镜编排、素材补全，到 FFmpeg 合成 16:9 横屏视频的一站式 AI 创作平台。

项目地址：[https://github.com/lhx-cmd/maomemeclaude](https://github.com/lhx-cmd/maomemeclaude)

## 核心能力

- **爆款结构迁移**：从内置或上传视频中提取 hook、节奏、包装、叙事弧线和情绪曲线。
- **三版本剧本生成**：并发生成高点击版、高共鸣版、高节奏版候选剧本，先给简略剧情概要，用户选择后再展开详细分镜。
- **LangGraph 局部编排**：主流程使用 LangGraph 做单次请求内的粗粒度编排，保留现有 Flask 内存 session，不引入持久化 checkpoint。
- **HyperFrames 画面包装**：支持顶部主题条、分镜解释字幕、猫头台词、多猫互动和底部吐槽字幕。
- **多猫角色选择**：模型根据 speaker、台词、情绪和剧情选择不同猫动作素材，避免简单复制同一只猫。
- **贴纸/道具审核**：贴纸只在剧情需要时出现，并尽量放在猫爪、桌面、通知区等合理位置。
- **素材缺口补全**：检测背景、道具、猫动作、贴纸等缺口；视频生成阶段再调用 Seedream 补齐昂贵素材。
- **生成素材沉淀复用**：Seedream 生成的背景、道具、贴纸会写入 metadata 和 `index.json`，后续可按描述复用。
- **猫 Meme 音频素材库**：猫动作视频的原声音轨会抽取到 `assets/audio/cat-motions/`，并生成带描述和标签的 `index.json`。
- **FFmpeg 视频合成**：输出 1920x1080、16:9 MP4，包含绿幕抠像、背景、猫动作、贴纸、字幕和多猫布局。
- **自然语言编辑**：支持用中文指令调整分镜，例如“开头更抓人”“把崩溃镜头提前”“加个奶茶贴纸”。

## 技术架构

```text
用户输入主题 / 参考视频 / 素材
          |
          v
Flask Web + SSE + 内存 session
          |
          v
LangGraph 单次请求编排
  |-- generate_briefs       候选剧本生成
  |-- expand_detail         详细剧本展开
  |-- build_storyboard      分镜预览、素材匹配、缺口检查
  |-- compose_video         补素材并合成视频
          |
          v
业务 Agent 模块
  |-- 豆包文本/视觉模型
  |-- Seedream 图像生成
  |-- 素材匹配和复用索引
  |-- HyperFrames 布局
  |-- FFmpeg 合成
```

## 项目结构

```text
maomemeclaude/
├── server.py                    # Flask API、SSE、会话管理
├── templates/
│   └── index.html               # 单页 Web 向导界面
├── agent/
│   ├── workflow_graph.py        # LangGraph 主流程编排层
│   ├── doubao_client.py         # 豆包文本/视觉 API 客户端
│   ├── seedream_client.py       # Seedream 图像生成客户端
│   ├── video_analyzer.py        # 爆款视频结构分析
│   ├── script_generator.py      # 简略剧本 + 详细剧本生成
│   ├── storyboard_generator.py  # 分镜生成、缺口填充、素材审核
│   ├── cat_role_planner.py      # 多猫角色动作选择
│   ├── dialogue_enricher.py     # 多猫台词和互动规划
│   ├── hyperframe_layout.py     # HyperFrames 字幕/猫位布局
│   ├── composition_planner.py   # 贴纸/道具安全位置规划
│   ├── material_matcher.py      # 猫动作和贴纸匹配
│   ├── generated_asset_library.py # 生成素材索引和复用
│   ├── gap_detector.py          # 素材缺口识别
│   ├── editor.py                # 自然语言编辑分镜
│   ├── video_composer.py        # FFmpeg 合成
│   └── utils.py                 # 文件、JSON、视频工具
├── assets/
│   ├── baokuan/                 # 参考爆款视频和结构 JSON
│   ├── audio/                   # 猫动作原声音频素材 + index.json
│   ├── cat-motions/             # 猫动作 MP4 素材
│   ├── stickers/                # 贴纸素材库
│   └── generated/
│       ├── backgrounds/         # 可复用生成背景 + index.json
│       ├── props/               # 可复用生成道具 + index.json
│       ├── output/              # 运行输出，git 忽略
│       ├── tmp/                 # 临时状态，git 忽略
│       └── uploads/             # 上传素材，git 忽略
├── tests/                       # 单元测试
├── doc/                         # 课题文档
├── requirements.txt
└── .env.example
```

## 环境要求

- Python 3.9
- FFmpeg
- 火山方舟 ARK API Key
- 推荐开通 Seedream 5 图像生成模型

安装 FFmpeg：

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg
```

## 快速开始

```bash
git clone https://github.com/lhx-cmd/maomemeclaude.git
cd maomemeclaude

python3 -m pip install -r requirements.txt
cp .env.example .env
```

编辑 `.env`：

```bash
ARK_API_KEY=your-api-key-here
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
ARK_MODEL=doubao-seed-2-0-pro-260215

# 推荐：已开通 Seedream 5 时使用
SEEDREAM_MODEL=doubao-seedream-5-0-260128

# Seedream 背景/道具补齐并发数，建议 3-5
SEEDREAM_MAX_WORKERS=5
```

启动服务：

```bash
python3 server.py
```

访问：

```text
http://localhost:8080
```

## 使用流程

1. **输入主题**
   填写要迁移的主题，可上传参考视频或补充素材。

2. **生成并选择候选剧本**
   系统并发生成 3 个简略剧本。选择一个后，系统展开详细剧本并生成分镜预览。

3. **检查和调整分镜**
   查看猫动作、背景、台词、贴纸、缺口报告和素材匹配结果。可以用自然语言继续调整。

4. **生成视频**
   生成阶段会补齐必要背景/道具，复用已有素材库，最后合成 16:9 MP4。

## 输出规格

- 分辨率：1920x1080
- 画幅：16:9 横屏
- 编码：MP4 / H.264
- 默认输出目录：`assets/generated/output/`
- 分镜 JSON：可通过 `/api/finalize` 输出

## 资产和复用机制

内置资产：

| 类型 | 说明 |
| --- | --- |
| 爆款结构 | 内置 5 个参考视频及结构分析 JSON |
| 猫动作素材 | 26 个 MP4，带动作、情绪、场景标签 |
| 猫原声音频 | 从猫动作 MP4 抽取的 M4A，带源视频、描述、标签索引 |
| 贴纸素材 | 多分类 PNG/JPG 素材库 |
| 生成背景 | `assets/generated/backgrounds/index.json` 汇总描述 |
| 生成道具 | `assets/generated/props/index.json` 汇总描述 |

复用策略：

- 背景统一生成 16:9，Seedream size 为 `2560x1440`。
- 道具/贴纸生成透明或近透明方图，Seedream size 为 `1920x1920`。
- 每个生成素材会保存 `.meta.json`，并刷新对应 `index.json`。
- 猫动作原声音频可用以下命令重建：
  ```bash
  python3 scripts/rebuild_audio_assets.py --force
  ```
- 后续生成时优先按描述匹配已有素材，减少重复调用 Seedream。

## API 概览

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/health` | GET | 健康检查 |
| `/api/session` | POST | 创建会话 |
| `/api/state` | GET | 查询会话状态 |
| `/api/analyze` | POST | 主题分析和爆款结构匹配 |
| `/api/generate-scripts-stream` | GET | SSE 生成候选简略剧本 |
| `/api/select-script` | POST | 选择剧本，展开详细剧本并生成分镜 |
| `/api/edit` | POST | 自然语言编辑分镜 |
| `/api/finalize` | POST | 导出最终分镜方案 |
| `/api/generate-video-stream` | GET | SSE 合成视频 |
| `/api/reset` | POST | 重置会话 |

## 测试

```bash
python3 -m unittest discover -v
python3 -m py_compile server.py agent/*.py
```

当前测试覆盖重点：

- LangGraph 主流程节点
- 候选剧本顺序和错误占位
- 多猫角色动作去重
- HyperFrames 字幕和多猫布局
- 贴纸/道具位置规划
- Seedream 素材复用和并发
- FFmpeg filter graph 和失败日志
- SSE terminal event 不丢失

## 开发说明

- 不存会话数据库，当前会话只保存在 Flask 进程内存中。
- LangGraph 只负责单次请求内的流程编排，不使用 checkpoint。
- Python 3.9 环境下固定使用 `langgraph>=0.6,<1.0`。
- `.env`、上传文件、临时状态、最终视频输出均已加入 `.gitignore`。
- 公开仓库不包含真实 API Key。

## 常见问题

### 生成分镜较慢怎么办？

选剧本后的 Step 2 主要包含两个模型调用：详细剧本展开和分镜 AI 编排。当前已做轻量上下文、候选动作池压缩、重复选择缓存，并把 Seedream 补图延后到视频生成阶段。服务日志会打印 LangGraph 节点耗时，便于定位慢点。

### 为什么有些背景/道具在分镜预览里还没有图？

为了加快预览，分镜阶段只做现有素材匹配和缺口检查。真正昂贵的 Seedream 背景/道具生成会在“生成视频”阶段执行。

### 为什么不是每个分镜都有多只猫？

系统会在朋友、同事、领导、老师、客户、家人、群消息、争辩、回应等关系场景中优先规划多猫互动。独白、强反应、崩溃、转场镜头会保留单猫，避免强行凑多猫。

## License

MIT License
