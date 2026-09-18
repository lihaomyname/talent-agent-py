const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const vm = require('node:vm');

class Element {
  constructor() { this.children = []; this.dataset = {}; this.listeners = {}; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  querySelector(selector) {
    if (selector === '.message-content') return this.content;
    const version = selector.match(/data-result-plan="(\d+)"/)?.[1];
    return this.children.find(item => String(item.dataset.resultPlan) === version) || null;
  }
}
const context = vm.createContext({
  window: {addEventListener() {}}, document: {createElement: () => new Element()},
});
vm.runInContext(readFileSync(resolve(__dirname, '../../src/talent_agent_py/static/app.js'), 'utf8') +
  '\nglobalThis.Page = TalentAgentPage;', context);

function page() {
  const view = Object.create(context.Page.prototype);
  view.sessionId = 'session';
  view.elements = {conversation: new Element(), requestPreview: new Element()};
  view.createMessageRow = () => {
    const root = new Element();
    const content = new Element();
    root.content = content;
    view.elements.conversation.append(root);
    return {root, content};
  };
  view.scrollToBottom = view.updateSessionMeta = () => {};
  view.buildRequestPreview = result => ({currentPage: result.page});
  return view;
}
function result(number) {
  return {status: 'OK', plan_version: 1, page: number, candidates: [], total: 30,
    next_page: number < 3 ? {session_id: 'session', plan_version: 1, page: number + 1} : null};
}

test('pagination replaces the same result row and previous button targets preceding page', () => {
  const view = page();
  view.appendResults(result(1));
  const original = view.elements.conversation.children[0];
  view.renderOutcome({kind: 'RESULT', result: result(2), is_page: true});
  view.renderOutcome({kind: 'RESULT', result: result(3), is_page: true});
  assert.equal(view.elements.conversation.children.length, 1);
  assert.equal(view.elements.conversation.children[0], original);
  const block = original.content.children[0];
  assert.match(block.innerHTML, /第 3 页/);
  let requested;
  view.loadNextPage = reference => requested = reference;
  block.children[0].children[0].listeners.click();
  assert.equal(requested.page, 2);
});

test('refresh restores ordered messages and replies, then the current browsed page', async () => {
  const view = page();
  const events = [];
  view.api = async path => path.endsWith('/messages') ? [
    {content: '找人', outcome: {kind: 'RESULT', result: result(1)}},
    {content: '谢谢', outcome: {kind: 'CHAT', reply: '收到'}},
  ] : path.endsWith('/result') ? result(3) : {};
  view.resetConversation = () => events.push('reset');
  view.appendUserMessage = text => events.push(text);
  view.renderOutcome = outcome => events.push(outcome.kind);
  view.appendResults = value => events.push(value.page);
  view.showGlobalError = error => assert.fail(error);
  await view.restoreSession();
  assert.deepEqual(events, ['reset', '找人', 'RESULT', '谢谢', 'CHAT', 3]);
});

test('matching references use matching renderer instead of adding status messages', () => {
  const view = page();
  const events = [];
  view.watchMatch = (id, mode) => events.push([id, mode]);
  view.appendAssistantText = () => assert.fail('must not append a separate status row');
  view.renderOutcome({kind: 'STATUS', matching_reference: {run_id: 'matching-1', mode: 'MATCHING'}});
  assert.deepEqual(events, [['matching-1', 'MATCHING']]);
});

test('refresh restores persisted requirement draft without browser draft storage', async () => {
  const view = page();
  const draft = {requirement_id: 'draft-1'};
  view.api = async path => path.endsWith('/messages') ? [] : path.endsWith('/result') ? null : {matching_draft: draft};
  view.resetConversation = view.appendAssistantText = () => {};
  view.showGlobalError = error => assert.fail(error);
  let restored;
  view.renderRequirementDraft = value => restored = value;
  await view.restoreSession();
  assert.equal(restored, draft);
});

test('matching status updates the selected history item without replacing it with session id', () => {
  const view = page();
  view.sessions = [{id: 'session', title: '职位要求', meta: '暂无结果'}];
  let saved = 0;
  let rendered = 0;
  view.saveSessions = () => saved += 1;
  view.renderSessions = () => rendered += 1;
  view.updateSessionMetaFor('session', '匹配完成 · 10 人 · 计划 v1');
  assert.equal(view.sessions[0].meta, '匹配完成 · 10 人 · 计划 v1');
  assert.equal(saved, 1);
  assert.equal(rendered, 1);
});
