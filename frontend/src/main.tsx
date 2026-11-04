import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { QueuePage } from "./pages/QueuePage";
import "./styles.css";

// The review page bundles PDF.js; load it only when a claim is opened.
const ClaimPage = lazy(() => import("./pages/ClaimPage").then((m) => ({ default: m.ClaimPage })));

function App() {
  return (
    <BrowserRouter>
      <header className="topbar">
        <Link to="/" className="brand">
          <span className="brand__mark" aria-hidden>
            <svg viewBox="0 0 32 32" width="22" height="22">
              <circle cx="14" cy="14" r="7" fill="none" stroke="currentColor" strokeWidth="3" />
              <path d="M19.5 19.5l6 6" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
            </svg>
          </span>
          ClaimLens
        </Link>
        <span className="topbar__subtitle">Claim intake &amp; review</span>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<QueuePage />} />
          <Route
            path="/claims/:id"
            element={
              <Suspense fallback={<div className="page muted">Loading…</div>}>
                <ClaimPage />
              </Suspense>
            }
          />
          <Route path="*" element={<div className="page">Page not found. <Link to="/">Go to claims</Link></div>} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
