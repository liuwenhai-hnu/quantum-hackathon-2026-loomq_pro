import {
  ApiError,
  applyLlmConfig,
  generateExperiment,
  getLlmConfig,
  runExperiment,
  testLlmConfig,
} from "./api.js?v=api-session-1";
import { escapeMarkup, renderCircuit } from "./circuit.js?v=api-session-1";

function byId(id) {
  const element = document.getElementById(id);
  if (!element) throw new Error(`Missing required UI hook: #${id}`);
  return element;
}

const elements = {
  promptForm: byId("prompt-form"), prompt: byId("prompt"), promptError: byId("prompt-error"), promptStatus: byId("prompt-status"),
  generateButton: byId("generate-experiment"), generateLabel: byId("generate-label"),
  serviceNotice: byId("service-notice"),
  examples: byId("examples"), firstVisit: byId("first-visit"),
  workspace: byId("workspace"), workspaceStatus: byId("workspace-status"), workspaceTitle: byId("workspace-title"),
  backendMark: byId("backend-mark"), backendTitle: byId("backend-title"), backendReason: byId("backend-reason"),
  backendRecommendBadge: byId("backend-recommend-badge"), backendFacts: byId("backend-facts"),
  backendSummary: byId("backend-summary"), backendCapacity: byId("backend-capacity"),
  backendPicker: byId("backend-picker"), backendOptions: byId("backend-options"),
  tabs: [...document.querySelectorAll("[data-experiment-tab]")],
  circuitSvg: byId("circuit-svg"), stateOrder: byId("state-order"), circuitSteps: byId("circuit-steps"),
  gateQuickCard: byId("gate-quick-card"), gateQuickTitle: byId("gate-quick-title"),
  gateQuickTarget: byId("gate-quick-target"), gateQuickChange: byId("gate-quick-change"), gateQuickWhy: byId("gate-quick-why"),
  gateQuickExample: byId("gate-quick-example"), gateQuickExampleText: byId("gate-quick-example-text"),
  gateQuickExperiment: byId("gate-quick-experiment"), gateQuickExperimentText: byId("gate-quick-experiment-text"),
  gatePalette: byId("gate-palette"), gateWhitelistTrigger: byId("gate-whitelist-trigger"),
  gateWhitelistPopover: byId("gate-whitelist-popover"),
  gateCard: byId("gate-card"), gateCardConcept: byId("gate-card-concept"), gateCardTechnical: byId("gate-card-technical"),
  gateCardRule: byId("gate-card-rule"), gateCardTransition: byId("gate-card-transition"), gateCardBefore: byId("gate-card-before"),
  gateCardAfter: byId("gate-card-after"), gateCardCurrent: byId("gate-card-current"), gateCardWhy: byId("gate-card-why"),
  gateCardWithout: byId("gate-card-without"), gateMath: byId("gate-math"), gateMathLabel: byId("gate-math-label"),
  gateCardMath: byId("gate-card-math"), gateCardClose: byId("gate-card-close"), qasmCode: byId("qasm-code"),
  shots: byId("shots"), runButton: byId("run-experiment"), runLabel: byId("run-label"), runStatus: byId("run-status"),
  results: byId("results"), resultsTitle: byId("results-title"), resultSource: byId("result-source"),
  resultBackend: byId("result-backend"), resultShots: byId("result-shots"), resultElapsed: byId("result-elapsed"),
  resultChart: byId("result-chart"), resultBars: byId("result-bars"), resultSummary: byId("result-summary"),
  resultChartTitle: byId("result-chart-title"),
  resultMeaning: byId("result-meaning"), resultWhy: byId("result-why"), gateReferences: byId("gate-references"),
  resultBitOrder: byId("result-bit-order"), rawBitOrder: byId("raw-bit-order"), rawCounts: byId("raw-counts"),
  rawCountsDetails: byId("raw-counts-details"), chartShots: byId("chart-shots"), keyFormulas: byId("key-formulas"),
  previousCircuit: byId("previous-circuit"), circuitEmpty: byId("circuit-empty"), resultStatusText: byId("result-status-text"),
  apiStatusButton: byId("api-status-button"), apiStatusLabel: byId("api-status-label"), apiDialog: byId("api-dialog"),
  apiConfigForm: byId("api-config-form"), apiDialogClose: byId("api-dialog-close"), apiCancel: byId("api-cancel"),
  apiBaseUrl: byId("api-base-url"), apiKey: byId("api-key"), apiModel: byId("api-model"),
  apiTest: byId("api-test"), apiApply: byId("api-apply"), apiConfigMessage: byId("api-config-message"),
};

let generatedPrompt = null;
let generatedResponseType = null;
let activeExperiment = null;
let generationState = "idle";
let runState = "idle";
let pinnedOperationIndex = null;
let availableBackends = [];
let recommendedBackendId = null;
let selectedBackendId = null;
let backendRecommendationReason = "";
let llmStatus = "loading";
let apiTestPassed = false;

setGenerationState("idle");
initializeEmptyState();
initializeLlmConfig();

elements.apiStatusButton.addEventListener("click", openApiDialog);
elements.apiDialogClose.addEventListener("click", closeApiDialog);
elements.apiCancel.addEventListener("click", closeApiDialog);
elements.apiDialog.addEventListener("click", (event) => {
  if (event.target === elements.apiDialog) closeApiDialog();
});

[elements.apiBaseUrl, elements.apiKey, elements.apiModel].forEach((input) => {
  input.addEventListener("input", () => {
    apiTestPassed = false;
    elements.apiApply.disabled = true;
    setApiConfigMessage("配置已修改，请重新测试连接。", "idle");
  });
});

elements.apiTest.addEventListener("click", handleApiTest);
elements.apiConfigForm.addEventListener("submit", handleApiApply);

function setGateWhitelistOpen(open) {
  elements.gateWhitelistPopover.hidden = !open;
  elements.gateWhitelistTrigger.setAttribute("aria-expanded", String(open));
}

elements.gateWhitelistTrigger.addEventListener("click", () => {
  setGateWhitelistOpen(elements.gateWhitelistPopover.hidden);
});

document.addEventListener("click", (event) => {
  if (!elements.gateWhitelistPopover.hidden && !elements.gatePalette.contains(event.target)) {
    setGateWhitelistOpen(false);
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !elements.gateWhitelistPopover.hidden) {
    setGateWhitelistOpen(false);
    elements.gateWhitelistTrigger.focus();
  }
});

function readApiPreferences() {
  try {
    return {
      baseUrl: localStorage.getItem("loomq_llm_base_url") || "https://api.deepseek.com",
      model: localStorage.getItem("loomq_llm_model") || "deepseek-v4-flash",
    };
  } catch {
    return { baseUrl: "https://api.deepseek.com", model: "deepseek-v4-flash" };
  }
}

function saveApiPreferences(baseUrl, model) {
  try {
    localStorage.setItem("loomq_llm_base_url", baseUrl);
    localStorage.setItem("loomq_llm_model", model);
  } catch {
    // Non-sensitive preferences are optional; the API key is never persisted here.
  }
}

function setApiStatus(status, message = "") {
  llmStatus = status;
  elements.apiStatusButton.classList.remove("is-loading", "is-connected", "is-error");

  if (status === "connected") {
    elements.apiStatusButton.classList.add("is-connected");
    elements.apiStatusLabel.textContent = "API 已连接";
  } else if (status === "error" || status === "service-error") {
    elements.apiStatusButton.classList.add("is-error");
    elements.apiStatusLabel.textContent = "API 异常";
  } else if (status === "loading") {
    elements.apiStatusButton.classList.add("is-loading");
    elements.apiStatusLabel.textContent = "检查 API…";
  } else {
    elements.apiStatusLabel.textContent = "连接 API";
  }

  const serviceProblem = status === "service-error";
  elements.serviceNotice.hidden = !serviceProblem;
  elements.serviceNotice.textContent = serviceProblem ? message : "";
  elements.apiStatusButton.title = message;
  updateControlAvailability();
}

function setApiConfigMessage(message, state = "idle") {
  elements.apiConfigMessage.textContent = message;
  elements.apiConfigMessage.classList.toggle("is-success", state === "success");
  elements.apiConfigMessage.classList.toggle("is-error", state === "error");
  elements.apiConfigMessage.classList.toggle("is-testing", state === "testing");
}

async function initializeLlmConfig() {
  const preferences = readApiPreferences();
  elements.apiBaseUrl.value = preferences.baseUrl;
  elements.apiModel.value = preferences.model;

  if (window.location.protocol === "file:") {
    const message = "LoomQ Product Service 未连接。请通过 http://127.0.0.1:4173/ 打开 Playground。";
    setApiStatus("service-error", message);
    setApiConfigMessage(message, "error");
    return;
  }

  try {
    const config = await getLlmConfig();
    if (config.configured && config.connected) {
      elements.apiBaseUrl.value = config.base_url || preferences.baseUrl;
      elements.apiModel.value = config.model || preferences.model;
      setApiStatus("connected", "当前浏览器会话已连接 LLM API。");
    } else if (config.configured) {
      elements.apiBaseUrl.value = config.base_url || preferences.baseUrl;
      elements.apiModel.value = config.model || preferences.model;
      setApiStatus("error", "当前 API 配置最近一次调用失败，请重新测试连接。");
    } else {
      setApiStatus("unconfigured", "生成实验前，请连接自己的 OpenAI-compatible API。");
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : "LoomQ Product Service 未连接。";
    setApiStatus("service-error", message);
    setApiConfigMessage(message, "error");
  }
}

function openApiDialog() {
  apiTestPassed = false;
  elements.apiApply.disabled = true;
  elements.apiKey.value = "";
  if (llmStatus === "connected") {
    setApiConfigMessage("当前会话已连接。若要更换 API，请填写新 Key 并重新测试。", "success");
  } else if (llmStatus === "service-error") {
    setApiConfigMessage("LoomQ Product Service 未连接。请通过 http://127.0.0.1:4173/ 打开 Playground。", "error");
  } else {
    setApiConfigMessage("填写后先测试连接，再应用到当前会话。", "idle");
  }
  elements.apiDialog.showModal();
}

function closeApiDialog() {
  elements.apiKey.value = "";
  if (elements.apiDialog.open) elements.apiDialog.close();
}

function currentApiFormConfig() {
  return {
    base_url: elements.apiBaseUrl.value.trim(),
    api_key: elements.apiKey.value,
    model: elements.apiModel.value.trim(),
  };
}

async function handleApiTest() {
  if (!elements.apiConfigForm.reportValidity()) return;
  const config = currentApiFormConfig();
  apiTestPassed = false;
  elements.apiApply.disabled = true;
  elements.apiTest.disabled = true;
  setApiConfigMessage("正在进行一次真实的最小调用…", "testing");

  try {
    const result = await testLlmConfig(config);
    apiTestPassed = Boolean(result.connected);
    elements.apiApply.disabled = !apiTestPassed;
    saveApiPreferences(config.base_url, config.model);
    setApiConfigMessage(result.message || "连接测试成功，可以应用此配置。", "success");
  } catch (error) {
    const message = error instanceof Error ? error.message : "连接测试失败。";
    setApiConfigMessage(message, "error");
    if (error instanceof ApiError && error.code === "product_service_unavailable") {
      setApiStatus("service-error", message);
    } else {
      setApiStatus("error", message);
    }
  } finally {
    elements.apiTest.disabled = false;
  }
}

async function handleApiApply(event) {
  event.preventDefault();
  if (!apiTestPassed) {
    setApiConfigMessage("请先测试连接。", "error");
    return;
  }

  elements.apiApply.disabled = true;
  try {
    const config = await applyLlmConfig();
    saveApiPreferences(config.base_url, config.model);
    setApiStatus("connected", "当前浏览器会话已连接 LLM API。");
    closeApiDialog();
  } catch (error) {
    const message = error instanceof Error ? error.message : "应用 API 配置失败。";
    setApiConfigMessage(message, "error");
    setApiStatus(error instanceof ApiError && error.code === "product_service_unavailable" ? "service-error" : "error", message);
  } finally {
    elements.apiApply.disabled = !apiTestPassed;
  }
}

function initializeEmptyState() {
  elements.workspace.classList.add("is-empty");
  elements.results.classList.add("is-empty");
  elements.resultBars.classList.remove("is-dense");
  elements.resultChartTitle.textContent = "测量结果";
  elements.resultBars.innerHTML = '<p class="chart-empty">暂无测量数据</p>';
}

function fillPromptFromTrigger(trigger) {
  elements.prompt.value = trigger.dataset.prompt;
  elements.promptError.hidden = true;
  updateDirtyState();
  elements.prompt.focus();
}

elements.examples.addEventListener("click", (event) => {
  const card = event.target.closest("[data-example]");
  if (!card) return;
  fillPromptFromTrigger(card);
});

elements.firstVisit.addEventListener("click", () => fillPromptFromTrigger(elements.firstVisit));

elements.prompt.addEventListener("input", updateDirtyState);

elements.promptForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const prompt = elements.prompt.value.trim();

  if (!prompt) {
    elements.promptError.hidden = false;
    elements.prompt.focus();
    return;
  }

  elements.promptError.hidden = true;
  setGenerationState("generating");
  clearRunResult();

  try {
    const generated = await generateExperiment(prompt);
    if (generated.response_type === "backend_recommendation") {
      generatedPrompt = prompt;
      generatedResponseType = "backend_recommendation";
      renderBackendChooser(generated.backends || [], generated.backend_recommendation || {});
      elements.workspace.hidden = false;
      setGenerationState("backend-ready", generated.message);
      setRunState(activeExperiment ? "ready" : "idle");
      elements.workspace.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    const experiment = generated.experiment;
    activeExperiment = experiment;
    generatedPrompt = prompt;
    generatedResponseType = "experiment";
    renderExperiment(experiment);
    elements.workspace.hidden = false;
    selectTab("circuit-tab");
    setGenerationState("ready");
    setRunState("ready");
    elements.workspace.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    const message = error instanceof Error ? error.message : "生成实验失败，请稍后重试。";
    setGenerationState("error", message);
    if (error instanceof ApiError) {
      if (error.code === "product_service_unavailable") setApiStatus("service-error", message);
      else if (error.code === "llm_not_configured") setApiStatus("unconfigured", message);
      else if (["invalid_api_key", "model_unavailable", "rate_limited", "llm_timeout", "base_url_unreachable", "llm_call_failed"].includes(error.code)) setApiStatus("error", message);
    }
  }
});

elements.tabs.forEach((tab) => {
  tab.addEventListener("click", () => selectTab(tab.id));
});

elements.backendOptions.addEventListener("change", (event) => {
  const radio = event.target.closest("[data-backend-option]");
  if (!radio || radio.value === selectedBackendId) return;
  selectedBackendId = radio.value;
  renderSelectedBackend();
  clearRunResult();
  setRunState("ready");
});

elements.circuitSvg.addEventListener("pointerover", (event) => {
  const operationElement = event.target.closest("[data-operation-index]");
  if (!operationElement || pinnedOperationIndex !== null) return;
  showQuickGateCard(Number(operationElement.dataset.operationIndex));
});

elements.circuitSvg.addEventListener("pointerout", (event) => {
  if (pinnedOperationIndex !== null) return;
  const operationElement = event.target.closest("[data-operation-index]");
  if (!operationElement || operationElement.contains(event.relatedTarget)) return;
  hideQuickGateCard();
});

elements.circuitSvg.addEventListener("focusin", (event) => {
  const operationElement = event.target.closest("[data-operation-index]");
  if (operationElement && pinnedOperationIndex === null) showQuickGateCard(Number(operationElement.dataset.operationIndex));
});

elements.circuitSvg.addEventListener("focusout", (event) => {
  if (pinnedOperationIndex !== null) return;
  const operationElement = event.target.closest("[data-operation-index]");
  if (!operationElement || operationElement.contains(event.relatedTarget)) return;
  hideQuickGateCard();
});

elements.circuitSvg.addEventListener("click", (event) => {
  const operationElement = event.target.closest("[data-operation-index]");
  if (!operationElement) return;
  openGateCard(Number(operationElement.dataset.operationIndex));
});

elements.circuitSvg.addEventListener("keydown", (event) => {
  if (!['Enter', ' '].includes(event.key)) return;
  const operationElement = event.target.closest("[data-operation-index]");
  if (!operationElement) return;
  event.preventDefault();
  openGateCard(Number(operationElement.dataset.operationIndex));
});

elements.gateCardClose.addEventListener("click", () => {
  pinnedOperationIndex = null;
  hideGateCard();
  hideQuickGateCard();
});

elements.gateReferences.addEventListener("click", (event) => {
  const button = event.target.closest("[data-gate-ref]");
  if (!button) return;
  focusOperation(Number(button.dataset.gateRef));
});

elements.shots.addEventListener("change", normalizeShots);
elements.shots.addEventListener("blur", normalizeShots);

elements.previousCircuit.addEventListener("click", () => {
  elements.runStatus.textContent = "当前演示版本不保存电路历史。";
});

elements.runButton.addEventListener("click", async () => {
  if (!activeExperiment || !["ready", "backend-ready"].includes(generationState) || runState === "running") return;

  const shots = normalizeShots();
  setRunState("running");

  try {
    const result = await runExperiment(activeExperiment.qasm, shots, selectedBackendId);
    renderRunResult(activeExperiment, result);
    setRunState("success");
    elements.results.hidden = false;
    elements.results.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    setRunState("error", error instanceof Error ? error.message : "实验运行失败，请稍后重试。");
  }
});

function selectTab(tabId) {
  elements.tabs.forEach((tab) => {
    const selected = tab.id === tabId;
    tab.setAttribute("aria-selected", String(selected));
    byId(tab.dataset.panelId).hidden = !selected;
  });
}

function normalizeShots() {
  const parsed = Number.parseInt(elements.shots.value, 10);
  const safeValue = Number.isFinite(parsed) ? parsed : 1000;
  const clamped = Math.min(8192, Math.max(100, safeValue));
  elements.shots.value = String(clamped);
  return clamped;
}

function updateDirtyState() {
  if (generationState === "generating") return;
  const prompt = elements.prompt.value.trim();

  if (!prompt && !activeExperiment) {
    setGenerationState("idle");
  } else if (prompt === generatedPrompt && generatedResponseType === "backend_recommendation") {
    setGenerationState("backend-ready", "已完成后端推荐，本次未生成新电路。");
  } else if (activeExperiment && prompt === generatedPrompt) {
    setGenerationState("ready");
  } else {
    setGenerationState("dirty");
  }
}

function setGenerationState(state, message = "") {
  generationState = state;
  elements.promptForm.dataset.state = state;
  elements.promptStatus.classList.remove("is-generating", "is-error");
  elements.workspace.classList.remove("is-stale", "is-generating");
  const generating = state === "generating";
  elements.generateLabel.textContent = generating ? "正在生成…" : "生成实验";

  if (state === "idle") {
    elements.promptStatus.hidden = true;
  } else if (state === "dirty") {
    elements.promptStatus.hidden = false;
    elements.promptStatus.textContent = activeExperiment
      ? "实验描述已修改，点击「生成实验」更新下方方案"
      : "实验描述已准备好，点击「生成实验」创建方案";
    if (activeExperiment) {
      elements.workspace.classList.add("is-stale");
      elements.workspaceStatus.textContent = "上一版已生成方案";
    }
  } else if (state === "generating") {
    elements.promptStatus.hidden = false;
    elements.promptStatus.classList.add("is-generating");
    elements.promptStatus.textContent = "正在调用真实 L2，并使用现有 L1 parser/IR 校验电路…";
    if (activeExperiment) {
      elements.workspace.classList.add("is-generating");
      elements.workspaceStatus.textContent = "正在生成新方案…";
    }
  } else if (state === "ready") {
    elements.promptStatus.hidden = true;
    elements.workspaceStatus.textContent = "真实 L2 方案";
  } else if (state === "backend-ready") {
    elements.promptStatus.hidden = false;
    elements.promptStatus.textContent = message || "已完成后端推荐，本次未生成新电路。";
    elements.workspaceStatus.textContent = activeExperiment ? "上一轮电路 · 本次仅推荐后端" : "本次仅推荐后端";
  } else if (state === "error") {
    elements.promptStatus.hidden = false;
    elements.promptStatus.classList.add("is-error");
    elements.promptStatus.textContent = message;
    if (activeExperiment) {
      elements.workspace.classList.add("is-stale");
      elements.workspaceStatus.textContent = "上一版已生成方案";
    }
  }

  updateControlAvailability();
}

function setRunState(state, message = "") {
  runState = state;
  elements.workspace.dataset.runState = state;
  elements.runStatus.classList.remove("is-running", "is-error", "is-success");
  elements.runLabel.textContent = state === "running" ? "Running…" : "Run Experiment";
  const backendName = getSelectedBackend()?.name || "所选本地模拟器";

  if (state === "idle") {
    elements.runStatus.textContent = "生成实验后即可在本地模拟器运行。";
  } else if (state === "ready") {
    elements.runStatus.textContent = `QASM 已就绪，可在 ${backendName} 上运行。`;
  } else if (state === "running") {
    elements.runStatus.classList.add("is-running");
    elements.runStatus.textContent = `正在 ${backendName} 上运行…`;
  } else if (state === "success") {
    elements.runStatus.classList.add("is-success");
    elements.runStatus.textContent = "实验运行完成。";
  } else if (state === "error") {
    elements.runStatus.classList.add("is-error");
    elements.runStatus.textContent = message;
  }

  updateControlAvailability();
}

function updateControlAvailability() {
  const locked = generationState === "generating" || runState === "running";
  const apiReady = llmStatus === "connected";
  elements.generateButton.disabled = locked || !apiReady;
  elements.generateButton.title = apiReady ? "" : "请先通过右上角连接自己的 LLM API";
  elements.prompt.readOnly = locked;
  elements.examples.querySelectorAll("[data-example]").forEach((button) => { button.disabled = locked; });
  elements.firstVisit.disabled = locked;
  elements.shots.disabled = runState === "running";
  elements.backendOptions.querySelectorAll("[data-backend-option]").forEach((input) => { input.disabled = locked; });
  elements.runButton.disabled = !["ready", "backend-ready"].includes(generationState) || !activeExperiment || !selectedBackendId || runState === "running";
}

function clearRunResult() {
  elements.results.hidden = false;
  elements.results.classList.add("is-empty");
  elements.resultsTitle.textContent = "等待运行结果";
  elements.resultStatusText.textContent = "尚未运行实验";
  elements.resultBars.classList.remove("is-dense");
  elements.resultChartTitle.textContent = "测量结果";
  elements.resultBars.innerHTML = '<p class="chart-empty">暂无测量数据</p>';
  elements.rawCounts.textContent = "";
  elements.resultSummary.textContent = "运行后会根据真实 counts 总结测量现象。";
  elements.resultSource.textContent = "生成电路并运行后，结果会显示在这里。";
  elements.resultMeaning.textContent = "这里会把结果与当前电路联系起来。";
  elements.resultWhy.textContent = "";
  elements.gateReferences.replaceChildren();
  elements.rawCountsDetails.open = false;
  setRunState("idle");
}

function renderRunResult(experiment, result) {
  const observedEntries = Object.entries(result.counts)
    .filter(([, count]) => Number.isFinite(Number(count)))
    .map(([state, count]) => [state, Number(count)])
    .sort(([left], [right]) => left.localeCompare(right));

  if (!observedEntries.length) throw new Error("运行结果中没有有效 counts。");

  const countsByState = new Map(observedEntries);
  const displayOrder = experiment.circuit.num_clbits === 2
    ? ["00", "11", "01", "10"]
    : observedEntries.map(([state]) => state);
  const hasHighCardinality = observedEntries.length > 16;
  const weightGroups = hasHighCardinality
    ? observedEntries.reduce((groups, [state, count]) => {
      const ones = [...state].filter((bit) => bit === "1").length;
      groups.set(ones, (groups.get(ones) || 0) + count);
      return groups;
    }, new Map())
    : null;
  const entries = hasHighCardinality
    ? Array.from({ length: experiment.circuit.num_clbits + 1 }, (_, ones) => [ones, weightGroups.get(ones) || 0])
    : displayOrder.map((state) => [state, countsByState.get(state) || 0]);
  const totalCounts = observedEntries.reduce((sum, [, count]) => sum + count, 0);
  const shots = Number(result.shots);
  const highestClassicalBit = Math.max(0, experiment.circuit.num_clbits - 1);
  const bitOrderNote = `结果位序：c${highestClassicalBit}...c0，c0 在最右侧`;
  elements.results.classList.remove("is-empty");
  elements.resultsTitle.textContent = "测量结果";
  elements.resultStatusText.textContent = "实验运行完成";
  const backendName = result.backend_name || getSelectedBackend()?.name || result.backend;
  elements.resultBackend.textContent = backendName;
  elements.resultSource.textContent = `结果来自 ${backendName}。`;
  elements.resultShots.textContent = shots.toLocaleString("zh-CN");
  elements.chartShots.textContent = shots.toLocaleString("zh-CN");
  elements.resultElapsed.textContent = `${Number(result.elapsed_seconds).toFixed(3)} s`;
  elements.resultBitOrder.textContent = hasHighCardinality
    ? `${bitOrderNote} · 状态较多，横轴按每次结果中“1”的数量汇总`
    : bitOrderNote;
  elements.resultChartTitle.textContent = hasHighCardinality ? "测量结果概览 · 1 的数量分布" : "测量结果";
  elements.rawBitOrder.textContent = bitOrderNote;
  elements.rawCounts.textContent = JSON.stringify(result.counts, null, 2);
  elements.resultBars.classList.toggle("is-dense", hasHighCardinality);
  elements.resultChart.setAttribute("aria-label", entries.map(([state, count]) => hasHighCardinality ? `包含 ${state} 个 1 的结果为 ${count} 次` : `${state} 为 ${count} 次`).join("，"));
  elements.resultBars.innerHTML = entries.map(([state, count], index) => {
    const percentage = shots > 0 ? (count / shots) * 100 : 0;
    const tooltip = hasHighCardinality
      ? `包含 ${state} 个 1 · ${count} 次 · ${percentage.toFixed(1)}%`
      : `${state} · ${count} 次 · ${percentage.toFixed(1)}%`;
    return `<div class="bar-item" tabindex="0" data-chart-tooltip="${escapeMarkup(tooltip)}"><strong>${percentage.toFixed(1)}%</strong><div class="bar${index % 2 ? " alt" : ""}" style="--height:${percentage.toFixed(2)}%"></div><span>${escapeMarkup(state)}</span></div>`;
  }).join("");

  const ranked = [...observedEntries].sort(([, left], [, right]) => right - left);
  if (ranked.length === 1) {
    elements.resultSummary.textContent = `本次 ${totalCounts} 次有效测量都得到 ${ranked[0][0]}。`;
  } else {
    const [[firstState, firstCount], [secondState, secondCount]] = ranked;
    const topShare = shots > 0 ? (firstCount + secondCount) / shots : 0;
    elements.resultSummary.textContent = topShare >= 0.8
      ? `测量结果主要集中在 ${firstState}（${firstCount} 次）和 ${secondState}（${secondCount} 次）。`
      : `出现次数最多的是 ${firstState}（${firstCount} 次），其次是 ${secondState}（${secondCount} 次）。`;
  }

  const explanation = experiment.result_explanation || {};
  elements.resultMeaning.textContent = explanation.meaning || "这些柱子展示不同测量结果在本次重复运行中的出现频率。";
  elements.resultWhy.textContent = explanation.why || "电路中的门依次改变状态，Measure 最后把状态转换成可统计的经典结果。";
  elements.keyFormulas.hidden = experiment.kind !== "bell";
  const operationsByIndex = new Map(experiment.circuit.operations.map((operation) => [operation.index, operation]));
  elements.gateReferences.innerHTML = (explanation.gate_refs || []).map((index) => {
    const operation = operationsByIndex.get(index);
    if (!operation) return "";
    const label = operation.type === "measure" ? "Measure" : operation.gate.toUpperCase();
    return `<button type="button" data-gate-ref="${index}">回看 ${escapeMarkup(label)}</button>`;
  }).join("");
}

function renderExperiment(experiment) {
  pinnedOperationIndex = null;
  hideGateCard();
  hideQuickGateCard();
  elements.workspace.classList.remove("is-empty");
  elements.workspaceTitle.textContent = experiment.kind === "bell" ? "Bell 态实验" : experiment.title;
  elements.qasmCode.textContent = experiment.qasm;
  renderBackendChooser(experiment.backends || [], experiment.backend_recommendation || {});
  renderCircuit(experiment, { svg: elements.circuitSvg, stateOrder: elements.stateOrder });
  renderSteps(experiment.steps);
}

function renderBackendChooser(backends, recommendation) {
  availableBackends = backends;
  recommendedBackendId = recommendation.backend_id || null;
  selectedBackendId = recommendedBackendId || backends[0]?.id || null;
  backendRecommendationReason = recommendation.reason || "";
  elements.backendOptions.innerHTML = backends.map((backend) => `
    <label class="backend-option">
      <input type="radio" name="backend" data-backend-option value="${escapeMarkup(backend.id)}"${backend.id === selectedBackendId ? " checked" : ""} />
      <span class="backend-option-copy">
        <strong>${escapeMarkup(backend.name)}</strong>
        <small>${escapeMarkup(backend.kind_label)} · 最大 ${backend.max_qubits} qubits · ${escapeMarkup(backend.queue_label)} · ${escapeMarkup(backend.cost_label)} · ${backend.requires_account ? "需要账号" : "无需账号"}</small>
      </span>
      ${backend.id === recommendedBackendId ? '<span class="recommend">AI 推荐</span>' : ""}
    </label>
  `).join("");
  elements.backendPicker.open = false;
  elements.backendPicker.hidden = backends.length === 0;
  renderSelectedBackend();
}

function renderSelectedBackend() {
  const backend = getSelectedBackend();
  if (!backend) return;
  const isRecommended = Boolean(recommendedBackendId && backend.id === recommendedBackendId);
  const recommended = availableBackends.find((item) => item.id === recommendedBackendId);
  elements.backendMark.textContent = backend.platform;
  elements.backendTitle.textContent = backend.name;
  elements.backendRecommendBadge.textContent = isRecommended ? "AI 推荐" : (recommendedBackendId ? "手动选择" : "可用后端");
  elements.backendRecommendBadge.classList.toggle("is-manual", !isRecommended);
  const accountLabel = backend.requires_account ? "需要账号" : "无需账号";
  elements.backendSummary.textContent = `${backend.kind_label} · ${backend.cost_label} · ${accountLabel} · ${backend.queue_label}`;
  elements.backendCapacity.textContent = `最大 ${backend.max_qubits} 量子比特${backend.notes ? ` · ${backend.notes}` : ""}`;
  elements.backendReason.textContent = isRecommended
    ? backendRecommendationReason
    : (recommendedBackendId
      ? `你已手动选择该后端。AI 推荐仍是 ${recommended?.name || "另一可用后端"}，但不会强制切换。`
      : backendRecommendationReason);
  elements.backendFacts.innerHTML = `
    <div><dt>类型</dt><dd>${escapeMarkup(backend.kind_label)}</dd></div>
    <div><dt>最大量子比特</dt><dd>${backend.max_qubits}</dd></div>
    <div><dt>排队</dt><dd>${escapeMarkup(backend.queue_label)}</dd></div>
    <div><dt>费用</dt><dd>${escapeMarkup(backend.cost_label)}</dd></div>
    <div><dt>账号</dt><dd>${accountLabel}</dd></div>
  `;
}

function getSelectedBackend() {
  return availableBackends.find((backend) => backend.id === selectedBackendId) || null;
}

function renderSteps(steps) {
  elements.circuitSteps.innerHTML = steps.map((step) => {
    const operationAttribute = Number.isInteger(step.operation_index)
      ? ` data-step-operation="${step.operation_index}"`
      : "";
    const basisHelp = (step.basis_help || []).length
      ? `<div class="basis-help"><span>这些状态表示</span>${step.basis_help.map((item) => `<code>${escapeMarkup(item)}</code>`).join("")}</div>`
      : "";
    const simpleState = step.show_simple_state && step.after_state
      ? step.before_state
        ? `<div class="trace-state-flow"><div><span>这一步之前</span><code>${escapeMarkup(step.before_state)}</code></div><b aria-hidden="true">→</b><div><span>这一步之后</span><code>${escapeMarkup(step.after_state)}</code></div></div>`
        : `<div class="trace-initial-state"><span>当前状态</span><code>${escapeMarkup(step.after_state)}</code></div>`
      : "";
    const measurementContext = step.measurement_analysis
      ? measurementAnalysisMarkup(step.measurement_analysis)
      : "";
    const concreteDetail = `
      <details class="trace-detail">
        <summary>看看具体发生了什么</summary>
        <div class="trace-detail-body">
          <div class="trace-technical"><span>当前操作</span><code>${escapeMarkup(step.technical || step.concept || "")}</code></div>
          <p class="simple-change">${escapeMarkup(step.simple_change || step.change || "")}</p>
          ${measurementContext}
          ${simpleState}
          ${basisHelp}
        </div>
      </details>`;
    const math = step.math_detail;
    const mathStates = math && (math.before_state || math.after_state)
      ? `<div class="trace-math-states">
          ${math.before_state ? `<div><span>完整 statevector · 之前</span><code>${escapeMarkup(math.before_state)}</code></div>` : ""}
          ${math.after_state ? `<div><span>完整 statevector · 之后</span><code>${escapeMarkup(math.after_state)}</code></div>` : ""}
        </div>`
      : "";
    const mathDetail = math
      ? `<details class="trace-detail trace-math-detail">
          <summary>看看数学怎么算</summary>
          <div class="trace-detail-body">
            ${mathStates}
            ${math.gate_math ? gateMathMarkup(math.gate_math) : ""}
            <p class="trace-math-note">${escapeMarkup(math.note || "")}</p>
            ${basisHelp}
          </div>
        </details>`
      : "";

    return `
      <li class="trace-step trace-${escapeMarkup(step.trace_mode || "fallback")}"${operationAttribute}>
        <span class="step-number">${step.index}</span>
        <div class="trace-content">
          <div class="trace-heading"><strong>${escapeMarkup(step.purpose || step.title)}</strong></div>
          <p class="trace-explanation">${escapeMarkup(step.explanation || step.description || "")}</p>
          <div class="intuitive-example"><span>当前实验里的直观例子</span><p>${escapeMarkup(step.intuitive_example || step.simple_change || "")}</p></div>
          <div class="trace-disclosures">${concreteDetail}${mathDetail}</div>
        </div>
      </li>`;
  }).join("");
}

function measurementAnalysisMarkup(analysis) {
  const qubitRows = (analysis.qubits || [])
    .map((row) => `<li>${escapeMarkup(row.text)}</li>`)
    .join("");
  const counts = (analysis.predicted_counts || [])
    .map((item) => `<span><code>${escapeMarkup(item.result)}</code> 约 ${escapeMarkup(item.percent)}</span>`)
    .join("");
  return `
    <div class="measurement-analysis">
      <div class="measurement-orders">
        <span>量子态顺序：<code>${escapeMarkup(analysis.state_order)}</code></span>
        <span>结果位序：<code>${escapeMarkup(analysis.result_order)}</code>，c0 在最右侧</span>
      </div>
      <p>${escapeMarkup(analysis.measured_summary)}</p>
      ${qubitRows ? `<ul>${qubitRows}</ul>` : ""}
      ${counts ? `<div class="predicted-counts"><strong>由测量前 statevector 推得</strong>${counts}</div>` : ""}
    </div>`;
}

function getOperation(operationIndex) {
  return activeExperiment?.circuit.operations.find((item) => item.index === operationIndex);
}

function operationTarget(operation) {
  if (operation.type === "measure") return `q${operation.qubit} → c${operation.cbit}`;
  return operation.qubits.map((qubit) => `q${qubit}`).join(" → ");
}

function highlightOperation(operationIndex) {
  elements.circuitSvg.querySelectorAll("[data-operation-index]").forEach((element) => {
    element.classList.toggle("is-highlighted", Number(element.dataset.operationIndex) === operationIndex);
  });
}

function showQuickGateCard(operationIndex) {
  const operation = getOperation(operationIndex);
  if (!operation?.gate_card) return;
  const card = operation.gate_card;
  const current = card.current;
  const isCx = operation.type === "gate" && operation.gate === "cx";
  const isBellCx = isCx && activeExperiment?.kind === "bell";
  highlightOperation(operationIndex);
  elements.gateQuickCard.classList.toggle("is-cx", isCx);
  elements.gateQuickTitle.textContent = isCx ? "CX · 受控非门" : card.concept;
  elements.gateQuickTarget.textContent = operationTarget(operation);
  elements.gateQuickChange.textContent = isCx
    ? "q0=0 时 q1 保持不变；q0=1 时 q1 翻转"
    : operation.intuitive_example || current.explanation;
  elements.gateQuickExample.hidden = !isCx;
  elements.gateQuickExperiment.hidden = !isBellCx || current.mode !== "exact";
  elements.gateQuickExampleText.textContent = isCx ? "00 → 00　　　　　10 → 11" : "";
  elements.gateQuickExperimentText.textContent = isBellCx && current.mode === "exact"
    ? `${current.before} → ${current.after}`
    : "";
  elements.gateQuickWhy.textContent = card.why;
  elements.gateQuickCard.hidden = false;
}

function hideQuickGateCard() {
  elements.gateQuickCard.hidden = true;
  if (pinnedOperationIndex === null) highlightOperation(-1);
}

function openGateCard(operationIndex) {
  const operation = getOperation(operationIndex);
  if (!operation?.gate_card) return;
  pinnedOperationIndex = operationIndex;
  hideQuickGateCard();
  highlightOperation(operationIndex);
  const card = operation.gate_card;
  const current = card.current;
  elements.gateCardConcept.textContent = card.concept;
  elements.gateCardTechnical.textContent = card.technical;
  elements.gateCardRule.textContent = card.rule;
  elements.gateCardTransition.hidden = current.mode !== "exact";
  elements.gateCardBefore.textContent = current.before || "";
  elements.gateCardAfter.textContent = current.after || "";
  elements.gateCardCurrent.textContent = current.explanation;
  elements.gateCardWhy.textContent = card.why;
  elements.gateCardWithout.textContent = card.without;
  elements.gateMathLabel.textContent = card.math.label;
  renderGateMath(card.math);
  elements.gateMath.open = false;
  elements.gateCard.hidden = false;
}

function renderGateMath(math) {
  elements.gateCardMath.innerHTML = gateMathMarkup(math);
}

function gateMathMarkup(math) {
  if (math.kind === "matrix" && Array.isArray(math.rows)) {
    const cells = math.rows.flat().map((cell) => `<span>${escapeMarkup(cell)}</span>`).join("");
    const notes = (math.notes || []).map((note) => `<li>${escapeMarkup(note)}</li>`).join("");
    const parameter = math.parameter ? `<p class="math-parameter">当前参数：θ = ${escapeMarkup(math.parameter)}</p>` : "";
    return `
      ${parameter}
      <div class="math-equation">
        <span class="math-symbol">${escapeMarkup(math.symbol || "U")}</span><span>=</span>
        ${math.coefficient ? `<span class="math-coefficient">${escapeMarkup(math.coefficient)} ·</span>` : ""}
        <span class="matrix-grid">${cells}</span>
      </div>
      ${notes ? `<ul class="math-notes">${notes}</ul>` : ""}
    `;
  }

  const lines = Array.isArray(math.lines)
    ? math.lines
    : String(math.content || "当前没有可可靠展示的数学形式。").split("\n");
  return `<div class="math-rule-lines">${lines.map((line) => `<code>${escapeMarkup(line)}</code>`).join("")}</div>`;
}

function hideGateCard() {
  elements.gateCard.hidden = true;
  highlightOperation(-1);
}

function focusOperation(operationIndex) {
  elements.workspace.hidden = false;
  selectTab("circuit-tab");
  elements.workspace.scrollIntoView({ behavior: "smooth", block: "start" });
  window.setTimeout(() => {
    const operationElement = elements.circuitSvg.querySelector(`[data-operation-index="${operationIndex}"]`);
    if (!operationElement) return;
    openGateCard(operationIndex);
    operationElement.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
    operationElement.focus({ preventScroll: true });
  }, 350);
}
