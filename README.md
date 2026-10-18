# Bloqueador de Tela

Cobre conteúdo sensível com mosaico, em qualquer app. A IA roda 100% local:
nenhuma imagem da tela sai do PC.

## Instalar e usar
1. `1_instalar.bat`: cria o `.venv`, instala tudo e baixa os modelos (~550 MB).
2. `2_iniciar.bat`: inicia o bloqueador (`2_iniciar_com_log.bat` mostra o DEBUG).
3. `4_ativar_protecao.bat` (admin): define a senha, inicia com o Windows,
   reinicia sozinho se for fechado e bloqueia os sites.
4. `Ctrl+Alt+Shift+Q`: pede a senha e pausa por N minutos.
5. `5_desativar_protecao.bat` (pede a senha): remove tudo.

Log: `logs/bloqueador.log`.

## Como decide (config.json)
Para cada imagem/vídeo na tela:

    pontos = NSFW * peso_classificador + Σ (maior score da classe * pesos[classe])

Bloqueia se `pontos >= limiar_bloqueio` (1.0).
- `NSFW` = classificador da imagem inteira (pega mão cobrindo, sem rosto).
- Classes = NudeNet 640m (partes do corpo), rodando em fatias para achar miniaturas.
- `MALE_BREAST_EXPOSED` tem peso negativo (lutador sem camisa).
- Peito feminino sozinho fica limitado a `teto_peito_sozinho` (< 1, então não bloqueia sozinho).
- Se o classificador tem certeza que é normal (`< veto_classificador`), o NudeNet vale `fator_veto`.

Bloqueando pouco: baixe `limiar_bloqueio` ou suba o peso da classe que aparece no log.
Falso positivo: faça o contrário com a classe que aparece no log.

## Outras camadas
- `sites_bloqueados.txt`: domínios bloqueados pelo arquivo hosts (`3_bloquear_sites.bat`).
- `forcar_safesearch`: Google/Bing/DuckDuckGo sempre com SafeSearch.
- `palavras_titulo` e `ocr.palavras`: palavras no título da aba ou visíveis na tela.

## Gore (futuro)
Veja `bloqueador/detectores/gore.py`: é só plugar um classificador ONNX.
