import { ArrowRight, CheckCircle, Info } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { appBenefits, evidenceFacts, GatePanel, PublicNav, valueFlow } from "../components.jsx";

export function HomePage() {
  return (
    <div className="marketing-page dark-page">
      <PublicNav />
      <main>
        <section className="hero" id="product">
          <div className="hero-copy">
            <p className="kicker">长尾数据智能与生产编排，面向具身机器人团队</p>
            <h1>从长尾缺口，到可采购结果</h1>
            <p className="hero-summary">
              把任务摘要转化为风险评分、预算编排与可审计输出，让生产预算对应可验证结果。
            </p>
            <div className="value-flow" aria-label="Q-Tail 产品流程">
              {valueFlow.map(({ icon: Icon, label, sub }, index) => (
                <div className="flow-step" key={label}>
                  <span className="flow-icon"><Icon size={28} /></span>
                  <strong>{label}</strong>
                  <span>{sub}</span>
                  {index < valueFlow.length - 1 && <ArrowRight className="flow-arrow" aria-hidden="true" />}
                </div>
              ))}
            </div>
            <p className="hero-note">
              Q-Tail 以四道采购 Gate 为核心框架：发现尾部缺口、编排生产预算、
              记录证据边界，并为轨迹生产与闭环评测提供可执行任务契约。
            </p>
            <div className="hero-actions">
              <Link className="button button-primary button-large" to="/register">申请设计伙伴</Link>
              <Link className="text-link" to="/evidence">查看证据边界 <ArrowRight /></Link>
            </div>
          </div>
          <GatePanel />
        </section>

        <section className="evidence-strip" aria-label="当前证据与审计快照">
          <div className="strip-title">
            <span></span>
            <div><h2>证据与审计快照</h2><p>基于当前可审计证据，非实时监控</p></div>
          </div>
          {evidenceFacts.map((fact) => (
            <article key={fact.label}>
              <strong>{fact.value}</strong>
              <h3>{fact.label}</h3>
              <p>{fact.note}</p>
            </article>
          ))}
        </section>

        <section className="product-section" id="gates">
          <div className="section-heading">
            <span className="eyebrow">PRODUCT SYSTEM</span>
            <h2>让采购团队看到证据，而不是只看到叙事</h2>
            <p>围绕机器人构型、训练格式、闭环指标和商业条款，形成同一份可追踪任务契约。</p>
          </div>
          <div className="benefit-grid">
            {appBenefits.map(({ icon: Icon, title, text }) => (
              <article key={title}><Icon size={27} /><h3>{title}</h3><p>{text}</p></article>
            ))}
          </div>
        </section>

        <section className="pricing-section" id="pricing">
          <div>
            <span className="eyebrow">COMMERCIAL PATH</span>
            <h2>先卖决策，再卖闭环结果</h2>
            <p>免费层用于了解方法与提交 API 申请；Pro 解锁数据工坊、API 密钥、运行记录和可审计交付包。</p>
            <div className="claim-note"><Info /> MetaWorld Sawyer 合成轨迹的 LeRobot/RLDS 双格式生产基线和闭环对照已通过；客户任务仍需接入其指定后端并完成独立与真机验收。</div>
          </div>
          <div className="pricing-card">
            <div className="price-head"><span>Q-TAIL PRO</span><strong>内测计划</strong></div>
            <ul>
              <li><CheckCircle weight="fill" /> 采购门槛配置检查</li>
              <li><CheckCircle weight="fill" /> 私有 API 密钥与配额</li>
              <li><CheckCircle weight="fill" /> Q-Tail 模型生成任务</li>
              <li><CheckCircle weight="fill" /> 版本、清单和审计记录</li>
            </ul>
            <Link className="button button-primary" to="/register">注册并申请 API <ArrowRight /></Link>
          </div>
        </section>
      </main>
      <footer className="dark-footer">
        <span>Q-TAIL · Coherent (Beijing) Technology Co., Ltd.</span>
        <span className="footer-links"><Link to="/terms">服务条款</Link><Link to="/privacy">隐私与数据</Link><Link to="/payment-policy">支付/退款/发票</Link></span>
      </footer>
    </div>
  );
}
