import { useCallback, useEffect, useState } from 'react'
import { fetchShow } from './api.js'
import Nav from './components/Nav.jsx'
import Hero from './components/Hero.jsx'
import Dossier from './components/Dossier.jsx'
import Characters from './components/Characters.jsx'
import Signup from './components/Signup.jsx'
import Footer from './components/Footer.jsx'
import Toast from './components/Toast.jsx'
import { useBgm } from './components/BgmToggle.jsx'
import Play from './play/Play.jsx'

const THEMES = ['noir', 'sepia', 'midnight']

/** 用 URL hash 区分「介绍页」和「对局台」，刷新后仍停在原页面 */
function viewFromHash() {
  return window.location.hash === '#play' ? 'play' : 'show'
}

export default function App() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [view, setView] = useState(viewFromHash)
  const [theme, setTheme] = useState(() => {
    // 读取上次选择，非法值回落到默认主题，避免 data-theme 失效导致变量缺失
    const saved = localStorage.getItem('jubensha-theme')
    return THEMES.includes(saved) ? saved : 'noir'
  })
  const [toast, setToast] = useState(null)
  const bgm = useBgm()

  // 主题写入 <html data-theme> 并持久化
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('jubensha-theme', theme)
  }, [theme])

  // 浏览器前进/后退时同步视图
  useEffect(() => {
    const onHash = () => setView(viewFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  // 首屏数据：失败时给出可读提示，页面其余部分仍可浏览
  useEffect(() => {
    let alive = true
    fetchShow()
      .then((payload) => {
        if (alive) setData(payload)
      })
      .catch((err) => {
        if (alive) setError(err.message)
      })
    return () => {
      alive = false
    }
  }, [])

  const showToast = useCallback((message, tone = 'info') => {
    setToast({ message, tone, id: Date.now() })
  }, [])

  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(null), 4200)
    return () => clearTimeout(timer)
  }, [toast])

  const enterPlay = useCallback(() => {
    window.location.hash = 'play'
    setView('play')
    window.scrollTo({ top: 0 })
  }, [])

  const exitPlay = useCallback(() => {
    window.location.hash = ''
    setView('show')
    window.scrollTo({ top: 0 })
  }, [])

  // 对局台：独立布局，不显示宣传页导航
  if (view === 'play') {
    return (
      <>
        <Play show={data} onExit={exitPlay} />
        <Toast toast={toast} onClose={() => setToast(null)} />
      </>
    )
  }

  return (
    <>
      <a className="skip-link" href="#cast">
        跳到角色档案
      </a>

      <Nav
        title={data?.title || '雾港谜案'}
        theme={theme}
        onThemeChange={setTheme}
        bgm={bgm}
        onStart={enterPlay}
      />

      <main>
        <Hero data={data} onStart={enterPlay} />

        {error && (
          <div className="wrap" style={{ paddingBottom: 24 }}>
            <div className="verdict is-wrong" role="alert">
              <p className="verdict__kicker">数据加载失败</p>
              <p className="verdict__text">{error}（后端接口未启动时页面仍可浏览）</p>
            </div>
          </div>
        )}

        <Dossier data={data} />
        <Characters data={data} />
        <Signup onToast={showToast} />
      </main>

      <Footer data={data} />
      <Toast toast={toast} onClose={() => setToast(null)} />
    </>
  )
}
