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
        "max_tokens": 4096,
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
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        raise RuntimeError(f"无法解析 LLM 返回：{json.dumps(data, ensure_ascii=False)[:500]}")


def parse_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        s, e = text.find("{"), text.rfind("}")
        if s >= 0 and e > s:
            return json.loads(text[s:e + 1])
        raise


SYSTEM = (
    "你是湖南大学《程序设计》课程的小班课助教，负责把一道在线评测题讲清楚。"
    "你的读者是大一/大二学生，讲解要具体、口语化、循序渐进，避免空话。"
    "所有输出必须是合法 JSON，不要输出 JSON 以外的任何文字。"
)


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
- 如果是填空题或程序补全题，要在讲解里明确指出每个空为什么这样填；
- tips 必须是一句有信息量的话；
- summary 恰好 3 条，每条约 30~60 字，面向“学习方法/易错点/举一反三”。
"""
    raw = chat(cfg, [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": user}])
    data = parse_json(raw)
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
    return res


def summarize_deck(cfg: LLMConfig, deck) -> list[str]:
    """为整份课件生成三条总结（若单题生成时已有总结，取并集）。"""
    names = "、".join(p.title for p in deck.problems)
    user = (
        f"这节小班课讲了这些题目：{names}。\n"
        "请写 3 条课堂总结，每条 30~60 字，分别侧重：方法共性、常见错误、学习建议。\n"
        '严格返回 JSON：{"summary": ["...", "...", "..."]}'
    )
    raw = chat(cfg, [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": user}])
    data = parse_json(raw)
    return [str(x).strip() for x in data.get("summary", []) if str(x).strip()][:3]
