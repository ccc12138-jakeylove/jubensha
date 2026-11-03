/**
 * 页面内提示条（不使用浏览器 alert）。
 * 固定底部居中，4.2 秒后由 App 自动关闭，也可点叉关闭。
 */
export default function Toast({ toast, onClose }) {
  if (!toast) return null

  const tone = toast.tone || 'info'

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: 'fixed',
        left: '50%',
        bottom: 'max(22px, env(safe-area-inset-bottom))',
        transform: 'translateX(-50%)',
        zIndex: 90,
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        maxWidth: 'min(92vw, 520px)',
        padding: '12px 16px',
        borderRadius: 12,
        border: `1px solid ${
          tone === 'ok' ? 'var(--gold)' : tone === 'warn' ? 'var(--accent-soft)' : 'var(--line)'
        }`,
        background: 'color-mix(in srgb, var(--bg) 88%, transparent)',
        boxShadow: '0 18px 40px rgba(0, 0, 0, 0.55)',
        backdropFilter: 'blur(12px)',
        animation: 'fadeUp 0.34s var(--ease) both',
      }}
    >
      <span style={{ fontSize: 13.5, lineHeight: 1.6, color: 'var(--ink)' }}>{toast.message}</span>
      <button
        type="button"
        onClick={onClose}
        aria-label="关闭提示"
        style={{
          marginLeft: 'auto',
          border: 0,
          background: 'transparent',
          color: 'var(--ink-dim)',
          cursor: 'pointer',
          fontSize: 16,
          lineHeight: 1,
          padding: 4,
        }}
      >
        ×
      </button>
    </div>
  )
}
