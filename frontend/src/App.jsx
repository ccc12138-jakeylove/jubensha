import { useCallback, useEffect, useMemo, useState } from 'react'
import { fetchShow } from './api.js'
import Nav from './components/Nav.jsx'
import Hero from './components/Hero.jsx'
import Dossier from './components/Dossier.jsx'
import Characters from './components/Characters.jsx'
import Clues from './components/Clues.jsx'
import Timeline from './components/Timeline.jsx'
import Accuse from './components/Accuse.jsx'
import Signup from './components/Signup.jsx'
import Footer from './components/Footer.jsx'
import Toast from './components/Toast.jsx'
import { useBgm } from './components/BgmToggle.jsx'

const THEMES = ['noir', 'sepia', 'midnight']

export default function App() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
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

  const cycleTheme = useCallback(() => {
    setTheme((current) => THEMES[(THEMES.indexOf(current) + 1) % THEMES.length])
  }, [])

  const suspects = useMemo(() => data?.characters ?? [], [data])

  return (
    <>
      <a className="skip-link" href="#cast">
        跳到角色档案
      </a>

      <Nav
        title={data?.title || '雾港谜案'}
        theme={theme}
        onThemeChange={setTheme}
        onThemeCycle={cycleTheme}
        bgm={bgm}
      />

      <main>
        <Hero data={data} />

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
        <Clues data={data} onToast={showToast} />
        <Timeline data={data} />
        <Accuse suspects={suspects} onToast={showToast} />
        <Signup onToast={showToast} />
      </main>

      <Footer data={data} />
      <Toast toast={toast} onClose={() => setToast(null)} />
    </>
  )
}
