import { useState } from 'react'
import { useReveal } from '../hooks.js'
import { avatarGradient, initialOf } from '../utils.js'

/**
 * 角色区：3D 翻转卡。
 * - 桌面：hover 即预览背面，点击可固定；
 * - 移动端：点击翻转，再点翻回；
 * - 键盘：Tab 聚焦时自动翻面，回车切换。
 * 头像为纯渐变 + 姓氏首字，不使用图片。
 */
export default function Characters({ data }) {
  const [ref, visible] = useReveal()
  const [flipped, setFlipped] = useState({})
  const characters = data?.characters || []

  const toggle = (roleId) => {
    setFlipped((current) => ({ ...current, [roleId]: !current[roleId] }))
  }

  return (
    <section className="section" id="cast">
      <div className="wrap">
        <div className="section-head">
          <p className="section-kicker">Dramatis Personae</p>
          <h2 className="section-title">登场角色</h2>
          <p className="section-desc">
            点击卡片翻面查看隐藏档案；桌上的每个人都在隐瞒同一段时间里的一件小事。
          </p>
          <div className="divider">
            <span />
          </div>
        </div>

        <div ref={ref} className={`cast-grid reveal ${visible ? 'is-visible' : ''}`}>
          {characters.length === 0 && <p className="section-desc">角色档案加载中…</p>}

          {characters.map((item) => (
            <button
              key={item.role_id}
              type="button"
              className={`flip ${flipped[item.role_id] ? 'is-flipped' : ''}`}
              onClick={() => toggle(item.role_id)}
              aria-pressed={Boolean(flipped[item.role_id])}
              aria-label={`${item.name}，${item.identity}，点击翻转查看隐藏档案`}
            >
              <div className="flip__inner">
                {/* 正面 */}
                <div className="flip__face flip__face--front" aria-hidden={flipped[item.role_id]}>
                  <span
                    className="avatar"
                    style={{ '--avatar': avatarGradient(item.role_id) }}
                    aria-hidden="true"
                  >
                    {initialOf(item.name)}
                  </span>
                  <h3 className="cast-name">{item.name}</h3>
                  <span className="cast-role">{item.identity}</span>
                  <p className="cast-text">{item.profile}</p>
                  <span className="cast-hint">翻转查看隐藏档案</span>
                </div>

                {/* 背面：不泄露具体秘密，只给线索指引 */}
                <div className="flip__face flip__face--back" aria-hidden={!flipped[item.role_id]}>
                  <span
                    className="avatar"
                    style={{ '--avatar': avatarGradient(`${item.role_id}-back`) }}
                    aria-hidden="true"
                  >
                    {initialOf(item.name)}
                  </span>
                  <h3 className="cast-name">{item.name} · 隐藏档案</h3>
                  <p className="cast-secret">
                    {item.style ? `说话方式：${item.style}` : '口供前后矛盾，需要当面对质。'}
                  </p>
                  <div className="cast-stat">
                    <span>
                      <b>{item.secret_count ?? 0}</b>
                      私密秘密
                    </span>
                    <span>
                      <b>{item.goal_count ?? 0}</b>
                      隐藏目标
                    </span>
                  </div>
                  <span className="cast-hint">再点一次翻回正面</span>
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>
    </section>
  )
}
