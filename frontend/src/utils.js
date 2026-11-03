/**
 * 通用小工具：稳定哈希、头像渐变、时间线文案。
 * 头像不使用任何图片，用同一份种子生成稳定的双色渐变。
 */

/** 字符串转 32 位无符号哈希，用于派生颜色 */
export function hashCode(text = '') {
  let hash = 0
  for (let i = 0; i < text.length; i += 1) {
    hash = (hash << 5) - hash + text.charCodeAt(i)
    hash |= 0
  }
  return Math.abs(hash)
}

/** 由种子生成头像渐变：色相分散，但明度压暗，贴合悬疑气氛 */
export function avatarGradient(seed = '') {
  const hash = hashCode(seed)
  const hue = hash % 360
  const hue2 = (hue + 28) % 360
  return `linear-gradient(140deg, hsl(${hue} 42% 34%), hsl(${hue2} 38% 16%))`
}

/** 取姓名首字作为头像文字 */
export function initialOf(name = '') {
  return name.trim().slice(0, 1) || '？'
}

/**
 * 把 truth_events 的相对分钟转成人话。
 * 负数表示案发前，正数表示案发后。
 */
export function formatOffset(minutes) {
  if (typeof minutes !== 'number') return '时间不明'
  if (minutes === 0) return '案发时刻'
  const value = Math.abs(minutes)
  const text = value >= 60 ? `${Math.floor(value / 60)} 小时 ${value % 60} 分` : `${value} 分钟`
  return minutes < 0 ? `案发前 ${text}` : `案发后 ${text}`
}

/** 把数组按索引取模，返回稳定的视觉参数（倾角等） */
export function tiltBy(index) {
  const pattern = [-0.9, 0.7, -0.4, 1.1, -1.2, 0.5, -0.7, 0.9]
  return `${pattern[index % pattern.length]}deg`
}
