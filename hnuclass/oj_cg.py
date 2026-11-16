"""把力扣这类“函数式评测”的题，转写成湖大 CG 风格的标准输入输出题。

思路：
1. 让模型给出 CG 输入/输出格式、参考程序、包装了用户代码的完整程序；
2. 用官方示例（转成 CG 输入）跑参考程序，得到标准输出；
3. 用同一批官方输入跑用户程序，逐组比对（exact 或 any_valid 合法性判定）；
4. 用户代码正确时，用模型新造的输入喂用户程序，实跑得到用例输出。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .llm import LLMConfig, _json_chat
from .model import Case
from .runner import compile_and_run


class OJConvertError(RuntimeError):
    pass


@dataclass
class CGResult:
    input_format: str = ""
    output_format: str = ""
    samples: list[Case] = field(default_factory=list)
    user_ok: bool = False
    check_mode: str = "exact"
    reference_code: str = ""
    user_program: str = ""
    note: str = ""


_SYS = (
    "你是算法竞赛教练，负责把力扣（LeetCode）风格的函数题改写成"
    "湖南大学 CG 平台的标准输入输出题。只输出合法 JSON，不要任何解释。"
)

_USER_TMPL = """题目：{title}

题面：
{desc}

力扣官方示例（函数式写法，仅供参考）：
{samples}

用户提交的代码（可能为空）：
```cpp
{user_code}
```

请完成：
1. input_format / output_format：用中文描述 CG 平台的输入输出格式（第一行…第二行…），
   要求能用 stdin 唯一确定输入；字符串题可用“第一行长度 L，第二行字符串”。
2. ref_code：完整可编译的 C++17 参考程序，严格按 input_format 读入、输出答案。
3. check_mode：答案唯一写 "exact"；答案可能不唯一（如最长回文子串）写 "any_valid"。
4. official：把上面的力扣官方示例逐条改写成 CG 输入，字段 input / expected（expected 可留空）。
5. inputs：新造 2~3 组**普通**输入（规模小、含边界，不要极端大数），只给 input。
6. user_program：若用户代码非空，把用户函数**原样嵌入**一个完整程序（只加 include/main/
   读入与输出，函数体逻辑一行不改）；为空则给空串。

输出 JSON：
{{"input_format":"","output_format":"","ref_code":"","check_mode":"exact",
 "official":[{{"input":"","expected":""}}],"inputs":[""],"user_program":""}}"""


_JUDGE_SYS = "你是严谨的算法题裁判，只输出 JSON。"


def _pair(s) -> tuple[str, str]:
    if isinstance(s, (list, tuple)):
        return str(s[0]), str(s[1] if len(s) > 1 else "")
    return str(getattr(s, "input", "")), str(getattr(s, "output", ""))


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _run(code: str, inputs: list[str], workdir: str | None):
    cases = [Case(i, "") for i in inputs]
    res = compile_and_run(code, cases, timeout=8, workdir=workdir)
    if not res.ok:
        raise OJConvertError("编译失败：" + (res.stderr or "")[:300])
    return [o for o in res.outputs]


def _valid_any(cfg: LLMConfig, desc: str, inp: str, got: str, expected: str = "") -> bool:
    msg = f"""题目：
{desc[:2500]}

输入：
{inp}

待判输出：
{got}

标准答案（可能只是其中一种合法解）：
{expected}

请判断“待判输出”是否是这道题在该输入下的合法输出（答案不唯一时，只要满足题意即可）。
只输出 JSON：{{"valid": true/false, "reason": "一句话"}}"""
    try:
        data = _json_chat(cfg, [{"role": "system", "content": _JUDGE_SYS},
                                {"role": "user", "content": msg}], tries=1)
        return bool(data.get("valid"))
    except Exception:
        return _norm(got) == _norm(expected)


def convert(cfg: LLMConfig, problem: dict, user_code: str = "",
            workdir: str | None = None) -> CGResult:
    """problem 为 oj.fetch_problem 的 dict。"""
    if not getattr(cfg, "ready", False):
        raise OJConvertError("未配置 LLM")

    desc = (problem.get("description") or "")[:6000]
    samples_txt = "\n".join(
        "输入：{}\n输出：{}".format(*_pair(s)) for s in (problem.get("samples") or [])
    )
    prompt = _USER_TMPL.format(
        title=problem.get("title", ""), desc=desc,
        samples=samples_txt or "（无）",
        user_code=(user_code or "").strip(),
    )
    data = _json_chat(cfg, [{"role": "system", "content": _SYS},
                            {"role": "user", "content": prompt}], tries=2)

    ref = (data.get("ref_code") or "").strip()
    if not ref:
        raise OJConvertError("模型没有给出参考程序")
    input_format = (data.get("input_format") or "").strip()
    output_format = (data.get("output_format") or "").strip()
    check_mode = (data.get("check_mode") or "exact").strip()

    official = data.get("official") or []
    off_inputs = [str(o.get("input", "")).strip() for o in official if str(o.get("input", "")).strip()]
    if not off_inputs:
        raise OJConvertError("模型没有给出官方示例的 CG 输入")

    ref_out = _run(ref, off_inputs, workdir)

    user_ok = False
    user_prog = (data.get("user_program") or "").strip()
    if user_code.strip() and user_prog:
        try:
            got = _run(user_prog, off_inputs, workdir)
            ok = True
            for idx, (a, b) in enumerate(zip(got, ref_out)):
                if _norm(a) == _norm(b):
                    continue
                if check_mode == "any_valid":
                    if _valid_any(cfg, desc, off_inputs[idx], a, b):
                        continue
                ok = False
                break
            user_ok = ok
        except Exception:
            user_ok = False

    new_inputs = [str(x).strip() for x in (data.get("inputs") or []) if str(x).strip()]
    if not new_inputs:
        raise OJConvertError("模型没有给出新用例输入")

    base_out = _run(ref, new_inputs, workdir)
    samples: list[Case] = []
    user_out: list[str] = []
    if user_ok and user_prog:
        try:
            user_out = _run(user_prog, new_inputs, workdir)
        except Exception:
            user_out = []

    for idx, inp in enumerate(new_inputs[:3]):
        out = base_out[idx]
        if idx < len(user_out):
            if _norm(user_out[idx]) == _norm(out):
                out = user_out[idx]
            elif check_mode == "any_valid" and _valid_any(cfg, desc, inp, user_out[idx], out):
                out = user_out[idx]
        samples.append(Case(inp, out))

    # 再补一组官方示例，凑够 3 组
    if len(samples) < 3:
        samples.append(Case(off_inputs[0], ref_out[0]))

    return CGResult(input_format=input_format, output_format=output_format,
                    samples=samples, user_ok=user_ok, check_mode=check_mode,
                    reference_code=ref, user_program=user_prog,
                    note="力扣题已转写为 CG 输入输出")
