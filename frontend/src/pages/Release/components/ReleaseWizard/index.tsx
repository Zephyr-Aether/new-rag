import { useState } from 'react'
import { api, ContractCheck, Regression, Version } from '@/services'
import { Badge, Button, ErrorBox, Field, Modal, stateLabel, SuccessBox } from '@/components'
const STEP_NAMES = ['兼容性检查', '回归验证', '发布', '灰度放量']

export default function ReleaseWizard({
  agentId,
  versions,
  onClose,
  onDone,
}: {
  agentId: string
  versions: Version[]
  onClose: () => void
  onDone: () => void
}) {
  const [step, setStep] = useState(0)
  const [version, setVersion] = useState<number | ''>('')
  const [contract, setContract] = useState<ContractCheck | null>(null)
  const [regression, setRegression] = useState<Regression | null>(null)
  const [publishMsg, setPublishMsg] = useState('')
  const [pct, setPct] = useState('10')
  const [force, setForce] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function runContract() {
    if (version === '') return
    setBusy(true)
    setErr('')
    setContract(null)
    try {
      setContract(await api.contractCheck(agentId, version))
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function runRegression() {
    if (version === '') return
    setBusy(true)
    setErr('')
    setRegression(null)
    try {
      setRegression(await api.regression(agentId, version))
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function doPublish() {
    if (version === '') return
    setBusy(true)
    setErr('')
    setPublishMsg('')
    try {
      const r = await api.publish(agentId, version, force, true) // evaluate 门禁
      setPublishMsg(`v${version} 已发布 → ${stateLabel(String(r.status))}`)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  // 发布完成后的"下一步建议"：进入灰度监控或历史
  const nextAfterPublish = version === ''
    ? null
    : `v${version} 已进入 ${stateLabel(String(versions.find((x) => x.version === version)?.status ?? ''))}。下一步：到发布页看灰度指标 —— 如果指标恶化，从这里一键回滚。`

  async function doGray() {
    if (version === '') return
    setBusy(true)
    setErr('')
    try {
      const p = Math.max(0, Math.min(100, Number(pct) || 0))
      await api.gray(agentId, version, p)
      onDone()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const contractBlocked = !!contract?.blocked
  const regressionFailed = !!regression?.regressed
  const canNext0 = contract !== null && (!contractBlocked || force)
  const canNext1 = regression !== null && (!regressionFailed || force)

  return (
    <Modal title="发布全流程引导" onClose={onClose}>
      {/* 版本选择 */}
      <Field label="选择要发布的版本">
        <select value={version} onChange={(e) => setVersion(e.target.value === '' ? '' : Number(e.target.value))}>
          <option value="">请选择…</option>
          {versions.map((x) => (
            <option key={x.version} value={x.version}>
              v{x.version} · {stateLabel(x.status)} {x.system_prompt ? `· ${x.system_prompt.slice(0, 18)}` : ''}
            </option>
          ))}
        </select>
      </Field>

      {/* 步骤进度 */}
      <div className="wizard-steps">
        {STEP_NAMES.map((name, i) => (
          <div key={name} className={i <= step ? 'on' : ''}>
            <span className="dot">{i + 1}</span>
            <span>{name}</span>
          </div>
        ))}
      </div>

      {err && <div className="mb"><ErrorBox message={err} /></div>}
      {publishMsg && <div className="mb"><SuccessBox message={publishMsg} /></div>}

      {version === '' ? (
        <div className="empty">请先选择版本</div>
      ) : (
        <>
          {step === 0 && (
            <div>
              {contract === null ? (
                <div className="empty">
                  <p>发布前 10 项兼容性检查</p>
                  <Button tone="primary" disabled={busy} onClick={runContract} className="mt">
                    {busy ? '检查中…' : '运行契约检查'}
                  </Button>
                </div>
              ) : (
                <ContractView data={contract} />
              )}
              {contractBlocked && (
                <div className="mt">
                  <ErrorBox message="存在阻断项（fail），发布被门禁拦截" />
                  <div className="small muted mt">建议先修复：{contract.checks.filter((c) => c.status === 'fail').map((c) => c.id).join('、') || '阻断项'}，再重新检查。</div>
                  <label className="field row" style={{ marginTop: 8 }}>
                    <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
                    <span>{force ? '✓ 我已确认风险，仍要继续' : '我已确认风险，仍要继续'}</span>
                  </label>
                  {force && <p className="small muted">强制发布会跳过本次门禁，并在审计中记录你的选择。确认无误后点「下一步」。</p>}
                </div>
              )}
            </div>
          )}

          {step === 1 && (
            <div>
              {regression === null ? (
                <div className="empty">
                  <p>对坏案例评测集回归，通过率对比上一版本</p>
                  <Button tone="primary" disabled={busy} onClick={runRegression} className="mt">
                    {busy ? '回归中…' : '运行回归'}
                  </Button>
                </div>
              ) : (
                <RegressionView data={regression} />
              )}
              {regressionFailed && (
                <div className="mt">
                  <ErrorBox message="回归未通过：质量回退，发布被拦截" />
                  <div className="small muted mt">建议先检查退化案例，再重新运行回归；如确认是误判，可在人工确认后继续。</div>
                  <label className="field row" style={{ marginTop: 8 }}>
                    <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
                    <span>{force ? '✓ 我已确认回归误判，仍要继续' : '我已确认回归误判，仍要继续'}</span>
                  </label>
                </div>
              )}
            </div>
          )}

          {step === 2 && (
            <div>
              <p className="small muted">
                发布 v{version}（含兼容性与回归检查）
              </p>
              <Button tone="primary" disabled={busy || publishMsg !== ''} onClick={doPublish} className="mt">
                {busy ? '发布中…' : '发布'}
              </Button>
            </div>
          )}

          {/* 发布完成反馈：下一步去观察结果 / 看历史 */}
          {publishMsg && nextAfterPublish && (
            <div className="mt">
              <p className="small">{nextAfterPublish}</p>
              <div className="row mt" style={{ gap: 8 }}>
                <Button onClick={onDone}>回到发布页看指标</Button>
              </div>
            </div>
          )}

          {step === 3 && (
            <div>
              <Field label="灰度百分比（0-100）">
                <input type="number" min={0} max={100} value={pct} onChange={(e) => setPct(e.target.value)} />
              </Field>
              <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
                {['1', '5', '10', '25'].map((p) => (
                  <button
                    key={p}
                    type="button"
                    className={`tmp-card${pct === p ? ' on' : ''}`}
                    style={{ padding: '4px 10px', width: 'auto' }}
                    onClick={() => setPct(p)}
                  >
                    {p}%
                  </button>
                ))}
              </div>
              <p className="small muted mt">
                {Number(pct) <= 1 ? '保守灰度：先给极少量流量验证。' : Number(pct) <= 10 ? '常规灰度：可控范围内验证。' : '偏激进：接近全量，请确认 Canary 指标健康。'}
              </p>
              <div className="row">
                <Button tone="primary" disabled={busy} onClick={doGray}>
                  {busy ? '灰度中…' : '灰度放量并完成'}
                </Button>
                <Button onClick={onDone}>跳过灰度，直接完成</Button>
              </div>
            </div>
          )}
        </>
      )}

      <div className="row mt" style={{ justifyContent: 'space-between' }}>
        <div className="row">
          {step > 0 && version !== '' && (
            <Button onClick={() => setStep(step - 1)}>上一步</Button>
          )}
        </div>
        {version !== '' && step < 3 && (
          <Button
            tone="primary"
            disabled={(step === 0 && !canNext0) || (step === 1 && !canNext1) || (step === 2 && publishMsg === '')}
            onClick={() => setStep(step + 1)}
          >
            下一步
          </Button>
        )}
      </div>
    </Modal>
  )
}

function ContractView({ data }: { data: ContractCheck }) {
  return (
    <div>
      <div className="row" style={{ marginBottom: 10 }}>
        <span>
          总体 <Badge status={data.status} /> {data.blocked && <b style={{ color: 'var(--red)' }}>阻断</b>}
        </span>
        {data.needs_manual.length > 0 && <span className="small muted">人工签核：{data.needs_manual.join('、')}</span>}
      </div>
      <table className="tbl">
        <thead>
          <tr>
            <th>检查</th>
            <th>结果</th>
            <th>说明</th>
          </tr>
        </thead>
        <tbody>
          {data.checks.map((c) => (
            <tr key={c.id}>
              <td className="mono small">{c.id}</td>
              <td>
                <Badge status={c.status} />
              </td>
              <td className="small">{c.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function RegressionView({ data }: { data: Regression }) {
  const fmtTools = (list?: string[]) => (list && list.length ? list.join(' → ') : '—')
  const pct = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v * 100)}%`)
  return (
    <div>
      {data.total === 0 ? (
        <div className="success-box mb">评测集为空：回归自动通过，无质量回退风险，可正常发布。</div>
      ) : data.regressed ? (
        <div className="error-box mb">
          回归未通过：通过率 {pct(data.pass_rate)} 低于上一版本 {pct(data.previous_pass_rate)}，已阻止发布。
        </div>
      ) : (
        <div className="success-box mb">
          回归通过：{data.passed}/{data.total} 通过（{pct(data.pass_rate)}），无质量回退。
        </div>
      )}
      <div className="grid cols-3" style={{ gap: 12 }}>
        <div className="stat">
          <div className="label">通过率</div>
          <div className="value">{pct(data.pass_rate)}</div>
          <div className="sub">
            上一版本 {pct(data.previous_pass_rate)}
          </div>
        </div>
        <div className="stat">
          <div className="label">通过 / 总数</div>
          <div className="value">{data.passed}/{data.total}</div>
          <div className="sub">完成 {data.completed}</div>
        </div>
        <div className="stat">
          <div className="label">结果</div>
          <div className="value">
            <Badge status={data.regressed ? 'fail' : 'passed'} />
          </div>
          <div className="sub">{data.regressed ? '质量回退' : '无回退'}</div>
        </div>
      </div>

      {(data.cases ?? []).length > 0 && (
        <table className="tbl mt">
          <thead>
            <tr>
              <th>问题</th>
              <th>结果</th>
              <th>判定</th>
              <th>实际调用</th>
              <th>期望调用</th>
              <th>禁用调用</th>
            </tr>
          </thead>
          <tbody>
            {data.cases!.map((c, i) => (
              <tr key={i}>
                <td className="small">{c.query}</td>
                <td>
                  {c.ok ? <span style={{ color: 'var(--success)' }}>✓ 通过</span> : <span style={{ color: 'var(--danger)' }}>✗ 未过</span>}
                </td>
                <td className="small muted">
                  {c.judge_type === 'llm' ? 'LLM' : '关键词'}
                  {c.judge_note ? (
                    <div style={{ fontSize: 11, color: 'var(--text-3)' }}>{c.judge_note}</div>
                  ) : null}
                </td>
                <td className="mono small">{fmtTools(c.tool_calls)}</td>
                <td className="mono small muted">{fmtTools(c.expected_tool_calls)}</td>
                <td className="mono small">
                  {c.forbidden_calls && c.forbidden_calls.length > 0 ? (
                    <span style={{ color: 'var(--danger)' }}>{c.forbidden_calls.join(', ')}</span>
                  ) : (
                    fmtTools(c.must_not_call)
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
