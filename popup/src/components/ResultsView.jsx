import { useMemo } from "react";
import ProductCard from "./ProductCard.jsx";

export default function ResultsView({ products, sort, priceOnly, onSortChange, onPriceOnlyChange }) {
  const list = useMemo(() => {
    let filtered = priceOnly ? products.filter((p) => p.price_value != null) : [...products];

    if (sort === "price_asc" || sort === "price_desc") {
      const dir = sort === "price_asc" ? 1 : -1;
      filtered.sort((a, b) => {
        if (a.price_value == null && b.price_value == null) return 0;
        if (a.price_value == null) return 1;
        if (b.price_value == null) return -1;
        return dir * (a.price_value - b.price_value);
      });
    }
    // "match" keeps server order (similarity score desc)

    return filtered;
  }, [products, sort, priceOnly]);

  const withPrice = list.filter((p) => p.price_value != null).length;

  return (
    <div className="view">
      <div className="toolbar">
        <select value={sort} onChange={(e) => onSortChange(e.target.value)}>
          <option value="match">Sort: Best match</option>
          <option value="price_asc">Sort: Price low → high</option>
          <option value="price_desc">Sort: Price high → low</option>
        </select>
        <label className="filter-label">
          <input
            type="checkbox"
            checked={priceOnly}
            onChange={(e) => onPriceOnlyChange(e.target.checked)}
          />
          Priced only
        </label>
      </div>

      {list.length === 0 ? (
        <div className="state-box">
          <div className="icon">🔍</div>
          <p>No results. Try adjusting filters.</p>
        </div>
      ) : (
        <>
          <div className="results-header">{list.length} matches · {withPrice} with price</div>
          <div className="product-list">
            {list.map((p, i) => <ProductCard key={p.link || i} product={p} />)}
          </div>
        </>
      )}
    </div>
  );
}
