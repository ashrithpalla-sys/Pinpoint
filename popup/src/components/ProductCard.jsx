export default function ProductCard({ product }) {
  const scorePercent = Math.round((product.similarity_score || 0) * 100);

  let priceEl;
  if (product.price) {
    if (product.in_stock === false) {
      priceEl = <span className="pill pill-outofstock">{product.price} · Out of stock</span>;
    } else {
      priceEl = <span className="pill pill-price">{product.price}</span>;
    }
  } else {
    priceEl = <span className="pill pill-unknown">Price not found</span>;
  }

  return (
    <a className="product-card" href={product.link || "#"} target="_blank" rel="noopener noreferrer">
      <img
        className="product-thumb"
        src={product.thumbnail}
        alt=""
        onError={(e) => { e.currentTarget.style.opacity = "0.2"; }}
      />
      <div className="product-info">
        <div className="product-title" title={product.title}>{product.title}</div>
        <div className="product-source">{product.source}</div>
        <div className="product-footer">
          {priceEl}
          <span className="pill pill-score">{scorePercent}% match</span>
        </div>
      </div>
    </a>
  );
}
