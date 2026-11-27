import { useState } from 'react';
import { Link, NavLink, Route, Routes, useLocation } from 'react-router-dom';
import { USE_MOCKS } from './api';
import { HealthIndicator } from './components/HealthIndicator';
import { EmptyState } from './components/States';
import { ScanPage } from './pages/ScanPage';
import { BatchesPage } from './pages/BatchesPage';
import { BatchPage } from './pages/BatchPage';
import { ReviewPage } from './pages/ReviewPage';
import { KeysPage } from './pages/KeysPage';
import { BenchmarksPage } from './pages/BenchmarksPage';

const NAV = [
  { to: '/', label: 'Scan', end: true },
  { to: '/batches', label: 'Batches', end: false },
  { to: '/keys', label: 'Answer keys', end: false },
  { to: '/benchmarks', label: 'Benchmarks', end: false },
];

export function App() {
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();
  const isReview = location.pathname.startsWith('/scans/');

  return (
    <div className={`app${isReview ? ' app--wide' : ''}`}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <div className="topbar__inner">
          <Link to="/" className="brand" aria-label="OMR Scanner home">
            <span className="brand__mark" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="22" height="22">
                <circle cx="7" cy="8" r="3.2" fill="currentColor" />
                <circle cx="17" cy="8" r="3.2" fill="none" stroke="currentColor" strokeWidth="1.8" />
                <circle cx="7" cy="17" r="3.2" fill="none" stroke="currentColor" strokeWidth="1.8" />
                <circle cx="17" cy="17" r="3.2" fill="currentColor" />
              </svg>
            </span>
            <span className="brand__name">OMR Scanner</span>
          </Link>
          <button
            type="button"
            className="btn btn--ghost topbar__menu"
            aria-expanded={menuOpen}
            aria-controls="main-nav"
            onClick={() => setMenuOpen((o) => !o)}
          >
            Menu
          </button>
          <nav id="main-nav" className={`nav${menuOpen ? ' nav--open' : ''}`} aria-label="Main">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end} className="nav__link" onClick={() => setMenuOpen(false)}>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="topbar__status">
            {USE_MOCKS && <span className="badge badge--mock">Mock data</span>}
            <HealthIndicator />
          </div>
        </div>
      </header>
      <main id="main" className="main" tabIndex={-1}>
        <Routes>
          <Route path="/" element={<ScanPage />} />
          <Route path="/batches" element={<BatchesPage />} />
          <Route path="/batches/:id" element={<BatchPage />} />
          <Route path="/scans/:id" element={<ReviewPage />} />
          <Route path="/keys" element={<KeysPage />} />
          <Route path="/keys/:id" element={<KeysPage />} />
          <Route path="/benchmarks" element={<BenchmarksPage />} />
          <Route
            path="*"
            element={
              <EmptyState title="Page not found">
                <p>
                  <Link to="/">Go to the Scan page</Link>
                </p>
              </EmptyState>
            }
          />
        </Routes>
      </main>
    </div>
  );
}
