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

  function render() {
    const width = canvas.clientWidth, height = canvas.clientHeight;
    if (!width || !height) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 3);
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    const size = Math.min(width / 485, height / 290);
    function project([x, y, z]) {
      const X = x * Math.cos(yaw) + z * Math.sin(yaw);
      const depth = z * Math.cos(yaw) - x * Math.sin(yaw);
      const Y = y * Math.cos(pitch) - depth * Math.sin(pitch);
      const Z = y * Math.sin(pitch) + depth * Math.cos(pitch);
      const perspective = 540 / (540 - Z);
      return {x: width / 2 + X * size * perspective,
              y: height / 2 + Y * size * perspective, depth: Z, scale: perspective};
    }
    function line(a, b, color, weight) {
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
      ctx.strokeStyle = color; ctx.lineWidth = weight; ctx.stroke();
    }
    for (let i = -180; i <= 180; i += 36) {
      line(project([i, 108, -170]), project([i, 108, 150]), '#375143', .6);
      line(project([-180, 108, i]), project([180, 108, i]), '#375143', .6);
    }
    projected = components.map(node => ({...project(node.position), node})).sort((a,b) => a.depth - b.depth);
    for (const end of projected) {
      for (const input of end.node.inputs) {
        const start = projected.find(point => point.node.id === input);
        const highlighted = end.node === active || start.node === active;
        const color = highlighted ? '#d6f59d' : '#85a18e';
        line(start, end, color, highlighted ? 1.9 : 1);
        const dx = end.x - start.x, dy = end.y - start.y;
        const angle = Math.atan2(dy, dx), ax = start.x + dx * .58, ay = start.y + dy * .58;
        ctx.beginPath(); ctx.moveTo(ax, ay);
        for (const turn of [-.48, .48]) ctx.lineTo(ax - 7 * Math.cos(angle + turn), ay - 7 * Math.sin(angle + turn));
        ctx.fillStyle = color; ctx.closePath(); ctx.fill();
      }
    }
    for (const point of projected) {
      const selected = point.node === active;
      const r = (selected ? 10 : 6) * point.scale;
      const glow = ctx.createRadialGradient(point.x, point.y, 0, point.x, point.y, r * 3);
      glow.addColorStop(0, selected ? '#dbff9088' : '#76b39266'); glow.addColorStop(1, '#83a78b00');
      ctx.fillStyle = glow; ctx.fillRect(point.x-r*3, point.y-r*3, r*6, r*6);
      ctx.beginPath(); ctx.arc(point.x, point.y, r, 0, Math.PI * 2);
      ctx.fillStyle = selected ? '#e0f8ab' : '#79a48a'; ctx.fill();
      ctx.strokeStyle = '#e7f8cc'; ctx.lineWidth = 1.3; ctx.stroke();
      ctx.textAlign = 'center';
      ctx.font = (selected ? 'bold ' : '') + (width < 420 ? '11' : '13') + 'px Arial';
      ctx.lineWidth = 3.5; ctx.strokeStyle = '#142d22';
      ctx.strokeText(point.node.label, point.x, point.y + r + 14);
      ctx.fillStyle = '#f3f6e8'; ctx.fillText(point.node.label, point.x, point.y + r + 14);
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
    drag = {id: event.pointerId, x: event.clientX, y: event.clientY, distance: 0};
    canvas.setPointerCapture(drag.id);
  });
  canvas.addEventListener('pointermove', event => {
    if (!drag || drag.id !== event.pointerId) return;
    const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
    drag.distance += Math.hypot(dx, dy);
    drag.x = event.clientX; drag.y = event.clientY;
    if (drag.distance > 4) rotate(dx * .009, dy * .006);
  });
  canvas.addEventListener('pointerup', event => {
    if (!drag || drag.id !== event.pointerId) return;
    if (drag.distance < 6) {
      const rect = canvas.getBoundingClientRect();
      const hits = projected.map(p => ({p, d: Math.hypot(p.x - event.clientX + rect.left, p.y - event.clientY + rect.top)}));
      const nearest = hits.sort((a, b) => a.d - b.d)[0];
      if (nearest.d <= 22) inspect(nearest.p.node.id, true);
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
