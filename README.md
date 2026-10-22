# Bloqueador de Tela

Cobre conteúdo sensível com mosaico, em qualquer app. A IA roda 100% local:
nenhuma imagem da tela sai do PC.

## Usar
- **Instalar.bat**: instala tudo, baixa os modelos (~550 MB), liga o início
  com o Windows e abre o Painel. Só precisa rodar uma vez. Na primeira
  abertura o Painel pergunta onde criar os atalhos.
- **Painel** (atalho "Bloqueador de Tela" ou `Painel.bat`): tudo se aplica
  na hora, sem botão salvar.
- **Ctrl + Alt + Shift + Q**: pausa sem abrir o painel.
- **Ctrl + Alt + Shift + B**: bloqueio rápido sem abrir o painel.

## Modo restrito
Como o "Strict mode" do AppBlock: você escolhe o tempo (1 hora a 1 semana)
e até acabar não dá para pausar, desligar proteções, diminuir a
sensibilidade, editar a lista de sites nem desligar o app. Só dá para deixar
mais rígido. Não tem como cancelar antes. Enquanto vale, os arquivos do app
ficam "em uso" e o Windows não deixa apagar a pasta.

Enquanto o modo restrito vale:
- o `config.json` só aceita mudanças que deixam **mais rígido** (vale uma cópia
  assinada guardada ao ativar, `dados/config_restrito.json`); editar à mão e
  reiniciar o app não afrouxa nada, e um config estragado vira o padrão;
- o app e o guardião negam "Finalizar tarefa" ao seu usuário (só um admin com
  privilégio de depuração consegue; aí a Proteção forte reabre em 1 min);
- apagar `restrito.json` e a chave do registro não desliga: os dois regravam;
- adiantar o relógio do Windows estende o restrito pelo mesmo tanto;
- desabilitar em "Aplicativos de inicialização" volta sozinho;
- `admin.py` não remove o bloqueio de sites nem a Proteção forte;
- os arquivos do app e do Python que ele usa ficam "em uso" (não dá para apagar).

Não tem como impedir (precisaria de um serviço do Windows ou de outra conta):
modo de segurança, outra conta, um admin desinstalando o Python, VPN/proxy.

**Bloqueio rápido** (botão vermelho no Painel ou Ctrl + Alt + Shift + B): um
clique, sem perguntas, liga o modo restrito por `bloqueio_rapido_min` (30 min)
e todas as proteções que não pedem admin.

## Lembrete de pausa
Cartão "Bem-estar": depois de 25/45/60/90 min seguidos no PC aparece um aviso
no canto da tela. Ficar 5 min sem mexer no mouse/teclado conta como pausa.

## Vídeos curtos (Shorts, Reels, TikTok)
Cartão "O que bloquear" → "Vídeos curtos". Em vez de cobrir, **remove** os
curtos da página — o que só uma extensão de navegador consegue fazer:

- A extensão fica em `extensao/` (Chrome, Edge, Brave). Instale uma vez pelo
  botão "Instalar" (liga o modo do desenvolvedor → "Carregar sem compactação"
  → pasta `extensao/`).
- Quem liga/desliga é o Painel. A extensão pergunta o ajuste ao app por
  *native messaging* (`app/host_curtos.py`), que lê o config efetivo — então o
  **modo restrito** mantém ligado.
- YouTube: some Shorts (atalho, prateleiras, resultados) e abre `/shorts/`
  como vídeo normal. Instagram: some Reels. TikTok: some o feed "Para Você".
- O endereço fixo da extensão vem da chave pública no `manifest.json`. A chave
  privada (`dados/extensao_chave.pem`) não vai para o git.

## Pastas
| Pasta | O que tem |
|---|---|
| `app/` | código (motor `bloqueador_tela.py`, `guardiao.py`, `painel.py`, `admin.py`, host da extensão `host_curtos.py`) e ícone em `app/recursos/` |
| `extensao/` | extensão de navegador que remove os vídeos curtos |
| `dados/` | `config.json`, `sites_bloqueados.txt`, modo restrito, status |
| `modelos/` | modelos de IA (NudeNet + classificador NSFW) |
| `logs/` | `bloqueador.log` (palavras proibidas aparecem mascaradas, ex: `p**n`) |

## Como liga sozinho
- **Iniciar com o Windows** (padrão, sem admin): ao entrar no PC sobe o
  guardião, que mantém o bloqueador aberto e o reabre em segundos se fechar.
- **Proteção forte** (opcional, admin): tarefa do Windows que reabre o
  guardião em até 1 min se ele for fechado.

## Como decide (dados/config.json)
Para cada imagem/vídeo na tela:

    pontos = NSFW * peso_classificador + Σ (maior score da classe * pesos[classe])

Bloqueia se `pontos >= limiar_bloqueio` (no painel: "Sensibilidade").
- Miniaturas (Google Imagens) são separadas e pontuadas uma a uma.
- Contexto masculino (peito/rosto de homem, nenhum rosto feminino): peitoral
  não conta e não bloqueia, a não ser com genitália visível (lutadores).
- Classificador sozinho, sem sinal de corpo, não bloqueia (`teto_classificador_sozinho`).
- Palavra proibida (título da aba ou texto lido pelo OCR) **não cobre nada
  sozinha**: as imagens daquela janela passam a bloquear com
  `limiar_com_palavra` (0.4) em vez de `limiar_bloqueio`. Página só de texto
  nunca é coberta. Vale para todo navegador visível, mesmo com outra janela
  na frente. Só conta palavra inteira ou plural ("pornomes" não).
- Print: com algo coberto na tela (e até 3 s depois), PrtSc e Win+Shift+S
  são ignorados e os apps de `apps_de_print` são fechados se abrirem. A tela
  congelada da Captura fica numa camada acima de qualquer programa e o
  mosaico é invisível para capturas, então o print sairia sem ele.
- Rolando (roda do mouse, setas, PgDn, espaço) uma janela que está mostrando
  conteúdo sensível: a janela é coberta na hora e só volta depois que a IA
  olhou a tela parada. Alt+Tab, Win+Tab e a prévia da barra de tarefas são
  cobertos se alguma janela aberta mostrou conteúdo sensível (até 10 min).
- O OCR lê só o navegador ativo (lendo um de trás, pegava o texto da janela
  que estava por cima dele).
- Em qualquer mosaico, as abas/botões da janela e a barra de tarefas ficam
  livres para você fechar (`faixa_livre_px`, `liberar_barra_tarefas`), menos
  em tela cheia (F11/vídeo).

## Testar a IA com suas imagens
    python app/testes/teste_pastas.py pasta_adulto pasta_normal

Mostra só nome do arquivo e nota (as imagens não saem do PC) e quais erraram,
sozinhas (como no Fotos) e em grade (como no Google Imagens).

## Gore (futuro)
Veja `app/bloqueador/detectores/gore.py`: é só plugar um classificador ONNX.

## Licença
Freeware sob a licença MIT — veja o arquivo `LICENSE`. Os modelos de IA
são baixados das fontes originais pelo `Instalar.bat`, cada um sob a sua
própria licença.
