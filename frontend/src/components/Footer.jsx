/** 页脚：版权与免责声明 */
export default function Footer({ data }) {
  const year = new Date().getFullYear()

  return (
    <footer className="footer">
      <div className="wrap footer__inner">
        <div>
          <div className="footer__brand">雾港档案室 · {data?.title || '雾港谜案'}</div>
          <p className="footer__note">
            本站为剧本杀作品的宣传与预约页面，剧情、角色与线索均为虚构，如与现实人物或事件相似纯属巧合。
            页面不收集除场次联络外的个人信息；未满 16 周岁请在监护人陪同下参与。
          </p>
        </div>

        <div className="footer__meta">
          <div>© {year} 雾港档案室</div>
          <div>ALL NAMES FICTIONAL</div>
        </div>
      </div>
    </footer>
  )
}
