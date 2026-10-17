# Bot do O Caça Preço 🎯

Você manda a oferta no privado do bot, ele monta o post e publica no canal **@ocacapreco**.
Roda de graça no GitHub, sem precisar deixar computador ligado.

## Passo 1 – Criar o bot no Telegram
1. No Telegram, abra o **@BotFather** e mande `/newbot`.
2. Nome: `O Caça Preço Bot`. Usuário: algo terminando em `bot`, por ex. `ocacapreco_bot`.
3. O BotFather te dá um **token** (parece `123456:ABC-xyz...`). Guarde e **não mostre para ninguém**.

## Passo 2 – Colocar o bot no canal
1. Abra o canal **@ocacapreco** › Administradores › Adicionar administrador.
2. Procure o seu bot e dê a permissão **Publicar mensagens**.

## Passo 3 – Subir os arquivos no GitHub
1. Crie uma conta grátis em github.com.
2. Clique em **New repository**, nome `bot-ocacapreco`, marque **Public** e crie.
   (Público é o que deixa rodar de graça sem limite. O token fica guardado como segredo, ninguém vê.)
3. Clique em **uploading an existing file** e arraste o `bot.py`, o `LEIA-ME.md` **e a pasta `.github`** inteira. Clique em **Commit changes**.
   - Se a pasta `.github` não aparecer no seu computador (ela fica oculta), crie pelo site: **Add file › Create new file**, digite o nome `.github/workflows/bot.yml` e cole o conteúdo do arquivo `bot.yml`.

## Passo 4 – Guardar o token como segredo
1. No repositório: **Settings › Secrets and variables › Actions › New repository secret**.
2. Nome `TELEGRAM_TOKEN`, valor = o token do BotFather. Salve.

## Passo 5 – Descobrir seu ID
1. No Telegram, abra o seu bot e mande `/start`.
2. No GitHub, vá em **Actions › Bot O Caça Preço › Run workflow**.
3. Em até 1 minuto o bot te responde com **seu ID** (um número).
4. Crie outro segredo: nome `OWNER_ID`, valor = esse número.

Pronto! Só você consegue publicar pelo bot.

## Como usar no dia a dia
Mande no privado do bot (uma informação por linha):

```
Fone Bluetooth JBL Tune 520
199,90
129,90
Frete grátis Full
https://meli.la/SEU-LINK
```

- 1ª linha = nome · números = preços (o maior vira o "De") · link = seu link de afiliado · outras linhas = vantagens
- Pode mandar uma **foto** (print do produto) com esse texto na legenda.
- Comece com **teste** para ver a prévia sem publicar.
- O bot confere as mensagens a cada ~10 minutos (o GitHub às vezes atrasa um pouco). Para publicar na hora: **Actions › Run workflow**.

## Bom saber
- Se o repositório ficar 60 dias sem nenhuma alteração, o GitHub pausa o agendamento e manda um e-mail. É só entrar em Actions e clicar para reativar.
- Para mudar o rodapé ou a hashtag, edite as linhas `RODAPE` e `HASHTAG` no começo do `bot.py`.
