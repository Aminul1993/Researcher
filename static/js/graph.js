/**
 * Live workflow graph for the Researcher front-end.
 *
 * Draws a run as a graph (task, team designer, supervisor, each agent,
 * finalizer and answer) and lights up each node while it works. Every node
 * execution is also listed, in order, as the execution path, and selecting a
 * step or a node shows its details.
 *
 * The stream reports when a node finishes, not when the next one starts, but
 * the graph's shape settles what runs next: the designer runs first, the
 * supervisor runs once the team is ready and after every agent step, and the
 * node the supervisor routes to runs after it. So each event ends the node in
 * progress and starts the next one.
 *
 * Exposes window.WorkflowGraph.create(section, options).
 */
(function () {
  'use strict';

  const SVG_NS = 'http://www.w3.org/2000/svg';
  const FINISH = 'FINISH';
  const COLLAPSED_KEY = 'agent-orchestrator:graph-collapsed';
  const SYSTEM_COLOR = 'agent-supervisor';
  const ANSWER_COLOR = 'graph-color-answer';
  const EXCERPT_LENGTH = 320;
  const TASK_EXCERPT_LENGTH = 600;

  // Edge geometry, in CSS pixels.
  const ARROW_LENGTH = 6;
  const ARROW_HALF_WIDTH = 3.5;
  const NODE_GAP = 3; // Space between an arrow tip and the node it reaches
  const HUB_SPACING = 16; // Between agents' attachment points on the supervisor
  const LANE_OFFSET = 4; // Separates an agent's outgoing and returning edges

  // The fixed nodes, left to right along the main row: [id, label, icon].
  const SYSTEM_NODES = [
    ['task', 'Task', 'bi-chat-square-text'],
    ['designer', 'Team designer', 'bi-magic'],
    ['supervisor', 'Supervisor', 'bi-diagram-3'],
    ['finalizer', 'Finalizer', 'bi-intersect'],
    ['answer', 'Answer', 'bi-stars'],
  ];
  const MAIN_EDGES = [
    ['task', 'designer'],
    ['designer', 'supervisor'],
    ['supervisor', 'finalizer'],
    ['finalizer', 'answer'],
  ];

  // What a node is doing while it runs, by kind.
  const ACTIVE_VERBS = {
    designer: 'Designing',
    supervisor: 'Routing',
    agent: 'Working',
    finalizer: 'Writing',
  };
  const VISIT_STATUS = { done: 'Done', error: 'Failed', stopped: 'Stopped' };
  const RUN_STATES = {
    running: 'Live',
    done: 'Completed',
    failed: 'Failed',
    stopped: 'Stopped',
  };

  /* ------------------------------------------------------------------ */
  /* Small utilities                                                     */
  /* ------------------------------------------------------------------ */
  function plural(count, word, many = `${word}s`) {
    return `${count} ${count === 1 ? word : many}`;
  }

  /** A clock that is still running: 0:07, 1:42. */
  function formatClock(ms) {
    const total = Math.max(0, Math.floor(ms / 1000));
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
  }

  /** A finished duration: 0.4s, 12s, 1:05. */
  function formatDuration(ms) {
    if (ms >= 60000) return formatClock(ms);
    const seconds = Math.max(0, ms) / 1000;
    return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)}s`;
  }

  /** A short plain-text preview of a Markdown reply. */
  function excerpt(text, limit) {
    const plain = String(text || '')
      .replace(/```[\s\S]*?(?:```|$)/g, '\n[code]\n')
      .replace(/^\s{0,3}(?:#{1,6}|>)\s*/gm, '')
      .replace(/\*\*|__|`/g, '')
      .replace(/\s+/g, ' ')
      .trim();
    return plain.length > limit
      ? `${plain.slice(0, limit - 1).trimEnd()}…`
      : plain;
  }

  function el(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function iconEl(name) {
    const element = el('i', `bi ${name}`);
    element.setAttribute('aria-hidden', 'true');
    return element;
  }

  function avatarEl(name) {
    const avatar = el('span', 'agent-avatar');
    avatar.append(iconEl(name));
    return avatar;
  }

  function svgEl(tag, className) {
    const element = document.createElementNS(SVG_NS, tag);
    if (className) element.setAttribute('class', className);
    return element;
  }

  function round(value) {
    return Math.round(value * 10) / 10;
  }

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

  function agentId(name) {
    return `agent:${name}`;
  }

  function edgeKey(from, to) {
    return `${from}>${to}`;
  }

  /** A straight edge along the main row, pointing right. */
  function horizontalEdge(x0, y, x1) {
    const end = x1 - ARROW_LENGTH;
    return {
      line: `M ${round(x0)} ${round(y)} L ${round(end)} ${round(y)}`,
      head:
        `M ${round(end)} ${round(y - ARROW_HALF_WIDTH)} ` +
        `L ${round(x1)} ${round(y)} ` +
        `L ${round(end)} ${round(y + ARROW_HALF_WIDTH)} Z`,
    };
  }

  /** A curved edge between the rows, pointing up or down. */
  function verticalEdge(x0, y0, x1, y1) {
    const direction = y1 >= y0 ? 1 : -1;
    const end = y1 - direction * ARROW_LENGTH;
    const middle = (y0 + end) / 2;
    return {
      line:
        `M ${round(x0)} ${round(y0)} ` +
        `C ${round(x0)} ${round(middle)}, ${round(x1)} ${round(middle)}, ` +
        `${round(x1)} ${round(end)}`,
      head:
        `M ${round(x1 - ARROW_HALF_WIDTH)} ${round(end)} ` +
        `L ${round(x1)} ${round(y1)} ` +
        `L ${round(x1 + ARROW_HALF_WIDTH)} ${round(end)} Z`,
    };
  }

  /* ------------------------------------------------------------------ */
  /* The graph                                                           */
  /* ------------------------------------------------------------------ */
  /**
   * Bind a graph to its section of the page.
   *
   * options.agentStyle(name) returns { colorClass, icon } so agents match
   * the roster; options.onOpenStep(stepNumber) and options.onOpenFinal()
   * reveal a step's full contribution and the final answer.
   */
  function create(section, options) {
    const els = {
      toggle: section.querySelector('.graph-toggle'),
      state: section.querySelector('.graph-state'),
      canvas: section.querySelector('.graph-canvas'),
      edges: section.querySelector('.graph-edges'),
      mainRow: section.querySelector('.graph-row-main'),
      agentRow: section.querySelector('.graph-row-agents'),
      trail: section.querySelector('.graph-trail'),
      detail: section.querySelector('.graph-detail'),
    };
    let run = null;
    let edgeFrame = 0;

    /* ---------------- Model ---------------- */
    function addNode(spec) {
      const node = {
        role: '',
        skill: '',
        model: '',
        ...spec,
        status: 'pending',
        visits: [],
      };
      const button = el('button', 'graph-node');
      button.type = 'button';
      node.metaEl = el('span', 'graph-node-meta');
      button.append(
        avatarEl(node.icon),
        el('span', 'graph-node-name', node.label),
        node.metaEl
      );
      button.title = node.role || node.label;
      button.addEventListener('click', () => selectNode(node));
      node.el = button;
      run.nodes.set(node.id, node);
      return node;
    }

    function addEdge(from, to, colorClass, kind) {
      const group = svgEl('g', `graph-edge ${colorClass}`);
      const line = svgEl('path', 'graph-edge-line');
      const head = svgEl('path', 'graph-edge-head');
      group.append(line, head);
      els.edges.append(group);
      run.edges.set(edgeKey(from, to), {
        from: run.nodes.get(from),
        to: run.nodes.get(to),
        kind,
        traversals: 0,
        el: group,
        line,
        head,
      });
    }

    function addAgent(agent) {
      const style = options.agentStyle(agent.name);
      const node = addNode({
        id: agentId(agent.name),
        kind: 'agent',
        label: agent.name,
        icon: style.icon,
        colorClass: style.colorClass,
        role: agent.role || '',
        skill: agent.skill || '',
        model: agent.model || '',
      });
      els.agentRow.append(node.el);
      addEdge('supervisor', node.id, style.colorClass, 'down');
      addEdge(node.id, 'supervisor', style.colorClass, 'up');
      return node;
    }

    function traverse(from, to) {
      const edge = run.edges.get(edgeKey(from, to));
      if (edge) edge.traversals += 1;
    }

    /** Start a visit of a node, reached along the edge from another. */
    function enter(nodeId, fromId) {
      const node = run.nodes.get(nodeId);
      const visit = {
        index: run.visits.length,
        node,
        from: fromId,
        status: 'active',
        startedAt: Date.now(),
        endedAt: 0,
      };
      run.visits.push(visit);
      node.visits.push(visit);
      node.status = 'active';
      run.current = visit;
      traverse(fromId, nodeId);
      appendTrailItem(visit);
    }

    /** End the visit in progress, recording what it produced. */
    function leave(details) {
      const visit = run.current;
      if (!visit) return;
      Object.assign(visit, details, { status: 'done', endedAt: Date.now() });
      visit.node.status = 'done';
      run.current = null;
    }

    /** End the run; a visit still in progress ends with ``status``. */
    function finish(state, status, error) {
      const visit = run.current;
      if (visit) {
        Object.assign(visit, { status, error, endedAt: Date.now() });
        visit.node.status = status;
        run.current = null;
      }
      run.nodes.forEach((node) => {
        if (node.status === 'pending') node.status = 'skipped';
      });
      run.state = state;
      window.clearInterval(run.timerId);
      render();
    }

    function isRunning() {
      return Boolean(run) && run.state === 'running';
    }

    /* ---------------- Public API: one call per stream event ---------------- */
    function begin(task, { live = true } = {}) {
      clear();
      run = {
        task,
        live,
        state: 'running',
        nodes: new Map(),
        edges: new Map(),
        visits: [],
        current: null,
        selection: null,
        teamSize: 0,
        timerId: null,
        detailKey: '',
        detailMetaEl: null,
      };
      SYSTEM_NODES.forEach(([id, label, icon]) => {
        const colorClass = id === 'answer' ? ANSWER_COLOR : SYSTEM_COLOR;
        els.mainRow.append(
          addNode({ id, kind: id, label, icon, colorClass }).el
        );
      });
      MAIN_EDGES.forEach(([from, to]) => {
        addEdge(from, to, to === 'answer' ? ANSWER_COLOR : SYSTEM_COLOR, 'main');
      });
      run.nodes.get('task').status = 'done';
      if (live) {
        const placeholder = el('div', 'graph-placeholder');
        placeholder.append(
          iconEl('bi-magic'),
          el('span', '', 'The team appears here once it is designed.')
        );
        els.agentRow.append(placeholder);
        run.timerId = window.setInterval(tick, 1000);
      }
      enter('designer', 'task');
      section.classList.remove('d-none');
      render();
      scheduleEdges();
    }

    function team(data) {
      if (!isRunning()) return;
      const agents = data.agents || [];
      const models = data.models || {};
      leave({
        agents,
        generated: Boolean(data.generated),
        model: models.designer || '',
      });
      ['designer', 'supervisor', 'finalizer'].forEach((id) => {
        run.nodes.get(id).model = models[id] || '';
      });
      run.teamSize = agents.length;
      els.agentRow.replaceChildren();
      agents.forEach(addAgent);
      enter('supervisor', 'designer');
      render();
      scheduleEdges();
    }

    function routing(data) {
      if (!isRunning()) return;
      const next = data.next_agent;
      leave({ decision: next, reason: data.reason || '' });
      if (next === FINISH) {
        enter('finalizer', 'supervisor');
      } else {
        if (!run.nodes.has(agentId(next))) {
          addAgent({ name: next });
          scheduleEdges();
        }
        enter(agentId(next), 'supervisor');
      }
      render();
    }

    function step(data) {
      if (!isRunning()) return;
      leave({
        step: data.step,
        model: data.model || '',
        message: data.message || '',
      });
      enter('supervisor', agentId(data.agent));
      render();
    }

    function final(data) {
      if (!isRunning()) return;
      leave({ model: data.model || '' });
      run.nodes.get('answer').status = 'done';
      traverse('finalizer', 'answer');
      render();
    }

    function complete() {
      if (isRunning()) finish('done');
    }

    function fail(message) {
      if (isRunning()) finish('failed', 'error', message);
    }

    function stop() {
      if (isRunning()) finish('stopped', 'stopped');
    }

    /** Draw a finished /api/run result as if it had been streamed. */
    function replay(task, result) {
      const models = result.models || {};
      begin(task, { live: false });
      team({
        agents: result.team,
        generated: result.team_generated,
        models,
      });
      (result.steps || []).forEach((record) => {
        routing({ next_agent: record.agent, reason: record.reason });
        step(record);
      });
      routing({ next_agent: FINISH, reason: '' });
      final({ model: models.finalizer || '' });
      complete();
    }

    function clear() {
      if (run) window.clearInterval(run.timerId);
      if (edgeFrame) window.cancelAnimationFrame(edgeFrame);
      edgeFrame = 0;
      run = null;
      [els.mainRow, els.agentRow, els.edges, els.trail, els.detail].forEach(
        (element) => element.replaceChildren()
      );
      section.classList.add('d-none');
    }

    /* ---------------- Selection ---------------- */
    function selectVisit(visit) {
      const pinned = run.selection && run.selection.visit === visit;
      run.selection = pinned ? null : { visit };
      render();
    }

    /** Show a node's latest visit, or the node itself if it has not run. */
    function selectNode(node) {
      if (!run) return;
      const latest = node.visits[node.visits.length - 1];
      if (latest) {
        selectVisit(latest);
        return;
      }
      const pinned = run.selection && run.selection.node === node;
      run.selection = pinned ? null : { node };
      render();
    }

    function followLive() {
      run.selection = null;
      render();
      if (run.current) run.current.chip.focus();
    }

    /** What the details panel shows: the pinned item, else the live step. */
    function shownItem() {
      if (run.selection) return run.selection;
      const visit = run.current || run.visits[run.visits.length - 1];
      return visit ? { visit } : null;
    }

    function pinnedNode() {
      const selection = run.selection;
      if (!selection) return null;
      return selection.visit ? selection.visit.node : selection.node;
    }

    /* ---------------- Text ---------------- */
    function visitTime(visit) {
      if (!run.live) return '';
      if (visit.endedAt) return formatDuration(visit.endedAt - visit.startedAt);
      return formatClock(Date.now() - visit.startedAt);
    }

    function totalTime(node) {
      if (!run.live || !node.visits.length) return '';
      const total = node.visits.reduce(
        (sum, visit) =>
          sum + (visit.endedAt ? visit.endedAt - visit.startedAt : 0),
        0
      );
      return formatDuration(total);
    }

    function nodeMeta(node) {
      if (run.current && run.current.node === node) {
        const verb = ACTIVE_VERBS[node.kind];
        return run.live ? `${verb} · ${visitTime(run.current)}` : `${verb}…`;
      }
      switch (node.status) {
        case 'error':
          return 'Failed';
        case 'stopped':
          return 'Stopped';
        case 'skipped':
          return node.kind === 'agent' ? 'Not called' : 'Not reached';
        case 'pending':
          return node.kind === 'agent' && node.skill ? node.skill : 'Waiting';
        default:
          break;
      }
      const summary = {
        task: 'Received',
        answer: 'Ready',
        designer: plural(run.teamSize, 'agent'),
        supervisor: plural(node.visits.length, 'decision'),
        agent: plural(node.visits.length, 'reply', 'replies'),
        finalizer: 'Merged',
      }[node.kind];
      const time = totalTime(node);
      return time ? `${summary} · ${time}` : summary;
    }

    function trailLabel(visit) {
      if (visit.node.kind !== 'supervisor') return visit.node.label;
      if (!visit.decision) return 'Routing';
      return `→ ${visit.decision === FINISH ? 'Finish' : visit.decision}`;
    }

    /** The trail item's accessible name, which has no arrows or icons. */
    function describeVisit(visit) {
      const node = visit.node;
      let text = node.label;
      if (node.kind === 'supervisor') {
        if (visit.decision === FINISH) {
          text = 'Supervisor marked the task complete';
        } else if (visit.decision) {
          text = `Supervisor routed to ${visit.decision}`;
        } else {
          text = 'Supervisor, routing';
        }
      } else if (visit.step) {
        text = `Step ${visit.step}, ${node.label}`;
      }
      if (visit.status === 'active') return `${text}, in progress`;
      if (visit.status !== 'done') {
        text = `${text}, ${VISIT_STATUS[visit.status].toLowerCase()}`;
      }
      const time = visitTime(visit);
      return time ? `${text}, ${time}` : text;
    }

    function visitTitle(visit) {
      const node = visit.node;
      switch (node.kind) {
        case 'designer':
          return 'Team design';
        case 'supervisor':
          return `Routing decision ${node.visits.indexOf(visit) + 1}`;
        case 'agent':
          return visit.step ? `Step ${visit.step} · ${node.label}` : node.label;
        default:
          return node.label;
      }
    }

    function detailMeta(item) {
      if (item.visit) {
        const visit = item.visit;
        const status =
          visit.status === 'active'
            ? ACTIVE_VERBS[visit.node.kind]
            : VISIT_STATUS[visit.status];
        const model = visit.model || visit.node.model;
        return [status, visitTime(visit), model].filter(Boolean).join(' · ');
      }
      const node = item.node;
      return [nodeMeta(node), node.kind === 'agent' ? node.model : '']
        .filter(Boolean)
        .join(' · ');
    }

    /* ---------------- Rendering ---------------- */
    function render() {
      if (!run) return;
      const pinned = pinnedNode();
      run.nodes.forEach((node) => {
        node.el.className =
          `graph-node ${node.colorClass} is-${node.status}` +
          (node === pinned ? ' is-selected' : '');
        node.el.setAttribute('aria-pressed', String(node === pinned));
        node.metaEl.textContent = nodeMeta(node);
      });
      renderEdgeStates();
      run.visits.forEach(renderTrailItem);
      els.state.textContent = RUN_STATES[run.state];
      els.state.className = `graph-state is-${run.state}`;
      renderDetail();
    }

    function renderEdgeStates() {
      const current = run.current;
      const activeKey = current ? edgeKey(current.from, current.node.id) : '';
      run.edges.forEach((edge, key) => {
        const active = key === activeKey;
        edge.el.classList.toggle('is-traversed', edge.traversals > 0);
        edge.el.classList.toggle('is-active', active);
        // Draw the active edge last, so no idle edge crosses over it.
        if (active && els.edges.lastChild !== edge.el) {
          els.edges.append(edge.el);
        }
      });
    }

    function appendTrailItem(visit) {
      const item = el('li');
      const chip = el('button', 'trail-step');
      chip.type = 'button';
      visit.labelEl = el('span', 'trail-label');
      visit.timeEl = el('span', 'trail-time');
      chip.append(iconEl(visit.node.icon), visit.labelEl, visit.timeEl);
      chip.addEventListener('click', () => selectVisit(visit));
      item.append(chip);
      visit.chip = chip;
      els.trail.append(item);
    }

    function renderTrailItem(visit) {
      const pinned = Boolean(run.selection) && run.selection.visit === visit;
      visit.chip.className =
        `trail-step ${visit.node.colorClass} is-${visit.status}`;
      visit.chip.setAttribute('aria-pressed', String(pinned));
      visit.chip.setAttribute('aria-label', describeVisit(visit));
      visit.labelEl.textContent = trailLabel(visit);
      visit.timeEl.textContent = visitTime(visit);
    }

    /** Rebuild the details only when they change, so focus is kept. */
    function renderDetail() {
      const item = shownItem();
      if (!item) return;
      const subject = item.visit
        ? `visit-${item.visit.index}-${item.visit.status}`
        : `node-${item.node.id}-${item.node.status}`;
      const key = `${subject}:${Boolean(run.selection)}:${run.state}`;
      if (key !== run.detailKey) {
        run.detailKey = key;
        buildDetail(item);
      }
      run.detailMetaEl.textContent = detailMeta(item);
    }

    function paragraph(text, className = '') {
      return el('p', `graph-detail-text ${className}`.trim(), text);
    }

    /** A button that jumps to the full content further down the page. */
    function openButton(label, onClick) {
      const button = el('button', 'btn btn-sm btn-outline-secondary');
      button.type = 'button';
      button.append(
        iconEl('bi-arrow-down-circle'),
        document.createTextNode(` ${label}`)
      );
      button.addEventListener('click', onClick);
      const actions = el('div', 'graph-detail-actions');
      actions.append(button);
      return actions;
    }

    function reasonNote(reason) {
      const note = el('p', 'routing-note graph-detail-reason');
      note.append(iconEl('bi-signpost-split'), el('span', '', reason));
      return note;
    }

    function teamList(agents) {
      const list = el('ul', 'graph-detail-team');
      agents.forEach((agent) => {
        const item = el('li');
        item.append(
          el('strong', '', agent.name),
          document.createTextNode(agent.skill ? ` · ${agent.skill}` : '')
        );
        list.append(item);
      });
      return list;
    }

    function visitBody(visit) {
      const node = visit.node;
      const active = visit.status === 'active';
      const parts = [];
      switch (node.kind) {
        case 'designer':
          if (active) {
            parts.push(paragraph(
              'Reading the task and designing a team of specialists for it.'
            ));
          } else if (visit.agents) {
            parts.push(paragraph(
              visit.generated
                ? `Designed ${plural(visit.agents.length, 'agent')} for this task:`
                : "The designer's reply could not be used, so the default team took over:"
            ));
            parts.push(teamList(visit.agents));
          }
          break;
        case 'supervisor':
          if (active) {
            parts.push(paragraph(
              'Reading the work so far to choose who acts next.'
            ));
          } else if (visit.decision === FINISH) {
            parts.push(paragraph(
              'Marked the task complete and handed over to the finalizer.'
            ));
          } else if (visit.decision) {
            parts.push(paragraph(`Routed the work to ${visit.decision}.`));
          }
          if (visit.reason) parts.push(reasonNote(visit.reason));
          break;
        case 'agent':
          if (node.role) parts.push(paragraph(node.role, 'graph-detail-role'));
          if (active) {
            parts.push(paragraph('Working on its part of the task.'));
          } else if (visit.step) {
            parts.push(paragraph(
              excerpt(visit.message, EXCERPT_LENGTH) || 'No response.'
            ));
            parts.push(openButton('Read full contribution', () =>
              options.onOpenStep(visit.step)
            ));
          }
          break;
        case 'finalizer':
          if (active) {
            parts.push(paragraph("Merging the team's work into one final answer."));
          } else if (visit.status === 'done') {
            parts.push(paragraph("Merged the team's work into the final answer."));
            parts.push(openButton('Read final answer', options.onOpenFinal));
          }
          break;
        default:
          break;
      }
      if (visit.status === 'error') {
        parts.push(paragraph(
          visit.error ? `The run failed here: ${visit.error}` : 'The run failed here.',
          'graph-detail-error'
        ));
      } else if (visit.status === 'stopped') {
        parts.push(paragraph('The run was stopped here.'));
      }
      return parts;
    }

    function nodeBody(node) {
      const running = run.state === 'running';
      switch (node.kind) {
        case 'task':
          return [paragraph(excerpt(run.task, TASK_EXCERPT_LENGTH))];
        case 'answer':
          if (node.status === 'done') {
            return [
              paragraph('The final answer is ready.'),
              openButton('Read final answer', options.onOpenFinal),
            ];
          }
          return [paragraph(
            running
              ? "Appears once the finalizer has merged the team's work."
              : 'The run ended before an answer was written.'
          )];
        case 'agent':
          return [
            node.role ? paragraph(node.role, 'graph-detail-role') : null,
            paragraph(
              running
                ? 'The supervisor has not called this agent yet.'
                : 'The supervisor did not call this agent in this run.'
            ),
          ].filter(Boolean);
        default:
          return [paragraph(running ? 'Not reached yet.' : 'Not reached in this run.')];
      }
    }

    function buildDetail(item) {
      const node = item.visit ? item.visit.node : item.node;
      els.detail.className = `graph-detail ${node.colorClass}`;

      const head = el('div', 'graph-detail-head');
      const titles = el('div', 'graph-detail-titles');
      run.detailMetaEl = el('p', 'graph-detail-meta');
      titles.append(
        el('h3', 'graph-detail-title', item.visit ? visitTitle(item.visit) : node.label),
        run.detailMetaEl
      );
      head.append(avatarEl(node.icon), titles);
      if (run.selection && run.state === 'running') {
        const follow = el('button', 'btn btn-sm btn-link graph-follow');
        follow.type = 'button';
        follow.append(iconEl('bi-broadcast'), document.createTextNode(' Follow live'));
        follow.addEventListener('click', followLive);
        head.append(follow);
      }
      els.detail.replaceChildren(
        head,
        ...(item.visit ? visitBody(item.visit) : nodeBody(node))
      );
    }

    /** Once a second: advance the clocks of the step in progress. */
    function tick() {
      if (!isRunning() || !run.current) return;
      const visit = run.current;
      visit.node.metaEl.textContent = nodeMeta(visit.node);
      visit.timeEl.textContent = visitTime(visit);
      const item = shownItem();
      if (item && item.visit === visit) {
        run.detailMetaEl.textContent = detailMeta(item);
      }
    }

    /* ---------------- Edge geometry ---------------- */
    function scheduleEdges() {
      if (!edgeFrame) edgeFrame = window.requestAnimationFrame(drawEdges);
    }

    /**
     * A node's box within the canvas. Uses layout offsets rather than
     * getBoundingClientRect, which would include the entry animation's
     * transform and leave the edges a few pixels off once it ends.
     */
    function box(node) {
      let left = 0;
      let top = 0;
      for (let at = node.el; at && at !== els.canvas; at = at.offsetParent) {
        left += at.offsetLeft;
        top += at.offsetTop;
      }
      const width = node.el.offsetWidth;
      const height = node.el.offsetHeight;
      return {
        left,
        top,
        right: left + width,
        bottom: top + height,
        centerX: left + width / 2,
        centerY: top + height / 2,
        width,
      };
    }

    function drawEdges() {
      edgeFrame = 0;
      if (!run || !els.canvas.offsetWidth) return; // Hidden or collapsed.

      const agents = [...run.nodes.values()].filter((n) => n.kind === 'agent');
      const hub = box(run.nodes.get('supervisor'));
      const spacing = Math.min(
        HUB_SPACING,
        (hub.width * 0.75) / Math.max(agents.length, 1)
      );
      const hubX = (agent) =>
        hub.centerX + (agents.indexOf(agent) - (agents.length - 1) / 2) * spacing;

      run.edges.forEach((edge) => {
        let shape;
        if (edge.kind === 'main') {
          const from = box(edge.from);
          const to = box(edge.to);
          shape = horizontalEdge(
            from.right + NODE_GAP,
            from.centerY,
            to.left - NODE_GAP
          );
        } else if (edge.kind === 'down') {
          const agent = box(edge.to);
          shape = verticalEdge(
            hubX(edge.to) - LANE_OFFSET,
            hub.bottom + NODE_GAP,
            agent.centerX - LANE_OFFSET * 2,
            agent.top - NODE_GAP
          );
        } else {
          const agent = box(edge.from);
          shape = verticalEdge(
            agent.centerX + LANE_OFFSET * 2,
            agent.top - NODE_GAP,
            hubX(edge.from) + LANE_OFFSET,
            hub.bottom + NODE_GAP
          );
        }
        edge.line.setAttribute('d', shape.line);
        edge.head.setAttribute('d', shape.head);
      });
    }

    /* ---------------- Collapse ---------------- */
    function setCollapsed(collapsed) {
      section.classList.toggle('is-collapsed', collapsed);
      els.toggle.setAttribute('aria-expanded', String(!collapsed));
      els.toggle.setAttribute(
        'aria-label',
        `${collapsed ? 'Expand' : 'Collapse'} workflow graph`
      );
      els.toggle.querySelector('i').className = collapsed
        ? 'bi bi-chevron-down'
        : 'bi bi-chevron-up';
    }

    els.toggle.addEventListener('click', () => {
      const collapsed = !section.classList.contains('is-collapsed');
      setCollapsed(collapsed);
      storageSet(COLLAPSED_KEY, String(collapsed));
    });
    setCollapsed(storageGet(COLLAPSED_KEY) === 'true');

    // Redraw the edges whenever the layout moves: on resize, on expanding
    // the section, and once the icon font has loaded.
    new ResizeObserver(scheduleEdges).observe(els.canvas);
    if (document.fonts) document.fonts.ready.then(scheduleEdges);

    return {
      begin,
      team,
      routing,
      step,
      final,
      complete,
      fail,
      stop,
      replay,
      clear,
    };
  }

  window.WorkflowGraph = { create };
})();
