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
    if (navigator.canShare?.({ files })) { R.pending = { base, files }; R.onSaved?.(base, 'share', chunks.length > 0); return; }
    for (const [name, data] of [[base + '.wav', blob], [base + '.json', new Blob([text], { type: 'application/json' })]]) {
      const a = document.createElement('a');""")

# 7. Recording controls text.
patch('rec-msg',
"""<p id="recMsg" class="note">Every game is saved by itself as a sound file plus a log of what the game heard and decided, so a missed note can be found and fixed. Pick a folder once (for example Desktop\\Piano Instant\\recordings); without one, each recording downloads. Press <kbd>M</kbd> during a song the moment it misses a note you played. Nothing leaves this computer.</p>""",
"""<p id="recMsg" class="note">Every game is saved as a sound file plus a log of what the game heard and decided, so a missed note can be found and fixed. On this page they're stored with the page itself, where Claude can fetch and check them. Tap <b>Missed one</b> during a song the moment it misses a note you played.</p>
      <p id="recCount" class="note" hidden></p>
      <button id="btnRecShare" class="ghost" type="button" hidden>Save last recording</button>""")

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
  cloud.then(c => { if (!c) $('#recMsg').innerHTML = 'Every game is saved as a sound file plus a log of what the game heard and decided, so a missed note can be found and fixed. After a game, tap <b>Save last recording</b> here to send it to Files, AirDrop or a chat. Tap <b>Missed one</b> during a song the moment it misses a note you played.'; });
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

  // Share sheet (Safari outside claude.ai): sharing needs a tap, so the recording waits for one.
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
