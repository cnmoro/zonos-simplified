const $ = id => document.getElementById(id);
let catalog = null, language = 'pt_br', locked = false;
const positions = {pt_br:0, en_us:0};
function render() {
  if (!catalog) return;
  const prompts = catalog.languages[language] || [];
  $('reading-prompt').replaceChildren(...prompts.map((prompt,i) => new Option(`${i+1}. ${prompt.title}`,String(i))));
  $('reading-prompt').value = String(positions[language] || 0);
  const prompt = prompts[positions[language] || 0];
  $('reading-text').textContent = prompt?.text || 'Nenhum texto disponível neste idioma.';
  $('reading-text').lang = language === 'pt_br' ? 'pt-BR' : 'en-US';
  $('reading-count').textContent = prompt ? `${(positions[language] || 0)+1} de ${prompts.length} · ${prompt.text.trim().split(/\s+/u).length} palavras` : '';
  setReadingLocked(locked);
}
export function setReadingLanguage(value) { language = value; render(); }
export function setReadingLocked(value) {
  locked = value;
  for (const id of ['reading-prompt','reading-previous','reading-next']) $(id).disabled = locked || !catalog;
}
export async function initializeReadingPrompts(value) {
  language = value;
  $('reading-prompt').onchange = () => { positions[language] = Number($('reading-prompt').value); render(); };
  $('reading-previous').onclick = () => { positions[language] = ((positions[language] || 0)-1+catalog.languages[language].length)%catalog.languages[language].length; render(); };
  $('reading-next').onclick = () => { positions[language] = ((positions[language] || 0)+1)%catalog.languages[language].length; render(); };
  try {
    const response = await fetch('/reading-prompts.json');
    if (!response.ok) throw new Error('Textos indisponíveis');
    catalog = await response.json(); render();
  } catch {
    $('reading-text').textContent = 'Não foi possível carregar os textos de apoio. Você pode gravar falando naturalmente ou ler um texto próprio.';
  }
}
