console.log("Pinpoint background loaded");

const FASTAPI_URL = "http://localhost:8000";

async function getCountryCode() {
    try {
        // Use a free IP geolocation API — no key needed
        const resp = await fetch("https://ipapi.co/json/", { timeout: 5000 });
        const data = await resp.json();
        const code = (data.country_code || "us").toLowerCase();
        console.log("Pinpoint detected country:", code, "(" + (data.country_name || "") + ")");
        return code;
    } catch (e) {
        console.warn("Country detection failed, falling back to us:", e);
        // Fallback: try a second service
        try {
            const resp2 = await fetch("https://api.country.is/");
            const data2 = await resp2.json();
            return (data2.country || "us").toLowerCase();
        } catch (e2) {
            return "us";
        }
    }
}

chrome.runtime.onMessage.addListener(
    async (message, sender) => {

        if (message.action === "captureArea") {
            const screenshot = await chrome.tabs.captureVisibleTab();
            chrome.tabs.sendMessage(sender.tab.id, {
                action:   "cropImage",
                screenshot,
                cropData: message.cropData,
            });
        }

        if (message.action === "searchImage") {

            await chrome.storage.local.set({ pinpointSearching: true, pinpointResults: null });
            chrome.action.openPopup().catch(() => {});

            // Detect country from actual IP (respects VPN)
            const country = await getCountryCode();
            console.log("Pinpoint searching with country:", country);

            try {
                const resp = await fetch(`${FASTAPI_URL}/search`, {
                    method:  "POST",
                    headers: { "Content-Type": "application/json" },
                    body:    JSON.stringify({
                        image: message.croppedImage,
                        country,
                    }),
                });

                if (!resp.ok) {
                    // Backend sends {"detail": "specific, actionable message"} —
                    // fall back to raw text only if the body isn't JSON
                    let message;
                    try {
                        const errJson = await resp.json();
                        message = errJson.detail || JSON.stringify(errJson);
                    } catch {
                        message = await resp.text();
                    }
                    throw new Error(message);
                }

                const products = await resp.json();

                await chrome.storage.local.set({
                    pinpointResults:   products,
                    pinpointSearching: false,
                });

                chrome.runtime.sendMessage({ action: "searchComplete", products }).catch(() => {});
                chrome.action.openPopup().catch(() => {});

            } catch (err) {
                console.error("Pinpoint search error:", err);
                await chrome.storage.local.set({ pinpointSearching: false });
                chrome.runtime.sendMessage({ action: "searchError", error: err.message }).catch(() => {});
                chrome.action.openPopup().catch(() => {});
            }
        }
    }
);
