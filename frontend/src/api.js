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

/** Only pre-game public script information is returned. */
export function fetchShow(scriptId) {
  const query = scriptId ? `?${new URLSearchParams({ script_id: scriptId })}` : ''
  return request(`/api/show/script${query}`)
}

export function fetchPublishedScripts() {
  return request('/api/show/scripts')
}

export function fetchActView(gameId, seatId = 'seat_1') {
  return request(`/api/show/games/${gameId}/act?${new URLSearchParams({ seat_id: seatId })}`)
}

/** 提交报名，返回 {ok, session, name} */
export function submitSignup(form) {
  return request('/api/show/signup', {
    method: 'POST',
    body: JSON.stringify(form),
  })
}

/* ---------------------------------------------------------------------------
   对局接口：直接复用后端既有 /api/games 路由，规则完全由后端裁定
   --------------------------------------------------------------------------- */

/** 开新局，返回 {game_id, script_id} */
export function createGame(scriptId) {
  return request('/api/games', {
    method: 'POST',
    body: JSON.stringify({ script_id: scriptId }),
  })
}

/** 读取当前座位视角的对局状态（GameState） */
export function fetchGame(gameId, seatId = 'seat_1') {
  return request(`/api/games/${gameId}?seat_id=${seatId}`)
}

/** 已获得的线索（公开 + 私密） */
export function fetchClues(gameId, seatId = 'seat_1') {
  return request(`/api/games/${gameId}/clues?seat_id=${seatId}`)
}

/**
 * 某个地点的搜证候选。
 * 前置线索、地点容量、剩余点数由引擎（available_clues）判定，前端只做展示。
 */
export function fetchSearchOptions(gameId, locationId, seatId = 'seat_1') {
  const query = new URLSearchParams({ game_id: gameId, location_id: locationId, seat_id: seatId })
  return request(`/api/show/search-options?${query.toString()}`)
}

/**
 * 推进一步回合。
 * action 取值由后端 FSM 校验：begin / read_done / talk / enter_search / search /
 * leave_search / enter_private / private_talk / leave_private / enter_confront /
 * confront_talk / leave_confront / vote / recap / next_act / end
 */
export function postTurn(gameId, payload) {
  return request(`/api/games/${gameId}/turns`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
