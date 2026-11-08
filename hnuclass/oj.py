"""从常见 OJ 网站抓取题面（洛谷 / AtCoder / LeetCode / Codeforces / 通用网页）。"""
from __future__ import annotations

import html as htmllib
import json
import re
import ssl
import urllib.parse
import urllib.request
import http.cookiejar

import lxml.html

from .model import Case

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

SITES = {
    "luogu.com.cn": "洛谷",
    "codeforces.com": "Codeforces",
    "atcoder.jp": "AtCoder",
    "leetcode.cn": "力扣",
    "leetcode.com": "LeetCode",
}


class OJError(RuntimeError):
    pass


def detect(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    for k, v in SITES.items():
        if host == k or host.endswith("." + k):
            return v
    return "网页题目"


def _open(url: str, timeout: int = 25):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx),
                                     urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", UA), ("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.6")]
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with op.open(req, timeout=timeout) as r:
        raw = r.read()
        ct = r.headers.get("Content-Type", "")
    charset = "utf-8"
    m = re.search(r"charset=([\w-]+)", ct)
    if m:
        charset = m.group(1)
    return raw.decode(charset, "replace")


def _text(node) -> str:
    s = node.text_content().replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n\n", s)
    return s.strip()


def _pair_samples(pres):
    vals = [_text(p) for p in pres]
    out = []
    for i in range(0, len(vals) - 1, 2):
        a, b = vals[i], vals[i + 1]
        if a or b:
            out.append(Case(a, b))
    return out


def _clean_title(t: str) -> str:
    t = htmllib.unescape(t or "").strip()
    t = re.sub(r"\s*[-–|]\s*洛谷.*$", "", t)
    t = re.sub(r"\s*-\s*AtCoder.*$", "", t, flags=re.I)
    return t.strip()


def fetch_atcoder(html: str):
    doc = lxml.html.fromstring(html)
    node = doc.cssselect("#task-statement")
    if not node:
        raise OJError("AtCoder 页面里没有找到题面")
    node = node[0]
    title = _clean_title(_text(doc.cssselect("h2")[0]) if doc.cssselect("h2") else
                         (doc.findtext(".//title") or ""))
    desc = inp = outp = ""
    samples = []
    scope = node.cssselect(".lang-en") or node.cssselect(".lang-ja")
    heads = (scope[0] if scope else node).cssselect("h3")
    for h3 in heads:
        head = _text(h3)
        body = []
        pre_after = []
        for sib in h3.itersiblings():
            if sib.tag == "h3":
                break
            body.append(_text(sib))
            pre_after.extend(sib.cssselect("pre") if hasattr(sib, "cssselect") else [])
            if sib.tag == "pre":
                pre_after.append(sib)
        text = "\n".join(x for x in body if x).strip()
        if ("Sample Input" in head) or ("入力例" in head):
            samples.append([_text(pre_after[0]) if pre_after else text, ""])
        elif ("Sample Output" in head) or ("出力例" in head):
            if samples:
                samples[-1][1] = _text(pre_after[0]) if pre_after else text
        elif head.startswith("Problem Statement") or head.startswith("問題文"):
            desc = text
        elif head.startswith("Input") or head.startswith("入力"):
            inp = text
        elif head.startswith("Output") or head.startswith("出力"):
            outp = text
    if not desc:
        raise OJError("AtCoder 页面没有解析到题面（语种结构可能不同）")
    pairs = [Case(a, b) for a, b in samples if a or b]
    return dict(title=title, description=desc, input_form=inp, output_form=outp,
                samples=pairs)


def fetch_luogu(html: str):
    doc = lxml.html.fromstring(html)
    title = _clean_title(doc.findtext(".//title") or "")
    parts = {}
    for h2 in doc.cssselect("h2"):
        head = _text(h2)
        if head in ("题目描述", "输入格式", "输出格式", "说明/提示"):
            sib = h2.getnext()
            if sib is not None:
                parts[head] = _text(sib)
    desc = parts.get("题目描述", "")
    note = parts.get("说明/提示", "")
    if not desc:
        raise OJError("洛谷页面没有解析到题面（可能需要登录或页面结构变化）")
    return dict(title=title, description=desc, input_form=parts.get("输入格式", ""),
                output_form=parts.get("输出格式", ""), samples=[], note=note)


_BLOCK_RE = re.compile(r"</?(?:p|div|br|li|ul|ol|tr|h[1-6]|pre|section|table|blockquote)\b[^>]*>", re.I)


def _html_text(body: str) -> str:
    """HTML→纯文本：只有块级标签断行，行内 <code>/<span> 保持在同一行。"""
    s = re.sub(r"<br\s*/?>", "\n", body or "", flags=re.I)
    s = _BLOCK_RE.sub("\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = htmllib.unescape(s).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in s.splitlines()]
    out = []
    for ln in lines:
        if ln:
            out.append(ln)
        elif out and out[-1] != "":
            out.append("")
    return "\n".join(out).strip()


def fetch_leetcode(html: str):
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        raise OJError("力扣页面里没有找到题目数据（可能被风控拦截）")
    data = json.loads(m.group(1))
    found = {}

    def walk(o):
        if isinstance(o, dict):
            if o.get("content") and (o.get("title") or o.get("translatedTitle")):
                found.setdefault("q", o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    q = found.get("q")
    if not q:
        raise OJError("力扣页面里没有解析到题面")
    title = q.get("translatedTitle") or q.get("title") or ""
    body = q.get("translatedContent") or q.get("content") or ""
    txt = _html_text(body)
    # “示例 N：”与紧随其后的输入/输出/解释保持在同一段，避免翻页时被拆散
    txt = re.sub(r"(示例\s*\d+\s*[:：])\s*\n+\s*", r"\1\n", txt)
    return dict(title=title, description=txt, input_form="", output_form="", samples=[])


def fetch_codeforces(html: str):
    doc = lxml.html.fromstring(html)
    st = doc.cssselect("div.problem-statement")
    if not st:
        raise OJError("Codeforces 页面里没有找到题面")
    st = st[0]
    title = _text(st.cssselect("div.title")[0]) if st.cssselect("div.title") else ""
    title = re.sub(r"^[A-Z]\d*\.\s*", "", title)
    def sec(cls):
        n = st.cssselect(f"div.{cls}")
        return _text(n[0]) if n else ""
    desc = sec("input-specification")
    # description is everything before input-specification
    desc = ""
    for child in st:
        if "input-specification" in (child.get("class") or ""):
            break
        if "header" in (child.get("class") or ""):
            continue
        desc += _text(child) + "\n"
    samples = []
    for block in st.cssselect("div.sample-test"):
        ins = block.cssselect("div.input pre")
        outs = block.cssselect("div.output pre")
        if ins and outs:
            samples.append(Case(_text(ins[0]), _text(outs[0])))
    return dict(title=title, description=desc.strip(), input_form=sec("input-specification"),
                output_form=sec("output-specification"), samples=samples)


def fetch_generic(html: str, url: str):
    doc = lxml.html.fromstring(html)
    for bad in doc.cssselect("script,style,nav,header,footer,aside"):
        bad.drop_tree()
    title = _clean_title(doc.findtext(".//title") or "")
    node = None
    for sel in ("article", "main", "#content", ".content", "body"):
        n = doc.cssselect(sel)
        if n:
            node = n[0]
            break
    desc = _text(node)[:4000] if node is not None else ""
    pres = doc.cssselect("pre")
    return dict(title=title, description=desc, input_form="", output_form="",
                samples=_pair_samples(pres))


def fetch_problem(url: str, timeout: int = 25) -> dict:
    url = url.strip()
    if not re.match(r"^https?://", url):
        url = "https://" + url
    source = detect(url)
    try:
        html = _open(url, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        raise OJError(f"{source} 页面打不开：{e}") from e
    if "atcoder.jp" in url:
        data = fetch_atcoder(html)
    elif "luogu.com.cn" in url:
        data = fetch_luogu(html)
    elif "leetcode." in url:
        data = fetch_leetcode(html)
    elif "codeforces.com" in url:
        data = fetch_codeforces(html)
    else:
        data = fetch_generic(html, url)
    try:
        from .cg import _reflow
        data["description"] = _reflow(data.get("description") or "")
    except Exception:  # noqa: BLE001
        pass
    data["source"] = source
    data["url"] = url
    data.setdefault("note", "")
    return data
