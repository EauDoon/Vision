'use strict';

(() => {
  const el = id => document.getElementById(id);
  const canvas = el('scene');
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  // The readable directory is the model for both the drawing and the local query.
  const components = [...document.querySelectorAll('.cards article')].map(article => ({
    id: article.id,
    name: article.querySelector('h3').textContent,
    label: article.dataset.label,
    description: article.querySelector('.meaning').textContent,
    path: article.querySelector('.source').textContent,
    inputs: [...article.querySelectorAll('.inputs a')].map(link => link.hash.slice(1)),
    position: article.dataset.position.split(' ').map(Number)
  }));
  const byId = new Map(components.map(component => [component.id, component]));
  const selector = el('component');
  const initialYaw = -0.12, initialPitch = 0.18;
  let yaw = initialYaw, pitch = initialPitch, active, projected = [], drag;
  selector.replaceChildren(...components.map(node => new Option(node.name, node.id)));

  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

  // Keep the six projected labels apart as their depth order changes on orbit.
  function arrange(nodes, width, height) {
    for (let pass = 0; pass < 28; pass++) {
      let settled = true;
      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i];
        for (const b of nodes.slice(i + 1)) {
          const dx = b.x - a.x, dy = b.y - a.y;
          const overlapX = a.w + b.w + 12 - Math.abs(dx);
          const overlapY = a.h + b.h + 12 - Math.abs(dy);
          if (overlapX <= .1 || overlapY <= .1) continue;
          settled = false;
          if (overlapX < overlapY) {
            const shift = (dx >= 0 ? 1 : -1) * overlapX / 2;
            a.x -= shift; b.x += shift;
          } else {
            const shift = (dy >= 0 ? 1 : -1) * overlapY / 2;
            a.y -= shift; b.y += shift;
          }
        }
      }
      for (const node of nodes) {
        node.x = clamp(node.x, node.w + 6, width - node.w - 6);
        node.y = clamp(node.y, node.h + 6, height - node.h - 10);
      }
      if (settled && pass > 0) break;
    }
  }

  // Find an unobstructed route, using a side channel when the camera lines up cards.
  function route(start, end, nodes, width) {
    const obstacles = nodes.filter(p => p !== start && p !== end);
    function crosses(a, b, rect) {
      let lo = 0, hi = 1;
      for (const [axis, half] of [['x', rect.w + 3], ['y', rect.h + 4]]) {
        const delta = b[axis] - a[axis], offset = a[axis] - rect[axis];
        if (Math.abs(delta) < .01) {
          if (Math.abs(offset) >= half) return false;
        } else {
          const p = (-half - offset) / delta, q = (half - offset) / delta;
          lo = Math.max(lo, Math.min(p, q));
          hi = Math.min(hi, Math.max(p, q));
        }
      }
      return lo < hi;
    }
    const clear = (a, b) => obstacles.every(rect => !crosses(a, b, rect));
    if (clear(start, end)) return [start, end];
    let best = null, shortest = Infinity;
    for (const node of obstacles) {
      for (const side of [-1, 1]) {
        const x = clamp(node.x + side * (node.w + 10), 3, width - 3);
        const near = {x, y: start.y}, far = {x, y: end.y};
        const distance = Math.abs(x - start.x) + Math.abs(start.y - end.y) + Math.abs(end.x - x);
        if (Math.abs(x - end.x) < end.w + 12 || Math.abs(x - start.x) < start.w + 3) continue;
        if (distance < shortest && clear(start, near) && clear(near, far) && clear(far, end)) {
          best = [start, near, far, end];
          shortest = distance;
        }
      }
    }
    return best || [start, end];
  }

  function render() {
    const width = canvas.clientWidth, height = canvas.clientHeight;
    if (!width || !height) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 3);
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    const compact = width < 510;
    ctx.font = '600 ' + (compact ? 13 : 15) + 'px Arial';
    function project([x, y, z]) {
      const X = x * Math.cos(yaw) + z * Math.sin(yaw);
      const depth = z * Math.cos(yaw) - x * Math.sin(yaw);
      const Y = y * Math.cos(pitch) - depth * Math.sin(pitch);
      const Z = y * Math.sin(pitch) + depth * Math.cos(pitch);
      const perspective = 560 / (560 - Z);
      return {x: width / 2 + X * (width - (compact ? 100 : 165)) / 400 * perspective,
              y: height * .52 + Y * (height - 56) / 265 * perspective, depth: Z};
    }
    // A perspective floor gives the orbit a reference without introducing data edges.
    ctx.lineWidth = .8;
    ctx.strokeStyle = '#42664c';
    function floorLine(a, b) {
      const first = project(a), last = project(b);
      ctx.beginPath(); ctx.moveTo(first.x, first.y); ctx.lineTo(last.x, last.y); ctx.stroke();
    }
    ctx.save();
    ctx.globalAlpha = .5;
    for (let i = -180; i <= 180; i += 30) {
      floorLine([i, 138, -140], [i, 138, 140]);
      floorLine([-180, 138, i], [180, 138, i]);
    }
    ctx.restore();
    projected = components.map(node => {
      const label = compact ? node.label : node.name;
      return {...project(node.position), node, label, w: ctx.measureText(label).width / 2 + 12, h: compact ? 14 : 18};
    }).sort((a, b) => a.depth - b.depth);
    arrange(projected, width, height);
    for (const end of projected) {
      for (const input of end.node.inputs) {
        const start = projected.find(point => point.node.id === input);
        const path = route(start, end, projected, width);
        const last = path[path.length - 2];
        const dx = end.x - last.x, dy = end.y - last.y;
        // Connect the card boundaries. Stop the arrow before the lower bevel.
        const inset = Math.min((end.w + 3) / Math.abs(dx), (end.h + 4) / Math.abs(dy));
        const tip = {x: end.x - dx * inset, y: end.y - dy * inset};
        const near = start.node === active || end.node === active;
        ctx.strokeStyle = near ? '#d4f59b' : '#8aa994';
        ctx.fillStyle = ctx.strokeStyle;
        ctx.lineWidth = near ? 2 : 1.4;
        ctx.beginPath(); ctx.moveTo(start.x, start.y);
        for (const point of path.slice(1, -1)) ctx.lineTo(point.x, point.y);
        ctx.lineTo(tip.x, tip.y); ctx.stroke();
        const angle = Math.atan2(dy, dx);
        ctx.beginPath(); ctx.moveTo(tip.x, tip.y);
        for (const turn of [-.46, .46]) ctx.lineTo(tip.x - 9 * Math.cos(angle + turn), tip.y - 9 * Math.sin(angle + turn));
        ctx.closePath(); ctx.fill();
      }
    }
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    for (const node of projected) {
      const on = node.node === active;
      const x = node.x - node.w, y = node.y - node.h;
      ctx.fillStyle = on ? '#7eab62' : '#426a53';
      ctx.beginPath(); ctx.roundRect(x, y + 3, node.w * 2, node.h * 2, 5); ctx.fill();
      ctx.fillStyle = on ? '#d9f49d' : '#183b2d';
      ctx.strokeStyle = on ? '#efffc4' : '#91b69a';
      ctx.lineWidth = on ? 2 : 1;
      ctx.beginPath(); ctx.roundRect(x, y, node.w * 2, node.h * 2, 5); ctx.fill(); ctx.stroke();
      ctx.fillStyle = on ? '#172e21' : '#f3f7e8';
      ctx.fillText(node.label, node.x, node.y);
    }
  }

  function inspect(id, share) {
    active = byId.get(id) || byId.get('compare');
    selector.value = active.id;
    el('inspector-title').textContent = active.name;
    el('inspector-description').textContent = active.description;
    el('jump').href = '#' + active.id;
    el('query').textContent = 'query { component(id: "' + active.id + '") { id name path inputs { id name } } }';
    const {name, path, inputs} = active;
    const component = {id: active.id, name, path, inputs: inputs.map(id => ({id, name: byId.get(id).name}))};
    el('answer').textContent = JSON.stringify({data: {component}}, null, 2);
    if (share) {
      const url = new URL(location.href);
      url.searchParams.set('node', active.id);
      try { history.replaceState(history.state, '', url); }
      catch { /* The selector also works when browser history is unavailable. */ }
    }
    render();
  }

  function rotate(dx, dy) {
    yaw += dx;
    pitch = Math.max(-.85, Math.min(.85, pitch + dy));
    render();
  }
  selector.addEventListener('change', () => inspect(selector.value, true));
  el('left').addEventListener('click', () => rotate(-.24, 0));
  el('right').addEventListener('click', () => rotate(.24, 0));
  el('reset').addEventListener('click', () => { yaw = initialYaw; pitch = initialPitch; render(); });
  canvas.addEventListener('keydown', event => {
    const angles = {ArrowLeft: [-.24,0], ArrowRight: [.24,0], ArrowUp: [0,-.14], ArrowDown: [0,.14]};
    if (!Object.hasOwn(angles, event.key)) return;
    event.preventDefault();
    rotate(...angles[event.key]);
  });
  canvas.addEventListener('pointerdown', event => {
    if (!event.isPrimary || event.button !== 0) return;
    drag = {id: event.pointerId, startX: event.clientX, startY: event.clientY, x: event.clientX, y: event.clientY, distance: 0};
    canvas.setPointerCapture(drag.id);
  });
  function isTouchOrbit(x, y) {
    if (!drag.axis) {
      const dx = Math.abs(x - drag.startX), dy = Math.abs(y - drag.startY);
      if (Math.max(dx, dy) > 4) drag.axis = dx > dy ? 'orbit' : 'scroll';
    }
    return drag.axis === 'orbit';
  }
  // Claim a one-finger horizontal orbit before the browser starts a fling.
  // A vertical gesture still belongs to the page's native scroll.
  canvas.addEventListener('touchmove', event => {
    if (!drag || event.touches.length !== 1 || !event.cancelable) return;
    const finger = event.touches[0];
    if (isTouchOrbit(finger.clientX, finger.clientY)) event.preventDefault();
  }, {passive: false});
  canvas.addEventListener('pointermove', event => {
    if (!drag || drag.id !== event.pointerId) return;
    const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
    drag.distance += Math.hypot(dx, dy);
    drag.x = event.clientX; drag.y = event.clientY;
    if (event.pointerType === 'touch' && !isTouchOrbit(event.clientX, event.clientY)) return;
    if (drag.distance > 4) rotate(dx * .009, dy * .006);
  });
  canvas.addEventListener('pointerup', event => {
    if (!drag || drag.id !== event.pointerId) return;
    if (drag.distance < 6) {
      const rect = canvas.getBoundingClientRect();
      const x = event.clientX - rect.left, y = event.clientY - rect.top;
      const hit = [...projected].reverse().find(p => Math.abs(x - p.x) <= p.w + 3 && Math.abs(y - p.y) <= p.h + 5);
      if (hit) inspect(hit.node.id, true);
    }
    drag = null;
  });
  canvas.addEventListener('lostpointercapture', () => { drag = null; });
  el('viewer').hidden = false;
  el('query-panel').hidden = false;
  const restore = () => inspect(new URLSearchParams(location.search).get('node'), false);
  window.addEventListener('popstate', restore);
  window.addEventListener('resize', render);
  restore();
})();
