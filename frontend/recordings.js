const $ = id => document.getElementById(id);
let recorder = null, stream = null, chunks = [], timer = null, limit = null;
let active = false, available = true, count = 0, callbacks = {}, generation = 0;
export function microphoneSupported() {
  return !!(window.isSecureContext && navigator.mediaDevices?.getUserMedia && window.MediaRecorder);
}
export function setMicrophoneAvailable(value) {
  available = value;
  $('record-start').disabled = !value || active || !microphoneSupported();
}
function stopTracks() { if (stream) for (const track of stream.getTracks()) track.stop(); stream = null; }
function release() {
  clearInterval(timer); clearTimeout(limit); timer = null; limit = null;
  stopTracks(); active = false; recorder = null; chunks = [];
  $('record-stop').disabled = true; setMicrophoneAvailable(available);
  callbacks.onStateChange(false);
}
export function initializeMicrophone(options) {
  callbacks = options;
  if (!microphoneSupported()) {
    $('microphone-help').hidden = false;
    $('microphone-origin').textContent = 'A API HTTP continua disponível; a gravação usa HTTPS ou localhost.';
    $('microphone-status').textContent = 'O navegador não permite microfone nesta origem. Veja como habilitar abaixo.';
  }
  const https = new URL(location.href); https.protocol = 'https:'; https.port = '1920';
  $('microphone-https').href = https.origin;
  fetch('/tls.json').then(response => response.ok ? response.json() : null).then(config => {
    if (config) { https.port = String(config.https_port); $('microphone-https').href = https.origin; }
  }).catch(() => {});
  setMicrophoneAvailable(true);
  $('record-start').onclick = async () => {
    if (active || !available || !microphoneSupported()) return;
    for (const audio of document.querySelectorAll('audio')) audio.pause();
    const requestGeneration = ++generation;
    active = true; callbacks.onStateChange(true); $('record-start').disabled = true;
    $('microphone-status').textContent = 'Aguardando permissão do microfone…';
    try {
      const acquired = await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:false, noiseSuppression:false, autoGainControl:false}});
      if (requestGeneration !== generation) { for (const track of acquired.getTracks()) track.stop(); return; }
      stream = acquired;
      const mimeType = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4']
        .find(type => MediaRecorder.isTypeSupported(type));
      recorder = mimeType ? new MediaRecorder(stream, {mimeType}) : new MediaRecorder(stream);
      const currentRecorder = recorder;
      chunks = [];
      let failed = false, bytes = 0;
      recorder.ondataavailable = event => {
        if (recorder !== currentRecorder) return;
        if (event.data.size) { chunks.push(event.data); bytes += event.data.size; }
        if (bytes > 20 * 1024 * 1024 && recorder?.state === 'recording') {
          failed = true; $('microphone-status').textContent = 'Gravação excedeu 20 MiB.'; recorder.stop();
        }
      };
      recorder.onerror = () => {
        if (recorder !== currentRecorder) return;
        failed = true; $('microphone-status').textContent = 'Falha ao gravar. Verifique o microfone e tente novamente.';
        if (recorder && recorder.state !== 'inactive') recorder.stop(); else release();
      };
      recorder.onstop = () => {
        if (recorder !== currentRecorder) return;
        const type = recorder?.mimeType || chunks[0]?.type || 'audio/webm';
        const blob = new Blob(chunks, {type});
        try {
          if (!failed && blob.size) {
            const extension = type.includes('ogg') ? 'ogg' : type.includes('mp4') ? 'm4a' : 'webm';
            const file = new File([blob], `microfone-${++count}.${extension}`, {type});
            callbacks.onRecorded(file);
            $('microphone-status').textContent = `${file.name} adicionada. Você pode gravar outra amostra.`;
          } else if (!failed) $('microphone-status').textContent = 'Nenhum áudio capturado. Tente novamente.';
        } catch (error) { $('microphone-status').textContent = error.message; }
        finally { release(); }
      };
      const started = performance.now();
      recorder.start(250); $('record-stop').disabled = false;
      $('microphone-status').textContent = 'Gravando 0,0 s. Limite de 60 s por amostra.';
      timer = setInterval(() => { $('microphone-status').textContent = `Gravando ${((performance.now()-started)/1000).toFixed(1)} s. Limite de 60 s por amostra.`; }, 200);
      limit = setTimeout(() => { if (recorder?.state === 'recording') recorder.stop(); }, 60000);
    } catch (error) {
      if (requestGeneration !== generation) return;
      $('microphone-status').textContent = error.name === 'NotAllowedError'
        ? 'Permissão negada. Libere o microfone nas permissões deste site e tente novamente.'
        : `Não foi possível abrir o microfone: ${error.message}`;
      release();
    }
  };
  $('record-stop').onclick = () => { if (recorder?.state === 'recording') recorder.stop(); };
  window.addEventListener('pagehide', () => {
    generation++;
    if (recorder?.state === 'recording') recorder.stop();
    release();
  });
}
