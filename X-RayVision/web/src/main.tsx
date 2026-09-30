import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter, Route, Routes } from "react-router-dom";
import { AppProvider } from "./app/context";
import { Audit, Diagnostics, WatchFolders } from "./pages/Admin";
import { AuthGate } from "./pages/Auth";
import { Imports } from "./pages/Imports";
import { ManualInspection } from "./pages/ManualInspection";
import { Overview } from "./pages/Overview";
import { RecipeEditor } from "./pages/RecipeEditor";
import { Recipes } from "./pages/Recipes";
import { Annotate } from "./pages/Annotate";
import { Report } from "./pages/Report";
import { RunDetail } from "./pages/RunDetail";
import { Runs } from "./pages/Runs";
import { SystemPage } from "./pages/System";
import { Users } from "./pages/Users";
import "./styles/theme.css";

// HashRouter：靜態檔由後端直接提供，深層連結不需伺服器端路由設定
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppProvider>
      <AuthGate>
      <HashRouter>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/runs" element={<Runs />} />
          <Route path="/runs/:id" element={<RunDetail />} />
          <Route path="/runs/:id/report" element={<Report />} />
          <Route path="/runs/:id/annotate" element={<Annotate />} />
          <Route path="/imports" element={<Imports />} />
          <Route path="/recipes" element={<Recipes />} />
          <Route path="/manual" element={<ManualInspection />} />
          <Route path="/recipes/new/:moduleId" element={<RecipeEditor />} />
          <Route path="/recipes/:pk" element={<RecipeEditor />} />
          <Route path="/watch" element={<WatchFolders />} />
          <Route path="/diagnostics" element={<Diagnostics />} />
          <Route path="/audit" element={<Audit />} />
          <Route path="/users" element={<Users />} />
          <Route path="/system" element={<SystemPage />} />
          <Route path="*" element={<Overview />} />
        </Routes>
      </HashRouter>
      </AuthGate>
    </AppProvider>
  </StrictMode>,
);
