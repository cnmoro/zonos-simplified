const $ = id => document.getElementById(id);
let current = null, timer = null, sequence = 0;
function disableDownload() { $('download').removeAttribute('href'); $('download').setAttribute('aria-disabled','true'); }
function ready(url, speed, seconds) {
  $('download').href = url; $('download').download = `zonos-${speed.toFixed(1)}x.wav`;
  $('download').setAttribute('aria-disabled','false');
  $('download-duration').textContent = `${seconds.toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:3})} s`;
  $('download-duration').dataset.seconds = String(seconds);
}
function discard(asset,keepalive=false) {
  if (asset) fetch(`/v2/audio-assets/${asset.id}`,{method:'DELETE',keepalive}).catch(() => {});
}
async function register(state) {
  if (state.asset && state.asset.expires_at > Date.now()/1000) return state.asset;
  if (state.pending) return state.pending;
  state.pending = (async () => {
    const form = new FormData(); form.append('audio',state.blob,'zonos.wav');
    const response = await fetch('/v2/audio-assets',{method:'POST',body:form});
    if (!response.ok) throw new Error(`API ${response.status}: ${(await response.text()).slice(0,250)}`);
    const asset = await response.json();
    if (state !== current) { discard(asset); throw new Error('Áudio substituído'); }
    state.asset = asset; state.pending = null;
    $('download-durations').href = asset.durations_url; $('download-durations').hidden = false;
    return asset;
  })().catch(error => { state.pending = null; throw error; });
  return state.pending;
}
async function selectedDuration(state, speed, retry=true) {
  const asset = await register(state);
  const response = await fetch(`${asset.durations_url}?speeds=${speed.toFixed(1)}`,{cache:'no-store'});
  if (!response.ok && [404,410].includes(response.status) && retry) {
    state.asset = null; state.pending = null;
    return selectedDuration(state,speed,false);
  }
  if (!response.ok) throw new Error(`API ${response.status}: ${(await response.text()).slice(0,250)}`);
  const info = await response.json();
  return info.variants[0];
}
function speedChanged() {
  clearTimeout(timer);
  const state = current, version = ++sequence, speed = Number($('download-speed').value);
  $('download-speed-value').textContent = `${speed.toFixed(1)}x`;
  $('download').textContent = `Baixar WAV ${speed.toFixed(1)}x`;
  if (!state) { disableDownload(); return; }
  if (speed === 1) { ready(state.url,1,state.duration); $('download-note').textContent = 'Velocidade aplicada ao arquivo baixado. O player acima reproduz o original.'; return; }
  disableDownload(); $('download-duration').textContent = 'Calculando duração…'; delete $('download-duration').dataset.seconds;
  timer = setTimeout(async () => {
    try {
      const variant = await selectedDuration(state,speed);
      if (current !== state || version !== sequence) return;
      ready(variant.download_url,speed,variant.duration_seconds);
      $('download-note').textContent = 'Duração medida no arquivo convertido. O tom da voz é preservado; o player acima reproduz o original.';
    } catch (error) {
      if (current !== state || version !== sequence) return;
      $('download-duration').textContent = 'Conversão indisponível';
      $('download-note').textContent = `${error.message}. Você ainda pode baixar o original em 1.0x.`;
    }
  },180);
}
export function clearDownloadAudio() {
  clearTimeout(timer); sequence++;
  if (current) discard(current.asset);
  current = null;
  $('download-durations').hidden = true; disableDownload();
}
export function setDownloadAudio(blob,url,duration) {
  clearDownloadAudio();
  const state = {blob,url,duration,asset:null,pending:null}; current = state;
  $('download-speed').value = '1.0'; speedChanged();
  register(state).catch(error => {
    if (current === state && Number($('download-speed').value) === 1)
      $('download-note').textContent = `Original disponível. Não foi possível preparar as outras velocidades: ${error.message}`;
  });
}
export function initializeDownloads() {
  window.addEventListener('pagehide',event => { if (!event.persisted) discard(current?.asset,true); });
  $('download-speed').oninput = speedChanged;
  $('download').onclick = event => { if ($('download').getAttribute('aria-disabled') === 'true') event.preventDefault(); };
}
