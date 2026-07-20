import { ArrowRight, ChartPieSlice, CheckCircle, Circle, ClipboardText, DownloadSimple, FileText, GearSix, Scales, ShareNetwork, ShieldCheck, Target } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { PublicNav } from "../components.jsx";

const gates = [
  { id: 0, icon: ClipboardText, title: "重新定义商品", copy: "统一为长尾数据智能/分配服务，修复 Strong 状态与复现口径。", state: "已完成" },
  { id: 1, icon: ShareNetwork, title: "轨迹生产", copy: "Sawyer/MuJoCo 新执行 64 条、3,285 帧合成 episode；LeRobot v3 官方 loader 与 RLDS TFRecord 逐帧校验均通过。", state: "仿真生产基线通过", href: "/evidence/gate1-summary.json" },
  { id: 2, icon: Scales, title: "闭环对照", copy: "直接读取 Gate 1 合成包，同策略、同 64 条轨迹预算完成 900 回合；Tail SR +16.33 pp，95% CI 下界 +12.00 pp。", state: "仿真对照通过", href: "/evidence/gate2-summary.json" },
  { id: 3, icon: GearSix, title: "真机与合同", copy: "本地完成 3 个任务、600 回合安全测试；真机、买方验收与合同不以仿真替代。", state: "外部验收待完成", href: "/evidence/gate3-summary.json" },
];

export function EvidencePage() {
  return (
    <div className="evidence-page light-page">
      <PublicNav light />
      <main className="evidence-main">
        <section className="evidence-hero">
          <div className="evidence-intro">
            <h1>先卖决策，再卖闭环结果</h1>
            <p>Q-Tail 帮助团队识别罕见失败簇、分配仿真与采集预算，并交付可审计的生产方案。</p>
            <ul>
              <li><CheckCircle /> 区分公共轨迹、闭环仿真与真实机器人证据</li>
              <li><CheckCircle /> 当前不把分配 CSV 称为可训练数据集</li>
              <li><CheckCircle /> 同预算条件下，为关键场景提供生产优先级</li>
            </ul>
          </div>
          <article className="readiness-ledger">
            <div className="ledger-heading"><h2>当前可审计证据</h2><span>截至 2026-07-17</span></div>
            <p>本地可复现结果；不含客户真机和采购签字</p>
            <div className="score-row">
              <div><span>Gate 2 闭环 Tail SR</span><strong>+16.33<small> pp</small></strong></div>
              <div className="score-status blue"><Circle weight="fill" /><div><b>受控仿真通过</b><p>同策略、同预算；95% 配对区间为 +12.00～+20.67 pp。</p></div></div>
            </div>
            <div className="score-row">
              <div><span>Gate 3 仿真等价成本</span><strong className="amber">−24.02<small>%</small></strong></div>
              <div className="score-status amber"><Circle weight="fill" /><div><b>模型值，非发票值</b><p>真机成本、客户任务和合同验收仍需外部证据。</p></div></div>
            </div>
            <small>原始评估中的 34.5/100 与 58/100 是推进 Gate 之前的基线，不在这里伪装为实时评分。</small>
          </article>
        </section>

        <section className="evidence-gates">
          <div className="evidence-section-title"><h2>从评测到闭环的四道采购 Gate</h2></div>
          <div className="horizontal-gates">
            {gates.map((gate) => {
              const GateIcon = gate.icon;
              return (
              <article key={gate.id}>
                <span className={`gate-number ${gate.id === 3 ? "waiting" : ""}`}><GateIcon weight="regular" /></span>
                <div><span>Gate {gate.id}</span><h3>{gate.title}</h3><p>{gate.copy}</p><small>{gate.state}</small>{gate.href && <a className="evidence-download" href={gate.href} download>JSON 证据 <ArrowRight /></a>}</div>
              </article>
              );
            })}
          </div>
        </section>

        <section className="pilot-kit-section" id="pilot-kit" aria-labelledby="pilot-kit-title">
          <div className="pilot-kit-heading">
            <div><span>BUYER PILOT KIT · v1.2.0</span><h2 id="pilot-kit-title">把验收要求交给机器人厂商执行</h2><p>一套可直接回传的采购工作底稿与 Gate 1 校验器，覆盖冻结 SOW、机器人与数据契约、生产后端数据包/日志核验、Gate 1–3 原始记录、真机/成本台账、双方独立签署凭证和合同归档检查。</p></div>
            <div className="pilot-kit-actions">
              <a className="button button-ink" href="/buyer-kit/qtail-buyer-pilot-kit-v1.2.0.zip" download><DownloadSimple /> 下载完整试点包</a>
              <a href="/buyer-kit/qtail-buyer-pilot-kit-v1.2.0.zip.sha256" download>SHA-256 校验文件</a>
              <a href="/buyer-kit/manifest.json" download>查看逐文件 Manifest</a>
            </div>
          </div>
          <div className="pilot-kit-grid">
            <article><ClipboardText /><span>01</span><h3>冻结 SOW 与构型</h3><p>机器人、传感器、控制频率、策略、预算、任务、部署与责任人先写清。</p></article>
            <article><FileText /><span>02</span><h3>执行 Gate 1 校验器</h3><p>核对厂商后端数据包、生产日志、机器人契约和 SHA-256；篡改或空白模板直接失败。</p></article>
            <article><Target /><span>03</span><h3>逐回合真机与成本账本</h3><p>保留试验、急停、日志、视频、发票或财务账本的原始可核验记录。</p></article>
            <article><ShieldCheck /><span>04</span><h3>买方签字与合同哈希</h3><p>签名必须在平台外真实完成；系统只归档原件、签署件和执行合同哈希。</p></article>
          </div>
          <div className="pilot-kit-boundary"><ShieldCheck /><p><strong>声明边界：</strong>试点包不含买方数据、真实机器人结果、发票、法律意见或签名。只有买方填写、外部签署并经运营核验的 `buyer_external` 证据才可能进入采购合同。</p></div>
        </section>

        <section className="audit-offer">
          <div>
            <span>商业定位与首个可采购服务</span>
            <h2>Long-Tail Data Audit</h2>
            <p>为工业操控团队提供尾部缺口定位、预算方案与可审计报告，支持采购决策与内部立项。</p>
            <div className="pro-api-badge"><ShieldCheck /> Pro API 可用</div>
          </div>
          <div className="deliverables">
            <article><Target /><h3>尾部缺口</h3><p>识别罕见失败簇与风险排序。</p></article>
            <article><ChartPieSlice /><h3>预算方案</h3><p>输出仿真与采集优先级建议。</p></article>
            <article><FileText /><h3>可审计报告</h3><p>记录方法、版本、清单与证据边界。</p></article>
          </div>
          <div className="offer-cta"><span>交付与定价</span><h3>按项目/工位报价</h3><p>范围、周期与交付物以 SOW 为准。</p><Link className="button button-ink" to="/register">申请评估 <ArrowRight /></Link></div>
        </section>
      </main>
      <footer className="light-footer"><span>合规与安全：最小化处理客户数据 · 完整审计日志 · 权限分离</span><span className="footer-links"><Link to="/terms">服务条款</Link><Link to="/privacy">隐私与数据</Link><Link to="/payment-policy">支付/退款/发票</Link></span></footer>
    </div>
  );
}
