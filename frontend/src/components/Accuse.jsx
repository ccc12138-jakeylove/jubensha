import { useState } from 'react'
import { submitAccuse } from '../api.js'
import { useReveal } from '../hooks.js'
import { avatarGradient } from '../utils.js'

/**
 * 指认区：选择一名嫌疑人并提交，结果直接渲染在右侧面板（不弹浏览器 alert）。
 * 结果由后端根据剧本真相判定，前端只负责展示。
 */
export default function Accuse({ suspects, onToast }) {
  const [ref, visible] = useReveal()
  const [picked, setPicked] = useState('')
  const [state, setState] = useState({ status: 'idle', result: null, error: '' })

  const submit = async () => {
    if (!picked) {
      setState({ status: 'error', result: null, error: '先选一个人。' })
      return
    }
    setState({ status: 'loading', result: null, error: '' })
    try {
      const result = await submitAccuse(picked)
      setState({ status: 'done', result, error: '' })
      onToast?.(result.correct ? '指认成功，档案结案' : '指认失败，卷宗退回重审', result.correct ? 'ok' : 'warn')
    } catch (err) {
      setState({ status: 'error', result: null, error: err.message })
      onToast?.(err.message, 'warn')
    }
  }

  const verdictClass = state.result
    ? state.result.correct
      ? 'is-correct'
      : 'is-wrong'
    : ''

  return (
    <section className="section" id="accuse">
      <div className="wrap">
        <div className="section-head">
          <p className="section-kicker">Accusation</p>
          <h2 className="section-title">指认凶手</h2>
          <p className="section-desc">
            选一个人，把名字写在结案报告上。提交后不可撤回，也不会告诉你错在哪里。
          </p>
          <div className="divider">
            <span />
          </div>
        </div>

        <div ref={ref} className={`accuse reveal ${visible ? 'is-visible' : ''}`}>
          <div className="suspects" role="radiogroup" aria-label="嫌疑人列表">
            {suspects.length === 0 && <p className="section-desc">嫌疑人名单加载中…</p>}

            {suspects.map((person) => (
              <button
                key={person.role_id}
                type="button"
                role="radio"
                aria-checked={picked === person.role_id}
                className={`suspect ${picked === person.role_id ? 'is-picked' : ''}`}
                onClick={() => setPicked(person.role_id)}
              >
                <span
                  className="suspect__dot"
                  style={{ '--avatar': avatarGradient(person.role_id) }}
                  aria-hidden="true"
                />
                <span className="suspect__name">{person.name}</span>
                <span className="suspect__tag">{person.identity}</span>
              </button>
            ))}

            <button
              type="button"
              className="btn btn--primary"
              style={{ marginTop: 8 }}
              onClick={submit}
              disabled={state.status === 'loading' || !suspects.length}
            >
              {state.status === 'loading' ? '正在比对…' : '提交指认'}
            </button>
          </div>

          <div className={`verdict ${verdictClass}`} aria-live="polite">
            {state.status === 'idle' && (
              <>
                <p className="verdict__kicker">等待提交</p>
                <p className="verdict__title">卷宗尚未署名</p>
                <p className="verdict__text">左侧选择一名嫌疑人后提交，系统会核对现场证据链。</p>
              </>
            )}

            {state.status === 'error' && (
              <>
                <p className="verdict__kicker">提交失败</p>
                <p className="verdict__title">档案退回</p>
                <p className="verdict__text">{state.error}</p>
              </>
            )}

            {state.status === 'done' && state.result && (
              <>
                <p className="verdict__kicker">结案结果</p>
                <p className="verdict__title">{state.result.correct ? '指认成立' : '指认不成立'}</p>
                <p className="verdict__text">{state.result.message}</p>
                {state.result.truth && (
                  <p className="verdict__text" style={{ color: 'var(--gold-soft)' }}>
                    {state.result.truth}
                  </p>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
