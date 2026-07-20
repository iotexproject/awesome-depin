import {
  ArrowRight,
  Bell,
  CaretDown,
  ChartLineUp,
  Check,
  CheckCircle,
  ClipboardText,
  CreditCard,
  Database,
  FileText,
  Flask,
  Gauge,
  House,
  Key,
  ListChecks,
  Lock,
  Robot,
  ShieldCheck,
  SignOut,
  UserCircle,
} from "@phosphor-icons/react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "./AuthContext.jsx";

export function Brand({ compact = false, light = false }) {
  return (
    <Link className={`brand ${light ? "brand-light" : ""}`} to="/" aria-label="Q-Tail 首页">
      <span className="brand-mark" aria-hidden="true">Q</span>
      {!compact && <span className="brand-name">Q-TAIL</span>}
    </Link>
  );
}

export function PublicNav({ light = false }) {
  const { user } = useAuth();
  return (
    <header className={`public-nav ${light ? "public-nav-light" : ""}`}>
      <div className="nav-inner">
        <Brand light={light} />
        <nav className="public-links" aria-label="主要导航">
          <Link to="/#product">产品</Link>
          <Link to="/#gates">四道 Gate</Link>
          <Link to="/evidence">证据</Link>
          <Link to="/evidence#pilot-kit">试点包</Link>
          <Link to="/docs">API</Link>
          <Link to="/#pricing">定价</Link>
        </nav>
        <div className="nav-actions">
          {user ? (
            <Link className="nav-login" to="/app">控制台</Link>
          ) : (
            <Link className="nav-login" to="/login">登录</Link>
          )}
          <Link className={`button ${light ? "button-ink" : "button-primary"}`} to={user ? "/app/studio" : "/register"}>
            申请设计伙伴 <ArrowRight weight="bold" />
          </Link>
        </div>
      </div>
    </header>
  );
}

const gateData = [
  {
    key: "gate0",
    title: "Gate 0 · 重新定义商品",
    detail: "统一为“长尾数据智能/分配服务”，修复状态与复现口径。",
    defaultState: "passed",
    status: "已通过",
  },
  {
    key: "gate1",
    title: "Gate 1 · 产出可训练轨迹",
    detail: "Sawyer/MuJoCo 已生产 64 条、3,285 帧合成轨迹；LeRobot v3 与 RLDS 双格式校验通过。",
    defaultState: "passed",
    status: "仿真生产基线通过",
  },
  {
    key: "gate2",
    title: "Gate 2 · 完成闭环对照",
    detail: "MetaWorld 同策略、同预算 900 回合：Tail SR +16.33 pp，95% CI +12.00～+20.67 pp。",
    defaultState: "passed",
    status: "仿真对照通过",
  },
  {
    key: "gate3",
    title: "Gate 3 · 真机和商业验证",
    detail: "本地完成 3 个任务、600 回合安全测试和 24.02% 仿真成本模型；真机与买方签字待外部完成。",
    defaultState: "progress",
    status: "本地部分通过",
  },
];

export function GatePanel({ states = {} }) {
  return (
    <section className="gate-panel" aria-labelledby="gate-title">
      <div className="gate-panel-heading">
        <h2 id="gate-title">采购就绪进度</h2>
        <span>更新于 2026-07-17</span>
      </div>
      <div className="gate-list">
        {gateData.map((gate, index) => {
          const state = states[gate.key] || gate.defaultState;
          return (
            <article className={`gate-item gate-${state}`} key={gate.key}>
              <span className="gate-icon" aria-hidden="true">
                {state === "passed" ? <Check weight="bold" /> : <Lock weight="fill" />}
              </span>
              <div>
                <div className="gate-title-row">
                  <h3>{gate.title}</h3>
                  <span className="status-pill">
                    {states[gate.key] ? (state === "passed" ? "已通过" : state === "progress" ? "进行中" : "未开始") : gate.status}
                  </span>
                </div>
                <p>{gate.detail}</p>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

const sidebarLinks = [
  { to: "/app", label: "概览", icon: House, end: true },
  { to: "/app/studio", label: "数据工坊", icon: Flask },
  { to: "/app/gates", label: "采购 Gate", icon: ShieldCheck },
  { to: "/app/runs", label: "运行记录", icon: ListChecks },
  { to: "/app/api", label: "API 密钥", icon: Key },
  { to: "/app/billing", label: "账单", icon: CreditCard },
  { to: "/app/compliance", label: "合规与权利", icon: FileText },
];

export function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const title = sidebarLinks.find((item) => item.to === location.pathname)?.label || "Q-Tail 控制台";

  async function handleLogout() {
    await logout();
    window.location.assign("/");
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand"><Brand /></div>
        <nav className="sidebar-links" aria-label="工作区导航">
          {sidebarLinks.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} end={end} to={to} aria-label={label} className={({ isActive }) => isActive ? "active" : ""}>
              <Icon size={21} /> <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <Link to="/evidence"><FileText /> 证据中心</Link>
          <span>v1.3 · Buyer pilot kit</span>
        </div>
      </aside>
      <div className="app-main">
        <header className="app-topbar">
          <div>
            <span className="eyebrow">当前工作区</span>
            <strong>{user?.company || "设计伙伴演示"}</strong>
            <CaretDown size={14} />
          </div>
          <div className="topbar-actions">
            <span className={`plan-pill ${user?.is_pro ? "is-pro" : ""}`}>{user?.is_pro ? "PRO" : "FREE"}</span>
            <button className="icon-button" aria-label="通知"><Bell /></button>
            <div className="user-menu">
              <UserCircle weight="fill" />
              <Link to="/app/account">{user?.name || user?.email}</Link>
              <button className="icon-button" onClick={handleLogout} aria-label="退出登录"><SignOut /></button>
            </div>
          </div>
        </header>
        <div className="app-page-heading mobile-only"><span>{title}</span></div>
        <main className="app-content"><Outlet /></main>
      </div>
    </div>
  );
}

export const valueFlow = [
  { icon: ClipboardText, label: "任务汇总", sub: "任务摘要与缺口盘点" },
  { icon: ShieldCheck, label: "风险评分", sub: "场景难度与风险评估" },
  { icon: Database, label: "预算编排", sub: "优先级与成本分配" },
  { icon: FileText, label: "可审计输出", sub: "证据边界与交付物" },
];

export const evidenceFacts = [
  { value: "64", label: "双格式合成轨迹", note: "Sawyer/MuJoCo；3,285 帧，损坏帧 0" },
  { value: "+16.33 pp", label: "闭环 Tail SR", note: "MetaWorld 同策略同预算；非真机" },
  { value: "900", label: "Gate 2 回合", note: "3 个模型种子 × 2 条件 × 3 任务" },
  { value: "600", label: "Gate 3 安全回合", note: "本地仿真；真机与客户验收仍待外部" },
];

export const appBenefits = [
  { icon: Gauge, title: "同预算编排", text: "在客户锁定预算内重新分配稀缺任务的生产优先级。" },
  { icon: ChartLineUp, title: "尾部风险可见", text: "同时报告 head、tail、CVaR 与声明边界。" },
  { icon: Robot, title: "机型约束先行", text: "把构型、传感器、控制频率和训练格式写进任务契约。" },
  { icon: CheckCircle, title: "审计链完整", text: "保留版本、输入、哈希、Gate 检查与可复现交付包。" },
];
