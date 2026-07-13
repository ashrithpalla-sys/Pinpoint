import { useEffect, useState, useCallback } from "react";
import Header from "./components/Header.jsx";
import IdleView from "./components/IdleView.jsx";
import LoadingView from "./components/LoadingView.jsx";
import ErrorView from "./components/ErrorView.jsx";
import ResultsView from "./components/ResultsView.jsx";
import HistoryView from "./components/HistoryView.jsx";

export default function App() {
  const [view, setView] = useState("idle");
  const [products, setProducts] = useState([]);
  const [errorMsg, setErrorMsg] = useState("");
  const [scanDisabled, setScanDisabled] = useState(false);
  const [sort, setSort] = useState("match");
  const [priceOnly, setPriceOnly] = useState(false);

  // Restore state on popup open (mirrors old popup.js chrome.storage.local check)
  useEffect(() => {
    chrome.storage.local.get(["pinpointResults", "pinpointSearching"], (data) => {
      if (data.pinpointSearching) {
        setView("loading");
        setScanDisabled(true);
      } else if (data.pinpointResults && data.pinpointResults.length > 0) {
        setProducts(data.pinpointResults);
        setView("results");
      }
    });
  }, []);

  // Background script messages
  useEffect(() => {
    const listener = (message) => {
      if (message.action === "searchStarted") {
        setView("loading");
        setScanDisabled(true);
      }
      if (message.action === "searchComplete") {
        setScanDisabled(false);
        setProducts(message.products || []);
        setView("results");
      }
      if (message.action === "searchError") {
        setScanDisabled(false);
        setErrorMsg(message.error || "Something went wrong.");
        setView("error");
      }
    };
    chrome.runtime.onMessage.addListener(listener);
    return () => chrome.runtime.onMessage.removeListener(listener);
  }, []);

  const handleScan = useCallback(async () => {
    setScanDisabled(true);
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    await chrome.storage.local.remove(["pinpointResults", "pinpointSearching"]);
    chrome.tabs.sendMessage(tab.id, { action: "startSelection" });
    window.close();
  }, []);

  const handleRetry = useCallback(() => {
    setView("idle");
    setScanDisabled(false);
  }, []);

  const handleHistoryOpen = useCallback(() => setView("history"), []);

  const handleHistorySelect = useCallback((selectedProducts) => {
    setProducts(selectedProducts || []);
    setView("results");
  }, []);

  const handleHistoryError = useCallback((message) => {
    setErrorMsg(message || "Couldn't load that scan.");
    setView("error");
  }, []);

  return (
    <>
      <Header scanDisabled={scanDisabled} onScan={handleScan} onHistory={handleHistoryOpen} />

      {view === "idle" && <IdleView />}
      {view === "loading" && <LoadingView />}
      {view === "error" && <ErrorView message={errorMsg} onRetry={handleRetry} />}
      {view === "results" && (
        <ResultsView
          products={products}
          sort={sort}
          priceOnly={priceOnly}
          onSortChange={setSort}
          onPriceOnlyChange={setPriceOnly}
        />
      )}
      {view === "history" && (
        <HistoryView onSelect={handleHistorySelect} onError={handleHistoryError} />
      )}
    </>
  );
}
