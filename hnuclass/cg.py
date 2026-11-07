# -*- coding: utf-8 -*-
"""CG 教学平台（cg.hnu.edu.cn）客户端。

登录采用“浏览器辅助”方式：程序拉起一个独立的 Chrome/Edge 调试实例，
由用户自己在页面里输入账号、密码和验证码；程序只通过 DevTools 协议
读取 cg.hnu.edu.cn 域下的 Cookie，不在任何地方保存密码。
"""
from __future__ import annotations

import json
import os
import re
import ssl
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from http.cookies import SimpleCookie

from lxml import html as LH

BASE = "https://cg.hnu.edu.cn"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


class CGError(RuntimeError):
    pass


@dataclass
class Course:
    id: str
    name: str


@dataclass
class Assignment:
    id: str
    name: str


@dataclass
class ProblemRef:
    index: str
    problem_id: str
    title: str
    score: str = ""
    kind: str = ""
    via: str = "program"   # content | program | fill | interface | cloze
    detail: str = ""       # 填空题/单选题的完整题面（列表里可展开）


@dataclass
class Resp:
    status: int
    url: str
    text: str
    headers: dict = field(default_factory=dict)
    content: bytes = b""



@dataclass
class Submission:
    problem_id: str
    score: float
    max_score: float
    when: str
    filename: str
    code: str
    tests_total: int = 0
    tests_ok: int = 0

    @property
    def full(self) -> bool:
        return self.max_score > 0 and self.score + 1e-6 >= self.max_score


class CGClient:
    def __init__(self, base: str = BASE, cookies: dict | None = None, timeout: int = 25):
        self.base = base.rstrip("/")
        self.cookies: dict[str, str] = dict(cookies or {})
        self.timeout = timeout
        self.ctx = ssl._create_unverified_context()

    # ------------------------------------------------------------- HTTP
    def _request(self, path: str, data: dict | None = None, follow: bool = True) -> Resp:
        url = path if path.startswith("http") else self.base + path
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body)
        req.add_header("User-Agent", UA)
        req.add_header("Accept-Language", "zh-CN,zh;q=0.9")
        if body is not None:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        if self.cookies:
            req.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in self.cookies.items()))

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw):
                return None

        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=self.ctx),
            urllib.request.HTTPCookieProcessor(),
            *( () if follow else (NoRedirect(),) ),
        )
        try:
            with opener.open(req, timeout=self.timeout) as r:
                raw = r.read()
                resp = Resp(r.status, r.geturl(), raw.decode("utf-8", "replace"), dict(r.headers), raw)
        except urllib.error.HTTPError as e:
            raw = e.read()
            resp = Resp(e.code, e.geturl(), raw.decode("utf-8", "replace"), dict(e.headers), raw)
        for k, v in resp.headers.items():
            if k.lower() == "set-cookie":
                sc = SimpleCookie()
                try:
                    sc.load(v)
                except Exception:
                    continue
                for name, morsel in sc.items():
                    self.cookies[name] = morsel.value
        return resp

    def get(self, path: str, follow: bool = True) -> Resp:
        return self._request(path, None, follow)

    def post(self, path: str, data: dict, follow: bool = True) -> Resp:
        return self._request(path, data, follow)

    # ------------------------------------------------------------- 登录态
    def is_logged_in(self) -> bool:
        if not self.cookies:
            return False
        try:
            r = self.get("/main.jsp")
        except Exception:
            return False
        return r.status == 200 and len(r.text) > 2000 and ("退出" in r.text or "course" in r.text)

    def whoami(self) -> str:
        r = self.get("/main.jsp")
        m = re.search(r'<span[^>]*class="[^"]*(?:user|name)[^"]*"[^>]*>([^<]{2,20})</span>', r.text)
        if m:
            return m.group(1).strip()
        m = re.search(r"([\u4e00-\u9fa5]{2,4})\s*同学", r.text)
        return m.group(1) if m else ""

    # ------------------------------------------------------------- 课程/作业/题目
    def _doc(self, r):
        """把响应当 HTML 解析；空页面通常意味着登录态失效。"""
        if not r.text or len(r.text.strip()) < 50:
            raise CGError("登录已过期或未登录，请先执行「浏览器辅助登录」再重试。")
        # 只认真正的登录表单；正常页面里也会引用 loginproc.jsp 脚本，不能据此判失效
        if re.search(r'name=["\']loginForm["\']', r.text):
            raise CGError("登录已过期或未登录，请先执行「浏览器辅助登录」再重试。")
        try:
            return LH.fromstring(r.text)
        except Exception as exc:
            raise CGError(f"页面解析失败（{exc}）；若平台正在维护请稍后再试。") from exc

    def courses(self) -> list[Course]:
        r = self.get("/courselist.jsp")
        doc = self._doc(r)
        out, seen = [], set()
        for a in doc.xpath('//a[contains(@href,"courselist.jsp?courseID=")]'):
            m = re.search(r"courseID=(\d+)", a.get("href", ""))
            name = (a.text_content() or "").strip()
            if m and name and m.group(1) not in seen:
                seen.add(m.group(1))
                out.append(Course(m.group(1), name))
        return out

    def select_course(self, course_id: str) -> Resp:
        """切换当前课程。平台的切换是 main.jsp 上的一个 POST 表单，
        不是 GET /courselist.jsp?courseID=…（那个只会 302 回首页）。"""
        return self.post("/main.jsp", {"doChangeCourse": "true", "changeCourse": str(course_id)})

    def assignments(self, course_id: str) -> list[Assignment]:
        self.select_course(course_id)
        r = self.get("/assignment/mainActiveAssigns.jsp")
        if not r.text.strip():
            return []
        if re.search(r'name=["\']loginForm["\']', r.text):
            raise CGError("登录已过期或未登录，请先执行「浏览器辅助登录」再重试。")
        doc = self._doc(r)
        out, seen = [], set()
        for block in doc.xpath('//div[contains(@class,"main-zy")]'):
            t = block.xpath('.//p[contains(@class,"main-title")]')
            a = block.xpath('.//a[contains(@href,"assignID=")]')
            if not t or not a:
                continue
            m = re.search(r"assignID=(\d+)", a[0].get("href", ""))
            name = (t[0].text_content() or "").strip()
            if m and name and m.group(1) not in seen:
                seen.add(m.group(1))
                out.append(Assignment(m.group(1), name))
        if not out:  # 兜底：直接扫链接
            for a in doc.xpath('//a[contains(@href,"assignID=")]'):
                m = re.search(r"assignID=(\d+)", a.get("href", ""))
                name = (a.text_content() or "").strip()
                if m and name and m.group(1) not in seen:
                    seen.add(m.group(1))
                    out.append(Assignment(m.group(1), name))
        return out

    def problems(self, assign_id: str) -> list[ProblemRef]:
        """解析作业页的题目列表。

        平台把题目按题型分区，每个分区是“标题 + 一张 table-striped”：
        - 填空题：题目内联在页面里（form name=answerForm<problemID>），没有跳转链接；
        - 接口编程题：链到 programWithInterfaceList.jsp?proNum=&assignID=；
        - 程序片段编程题：链到 programFillGapList.jsp?proNum=&assignID=；
        - 编程题：programList.jsp 或 problemContent.jsp。
        """
        r = self.get(f"/assignment/index.jsp?assignID={assign_id}")
        doc = self._doc(r)
        out: list[ProblemRef] = []
        seen = set()

        def add_row(row, section: str) -> None:
            kind = _kind_label(section)
            links = row.xpath(".//a[@href]")

            def pick(part: str):
                return next((a for a in links if part in (a.get("href") or "")), None)

            inter = pick("programWithInterfaceList.jsp")
            fill = pick("programFillGapList.jsp")
            prog = pick("programList.jsp")
            content = pick("problemContent.jsp")
            judge = pick("judgeDetailsRedirect.jsp")
            form = row.xpath('.//form[starts-with(@name,"answerForm")]')
            idx = pid = title = via = detail = ""
            if inter is not None:
                via = "interface"
                m = re.search(r"proNum=(\d+)", inter.get("href", ""))
                idx = m.group(1) if m else ""
                title = (inter.text_content() or "").strip()
            elif fill is not None:
                via = "fill"
                m = re.search(r"proNum=(\d+)", fill.get("href", ""))
                idx = m.group(1) if m else ""
                title = (fill.text_content() or "").strip()
            elif prog is not None:
                via = "program"
                m = re.search(r"proNum=(\d+)", prog.get("href", ""))
                idx = m.group(1) if m else ""
                title = (prog.text_content() or "").strip()
            elif content is not None:
                via = "content"
                m = re.search(r"problemID=([^&'\"]+)", content.get("href", ""))
                if not m:
                    return
                pid = m.group(1)
                title = (content.text_content() or "").strip()
            elif form:
                via = "cloze"
                pid = (form[0].get("name") or "").replace("answerForm", "")
                ps = form[0].xpath(".//p")
                stem = " ".join((ps[0].text_content() if ps else form[0].text_content()).split())
                title = stem[:36] + ("…" if len(stem) > 36 else "")
                frag = _cloze_fragment(r.text, pid, "1")
                if frag:
                    fd = LH.fromstring(frag)
                    dnode = fd.get_element_by_id("problem-description")
                    if dnode is not None:
                        detail = _clean(_block_text(dnode))
            else:
                return
            if judge is not None and not pid:
                mj = re.search(r"problemID=([^&]+)", judge.get("href", ""))
                pid = mj.group(1) if mj else ""
            if not idx:
                th = row.xpath("./th")
                if th:
                    mi = re.match(r"\s*(\d+)", th[0].text_content() or "")
                    if mi:
                        idx = mi.group(1)
            key = pid or f"{via}:{idx}:{title}"
            if key in seen:
                return
            seen.add(key)
            cells = row.xpath("./td")
            score = ""
            if via != "cloze" and len(cells) >= 2:
                score = " ".join(cells[1].text_content().split())[:24]
            out.append(ProblemRef(idx or str(len(out) + 1), pid,
                                  title, score, kind, via, detail))

        for head in doc.xpath('//div[contains(@class,"add-style-title")]'):
            section = _clean(head.text_content())
            tbls = head.xpath('following::table[contains(@class,"table-striped")][1]')
            if not tbls:
                continue
            table = tbls[0]
            prev = table.xpath('preceding::div[contains(@class,"add-style-title")][1]')
            if not prev or prev[0] is not head:
                continue
            for row in table.xpath("./tbody/tr[td] | ./tr[td]"):
                add_row(row, section)

        if not out:  # 兜底：老式页面没有分区标题
            for row in doc.xpath("//tr[.//a[@href] or .//form[starts-with(@name,'answerForm')]]"):
                add_row(row, "")
        return out


    # ------------------------------------------------------------- 提交记录
    def submission(self, assign_id: str, problem_id: str) -> "Submission | None":
        """取该题最近一次提交（平台的作业页只暴露最近一次源码下载）。"""
        if not problem_id:
            return None
        r = self.get(f"/assignment/index.jsp?assignID={assign_id}")
        doc = LH.fromstring(r.text)
        rows = doc.xpath('//table[contains(@class,"table-striped")]//tr')
        row = None
        for tr in rows:
            for a in tr.xpath('.//a[contains(@href,"judgeDetailsRedirect.jsp")]'):
                if f"problemID={problem_id}" in (a.get("href") or ""):
                    row = tr
                    break
            if row is not None:
                break
        if row is None:
            return None
        text = " ".join(row.text_content().split())
        m_score = re.search(r"得分[:：]\s*([\d.]+)", text)
        m_time = re.search(r"最后一次提交时间[:：]\s*([\d\-: ]+)", text)
        tds = row.xpath("./td")
        max_score = 0.0
        if len(tds) >= 2:
            m_max = re.search(r"([\d.]+)", tds[1].text_content() or "")
            if m_max:
                try:
                    max_score = float(m_max.group(1))
                except ValueError:
                    max_score = 0.0
        link = next((a.get("href") for a in row.xpath('.//a[contains(@href,"downloadFile")]')), "")
        tests_total = len(re.findall(r"测试数据\s*\d+", text))
        tests_ok = len(re.findall(r"测试数据\s*\d+\s*完全正确", text))
        code = ""
        if link:
            raw = self.get(link).content
            for enc in ("utf-8", "gb18030"):
                try:
                    code = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
        if not (m_score or link):
            return None
        try:
            score = float(m_score.group(1)) if m_score else 0.0
        except ValueError:
            score = 0.0
        return Submission(
            problem_id=problem_id, score=score, max_score=max_score,
            when=(m_time.group(1).strip() if m_time else ""),
            filename=(link.split("filename=")[-1][:24] if link else ""),
            code=code.strip(), tests_total=tests_total, tests_ok=tests_ok,
        )

    def problem_html(self, assign_id: str, index: str, problem_id: str = "", via: str = "") -> str:
        pid = problem_id
        # hash 型题号走 problemContent；纯数字（在线评测题）走 programList
        if via == "interface":
            r = self.get(f"/assignment/programWithInterfaceList.jsp?proNum={index}&assignID={assign_id}")
        elif via == "cloze":
            page = self.get(f"/assignment/index.jsp?assignID={assign_id}").text
            frag = _cloze_fragment(page, pid, index)
            if frag:
                return frag
            r = self.get(f"/assignment/index.jsp?assignID={assign_id}")
        elif via == "content" or (not via and pid and not pid.isdigit()):
            url = f"/assignment/problemContent.jsp?problemID={pid}"
            r = self.get(url)
        elif via == "program" or (not via and pid.isdigit()):
            url = f"/assignment/programList.jsp?proNum={index}&assignID={assign_id}"
            r = self.get(url)
        else:
            # 程序片段/补全题没有独立题号，走 programFillGapList
            r = self.get(f"/assignment/programFillGapList.jsp?proNum={index}&assignID={assign_id}")
            if len(r.text) < 300:
                r = self.get(f"/assignment/programList.jsp?proNum={index}&assignID={assign_id}")
        if len(r.text) < 300:
            raise CGError(f"题目页为空（HTTP {r.status}），可能登录已失效。")
        return r.text


# ---------------------------------------------------------------- 解析
MARKERS = {
    "description": ["【问题描述】", "问题描述", "题目描述", "题目内容", "描述"],
    "input": ["【输入形式】", "输入形式", "输入描述", "输入格式", "输入"],
    "output": ["【输出形式】", "输出形式", "输出描述", "输出格式", "输出"],
    "sample_in": ["【样例输入】", "样例输入", "输入样例", "样例"],
    "sample_out": ["【样例输出】", "样例输出", "输出样例"],
    "hint": ["【提示】", "提示", "说明"],
}


def _kind_label(s: str) -> str:
    """把平台的分区标题（程序片段编程题/填空题…）归一成题型。"""
    if "片段" in s or "补全" in s:
        return "程序补全"
    if "接口" in s:
        return "接口编程题"
    if "填空" in s:
        return "填空题"
    if "选择" in s or "单选" in s or "多选" in s:
        return "选择题"
    if "判断" in s:
        return "判断题"
    if "编程" in s:
        return "编程题"
    return s or ""


def _cloze_fragment(page_html: str, pid: str, index: str) -> str:
    """把页内填空题的题干抽成独立 HTML：输入框换成 ____，去掉提交状态。"""
    import copy
    try:
        doc = LH.fromstring(page_html)
    except Exception:  # noqa: BLE001
        return ""
    form = doc.xpath(f'//form[@name="answerForm{pid}"]') if pid else []
    if not form:
        forms = doc.xpath('//form[starts-with(@name,"answerForm")]')
        try:
            form = [forms[int(index) - 1]]
        except Exception:  # noqa: BLE001
            return ""
    td = form[0].xpath("ancestor::td[1]")
    if not td:
        return ""
    node = copy.deepcopy(td[0])
    for sp in node.xpath('.//span[contains(@class,"cgsavetip")]'):
        sp.getparent().remove(sp)
    for el in node.xpath('.//input[@type="hidden"] | .//button | .//script'):
        el.getparent().remove(el)
    for el in node.xpath('.//input | .//textarea | .//select'):
        blank = LH.Element("span")
        blank.set("class", "blank")
        blank.text = " ____ "
        el.getparent().replace(el, blank)
    body = LH.Element("div")
    body.set("id", "problem-description")
    for child in list(node):
        body.append(child)
    if node.text and node.text.strip():
        body.text = node.text
    return ('<html><body><h2>'
            f'填空题 {index}</h2>' + LH.tostring(body, encoding="unicode") + "</body></html>")


_BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
               "pre", "table", "section", "article", "ul", "ol", "dt", "dd", "blockquote"}


def _block_text(node) -> str:
    """按块级元素把文本拆行，避免 <p>/<div> 之间黏成一行。"""
    import copy
    el = copy.deepcopy(node)
    for br in el.iter("br"):
        br.tail = "\n" + (br.tail or "")
    for sub in el.iter():
        if sub is not el and isinstance(sub.tag, str) and sub.tag.lower() in _BLOCK_TAGS:
            sub.tail = "\n" + (sub.tail or "")
    return el.text_content()


def _clean(text: str) -> str:
    """压掉行内多余空白，但保留段落之间的空行。"""
    text = text.replace("\xa0", " ").replace("\r", "")
    lines: list[str] = []
    for ln in text.split("\n"):
        ln = re.sub(r"[ \t]+", " ", ln).strip()
        if ln:
            lines.append(ln)
        elif lines and lines[-1] != "":
            lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _main_node(doc):
    best, best_len = None, 0
    for el in doc.iter():
        if not isinstance(el.tag, str):
            continue
        ident = f"{el.get('id','')} {el.get('class','')}".lower()
        if not any(k in ident for k in ("problem", "content", "main", "description", "statement")):
            continue
        txt = el.text_content()
        if len(txt) > best_len:
            best, best_len = el, len(txt)
    return best if best is not None else doc.body


def parse_problem(page_html: str, assign_id: str, index: str, meta: ProblemRef | None = None):
    """把题目页（problemContent.jsp）解析成 Problem 字段。"""
    from .model import Case, Problem

    doc = LH.fromstring(page_html)
    for bad in doc.xpath("//script|//style|//nav|//header|//footer"):
        bad.drop_tree()

    title = ""
    for xp in ('//h4[contains(@class,"text-center")]', "//h1", "//h2",
               '//*[contains(@class,"problem-title")]', "//title"):
        got = doc.xpath(xp)
        if got:
            title = _clean(got[0].text_content())
            if title:
                break
    if meta and meta.title and (not title or title.startswith("湖南大学")):
        title = meta.title
    title = re.sub(r"\s*[-_|].*?CG.*$", "", title).strip()

    node = _main_node(doc)
    raw = _clean(_block_text(node))

    def find(words, start: int = 0):
        best = None
        for w in words:
            m = re.search(re.escape(w), raw[start:])
            if m:
                pos = start + m.start()
                if best is None or pos < best[0]:
                    best = (pos, start + m.end())
        return best

    d = find(["【问题描述】", "问题描述", "题目描述", "题目内容"])
    i = find(["【输入形式】", "输入形式", "输入描述", "输入格式"])
    o = find(["【输出形式】", "输出形式", "输出描述", "输出格式"])
    s = find(["【样例输入", "样例输入", "输入样例"])

    def seg(a, b):
        if a is None:
            return ""
        start = a[1]
        end = b[0] if b and b[0] > start else len(raw)
        return raw[start:end].strip()

    if d is None and i is None and o is None:
        cut = re.split(r"【?样例(?:输入|输出)\s*\d*】?", raw)[0]
        description, input_form, output_form = cut.strip()[:2500], "", ""
    else:
        description = seg(d, i or o)
        input_form = seg(i, o)
        output_form = seg(o, s)

    # 样例：优先用 pre/textarea 成对提取（平台题面就是【样例输入N】+pre）
    samples: list[Case] = []
    pres = doc.xpath("//pre")          # 样例只认 pre，textarea 是填空答案
    # 样例区在【样例说明/解释/解析】之后就不再有正式样例了，截断避免把解释示例当成样例
    expl = re.compile(r"【样例\s*\d*\s*(?:说明|解释|解析|分析)】|"
                      r"样例\s*\d*\s*(?:说明|解释|解析|分析)\s*[:：]")
    for el in doc.xpath("//p|//div|//span|//td|//li"):
        txt = (el.text or "").strip()
        if txt and expl.search(txt):
            before = {id(x) for x in el.xpath("preceding::pre")}
            pres = [x for x in pres if id(x) in before]
            break
    blocks: list[str] = []
    for p in pres:
        val = p.text_content() or p.get("value") or ""
        val = val.replace("\r", "").strip("\n")
        if val.strip():
            blocks.append(val)
    code_like = re.compile(r"#\s*include|int\s+main|using\s+namespace")
    cjk = re.compile(r"[\u4e00-\u9fff]")
    non_code = [b for b in blocks if not code_like.search(b) and not cjk.search(b)]
    def _sample_text(v: str) -> str:
        v = v.replace("\xa0", " ")
        m = re.search(r"【样例\s*\d*\s*(?:说明|解释|解析|分析)】|【(?:评分标准|提示|数据范围)】|"
                      r"样例\s*\d*\s*(?:说明|解释|解析|分析)\s*[:：]", v)
        if m:
            v = v[:m.start()]
        for mark in ("【样例说明】", "【样例解释】", "【评分标准】", "【提示】", "【数据范围】"):
            if mark in v:
                v = v.split(mark)[0]
        if "#include" in v:
            v = v.split("#include")[0]
        v = re.sub(r"\n\s*\n+", "\n", v)   # 折叠样例中的空行
        return v.strip("\n").rstrip()

    if len(non_code) >= 2:
        # 4 个 pre 时按 (输入1,输出1)、(输入2,输出2) 配对
        for k in range(0, len(non_code) - 1, 2):
            samples.append(Case(_sample_text(non_code[k]), _sample_text(non_code[k + 1])))

    # 没有 pre 时按【样例输入N】/【样例输出N】的文本切
    if not samples:
        pin = re.compile(r"【样例输入\s*(\d*)】")
        for m in pin.finditer(raw):
            n = m.group(1)
            mo = re.search(r"【样例输出\s*" + re.escape(n) + r"】", raw[m.end():])
            if not mo:
                continue
            si = _sample_text(raw[m.end(): m.end() + mo.start()])
            after = m.end() + mo.end()
            nxt = re.search(r"【样例(?:输入|输出)", raw[after:])
            so = _sample_text(raw[after: after + nxt.start() if nxt else len(raw)])
            if si or so:
                samples.append(Case(si, so))

    # 程序补全题：代码模板
    code = ""
    for b in blocks:
        if code_like.search(b) and len(b) > 30:
            code = b
            break
    for t in doc.xpath("//textarea"):
        v = (t.text or "").replace("\r", "")
        if code_like.search(v):
            code = v
            break
    if not code:
        for b in doc.xpath("//textarea"):
            v = b.text or ""
            if len(v) > 200:
                code = v.replace("\r", "")
                break
    # 程序片段题：模板在 <code class="cgcode"> 里，空格是 &nbsp;
    if not code:
        parts = []
        for cn in doc.xpath('//code[contains(@class,"cgcode")]'):
            txt = cn.text_content().replace("\xa0", " ").replace("\r", "")
            lines = [ln.rstrip() for ln in txt.split("\n")]
            while lines and not lines[0].strip():
                lines.pop(0)
            while lines and not lines[-1].strip():
                lines.pop()
            if lines:
                parts.append("\n".join(lines))
        code = "\n".join(parts)

    images = []
    for img in node.xpath(".//img[@src]"):
        images.append(img.get("src"))

    if meta is None:
        meta = ProblemRef(index=index, problem_id="", title=title)

    kind = guess_kind(meta.kind or meta.title or title, "")
    p = Problem(
        number=0,
        assignment="",
        ptype=kind,
        title=meta.title or title or f"题目{index}",
        index=index,
        problem_id=meta.problem_id,
        description=description,
        input_form=input_form,
        output_form=output_form,
        samples=samples,
        code=code,
        images=images,
        raw_html=page_html[:200000],
    )
    return p


def guess_kind(text: str, assignment: str = "") -> str:
    s = f"{text} {assignment}"
    for key, label in (
        ("程序补全", "程序补全"), ("补全", "程序补全"), ("片段", "程序补全"),
        ("填空", "填空题"), ("选择", "选择题"), ("判断", "判断题"),
    ):
        if key in s:
            return label
    return "编程题"
