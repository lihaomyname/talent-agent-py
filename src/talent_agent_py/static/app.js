const API_PREFIX = "/api/v1";
const COOKIE_NAME = "authOpenIdToken";

const NODE_DEFINITIONS = [
  ["load_context", "加载上下文", "读取当前计划与会话消息"],
  ["parse_plan", "理解并生成计划", "LLM 生成 SearchPlanDraft / PlanPatch"],
  ["validate", "校验搜索条件", "检查支持范围、冲突与缺失信息"],
  ["clarify", "澄清关键信息", "条件不明确时等待用户选择"],
  ["resolve_entities", "解析业务实体", "将学历、公司、学校和城市转换为业务编码"],
  ["save_plan", "保存计划版本", "冻结本轮可执行的 SearchPlan"],
  ["search_candidates", "执行人才搜索", "调用招聘系统 eTalent 接口"],
  ["finalize", "整理搜索结果", "返回候选人卡片和分页引用"],
];

class TalentAgentPage {
  constructor() {
    this.sessionId = sessionStorage.getItem("talentAgentSessionId");
    this.userId = localStorage.getItem("talentAgentUserId") || "lihao";
    this.sessions = this.readSessions();
    this.busy = false;
    this.pendingImage = null;
    this.progressTimer = null;
    this.activeNodeIndex = -1;

    this.elements = {
      conversation: document.querySelector("#conversation"),
      welcome: document.querySelector("#welcome"),
      input: document.querySelector("#messageInput"),
      send: document.querySelector("#sendButton"),
      newSession: document.querySelector("#newSessionButton"),
      sessionList: document.querySelector("#sessionList"),
      connectionButton: document.querySelector("#connectionButton"),
      connectionDot: document.querySelector("#connectionDot"),
      connectionText: document.querySelector("#connectionText"),
      modal: document.querySelector("#configModal"),
      closeModal: document.querySelector("#closeModalButton"),
      userId: document.querySelector("#userIdInput"),
      cookie: document.querySelector("#cookieInput"),
      toggleSecret: document.querySelector("#toggleSecretButton"),
      saveConfig: document.querySelector("#saveConfigButton"),
      disconnect: document.querySelector("#disconnectButton"),
      configError: document.querySelector("#configError"),
      nodeTimeline: document.querySelector("#nodeTimeline"),
      runStatus: document.querySelector("#runStatus"),
      cancel: document.querySelector("#cancelButton"),
      requestToggle: document.querySelector("#requestToggle"),
      requestPreview: document.querySelector("#requestPreview"),
    };
  }

  async init() {
    this.elements.userId.value = this.userId;
    this.bindEvents();
    this.renderConnectionState();
    this.renderTimeline();
    await this.loadSessionHistory();
    const features = await this.api("/features").catch(() => ({}));
    if (features.images) this.installImageUpload();

    if (!this.isConnected()) {
      this.openConfig();
    } else if (this.sessionId) {
      this.restoreSession();
    }
  }

  bindEvents() {
    this.elements.connectionButton.addEventListener("click", () => this.openConfig());
    this.elements.closeModal.addEventListener("click", () => this.closeConfig());
    this.elements.modal.addEventListener("click", (event) => {
      if (event.target === this.elements.modal) this.closeConfig();
    });
    this.elements.toggleSecret.addEventListener("click", () => this.toggleSecret());
    this.elements.saveConfig.addEventListener("click", () => this.saveConfig());
    this.elements.disconnect.addEventListener("click", () => this.disconnect());
    this.elements.newSession.addEventListener("click", () => this.createNewSession());
    this.elements.send.addEventListener("click", () => this.sendCurrentMessage());
    this.elements.cancel.addEventListener("click", () => this.cancelRun());
    this.elements.requestToggle.addEventListener("click", () => {
      this.elements.requestToggle.closest(".request-section").classList.toggle("collapsed");
    });
    this.elements.input.addEventListener("input", () => this.resizeComposer());
    this.elements.input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        this.sendCurrentMessage();
      }
    });
    document.querySelectorAll("[data-example]").forEach((button) => {
      button.addEventListener("click", () => {
        this.elements.input.value = button.dataset.example;
        this.resizeComposer();
        this.elements.input.focus();
      });
    });
  }

  async api(path, options = {}) {
    const headers = {
      "X-User-Id": this.userId,
      ...(options.body && !(options.body instanceof FormData) ? {"Content-Type": "application/json"} : {}),
      ...(options.headers || {}),
    };
    const response = await fetch(`${API_PREFIX}${path}`, {
      credentials: "same-origin",
      ...options,
      headers,
    });
    const body = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(body?.message || body?.detail || `请求失败（${response.status}）`);
    }
    return body;
  }

  isConnected() {
    return document.cookie.split("; ").some((item) => item.startsWith(`${COOKIE_NAME}=`));
  }

  renderConnectionState() {
    const connected = this.isConnected();
    this.elements.connectionDot.classList.toggle("connected", connected);
    this.elements.connectionText.textContent = connected ? "招聘系统已连接" : "连接招聘系统";
  }

  openConfig() {
    this.elements.configError.textContent = "";
    this.elements.cookie.value = "";
    this.elements.modal.classList.remove("hidden");
    setTimeout(() => this.elements.cookie.focus(), 0);
  }

  closeConfig() {
    this.elements.modal.classList.add("hidden");
  }

  toggleSecret() {
    const isPassword = this.elements.cookie.type === "password";
    this.elements.cookie.type = isPassword ? "text" : "password";
    this.elements.toggleSecret.querySelector("i").className =
      isPassword ? "bi bi-eye-slash" : "bi bi-eye";
  }

  saveConfig() {
    let token = this.elements.cookie.value.trim();
    if (token.startsWith(`${COOKIE_NAME}=`)) {
      token = token.slice(COOKIE_NAME.length + 1);
    }
    const userId = this.elements.userId.value.trim();
    if (!userId) {
      this.elements.configError.textContent = "请输入用户 ID。";
      return;
    }
    if (!token || token.length > 4096 || token.includes(";")) {
      this.elements.configError.textContent = "请输入有效的 authOpenIdToken。";
      return;
    }

    // 不设置 Max-Age 或 Expires，因此浏览器关闭后 Cookie 自动失效。
    document.cookie = `${COOKIE_NAME}=${token}; Path=/; SameSite=Lax`;
    this.userId = userId;
    localStorage.setItem("talentAgentUserId", userId);
    this.renderConnectionState();
    this.closeConfig();
  }

  disconnect() {
    document.cookie = `${COOKIE_NAME}=; Path=/; Max-Age=0; SameSite=Lax`;
    this.renderConnectionState();
    this.closeConfig();
  }

  readSessions() {
    try {
      return JSON.parse(sessionStorage.getItem("talentAgentSessions") || "[]");
    } catch {
      return [];
    }
  }

  saveSessions() {
    sessionStorage.setItem("talentAgentSessions", JSON.stringify(this.sessions.slice(0, 8)));
  }

  async loadSessionHistory() {
    try {
      const sessions = await this.api("/sessions");
      this.sessions = sessions.map((session) => ({
        id: session.session_id,
        title: session.title,
        meta: this.sessionStatusText(session),
      }));
      this.saveSessions();
    } catch (error) {
      // 后端短暂不可用时保留本次浏览器会话中的缓存，避免侧栏突然变空。
      console.warn("历史会话加载失败", error);
    }
    this.renderSessions();
  }

  sessionStatusText(session) {
    const labels = {
      READY: "等待输入",
      OK: `搜索完成 · 计划 v${session.plan_version}`,
      EMPTY: `暂无结果 · 计划 v${session.plan_version}`,
      NEEDS_CLARIFICATION: "等待澄清",
      RUNNING: "正在搜索",
      QUEUED: "等待执行",
      FAILED: "执行失败",
      DENIED: "招聘系统未授权",
      MODEL_ERROR: "模型调用失败",
      DEPENDENCY_ERROR: "招聘系统调用失败",
      INTERNAL_ERROR: "系统执行失败",
      CANCELLED: "已停止",
      SUPERSEDED: "已更新条件",
    };
    return labels[session.status] || `计划 v${session.plan_version}`;
  }

  renderSessions() {
    this.elements.sessionList.replaceChildren();
    if (!this.sessions.length) {
      const empty = document.createElement("div");
      empty.className = "session-meta";
      empty.style.padding = "10px";
      empty.textContent = "暂无历史对话";
      this.elements.sessionList.append(empty);
      return;
    }
    this.sessions.forEach((session) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `session-item${session.id === this.sessionId ? " active" : ""}`;
      button.innerHTML = `
        <span class="session-title">${this.escapeHtml(session.title)}</span>
        <span class="session-meta">${this.escapeHtml(session.meta || "新对话")}</span>
      `;
      button.addEventListener("click", () => this.selectSession(session.id));
      this.elements.sessionList.append(button);
    });
  }

  updateSessionMetaFor(sessionId, meta) {
    const session = this.sessions.find((item) => item.id === sessionId);
    if (!session || session.meta === meta) return;
    session.meta = meta;
    this.saveSessions();
    this.renderSessions();
  }

  async createNewSession() {
    if (!this.isConnected()) {
      this.openConfig();
      return;
    }
    try {
      const session = await this.api("/sessions", {method: "POST"});
      this.sessionId = session.session_id;
      sessionStorage.setItem("talentAgentSessionId", this.sessionId);
      this.sessions.unshift({id: this.sessionId, title: "新的人才搜索", meta: "等待输入"});
      this.saveSessions();
      this.renderSessions();
      this.clearPendingImage();
      this.resetConversation();
      this.elements.input.focus();
    } catch (error) {
      this.showGlobalError(error.message);
    }
  }

  async selectSession(sessionId) {
    if (this.busy || sessionId === this.sessionId) return;
    this.clearPendingImage();
    this.sessionId = sessionId;
    sessionStorage.setItem("talentAgentSessionId", sessionId);
    this.renderSessions();
    await this.restoreSession();
  }

  async restoreSession() {
    try {
      const [session, result, messages] = await Promise.all([
        this.api(`/sessions/${this.sessionId}`),
        this.api(`/sessions/${this.sessionId}/result`),
        this.api(`/sessions/${this.sessionId}/messages`),
      ]);
      this.resetConversation(false);
      this.restoring = true;
      this.pendingQuestionId = session.pending_clarification?.question_id;
      messages.forEach((message) => {
        this.appendUserMessage(message.content);
        if (message.outcome) this.renderOutcome(message.outcome);
      });
      this.restoring = false;
      if (session.matching_draft) this.renderRequirementDraft(session.matching_draft);
      if (!messages.length) this.appendAssistantText("可以继续描述你想找的人。");
      if (session.pending_clarification && !messages.some((message) =>
        message.outcome?.result?.clarification?.question_id === this.pendingQuestionId
      )) this.appendClarification(session.pending_clarification);
      if (result?.status === "OK" || result?.status === "EMPTY") {
        this.appendResults(result);
      }
    } catch (error) {
      this.restoring = false;
      this.showGlobalError(error.message);
    }
  }

  resetConversation(showWelcome = true) {
    this.elements.conversation.replaceChildren();
    if (showWelcome) {
      const welcome = this.elements.welcome;
      if (welcome) this.elements.conversation.append(welcome);
      else this.renderCompactWelcome();
    }
    this.resetProgress();
    this.elements.requestPreview.textContent = "尚未生成搜索请求";
  }

  renderCompactWelcome() {
    const wrapper = document.createElement("div");
    wrapper.className = "welcome-state";
    wrapper.innerHTML = `
      <div class="welcome-mark"><i class="bi bi-person-bounding-box" aria-hidden="true"></i></div>
      <h2>描述你想找的人</h2>
      <p>你可以从姓名、职位、学历、年限、公司、学校和城市开始。</p>
    `;
    this.elements.conversation.append(wrapper);
  }

  async sendCurrentMessage() {
    const content = this.elements.input.value.trim();
    const image = this.pendingImage;
    if ((!content && !image) || this.busy) return;
    if (!this.isConnected()) {
      this.openConfig();
      return;
    }
    if (!this.sessionId) await this.createNewSession();
    if (!this.sessionId) return;

    if (image) {
      await this.executeImageMessage(content, image);
      return;
    }
    this.elements.input.value = "";
    this.resizeComposer();
    this.appendUserMessage(content);
    this.updateSessionTitle(content);
    await this.executeMessage({content});
  }

  async executeImageMessage(content, image) {
    this.setBusy(true);
    const loading = this.appendLoading();
    const visibleMessage = content ? `[职位截图]\n${content}` : "[职位截图]";
    try {
      const data = new FormData();
      data.append("image", image);
      data.append("content", content);
      data.append("request_key", crypto.randomUUID());
      const outcome = await this.api(`/sessions/${this.sessionId}/requirement-images`, {
        method: "POST", body: data,
      });
      loading.remove();
      this.elements.input.value = "";
      this.resizeComposer();
      this.clearPendingImage();
      this.appendUserMessage(visibleMessage);
      this.updateSessionTitle(content || "职位截图");
      this.renderOutcome(outcome);
    } catch (error) {
      loading.remove();
      this.appendError(error.message);
    } finally {
      this.setBusy(false);
    }
  }

  async executeMessage({content, clarificationAnswer = null}) {
    this.setBusy(true);
    const loading = this.appendLoading();
    this.startProgress();
    try {
      const outcome = await this.api(`/sessions/${this.sessionId}/messages`, {
        method: "POST",
        body: JSON.stringify({
          client_message_id: `web-${Date.now()}-${crypto.randomUUID()}`,
          content,
          clarification_answer: clarificationAnswer,
        }),
      });
      loading.remove();
      this.finishProgress(outcome);
      this.renderOutcome(outcome);
    } catch (error) {
      loading.remove();
      this.failProgress();
      this.appendError(error.message);
    } finally {
      this.setBusy(false);
    }
  }

  renderOutcome(outcome) {
    if (outcome.matching_reference) {
      const reference = outcome.matching_reference;
      if (reference.run_id) this.watchMatch(reference.run_id, reference.mode);
      else if (reference.requirement_id && !this.restoring) {
        this.api(`/sessions/${this.sessionId}`).then((session) => {
          if (session.matching_draft) this.renderRequirementDraft(session.matching_draft);
        }).catch((error) => this.appendError(error.message));
      }
      return;
    }
    if (outcome.kind === "CHAT") {
      this.appendAssistantText(outcome.reply || "收到。你可以继续描述搜索条件。");
      return;
    }
    if (outcome.kind === "STATUS") {
      this.appendAssistantText(`当前运行状态：${outcome.run?.status || "未知"}`);
      return;
    }
    if (!outcome.result) return;

    const result = outcome.result;
    if (outcome.is_page && ["OK", "EMPTY"].includes(result.status)) {
      this.appendResults(result);
      return;
    }
    if (result.executed_conditions) {
      this.appendAssistantText("已理解你的需求，以下是本轮实际执行的搜索计划：");
      this.appendPlan(result.executed_conditions);
      this.elements.requestPreview.textContent = JSON.stringify(
        this.buildRequestPreview(result), null, 2,
      );
    }
    if (result.clarification) {
      this.appendClarification(result.clarification);
      return;
    }
    if (["OK", "EMPTY"].includes(result.status)) {
      this.appendResults(result);
      return;
    }
    this.appendError(result.message || `本轮处理未完成：${result.status}`);
  }

  appendUserMessage(content) {
    this.removeWelcome();
    const row = this.createMessageRow("user", "我");
    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    bubble.textContent = content;
    row.content.append(bubble);
    this.scrollToBottom();
  }

  installImageUpload() {
    const picker = document.createElement("input");
    picker.type = "file";
    picker.accept = "image/png,image/jpeg,image/webp";
    picker.hidden = true;
    const button = document.createElement("button");
    button.type = "button";
    button.innerHTML = '<i class="bi bi-image" aria-hidden="true"></i>';
    button.title = "添加职位截图";
    button.setAttribute("aria-label", "添加职位截图");
    button.className = "composer-image-button";
    button.addEventListener("click", () => picker.click());
    const preview = document.createElement("div");
    preview.className = "pending-image hidden";
    picker.addEventListener("change", () => {
      const file = picker.files[0];
      if (!file) return;
      if (file.size > 10 * 1024 * 1024) return this.appendError("图片不能超过 10 MiB");
      this.pendingImage = file;
      preview.replaceChildren();
      const name = document.createElement("span");
      name.textContent = file.name;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "移除";
      remove.addEventListener("click", () => this.clearPendingImage());
      preview.append(name, remove);
      preview.classList.remove("hidden");
      this.elements.input.focus();
    });
    this.imagePicker = picker;
    this.imagePreview = preview;
    this.elements.input.before(button);
    this.elements.input.parentElement.before(preview);
    this.elements.input.parentElement.after(picker);
  }

  clearPendingImage() {
    this.pendingImage = null;
    if (this.imagePicker) this.imagePicker.value = "";
    if (this.imagePreview) {
      this.imagePreview.replaceChildren();
      this.imagePreview.classList.add("hidden");
    }
  }

  renderRequirementDraft(draft) {
    const selector = `[data-requirement-id="${CSS.escape(draft.requirement_id)}"]`;
    if (this.elements.conversation.querySelector(selector)) return;
    const row = this.createMessageRow("assistant", "AI");
    row.root.dataset.requirementId = draft.requirement_id;
    const title = document.createElement("h3");
    title.textContent = "确认搜索需求";
    const source = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "识别原文";
    const original = document.createElement("pre");
    original.textContent = draft.requirements.source_text;
    source.append(summary, original);
    row.content.append(title, source);
    const requirements = structuredClone(draft.requirements);
    const filterText = document.createElement("p");
    filterText.className = "matching-filters";
    filterText.textContent = `搜索条件：${this.conditionItems(requirements.conditions).map(([k, v]) => `${k}：${v}`).join("；") || "尚未指定，请在对话中补充"}`;
    row.content.append(filterText);
    requirements.preferences = [
      ...requirements.required_criteria,
      ...requirements.preferences,
      ...requirements.interview_items,
    ].filter((item, index, items) => items.findIndex((other) => other.id === item.id) === index);
    requirements.required_criteria = [];
    requirements.interview_items = [];
    const groups = {
      preferences: "偏好匹配（不淘汰候选人）",
    };
    for (const [group, label] of Object.entries(groups)) {
      if (!requirements[group].length) continue;
      const section = document.createElement("details");
      section.className = "matching-group";
      section.open = requirements[group].length <= 4;
      const heading = document.createElement("summary");
      heading.textContent = `${label}（${requirements[group].length}）`;
      section.append(heading);
      for (const criterion of requirements[group]) {
        const line = document.createElement("p");
        line.className = "matching-preference";
        line.textContent = criterion.description;
        section.append(line);
      }
      row.content.append(section);
    }
    const help = document.createElement("p");
    help.className = "matching-help";
    help.textContent = requirements.ambiguities.length
      ? `待确认：${requirements.ambiguities.join("；")}。请在对话中补充后重新确认。`
      : "固定搜索条件负责召回；以下内容只作为偏好排序。教育或工作经历未提及时显示“信息不足”，不会淘汰候选人。";
    row.content.append(help);
    if (requirements.ambiguities.length) {
      const ambiguityText = requirements.ambiguities.join("；");
      const choices = ambiguityText.includes("城市") || ambiguityText.includes("现居")
        || ambiguityText.includes("期望工作")
        ? [["现居住地", "待确认的城市按候选人现居住地处理"],
          ["期望工作地", "待确认的城市按候选人期望工作地处理"]]
        : ambiguityText.includes("学历")
          ? [["本科及以上", "最低学历设为本科"], ["硕士及以上", "最低学历设为硕士"],
            ["博士", "最低学历设为博士"]]
          : [];
      if (choices.length) {
        const options = document.createElement("div");
        options.className = "clarification-options";
        for (const [label, answer] of choices) {
          const button = document.createElement("button");
          button.type = "button";
          button.textContent = label;
          button.addEventListener("click", async () => {
            options.querySelectorAll("button").forEach((item) => item.disabled = true);
            try {
              const updated = await this.api(`/sessions/${this.sessionId}/requirements`, {
                method: "POST",
                body: JSON.stringify({request_key: crypto.randomUUID(), content: answer}),
              });
              row.root.remove();
              this.appendUserMessage(label);
              this.renderRequirementDraft(updated);
            } catch (error) {
              this.appendError(error.message);
              options.querySelectorAll("button").forEach((item) => item.disabled = false);
            }
          });
          options.append(button);
        }
        row.content.append(options);
      }
    }
    const confirm = document.createElement("button");
    confirm.className = "matching-action";
    confirm.textContent = "确认并开始找人";
    confirm.disabled = requirements.ambiguities.length > 0;
    const requestKey = crypto.randomUUID();
    confirm.addEventListener("click", async () => {
      confirm.disabled = true;
      try {
        const started = await this.api(`/sessions/${this.sessionId}/requirements/${draft.requirement_id}/confirm`, {
          method: "POST", body: JSON.stringify({request_key: requestKey, requirements}),
        });
        confirm.textContent = "已确认";
        this.watchMatch(started.run_id, started.mode);
      } catch (error) { this.appendError(error.message); confirm.disabled = false; }
    });
    row.content.append(confirm);
    this.scrollToBottom();
  }

  async watchMatch(runId, mode) {
    const sessionId = this.sessionId;
    const selector = `[data-match-run="${CSS.escape(runId)}"]`;
    if (this.elements.conversation.querySelector(selector)) return;
    const row = this.createMessageRow("assistant", "AI");
    row.root.dataset.matchRun = runId;
    row.content.textContent = "正在匹配候选人…";
    const refresh = async () => {
      if (this.sessionId !== sessionId || !row.root.isConnected) return;
      try {
        const run = await this.api(`/runs/${runId}`);
        if (this.sessionId !== sessionId) return;
        if (run.status === "SUCCEEDED" && (mode === "SIMPLE" || run.stage !== "matching")) {
          const result = await this.api(`/sessions/${sessionId}/result`);
          if (result?.run_id === runId) {
            row.root.remove();
            this.appendResults(result);
            return;
          }
        }
        const data = await this.api(`/sessions/${sessionId}/matches/${runId}?include_results=${!["RUNNING", "QUEUED"].includes(run.status)}`);
        if (this.sessionId !== sessionId) return;
        row.content.replaceChildren();
        const title = document.createElement("h3");
        title.textContent = `需求版本 ${data.plan_version} · 已检查 ${data.usage.checked_candidates} 人`;
        row.content.append(title);
        if (["RUNNING", "QUEUED"].includes(data.status)) {
          this.updateSessionMetaFor(sessionId, `正在匹配 · 已评估 ${data.usage.checked_candidates} 人`);
          const progress = document.createElement("p");
          const matchingHint = data.provisional_result_count
            ? `暂有 ${data.provisional_result_count} 位候选人可展示`
            : data.provisional_pending_count
              ? `暂有 ${data.provisional_pending_count} 位候选人正在核验偏好`
              : "正在读取并核验证据";
          progress.textContent = `已召回 ${data.recalled_count} 人，评估 ${data.usage.checked_candidates} 人；${matchingHint}`;
          row.content.append(progress);
          setTimeout(refresh, 1000);
          return;
        }
        const stopped = document.createElement("p");
        const reasons = {TARGET_REACHED: "已找到目标人数", SOURCE_EXHAUSTED: "候选池已读完",
          PAGE_LIMIT: "达到搜索批次上限", CANDIDATE_LIMIT: "达到评估人数上限",
          MODEL_LIMIT: "达到模型调用上限", TIME_LIMIT: "达到本轮时间上限",
          NO_NEW_CANDIDATES: "没有更多新候选人", CANCELLED: "已取消",
          DEPENDENCY_ERROR: "依赖服务异常", CONTEXT_LIMIT: "达到累计任务上限"};
        stopped.className = data.result_count ? "matching-summary" : "matching-summary matching-empty";
        stopped.textContent = data.result_count
          ? `推荐 ${data.result_count} 人，另有 ${data.pending_count} 人待核验；${reasons[data.stop_reason] || data.stop_reason}`
          : data.pending_count
            ? `找到 ${data.pending_count} 位偏好证据待核验候选人；${reasons[data.stop_reason] || data.stop_reason}`
            : `本轮确实没有召回可展示人选；${reasons[data.stop_reason] || data.stop_reason}`;
        row.content.append(stopped);
        const matchMeta = data.result_count || data.pending_count
          ? `匹配完成 · ${data.result_count + data.pending_count} 人 · 计划 v${data.plan_version}`
          : `未召回候选人 · 计划 v${data.plan_version}`;
        this.updateSessionMetaFor(sessionId, matchMeta);
        const preferenceNames = new Map((data.requirements?.preferences || [])
          .map((item) => [item.id, item.description]));
        for (const [group, label] of [["candidates", "推荐"], ["pending", "待核验"]]) {
          for (const person of data[group] || []) {
            const detail = document.createElement("details");
            detail.className = "matching-candidate";
            const heading = document.createElement("summary");
            const name = person.card.display_name || person.card.candidate_id;
            const supported = person.evaluation.evidence.filter((item) =>
              ["SUPPORTED", "PARTIAL"].includes(item.status));
            const compactPreference = (item) => {
              const full = preferenceNames.get(item.criterion_id) || item.explanation;
              const cleaned = full.replace(/^(最好|优先|偏好|具备|熟悉)/, "")
                .replace(/，?用于证据说明与排序.*$/, "").replace(/[。；]$/, "");
              return cleaned.length > 18 ? `${cleaned.slice(0, 18)}…` : cleaned;
            };
            heading.innerHTML = `
              <span class="candidate-avatar">${this.escapeHtml(name.slice(0, 1))}</span>
              <span class="matching-candidate-main">
                <strong>${this.escapeHtml(name)}</strong>
                <span>${this.escapeHtml(person.card.headline || "职位暂未填写")}${person.card.current_company ? ` · ${this.escapeHtml(person.card.current_company)}` : ""}</span>
                <span class="candidate-tags">${supported.map((item) =>
                  `<span>${this.escapeHtml(compactPreference(item))}</span>`).join("")}</span>
              </span>
              <span class="matching-candidate-side">${this.escapeHtml(person.card.current_city || label)}</span>
            `;
            detail.append(heading);
            const body = document.createElement("div");
            body.className = "matching-candidate-detail";
            const reasonTitle = document.createElement("h4");
            reasonTitle.textContent = "推荐依据";
            body.append(reasonTitle);
            const statusNames = {SUPPORTED: "支持", PARTIAL: "部分支持", UNKNOWN: "信息不足",
              CONTRADICTED: "存在矛盾"};
            for (const evidence of person.evaluation.evidence) {
              const reason = document.createElement("div");
              reason.className = `matching-reason status-${evidence.status.toLowerCase()}`;
              const badge = document.createElement("span");
              badge.className = "matching-reason-status";
              badge.textContent = statusNames[evidence.status] || evidence.status;
              const explanation = document.createElement("span");
              explanation.textContent = evidence.explanation;
              reason.append(badge, explanation);
              body.append(reason);
            }
            const education = (person.profile_sources || []).filter((item) => item.path.includes("education"));
            const work = (person.profile_sources || []).filter((item) => item.path.includes("work"));
            for (const [sectionName, sources] of [["教育经历", education], ["工作经历", work]]) {
              if (!sources.length) continue;
              const sectionTitle = document.createElement("h4");
              sectionTitle.textContent = sectionName;
              body.append(sectionTitle);
              for (const source of sources) {
                const line = document.createElement("p");
                line.textContent = source.text;
                body.append(line);
              }
            }
            if (!education.length && !work.length) {
              const empty = document.createElement("p");
              empty.textContent = "教育和工作经历暂未填写。";
              body.append(empty);
            }
            detail.append(body);
            row.content.append(detail);
          }
        }
        for (const item of data.requirements?.interview_items || []) {
          const line = document.createElement("p");
          line.textContent = `面试待验证：${item.description}`;
          row.content.append(line);
        }
        const next = document.createElement("button");
        next.className = "matching-action"; next.textContent = "继续找 10 位";
        next.disabled = !data.can_continue;
        const key = crypto.randomUUID();
        next.addEventListener("click", async () => {
          next.disabled = true;
          try {
            const started = await this.api(`/sessions/${sessionId}/matches/${runId}/continue`, {
              method: "POST", body: JSON.stringify({request_key: key}),
            });
            this.watchMatch(started.run_id, started.mode);
          } catch (error) { this.appendError(error.message); next.disabled = false; }
        });
        row.content.append(next);
      } catch (error) { row.content.textContent = error.message; }
    };
    await refresh();
  }

  appendAssistantText(content) {
    this.removeWelcome();
    const row = this.createMessageRow("assistant", "AI");
    const text = document.createElement("div");
    text.className = "assistant-lead";
    text.textContent = content;
    row.content.append(text);
    this.scrollToBottom();
  }

  appendLoading() {
    this.removeWelcome();
    const row = this.createMessageRow("assistant", "AI");
    const loading = document.createElement("div");
    loading.className = "loading-line";
    loading.textContent = "正在理解需求并执行搜索…";
    row.content.append(loading);
    this.scrollToBottom();
    return row.root;
  }

  appendPlan(conditions) {
    const row = this.createMessageRow("assistant", "AI");
    const block = document.createElement("div");
    block.className = "plan-block";
    const items = this.conditionItems(conditions);
    block.innerHTML = `
      <div class="block-title"><i class="bi bi-bullseye" aria-hidden="true"></i>SearchPlan</div>
      <dl class="condition-grid">
        ${items.map(([label, value]) => `<dt>${label}</dt><dd>${this.escapeHtml(value)}</dd>`).join("")}
      </dl>
    `;
    row.content.append(block);
    this.scrollToBottom();
  }

  appendClarification(card) {
    const row = this.createMessageRow("assistant", "AI");
    const block = document.createElement("div");
    block.className = "clarification-card";
    const title = document.createElement("h3");
    title.textContent = card.title;
    const options = document.createElement("div");
    options.className = "clarification-options";
    card.options.forEach((option) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = option.label;
      button.disabled = this.restoring && card.question_id !== this.pendingQuestionId;
      button.addEventListener("click", async () => {
        if (this.busy) return;
        options.querySelectorAll("button").forEach((item) => item.disabled = true);
        this.appendUserMessage(option.label);
        await this.executeMessage({
          content: option.label,
          clarificationAnswer: {question_id: card.question_id, value: option.value},
        });
      });
      options.append(button);
    });
    block.append(title, options);
    row.content.append(block);
    this.scrollToBottom();
  }

  appendResults(result) {
    const existing = this.elements.conversation.querySelector(
      `[data-result-plan="${result.plan_version}"]`,
    );
    const row = existing
      ? {root: existing, content: existing.querySelector(".message-content")}
      : this.createMessageRow("assistant", "AI");
    row.root.dataset.resultPlan = result.plan_version;
    row.content.replaceChildren();
    const block = document.createElement("div");
    block.className = "result-block";
    const total = result.total ?? result.candidates.length;
    const pageCount = result.candidates.length;
    block.innerHTML = `
      <div class="result-header">
        <strong>${total ? `共 ${total} 位候选人，本页展示 ${pageCount} 位` : "暂未找到符合条件的候选人"}</strong>
        <span>第 ${result.page || 1} 页 · 每页 10 位</span>
      </div>
    `;
    result.candidates.forEach((candidate) => {
      const item = document.createElement("div");
      item.className = "candidate-row";
      const name = candidate.display_name || "候选人";
      item.innerHTML = `
        <div class="candidate-avatar">${this.escapeHtml(name.slice(0, 1))}</div>
        <div>
          <div class="candidate-name">${this.escapeHtml(name)}</div>
          <div class="candidate-meta">${this.escapeHtml(candidate.headline || "职位暂未填写")}${candidate.current_company ? ` · ${this.escapeHtml(candidate.current_company)}` : ""}</div>
          <div class="candidate-tags">${(candidate.highlights || []).map((tag) => `<span>${this.escapeHtml(tag)}</span>`).join("")}</div>
        </div>
        <div class="candidate-city">${this.escapeHtml(candidate.current_city || "")}</div>
      `;
      block.append(item);
    });
    if (result.next_page || result.page > 1) {
      const actions = document.createElement("div");
      actions.className = "result-actions";
      if (result.page > 1) {
        const previous = document.createElement("button");
        previous.type = "button";
        previous.className = "text-button";
        previous.textContent = "查看上一页";
        previous.addEventListener("click", () => this.loadNextPage({
          session_id: this.sessionId,
          plan_version: result.plan_version,
          page: result.page - 1,
        }));
        actions.append(previous);
      }
      if (result.next_page) {
        const next = document.createElement("button");
        next.type = "button";
        next.className = "text-button";
        next.textContent = "查看下一页";
        next.addEventListener("click", () => this.loadNextPage(result.next_page));
        actions.append(next);
      }
      block.append(actions);
    }
    row.content.append(block);
    if (!this.restoring) this.updateSessionMeta(`本页已返回 ${pageCount} 位候选人`);
    this.elements.requestPreview.textContent = JSON.stringify(this.buildRequestPreview(result), null, 2);
    this.scrollToBottom();
  }

  async loadNextPage(reference) {
    if (this.busy) return;
    this.setBusy(true);
    this.startProgress(NODE_DEFINITIONS.findIndex(([name]) => name === "search_candidates"));
    try {
      const outcome = await this.api(`/sessions/${this.sessionId}/pages`, {
        method: "POST",
        body: JSON.stringify({reference}),
      });
      this.finishProgress(outcome);
      if (outcome.result) this.appendResults(outcome.result);
    } catch (error) {
      this.failProgress();
      this.appendError(error.message);
    } finally {
      this.setBusy(false);
    }
  }

  async cancelRun() {
    if (!this.sessionId || !this.busy) return;
    try {
      await this.api(`/sessions/${this.sessionId}/cancel`, {method: "POST"});
      this.appendAssistantText("已停止当前搜索。你可以修改条件后重新开始。");
      this.failProgress("已停止");
    } catch (error) {
      this.appendError(error.message);
    }
  }

  createMessageRow(role, avatarText) {
    const root = document.createElement("div");
    root.className = `message-row ${role}`;
    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.textContent = avatarText;
    const content = document.createElement("div");
    content.className = "message-content";
    root.append(avatar, content);
    this.elements.conversation.append(root);
    return {root, content};
  }

  appendError(message) {
    const row = this.createMessageRow("assistant", "AI");
    const block = document.createElement("div");
    block.className = "error-message";
    block.textContent = message;
    row.content.append(block);
    this.scrollToBottom();
  }

  showGlobalError(message) {
    this.removeWelcome();
    this.appendError(message);
  }

  conditionItems(conditions) {
    const values = [];
    if (conditions.applicant_name) values.push(["姓名", conditions.applicant_name.value]);
    if (conditions.candidate_position) values.push(["目标职位", conditions.candidate_position.value]);
    if (conditions.minimum_degree) values.push(["最低学历", conditions.minimum_degree.value]);
    if (conditions.work_years) {
      const minimum = conditions.work_years.minimum;
      const maximum = conditions.work_years.maximum;
      values.push(["工作年限", maximum ? `${minimum ?? 0}～${maximum} 年` : `${minimum} 年以上`]);
    }
    if (conditions.company) values.push(["公司经历", conditions.company.names.join("、")]);
    if (conditions.school) values.push(["毕业院校", conditions.school.names.join("、")]);
    if (conditions.current_city) values.push(["现居住地", conditions.current_city.name]);
    if (conditions.expected_city) values.push(["期望工作地", conditions.expected_city.name]);
    if (conditions.school_level) values.push(["院校标签", conditions.school_level.labels.join("、")]);
    return values.length ? values : [["搜索条件", "未设置"]];
  }

  buildRequestPreview(result) {
    const conditions = result.executed_conditions || {};
    const resolvedCodes = (condition) => (condition?.resolved || []).map((item) => item.code);
    return {
      applicantName: conditions.applicant_name?.value || null,
      nowPosition: conditions.candidate_position?.value || null,
      onlyNowPosition: conditions.candidate_position?.scope === "CURRENT",
      topDegree: conditions.minimum_degree?.resolved?.code || null,
      workYearsMin: conditions.work_years?.minimum ?? null,
      workYearsMax: conditions.work_years?.maximum ?? null,
      nowCompany: resolvedCodes(conditions.company),
      onlyNowCompany: conditions.company?.scope === "CURRENT",
      school: resolvedCodes(conditions.school),
      livePlace: conditions.current_city?.resolved?.code ? [conditions.current_city.resolved.code] : [],
      expectWorkPlace: conditions.expected_city?.resolved?.code ? [conditions.expected_city.resolved.code] : [],
      schoolLevelList: resolvedCodes(conditions.school_level),
      currentPage: result.page || 1,
      pageSize: 10,
    };
  }

  renderTimeline() {
    this.elements.nodeTimeline.replaceChildren();
    NODE_DEFINITIONS.forEach(([name, title, description], index) => {
      const item = document.createElement("div");
      item.className = "node-item";
      if (index < this.activeNodeIndex) item.classList.add("done");
      if (index === this.activeNodeIndex) item.classList.add("active");
      const iconName = index < this.activeNodeIndex ? "bi bi-check" : "";
      item.innerHTML = `
        <div class="node-icon">${iconName ? `<i class="${iconName}" aria-hidden="true"></i>` : ""}</div>
        <div><div class="node-title">${name}</div><div class="node-description">${description}</div></div>
      `;
      item.title = title;
      this.elements.nodeTimeline.append(item);
    });
  }

  startProgress(startIndex = 0) {
    clearInterval(this.progressTimer);
    this.activeNodeIndex = startIndex;
    this.elements.runStatus.textContent = "正在执行";
    this.renderTimeline();
    this.progressTimer = setInterval(() => {
      if (this.activeNodeIndex < NODE_DEFINITIONS.length - 2) {
        this.activeNodeIndex += 1;
        this.renderTimeline();
      }
    }, 850);
  }

  finishProgress(outcome) {
    clearInterval(this.progressTimer);
    const needsClarification = outcome.result?.status === "NEEDS_CLARIFICATION" || outcome.result?.status === "UNSUPPORTED";
    this.activeNodeIndex = needsClarification
      ? NODE_DEFINITIONS.findIndex(([name]) => name === "clarify")
      : NODE_DEFINITIONS.length;
    this.elements.runStatus.textContent = needsClarification ? "等待用户澄清" : "执行完成";
    this.renderTimeline();
  }

  failProgress(status = "执行失败") {
    clearInterval(this.progressTimer);
    this.elements.runStatus.textContent = status;
    this.renderTimeline();
  }

  resetProgress() {
    clearInterval(this.progressTimer);
    this.activeNodeIndex = -1;
    this.elements.runStatus.textContent = "等待搜索";
    this.renderTimeline();
  }

  setBusy(busy) {
    this.busy = busy;
    this.elements.send.disabled = busy;
    this.elements.cancel.disabled = !busy;
  }

  updateSessionTitle(content) {
    const session = this.sessions.find((item) => item.id === this.sessionId);
    if (!session) return;
    if (session.title === "新的人才搜索") session.title = content.slice(0, 24);
    session.meta = "正在搜索";
    this.saveSessions();
    this.renderSessions();
  }

  updateSessionMeta(meta) {
    const session = this.sessions.find((item) => item.id === this.sessionId);
    if (!session) return;
    session.meta = meta;
    this.saveSessions();
    this.renderSessions();
  }

  removeWelcome() {
    this.elements.conversation.querySelector(".welcome-state")?.remove();
  }

  resizeComposer() {
    this.elements.input.style.height = "auto";
    this.elements.input.style.height = `${Math.min(this.elements.input.scrollHeight, 120)}px`;
  }

  scrollToBottom() {
    requestAnimationFrame(() => {
      this.elements.conversation.scrollTop = this.elements.conversation.scrollHeight;
    });
  }

  escapeHtml(value) {
    const element = document.createElement("span");
    element.textContent = String(value ?? "");
    return element.innerHTML;
  }
}

window.addEventListener("DOMContentLoaded", () => new TalentAgentPage().init());
