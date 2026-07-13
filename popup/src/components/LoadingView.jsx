import { useEffect, useState } from "react";

const STEPS = ["Uploading image…", "Running visual search…", "Scraping prices…", "Almost done…"];

function SkeletonCard() {
  return (
    <div className="skeleton-card">
      <div className="skeleton-thumb" />
      <div className="skeleton-lines">
        <div className="skeleton-line w-70" />
        <div className="skeleton-line w-40" />
        <div className="skeleton-line w-30" />
      </div>
    </div>
  );
}

export default function LoadingView() {
  const [stepIdx, setStepIdx] = useState(0);

  useEffect(() => {
    setStepIdx(0);
    const timer = setInterval(() => {
      setStepIdx((i) => Math.min(i + 1, STEPS.length - 1));
    }, 3500);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="view">
      <div className="spinner-wrap">
        <div className="spinner" />
        <div className="step-label">{STEPS[stepIdx]}</div>
      </div>
      <div className="skeleton-list">
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
    </div>
  );
}
