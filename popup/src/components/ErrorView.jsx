export default function ErrorView({ message, onRetry }) {
  return (
    <div className="view error-box">
      <div className="error-icon" style={{ fontSize: 28 }}>⚠️</div>
      <div className="error-msg">{message || "Something went wrong."}</div>
      <button className="retry-btn" onClick={onRetry}>Try again</button>
    </div>
  );
}
