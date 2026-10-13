/**
 * Researcher front-end.
 *
 * Sends the task to the Flask API — either the blocking /api/run endpoint or
 * the /api/stream Server-Sent Events endpoint — and renders each agent's
 * contribution as a card in chronological order, followed by the final answer.
 *
 * This file is loaded in <head> so the saved theme applies before first paint;
 * everything else waits for DOMContentLoaded.
 */
(function () {
  'use strict';

  const THEME_KEY = 'agent-orchestrator:theme';
  const STREAM_KEY = 'agent-orchestrator:stream';
  const SUPERVISOR = 'Supervisor';
  const FINISH = 'FINISH';
  const COLOR_COUNT = 6;
  const EXAMPLE_TASK =
    'Write a high-performance Python function to compute the nth Fibonacci ' +
    'number using memoization, and explain its time complexity.';

  // Agents are generated per task, so pick an icon from keywords in the name.
  const ICON_RULES = [
    [/plan|strateg|architect|outline/i, 'bi-list-check'],
    [/research|search|investigat|fact|scout/i, 'bi-search'],
    [/review|critic|\bqa\b|test|audit|verif|check/i, 'bi-shield-check'],
    [/cod|develop|engineer|program|implement|debug/i, 'bi-code-slash'],
    [/data|analy|stat|math|calcul|quant/i, 'bi-bar-chart'],
    [/writ|edit|author|copy|document|content/i, 'bi-pencil-square'],
    [/design|\bui\b|\bux\b|visual|creative/i, 'bi-palette'],
    [/secur|risk/i, 'bi-shield-lock'],
    [/legal|complian|policy/i, 'bi-bank'],
    [/market|sales|seo|brand/i, 'bi-megaphone'],
    [/financ|budget|cost|account/i, 'bi-currency-dollar'],
    [/teach|tutor|explain|educat/i, 'bi-mortarboard'],
  ];

  /* ------------------------------------------------------------------ */
  /* Storage (may be unavailable in private windows)                     */
  /* ------------------------------------------------------------------ */
  function storageGet(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (err) {
      return null;
    }
  }

  function storageSet(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (err) {
      /* Storage is optional; ignore failures. */
    }
  }

  /* ------------------------------------------------------------------ */
  /* Theme                                                               */
  /* ------------------------------------------------------------------ */
  const darkQuery = window.matchMedia('(prefers-color-scheme: dark)');

  function currentTheme() {
    return document.documentElement.getAttribute('data-bs-theme') === 'dark'
      ? 'dark'
      : 'light';
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-bs-theme', theme);

    const lightSheet = document.getElementById('hljs-theme-light');
    const darkSheet = document.getElementById('hljs-theme-dark');
    if (lightSheet && darkSheet) {
      lightSheet.disabled = theme === 'dark';
      darkSheet.disabled = theme !== 'dark';
    }

    const toggle = document.getElementById('theme-toggle');
    if (toggle) {
      const next = theme === 'dark' ? 'light' : 'dark';
      toggle.setAttribute('aria-label', `Switch to ${next} mode`);
      toggle.setAttribute('title', `Switch to ${next} mode`);
      toggle.querySelector('i').className =
        theme === 'dark' ? 'bi bi-sun' : 'bi bi-moon-stars';
    }
  }

  applyTheme(storageGet(THEME_KEY) || (darkQuery.matches ? 'dark' : 'light'));
  darkQuery.addEventListener('change', (event) => {
    if (!storageGet(THEME_KEY)) applyTheme(event.matches ? 'dark' : 'light');
  });

  /* ------------------------------------------------------------------ */
  /* State and element references                                        */
  /* ------------------------------------------------------------------ */
  const state = {
    running: false,
    controller: null,
    finalText: '',
    finalizerModel: '',
    stepCount: 0,
    agentCounts: new Map(),
    startedAt: 0,
    timerId: null,
    workingColorClass: '',
    copyResetId: null,
  };

  let els = null;
  let api = null;

  /* ------------------------------------------------------------------ */
  /* Small utilities                                                     */
  /* ------------------------------------------------------------------ */
  function plural(count, word) {
    return `${count} ${word}${count === 1 ? '' : 's'}`;
  }

  function formatElapsed(ms) {
    const total = Math.max(0, Math.floor(ms / 1000));
    const minutes = Math.floor(total / 60);
    const seconds = String(total % 60).padStart(2, '0');
    return `${minutes}:${seconds}`;
  }

  function hashString(value) {
    let hash = 0;
    for (let i = 0; i < value.length; i += 1) {
      hash = (hash * 31 + value.charCodeAt(i)) >>> 0;
    }
    return hash;
  }

  function prefersReducedMotion() {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function isStackedLayout() {
    return window.matchMedia('(max-width: 991.98px)').matches;
  }

  function scrollToElement(element) {
    element.scrollIntoView({
      behavior: prefersReducedMotion() ? 'auto' : 'smooth',
      block: 'start',
    });
  }

  /* ------------------------------------------------------------------ */
  /* Markdown rendering (sanitised)                                      */
  /* ------------------------------------------------------------------ */
  function setupMarkdown() {
    if (window.marked) {
      window.marked.use({ gfm: true, breaks: false });
    }
    if (window.DOMPurify) {
      window.DOMPurify.addHook('afterSanitizeAttributes', (node) => {
        if (node.tagName === 'A') {
          node.setAttribute('target', '_blank');
          node.setAttribute('rel', 'noopener noreferrer');
        }
      });
    }
    if (window.hljs) {
      window.hljs.configure({ ignoreUnescapedHTML: true });
    }
  }

  function renderMarkdown(target, text) {
    const content = text || '';
    if (window.marked && window.DOMPurify) {
      target.classList.remove('is-plain');
      target.innerHTML = window.DOMPurify.sanitize(window.marked.parse(content));
      if (window.hljs) {
        target.querySelectorAll('pre code').forEach((block) => {
          window.hljs.highlightElement(block);
        });
      }
    } else {
      // Libraries failed to load: fall back to safe plain text.
      target.textContent = content;
      target.classList.add('is-plain');
    }
  }

  /* ------------------------------------------------------------------ */
  /* Roster                                                              */
  /* ------------------------------------------------------------------ */
  function rosterItem(agent) {
    if (!agent) return null;
    return els.roster.querySelector(`[data-agent="${CSS.escape(agent)}"]`);
  }

  function agentInfo(agent) {
    const item = rosterItem(agent);
    if (item) {
      return { colorClass: item.dataset.colorClass, icon: item.dataset.icon };
    }
    const index = hashString(agent || '') % COLOR_COUNT;
    return { colorClass: `agent-color-${index}`, icon: 'bi-robot' };
  }

  function setRosterStatus(agent, status, label) {
    const item = rosterItem(agent);
    if (!item) return;
    item.classList.toggle('is-active', status === 'active');
    item.classList.toggle('is-done', status === 'done');
    item.querySelector('.roster-status').textContent = label;
  }

  function contributionLabel(agent) {
    const count = state.agentCounts.get(agent) || 0;
    return plural(count, 'reply');
  }

  /** Clear any "working" highlight, keeping each agent's reply count. */
  function settleRoster() {
    els.roster.querySelectorAll('.roster-item.is-active').forEach((item) => {
      const agent = item.dataset.agent;
      if (state.agentCounts.has(agent)) {
        setRosterStatus(agent, 'done', contributionLabel(agent));
      } else {
        setRosterStatus(agent, 'idle', 'Idle');
      }
    });
  }

  function iconFor(name) {
    const rule = ICON_RULES.find(([pattern]) => pattern.test(name));
    return rule ? rule[1] : 'bi-robot';
  }

  /** Replace the specialist agents in the roster with a newly designed team. */
  function buildRoster(agents, generated) {
    els.roster.querySelectorAll('.roster-item-agent').forEach((item) => item.remove());
    (agents || []).forEach((agent, index) => {
      const item = els.rosterTemplate.content.firstElementChild.cloneNode(true);
      const colorClass = `agent-color-${index % COLOR_COUNT}`;
      const icon = iconFor(agent.name);
      item.classList.add(colorClass);
      item.dataset.agent = agent.name;
      item.dataset.colorClass = colorClass;
      item.dataset.icon = icon;
      item.querySelector('.agent-avatar i').classList.add(icon);
      item.querySelector('.roster-name').textContent = agent.name;
      const role = item.querySelector('.roster-role');
      role.textContent = agent.role;
      role.title = agent.role;
      const model = item.querySelector('.roster-model');
      model.querySelector('.roster-model-name').textContent =
        `${agent.skill} · ${agent.model}`;
      model.title = `${agent.skill} skill, runs on ${agent.model}`;
      els.roster.appendChild(item);
    });

    const count = (agents || []).length;
    els.rosterHint.classList.toggle('d-none', count > 0);
    els.teamBadge.classList.toggle('d-none', count === 0);
    els.teamBadge.textContent = generated ? 'Designed for this task' : 'Default team';
    els.teamBadge.title = generated
      ? 'The team was generated from your task.'
      : 'Team generation failed, so the default team was used.';
  }

  function resetRoster() {
    buildRoster([], false);
    els.roster.querySelectorAll('.roster-item').forEach((item) => {
      item.classList.remove('is-active', 'is-done');
      item.querySelector('.roster-status').textContent = 'Idle';
    });
  }

  function onTeam(data) {
    buildRoster(data.agents, data.generated);
    const models = data.models || {};
    state.finalizerModel = models.finalizer || '';
    if (models.supervisor) {
      rosterItem(SUPERVISOR).querySelector('.roster-model-name').textContent =
        models.supervisor;
    }
    const names = (data.agents || []).map((agent) => agent.name).join(', ');
    setStatus(
      data.generated
        ? `Team ready: ${names}.`
        : `Team generation failed, so the default team is working: ${names}.`
    );
  }

  /* ------------------------------------------------------------------ */
  /* Status, timer and working indicator                                 */
  /* ------------------------------------------------------------------ */
  function setStatus(text) {
    els.statusText.textContent = text;
    els.statusText.title = text;
  }

  function startTimer() {
    stopTimer();
    state.startedAt = Date.now();
    els.statusTimer.textContent = '0:00';
    state.timerId = window.setInterval(() => {
      els.statusTimer.textContent = formatElapsed(Date.now() - state.startedAt);
    }, 1000);
  }

  function stopTimer() {
    if (state.timerId !== null) {
      window.clearInterval(state.timerId);
      state.timerId = null;
    }
  }

  function setWorking(agent, label) {
    const { colorClass } = agentInfo(agent);
    if (state.workingColorClass) {
      els.working.classList.remove(state.workingColorClass);
    }
    state.workingColorClass = colorClass;
    els.working.classList.add(colorClass);
    els.workingLabel.textContent = label;
    els.working.classList.remove('d-none');
  }

  function hideWorking() {
    els.working.classList.add('d-none');
  }

  /* ------------------------------------------------------------------ */
  /* Results rendering                                                   */
  /* ------------------------------------------------------------------ */
  function addStep(step) {
    const item = els.stepTemplate.content.firstElementChild.cloneNode(true);
    const { colorClass, icon } = agentInfo(step.agent);
    const bodyId = `step-body-${step.step}`;

    item.classList.add(colorClass);
    item.querySelector('.agent-avatar i').classList.add(icon);
    item.querySelector('.step-agent').textContent = step.agent;
    // The model that actually answered, which reflects any fallback.
    item.querySelector('.step-meta').textContent = step.model
      ? `Step ${step.step} · ${step.model}`
      : `Step ${step.step}`;
    item.querySelector('.step-body').id = bodyId;
    item.querySelector('.step-toggle').setAttribute('aria-controls', bodyId);

    const note = item.querySelector('.routing-note');
    if (step.reason) {
      note.querySelector('span').textContent = `Supervisor: ${step.reason}`;
    } else {
      note.remove();
    }

    renderMarkdown(
      item.querySelector('.markdown-body'),
      step.message || '_No response._'
    );

    els.steps.appendChild(item);
    els.stepsSection.classList.remove('d-none');
    els.emptyState.classList.add('d-none');

    state.stepCount += 1;
    els.stepCount.textContent = plural(state.stepCount, 'step');
    state.agentCounts.set(step.agent, (state.agentCounts.get(step.agent) || 0) + 1);
    setRosterStatus(step.agent, 'done', contributionLabel(step.agent));
  }

  function showFinal(text, model) {
    state.finalText = text || '';
    const finalModel = model || state.finalizerModel;
    els.finalModel.textContent = finalModel ? `· ${finalModel}` : '';
    renderMarkdown(
      els.finalOutput,
      state.finalText || '_The team did not produce a final answer._'
    );
    els.finalSection.classList.remove('d-none');
    els.emptyState.classList.add('d-none');
    els.copyBtn.disabled = !state.finalText;

    hideWorking();
    settleRoster();
    setRosterStatus(SUPERVISOR, 'done', 'Finished');
    setStatus(
      `Completed ${plural(state.stepCount, 'step')} in ` +
        `${formatElapsed(Date.now() - state.startedAt)}.`
    );
    scrollToElement(els.finalSection);
  }

  function showError(message) {
    els.errorMessage.textContent = message;
    els.errorAlert.classList.remove('d-none');
    els.emptyState.classList.add('d-none');
  }

  function hideError() {
    els.errorAlert.classList.add('d-none');
    els.errorMessage.textContent = '';
  }

  function resetResults() {
    hideError();
    hideWorking();
    els.steps.replaceChildren();
    els.stepsSection.classList.add('d-none');
    els.stepCount.textContent = '';
    els.finalSection.classList.add('d-none');
    els.finalOutput.replaceChildren();
    els.finalModel.textContent = '';
    state.finalizerModel = '';
    els.copyBtn.disabled = true;
    state.finalText = '';
    state.stepCount = 0;
    state.agentCounts.clear();
    resetRoster();
  }

  function hasResults() {
    return state.stepCount > 0 || Boolean(state.finalText);
  }

  /* ------------------------------------------------------------------ */
  /* Running the workflow                                                */
  /* ------------------------------------------------------------------ */
  function setRunning(running) {
    state.running = running;
    els.runBtn.disabled = running;
    els.runBtn.querySelector('.spinner-border').classList.toggle('d-none', !running);
    els.runBtn.querySelector('.btn-icon').classList.toggle('d-none', running);
    els.runBtn.querySelector('.btn-label').textContent = running
      ? 'Running…'
      : 'Run workflow';
    els.stopBtn.classList.toggle('d-none', !running);
    els.streamToggle.disabled = running;
    els.task.readOnly = running;
    els.form.setAttribute('aria-busy', String(running));
    if (running) {
      startTimer();
    } else {
      stopTimer();
    }
  }

  async function errorMessageFrom(response) {
    try {
      const data = await response.json();
      if (data && data.error) return data.error;
    } catch (err) {
      /* Not JSON; fall through to a generic message. */
    }
    return `Request failed with status ${response.status}.`;
  }

  function postJson(url, task, signal, accept) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: accept },
      body: JSON.stringify({ task }),
      signal,
    });
  }

  async function runStandard(task, signal) {
    setRosterStatus(SUPERVISOR, 'active', 'Coordinating');
    setWorking(SUPERVISOR, 'Designing a team and working on your task…');
    setStatus('Agents are working. This can take a minute or two.');

    const response = await postJson(api.run, task, signal, 'application/json');
    if (!response.ok) throw new Error(await errorMessageFrom(response));

    const data = await response.json();
    if (data.status !== 'success') {
      throw new Error(data.error || 'The workflow failed.');
    }
    onTeam({
      agents: data.team,
      generated: data.team_generated,
      models: data.models,
    });
    (data.steps || []).forEach(addStep);
    showFinal(data.final_response);
  }

  function parseFrame(frame) {
    let event = 'message';
    const dataLines = [];
    frame.split('\n').forEach((line) => {
      if (line.startsWith('event:')) {
        event = line.slice(6).trim();
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).replace(/^ /, ''));
      }
    });
    if (!dataLines.length) return null;
    try {
      return { event, data: JSON.parse(dataLines.join('\n')) };
    } catch (err) {
      return null;
    }
  }

  function onRouting(data) {
    if (data.next_agent === FINISH) {
      setRosterStatus(SUPERVISOR, 'done', 'Finished');
      setWorking(SUPERVISOR, 'Writing the consolidated final answer…');
      setStatus('Supervisor marked the task complete. Writing the final answer…');
      return;
    }
    setRosterStatus(SUPERVISOR, 'idle', 'Waiting');
    setRosterStatus(data.next_agent, 'active', 'Working…');
    setWorking(data.next_agent, `${data.next_agent} is working…`);
    setStatus(`Supervisor → ${data.next_agent}: ${data.reason || 'next step.'}`);
  }

  /** Handle one SSE event. Returns true once the run has completed. */
  function handleStreamEvent(type, data) {
    switch (type) {
      case 'start':
        setRosterStatus(SUPERVISOR, 'active', 'Designing…');
        setWorking(SUPERVISOR, 'Designing a team of agents for this task…');
        setStatus('Supervisor is designing a team for the task…');
        return false;
      case 'team':
        onTeam(data);
        setRosterStatus(SUPERVISOR, 'active', 'Routing…');
        setWorking(SUPERVISOR, 'Supervisor is choosing the first agent…');
        return false;
      case 'routing':
        onRouting(data);
        return false;
      case 'step':
        addStep(data);
        setRosterStatus(SUPERVISOR, 'active', 'Routing…');
        setWorking(SUPERVISOR, 'Supervisor is choosing the next agent…');
        return false;
      case 'final':
        showFinal(data.message, data.model);
        return false;
      case 'done':
        return true;
      case 'error':
        throw new Error(data.error || 'The workflow failed.');
      default:
        return false;
    }
  }

  async function runStreaming(task, signal) {
    const response = await postJson(api.stream, task, signal, 'text/event-stream');
    if (!response.ok) throw new Error(await errorMessageFrom(response));
    if (!response.body) {
      throw new Error(
        'This browser cannot read streamed responses. Turn off live streaming and try again.'
      );
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let completed = false;

    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replace(/\r/g, '');

      let boundary = buffer.indexOf('\n\n');
      while (boundary !== -1) {
        const parsed = parseFrame(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        if (parsed && handleStreamEvent(parsed.event, parsed.data)) {
          completed = true;
        }
        boundary = buffer.indexOf('\n\n');
      }
    }

    if (!completed) {
      throw new Error('The connection closed before the workflow finished.');
    }
  }

  async function run(task, streaming) {
    resetResults();
    els.emptyState.classList.add('d-none');
    setRunning(true);

    const controller = new AbortController();
    state.controller = controller;
    if (isStackedLayout()) scrollToElement(els.results);

    try {
      if (streaming) {
        await runStreaming(task, controller.signal);
      } else {
        await runStandard(task, controller.signal);
      }
    } catch (err) {
      settleRoster();
      if (err && err.name === 'AbortError') {
        setStatus('Run stopped.');
      } else {
        const message =
          err && err.message ? err.message : 'Something went wrong. Please try again.';
        showError(
          err instanceof TypeError
            ? 'Could not reach the server. Check that it is running and try again.'
            : message
        );
        setStatus('Run failed.');
      }
    } finally {
      // Releases the connection if the stream is still open after an error.
      controller.abort();
      if (state.controller === controller) state.controller = null;
      hideWorking();
      setRunning(false);
      if (!hasResults() && els.errorAlert.classList.contains('d-none')) {
        els.emptyState.classList.remove('d-none');
      }
    }
  }

  function stopRun() {
    if (state.controller) state.controller.abort();
  }

  function clearResults() {
    stopRun();
    resetResults();
    els.emptyState.classList.remove('d-none');
    els.statusTimer.textContent = '';
    setStatus('Ready.');
  }

  /* ------------------------------------------------------------------ */
  /* Copy to clipboard                                                   */
  /* ------------------------------------------------------------------ */
  function legacyCopy(text) {
    const buffer = document.createElement('textarea');
    buffer.value = text;
    buffer.setAttribute('readonly', '');
    buffer.className = 'clipboard-buffer';
    document.body.appendChild(buffer);
    buffer.select();
    let copied = false;
    try {
      copied = document.execCommand('copy');
    } catch (err) {
      copied = false;
    }
    buffer.remove();
    return copied;
  }

  async function copyFinal() {
    if (!state.finalText) return;
    let copied = false;
    try {
      await navigator.clipboard.writeText(state.finalText);
      copied = true;
    } catch (err) {
      copied = legacyCopy(state.finalText);
    }

    const label = els.copyBtn.querySelector('.copy-label');
    const icon = els.copyBtn.querySelector('i');
    label.textContent = copied ? 'Copied!' : 'Copy failed';
    icon.className = copied ? 'bi bi-clipboard-check' : 'bi bi-clipboard-x';
    window.clearTimeout(state.copyResetId);
    state.copyResetId = window.setTimeout(() => {
      label.textContent = 'Copy';
      icon.className = 'bi bi-clipboard';
    }, 2000);
  }

  /* ------------------------------------------------------------------ */
  /* Event wiring                                                        */
  /* ------------------------------------------------------------------ */
  function updateCharCount() {
    els.charCount.textContent = `${els.task.value.length} / ${els.task.maxLength}`;
  }

  function submitForm() {
    if (typeof els.form.requestSubmit === 'function') {
      els.form.requestSubmit();
    } else {
      els.runBtn.click();
    }
  }

  function onSubmit(event) {
    event.preventDefault();
    if (state.running) return;
    const task = els.task.value.trim();
    if (!task) {
      els.task.classList.add('is-invalid');
      els.task.focus();
      return;
    }
    els.task.classList.remove('is-invalid');
    run(task, els.streamToggle.checked);
  }

  function onStepToggle(event) {
    const button = event.target.closest('.step-toggle');
    if (!button) return;
    const card = button.closest('.step-card');
    const collapsed = card.classList.toggle('is-collapsed');
    button.setAttribute('aria-expanded', String(!collapsed));
    button.setAttribute('aria-label', collapsed ? 'Expand step' : 'Collapse step');
    button.querySelector('i').className = collapsed
      ? 'bi bi-chevron-down'
      : 'bi bi-chevron-up';
  }

  function bindEvents() {
    els.form.addEventListener('submit', onSubmit);
    els.task.addEventListener('input', () => {
      updateCharCount();
      els.task.classList.remove('is-invalid');
    });
    els.task.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        submitForm();
      }
    });
    els.exampleBtn.addEventListener('click', () => {
      if (state.running) return;
      els.task.value = EXAMPLE_TASK;
      els.task.classList.remove('is-invalid');
      updateCharCount();
      els.task.focus();
    });
    els.streamToggle.addEventListener('change', () => {
      storageSet(STREAM_KEY, String(els.streamToggle.checked));
    });
    els.stopBtn.addEventListener('click', stopRun);
    els.clearBtn.addEventListener('click', clearResults);
    els.copyBtn.addEventListener('click', copyFinal);
    els.errorClose.addEventListener('click', () => {
      hideError();
      if (!hasResults() && !state.running) els.emptyState.classList.remove('d-none');
    });
    els.themeToggle.addEventListener('click', () => {
      const next = currentTheme() === 'dark' ? 'light' : 'dark';
      storageSet(THEME_KEY, next);
      applyTheme(next);
    });
    els.steps.addEventListener('click', onStepToggle);
  }

  function init() {
    const byId = (id) => document.getElementById(id);
    els = {
      form: byId('task-form'),
      task: byId('task-input'),
      charCount: byId('char-count'),
      exampleBtn: byId('example-btn'),
      streamToggle: byId('stream-toggle'),
      runBtn: byId('run-btn'),
      stopBtn: byId('stop-btn'),
      clearBtn: byId('clear-btn'),
      roster: byId('agent-roster'),
      rosterHint: byId('roster-hint'),
      rosterTemplate: byId('roster-item-template'),
      teamBadge: byId('team-badge'),
      statusText: byId('status-text'),
      statusTimer: byId('status-timer'),
      results: byId('results'),
      errorAlert: byId('error-alert'),
      errorMessage: byId('error-message'),
      errorClose: byId('error-close'),
      emptyState: byId('empty-state'),
      stepsSection: byId('steps-section'),
      steps: byId('steps'),
      stepCount: byId('step-count'),
      working: byId('working-indicator'),
      workingLabel: byId('working-label'),
      finalSection: byId('final-section'),
      finalOutput: byId('final-output'),
      finalModel: byId('final-model'),
      copyBtn: byId('copy-btn'),
      themeToggle: byId('theme-toggle'),
      stepTemplate: byId('step-template'),
    };
    api = {
      run: document.body.dataset.runUrl,
      stream: document.body.dataset.streamUrl,
    };

    setupMarkdown();
    applyTheme(currentTheme()); // Sync the toggle button now that it exists.

    const savedStream = storageGet(STREAM_KEY);
    if (savedStream !== null) els.streamToggle.checked = savedStream === 'true';

    updateCharCount();
    bindEvents();
  }

  document.addEventListener('DOMContentLoaded', init);
})();
