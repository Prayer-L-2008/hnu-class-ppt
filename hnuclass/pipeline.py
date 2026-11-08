# -*- coding: utf-8 -*-
"""编排：抓题 -> AI 讲解 -> 本地跑代码 -> 渲染 PPTX。"""
from __future__ import annotations

import os
import zipfile
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from .cg import CGClient, CGError, ProblemRef, guess_kind, parse_problem
from .llm import LLMConfig, generate as llm_generate, summarize_deck
from .model import Case, Deck, Problem
from .render import render_deck
from .runner import compile_and_run


class Progress:
    def __init__(self, fn=None):
        self.fn = fn or (lambda *a, **k: None)

    def __call__(self, message: str, frac: float | None = None) -> None:
        self.fn(message, frac)


@dataclass
class ProblemSpec:
    assign_id: str
    index: str
    assignment: str = ""
    ptype: str = ""
    title: str = ""
    problem_id: str = ""
    via: str = ""
    user_code: str = ""
    oj: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "ProblemSpec":
        return cls(
            assign_id=str(d.get("assign_id") or d.get("assignID") or ""),
            index=str(d.get("index") or d.get("proNum") or ""),
            assignment=d.get("assignment", ""),
            ptype=d.get("ptype", ""),
            title=d.get("title", ""),
            problem_id=str(d.get("problem_id", "")),
            via=d.get("via", ""),
            user_code=str(d.get("user_code", "")),
            oj=d.get("oj") or {},
        )


@dataclass
class BuildJob:
    meta: dict
    problems: list[ProblemSpec]
    llm: LLMConfig
    template: str
    out: str
    run_code: bool = True
    workdir: str = ""

    @classmethod
    def from_dict(cls, d: dict, base_dir: str = ".") -> "BuildJob":
        meta = dict(d.get("meta") or {})
        probs = [ProblemSpec.from_dict(x) for x in d.get("problems", [])]
        if not probs:
            raise ValueError("problems 为空：请至少指定一道题。")
        tpl = d.get("template") or "template.pptx"
        out = d.get("out") or "小班课件.pptx"
        return cls(
            meta=meta, problems=probs,
            llm=LLMConfig.from_dict(d.get("llm")),
            template=tpl if os.path.isabs(tpl) else os.path.join(base_dir, tpl),
            out=out if os.path.isabs(out) else os.path.join(base_dir, out),
            run_code=bool(d.get("run_code", True)),
            workdir=d.get("workdir") or "",
        )


def _download_image(client: CGClient, src: str, dest_dir: str, tag: str) -> str:
    if not src or src.startswith("data:"):
        return ""
    url = src if src.startswith("http") else client.base + ("" if src.startswith("/") else "/") + src
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".bmp"):
        ext = ".png"
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"{tag}{ext}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                                   "Cookie": "; ".join(f"{k}={v}" for k, v in client.cookies.items())})
        with urllib.request.urlopen(req, timeout=25,
                                    context=client.ctx) as r, open(dest, "wb") as f:
            f.write(r.read())
        return dest
    except Exception:
        return ""


def _samples_pass(code: str, samples, workdir: str | None = None) -> bool:
    """本地编译并逐用例比对；没有样例时视为无法验证。"""
    if not code or not samples:
        return False
    run = compile_and_run(code, samples, workdir=workdir)
    if not run.ok or len(run.outputs) < len(samples):
        return False
    for n, got in enumerate(run.outputs):
        exp = (samples[n].output or "").strip().replace("\r", "").rstrip()
        if not exp:
            continue
        if got.strip().replace("\r", "").rstrip() != exp:
            return False
    return True



def _write_code_zip(deck: Deck, out_path: str) -> str:
    """把 PPT 里编程题的 C++ 代码打包，放在 PPTX 旁边。"""
    progs = [p for p in deck.problems if p.ptype == "编程题" and (p.code or "").strip()]
    if not progs:
        return ""
    # 只有存在“未上传代码 / 审查未通过改用 AI 解法”的编程题时才需要代码包
    if all((p.code_source or "") == "user" for p in progs):
        return ""
    path = os.path.splitext(out_path)[0] + "_代码.zip"
    used = set()
    try:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for p in progs:
                base = re.sub(r'[\\/:*?"<>|\r\n]+', "_", f"{p.number}. {p.title}").strip()[:60]
                name = base + ".cpp"
                i = 2
                while name in used:
                    name = f"{base}({i}).cpp"; i += 1
                used.add(name)
                z.writestr(name, p.code)
    except Exception:
        return ""
    return path


def build(job: BuildJob, client: CGClient, progress: Progress | None = None) -> str:
    progress = progress or Progress()
    deck = Deck(
        session=job.meta.get("session", "小班课"),
        group=job.meta.get("group", ""),
        klass=job.meta.get("klass", ""),
        name=job.meta.get("name", ""),
        student_id=job.meta.get("student_id", ""),
        problems=[],
        summary=[],
    )
    total = len(job.problems)
    workdir = os.path.dirname(os.path.abspath(job.out))
    warnings: list[str] = []
    summary_bits: list[str] = []

    for i, spec in enumerate(job.problems):
        tag = f"P{i+1}"
        progress(f"[{i+1}/{total}] 抓取《{spec.title or spec.assignment or spec.index}》…",
                 0.05 + 0.9 * i / total)
        try:
            if spec.oj:
                o = spec.oj
                p = Problem(
                    number=0,
                    assignment=o.get("source", "外源题目"),
                    ptype="编程题",
                    title=o.get("title", ""),
                    index=spec.index,
                    problem_id=o.get("url", ""),
                    url=o.get("url", ""),
                    description=o.get("description", ""),
                    input_form=o.get("input_form", ""),
                    output_form=o.get("output_form", ""),
                    samples=[Case(a, b) for a, b in o.get("samples", [])],
                    tips=o.get("note", ""),
                )
            else:
                html = client.problem_html(spec.assign_id, spec.index, spec.problem_id, spec.via)
                meta = ProblemRef(index=spec.index, problem_id=spec.problem_id, title=spec.title)
                p = parse_problem(html, spec.assign_id, spec.index, meta)
        except Exception as e:
            warnings.append(f"{spec.title or spec.index} 抓取失败：{e}")
            p = Problem(number=0, assignment=spec.assignment, ptype=spec.ptype or "编程题",
                        title=spec.title or f"题目{spec.index}", index=spec.index,
                        problem_id=spec.problem_id,
                        description=f"（抓取失败：{e}）")
        p.assignment = spec.assignment or p.assignment
        p.ptype = spec.ptype or p.ptype or guess_kind(p.title, p.assignment)
        p.title = p.title or spec.title

        if p.images:
            local = []
            for n, src in enumerate(p.images):
                got = _download_image(client, src, os.path.join(os.path.dirname(job.out), "images"),
                                      f"p{i+1}_{n+1}")
                if got:
                    local.append(got)
            p.images = local

        p.user_code = (spec.user_code or "").strip()
        if job.llm.ready:
            progress(f"[{i+1}/{total}] AI 生成《{p.title}》的思路与逐行讲解…",
                     0.1 + 0.9 * i / total)
            try:
                used_user = False
                if p.user_code and p.ptype == "编程题":
                    has_samples = bool(p.samples)
                    if has_samples and not _samples_pass(p.user_code, p.samples, workdir):
                        warnings.append(f"{p.title} 你提交的代码未通过样例，已改用 AI 解法")
                        p.code_note = "我提交的代码未通过样例，本页改用 AI 给出的解法"
                    else:
                        from .llm import generate_from_user_code
                        if not has_samples:
                            chk = compile_and_run(p.user_code, [], workdir=workdir)
                            if not chk.ok:
                                warnings.append(f"{p.title} 你提交的代码编译失败，已改用 AI 解法")
                                p.code_note = "我提交的代码本地编译失败，本页改用 AI 解法"
                                res = None
                            else:
                                res = generate_from_user_code(job.llm, p, p.user_code,
                                                              force_correct=False)
                        else:
                            res = generate_from_user_code(job.llm, p, p.user_code,
                                                          force_correct=True)
                        if res is not None:
                            if has_samples:
                                res.correct = True
                            p.analysis = res.analysis
                            p.code_pages = res.code_pages
                            p.tips = res.tips
                            if res.summary:
                                summary_bits = res.summary
                            if res.correct:
                                p.code = p.user_code
                                p.code_source = "user"
                                p.code_note = ("本页讲解依据我提交的代码" if has_samples
                                               else "本页讲解依据我提交的代码（该站未提供样例，未做样例校验）")
                                used_user = True
                            else:
                                issues = "；".join(res.issues[:2])
                                fixed_ok = bool(res.fixed_code) and compile_and_run(
                                    res.fixed_code, p.samples or [], workdir=workdir).ok
                                if fixed_ok:
                                    p.code = res.fixed_code
                                    p.code_source = "ai_fixed"
                                    p.code_note = ("我提交的代码未完全正确" +
                                                   (f"（{issues}）" if issues else "") +
                                                   "，以下为修正版" + ("（该站无样例，未做样例校验）" if not has_samples else ""))
                                    used_user = True
                                else:
                                    p.code = p.user_code
                                    p.code_source = "user"
                                    p.code_note = ("AI 审查提示：" + (issues or "可能存在问题") +
                                                   "；该站未提供样例，仍按我提交的代码讲解")
                                    warnings.append(f"{p.title} AI 审查认为代码可能有问题：{issues or '未说明'}")
                                    used_user = True

                if (not used_user and p.ptype == "编程题" and p.problem_id
                        and not spec.oj and spec.assign_id):
                    sub = None
                    try:
                        sub = client.submission(spec.assign_id, p.problem_id)
                    except Exception as e:
                        warnings.append(f"{p.title} 读取提交记录失败：{e}")
                    if sub and sub.code and sub.full and _samples_pass(sub.code, p.samples, workdir):
                        from .llm import generate_from_user_code
                        progress(f"[{i+1}/{total}] 使用提交记录中的满分代码讲解《{p.title}》…",
                                 0.1 + 0.9 * i / total)
                        res2 = generate_from_user_code(job.llm, p, sub.code, force_correct=True)
                        res2.correct = True
                        p.analysis = res2.analysis
                        p.code_pages = res2.code_pages
                        p.tips = res2.tips
                        if res2.summary:
                            summary_bits = res2.summary
                        if res2.correct:
                            p.code = sub.code
                            p.code_source = "submission"
                            p.code_note = (f"本页讲解依据我提交记录中的满分代码"
                                           f"（{sub.when}，{sub.score:g} 分）")
                            used_user = True
                        elif res2.fixed_code and _samples_pass(res2.fixed_code, p.samples, workdir):
                            p.code = res2.fixed_code
                            p.code_source = "ai_fixed"
                            p.code_note = "提交记录中的代码未完全正确，以下为修正版"
                            used_user = True
                    elif sub:
                        warnings.append(
                            f"{p.title} 提交记录最近一次 {sub.score:g}/{sub.max_score:g} 分，"
                            "不是满分，已改用 AI 解法")

                if not used_user:
                    res = llm_generate(job.llm, p)
                    p.analysis = res.analysis
                    p.code_pages = res.code_pages
                    p.tips = res.tips
                    p.code = res.solution_code or p.code
                    if p.code_source != "ai_fixed":
                        p.code_source = "ai"
                    if res.summary:
                        summary_bits = res.summary

                if job.run_code and p.code and p.samples:
                    run = compile_and_run(p.code, p.samples, workdir=workdir)
                    if run.ok:
                        for n, out in enumerate(run.outputs):
                            if n < len(p.samples):
                                p.samples[n].output = out
                        p.run_output = run.outputs[0] if run.outputs else ""
                    elif run.stderr:
                        warnings.append(f"{p.title} 参考代码运行失败：{run.stderr.splitlines()[0][:120]}")
                if p.code_note and p.code_pages:
                    p.code_pages[0].note = p.code_note
            except Exception as e:
                warnings.append(f"{p.title} AI 生成失败：{e}")
        else:
            p.analysis = ["（未配置 LLM API：请在软件「AI 设置」里填入 base_url / api_key / model 后重新生成，"
                          "本页会自动写入完整的思路分析。）"]
            p.tips = "配置 AI 接口后，这里会给出针对本题的提醒。"

        deck.problems.append(p)

    if job.llm.ready:
        try:
            summary_bits = summarize_deck(job.llm, deck) or summary_bits
        except Exception as e:
            warnings.append(f"总结生成失败：{e}")
    if not summary_bits:
        summary_bits = [
            "先把题意转成模型：明确状态、转移和边界，再动手写代码。",
            "样例通过不等于正确，要主动构造边界与极端数据检验程序。",
            "做完一题要复盘：这类题的共同套路是什么，下次遇到从哪里下手。",
        ]
    deck.summary = summary_bits[:3]

    progress("渲染 PPTX…", 0.97)
    render_deck(deck, job.out, job.template)
    _write_code_zip(deck, job.out)
    try:
        from .layoutcheck import audit
        layout_issues = audit(job.out, fix=True)
        warnings.extend(layout_issues[:6])
        if layout_issues:
            progress(f"排版自检：自动调整了 {len(layout_issues)} 处文本框")
    except Exception as e:
        warnings.append(f"排版自检失败：{e}")
    for w in warnings:
        progress("⚠ " + w)
    progress(f"完成：{job.out}", 1.0)
    return job.out
