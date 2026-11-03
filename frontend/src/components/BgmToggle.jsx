import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * 背景音：不加载任何音频文件，用 Web Audio 现场合成一段「雨夜低频」。
 * 结构 = 白噪声经过低通（雨声）+ 58Hz 正弦低音（氛围）+ 缓慢增益起伏。
 * 浏览器要求音频必须在用户手势中启动，因此只在点击开关时创建 AudioContext。
 */
export function useBgm() {
  const [on, setOn] = useState(false)
  const ctxRef = useRef(null)
  const gainRef = useRef(null)
  const extraRef = useRef(null)

  const teardown = useCallback(() => {
    const ctx = ctxRef.current
    if (!ctx) return
    // 淡出后关闭，避免爆音
    try {
      gainRef.current?.gain.cancelScheduledValues(ctx.currentTime)
      gainRef.current?.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.4)
    } catch {
      /* 上下文已关闭时忽略 */
    }
    setTimeout(() => {
      ctx.close().catch(() => {})
      ctxRef.current = null
      gainRef.current = null
      extraRef.current = null
    }, 460)
  }, [])

  const start = useCallback(() => {
    const AudioCtor = window.AudioContext || window.webkitAudioContext
    if (!AudioCtor) return
    const ctx = new AudioCtor()
    ctxRef.current = ctx

    // 1) 雨声：2 秒白噪声循环 + 低通
    const buffer = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate)
    const channel = buffer.getChannelData(0)
    for (let i = 0; i < channel.length; i += 1) {
      channel[i] = Math.random() * 2 - 1
    }
    const noise = ctx.createBufferSource()
    noise.buffer = buffer
    noise.loop = true

    const lowpass = ctx.createBiquadFilter()
    lowpass.type = 'lowpass'
    lowpass.frequency.value = 460
    lowpass.Q.value = 0.6

    const master = ctx.createGain()
    master.gain.value = 0
    gainRef.current = master

    noise.connect(lowpass).connect(master).connect(ctx.destination)
    noise.start()

    // 2) 低音氛围：58Hz 正弦 + 缓慢呼吸
    const drone = ctx.createOscillator()
    drone.type = 'sine'
    drone.frequency.value = 58
    const droneGain = ctx.createGain()
    droneGain.gain.value = 0.012
    drone.connect(droneGain).connect(master)
    drone.start()
    extraRef.current = { drone, droneGain }

    // 淡入到目标音量
    master.gain.linearRampToValueAtTime(0.05, ctx.currentTime + 1.2)
  }, [])

  const toggle = useCallback(() => {
    setOn((current) => {
      const next = !current
      if (next) start()
      else teardown()
      return next
    })
  }, [start, teardown])

  // 页面卸载时释放音频资源
  useEffect(() => () => teardown(), [teardown])

  return { on, toggle }
}

export default function BgmToggle({ bgm }) {
  return (
    <button
      type="button"
      className={`toggle ${bgm.on ? 'is-on' : ''}`}
      onClick={bgm.toggle}
      aria-pressed={bgm.on}
      title="雨夜环境音（合成，不加载音频文件）"
    >
      <span className="toggle__dot" aria-hidden="true" />
      <span className="toggle__label">BGM {bgm.on ? 'ON' : 'OFF'}</span>
    </button>
  )
}
