export default function Header({ scanDisabled, onScan, onHistory }) {
  return (
    <div className="header">
      <div className="logo">
        <svg className="logo-mark" width="21" height="21" viewBox="0 0 22 22" fill="none" xmlns="http://www.w3.org/2000/svg">
          <circle cx="11" cy="11" r="5.5" stroke="var(--accent)" strokeWidth="2" />
          <circle cx="11" cy="11" r="1.6" fill="var(--accent)" />
          <path d="M11 0.5V4.5M11 17.5V21.5M0.5 11H4.5M17.5 11H21.5" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" />
        </svg>
        Pinpoint
      </div>
      <div className="header-actions">
        <button id="historyBtn" title="Past scans" onClick={onHistory}>
          &#128340;
        </button>
        <button id="scanBtn" disabled={scanDisabled} onClick={onScan}>
          &#9654; Scan clothing
        </button>
      </div>
    </div>
  );
}
