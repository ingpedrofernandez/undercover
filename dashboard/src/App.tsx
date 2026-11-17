import { Link, NavLink, Route, Routes } from "react-router";
import { ClaimPage } from "./pages/ClaimPage";
import { EvaluationPage } from "./pages/EvaluationPage";
import { InstructionsPage } from "./pages/InstructionsPage";
import { QueuePage } from "./pages/QueuePage";
import { ScoreboardPage } from "./pages/ScoreboardPage";

export function App() {
  return (
    <>
      <header className="header">
        <Link to="/" className="brand">
          UnderCover <span className="tagline">claims pilot</span>
        </Link>
        <nav className="nav" aria-label="Main">
          <NavLink to="/" end>
            Queue
          </NavLink>
          <NavLink to="/scoreboard">Scoreboard</NavLink>
          <NavLink to="/instructions">Instructions</NavLink>
        </nav>
      </header>
      <main className="page">
        <Routes>
          <Route path="/" element={<QueuePage />} />
          <Route path="/claims/:claimId" element={<ClaimPage />} />
          <Route path="/scoreboard" element={<ScoreboardPage />} />
          <Route path="/evaluations/:runId" element={<EvaluationPage />} />
          <Route path="/instructions" element={<InstructionsPage />} />
          <Route path="*" element={<p className="message">Page not found</p>} />
        </Routes>
      </main>
    </>
  );
}
