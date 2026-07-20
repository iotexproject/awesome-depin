import {
  ArrowRight,
  Check,
  CheckCircle,
  ClipboardText,
  Copy,
  DownloadSimple,
  FileText,
  Info,
  Key,
  Lock,
  Plus,
  Receipt,
  ShieldCheck,
  SpinnerGap,
  Trash,
  UploadSimple,
  WarningCircle,
  XCircle,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import QRCode from "qrcode";
import { useAuth } from "../AuthContext.jsx";
import { apiFetch, formatDate, formatMoney } from "../api.js";

const initialStudioForm = {
  delivery_product: "allocation_plan",
  trajectory_count: 16,
  robot_model: "Franka Panda",
  control_frequency_hz: 20,
  sensors: "RGB-D + 关节状态",
  training_format: "RLDS + LeRobot v3",
  production_backend: "MuJoCo",
  synthetic_budget: 100000,
  filename: "customer_tasks.csv",
  csv_text: "task,count,success_rate,difficulty,group\nrare_pick,12,0.32,0.91,tail\nstandard_pick,540,0.86,0.22,head\n",
  claim_acknowledged: true,
  data_rights: {
    source_type: "customer_owned",
    license_basis: "客户自有任务统计与失败日志",
    contains_personal_data: false,
    retention_days: 90,
    source_rights_confirmed: false,
    derivative_rights_confirmed: false,
    restricted_data_excluded: false,
  },
};

function PageHeader({ eyebrow, title, description, action }) {
  return <div className="workspace-page-header"><div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h1>{title}</h1><p>{description}</p></div>{action}</div>;
}

export function OverviewPage() {
  const { user } = useAuth();
  const [data, setData] = useState(null);
  useEffect(() => { apiFetch("/api/dashboard").then(setData).catch(() => setData(null)); }, []);
  const nextStep = !data?.api_application
    ? { title: "提交 API 申请", text: "说明团队、机型、训练栈和首个 PoC 目标。", to: "/app/api" }
    : !user?.is_pro
      ? { title: "开通 Pro", text: "完成二维码下单与人工核验后解锁。", to: "/app/billing" }
      : !data?.generation_count
        ? { title: "创建采购级任务", text: "配置机器人约束并运行 Q-Tail 生成任务。", to: "/app/studio" }
        : !data?.compliance?.ready_for_contract
          ? { title: "提交合规与数据权利资料", text: "锁定来源授权、DPA、部署、驻留与删除边界。", to: "/app/compliance" }
        : !data?.procurement_case_count
          ? { title: "建立采购验证项目", text: "从已完成任务进入 Gate 1–3 证据与审核流程。", to: "/app/gates" }
          : { title: "推进采购 Gate", text: "提交下一道买方证据，直到合同就绪。", to: "/app/gates" };
  return (
    <div className="workspace-page">
      <PageHeader eyebrow="WORKSPACE OVERVIEW" title={`你好，${user?.name || "设计伙伴"}`} description="从 API 申请、Pro 开通到采购 Gate 与生成任务，所有状态都在同一处追踪。" action={<Link className="button button-primary" to="/app/studio">创建任务 <ArrowRight /></Link>} />
      <section className="workspace-stats">
        <article><span>会员状态</span><strong>{user?.is_pro ? "Pro 已开通" : "Free"}</strong><p>{user?.is_pro ? `有效期至 ${formatDate(user.pro_expires_at)}` : "生成与 API 密钥需要 Pro"}</p></article>
        <article><span>API 申请</span><strong>{data?.api_application?.status_label || "未提交"}</strong><p>采购场景与用途审核</p></article>
        <article><span>API 密钥</span><strong>{data?.api_key_count ?? 0}</strong><p>仅展示活跃密钥数量</p></article>
        <article><span>生成任务</span><strong>{data?.generation_count ?? 0}</strong><p>含运行中与已完成任务</p></article>
      </section>
      <section className="workspace-grid">
        <article className="next-step-card">
          <span>推荐下一步</span>
          <h2>{nextStep.title}</h2>
          <p>{nextStep.text}</p>
          <Link className="text-link" to={nextStep.to}>继续 <ArrowRight /></Link>
        </article>
        <article className="truth-card">
          <Info weight="fill" />
          <div><h2>当前声明边界</h2><p>Pro 可下载完整 64 条 MetaWorld/Sawyer 双格式样包，也可按受支持任务请求 1–64 条 RLDS-compatible 模拟轨迹。两者都是 Q-Tail 模拟交付，不等于买方独立验收、真机证据或采购通过。</p></div>
        </article>
      </section>
    </div>
  );
}

export function AccountPage() {
  const { user } = useAuth();
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function exportAccount() {
    setWorking(true); setError(""); setMessage("");
    try {
      const data = await apiFetch("/api/account/export");
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const anchor = document.createElement("a");
      anchor.href = url; anchor.download = `qtail-account-${user.id}.json`; anchor.click();
      URL.revokeObjectURL(url);
      setMessage("账户数据导出已生成。文件包含账户、订单、任务和采购记录，不含密码或 API 密钥原文。");
    } catch (err) { setError(err.message); }
    finally { setWorking(false); }
  }

  async function closeAccount(event) {
    event.preventDefault();
    setWorking(true); setError(""); setMessage("");
    try {
      await apiFetch("/api/account", { method: "DELETE", body: JSON.stringify({ password, confirmation }) });
      window.location.assign("/");
    } catch (err) { setError(err.message); setWorking(false); }
  }

  return <div className="workspace-page account-page">
    <PageHeader eyebrow="ACCOUNT & DATA RIGHTS" title="账户与数据" description="导出账户记录、查看保存边界，或验证密码后关闭账户并撤销访问凭据。" />
    <section className="account-grid">
      <article className="workspace-panel account-card"><ShieldCheck size={30} /><span>当前账户</span><h2>{user.name}</h2><p>{user.email}<br />{user.company}</p><small>计划：{user.is_pro ? "Pro" : "Free"} · 用户 ID：{user.id}</small></article>
      <article className="workspace-panel account-card"><DownloadSimple size={30} /><span>数据副本</span><h2>导出 JSON</h2><p>包含账户资料、API 申请、订单、生成任务、采购项目与合同索引。</p><button className="button button-secondary" disabled={working} onClick={exportAccount}>导出账户数据</button></article>
    </section>
    {message && <div className="form-success"><CheckCircle />{message}</div>}
    {error && <div className="form-error"><WarningCircle />{error}</div>}
    <form className="workspace-panel danger-zone" onSubmit={closeAccount}>
      <div><span>DANGER ZONE</span><h2>关闭账户</h2><p>将撤销所有 Session 和 API 密钥、终止未完成订单、关闭活跃采购项目并匿名化身份。依法需保留的支付、审计与合同证据不会被伪造删除。</p></div>
      <div className="form-grid two-columns"><label>当前密码<input required type="password" value={password} onChange={(event) => setPassword(event.target.value)} /></label><label>输入 CLOSE MY ACCOUNT<input required value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label></div>
      <button className="button danger-button" disabled={working || confirmation !== "CLOSE MY ACCOUNT"}>永久关闭账户</button>
    </form>
  </div>;
}

export function CompliancePage() {
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [form, setForm] = useState(() => ({
    organization_legal_name: user?.company || "",
    security_contact_email: user?.email || "",
    deployment_boundary: "qtail_cloud",
    data_residency: "中国大陆",
    retention_days: 90,
    deletion_sla_days: 30,
    source_rights_confirmed: false,
    derivative_rights_confirmed: false,
    restricted_data_excluded: false,
    subprocessor_reviewed: false,
    terms_accepted: false,
    privacy_acknowledged: false,
    dpa_accepted: false,
  }));
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function refresh() {
    const result = await apiFetch("/api/compliance");
    setData(result);
    if (result.profile) {
      setForm((current) => ({
        ...current,
        organization_legal_name: result.profile.organization_legal_name,
        security_contact_email: result.profile.security_contact_email,
        deployment_boundary: result.profile.deployment_boundary,
        data_residency: result.profile.data_residency,
        retention_days: result.profile.retention_days,
        deletion_sla_days: result.profile.deletion_sla_days,
      }));
    }
  }
  useEffect(() => { refresh().catch((err) => setError(err.message)); }, []);
  function setField(key, value) { setForm((current) => ({ ...current, [key]: value })); }
  async function submit(event) {
    event.preventDefault(); setWorking(true); setError(""); setMessage("");
    try {
      await apiFetch("/api/compliance", { method: "PUT", body: JSON.stringify(form) });
      setMessage("合规资料和协议版本已哈希存档，等待运营人员复核。资料变更会生成新版本并重新审核。");
      await refresh();
    } catch (err) { setError(err.message); }
    finally { setWorking(false); }
  }
  const profile = data?.profile;
  const allAccepted = form.source_rights_confirmed && form.derivative_rights_confirmed && form.restricted_data_excluded && form.subprocessor_reviewed && form.terms_accepted && form.privacy_acknowledged && form.dpa_accepted;
  return <div className="workspace-page compliance-page">
    <PageHeader eyebrow="DATA RIGHTS & SECURITY" title="合规与数据权利中心" description="把来源授权、衍生权、DPA、部署边界、驻留和删除期限变成版本化采购证据。" />
    {error && <div className="form-error"><WarningCircle /> {error}</div>}
    {message && <div className="form-success"><CheckCircle /> {message}</div>}
    <section className="compliance-summary">
      <article className="workspace-panel"><span>采购准入状态</span><strong>{data?.ready_for_contract ? "已满足" : profile?.status_label || "未提交"}</strong><p>{data?.ready_for_contract ? "当前协议版本与合规资料均已批准。" : "合同记录只能在运营复核通过后生成。"}</p></article>
      <article className="workspace-panel"><span>资料版本</span><strong>{profile ? `v${profile.version}` : "—"}</strong><p className="hash-value">{profile?.profile_sha256 || "提交后生成不可变 SHA-256"}</p></article>
      <article className="workspace-panel"><span>文件接受记录</span><strong>{data?.legal_acceptances?.length || 0}/3</strong><p>服务条款、隐私说明、DPA/数据处理附件。</p></article>
    </section>
    <form className="workspace-panel compliance-form" onSubmit={submit}>
      <div className="panel-heading"><div><h2>企业处理边界</h2><p>以下字段会进入 Gate 3 与合同验收快照。</p></div>{profile && <span className={`status-badge status-${profile.status}`}>{profile.status_label}</span>}</div>
      <div className="form-grid two-columns">
        <label>企业法定名称 *<input value={form.organization_legal_name} onChange={(e) => setField("organization_legal_name", e.target.value)} /></label>
        <label>安全联系人邮箱 *<input type="email" value={form.security_contact_email} onChange={(e) => setField("security_contact_email", e.target.value)} /></label>
        <label>部署边界 *<select value={form.deployment_boundary} onChange={(e) => setField("deployment_boundary", e.target.value)}><option value="qtail_cloud">Q-Tail 托管环境</option><option value="customer_vpc">客户 VPC</option><option value="on_prem">客户本地部署</option></select></label>
        <label>数据驻留 *<input value={form.data_residency} onChange={(e) => setField("data_residency", e.target.value)} /></label>
        <label>默认保存期限（天） *<input type="number" min="7" max="3650" value={form.retention_days} onChange={(e) => setField("retention_days", Number(e.target.value))} /></label>
        <label>删除处理 SLA（天） *<input type="number" min="1" max="90" value={form.deletion_sla_days} onChange={(e) => setField("deletion_sla_days", Number(e.target.value))} /></label>
      </div>
      <div className="compliance-attestations">
        <label><input type="checkbox" checked={form.source_rights_confirmed} onChange={(e) => setField("source_rights_confirmed", e.target.checked)} /><span>企业确认对上传数据和机器人日志具有合法处理授权。</span></label>
        <label><input type="checkbox" checked={form.derivative_rights_confirmed} onChange={(e) => setField("derivative_rights_confirmed", e.target.checked)} /><span>企业确认约定范围内的分配计划、场景规格和衍生处理权。</span></label>
        <label><input type="checkbox" checked={form.restricted_data_excluded} onChange={(e) => setField("restricted_data_excluded", e.target.checked)} /><span>共享入口不上传个人信息、秘密、出口管制或其他无权处理数据。</span></label>
        <label><input type="checkbox" checked={form.subprocessor_reviewed} onChange={(e) => setField("subprocessor_reviewed", e.target.checked)} /><span>已了解托管/监控/备份等受托处理者须在正式项目中列入清单。</span></label>
        <label><input type="checkbox" checked={form.terms_accepted} onChange={(e) => setField("terms_accepted", e.target.checked)} /><span>接受当前版本的 <Link to="/terms" target="_blank">服务条款</Link>。</span></label>
        <label><input type="checkbox" checked={form.privacy_acknowledged} onChange={(e) => setField("privacy_acknowledged", e.target.checked)} /><span>确认已阅读当前 <Link to="/privacy" target="_blank">隐私与数据处理说明</Link>。</span></label>
        <label><input type="checkbox" checked={form.dpa_accepted} onChange={(e) => setField("dpa_accepted", e.target.checked)} /><span>接受当前 <Link to="/dpa" target="_blank">数据处理附件</Link> 版本；最终项目仍以双方签署 DPA/SOW 为准。</span></label>
      </div>
      {profile?.review_note && <div className="review-note"><strong>审核备注</strong><p>{profile.review_note}</p></div>}
      <button className="button button-primary" disabled={working || !allAccepted}>{working ? "提交中…" : profile ? "提交新版本复核" : "提交合规资料"}</button>
    </form>
  </div>;
}

function StudioGateRail({ form, result }) {
  const rightsReady = Boolean(form.data_rights.source_rights_confirmed && form.data_rights.derivative_rights_confirmed && form.data_rights.restricted_data_excluded);
  const gate1Ready = Boolean(form.robot_model && form.control_frequency_hz && form.sensors && form.training_format && form.production_backend && form.csv_text && rightsReady);
  const trajectoryMode = form.delivery_product === "simulation_trajectory_batch";
  return (
    <aside className="studio-gates">
      <div><h2>采购门槛检查</h2><p>四道 Gate 缺一不可；当前任务先验证输入契约与可审计输出。</p></div>
      <article className="studio-gate passed"><span><Check /></span><div><h3>Gate 0 · 重新定义商品</h3><b>已通过</b><p>{trajectoryMode ? "本任务交付完整模拟轨迹，但不冒充买方采购证据。" : "本任务明确输出分配计划与场景规格，不冒充轨迹数据。"}</p><small>声明边界与输入哈希将写入审计清单。</small></div></article>
      <article className={`studio-gate ${gate1Ready ? "progress" : "waiting"}`}><span>1</span><div><h3>Gate 1 · 产出可训练轨迹（必需）</h3><b>{gate1Ready ? (trajectoryMode ? "模拟后端可执行" : "待确认") : "待补充"}</b><p>机器人、频率、传感器、训练格式与生产后端已写入契约。</p><strong>{form.training_format || "RLDS + LeRobot v3"}</strong><small>{trajectoryMode ? `从 SHA-256 锁定的 Sawyer/MetaWorld 源中按需抽取 ${form.trajectory_count} 条完整 episode；买方指定后端验收仍待完成。` : "当前仅验证生产契约；轨迹须由配置的后端执行。"}</small></div></article>
      <article className="studio-gate waiting"><span>2</span><div><h3>Gate 2 · 完成闭环对照</h3><b>待验证</b><p>同一策略、同一预算，与简单强基线独立对照：</p><ul><li>Tail SR ≥ +5 pp 且 95% CI &gt; 0</li><li>overall 不低于 -1 pp</li><li>head 不低于 -2 pp</li></ul></div></article>
      <article className="studio-gate waiting"><span>3</span><div><h3>Gate 3 · 真机和商业验证</h3><b>待验证</b><p>3–5 个客户尾部任务，跨天/场景真机复核：</p><ul><li>每条件仿真 ≥ 100 episodes</li><li>真机每任务 30–50 次</li><li>单位有效增益成本下降 ≥ 20%</li></ul></div></article>
      {result?.status === "completed" && <div className="studio-success"><CheckCircle weight="fill" /><div><strong>任务已完成</strong><span>{result.job_id}</span></div><a href={result.download_url}><DownloadSimple /> 下载交付包</a></div>}
      {result && ["queued", "running"].includes(result.status) && <div className="studio-success pending"><SpinnerGap className="spin" /><div><strong>{result.status === "queued" ? "任务已进入持久化队列" : "独立 Worker 正在生成"}</strong><span>{result.job_id} · 尝试 {result.attempt_count}/{result.max_attempts}</span></div><Link to="/app/runs">查看运行记录</Link></div>}
      {result?.status === "failed" && <div className="studio-success failed"><WarningCircle /><div><strong>任务生成失败</strong><span>{result.error_message || "已达到最大重试次数"}</span></div><Link to="/app/runs">查看审计记录</Link></div>}
    </aside>
  );
}

export function StudioPage() {
  const { user } = useAuth();
  const [form, setForm] = useState(initialStudioForm);
  const [fileName, setFileName] = useState("customer_tasks.csv");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [checkMessage, setCheckMessage] = useState("");
  const [catalogs, setCatalogs] = useState([]);
  const [catalogError, setCatalogError] = useState("");

  useEffect(() => {
    if (!user?.is_pro) return undefined;
    let active = true;
    apiFetch("/api/catalogs")
      .then((data) => { if (active) setCatalogs(data.catalogs || []); })
      .catch((err) => { if (active) setCatalogError(err.message); });
    return () => { active = false; };
  }, [user?.is_pro]);

  useEffect(() => {
    if (!result?.job_id || !["queued", "running"].includes(result.status)) return undefined;
    let cancelled = false;
    const poll = async () => {
      try {
        const current = await apiFetch(`/api/generations/${result.job_id}`);
        if (!cancelled) setResult(current);
      } catch (err) {
        if (!cancelled) setError(err.message);
      }
    };
    const timer = window.setInterval(poll, 2000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [result?.job_id, result?.status]);

  function setField(key, value) { setForm((current) => ({ ...current, [key]: value })); }
  function setRightsField(key, value) { setForm((current) => ({ ...current, data_rights: { ...current.data_rights, [key]: value } })); }
  function setDeliveryProduct(value) {
    if (value === "simulation_trajectory_batch") {
      setFileName("metaworld_tasks.csv");
      setForm((current) => ({
        ...current,
        delivery_product: value,
        trajectory_count: 16,
        robot_model: "Sawyer / MetaWorld",
        control_frequency_hz: 20,
        sensors: "256x256 RGB + 39D 状态",
        training_format: "RLDS",
        production_backend: "MuJoCo / MetaWorld",
        filename: "metaworld_tasks.csv",
        csv_text: "task,count,success_rate,difficulty,group\nreach-v3,50,0.82,0.22,head\nbutton-press-v3,7,0.57,0.71,tail\npick-place-v3,7,0.43,0.84,tail\n",
      }));
    } else {
      setFileName("customer_tasks.csv");
      setForm((current) => ({ ...initialStudioForm, data_rights: current.data_rights }));
    }
    setCheckMessage("");
  }
  async function loadFile(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    setField("filename", file.name);
    setField("csv_text", await file.text());
  }
  async function submit(event) {
    event.preventDefault();
    setSubmitting(true); setError(""); setResult(null);
    try {
      const data = await apiFetch("/api/generations", { method: "POST", body: JSON.stringify(form) });
      setResult(data);
      setCheckMessage("输入契约已锁定，任务已进入 MySQL 持久化队列；离开页面不会中断生成。");
    } catch (err) { setError(err.message); }
    finally { setSubmitting(false); }
  }
  function validateDraft() {
    const headers = form.csv_text.split(/\r?\n/, 1)[0].split(",").map((item) => item.trim());
    const required = form.delivery_product === "simulation_trajectory_batch" ? ["task", "count"] : ["task", "count", "success_rate", "difficulty"];
    const missing = required.filter((item) => !headers.includes(item));
    setCheckMessage(missing.length ? `还缺少 CSV 字段：${missing.join(", ")}` : "格式检查通过：机器人约束、训练格式与 CSV 表头均已就绪。");
  }

  const trajectoryMode = form.delivery_product === "simulation_trajectory_batch";

  return (
    <div className="workspace-page studio-page">
      <PageHeader title="创建采购级数据任务" description="配置机器人、任务与生产规范；所有任务必须通过采购门槛检查后才可生成。" />
      <section className="workspace-panel synthetic-catalog-panel">
        <div>
          <span className="eyebrow">PRO SYNTHETIC CATALOG</span>
          <h2>已验证模拟轨迹样包</h2>
          <p>MetaWorld/Sawyer · 64 条轨迹 · 3,285 帧 · LeRobotDataset v3 + RLDS-compatible TFRecord</p>
          <small>完整性由固定 SHA-256 校验；这是 Q-Tail 自主模拟技术样包，不是买方指定后端、真机或采购验收证据。</small>
        </div>
        {!user?.is_pro
          ? <Link className="button button-secondary" to="/app/billing"><Lock /> Pro 解锁</Link>
          : catalogError
            ? <span className="catalog-unavailable"><WarningCircle /> {catalogError}</span>
            : catalogs[0]?.available
              ? <a className="button button-primary" href={catalogs[0].download_url}><DownloadSimple /> 下载 53.8 MiB</a>
              : <span className="catalog-unavailable"><SpinnerGap className={!catalogs.length ? "spin" : ""} /> {!catalogs.length ? "正在校验目录" : "样包完整性检查未通过"}</span>}
      </section>
      <div className="studio-layout">
        <form className="studio-form" onSubmit={submit}>
          <label>交付产品 *<select value={form.delivery_product} onChange={(e) => setDeliveryProduct(e.target.value)}><option value="allocation_plan">长尾分配计划与场景规格</option><option value="simulation_trajectory_batch">按需 Sawyer/MetaWorld 模拟轨迹批次</option></select><small className="form-help">按需轨迹会生成真实 TFRecord episode；证据范围仍严格限定为 Q-Tail 模拟。</small></label>
          <div className="form-section-title"><span>1</span><div><h2>任务与机器人配置</h2></div></div>
          <div className="form-grid">
            <label>机器人构型 *<select value={form.robot_model} onChange={(e) => setField("robot_model", e.target.value)} disabled={trajectoryMode}><option>Sawyer / MetaWorld</option><option>Franka Panda</option><option>UR5e</option><option>Unitree Z1</option><option>自定义构型</option></select><small className="form-help">{trajectoryMode ? "按需轨迹源锁定为 Sawyer 的 MetaWorld 抽象。" : "选择用于任务与真机执行的机器人构型。"}</small></label>
            <label>控制频率 *<select value={form.control_frequency_hz} onChange={(e) => setField("control_frequency_hz", Number(e.target.value))} disabled={trajectoryMode}><option value="10">10 Hz</option><option value="20">20 Hz</option><option value="50">50 Hz</option></select><small className="form-help">{trajectoryMode ? "源轨迹控制与记录频率锁定为 20 Hz。" : "控制与数据记录频率，采购建议为 10–50 Hz。"}</small></label>
            <label>传感器配置 *<select value={form.sensors} onChange={(e) => setField("sensors", e.target.value)} disabled={trajectoryMode}><option>256x256 RGB + 39D 状态</option><option>RGB-D + 关节状态</option><option>双目 RGB + 关节状态</option><option>RGB + 力/力矩 + 关节状态</option></select><small className="form-help">用于生成数据的观测模态与状态信息。</small></label>
            <label>训练格式 *<select value={form.training_format} onChange={(e) => setField("training_format", e.target.value)} disabled={trajectoryMode}><option>LeRobot v3</option><option>RLDS</option><option>RLDS + LeRobot v3</option></select><small className="form-help">{trajectoryMode ? "按需子集交付 RLDS-compatible TFRecord。" : "输出数据与任务规范遵循所选训练栈。"}</small></label>
            <label>生产后端 *<select value={form.production_backend} onChange={(e) => setField("production_backend", e.target.value)} disabled={trajectoryMode}><option>MuJoCo / MetaWorld</option><option>MuJoCo</option><option>Isaac Sim / Omniverse</option><option>Genesis</option><option>真实遥操作</option></select><small className="form-help">仿真、renderer 或遥操作执行后端。</small></label>
            {trajectoryMode && <label>轨迹条数 *<input type="number" min="1" max="64" value={form.trajectory_count} onChange={(e) => setField("trajectory_count", Number(e.target.value))} /><small className="form-help">1–64 条，且不少于所选任务数。</small></label>}
          </div>
          <label className="upload-field">任务摘要文件 *<span><UploadSimple size={24} /><strong>{fileName}</strong><small>CSV · task,count,success_rate,difficulty,group</small><input type="file" accept=".csv,text/csv" onChange={loadFile} /></span></label>
          <section className="data-rights-panel">
            <div className="form-section-title"><span>2</span><div><h2>数据来源与处理授权</h2><p>声明会按版本哈希并绑定到本次生成任务。</p></div></div>
            <div className="form-grid two-columns">
              <label>来源类型 *<select value={form.data_rights.source_type} onChange={(e) => setRightsField("source_type", e.target.value)}><option value="customer_owned">客户自有</option><option value="licensed">已获许可</option><option value="public_open">公开开放数据</option><option value="synthetic">合成来源</option></select></label>
              <label>保存期限 *<input type="number" min="7" max="3650" value={form.data_rights.retention_days} onChange={(e) => setRightsField("retention_days", Number(e.target.value))} /><small className="form-help">7–3650 天；交付/SOW 可进一步缩短。</small></label>
            </div>
            <label>权利或许可依据 *<input value={form.data_rights.license_basis} onChange={(e) => setRightsField("license_basis", e.target.value)} placeholder="例如：客户自有任务统计；内部授权编号…" /></label>
            <div className="rights-checks">
              <label><input type="checkbox" checked={form.data_rights.source_rights_confirmed} onChange={(e) => setRightsField("source_rights_confirmed", e.target.checked)} /><span>我确认有权上传并委托处理该任务数据。</span></label>
              <label><input type="checkbox" checked={form.data_rights.derivative_rights_confirmed} onChange={(e) => setRightsField("derivative_rights_confirmed", e.target.checked)} /><span>我确认允许生成本项目所需的分配计划和衍生规格。</span></label>
              <label><input type="checkbox" checked={form.data_rights.restricted_data_excluded} onChange={(e) => setRightsField("restricted_data_excluded", e.target.checked)} /><span>我确认不包含个人信息、国家秘密、出口管制或其他无权处理的数据。</span></label>
            </div>
          </section>
          <label className="acknowledgement"><input type="checkbox" checked={form.claim_acknowledged} onChange={(e) => setField("claim_acknowledged", e.target.checked)} /><span>{trajectoryMode ? "我理解本任务交付完整的模拟轨迹 episode，但它不是买方指定后端、真机、政策增益或采购验收证据。" : "我理解当前任务生成分配计划与场景规格；可训练轨迹和政策增益需要后续生产与闭环验证。"}</span></label>
          <details className="advanced-options"><summary>3. 高级选项（可选）</summary><div><label>合成预算 *<input type="number" min="100" max="10000000" value={form.synthetic_budget} onChange={(e) => setField("synthetic_budget", Number(e.target.value))} /><small className="form-help">用于分配计划的总预算单位，范围 100–10,000,000。</small></label></div></details>
          {error && <div className="form-error" role="alert"><WarningCircle /> {error}</div>}
          {checkMessage && <div className={`format-check ${checkMessage.startsWith("格式检查通过") ? "passed" : ""}`}>{checkMessage}</div>}
          <div className="studio-submit"><span><Info /> {trajectoryMode ? "生成 Q-Tail 模拟轨迹批次；买方采购 Gate 仍需外部验收。" : "当前生成分配计划与场景规格；可训练轨迹需接入生产后端。"}</span><div className="studio-submit-actions"><button type="button" className="button button-secondary" onClick={validateDraft}>先运行格式检查</button>{!user?.is_pro ? <Link className="button button-primary" to="/app/billing">开通 Pro 后生成 <Lock /></Link> : <button className="button button-primary" disabled={submitting || !form.claim_acknowledged || !form.data_rights.source_rights_confirmed || !form.data_rights.derivative_rights_confirmed || !form.data_rights.restricted_data_excluded}>{submitting ? <><SpinnerGap className="spin" /> 生成中</> : <>{trajectoryMode ? "生成模拟轨迹批次" : "生成采购级任务计划"} <span className="mini-pro">Pro</span></>}</button>}</div></div>
        </form>
        <StudioGateRail form={form} result={result} />
      </div>
    </div>
  );
}

const evidenceProvenanceDefaults = {
  evidence_scope: "simulation",
  evidence_issuer: "",
  evidence_artifact_sha256: "",
  buyer_signoff_sha256: "",
  evidence_observed_at: "",
};

const evidenceDefaults = {
  1: {
    ...evidenceProvenanceDefaults,
    trajectory_count: "",
    schema_validation_passed: false,
    sample_playback_passed: false,
    dataset_manifest_sha256: "",
    production_log_url: "",
    evidence_notes: "",
  },
  2: {
    ...evidenceProvenanceDefaults,
    same_policy: false,
    same_budget: false,
    baseline_name: "",
    tail_sr_gain_pp: "",
    ci95_lower_pp: "",
    overall_gain_pp: "",
    head_gain_pp: "",
    evaluation_episodes: "",
    evaluation_report_url: "",
    evidence_notes: "",
  },
  3: {
    ...evidenceProvenanceDefaults,
    tail_task_count: "",
    simulation_episodes_per_condition: "",
    real_robot_trials_per_task: "",
    unit_cost_reduction_pct: "",
    safety_review_passed: false,
    buyer_acceptance_owner: "",
    validation_report_url: "",
    evidence_notes: "",
  },
};

function EvidenceProvenanceFields({ form, setField }) {
  const external = form.evidence_scope === "buyer_external";
  return <section className={`evidence-provenance ${external ? "external" : "simulation"}`}>
    <div className="form-grid two-columns">
      <label>证据级别 *<select value={form.evidence_scope} onChange={(e) => setField("evidence_scope", e.target.value)}><option value="simulation">模拟 / 公共基准（不可进入合同）</option><option value="buyer_external">买方外部证据（需运营核验）</option></select></label>
      <div className="provenance-note"><Info /><span>{external ? "必须绑定原件、买方签署件和观测时间；运营复核后才具备合同资格。" : "可用于记录技术进度和解锁后续实验，但不会生成合同就绪状态。"}</span></div>
    </div>
    {external && <>
      <div className="form-grid two-columns">
        <label>证据出具方 *<input value={form.evidence_issuer} onChange={(e) => setField("evidence_issuer", e.target.value)} placeholder="买方 QA / 独立实验室法定名称" /></label>
        <label>证据观测时间 *<input type="datetime-local" value={form.evidence_observed_at} onChange={(e) => setField("evidence_observed_at", e.target.value)} /></label>
        <label>证据原件 SHA-256 *<input className="mono-input" maxLength="64" value={form.evidence_artifact_sha256} onChange={(e) => setField("evidence_artifact_sha256", e.target.value)} placeholder="64 位十六进制" /></label>
        <label>买方签署件 SHA-256 *<input className="mono-input" maxLength="64" value={form.buyer_signoff_sha256} onChange={(e) => setField("buyer_signoff_sha256", e.target.value)} placeholder="64 位十六进制" /></label>
      </div>
    </>}
  </section>;
}

function EvidenceFields({ gateNumber, form, setField }) {
  if (gateNumber === 1) return <>
    <div className="form-grid two-columns">
      <label>轨迹数量 *<input type="number" min="1" value={form.trajectory_count} onChange={(e) => setField("trajectory_count", e.target.value)} /><small className="form-help">生产后端实际导出的轨迹条数。</small></label>
      <label>交付清单 SHA-256 *<input className="mono-input" maxLength="64" value={form.dataset_manifest_sha256} onChange={(e) => setField("dataset_manifest_sha256", e.target.value)} /><small className="form-help">64 位十六进制哈希，用于锁定数据版本。</small></label>
    </div>
    <label>生产后端日志 URL *<input placeholder="https://evidence.example/gate1" value={form.production_log_url} onChange={(e) => setField("production_log_url", e.target.value)} /></label>
    <div className="evidence-checks"><label><input type="checkbox" checked={form.schema_validation_passed} onChange={(e) => setField("schema_validation_passed", e.target.checked)} /> RLDS / LeRobot Schema 验证通过</label><label><input type="checkbox" checked={form.sample_playback_passed} onChange={(e) => setField("sample_playback_passed", e.target.checked)} /> 样本解码与回放通过</label></div>
  </>;
  if (gateNumber === 2) return <>
    <div className="form-grid two-columns">
      <label>强基线名称 *<input placeholder="inverse-frequency" value={form.baseline_name} onChange={(e) => setField("baseline_name", e.target.value)} /></label>
      <label>评测 episodes *<input type="number" min="1" value={form.evaluation_episodes} onChange={(e) => setField("evaluation_episodes", e.target.value)} /></label>
      <label>Tail SR 增益（pp）*<input type="number" step="0.01" value={form.tail_sr_gain_pp} onChange={(e) => setField("tail_sr_gain_pp", e.target.value)} /></label>
      <label>95% CI 下界（pp）*<input type="number" step="0.01" value={form.ci95_lower_pp} onChange={(e) => setField("ci95_lower_pp", e.target.value)} /></label>
      <label>Overall 增益（pp）*<input type="number" step="0.01" value={form.overall_gain_pp} onChange={(e) => setField("overall_gain_pp", e.target.value)} /></label>
      <label>Head 增益（pp）*<input type="number" step="0.01" value={form.head_gain_pp} onChange={(e) => setField("head_gain_pp", e.target.value)} /></label>
    </div>
    <label>闭环对照报告 URL *<input placeholder="https://evidence.example/gate2" value={form.evaluation_report_url} onChange={(e) => setField("evaluation_report_url", e.target.value)} /></label>
    <div className="evidence-checks"><label><input type="checkbox" checked={form.same_policy} onChange={(e) => setField("same_policy", e.target.checked)} /> Q-Tail 与基线使用同一策略</label><label><input type="checkbox" checked={form.same_budget} onChange={(e) => setField("same_budget", e.target.checked)} /> Q-Tail 与基线使用同一预算</label></div>
  </>;
  return <>
    <div className="form-grid two-columns">
      <label>尾部任务数 *<input type="number" min="3" max="5" value={form.tail_task_count} onChange={(e) => setField("tail_task_count", e.target.value)} /></label>
      <label>每条件仿真 episodes *<input type="number" min="100" value={form.simulation_episodes_per_condition} onChange={(e) => setField("simulation_episodes_per_condition", e.target.value)} /></label>
      <label>每任务真机试验次数 *<input type="number" min="30" value={form.real_robot_trials_per_task} onChange={(e) => setField("real_robot_trials_per_task", e.target.value)} /></label>
      <label>单位成本下降（%）*<input type="number" min="20" step="0.1" value={form.unit_cost_reduction_pct} onChange={(e) => setField("unit_cost_reduction_pct", e.target.value)} /></label>
      <label>买方验收负责人 *<input value={form.buyer_acceptance_owner} onChange={(e) => setField("buyer_acceptance_owner", e.target.value)} /></label>
      <label>真机与商业报告 URL *<input placeholder="https://evidence.example/gate3" value={form.validation_report_url} onChange={(e) => setField("validation_report_url", e.target.value)} /></label>
    </div>
    <div className="evidence-checks"><label><input type="checkbox" checked={form.safety_review_passed} onChange={(e) => setField("safety_review_passed", e.target.checked)} /> 安全复核与事故记录已通过买方审查</label></div>
  </>;
}

function ProcurementGateRail({ currentCase }) {
  return <aside className="procurement-rail">
    <div className="procurement-rail-heading"><span className="eyebrow">BUYER ACCEPTANCE</span><h2>四道 Gate</h2><p>自动阈值通过后仍需运营审核；系统不会自行伪造买方验收。</p></div>
    <div className="procurement-gates">{currentCase.gates.map((gate) => {
      const passed = gate.status === "approved";
      const review = gate.status === "received";
      const rejected = gate.status === "rejected";
      return <article key={gate.gate_number} className={`procurement-gate ${passed ? "passed" : review ? "review" : rejected ? "rejected" : gate.status}`}>
        <span>{passed ? <Check /> : gate.gate_number}</span>
        <div><div className="procurement-gate-title"><h3>Gate {gate.gate_number} · {gate.label}</h3><b>{passed ? gate.gate_number === 0 ? "声明边界通过" : gate.evidence?.contract_eligible ? "外部证据通过" : "技术阈值通过" : review ? "审核中" : rejected ? "需重交" : gate.status === "open" ? "可提交" : "未解锁"}</b></div><p>{gate.acceptance}</p>{gate.evidence?.evidence_sha256 && <small>{gate.evidence.evidence_scope_label} · {gate.evidence.evidence_sha256.slice(0, 12)}…</small>}</div>
      </article>;
    })}</div>
    <section className={`contract-status-card ${currentCase.contract_evidence?.ready ? "approved" : "active"}`}><ShieldCheck size={26} /><div><span>买方外部证据</span><strong>{currentCase.contract_evidence?.ready ? "Gate 1–3 已核验" : `仍缺 Gate ${(currentCase.contract_evidence?.missing_gates || []).join("、")}`}</strong><small>模拟与公共基准可以记录技术进度，但不能进入合同。</small></div></section>
    <section className={`contract-status-card ${currentCase.compliance?.ready_for_contract ? "approved" : "active"}`}><ShieldCheck size={26} /><div><span>数据权利与安全边界</span><strong>{currentCase.compliance?.ready_for_contract ? "已批准" : currentCase.compliance?.profile?.status_label || "尚未提交"}</strong>{!currentCase.compliance?.ready_for_contract && <Link className="contract-draft-link" to="/app/compliance">前往合规中心</Link>}{currentCase.compliance?.profile?.profile_sha256 && <small>资料 {currentCase.compliance.profile.profile_sha256.slice(0, 12)}…</small>}</div></section>
    <section className={`contract-status-card ${currentCase.contract?.status || currentCase.status}`}><FileText size={26} /><div><span>采购合同状态</span><strong>{currentCase.contract?.status_label || (currentCase.status === "contract_ready" ? "等待运营生成合同记录" : currentCase.gates.every((gate) => gate.status === "approved") ? "等待合规资料批准" : "Gate 1–3 通过后解锁")}</strong>{currentCase.contract?.contract_reference && <small>存档引用：{currentCase.contract.contract_reference}</small>}{currentCase.contract?.draft_download_url && <a className="contract-draft-link" href={currentCase.contract.draft_download_url}><DownloadSimple /> 下载采购/SOW 协商草案</a>}</div></section>
  </aside>;
}

export function ProcurementPage() {
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [selectedId, setSelectedId] = useState("");
  const [createForm, setCreateForm] = useState({ generation_job_id: "", title: "", buyer_owner: user?.name || "", pilot_scope: "" });
  const [evidenceForm, setEvidenceForm] = useState(evidenceDefaults[1]);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [failedChecks, setFailedChecks] = useState([]);
  const [working, setWorking] = useState(false);

  async function refresh(preferredId = selectedId) {
    const response = await apiFetch("/api/procurement-cases");
    setData(response);
    const nextId = preferredId || response.cases?.[0]?.id || "";
    setSelectedId(nextId);
    if (!createForm.generation_job_id && response.eligible_jobs?.[0]) setCreateForm((current) => ({ ...current, generation_job_id: response.eligible_jobs[0].id }));
  }
  useEffect(() => { refresh().catch((err) => setError(err.message)); }, []);

  const cases = data?.cases || [];
  const currentCase = cases.find((item) => item.id === selectedId) || cases[0] || null;
  const thresholdGate = currentCase?.gates.find((gate) => gate.gate_number > 0 && ["open", "rejected"].includes(gate.status));
  const externalUpgradeGate = !thresholdGate ? currentCase?.gates.find((gate) => gate.gate_number > 0 && gate.status === "approved" && !gate.evidence?.contract_eligible) : null;
  const actionableGate = thresholdGate || externalUpgradeGate;
  const waitingGate = currentCase?.gates.find((gate) => gate.gate_number > 0 && gate.status === "received");

  useEffect(() => {
    if (actionableGate) {
      const retryingExternal = externalUpgradeGate?.gate_number === actionableGate.gate_number || actionableGate.evidence?.evidence_scope === "buyer_external";
      setEvidenceForm({ ...evidenceDefaults[actionableGate.gate_number], evidence_scope: retryingExternal ? "buyer_external" : "simulation" });
    }
    setFailedChecks([]); setSuccess(""); setError("");
  }, [selectedId, actionableGate?.gate_number]);

  async function createCase(event) {
    event.preventDefault(); setWorking(true); setError("");
    try {
      const response = await apiFetch("/api/procurement-cases", { method: "POST", body: JSON.stringify(createForm) });
      setSuccess("采购验证项目已创建，Gate 1 可以开始提交证据。");
      await refresh(response.case.id);
    } catch (err) { setError(err.message); }
    finally { setWorking(false); }
  }
  function setEvidenceField(key, value) { setEvidenceForm((current) => ({ ...current, [key]: value })); }
  async function submitEvidence(event) {
    event.preventDefault();
    if (!currentCase || !actionableGate) return;
    setWorking(true); setError(""); setSuccess(""); setFailedChecks([]);
    try {
      await apiFetch(`/api/procurement-cases/${currentCase.id}/gates/${actionableGate.gate_number}/evidence`, { method: "POST", body: JSON.stringify(evidenceForm) });
      setSuccess(`Gate ${actionableGate.gate_number} 自动阈值通过，证据已进入运营审核。`);
      await refresh(currentCase.id);
    } catch (err) {
      setError(err.message);
      setFailedChecks(err.payload?.error?.evaluation?.failed_checks || []);
    } finally { setWorking(false); }
  }

  return <div className="workspace-page procurement-page">
    <PageHeader eyebrow="PROCUREMENT GATES" title="采购验证与合同" description="把轨迹、闭环、真机和成本证据提交到同一审计链，全部通过后形成合同就绪记录。" action={<div className="workspace-header-actions"><a className="button button-secondary" href="/buyer-kit/qtail-buyer-pilot-kit-v1.2.0.zip" download><DownloadSimple /> 下载买方试点包</a><Link className="button button-secondary" to="/app/studio">新建生成任务 <Plus /></Link></div>} />
    {error && <div className="form-error" role="alert"><WarningCircle /> {error}</div>}
    {success && <div className="form-success"><CheckCircle /> {success}</div>}
    <details className="case-create" open={cases.length === 0}>
      <summary>{cases.length === 0 ? "从已完成任务创建采购验证项目" : "创建另一个采购验证项目"}</summary>
      {!user?.is_pro ? <div className="locked-message"><Lock /><div><strong>需要 Pro</strong><p>采购 Gate 证据链属于 Pro 交付能力。</p><Link to="/app/billing">前往开通</Link></div></div> : data?.eligible_jobs?.length ? <form onSubmit={createCase} className="compact-form procurement-create-form"><div className="form-grid two-columns"><label>已完成生成任务 *<select value={createForm.generation_job_id} onChange={(e) => setCreateForm({ ...createForm, generation_job_id: e.target.value })}>{data.eligible_jobs.map((job) => <option value={job.id} key={job.id}>{job.robot_model} · {job.filename} · {job.id.slice(0, 8)}</option>)}</select></label><label>项目名称 *<input placeholder="Rare Pick Pilot" value={createForm.title} onChange={(e) => setCreateForm({ ...createForm, title: e.target.value })} /></label><label>买方负责人 *<input value={createForm.buyer_owner} onChange={(e) => setCreateForm({ ...createForm, buyer_owner: e.target.value })} /></label><label>试点范围 *<input placeholder="3–5 个尾部任务" value={createForm.pilot_scope} onChange={(e) => setCreateForm({ ...createForm, pilot_scope: e.target.value })} /></label></div><button className="button button-primary" disabled={working}>创建验证项目</button></form> : <div className="empty-state"><ClipboardText /><h2>还没有可关联的已完成任务</h2><p>先在数据工坊生成一个通过 Gate 0/1 输入契约的交付包。</p><Link className="button button-primary" to="/app/studio">前往数据工坊</Link></div>}
    </details>
    {cases.length > 0 && <div className="case-tabs" role="tablist" aria-label="采购验证项目">{cases.map((item) => <button role="tab" aria-selected={item.id === currentCase?.id} className={item.id === currentCase?.id ? "active" : ""} onClick={() => setSelectedId(item.id)} key={item.id}><span>{item.title}</span><small>{item.generation_job?.robot_model} · {item.status_label}</small></button>)}</div>}
    {currentCase && <div className="procurement-layout">
      <section className="workspace-panel evidence-workbench">
        <div className="panel-heading"><div><span className="eyebrow">{currentCase.generation_job?.id.slice(0, 8)}</span><h2>{currentCase.title}</h2><p>{currentCase.pilot_scope}</p></div><span className={`status-badge status-${currentCase.status}`}>{currentCase.status_label}</span></div>
        <dl className="case-meta"><div><dt>机器人 / 格式</dt><dd>{currentCase.generation_job?.robot_model} · {currentCase.generation_job?.training_format}</dd></div><div><dt>买方负责人</dt><dd>{currentCase.buyer_owner}</dd></div><div><dt>来源任务</dt><dd>{currentCase.generation_job?.filename}</dd></div></dl>
        {actionableGate ? <form className="gate-evidence-form" onSubmit={submitEvidence}><div className="evidence-form-heading"><span>GATE {actionableGate.gate_number}</span><h2>{externalUpgradeGate ? "补交买方外部证据" : `${actionableGate.label}证据`}</h2><p>{actionableGate.acceptance}</p></div><EvidenceProvenanceFields form={evidenceForm} setField={setEvidenceField} /><EvidenceFields gateNumber={actionableGate.gate_number} form={evidenceForm} setField={setEvidenceField} /><label>证据说明<textarea placeholder="记录实验版本、异常处理和买方复核范围。" value={evidenceForm.evidence_notes} onChange={(e) => setEvidenceField("evidence_notes", e.target.value)} /></label>{failedChecks.length > 0 && <div className="threshold-failures"><strong>尚未通过的自动检查</strong><ul>{failedChecks.map((item) => <li key={item}>{item}</li>)}</ul></div>}<div className="evidence-submit"><span><ShieldCheck /> 提交后生成证据哈希，并进入人工审核。</span><button className="button button-primary" disabled={working}>{working ? <><SpinnerGap className="spin" /> 提交中</> : <>运行阈值检查并提交</>}</button></div></form> : waitingGate ? <div className="review-waiting"><SpinnerGap className="spin" /><h2>Gate {waitingGate.gate_number} 证据审核中</h2><p>自动阈值已经通过；运营人员核对外部报告后才能解锁下一道 Gate。</p></div> : <div className="review-waiting complete"><CheckCircle weight="fill" /><h2>{currentCase.contract?.status === "signed" ? "采购合同已签署归档" : "技术与买方外部证据已全部通过"}</h2><p>{currentCase.contract ? `合同版本 v${currentCase.contract.version} · ${currentCase.contract.status_label}` : "等待运营生成合同就绪记录；外部签署完成后再写入执行件哈希。"}</p></div>}
      </section>
      <ProcurementGateRail currentCase={currentCase} />
    </div>}
  </div>;
}

export function ApiPage() {
  const { user } = useAuth();
  const [application, setApplication] = useState(null);
  const [keys, setKeys] = useState([]);
  const [createdKey, setCreatedKey] = useState("");
  const [error, setError] = useState("");
  const [form, setForm] = useState({ role: "机器人数据负责人", use_case: "工业机械臂长尾任务预算编排", data_format: "CSV / LeRobot v3", monthly_volume: "10 万任务预算单位", pilot_goal: "围绕 3–5 个尾部任务完成设计伙伴 PoC。" });

  async function refresh() {
    const data = await apiFetch("/api/api-access"); setApplication(data.application); setKeys(data.keys || []);
  }
  useEffect(() => { refresh().catch((err) => setError(err.message)); }, []);
  async function apply(event) {
    event.preventDefault(); setError("");
    try { await apiFetch("/api/api-access", { method: "POST", body: JSON.stringify(form) }); await refresh(); }
    catch (err) { setError(err.message); }
  }
  async function createKey() {
    setError(""); setCreatedKey("");
    try { const data = await apiFetch("/api/api-keys", { method: "POST", body: JSON.stringify({ label: "Default production key" }) }); setCreatedKey(data.api_key); await refresh(); }
    catch (err) { setError(err.message); }
  }
  async function copyKey() { await navigator.clipboard.writeText(createdKey); }

  return (
    <div className="workspace-page">
      <PageHeader eyebrow="API ACCESS" title="API 申请与密钥" description="先提交真实采购场景，经审核并开通 Pro 后创建生产密钥。" />
      {error && <div className="form-error"><WarningCircle /> {error}</div>}
      <div className="api-layout">
        <section className="workspace-panel">
          <div className="panel-heading"><div><h2>API 访问申请</h2><p>审核状态决定能否创建密钥。</p></div>{application && <span className={`status-badge status-${application.status}`}>{application.status_label}</span>}</div>
          {application ? <div className="application-summary"><strong>{application.use_case}</strong><p>{application.pilot_goal}</p><dl><div><dt>数据格式</dt><dd>{application.data_format}</dd></div><div><dt>月度规模</dt><dd>{application.monthly_volume}</dd></div><div><dt>提交时间</dt><dd>{formatDate(application.created_at)}</dd></div></dl></div> : <form onSubmit={apply} className="compact-form"><div className="form-grid two-columns"><label>岗位<input value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} /></label><label>月度规模<input value={form.monthly_volume} onChange={(e) => setForm({ ...form, monthly_volume: e.target.value })} /></label><label>使用场景<input value={form.use_case} onChange={(e) => setForm({ ...form, use_case: e.target.value })} /></label><label>目标格式<input value={form.data_format} onChange={(e) => setForm({ ...form, data_format: e.target.value })} /></label></div><label>PoC 目标<textarea value={form.pilot_goal} onChange={(e) => setForm({ ...form, pilot_goal: e.target.value })} /></label><button className="button button-primary">提交申请</button></form>}
        </section>
        <section className="workspace-panel">
          <div className="panel-heading"><div><h2>API 密钥</h2><p>密钥只在创建时显示一次。</p></div><button className="button button-secondary" onClick={createKey} disabled={!user?.is_pro || application?.status !== "approved"}><Plus /> 创建密钥</button></div>
          {!user?.is_pro && <div className="locked-message"><Lock /><div><strong>需要 Pro</strong><p>完成 Pro 开通后才能创建 API 密钥。</p><Link to="/app/billing">前往开通</Link></div></div>}
          {createdKey && <div className="created-key"><span>请立即复制并安全保存</span><code>{createdKey}</code><button onClick={copyKey}><Copy /> 复制</button></div>}
          <div className="key-list">{keys.length === 0 ? <div className="empty-state"><Key /><p>暂无活跃密钥</p></div> : keys.map((item) => <article key={item.id}><div><Key /><span><strong>{item.label}</strong><small>{item.prefix}••••••••</small></span></div><span>创建于 {formatDate(item.created_at)}</span></article>)}</div>
        </section>
      </div>
    </div>
  );
}

export function BillingPage() {
  const { user, refresh: refreshUser } = useAuth();
  const [plan, setPlan] = useState(null);
  const [orders, setOrders] = useState([]);
  const [invoiceRequests, setInvoiceRequests] = useState([]);
  const [refundRequests, setRefundRequests] = useState([]);
  const [paymentMode, setPaymentMode] = useState("manual_qr_verification");
  const [checkoutQr, setCheckoutQr] = useState("");
  const [order, setOrder] = useState(null);
  const [reference, setReference] = useState("");
  const [invoiceForm, setInvoiceForm] = useState({ order_id: "", invoice_title: user?.company || "", taxpayer_id: "", invoice_email: user?.email || "" });
  const [refundForm, setRefundForm] = useState({ order_id: "", reason: "" });
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);
  async function refresh() {
    const data = await apiFetch("/api/billing");
    const nextOrders = data.orders || [];
    setPlan(data.plan); setOrders(nextOrders); setInvoiceRequests(data.invoice_requests || []); setRefundRequests(data.refund_requests || []); setPaymentMode(data.payment_mode || "manual_qr_verification");
    if (nextOrders[0]) setOrder(nextOrders[0]);
    const firstPaid = nextOrders.find((item) => item.status === "paid");
    if (firstPaid) {
      setInvoiceForm((current) => ({ ...current, order_id: current.order_id || firstPaid.id }));
      setRefundForm((current) => ({ ...current, order_id: current.order_id || firstPaid.id }));
    }
  }
  useEffect(() => { refresh().catch((err) => setError(err.message)); }, []);
  useEffect(() => {
    let active = true;
    if (order?.payment_mode !== "official_merchant" || !order.checkout_url) { setCheckoutQr(""); return () => { active = false; }; }
    QRCode.toDataURL(order.checkout_url, { width: 360, margin: 2, errorCorrectionLevel: "M" })
      .then((value) => { if (active) setCheckoutQr(value); })
      .catch(() => { if (active) setError("官方收银台二维码生成失败，请刷新后重试。") });
    return () => { active = false; };
  }, [order?.id, order?.checkout_url, order?.payment_mode]);
  useEffect(() => {
    if (order?.payment_mode !== "official_merchant" || order.status !== "pending") return undefined;
    const timer = window.setInterval(() => { refresh().then(refreshUser).catch(() => {}); }, 3000);
    return () => window.clearInterval(timer);
  }, [order?.id, order?.status, order?.payment_mode]);
  async function createOrder(channel) { setLoading(true); setError(""); try { const data = await apiFetch("/api/payment-orders", { method: "POST", body: JSON.stringify({ channel, plan: "pro_monthly" }) }); setOrder(data.order); await refresh(); } catch (err) { setError(err.message); } finally { setLoading(false); } }
  async function submitReference() { setError(""); try { await apiFetch(`/api/payment-orders/${order.id}/submit`, { method: "POST", body: JSON.stringify({ payment_reference: reference }) }); await refresh(); await refreshUser(); } catch (err) { setError(err.message); } }
  async function submitInvoice(event) {
    event.preventDefault(); setLoading(true); setError(""); setSuccess("");
    try { await apiFetch(`/api/payment-orders/${invoiceOrderId}/invoice-requests`, { method: "POST", body: JSON.stringify({ ...invoiceForm, order_id: invoiceOrderId }) }); setSuccess("发票申请已进入运营审核；税务系统实际开具后才会显示发票号码。"); await refresh(); }
    catch (err) { setError(err.message); } finally { setLoading(false); }
  }
  async function submitRefund(event) {
    event.preventDefault(); setLoading(true); setError(""); setSuccess("");
    try { await apiFetch(`/api/payment-orders/${refundOrderId}/refund-requests`, { method: "POST", body: JSON.stringify({ reason: refundForm.reason }) }); setSuccess("退款申请已提交；人工审核不会自动视为退款到账。"); await refresh(); }
    catch (err) { setError(err.message); } finally { setLoading(false); }
  }
  const paidOrders = orders.filter((item) => item.status === "paid");
  const invoiceEligible = paidOrders.filter((item) => !invoiceRequests.some((request) => request.order_id === item.id && ["requested", "issued"].includes(request.status)));
  const refundEligible = paidOrders.filter((item) => !refundRequests.some((request) => request.order_id === item.id));
  const invoiceOrderId = invoiceEligible.some((item) => item.id === invoiceForm.order_id) ? invoiceForm.order_id : (invoiceEligible[0]?.id || "");
  const refundOrderId = refundEligible.some((item) => item.id === refundForm.order_id) ? refundForm.order_id : (refundEligible[0]?.id || "");
  const officialPayment = order?.payment_mode === "official_merchant";
  const qrSrc = officialPayment ? checkoutQr : (order?.channel === "wechat" ? "/pay/wechat.jpg" : "/pay/alipay.jpg");
  return (
    <div className="workspace-page">
      <PageHeader eyebrow="BILLING & ENTITLEMENT" title="Pro 会员与账单" description={paymentMode === "official_merchant" ? "官方商户收银台验签到账后自动开通 Pro。" : "二维码付款后提交订单备注，由管理员核验到账并开通 Pro。"} />
      {error && <div className="form-error"><WarningCircle /> {error}</div>}
      {success && <div className="form-success"><CheckCircle /> {success}</div>}
      <div className="billing-layout">
        <section className="plan-card"><div className="plan-top"><span>Q-TAIL PRO</span><strong>{plan ? formatMoney(plan.price_cents) : "—"}<small>/月</small></strong></div><ul><li><CheckCircle weight="fill" /> 数据工坊与 Q-Tail 生成任务</li><li><CheckCircle weight="fill" /> API 申请审核后创建密钥</li><li><CheckCircle weight="fill" /> 运行记录与审计交付包</li><li><CheckCircle weight="fill" /> 采购 Gate 配置检查</li></ul>{user?.is_pro ? <div className="current-plan"><CheckCircle weight="fill" /><div><strong>Pro 已开通</strong><span>有效期至 {formatDate(user.pro_expires_at)}</span></div></div> : <div className="payment-buttons"><button disabled={loading} onClick={() => createOrder("wechat")} className="button wechat-button">微信支付</button><button disabled={loading} onClick={() => createOrder("alipay")} className="button alipay-button">支付宝</button></div>}<p className="payment-disclaimer"><Info /> {paymentMode === "official_merchant" ? "仅在签名、商户身份、订单号和金额全部一致后自动开通；重复回调不会重复增加权益。" : "当前收款码不提供服务器回调，订单需人工核验；不会因提交备注而自动开通。"}</p></section>
        <section className="payment-panel">{order ? <><div className="panel-heading"><div><h2>订单 {order.id.slice(0, 8).toUpperCase()}</h2><p>{order.channel_label} · {formatMoney(order.amount_cents)}</p></div><span className={`status-badge status-${order.status}`}>{order.status_label}</span></div>{qrSrc ? <img className="payment-qr" src={qrSrc} alt={`${order.channel_label}收款码`} /> : <div className="empty-payment"><SpinnerGap className="spin" /><p>正在生成安全收银台二维码…</p></div>}{officialPayment ? <div className="official-payment-state"><p><ShieldCheck /> 商户订单 {order.merchant_order_no}</p><small>{order.status === "paid" ? `渠道流水 ${order.provider_transaction_id || "已验签"}` : "扫码支付后页面会自动刷新；请勿重复付款。"}</small><button className="button button-secondary button-full" onClick={() => refresh().then(refreshUser)}>刷新支付状态</button></div> : <><label>付款备注或交易单号<input placeholder="请填写可用于人工核验的信息" value={reference} onChange={(e) => setReference(e.target.value)} /></label><button className="button button-primary button-full" onClick={submitReference} disabled={!reference.trim() || order.status === "under_review"}>{order.status === "under_review" ? "已提交，等待核验" : "我已付款，提交核验"}</button></>}</> : <div className="empty-payment"><Receipt /><h2>选择支付方式创建订单</h2><p>创建后将显示对应收款码和唯一订单号。</p></div>}</section>
      </div>
      <section className="workspace-panel order-history"><div className="panel-heading"><div><h2>订单记录</h2><p>所有订单状态均由服务端记录。</p></div></div>{orders.length === 0 ? <div className="empty-state">暂无订单</div> : <div className="table-wrap"><table><thead><tr><th>订单</th><th>方式</th><th>金额</th><th>状态</th><th>创建时间</th></tr></thead><tbody>{orders.map((item) => <tr key={item.id}><td>{item.id.slice(0, 8).toUpperCase()}</td><td>{item.channel_label}</td><td>{formatMoney(item.amount_cents)}</td><td>{item.status_label}</td><td>{formatDate(item.created_at)}</td></tr>)}</tbody></table></div>}</section>
      <section className="billing-aftercare">
        <article className="workspace-panel aftercare-panel">
          <div className="panel-heading"><div><h2>数电发票申请</h2><p>只接受已核验到账且未退款的订单。</p></div><Receipt /></div>
          {invoiceEligible.length ? <form className="compact-form" onSubmit={submitInvoice}><label>订单<select value={invoiceOrderId} onChange={(e) => setInvoiceForm({ ...invoiceForm, order_id: e.target.value })}>{invoiceEligible.map((item) => <option key={item.id} value={item.id}>{item.id.slice(0, 8).toUpperCase()} · {formatMoney(item.amount_cents)}</option>)}</select></label><label>发票抬头<input value={invoiceForm.invoice_title} onChange={(e) => setInvoiceForm({ ...invoiceForm, invoice_title: e.target.value })} /></label><label>纳税人识别号<input maxLength="20" value={invoiceForm.taxpayer_id} onChange={(e) => setInvoiceForm({ ...invoiceForm, taxpayer_id: e.target.value.toUpperCase() })} /></label><label>收票邮箱<input type="email" value={invoiceForm.invoice_email} onChange={(e) => setInvoiceForm({ ...invoiceForm, invoice_email: e.target.value })} /></label><button className="button button-secondary" disabled={loading}>提交开票申请</button></form> : <div className="aftercare-empty">暂无可开票订单，或现有申请仍在处理。</div>}
          <div className="aftercare-list">{invoiceRequests.map((item) => <div key={item.id}><span>{item.invoice_title}</span><b className={`status-${item.status}`}>{item.status_label}</b><small>订单 {item.order_id.slice(0, 8).toUpperCase()}{item.invoice_number ? ` · 发票 ${item.invoice_number}` : ""}</small>{item.invoice_document_url && <a href={item.invoice_document_url} target="_blank" rel="noreferrer">查看外部发票文件</a>}{item.cancellation_reference && <small>红冲/作废引用：{item.cancellation_reference}</small>}</div>)}</div>
        </article>
        <article className="workspace-panel aftercare-panel">
          <div className="panel-heading"><div><h2>原路退款申请</h2><p>退款完成以实际渠道流水和参考号为准。</p></div><Receipt /></div>
          {refundEligible.length ? <form className="compact-form" onSubmit={submitRefund}><label>订单<select value={refundOrderId} onChange={(e) => setRefundForm({ ...refundForm, order_id: e.target.value })}>{refundEligible.map((item) => <option key={item.id} value={item.id}>{item.id.slice(0, 8).toUpperCase()} · {formatMoney(item.amount_cents)}</option>)}</select></label><label>退款原因<textarea minLength="8" value={refundForm.reason} onChange={(e) => setRefundForm({ ...refundForm, reason: e.target.value })} /></label><button className="button button-secondary" disabled={loading || refundForm.reason.trim().length < 8}>提交退款申请</button><p className="payment-disclaimer"><Info /> 审批不会自动撤销权益；真实原路退款完成后才更新订单与 Pro。</p></form> : <div className="aftercare-empty">暂无可退款订单，或该订单已有退款记录。</div>}
          <div className="aftercare-list">{refundRequests.map((item) => <div key={item.id}><span>{formatMoney(item.amount_cents)} · {item.reason}</span><b className={`status-${item.status}`}>{item.status_label}</b><small>订单 {item.order_id.slice(0, 8).toUpperCase()}{item.refund_reference ? ` · 退款 ${item.refund_reference}` : ""}</small></div>)}</div>
        </article>
      </section>
    </div>
  );
}

export function RunsPage() {
  const [runs, setRuns] = useState([]);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [deletionJob, setDeletionJob] = useState("");
  const [deletionReason, setDeletionReason] = useState("");
  const [working, setWorking] = useState(false);
  async function refreshRuns() {
    try { const data = await apiFetch("/api/generations"); setRuns(data.jobs || []); setError(""); }
    catch (err) { setError(err.message); }
  }
  async function submitDeletion(event) {
    event.preventDefault();
    setWorking(true); setError(""); setSuccess("");
    try {
      const result = await apiFetch(`/api/generations/${deletionJob}/deletion-request`, { method: "POST", body: JSON.stringify({ reason: deletionReason }) });
      setSuccess(`删除申请已登记，最迟处理时间：${formatDate(result.deletion_request.due_at)}`);
      setDeletionJob(""); setDeletionReason("");
      await refreshRuns();
    } catch (err) { setError(err.message); }
    finally { setWorking(false); }
  }
  useEffect(() => {
    refreshRuns();
    const timer = window.setInterval(refreshRuns, 4000);
    return () => window.clearInterval(timer);
  }, []);
  return <div className="workspace-page">
    <PageHeader eyebrow="RUN LEDGER" title="运行记录" description="每次生成任务都记录输入契约、Gate 状态、留存期限与可验证删除回执。" action={<Link className="button button-primary" to="/app/studio">新建任务 <Plus /></Link>} />
    {error && <div className="form-error">{error}</div>}
    {success && <div className="form-success"><CheckCircle /> {success}</div>}
    <section className="workspace-panel run-ledger">{runs.length === 0 ? <div className="empty-state"><ClipboardText /><h2>还没有运行记录</h2><p>从数据工坊创建第一条采购级任务。</p></div> : <div className="table-wrap"><table><thead><tr><th>任务</th><th>交付</th><th>机器人</th><th>格式</th><th>预算</th><th>状态</th><th>留存/删除</th><th></th></tr></thead><tbody>{runs.map((run) => {
      const deletion = run.deletion_request;
      const terminal = run.status === "completed" || run.status === "failed";
      return [
        <tr key={run.id}><td><strong>{run.filename}</strong><small>{run.id.slice(0, 8)} · {formatDate(run.created_at)}</small></td><td>{run.delivery_product_label}<small>{run.trajectory_count ? `${run.trajectory_count} 条` : "规格/计划"}</small></td><td>{run.robot_model}</td><td>{run.training_format}</td><td>{Number(run.synthetic_budget).toLocaleString()}</td><td><span className={`status-badge status-${run.status}`}>{run.status_label}</span></td><td>{run.payload_deleted ? <><span className="status-badge status-completed">载荷已删除</span><small className="deletion-hash">{deletion?.deletion_sha256?.slice(0, 12)}…</small></> : deletion ? <><span className={`status-badge status-${deletion.status}`}>{deletion.status_label}</span><small className="deletion-hash">截止 {formatDate(deletion.due_at)}</small></> : <small>保存 {run.data_rights?.retention_days || "—"} 天</small>}</td><td><div className="run-actions">{run.download_url && <a className="table-action" href={run.download_url}><DownloadSimple /> 下载</a>}{terminal && !deletion && <button className="table-action destructive-link" onClick={() => { setDeletionJob(run.id); setDeletionReason(""); setSuccess(""); }}><Trash /> 申请删除</button>}</div></td></tr>,
        deletionJob === run.id && <tr key={`${run.id}-deletion`} className="deletion-request-row"><td colSpan="8"><form onSubmit={submitDeletion}><div><strong>删除输入与交付载荷</strong><p>文件删除后不可恢复；输入哈希、权利声明、审计、Gate 和合同元数据继续保留。</p></div><input autoFocus minLength="8" placeholder="填写删除原因（至少 8 个字符）" value={deletionReason} onChange={(e) => setDeletionReason(e.target.value)} /><button className="button button-danger" disabled={working || deletionReason.trim().length < 8}>确认申请</button><button type="button" className="button button-secondary" onClick={() => setDeletionJob("")}>取消</button></form></td></tr>,
      ];
    })}</tbody></table></div>}</section>
  </div>;
}

export function DocsPage() {
  const apiCurl = `curl -X POST https://your-domain.example/api/generations \\\n  -H "X-API-Key: qtail_live_..." \\\n  -H "Content-Type: application/json" \\\n  --data '{"robot_model":"Franka Panda","control_frequency_hz":20,"sensors":"RGB-D + joint state","training_format":"LeRobot v3","production_backend":"MuJoCo","synthetic_budget":100000,"data_rights":{"source_type":"customer_owned","license_basis":"customer-owned task statistics","contains_personal_data":false,"retention_days":90,"source_rights_confirmed":true,"derivative_rights_confirmed":true,"restricted_data_excluded":true},"claim_acknowledged":true,"csv_text":"task,count,success_rate,difficulty,group\\nrare_pick,12,0.32,0.91,tail"}'`;
  const catalogCurl = `curl -H "X-API-Key: qtail_live_..." https://your-domain.example/api/catalogs/metaworld-sawyer-v0.1.0/download -o qtail-gate1-metaworld-sawyer-v0.1.0.tar.gz\nsha256sum qtail-gate1-metaworld-sawyer-v0.1.0.tar.gz\n# c58b39d83a1a9f9d72533ed2f33d8280bbf7fee98e28b3c082fca116894d2fb0`;
  const trajectoryCurl = "POST /api/generations\\n{\\n  \"delivery_product\": \"simulation_trajectory_batch\",\\n  \"trajectory_count\": 16,\\n  \"robot_model\": \"Sawyer / MetaWorld\",\\n  \"control_frequency_hz\": 20,\\n  \"sensors\": \"256x256 RGB + 39D state\",\\n  \"training_format\": \"RLDS\",\\n  \"production_backend\": \"MuJoCo / MetaWorld\",\\n  \"csv_text\": \"task,count\\\\nreach-v3,50\\\\nbutton-press-v3,7\\\\npick-place-v3,7\",\\n  \"data_rights\": { \"source_type\": \"customer_owned\", \"license_basis\": \"customer-owned task specification\", \"contains_personal_data\": false, \"retention_days\": 90, \"source_rights_confirmed\": true, \"derivative_rights_confirmed\": true, \"restricted_data_excluded\": true },\\n  \"claim_acknowledged\": true\\n}";
  return <div className="docs-page"><div className="docs-nav"><Link to="/">← 返回官网</Link><strong>Q-Tail API</strong><Link to="/app/api">申请访问</Link></div><main><span className="eyebrow">API V1</span><h1>将采购约束写进每一次生成请求</h1><p>API 面向已审核并开通 Pro 的设计伙伴，支持长尾分配计划和受支持任务的按需模拟轨迹批次。</p><section><h2>认证</h2><p>使用创建时仅显示一次的 <code>X-API-Key</code>。密钥按哈希存储，服务端不会保存明文。</p></section><section><h2>下载已验证模拟样包</h2><pre><code>{catalogCurl}</code></pre><p><code>GET /api/catalogs</code> 返回格式、轨迹数、帧数、证据范围和完整性状态；下载响应同时返回 <code>X-Content-SHA256</code>。样包含 64 条 MetaWorld/Sawyer 模拟轨迹，共 3,285 帧。</p></section><section><h2>创建长尾分配任务</h2><pre><code>{apiCurl}</code></pre></section><section><h2>创建按需模拟轨迹批次</h2><pre><code>{trajectoryCurl}</code></pre><p>当前支持 <code>reach-v3</code>、<code>button-press-v3</code>、<code>pick-place-v3</code>，每次 1–64 条。Worker 先运行 Q-Tail 分配，再从 SHA-256 锁定源中复制完整 TFRecord episode；交付 ZIP 包含逐文件哈希、源清单和选择记录。</p></section><section><h2>异步任务与数据权利</h2><p>成功提交返回 HTTP 202、任务 ID 和 <code>status_url</code>。每个请求必须携带 <code>data_rights</code>；来源/许可依据、保存期限和三项权利确认会生成 SHA-256 并绑定任务。共享入口拒绝含个人信息的数据。轮询状态变为 <code>completed</code> 后下载交付包。</p></section><section><h2>合同前合规资料</h2><p>登录用户通过 <code>GET/PUT /api/compliance</code> 提交企业法定名称、安全联系人、部署/驻留/删除边界，并接受当前服务条款、隐私说明和 DPA 版本。运营审核通过前不会生成合同记录。</p></section><section><h2>声明边界</h2><div className="docs-warning"><Info /> 固定样包和按需批次都是 Q-Tail 自主模拟交付；<code>buyer_gate_passed=false</code>。它们不等同于买方指定生产后端、独立复现、真实机器人、安全/成本负责人验收或双方签署采购合同。</div></section></main></div>;
}

export function OperatorPage() {
  const [token, setToken] = useState(() => sessionStorage.getItem("qtail_operator_token") || "");
  const [draftToken, setDraftToken] = useState(token);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [working, setWorking] = useState("");
  const [evidenceOps, setEvidenceOps] = useState({});
  const [contractOps, setContractOps] = useState({});
  const [invoiceOps, setInvoiceOps] = useState({});
  const [refundOps, setRefundOps] = useState({});

  async function refresh(currentToken = token) {
    const summary = await apiFetch("/api/admin/summary", { headers: { "X-Admin-Token": currentToken } });
    setData(summary);
  }
  useEffect(() => { if (token) refresh(token).catch((err) => setError(err.message)); }, []);

  async function unlock(event) {
    event.preventDefault(); setError("");
    try { await refresh(draftToken); sessionStorage.setItem("qtail_operator_token", draftToken); setToken(draftToken); }
    catch (err) { setError(err.message); }
  }
  async function review(kind, id, decision) {
    const evidenceItem = kind === "evidence" ? (data?.procurement_evidence || []).find((item) => item.id === id) : null;
    const evidenceValues = evidenceOps[id] || {};
    if (evidenceItem?.evidence_scope === "buyer_external" && decision === "approve" && (!evidenceValues.verification_reference?.trim() || !evidenceValues.reviewer_name?.trim())) {
      setError("批准买方外部证据必须填写核验引用和审核人"); return;
    }
    setWorking(id); setError("");
    const endpoint = kind === "application"
      ? `/api/admin/api-access/${id}/${decision}`
      : kind === "payment"
        ? `/api/admin/payment-orders/${id}/${decision}`
        : kind === "compliance"
          ? `/api/admin/compliance-profiles/${id}/${decision}`
          : `/api/admin/procurement-evidence/${id}/${decision}`;
    const body = evidenceItem?.evidence_scope === "buyer_external" && decision === "approve"
      ? { review_note: evidenceValues.review_note || "Buyer-external artifact and signoff hashes verified against the referenced record", verification_reference: evidenceValues.verification_reference, reviewer_name: evidenceValues.reviewer_name }
      : { review_note: "Reviewed in Q-Tail operator console" };
    try {
      await apiFetch(endpoint, { method: "POST", headers: { "X-Admin-Token": token }, body: JSON.stringify(body) });
      await refresh();
    } catch (err) { setError(err.message); }
    finally { setWorking(""); }
  }
  async function issueContract(caseId) {
    setWorking(caseId); setError("");
    try {
      await apiFetch(`/api/admin/procurement-cases/${caseId}/issue-contract`, { method: "POST", headers: { "X-Admin-Token": token }, body: "{}" });
      await refresh();
    } catch (err) { setError(err.message); }
    finally { setWorking(""); }
  }
  async function markSigned(contractId) {
    const values = contractOps[contractId] || {};
    if (!values.contract_reference?.trim() || !values.executed_document_sha256?.trim() || !values.provider_signatory?.trim() || !values.provider_signature_sha256?.trim() || !values.buyer_signatory?.trim() || !values.buyer_signature_sha256?.trim() || !values.effective_date) { setError("请填写外部合同编号、执行件 SHA-256、双方签署人、双方独立签署凭证 SHA-256 和有效日期"); return; }
    if (values.provider_signature_sha256.trim().toLowerCase() === values.buyer_signature_sha256.trim().toLowerCase()) { setError("服务方与采购方签署凭证 SHA-256 必须不同"); return; }
    setWorking(contractId); setError("");
    try {
      await apiFetch(`/api/admin/procurement-contracts/${contractId}/mark-signed`, { method: "POST", headers: { "X-Admin-Token": token }, body: JSON.stringify(values) });
      await refresh();
    } catch (err) { setError(err.message); }
    finally { setWorking(""); }
  }
  async function invoiceAction(requestId, action) {
    const values = invoiceOps[requestId] || {};
    if (action === "issue" && !values.invoice_number?.trim()) { setError("请填写真实发票号码或税务平台引用"); return; }
    if (action === "cancel" && !values.cancellation_reference?.trim()) { setError("请填写真实红冲/作废凭证引用"); return; }
    setWorking(requestId); setError("");
    const body = action === "issue" ? { invoice_number: values.invoice_number, invoice_document_url: values.invoice_document_url, review_note: "Recorded after external tax-system verification" }
      : action === "cancel" ? { cancellation_reference: values.cancellation_reference, review_note: "External red-letter/cancellation verified" }
        : { review_note: "Invoice request rejected; buyer information requires correction" };
    try { await apiFetch(`/api/admin/invoice-requests/${requestId}/${action}`, { method: "POST", headers: { "X-Admin-Token": token }, body: JSON.stringify(body) }); await refresh(); }
    catch (err) { setError(err.message); } finally { setWorking(""); }
  }
  async function refundAction(requestId, action) {
    const values = refundOps[requestId] || {};
    if (action === "complete" && !values.refund_reference?.trim()) { setError("请填写原支付渠道真实退款参考号"); return; }
    setWorking(requestId); setError("");
    const body = action === "complete" ? { refund_reference: values.refund_reference, review_note: "Original-channel refund settlement verified" } : { review_note: `Refund ${action} reviewed in operator console` };
    try { await apiFetch(`/api/admin/refund-requests/${requestId}/${action}`, { method: "POST", headers: { "X-Admin-Token": token }, body: JSON.stringify(body) }); await refresh(); }
    catch (err) { setError(err.message); } finally { setWorking(""); }
  }
  async function deletionAction(requestId, action) {
    setWorking(requestId); setError("");
    const review_note = action === "complete" ? "Deletion scope verified and payload removal executed" : "Deletion request requires clarification before execution";
    try { await apiFetch(`/api/admin/data-deletion-requests/${requestId}/${action}`, { method: "POST", headers: { "X-Admin-Token": token }, body: JSON.stringify({ review_note }) }); await refresh(); }
    catch (err) { setError(err.message); } finally { setWorking(""); }
  }
  function lock() { sessionStorage.removeItem("qtail_operator_token"); setToken(""); setDraftToken(""); setData(null); }

  if (!token || !data) return <div className="operator-page"><header><Link to="/">Q-TAIL</Link><span>运营控制台</span></header><main className="operator-unlock"><ShieldCheck /><span className="eyebrow">RESTRICTED OPERATIONS</span><h1>输入运营令牌</h1><p>这里用于审核 API、核验二维码订单、复核采购 Gate 证据与合同归档。令牌只保存在当前浏览器会话中。</p><form onSubmit={unlock}><label>ADMIN_TOKEN<input type="password" autoComplete="off" value={draftToken} onChange={(e) => setDraftToken(e.target.value)} /></label>{error && <div className="form-error">{error}</div>}<button className="button button-primary button-full">进入控制台</button></form></main></div>;

  const evidenceQueue = data.procurement_evidence || [];
  const contractReady = data.contract_ready_cases || [];
  const readyContracts = data.ready_contracts || [];
  const invoiceQueue = data.invoice_requests || [];
  const refundQueue = data.refund_requests || [];
  const complianceQueue = data.compliance_profiles || [];
  const deletionQueue = data.deletion_requests || [];

  return <div className="operator-page">
    <header><Link to="/">Q-TAIL</Link><span>运营控制台</span><button onClick={lock}>锁定</button></header>
    <main className="operator-main">
      <div className="operator-heading"><div><span className="eyebrow">COMMERCIAL OPERATIONS</span><h1>申请、支付与采购审核</h1><p>Pro、Gate 和合同状态都必须来自服务端审核记录，不由用户自报自动生效。</p></div><button className="button button-secondary" onClick={() => refresh().catch((err) => setError(err.message))}>刷新</button></div>
      {error && <div className="form-error">{error}</div>}
      <section className="operator-metrics operator-metrics-six"><article><span>注册用户</span><strong>{data.metrics.users}</strong></article><article><span>有效 Pro</span><strong>{data.metrics.active_pro}</strong></article><article><span>生成任务</span><strong>{data.metrics.generations}</strong></article><article><span>活跃密钥</span><strong>{data.metrics.active_api_keys}</strong></article><article><span>采购项目</span><strong>{data.metrics.procurement_cases || 0}</strong></article><article><span>合同就绪</span><strong>{data.metrics.contract_ready || 0}</strong></article></section>
      <div className="operator-columns">
        <section className="workspace-panel"><div className="panel-heading"><div><h2>待审 API 申请</h2><p>{data.applications.length} 条需要处理</p></div></div><div className="operator-list">{data.applications.length === 0 ? <div className="empty-state">暂无待审申请</div> : data.applications.map((item) => <article key={item.id}><div><strong>{item.applicant.company}</strong><span>{item.applicant.name} · {item.applicant.email}</span><p>{item.use_case}</p><small>{item.pilot_goal}</small></div><div className="operator-actions"><button disabled={working === item.id} onClick={() => review("application", item.id, "approve")}><CheckCircle /> 批准</button><button disabled={working === item.id} onClick={() => review("application", item.id, "reject")}><XCircle /> 拒绝</button></div></article>)}</div></section>
        <section className="workspace-panel"><div className="panel-heading"><div><h2>待核验订单</h2><p>{data.payments.length} 条需要查账</p></div></div><div className="operator-list">{data.payments.length === 0 ? <div className="empty-state">暂无待核验订单</div> : data.payments.map((item) => <article key={item.id}><div><strong>{item.buyer.company} · {formatMoney(item.amount_cents)}</strong><span>{item.channel_label} · {item.buyer.email}</span><p>交易备注：{item.payment_reference}</p><small>订单 {item.id}</small></div><div className="operator-actions"><button disabled={working === item.id} onClick={() => review("payment", item.id, "confirm")}><CheckCircle /> 确认到账</button><button disabled={working === item.id} onClick={() => review("payment", item.id, "reject")}><XCircle /> 无法核验</button></div></article>)}</div></section>
      </div>
      <div className="operator-aftercare">
        <section className="workspace-panel"><div className="panel-heading"><div><h2>待开票申请</h2><p>{invoiceQueue.length} 条需核对税务系统</p></div></div><div className="operator-list">{invoiceQueue.length === 0 ? <div className="empty-state">暂无待开票申请</div> : invoiceQueue.map((item) => <article key={item.id}><div><strong>{item.invoice_title} · {formatMoney(item.amount_cents)}</strong><span>{item.buyer.company} · {item.invoice_email}</span><p>税号：{item.taxpayer_id}</p><small>订单 {item.order_id}</small><div className="operator-action-fields"><input placeholder="发票号码 / 税务引用" value={invoiceOps[item.id]?.invoice_number || ""} onChange={(e) => setInvoiceOps({ ...invoiceOps, [item.id]: { ...invoiceOps[item.id], invoice_number: e.target.value } })} /><input placeholder="HTTPS 发票文件链接（可选）" value={invoiceOps[item.id]?.invoice_document_url || ""} onChange={(e) => setInvoiceOps({ ...invoiceOps, [item.id]: { ...invoiceOps[item.id], invoice_document_url: e.target.value } })} /></div></div><div className="operator-actions"><button disabled={working === item.id} onClick={() => invoiceAction(item.id, "issue")}><CheckCircle /> 记录已开票</button><button disabled={working === item.id} onClick={() => invoiceAction(item.id, "reject")}><XCircle /> 信息退回</button></div></article>)}</div></section>
        <section className="workspace-panel"><div className="panel-heading"><div><h2>退款与原路结算</h2><p>{refundQueue.length} 条需处理或等待渠道结果</p></div></div><div className="operator-list">{refundQueue.length === 0 ? <div className="empty-state">暂无退款申请</div> : refundQueue.map((item) => <article key={item.id}><div><strong>{item.buyer.company} · {formatMoney(item.amount_cents)}</strong><span>{item.channel_label} · {item.status_label}</span><p>{item.reason}</p><small>{item.payment_mode === "official_merchant" ? `商户退款单：${item.merchant_refund_no}` : `付款参考：${item.payment_reference || "未记录"}`}</small>{item.provider_refund_id && <small>渠道退款号：{item.provider_refund_id}</small>}{item.invoice && <small>发票状态：{item.invoice.status_label}{item.invoice.invoice_number ? ` · ${item.invoice.invoice_number}` : ""}</small>}{["approved", "failed"].includes(item.status) && item.invoice?.status === "issued" && <div className="operator-action-fields"><input placeholder="红冲/作废凭证引用" value={invoiceOps[item.invoice.id]?.cancellation_reference || ""} onChange={(e) => setInvoiceOps({ ...invoiceOps, [item.invoice.id]: { ...invoiceOps[item.invoice.id], cancellation_reference: e.target.value } })} /><button className="inline-operator-button" onClick={() => invoiceAction(item.invoice.id, "cancel")}>记录红冲/作废</button></div>}{item.payment_mode !== "official_merchant" && item.status === "approved" && <div className="operator-action-fields"><input placeholder="原渠道退款参考号" value={refundOps[item.id]?.refund_reference || ""} onChange={(e) => setRefundOps({ ...refundOps, [item.id]: { refund_reference: e.target.value } })} /></div>}</div><div className="operator-actions">{item.status === "requested" ? <><button disabled={working === item.id} onClick={() => refundAction(item.id, "approve")}><CheckCircle /> 批准退款</button><button disabled={working === item.id} onClick={() => refundAction(item.id, "reject")}><XCircle /> 拒绝申请</button></> : item.payment_mode === "official_merchant" ? (["approved", "failed"].includes(item.status) ? <button disabled={working === item.id || item.invoice?.status === "issued"} onClick={() => refundAction(item.id, "initiate")}><CheckCircle /> {item.status === "failed" ? "按原单号重试" : "发起原路退款"}</button> : <button disabled><SpinnerGap className={item.status === "processing" ? "spin" : ""} /> {item.status === "processing" ? "等待渠道回调" : item.status_label}</button>) : <button disabled={working === item.id || item.invoice?.status === "issued"} onClick={() => refundAction(item.id, "complete")}><CheckCircle /> 确认原路退款</button>}</div></article>)}</div></section>
      </div>
      <section className="workspace-panel operator-compliance"><div className="panel-heading"><div><h2>数据权利与安全边界审核</h2><p>{complianceQueue.length} 份资料等待供应商准入复核</p></div></div><div className="operator-list">{complianceQueue.length === 0 ? <div className="empty-state">暂无待审合规资料</div> : complianceQueue.map((item) => <article key={item.user_id}><div><strong>{item.organization_legal_name} · v{item.version}</strong><span>{item.buyer.company} · {item.security_contact_email}</span><p>{item.deployment_boundary} · {item.data_residency} · 保存 {item.retention_days} 天 · 删除 SLA {item.deletion_sla_days} 天</p><small>SHA-256 {item.profile_sha256}</small></div><div className="operator-actions"><button disabled={working === item.user_id} onClick={() => review("compliance", item.user_id, "approve")}><CheckCircle /> 批准边界</button><button disabled={working === item.user_id} onClick={() => review("compliance", item.user_id, "reject")}><XCircle /> 退回修订</button></div></article>)}</div></section>
      <section className="workspace-panel operator-deletions"><div className="panel-heading"><div><h2>载荷删除与留存 SLA</h2><p>{deletionQueue.length} 条申请等待执行；到期后 Worker 自动处理</p></div></div><div className="operator-list">{deletionQueue.length === 0 ? <div className="empty-state">暂无待处理删除申请</div> : deletionQueue.map((item) => <article key={item.id}><div><strong>{item.filename} · {item.request_source}</strong><span>{item.buyer.company} · 截止 {formatDate(item.due_at)}</span><p>{item.reason}</p><small>任务 {item.generation_job_id}</small></div><div className="operator-actions"><button disabled={working === item.id || item.status === "processing"} onClick={() => deletionAction(item.id, "complete")}><Trash /> 执行删除</button><button disabled={working === item.id || item.status === "processing"} onClick={() => deletionAction(item.id, "reject")}><XCircle /> 退回说明</button></div></article>)}</div></section>
      <div className="operator-procurement">
        <section className="workspace-panel"><div className="panel-heading"><div><h2>待审采购 Gate 证据</h2><p>{evidenceQueue.length} 条自动阈值已通过</p></div></div><div className="operator-list evidence-review-list">{evidenceQueue.length === 0 ? <div className="empty-state">暂无待审 Gate 证据</div> : evidenceQueue.map((item) => <article key={item.id}><div><strong>Gate {item.gate_number} · {item.case_title}</strong><span>{item.buyer.company} · {item.buyer.email}</span><p>{item.automated_findings?.acceptance}</p><small>{item.evidence_scope_label} · SHA-256 {item.evidence_sha256}</small>{item.evidence_scope === "buyer_external" && <div className="operator-action-fields"><input placeholder="外部核验引用 / 数据室编号" value={evidenceOps[item.id]?.verification_reference || ""} onChange={(e) => setEvidenceOps({ ...evidenceOps, [item.id]: { ...evidenceOps[item.id], verification_reference: e.target.value } })} /><input placeholder="审核人姓名" value={evidenceOps[item.id]?.reviewer_name || ""} onChange={(e) => setEvidenceOps({ ...evidenceOps, [item.id]: { ...evidenceOps[item.id], reviewer_name: e.target.value } })} /><input placeholder="具体审核说明" value={evidenceOps[item.id]?.review_note || ""} onChange={(e) => setEvidenceOps({ ...evidenceOps, [item.id]: { ...evidenceOps[item.id], review_note: e.target.value } })} /></div>}</div><div className="operator-actions"><button disabled={working === item.id} onClick={() => review("evidence", item.id, "approve")}><CheckCircle /> {item.evidence_scope === "buyer_external" ? "核验并批准" : "批准技术证据"}</button><button disabled={working === item.id} onClick={() => review("evidence", item.id, "reject")}><XCircle /> 退回重交</button></div></article>)}</div></section>
        <section className="workspace-panel"><div className="panel-heading"><div><h2>合同就绪与签署归档</h2><p>{contractReady.length + readyContracts.length} 条需要处理</p></div></div><div className="operator-list contract-review-list">{contractReady.length === 0 && readyContracts.length === 0 ? <div className="empty-state">暂无合同操作</div> : <>{contractReady.map((item) => <article key={item.id}><div><strong>{item.title}</strong><span>{item.buyer.company} · Gate 1–3 买方外部证据已核验</span><p>为已审核证据生成不可变验收快照和合同就绪记录。</p><small>采购项目 {item.id}</small></div><div className="operator-actions"><button disabled={working === item.id} onClick={() => issueContract(item.id)}><FileText /> 生成合同记录</button></div></article>)}{readyContracts.map((item) => { const values = contractOps[item.id] || {}; return <article key={item.id}><div><strong>{item.case_title} · v{item.version}</strong><span>{item.buyer.company} · 等待外部执行件与双方独立签署凭证核验</span><div className="operator-action-fields"><input placeholder="合同编号 / 电子签约存档" value={values.contract_reference || ""} onChange={(e) => setContractOps({ ...contractOps, [item.id]: { ...values, contract_reference: e.target.value } })} /><input className="mono-input" maxLength="64" placeholder="执行合同文件 SHA-256" value={values.executed_document_sha256 || ""} onChange={(e) => setContractOps({ ...contractOps, [item.id]: { ...values, executed_document_sha256: e.target.value } })} /><input placeholder="服务方签署人" value={values.provider_signatory || ""} onChange={(e) => setContractOps({ ...contractOps, [item.id]: { ...values, provider_signatory: e.target.value } })} /><input className="mono-input" maxLength="64" placeholder="服务方签署凭证 SHA-256" value={values.provider_signature_sha256 || ""} onChange={(e) => setContractOps({ ...contractOps, [item.id]: { ...values, provider_signature_sha256: e.target.value } })} /><input placeholder="采购方签署人" value={values.buyer_signatory || ""} onChange={(e) => setContractOps({ ...contractOps, [item.id]: { ...values, buyer_signatory: e.target.value } })} /><input className="mono-input" maxLength="64" placeholder="采购方签署凭证 SHA-256" value={values.buyer_signature_sha256 || ""} onChange={(e) => setContractOps({ ...contractOps, [item.id]: { ...values, buyer_signature_sha256: e.target.value } })} /><label>有效日期<input type="date" value={values.effective_date || ""} onChange={(e) => setContractOps({ ...contractOps, [item.id]: { ...values, effective_date: e.target.value } })} /></label></div><small>合同记录 {item.id}</small></div><div className="operator-actions"><button disabled={working === item.id} onClick={() => markSigned(item.id)}><CheckCircle /> 核验执行件并标记签署</button></div></article>; })}</>}</div></section>
      </div>
    </main>
  </div>;
}
