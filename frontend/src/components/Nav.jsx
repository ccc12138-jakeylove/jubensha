import BgmToggle from './BgmToggle.jsx'
import { scrollToId, useScrolled } from '../hooks.js'

const THEME_LABEL = { noir: '暗夜', sepia: '旧档', midnight: '冷雾' }

export default function Nav({ title, theme, onThemeChange, bgm }) {
  const scrolled = useScrolled(24)

  return (
    <header className={`nav ${scrolled ? 'is-scrolled' : ''}`}>
      <div className="nav__inner">
        <a className="brand" href="#top" aria-label="返回顶部">
          <span className="brand__mark" aria-hidden="true" />
          雾港档案室
        </a>
        <span className="nav__script" title={title}>
          正在展卷 · {title}
        </span>

        <span className="nav__spacer" />

        <div className="nav__actions">
          {/* 主题切换：色点按钮 + 循环切换，兼顾手机 */}
          <div className="themes" role="group" aria-label="风格切换">
            {Object.entries(THEME_LABEL).map(([key, label]) => (
              <button
                key={key}
                type="button"
                data-theme-option={key}
                aria-pressed={theme === key}
                aria-label={`切换到${label}风格`}
                title={label}
                onClick={() => onThemeChange(key)}
              />
            ))}
          </div>

          <BgmToggle bgm={bgm} />

          <button type="button" className="btn btn--primary" onClick={() => scrollToId('signup')}>
            报名
          </button>
        </div>
      </div>
    </header>
  )
}
