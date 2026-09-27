# Tier list resenhuda

Site para criar várias tier lists. Cada uma tem cinco categorias (S, A, B, C e D), e sua própria biblioteca de fotos. Usa HTML/CSS, JavaScript e um servidor local Python com SQLite.

## Como abrir

É necessário Python 3.10 ou superior. Não precisa instalar pacotes.

Abra um terminal na pasta do projeto e execute:

```powershell
python server.py
```

Se o Windows não reconhecer `python`, use `py server.py`.

Acesse **http://127.0.0.1:8006** no navegador e deixe o terminal aberto enquanto usa o site. Para encerrar, pressione `Ctrl+C` no terminal. Não abra o HTML diretamente nem use o Live Server: o salvamento precisa do servidor Python.

Se a porta estiver ocupada, use `python server.py --port 8001` e abra http://127.0.0.1:8001.

## Como usar

- **Criar uma tier list:** digite um nome em "Minhas tier lists" e clique em **Criar tier list**. Use os links logo abaixo para alternar entre as listas. Cada lista também possui um endereço próprio, como `/?board=2`.
- **Excluir uma tier list criada:** clique na lixeira ao lado do nome e confirme a exclusão. As fotos que pertencem a ela também são removidas. A primeira lista permanece disponível.
- **Importar fotos:** escolha uma ou várias imagens do computador.
- **Importar pasta:** escolha uma pasta de fotos; arquivos incompatíveis são ignorados. O navegador pode pedir confirmação para ler a pasta.
- **Caixa vazia:** clique para escolher uma foto diretamente do computador.
- **Organizar:** arraste uma foto para uma caixa ou clique na foto e depois na caixa de destino. Essa segunda opção também funciona por toque e teclado.
- **Trocar:** mover para uma caixa ocupada troca as fotos de lugar; se a nova foto veio da biblioteca, a anterior volta para lá.
- **Retirar do ranking:** use o botão × sobre a foto ou arraste de volta para a área de fotos disponíveis. A foto continua salva.
- **Excluir foto:** clique na lixeira da imagem, na caixa ou na biblioteca. Após confirmar, a foto é apagada definitivamente da tier list e do SQLite. Essa ação não pode ser desfeita.
- **Soltar arquivos:** arraste imagens do computador para uma caixa ou para a biblioteca. Se soltar várias em uma caixa, a primeira ocupa a caixa e as demais ficam disponíveis.

Formatos aceitos: PNG, JPEG, WebP e GIF, até 10 MB por foto. Arquivos ZIP não são importados; extraia a pasta antes. Em telas pequenas, deslize horizontalmente cada categoria para acessar todas as oito caixas.

## Salvamento

As listas, imagens completas (BLOB), nomes e posições ficam em **`data/tierlist.sqlite3`**, criado automaticamente na primeira execução. O salvamento acontece após cada criação, importação ou movimento; a mensagem na página informa o resultado. Recarregar a página ou reiniciar o servidor recupera os rankings. Ao atualizar um banco criado pela versão anterior, as fotos existentes são mantidas em "Minha tier list".

Para fazer backup, encerre o servidor e copie `data/tierlist.sqlite3`. Para restaurar, com o servidor parado, coloque a cópia nesse mesmo caminho. Não apague o banco se quiser manter suas fotos.

O servidor é destinado ao uso local, escutando apenas em `127.0.0.1`. As listas do mesmo banco são compartilhadas pelas abas que acessam esse servidor; recarregue a página para ver alterações feitas em outra aba.

## Arquivos

- `index.html`: estrutura da página.
- `style.css`: aparência e adaptação a telas pequenas.
- `app.js`: importação, seleção, arrastar/soltar e comunicação com o servidor.
- `server.py`: servidor HTTP, validações e persistência SQLite.
- `tests/test_server.py`: testes de integração.

Execute os testes com `python -m unittest discover -s tests -v`.
