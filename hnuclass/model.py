# -*- coding: utf-8 -*-
"""数据模型：一套与渲染器解耦的 deck 描述。

整个软件只认这些 dataclass：抓题模块产出 Problem，内容模块填充
analysis / code_pages / run_output，渲染模块消费 Deck。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Case:
    """一组用例。input/output 为原始文本（保留换行）。"""
    input: str = ""
    output: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Case":
        return cls(input=str(d.get("input", "")), output=str(d.get("output", "")))


@dataclass
class CodePage:
    """代码逐行讲解的一页。heading 可选（如“全局变量”）。"""
    heading: str = ""
    bullets: list[str] = field(default_factory=list)
    note: str = ""            # 右上红色注记框

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CodePage":
        return cls(
            heading=str(d.get("heading", "")),
            bullets=[str(x) for x in d.get("bullets", [])],
            note=str(d.get("note", "")),
        )


@dataclass
class Problem:
    number: int = 0                    # 在本次小班课中的序号，从 1 开始
    assignment: str = ""               # 作业名，如“指针”“函数(强化)”
    ptype: str = ""                    # 填空 / 选择 / 编程题 / 程序补全 …
    title: str = ""                    # 题目标题
    index: int = 0                     # 题目在作业中的题号
    problem_id: int = 0                # 平台 problemID（有则记录）
    url: str = ""

    # 抓取到的题面
    description: str = ""
    input_form: str = ""
    output_form: str = ""
    samples: list[Case] = field(default_factory=list)
    code: str = ""                     # 题目自带代码/模板（填空、补全题）
    images: list[str] = field(default_factory=list)   # 题面截图本地路径
    raw_html: str = ""

    # LLM / 人工补充
    analysis: list[str] = field(default_factory=list)         # 段落
    code_pages: list[CodePage] = field(default_factory=list)
    run_output: str = ""
    tips: str = ""                     # 用例页底部小注
    user_code: str = ""                # 学生自己上传的代码（可选）
    code_source: str = ""              # user / ai / ai_fixed
    code_note: str = ""                # 代码页上的来源说明

    # ---------- 便捷属性 ----------
    @property
    def display_name(self) -> str:
        """目录与标题里显示的名字。"""
        a, t = self.assignment.strip(), self.title.strip()
        if not a:
            return t
        if not t:
            return a
        if t.startswith(a) or a in t:
            return t
        return f"{a} {t}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "assignment": self.assignment,
            "ptype": self.ptype,
            "title": self.title,
            "index": self.index,
            "problem_id": self.problem_id,
            "url": self.url,
            "description": self.description,
            "input_form": self.input_form,
            "output_form": self.output_form,
            "samples": [{"input": c.input, "output": c.output} for c in self.samples],
            "code": self.code,
            "images": list(self.images),
            "analysis": list(self.analysis),
            "code_pages": [
                {"heading": p.heading, "bullets": p.bullets, "note": p.note}
                for p in self.code_pages
            ],
            "run_output": self.run_output,
            "tips": self.tips,
            "user_code": self.user_code,
            "code_source": self.code_source,
            "code_note": self.code_note,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Problem":
        return cls(
            number=int(d.get("number", 0)),
            assignment=str(d.get("assignment", "")),
            ptype=str(d.get("ptype", "")),
            title=str(d.get("title", "")),
            index=int(d.get("index", 0)),
            problem_id=int(d.get("problem_id", 0)),
            url=str(d.get("url", "")),
            description=str(d.get("description", "")),
            input_form=str(d.get("input_form", "")),
            output_form=str(d.get("output_form", "")),
            samples=[Case.from_dict(x) for x in d.get("samples", [])],
            code=str(d.get("code", "")),
            images=[str(x) for x in d.get("images", [])],
            analysis=[str(x) for x in d.get("analysis", [])],
            code_pages=[CodePage.from_dict(x) for x in d.get("code_pages", [])],
            run_output=str(d.get("run_output", "")),
            tips=str(d.get("tips", "")),
            user_code=str(d.get("user_code", "")),
            code_source=str(d.get("code_source", "")),
            code_note=str(d.get("code_note", "")),
        )


@dataclass
class Deck:
    session: str = "第五次"            # 只写“第五次”，渲染时补“小班课”
    group: str = "第二组 3 号"
    klass: str = "计科 2304"
    name: str = "覃禹嘉"
    student_id: str = "202308010423"
    problems: list[Problem] = field(default_factory=list)
    summary: list[str] = field(default_factory=list)

    @property
    def cover_title(self) -> str:
        s = self.session.strip()
        return s if s.endswith("小班课") else f"{s}小班课"

    def to_dict(self) -> dict[str, Any]:
        return {
            "session": self.session,
            "group": self.group,
            "klass": self.klass,
            "name": self.name,
            "student_id": self.student_id,
            "problems": [p.to_dict() for p in self.problems],
            "summary": list(self.summary),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Deck":
        return cls(
            session=str(d.get("session", "第五次")),
            group=str(d.get("group", "")),
            klass=str(d.get("klass", "")),
            name=str(d.get("name", "")),
            student_id=str(d.get("student_id", "")),
            problems=[Problem.from_dict(x) for x in d.get("problems", [])],
            summary=[str(x) for x in d.get("summary", [])],
        )
