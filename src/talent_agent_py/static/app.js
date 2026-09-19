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
      this.appendPlan(result.executed_conditions, result.executed_preferences || []);
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

  appendPlan(conditions, preferences = []) {
    const row = this.createMessageRow("assistant", "AI");
    const block = document.createElement("div");
    block.className = "plan-block";
    const items = this.conditionItems(conditions);
    if (preferences.length) {
      items.push(["偏好条件", preferences.map((item) => item.description).join("、")]);
    }
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
      const hasPreference = (candidate.preference_evidence || []).length > 0;
      const item = document.createElement("details");
      item.className = "candidate-row candidate-expandable";
      const name = candidate.display_name || "候选人";
      const summary = document.createElement("summary");
      summary.className = "candidate-summary";
      const preferenceTags = (candidate.preference_evidence || []).map((evidence) =>
        `<span>${this.escapeHtml(evidence.preference)}</span>`).join("");
      summary.innerHTML = `
        <div class="candidate-avatar">${this.escapeHtml(name.slice(0, 1))}</div>
        <div class="candidate-main">
          <div class="candidate-name-line">
            <div class="candidate-name">${this.escapeHtml(name)}</div>
            ${preferenceTags ? `<div class="candidate-tags preference-tags">${preferenceTags}</div>` : ""}
          </div>
          <div class="candidate-meta">${this.escapeHtml(candidate.headline || "职位暂未填写")}${candidate.current_company ? ` · ${this.escapeHtml(candidate.current_company)}` : ""}</div>
          <div class="candidate-facts">
            <span><b>工作年限</b>${this.escapeHtml(candidate.work_years || "--")}</span>
            <span><b>最高学历</b>${this.escapeHtml(candidate.highest_degree || "--")}</span>
            <span><b>毕业院校</b>${this.escapeHtml(candidate.highest_school || "--")}</span>
          </div>
          ${(candidate.highlights || []).length ? `<div class="candidate-tags">${candidate.highlights.map((tag) => `<span>${this.escapeHtml(tag)}</span>`).join("")}</div>` : ""}
        </div>
        <div class="candidate-locations">
          <span><b>现居地</b>${this.escapeHtml(candidate.current_city || "--")}</span>
          <span><b>期望工作地</b>${this.escapeHtml(candidate.expected_city || "--")}</span>
        </div>
      `;
      item.append(summary);
      const detail = document.createElement("div");
      detail.className = "candidate-detail";
      if (hasPreference) {
        const reasons = document.createElement("section");
        reasons.innerHTML = "<h4>推荐依据</h4>";
        for (const evidence of candidate.preference_evidence) {
          const line = document.createElement("p");
          line.className = `matching-reason status-${evidence.status.toLowerCase()}`;
          const status = evidence.status === "SUPPORTED" ? "支持" : "部分支持";
          line.innerHTML = `<span class="matching-reason-status">${status}</span><span>${this.escapeHtml(evidence.explanation)}</span>`;
          reasons.append(line);
        }
        detail.append(reasons);
      }
      for (const [category, title] of [["WORK", "工作经历"], ["EDUCATION", "教育经历"]]) {
        const experiences = (candidate.experiences || []).filter((experience) => experience.category === category);
        const section = document.createElement("section");
        section.innerHTML = `<h4>${title}</h4>`;
        if (experiences.length) {
          experiences.forEach((experience) => {
            const line = document.createElement("p");
            line.className = "candidate-experience";
            line.textContent = experience.text;
            section.append(line);
          });
        } else {
          const empty = document.createElement("p");
          empty.className = "candidate-detail-empty";
          empty.textContent = "暂无记录";
          section.append(empty);
        }
        detail.append(section);
      }
      item.append(detail);
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
