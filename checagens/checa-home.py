#!/usr/bin/env python3
"""As checagens da home de zunfy.com.br (design D5 do home-marketing; capability home-publishing, requisito «O conteúdo
publicado obedece às regras da home»). Um programa só, biblioteca padrão, sem rede, rodado com `python3 -I -B`.

A cópia que VALE é a do servidor: o publicador a roda antes de publicar (publicador.py, ao lado). A do repositório da home é
cópia byte a byte desta, insumo para quem edita a home, e a conferência compara o resumo das duas (design D12).

Uso:
  python3 -I -B checa-home.py <diretório do pacote>     o modo do pacote — o servidor e o CI do repositório da home
  python3 -I -B checa-home.py --pagina <arquivo .html>   o modo da página sozinha — a conferência de fora, sem a regra
                                                         dos links internos e sem a dos arquivos

Cada reprovação sai numa linha «REPROVA [regra] arquivo:linha: motivo», e a última linha resume. Código de saída: 0, passa;
1, reprova; 2, erro de uso.

As regras são as oito do requisito, com o número de lá: 1 login · 2 local · 3 terceiros · 4 contato · 5 csp · 6 cookie ·
7 marca · 8 arquivos.

⚠️ LIMITE DECLARADO (a spec): as regras 3 a 6 leem o TEXTO dos arquivos. Script escrito para escondê-las passa por elas; a
CSP da borda é a camada que segura o que elas não veem, e a conferência do Wilerson, a outra. ⚠️ Elas também não leem
âncora: um link para «#x» sem o «id» na página passa (design D20).
"""
import bisect
import html.parser
import os
import posixpath
import re
import sys
from collections import namedtuple
from urllib.parse import unquote, urlsplit

APP = "https://app.zunfy.com.br"
APP_HOST = "app.zunfy.com.br"

TIPOS = {".html", ".css", ".js", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".avif", ".ico", ".ttf", ".txt"}
TEXTO = {".html", ".css", ".js", ".svg", ".txt"}
COMPONENTE = re.compile(r"[A-Za-z0-9._\-\[\]]+")  # as fontes vêm com maiúsculas e colchetes: «Unbounded[wght].ttf»
MAX_ARQUIVO = 2 * 1024 * 1024
MAX_TOTAL = 10 * 1024 * 1024
MAX_ARQUIVOS = 500
MAX_NIVEIS = 8

# Toda expressão aqui é LINEAR: nenhum quantificador volta atrás sobre outro. O «\b[\w-]+\.local\b» do protótipo era
# quadrático numa linha longa de «a-a-a-…» (lente 1, achado 13, da revisão do propose); o «.local» se acha pelo ponto, com o
# caractere de antes olhado para trás.
LOCAL = re.compile(rb"localhost|127\.0\.0\.1|10\.0\.2\.2|0\.0\.0\.0|file://|(?<=[\w-])\.local\b", re.I)
MARCA = re.compile(r"ticket", re.I)
CONTATO = re.compile(r"\bmailto:|\btel:", re.I)
JAVASCRIPT = re.compile(r"javascript:", re.I)
ADIADAS = re.compile(r"privacidade|privacy|\btermos?\b|\bterms\b", re.I)
LOGIN = re.compile(r"\blog\s*-?\s*in\b|\bportal\b|\bj[aá]\s+(?:sou|é|e)\s+cliente\b", re.I)
APP_URL = re.compile(r"\bappUrl\s*[:=]\s*([\"'`])([^\"'`\n]*)\1")

# No script (arquivos .js): o que a regra de cada número proíbe, por texto.
JS = (
    ("3 terceiros", re.compile(r"\blocation\b"), "navegação por script (location)"),
    ("3 terceiros", re.compile(r"\bopen\s*\("), "navegação por script (open)"),
    ("4 contato", re.compile(r"\b(?:fetch|XMLHttpRequest|sendBeacon|WebSocket|EventSource)\b"), "envio por script"),
    ("5 csp", re.compile(r"\beval\s*\("), "eval"),
    ("5 csp", re.compile(r"\bFunction\s*\("), "Function (new Function)"),
    ("5 csp", re.compile(r"\bset(?:Timeout|Interval)\s*\(\s*[\"'`]"), "temporizador com texto"),
    ("5 csp", re.compile(r"\bsetAttribute\s*\(\s*[\"'`]\s*(?:on|style\b)", re.I), "setAttribute de on…/style"),
    ("5 csp", re.compile(r"\bserviceWorker\b"), "registro de service worker"),
    ("5 csp", re.compile(r"\b(?:Shared)?Worker\s*\("), "worker (a CSP o bloqueia)"),
    ("6 cookie", re.compile(r"\bdocument\s*\.\s*cookie\b|\bcookieStore\b"), "cookie por script"),
)
URL_NO_SCRIPT = re.compile(r"\b(?:https?|wss?|ftp)://[^\s\"'`<>/)\\]*", re.I)
REDE_NO_SCRIPT = re.compile(r"[\"'`]//(?=[A-Za-z0-9\[])")
MAX_POR_REGRA = 20  # por regra e por arquivo; o resto sai numa linha só, para um pacote hostil não inundar o registro

# No HTML e no SVG: as tags proibidas pela regra 5, e os atributos que carregam recurso (regra 3) ou navegam.
TAGS_PROIBIDAS = {"base", "iframe", "object", "embed"}
CARGA = {
    "link": ("href",), "script": ("src", "href", "xlink:href"), "img": ("src", "srcset"), "source": ("src", "srcset"),
    "video": ("src", "poster"), "audio": ("src",), "track": ("src",), "input": ("src",), "iframe": ("src",),
    "embed": ("src",), "object": ("data",), "image": ("href", "xlink:href"), "use": ("href", "xlink:href"),
    "feimage": ("href", "xlink:href"),
}
NAVEGA = {"a": ("href", "xlink:href"), "area": ("href",)}
IMAGEM = {("img", "src"), ("img", "srcset"), ("source", "srcset"), ("source", "src"), ("input", "src"),
          ("video", "poster"), ("image", "href"), ("image", "xlink:href"), ("feimage", "href"), ("feimage", "xlink:href")}

Reprovacao = namedtuple("Reprovacao", "regra onde motivo")


class Linhas:
    """O número da linha de uma posição do texto (ou dos bytes), por busca binária nos inícios de linha."""

    def __init__(self, texto):
        quebra = b"\n" if isinstance(texto, bytes) else "\n"
        self.inicios = [0] + [m.end() for m in re.finditer(re.escape(quebra), texto)]

    def de(self, pos):
        return bisect.bisect_right(self.inicios, pos)


def classifica(url):
    """O tipo de uma referência, como o navegador a lê: tabulação e quebra de linha somem, e a barra invertida é barra.
    Devolve («vazio»|«fragmento»|«relativo»|«rede»|«esquema», esquema)."""
    u = re.sub(r"[\t\n\r]", "", url).strip(" \x00\x0b\x0c")
    if not u:
        return "vazio", ""
    if u.startswith("#"):
        return "fragmento", ""
    m = re.match(r"([A-Za-z][A-Za-z0-9+.\-]*):", u)
    if m:
        return "esquema", m.group(1).lower()
    if u.replace("\\", "/").startswith("//"):
        return "rede", ""
    return "relativo", ""


def eh_app(url):
    """A navegação para fora só vale para o app: https, o host do app, sem porta nem usuário."""
    try:
        p = urlsplit(re.sub(r"[\t\n\r]", "", url).strip())
        return p.scheme.lower() == "https" and p.hostname == APP_HOST and p.port in (None, 443) and not p.username
    except ValueError:
        return False


def eh_imagem_data(url):
    return re.sub(r"[\t\n\r\s]", "", url).lower().startswith("data:image/")


def candidatos_srcset(valor):
    """As URLs de um srcset, como o navegador as separa: a URL é a sequência sem espaço, e a vírgula final a encerra."""
    urls, i, n = [], 0, len(valor)
    while i < n:
        while i < n and (valor[i].isspace() or valor[i] == ","):
            i += 1
        j = i
        while j < n and not valor[j].isspace():
            j += 1
        url = valor[i:j]
        if url.endswith(","):
            url = url.rstrip(",")
            i = j
        else:
            i = j
            profundidade = 0
            while i < n and not (valor[i] == "," and profundidade == 0):
                profundidade += {"(": 1, ")": -1}.get(valor[i], 0)
                i += 1
        if url:
            urls.append(url)
    return urls


class Leitor(html.parser.HTMLParser):
    """Lê HTML e SVG: as tags com os atributos e a linha, o texto de cada <a>, e o que vem embutido."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []        # (linha, tag, atributos)
        self.links = []       # (linha, atributos, texto visível) de cada <a>
        self._abertos = []

    def handle_starttag(self, tag, attrs):
        linha = self.getpos()[0]
        a = {k: (v if v is not None else "") for k, v in attrs}
        self.tags.append((linha, tag, a))
        if tag == "a":
            self._abertos.append([linha, a, []])

    def handle_startendtag(self, tag, attrs):
        linha = self.getpos()[0]
        self.tags.append((linha, tag, {k: (v if v is not None else "") for k, v in attrs}))

    def handle_data(self, data):
        for aberto in self._abertos:
            aberto[2].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._abertos:
            linha, a, texto = self._abertos.pop()
            self.links.append((linha, a, " ".join("".join(texto).split())))

    def close(self):
        super().close()
        while self._abertos:
            linha, a, texto = self._abertos.pop()
            self.links.append((linha, a, " ".join("".join(texto).split())))


class Checagem:
    def __init__(self, raiz=None):
        self.raiz = raiz            # None no modo da página sozinha: sem links internos
        self.arquivos = set()       # caminhos relativos dos arquivos do pacote
        self.reprovacoes = []
        self._contas = {}           # (regra, arquivo) -> quantas

    def reprova(self, regra, onde, motivo):
        chave = (regra, onde.split(":", 1)[0])
        n = self._contas[chave] = self._contas.get(chave, 0) + 1
        if n <= MAX_POR_REGRA:
            self.reprovacoes.append(Reprovacao(regra, onde, motivo))

    def fecha(self):
        for (regra, arquivo), n in sorted(self._contas.items()):
            if n > MAX_POR_REGRA:
                self.reprovacoes.append(Reprovacao(regra, arquivo, f"e mais {n - MAX_POR_REGRA} na mesma regra"))
        return self.reprovacoes

    # ---------- os arquivos (regra 8) ----------

    def listar(self, ignorar_versao=False):
        """Percorre o pacote SEM seguir link. Devolve [(relativo, caminho, tamanho)] dos arquivos comuns."""
        lista, total, pendentes = [], 0, [("", 0)]
        while pendentes:
            rel_dir, nivel = pendentes.pop()
            with os.scandir(os.path.join(self.raiz, rel_dir)) as entradas:
                for e in sorted(entradas, key=lambda e: e.name):
                    rel = posixpath.join(rel_dir, e.name) if rel_dir else e.name
                    if ignorar_versao and rel == "versao.txt":
                        continue
                    if ADIADAS.search(e.name):
                        self.reprova("4 contato", rel, "página adiada (privacidade ou termos) no pacote")
                    if e.name.startswith("."):
                        self.reprova("8 arquivos", rel, "arquivo ou diretório oculto")
                    elif not COMPONENTE.fullmatch(e.name):
                        self.reprova("8 arquivos", rel, "nome fora de [A-Za-z0-9._-[]]")
                    if e.is_symlink():
                        self.reprova("8 arquivos", rel, "link")
                    elif e.is_dir(follow_symlinks=False):
                        if nivel + 1 >= MAX_NIVEIS:
                            self.reprova("8 arquivos", rel, f"mais de {MAX_NIVEIS} níveis")
                        else:
                            pendentes.append((rel, nivel + 1))
                    elif e.is_file(follow_symlinks=False):
                        tamanho = e.stat(follow_symlinks=False).st_size
                        total += tamanho
                        lista.append((rel, e.path, tamanho))
                        if nivel + 1 > MAX_NIVEIS:
                            self.reprova("8 arquivos", rel, f"mais de {MAX_NIVEIS} níveis")
                        if posixpath.splitext(e.name)[1].lower() not in TIPOS:
                            self.reprova("8 arquivos", rel, "tipo fora da lista permitida")
                        if tamanho > MAX_ARQUIVO:
                            self.reprova("8 arquivos", rel, f"{tamanho} bytes, acima do teto de {MAX_ARQUIVO}")
                        if e.name == "versao.txt":
                            self.reprova("8 arquivos", rel, "o versao.txt é do publicador")
                    else:
                        self.reprova("8 arquivos", rel, "não é arquivo nem diretório comum")
        if len(lista) > MAX_ARQUIVOS:
            self.reprova("8 arquivos", "(pacote)", f"{len(lista)} arquivos, acima do teto de {MAX_ARQUIVOS}")
        if total > MAX_TOTAL:
            self.reprova("8 arquivos", "(pacote)", f"{total} bytes, acima do teto de {MAX_TOTAL}")
        if "index.html" not in {rel for rel, _, _ in lista}:
            self.reprova("8 arquivos", "(pacote)", "sem index.html na raiz")
        self.arquivos = {rel for rel, _, _ in lista}
        return lista, total

    def texto_de(self, rel, dados):
        """O texto UTF-8 de um arquivo de texto, ou None: o navegador decodificaria outra coisa, e as regras não a leriam."""
        if dados.startswith((b"\xff\xfe", b"\xfe\xff")):
            self.reprova("8 arquivos", rel, "codificação UTF-16 ou UTF-32 (só UTF-8)")
            return None
        try:
            texto = dados.decode("utf-8")
        except UnicodeDecodeError:
            self.reprova("8 arquivos", rel, "não é UTF-8")
            return None
        return texto[1:] if texto.startswith("﻿") else texto

    # ---------- as regras de cada arquivo ----------

    def checar_arquivo(self, rel, dados):
        ext = posixpath.splitext(rel)[1].lower()
        linhas_b = None
        for m in LOCAL.finditer(dados):
            linhas_b = linhas_b or Linhas(dados)
            self.reprova("2 local", f"{rel}:{linhas_b.de(m.start())}", f"«{m.group().decode('latin-1')}»")
        if ext not in TEXTO:
            return
        texto = self.texto_de(rel, dados)
        if texto is None:
            return
        linhas = Linhas(texto)
        for m in MARCA.finditer(texto):
            self.reprova("7 marca", f"{rel}:{linhas.de(m.start())}", f"«{m.group()}»")
        if ext == ".txt":
            return
        for m in CONTATO.finditer(texto):
            self.reprova("4 contato", f"{rel}:{linhas.de(m.start())}", f"«{m.group()}»")
        for m in JAVASCRIPT.finditer(texto):
            self.reprova("5 csp", f"{rel}:{linhas.de(m.start())}", "javascript:")
        if ext in (".html", ".svg"):
            self.checar_marcacao(rel, texto, svg=(ext == ".svg"))
        elif ext == ".css":
            self.checar_css(rel, texto, linhas)
        elif ext == ".js":
            self.checar_js(rel, texto, linhas)

    def checar_marcacao(self, rel, texto, svg):
        leitor = Leitor()
        leitor.feed(texto)
        leitor.close()
        base = posixpath.dirname(rel)
        for linha, tag, a in leitor.tags:
            onde = f"{rel}:{linha}"
            if tag == "script" and (svg or "src" not in a):
                self.reprova("5 csp", onde, "<script> no SVG" if svg else "<script> embutido, sem src")
            if tag == "style":
                self.reprova("5 csp", onde, "<style> embutido")
            if tag in TAGS_PROIBIDAS:
                self.reprova("5 csp", onde, f"<{tag}>")
            if tag == "meta":
                if "http-equiv" in a:
                    self.reprova("5 csp", onde, f"<meta http-equiv=\"{a['http-equiv']}\">")
                if a.get("name", "").strip().lower() == "referrer":
                    self.reprova("5 csp", onde, "<meta name=\"referrer\">")
                if "charset" in a and a["charset"].strip().lower() not in ("utf-8", "utf8"):
                    self.reprova("8 arquivos", onde, f"<meta charset=\"{a['charset']}\">: só UTF-8")
            if tag == "form":
                self.reprova("4 contato", onde, "formulário")
            for nome in a:
                if nome.startswith("on"):
                    self.reprova("5 csp", onde, f"atributo {nome}=")
                elif nome == "style":
                    self.reprova("5 csp", onde, "atributo style=")
                elif nome == "formaction":
                    self.reprova("4 contato", onde, "atributo formaction= (formulário)")
            for nome in CARGA.get(tag, ()):
                if nome not in a:
                    continue
                urls = candidatos_srcset(a[nome]) if nome == "srcset" else [a[nome]]
                imagem = (tag, nome) in IMAGEM or (tag == "link" and "icon" in a.get("rel", "").lower().split())
                for url in urls:
                    self.carga(onde, base, url, imagem)
            for nome in NAVEGA.get(tag, ()):
                if nome in a:
                    self.navegacao(onde, base, a[nome])
        for linha, a, visivel in leitor.links:
            onde = f"{rel}:{linha}"
            href = a.get("href", a.get("xlink:href"))
            # O texto de login ou de portal só marca o link que sai da página: a âncora da própria página, o href vazio e o
            # <a> sem href não levam ao login, pela mesma leitura da navegação. O data-app marca sempre (pergunta 16 (a) do
            # apply do home-marketing: o «Portal do organizador» do rodapé da 1.1 leva a #solucoes).
            sai_da_pagina = href is not None and classifica(href)[0] not in ("vazio", "fragmento")
            if "data-app" in a or (sai_da_pagina and LOGIN.search(visivel)):
                if (href or "").strip() not in (APP, APP + "/"):
                    self.reprova("1 login", onde, f"link de login ou portal («{visivel[:60]}») leva a {href!r}, e não a {APP}")
            if ADIADAS.search(visivel):
                self.reprova("4 contato", onde, f"link de página adiada: «{visivel[:60]}»")

    def carga(self, onde, base, url, imagem):
        tipo, esquema = classifica(url)
        if tipo in ("vazio", "fragmento"):
            return
        if tipo == "relativo":
            self.interno(onde, base, url)
        elif esquema == "data" and imagem and eh_imagem_data(url):
            return
        elif esquema == "javascript":
            # Também pelo atributo: com tabulação ou entidade no meio, a busca por texto não o vê, e o navegador sim.
            self.reprova("5 csp", onde, "javascript:")
        else:
            self.reprova("3 terceiros", onde, f"carrega {url[:80]!r}, que não vem da própria origem por caminho relativo")

    def navegacao(self, onde, base, url):
        tipo, esquema = classifica(url)
        if ADIADAS.search(url):
            self.reprova("4 contato", onde, f"link de página adiada: {url[:80]!r}")
        if tipo in ("vazio", "fragmento"):
            return
        if tipo == "relativo":
            self.interno(onde, base, url)
        elif esquema in ("mailto", "tel"):
            # Também pelo atributo: com tabulação ou entidade no meio, a busca por texto não o vê, e o navegador sim.
            self.reprova("4 contato", onde, f"{esquema}:")
        elif esquema == "javascript":
            self.reprova("5 csp", onde, "javascript:")
        elif not eh_app(url):
            self.reprova("3 terceiros", onde, f"navega para {url[:80]!r}: para fora, só {APP}")

    def interno(self, onde, base, url):
        """Regra 4, os links internos: só passa o caminho que a borda serviria (`try_files $uri $uri/ =404`, sem `x.html`)."""
        if self.raiz is None:
            return  # o modo da página sozinha não tem o pacote
        caminho = re.sub(r"[\t\n\r]", "", url).strip().replace("\\", "/").split("#", 1)[0].split("?", 1)[0]
        if not caminho:
            return
        caminho = unquote(caminho)
        # A resolução do navegador: relativo ao diretório da página, e o «..» acima da raiz fica na raiz.
        partes = [] if caminho.startswith("/") else [p for p in base.split("/") if p]
        for p in caminho.split("/"):
            if p in ("", "."):
                continue
            if p == "..":
                if partes:
                    partes.pop()
            else:
                partes.append(p)
        rel = "/".join(partes)
        if caminho.endswith("/") or caminho.split("/")[-1] in (".", "..") or rel == "":
            alvo = posixpath.join(rel, "index.html") if rel else "index.html"
            if alvo not in self.arquivos:
                self.reprova("4 contato", onde, f"{url[:80]!r}: a borda não serviria — falta {alvo}")
        elif rel not in self.arquivos:
            if posixpath.join(rel, "index.html") in self.arquivos:
                self.reprova("4 contato", onde, f"{url[:80]!r}: diretório sem a barra final (a borda redirecionaria)")
            else:
                self.reprova("4 contato", onde, f"{url[:80]!r}: a borda não serviria — {rel} não existe no pacote")

    def checar_css(self, rel, texto, linhas):
        base = posixpath.dirname(rel)
        for pos, url in urls_do_css(texto):
            self.carga(f"{rel}:{linhas.de(pos)}", base, url, imagem=True)

    def checar_js(self, rel, texto, linhas):
        for regra, padrao, motivo in JS:
            for m in padrao.finditer(texto):
                self.reprova(regra, f"{rel}:{linhas.de(m.start())}", motivo)
        for m in URL_NO_SCRIPT.finditer(texto):
            if not eh_app(m.group(0)):
                self.reprova("3 terceiros", f"{rel}:{linhas.de(m.start())}", f"endereço de fora no script: {m.group(0)[:80]!r}")
        for m in REDE_NO_SCRIPT.finditer(texto):
            self.reprova("3 terceiros", f"{rel}:{linhas.de(m.start())}", "endereço de rede («//…») no script")
        for m in APP_URL.finditer(texto):
            if m.group(2).strip() not in (APP, APP + "/"):
                self.reprova("1 login", f"{rel}:{linhas.de(m.start())}", f"appUrl = {m.group(2)!r}, e não {APP}")


def urls_do_css(texto):
    """As referências de um CSS — `url(…)` e `@import "…"` —, por uma varredura LINEAR: cada trecho se lê uma vez, e a
    procura seguinte começa depois do fim da anterior."""
    achadas, i, n = [], 0, len(texto)
    baixo = texto.lower()
    while True:
        u = baixo.find("url(", i)
        imp = baixo.find("@import", i)
        if u < 0 and imp < 0:
            break
        if imp >= 0 and (u < 0 or imp < u):
            j = imp + len("@import")
            while j < n and texto[j].isspace():
                j += 1
            if j < n and texto[j] in "\"'":
                fim = texto.find(texto[j], j + 1)
                if fim < 0:
                    achadas.append((imp, texto[j + 1:]))
                    break
                achadas.append((imp, texto[j + 1:fim]))
                i = fim + 1
            else:
                i = j  # @import url(…): a próxima volta o lê como url(
            continue
        j = u + len("url(")
        while j < n and texto[j].isspace():
            j += 1
        if j < n and texto[j] in "\"'":
            fim = texto.find(texto[j], j + 1)
            if fim < 0:
                achadas.append((u, texto[j + 1:]))
                break
            achadas.append((u, texto[j + 1:fim]))
            i = fim + 1
        else:
            fim = texto.find(")", j)
            if fim < 0:
                achadas.append((u, texto[j:].strip()))
                break
            achadas.append((u, texto[j:fim].strip()))
            i = fim + 1
    return achadas


def checar_pacote(raiz, ignorar_versao=False):
    """O modo do pacote: as oito regras sobre o diretório. `ignorar_versao` deixa de fora o `versao.txt` da raiz, que o
    publicador escreve: é o que a conferência da versão no ar usa (design D12)."""
    if not os.path.isdir(raiz):
        raise FileNotFoundError(f"não é diretório: {raiz}")
    c = Checagem(raiz)
    lista, _ = c.listar(ignorar_versao)
    for rel, caminho, tamanho in lista:
        if tamanho > MAX_ARQUIVO:
            continue  # já reprovado; não se lê arquivo acima do teto
        with open(caminho, "rb") as f:
            dados = f.read(MAX_ARQUIVO + 1)
        c.checar_arquivo(rel, dados)
    return c.fecha()


def checar_pagina(caminho):
    """O modo da página sozinha: as regras que se leem de uma página — sem a dos links internos e sem a dos arquivos."""
    with open(caminho, "rb") as f:
        dados = f.read(MAX_ARQUIVO + 1)
    c = Checagem(None)
    nome = os.path.basename(caminho)
    if len(dados) > MAX_ARQUIVO:
        c.reprova("8 arquivos", nome, f"acima do teto de {MAX_ARQUIVO} bytes")
        return c.fecha()
    rel = nome if nome.lower().endswith(".html") else nome + ".html"
    c.checar_arquivo(rel, dados)
    return c.fecha()


USO = "uso: checa-home.py <diretório do pacote> | --pagina <arquivo .html>"


def main(argv):
    try:
        if len(argv) == 3 and argv[1] == "--pagina":
            alvo, reprovacoes = argv[2], checar_pagina(argv[2])
        elif len(argv) == 2 and not argv[1].startswith("-"):
            alvo, reprovacoes = argv[1], checar_pacote(argv[1])
        else:
            print(USO, file=sys.stderr)
            return 2
    except OSError as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 2
    for r in reprovacoes:
        print(f"REPROVA [{r.regra}] {r.onde}: {r.motivo}")
    regras = sorted({r.regra for r in reprovacoes})
    print(f"== {alvo}: {len(reprovacoes)} reprovação(ões)" + (f", nas regras {', '.join(regras)}" if regras else ", passa"))
    return 1 if reprovacoes else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
