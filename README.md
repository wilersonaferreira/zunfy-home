# zunfy-home

A home de [zunfy.com.br](https://zunfy.com.br).

## O que vai ao ar

Só o diretório `site/`: a página, o estilo, o script e as fontes. O resto do repositório não é publicado.

## A versão no ar

O servidor grava, em cada versão que publica, um `versao.txt` com o commit e a hora da publicação: [zunfy.com.br/versao.txt](https://zunfy.com.br/versao.txt) mostra o que está no ar.

## As checagens

`checagens/checa-home.py` é uma cópia das checagens que o servidor roda antes de publicar. Para conferir o `site/` antes de um commit, da raiz do repositório:

    python3 -I checagens/checa-home.py site

O workflow `checagens` roda o mesmo a cada push na `main` e a cada pull request. O resultado daqui é um aviso antecipado: quem decide é a cópia do servidor.

## As fontes

As fontes de `site/fontes/` vêm do repositório [google/fonts](https://github.com/google/fonts), no commit `e7db6ca603fd4862010383ff17ffd6cc4ffac1c0`, nos arquivos como vêm:
- a Ubuntu, sob a Ubuntu Font Licence 1.0 (`site/fontes/ubuntu/UFL.txt`);
- a Unbounded, sob a SIL Open Font License 1.1 (`site/fontes/unbounded/OFL.txt`).
