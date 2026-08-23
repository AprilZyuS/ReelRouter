# ReelRouter

面向长文本分集改编的 AI 视频生成编排与成本优化原型。项目把“大模型负责创作与判断、确定性代码负责约束与执行”作为边界：模型输出必须通过 Schema 校验，原文与分块以 MySQL 为事实来源，FAISS 只负责按项目检索。

## 当前能力

- 单视频任务：Text-to-Video / Image-to-Video 请求、能力与成本路由、预算守卫、人工审批、异步轮询、输出评审。
- 视频 Provider：Mock Provider 与 Runway 适配器；任务请求、Provider、状态、人工输出评审和高成本审批均持久化到 MySQL。真实 Runway 任务可以在服务重启后继续查询。
- 叙事生产链：方舟 Story Writer 生成结构化小说稿，Pydantic 校验后写入 MySQL，按字符位置分块，以本地 BGE-M3 构建项目级 FAISS 索引，并回查原文证据。
- 两集连续创作：Episode Planner 为每集生成可审计的 `scope`；剧本先保存为候选稿，经 Reviewer 审查和人工批准后，才写入正式剧本与 `EpisodeSummary`，第 2 集会自动读取上一集摘要。
- 分镜执行：已批准剧本可生成带证据的优先级分镜；执行器在逐镜头提交前预检整集预算、选择最低成本合格模型、绑定可版本化的参考图资产，并保存镜头与 Provider 任务映射。
- 交付守卫：全部镜头完成并由人工接受后，才允许下载 Provider 成片 URL 并由 FFmpeg 按分镜顺序合成最终视频。
- 自动化测试：覆盖路由、预算、持久化、RAG 分块与检索、Story Writer/Reviewer 输出契约、候选审批和跨集摘要恢复。

## 当前边界

当前已完成“小说 → 两集计划 → 候选剧本 → Reviewer → 人工批准 → 跨集摘要 → 优先级分镜 → 逐镜头预算预检与视频提交 → 人工输出评审 → FFmpeg 合成”的 v1 主链。

v1 目标保持为：两集连续演示、每集 30–60 秒、6–12 个镜头、最多两名核心角色。项目不会宣称自动保证绝对角色一致性：参考图登记与版本绑定只是在调用 image-to-video 前建立可审计的一致性守卫，最终仍须由人工输出评审决定是否接受。

## 本地启动

1. 从 `.env.example` 复制出本地 `.env`，填入 MySQL、Ark 和可选的 Runway 配置。`.env` 已被 Git 忽略，绝不能提交真实密钥。

2. 仅启动 MySQL（开发 CLI 与本地测试）：

   ```powershell
   docker compose up -d
   ```

3. 安装基础依赖；若使用本地 BGE-M3，再安装 GPU 附加依赖：

   ```powershell
   python -m pip install -r requirements.txt
   python -m pip install -r requirements-local-gpu.txt
   ```

4. 运行测试：

   ```powershell
   python -m pytest -q
   ```

5. 启动视频任务 API：

   ```powershell
   uvicorn api:app --reload
   ```

   打开 `http://127.0.0.1:8000/docs` 查看接口文档。

也可以将 API 与 MySQL 一起容器化启动：

```powershell
docker compose up -d --build
```

容器内 API 使用 `MYSQL_HOST=mysql`，宿主机仍通过 `http://127.0.0.1:8000/docs` 访问。`VIDEO_PROVIDER` 默认是 `mock`，不会产生真实视频费用。

## 生成并导入一份小说

以下命令会调用真实 Ark 模型并产生费用；脚本要求显式确认。成功后会输出小说、MySQL 分块数和 FAISS 回查到的 `chunk_id`。

```powershell
python -m scripts.generate_narrative_project --confirm-paid-call --project-id rain-letter-demo-001
```

对于结构化小说 JSON，默认配置为：

```text
ARK_STORY_THINKING=disabled
ARK_STORY_MAX_TOKENS=8192
ARK_STORY_TEMPERATURE=0.2
```

若响应中仍出现 `finish_reason=length`，先查看脚本输出中的安全 token 诊断，再有控制地提高 `ARK_STORY_MAX_TOKENS`；不要无限重试或记录模型原始推理内容。

## 两集连续创作流程

先生成并保存两集计划。项目创建时的关键词、题材、时长和预算会从 MySQL Profile 读取，后续 CLI 不会伪造这些约束：

```powershell
python -m scripts.plan_episodes --confirm-paid-call --save --project-id rain-letter-demo-001
```

如果项目是在本次版本化改造之前创建的，先用一次无模型调用的迁移命令补齐原始约束；它不会重写小说或清空已有资产：

```powershell
python -m scripts.upgrade_project_profile --confirm-profile-update --project-id rain-letter-demo-001 --keywords "匿名来信,姐姐失踪,港口仓库" --genre "都市悬疑" --episode-duration-seconds 45 --episode-budget-usd 2.5
```

生成第 1 集候选剧本。该命令只保存候选稿，不会覆盖已批准剧本；请记录输出的候选 ID：

```powershell
python -m scripts.write_screenplay --confirm-paid-call --project-id rain-letter-demo-001 --episode-number 1
```

调用 Reviewer 审查候选稿。通过仅代表系统建议可发布，仍不会自动进入长期记忆：

```powershell
python -m scripts.review_screenplay --confirm-paid-call --candidate-id <候选剧本ID>
```

人工查看候选稿和 Reviewer 结论后，显式发布。发布会同时写入正式剧本与第 1 集摘要：

```powershell
python -m scripts.approve_screenplay --confirm-human-approval --candidate-id <候选剧本ID>
```

此后可生成第 2 集；Context Pack 会自动加载已批准的第 1 集摘要：

```powershell
python -m scripts.write_screenplay --confirm-paid-call --project-id rain-letter-demo-001 --episode-number 2
```

对应候选经过同样审查与人工批准后，可为已批准剧本生成优先级分镜：

```powershell
python -m scripts.create_storyboard --confirm-paid-call --project-id rain-letter-demo-001 --episode-number 1
```

## 从已保存分镜生成视频

以下是可复现的第 1 集视频执行流程。先使用 Mock 完整验证路由、预算、异步轮询与存储；它返回的是模拟 URL，不能作为真实成片合成输入：

```powershell
python -m scripts.execute_episode_videos --project-id rain-letter-demo-001 --episode-number 1 --provider mock --confirm-video-execution
python -m scripts.poll_episode_videos --project-id rain-letter-demo-001 --episode-number 1 --provider mock
python -m scripts.poll_episode_videos --project-id rain-letter-demo-001 --episode-number 1 --provider mock
```

若要真正生成视频，需先在 `.env` 设置 `RUNWAY_API_KEY`，并使用 Runway。请先检查预估成本：执行器会在任何提交前拒绝“整集总价超过 `episode_budget_usd`”的计划。45 秒、`$0.12/秒` 的保守 Runway 估算约为 `$5.40`；若项目预算仍为 `$2.50`，这是预期的拒绝，而不是错误。确认预算后可用 Profile 迁移命令更新预算，再提交：

```powershell
python -m scripts.upgrade_project_profile --confirm-profile-update --project-id rain-letter-demo-001 --keywords "匿名来信,姐姐失踪,港口仓库" --genre "都市悬疑" --episode-duration-seconds 45 --episode-budget-usd 6.0
python -m scripts.execute_episode_videos --project-id rain-letter-demo-001 --episode-number 1 --provider runway --confirm-video-execution
python -m scripts.poll_episode_videos --project-id rain-letter-demo-001 --episode-number 1 --provider runway
```

为降低角色漂移，建议先由你选定的图像生成工具生成并人工检查每个镜头的参考图，再登记参考图版本。v1 不绑定某一家文生图 API，避免把未验证的供应商实现硬编码进主链：

```powershell
python -m scripts.bind_shot_reference --project-id rain-letter-demo-001 --episode-number 1 --shot-id <shot-id> --asset-id lin-xiao-v1 --asset-version 1 --reference-image-url "https://你的已批准参考图URL" --confirm-reference-asset
```

所有镜头都登记后，给视频执行命令加上 `--require-reference-assets`，系统会强制使用 image-to-video，并在缺失资产时拒绝提交。

每个真实镜头完成后，先观看其 `output_url`，再保存人工结论；被拒绝或未评审的镜头不会进入合成：

```powershell
python -m scripts.review_episode_video --job-id <job-id> --provider runway --accepted true --visual-quality-score 4 --prompt-alignment-score 4 --feedback "人物、服装与提示词一致。" --confirm-human-review
python -m scripts.assemble_episode --project-id rain-letter-demo-001 --episode-number 1 --confirm-assembly
```

最后一条命令会从 Provider 下载已接受的镜头，并使用本机 `ffmpeg` 生成 `data/outputs/<project-id>/episode-<n>.mp4`。它绝不会在存在未完成、未评审或被拒绝镜头时生成“看似完成”的成片。

## Vue 3 视频工作台

`frontend/` 是独立的 Vue 3 + Vite 工作台，直接调用现有 FastAPI 视频 API。它包含关键词辅助提示词、参数输入、模型路由/预算解释、人工审批、异步状态轮询、视频播放下载和人工输出验收；当前范围是单镜头视频任务，不替代仍由 CLI 执行的长文本分集流水线。

先启动已经配置好真实 Provider 的 FastAPI（示例使用本地 `8001`）：

```powershell
python -m uvicorn api:app --reload --port 8001
```

另开一个终端启动前端：

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm run dev
```

打开 `http://127.0.0.1:5173`。若 API 使用 Docker 的 `8000` 端口，把 `frontend/.env` 中的 `VITE_API_BASE_URL` 改为 `http://127.0.0.1:8000`，并重启 Vite。
