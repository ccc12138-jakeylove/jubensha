import { useTypewriter, scrollToId } from '../hooks.js'

/**
 * 首屏：剧本大标题（逐字打出）、副标题、悬疑文案与「翻开档案」入口。
 * 背景聚光灯与雨丝全部由 CSS 渐变绘制。
 */
export default function Hero({ data }) {
  const title = data?.title || '雾港谜案'
  const subtitle = data?.subtitle || '暴雨封港的一夜，302 房间的门闩从内侧扣死'
  const tagline = data?.tagline || '五个人的证词互相咬合，只有一个人的时间线永远对不上。'

  const typedTitle = useTypewriter(title, 150)
  const typedSub = useTypewriter(subtitle, 46, typedTitle.done)

  return (
    <section className="hero" id="top">
      <div className="hero__spot" aria-hidden="true" />
      <div className="hero__rain" aria-hidden="true" />

      <div className="hero__inner">
        <span className="hero__tag">悬疑 · 本格 · 单局 2.5 小时</span>

        <h1 className="hero__title" aria-label={title}>
          {typedTitle.text}
          {!typedTitle.done && <span className="caret" aria-hidden="true" />}
        </h1>

        <p className="hero__subtitle">
          {typedSub.text}
          {typedTitle.done && !typedSub.done && <span className="caret" aria-hidden="true" />}
        </p>

        <p className="hero__meta">
          <span>{data?.genre || '本格推理'}</span>
          <span>{data?.tone || '阴郁 · 潮湿 · 克制'}</span>
          <span>{data?.seat_range ? `${data.seat_range[0]}–${data.seat_range[1]} 人` : '1–5 人'}</span>
          <span>{data?.difficulty ? `难度 ${data.difficulty}` : '难度 4 / 5'}</span>
        </p>

        <div className="hero__actions">
          <button type="button" className="btn btn--primary" onClick={() => scrollToId('cast')}>
            翻开档案
          </button>
          <button type="button" className="btn" onClick={() => scrollToId('clues')}>
            查看线索墙
          </button>
        </div>

      </div>

      {/* 悬疑文案：单独一行，避免与打字机抢注意力 */}
      <span className="sr-only">{tagline}</span>
    </section>
  )
}
