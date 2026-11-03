import { useReveal } from '../hooks.js'
import { formatOffset } from '../utils.js'

/**
 * 时间线：按案发前后相对分钟排序的关键节点。
 * 桌面为左右交错布局，移动端收成单列。
 */
export default function Timeline({ data }) {
  const [ref, visible] = useReveal()
  const events = data?.timeline || []

  return (
    <section className="section" id="timeline">
      <div className="wrap">
        <div className="section-head">
          <p className="section-kicker">Timeline</p>
          <h2 className="section-title">案发时间线</h2>
          <p className="section-desc">
            以死亡时刻为原点。凡是无法与这条时间线对齐的证词，都值得再问一遍。
          </p>
          <div className="divider">
            <span />
          </div>
        </div>

        <ol ref={ref} className={`timeline reveal ${visible ? 'is-visible' : ''}`}>
          {events.length === 0 && <p className="section-desc">时间线整理中…</p>}

          {events.map((event) => (
            <li className="tl-item" key={event.id}>
              <p className="tl-time">{formatOffset(event.offset)}</p>
              <h3 className="tl-title">{event.title}</h3>
              <p className="tl-text">{event.detail}</p>
              {event.place && <span className="tl-place">{event.place}</span>}
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}
