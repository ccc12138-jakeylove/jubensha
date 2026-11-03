/**
 * 与后端展示接口通信的最小封装。
 * 同源部署时 BASE 为空；开发环境由 vite proxy 转发到 8100。
 */
const BASE = ''

async function request(path, options = {}) {
  const response = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    // 后端可能返回 {detail: "文本"}、{detail: [{msg}]}（FastAPI 校验）或 {error:{message}}
    const detail = payload.detail
    const message =
      (Array.isArray(detail) ? detail[0]?.msg : detail) ||
      payload.error?.message ||
      `请求失败（${response.status}）`
    throw new Error(message)
  }
  return payload
}

/** 拉取剧本展示数据：标题、角色、线索、时间线 */
export function fetchShow() {
  return request('/api/show/script')
}

/** 提交指认，返回 {correct, message, truth} */
export function submitAccuse(suspectId) {
  return request('/api/show/accuse', {
    method: 'POST',
    body: JSON.stringify({ suspect_id: suspectId }),
  })
}

/** 提交报名，返回 {ok, session, name} */
export function submitSignup(form) {
  return request('/api/show/signup', {
    method: 'POST',
    body: JSON.stringify(form),
  })
}
