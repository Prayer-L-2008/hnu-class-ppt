# -*- coding: utf-8 -*-
"""OpenAI 兼容接口封装：生成思路分析、逐行讲解、参考代码与总结。"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .model import CodePage, Problem


@dataclass
class LLMConfig:
    base_url: str = "https://api.deepseek.com/v1"
    api_key: str = ""
    model: str = "deepseek-chat"
    temperature: float = 0.3
    timeout: int = 240

    @property
    def ready(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    @classmethod
    def from_dict(cls, d: dict | None) -> "LLMConfig":
        d = d or {}
        return cls(
            base_url=d.get("base_url") or "https://api.deepseek.com/v1",
            api_key=d.get("api_key", ""),
            model=d.get("model") or "deepseek-chat",
            temperature=float(d.get("temperature", 0.3)),
            timeout=int(d.get("timeout", 240)),
        )


@dataclass
class LLMResult:
    analysis: list[str] = field(default_factory=list)
    solution_code: str = ""
    code_pages: list[CodePage] = field(default_factory=list)
    tips: str = ""
    summary: list[str] = field(default_factory=list)


def _post(url: str, payload: dict, api_key: str, timeout: int) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:800]
        raise RuntimeError(f"LLM 接口返回 {e.code}: {body}") from None


def chat(cfg: LLMConfig, messages: list[dict], json_mode: bool = True) -> str:
    base = cfg.base_url.rstrip("/")
    url = base + "/chat/completions"
    payload = {
        "model": cfg.model,
        "messages": messages,
        "temperature": cfg.temperature,
        "max_tokens": 8192,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    try:
        data = _post(url, payload, cfg.api_key, cfg.timeout)
    except RuntimeError:
        if not json_mode:
            raise
        payload.pop("response_format", None)
        data = _post(url, payload, cfg.api_key, cfg.timeout)
    # 推理型模型常把 token 花在思考上，长度截断时自动加倍重试一次
    try:
        fr = data["choices"][0].get("finish_reason")
    except Exception:
        fr = None
    if fr == "length" and payload.get("max_tokens", 0) < 16384:
        payload["max_tokens"] = 16384
        try:
            data = _post(url, payload, cfg.api_key, cfg.timeout)
        except RuntimeError:
            pass
    try:
        msg = data["choices"][0]["message"]
    except Exception:
        raise RuntimeError(f"无法解析 LLM 返回：{json.dumps(data, ensure_ascii=False)[:500]}")
    content = msg.get("content")
    if isinstance(content, list):  # 多模态分段
        content = "".join(str(x.get("text", "")) if isinstance(x, dict) else str(x) for x in content)
    if not (content or "").strip():
        # 部分推理模型把正文放在 reasoning_content；再兜底 text 字段
        content = msg.get("reasoning_content") or data.get("text") or ""
    if not (content or "").strip():
        raise RuntimeError(f"LLM 返回内容为空：{json.dumps(data, ensure_ascii=False)[:400]}")
    return content


def _balanced_json(text: str) -> str:
    """从任意文本里截出第一个完整的 JSON 对象（正确处理字符串内的括号/转义）。"""
    start = text.find("{")
    if start < 0:
        return ""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return ""


def parse_json(text: str) -> dict:
    text = (text or "").strip().lstrip("\ufeff")
    m = re.search(r"```(?:json|JSON)?\s*([\s\S]*?)(?:```|$)", text)
    if m:
        text = m.group(1).strip()
    for candidate in (text, _balanced_json(text)):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            fixed = re.sub(r",\s*([}\]])", r"\1", candidate)  # 去掉尾逗号
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                continue
    raise ValueError(f"LLM 返回的不是合法 JSON（前 200 字）：{text[:200]!r}")


def _json_chat(cfg: LLMConfig, messages: list[dict], tries: int = 3) -> dict:
    """调用并解析 JSON；失败时换一种更强硬的方式重试，最多 3 次。"""
    last: Exception | None = None
    original = list(messages)
    for n in range(tries):
        raw = chat(cfg, messages, json_mode=True)
        try:
            return parse_json(raw)
        except Exception as e:  # noqa: BLE001
            last = e
        if n == 0:
            # 第二次：把原文附回去，明确要求“只输出 JSON”
            messages = original + [
                {"role": "assistant", "content": raw[:4000]},
                {"role": "user", "content": "上面的输出不是合法 JSON。请只输出一个 JSON 对象，"
                                            "不要 markdown 代码块、不要解释文字、不要思考过程，"
                                            "从 { 开始、以 } 结束。"},
            ]
        else:
            # 第三次：丢掉之前的上下文，重建最短对话，避免被长推理带偏
            user = next((m["content"] for m in reversed(original) if m.get("role") == "user"), "")
            messages = [
                {"role": "system", "content": "你是 JSON 生成器。只输出一个合法 JSON 对象，"
                                              "不要输出任何解释、思考过程或 markdown 代码块。"},
                {"role": "user", "content": "请完成下面的任务，并只返回 JSON：\n" + user},
            ]
    raise last  # type: ignore[misc]


SYSTEM = (
    "你是湖南大学计算机专业的学生，正在小班课上给全班同学讲自己做的这道题。"
    "语气要像同学上台讲题：讲自己的思路和踩过的坑时用「我」（我先想的是……、我一开始写错了……），"
    "带着大家看代码时可以用「我们」「大家」「同学们」（我们来看这里、大家注意这个边界）。"
    "不要用「作者」「笔者」「本文」「该算法」「综上所述」「首先/其次/最后」这类书面或 AI 腔，"
    "也不要写成教程、说明书或助教点评。"
    "句子口语化、具体，讲清楚为什么这么做，避免空话。"
    "所有输出必须是合法 JSON，不要输出 JSON 以外的任何文字。"
)


def _fp_text(v):
    """把讲解文字统一成第一人称。"""
    if not isinstance(v, str):
        return v
    for a, b in (("作者", "我"), ("笔者", "我"), ("本文", "我")):
        v = v.replace(a, b)
    return v


def _fp_result(res):
    try:
        res.analysis = [_fp_text(x) for x in (res.analysis or [])]
        res.tips = _fp_text(res.tips)
        res.summary = [_fp_text(x) for x in (res.summary or [])]
        for cp in (res.code_pages or []):
            cp.heading = _fp_text(cp.heading)
            cp.note = _fp_text(cp.note)
            cp.bullets = [_fp_text(x) for x in (cp.bullets or [])]
    except Exception:
        pass
    return res


def _problem_digest(p: Problem) -> str:
    parts = [
        f"题目：{p.title}",
        f"题型：{p.ptype}",
        f"题面：{p.description[:2500]}",
    ]
    if p.input_form:
        parts.append(f"输入：{p.input_form[:500]}")
    if p.output_form:
        parts.append(f"输出：{p.output_form[:500]}")
    for i, c in enumerate(p.samples[:3], 1):
        parts.append(f"样例{i} 输入：{c.input[:400]}")
        parts.append(f"样例{i} 输出：{c.output[:400]}")
    if p.code:
        parts.append(f"题目自带代码/模板：\n{p.code[:2500]}")
    return "\n".join(parts)


def generate(cfg: LLMConfig, p: Problem) -> LLMResult:
    user = f"""{_problem_digest(p)}

请生成小班课课件所需的内容，严格返回如下 JSON：
{{
  "analysis": ["思路分析第1段", "第2段", "..."],
  "solution_code": "完整的 C++17 参考程序（可直接编译运行，从 stdin 读入、向 stdout 输出）",
  "code_pages": [
    {{"heading": "这一页的小标题，可为空", "bullets": ["逐行讲解条目1", "条目2"], "note": "右上角红色注记，可为空"}}
  ],
  "tips": "写在用例页底部的一句提醒，20字以内",
  "summary": ["总结第1点", "第2点", "第3点"]
}}

要求：
- analysis 3~6 段，每段 60~140 字，讲清算法选择、状态/变量含义、关键步骤、复杂度与易错点；
- code_pages 1~3 页；每页 4~8 条，每条 15~45 字，按代码从上到下的顺序讲，不要贴大段代码；
- 不要逐行解释 #include、using namespace、return 0、大括号、变量声明这类模板代码；只讲关键变量/数据结构/核心循环/边界处理与易错点，短代码 3~5 条即可；
- 如果是填空题或程序补全题，要在讲解里明确指出每个空为什么这样填；
- tips 必须是一句有信息量的话；
- summary 恰好 3 条，每条约 30~60 字，面向“学习方法/易错点/举一反三”。
"""
    data = _json_chat(cfg, [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": user}])
    res = LLMResult()
    res.analysis = [str(x).strip() for x in data.get("analysis", []) if str(x).strip()]
    code = str(data.get("solution_code", "")).strip()
    code = re.sub(r"^```[\w+]*\s*", "", code)
    code = re.sub(r"\s*```$", "", code)
    res.solution_code = code
    for cp in data.get("code_pages", []) or []:
        bullets = [str(b).strip() for b in cp.get("bullets", []) if str(b).strip()]
        if bullets:
            res.code_pages.append(CodePage(
                heading=str(cp.get("heading", "")).strip(),
                bullets=bullets,
                note=str(cp.get("note", "")).strip(),
            ))
    res.tips = str(data.get("tips", "")).strip()
    res.summary = [str(x).strip() for x in data.get("summary", []) if str(x).strip()]
    if not res.analysis:
        raise RuntimeError("LLM 没有返回 analysis 字段")
    return _fp_result(res)


@dataclass
class UserCodeResult:
    correct: bool = True
    issues: list[str] = field(default_factory=list)
    analysis: list[str] = field(default_factory=list)
    code_pages: list[CodePage] = field(default_factory=list)
    tips: str = ""
    summary: list[str] = field(default_factory=list)
    fixed_code: str = ""


def generate_from_user_code(cfg: LLMConfig, p: Problem, code: str,
                            force_correct: bool = False) -> UserCodeResult:
    """校验学生代码，并按学生代码（或修正版）生成讲解。

    force_correct=True 表示这份代码已在本地通过全部公开样例，要求 AI 按正确代码讲解，
    不再判错（避免 AI 误判导致满分代码被改成“修正版”）。
    """
    user = f"""{_problem_digest(p)}

学生提交的代码：
```cpp
{code[:7000]}
```

请完成两件事：先判断这份代码是否正确（能否通过样例、边界情况、复杂度是否合理），再据此写讲解。
<<EXTRA>>
严格返回如下 JSON：
{{
  "correct": true,
  "issues": ["如果代码有问题，这里逐条列出，15~40字；没有问题就空数组"],
  "analysis": ["思路分析第1段", "第2段", "..."],
  "code_pages": [
    {{"heading": "这一页的小标题，可为空", "bullets": ["逐行讲解条目1", "条目2"], "note": "右上角红色注记，可为空"}}
  ],
  "tips": "写在用例页底部的一句提醒，20字以内",
  "summary": ["总结第1点", "第2点", "第3点"],
  "fixed_code": "correct=false 时给出修正后的完整 C++17 程序；correct=true 时留空字符串"
}}

要求：
- correct=false 时：issues 说清问题，fixed_code 必须是可直接编译运行的完整程序，code_pages 讲解修正版；
- correct=true 时：fixed_code 留空，code_pages 严格按学生代码的结构、变量名和语句顺序讲解，不要改写成另一份代码；
- analysis 3~6 段，每段 60~140 字，先点评学生思路，再讲算法、关键步骤、复杂度与易错点；
- code_pages 1~3 页，每页 4~8 条，每条 15~45 字；
- 不要讲 #include、using namespace、return 0、大括号这类模板代码；只讲关键变量、核心循环、边界与易错点；
- summary 恰好 3 条，每条约 30~60 字。
"""
    extra = ("这份代码已经在本地通过该题的全部公开样例，请视为正确代码，"
             "correct 必须为 true，issues 留空，fixed_code 留空，讲解严格按这份代码写。"
             if force_correct else
             "该题没有可用的公开样例，请只依据代码本身审查：只有出现确定的编译错误、"
             "数组越界、变量未初始化、死循环、明显逻辑错误时才判 correct=false；"
             "仅是写法风格、常数优化、内存偏大等建议不要判错，可写进 tips。")
    user = user.replace("<<EXTRA>>", extra)
    data = _json_chat(cfg, [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": user}])
    res = UserCodeResult()
    res.correct = True if force_correct else bool(data.get("correct", True))
    res.issues = [str(x).strip() for x in (data.get("issues") or []) if str(x).strip()]
    res.analysis = [str(x).strip() for x in (data.get("analysis") or []) if str(x).strip()]
    for cp in data.get("code_pages", []) or []:
        bullets = [str(b).strip() for b in cp.get("bullets", []) if str(b).strip()]
        if bullets:
            res.code_pages.append(CodePage(
                heading=str(cp.get("heading", "")).strip(),
                bullets=bullets,
                note=str(cp.get("note", "")).strip(),
            ))
    res.tips = str(data.get("tips", "")).strip()
    res.summary = [str(x).strip() for x in (data.get("summary") or []) if str(x).strip()]
    fixed = str(data.get("fixed_code", "")).strip()
    fixed = re.sub(r"^```[\w+]*\s*", "", fixed)
    fixed = re.sub(r"\s*```$", "", fixed)
    res.fixed_code = fixed
    if not res.analysis:
        raise RuntimeError("LLM 没有返回 analysis 字段")
    return _fp_result(res)


def annotate_code(cfg: "LLMConfig", title: str, code: str) -> str:
    """给用户上传的代码加行内注释，返回纯代码文本（失败返回空串）。"""
    user = (
        "下面是我写的一道 C++ 题的代码，题目是《" + title + "》。\n"
        "请在不改变任何一行代码逻辑、不删代码的前提下，给关键行加中文行尾注释 `// …`，"
        "并在文件开头加 3 行注释：题目、我的整体思路一句话、复杂度。\n"
        "要求：只输出代码本身，不要 markdown 代码围栏，不要额外解释。\n\n"
        + code
    )
    try:
        raw = chat(cfg, [{"role": "system", "content": "你是 C++ 代码注释助手，只输出代码。"},
                         {"role": "user", "content": user}], json_mode=False)
    except Exception:
        return ""
    txt = (raw or "").strip()
    if txt.startswith("```"):
        lines = txt.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        txt = "\n".join(lines).strip()
    return txt


def summarize_deck(cfg: LLMConfig, deck) -> list[str]:
    """为整份课件生成三条总结（若单题生成时已有总结，取并集）。"""
    names = "、".join(p.title for p in deck.problems)
    user = (
        f"这节小班课讲了这些题目：{names}。\n"
        "请写 3 条课堂总结，每条 30~60 字，分别侧重：方法共性、常见错误、学习建议。\n"
        '严格返回 JSON：{"summary": ["...", "...", "..."]}'
    )
    data = _json_chat(cfg, [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": user}])
    return [_fp_text(str(x).strip()) for x in data.get("summary", []) if str(x).strip()][:3]
