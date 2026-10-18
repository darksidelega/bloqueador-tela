# Bloqueador de Tela

Cobre conteúdo sensível com mosaico, em qualquer app. A IA roda 100% local:
nenhuma imagem da tela sai do PC.

## Usar
- **Instalar.bat**: instala tudo, baixa os modelos (~550 MB), liga o início
  com o Windows e abre o Painel. Só precisa rodar uma vez.
- **Painel.bat**: status, liga/desliga das proteções, sensibilidade, senha,
  pausa, lista de sites e log.
- **Ctrl + Alt + Shift + Q**: pausa sem abrir o painel (pede a senha).

Com senha definida, o painel fica travado: mudar ajustes, pausar ou desligar
pede a senha.

## Pastas
| Pasta | O que tem |
|---|---|
| `app/` | código (motor `bloqueador_tela.py`, `guardiao.py`, `painel.py`, `admin.py`) |
| `dados/` | `config.json`, `sites_bloqueados.txt`, senha (só o hash), status |
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
