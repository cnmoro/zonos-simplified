import {PCMReader, wavBlob} from './audio.mjs';
import {initializeReferences, addReferenceFiles, clearReferenceFiles, getReferenceFiles, referenceFileCount, setReferenceListDisabled, selectionPayload, analyzedReferenceCount, referencesBusy} from './references.js';
import {initializeMicrophone, setMicrophoneAvailable} from './recordings.js';
import {initializeReadingPrompts, setReadingLanguage, setReadingLocked} from './reading-prompts.js';
const $ = id => document.getElementById(id);
const session = globalThis.crypto?.randomUUID?.() ?? Array.from(globalThis.crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');
let cachedFile = null, cachedVoice = null, controller, context, objectURL;
let speakers = [], working = false, microphoneActive = false;
function chooseDefaultVoice() {
  if (speakers.some(speaker => speaker.id === $('voice').value && speaker.persistent)) return;
  const name = $('language').value === 'pt_br' ? 'Thiago_' : 'Jett_';
  const voice = speakers.find(speaker => speaker.original_name?.startsWith(name) && speaker.source_type === 'audio');
  if (voice) $('voice').value = voice.id;
}
$('language').onchange = () => { chooseDefaultVoice(); setReadingLanguage($('language').value); };
initializeReadingPrompts($('language').value);
const headers = {'Content-Type': 'application/json', 'X-TTS-Session-ID': session};
async function checked(response) {
  if (!response.ok) throw new Error(`API ${response.status}: ${(await response.text()).slice(0, 300)}`);
  return response;
}
async function loadSpeakers(selected) {
  const data = await (await checked(await fetch('/v2/speakers', {headers}))).json();
  speakers = data.speakers;
  $('voice').replaceChildren(new Option('Padrão do modelo', ''));
  const saved = document.createElement('optgroup'); saved.label = 'Minhas vozes prontas';
  const defaults = document.createElement('optgroup'); defaults.label = 'Vozes oficiais';
  for (const speaker of speakers) {
    if (speaker.speaker_modes.includes('embedding')) {
      (speaker.persistent ? saved : defaults).append(new Option(speaker.label, speaker.id));
    }
  }
  if (saved.children.length) $('voice').append(saved);
  $('voice').append(defaults);
  if (selected && speakers.some(speaker => speaker.id === selected)) $('voice').value = selected;
  else chooseDefaultVoice();
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
  $('generate').disabled = occupied || files.length > 1;
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
$('save-voice').onclick = async () => {
  const name = $('voice-name').value.trim();
  if (!name) { $('status').textContent = 'Dê um nome à voz antes de confirmar.'; return; }
  let selection;
  try { selection = selectionPayload(); }
  catch (error) { $('status').textContent = error.message; return; }
  working = true; updateReferenceControls();
  const controls = ['generate', 'language', 'voice', 'text', 'reference', 'voice-name', 'save-voice', 'analyze-references'];
  for (const id of controls) $(id).disabled = true;
  for (const input of document.querySelectorAll('#reference-rows input')) input.disabled = true;
  $('status').textContent = 'Salvando o perfil com as referências selecionadas…';
  try {
    const body = {name, language:$('language').value, ...selection};
    const voice = await (await checked(await fetch('/v2/voices', {method:'POST', headers, body:JSON.stringify(body)}))).json();
    $('reference').value = ''; $('voice-name').value = '';
    cachedFile = null; cachedVoice = null; clearReferenceFiles();
    await loadSpeakers(voice.id);
    $('reference-info').textContent = `${voice.name} está pronta com ${voice.sample_count} referência(s) e continuará disponível após reiniciar a API.`;
    $('status').textContent = 'Voz salva e pronta para usar';
  } catch (error) { $('status').textContent = error.message; }
  finally {
    for (const id of controls) $(id).disabled = false;
    for (const input of document.querySelectorAll('#reference-rows input')) input.disabled = false;
    working = false;
    updateReferenceControls();
  }
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
  if (working || referencesBusy() || microphoneActive || referenceFileCount() > 1) return;
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
    if (file) {
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
