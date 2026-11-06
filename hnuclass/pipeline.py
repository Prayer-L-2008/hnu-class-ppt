# -*- coding: utf-8 -*-
"""编排：抓题 -> AI 讲解 -> 本地跑代码 -> 渲染 PPTX。"""
from __future__ import annotations

import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from .cg import CGClient, CGError, ProblemRef, guess_kind, parse_problem
from .llm import LLMConfig, generate as llm_generate, summarize_deck
from .model import Deck, Problem
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
    warnings: list[str] = []
    summary_bits: list[str] = []

    for i, spec in enumerate(job.problems):
        tag = f"P{i+1}"
        progress(f"[{i+1}/{total}] 抓取《{spec.title or spec.assignment or spec.index}》…",
                 0.05 + 0.9 * i / total)
        try:
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

        if job.llm.ready:
            progress(f"[{i+1}/{total}] AI 生成《{p.title}》的思路与逐行讲解…",
                     0.1 + 0.9 * i / total)
            try:
                res = llm_generate(job.llm, p)
                p.analysis = res.analysis
                p.code_pages = res.code_pages
                p.tips = res.tips
                p.code = res.solution_code or p.code
                if res.summary:
                    summary_bits = res.summary
                if job.run_code and res.solution_code and p.samples:
                    run = compile_and_run(res.solution_code, p.samples)
                    if run.ok:
                        for n, out in enumerate(run.outputs):
                            if n < len(p.samples):
                                p.samples[n].output = out
                        p.run_output = run.outputs[0] if run.outputs else ""
                    elif run.stderr:
                        warnings.append(f"{p.title} 参考代码运行失败：{run.stderr.splitlines()[0][:120]}")
            except Exception as e:
                warnings.append(f"{p.title} AI 生成失败：{e}")
        else:
            p.analysis = ["（未配置 LLM API：请在软件「AI 设置」里填入 base_url / api_key / model 后重新生成，"
                          "本页会自动写入完整的思路分析。）"]
            p.tips = "配置 AI 接口后，这里会给出针对本题的提醒。"

        deck.problems.append(p)

    if job.llm.ready and not summary_bits:
        try:
            summary_bits = summarize_deck(job.llm, deck)
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
    for w in warnings:
        progress("⚠ " + w)
    progress(f"完成：{job.out}", 1.0)
    return job.out
