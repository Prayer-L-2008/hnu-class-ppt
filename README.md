# 湖大程序设计 · 小班课课件生成器

从 **湖南大学程序设计课程平台**（<https://cg.hnu.edu.cn>）按「作业 → 题型 → 题号」取题，
自动生成一份与 `第5次小班作业覃禹嘉.pptx` **同版式、同分区、同排版**的小班课课件；
「思路分析及原理 / 代码逐行讲解 / 用例讲解 / 总结」由大模型（任意 OpenAI 兼容 API）生成，
样例输出可用本机 g++ 真跑一遍再写回。

本项目有两种使用形态：

| 形态 | 入口 | 适合 |
| --- | --- | --- |
| **独立软件**（主体） | `run_gui.bat` → 浏览器打开 `http://127.0.0.1:8765` | 日常使用，五步向导，不依赖 DSH |
| **DSH 插件**（薄壳） | `plugin/` 目录，工具名 `hnu_class_ppt` | 在 DeepSeek Harness 对话里直接说“帮我做第五次小班课” |

两者共用同一个 Python 引擎，插件只负责把参数转成 CLI 调用，不存在两套实现。

> **v1.7 新增**：① AI 回复容错（自动截取 JSON、失败重试，不再出现 “Expecting value” 占位页）；
> ② 已选题目可给编程题上传自己的代码，先本地跑样例、再由 AI 核对并按你的代码讲解；
> ③ 生成后自动排版自检，文本框越界/溢出会自动缩字号或挪回页面内；
> ④ PPTX 旁边同时生成「下载代码包」，含 PPT 里所有编程题的 .cpp；
> ⑤ 安装程序带进度条，并用同款图标。
>
> v1.7.3 修复：平台题面里「【样例2解析】」后面的示例 `<pre>` 曾被误当成样例，导致满分代码被判“未通过样例”。

---

## 1. 快速开始（独立软件）

```bat
cd E:\_项目\DSH\hnu_ppt
run_gui.bat
```

浏览器会自动打开 <http://127.0.0.1:8765>，按页面五步走：

1. **登录 CG 平台** — 点「打开浏览器登录」，会弹出一个**独立的 Chrome/Edge 窗口**并停在登录页。
   在窗口里自己输入学号、密码、验证码；程序只读取登录后的 Cookie，**不保存密码**。
   登录成功状态点变绿后关掉该窗口即可。
2. **选择作业与题目** — 选课程 → 选作业 → 勾选要讲的题；题型默认按平台分区识别
   （编程题 / 填空题 / 单选题 / 接口编程题 / 程序补全），可在下拉框里改。也支持「手动添加」直接填 `assignID` + `proNum`。
3. **个人信息** — 第几次、第几组、第几号、班级、姓名、学号，下方实时预览封面效果。
   填一次就会记在本机浏览器里（`localStorage`），下次打开自动带出，换人再做时直接改。
4. **AI 接口** — 任意 OpenAI 兼容服务：Base URL、API Key、模型名。
   默认 `https://api.deepseek.com/v1` + `deepseek-chat`。留空也能生成，但分析页会是占位文字。
5. **生成** — 进度条走完点「下载 PPTX」。

生成文件默认在 `out/` 下，文件名形如 `第五次小班课.pptx`。

### 命令行等价用法

```bat
set PYTHONPATH=%cd%;%cd%\pylib

python -m hnuclass.cli login                 :: 浏览器辅助登录，Cookie 存到 %LOCALAPPDATA%\hnuclass\cookies.json
python -m hnuclass.cli courses               :: 列课程
python -m hnuclass.cli assignments --course 123
python -m hnuclass.cli problems --assign 456
python -m hnuclass.cli build --config examples\job.example.json --api-key sk-xxx
python -m hnuclass.cli demo --out out\示例_第五次小班课.pptx   :: 不需要账号，看版式
:: 生成时直接改封面信息（build / demo 都支持）
python -m hnuclass.cli demo --session 第六次 --group "第三组 12 号" --class "计科 2304" --name 张三 --sid 202308019999
python -m hnuclass.cli build --config examples\job.example.json --name 张三 --sid 202308019999
python -m hnuclass.cli gui --port 8765
```

`job.json` 的字段见 [examples/job.example.json](examples/job.example.json)：
`meta`（封面信息）、`problems[]`（assign_id/index/assignment/ptype/title）、
`llm`、`template`、`out`、`run_code`。

---

## 2. 生成出来的课件长什么样

严格复刻模板 `template.pptx`（30 页原稿的母版、主题、背景图、六边形目录、标题条全部保留）：

```
封面（深绿渐变 + POWERPOINT + 第 N 次小班课 + 组别/班级/姓名/学号）
目录（左侧六边形 CONTENTS，右侧 01/02/… 白底红虚线条目）
每个题目一组：
  ├─ N、问题 - 题名       题面（文本分页；平台题面是整张截图时直接等比铺图）
  ├─ N- 思路分析及原理     编号段落，20pt 起自动缩到放得下
  ├─ N- 代码逐行讲解 (P1)  分页讲变量/函数/边界，可带右上角红色注记条
  ├─ N- 代码逐行讲解 (P2)  …
  └─ N- 用例及运行结果     左上下两个用例框 + 右侧终端风格运行结果 + 底部提醒
小班分析与总结（三条）
```

排版细节与原稿一致：标题条 0.637in 高、白底黑字、2.25pt 暗红点划线、内阴影；
正文微软雅黑白色；代码/输出 Consolas；配色取自模板主题（accent1 `#B01513`）。
原稿里标题溢出压正文、目录第六条换行这类瑕疵，生成时会按字宽自动缩字号避开。

---

## 3. 目录结构

```
hnu_ppt/
├─ run_gui.bat                 启动独立软件
├─ run_cli.bat                 命令行入口
├─ install_plugin.bat          安装 DSH 插件
├─ requirements.txt            python-pptx / lxml / Pillow
├─ template.pptx               版式母版（原稿复制，生成时只读）
├─ source.pptx                 上传的原稿，供对照（不参与生成）
├─ hnuclass/
│  ├─ model.py                 Deck / Problem 数据模型
│  ├─ render.py                PPTX 渲染器（克隆母版、生成各分区）
│  ├─ textfit.py               PIL 真实字宽测量与折行估算
│  ├─ cg.py                    CG 平台客户端 + 题面 HTML 解析（描述/输入/输出/样例/图片）
│  ├─ browser_login.py         CDP 拉起独立浏览器并抓 Cookie（验证码由用户手输）
│  ├─ parse_problem.py         题面 HTML → 问题描述/输入/输出/样例/图片
│  ├─ llm.py                   OpenAI 兼容接口，产出分析/代码页/提醒/总结
│  ├─ runner.py                g++ 编译并跑样例，拿真实输出
│  ├─ pipeline.py              抓题 → 生成 → 渲染 的编排
│  ├─ cli.py                   命令行入口
│  ├─ gui.py                   本地 Web GUI（标准库 http.server）
│  └─ demo.py                  内置两题示例
├─ web/index.html              五步向导前端
├─ examples/job.example.json
├─ tests/sample_problem.html
└─ plugin/                     DSH 插件薄壳
   ├─ index.js
   └─ package.json
```

依赖：Python 3.10+（本机 3.13）、`python-pptx`、`lxml`、`Pillow`；
可选 g++（`C:\Program Files (x86)\Dev-Cpp\MinGW32\bin\g++.exe`）用于真跑样例。
`pylib/` 是随包携带的依赖目录，`hnuclass/__init__.py` 会自动把它加进 `sys.path`，所以直接
`python -m hnuclass.cli ...` 即可，不必配环境变量。

安装依赖（任选）：

```bat
pip install -r requirements.txt
:: 或把 wheel 解压到 pylib/（本机 pip 受临时目录 ACL 限制时用这个办法）
```

---

## 4. 接入 AI API

任何兼容 OpenAI Chat Completions 的服务都能用：

```json
"llm": {
  "base_url": "https://api.deepseek.com/v1",
  "api_key": "sk-...",
  "model": "deepseek-chat",
  "temperature": 0.3
}
```

引擎要求模型返回 JSON：
`analysis`（3~6 段）、`solution_code`、`code_pages`（1~3 页，每页 4~8 条）、
`tips`（≤20 字）、`summary`（恰好 3 条）。失败会自动重试一次（去掉 `response_format`），
仍失败则该题降级为占位页并在结果里给出 warning，不会中断整份课件。

> 说明：题面和样例来自平台，属于“取”；分析与逐行讲解属于“讲”，必须由模型生成，
> 所以没有 API Key 时只能得到版式正确、内容占位的草稿。

---

## 5. 作为 DSH 插件安装

插件在 `plugin/`，工具名 `hnu_class_ppt`，参数：

```json
{ "action": "build", "config": { "meta": {...}, "problems": [...] } }
```

`action` 可取 `login | courses | assignments | problems | build | demo`。

安装（在 `hnu_ppt` 目录下）：

```bat
install_plugin.bat
:: 等价于 dsh plugin --profile desktop add "file:E:\_项目\DSH\hnu_ppt\plugin"
```

然后在 `C:\Users\Prayer_L\.dsh\profiles\desktop\cordis.patch.yml` 追加：

```yaml
- id: hnu-class-ppt
  name: dsh-hnu-class-ppt
```

重启 DSH 后即可在对话里让 Agent 调用。插件通过 `HNUCLASS_HOME` 或 `config.engineDir`
找到引擎目录（默认取当前工作目录），并用同一个 Python 解释器执行 CLI。

---

## 6. 已知限制

- **验证码**：CG 登录必须手输验证码，所以第一次登录一定要走「浏览器辅助登录」，
  程序不碰账号密码。Cookie 有效期由平台决定，过期后重新点一次登录即可。
- **题型判断**：平台作业名并不总是规范（“函数(强化)”“指针 片段1”），引擎按关键词猜，
  GUI 里可以逐题改。
- **题面是图片**：部分题目整页是截图，生成时会整图铺页，不再拆分输入/输出。
- **样例输出**：开了 `run_code` 且本机有 g++ 时用真实运行结果覆盖平台样例；
  代码需要补全的题（填空/片段）跑不通时会保留平台样例并标注。
- **打包 exe**：可用 PyInstaller `--add-data "template.pptx;." --add-data "web;web"`，
  入口 `hnuclass.cli gui`；未在本仓库内置打包脚本，避免把 2MB 模板和依赖塞进 Git。

---

## 7. 故障排查

| 现象 | 处理 |
| --- | --- |
| 点登录没反应 | 检查 `C:\Program Files\Google\Chrome\Application\chrome.exe` 是否存在；端口 9333 被占用时换 `--port` |
| 一直显示未登录 | 浏览器窗口里是否真的进了 `main.jsp`；平台有时要二次跳转，登录后刷新一次 |
| 生成报“未登录/会话过期” | 重新执行 `python -m hnuclass.cli login` |
| 中文变宋体/方框 | 系统需有 `C:\Windows\Fonts\msyh.ttc`、`msyhbd.ttc`（Win10/11 自带） |
| 想先看版式 | `python -m hnuclass.cli demo`，不需要账号和 API |

## 常见问题

**“作业”下拉框只有一个“选择作业”？**
先在上面的“课程”里选一门课。程序会用 POST 切到那门课（平台的切课表单），再异步拉作业列表；
切完课后下拉框会自动出现该课程下的作业。若仍然为空，通常是登录态过期，重新点“打开浏览器登录”。

**可以跨作业选题吗？**
可以。每次勾选都会进入第 2 张卡下方的「已选题目」清单，切换作业不会清空；
清单里按选择顺序列出 作业 / 题号 / 题型 / 题目，可单条“移除”或一键“清空”。
生成时按清单顺序编号，第 1 条就是课件里的第 1 题。

**选完作业后还要再点“加载题目”吗？**
v1.2 起不用：选中作业即自动拉取题目表格；题型（编程题/填空题/程序补全…）会自动识别，可在下拉里改。

**填空 / 选择 / 接口编程 / 程序补全题都能抓吗？**
能。平台按题型分成几个分区，程序逐区识别：
- 编程题：`programList.jsp` / `problemContent.jsp`
- 接口编程题：`programWithInterfaceList.jsp`（`via=interface`）
- 程序补全题：`programFillGapList.jsp`（`via=fill`，会解析 `cgcode` 代码模板和空位）
- 填空题 / 单选题：题面直接内联在 `index.jsp` 的表格里，没有单独链接，
  程序会把输入框换成 `____` 后抽成题干（`via=cloze`），题型记为填空题或单选题。
填空/选择没有输入输出样例，生成的课件会跳过「用例及运行结果」页。
题目列表里每条填空题右侧有「展开题面」，点开可看完整题干（含代码、`____` 空位），再点「收起题面」折叠。

**API Key 会保存吗？每次都要重填吗？**
不用重填。第一次填入后自动保存，下次打开：
- 输入框显示「已保存，留空即使用」，直接点生成就会用保存的 Key；
- 模型列表也会用保存的 Key 自动拉取；
- 要换 Key，直接输入新的覆盖；点「清除」则删掉保存的 Key。
Key 用 Windows DPAPI 以当前用户加密后存在 `%LOCALAPPDATA%\hnuclass\settings.json`，
文件里没有明文，页面也不会回显已保存的 Key。

**DeepSeek 的 Key 去哪拿？**
「AI 接口」那一行右侧有「DeepSeek API 官网 ↗」直达按钮。把 Key 粘进 API Key 输入框，
程序会自动请求 `{Base URL}/models`，把可用模型填进“模型”下拉（默认 deepseek-chat）。

**没有配置 AI 接口能生成吗？**
能生成完整排版，但“思路分析”“代码逐行讲解”会是提示占位页；填入任意 OpenAI 兼容接口后重新生成即可。
