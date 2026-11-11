import {PCMReader, wavBlob} from './audio.mjs';
import {initializeReferences, addReferenceFiles, clearReferenceFiles, getReferenceFiles, referenceFileCount, setReferenceListDisabled, selectionPayload, analyzedReferenceCount, referencesBusy, hasReferenceAnalysis} from './references.js';
import {initializeMicrophone, setMicrophoneAvailable} from './recordings.js';
import {initializeReadingPrompts, setReadingLanguage, setReadingLocked} from './reading-prompts.js';
const $ = id => document.getElementById(id);
function newSession() {
  return globalThis.crypto?.randomUUID?.() ?? Array.from(globalThis.crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');
}
let session;
try { session = sessionStorage.getItem('zonos.session') || newSession(); sessionStorage.setItem('zonos.session',session); }
catch { session = newSession(); }
function preference(key) { try { return localStorage.getItem(key); } catch { return null; } }
function remember(key,value) { try { value ? localStorage.setItem(key,value) : localStorage.removeItem(key); } catch {} }
function rememberSelection() {
  const selected = speakers.find(speaker => speaker.id === $('voice').value);
  remember('zonos.voiceId',selected && (selected.persistent || selected.is_default) ? selected.id : null);
  remember('zonos.language',$('language').value);
  updateReferenceControls();
}
let cachedFile = null, cachedVoice = null, controller, context, objectURL;
let speakers = [], working = false, microphoneActive = false;
function chooseDefaultVoice() {
  if (speakers.some(speaker => speaker.id === $('voice').value && speaker.persistent)) return;
  const name = $('language').value === 'pt_br' ? 'Thiago_' : 'Jett_';
  const voice = speakers.find(speaker => speaker.original_name?.startsWith(name) && speaker.source_type === 'audio');
  if (voice) $('voice').value = voice.id;
}
if (['pt_br','en_us'].includes(preference('zonos.language'))) $('language').value = preference('zonos.language');
$('language').onchange = () => { chooseDefaultVoice(); setReadingLanguage($('language').value); rememberSelection(); };
$('voice').onchange = rememberSelection;
initializeReadingPrompts($('language').value);
const headers = {'Content-Type': 'application/json', 'X-TTS-Session-ID': session};
async function checked(response) {
  if (!response.ok) throw new Error(`API ${response.status}: ${(await response.text()).slice(0, 300)}`);
  return response;
}
async function loadSpeakers(selected) {
  const data = await (await checked(await fetch('/v2/speakers', {headers,cache:'no-store'}))).json();
  speakers = data.speakers;
  $('voice').replaceChildren(new Option('Padrão do modelo', ''));
  const saved = document.createElement('optgroup'); saved.label = 'Minhas vozes prontas';
  const defaults = document.createElement('optgroup'); defaults.label = 'Vozes oficiais';
  const temporary = document.createElement('optgroup'); temporary.label = 'Referências temporárias desta aba';
  for (const speaker of speakers) {
    if (speaker.speaker_modes.includes('embedding')) {
      (speaker.persistent ? saved : speaker.is_default ? defaults : temporary).append(new Option(speaker.label, speaker.id));
    }
  }
  if (saved.children.length) $('voice').append(saved);
  $('voice').append(defaults);
  if (temporary.children.length) $('voice').append(temporary);
  const preferred = selected || preference('zonos.voiceId');
  if (preferred && speakers.some(speaker => speaker.id === preferred)) $('voice').value = preferred;
  else chooseDefaultVoice();
  updateReferenceControls();
}
async function connect() {
  try {
    await checked(await fetch('/v2/health'));
    await loadSpeakers();
    $('health').textContent = 'Modelo conectado';
  } catch { $('health').textContent = 'Modelo indisponível'; }
}
function fileBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(',')[1]);
    reader.onerror = () => reject(new Error('Falha ao ler arquivo')); reader.readAsDataURL(file);
  });
}
function updateReferenceControls() {
  const files = getReferenceFiles();
  const occupied = working || referencesBusy() || microphoneActive;
  $('reference').disabled = occupied;
  $('language').disabled = occupied;
  setReadingLocked(occupied);
  setReferenceListDisabled(occupied);
  for (const input of document.querySelectorAll('#reference-rows input')) input.disabled = occupied;
  setMicrophoneAvailable(!occupied && files.length < 20);
  $('voice').disabled = occupied || !!files.length;
  $('analyze-references').disabled = occupied || !files.length;
  $('save-voice').disabled = occupied || !analyzedReferenceCount();
  $('generate').disabled = occupied || files.length > 1 || (hasReferenceAnalysis() && !analyzedReferenceCount());
  const named = !!$('voice-name').value.trim();
  if (named && !files.length) $('generate').disabled = true;
  $('generate').textContent = files.length > 1 ? 'Salve o perfil para gerar' : files.length && named ? 'Salvar voz e gerar' : files.length ? 'Gerar sem salvar' : 'Gerar voz';
  const selected = speakers.find(speaker => speaker.id === $('voice').value);
  $('voice-state').textContent = files.length
    ? (named ? 'A voz será salva no servidor antes da geração.' : 'Sem nome: a referência é temporária. Para guardar, preencha o nome.')
    : named ? 'Grave ou envie um áudio para criar a voz com esse nome.'
    : selected?.persistent ? 'Perfil salvo no servidor, disponível após recarregar a página.'
    : selected?.is_default ? 'Voz oficial selecionada.' : '';

}
initializeReferences(updateReferenceControls);
initializeMicrophone({
  onStateChange: active => {
    microphoneActive = active;
    if (active && context && context.state !== 'closed') context.close().catch(() => {});
    updateReferenceControls();
  },
  onRecorded: file => { cachedFile = null; cachedVoice = null; addReferenceFiles([file], 'microphone'); }
});
$('voice-name').oninput = updateReferenceControls;
async function persistNamedVoice({allowSingle=false,signal}={}) {
  const name = $('voice-name').value.trim();
  if (!name) throw new Error('Dê um nome à voz antes de confirmar.');
  let source;
  if (hasReferenceAnalysis()) source = selectionPayload();
  else if (allowSingle && referenceFileCount() === 1) {
    const file = getReferenceFiles()[0];
    source = {speaker_audio_name:file.name,speaker_audio_base64:await fileBase64(file)};
  } else throw new Error('Analise as referências e confirme a seleção antes de salvar.');
  $('status').textContent = 'Salvando a voz no servidor…';
  const body = {name,language:$('language').value,...source};
  const voice = await (await checked(await fetch('/v2/voices', {method:'POST',headers,signal,body:JSON.stringify(body)}))).json();
  if (!voice.ready || !voice.persistent) throw new Error('A API não confirmou a persistência da voz. A geração foi interrompida.');
  remember('zonos.voiceId',voice.id); remember('zonos.language',$('language').value);
  $('reference').value = ''; $('voice-name').value = '';
  cachedFile = null; cachedVoice = null; clearReferenceFiles();
  await loadSpeakers(voice.id);
  $('reference-info').textContent = `${voice.name} foi salva no servidor e continuará disponível após recarregar a página.`;
  return voice;
}
$('save-voice').onclick = async () => {
  working = true; updateReferenceControls();
  $('voice-name').disabled = true;
  try {
    await persistNamedVoice();
    $('status').textContent = 'Voz salva e pronta para usar';
  } catch (error) { $('status').textContent = error.message; }
  finally { working = false; $('voice-name').disabled = false; updateReferenceControls(); }
};
$('reference').onchange = () => {
  cachedFile = null; cachedVoice = null;
  try { addReferenceFiles([...$('reference').files]); }
  catch (error) { $('status').textContent = error.message; }
  $('reference').value = '';
  updateReferenceControls();
  $('reference-info').textContent = referenceFileCount() > 1
    ? 'Analise os áudios e confirme os selecionados para criar o perfil antes de gerar.'
    : 'Analise para salvar um perfil, ou gere diretamente com a referência temporária.';
};
$('cancel').onclick = () => { controller?.abort(); context?.close(); };
$('form').onsubmit = async event => {
  event.preventDefault();
  if (working || referencesBusy() || microphoneActive || referenceFileCount() > 1 || (hasReferenceAnalysis() && !analyzedReferenceCount())) return;
  if ($('voice-name').value.trim() && !referenceFileCount()) { $('status').textContent = 'Grave ou envie a referência antes de salvar uma nova voz.'; return; }
  working = true; updateReferenceControls();
  controller = new AbortController();
  const signal = controller.signal;
  $('generate').disabled = true; $('cancel').hidden = false; $('result').hidden = true;
  for (const id of ['language', 'voice', 'text', 'reference', 'voice-name', 'save-voice', 'analyze-references']) $(id).disabled = true;
  $('audio').pause(); $('audio').removeAttribute('src');
  if (objectURL) { URL.revokeObjectURL(objectURL); objectURL = null; }
  $('status').textContent = 'Preparando…';
  const chunks = [], readerPCM = new PCMReader();
  let samples = 0, first = null, nextTime = 0, start;
  try {
    if (context && context.state !== 'closed') await context.close();
    context = new AudioContext({sampleRate: 44100}); await context.resume();
    const file = getReferenceFiles()[0];
    if (file && file.size > 20 * 1024 * 1024) throw new Error('Use uma referência com até 20 MB.');
    let voice = $('voice').value;
    const saveBeforeGenerating = file && $('voice-name').value.trim();
    if (saveBeforeGenerating) voice = (await persistNamedVoice({allowSingle:true,signal})).id;
    if (file && !saveBeforeGenerating) {
      if (cachedFile !== file || !cachedVoice) {
        $('status').textContent = 'Processando a voz de referência…';
        const base64 = await fileBase64(file);
        const result = await (await checked(await fetch('/v2/speakers', {method:'POST', headers, signal,
          body:JSON.stringify({label:file.name, speaker_audio_name:file.name, speaker_audio_base64:base64})}))).json();
        cachedFile = file; cachedVoice = result.id;
      }
      voice = cachedVoice;
    }
    start = performance.now();
    const payload = {text:$('text').value.trim(), language:$('language').value, stream:true, format:'pcm',
      speaker_mode:'embedding', speaker_cfg_scale:1, decoder:'keep2_plain', max_tokens:1000};
    if (voice) payload.speaker_embedding_id = voice;
    const response = await checked(await fetch('/v2/generate', {method:'POST', headers, signal, body:JSON.stringify(payload)}));
    const stream = response.body.getReader();
    $('status').textContent = 'Gerando…';
    while (true) {
      const {value, done} = await stream.read(); if (done) break;
      const part = readerPCM.push(value); if (!part.length) continue;
      if (first === null) first = performance.now() - start;
      samples += part.length;
      if (samples > 44100 * 75) throw new Error('Limite de áudio excedido. Divida o texto.');
      chunks.push(part);
      const buffer = context.createBuffer(1, part.length, 44100); buffer.copyToChannel(part, 0);
      const source = context.createBufferSource(); source.buffer = buffer; source.connect(context.destination);
      nextTime = Math.max(nextTime, context.currentTime + 0.06); source.start(nextTime); nextTime += buffer.duration;
      $('status').textContent = 'Reproduzindo enquanto gera…';
    }
    if (readerPCM.pending.length || !samples) throw new Error('Áudio incompleto ou vazio.');
    objectURL = URL.createObjectURL(wavBlob(chunks)); $('audio').src = objectURL; $('download').href = objectURL;
    const elapsed = (performance.now() - start) / 1000, duration = samples / 44100;
    $('metrics').textContent = `${duration.toFixed(1)} s de áudio · Primeiro áudio: ${Math.round(first)} ms · RTF: ${(elapsed / duration).toFixed(2)}`;
    $('result').hidden = false; $('status').textContent = 'Concluído';
    // Let queued playback finish, then release audio resources.
    const finishedContext = context;
    setTimeout(() => { if (finishedContext.state !== 'closed') finishedContext.close(); }, Math.max(0, nextTime - context.currentTime + 0.2) * 1000);
  } catch (error) {
    controller.abort();
    if (context && context.state !== 'closed') await context.close();
    $('status').textContent = error.name === 'AbortError' ? 'Interrompido' : error.message;
  } finally {
    $('generate').disabled = false; $('cancel').hidden = true;
    for (const id of ['language', 'text', 'reference', 'voice-name']) $(id).disabled = false;
    working = false;
    updateReferenceControls();
  }
};
connect();
