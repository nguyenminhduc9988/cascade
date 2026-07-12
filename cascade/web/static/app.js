/* Cascade web client — SSE indicator + HTMX helpers.
 *
 * The HTMX SSE extension wires per-project event streams into the DOM; this
 * file augments the global nav with a connection indicator and provides a few
 * small utilities shared across pages.
 */
(function () {
    "use strict";

    function setSseStatus(connected) {
        const el = document.getElementById("sse-status");
        if (!el) return;
        const dot = el.querySelector("span:first-child");
        const text = el.lastChild;
        if (connected) {
            if (dot) dot.className = "w-2 h-2 rounded-full bg-emerald-400 animate-pulse";
            el.classList.remove("text-slate-400");
            el.classList.add("text-emerald-400");
            text.textContent = " live";
        } else {
            if (dot) dot.className = "w-2 h-2 rounded-full bg-slate-600";
            el.classList.add("text-slate-400");
            el.classList.remove("text-emerald-400");
            text.textContent = " offline";
        }
    }

    // Reflect any active SSE connection (opened by the htmx sse extension) in the nav.
    document.body.addEventListener("htmx:sseConnect", () => setSseStatus(true));
    document.body.addEventListener("htmx:sseClose", () => setSseStatus(false));
    document.body.addEventListener("htmx:sseError", () => setSseStatus(false));

    // When a message arrives, flash the nav dot briefly.
    document.body.addEventListener("htmx:sseMessage", () => {
        const el = document.getElementById("sse-status");
        if (el) {
            el.style.transition = "color 0.2s";
            el.classList.add("text-brand-400");
            setTimeout(() => el.classList.remove("text-brand-400"), 600);
        }
    });

    // Auto-scroll conversation logs to the bottom on load.
    function scrollMessages() {
        const box = document.getElementById("messages");
        if (box) box.scrollTop = box.scrollHeight;
    }
    window.addEventListener("load", scrollMessages);
    document.body.addEventListener("htmx:afterSwap", scrollMessages);
})();
