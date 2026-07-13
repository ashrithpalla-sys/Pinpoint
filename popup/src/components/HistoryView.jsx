import { useEffect, useState } from "react";

const FASTAPI_URL = "http://localhost:8000";

function relativeTime(isoLike) {
  // SQLite CURRENT_TIMESTAMP is UTC without a "Z" — append it so Date parses correctly
  const date = new Date(isoLike.includes("Z") ? isoLike : isoLike.replace(" ", "T") + "Z");
  const mins = Math.round((Date.now() - date.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export default function HistoryView({ onSelect, onError }) {
  const [items, setItems] = useState(null); // null = loading
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetch(`${FASTAPI_URL}/history`)
      .then((resp) => {
        if (!resp.ok) throw new Error(`Server error ${resp.status}`);
        return resp.json();
      })
      .then((data) => { if (!cancelled) setItems(data); })
      .catch((err) => { if (!cancelled) setLoadError(err.message); });
    return () => { cancelled = true; };
  }, []);

  const handleClick = async (id) => {
    try {
      const resp = await fetch(`${FASTAPI_URL}/history/${id}`);
      if (!resp.ok) throw new Error(`Server error ${resp.status}`);
      const item = await resp.json();
      onSelect(item.products);
    } catch (err) {
      onError(err.message);
    }
  };

  return (
    <div className="view">
      <div className="results-header">Past scans</div>
      <div className="product-list">
        {loadError ? (
          <div className="state-box">
            <div className="icon">⚠️</div>
            <p>Couldn't load history.<br />{loadError}</p>
          </div>
        ) : items === null ? (
          <div className="state-box"><p>Loading…</p></div>
        ) : items.length === 0 ? (
          <div className="state-box">
            <div className="icon">🕘</div>
            <p>No past scans yet.</p>
          </div>
        ) : (
          items.map((item) => (
            <div key={item.id} className="history-item" onClick={() => handleClick(item.id)}>
              <img
                className="history-thumb"
                src={item.query_image_url}
                alt=""
                onError={(e) => { e.currentTarget.style.opacity = "0.2"; }}
              />
              <div className="history-info">
                <div className="product-title">
                  {item.result_count} match{item.result_count === 1 ? "" : "es"}
                </div>
                <div className="history-meta">
                  {item.country.toUpperCase()} · {relativeTime(item.created_at)}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
