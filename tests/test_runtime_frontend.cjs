const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');

(async () => {
  const watchdog = setTimeout(() => { throw new Error('Test JS resté en attente'); }, 3000);
  let deadline;
  const ctx = {document: {querySelector: () => ({})}, console, window: {addEventListener() {}},
    FormData, AbortController, TypeError, setTimeout: (fn, ms) => { deadline = {fn, ms}; return 1; }, clearTimeout: () => {},
    fetch: (_path, options) => new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))))};
  vm.createContext(ctx);
  const source = fs.readFileSync('static/app.js', 'utf8');
  vm.runInContext(source.substring(0, source.lastIndexOf('(async function init(){')), ctx);
  const hung = vm.runInContext("api('/api/auth/me')", ctx);
  assert.equal(deadline.ms, 8000);
  deadline.fn();
  await assert.rejects(hung, error => error.unavailable && error.message.includes('Impossible de joindre'));
  ctx.fetch = async (_path, options) => ({ok: true, headers: {get: () => 'application/json'},
    json: () => new Promise((_resolve, reject) => {
      if (options.signal.aborted) reject(new DOMException('aborted', 'AbortError'));
      else options.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
    })});
  const body = vm.runInContext("api('/api/auth/me')", ctx);
  await Promise.resolve();
  deadline.fn();
  await assert.rejects(body, error => error.unavailable); // headers arrived, body stalled
  assert(source.includes("window.addEventListener('DOMContentLoaded'"));
  let releaseNavigation;
  const rendered = [];
  const navigation = {
    navigate: async view => { if (view === 'slow') await new Promise(resolve => { releaseNavigation = resolve; }); rendered.push(view); },
    openLaunch: async id => { if (id === 'failure') throw new Error('test'); rendered.push(id); },
  };
  vm.createContext(navigation);
  vm.runInContext(fs.readFileSync('static/runtime-navigation.js', 'utf8'), navigation);
  const slow = navigation.navigate('slow');
  const latest = navigation.openLaunch('latest-dossier');
  await Promise.resolve();
  assert.deepEqual(rendered, []);
  releaseNavigation();
  await Promise.all([slow, latest]);
  assert.deepEqual(rendered, ['slow', 'latest-dossier']);
  await assert.rejects(navigation.openLaunch('failure'));
  await navigation.navigate('recovered');
  assert.equal(rendered.at(-1), 'recovered');

  let html = '', retry, timer, observerDisconnected = false, reloaded = false;
  const node = {querySelector: selector => selector === '.boot, .loading-page' ? {} : {addEventListener: (_event, fn) => { retry = fn; }},
    set innerHTML(value) { html = value; }};
  const guard = {document: {getElementById: () => node},
    window: {addEventListener: () => {}, location: {reload: () => { reloaded = true; }}},
    setTimeout: (fn, ms) => { timer = fn; assert.equal(ms, 10000); return 1; }, clearTimeout: () => {},
    MutationObserver: class {observe() {} disconnect() {observerDisconnected = true;}}};
  vm.runInNewContext(fs.readFileSync('static/boot-guard.js', 'utf8'), guard);
  timer(); // app.js absent, refused MIME/CSP or syntax error: still exits loading
  assert(html.includes('Impossible de joindre le serveur FRAMATEX.'));
  assert(html.includes('Réessayer'));
  retry(); assert(reloaded);

  const {pathToFileURL} = require('url');
  const client = await import(pathToFileURL(process.cwd() + '/static/client/api.js'));
  const oldFetch = global.fetch, oldSet = global.setTimeout, oldClear = global.clearTimeout;
  try {
    global.setTimeout = (fn, ms) => { deadline = {fn, ms}; return 1; };
    global.clearTimeout = () => {};
    global.fetch = (_url, opts) => new Promise((_resolve, reject) => opts.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))));
    const request = client.getCurrentClient();
    assert.equal(deadline.ms, 8000); deadline.fn();
    await assert.rejects(request, error => error.code === 'network');
  } finally { global.fetch = oldFetch; global.setTimeout = oldSet; global.clearTimeout = oldClear; }
  console.log('Runtime frontend : fetch et corps bloqués bornés, garde autonome, Réessayer, Client timeout OK');
  clearTimeout(watchdog);
})().catch(error => { console.error(error); process.exitCode = 1; });
