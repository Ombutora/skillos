import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { AppShell, RequireRole } from "./components/AppShell";
import "./index.css";
import { Login, Register } from "./pages/Auth";
import { Capture, ExpertDashboard } from "./pages/Expert";
import Landing from "./pages/Landing";
import { CompetencyProfile, LearnerDashboard, ReportPage, SkillDetailPage, SkillLibrary } from "./pages/Learner";
import { AdminPage, OrgDashboard } from "./pages/Org";
import Review from "./pages/Review";
import Workspace from "./pages/Workspace";

const staff = ["expert", "admin"] as const;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/app" element={<AppShell />}>
            <Route index element={<LearnerDashboard />} />
            <Route path="skills" element={<SkillLibrary />} />
            <Route path="skills/:id" element={<SkillDetailPage />} />
            <Route path="skills/:id/review" element={<RequireRole roles={[...staff]}><Review /></RequireRole>} />
            <Route path="sessions/:id" element={<Workspace />} />
            <Route path="reports/:id" element={<ReportPage />} />
            <Route path="competency" element={<CompetencyProfile />} />
            <Route path="expert" element={<RequireRole roles={[...staff]}><ExpertDashboard /></RequireRole>} />
            <Route path="capture" element={<RequireRole roles={[...staff]}><Capture /></RequireRole>} />
            <Route path="org" element={<RequireRole roles={[...staff]}><OrgDashboard /></RequireRole>} />
            <Route path="admin" element={<RequireRole roles={["admin"]}><AdminPage /></RequireRole>} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  </StrictMode>,
);
