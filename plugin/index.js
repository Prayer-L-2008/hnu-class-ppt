/**
 * DSH 插件：湖南大学程序设计小班课课件生成器。
 *
 * 这是一个“薄壳”：真正的抓题、AI 讲解、PPTX 渲染都在本机 Python 引擎
 * （hnuclass）里完成，插件只把模型调用转成一次命令行执行。
 */
import { spawn } from 'node:child_process'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'

export const name = 'hnu-class-ppt'
export const inject = ['tools']

const DEFAULTS = {
  python: 'python',
  engineDir: '',
}

function engineDirOf(config) {
  return config.engineDir || process.env.HNUCLASS_HOME || process.cwd()
}

/** 没有 @deepseek-ai/dsh-tools 时，把 DSH 的参数规格转成标准 JSON Schema。 */
function toJsonSchema(spec) {
  const properties = {}
  const required = []
  for (const [key, value] of Object.entries(spec)) {
    const { required: isRequired, ...rest } = value
    properties[key] = rest
    if (isRequired) required.push(key)
  }
  return { type: 'object', additionalProperties: false, properties, required }
}

function run(cmd, args, opts, timeoutMs) {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, { ...opts, windowsHide: true })
    let out = ''
    let err = ''
    const timer = setTimeout(() => {
      try { child.kill() } catch { /* noop */ }
    }, timeoutMs)
    child.stdout.on('data', (d) => { out += d.toString('utf8') })
    child.stderr.on('data', (d) => { err += d.toString('utf8') })
    child.on('error', (e) => { clearTimeout(timer); resolve({ code: -1, out, err: String(e) }) })
    child.on('close', (code) => { clearTimeout(timer); resolve({ code, out, err }) })
  })
}

async function callEngine(config, args, timeoutMs = 600000) {
  const dir = engineDirOf(config)
  const env = {
    ...process.env,
    PYTHONIOENCODING: 'utf-8',
    PYTHONPATH: [dir, path.join(dir, 'pylib')].filter(Boolean).join(path.delimiter),
  }
  return run(config.python || 'python', ['-m', 'hnuclass.cli', ...args], { cwd: dir, env }, timeoutMs)
}

export async function apply(ctx, config = {}) {
  const cfg = { ...DEFAULTS, ...config }
  let defineTool = null
  try {
    ;({ defineTool } = await import('@deepseek-ai/dsh-tools'))
  } catch { /* 允许在没有该包的环境里退化为普通对象 */ }

  const tool = {
    name: 'hnu_class_ppt',
    description:
      '生成湖南大学程序设计小班课 PPT。可先 login 让用户在浏览器里完成 CG 平台登录，' +
      '再 courses/assignments/problems 查询作业与题目，最后 build 按指定题目生成与模板版式一致的课件。' +
      'build 需要传入 config 对象：{meta:{session,group,klass,name,student_id}, ' +
      'problems:[{assign_id,index,title,ptype,assignment}], llm:{base_url,api_key,model}, out}。',
    parameters: {
      action: {
        type: 'string', required: true,
        enum: ['login', 'courses', 'assignments', 'problems', 'build', 'demo'],
        description: 'login=浏览器登录；courses/assignments/problems=查询；build=生成课件；demo=内置示例',
      },
      course: { type: 'string', description: '课程 ID（action=assignments 时必填）' },
      assign: { type: 'string', description: '作业 ID（action=problems 时必填）' },
      config: { type: 'object', description: 'action=build 时的完整生成配置', additionalProperties: true },
    },
    output: {
      schema: {
        type: 'object', additionalProperties: false,
        properties: {
          ok: { type: 'boolean', required: true },
          output: { type: 'string', required: true },
          pptx: { type: 'string' },
        },
      },
      render: (_a, v) => [{ type: 'text', text: v.output }],
    },
    async execute(args) {
      const action = args.action
      if (action === 'build') {
        if (!args.config) throw new Error('build 需要 config 对象')
        const dir = await mkdtemp(path.join(tmpdir(), 'hnuclass-'))
        const file = path.join(dir, 'job.json')
        await writeFile(file, JSON.stringify(args.config, null, 2), 'utf8')
        const r = await callEngine(cfg, ['build', '--config', file], 1800000)
        await rm(dir, { recursive: true, force: true })
        const out = (r.out + (r.err ? '\n' + r.err : '')).trim()
        const pptx = out.split(/\r?\n/).filter((l) => l.toLowerCase().endsWith('.pptx')).pop()
        return { ok: r.code === 0, output: out || `退出码 ${r.code}`, ...(pptx ? { pptx } : {}) }
      }

      let argv
      if (action === 'login') argv = ['login']
      else if (action === 'courses') argv = ['courses']
      else if (action === 'assignments') argv = ['assignments', '--course', String(args.course || '')]
      else if (action === 'problems') argv = ['problems', '--assign', String(args.assign || '')]
      else if (action === 'demo') argv = ['demo', '--out', path.join(engineDirOf(cfg), 'out', 'demo.pptx')]
      else throw new Error(`未知 action: ${action}`)

      const r = await callEngine(cfg, argv, action === 'login' ? 900000 : 120000)
      const out = (r.out + (r.err ? '\n' + r.err : '')).trim()
      return { ok: r.code === 0, output: out || `退出码 ${r.code}` }
    },
  }
  if (defineTool) {
    ctx.tools.register(defineTool(tool))
  } else {
    const { parameters, ...rest } = tool
    ctx.tools.register({ ...rest, parameters: toJsonSchema(parameters) })
  }
}
