# TODO4: 收敛分镜与素材决策链路，修复用户素材选择失效

## Original Goal

把当前猫 meme 视频生成链路改造成更稳定、可追踪、可验收的素材决策系统，解决“用户上传素材虽然进入候选池，但最终分镜/视频仍被规则预绑、恢复逻辑或兜底逻辑覆盖”的问题。

## Task Background

当前项目更新困难的核心原因不是单个 prompt 或单个 agent 能力不足，而是素材选择权分散在多个阶段：

- 用户上传素材分析生成临时 `material_index`。
- 剧本生成 prompt 写入“用户素材优先”。
- 分镜生成会先用规则匹配器自动绑定用户素材。
- 分镜 AI 编排、角色 motion 分配、缺口补全、恢复用户 motion 绑定、视频渲染都会继续读写同一份 storyboard。
- 部分保护逻辑无法区分“用户明确指定素材”和“规则自动预绑定素材”，导致 agent 的选择被恢复或覆盖。

目标是把“建议”和“最终渲染决策”分开，让用户上传猫动作成为一等素材库，并给每个最终动作选择留下来源和阶段信息。

## Execution Steps

1. 梳理现有素材决策链路
   - 检查 `/api/analyze` 保存上传素材和构建 `material_index` 的字段。
   - 检查 `script_generator` 如何把用户素材传入简略剧本和详细剧本 prompt。
   - 检查 `storyboard_generator` 中规则匹配、AI 编排、角色 motion 分配、用户绑定恢复、缺口补全的执行顺序。
   - 检查 `video_composer` 和 API 序列化最终消费哪些 motion 字段。

2. 定义素材决策字段所有权
   - 区分 `suggested_motion`、`rule_suggestion`、`agent_selected`、`user_locked`、`fallback`。
   - 明确 scene-level motion 与 dialogue/rendered cat motion 的关系。
   - 规定最终渲染只消费一个权威字段集合，例如 `rendered_cats` 或 `motion_assignments`。

3. 将用户上传猫动作升级为一等素材库
   - 保持用户素材分析结果与 `assets/cat-motions/descriptions.json` 单条目同构。
   - 建立稳定 `user:*` motion catalog，并保留 `file_path`、`source=user`、`description`、`motion_tags`。
   - 在无上传素材时只使用本地素材库；有上传素材时优先提供用户 catalog，本地 catalog 只补充。

4. 改造分镜生成阶段的决策顺序
   - 规则匹配器只能产出建议，不直接锁死最终猫动作。
   - 分镜 AI 编排和角色 motion 选择拥有最终 motion 分配权。
   - 自动预绑定必须标记为可覆盖，例如 `motion_binding=auto_user_match`。
   - 用户明确选择或编辑指定的素材必须标记为不可覆盖，例如 `motion_binding=user_locked`。

5. 增加决策 provenance 和调试可视化数据
   - 每个最终猫动作记录 `motion_source`、`selection_stage`、`selection_reason`、`candidate_pool` 或简化候选摘要。
   - API 序列化返回最终渲染用的 motion，而不是只展示中间 scene motion。
   - 前端分镜卡片显示“规则建议/agent选择/用户锁定/兜底”的来源标签。

6. 增加端到端回归测试
   - 上传 2 个用户猫动作素材，mock 分镜规划 agent 为不同角色选择不同 `user:*` motion。
   - 验证最终 storyboard 的 dialogue/rendered cats 使用不同用户素材。
   - 验证自动预绑定不会覆盖 agent 选择。
   - 验证用户锁定素材不会被 agent、兜底或恢复逻辑覆盖。
   - 验证无上传素材时仍只走本地素材库。

7. 验证视频合成读取最终决策
   - 检查 render plan 中每个角色读取的 motion 文件。
   - 确保最终 MP4 中使用的素材和分镜预览/API 返回一致。

## Expected Result

用户上传多个猫 meme 素材后，系统会先把它们分析成可选择的 `user:*` motion catalog。剧本 agent 和分镜 agent 优先围绕这些用户素材设计剧情和角色动作，本地素材只在用户素材不足或不适合时补充。最终分镜和视频渲染使用同一份明确的最终 motion 分配结果，不再出现“候选池里有用户素材，但最终固定用同一只猫”的隐式覆盖问题。

## Acceptance Criteria

- 上传素材分析结果包含与 `assets/cat-motions/descriptions.json` 单条目同构的猫动作描述。
- 有用户上传素材时，剧本 prompt 和分镜 motion catalog 都把 `user:*` 素材放在本地素材之前。
- 自动规则匹配只能作为可覆盖建议，不能锁死最终 motion。
- 分镜 agent 或角色 motion agent 可以为不同角色选择不同用户上传素材，并且不会被恢复逻辑覆盖。
- 用户明确锁定的素材不会被 agent 或兜底逻辑覆盖。
- API 返回和前端展示能说明最终 motion 的来源阶段。
- 视频合成使用的 motion 文件与最终 storyboard/rendered cats 一致。
- 单元测试和端到端 mock 测试覆盖上述行为。

## Execution Result Summary

pending
