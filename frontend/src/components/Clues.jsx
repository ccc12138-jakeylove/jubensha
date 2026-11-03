import { useState } from 'react'
import { useReveal } from '../hooks.js'
import { tiltBy } from '../utils.js'

/**
 * 线索墙：图钉 + 红绳 + 旧纸卡片。
 * 卡片点一下展开详情，再点收起；展开状态用 id 集合维护。
 */
export default function Clues({ data, onToast }) {
  const [ref, visible] = useReveal()
  const [open, setOpen] = useState({})
  const clues = data?.clues || []

  const toggle = (clueId) => {
    setOpen((current) => {
      const next = { ...current, [clueId]: !current[clueId] }
      if (next[clueId] && typeof onToast === 'function') {
        // 轻提示：告诉用户可以再点一次收起
        onToast(`已展开 ${clueId} 的完整记录`, 'info')
      }
      return next
    })
  }

  return (
    <section className="section" id="clues">
      <div className="wrap">
        <div className="section-head">
          <p className="section-kicker">Evidence Board</p>
          <h2 className="section-title">线索墙</h2>
          <p className="section-desc">
            现场取回的物证与口供碎片。点击任意卡片展开原始记录，红绳代表已被交叉验证的关联。
          </p>
          <div className="divider">
            <span />
          </div>
        </div>

        <div ref={ref} className={`board reveal ${visible ? 'is-visible' : ''}`}>
          <div className="board__strings" aria-hidden="true" />

          <div className="clue-grid">
            {clues.length === 0 && <p className="section-desc">线索正在归档…</p>}

            {clues.map((clue, index) => (
              <button
                key={clue.clue_id}
                type="button"
                className={`clue ${open[clue.clue_id] ? 'is-open' : ''}`}
                style={{ '--tilt': tiltBy(index) }}
                onClick={() => toggle(clue.clue_id)}
                aria-expanded={Boolean(open[clue.clue_id])}
                aria-label={`${clue.name}，点击${open[clue.clue_id] ? '收起' : '展开'}`}
              >
                <div className="clue__card">
                  <span className="clue__id">物证 {clue.clue_id}</span>
                  <span className="clue__toggle" aria-hidden="true">
                    ▾
                  </span>
                  <h3 className="clue__name">{clue.name}</h3>
                  <p className="clue__brief">{clue.text}</p>

                  {open[clue.clue_id] && (
                    <div className="clue__detail">
                      <span>
                        <b>发现地点</b>
                        {clue.location || '未记录'}
                      </span>
                      <span>
                        <b>可用幕次</b>
                        {clue.act || '—'}
                      </span>
                      <span>
                        <b>搜证成本</b>
                        {clue.cost ?? 1} 点
                      </span>
                      <span>
                        <b>是否红鲱鱼</b>
                        {clue.red_herring ? '疑似误导' : '核心证据'}
                      </span>
                    </div>
                  )}
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
