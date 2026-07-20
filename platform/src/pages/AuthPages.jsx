import { Eye, EyeSlash } from "@phosphor-icons/react";
import { useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../AuthContext.jsx";
import { Brand } from "../components.jsx";

function AuthLayout({ mode }) {
  const isLogin = mode === "login";
  const { user, login, register } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [showPassword, setShowPassword] = useState(false);
  const [form, setForm] = useState({ name: "", company: "", email: "", password: "" });
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to="/app" replace />;

  async function submit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      if (isLogin) await login({ email: form.email, password: form.password });
      else await register(form);
      navigate(location.state?.from?.pathname || "/app", { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-brand"><Brand /></div>
      <section className="auth-panel">
        <div className="auth-copy">
          <span className="eyebrow">Q-TAIL WORKSPACE</span>
          <h1>{isLogin ? "欢迎回来" : "创建你的设计伙伴工作区"}</h1>
          <p>{isLogin ? "登录后管理 API、生成任务、采购 Gate 与 Pro 订单。" : "先建立工作区，再提交 API 申请并完成 Pro 开通。"}</p>
        </div>
        <form onSubmit={submit}>
          {!isLogin && (
            <div className="form-grid two-columns">
              <label>姓名<input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} autoComplete="name" /></label>
              <label>公司<input required value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} autoComplete="organization" /></label>
            </div>
          )}
          <label>工作邮箱<input required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} autoComplete="email" /></label>
          <label>密码<span className="password-field"><input required minLength={10} type={showPassword ? "text" : "password"} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} autoComplete={isLogin ? "current-password" : "new-password"} /><button type="button" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? "隐藏密码" : "显示密码"}>{showPassword ? <EyeSlash /> : <Eye />}</button></span></label>
          {error && <div className="form-error" role="alert">{error}</div>}
          <button className="button button-primary button-full" disabled={submitting}>{submitting ? "提交中…" : isLogin ? "登录" : "注册并进入工作区"}</button>
        </form>
        <p className="auth-switch">{isLogin ? "还没有账户？" : "已有账户？"}<Link to={isLogin ? "/register" : "/login"}>{isLogin ? "立即注册" : "直接登录"}</Link></p>
      </section>
      <aside className="auth-aside"><span>四道 Gate，贯穿从 MVP 到采购合同</span><strong>用真实状态建立信任，<br />用可审计结果推进成交。</strong></aside>
    </div>
  );
}

export function LoginPage() { return <AuthLayout mode="login" />; }
export function RegisterPage() { return <AuthLayout mode="register" />; }
