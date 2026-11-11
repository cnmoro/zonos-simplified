import {selectedSimilarities} from './reference-math.mjs';
const $ = id => document.getElementById(id);
let analysis = null, selected = new Set(), urls = [], busy = false, validSelection = false;
let onChange = () => {};
let entries = [], fileUrls = [];
const coefficient = value => value === null ? 'Sem seleção' : value.toLocaleString('pt-BR', {minimumFractionDigits:3, maximumFractionDigits:3});
function cell(tag, text) { const node = document.createElement(tag); node.textContent = text; return node; }
export function getReferenceFiles() { return entries.map(entry => entry.file); }
export function referenceFileCount() { return entries.length; }
export function addReferenceFiles(files, source = 'upload') {
  if (entries.length + files.length > 20) throw new Error('Limite de 20 referências no conjunto. Remova uma antes de adicionar outra.');
  const total = [...getReferenceFiles(), ...files];
  if (total.some(file => file.size > 20 * 1024 * 1024) || total.reduce((sum, file) => sum + file.size, 0) > 64 * 1024 * 1024)
    throw new Error('Limite: 20 MiB por arquivo e 64 MiB no total.');
  resetReferences();
  entries.push(...files.map(file => ({file,source})));
  renderFileList(); onChange();
}
export function clearReferenceFiles() {
  resetReferences(); entries = []; renderFileList(); onChange();
}
export function setReferenceListDisabled(disabled) {
  for (const button of document.querySelectorAll('#reference-file-rows button')) button.disabled = disabled;
  $('clear-references').disabled = disabled;
}
function renderFileList() {
  for (const audio of document.querySelectorAll('#reference-file-rows audio')) { audio.pause(); audio.removeAttribute('src'); audio.load(); }
  for (const url of fileUrls) URL.revokeObjectURL(url); fileUrls = [];
  $('reference-file-rows').replaceChildren();
  $('reference-files').hidden = !entries.length; $('reference-files').open = true;
  $('reference-file-summary').textContent = `${entries.length} referência(s) carregada(s)`;
  entries.forEach((entry,i) => {
    const row = document.createElement('div'); row.className = 'reference-file';
    const name = cell('span', `${i+1}. ${entry.file.name} · ${entry.source === 'microphone' ? 'microfone' : 'arquivo'}`);
    const audio = document.createElement('audio'); audio.controls = true; audio.preload = 'none';
    const url = URL.createObjectURL(entry.file); fileUrls.push(url); audio.src = url;
    const remove = cell('button', 'Remover'); remove.type = 'button'; remove.setAttribute('aria-label', `Remover ${entry.file.name}`);
    remove.onclick = () => { resetReferences(); entries.splice(i,1); renderFileList(); onChange(); };
    row.append(name, remove, audio); $('reference-file-rows').append(row);
  });
}
export function hasReferenceAnalysis() { return analysis !== null; }
export function analyzedReferenceCount() { return analysis && validSelection ? selected.size : 0; }
export function referencesBusy() { return busy; }
export function selectionPayload() {
  if (!analysis || !selected.size) throw new Error('Analise as referências e marque pelo menos uma.');
  if (!validSelection) throw new Error('Os embeddings selecionados não formam uma média válida.');
  if (Date.now() / 1000 >= analysis.expires_at) throw new Error('A análise expirou. Analise os arquivos novamente.');
  return {analysis_id:analysis.id, selected_sample_ids:analysis.samples.filter((_, i) => selected.has(i)).map(sample => sample.id), confirmed:true};
}
export function resetReferences() {
  const previous = analysis;
  for (const audio of document.querySelectorAll('#reference-rows audio')) { audio.pause(); audio.removeAttribute('src'); audio.load(); }
  analysis = null; selected = new Set(); validSelection = false;
  for (const url of urls) URL.revokeObjectURL(url);
  urls = [];
  $('reference-analysis').hidden = true;
  $('reference-rows').replaceChildren(); $('similarity-matrix').replaceChildren();
  $('analysis-status').textContent = '';
  if (previous) fetch(`/v2/voice-analyses/${previous.id}`, {method:'DELETE'}).catch(() => {});
}
function updateSelection() {
  if (!analysis) return;
  const scores = selectedSimilarities(analysis.pairwise_similarity, analysis.samples.map(sample => sample.embedding_norm), [...selected].sort((a,b) => a-b));
  validSelection = selected.size > 0 && scores.every(score => score !== null);
  for (let i = 0; i < scores.length; i++) {
    $(`selected-mean-${i}`).textContent = coefficient(scores[i]);
    $(`sample-row-${i}`).classList.toggle('excluded', !selected.has(i));
  }
  $('selection-count').textContent = `${selected.size} de ${analysis.samples.length} referências selecionadas`;
  $('save-voice').disabled = busy || !selected.size || scores.every(score => score === null);
  onChange();
}
function render(files) {
  const rows = $('reference-rows'); rows.replaceChildren();
  for (let i = 0; i < analysis.samples.length; i++) {
    const sample = analysis.samples[i], row = document.createElement('tr'); row.id = `sample-row-${i}`;
    const choice = document.createElement('input'); choice.type = 'checkbox'; choice.checked = true;
    choice.dataset.sampleId = sample.id; choice.setAttribute('aria-label', `Usar ${sample.name}`);
    choice.onchange = () => { choice.checked ? selected.add(i) : selected.delete(i); updateSelection(); };
    const chooseCell = document.createElement('td'); chooseCell.append(choice); row.append(chooseCell);
    row.append(cell('th', `${i+1}. ${sample.name}`)); row.lastChild.scope = 'row';
    const audio = document.createElement('audio'); audio.controls = true; audio.preload = 'none';
    const url = URL.createObjectURL(files[i]); urls.push(url); audio.src = url; audio.setAttribute('aria-label', `Ouvir ${sample.name}`);
    const listen = document.createElement('td'); listen.append(audio); row.append(listen);
    row.append(cell('td', `${sample.reference_seconds.toFixed(1)} s`));
    row.append(cell('td', coefficient(sample.similarity_to_mean)));
    const score = cell('td', coefficient(sample.similarity_to_mean)); score.id = `selected-mean-${i}`; row.append(score);
    rows.append(row);
  }
  const table = $('similarity-matrix'); table.replaceChildren();
  const caption = document.createElement('caption'); caption.textContent = 'Cosseno entre cada par. Os números seguem a ordem dos arquivos acima.'; table.append(caption);
  const head = document.createElement('thead'), header = document.createElement('tr'); header.append(cell('th', 'Áudio'));
  for (let i = 0; i < analysis.samples.length; i++) { const th = cell('th', String(i+1)); th.scope = 'col'; th.title = analysis.samples[i].name; header.append(th); }
  head.append(header); table.append(head);
  const body = document.createElement('tbody');
  for (let i = 0; i < analysis.samples.length; i++) {
    const row = document.createElement('tr'), th = cell('th', String(i+1)); th.scope = 'row'; th.title = analysis.samples[i].name; row.append(th);
    for (const score of analysis.pairwise_similarity[i]) row.append(cell('td', coefficient(score)));
    body.append(row);
  }
  table.append(body); $('reference-analysis').hidden = false; $('reference-files').open = false; updateSelection();
}
export function initializeReferences(callback) {
  onChange = callback;
  $('clear-references').onclick = clearReferenceFiles;
  $('analyze-references').onclick = async () => {
    const files = getReferenceFiles();
    if (!files.length || files.length > 20) { $('analysis-status').textContent = 'Selecione de 1 a 20 áudios.'; return; }
    if (files.some(file => file.size > 20 * 1024 * 1024) || files.reduce((sum, file) => sum + file.size, 0) > 64 * 1024 * 1024) {
      $('analysis-status').textContent = 'Limite: 20 MiB por arquivo e 64 MiB no total.'; return;
    }
    resetReferences(); busy = true;
    setReferenceListDisabled(true); onChange();
    for (const id of ['reference', 'save-voice', 'generate', 'analyze-references']) $(id).disabled = true;
    $('analysis-status').textContent = `Processando ${files.length} áudio(s), um por vez…`;
    try {
      const form = new FormData(); for (const file of files) form.append('audio', file, file.name);
      const response = await fetch('/v2/voice-analyses', {method:'POST', body:form});
      if (!response.ok) throw new Error(`API ${response.status}: ${(await response.text()).slice(0,500)}`);
      analysis = await response.json(); selected = new Set(analysis.samples.map((_, i) => i));
      render(files);
      $('analysis-status').textContent = 'Análise pronta. Revise os áudios marcados antes de confirmar.';
    } catch (error) { $('analysis-status').textContent = error.message; }
    finally {
      busy = false; setReferenceListDisabled(false);
      $('reference').disabled = false; $('analyze-references').disabled = false;
      updateSelection(); onChange();
    }
  };
}
