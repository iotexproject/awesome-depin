import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./AuthContext.jsx";
import { AppShell } from "./components.jsx";
import { HomePage } from "./pages/HomePage.jsx";
import { EvidencePage } from "./pages/EvidencePage.jsx";
import { LoginPage, RegisterPage } from "./pages/AuthPages.jsx";
import { AccountPage, ApiPage, BillingPage, CompliancePage, DocsPage, OperatorPage, OverviewPage, ProcurementPage, RunsPage, StudioPage } from "./pages/AppPages.jsx";
import { LegalPage } from "./pages/LegalPages.jsx";

function ProtectedRoute() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="full-loading"><span></span><p>正在连接 Q-Tail 工作区…</p></div>;
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />;
  return <AppShell />;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/evidence" element={<EvidencePage />} />
      <Route path="/docs" element={<DocsPage />} />
      <Route path="/operator" element={<OperatorPage />} />
      <Route path="/terms" element={<LegalPage page="terms" />} />
      <Route path="/privacy" element={<LegalPage page="privacy" />} />
      <Route path="/dpa" element={<LegalPage page="dpa" />} />
      <Route path="/payment-policy" element={<LegalPage page="payment" />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/app" element={<ProtectedRoute />}>
        <Route index element={<OverviewPage />} />
        <Route path="studio" element={<StudioPage />} />
        <Route path="gates" element={<ProcurementPage />} />
        <Route path="api" element={<ApiPage />} />
        <Route path="billing" element={<BillingPage />} />
        <Route path="compliance" element={<CompliancePage />} />
        <Route path="runs" element={<RunsPage />} />
        <Route path="account" element={<AccountPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export function App() {
  return <AuthProvider><AppRoutes /></AuthProvider>;
}
