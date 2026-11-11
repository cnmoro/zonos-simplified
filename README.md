# Zonos Simplified

Geração de voz em **inglês e português**, clonagem a partir de áudio e biblioteca de **vozes nomeadas já pré-processadas**. API HTTP e frontend simples no mesmo processo nativo C++/ggml, usando CUDA e ZONOS3-Mini.

Sem servidor Python de inferência, sem proxy e sem segunda cópia do modelo. O cliente Python usa somente a biblioteca padrão.

## Instalar

Requer Linux, GPU NVIDIA com driver funcional, toolkit CUDA (`nvcc`), compiladores C/C++, CMake >= 3.24, Rust/Cargo, Git, FFmpeg e Python >= 3.10.

Confira a GPU antes de instalar:

```bash
nvidia-smi
nvcc --version
```

```bash
git clone https://github.com/cnmoro/zonos-simplified.git
cd zonos-simplified
python -m venv .venv
.venv/bin/pip install -r requirements-setup.txt
.venv/bin/python scripts/setup.py
```

O setup:

1. Baixa `zonos3-ptq.gguf`, `zac-keep2.gguf`, `spk-encoder.gguf` e as vozes oficiais EN/PT para `models/gguf/`, aproximadamente 1,2 GB.
2. Clona o runtime oficial e os submódulos necessários em `vendor/`.
3. Aplica a extensão nativa deste projeto para vozes persistentes e documentação Markdown.
4. Compila em Release/CUDA para a arquitetura da GPU local, gerando `build/cuda/zonos3-server`.

`install-lock.json` fixa as revisões do modelo/runtime usadas por padrão. O arquivo não contém credenciais nem dados de vozes. `--runtime-revision` e `--model-revision` permitem escolher outras revisões, mas mudanças upstream podem exigir adaptar os patches. Não edite `vendor/` diretamente: a extensão mantida pelo projeto fica em `native/saved-voices.inc` e é aplicada por `scripts/patch_runtime.py`.

A compilação inicial pode demorar vários minutos. O padrão de quatro jobs limita a RAM durante o build; altere com `--jobs`. Em instalações com CUDA 12.0, o setup prefere GCC 12 quando disponível; `--cuda-host-compiler /caminho/para/g++` permite ajustar essa escolha. Não é preciso instalar PyTorch para servir ou inferir.

## Subir a API e o frontend

```bash
bash scripts/serve.sh
```

O bind padrão é **`0.0.0.0:1919`**. Abra:

- No próprio host: `http://127.0.0.1:1919`.
- Na LAN ou Tailscale: `http://IP_DO_HOST:1919`.
- Documentação para agentes: `http://IP_DO_HOST:1919/agents.md`.

Não há Funnel, Tailscale Serve ou proxy configurado. Para descobrir o IP Tailscale do host, use `tailscale ip -4`. O dispositivo cliente deve ter acesso ao host/porta conforme as regras de rede e firewall.

Para manter em background:

```bash
mkdir -p outputs
nohup bash scripts/serve.sh > outputs/server.log 2>&1 &
echo $! > outputs/server.pid
```

Consultar e encerrar:

```bash
curl --fail-with-body http://127.0.0.1:1919/v2/health
cat outputs/server.pid
kill "$(cat outputs/server.pid)"
```

O processo em background não é um serviço de inicialização automática após reboot. Para reiniciar, execute novamente o launcher. Leia `outputs/server.log` se a GPU, os pesos ou a porta não estiverem disponíveis.

Variáveis de ambiente:

| Variável | Padrão | Uso |
| --- | --- | --- |
| `ZONOS3_HOST` | `0.0.0.0` | Endereço de bind; use `127.0.0.1` para acesso só local. |
| `ZONOS3_PORT` | `1919` | Porta HTTP. |
| `ZONOS3_VOICES_DIR` | `<projeto>/voices` | Diretório persistente das vozes do usuário. |
| `ZONOS3_MAX_TOKENS` | `1000` | Teto de posições de áudio por geração. |
| `ZONOS3_ACCESS_TOKEN` | ausente | Exige bearer token/cookie em todas as rotas, quando configurado. |

Argumentos extras do launcher são encaminhados ao servidor nativo.

**Acesso de rede:** o padrão permite que clientes com acesso à porta usem a API, inclusive a biblioteca de vozes. `X-TTS-Session-ID` organiza vozes temporárias, mas não é autenticação. Para acesso controlado, use firewall/tailnet e, se necessário, `ZONOS3_ACCESS_TOKEN`. Nesse caso, agentes usam `Authorization: Bearer TOKEN`; no navegador, o runtime aceita o cookie definido por `/?access_token=TOKEN`. Não coloque tokens no Git, em logs ou em links compartilhados. Para tráfego fora de rede confiável, providencie TLS na sua infraestrutura.

## Salvar uma voz pronta pelo frontend

1. Abra a interface.
2. Escolha inglês ou português.
3. Selecione uma referência de áudio e preencha **Nome para guardar esta voz**.
4. Clique em **Salvar voz pronta**.
5. Espere a mensagem **Voz salva e pronta para usar**. A API só confirma depois de calcular e gravar o embedding.
6. A voz passa a aparecer em **Minhas vozes prontas**. Escolha-a para gerar sem reenviar áudio ou extrair novamente o locutor.

O nome/ID e o embedding sobrevivem a recarregamentos da página e reinicializações da API. Não é preciso gerar uma frase para concluir o pré-processamento. A mesma voz pode ser usada em ambos os idiomas.

Também é possível gerar diretamente com um arquivo de referência sem salvá-lo: nesse caso, o frontend usa uma voz temporária e reaproveita a cache enquanto a página/sessão estiver ativa.

Referências aceitas: WAV, MP3, OGG, FLAC, M4A, AAC, Opus e outros formatos decodificáveis pelo FFmpeg. Prefira **5–15 segundos** de fala limpa, uma pessoa e sem música. Uploads para a biblioteca têm limite de **20 MiB**; o runtime considera até 60 segundos. Os nomes têm limite de 120 bytes UTF-8 e precisam ser únicos. Nomes não são usados como caminhos de arquivo.

## API e guia para agentes

Envie a URL **`/agents.md`** a um agente de IA. O documento é servido como `text/markdown` e inclui descoberta, parâmetros, tipos de áudio, nomes/IDs, sessões, pré-processamento, persistência, geração, streaming, compatibilidade OpenAI, erros e exemplos executáveis. Também está disponível em [frontend/agents.md](frontend/agents.md).

Principais rotas:

| Rota | Função |
| --- | --- |
| `GET /v2/health` | Disponibilidade. |
| `GET /v2/capabilities` | Capacidades carregadas. |
| `GET /v2/speakers` | Vozes oficiais, vozes salvas e vozes temporárias da sessão. |
| `GET /v2/voices` | Biblioteca persistente do usuário. |
| `POST /v2/voices` | Upload + pré-processamento + gravação da voz nomeada. |
| `GET /v2/voices/{id}` | Metadados e confirmação `ready`. |
| `PATCH /v2/voices/{id}` | Renomear/alterar idioma sugerido sem recalcular o embedding. |
| `DELETE /v2/voices/{id}` | Excluir da biblioteca. |
| `POST /v2/speakers` | Criar voz temporária na sessão. |
| `GET /v2/speakers/{id}/embedding` | Calcular/consultar o embedding de uma voz. |
| `POST /v2/generate` | Geração nativa, WAV ou PCM progressivo. |
| `POST /v1/audio/speech` | Geração compatível com OpenAI. |
| `GET /agents.md` | Guia completo para uso autônomo. |

Salvar por upload multipart:

```bash
BASE='http://127.0.0.1:1919'
curl --fail-with-body --max-time 180 "$BASE/v2/voices" \
  -F 'name=Narradora principal' \
  -F 'language=pt_br' \
  -F 'audio=@referencia.mp3'
```

A resposta HTTP 201 contém `id: "voice_..."`, `ready: true`, `persistent: true` e `preprocessing_ms`. Use o ID retornado nas próximas gerações, sem cabeçalho de sessão. Nomes duplicados retornam 409, com o ID existente; não sobrescrevem a voz.

Geração com voz salva:

```bash
# Troque voice_ID_REAL pelo id retornado acima.
curl --fail-with-body --max-time 180 "$BASE/v2/generate" \
  -H 'Content-Type: application/json' \
  -d '{"text":"Olá! Esta voz já estava pronta.","language":"pt_br","speaker_embedding_id":"voice_ID_REAL","speaker_mode":"embedding","decoder":"keep2_plain","stream":false,"format":"wav","max_tokens":1000}' \
  -o outputs/voz.wav
```

Para inglês, use `language:"en_us"` e texto em inglês. **Sempre envie `speaker_mode:"embedding"` nesta configuração.** O modo de referência bruta requer encoders adicionais que não são instalados aqui.

`stream:true, format:"pcm"` retorna **float32 little-endian, mono, 44100 Hz**, sem cabeçalho; não é PCM16. WAV exige `stream:false`. O frontend reproduz chunks durante a geração e disponibiliza um WAV ao terminar.

## Cliente Python

Com a API ativa:

```bash
python infer.py --language en --text "Hello! How are you?" --output outputs/english.wav
python infer.py --language pt --text "Olá! Como você está?" --output outputs/portugues.wav
python infer.py --language pt --text "Clonagem pontual." --reference referencia.ogg --output outputs/clone.wav
python infer.py --language pt --text "Reutilizando uma voz salva." --voice voice_ID_REAL --output outputs/saved.wav
```

`--url http://IP_DO_HOST:1919` permite uso remoto. Por padrão, o cliente converte o streaming PCM para WAV incrementalmente, sem acumular todo o áudio em memória. `--buffered` pede WAV pronto. O arquivo final só substitui a saída após uma resposta completa.

O JSON de retorno inclui duração, tempo de geração, primeiro áudio e RTF (tempo/duração; menor é melhor). Na clonagem temporária, a primeira geração inclui a extração lazy do embedding; a voz persistente já passou por essa etapa no cadastro. O cliente também retorna ID/sessão de vozes temporárias para reutilização com `--voice ID --session SESSION`.

Se houver token configurado, use os exemplos HTTP autenticados de `/agents.md`; o CLI simples não tem opção específica de token.

## Memória e latência

Configuração escolhida para reduzir consumo:

- Backbone oficial GGUF com especialistas Q4 e mixers Q8, aproximadamente 0,66 GB em disco.
- Apenas decoder reduzido `keep2_plain` em GPU, sem carregar `full_mr`.
- Um slot (`--batch 1`) e uma lane de decoder (`--zac-threads 1`), guidance desligada.
- Embeddings prontos em vez de prefixos longos de referência bruta.
- Sem ASR, edição de fala, steering ou encoders grandes de referência bruta instalados.
- Somente metadados e o vetor de 192 dimensões por voz persistente: não retém PCM nem o arquivo original.

Em uma RTX 2060 SUPER de 8 GB, os testes de geração curta aquecida com vozes prontas observaram primeiro áudio em cerca de **30 ms**, RTF próximo de **0,07–0,09**, aproximadamente **1,3 GiB de VRAM** antes de usar o speaker encoder e **1,6–1,7 GiB** após clonagem; RAM RSS em torno de **0,5 GiB**. Pré-processar uma nova referência levou cerca de **1,5–2,2 s**. São medições de exemplos curtos, não garantias para outros textos, versões, GPUs ou concorrências.

Mil posições de áudio correspondem aproximadamente a um minuto, já descontados os atrasos dos codebooks. Divida textos longos; atingir o teto pode cortar a fala. A API nativa aceita opções além das expostas na interface: consulte o guia local e o schema upstream. Não suponha que endpoints opcionais estejam disponíveis.

## Testes e validação

Testes locais de cliente, PCM/WAV e erros:

```bash
python -m unittest discover -s tests -v
node tests/audio.test.mjs
bash -n scripts/serve.sh
python -m compileall -q infer.py scripts tests
```

Os testes reais de biblioteca são opt-in e precisam da API/modelo em execução:

```bash
ZONOS_LIVE_URL=http://127.0.0.1:1919 python -m unittest discover -s tests -v
python scripts/validate.py --reference models/gguf/voices/English/Jett_en-energetic_M_1.wav
```

O teste de validação gera EN/PT, WAV buffered, streaming e clonagem com WAV/MP3/OGG, salva os resultados em `outputs/validation/` e mede latência/RTF. `--server-pid PID` adiciona amostras de RAM RSS; a medição de VRAM é do dispositivo inteiro e inclui outros processos, podendo perder picos muito breves.

Testes reais de interface no Chromium:

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python scripts/browser_smoke.py --reference outputs/validation/reference.mp3
.venv/bin/python scripts/named_voice_smoke.py --reference outputs/validation/reference.mp3
```

Os scripts do navegador também aceitam `--url`. Verificam geração nos dois idiomas, upload/cache, cadastro de voz nomeada, reutilização após recarregar a página, ausência de novo upload nas gerações, WAV baixável e layout desktop/mobile. Cada voz criada pelos testes de biblioteca/interface é excluída ao final; use uma instância de teste se não quiser compartilhar recursos com usuários ativos.

A persistência também foi validada com reinício real do processo: a voz foi restaurada, gerou sem sessão e sem carregar novamente o speaker encoder. Testes de fluxo e sinal não substituem avaliação humana de pronúncia, timbre ou semelhança.

## Dados locais e Git

Não são versionados: pesos, runtime baixado, builds, biblioteca `voices/`, áudio de referência, áudio gerado, embeddings, relatórios, capturas, logs, PIDs, `.env`, chaves ou configurações de agentes/cloud.

As vozes persistentes ficam em `voices/` (ou `ZONOS3_VOICES_DIR`). Para backup/restauração, copie esse diretório com a API parada e mantenha encoder/modelo compatível. Ele contém dados de voz e deve ser tratado como dado sensível. Apagar `voices/` remove a biblioteca. Atualizar o código não deve apagar esse diretório.

## Licenças e fontes

Código deste projeto e runtime oficial: MIT; veja [LICENSE](LICENSE) e [NOTICE](NOTICE). Pesos do modelo: Apache-2.0 conforme a [model card](https://huggingface.co/Zyphra/ZONOS3-Mini). Dependências e submódulos mantêm suas respectivas licenças.

- [Runtime oficial ZONOS3-Mini](https://github.com/Zyphra/ZONOS3-Mini)
- [Backend ggml/CUDA](https://github.com/Zyphra/ZONOS3-Mini/tree/main/servers/ggml)
- [Contrato HTTP upstream](https://github.com/Zyphra/ZONOS3-Mini/blob/main/docs/api.md)
