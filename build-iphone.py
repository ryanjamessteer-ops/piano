#!/usr/bin/env python3
"""Build the iPhone test version of Piano Instant from the main prototype.

    python3 build-iphone.py [../piano-instant.html] [piano-instant-iphone.html]

The main file stays the source of truth; this applies a small set of iPhone / Claude-artifact patches
on top so a newer prototype can be re-ported by running it again. Every patch must match exactly once,
otherwise the build stops and says which one drifted.
"""
import pathlib, sys

here = pathlib.Path(__file__).resolve().parent
src = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else here.parent / 'piano-instant.html'
dst = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else here / 'piano-instant-iphone.html'
html = src.read_text(encoding='utf-8')

def patch(name, old, new, count=1):
    global html
    n = html.count(old)
    if n != count:
        sys.exit(f'patch "{name}": expected {count} match(es), found {n}')
    html = html.replace(old, new)

# 1. Build label, so recordings say which build made them.
patch('version', "const VERSION = 'v16';", "const VERSION = 'v16-iphone';")

# 2. Audio start. iOS only unlocks audio inside the tap, so resume() is called before anything is awaited
#    and again once the mic is open (opening the mic can suspend a context made before it). Safari only
#    runs analysers that lead to the speakers, so both feed a silent gain into the destination.
patch('audio-start',
"""    this.ctx = new AC({ latencyHint: 'interactive' });
    await this.ctx.resume();
    const an = this.analyser = this.ctx.createAnalyser();""",
"""    this.ctx = new AC({ latencyHint: 'interactive' });
    const unlocked = this.ctx.resume().catch(() => {});   // inside the tap: the only moment iOS allows it
    const an = this.analyser = this.ctx.createAnalyser();""")
patch('audio-sink',
"""    this.mag2 = new Float32Array(this.nBins2);
    this.clean2 = new Float32Array(this.nBins2);
    this.mode = mode;""",
"""    this.mag2 = new Float32Array(this.nBins2);
    this.clean2 = new Float32Array(this.nBins2);
    // Safari only processes nodes that lead to the destination: give the analysers a silent path there.
    const sink = this.ctx.createGain(); sink.gain.value = 0;
    an.connect(sink); an2.connect(sink); sink.connect(this.ctx.destination);
    this.mode = mode;""")
patch('audio-ready',
"""      this.piano = new VirtualPiano(this.ctx, an, an2);
    }
    this.ready = true;""",
"""      this.piano = new VirtualPiano(this.ctx, an, an2);
    }
    await unlocked;
    if (this.ctx.state !== 'running') await this.ctx.resume().catch(() => {});
    this.ready = true;""")

# 3. Mic error: inside the Claude app or a claude.ai frame the mic may be blocked; say what to do on a phone.
patch('mic-error',
"""      ? "The microphone isn't available here. Download the HTML file and open it in Chrome or Safari, then allow the microphone. The virtual piano works right now."
      : `The microphone couldn't start (${err.name || err.message}). Check that no other app is using it, or try the virtual piano.`;
    ui.introErr.hidden = false;""",
"""      ? (window.self !== window.top
        ? "The microphone is blocked inside this frame. Tap \\"Open on its own page\\" below, then allow the microphone. The virtual piano works right now."
        : "The microphone isn't allowed. On iPhone: Settings › Apps › Safari › Microphone › Allow (or tap aA in the address bar › Website Settings), then reload. The virtual piano works right now.")
      : `The microphone couldn't start (${err.name || err.message}). Check that no other app is using it, or try the virtual piano.`;
    ui.introErr.hidden = false;
    if (window.self !== window.top) $('#ownPage').hidden = false;""")
patch('own-page-link',
"""    <p id="introErr" class="err" hidden></p>""",
"""    <p id="introErr" class="err" hidden></p>
    <p id="ownPage" class="note" hidden>Microphone not starting here? <a id="ownPageLink" href="#" target="_blank" rel="noopener">Open on its own page</a> to run the game by itself in Safari, where it can ask for the microphone.</p>""")

# 4. "Missed one" button: the touch version of pressing M during a song.
patch('end-send',
"""      <button id="btnEndRecal" class="ghost" type="button">Lessons</button>""",
"""      <button id="btnEndRecal" class="ghost" type="button">Lessons</button>
      <button id="btnEndSend" class="ghost" type="button" hidden>Send recordings</button>""")
patch('build-stamp',
"""    <p id="introErr" class="err" hidden></p>""",
"""    <p id="introErr" class="err" hidden></p>
    <p id="buildStamp" class="note">iPhone build 6 · recordings save on this phone</p>""")
# 4b. Phone mics hear a note's fundamental weakly, so its octave overtone can win (Ryan's first phone
#     game: C4 heard as C5 twice, with an "OCTAVE" penalty). With OCTAVE_ANY an octave of the due key
#     counts as the due key for single notes too, not only for chords and low bass.
patch('octave-any',
"""&& (nx.lanes.length > 1 || LANES[l].midi < 48)) : undefined;""",
"""&& (nx.lanes.length > 1 || LANES[l].midi < 48 || CFG.OCTAVE_ANY)) : undefined;""")
patch('mark-button',
"""    <button id="quit" class="ghost" type="button">Menu</button>""",
"""    <button id="markBtn" class="ghost" type="button" title="Tap the moment the game misses a note you played">Missed one</button>
    <button id="quit" class="ghost" type="button">Menu</button>""")

# 5. Recorder: read the game's globals through closures instead of eval (a claude.ai page may forbid eval).
patch('recorder-globals',
"""(() => {
  if (window.PIRec) return;""",
"""const __piGlobals = { CFG: () => CFG, LANES: () => LANES, Matcher: () => Matcher, VERSION: () => VERSION, audio: () => audio, game: () => game,
  kbRange: () => kbRange, noise: () => noise, phase: () => phase, practice: () => practice, profiles: () => profiles, sig: () => sig, song: () => song };
(() => {
  if (window.PIRec) return;""")
patch('recorder-g',
"""  const g = name => { try { return (0, eval)(name); } catch (e) { return undefined; } };   // the game's top-level let/const/class""",
"""  const g = name => { try { return __piGlobals[name]?.(); } catch (e) { return undefined; } };   // the game's top-level let/const/class""")

# 6. Saving: claude.ai storage first (Claude can fetch it from there), then the iPhone share sheet, then downloads.
patch('recorder-save',
"""    for (const [name, data] of [[base + '.wav', blob], [base + '.json', new Blob([text], { type: 'application/json' })]]) {
      const a = document.createElement('a');""",
"""    try {
      if (await R.cloudSave?.(base, blob, text, rec)) { R.onSaved?.(base, 'cloud', chunks.length > 0); return; }
    } catch (e) { console.warn('PIRec cloud save failed', e); R.cloudErr = e?.code || e?.message || String(e); }
    const files = [new File([blob], base + '.wav', { type: 'audio/wav' }), new File([text], base + '.json', { type: 'application/json' })];
    if (R.localSave) {
      try { await R.localSave(base, blob, text); R.onSaved?.(base, 'local', chunks.length > 0); return; } catch (e) { console.warn('PIRec local save failed', e); }
    }
    if (navigator.canShare?.({ files })) { R.pending = { base, files }; R.onSaved?.(base, 'share', chunks.length > 0); return; }
    for (const [name, data] of [[base + '.wav', blob], [base + '.json', new Blob([text], { type: 'application/json' })]]) {
      const a = document.createElement('a');""")

# 7. Recording controls text.
patch('rec-msg',
"""<p id="recMsg" class="note">Every game is saved by itself as a sound file plus a log of what the game heard and decided, so a missed note can be found and fixed. Pick a folder once (for example Desktop\\Piano Instant\\recordings); without one, each recording downloads. Press <kbd>M</kbd> during a song the moment it misses a note you played. Nothing leaves this computer.</p>""",
"""<p id="recMsg" class="note">Every game is saved as a sound file plus a log of what the game heard and decided, so a missed note can be found and fixed. On this page they're stored with the page itself, where Claude can fetch and check them. Tap <b>Missed one</b> during a song the moment it misses a note you played.</p>
      <p id="recCount" class="note" hidden></p>
      <button id="btnRecShare" class="ghost" type="button" hidden>Save last recording</button>
      <button id="btnRecSend" class="ghost" type="button" hidden>Send recordings</button>""")

# 8. CSS: notch / home-bar safe areas, no double-tap zoom, compact HUD on a phone.
patch('css',
"""@media (prefers-reduced-motion: reduce) {
  #mult.bump { animation: none; }
}""",
"""@media (prefers-reduced-motion: reduce) {
  #mult.bump { animation: none; }
}
/* iPhone */
html, body { touch-action: manipulation; -webkit-tap-highlight-color: transparent; -webkit-text-size-adjust: 100%; }
#stage { -webkit-user-select: none; user-select: none; -webkit-touch-callout: none; }
#hud { padding-top: max(12px, env(safe-area-inset-top)); padding-left: max(16px, env(safe-area-inset-left)); padding-right: max(16px, env(safe-area-inset-right)); }
#calbar { top: calc(16px + env(safe-area-inset-top, 0px)); }
.panel { max-height: calc(100% - 32px - env(safe-area-inset-top, 0px) - env(safe-area-inset-bottom, 0px)); }
#markBtn { padding: 10px 12px; }
#markBtn.flash { border-color: var(--gold); color: var(--gold); }
#wakeNote { position: fixed; left: 50%; top: calc(50% - 30px); transform: translateX(-50%); z-index: 5; padding: 14px 18px; border-radius: 12px; background: #1b1733; border: 1px solid var(--gold); color: var(--fg); font: 600 15px/1.3 var(--font-body); text-align: center; max-width: calc(100vw - 48px); }
@media (max-width: 560px), (max-height: 480px) {
  #hud { gap: 6px 14px; padding-bottom: 6px; }
  #hud > .hb:nth-child(3), #hud > .hb:nth-child(6) { display: none; }   /* streak and mic level: the score and "hearing" matter most */
  #hud button { padding: 9px 11px; font-size: 13px; }
  .num { font-size: 18px; } #mult { font-size: 20px; }
}
@media (max-height: 480px) {
  #calbar { gap: 4px; top: calc(6px + env(safe-area-inset-top, 0px)); }
  #calbar .steps { display: none; }
  #calText { min-height: 0; }
}""")

# 8b. The "every C" step had no way past a C the mic can't hear (phone mics barely pick up the lowest
#     notes). After SKIP_AFTER seconds on one C, offer "Skip this C": the run moves to the next C and the
#     skipped one is estimated from its neighbours like any key the run missed.
patch('c-skip-visible',
"""  ui.walkSkip.hidden = !(cal.mode !== 'run' && walkTarget() !== undefined && t - cal.keyT0 > CFG.SKIP_AFTER && cal.sub === 'listen');
  ui.walkSkip.textContent = cal.mode === 'check' ? 'Skip the check' : 'Skip this key';""",
"""  if (cal.mode === 'run' && cal.run === 'c') {
    if (cal.cSkipPrev !== cal.runPrev) { cal.cSkipPrev = cal.runPrev; cal.cSkipT0 = t; }
    const exp = runExpect();
    ui.walkSkip.hidden = !(t - Math.max(cal.cSkipT0, cal.keyT0) > CFG.SKIP_AFTER && !cal.runProf[exp] && exp !== cal.runKeys.at(-1));
    ui.walkSkip.textContent = `Skip ${noteName(exp)}`;
  } else {
  ui.walkSkip.hidden = !(cal.mode !== 'run' && walkTarget() !== undefined && t - cal.keyT0 > CFG.SKIP_AFTER && cal.sub === 'listen');
  ui.walkSkip.textContent = cal.mode === 'check' ? 'Skip the check' : 'Skip this key';
  }""")
patch('c-skip-click',
"""function skipKey() {
  const m = walkTarget(); if (m === undefined) return;""",
"""function skipKey() {
  if (cal.mode === 'run' && cal.run === 'c') {
    const exp = runExpect(); cal.runPrev = exp; dlog('run-skip', { key: noteName(exp) });
    return runText(`Skipped ${noteName(exp)}: it will be estimated from the keys around it. Now play ${noteName(runExpect())}.`);
  }
  const m = walkTarget(); if (m === undefined) return;""")

# 9. iPhone runtime glue + claude.ai storage, appended before </script>.
GLUE = r"""
/* =====================================================================================
   iPHONE / CLAUDE.AI GLUE (build-iphone.py)
   - wakes audio on any touch (iOS suspends it after calls, Siri, or leaving the app)
   - reopens the mic when iOS ended it while the app was in the background
   - keeps the screen on while playing
   - stores recordings with the page (claude.ai artifact storage) so Claude can fetch and analyse them
   ===================================================================================== */
(() => {
  const wakeNote = document.createElement('div');
  wakeNote.id = 'wakeNote'; wakeNote.hidden = true; wakeNote.setAttribute('role', 'status');
  wakeNote.textContent = 'Tap anywhere to wake the microphone';
  document.body.appendChild(wakeNote);
  const ownLink = $('#ownPageLink'); if (ownLink) ownLink.href = location.href;
  if (window.self !== window.top) $('#ownPage').hidden = false;   // claude.ai frames may refuse the mic: offer the way out up front

  const wake = () => {
    const c = audio.ctx;
    if (c && c.state !== 'running' && c.state !== 'closed') c.resume().then(() => { wakeNote.hidden = true; }).catch(() => {});
    lockScreen();
  };
  addEventListener('pointerdown', wake, true);
  addEventListener('touchend', wake, true);
  setInterval(() => {   // show the hint only while audio is stuck and the app is in use
    const c = audio.ctx;
    wakeNote.hidden = !(audio.ready && c && c.state !== 'running' && c.state !== 'closed' && !document.hidden);
  }, 500);

  let lock = null;
  async function lockScreen() {
    if (lock || !navigator.wakeLock || !audio.ready || document.hidden) return;
    try { lock = await navigator.wakeLock.request('screen'); lock.addEventListener('release', () => { lock = null; }); } catch (e) { /* not allowed here: the phone may dim */ }
  }
  document.addEventListener('visibilitychange', async () => {
    if (document.hidden) return;
    wake();
    const tr = audio.stream?.getAudioTracks()[0];
    if (audio.mode === 'mic' && audio.ready && tr && tr.readyState === 'ended') {
      try { await audio.useMic(audio.deviceId || null); } catch (e) { try { await audio.useMic(null); } catch (e2) { /* the tap hint stays up */ } }
    }
  });

  // Repeated tries count (Ryan's idea, for mics that hear the piano faintly).
  // Setup, every-C step: three strikes on the C that's due without a usable pitch skip it; it is
  // estimated from its neighbours like any key the run missed.
  setInterval(() => {
    if (phase !== 'walk' || cal.mode !== 'run' || cal.run !== 'c') return;
    const exp = runExpect(), auto = cal.autoSkipped || (cal.autoSkipped = {});
    if ((cal.fails?.[exp] || 0) >= 3 && !cal.runProf[exp] && !auto[exp] && exp !== cal.runKeys.at(-1)) {
      auto[exp] = true; cal.runPrev = exp; dlog('run-autoskip', { key: noteName(exp), tries: cal.fails[exp] });
      runText(`Heard you try ${noteName(exp)} ${cal.fails[exp]} times without a clear note, so it's taken as played and estimated from the keys around it. Now play ${noteName(runExpect())}.`);
    }
  }, 200);
  // Songs: while the game waits on a note, three strikes within 6 s whose closest key is that note
  // (even below the normal match) count as playing it. Off with CFG.REPEAT_CREDIT = 0.
  CFG.OCTAVE_ANY = true;
  CFG.REPEAT_CREDIT = 3; CFG.REPEAT_MIN = 0.4; CFG.REPEAT_WIN = 6;
  let rep = null;
  const upd = Matcher.prototype.update;
  Matcher.prototype.update = function () {
    const r = upd.apply(this, arguments);
    try {
      const ms = r?.missed;
      if (CFG.REPEAT_CREDIT && ms && phase === 'game' && game.frozen && game.notes) {
        const n = game.notes.find(x => x.state === 'pending');
        if (n && n.lanes.includes(ms.i) && !(n.got && ms.i in n.got) && ms.best >= CFG.REPEAT_MIN) {
          rep = rep && rep.n === n && rep.lane === ms.i && ms.t - rep.t0 < CFG.REPEAT_WIN ? { ...rep, k: rep.k + 1 } : { n, lane: ms.i, k: 1, t0: ms.t };
          dlog('repeat-try', { key: LANES[ms.i]?.name, tries: rep.k, best: +ms.best.toFixed(2) });
          if (rep.k >= CFG.REPEAT_CREDIT) {
            dlog('repeat-credit', { key: LANES[ms.i]?.name }); window.PIRec?.ev?.('repeat-credit', { lane: ms.i, tries: rep.k, best: +ms.best.toFixed(3) });
            rep = null; window.gameHit(ms.i, ms.t, ms.best);
          }
        }
      }
    } catch (e) { console.warn('repeat credit', e); }
    return r;
  };

  // "Missed one": same mark as pressing M on a computer.
  const mark = $('#markBtn'), R = window.PIRec;
  mark.onclick = () => {
    if (R?.rec && phase === 'game') { const n = game.notes?.find(x => x.state === 'pending'); R.ev('mark', { g: R.gameId(), note: n ? game.notes.indexOf(n) : -1 }); }
    mark.classList.add('flash'); setTimeout(() => mark.classList.remove('flash'), 400);
  };
  if (!R) { mark.hidden = true; return; }
  const syncMark = () => { mark.hidden = R.enabled === false; };
  syncMark(); $('#recOn').addEventListener('change', syncMark);

  /* ---------- recordings → claude.ai storage ---------- */
  // Asset storage takes text, JSON, images and video but not WAV, and caps a file at 20 MiB, so the WAV is
  // stored as base64 text in parts of 12 MiB of audio (~16 MiB of text). The 'recordings' table indexes them.
  const cloud = (async () => {
    if (!window.claude?.use) return null;
    try {
      const [assets, db] = await Promise.all([claude.use('assets'), claude.use('db')]);
      return assets && db ? { assets, db } : null;
    } catch (e) { return null; }
  })();
  const b64 = blob => new Promise((res, rej) => { const fr = new FileReader(); fr.onload = () => res(String(fr.result).split(',')[1] || ''); fr.onerror = () => rej(fr.error); fr.readAsDataURL(blob); });
  const MiB = 1024 * 1024, WAV_PART = 12 * MiB, TEXT_PART = 18 * MiB;
  const count = $('#recCount');
  async function showCount() {
    const c = await cloud; if (!c) return;
    try {
      const snap = await c.db.collection('recordings').get();
      count.textContent = snap.size ? `${snap.size} recording${snap.size === 1 ? '' : 's'} stored on this page for Claude to check.` : 'No recordings stored yet.';
      count.hidden = false;
    } catch (e) { /* not signed in: stays hidden */ }
  }
  showCount();
  cloud.then(c => { if (!c) $('#recMsg').innerHTML = 'Every game is saved as a sound file plus a log of what the game heard and decided, so a missed note can be found and fixed. Each one is kept on this phone automatically. Tap <b>Send recordings</b> to send all new ones at once, as one .zip, to Files, AirDrop or a chat with Claude. Tap <b>Missed one</b> during a song the moment it misses a note you played.'; });
  R.cloudSave = async (base, wavBlob, text, rec) => {
    const c = await cloud; if (!c) return false;
    toast(`Uploading recording ${base}…`, 0);
    const wavParts = [];
    for (let o = 0; o < wavBlob.size; o += WAV_PART) {
      const t = await b64(wavBlob.slice(o, o + WAV_PART));
      wavParts.push((await c.assets.upload(new Blob([t], { type: 'text/plain' }), { type: 'text/plain' })).id);
    }
    const jsonParts = [];
    if (text.length <= TEXT_PART) jsonParts.push((await c.assets.upload(new Blob([text], { type: 'application/json' }), { type: 'application/json' })).id);
    else for (let o = 0; o < text.length; o += TEXT_PART) jsonParts.push((await c.assets.upload(new Blob([text.slice(o, o + TEXT_PART)], { type: 'text/plain' }), { type: 'text/plain' })).id);
    const songs = rec.json.songs || [];
    await c.db.collection('recordings').doc(base).set({
      base, createdAt: rec.json.createdAt, build: rec.json.app?.build || '', mode: rec.json.mode || '',
      song: songs[0]?.name || rec.songId || '', games: songs.length, sampleRate: rec.json.audio?.sampleRate || 0,
      wavBytes: wavBlob.size, wavParts, wavEncoding: 'base64 text, concatenate the decoded parts in order',
      jsonParts, jsonEncoding: jsonParts.length > 1 ? 'concatenate the text parts in order' : 'one JSON file',
      device: navigator.userAgent,
    });
    showCount();
    return true;
  };

  /* ---------- recordings kept on the phone (Safari outside claude.ai) ---------- */
  // Every game is stored in this browser's IndexedDB as it ends. "Send recordings" zips all the unsent
  // ones into one file for the share sheet (sharing needs a tap, so it can't happen by itself). Sent
  // recordings are kept until there are more than KEEP_SENT of them.
  const KEEP_SENT = 10;
  const recDb = () => new Promise((res, rej) => { const q = indexedDB.open('pi-recs', 1); q.onupgradeneeded = () => q.result.createObjectStore('recs', { keyPath: 'base' }); q.onsuccess = () => res(q.result); q.onerror = () => rej(q.error); });
  const tx = async (mode, fn) => { const db = await recDb(); return new Promise((res, rej) => { const t = db.transaction('recs', mode), st = t.objectStore('recs'); const out = fn(st); t.oncomplete = () => res(out?.result ?? out); t.onerror = () => rej(t.error); }); };
  const allRecs = () => tx('readonly', st => st.getAll());
  cloud.then(c => { if (c) return; R.localSave = async (base, wavBlob, text) => {
    // Safari can't store a Blob in IndexedDB in every version: keep the bytes as an ArrayBuffer.
    const wav = await wavBlob.arrayBuffer();
    await tx('readwrite', st => st.put({ base, wav, json: text, at: Date.now(), sent: false }));
    showSend();
  }; showSend(); });
  const send = $('#btnRecSend'), endSend = $('#btnEndSend');
  endSend.onclick = () => send.onclick();
  async function showSend() {
    try {
      const recs = await allRecs(), n = recs.filter(r => !r.sent).length;
      send.hidden = !n; send.textContent = `Send ${n} recording${n === 1 ? '' : 's'}`;
      endSend.hidden = !n; endSend.textContent = `Send ${n} recording${n === 1 ? '' : 's'} to Claude`;
      const c = $('#recCount'); c.hidden = false;
      c.textContent = n ? `${n} recording${n === 1 ? '' : 's'} saved on this phone, not sent yet.` : recs.length ? 'All recordings sent.' : 'No recordings yet.';
    } catch (e) { /* storage blocked */ }
  }
  // Minimal .zip writer (stored, no compression: WAV doesn't compress much and this stays fast).
  const CRC = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
  const crc32 = u8 => { let c = 0xFFFFFFFF; for (let i = 0; i < u8.length; i++) c = CRC[(c ^ u8[i]) & 255] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; };
  function zip(entries) {
    const enc = new TextEncoder(), parts = [], central = []; let off = 0;
    for (const { name, data } of entries) {
      const nm = enc.encode(name), crc = crc32(data), h = new DataView(new ArrayBuffer(30));
      h.setUint32(0, 0x04034b50, true); h.setUint16(4, 20, true); h.setUint32(14, crc, true); h.setUint32(18, data.length, true); h.setUint32(22, data.length, true); h.setUint16(26, nm.length, true);
      parts.push(h, nm, data);
      const c = new DataView(new ArrayBuffer(46));
      c.setUint32(0, 0x02014b50, true); c.setUint16(4, 20, true); c.setUint16(6, 20, true); c.setUint32(16, crc, true); c.setUint32(20, data.length, true); c.setUint32(24, data.length, true); c.setUint16(28, nm.length, true); c.setUint32(42, off, true);
      central.push(c, nm); off += 30 + nm.length + data.length;
    }
    const cl = central.reduce((a, x) => a + x.byteLength, 0), e = new DataView(new ArrayBuffer(22));
    e.setUint32(0, 0x06054b50, true); e.setUint16(8, entries.length, true); e.setUint16(10, entries.length, true); e.setUint32(12, cl, true); e.setUint32(16, off, true);
    return new Blob([...parts, ...central, e], { type: 'application/zip' });
  }
  send.onclick = async () => {
    const recs = (await allRecs()).filter(r => !r.sent).sort((a, b) => a.at - b.at);
    if (!recs.length) return showSend();
    const enc = new TextEncoder(), entries = recs.flatMap(r => [{ name: r.base + '.wav', data: new Uint8Array(r.wav) }, { name: r.base + '.json', data: enc.encode(r.json) }]);
    const d = new Date(), p2 = n => String(n).padStart(2, '0');
    const file = new File([zip(entries)], `piano-instant-recordings-${d.getFullYear()}${p2(d.getMonth() + 1)}${p2(d.getDate())}-${p2(d.getHours())}${p2(d.getMinutes())}.zip`, { type: 'application/zip' });
    try {
      if (navigator.canShare?.({ files: [file] })) await navigator.share({ files: [file], title: file.name });
      else { const a = document.createElement('a'); a.href = URL.createObjectURL(file); a.download = file.name; document.body.appendChild(a); a.click(); a.remove(); }
    } catch (e) { return; }   // cancelled: nothing marked as sent
    await tx('readwrite', st => { for (const r of recs) st.put({ ...r, sent: true }); });
    const sent = (await allRecs()).filter(r => r.sent).sort((a, b) => b.at - a.at).slice(KEEP_SENT);
    if (sent.length) await tx('readwrite', st => { for (const r of sent) st.delete(r.base); });
    showSend();
  };

  // Share sheet fallback when the phone can't keep recordings: sharing needs a tap, so it waits for one.
  const share = $('#btnRecShare');
  share.onclick = async () => {
    const p = R.pending; if (!p) return;
    try { await navigator.share({ files: p.files, title: p.base }); R.pending = null; share.hidden = true; }
    catch (e) { /* cancelled: keep it for another try */ }
  };
  const msg = $('#recMsg'), shown = R.onSaved;
  function toast(text, ms = 4500) {
    let t = document.querySelector('.rectoast'); if (!t) return;
    t.textContent = text; t.classList.add('on'); clearTimeout(t.t);
    if (ms) t.t = setTimeout(() => t.classList.remove('on'), ms);
  }
  R.onSaved = (base, how, withAudio = true) => {
    if (how === 'cloud') {
      msg.textContent = withAudio ? `Stored ${base} on this page. Ask Claude to analyse your latest recordings.` : `Stored ${base}, but without audio: the page couldn't record the microphone.`;
      toast(`Recording stored: ${base}` + (withAudio ? '' : ' (no audio)'));
      return;
    }
    if (how === 'local') {
      msg.textContent = withAudio ? `Saved ${base} on this phone. Tap "Send recordings" whenever you want to send them.` : `Saved ${base}, but without audio: the page couldn't record the microphone.`;
      toast(`Recording saved on this phone`);
      return;
    }
    if (how === 'share') {
      share.hidden = false; share.textContent = `Save ${base}`;
      msg.textContent = (R.cloudErr ? `Couldn't store it on the page (${R.cloudErr}). ` : '') + 'Tap "Save" to send the recording to Files, AirDrop or a chat.';
      toast(`Recording ready: tap Save on the Lessons screen`);
      return;
    }
    shown?.(base, how, withAudio);
  };
})();
"""
patch('glue', "\n</script>\n</body>", GLUE + "</script>\n</body>")

# 10. claude.ai artifacts wrap the page in their own <html>/<head>/<body>: ship only the content.
#     STANDALONE=1 keeps the full document (for a normal web host such as GitHub Pages).
import os, re
if os.environ.get('STANDALONE') == '1':
    dst.write_text(html, encoding='utf-8')
    print(f'wrote {dst} ({len(html) / 1024:.1f} KB, standalone)')
    sys.exit(0)
html = re.sub(r'^<!doctype html>\s*<html[^>]*>\s*<head>\s*<meta charset="utf-8">\s*<meta name="viewport"[^>]*>\s*', '', html, flags=re.I)
html = html.replace('</head>\n<body>\n', '\n', 1)
html = re.sub(r'</body>\s*</html>\s*$', '\n', html)
dst.write_text(html, encoding='utf-8')
print(f'wrote {dst} ({len(html) / 1024:.1f} KB)')
