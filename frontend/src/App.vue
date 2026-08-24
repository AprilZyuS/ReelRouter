<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";

import {
  approveScreenplay,
  createNarrativeProject,
  createStoryboard,
  executeEpisodeVideos,
  getNarrativeProject,
  getScreenplayCandidate,
  getStoryboard,
  planEpisodes,
  pollEpisodeVideos,
  previewEpisodeVideos,
  reviewScreenplay,
  writeScreenplay,
  type EpisodePlan,
  type EpisodeReadiness,
  type Manuscript,
  type PrioritizedStoryboard,
  type ProjectProfile,
  type ScreenplayCandidate,
  type VideoJob,
  type VideoPlan,
} from "./api";

const ACTIVE_PROJECT_KEY = "reelrouter.active-project-id";
const ACTIVE_CANDIDATE_KEY = "reelrouter.active-screenplay-candidate-id";
const POLLING_INTERVAL_MS = 5_000;

const form = reactive({
  projectId: "rain-letter-project-001",
  title: "雨夜来信",
  keywordsText: "匿名来信, 姐姐失踪, 港口仓库",
  genre: "都市悬疑",
  visualStyle: "冷色调电影感，雨夜霓虹，克制悬疑；强调人物表情、环境细节与镜头连续性。",
  duration: 45,
  episodeBudget: 8,
  episodeCount: 2,
});

const profile = ref<ProjectProfile | null>(null);
const manuscript = ref<Manuscript | null>(null);
const episodes = ref<EpisodePlan[]>([]);
const episodeReadiness = ref<EpisodeReadiness[]>([]);
const selectedEpisodeNumber = ref(1);
const candidate = ref<ScreenplayCandidate | null>(null);
const storyboard = ref<PrioritizedStoryboard | null>(null);
const videoPlan = ref<VideoPlan | null>(null);
const videoJobs = ref<VideoJob[]>([]);
const paidConfirmed = ref(false);
const videoConfirmed = ref(false);
const busyStep = ref<string | null>(null);
const errorMessage = ref("");
const operationMessage = ref("准备就绪：请先从关键词创建或加载一个项目。");
const operationFailed = ref(false);
const isPolling = ref(false);

let pollingTimer: number | undefined;
let pollingInFlight = false;

const selectedEpisode = computed(() => episodes.value.find((item) => item.episode_number === selectedEpisodeNumber.value) || null);
const selectedReadiness = computed(() => episodeReadiness.value.find((item) => item.episode_number === selectedEpisodeNumber.value) || null);
const candidateBelongsToSelectedEpisode = computed(() => candidate.value?.screenplay.episode_number === selectedEpisodeNumber.value);
const canUseCandidate = computed(() => candidateBelongsToSelectedEpisode.value && candidate.value !== null);
const approvedCandidate = computed(() => selectedReadiness.value?.screenplay_approved === true);
const canGenerateScreenplay = computed(() => Boolean(
  selectedEpisode.value && selectedReadiness.value?.previous_episode_summary_ready,
));
const videoTerminal = computed(() => videoJobs.value.length > 0 && videoJobs.value.every((job) => job.status === "completed" || job.status === "failed"));

function keywords() {
  return form.keywordsText.split(/[，,、\n]/).map((item) => item.trim()).filter(Boolean);
}

function requirePaidConfirmation() {
  if (!paidConfirmed.value) {
    throw new Error("请先确认本次操作会调用创作模型并可能产生小额费用。");
  }
}

function resetEpisodeArtifacts() {
  candidate.value = null;
  storyboard.value = null;
  videoPlan.value = null;
  videoJobs.value = [];
  videoConfirmed.value = false;
  window.localStorage.removeItem(ACTIVE_CANDIDATE_KEY);
  clearPolling();
}

function selectEpisode(episodeNumber: number) {
  if (selectedEpisodeNumber.value === episodeNumber) return;
  selectedEpisodeNumber.value = episodeNumber;
  resetEpisodeArtifacts();
  void restoreStoryboard();
}

async function runStep(name: string, action: () => Promise<void>) {
  busyStep.value = name;
  errorMessage.value = "";
  operationFailed.value = false;
  operationMessage.value = `${stepName(name)}正在执行，请勿重复点击。`;
  try {
    await action();
    operationMessage.value = `${stepName(name)}已完成。请按流程继续下一步。`;
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "操作失败，请查看后端日志。";
    operationFailed.value = true;
    operationMessage.value = `${stepName(name)}未完成：${errorMessage.value}`;
  } finally {
    busyStep.value = null;
  }
}

function stepName(step: string) {
  const names: Record<string, string> = {
    project: "小说生成与知识库入库",
    load: "项目加载",
    plan: "分集规划",
    screenplay: "候选剧本生成",
    review: "Reviewer 审查",
    approve: "人工剧本批准",
    storyboard: "分镜与镜头优先级生成",
    "video-plan": "视频成本预检",
    execute: "整集视频提交",
  };
  return names[step] || "当前操作";
}

async function createProject() {
  await runStep("project", async () => {
    requirePaidConfirmation();
    const projectId = form.projectId.trim();
    const inputKeywords = keywords();
    if (!projectId || !form.title.trim() || !inputKeywords.length) {
      throw new Error("请填写项目 ID、标题和至少一个关键词。");
    }
    const result = await createNarrativeProject({
      project_id: projectId,
      title: form.title.trim(),
      keywords: inputKeywords,
      genre: form.genre.trim(),
      visual_style: form.visualStyle.trim(),
      episode_duration_seconds: form.duration,
      episode_budget_usd: form.episodeBudget,
      enable_assembly: true,
      confirm_paid_call: true,
    });
    profile.value = result.profile;
    manuscript.value = result.manuscript;
    episodes.value = [];
    episodeReadiness.value = [];
    selectedEpisodeNumber.value = 1;
    resetEpisodeArtifacts();
    window.localStorage.setItem(ACTIVE_PROJECT_KEY, result.profile.project_id);
  });
}

async function loadProject(projectId = form.projectId.trim()) {
  await runStep("load", async () => {
    if (!projectId) throw new Error("请先输入项目 ID。");
    const result = await getNarrativeProject(projectId);
    profile.value = result.profile;
    episodes.value = result.episodes;
    episodeReadiness.value = result.episode_readiness;
    form.projectId = result.profile.project_id;
    form.title = result.profile.title;
    form.keywordsText = result.profile.keywords.join("、");
    form.genre = result.profile.genre;
    form.visualStyle = result.profile.style_bible;
    form.duration = result.profile.episode_duration_seconds;
    form.episodeBudget = result.profile.episode_budget_usd;
    selectedEpisodeNumber.value = result.episodes[0]?.episode_number || 1;
    window.localStorage.setItem(ACTIVE_PROJECT_KEY, result.profile.project_id);
    await restoreStoryboard();
  });
}

async function buildEpisodePlans() {
  await runStep("plan", async () => {
    requirePaidConfirmation();
    if (!profile.value) throw new Error("请先生成或加载项目。");
    const result = await planEpisodes(profile.value.project_id, form.episodeCount);
    const current = await getNarrativeProject(profile.value.project_id);
    episodes.value = current.episodes;
    episodeReadiness.value = current.episode_readiness;
    selectedEpisodeNumber.value = result.plans[0]?.episode_number || 1;
    resetEpisodeArtifacts();
  });
}

async function generateScreenplay() {
  await runStep("screenplay", async () => {
    requirePaidConfirmation();
    if (!profile.value || !selectedEpisode.value) throw new Error("请先完成分集规划并选择一集。");
    if (!selectedReadiness.value?.previous_episode_summary_ready) {
      throw new Error(selectedReadiness.value?.screenplay_block_reason || "当前集尚未满足连续性前置条件。");
    }
    const result = await writeScreenplay(profile.value.project_id, selectedEpisode.value.episode_number);
    candidate.value = result.candidate;
    storyboard.value = null;
    videoPlan.value = null;
    videoJobs.value = [];
    window.localStorage.setItem(ACTIVE_CANDIDATE_KEY, result.candidate.candidate_id);
  });
}

async function runReviewer() {
  await runStep("review", async () => {
    requirePaidConfirmation();
    if (!candidate.value) throw new Error("请先生成候选剧本。");
    candidate.value = (await reviewScreenplay(candidate.value.candidate_id)).candidate;
  });
}

async function approveCurrentScreenplay() {
  await runStep("approve", async () => {
    if (!candidate.value?.review?.passed) throw new Error("Reviewer 尚未通过当前候选剧本，不能批准。 ");
    candidate.value = (await approveScreenplay(candidate.value.candidate_id)).candidate;
    if (profile.value) {
      const current = await getNarrativeProject(profile.value.project_id);
      episodeReadiness.value = current.episode_readiness;
    }
  });
}

async function generateStoryboard() {
  await runStep("storyboard", async () => {
    requirePaidConfirmation();
    if (!profile.value || !approvedCandidate.value || !selectedEpisode.value) {
      throw new Error("请先完成 Reviewer 审查并人工批准当前集剧本。");
    }
    storyboard.value = (await createStoryboard(profile.value.project_id, selectedEpisode.value.episode_number)).storyboard;
    const current = await getNarrativeProject(profile.value.project_id);
    episodeReadiness.value = current.episode_readiness;
    videoPlan.value = null;
    videoJobs.value = [];
  });
}

async function restoreStoryboard() {
  if (!profile.value || !selectedEpisode.value || !selectedReadiness.value?.storyboard_ready) return;
  try {
    storyboard.value = (await getStoryboard(profile.value.project_id, selectedEpisode.value.episode_number)).storyboard;
    await refreshVideoJobs();
    if (videoJobs.value.length && !videoTerminal.value) startPolling();
  } catch {
    // 尚未生成分镜是正常状态，不向用户显示恢复过程中的 404。
  }
}

async function previewVideos() {
  await runStep("video-plan", async () => {
    if (!profile.value || !storyboard.value) throw new Error("请先生成优先级分镜。");
    videoPlan.value = await previewEpisodeVideos(profile.value.project_id, storyboard.value.episode_number);
  });
}

function clearPolling() {
  if (pollingTimer !== undefined) {
    window.clearTimeout(pollingTimer);
    pollingTimer = undefined;
  }
  isPolling.value = false;
}

function scheduleNextPoll() {
  if (!profile.value || !storyboard.value || videoTerminal.value || pollingTimer !== undefined) return;
  pollingTimer = window.setTimeout(() => {
    pollingTimer = undefined;
    void refreshVideoJobs();
  }, POLLING_INTERVAL_MS);
}

function startPolling() {
  clearPolling();
  if (!profile.value || !storyboard.value || videoTerminal.value) return;
  isPolling.value = true;
  void refreshVideoJobs();
}

async function refreshVideoJobs() {
  if (!profile.value || !storyboard.value || pollingInFlight) return;
  pollingInFlight = true;
  try {
    const result = await pollEpisodeVideos(profile.value.project_id, storyboard.value.episode_number);
    videoJobs.value = result.jobs;
    if (result.terminal) clearPolling();
  } catch (error) {
    // 还没有提交任何镜头时，GET 返回空数组是正常状态；其他异常才显示。
    if (videoJobs.value.length) {
      errorMessage.value = error instanceof Error ? error.message : "视频状态刷新失败。";
    }
  } finally {
    pollingInFlight = false;
    if (!videoTerminal.value && videoJobs.value.length) scheduleNextPoll();
  }
}

async function submitEpisodeVideos() {
  await runStep("execute", async () => {
    if (!videoConfirmed.value) throw new Error("请确认整集预估成本后再提交真实视频任务。");
    if (!profile.value || !storyboard.value || !videoPlan.value) throw new Error("请先完成视频成本预检。");
    await executeEpisodeVideos(profile.value.project_id, storyboard.value.episode_number);
    await refreshVideoJobs();
    startPolling();
  });
}

async function restoreCandidate() {
  const candidateId = window.localStorage.getItem(ACTIVE_CANDIDATE_KEY);
  if (!candidateId) return;
  try {
    const restored = (await getScreenplayCandidate(candidateId)).candidate;
    if (restored.screenplay.project_id === profile.value?.project_id
      && restored.screenplay.episode_number === selectedEpisodeNumber.value) {
      candidate.value = restored;
    }
  } catch {
    window.localStorage.removeItem(ACTIVE_CANDIDATE_KEY);
  }
}

onMounted(async () => {
  const projectId = window.localStorage.getItem(ACTIVE_PROJECT_KEY);
  if (projectId) {
    await loadProject(projectId);
    await restoreCandidate();
  }
});
onBeforeUnmount(clearPolling);
</script>

<template>
  <main class="studio-shell">
    <header class="hero">
      <div>
        <p class="eyebrow">REELROUTER / NARRATIVE VIDEO STUDIO</p>
        <h1>从关键词，到分镜，再到可验收的镜头视频。</h1>
        <p class="hero-copy">小说、分集、剧本和镜头画面由独立 Agent 依次完成；每个生成步骤都带数据契约、RAG 证据或人工确认边界。</p>
      </div>
      <div class="system-state">
        <span class="signal"></span>
        <div><small>当前项目</small><strong>{{ profile?.title || "尚未创建" }}</strong></div>
      </div>
    </header>

    <p class="operation-status" :class="{ failed: operationFailed }">{{ operationMessage }}</p>

    <section class="workflow-rail" aria-label="ReelRouter 工作流">
      <span :class="{ active: profile }">01 关键词建项</span><i></i>
      <span :class="{ active: episodes.length }">02 分集规划</span><i></i>
      <span :class="{ active: candidate }">03 剧本审查</span><i></i>
      <span :class="{ active: storyboard }">04 分镜优先级</span><i></i>
      <span :class="{ active: videoJobs.length }">05 视频执行</span>
    </section>

    <section class="workspace">
      <form class="panel creation-panel" @submit.prevent="createProject">
        <div class="panel-heading"><div><p class="section-kicker">01 / NARRATIVE BRIEF</p><h2>关键词与创作约束</h2></div></div>
        <p class="hint">这里不直接填写视频提示词。关键词首先交给 Story Writer 生成小说，再由后续 Agent 生成剧本与每个镜头的画面提示词。</p>
        <label><span>项目 ID</span><div class="inline-input"><input v-model="form.projectId" /><button class="secondary small" type="button" :disabled="busyStep === 'load'" @click="loadProject()">加载已有项目</button></div></label>
        <label><span>故事标题</span><input v-model="form.title" /></label>
        <label><span>创作关键词</span><textarea v-model="form.keywordsText" rows="3" placeholder="用逗号分隔，例如：匿名来信、姐姐失踪、港口仓库"></textarea></label>
        <div class="form-grid">
          <label><span>题材</span><input v-model="form.genre" /></label>
          <label><span>单集时长（秒）</span><input v-model.number="form.duration" type="number" min="15" max="60" /></label>
          <label><span>单集视频预算（USD）</span><input v-model.number="form.episodeBudget" type="number" min="0.01" step="0.1" /></label>
          <label><span>先规划集数</span><input v-model.number="form.episodeCount" type="number" min="1" max="20" /></label>
        </div>
        <label><span>统一视觉风格</span><textarea v-model="form.visualStyle" rows="4"></textarea></label>
        <label class="toggle"><input v-model="paidConfirmed" type="checkbox" /><span>我确认“生成小说 / 分集 / 剧本 / 分镜”会调用创作模型并可能产生费用。</span></label>
        <button class="primary submit" :disabled="busyStep !== null" type="submit">{{ busyStep === 'project' ? "正在生成小说与知识库…" : "从关键词生成小说项目" }}</button>
      </form>

      <aside class="panel project-panel">
        <div class="panel-heading"><div><p class="section-kicker">PROJECT MEMORY</p><h2>长期叙事状态</h2></div></div>
        <div v-if="profile" class="project-facts">
          <strong>{{ profile.title }}</strong><p>{{ profile.logline }}</p>
          <dl><div><dt>版本</dt><dd>v{{ profile.narrative_version }}</dd></div><div><dt>建议总集数</dt><dd>{{ profile.planned_episode_count }}</dd></div><div><dt>知识库文档</dt><dd>{{ profile.manuscript_document_id }}</dd></div></dl>
          <p class="tag-list"><span v-for="word in profile.keywords" :key="word">{{ word }}</span></p>
        </div>
        <div v-else class="empty-state"><span class="empty-mark">◎</span><p>先提交关键词，系统将生成长文本并建立项目知识库。</p></div>
      </aside>
    </section>

    <section v-if="manuscript" class="panel manuscript-panel">
      <div class="panel-heading"><div><p class="section-kicker">SOURCE OF TRUTH</p><h2>小说原文</h2></div><span class="mode-tag">{{ manuscript.manuscript.length }} 字</span></div>
      <details><summary>查看 Story Writer 生成的小说正文</summary><p class="manuscript-text">{{ manuscript.manuscript }}</p></details>
    </section>

    <section class="panel stage-panel">
      <div class="panel-heading"><div><p class="section-kicker">02 / EPISODE PLANNER</p><h2>分集与本集目标</h2></div><button class="primary" type="button" :disabled="!profile || busyStep !== null" @click="buildEpisodePlans">{{ busyStep === 'plan' ? "正在规划…" : "生成并保存分集计划" }}</button></div>
      <p v-if="!episodes.length" class="hint">Planner 只依据小说知识库和初始关键词规划连续剧情，不会重新编造故事。</p>
      <div v-else class="episode-grid"><button v-for="item in episodes" :key="item.episode_number" class="episode-card" :class="{ selected: item.episode_number === selectedEpisodeNumber, locked: !episodeReadiness.find((state) => state.episode_number === item.episode_number)?.previous_episode_summary_ready }" type="button" @click="selectEpisode(item.episode_number)"><small>第 {{ item.episode_number }} 集 · {{ item.target_duration_seconds }} 秒</small><strong>{{ item.title }}</strong><span>{{ item.episode_goal }}</span><em>悬念：{{ item.closing_hook }}</em><em v-if="episodeReadiness.find((state) => state.episode_number === item.episode_number)?.screenplay_block_reason" class="blocked">等待上一集批准</em></button></div>
    </section>

    <section class="workspace production-grid">
      <article class="panel">
        <div class="panel-heading"><div><p class="section-kicker">03 / SCREENWRITER + REVIEWER</p><h2>结构化剧本</h2></div></div>
        <p class="hint">先生成候选稿，Reviewer 检查原文证据、剧情边界和跨集记忆；通过后仍需人工批准。</p>
        <div class="button-row"><button class="primary" type="button" :disabled="!canGenerateScreenplay || busyStep !== null" @click="generateScreenplay">{{ busyStep === 'screenplay' ? "正在写剧本…" : "生成候选剧本" }}</button><button class="secondary" type="button" :disabled="!canUseCandidate || busyStep !== null" @click="runReviewer">{{ busyStep === 'review' ? "审查中…" : "Reviewer 审查" }}</button><button class="secondary" type="button" :disabled="!candidate?.review?.passed || candidate?.status === 'approved' || busyStep !== null" @click="approveCurrentScreenplay">人工批准</button></div>
        <p v-if="selectedReadiness?.screenplay_block_reason" class="blocked">{{ selectedReadiness.screenplay_block_reason }}</p>
        <div v-if="canUseCandidate" class="candidate-card"><p class="card-label">候选稿状态：{{ candidate?.status }} · {{ candidate?.candidate_id }}</p><p v-if="candidate?.status === 'draft'" class="pending">待 Reviewer 审查。若审查接口提示“模型输出无效”，草稿不会被破坏，可点击“Reviewer 审查”安全重试。</p><p v-if="candidate?.review" :class="candidate.review.passed ? 'pass' : 'fail'">{{ candidate.review.passed ? "Reviewer 建议通过" : "Reviewer 拒绝" }}：{{ candidate.review.feedback }}</p><ul v-if="candidate?.review?.violations.length"><li v-for="item in candidate.review.violations" :key="item">{{ item }}</li></ul><p v-if="operationFailed && busyStep === null" class="error-box">{{ errorMessage }}</p><div v-for="scene in candidate?.screenplay.scenes" :key="scene.scene_id" class="scene"><strong>场景 {{ scene.order }} · {{ scene.duration_seconds }} 秒</strong><p>旁白：{{ scene.narration }}</p><p v-if="scene.dialogue">对白：{{ scene.dialogue }}</p><p>画面：{{ scene.visual_description }}</p></div></div>
      </article>

      <article class="panel">
        <div class="panel-heading"><div><p class="section-kicker">04 / STORYBOARD + PRIORITY</p><h2>镜头画面与成本层级</h2></div><button class="primary" type="button" :disabled="!approvedCandidate || busyStep !== null" @click="generateStoryboard">{{ busyStep === 'storyboard' ? "正在拆分镜头…" : "生成优先级分镜" }}</button></div>
        <p class="hint">这里展示的是 Storyboard Writer 从已批准剧本生成的镜头画面提示词，不是用户手写的单视频提示词。</p>
        <div v-if="storyboard" class="shot-list"><div v-for="shot in storyboard.shots" :key="shot.shot_id" class="shot"><div><span class="importance" :class="shot.importance">{{ shot.importance === 'key' ? "关键镜头" : "普通镜头" }}</span><strong>{{ shot.order }}. {{ shot.shot_id }} · {{ shot.duration_seconds }} 秒</strong></div><p>{{ shot.visual_prompt }}</p><small>镜头：{{ shot.camera_instruction }} · 最低质量 {{ shot.min_quality_score }} · {{ shot.priority_reason }}</small></div></div>
        <div v-else class="empty-state"><span class="empty-mark">◫</span><p>人工批准剧本后，才能生成可追溯的镜头画面与重要性分级。</p></div>
      </article>
    </section>

    <section class="panel video-stage">
      <div class="panel-heading"><div><p class="section-kicker">05 / VIDEO EXECUTOR</p><h2>整集视频预检与异步生成</h2></div><div class="button-row"><button class="secondary" type="button" :disabled="!storyboard || busyStep !== null" @click="previewVideos">{{ busyStep === 'video-plan' ? "计算中…" : "预检模型与成本" }}</button><button class="primary" type="button" :disabled="!videoPlan || !videoConfirmed || busyStep !== null" @click="submitEpisodeVideos">{{ busyStep === 'execute' ? "正在提交…" : "确认并提交整集镜头" }}</button></div></div>
      <p class="hint">预检只计算每个镜头的模型路由与成本；只有勾选确认并点击提交后，才会调用真实视频 Provider。</p>
      <label class="toggle"><input v-model="videoConfirmed" type="checkbox" :disabled="!videoPlan" /><span>我确认本集预估成本，并同意提交真实视频生成任务。</span></label>
      <div v-if="videoPlan" class="cost-summary"><strong>预估总成本 ${{ videoPlan.estimated_total_usd.toFixed(2) }}</strong><span>单集上限 ${{ videoPlan.episode_budget_usd.toFixed(2) }}</span></div>
      <div v-if="videoPlan" class="video-plan-grid"><div v-for="shot in videoPlan.shots" :key="shot.shot_id" class="plan-shot"><strong>{{ shot.shot_id }}</strong><span>{{ shot.importance === 'key' ? "关键" : "普通" }} · {{ shot.model_id }}</span><small>${{ shot.estimated_cost_usd.toFixed(2) }} · {{ shot.mode }}</small></div></div>
      <div v-if="videoJobs.length" class="video-jobs"><p class="card-label">镜头任务 {{ isPolling ? "· 每 5 秒刷新" : "" }}</p><div v-for="job in videoJobs" :key="job.job_id" class="job"><div><strong>{{ job.status }}</strong><span>{{ job.model_id }} · ${{ job.cost.estimated_usd.toFixed(2) }}</span></div><video v-if="job.status === 'completed' && job.output_url" :src="job.output_url" controls playsinline></video><a v-else-if="job.output_url" :href="job.output_url" target="_blank" rel="noreferrer">打开视频 ↗</a><p v-if="job.status === 'failed'" class="error-box">{{ job.failure_code }}：{{ job.failure_message }}</p></div></div>
    </section>
  </main>
</template>
