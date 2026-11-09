/* Original SVG artwork and server-directed wheel. No prize is selected here. */
(() => {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const palette = ['#823e2d', '#263d38', '#b78048', '#394b3a', '#694238', '#2c4348', '#825b36', '#39413c'];
  const artNames = ['crayfish', 'shrimp', 'crab', 'mussel', 'langoustine', 'set', 'bonus', 'gift'];
  const artwork = {
    crayfish: '<g fill="#e88b62" stroke="#492c25" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M25 16 16 12 9 18 12 29 19 28 23 20M39 16 48 12 55 18 52 29 45 28 41 20"/><path d="m12 13-2-7 9 3-2 8m35-4 2-7-9 3 2 8"/><ellipse cx="32" cy="29" rx="10" ry="15"/><path d="m24 40 2 9 6 7 6-7 2-9M25 45h14m-11 5h8M22 26l-8 7m8 0-9 7m10 0-7 7m26-21 8 7m-8 0 9 7m-10 0 7 7M27 17 21 3m16 14 6-14" fill="none" stroke="#edb288"/><circle cx="28" cy="18" r="2" fill="#221c19" stroke="none"/><circle cx="36" cy="18" r="2" fill="#221c19" stroke="none"/></g>',
    shrimp: '<g stroke="#583126" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M40 13C22 4 9 15 10 31c1 17 17 25 30 17 10-6 13-19 6-26-6-6-16-2-16 5 0 6 7 8 11 4-2 10-17 10-19-1-2-9 8-15 18-11Z" fill="#eaa276"/><path d="m19 13 7 9m-15 1 11 4m-11 8 12-2m-7 12 10-9m2 15 3-12m10 10-4-12m9 6-8-9M41 13 51 4M43 17 60 10" fill="none"/><path d="m45 22 12-5 4 11-10 4" fill="#bd6c4c"/><circle cx="39" cy="15" r="2" fill="#261e1b"/></g>',
    crab: '<g fill="#d77b57" stroke="#4f2e28" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m19 28-9-8-4 5 6 10m33-7 9-8 4 5-6 10M10 20 4 12l4-7 3 8 6-6 3 9-6 7m40-3 6-8-4-7-3 8-6-6-3 9 6 7"/><path d="M18 33 7 36 3 44m16-3L8 47l-1 9m16-9-8 9m31-23 11 3 4 8M45 41l11 6 1 9m-16-9 8 9" fill="none" stroke="#efb18a"/><path d="M15 33q2-14 17-14t17 14q-1 17-17 17T15 33"/><path d="m25 21-2-7m16 7 2-7" fill="none"/><circle cx="23" cy="13" r="3" fill="#f3d4a6"/><circle cx="41" cy="13" r="3" fill="#f3d4a6"/><path d="M21 35q11 6 22 0" fill="none" stroke="#ebad83"/></g>',
    mussel: '<g stroke="#a5b4ae" stroke-width="1.8" stroke-linecap="round"><path d="M31 56C14 49 6 30 12 16S38 3 49 17c12 17 5 33-18 39Z" fill="#263d47"/><path d="M31 53 19 15m12 38-2-43m2 43 10-40m-10 40 18-31" fill="none" stroke="#697c81"/><path d="M31 56C21 42 18 28 26 18c11-6 24 9 21 20-2 9-8 15-16 18Z" fill="#d1a169" stroke="#e8c89b"/><path d="M31 49c-5-12-3-21 4-24" fill="none" stroke="#f0d0a1"/></g>',
    langoustine: '<g fill="#d89471" stroke="#55362e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="32" cy="30" rx="7" ry="15"/><path d="m25 41 2 9 5 9 5-9 2-9M25 44h14m-12 5h10M25 20 18 13 16 3l-5 3 1 15 12 8m15-9 7-7 2-10 5 3-1 15-12 8"/><path d="m24 26-10 6m10 1-10 6m11 1-8 6m22-20 10 6m-10 1 10 6m-11 1 8 6m-19-29-3-12m10 12 3-12" fill="none" stroke="#efbe98"/><path d="m27 54-6 7 11-3 11 3-6-7"/><circle cx="29" cy="17" r="1.8" fill="#261e1b"/><circle cx="35" cy="17" r="1.8" fill="#261e1b"/></g>',
    bonus: '<g stroke="#765331" stroke-width="2"><circle cx="32" cy="32" r="25" fill="#e0bb79"/><circle cx="32" cy="32" r="20" fill="none" stroke="#f6deb0"/><path d="m32 15 5 11 12 2-9 8 2 12-10-6-10 6 2-12-9-8 12-2Z" fill="#916143" stroke="none"/></g>',
    set: '<g stroke="#e4c99b" stroke-width="2" stroke-linecap="round"><ellipse cx="32" cy="38" rx="29" ry="18" fill="#31443c"/><ellipse cx="32" cy="36" rx="23" ry="12" fill="none"/><path d="M12 36c2-13 14-16 20-3m-14 6c7-7 15-4 15 3M34 34c5-17 18-13 17-4m-14 8c10-6 17 0 12 5" fill="none" stroke="#e4946a" stroke-width="5"/><path d="m29 26 3-12m8 11 7-11m-29 9-4-9" fill="none" stroke="#7f966e"/></g>',
    gift: '<g stroke="#765331" stroke-width="2.2" stroke-linejoin="round"><path d="M10 28h44v29H10Z" fill="#c77a53"/><path d="M7 21h50v10H7Z" fill="#e6bc7d"/><path d="M27 21h10v36H27Z" fill="#f0d4a1"/><path d="M32 21C8 22 16 0 26 9l6 12Zm0 0C56 22 48 0 38 9l-6 12Z" fill="#e0bc7b"/></g>'
  };

  function element(name, attrs = {}) {
    const node = document.createElementNS(NS, name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
    return node;
  }

  function landingRotation(current, count, index, turns = 5) {
    if (!Number.isInteger(count) || count < 1 || !Number.isInteger(index) || index < 0 || index >= count || !Number.isFinite(current) || !Number.isInteger(turns) || turns < 0) throw new Error('invalid_wheel_sector');
    const desired = ((360 - index * 360 / count) % 360 + 360) % 360;
    const normalized = ((current % 360) + 360) % 360;
    return current + Math.max(0, turns) * 360 + ((desired - normalized + 360) % 360);
  }

  function validSpinResult(result) {
    return Boolean(result && Number.isSafeInteger(result.spin_id) && result.spin_id > 0 &&
      Array.isArray(result.sectors) && result.sectors.length > 0 && result.sectors.length <= 32 &&
      result.sectors.every(sector => typeof sector?.id === 'string' && typeof sector.title === 'string') &&
      new Set(result.sectors.map(sector => sector.id)).size === result.sectors.length &&
      Number.isInteger(result.sector_index) && result.sector_index >= 0 &&
      result.sectors[result.sector_index]?.id === result.prize?.id &&
      typeof result.prize?.title === 'string' && Number.isFinite(result.tickets));
  }

  function secureKey() {
    if (window.crypto.randomUUID) return window.crypto.randomUUID();
    return Array.from(window.crypto.getRandomValues(new Uint8Array(24)), byte => byte.toString(16).padStart(2, '0')).join('');
  }

  class PendingRequests {
    constructor(storage, prefix = 'rakovar_pending_v1:') {
      this.storage = storage;
      this.prefix = prefix;
      this.memory = new Map();
    }

    read(scope) {
      try { return JSON.parse(this.storage.getItem(this.prefix + scope) || 'null') || this.memory.get(scope) || null; }
      catch { return this.memory.get(scope) || null; }
    }

    async prepare(scope, payload) {
      const bytes = new TextEncoder().encode(JSON.stringify(payload));
      const digest = Array.from(new Uint8Array(await window.crypto.subtle.digest('SHA-256', bytes)), byte => byte.toString(16).padStart(2, '0')).join('');
      const pending = this.read(scope);
      if (pending && pending.digest === digest && typeof pending.key === 'string' && /^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$/.test(pending.key)) return pending;
      const next = { key: secureKey(), digest };
      this.memory.set(scope, next);
      try { this.storage.setItem(this.prefix + scope, JSON.stringify(next)); } catch { /* Current-page retry remains available. */ }
      return next;
    }

    clear(scope, key) {
      // A response from an earlier tab must not clear a newer request.
      const pending = this.read(scope);
      if (pending?.key !== key) return;
      this.memory.delete(scope);
      try { this.storage.removeItem(this.prefix + scope); } catch { /* Memory entry has already been removed. */ }
    }
  }

  class Wheel {
    constructor(rotor, status, legend) {
      this.rotor = rotor;
      this.status = status;
      this.legend = legend;
      this.rotation = 0;
      this.sectors = [];
      this.audio = null;
      this.sound = false;
      this.light = false;
      this.reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
      this.busy = false;
    }

    render(sectors) {
      if (!Array.isArray(sectors) || !sectors.length || sectors.length > 32 || sectors.some(s => typeof s.id !== 'string' || typeof s.title !== 'string') || new Set(sectors.map(s => s.id)).size !== sectors.length) {
        this.sectors = [];
        this.status.textContent = 'Призовой фонд пока недоступен.';
        return false;
      }
      const ids = sectors.map(s => `${s.id}:${s.title}:${s.artwork || ''}`).join('|');
      if (this.layout === ids) return true;
      this.layout = ids;
      this.sectors = sectors;
      const svg = element('svg', { viewBox: '0 0 400 400', 'aria-hidden': 'true', focusable: 'false' });
      const defs = element('defs');
      Object.entries(artwork).forEach(([name, content]) => {
        const symbol = element('symbol', { id: `rk-art-${name}`, viewBox: '0 0 64 64' });
        // Trusted, original artwork above; no server strings are inserted as markup.
        symbol.innerHTML = content;
        defs.append(symbol);
      });
      svg.append(defs);
      const step = 360 / sectors.length;
      const polar = (r, deg) => [200 + r * Math.cos(deg * Math.PI / 180), 200 + r * Math.sin(deg * Math.PI / 180)];
      sectors.forEach((sector, index) => {
        const angle = -90 + step * index;
        const [x1, y1] = polar(185, angle - step / 2);
        const [x2, y2] = polar(185, angle + step / 2);
        const group = element('g', { 'data-sector-id': sector.id, 'data-sector-index': index });
        const title = element('title'); title.textContent = sector.title; group.append(title);
        if (sectors.length === 1) group.append(element('circle', { cx: 200, cy: 200, r: 185, fill: palette[0] }));
        else group.append(element('path', { d: `M200 200 L${x1} ${y1} A185 185 0 ${step > 180 ? 1 : 0} 1 ${x2} ${y2} Z`, fill: palette[index % palette.length], stroke: '#e8c58a', 'stroke-opacity': '.45', 'stroke-width': 1 }));
        const [x, y] = polar(112, angle);
        const art = element('g', { transform: `translate(${x} ${y}) rotate(${index * step}) translate(-31 -31)` });
        const name = artNames.includes(sector.artwork) ? sector.artwork : artNames[index % artNames.length];
        art.append(element('use', { href: `#rk-art-${name}`, width: 62, height: 62 }));
        group.append(art);
        const [tx, ty] = polar(158, angle);
        const label = element('text', { x: tx, y: ty, transform: `rotate(${index * step} ${tx} ${ty})`, 'text-anchor': 'middle', 'dominant-baseline': 'central', fill: '#fff0d5', 'font-size': sectors.length > 8 ? 10 : 12, 'font-family': 'Arial,sans-serif', 'font-weight': 700 });
        const short = sector.title.replace(' на заказ', '').replace('Бесплатная доставка', 'Доставка').replace('Фирменный соус', 'Соус');
        label.textContent = short.length > 19 ? short.slice(0, 17) + '…' : short;
        group.append(label); svg.append(group);
      });
      svg.append(element('circle', { cx: 200, cy: 200, r: 188, fill: 'none', stroke: '#f0ce94', 'stroke-width': 6 }));
      svg.append(element('circle', { cx: 200, cy: 200, r: 193, fill: 'none', stroke: '#8a623c', 'stroke-width': 3 }));
      this.rotor.replaceChildren(svg);
      this.rotor.style.transform = `rotate(${this.rotation}deg)`;
      this.legend.replaceChildren();
      sectors.forEach((sector, index) => {
        const item = document.createElement('li');
        const dot = document.createElement('span'); dot.style.backgroundColor = palette[index % palette.length]; dot.setAttribute('aria-hidden', 'true');
        item.append(dot, document.createTextNode(sector.title));
        item.dataset.sectorIndex = String(index); this.legend.append(item);
      });
      this.status.textContent = 'Колесо готово. Все результаты в истории сохраняет сервер.';
      return true;
    }

    setSound(enabled) {
      this.sound = Boolean(enabled);
      if (this.sound) {
        const Context = window.AudioContext || window.webkitAudioContext;
        if (!Context) { this.sound = false; return false; }
        this.audio ||= new Context();
        this.audio.resume().catch(() => {});
      }
      return this.sound;
    }

    tone(frequency = 700, duration = .035) {
      if (!this.sound || !this.audio || this.audio.state !== 'running') return;
      const oscillator = this.audio.createOscillator();
      const gain = this.audio.createGain();
      oscillator.frequency.value = frequency;
      gain.gain.setValueAtTime(.025, this.audio.currentTime);
      gain.gain.exponentialRampToValueAtTime(.0001, this.audio.currentTime + duration);
      oscillator.connect(gain); gain.connect(this.audio.destination);
      oscillator.start(); oscillator.stop(this.audio.currentTime + duration);
    }

    async reveal(result) {
      if (!validSpinResult(result) || !this.render(result.sectors)) throw new Error('Ответ сервера не соответствует сектору. Откройте историю результатов.');
      this.legend.querySelectorAll('.is-winner').forEach(item => item.classList.remove('is-winner'));
      const duration = this.reduced.matches ? 0 : this.light ? 900 : 4800;
      const end = landingRotation(this.rotation, this.sectors.length, result.sector_index, duration > 1000 ? 5 : duration ? 1 : 0);
      const before = this.rotation;
      this.rotation = end;
      this.status.textContent = duration ? 'Сервер сохранил результат. Колесо останавливается…' : 'Результат сохранён.';
      this.rotor.closest('.wheel-stage')?.setAttribute('data-spinning', 'true');
      if (duration) {
        // One progress value drives both the dial and the sector click sound.
        // The quintic curve has zero speed at both ends: smooth acceleration,
        // several turns and controlled deceleration without a fabricated result.
        await new Promise(resolve => {
          let start;
          let lastTick = -1;
          const tick = now => {
            start ??= now;
            const t = Math.min(1, (now - start) / duration);
            const progress = t * t * t * (t * (t * 6 - 15) + 10);
            const rotation = before + (end - before) * progress;
            this.rotor.style.transform = `rotate(${rotation}deg)`;
            const segment = Math.floor((rotation * this.sectors.length) / 360);
            if (!this.light && segment !== lastTick) { this.tone(); lastTick = segment; }
            if (t < 1) requestAnimationFrame(tick);
            else resolve();
          };
          requestAnimationFrame(tick);
        });
      } else this.rotor.style.transform = `rotate(${end}deg)`;
      this.rotor.closest('.wheel-stage')?.removeAttribute('data-spinning');
      this.rotor.closest('.wheel-stage')?.setAttribute('data-result-sector', String(result.sector_index));
      this.legend.children[result.sector_index]?.classList.add('is-winner');
      this.status.textContent = `Ваш результат: ${result.prize.title}.`;
      this.tone(1000, .18);
    }
  }
  window.RakovarWheel = { Wheel, PendingRequests, landingRotation, validSpinResult, secureKey };
})();
