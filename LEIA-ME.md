# Bot do O Caça Preço 🎯 · versão 2

## O que ele faz
- **11:40 e 18:40** procura ofertas nos mais vendidos das categorias do `config.json` (desconto mínimo de 20%) e te manda as sugestões no privado.
- Você toca em **Abrir produto › Compartilhar › Copiar link** e **responde a sugestão** colando o link. Ele publica no canal **@ocacapreco** com foto, preço "de/por" e o seu link.
- Para cada oferta publicada, te manda o **story**, o **post do feed** e a **legenda do Instagram** prontos.
- Continua aceitando oferta manual (nome, preços e link em linhas separadas, com ou sem foto).

## Atualizar o repositório (quem já tem a versão 1)
1. No repositório, clique em **Add file › Upload files** e arraste: `bot.py`, `ml.py`, `arte.py`, `config.json`, `requirements.txt` e as **pastas** `fonts` e `state`. Clique em **Commit changes**.
2. Abra `.github/workflows/bot.yml`, clique no lápis ✏️, apague tudo, cole o conteúdo do novo `bot.yml` e faça **Commit changes**.
3. **Settings › Actions › General › Workflow permissions**: marque **Read and write permissions** e salve.
4. **Settings › Secrets and variables › Actions**: crie `ML_CLIENT_ID` e `ML_CLIENT_SECRET` com os dados do aplicativo do Mercado Livre.

## Conectar a conta do Mercado Livre (uma vez só)
1. Mande `/conectar` para o bot e rode o workflow (**Actions › Run workflow**).
2. Abra o link que ele mandar e clique em **Permitir**.
3. Você cai numa página do GitHub. Copie o **endereço inteiro** da barra (tem `code=TG-...`) e mande para o bot.
4. **Rode o workflow de novo na hora** (o código vale só 10 minutos). O bot avisa que conectou e já faz a primeira busca.

## Comandos
- `/buscar` busca ofertas na próxima execução (para ser na hora: Run workflow com modo **buscar**)
- `/status` mostra se está conectado e as categorias
- `/diagnostico` testa a conexão com o Mercado Livre passo a passo
- `/modelo` mostra os jeitos de mandar oferta

## Ajustes no config.json
- `desconto_minimo`: % OFF mínimo para sugerir
- `max_sugestoes_por_busca`: quantas sugestões por busca
- `categorias`: código e nome de cada categoria do Mercado Livre

## Segurança
- O token do Mercado Livre fica em `state/ml_token.enc`, **criptografado** com o seu `ML_CLIENT_SECRET`. Quem olhar o repositório não consegue usar.
- Se trocar o Client Secret no Mercado Livre, atualize o segredo no GitHub e mande `/conectar` de novo.
- Fonte Bricolage Grotesque: licença SIL OFL (`fonts/OFL.txt`).
