console.log("Pinpoint loaded");

let selectionActive = false;

// Single top-level listener — never registered inside startSelectionMode
chrome.runtime.onMessage.addListener((message) => {

    // ── Start selection mode ─────────────────────────────────────────────────
    if (message.action === "startSelection") {
        if (selectionActive) return;
        startSelectionMode();
    }

    // ── Receive raw screenshot, crop it, then send to background ────────────
    if (message.action === "cropImage") {

        const img = new Image();
        img.src = message.screenshot;

        img.onload = () => {

            const canvas = document.createElement("canvas");
            const ctx    = canvas.getContext("2d");
            const { x, y, width, height } = message.cropData;

            // Scale CSS pixels → physical pixels (fixes retina / HiDPI crops)
            const dpr          = window.devicePixelRatio || 1;
            const scaledX      = x      * dpr;
            const scaledY      = y      * dpr;
            const scaledWidth  = width  * dpr;
            const scaledHeight = height * dpr;

            canvas.width  = scaledWidth;
            canvas.height = scaledHeight;

            ctx.drawImage(
                img,
                scaledX, scaledY, scaledWidth, scaledHeight,
                0,       0,       scaledWidth, scaledHeight,
            );

            const croppedImage = canvas.toDataURL("image/png");

            // Remove old preview
            document.getElementById("pinpoint-preview")?.remove();

            // Show a small corner preview so the user sees what was captured
            const preview       = document.createElement("img");
            preview.id          = "pinpoint-preview";
            preview.src         = croppedImage;
            preview.title       = "Click to dismiss";
            preview.style.cssText = `
                position: fixed;
                bottom: 20px;
                right: 20px;
                width: 180px;
                z-index: 999999999;
                border: 3px solid #6c47ff;
                border-radius: 8px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.35);
                cursor: pointer;
                opacity: 0;
                transition: opacity 0.25s ease;
            `;
            preview.addEventListener("click", () => preview.remove());
            document.body.appendChild(preview);
            // Fade in
            requestAnimationFrame(() => {
                requestAnimationFrame(() => { preview.style.opacity = "1"; });
            });

            // Hand the cropped image off to the background script for the API call
            chrome.runtime.sendMessage({
                action:       "searchImage",
                croppedImage,
            });
        };
    }
});


function startSelectionMode() {

    selectionActive = true;

    // Clean up any leftover UI from a previous session
    document.getElementById("pinpoint-preview")?.remove();
    document.getElementById("pinpoint-overlay")?.remove();

    // ── Overlay ──────────────────────────────────────────────────────────────
    const overlay = document.createElement("div");
    overlay.id = "pinpoint-overlay";
    overlay.style.cssText = `
        position: fixed;
        top: 0; left: 0;
        width: 100vw; height: 100vh;
        cursor: crosshair;
        z-index: 999999999;
        background: rgba(0,0,0,0.08);
    `;
    document.body.appendChild(overlay);

    // ── Selection box ────────────────────────────────────────────────────────
    const selectionBox = document.createElement("div");
    selectionBox.style.cssText = `
        position: fixed;
        border: 2px solid #6c47ff;
        background: rgba(108,71,255,0.12);
        display: none;
        border-radius: 2px;
        pointer-events: none;
    `;
    overlay.appendChild(selectionBox);

    let startX, startY, isDrawing = false;

    overlay.addEventListener("mousedown", (e) => {
        isDrawing = true;
        startX = e.clientX;
        startY = e.clientY;
        selectionBox.style.display = "block";
        selectionBox.style.left   = startX + "px";
        selectionBox.style.top    = startY + "px";
        selectionBox.style.width  = "0px";
        selectionBox.style.height = "0px";
    });

    overlay.addEventListener("mousemove", (e) => {
        if (!isDrawing) return;
        const left   = Math.min(startX, e.clientX);
        const top    = Math.min(startY, e.clientY);
        const width  = Math.abs(e.clientX - startX);
        const height = Math.abs(e.clientY - startY);
        selectionBox.style.left   = left   + "px";
        selectionBox.style.top    = top    + "px";
        selectionBox.style.width  = width  + "px";
        selectionBox.style.height = height + "px";
    });

    overlay.addEventListener("mouseup", (e) => {
        if (!isDrawing) return;
        isDrawing = false;

        const cropData = {
            x:      Math.min(startX, e.clientX),
            y:      Math.min(startY, e.clientY),
            width:  Math.abs(e.clientX - startX),
            height: Math.abs(e.clientY - startY),
        };

        overlay.remove();
        selectionActive = false;

        chrome.runtime.sendMessage({ action: "captureArea", cropData });
    });

    overlay.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            overlay.remove();
            selectionActive = false;
        }
    });
}
