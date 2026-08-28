import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ModelConfig } from '../api'
import { Button, ErrorBox, Modal } from './ui'

const LS_KEY = 'agent_platform_onboarding'

export function isOnboardingDone(): boolean {
  return localStorage.getItem(LS_KEY) === '1'
}
export function markOnboardingDone(): void {
  localStorage.setItem(LS_KEY, '1')
}
export function resetOnboarding(): void {
  localStorage.removeItem(LS_KEY)
}

type Template = {
  id: string
  title: string
  desc: string
  kbName: string
  docTitle: string
  docText: string
  question: string
}

// 预置场景模板：让用户选一个贴近自己的场景，而不是空想「我该问什么」
const TEMPLATES: Template[] = [
  {
    id: 'support',
    title: '客服问答',
    desc: '退货、退款、售后等常见问题',
    kbName: '客服问答（示例）',
    docTitle: '退货与退款政策',
    docText: '# 退货与退款政策\n\n退货条件：商品签收后 7 天内支持无理由退货，商品需保持未使用、包装完整。\n\n退款时效：退款申请审核通过后，资金将在 3-7 个工作日内原路退回。\n\n运费说明：因质量问题退货运费由商家承担；无理由退货运费由买家承担。\n\n换货流程：签收后 15 天内支持换货，联系客服登记后寄回即可。',
    question: '退款一般多久到账？',
  },
  {
    id: 'policy',
    title: '制度查询',
    desc: '请假、报销、考勤等内部制度',
    kbName: '制度查询（示例）',
    docTitle: '员工请假制度',
    docText: '# 员工请假制度\n\n休假类型：年假、事假、病假、婚假、产假。\n\n申请规则：请假需提前 1 天在系统提交申请；连续超过 3 天需部门负责人审批。\n\n销假流程：假期结束当日需在系统确认销假，未销假将按旷工处理。\n\n年假说明：入职满一年后享有 5 天带薪年假，未使用可顺延至次年一季度。',
    question: '请假需要提前几天提交申请？',
  },
  {
    id: 'product',
    title: '产品资料助手',
    desc: '产品规格、保修、部署信息',
    kbName: '产品资料（示例）',
    docTitle: '产品规格说明',
    docText: '# 智能客服机器人产品说明\n\n产品定位：面向企业的知识问答 Agent，支持接入企业文档构建专属知识库。\n\n核心能力：多轮对话、文档检索引用、工具调用、效果评测与版本发布。\n\n部署方式：支持 Docker 一键部署，模型可对接 OpenAI 兼容网关。\n\n服务保障：企业版提供 SLA 99.9% 与 7×24 技术支持，保修期 12 个月。',
    question: '产品的保修期是多久？',
  },
  {
    id: 'ticket',
    title: '工单辅助处理',
    desc: '工单分级、SLA、流转与超时',
    kbName: '工单 FAQ（示例）',
    docTitle: '工单处理规范',
    docText: '# 工单处理规范\n\nSLA 目标：普通工单 4 小时内响应，紧急工单 30 分钟内响应。\n\n超时处理：触发 SLA 后自动升级一级支持，并追加告警通知负责人。\n\n流转规则：工单按「受理→分派→处理→验收→关闭」五环节流转。\n\n知识沉淀：处理完成的高价值方案会回流到知识库，供后续工单直接引用。',
    question: '工单超时后怎么处理？',
  },
]

// 首次价值路径：选场景 → 接模型 → 一键建库导知识 → 跑一个预设问题 → 看执行报告 → 进发布治理
const STEP_TITLES = ['选场景', '接模型', '导入样例', '运行问题', '发布治理']

export default function Onboarding({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [step, setStep] = useState(0)
  const [cfg, setCfg] = useState<ModelConfig | null>(null)
  const [kbCount, setKbCount] = useState(0)
  const [template, setTemplate] = useState<Template | null>(null)
  const [demoDone, setDemoDone] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    if (!open) return
    setStep(0)
    setTemplate(null)
    setDemoDone(false)
    setErr('')
    Promise.allSettled([api.modelConfig(), api.kbBases()]).then(([cfg, kb]) => {
      setCfg(cfg.status === 'fulfilled' ? cfg.value : null)
      setKbCount(kb.status === 'fulfilled' ? kb.value.bases.length : 0)
    })
  }, [open])

  function go(path: string) {
    markOnboardingDone()
    onClose()
    navigate(path)
  }

  async function createDemo() {
    if (!template) return
    setBusy(true)
    setErr('')
    try {
      const kb = await api.kbCreate(template.kbName, `${template.title}（示例知识库）`)
      await api.ingest({
        document_id: `demo-${template.id}`,
        title: template.docTitle,
        text: template.docText,
        kb_id: kb.kb_id,
      })
      setDemoDone(true)
      setStep(3)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function runQuestion() {
    if (!template) return
    setBusy(true)
    setErr('')
    try {
      const r = await api.createRun(template.question, true)
      go(`/runs/${r.run_id}`)
    } catch (e) {
      setErr((e as Error).message)
      setBusy(false)
    }
  }

  if (!open) return null

  const modelReady = !!cfg && !cfg.is_mock
  function nextDisabled(): boolean {
    if (busy) return true
    if (step === 0) return !template
    if (step === 2) return !demoDone
    return false
  }

  return (
    <Modal title="快速开始 · 3 分钟跑通第一次价值" onClose={() => { markOnboardingDone(); onClose() }}>
      {/* 步骤条：5 步，完成打绿钩 */}
      <div className="wizard-steps">
        {STEP_TITLES.map((t, i) => (
          <div key={t} className={`${i < step ? 'done' : ''} ${i <= step ? 'on' : ''}`}>
            <span className="dot">{i < step ? '✓' : i + 1}</span>
            <span>{t}</span>
          </div>
        ))}
      </div>

      <div style={{ minHeight: 200, fontSize: 13, lineHeight: 1.6, padding: '6px 0' }}>
        {step === 0 && (
          <div>
            <div className="home-hint" style={{ marginBottom: 12 }}>
              <div className="home-hint-copy">
                <span className="home-hint-kicker">这次会做什么</span>
                <span>先选一个贴近你的场景，我们会自动创建示例知识、跑通第一次提问，再带你去看结果和发布链路。</span>
                <span className="small muted">
                  {modelReady ? `当前已接入 ${cfg!.provider} · ${cfg!.model}` : '当前先用内置模拟模型，也能把整条流程走通。'}
                  {kbCount > 0 ? ` 你已经有 ${kbCount} 个知识库，后面可以直接接着用。` : ' 还没有知识库也没关系，我们会生成一份示例。'}
                </span>
              </div>
            </div>
            <p className="mb">选一个更像你真实业务的场景，后面的内容会跟着这个场景走。</p>
            <div className="grid cols-2">
              {TEMPLATES.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  className={`tmp-card${template?.id === t.id ? ' on' : ''}`}
                  onClick={() => setTemplate(t)}
                >
                  <div className="tmp-title">{t.title}</div>
                  <div className="tmp-desc">{t.desc}</div>
                  <div className="tmp-q small muted">示例提问：{t.question}</div>
                </button>
              ))}
            </div>
          </div>
        )}
        {step === 1 && (
          <div>
            {modelReady ? (
              <p style={{ color: '#16a34a' }}>
                ✓ 已接入真实模型：<b>{cfg!.provider}</b> · <code>{cfg!.model}</code>
              </p>
            ) : (
              <>
                <p>
                  当前是<b>内置模拟模型</b>，无需任何配置就能完整体验整个流程。
                  接入真实 LLM 后，答案质量和工具调用会更贴近生产环境。
                </p>
                <div className="muted small mt">
                  到「配置中心 → 模型接入」填写 Provider、模型、base_url 与 API key 保存即生效。
                </div>
              </>
            )}
            <div className="mt row">
              {!modelReady && <Button onClick={() => go('/settings')}>去配置真实模型（可选）</Button>}
            </div>
          </div>
        )}
        {step === 2 && (
          <div>
            {template && (
              <p>
                一键创建示例知识库「<b>{template.kbName}</b>」，并导入样例文档（{template.docTitle}）。
              </p>
            )}
            {demoDone ? (
              <p style={{ color: '#16a34a' }}>✓ 示例已就绪，Agent 现在可以检索这份知识回答问题。</p>
            ) : (
              <div className="mt row">
                <Button tone="primary" disabled={busy} onClick={createDemo}>
                  {busy ? '创建中…' : '一键创建示例库并导入'}
                </Button>
              </div>
            )}
          </div>
        )}
        {step === 3 && (
          <div>
            {template && (
              <p>
                运行预设问题「<b>{template.question}</b>」，让 Agent 基于刚导入的示例知识回答。
                完成后直接打开这张任务的执行报告，查看<b>答案、引用来源、成本与运行轨迹</b>。
              </p>
            )}
            <div className="mt row">
              <Button tone="primary" disabled={busy} onClick={runQuestion}>
                {busy ? '运行中…' : '运行示例问题并看结果'}
              </Button>
            </div>
          </div>
        )}
        {step === 4 && (
          <div>
            <p>
              答案靠谱后，就能进入发布与治理：先过契约检查与效果评测，再灰度放量，看指标决定继续还是回滚。
            </p>
            <div className="mt row">
              <Button tone="primary" onClick={() => go('/release')}>去发布第一个版本</Button>
            </div>
          </div>
        )}
        {err && <div className="mt"><ErrorBox message={err} /></div>}
      </div>

      <div className="row spread mt">
        <Button onClick={() => { markOnboardingDone(); onClose() }}>跳过</Button>
        <div className="row">
          {step > 0 && <Button onClick={() => setStep(step - 1)}>上一步</Button>}
          {step < STEP_TITLES.length - 1 ? (
            <Button tone="primary" disabled={nextDisabled()} onClick={() => setStep(step + 1)}>下一步</Button>
          ) : (
            <Button tone="primary" onClick={() => { markOnboardingDone(); onClose() }}>开始使用</Button>
          )}
        </div>
      </div>
    </Modal>
  )
}
