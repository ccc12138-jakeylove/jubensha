import { useEffect, useRef, useState } from 'react'

/**
 * 进入视口后触发一次淡入。
 * 用 IntersectionObserver 而不是滚动监听，避免每帧计算。
 */
export function useReveal() {
  const ref = useRef(null)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const node = ref.current
    if (!node) return
    // 不支持 IntersectionObserver 时直接显示，保证内容可见
    if (typeof IntersectionObserver === 'undefined') {
      setVisible(true)
      return
    }
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setVisible(true)
            observer.disconnect()
          }
        })
      },
      { threshold: 0.15, rootMargin: '0px 0px -60px 0px' },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  return [ref, visible]
}

/**
 * 打字机效果：逐字显示文本。
 * 返回 {text, done}，speed 为每字毫秒数。
 */
export function useTypewriter(source, speed = 90, start = true) {
  const [text, setText] = useState('')
  const [done, setDone] = useState(false)

  useEffect(() => {
    if (!start || !source) return
    // 尊重系统的减少动画偏好：直接输出全文
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduce) {
      setText(source)
      setDone(true)
      return
    }
    setText('')
    setDone(false)
    let index = 0
    const timer = setInterval(() => {
      index += 1
      setText(source.slice(0, index))
      if (index >= source.length) {
        clearInterval(timer)
        setDone(true)
      }
    }, speed)
    return () => clearInterval(timer)
  }, [source, speed, start])

  return { text, done }
}

/**
 * 记录页面滚动进度，用于导航栏压实效果。
 */
export function useScrolled(threshold = 24) {
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > threshold)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [threshold])
  return scrolled
}

/**
 * 平滑滚动到指定区块，兼容不支持 smooth 的浏览器。
 */
export function scrollToId(id) {
  const target = document.getElementById(id)
  if (!target) return
  const top = target.getBoundingClientRect().top + window.scrollY - 72
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  window.scrollTo({ top, behavior: reduce ? 'auto' : 'smooth' })
}
