"""剧本生成器 — 基于爆款结构生成3个候选剧本（并发调用）

两阶段生成：
  Phase 1: 生成3个简略版剧本（概述+走向，无详细镜头）
  Phase 2: 用户选择后，展开为完整详细剧本（含逐镜头）
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Callable

from .config import config
from .doubao_client import client
from .generated_asset_library import asset_index_context
from .video_analyzer import load_structures
from .material_matcher import build_material_context
from .utils import load_sticker_catalog


# ─── Phase 1: 简略版剧本生成 ──────────────────────────────────

BRIEF_SCRIPT_PROMPT = """你是一位专业的短视频编导，专精于猫meme短视频创作。

你的任务是：根据用户主题和爆款结构参考，快速生成一个猫meme短视频的**简略版剧本**（仅概述，不需要详细镜头）。

## 猫meme视频创作原则：
- 用猫的动作来表达情绪和推进剧情
- 字幕是叙事的主要载体，要口语化、有网感
- hook要快、要抓人（前3秒定生死）
- 情感曲线要有起伏：铺垫→升级→爆发→反转/升华
- 总时长控制在15-30秒

## 重要：这是**简略版**剧本，只需给出：
- 视频标题和一句话hook
- 完整叙事弧线（用→连接各阶段）
- 2-3句话的剧情概述（让用户快速了解故事走向）
- 结尾CTA和情绪目标
- 预估镜头数和总时长
- **不需要逐镜头详细描述**

请严格按以下JSON格式输出：
```json
{
  "version": "high_click",
  "version_name": "高点击版",
  "title": "视频标题（抓眼球、有网感，10字以内）",
  "hook": "开头3秒的具体内容和呈现方式（一句话）",
  "target_emotion": "目标观众看完后的情绪反应",
  "duration_estimate": 25,
  "scene_count_estimate": 10,
  "narrative_arc": "完整的叙事弧线，用→连接每个阶段",
  "brief_summary": "2-3句话描述整个视频的剧情走向，让用户快速理解故事脉络和笑点/泪点在哪里",
  "cta": "结尾引导（关注/评论/点赞的引导方式）",
  "reference_structure": "借鉴了什么结构"
}
```
"""

# ─── Phase 2: 详细版剧本展开 ──────────────────────────────────

DETAILED_SCRIPT_PROMPT = """你是一位专业的短视频编导，专精于猫meme短视频创作。

你的任务是：根据用户选择的简略剧本，展开生成**完整的逐镜头详细剧本**。

## 猫meme视频创作原则：
- 使用猫的动作素材来表达情绪和推进剧情（用suggested_cat_motion描述需要的动作类型）
- 贴纸只在剧情明确需要时使用（如消息气泡、倒计时、试卷、手机通知），用 suggested_stickers 推荐；不要为了装饰硬塞无关贴纸
- 每镜都要给出建议背景（suggested_background），只有剧情明确需要具体物件时才给出 suggested_prop；不需要时必须填空字符串
- 有贴纸时给出贴纸位置（sticker_position），可选值：near_cat_paw_left/near_cat_paw_right（手机、手、爪边交互）、desk_left/desk_right（试卷、书、笔、电脑等桌面物件）、upper_context_left/upper_context_right（消息气泡、倒计时、通知牌）；无贴纸时填空字符串。不要把剧情道具随意放到 top_left/top_right。
- 用 HyperFrames 风格组织字幕层：scene_caption 是画面正中上方的当前分镜解释，只写4-8个字极短标签（如：赖床时刻/闹钟催命/开会走神），渲染时会自动加 *；不要写完整剧情句。dialogues 是猫头上的台词数组，可为1只猫独白，也可为2-3只猫对话，不要写死必须双猫。
- dialogues 负责猫咪头上的对话；subtitle_text 是底部短字幕/角色标签/补充吐槽，避免和 dialogues 完全重复。
- 当剧情出现朋友、同事、领导、老师、室友、客户、家人、群消息、请求、催促、回应、争辩等关系时，优先用2-3条 dialogues 让一个分镜里出现多只不同猫形成互动；独白、强反应、崩溃、转场镜头可以保持1只猫。
- 一个完整视频建议至少安排2个适合的多猫互动分镜，让剧情有交流感；不要为了凑数在完全独白的镜头硬塞角色。
- 字幕是叙事的主要载体，要口语化、有网感
- 每镜建议3-4秒，关键反应/互动镜可到5秒；不要用低于3秒的碎切镜头
- hook要快、要抓人（前3秒定生死）
- 情感曲线要有起伏：铺垫→升级→爆发→反转/升华
- 总镜头数控制在6-8个，总时长22-30秒；用更少镜头表达完整故事，合并相邻碎片化情节
- 必须严格遵循给定的叙事弧线展开每镜内容

请严格按以下JSON格式输出：
```json
{
  "version": "high_click",
  "version_name": "高点击版",
  "title": "视频标题",
  "hook": "开头3秒的具体内容和呈现方式",
  "target_emotion": "目标观众看完后的情绪反应",
  "duration_estimate": 25,
  "narrative_arc": "完整的叙事弧线，用→连接",
  "scenes": [
    {
      "scene_id": 1,
      "duration_sec": 3,
      "description": "这一镜的具体内容和猫的动作",
      "suggested_cat_motion": "需要什么类型的猫动作（如：瞪眼震惊、崩溃大哭、淡定摆手）",
      "suggested_stickers": ["贴纸类型1"],
      "sticker_position": "near_cat_paw_left",
      "suggested_background": "这一镜适合的背景场景，如：宿舍书桌/教室/办公室；不需要则留空",
      "suggested_prop": "这一镜需要额外生成的道具，如：倒计时牌/奶茶/电脑；不需要则留空",
      "scene_caption": "4-8字短标签，如：早上起床/群消息轰炸/翻开试卷",
      "dialogues": [
        {"speaker": "我", "line": "猫头上的台词"},
        {"speaker": "朋友", "line": "另一只猫的回应；没有对话时只保留一条"}
      ],
      "subtitle_text": "字幕内容（口语化、有网感）",
      "subtitle_style": "底部居中/白字黑描边",
      "transition": "硬切",
      "emotion": "这一镜传达的情绪",
      "notes": ""
    }
  ],
  "cta": "结尾引导（关注/评论/点赞的引导方式）",
  "reference_structure": "借鉴了什么结构"
}
```
"""

# 旧版完整剧本 prompt（保留兼容）
SINGLE_SCRIPT_PROMPT = DETAILED_SCRIPT_PROMPT

# 三个版本的定位（简略版用）
BRIEF_VERSION_CONFIGS = [
    {
        "version": "high_click",
        "version_name": "高点击版",
        "style_hint": """
【高点击版】强调hook冲击力、快节奏、情绪反差大。
- 标题要抓眼球、有悬念感
- 前3秒用最夸张的情绪（震惊/崩溃）
- 情绪反差要大，前一秒崩溃后一秒反转
- 结尾留悬念或引发好奇
- 预估7-8镜，约24-28秒
""",
    },
    {
        "version": "high_resonance",
        "version_name": "高共鸣版",
        "style_hint": """
【高共鸣版】强调情感连接、真实生活场景、温暖收束。
- 标题走心有温度
- 用真实生活细节打动观众
- 情绪细腻：从日常→压力→脆弱→温暖
- 让观众看完想说"是我了"
- 预估6-8镜，约24-30秒
""",
    },
    {
        "version": "high_tempo",
        "version_name": "高节奏版",
        "style_hint": """
【高节奏版】强调密集笑点、快速转场、荒诞升级。
- 标题有趣、有梗
- 大量使用反差和反转
- 节奏轻快但不碎切，每镜约3秒，让观众看清反差
- 情绪从搞笑→更搞笑→笑到崩溃
- 预估7-8镜，约24-28秒
""",
    },
]

# 三个版本的定位（详细版用）
VERSION_CONFIGS = [
    {
        "version": "high_click",
        "version_name": "高点击版",
        "style_hint": """
【高点击版】强调hook冲击力、快节奏、情绪反差大。
- 标题要抓眼球、有悬念感
- 前3秒用最夸张的情绪（震惊/崩溃）
- 节奏偏快但镜头要完整，每镜3-4秒
- 情绪反差要大，前一秒崩溃后一秒反转
- 结尾留悬念或引发好奇
""",
    },
    {
        "version": "high_resonance",
        "version_name": "高共鸣版",
        "style_hint": """
【高共鸣版】强调情感连接、真实生活场景、温暖收束。
- 标题走心有温度
- 用真实生活细节打动观众
- 情绪细腻：从日常→压力→脆弱→温暖
- 让观众看完想说"是我了"
- 结尾温暖或引发评论共鸣
""",
    },
    {
        "version": "high_tempo",
        "version_name": "高节奏版",
        "style_hint": """
【高节奏版】强调密集笑点、快速转场、荒诞升级。
- 标题有趣、有梗
- 大量使用反差和反转
- 节奏轻快但不碎切，每镜约3秒
- 情绪从搞笑→更搞笑→笑到崩溃
- 结尾出乎意料或留下荒诞感
""",
    },
]


def _build_base_context(
    theme: str,
    reference_structure: dict,
    custom_materials: Optional[list[str]],
    user_preferences: str,
    material_context: Optional[str] = None,
) -> str:
    """构建公共上下文（避免重复代码）。"""
    if material_context is None:
        material_context = build_material_context()

    custom_materials_text = ""
    if custom_materials:
        custom_materials_text = "\n## 用户上传素材\n" + "\n".join(
            f"- {m}" for m in custom_materials
        )

    structure_summary = _summarize_structure(reference_structure)
    return f"""## 用户主题
{theme}

## 用户偏好
{user_preferences or "无特殊偏好，根据主题自由发挥"}

## 参考的爆款结构
{structure_summary}

## 可用素材
{material_context}
{custom_materials_text}"""


def _build_lightweight_detail_material_context() -> str:
    """Build compact material guidance for detailed script expansion.

    The detail pass only needs to describe creative intent. Exact motion,
    sticker, prop, and background choices are matched in the storyboard pass,
    so sending the full asset catalog here only slows the model down.
    """
    lines = [
        "## 可用素材说明（轻量版）",
        "- 猫动作素材会在分镜阶段自动匹配；这里写 suggested_cat_motion 的情绪/动作意图即可。",
        "- 贴纸只在剧情明确需要互动道具或信息提示时建议，如手机、电脑、试卷、奶茶、通知气泡。",
        "- 背景写语义场景即可，如办公室工位、会议室、宿舍、教室、茶水间；已有背景会优先复用。",
        "- 道具只写剧情必需物件；无关装饰、表情眼睛、鼠标等不要硬塞。",
    ]

    try:
        sticker_catalog = load_sticker_catalog()
    except Exception:
        sticker_catalog = []
    if sticker_catalog:
        categories = []
        for item in sticker_catalog[:8]:
            categories.append(
                f"{item.get('folder', '')}({str(item.get('description', ''))[:24]})"
            )
        lines.append("- 贴纸分类概览：" + "；".join(categories))

    background_context = asset_index_context("background", limit=12)
    if background_context:
        lines.append(background_context)
    return "\n".join(lines)


def _get_reference_structure(
    theme: str,
    reference_structure: Optional[dict] = None,
) -> dict:
    """获取参考结构（加载或自动匹配）。"""
    all_structures = load_structures()
    if not all_structures:
        raise RuntimeError("没有可用的爆款结构，请先运行视频分析")
    if reference_structure is None:
        reference_structure = _auto_match_structure(theme, all_structures)
    return reference_structure


# ═══════════════════════════════════════════════════════════════
# Phase 1: 简略版剧本生成（流式）
# ═══════════════════════════════════════════════════════════════

def generate_brief_scripts_streaming(
    theme: str,
    reference_structure: Optional[dict] = None,
    custom_materials: Optional[list[str]] = None,
    user_preferences: str = "",
    on_progress: Optional[Callable[[str, dict | None], None]] = None,
) -> dict:
    """生成3个**简略版**候选剧本（每个完成时回调 on_progress）。

    简略版仅包含：标题、hook、叙事弧线、剧情概述、情绪目标、CTA。
    不包含逐镜头详细描述，让用户快速了解剧情走向。

    Args:
        on_progress: 回调 (version_key, brief_script_dict)
                     当 version_key == "done" 时表示全部完成
    """
    ref = _get_reference_structure(theme, reference_structure)
    base_context = _build_base_context(theme, ref, custom_materials, user_preferences)

    def _generate_one(vc: dict) -> dict:
        version = vc["version"]
        user_message = f"""{base_context}

## 生成要求
{vc['style_hint']}

请生成一个猫meme短视频的**简略剧本**（仅概述，不要详细镜头）。"""

        try:
            result = client.chat_json(
                system_prompt=BRIEF_SCRIPT_PROMPT,
                user_message=user_message,
                temperature=0.85,
                max_tokens=2048,
                timeout=120,
            )
            if isinstance(result, dict):
                result["version"] = vc["version"]
                result["version_name"] = vc["version_name"]
            print(f"   ✅ [简略] {vc['version_name']}: {result.get('title', '')}")
            if on_progress:
                on_progress(vc["version"], result)
            return result
        except Exception as e:
            print(f"   ⚠️ [简略] {vc['version_name']} 生成失败: {e}")
            error_result = {
                "version": vc["version"],
                "version_name": vc["version_name"],
                "title": f"{vc['version_name']}（生成失败）",
                "error": str(e),
            }
            if on_progress:
                on_progress(vc["version"], error_result)
            return error_result

    scripts = []
    print(f"   🚀 并发生成3个简略剧本...")
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(_generate_one, vc): vc for vc in BRIEF_VERSION_CONFIGS}
        results_map = {}
        for future in as_completed(futures):
            vc = futures[future]
            try:
                results_map[vc["version"]] = future.result()
            except Exception as e:
                results_map[vc["version"]] = {
                    "version": vc["version"],
                    "version_name": vc["version_name"],
                    "error": str(e),
                }

    for vc in BRIEF_VERSION_CONFIGS:
        scripts.append(results_map.get(vc["version"], {
            "version": vc["version"],
            "version_name": vc["version_name"],
            "error": "未返回结果",
        }))

    elapsed = time.time() - start_time
    print(f"   ⚡ 简略剧本全部完成，耗时 {elapsed:.1f}秒（并发模式）")

    if on_progress:
        on_progress("done", None)

    return {
        "scripts": scripts,
        "theme": theme,
        "reference_video": ref.get("video_name", ""),
        "reference_narrative": ref.get("narrative_pattern", ""),
    }


# ═══════════════════════════════════════════════════════════════
# Phase 2: 详细版剧本展开
# ═══════════════════════════════════════════════════════════════

def expand_script_detail(
    brief_script: dict,
    theme: str,
    reference_structure: Optional[dict] = None,
    custom_materials: Optional[list[str]] = None,
) -> dict:
    """将用户选中的简略剧本展开为**完整详细剧本**（含逐镜头描述）。

    Args:
        brief_script: 用户选中的简略剧本（来自 Phase 1）
        theme: 用户主题
        reference_structure: 参考的爆款结构
        custom_materials: 用户上传的素材

    Returns:
        完整剧本 dict（含 scenes 列表）
    """
    ref = _get_reference_structure(theme, reference_structure)
    base_context = _build_base_context(
        theme,
        ref,
        custom_materials,
        "",
        material_context=_build_lightweight_detail_material_context(),
    )

    # 找到对应的详细版style_hint
    version = brief_script.get("version", "high_click")
    detail_config = None
    for vc in VERSION_CONFIGS:
        if vc["version"] == version:
            detail_config = vc
            break
    if detail_config is None:
        detail_config = VERSION_CONFIGS[0]

    brief_summary = json.dumps({
        "title": brief_script.get("title", ""),
        "hook": brief_script.get("hook", ""),
        "narrative_arc": brief_script.get("narrative_arc", ""),
        "target_emotion": brief_script.get("target_emotion", ""),
        "cta": brief_script.get("cta", ""),
        "duration_estimate": brief_script.get("duration_estimate", 25),
        "scene_count_estimate": brief_script.get("scene_count_estimate", 10),
        "brief_summary": brief_script.get("brief_summary", ""),
    }, ensure_ascii=False, indent=2)

    user_message = f"""{base_context}

## 选定的简略剧本
{brief_summary}

## 展开要求
{detail_config['style_hint']}

请将上述简略剧本展开为完整详细剧本。
重要规则：
- 严格遵循给定的叙事弧线和剧情概述
- 标题、hook、情绪目标、CTA 保持一致
- 镜头数优先控制在6-8个；如果简略剧本估计更高，也要合并相邻情节，避免剧情过密
- 每镜 duration_sec 不低于3秒，建议3-4秒，关键反应/互动镜可到5秒
- 总时长约22-30秒，保证观众能看清每个分镜
- 每镜都要有具体的猫动作和贴纸建议"""

    print(f"   📝 展开详细剧本: {brief_script.get('title', '')}...")
    start_time = time.time()

    try:
        result = client.chat_json(
            system_prompt=DETAILED_SCRIPT_PROMPT,
            user_message=user_message,
            temperature=0.8,
            max_tokens=3072,
            timeout=300,
        )
        if isinstance(result, dict):
            result["version"] = brief_script.get("version", "")
            result["version_name"] = brief_script.get("version_name", "")
        elapsed = time.time() - start_time
        print(f"   ✅ 详细剧本展开完成，耗时 {elapsed:.1f}秒")
        print(f"      标题: {result.get('title', '')}")
        print(f"      镜头数: {len(result.get('scenes', []))}")
        return result
    except Exception as e:
        print(f"   ❌ 详细剧本展开失败: {e}")
        raise


def generate_scripts(
    theme: str,
    reference_structure: Optional[dict] = None,
    custom_materials: Optional[list[str]] = None,
    user_preferences: str = "",
) -> dict:
    """为给定主题生成3个候选剧本（分3次API调用，每次一个版本）。

    Args:
        theme: 用户输入的主题描述（必填）
        reference_structure: 参考的爆款结构（可选，不传则自动匹配最佳）
        custom_materials: 用户上传的素材描述列表
        user_preferences: 用户偏好（如 "节奏快一点"、"偏搞笑"）

    Returns:
        {"scripts": [...], "matched_structure": "...", "theme": "..."}
    """
    # 1. 加载所有爆款结构
    all_structures = load_structures()
    if not all_structures:
        raise RuntimeError("没有可用的爆款结构，请先运行视频分析")

    # 2. 如果没有指定参考结构，自动匹配最佳
    if reference_structure is None:
        reference_structure = _auto_match_structure(theme, all_structures)

    # 3. 构建素材上下文
    material_context = build_material_context()

    # 4. 构建用户素材描述
    custom_materials_text = ""
    if custom_materials:
        custom_materials_text = "\n## 用户上传素材\n" + "\n".join(
            f"- {m}" for m in custom_materials
        )

    # 5. 构建公共上下文
    structure_summary = _summarize_structure(reference_structure)
    base_context = f"""## 用户主题
{theme}

## 用户偏好
{user_preferences or "无特殊偏好，根据主题自由发挥"}

## 参考的爆款结构
{structure_summary}

## 可用素材
{material_context}
{custom_materials_text}"""

    # 6. 并发生成3个版本（3个API调用同时发出）
    scripts = []

    def _generate_one(vc: dict) -> dict:
        """生成单个版本的剧本（在线程中执行）。"""
        version = vc["version"]
        user_message = f"""{base_context}

## 生成要求
{vc['style_hint']}

请生成一个6-8镜的猫meme短视频剧本，每镜3-5秒，避免剧情过密。"""

        try:
            result = client.chat_json(
                system_prompt=SINGLE_SCRIPT_PROMPT,
                user_message=user_message,
                temperature=0.85,
                max_tokens=4096,
                timeout=300,
            )
            if isinstance(result, dict):
                result["version"] = vc["version"]
                result["version_name"] = vc["version_name"]
            print(f"   ✅ {vc['version_name']}: {result.get('title', '')}")
            return result
        except Exception as e:
            print(f"   ⚠️ {vc['version_name']} 生成失败: {e}")
            return {
                "version": vc["version"],
                "version_name": vc["version_name"],
                "title": f"{vc['version_name']}（生成失败）",
                "error": str(e),
            }

    # 并发执行（3个版本同时请求豆包 API）
    print(f"   🚀 并发生成3个候选剧本（预计节省2/3时间）...")
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=3) as executor:
        # 按顺序提交以保持版本顺序
        futures = {executor.submit(_generate_one, vc): vc for vc in VERSION_CONFIGS}
        results_map = {}
        for future in as_completed(futures):
            vc = futures[future]
            try:
                results_map[vc["version"]] = future.result()
            except Exception as e:
                results_map[vc["version"]] = {
                    "version": vc["version"],
                    "version_name": vc["version_name"],
                    "title": f"{vc['version_name']}（生成失败）",
                    "error": str(e),
                }

    # 按原始顺序排列
    for vc in VERSION_CONFIGS:
        scripts.append(results_map.get(vc["version"], {
            "version": vc["version"],
            "version_name": vc["version_name"],
            "error": "未返回结果",
        }))

    elapsed = time.time() - start_time
    print(f"   ⚡ 全部完成，耗时 {elapsed:.1f}秒（并发模式）")

    # 7. 组装结果
    result = {
        "scripts": scripts,
        "theme": theme,
        "reference_video": reference_structure.get("video_name", ""),
        "reference_narrative": reference_structure.get("narrative_pattern", ""),
    }

    return result


def generate_scripts_streaming(
    theme: str,
    reference_structure: Optional[dict] = None,
    custom_materials: Optional[list[str]] = None,
    user_preferences: str = "",
    on_progress: Optional[Callable[[str, dict | None], None]] = None,
) -> dict:
    """流式版本 — 每个版本完成时立即回调 on_progress。

    Args:
        on_progress: 回调函数 (version_key, script_dict_or_None)
                     version_key: "high_click" | "high_resonance" | "high_tempo"
                     当 version_key == "done" 时表示全部完成

    用于 SSE 推送进度给前端。
    """
    all_structures = load_structures()
    if not all_structures:
        raise RuntimeError("没有可用的爆款结构，请先运行视频分析")

    if reference_structure is None:
        reference_structure = _auto_match_structure(theme, all_structures)

    material_context = build_material_context()

    custom_materials_text = ""
    if custom_materials:
        custom_materials_text = "\n## 用户上传素材\n" + "\n".join(
            f"- {m}" for m in custom_materials
        )

    structure_summary = _summarize_structure(reference_structure)
    base_context = f"""## 用户主题
{theme}

## 用户偏好
{user_preferences or "无特殊偏好，根据主题自由发挥"}

## 参考的爆款结构
{structure_summary}

## 可用素材
{material_context}
{custom_materials_text}"""

    def _generate_one(vc: dict) -> dict:
        version = vc["version"]
        user_message = f"""{base_context}

## 生成要求
{vc['style_hint']}

请生成一个6-8镜的猫meme短视频剧本，每镜3-5秒，避免剧情过密。"""

        try:
            result = client.chat_json(
                system_prompt=SINGLE_SCRIPT_PROMPT,
                user_message=user_message,
                temperature=0.85,
                max_tokens=4096,
                timeout=300,
            )
            if isinstance(result, dict):
                result["version"] = vc["version"]
                result["version_name"] = vc["version_name"]
            # 回调通知
            if on_progress:
                on_progress(vc["version"], result)
            return result
        except Exception as e:
            error_result = {
                "version": vc["version"],
                "version_name": vc["version_name"],
                "title": f"{vc['version_name']}（生成失败）",
                "error": str(e),
            }
            if on_progress:
                on_progress(vc["version"], error_result)
            return error_result

    scripts = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(_generate_one, vc): vc for vc in VERSION_CONFIGS}
        results_map = {}
        for future in as_completed(futures):
            vc = futures[future]
            try:
                results_map[vc["version"]] = future.result()
            except Exception as e:
                results_map[vc["version"]] = {
                    "version": vc["version"],
                    "version_name": vc["version_name"],
                    "error": str(e),
                }

    for vc in VERSION_CONFIGS:
        scripts.append(results_map.get(vc["version"], {
            "version": vc["version"],
            "version_name": vc["version_name"],
            "error": "未返回结果",
        }))

    if on_progress:
        on_progress("done", None)

    return {
        "scripts": scripts,
        "theme": theme,
        "reference_video": reference_structure.get("video_name", ""),
        "reference_narrative": reference_structure.get("narrative_pattern", ""),
    }


def _auto_match_structure(theme: str, structures: dict[str, dict]) -> dict:
    """根据主题自动匹配最合适的爆款结构。"""
    structure_list = []
    for name, s in structures.items():
        structure_list.append({
            "name": name,
            "narrative": s.get("narrative_pattern", ""),
            "emotional": s.get("emotional_arc", ""),
            "summary": s.get("overall_style_summary", ""),
        })

    prompt = f"""用户主题：{theme}

可用的爆款视频结构：
{json.dumps(structure_list, ensure_ascii=False, indent=2)}

请分析哪个爆款视频的结构最适合迁移到用户主题。
只返回最佳匹配的视频文件名（如 "抖音202664-122020.mp4"），不要其他内容。"""

    best_name = client.chat_text(
        system_prompt="你是一个视频结构匹配专家。只返回文件名。",
        user_message=prompt,
        temperature=0,
        max_tokens=100,
    ).strip()

    best_name = best_name.strip('"').strip("'").strip()
    for name in structures:
        if name in best_name or best_name in name:
            return structures[name]

    return list(structures.values())[0]


def _summarize_structure(structure: dict) -> str:
    """将爆款结构概括为简短的文本描述。"""
    script = structure.get("script_structure", {})
    rhythm = structure.get("rhythm_structure", {})
    packaging = structure.get("packaging_structure", {})

    lines = [
        f"视频名称: {structure.get('video_name', '')}",
        f"叙事模式: {structure.get('narrative_pattern', '')}",
        f"情绪曲线: {structure.get('emotional_arc', '')}",
    ]

    hook = script.get("hook", {})
    if hook:
        lines.append(f"Hook类型: {hook.get('type', '')} - {hook.get('description', '')}")

    development = script.get("development", [])
    if development:
        lines.append(f"发展阶段: {len(development)}个段落")
        for d in development:
            lines.append(f"  - {d.get('type', '')}: {d.get('description', '')[:80]}")

    climax = script.get("climax", {})
    if climax:
        lines.append(f"高潮: {climax.get('type', '')} - {climax.get('description', '')}")

    cta = script.get("cta", {})
    if cta:
        lines.append(f"CTA: {cta.get('type', '')} - {cta.get('description', '')}")

    lines.append(f"节奏曲线: {rhythm.get('tempo_curve', '')}")
    lines.append(f"镜头频率: {rhythm.get('shot_frequency', '')}")
    lines.append(f"字幕风格: {packaging.get('subtitle_style', '')}")
    lines.append(f"贴纸类型: {', '.join(packaging.get('sticker_types', []))}")
    lines.append(f"整体风格: {structure.get('overall_style_summary', '')}")

    return "\n".join(lines)


def format_scripts_for_display(result: dict) -> str:
    """将生成的剧本格式化为可读的展示文本。"""
    scripts = result.get("scripts", [])
    if not scripts:
        return "⚠️ 剧本生成失败，请重试"

    lines = []
    if result.get("reference_video"):
        lines.append(f"📊 参考结构: {result['reference_video']}")
        lines.append(f"📐 叙事模式: {result.get('reference_narrative', '')}")
        lines.append("")

    for i, script in enumerate(scripts, 1):
        emoji = {"high_click": "🔥", "high_resonance": "💗", "high_tempo": "⚡"}
        version = script.get("version", "")

        if script.get("error"):
            lines.append(f"---")
            lines.append(f"⚠️ **候选剧本 #{i} — {script.get('version_name', '')}**")
            lines.append(f"生成失败: {script['error']}")
            lines.append("")
            continue

        lines.append(f"---")
        lines.append(f"🎬 **候选剧本 #{i} — {script.get('version_name', '')}** {emoji.get(version, '')}")
        lines.append(f"**标题**: {script.get('title', '')}")
        lines.append(f"**时长**: 约{script.get('duration_estimate', '?')}秒")
        lines.append(f"**Hook**: {script.get('hook', '')}")
        lines.append(f"**叙事弧线**: {script.get('narrative_arc', '')}")
        lines.append(f"**目标情绪**: {script.get('target_emotion', '')}")
        lines.append(f"**CTA**: {script.get('cta', '')}")
        lines.append(f"**镜头数**: {len(script.get('scenes', []))}")

        # 简要列出镜头
        scenes = script.get("scenes", [])
        if scenes:
            lines.append("")
            lines.append("**镜头概览**:")
            for s in scenes[:6]:
                lines.append(f"  镜{s.get('scene_id', '?')} [{s.get('duration_sec', '?')}s] "
                           f"{s.get('description', '')[:50]}... | {s.get('emotion', '')}")
            if len(scenes) > 6:
                lines.append(f"  ... 共{len(scenes)}镜")

        lines.append("")

    return "\n".join(lines)
