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

## Modo restrito
Como o "Strict mode" do AppBlock: você escolhe o tempo (1 hora a 1 semana)
e até acabar não dá para pausar, desligar proteções, diminuir a
sensibilidade, editar a lista de sites nem desligar o app. Só dá para deixar
mais rígido. Não tem como cancelar antes.

## Pastas
| Pasta | O que tem |
|---|---|
| `app/` | código (motor `bloqueador_tela.py`, `guardiao.py`, `painel.py`, `admin.py`) e ícone em `app/recursos/` |
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
- Título da aba e OCR só valem quando a janela ativa é um navegador.
- No blur de tela inteira, as abas/botões da janela e a barra de tarefas
  ficam livres para você fechar (`faixa_livre_px`, `liberar_barra_tarefas`).

## Gore (futuro)
Veja `app/bloqueador/detectores/gore.py`: é só plugar um classificador ONNX.
