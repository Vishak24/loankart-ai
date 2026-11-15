import { Navigate, Route, Routes } from "react-router";
import CaseLayout from "./case/CaseLayout";
import Diagnosis from "./case/Diagnosis";
import Investigation from "./case/Investigation";
import Options from "./case/Options";
import Proposal from "./case/Proposal";
import Restructure from "./case/Restructure";
import Tracking from "./case/Tracking";
import Advisor from "./pages/Advisor";
import DemoControl from "./pages/DemoControl";
import Landing from "./pages/Landing";
import Onboarding from "./pages/Onboarding";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/borrower/intake" element={<Onboarding key="new" />} />
      <Route path="/borrower/intake/:id" element={<Onboarding key="edit" />} />
      <Route path="/case/:caseId" element={<CaseLayout />}>
        <Route index element={<Navigate to="investigation" replace />} />
        <Route path="investigation" element={<Investigation />} />
        <Route path="diagnosis" element={<Diagnosis />} />
        <Route path="restructure" element={<Restructure />} />
        <Route path="options" element={<Options />} />
        <Route path="proposal" element={<Proposal />} />
        <Route path="tracking" element={<Tracking />} />
      </Route>
      <Route path="/advisor" element={<Advisor />} />
      <Route path="/demo-control" element={<DemoControl />} />
      {/* Milestone 1 addresses keep working. */}
      <Route path="/start/new" element={<Navigate to="/borrower/intake?intent=new" replace />} />
      <Route path="/start/rejected" element={<Navigate to="/borrower/intake?intent=rejected" replace />} />
      <Route path="/demo" element={<Navigate to="/demo-control" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
