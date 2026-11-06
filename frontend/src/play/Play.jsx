import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createGame, fetchActView, fetchClues, fetchGame, fetchPublishedScripts,
  fetchSearchOptions, fetchShow, postTurn } from '../api.js'
import { avatarGradient, initialOf } from '../utils.js'

const SEAT = 'seat_1'
const STORAGE_KEY = 'jubensha-game-id'

function savedLog(gameId) {
  if (!gameId) return []
  try {
    const value = JSON.parse(localStorage.getItem(`${STORAGE_KEY}-log-${gameId}`) || '[]')
    return Array.isArray(value) ? value : []
  } catch {
    return []
  }
}

/** 阶段 → 中文标签 */
const PHASE_LABEL = {
  entry: '开场',
  read: '读本',
  act_open: '公聊',
  search: '搜证',
  private: '私聊',
  confront: '对质',
  vote: '投票',
  recap: '复盘',
  end: '结束',
}

/** 阶段 → 一句话提示，避免玩家不知道下一步能做什么 */
const PHASE_HINT = {
  entry: '点击「开局」进入这场雨夜。',
  read: '读完本幕的公开剧情，进入公聊。',
  act_open: '选择一个人提问，或者切换到搜证/私聊/对质。',
  search: '点击地点进行搜证，每次消耗搜索点数。',
  private: '现在是私聊，只有你和对面听得到。',
  confront: '对质阶段：可以逼问，也可以直接投票。',
  vote: '投票已提交，进入复盘查看真相。',
  recap: '案件已经结案，可以重开一局。',
  end: '本局结束。',
}

/**
 * 对局台：把后端 /api/games 的回合接口接成可玩界面。
 * 所有规则（阶段流转、点数扣除、泄密拦截）都由后端裁定，前端只负责发动作、渲染结果。
 */
export default function Play({ show, onExit }) {
  const [gameId, setGameId] = useState(() => localStorage.getItem(STORAGE_KEY) || '')
  const [state, setState] = useState(null)
  const [log, setLog] = useState(() => savedLog(localStorage.getItem(STORAGE_KEY)))
  const [activeShow, setActiveShow] = useState(show)
  const [publishedScripts, setPublishedScripts] = useState([])
  const [selectedScriptId, setSelectedScriptId] = useState(show?.script_id || '')
  const [actView, setActView] = useState(null)
  const [clues, setClues] = useState([])
  const [busy, setBusy] = useState(false)
  const [draft, setDraft] = useState('')
  const [target, setTarget] = useState('')
  const [motive, setMotive] = useState('')
  const [evidence, setEvidence] = useState([])
  const [sideTab, setSideTab] = useState('clues')
  const [error, setError] = useState('')
  // 搜证：先选地点，再选具体线索（或整点 bundle 搜证）
  const [place, setPlace] = useState(null)
  const [options, setOptions] = useState([])
  const [searchMode, setSearchMode] = useState('clue')
  const [remaining, setRemaining] = useState(0)
  const logRef = useRef(null)

  const characters = activeShow?.characters ?? []
  const locations = actView?.locations ?? activeShow?.locations ?? []
  const scriptOptions = publishedScripts.length ? publishedScripts
    : activeShow ? [{ script_id: activeShow.script_id, title: activeShow.title }] : []
  const phase = state?.phase ?? 'entry'
  const seat = state?.seats?.[SEAT]
  const searchPoints = seat?.search_points ?? 0

  useEffect(() => {
    if (!gameId && show) {
      setActiveShow(show)
      setSelectedScriptId((current) => current || show.script_id)
    }
  }, [gameId, show])

  useEffect(() => {
    fetchPublishedScripts().then(setPublishedScripts).catch((err) => setError(err.message))
  }, [])

  useEffect(() => {
    if (gameId) localStorage.setItem(`${STORAGE_KEY}-log-${gameId}`, JSON.stringify(log.slice(-200)))
  }, [gameId, log])

  /** 统一写一条对话记录 */
  const pushLog = useCallback((who, text, tone = 'normal') => {
    setLog((current) => [...current, { id: `${Date.now()}-${current.length}`, who, text, tone }])
  }, [])

  const refreshClues = useCallback(async (id) => {
    if (!id) return
    try {
      setClues(await fetchClues(id))
    } catch {
      /* 线索拉取失败不阻塞主流程 */
    }
  }, [])

  // 首次进入 / 刷新后恢复上一局
  useEffect(() => {
    if (!gameId) return
    let alive = true
    fetchGame(gameId)
      .then((next) => {
        if (!alive) return
        setState(next)
        Promise.all([fetchShow(next.script_id), fetchActView(gameId)]).then(([details, act]) => {
          if (!alive) return
          setActiveShow(details)
          setActView(act)
          setSelectedScriptId(next.script_id)
        }).catch((err) => { if (alive) setError(err.message) })
        refreshClues(gameId)
        pushLog('system', `已恢复上一局（${PHASE_LABEL[next.phase] || next.phase}）`)
      })
      .catch(() => {
        if (!alive) return
        localStorage.removeItem(STORAGE_KEY)
        setGameId('')
      })
    return () => {
      alive = false
    }
    // 只在挂载时尝试恢复一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 新消息出现时把对话区滚到底
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: 'smooth' })
  }, [log])

  /** 开局 */
  const start = async () => {
    setBusy(true)
    setError('')
    try {
      const created = await createGame(selectedScriptId || show?.script_id)
      localStorage.setItem(STORAGE_KEY, created.game_id)
      setGameId(created.game_id)
      setLog([])
      pushLog('system', '档案已开封，雨夜开始。')
      const next = await fetchGame(created.game_id)
      setState(next)
      const [details, act] = await Promise.all([
        fetchShow(next.script_id), fetchActView(created.game_id),
      ])
      setActiveShow(details)
      setActView(act)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  /** 发送一个回合动作 */
  const act = async (action, extra = {}, { quiet = false } = {}) => {
    if (!gameId || busy) return
    setBusy(true)
    setError('')
    try {
      const result = await postTurn(gameId, { seat_id: SEAT, action, ...extra })
      setState(result.state)
      if (result.state.act_id !== state?.act_id || !actView) {
        setActView(await fetchActView(gameId))
      }
      if (result.reply) {
        pushLog(extra.role_id ? 'npc' : 'system', result.reply)
      } else if (!quiet) {
        pushLog('system', `已执行：${action}`)
      }
      await refreshClues(gameId)
      return result
    } catch (err) {
      setError(err.message)
      pushLog('system', err.message, 'warn')
    } finally {
      setBusy(false)
    }
  }

  /** 公聊提问 */
  const talk = async () => {
    const text = draft.trim()
    if (!text) return
    const roleId = phase === 'private' ? state?.private_role_id : target
    if (!roleId) {
      setError('先选一个对话对象')
      return
    }
    pushLog('player', text)
    setDraft('')
    const action = phase === 'private' ? 'private_talk' : phase === 'confront' ? 'confront_talk' : 'talk'
    await act(action, { role_id: roleId, text })
  }

  /** 打开一个地点，拉取该地点当前可搜的线索（规则由引擎判定） */
  const openPlace = async (loc) => {
    setPlace(loc)
    setOptions([])
    setError('')
    setBusy(true)
    try {
      const res = await fetchSearchOptions(gameId, loc.id)
      setOptions(res.options || [])
      setSearchMode(res.mode || 'clue')
      setRemaining(res.remaining ?? 0)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  /** 搜证：bundle 模式按地点整搜，否则指定具体线索 */
  const doSearch = async (clueId) => {
    if (!place) return
    const bundle = searchMode === 'location_bundle'
    await act(
      bundle ? 'search_bundle' : 'search',
      bundle ? { location_id: place.id } : { location_id: place.id, clue_id: clueId },
    )
    await openPlace(place)
  }

  /** 投票 */
  const doVote = async () => {
    if (!target) {
      setError('先选一个你要指认的人')
      return
    }
    if (!motive.trim()) {
      setError('写一句你的推理动机')
      return
    }
    await act('vote', { role_id: target, motive: motive.trim(), evidence_ids: evidence })
  }

  const nameOf = useMemo(() => {
    const map = {}
    characters.forEach((item) => {
      map[item.role_id] = item.name
    })
    return (id) => map[id] || id || '某人'
  }, [characters])

  const toggleEvidence = (clueId) => {
    setEvidence((current) =>
      current.includes(clueId) ? current.filter((item) => item !== clueId) : [...current, clueId],
    )
  }

  /* ---------------- 未开局 ---------------- */
  if (!gameId) {
    return (
      <div className="play play--idle">
        <div className="play__card">
          <p className="section-kicker">New Case</p>
          <h1 className="play__title">{activeShow?.title || '剧本杀'}</h1>
          <label className="play__script-select">
            剧本
            <select value={selectedScriptId} disabled={busy} onChange={async (event) => {
              const scriptId = event.target.value
              setSelectedScriptId(scriptId)
              setError('')
              try {
                setActiveShow(await fetchShow(scriptId))
              } catch (err) {
                setError(err.message)
              }
            }}>
              {scriptOptions.map((item) => (
                <option key={item.script_id} value={item.script_id}>{item.title}</option>
              ))}
            </select>
          </label>
          <p className="play__desc">
            {PHASE_HINT.entry}
            <br />
            单机单人视角：你以旁观者身份盘问所有角色，规则与证据链由后端裁定。
          </p>
          <div className="play__idle-actions">
            <button type="button" className="btn btn--primary" onClick={start}
              disabled={busy || !selectedScriptId}>
              {busy ? '正在铺桌…' : '开局'}
            </button>
            <button type="button" className="btn" onClick={onExit}>
              返回介绍页
            </button>
          </div>
          {error && <p className="field__error">{error}</p>}
        </div>
      </div>
    )
  }

  /* ---------------- 对局中 ---------------- */
  return (
    <div className="play">
      {/* 顶部状态条 */}
      <header className="play__bar">
        <button type="button" className="btn btn--ghost" onClick={onExit}>
          ← 介绍页
        </button>
        <span className="play__act">{actView?.title || activeShow?.act_title || '第一幕'}</span>
        <span className={`play__phase play__phase--${phase}`}>{PHASE_LABEL[phase] || phase}</span>
        <span className="play__stat">回合 {state?.turn ?? 0}</span>
        <span className="play__stat">搜索点 {searchPoints}</span>
        <span className="play__stat">私聊 {state?.private_chats_used ?? 0} 次</span>
        <button
          type="button"
          className="btn btn--ghost"
          onClick={() => {
            localStorage.removeItem(STORAGE_KEY)
            setGameId('')
            setState(null)
            setLog([])
            setClues([])
          }}
        >
          重开
        </button>
      </header>

      <p className="play__hint">{PHASE_HINT[phase]}</p>

      <div className="play__body">
        {/* 左：对话与操作 */}
        <section className="play__main">
          <div className="play__log" ref={logRef}>
            {log.length === 0 && <p className="play__empty">还没有对话，先读本或找人问话。</p>}
            {log.map((item) => (
              <div key={item.id} className={`bubble bubble--${item.who} ${item.tone === 'warn' ? 'is-warn' : ''}`}>
                <span className="bubble__who">
                  {item.who === 'player' ? '你' : item.who === 'npc' ? '现场' : '系统'}
                </span>
                <p className="bubble__text">{item.text}</p>
              </div>
            ))}
          </div>

          {/* 读本 */}
          {phase === 'read' && (
            <div className="play__read">
              <h2>{actView?.title || activeShow?.act_title}</h2>
              <p>{actView?.narrative || activeShow?.act_narrative}</p>
              <button type="button" className="btn btn--primary" onClick={() => act('read_done')} disabled={busy}>
                读完了，进入公聊
              </button>
            </div>
          )}

          {/* 公聊 / 私聊 / 对质：输入框 */}
          {(phase === 'act_open' || phase === 'private' || phase === 'confront') && (
            <div className="play__composer">
              {phase !== 'private' && (
                <div className="chips">
                  {characters.map((person) => (
                    <button
                      key={person.role_id}
                      type="button"
                      className={`chip ${target === person.role_id ? 'is-on' : ''}`}
                      onClick={() => setTarget(person.role_id)}
                    >
                      <span className="chip__dot" style={{ background: avatarGradient(person.role_id) }} />
                      {person.name}
                    </button>
                  ))}
                </div>
              )}
              {phase === 'private' && (
                <p className="play__note">
                  私聊对象：{nameOf(state?.private_role_id)}
                </p>
              )}
              <div className="play__input">
                <textarea
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault()
                      talk()
                    }
                  }}
                  placeholder={phase === 'confront' ? '逼问对方，或说出你的推理…' : '你想问什么？'}
                  rows={2}
                />
                <button type="button" className="btn btn--primary" onClick={talk} disabled={busy}>
                  {busy ? '…' : '发送'}
                </button>
              </div>
            </div>
          )}

          {/* 搜证：先选地点，再选具体线索 */}
          {phase === 'search' && (
            <div className="play__search">
              {!place && (
                <>
                  {locations.map((loc) => (
                    <button
                      key={loc.id}
                      type="button"
                      className="place"
                      onClick={() => openPlace(loc)}
                      disabled={busy || searchPoints <= 0}
                    >
                      <span className="place__name">{loc.name}</span>
                      <span className="place__meta">{loc.clue_count} 条线索</span>
                    </button>
                  ))}
                  {searchPoints <= 0 && <p className="field__error">搜索点数已用完，离开搜证继续剧情。</p>}
                </>
              )}

              {place && (
                <div className="play__spot">
                  <div className="play__spot-head">
                    <b>{place.name}</b>
                    <span className="play__stat">本地点剩余 {remaining} 次</span>
                    <button
                      type="button"
                      className="btn btn--ghost"
                      onClick={() => {
                        setPlace(null)
                        setOptions([])
                      }}
                    >
                      换地点
                    </button>
                  </div>

                  {searchMode === 'location_bundle' ? (
                    <button
                      type="button"
                      className="clueopt"
                      onClick={() => doSearch('')}
                      disabled={busy || remaining <= 0 || searchPoints < 1}
                    >
                      <b>整点搜查</b>
                      <span>一次翻完这个地点 · 1 点</span>
                    </button>
                  ) : (
                    <>
                      {options.map((option) => (
                        <button
                          key={option.clue_id}
                          type="button"
                          className="clueopt"
                          onClick={() => doSearch(option.clue_id)}
                          disabled={busy || option.cost > searchPoints}
                        >
                          <b>{option.label}</b>
                          <span>{option.cost} 点</span>
                        </button>
                      ))}
                      {options.length === 0 && (
                        <p className="play__note">这里暂时搜不到新东西：可能已被搜走、需要前置线索，或点数不够。</p>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          )}

          {/* 投票 */}
          {phase === 'vote' && (
            <div className="play__vote">
              <p className="play__note">已投给 {nameOf(state?.vote_role_id)}，动机：{state?.vote_motive || '—'}</p>
              <button type="button" className="btn btn--primary"
                onClick={() => act(actView?.is_final ? 'recap' : 'next_act')} disabled={busy || !actView}>
                {actView?.is_final ? '查看复盘' : '进入下一幕'}
              </button>
            </div>
          )}

          {/* 复盘 */}
          {phase === 'recap' && (
            <div className="play__recap">
              <p className="play__note">结案陈词已生成，见上方对话；可以重开一局或回到介绍页。</p>
            </div>
          )}

          {error && <p className="field__error">{error}</p>}
        </section>

        {/* 右：动作 + 随身档案 */}
        <aside className="play__side">
          <div className="play__actions">
            {phase === 'entry' && (
              <button type="button" className="btn btn--primary" onClick={() => act('begin')} disabled={busy}>
                开始阅读
              </button>
            )}
            {phase === 'act_open' && (
              <>
                <button type="button" className="btn" onClick={() => act('enter_search')} disabled={busy}>
                  去搜证
                </button>
                <button
                  type="button"
                  className="btn"
                  onClick={() => {
                    if (!target) {
                      setError('先选一个私聊对象')
                      return
                    }
                    act('enter_private', { role_id: target })
                  }}
                  disabled={busy}
                >
                  私聊
                </button>
                <button type="button" className="btn" onClick={() => act('enter_confront')} disabled={busy}>
                  进入对质
                </button>
              </>
            )}
            {phase === 'search' && (
              <button type="button" className="btn" onClick={() => act('leave_search')} disabled={busy}>
                离开搜证
              </button>
            )}
            {phase === 'private' && (
              <button type="button" className="btn" onClick={() => act('leave_private')} disabled={busy}>
                结束私聊
              </button>
            )}
            {phase === 'confront' && (
              <>
                <button type="button" className="btn" onClick={() => act('leave_confront')} disabled={busy}>
                  回到公聊
                </button>
                {actView && !actView.requires_vote && !actView.is_final && (
                  <button type="button" className="btn btn--ghost"
                    onClick={() => act('next_act')} disabled={busy}>
                    下一幕
                  </button>
                )}
              </>
            )}
            {phase === 'vote' && (
              <button type="button" className="btn"
                onClick={() => act(actView?.is_final ? 'recap' : 'next_act')}
                disabled={busy || !actView}>
                {actView?.is_final ? '查看复盘' : '进入下一幕'}
              </button>
            )}
          </div>

          {/* 投票表单：仅对质阶段 */}
          {phase === 'confront' && (
            <div className="play__voteform">
              <p className="play__subtitle">提交指认</p>
              <textarea
                rows={2}
                value={motive}
                onChange={(event) => setMotive(event.target.value)}
                placeholder="动机与推理过程"
              />
              <p className="play__subtitle">引用的线索</p>
              <div className="chips chips--stack">
                {clues.map((clue) => (
                  <button
                    key={clue.clue_id}
                    type="button"
                    className={`chip ${evidence.includes(clue.clue_id) ? 'is-on' : ''}`}
                    onClick={() => toggleEvidence(clue.clue_id)}
                  >
                    {clue.display_name}
                  </button>
                ))}
                {clues.length === 0 && <span className="play__note">还没有搜到线索</span>}
              </div>
              <button type="button" className="btn btn--primary" onClick={doVote} disabled={busy}>
                投票指认 {target ? `：${nameOf(target)}` : ''}
              </button>
            </div>
          )}

          {/* 随身档案 */}
          <div className="play__tabs">
            <button
              type="button"
              className={sideTab === 'clues' ? 'is-on' : ''}
              onClick={() => setSideTab('clues')}
            >
              线索 {clues.length}
            </button>
            <button
              type="button"
              className={sideTab === 'people' ? 'is-on' : ''}
              onClick={() => setSideTab('people')}
            >
              人物
            </button>
          </div>

          {sideTab === 'clues' ? (
            <ul className="play__clues">
              {clues.map((clue) => (
                <li key={clue.clue_id}>
                  <b>{clue.display_name}</b>
                  <span>{clue.surface_text}</span>
                </li>
              ))}
              {clues.length === 0 && <li className="play__note">还没有搜到线索</li>}
            </ul>
          ) : (
            <ul className="play__people">
              {characters.map((person) => (
                <li key={person.role_id}>
                  <span className="suspect__dot" style={{ '--avatar': avatarGradient(person.role_id) }} />
                  <div>
                    <b>{person.name}</b>
                    <span>{person.identity}</span>
                  </div>
                  <button type="button" className="btn btn--ghost" onClick={() => setTarget(person.role_id)}>
                    选为目标
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>
      </div>
    </div>
  )
}
