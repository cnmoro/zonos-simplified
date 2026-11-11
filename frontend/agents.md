# Zonos Simplified: guia operacional para agentes

Este documento é servido por `GET /agents.md`. Use HTTP para operar a API; não é necessário acesso ao terminal do servidor. A base da API é **a mesma origem desta URL**, sem `/agents.md`. Exemplo: se este documento veio de `http://100.x.y.z:1919/agents.md`, use `http://100.x.y.z:1919`. Nos exemplos, `BASE` representa essa origem.

## 1. Regras essenciais

- O modelo é ZONOS3-Mini, com backbone quantizado e decoder leve em GPU. A aplicação oferece inglês (`en_us`) e português brasileiro (`pt_br`). O idioma não precisa ser o mesmo da referência; sotaque e semelhança não são garantidos.
- **Sempre envie `speaker_mode: "embedding"` e `decoder: "keep2_plain"` nas gerações.** O modo `reference` de referência bruta não está instalado nesta configuração e não é necessário para clonagem por embedding.
- Prefira vozes persistentes (`voice_...`) para trabalho recorrente. Elas ficam prontas antes de a criação responder, podem ser usadas sem sessão e sobrevivem à reinicialização.
- Vozes temporárias (`spk_...`) exigem o mesmo `X-TTS-Session-ID`, só existem enquanto o processo atual estiver ativo e processam o embedding na primeira utilização.
- Não invente IDs de vozes. Liste-os antes de usar. O ID, não o nome, deve ser passado na geração.
- Um slot de geração e um decoder estão configurados. Faça gerações sequenciais para obter latência previsível. Requisições concorrentes podem esperar na fila.
- Use timeout de conexão de 10 segundos e timeout total de pelo menos 180 segundos para pré-processamento/geração. Observe o status HTTP e o corpo dos erros antes de salvar uma saída como áudio.
- `max_tokens: 1000` é o teto configurado: são posições autoregressivas de áudio, incluindo o atraso dos codebooks, e não tokens de texto. Com 15 frames/s, permite aproximadamente um minuto. Divida textos longos em parágrafos/frases e gere sequencialmente; atingir o teto pode truncar a fala. O frontend/CLI limitam o texto a 3000 caracteres, mas o limite real útil depende da duração falada.
- Para baixa latência/custo, use `speaker_cfg_scale: 1.0`. Guidance acima disso exige mais slots e não é suportada pelo launcher atual.
- Os áudios são mono a 44100 Hz. `wav` é PCM16 completo. **`pcm` é float32 little-endian, não PCM16**, sem cabeçalho.
- Nesta implantação, não há autenticação configurada por padrão. Clientes com acesso de rede à API podem listar, criar, renomear, apagar e usar vozes salvas. Não trate `X-TTS-Session-ID` como autenticação. Se o operador configurar `ZONOS3_ACCESS_TOKEN`, envie `Authorization: Bearer TOKEN` em todas as chamadas, inclusive ao documento; não registre esse token em arquivos, logs ou URLs.

## 2. Descoberta e disponibilidade

```bash
BASE='http://127.0.0.1:1919' # substitua pela origem usada para obter este documento
curl --fail-with-body "$BASE/v2/health"
curl --fail-with-body "$BASE/v2/capabilities"
curl --fail-with-body "$BASE/v2/speakers"
curl --fail-with-body "$BASE/v2/voices"
```

- `GET /v2/health` -> HTTP 200 `{"status":"ok"}`.
- `GET /v2/capabilities` -> capacidades reais, decoders e controles disponíveis. Não deduza que recursos opcionais estão instalados só porque existem na documentação upstream.
- `GET /v2/speakers` -> `{"speakers":[...]}`. Inclui vozes oficiais e persistentes. Com `X-TTS-Session-ID`, inclui também as vozes temporárias daquela sessão. Cada voz inclui `id`, `label`, `source_type`, `speaker_modes`, `embedding_dim`, `has_preview`, `is_default`, `scope` e outros metadados. Vozes salvas incluem também `persistent:true`, `ready:true` e `language`. Para compatibilidade com o contrato nativo, essas vozes globais usam `scope:"default"`; identifique a biblioteca do usuário por `persistent:true`.
- `GET /v2/voices` -> `{"voices":[...]}`. Retorna **somente a biblioteca persistente do usuário**. Lista vazia é normal; vozes oficiais estão em `/v2/speakers`.
- `GET /v1/models` -> lista compatível com OpenAI; modelo `zonos3`.

Para selecionar uma voz oficial, filtre `speaker_modes` contendo `embedding`. `label` indica o nome. As vozes oficiais Thiago/Leonor falam português; Jett e outras vozes de rótulo `en` falam inglês. Consulte IDs atuais, em vez de fixar valores no código.

## 3. Salvar uma voz nomeada, pronta para reutilização

### 3.0 Vários áudios: analisar, revisar a seleção e confirmar

Para um perfil formado por várias gravações, use este fluxo em duas etapas. Analisar **não cria** a voz. Não envie `confirmed:true` sem que o usuário tenha escolhido quais referências usar e autorizado a criação do perfil.

**Etapa A: `POST /v2/voice-analyses`** aceita multipart com o campo `audio` repetido:

```bash
curl --fail-with-body --max-time 180 "$BASE/v2/voice-analyses" \
  -F 'audio=@take-1.wav' \
  -F 'audio=@take-2.mp3' \
  -F 'audio=@take-3.ogg' -o analysis.json
```

Também aceita JSON, com uma lista ordenada `samples`:

```json
{
  "samples": [
    {"name":"take-1.wav","speaker_audio_base64":"BASE64_REAL_1"},
    {"name":"take-2.ogg","speaker_audio_base64":"BASE64_REAL_2"}
  ]
}
```

Limites: **1 a 20 amostras**, **20 MiB por arquivo**, **64 MiB somados** e **96 MiB por requisição HTTP**. Cada áudio é considerado por até 60 segundos, independentemente dos outros. Processamento sequencial na GPU evita multiplicar workspaces. Apenas um lote é pré-processado por vez; outro lote concorrente recebe 429. Nenhuma média é salva automaticamente.

HTTP 201 retorna:

```json
{
  "id":"analysis_0123456789abcdef01234567",
  "analysis_id":"analysis_0123456789abcdef01234567",
  "created_at":1790000000.0,
  "expires_at":1790001800.0,
  "persistent":false,
  "sample_count":2,
  "preprocessing_ms":2500.0,
  "metric":"cosine",
  "aggregation":"arithmetic_mean",
  "selected_sample_ids":["sample_1","sample_2"],
  "samples":[
    {"id":"sample_1","name":"take-1.wav","reference_seconds":8.0,"preprocessing_ms":1200.0,"embedding_norm":10.0,"similarity_to_mean":0.97},
    {"id":"sample_2","name":"take-2.ogg","reference_seconds":7.0,"preprocessing_ms":1300.0,"embedding_norm":10.0,"similarity_to_mean":0.97}
  ],
  "pairwise_similarity":[[1.0,0.88],[0.88,1.0]],
  "interpretation":"Embedding consistency, not a quality score or identity probability"
}
```

Números e IDs são ilustrativos. `pairwise_similarity[i][j]` corresponde às posições `i` e `j` em `samples`. Os nomes podem se repetir; selecione pelos **IDs**, não pelo nome do arquivo. Os IDs `sample_1`, etc. só fazem sentido dentro de sua análise.

A matriz contém **similaridade de cosseno** entre os embeddings, no intervalo −1..1. Na resposta inicial, `similarity_to_mean` usa a média de todas as amostras. Os embeddings não são expostos nessa resposta; `embedding_norm` e a matriz permitem recalcular o cosseno de uma seleção no cliente.

**Não interprete os coeficientes como notas de qualidade, porcentagem de semelhança ou probabilidade de identidade.** Não há limiar automático de aprovação/reprovação. Uma amostra contribui para a média quando selecionada; com só uma amostra selecionada, sua similaridade com a própria média será 1 por construção. A escuta das referências continua relevante.

A agregação é a **média aritmética dos embeddings brutos float32**, um coeficiente `1/N` por gravação selecionada, sem normalização adicional ou peso por duração. Essa escolha segue o comportamento de agregação do runtime nativo. Gravações de durações diferentes têm o mesmo coeficiente; magnitudes dos vetores não são forçadas a serem iguais.

Para consultar a análise original: `GET /v2/voice-analyses/{analysis_id}`. Para recalcular a comparação com a média de um subconjunto, sem reenviar áudio ou criar um perfil:

```bash
curl --fail-with-body "$BASE/v2/voice-analyses/analysis_ID_REAL/selection" \
  -H 'Content-Type: application/json' \
  -d '{"selected_sample_ids":["sample_1","sample_3"]}'
```

A lista precisa conter pelo menos um ID válido, sem duplicatas. A resposta tem o mesmo formato da análise, mas `similarity_to_mean` é recalculado para **todos** os áudios em relação à média escolhida. A matriz entre pares continua igual. Essa consulta não altera a análise original nem cria uma voz. A seleção de exemplo só é válida se houver pelo menos três amostras na análise real.

**Etapa B: confirmação e cadastro.** Depois que o usuário escolher as referências e confirmar, faça:

```bash
curl --fail-with-body "$BASE/v2/voices" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Perfil revisado","language":"pt_br","analysis_id":"analysis_ID_REAL","selected_sample_ids":["sample_1","sample_3"],"confirmed":true}'
```

Retorna HTTP 201 com a voz persistente já pronta. A confirmação usa os embeddings em cache e **não extrai os áudios novamente**. A voz contém `sample_count` e `reference_analysis` com os IDs/nomes das referências escolhidas e o cosseno de cada uma com o perfil final. Referências desmarcadas não contribuem para a média e seus metadados não são gravados no perfil.

As análises expiram **30 minutos depois de terminar o processamento**, com no máximo 32 análises pendentes; a remoção da cache expirada ocorre no próximo acesso/novo lote ou ao encerrar o processo. Guardam apenas embeddings e metadados, não áudio/PCM. Reiniciar a API remove análises ainda não confirmadas; vozes já salvas permanecem em disco. Se receber 404/410, reenvie os arquivos e peça ao usuário para revisar a nova análise. `DELETE /v2/voice-analyses/{id}` descarta a análise; isso não apaga uma voz que já foi criada a partir dela. O frontend descarta sua análise após salvar ou mudar os arquivos.

Na UI, o usuário também pode gravar várias referências pelo microfone, ouvir/remover amostras e misturar gravações com uploads. O navegador produz WebM/Opus, OGG/Opus ou M4A conforme suporte; a API os recebe como qualquer outro arquivo. A gravação só é enviada ao servidor quando o usuário manda analisar, ou quando gera diretamente com uma única referência temporária.

A UI inclui **20 parágrafos em português e 20 em inglês** para leitura opcional. `GET /reading-prompts.json` retorna `{"version":1,"languages":{"pt_br":[{"id":"pt-01","title":"...","text":"..."}],"en_us":[...]}}`. Os IDs identificam sugestões de leitura, não amostras de áudio. Use o idioma do usuário, permita escolher o texto e recomende leitura natural em local silencioso. A UI impede mudar o texto durante a captura. Não trate a sugestão como transcrição comprovada nem atribua uma nota de qualidade por o usuário ter lido esses parágrafos; não há ASR/alinhamento neste fluxo.

Microfone exige contexto seguro e permissão do usuário. Use localhost ou o listener HTTPS, com o certificado local confiado no dispositivo. Um agente HTTP não pode acessar o microfone do usuário sem um cliente/browser autorizado. Não há endpoint que grave secretamente o microfone do servidor.

### 3.1 Upload multipart, recomendado

`POST /v2/voices`, `Content-Type: multipart/form-data`.

Campos:

| Campo | Obrigatório | Significado |
| --- | --- | --- |
| `name` | sim | Nome de 1 a 120 bytes UTF-8 após remover espaços nas pontas, sem caracteres de controle. Não é um caminho de arquivo. |
| `language` | não | `pt_br` (padrão) ou `en_us`. É uma sugestão de idioma, não altera o áudio nem restringe a voz a esse idioma. |
| `audio` | sim | Arquivo de áudio de até 20 MiB. |

```bash
curl --fail-with-body --max-time 180 "$BASE/v2/voices" \
  -F 'name=Narradora principal' \
  -F 'language=pt_br' \
  -F 'audio=@referencia.mp3' \
  -o voice.json
```

FFmpeg decodifica WAV, MP3, OGG, FLAC, AAC, M4A, Opus, WebM e outros formatos aceitos pela instalação. A extensão não basta: os bytes precisam ser áudio válido. Prefira 5–15 segundos de uma pessoa falando, com pouca reverberação, sem música. O runtime usa no máximo 60 segundos; referências maiores são cortadas a esse limite.

### 3.2 Upload JSON/base64

O mesmo endpoint aceita JSON. `speaker_audio_base64` contém os bytes do arquivo em base64 padrão; não envie o caminho local como conteúdo.

```python
import base64, json, urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:1919"  # substitua pela origem real
path = Path("referencia.ogg")
body = {
    "name": "Voz de atendimento",
    "language": "pt_br",
    "speaker_audio_name": path.name,
    "speaker_audio_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
}
request = urllib.request.Request(BASE + "/v2/voices", json.dumps(body).encode(),
    headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(request, timeout=180) as response:
    voice = json.load(response)
print(voice["id"])
```

O corpo JSON total tem limite de 28 MiB; os bytes do áudio decodificados têm limite de 20 MiB. Campos desconhecidos retornam 422.

### 3.3 Resposta e garantias

Somente após decodificar, calcular o embedding na GPU e gravá-lo em disco, retorna **HTTP 201**:

```json
{
  "id": "voice_0123456789abcdef01234567",
  "speaker_embedding_id": "voice_0123456789abcdef01234567",
  "name": "Narradora principal",
  "language": "pt_br",
  "model": "ZONOS3-Mini/ownmect_s2",
  "created_at": 1790000000.0,
  "reference_seconds": 8.5,
  "preprocessing_ms": 1500.0,
  "ready": true,
  "persistent": true,
  "speaker_modes": ["embedding"],
  "embedding_dim": 192
}
```

Valores acima são ilustrativos. O ID gerado é estável; guarde-o. Não é necessário sintetizar uma frase para terminar o pré-processamento. A próxima geração não volta a extrair a voz. Após reiniciar o servidor, o embedding é recarregado do disco, sem exigir o áudio original. Apenas embedding e metadados são armazenados; o áudio original não é mantido na biblioteca.

Nomes precisam ser únicos na biblioteca: espaços nas pontas são removidos e letras ASCII são comparadas sem distinguir maiúsculas/minúsculas. Um conflito responde **409** com `{"detail":"...","voice_id":"voice_..."}`. Não substitua silenciosamente uma voz só porque o nome coincide. Se for a voz desejada, reutilize o ID; se for outro locutor, escolha um nome distinto. Em caso de timeout após criação, liste a biblioteca antes de repetir o POST: a voz pode já ter sido salva.

### 3.4 Promover uma voz temporária ou oficial para a biblioteca

Para esse fluxo de promoção, envie `speaker_embedding_id` em vez de `speaker_audio_base64`. Na criação por análise, use apenas `analysis_id` como fonte; nunca combine fontes diferentes.

```bash
curl --fail-with-body --max-time 180 "$BASE/v2/voices" \
  -H 'Content-Type: application/json' \
  -H 'X-TTS-Session-ID: minha-sessao' \
  -d '{"name":"Minha voz pronta","language":"pt_br","speaker_embedding_id":"spk_ID_REAL"}'
```

O cabeçalho de sessão é necessário se a origem é temporária (`spk_...`). Para uma voz oficial (`default_...`) ou já salva (`voice_...`), ele não é necessário. A promoção força o processamento que ainda estiver pendente e cria um novo ID persistente.

## 4. Gerar voz com uma voz pronta ou oficial

`POST /v2/generate`, `Content-Type: application/json`.

Use `speaker_embedding_id` com o ID retornado pela biblioteca ou pela listagem de speakers. A API identifica a voz pelo ID; `name` e `language` da biblioteca não substituem o campo `language` da requisição de geração.

```bash
VOICE_ID='voice_ID_REAL'
# Monte JSON com uma biblioteca JSON se o texto for dinâmico, evitando escapar aspas à mão.
python - "$VOICE_ID" <<'PY' > request.json
import json, sys
print(json.dumps({
    "text": "Olá! Este áudio utiliza uma voz já pré-processada.",
    "language": "pt_br",
    "speaker_embedding_id": sys.argv[1],
    "speaker_mode": "embedding",
    "decoder": "keep2_plain",
    "speaker_cfg_scale": 1.0,
    "stream": False,
    "format": "wav",
    "max_tokens": 1000,
    "seed": 42,
}, ensure_ascii=False))
PY
curl --fail-with-body --max-time 180 "$BASE/v2/generate" \
  -H 'Content-Type: application/json' --data-binary @request.json -o speech.wav
```

Para inglês, envie `language:"en_us"` e texto em inglês. A mesma voz salva pode ser usada nos dois idiomas.

Campos de geração usados nesta instalação:

| Campo | Tipo/padrão recomendado | Observações |
| --- | --- | --- |
| `text` | string obrigatória | Texto a ser falado. Não envie SSML supondo que seja aceito. |
| `language` | `pt_br` ou `en_us` | Use sempre explicitamente; o padrão nativo é inglês. |
| `speaker_mode` | `embedding` | Sempre explicitar nesta implantação. |
| `speaker_embedding_id` | string | Voz pronta/oficial; temporária exige sessão. Não combinar com outra fonte de voz. |
| `decoder` | `keep2_plain` | Único decoder carregado. |
| `stream` | boolean | `false` com WAV; `true` com PCM. |
| `format` | `wav` ou `pcm` | WAV completo ou float32 LE bruto. |
| `max_tokens` | inteiro, recomendado 1000 | Teto de posições de áudio configurado no servidor. |
| `seed` | inteiro 0..4294967295 ou null | Seed retornada em `X-Seed`; repetições com a mesma entrada/configuração podem ser reproduzíveis, sem promessa de igualdade entre versões/hardwares. |
| `speaker_cfg_scale` | 1.0 | Mantém guidance desligada e usa um slot. |
| `text_normalization` | true | Normalização de números, datas etc. |
| `temperature` | 0.75 | Amostragem. Preserve o padrão, salvo instrução específica. |
| `topk` | 80 | Amostragem. |
| `top_p` | 0.69 | Amostragem. |
| `min_p` | 0 | Amostragem. |
| `stream_decode` | `prefix` | Decodificação progressiva para primeiro áudio rápido. |
| `stream_codebooks` | 1 | Primeiro chunk antecipado; 10 espera todos os codebooks. |
| `stream_codebooks_scope` | `first` | Antecipação só no primeiro chunk, mantendo os demais completos. |

Não envie `voice`, `name` ou `speed` para `/v2/generate`: são campos desconhecidos nesse contrato. O schema nativo rejeita campos desconhecidos com 422. Para voz padrão sem condicionamento, pode omitir o ID, mas prefira selecionar uma voz oficial do idioma para maior previsibilidade.

## 5. Streaming e reprodução com baixa latência

Altere a requisição de geração para `stream:true`, `format:"pcm"`. Leia e processe o corpo incrementalmente; não espere `response.read()` completar para começar a tocar.

```bash
# Partindo de request.json criado acima:
python - <<'PY' > stream-request.json
import json
body = json.load(open('request.json'))
body.update(stream=True, format='pcm', stream_decode='prefix')
print(json.dumps(body))
PY
curl --fail-with-body --no-buffer --max-time 180 "$BASE/v2/generate" \
  -H 'Content-Type: application/json' --data-binary @stream-request.json \
  -o speech.f32le
# Depois do download, ou use um pipe para tocar durante a geração:
ffplay -autoexit -f f32le -ar 44100 -ch_layout mono speech.f32le
# Transformar o PCM bruto em WAV PCM16:
ffmpeg -y -f f32le -ar 44100 -ac 1 -i speech.f32le -c:a pcm_s16le speech.wav
```

Headers relevantes: `X-Audio-Sample-Rate:44100`, `X-Audio-Channels:1`, `X-Audio-Format:float32` em PCM; `X-Seed` e `X-Decoder` identificam seed/decoder. Preserve bytes incompletos entre chunks: uma amostra float32 ocupa 4 bytes, mas um chunk HTTP pode terminar no meio de uma amostra. Não trate os bytes como int16. Verifique fim limpo de resposta e descarte arquivos parciais em erros.

`stream:true` com `format:"wav"` é inválido (400). Para download simples de WAV, use geração buffered, seção 4. Para agente que não precisa tocar áudio ao vivo, WAV costuma ser o fluxo mais simples.

## 6. Clonagem temporária, sem salvar na biblioteca

Use quando o usuário não quiser manter a voz. Escolha uma sessão nova e reutilize-a em todas as chamadas relativas à voz.

1. `POST /v2/speakers`, com `X-TTS-Session-ID` e JSON:

```json
{
  "label": "Referência temporária",
  "speaker_audio_name": "referencia.mp3",
  "speaker_audio_base64": "BASE64_REAL_DOS_BYTES_DO_ARQUIVO"
}
```

2. A resposta HTTP 200 contém `id:"spk_..."`. Isso guarda o áudio decodificado na sessão, **mas ainda não calcula o embedding**.
3. Para deixar a voz temporária pré-processada sem gerar áudio, chame `GET /v2/speakers/ID/embedding`, com o mesmo cabeçalho. Retorna `{"id":"spk_...","embedding":[192 números]}` e força o processamento uma vez.
4. Gere em `/v2/generate` usando esse ID, `speaker_mode:"embedding"`, e o mesmo cabeçalho. As chamadas seguintes reutilizam o embedding.
A referência temporária fica na memória do servidor; não há endpoint de exclusão individual dessa cache nesta instalação. Reiniciar o processo remove as sessões temporárias.

5. Para preservar após reinício ou compartilhar entre clientes/sessões, promova para `/v2/voices`, seção 3.4.

Também é possível clonar em uma única chamada a `/v2/generate`: substitua `speaker_embedding_id` por `speaker_audio_base64` e `speaker_audio_name`. Isso processa a referência em cada chamada inline, portanto não é recomendado para baixa latência em uso recorrente. Não misture múltiplas fontes de voz na mesma requisição.

Um agente pode fornecer embeddings NumPy (`.npy` float32, vetor de 192 elementos compatível com MECT-B2) em `speaker_embedding_base64` e `speaker_embedding_name`, em vez de áudio, em `/v2/speakers` ou `/v2/generate`. Não use base64 de JSON no lugar de um `.npy`. Esse fluxo não cria uma voz persistente por si só: cache em `/v2/speakers` e promova conforme seção 3.4.

## 7. Consultar, renomear ou excluir vozes salvas

- `GET /v2/voices`: biblioteca completa, `{"voices":[...]}`.
- `GET /v2/voices/{id}`: metadados da voz, sem expor o vetor no retorno.
- `PATCH /v2/voices/{id}`: JSON com `name` e/ou `language`; preserva ID e embedding, sem novo processamento. Nome duplicado retorna 409. Corpo vazio ou campos desconhecidos retornam 422.
- `DELETE /v2/voices/{id}`: remove o arquivo e a voz da biblioteca; HTTP 200 `{"deleted":"voice_..."}`. Gerações já iniciadas podem terminar com o embedding que já copiaram. Não exclua uma voz sem instrução do usuário.
- `GET /v2/speakers/{id}/embedding`: retorna o vetor de 192 elementos com arredondamento nativo a seis casas; aceita ID salvo sem sessão. Use como inspeção, não como backup bit a bit.
- `GET /v2/speakers/{id}/preview`: WAV da referência para vozes oficiais/temporárias que têm áudio. Vozes persistentes guardam somente embedding e não têm preview do original; gere uma frase para ouvi-las.

```bash
curl --fail-with-body "$BASE/v2/voices/$VOICE_ID"
curl --fail-with-body -X PATCH "$BASE/v2/voices/$VOICE_ID" \
  -H 'Content-Type: application/json' -d '{"name":"Narradora atualizada"}'
# Somente quando solicitado:
curl --fail-with-body -X DELETE "$BASE/v2/voices/$VOICE_ID"
```

O idioma salvo é sugestivo. Alterar `language` no cadastro não muda o timbre nem o idioma de uma geração que já especificou `language` explicitamente.

## 8. Compatibilidade com OpenAI

`POST /v1/audio/speech` aceita o mesmo modelo local. Campos principais: `model`, `input`, `voice` e `response_format`. Use `voice` com o ID salvo/oficial, além de `speaker_mode` e `language`. Não combine `voice` com outros campos `speaker_*` de fonte de voz.

```python
import json, urllib.request
BASE = "http://127.0.0.1:1919"  # substitua pela origem real
body = {
    "model": "zonos3",
    "input": "Hello from a saved voice.",
    "voice": "voice_ID_REAL",
    "language": "en_us",
    "speaker_mode": "embedding",
    "decoder": "keep2_plain",
    "response_format": "wav",
    "max_tokens": 1000,
}
req = urllib.request.Request(BASE + "/v1/audio/speech", json.dumps(body).encode(),
    headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=180) as response, open("english.wav", "wb") as out:
    while chunk := response.read(65536):
        out.write(chunk)
```

Essa compatibilidade não implica todos os recursos da API hospedada da OpenAI: não envie `speed`, não peça MP3/Opus como formato de resposta, e não suponha PCM16. Formatos de saída disponíveis aqui são WAV e float32 PCM. O campo `model` é obrigatório; o servidor serve só este modelo.

## 8.1 Misturar duas vozes e ajustar condições acústicas

A API nativa permite combinar duas vozes por interpolação esférica dos embeddings. Pode usar IDs oficiais, persistentes ou temporários (estes últimos com sessão). Em `/v2/generate`, omita `speaker_embedding_id`, áudio inline e demais fontes de voz, e envie:

```json
{
  "text": "Uma voz combinada a partir de duas referências.",
  "language": "pt_br",
  "speaker_mode": "embedding",
  "speaker_blend_embedding_id_a": "voice_ID_A_REAL",
  "speaker_blend_embedding_id_b": "voice_ID_B_REAL",
  "speaker_blend_t": 0.5,
  "decoder": "keep2_plain",
  "stream": false,
  "format": "wav",
  "max_tokens": 1000
}
```

`0` seleciona A, `1` seleciona B e `0.5` é uma mistura intermediária. Esse fluxo gera áudio, mas não cadastra automaticamente uma terceira voz na biblioteca. Não combine os campos de blend com outro ID/upload de locutor.

O campo opcional `condition_values` aceita `loudness` em LUFS, `fmax` em Hz e `speaking_rate` em **bytes UTF-8 por segundo**. Não são um multiplicador `speed` nem garantia de duração exata. Os valores são mapeados aos buckets do modelo. `condition_buckets` permite definir os índices diretamente e prevalece por chave; consulte `condition_tokens` em `/v2/capabilities` e não invente índices fora do intervalo. Para geração comum e previsível, omita esses campos e mantenha os padrões. Esses controles acústicos não equivalem a controle livre de emoção ou sotaque.

## 9. Erros e retomada autônoma

| HTTP | Causa provável | Ação |
| --- | --- | --- |
| 200/201 | operação concluída | Parseie JSON ou áudio conforme endpoint/Content-Type. |
| 400 | áudio inválido, voz inexistente em geração, ausência de sessão, combinação inválida, modo não disponível | Leia `detail`, corrija campos ou redescubra IDs; não repita cegamente. |
| 403 | token exigido e ausente/incorreto | Use credencial fornecida pelo operador. Não tente adivinhar token. |
| 404 | rota ou voz salva não encontrada; preview ausente | Atualize a listagem, confira URL e ID. |
| 410 | análise expirada | Reenvie as amostras, refaça a análise e revise a seleção. |
| 429 | outro lote em processamento ou cache de análises cheia | Aguarde ou descarte análises que não serão usadas; não repita em loop rápido. |
| 409 | nome de voz já usado | Leia `voice_id`, reutilize se apropriado ou escolha outro nome. |
| 413 | referência acima de 20 MiB / corpo acima de 28 MiB na biblioteca | Corte ou recomprima o arquivo. |
| 422 | JSON inválido, tipo/campo/idioma incorreto | Corrija payload conforme este documento. |
| 500 | falha no encoder, armazenamento ou runtime | Leia o erro. Reporte ao operador se persistir. |
| timeout/rede | servidor ocupado, interrompido ou inacessível | Cheque `/v2/health`; antes de repetir criação, liste vozes para evitar duplicação. |

Erros usam `{"detail":"mensagem"}`; validação nativa também pode devolver `detail` como lista de objetos `{loc,msg,type}`. Não salve um corpo de erro como `.wav`. Prefira gravar a saída em arquivo temporário e renomeá-lo só após concluir com sucesso. Requisições já em execução podem terminar mesmo se o cliente abortar; abortar o cliente não garante cancelamento imediato da GPU.

### Comportamento da UI ao informar um nome

Com uma única referência e um nome preenchido, a interface usa **Salvar voz e gerar**. Ela chama `/v2/voices`, espera `ready:true` e `persistent:true`, e só então chama `/v2/generate` com o ID persistente. Falha no cadastro bloqueia a geração; não há fallback silencioso para a cache temporária. Com várias referências, continua sendo necessário analisar, revisar os checkboxes e confirmar o perfil.

Isso é uma orquestração da interface: `/v2/generate` por si só continua sem cadastrar perfis, e o campo `name` não é aceito nesse endpoint. Agentes devem executar as etapas de cadastro e geração separadamente. Sem nome, a interface apresenta **Gerar sem salvar** e mantém o comportamento de referência temporária. A sessão da aba é preservada em `sessionStorage` para F5, mas isso não transforma a cache temporária em biblioteca persistente. A seleção de perfil salvo e o idioma ficam como preferências locais; os embeddings continuam no servidor, não no armazenamento do navegador.

## 10. Fluxo autônomo recomendado

1. Determine a origem da API a partir da URL deste documento e verifique `/v2/health`.
2. Determine idioma e texto do pedido; use `pt_br` ou `en_us` explicitamente.
3. Se foi pedido usar uma voz já salva, liste `/v2/voices`, encontre por nome e use seu ID; em caso de ambiguidade, não escolha um locutor arbitrário.
4. Se há vários arquivos, analise em `/v2/voice-analyses`, apresente matriz e similaridades com a média, obtenha a seleção e confirmação do usuário e então cadastre com `analysis_id`. Com um arquivo, também pode usar esse fluxo de revisão. Para cadastro direto já autorizado, crie a voz nomeada em `/v2/voices` e espere `ready:true`. Guarde nome e ID. Se só quer uma clonagem pontual, use sessão temporária.
5. Sem referência nem voz escolhida, selecione uma voz oficial adequada em `/v2/speakers`.
6. Monte uma requisição de geração por frase/parágrafo, com uma única fonte de voz, modo embedding e decoder keep2_plain.
7. Para entregar um arquivo, use WAV buffered; para tocar com baixa latência, leia PCM progressivamente e converta corretamente.
8. Verifique que o resultado é WAV legível/não vazio (ou stream PCM íntegro). A avaliação de timbre, sotaque e semelhança pode exigir escuta; sinal não silencioso não comprova qualidade.
9. Entregue o áudio e, se tiver cadastrado uma voz, informe o nome e ID persistente para futuros pedidos.

## 11. Recursos não disponíveis nesta configuração

Não há ASR/transcrição, edição de fala, alinhamento, referência bruta (`speaker_mode:reference`), guidance com múltiplos slots, decoder `full_mr`, criação por direção/steering nem controle de emoção instalado. Não tente usar esses endpoints/controles supondo suporte. Se uma instalação mudar, consulte `/v2/capabilities` e a documentação local atualizada.

Vozes salvas ficam no diretório `voices/` do host (ou `ZONOS3_VOICES_DIR`). Esse diretório contém embeddings sensíveis: não é versionado. Backup/restauração exige copiar esse diretório com acesso ao host e manter o mesmo encoder/modelo compatível; a API não publica os arquivos internos nem o áudio original. Os endpoints HTTP de geração não armazenam automaticamente as saídas no disco do servidor; o cliente deve salvá-las.

## 12. HTTPS local e confiança no certificado

O listener HTTP padrão usa porta 1919. Quando o operador gera o certificado local, o launcher usa **somente HTTPS na porta 1920** por padrão, com HTTP desligado (dual opcional: `ZONOS3_HTTP_DISABLED=0`), com os mesmos endpoints, biblioteca e processo/modelo em GPU. Não há proxy, Serve ou Funnel. `/tls.json`, quando existe, informa `https_port` e o caminho do certificado público.

A CA local é autoassinada. O certificado público pode ser obtido em `/ca.crt` na origem HTTPS, ou copiado do host em `frontend/ca.crt`; o cliente precisa confiar nessa CA, ou informar seu arquivo explicitamente. Confira sua origem com o operador antes de importar. Nunca peça a chave privada da CA ou do servidor. Para curl:

```bash
# Obtenha a CA pública do operador (frontend/ca.crt no host), por um canal confiável.
# HTTP fica desligado por padrão quando há certificados.
BASE_HTTPS='https://HOST:1920' # substitua pelo host real
curl --cacert zonos-local-ca.crt --fail "$BASE_HTTPS/v2/health"
```

Em Python, use `ssl.create_default_context(cafile="zonos-local-ca.crt")` e passe `context=` ao `urllib.request.urlopen`. Para o CLI, `SSL_CERT_FILE=/caminho/zonos-local-ca.crt python infer.py --url https://HOST:1920 ...` usa a CA sem desativar verificação. Evite `verify=False`/`--insecure` nos fluxos normais; eles só ignoram a verificação e não instalam confiança no navegador para liberar microfone.

No navegador, importe o certificado público em autoridades confiáveis do dispositivo/navegador e abra a origem HTTPS. Depois permita acesso ao microfone. O certificado cobre os IPs/DNS informados na sua criação; usar outro IP/nome pode produzir erro de hostname. Consulte o README do projeto para gerar/renovar o certificado.

## 13. Baixar o mesmo áudio em velocidades diferentes e consultar durações

Esse fluxo **não chama o modelo de voz novamente**. Ele usa o filtro `atempo` do FFmpeg em CPU, preservando o tom, e disponibiliza WAV PCM16 mono a 44100 Hz. O intervalo é **0.5x a 2.0x, em passos de 0.1x**. Não envie `speed` para `/v2/generate` nem `/v1/audio/speech`: esses endpoints de síntese continuam com seu contrato original.

### 13.1 Registrar o áudio já gerado

Depois de receber o WAV da geração, registre seus bytes:

```bash
curl --cacert zonos-local-ca.crt --fail-with-body "$BASE/v2/audio-assets" \
  -F 'audio=@speech.wav' -o audio-asset.json
```

O exemplo assume `BASE` como origem HTTPS e uma CA pública já obtida do operador. Se a CA já estiver confiada no sistema, `--cacert` pode ser omitido.

Alternativa JSON: `{"audio_name":"speech.wav","audio_base64":"BASE64_REAL_DOS_BYTES"}`. Limites: um arquivo de até **20 MiB**, **120 segundos** e corpo de até 28 MiB. Outros formatos decodificáveis pelo FFmpeg também podem ser registrados e são normalizados; um WAV PCM16 mono/44100 válido é preservado byte a byte em 1.0x.

HTTP 201 retorna:

```json
{
  "id":"audio_0123456789abcdef01234567",
  "name":"speech.wav",
  "duration_seconds":3.2,
  "expires_at":1790003600.0,
  "persistent":false,
  "format":"wav",
  "sample_rate":44100,
  "channels":1,
  "speed_min":0.5,
  "speed_max":2.0,
  "speed_step":0.1,
  "durations_url":"/v2/audio-assets/audio_0123456789abcdef01234567/durations",
  "download_url":"/v2/audio-assets/audio_0123456789abcdef01234567/download?speed=1.0"
}
```

IDs e números são ilustrativos. Não confunda `audio_...` com `voice_...`: um identifica uma saída de áudio temporária, o outro um perfil persistente do locutor. Não é necessário usar sessão para esses assets.

### 13.2 Consultar a duração de cada velocidade

`GET /v2/audio-assets/{id}/durations` prepara e retorna **todas as 16 velocidades**. Para consultar apenas algumas, use `?speeds=1.0,1.3,1.5`. Isso reduz trabalho e armazenamento quando você só precisa de um subconjunto.

```bash
AUDIO_ID='audio_ID_REAL'
curl --cacert zonos-local-ca.crt --fail-with-body \
  "$BASE/v2/audio-assets/$AUDIO_ID/durations?speeds=1.0,1.3"
```

Resposta HTTP 200:

```json
{
  "id":"audio_ID_REAL",
  "original_duration_seconds":3.2,
  "expires_at":1790003600.0,
  "duration_is_measured":true,
  "preserves_pitch":true,
  "variants":[
    {"speed":1.0,"duration_seconds":3.2,"download_url":"/v2/audio-assets/audio_ID_REAL/download?speed=1.0"},
    {"speed":1.3,"duration_seconds":2.47,"download_url":"/v2/audio-assets/audio_ID_REAL/download?speed=1.3"}
  ]
}
```

As durações são **medidas no WAV convertido, pelo número de amostras**, e não apenas estimadas por `original/speed`. Pequenas diferenças em relação a essa divisão são normais no time-stretch. Os valores acima são exemplos; use a resposta real. A primeira consulta de uma velocidade produz e guarda a variante; consultas seguintes reaproveitam o arquivo. A duração retornada corresponde ao arquivo disponível para download.

### 13.3 Baixar a variante

`GET /v2/audio-assets/{id}/download?speed=1.3` retorna WAV, com `Content-Disposition: attachment`. `speed` é opcional e vale 1.0 por padrão.

```bash
curl --cacert zonos-local-ca.crt --fail --max-time 180 \
  "$BASE/v2/audio-assets/$AUDIO_ID/download?speed=1.3" -o speech-1.3x.wav.part \
  && mv speech-1.3x.wav.part speech-1.3x.wav
```

Headers `X-Audio-Duration-Seconds` e `X-Audio-Speed` também informam a duração medida e a velocidade. `Content-Type` é `audio/wav`. Não interprete esse endpoint como PCM bruto. Não há opção MP3/Opus de saída nesse fluxo. Velocidade inválida, fora do intervalo, fora do passo de 0.1 ou parâmetros repetidos/desconhecidos retornam 422.

### 13.4 Consultar e descartar o áudio temporário

- `GET /v2/audio-assets/{id}`: metadados do original e URLs, sem criar todas as variantes.
- `DELETE /v2/audio-assets/{id}`: descarta o original e variantes; responde `{"deleted":"audio_..."}`. Um download já iniciado pode terminar normalmente.
- 404/410: ID inexistente ou expirado. Registre novamente o WAV original que você guardou no cliente.
- 429: máximo de 32 assets ativos atingido; descarte assets antigos ou espere expirar.
- 507: cache de arquivos cheia; descarte assets antigos ou consulte menos velocidades.
- 400/413: áudio inválido, vazio ou acima dos limites.

Os assets expiram **uma hora após o registro**, são locais ao processo atual e não constituem histórico permanente de gerações. Reiniciar a API invalida os IDs. O cache usa disco, com teto de 512 MiB por instância, mantém apenas metadados em RAM e produz uma conversão por vez, com uma thread de codec/filtro. Entradas expiradas são limpas em novos registros; cache de processos encerrados é removida na próxima inicialização. Arquivos ficam fora do Git e da raiz pública do frontend.

Na UI, após gerar, o slider escolhe a velocidade **do arquivo para download**. Ao lado do botão aparece a duração medida correspondente. O player acima continua reproduzindo o áudio original. Enquanto converte, o download da velocidade escolhida fica desabilitado; 1.0x continua disponível localmente mesmo se a preparação das outras velocidades falhar. O link **Consultar durações na API** consulta o áudio atual. A UI descarta o asset anterior ao gerar outro áudio ou fechar/recarregar a página; agentes que registram assets diretamente controlam seu descarte pelo DELETE. Os perfis de voz persistentes são independentes desse cache e não são apagados.
