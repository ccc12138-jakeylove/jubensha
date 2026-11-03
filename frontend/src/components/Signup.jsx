import { useState } from 'react'
import { submitSignup } from '../api.js'
import { useReveal } from '../hooks.js'

const DEFAULT_SESSIONS = [
  { id: 'fri-1930', label: '周五 19:30 · 首场', seats: 6 },
  { id: 'sat-1400', label: '周六 14:00 · 下午场', seats: 6 },
  { id: 'sat-1930', label: '周六 19:30 · 夜场', seats: 6 },
]

/** 简易表单校验：返回字段级错误，提交前拦截明显错误 */
function validate(form) {
  const errors = {}
  if (!form.name.trim()) errors.name = '请填写称呼'
  if (!/^1[3-9]\d{9}$/.test(form.phone.trim())) errors.phone = '请填写 11 位手机号'
  if (!form.session) errors.session = '请选择场次'
  return errors
}

/**
 * 报名区：表单校验 → 提交后端 → 成功提示。
 * 成功后保留一个静态确认卡，避免用户重复提交。
 */
export default function Signup({ onToast }) {
  const [ref, visible] = useReveal()
  const [form, setForm] = useState({ name: '', phone: '', session: '' })
  const [errors, setErrors] = useState({})
  const [status, setStatus] = useState('idle')
  const [done, setDone] = useState(null)

  const update = (key) => (event) => {
    setForm((current) => ({ ...current, [key]: event.target.value }))
    setErrors((current) => ({ ...current, [key]: undefined }))
  }

  const submit = async (event) => {
    event.preventDefault()
    const found = validate(form)
    setErrors(found)
    if (Object.keys(found).length > 0) return

    setStatus('loading')
    try {
      const result = await submitSignup(form)
      setDone(result)
      setStatus('done')
      onToast?.('报名已记录，我们会在开场前联系你', 'ok')
    } catch (err) {
      setStatus('idle')
      onToast?.(err.message, 'warn')
    }
  }

  return (
    <section className="section" id="signup">
      <div className="wrap">
        <div className="section-head">
          <p className="section-kicker">Reservation</p>
          <h2 className="section-title">预约一场</h2>
          <p className="section-desc">
            每场 6 个席位，开场前 24 小时截止。留下联系方式，我们会把档案袋交到你手上。
          </p>
          <div className="divider">
            <span />
          </div>
        </div>

        <div ref={ref} className={`signup reveal ${visible ? 'is-visible' : ''}`}>
          {status === 'done' && done ? (
            <div className="success" role="status">
              <h3>报名成功</h3>
              <p>
                留档编号 <b>{done.ticket || done.session}</b>
                <br />
                {done.name}，场次：{done.session_label || done.session}
                <br />
                开场前我们会通过短信确认，若要改期直接回复即可。
              </p>
            </div>
          ) : (
            <form className="form" onSubmit={submit} noValidate>
              <div className="field">
                <label htmlFor="name">怎么称呼你</label>
                <input
                  id="name"
                  name="name"
                  autoComplete="name"
                  placeholder="例如：林先生"
                  value={form.name}
                  onChange={update('name')}
                  aria-invalid={Boolean(errors.name)}
                />
                {errors.name && <span className="field__error">{errors.name}</span>}
              </div>

              <div className="field">
                <label htmlFor="phone">手机号</label>
                <input
                  id="phone"
                  name="phone"
                  type="tel"
                  inputMode="numeric"
                  autoComplete="tel"
                  placeholder="用于开场前确认"
                  value={form.phone}
                  onChange={update('phone')}
                  aria-invalid={Boolean(errors.phone)}
                />
                {errors.phone && <span className="field__error">{errors.phone}</span>}
              </div>

              <div className="field">
                <label htmlFor="session">选择场次</label>
                <select
                  id="session"
                  name="session"
                  value={form.session}
                  onChange={update('session')}
                  aria-invalid={Boolean(errors.session)}
                >
                  <option value="">请选择</option>
                  {DEFAULT_SESSIONS.map((session) => (
                    <option key={session.id} value={session.id}>
                      {session.label}
                    </option>
                  ))}
                </select>
                {errors.session && <span className="field__error">{errors.session}</span>}
              </div>

              <div className="form__foot">
                <button type="submit" className="btn btn--primary" disabled={status === 'loading'}>
                  {status === 'loading' ? '正在提交…' : '提交报名'}
                </button>
                <span className="form__note">仅用于场次联络，不会用于其他用途。</span>
              </div>
            </form>
          )}

          <div className="sessions">
            {DEFAULT_SESSIONS.map((session) => (
              <div className="session" key={session.id}>
                <span className="session__time">{session.label}</span>
                <span className="session__meta">余 {session.seats} 席</span>
              </div>
            ))}
            <p className="form__note" style={{ marginTop: 6 }}>
              场次为示例数据，可在后端 `show_signups` 表接入真实排期。
            </p>
          </div>
        </div>
      </div>
    </section>
  )
}
