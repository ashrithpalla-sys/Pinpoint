const scanBtn       = document.getElementById("scanBtn");
const stepLabel     = document.getElementById("stepLabel");
const errorMsg      = document.getElementById("errorMsg");
const retryBtn      = document.getElementById("retryBtn");
const productList   = document.getElementById("productList");
const resultsHeader = document.getElementById("resultsHeader");
const sortSelect    = document.getElementById("sortSelect");
const priceFilter   = document.getElementById("priceFilter");
const toolbar       = document.getElementById("toolbar");

const STATES = ["idle", "loading", "error", "results"];

function showState(name) {
    STATES.forEach(s => {
        document.getElementById(`state-${s}`).style.display = s === name ? "block" : "none";
    });
    // Show toolbar only on results
    if (toolbar) toolbar.style.display = name === "results" ? "flex" : "none";
}

const STEPS = ["Uploading image…", "Running visual search…", "Scraping prices…", "Almost done…"];
let stepIdx = 0, stepTimer = null;

function startStepCycle() {
    stepIdx = 0;
    stepLabel.textContent = STEPS[0];
    stepTimer = setInterval(() => {
        stepIdx = Math.min(stepIdx + 1, STEPS.length - 1);
        stepLabel.textContent = STEPS[stepIdx];
    }, 3500);
}
function stopStepCycle() { clearInterval(stepTimer); }

function escHtml(str) {
    return String(str || "")
        .replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

let currentProducts = [];

function applyAndRender() {
    let list = [...currentProducts];

    // "Priced only" filter
    if (priceFilter && priceFilter.checked) {
        list = list.filter(p => p.price_value != null);
    }

    const sort = sortSelect ? sortSelect.value : "match";

    if (sort === "price_asc") {
        list.sort((a, b) => {
            // No price always goes to the bottom
            if (a.price_value == null && b.price_value == null) return 0;
            if (a.price_value == null) return 1;
            if (b.price_value == null) return -1;
            return a.price_value - b.price_value;
        });
    } else if (sort === "price_desc") {
        list.sort((a, b) => {
            if (a.price_value == null && b.price_value == null) return 0;
            if (a.price_value == null) return 1;
            if (b.price_value == null) return -1;
            return b.price_value - a.price_value;
        });
    }
    // "match" keeps server order (similarity score desc)

    renderList(list);
}

function renderList(products) {
    productList.innerHTML = "";

    if (!products || products.length === 0) {
        productList.innerHTML = `
            <div class="state-box" style="display:block">
                <div class="icon">🔍</div>
                <p>No results. Try adjusting filters.</p>
            </div>`;
        resultsHeader.textContent = "No results";
        return;
    }

    const withPrice    = products.filter(p => p.price_value != null).length;
    resultsHeader.textContent = `${products.length} matches · ${withPrice} with price`;

    products.forEach(p => {
        const scorePercent = Math.round((p.similarity_score || 0) * 100);

        let priceHtml;
        if (p.price) {
            if (p.in_stock === false) {
                priceHtml = `<span class="out-of-stock">${escHtml(p.price)} · Out of stock</span>`;
            } else {
                priceHtml = `<span class="product-price">${escHtml(p.price)}</span>`;
            }
        } else {
            priceHtml = `<span class="price-unknown">Price not found</span>`;
        }

        const card = document.createElement("a");
        card.className = "product-card";
        card.href      = p.link || "#";
        card.target    = "_blank";
        card.rel       = "noopener noreferrer";
        card.innerHTML = `
            <img class="product-thumb" src="${escHtml(p.thumbnail)}" alt=""
                 onerror="this.style.opacity='0.2'">
            <div class="product-info">
                <div class="product-title" title="${escHtml(p.title)}">${escHtml(p.title)}</div>
                <div class="product-source">${escHtml(p.source)}</div>
                <div class="product-footer">
                    ${priceHtml}
                    <span class="score-badge">${scorePercent}% match</span>
                </div>
            </div>`;
        productList.appendChild(card);
    });
}

function renderProducts(products) {
    currentProducts = products || [];
    applyAndRender();
    showState("results");
}

// Controls
if (sortSelect)  sortSelect.addEventListener("change", applyAndRender);
if (priceFilter) priceFilter.addEventListener("change", applyAndRender);

// On popup open
chrome.storage.local.get(["pinpointResults", "pinpointSearching"], (data) => {
    if (data.pinpointSearching) {
        showState("loading"); startStepCycle(); scanBtn.disabled = true;
    } else if (data.pinpointResults && data.pinpointResults.length > 0) {
        renderProducts(data.pinpointResults);
    }
});

// Scan
scanBtn.addEventListener("click", async () => {
    scanBtn.disabled = true;
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    await chrome.storage.local.remove(["pinpointResults", "pinpointSearching"]);
    chrome.tabs.sendMessage(tab.id, { action: "startSelection" });
    window.close();
});

// Retry
retryBtn.addEventListener("click", () => { showState("idle"); scanBtn.disabled = false; });

// Background messages
chrome.runtime.onMessage.addListener((message) => {
    if (message.action === "searchStarted") {
        showState("loading"); startStepCycle(); scanBtn.disabled = true;
    }
    if (message.action === "searchComplete") {
        stopStepCycle(); scanBtn.disabled = false; renderProducts(message.products);
    }
    if (message.action === "searchError") {
        stopStepCycle(); scanBtn.disabled = false;
        errorMsg.textContent = message.error || "Something went wrong.";
        showState("error");
    }
});


