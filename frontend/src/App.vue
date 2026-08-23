<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref } from "vue";

import {
  approveVideoJob,
  createVideoJob,
  getVideoJob,
  reviewVideoJob,
  type GenerationMode,
  type VideoJob,
  type WorkflowResponse,
} from "./api";

const form = reactive({
  keywords: "雨夜港口、匿名来信、姐姐失踪",
  prompt: "雨夜港口，年轻女性手持一封没有寄件人的信，冷色调电影感中景，远处可见货柜与吊机轮廓，雨水落在信封上。",
  mode: "text_to_video" as GenerationMode,
  duration: 4,
  budget: 1,
  quality: 7,
  referenceImageUrl: "",
});

const workflow = ref<WorkflowResponse | null>(null);
const job = ref<VideoJob | null>(null);
const errorMessage = ref("");
const isSubmitting = ref(false);
const isApproving = ref(false);
const isReviewing = ref(false);
const isPolling = ref(false);
const approvalFeedback = ref("");
const review = reactive({
  accepted: true,
  visual_quality_score: 4,
  prompt_alignment_score: 4,
  feedback: "",
});
let pollingTimer: number | undefined;

const isImageToVideo = computed(() => form.mode === "image_to_video");
const canSubmit = computed(() => {
  return form.prompt.trim().length > 0
    && form.duration >= 4
    && form.duration <= 15
    && form.budget > 0
    && (!isImageToVideo.value || form.referenceImageUrl.trim().length > 0);
});
const isTerminal = computed(() => job.value?.status === "completed" || job.value?.status === "failed");
const displayStatus = computed(() => job.value?.status || workflow.value?.status || "尚未创建任务");

function buildPromptFromKeywords() {
  const words = form.keywords
    .split(/[，,、\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
  if (!words.length) {
    errorMessage.value = "请先输入至少一个关键词。";
    return;
  }
  form.prompt = `${words.join("，")}。电影感短片，主体清晰，画面连贯，避免字幕与水印。`;
  errorMessage.value = "";
}

function clearPolling() {
  if (pollingTimer !== undefined) {
    window.clearInterval(pollingTimer);
    pollingTimer = undefined;
  }
  isPolling.value = false;
}

function startPolling() {
  clearPolling();
  if (!job.value || isTerminal.value) return;
  isPolling.value = true;
  pollingTimer = window.setInterval(() => void refreshJob(), 5_000);
}

async function refreshJob() {
  if (!job.value || isTerminal.value) {
    clearPolling();
    return;
  }
  try {
    job.value = await getVideoJob(job.value.job_id);
    errorMessage.value = "";
    if (isTerminal.value) clearPolling();
  } catch (error) {
    clearPolling();
    errorMessage.value = error instanceof Error ? error.message : "查询任务状态失败。";
  }
}

async function submitJob() {
  if (!canSubmit.value) {
    errorMessage.value = "请检查提示词、4–15 秒时长、预算和参考图。";
    return;
  }
  clearPolling();
  workflow.value = null;
  job.value = null;
  errorMessage.value = "";
  isSubmitting.value = true;
  try {
    const input = {
      prompt: form.prompt.trim(),
      mode: form.mode,
      duration_seconds: form.duration,
      budget_usd: form.budget,
      min_quality_score: form.quality,
      ...(isImageToVideo.value ? { reference_image_url: form.referenceImageUrl.trim() } : {}),
    };
    workflow.value = await createVideoJob(input);
    job.value = workflow.value.job;
    if (job.value) startPolling();
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "创建任务失败。";
  } finally {
    isSubmitting.value = false;
  }
}

async function resolveApproval(action: "approve" | "reject") {
  if (!workflow.value) return;
  isApproving.value = true;
  errorMessage.value = "";
  try {
    workflow.value = await approveVideoJob(workflow.value.thread_id, action, approvalFeedback.value.trim());
    job.value = workflow.value.job;
    if (job.value) startPolling();
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "审批操作失败。";
  } finally {
    isApproving.value = false;
  }
}

async function submitReview() {
  if (!job.value || job.value.status !== "completed") return;
  isReviewing.value = true;
  errorMessage.value = "";
  try {
    job.value = await reviewVideoJob(job.value.job_id, { ...review, feedback: review.feedback.trim() });
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "保存验收失败。";
  } finally {
    isReviewing.value = false;
  }
}

onBeforeUnmount(clearPolling);
</script>

<template>
  <main class="shell">
    <header class="hero">
      <div>
        <p class="eyebrow">REELROUTER / VIDEO STUDIO</p>
        <h1>将创作意图，变成可验收的视频任务。</h1>
        <p class="hero-copy">Vue 3 前端直接连接 FastAPI 的模型路由、预算护栏、人工审批与异步视频任务。</p>
      </div>
      <div class="system-state" :data-terminal="isTerminal">
        <span class="signal"></span>
        <div>
          <small>当前任务</small>
          <strong>{{ displayStatus }}</strong>
        </div>
      </div>
    </header>

    <section class="workspace">
      <form class="panel creation-panel" @submit.prevent="submitJob">
        <div class="panel-heading">
          <div>
            <p class="section-kicker">01 / CREATE</p>
            <h2>创作任务</h2>
          </div>
          <span class="mode-tag">{{ isImageToVideo ? "图生视频" : "文生视频" }}</span>
        </div>

        <label>
          <span>关键词</span>
          <div class="inline-input">
            <input v-model="form.keywords" placeholder="例如：雨夜、港口、匿名来信" />
            <button class="secondary small" type="button" @click="buildPromptFromKeywords">生成提示词草稿</button>
          </div>
        </label>

        <label>
          <span>自定义提示词</span>
          <textarea v-model="form.prompt" rows="6" maxlength="1000" placeholder="描述主体、环境、镜头语言、风格和动作。"></textarea>
          <small>{{ form.prompt.length }}/1000 · 最终以此内容提交给 Provider</small>
        </label>

        <div class="form-grid">
          <label>
            <span>生成方式</span>
            <select v-model="form.mode">
              <option value="text_to_video">文生视频</option>
              <option value="image_to_video">图生视频</option>
            </select>
          </label>
          <label>
            <span>时长（秒）</span>
            <input v-model.number="form.duration" type="number" min="4" max="15" />
            <small>Seedance：4–15 秒</small>
          </label>
          <label>
            <span>预算上限（USD）</span>
            <input v-model.number="form.budget" type="number" min="0.01" step="0.1" />
          </label>
          <label>
            <span>最低质量</span>
            <input v-model.number="form.quality" type="number" min="1" max="8" />
          </label>
        </div>

        <label v-if="isImageToVideo">
          <span>参考图 URL</span>
          <input v-model="form.referenceImageUrl" type="url" placeholder="https://.../character-reference.png" />
          <small>参考图必须是 Provider 可从公网访问的 URL。</small>
        </label>

        <p v-if="errorMessage" class="error-box">{{ errorMessage }}</p>
        <button class="primary submit" :disabled="isSubmitting || !canSubmit" type="submit">
          {{ isSubmitting ? "正在创建…" : "创建视频任务" }}
        </button>
      </form>

      <aside class="panel task-panel">
        <div class="panel-heading">
          <div>
            <p class="section-kicker">02 / ORCHESTRATE</p>
            <h2>任务编排</h2>
          </div>
          <button v-if="job && !isTerminal" class="icon-button" type="button" title="立即刷新状态" @click="refreshJob">↻</button>
        </div>

        <div v-if="!workflow" class="empty-state">
          <span class="empty-mark">◎</span>
          <p>创建任务后，这里会解释模型选择、成本和审批状态。</p>
        </div>

        <template v-else>
          <div v-if="workflow.selection" class="selection-card">
            <p class="card-label">模型路由</p>
            <strong>{{ workflow.selection.model_id }}</strong>
            <span>预估 ${{ workflow.selection.estimated_cost_usd.toFixed(2) }}</span>
            <p>{{ workflow.selection.reason }}</p>
          </div>

          <div v-if="workflow.status === 'awaiting_human_review'" class="approval-card">
            <p class="card-label">人工审批需要确认</p>
            <h3>该任务超过自动执行额度。</h3>
            <p>{{ workflow.interrupt?.budget_reason }}</p>
            <textarea v-model="approvalFeedback" rows="3" placeholder="可选：记录本次审批原因"></textarea>
            <div class="button-row">
              <button class="primary" :disabled="isApproving" type="button" @click="resolveApproval('approve')">确认生成</button>
              <button class="secondary" :disabled="isApproving" type="button" @click="resolveApproval('reject')">拒绝</button>
            </div>
          </div>

          <div v-if="job" class="job-card">
            <div class="status-line">
              <span class="status-dot" :class="job.status"></span>
              <strong>{{ job.status }}</strong>
              <small v-if="isPolling">自动刷新中</small>
            </div>
            <dl>
              <div><dt>任务 ID</dt><dd>{{ job.job_id }}</dd></div>
              <div><dt>Provider</dt><dd>{{ job.provider }}</dd></div>
              <div><dt>预估成本</dt><dd>${{ job.cost.estimated_usd.toFixed(2) }}</dd></div>
            </dl>
            <p v-if="job.status === 'failed'" class="error-box">
              {{ job.failure_code || "Provider 失败" }}：{{ job.failure_message || "未返回具体原因。" }}
            </p>
          </div>
        </template>
      </aside>
    </section>

    <section class="panel output-panel">
      <div class="panel-heading">
        <div>
          <p class="section-kicker">03 / REVIEW</p>
          <h2>视频验收</h2>
        </div>
        <a v-if="job?.output_url" class="download-link" :href="job.output_url" target="_blank" rel="noreferrer">打开 / 下载视频 ↗</a>
      </div>

      <div v-if="job?.status === 'completed' && job.output_url" class="completed-output">
        <video class="video-player" :src="job.output_url" controls playsinline></video>
        <form class="review-form" @submit.prevent="submitReview">
          <p class="card-label">人工质量验收</p>
          <label class="toggle"><input v-model="review.accepted" type="checkbox" /> <span>接受该视频输出</span></label>
          <label><span>视觉质量（1–5）</span><input v-model.number="review.visual_quality_score" type="number" min="1" max="5" /></label>
          <label><span>提示词一致性（1–5）</span><input v-model.number="review.prompt_alignment_score" type="number" min="1" max="5" /></label>
          <label><span>验收反馈</span><textarea v-model="review.feedback" rows="3" placeholder="例如：雨夜氛围准确，但港口元素不足。"></textarea></label>
          <button class="primary" :disabled="isReviewing" type="submit">{{ isReviewing ? "保存中…" : "保存验收结果" }}</button>
          <p v-if="job.output_review" class="saved-review">已保存：{{ job.output_review.accepted ? "接受" : "拒绝" }} · 视觉 {{ job.output_review.visual_quality_score }}/5 · 一致性 {{ job.output_review.prompt_alignment_score }}/5</p>
        </form>
      </div>
      <div v-else class="empty-state output-empty">
        <span class="empty-mark">▷</span>
        <p>视频完成后将在这里播放，并可下载与提交质量验收。</p>
      </div>
    </section>
  </main>
</template>
