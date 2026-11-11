/* Test geometric landing and durable request keys without a DOM or network. */
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { webcrypto } = require('node:crypto');
const vm = require('node:vm');

const window = { crypto: webcrypto };
vm.runInNewContext(readFileSync(join(__dirname, '../static/wheel.js'), 'utf8'), { window, TextEncoder, Uint8Array, Map, Set, Array });
const { landingRotation, validSpinResult, PendingRequests } = window.RakovarWheel;

function storage() {
  const data = new Map();
  return { data, getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value), removeItem: key => data.delete(key) };
}

async function test() {
  // After every supported layout and previous rotation, the confirmed sector's
  // world-space vector must point at the top pointer, never at a nearby sector.
  let landings = 0;
  for (let count = 1; count <= 32; count++) {
    for (let index = 0; index < count; index++) {
      for (const previous of [-90, 0, 390, 9999.25, 200000.25]) {
        const next = landingRotation(previous, count, index);
        const worldAngle = (-90 + index * 360 / count + next) * Math.PI / 180;
        assert.ok(Math.abs(Math.cos(worldAngle)) < 1e-8, `horizontal error: ${count}/${index}/${previous}`);
        assert.ok(Math.abs(Math.sin(worldAngle) + 1) < 1e-8, `pointer error: ${count}/${index}/${previous}`);
        assert.ok(next >= previous + 1800 - 1e-8, 'A normal spin must include five full turns.');
        landings++;
      }
    }
  }
  for (const args of [[0, 0, 0], [0, 8, -1], [0, 8, 8], [NaN, 8, 1], [0, 8, 1, -1]]) assert.throws(() => landingRotation(...args));

  const result = { spin_id: 7, sectors: [{ id: 'a', title: 'Соус' }, { id: 'b', title: 'Бонус' }], sector_index: 1, prize: { id: 'b', title: 'Бонус' }, tickets: 2 };
  assert.equal(validSpinResult(result), true);
  assert.equal(validSpinResult({ ...result, sector_index: 0 }), false, 'Prize mismatch must preserve pending request.');
  assert.equal(validSpinResult({ ...result, sectors: [result.sectors[1], result.sectors[1]] }), false);
  assert.equal(validSpinResult({ ...result, spin_id: undefined }), false);
  assert.equal(validSpinResult({ ...result, tickets: undefined }), false);

  const store = storage();
  const first = new PendingRequests(store);
  const payload = { guest_id: 'guest-abcdef123456', name: 'Synthetic contact', phone: '+79990000000', items: [{ id: 'a', quantity: 1 }] };
  const initial = await first.prepare('order:guest', payload);
  const samePageRetry = await first.prepare('order:guest', payload);
  const afterReload = await new PendingRequests(store).prepare('order:guest', payload);
  assert.equal(initial.key, samePageRetry.key);
  assert.equal(initial.key, afterReload.key, 'An ambiguous response must be retried with the original key.');
  assert.ok(initial.digest.length === 64);
  const storedText = [...store.data.values()].join();
  assert.ok(!storedText.includes(payload.name) && !storedText.includes(payload.phone) && !storedText.includes('items'));
  const changed = await first.prepare('order:guest', { ...payload, items: [{ id: 'a', quantity: 2 }] });
  assert.notEqual(initial.key, changed.key, 'A changed order is a different request.');
  first.clear('order:guest', initial.key);
  assert.equal(first.read('order:guest').key, changed.key, 'An earlier tab response cannot delete a newer pending key.');
  first.clear('order:guest', changed.key);
  assert.equal(first.read('order:guest'), null);

  const deniedWrites = { getItem: () => null, setItem: () => { throw new Error('quota'); }, removeItem: () => { throw new Error('denied'); } };
  const inMemory = new PendingRequests(deniedWrites);
  const fallback = await inMemory.prepare('spin:guest', { guest_id: 'guest-123456789012' });
  assert.equal((await inMemory.prepare('spin:guest', { guest_id: 'guest-123456789012' })).key, fallback.key);
  inMemory.clear('spin:guest', fallback.key);
  assert.equal(inMemory.read('spin:guest'), null);

  console.log(`PASS: ${landings} geometric landings, invalid server results, durable retry/privacy and storage fallback checks.`);
}

test().catch(error => { console.error(error); process.exitCode = 1; });
