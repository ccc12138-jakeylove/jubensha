import { useReveal } from '../hooks.js'

/**
 * 剧情简介：旧档案袋卡片 + 机密印章 + 一张渐变「老照片」。
 */
export default function Dossier({ data }) {
  const [ref, visible] = useReveal()

  const summary =
    data?.act_narrative ||
    '暴雨封港，旅馆电话线断了。夜里十一点十分，302 的房门被撞开，沈万山死在屋里。'
  const caseNo = data?.dossier_no || 'WG-1103-302'

  return (
    <section className="section" id="dossier">
      <div className="wrap">
        <div className="section-head">
          <p className="section-kicker">Case File</p>
          <h2 className="section-title">卷宗摘要</h2>
          <p className="section-desc">
            以下内容来自现场记录与旅店住客口供，未经交叉验证的部分以红笔标注。
          </p>
          <div className="divider">
            <span />
          </div>
        </div>

        <div ref={ref} className={`dossier reveal ${visible ? 'is-visible' : ''}`}>
          <article className="envelope paper">
            <div className="envelope__no">
              <span>档案编号 {caseNo}</span>
              <span>密封等级：仅限参与者</span>
            </div>
            <h3 className="envelope__title">{data?.act_title || '雾夜来客'}</h3>
            <p className="envelope__body">{summary}</p>
            <div className="envelope__foot">
              <span className="tl-place">潮汐旅馆 · 三楼</span>
              <span className="tl-place">暴雨 · 停电 · 无信号</span>
            </div>
            <span className="stamp" aria-hidden="true">
              机密
            </span>
          </article>

          <figure className="photo" style={{ margin: 0 }}>
            <div className="photo__frame" role="img" aria-label="案发现场的模拟老照片" />
            <figcaption className="photo__caption">
              现场照片 · 302 客房 · 拍摄于次日清晨
            </figcaption>
          </figure>
        </div>
      </div>
    </section>
  )
}
