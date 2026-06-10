# LangGraph Cat Meme Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于现有猫 meme 视频生成项目，重构一个以 LangGraph 为主编排层的新项目，解决上传素材优先、自然语言分镜修改、音视频分离管理和背景缺失识别问题。

**Architecture:** 新项目将参考视频分析、用户素材分析、剧本生成、分镜生成、素材匹配、自然语言分镜修改、HyperFrames 布局和 FFmpeg 合成拆成明确的 LangGraph 节点。素材优先级不只依赖 prompt，而是写入 `ProjectState`、候选池排序、匹配 Agent 和校验 Agent。

**Tech Stack:** Python、FastAPI 或 Flask、LangGraph、Pydantic、FFmpeg、HyperFrames、豆包文本/视觉模型、Seedream 图像生成、本地 JSON 素材索引。

---

## 1. 当前问题

现有项目的问题不是单个素材匹配函数，而是流程决策权分散：

- 上传爆款视频后，参考结构和本地爆款结构的选择逻辑不够清晰。
- 上传素材只在后置分镜匹配阶段被尽量使用，没有真正驱动剧本生成。
- 分镜 Agent 即使看到用户素材，也可能仍然固定选择同一只本地猫动作。
- 自然语言修改分镜偏工具函数式，缺少专门 Agent 做理解、改写、重匹配和校验。
- 视频、音频、背景图、贴纸、道具的资产边界不够清楚，容易互相抢职责。

---

## 2. 新项目核心原则

1. **上传爆款视频优先**
   有用户上传爆款视频时，只分析用户上传的视频，不再匹配本地爆款结构。

2. **上传素材驱动创作**
   有用户上传猫 meme 素材时，先分析成和 `assets/cat-motions/descriptions.json` 单条记录同构的结构，再让剧本 Agent 和分镜 Agent 优先围绕这些素材创作。

3. **本地素材只做补充**
   用户素材不足、不匹配或被明确判定不适合时，才使用本地素材库。

4. **自然语言修改走专门 Agent**
   用户输入修改指令后，进入独立 `Storyboard Edit Graph`，完成意图理解、目标分镜定位、智能改写、素材重匹配、结果校验。

5. **音视频背景分离**
   猫动作视频、音频、背景图、贴纸、道具分别建索引、分别匹配，最终只在 `render_plan` 和 FFmpeg 合成阶段汇合。

6. **HyperFrames 负责画面包装**
   顶部主题条、分镜说明、猫头台词、多猫布局、底部字幕、贴纸安全区由 HyperFrames 渲染规划层统一处理。

7. **FFmpeg 负责最终合成**
   FFmpeg 只消费确认后的 `render_plan`，负责背景、猫动作、贴纸、字幕、音频混流和 MP4 输出。
8. **要将贴纸、道具的匹配与后续的分镜包装中，贴纸和道具的部分做成可禁用的，因为这部分功能不太好做，不确定能不能做好**

---

## 3. 推荐目录结构

```text
maomeme2.0/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── sessions.py
│   │   ├── analyze.py
│   │   ├── scripts.py
│   │   ├── storyboard.py
│   │   ├── edits.py
│   │   └── render.py
│   ├── graph/
│   │   ├── state.py
│   │   ├── main_graph.py
│   │   ├── edit_graph.py
│   │   └── policies.py
│   ├── agents/
│   │   ├── reference_analyzer.py
│   │   ├── user_asset_analyzer.py
│   │   ├── script_agent.py
│   │   ├── storyboard_agent.py
│   │   ├── storyboard_edit_agent.py
│   │   ├── cat_video_match_agent.py
│   │   ├── background_match_agent.py
│   │   ├── prop_sticker_match_agent.py
│   │   ├── audio_match_agent.py
│   │   └── validation_agent.py
│   ├── assets/
│   │   ├── schemas.py
│   │   ├── catalog.py
│   │   ├── local_library.py
│   │   └── user_library.py
│   ├── hyperframes/
│   │   ├── layout_agent.py
│   │   ├── safe_zones.py
│   │   └── render_plan.py
│   ├── render/
│   │   ├── composer.py
│   │   ├── audio_mixer.py
│   │   └── ffmpeg_utils.py
│   └── clients/
│       ├── llm_client.py
│       ├── vision_client.py
│       └── image_client.py
├── assets/
│   ├── baokuan/
│   ├── cat-motions/
│   ├── audio/
│   ├── stickers/
│   └── generated/
├── tests/
└── docs/
```

---

## 4. 核心状态设计

```python
class ProjectState(TypedDict, total=False):
    session_id: str
    theme: str

    uploaded_reference_video: str | None
    uploaded_materials: list[str]

    reference_source: Literal["uploaded", "local"]
    reference_structure: dict
    source_policy: dict

    user_cat_video_assets: list[dict]
    user_audio_assets: list[dict]
    user_background_assets: list[dict]
    user_prop_assets: list[dict]

    local_cat_video_assets: list[dict]
    local_audio_assets: list[dict]
    local_background_assets: list[dict]
    local_sticker_assets: list[dict]
    generated_background_assets: list[dict]
    generated_prop_assets: list[dict]

    script_candidates: list[dict]
    selected_script: dict
    storyboard: dict

    edit_instruction: str
    edit_plan: dict
    edit_history: list[dict]

    render_plan: dict
    output_video_path: str
    errors: list[dict]
```

`source_policy` 是整个系统的硬约束：

```json
{
  "reference_priority": "uploaded_only_if_present",
  "asset_priority": ["user", "local", "generated"],
  "require_user_asset_first": true,
  "allow_local_fallback": true,
  "video_audio_background_separated": true
}
```

---

## 5. 主 LangGraph 流程

```text
start
  -> ingest_inputs
  -> decide_reference_source
  -> analyze_uploaded_reference OR select_local_reference
  -> analyze_user_assets
  -> load_local_assets
  -> build_asset_catalogs
  -> generate_script_candidates
  -> await_user_script_selection
  -> expand_selected_script
  -> generate_storyboard
  -> match_cat_video_assets
  -> match_background_assets
  -> match_prop_and_sticker_assets
  -> match_audio_assets
  -> validate_storyboard_policy
  -> build_hyperframes_render_plan
  -> await_user_edit_or_render
  -> compose_final_video_with_ffmpeg
  -> end
```

条件规则：

- 有上传爆款视频：走 `analyze_uploaded_reference`。
- 无上传爆款视频：走 `select_local_reference`。
- 有上传素材：`source_policy.require_user_asset_first = true`。
- 无上传素材：只加载本地素材。
- 用户输入自然语言修改：进入 `Storyboard Edit Graph`。
- 用户确认生成：进入 `compose_final_video_with_ffmpeg`。

---

## 6. 用户素材分析 Agent

`User Asset Analyzer` 负责分析用户上传的所有素材。

### 6.1 猫动作视频分析

用户上传猫 meme 视频后，视觉分析结果必须和 `assets/cat-motions/descriptions.json` 单条记录同构：

```json
{
  "asset_id": "user_motion_001",
  "asset_type": "cat_video",
  "source": "user",
  "priority": 0,
  "file_path": "assets/generated/uploads/xxx.mp4",
  "description": "猫站立挥爪，表情急切，适合求饶、解释、撒娇场景",
  "motion_tags": {
    "actions": ["站立", "挥爪", "摇晃"],
    "emotions": ["着急", "委屈", "撒娇"],
    "contexts": ["求原谅", "解释", "迟到"],
    "avoid": ["严肃威胁", "安静睡觉"]
  },
  "search_keywords": ["求饶", "撒娇", "解释", "迟到"]
}
```

### 6.2 音频抽取和分析

如果用户上传视频包含音轨，系统必须抽取音频，单独生成音频资产：

```json
{
  "asset_id": "user_audio_001",
  "asset_type": "audio",
  "source": "user",
  "priority": 0,
  "file_path": "assets/generated/audio/user_audio_001.m4a",
  "description": "高频猫叫和环境杂音，适合慌张、求救、混乱场景",
  "audio_tags": {
    "moods": ["慌张", "吵闹"],
    "use_cases": ["崩溃", "求救", "混乱"],
    "avoid": ["温情结尾", "安静独白"]
  }
}
```

### 6.3 背景图片分析

用户上传图片如果被识别为背景，进入 `user_background_assets`：

```json
{
  "asset_id": "user_bg_001",
  "asset_type": "background",
  "source": "user",
  "priority": 0,
  "file_path": "assets/generated/uploads/office.png",
  "description": "办公室工位背景，有电脑桌、椅子和白墙，适合加班、开会、摸鱼场景",
  "background_tags": {
    "locations": ["办公室", "工位"],
    "moods": ["压抑", "日常"],
    "use_cases": ["加班", "开会", "上班摸鱼"],
    "avoid": ["户外赶路", "校园课堂"]
  }
}
```

---

## 7. 剧本生成 Agent

`Script Agent` 生成候选剧本时必须接收：

- 用户主题
- 爆款参考结构
- `source_policy`
- 用户猫动作视频摘要
- 用户音频摘要
- 用户背景/道具摘要
- 本地补充素材摘要

有用户素材时，候选剧本必须围绕用户素材可表达的动作、情绪、场景设计。

候选剧本增加 `asset_strategy`：

```json
{
  "title": "迟到求生指南",
  "asset_strategy": {
    "user_assets_used": ["user_motion_001", "user_bg_001"],
    "local_assets_needed": ["local_motion_12"],
    "fallback_reason": "用户素材缺少明显崩溃大哭动作"
  }
}
```

验收要求：

- 有用户素材时，至少一个候选剧本必须明确使用用户素材。
- 如果候选剧本完全不使用用户素材，必须给出可解释原因，并由校验 Agent 判断是否接受。

---

## 8. 分镜生成 Agent

`Storyboard Agent` 根据选定剧本生成 6-8 个分镜。

每个分镜必须输出分层资产需求，不直接把所有素材混在一起：

```json
{
  "scene_id": 1,
  "description": "猫站着挥爪解释迟到原因",
  "dialogues": [
    {"speaker": "我", "line": "我真的已经出门了！"}
  ],
  "asset_requirements": {
    "cat_video": {
      "preferred_source": "user",
      "actions": ["挥爪", "解释"],
      "emotions": ["着急", "心虚"]
    },
    "background": {
      "preferred_source": "user",
      "description": "城市街道路口，适合迟到赶路场景"
    },
    "audio": {
      "preferred_source": "user",
      "moods": ["慌张"],
      "allow_silence": true
    },
    "stickers": [],
    "props": []
  }
}
```

---

## 9. 猫动作视频匹配 Agent

`Cat Video Match Agent` 只负责猫动作视频，不负责背景图和音频。

匹配顺序：

1. 用户猫动作视频精确匹配
2. 用户猫动作视频语义近似匹配
3. 本地猫动作视频精确匹配
4. 本地猫动作视频语义近似匹配
5. 标记猫动作缺口

禁止行为：

- 同一镜头多个角色复用同一个单猫素材。
- 有合适用户素材时跳到本地素材。
- 把用户上传视频无差别地固定套用到所有分镜。

输出示例：

```json
{
  "scene_id": 1,
  "cat_video_match": {
    "asset_id": "user_motion_001",
    "source": "user",
    "score": 91,
    "reason": "动作包含挥爪，情绪包含着急，符合迟到解释场景"
  }
}
```

---

## 10. 背景资产匹配 Agent

`Background Match Agent` 单独负责背景图匹配和背景缺失识别。

匹配顺序：

1. 用户背景图片精确匹配
2. 用户背景图片语义近似匹配
3. 已生成背景复用
4. 本地背景素材匹配
5. 标记背景缺口并交给图像生成 Agent

输出示例：

```json
{
  "scene_id": 1,
  "background_match": {
    "asset_id": null,
    "source": null,
    "missing": true,
    "description": "城市街道路口，适合迟到赶路场景",
    "gap_reason": "用户素材和本地背景库都没有匹配的城市道路背景"
  }
}
```

规则：

- 背景图不由猫动作视频匹配 Agent 管理。
- 背景缺失必须进入缺口报告。
- 背景缺失可以由 Seedream 或其他图像生成能力补齐。

---

## 11. 贴纸和道具匹配 Agent

`Prop Sticker Match Agent` 负责贴纸和道具。

匹配原则：

- 贴纸和道具必须服务剧情，不做纯装饰堆叠。
- 手机、电脑、试卷、奶茶、消息气泡等必须与台词或剧情直接相关。
- 道具和贴纸位置要交给 HyperFrames 安全区规则二次校验。

输出示例：

```json
{
  "scene_id": 2,
  "prop_matches": [
    {
      "asset_id": "local_prop_milk_tea_001",
      "source": "local",
      "reason": "台词明确提到奶茶"
    }
  ],
  "sticker_matches": []
}
```

---

## 12. 音频匹配 Agent

`Audio Match Agent` 独立于视频匹配。

匹配顺序：

1. 用户音频精确匹配
2. 用户音频语义近似匹配
3. 本地音频匹配
4. 静音或背景音乐兜底

输出示例：

```json
{
  "scene_id": 1,
  "audio_match": {
    "asset_id": "user_audio_001",
    "source": "user",
    "volume": 0.8,
    "start_sec": 0.0,
    "duration_sec": 3.0,
    "reason": "用户原声情绪慌张，适合迟到解释镜头"
  }
}
```

---

## 13. HyperFrames 渲染规划 Agent

`HyperFrames Render Plan Agent` 把分镜和素材匹配结果转换成最终画面布局。

负责内容：

- 1920x1080 画布布局
- 顶部主题条
- 分镜说明字幕
- 猫头台词
- 多猫站位
- 底部吐槽字幕
- 贴纸/道具安全区
- 猫主体、台词和字幕的遮挡校验

输出示例：

```json
{
  "scene_id": 1,
  "layout": {
    "canvas": "1920x1080",
    "background": {
      "file": "assets/generated/backgrounds/scene_1.png",
      "fit": "cover"
    },
    "cats": [
      {
        "video_asset_id": "user_motion_001",
        "position": "center",
        "scale": 1.15,
        "dialogue": "我真的已经出门了！"
      }
    ],
    "topic_caption": "迟到求生指南",
    "scene_caption": "路上狂奔",
    "subtitle": "求生欲直接拉满了",
    "stickers": []
  }
}
```

---

## 14. 自然语言分镜修改 Agent

建立独立 `Storyboard Edit Graph`：

```text
start
  -> parse_edit_instruction
  -> locate_target_scenes
  -> rewrite_storyboard
  -> rematch_cat_video_assets
  -> rematch_background_assets
  -> rematch_prop_and_sticker_assets
  -> rematch_audio_assets
  -> validate_edit_result
  -> rebuild_hyperframes_render_plan
  -> save_edit_history
  -> end
```

支持修改类型：

- 修改某一镜台词
- 调整镜头顺序
- 替换猫动作
- 指定使用某个用户上传猫素材
- 增加或删除分镜
- 修改背景、道具、贴纸
- 修改音频、静音或更换原声
- 调整情绪走向

编辑结果必须保留修改前后快照：

```json
{
  "edit_id": "edit_001",
  "instruction": "把第2镜改成更生气一点，并且用我上传的猫素材",
  "changed_scenes": [2],
  "before": {},
  "after": {},
  "validation": {
    "ok": true,
    "user_asset_policy_satisfied": true
  }
}
```

---

## 15. FFmpeg 合成 Agent

`FFmpeg Compose Agent` 只消费确认后的 `render_plan`。

职责：

1. 按分镜生成单镜头视频片段。
2. 叠加背景图、猫动作视频、贴纸、道具和字幕。
3. 应用 HyperFrames 布局。
4. 分别处理视频轨和音频轨。
5. 混合用户音频、本地音频、背景音乐或静音轨。
6. 拼接全部镜头。
7. 输出最终 MP4。

输出规格：

```text
resolution: 1920x1080
aspect_ratio: 16:9
format: mp4
video_codec: h264
audio_codec: aac
fps: 30
```

合成流程：

```text
storyboard
  -> render_plan
  -> per_scene_ffmpeg_filter
  -> scene_clips
  -> concat_clips
  -> mux_audio
  -> final_video.mp4
```

---

## 16. 校验 Agent

每次生成分镜或修改分镜后都要校验：

- 有用户素材时，是否优先使用用户素材。
- 每个本地素材使用是否有 fallback reason。
- 猫动作视频、背景图、贴纸/道具、音频是否分别匹配。
- 背景图缺失是否进入 gap report。
- 多猫场景是否避免复制同一个单猫素材。
- 分镜总时长是否合理。
- 字幕、台词、贴纸是否服务剧情。
- HyperFrames 布局是否避免遮挡猫脸和字幕。
- FFmpeg 合成所需资产是否齐全。

不通过时返回对应节点重试一次；仍失败则展示缺口报告，由用户确认是否生成补齐素材。

---

## 17. API 规划

```text
POST /api/session
POST /api/analyze
GET  /api/scripts/stream
POST /api/scripts/select
GET  /api/storyboard
POST /api/storyboard/edit
POST /api/storyboard/confirm
GET  /api/render/stream
GET  /api/state
POST /api/reset
```

关键变化：

- `/api/analyze` 同时完成参考视频选择和用户素材分析。
- `/api/storyboard/edit` 调用专门的分镜修改 Agent。
- `/api/render/stream` 只基于当前确认后的 storyboard 和 render_plan 生成视频。

---

## 18. 测试计划

必须覆盖：

- 上传爆款视频时不会选择本地爆款结构。
- 无上传爆款视频时能选择本地爆款结构。
- 上传用户猫视频后，会生成 `user_cat_video_assets`。
- 上传视频含音轨时，会生成独立 `user_audio_assets`。
- 上传背景图片后，会生成 `user_background_assets`。
- 有用户素材时，剧本候选包含 `asset_strategy.user_assets_used`。
- 有合适用户猫动作素材时，分镜猫动作来源为 `user`。
- 有合适用户背景图时，背景来源为 `user`。
- 背景缺失时，`background_match.missing = true`。
- 用户素材不足时，允许本地素材补充，并写明 fallback reason。
- 视频匹配、背景匹配、音频匹配互不覆盖。
- 自然语言修改后，最终视频使用修改后的 storyboard。
- 修改某镜指定用户素材时，匹配结果必须使用该用户素材。
- 多猫分镜不能复制同一个单猫动作素材。
- HyperFrames render_plan 包含字幕、猫位、背景和安全区。
- FFmpeg 合成使用最新 render_plan。

---

## 19. 开发里程碑

### Milestone 1: 项目骨架和状态模型

- [ ] 创建新项目目录。
- [ ] 定义 `ProjectState`、素材 schema、分镜 schema、render_plan schema。
- [ ] 建立 LangGraph 主图和空节点。
- [ ] 添加基础状态流转单元测试。

### Milestone 2: 参考视频与用户素材分析

- [ ] 实现上传爆款视频分析。
- [ ] 实现本地爆款结构选择。
- [ ] 实现用户猫动作视频分析。
- [ ] 实现用户视频音频抽取和音频描述。
- [ ] 实现用户背景图片分析。
- [ ] 生成统一用户资产 catalog。

### Milestone 3: 剧本和分镜生成

- [ ] 实现素材优先的剧本 Agent。
- [ ] 实现分层资产需求的分镜 Agent。
- [ ] 加入用户素材优先策略校验。
- [ ] 支持用户素材不足时本地补充。

### Milestone 4: 分离式素材匹配

- [ ] 实现猫动作视频匹配 Agent。
- [ ] 实现背景匹配 Agent。
- [ ] 实现贴纸和道具匹配 Agent。
- [ ] 实现音频匹配 Agent。
- [ ] 实现统一缺口报告。

### Milestone 5: HyperFrames 与 FFmpeg

- [ ] 实现 HyperFrames render_plan 生成。
- [ ] 实现布局安全区校验。
- [ ] 实现 FFmpeg 单镜头合成。
- [ ] 实现 FFmpeg 多镜头拼接。
- [ ] 实现音频混流和静音兜底。

### Milestone 6: 自然语言分镜修改

- [ ] 实现 `Storyboard Edit Graph`。
- [ ] 支持定位、改写、重匹配、校验。
- [ ] 保存 edit history。
- [ ] 确保最终视频只使用修改后的 storyboard 和 render_plan。

### Milestone 7: 前端与端到端验收

- [ ] 更新上传、候选剧本、分镜预览、自然语言修改、视频生成界面。
- [ ] 展示猫动作素材来源。
- [ ] 展示背景素材来源和缺口。
- [ ] 展示音频素材来源。
- [ ] 完成端到端测试。

---

## 20. 验收标准

项目完成时必须满足：

- 用户上传爆款视频后，系统只分析该视频作为参考结构。
- 用户未上传爆款视频时，系统使用本地爆款视频结构。
- 用户上传猫 meme 素材后，素材先被分析成结构化资产，再驱动剧本和分镜。
- 有合适用户猫动作素材时，分镜候选池优先选择用户素材。
- 本地猫动作只在用户素材不足时补充，并有可解释原因。
- 背景图由独立背景匹配 Agent 管理，不混入猫动作视频匹配。
- 系统能识别背景图片缺失，并生成明确 gap report。
- 背景缺失时可以调用图像生成能力补齐。
- 视频素材和音频素材分别建库、分别匹配、分别展示来源。
- 自然语言修改分镜后，最终视频严格基于修改后的分镜生成。
- HyperFrames 必须参与最终画面布局，不能只输出普通字幕视频。
- FFmpeg 必须作为最终视频合成引擎。
- 视频轨、音频轨、背景图、贴纸、道具必须在 `render_plan` 中分层表达。
- 无上传内容时，系统仍能使用本地爆款结构和本地素材完成生成。
