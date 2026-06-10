# TODO1: 修复自然语言编辑后视频 0:00 黑屏/无法播放

## 原始目标
修复用户在自然语言调整中修改左侧猫大小后，分镜脚本已更新但最终视频无法正常播放、页面显示 0:00 黑屏的问题。

## 任务背景
排查发现，生成出的 `/Users/shy/Documents/Agent/maomemeclaude/assets/generated/output/final_video_9b6bcd1b668a.mp4` 本地并不是坏文件：`ffprobe` 能读到约 28 秒视频和音频流，`ffmpeg` 能完整解码。更可疑的链路是：编辑后重新合成仍覆盖同一个 `final_video_{session_id}.mp4` 地址，前端继续用同一个 `<source src>`，浏览器媒体缓存和 Range 请求可能复用旧资源状态；同时最终 MP4 的 `moov` 元数据位于文件尾部，浏览器加载元数据更脆弱。自然语言编辑写入的 `cat_layout_overrides` 字段本身已经进入分镜，合成器也有消费该字段的路径。

## 执行步骤
1. 增加复现/回归测试，覆盖“同一 session 二次生成视频后返回不同可播放 URL”的行为。
2. 调整视频输出命名策略：每次生成视频使用唯一文件名，例如 `final_video_{session_id}_{timestamp_or_nonce}.mp4`，避免覆盖同 URL。
3. 在视频合成输出阶段加入 MP4 faststart 处理，让最终文件的 `moov` 元数据前置，提升浏览器播放稳定性。
4. 调整前端视频渲染逻辑：使用带版本参数或唯一 URL 的视频地址，必要时显式 `load()`，避免复用旧媒体源。
5. 在 `/api/edit` 成功后让旧视频状态失效：清空服务端 `video_path`，前端清空 `S.videoUrl`，避免用户误看编辑前的视频。
6. 检查 `/assets/...mp4` 服务响应是否保持正确的 `Content-Type: video/mp4`、Range 支持和 no-cache 行为。
7. 运行回归验证：视频合成相关单测、SSE 视频生成单测、前端序列化相关单测，以及 Python 编译检查。

## 预期结果
- 自然语言编辑后重新生成视频，不再复用旧的 mp4 URL。
- 页面中视频可以正常加载时长并播放，不再卡在 0:00 黑屏。
- 编辑后的猫布局缩放实际进入最终视频。
- 输出 MP4 对浏览器更友好，支持稳定首帧和时长加载。

## 验收标准
- `python3 -m unittest tests/test_video_stream.py tests/test_video_composer.py tests/test_serialization_and_editor.py -v` 通过。
- `python3 -m py_compile server.py agent/*.py` 通过。
- 生成后可用 `ffprobe` 验证最终 mp4 有有效视频/音频流和非零 duration。
- 新生成 mp4 的 `moov` 元数据位于 `mdat` 之前，或经过等价 faststart 处理。
- 连续生成两次视频时，接口返回的 `video_url` 不相同，前端不会继续引用旧视频地址。
- 执行自然语言编辑后，页面和服务端不再把编辑前视频当作当前最终视频。

## 执行结果摘要
- 执行时间：2026-06-09 12:17:35 +0800。
- 已将视频输出路径改为每次生成唯一文件名：`final_video_{session_id}_{timestamp}_{nonce}.mp4`，避免同一 session 二次生成复用旧 URL。
- `/api/edit` 成功后会清空服务端 `video_path`，并在响应里返回 `video_url: null`；前端自然语言调整后也会清空 `S.videoUrl`。
- 视频生成完成后前端使用带 `v=` 参数的播放 URL，避免浏览器媒体缓存继续拿旧 `<source>`。
- 最终视频 concat 和重新编码兜底均加入 `-movflags +faststart`。
- `/assets/...mp4` 静态响应现在显式 `video/mp4`、`no-store`，并保留 `Accept-Ranges: bytes`。
- 新增/更新回归测试覆盖：同 session 连续生成返回不同 URL、编辑后旧视频失效、MP4 faststart、视频资源 no-cache/Range 响应。
- 验证：`python3 -m unittest discover -v` 通过 111 个测试；`python3 -m py_compile server.py agent/*.py` 通过。
