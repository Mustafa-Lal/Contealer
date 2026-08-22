/**
 * web/static/js/app.js
 *
 * Vanilla JS for the ClipForge dashboard. Talks to the Flask API in
 * web/app.py:
 *
 *   POST   /api/process                            -> kick off the pipeline on a video URL
 *   GET    /api/status                              -> poll while a job is running
 *   GET    /api/clips                               -> list already-generated vertical clips
 *   POST   /api/clips/<filename>/publish/<platform>  -> publish one clip to one platform
 *   DELETE /api/clips/<filename>                     -> delete a clip
 *   GET    /media/<file>                              -> stream a clip's mp4
 *
 * No framework, no bundler -- just DOM APIs and fetch().
 */

(() => {
    "use strict";

    // ---------------------------------------------------------------
    // Element references
    // ---------------------------------------------------------------
    const urlInput = document.getElementById("url-input");
    const processBtn = document.getElementById("process-btn");

    const errorBanner = document.getElementById("error-banner");
    const errorMessage = document.getElementById("error-message");

    const statusSection = document.getElementById("status-section");
    const statusStepLabel = document.getElementById("status-step-label");

    const clipsCount = document.getElementById("clips-count");
    const emptyState = document.getElementById("empty-state");
    const clipGrid = document.getElementById("clip-grid");

    const toast = document.getElementById("toast");

    // How often to poll /api/status while a job is active (ms).
    const POLL_INTERVAL_MS = 1500;
    let pollTimer = null;

    // Platforms a clip can be published to, and their button labels.
    const PLATFORMS = [
        { key: "facebook", label: "Facebook" },
        { key: "youtube", label: "YouTube" },
        { key: "instagram", label: "Instagram" },
        { key: "tiktok", label: "TikTok" },
    ];

    // ---------------------------------------------------------------
    // Status / error / toast helpers
    // ---------------------------------------------------------------

    function showProcessing(stepLabel) {
        statusSection.classList.remove("hidden");
        statusStepLabel.textContent = stepLabel || "Starting...";
        processBtn.disabled = true;
        urlInput.disabled = true;
    }

    function hideProcessing() {
        statusSection.classList.add("hidden");
        processBtn.disabled = false;
        urlInput.disabled = false;
    }

    function showError(message) {
        errorMessage.textContent = message || "Something went wrong.";
        errorBanner.classList.remove("hidden");
    }

    function hideError() {
        errorBanner.classList.add("hidden");
        errorMessage.textContent = "";
    }

    function showToast(message) {
        toast.textContent = message;
        toast.classList.add("visible");
        window.clearTimeout(showToast._t);
        showToast._t = window.setTimeout(() => {
            toast.classList.remove("visible");
        }, 2800);
    }

    function showSuccess(clips) {
        renderClips(clips);
        showToast("Processing completed.");
    }

    // ---------------------------------------------------------------
    // Rendering
    // ---------------------------------------------------------------

    function formatDuration(seconds) {
        if (seconds === null || seconds === undefined || Number.isNaN(seconds)) {
            return "";
        }
        const total = Math.max(0, Math.round(seconds));
        const mins = Math.floor(total / 60);
        const secs = total % 60;
        return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
    }

    function createHashtagsRow(hashtags) {
        const row = document.createElement("div");
        row.className = "clip-hashtags";

        for (const tag of hashtags || []) {
            const chip = document.createElement("span");
            chip.className = "hashtag-chip";
            chip.textContent = tag;
            row.appendChild(chip);
        }

        return row;
    }

    // Updates a single platform button's label/state in place. Kept as a
    // standalone function so publishToPlatform() can call it again after
    // the request resolves without needing to re-render the whole card
    // (which would otherwise remount the <video> and interrupt playback).
    function updatePlatformButton(btn, { published, busy, label }) {
        btn.dataset.label = label;
        if (published) {
            btn.textContent = `${label} \u2713`; // checkmark
            btn.disabled = true;
            btn.classList.add("published");
        } else if (busy) {
            btn.textContent = "Publishing...";
            btn.disabled = true;
            btn.classList.remove("published");
        } else {
            btn.textContent = label;
            btn.disabled = false;
            btn.classList.remove("published");
        }
    }

    function createPlatformButton(clip) {
        return (platform) => {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "btn-platform";

            const isPublished = !!(clip.published && clip.published[platform.key]);
            updatePlatformButton(btn, { published: isPublished, busy: false, label: platform.label });

            if (!isPublished) {
                btn.addEventListener("click", () => {
                    publishToPlatform(clip.filename, platform.key, platform.label, btn);
                });
            }

            return btn;
        };
    }

    function createDeleteButton(clip, card) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn-delete";
        btn.textContent = "Delete";
        btn.addEventListener("click", () => deleteClip(clip.filename, btn, card));
        return btn;
    }

    function createClipCard(clip) {
        const card = document.createElement("div");
        card.className = "clip-card";

        const videoWrap = document.createElement("div");
        videoWrap.className = "clip-video-wrap";

        const video = document.createElement("video");
        video.controls = true;
        video.preload = "metadata";
        // Intentionally no autoplay -- clips only play when the user hits play.

        const source = document.createElement("source");
        source.src = clip.url;
        source.type = "video/mp4";
        video.appendChild(source);
        videoWrap.appendChild(video);

        const body = document.createElement("div");
        body.className = "clip-body";

        const title = document.createElement("div");
        title.className = "clip-title";
        title.textContent = clip.title || "Untitled clip";
        body.appendChild(title);

        const duration = document.createElement("div");
        duration.className = "clip-duration";
        duration.textContent = formatDuration(clip.duration);
        if (duration.textContent) {
            body.appendChild(duration);
        }

        body.appendChild(createHashtagsRow(clip.hashtags));

        const actions = document.createElement("div");
        actions.className = "clip-actions";
        const makeButton = createPlatformButton(clip);
        for (const platform of PLATFORMS) {
            actions.appendChild(makeButton(platform));
        }
        body.appendChild(actions);

        body.appendChild(createDeleteButton(clip, card));

        card.appendChild(videoWrap);
        card.appendChild(body);
        return card;
    }

    function renderClips(clips) {
        clipGrid.innerHTML = "";

        const list = Array.isArray(clips) ? clips : [];
        clipsCount.textContent = `${list.length} clip${list.length === 1 ? "" : "s"}`;

        if (list.length === 0) {
            emptyState.classList.remove("hidden");
            clipGrid.classList.add("hidden");
            return;
        }

        emptyState.classList.add("hidden");
        clipGrid.classList.remove("hidden");

        for (const clip of list) {
            clipGrid.appendChild(createClipCard(clip));
        }
    }

    function updateClipsCountAfterRemoval() {
        const remaining = clipGrid.children.length;
        clipsCount.textContent = `${remaining} clip${remaining === 1 ? "" : "s"}`;
        if (remaining === 0) {
            emptyState.classList.remove("hidden");
            clipGrid.classList.add("hidden");
        }
    }

    // ---------------------------------------------------------------
    // Publish / delete actions
    // ---------------------------------------------------------------

    async function publishToPlatform(filename, platformKey, platformLabel, btn) {
        updatePlatformButton(btn, { published: false, busy: true, label: platformLabel });

        try {
            const res = await fetch(
                `/api/clips/${encodeURIComponent(filename)}/publish/${encodeURIComponent(platformKey)}`,
                { method: "POST" }
            );
            const data = await res.json();

            if (!res.ok || !data.success) {
                updatePlatformButton(btn, { published: false, busy: false, label: platformLabel });
                showError(data.error || `Failed to publish to ${platformLabel}.`);
                return;
            }

            updatePlatformButton(btn, { published: true, busy: false, label: platformLabel });
            hideError();
            showToast(`Published to ${platformLabel}.`);
        } catch (err) {
            console.error(`Failed to publish to ${platformLabel}:`, err);
            updatePlatformButton(btn, { published: false, busy: false, label: platformLabel });
            showError(`Could not reach the server to publish to ${platformLabel}.`);
        }
    }

    async function deleteClip(filename, btn, card) {
        const confirmed = window.confirm("Delete this clip? This can't be undone.");
        if (!confirmed) {
            return;
        }

        btn.disabled = true;
        btn.textContent = "Deleting...";

        try {
            const res = await fetch(`/api/clips/${encodeURIComponent(filename)}`, { method: "DELETE" });
            const data = await res.json();

            if (!res.ok || !data.success) {
                btn.disabled = false;
                btn.textContent = "Delete";
                showError(data.error || "Failed to delete this clip.");
                return;
            }

            card.remove();
            updateClipsCountAfterRemoval();
            hideError();
            showToast("Clip deleted.");
        } catch (err) {
            console.error("Failed to delete clip:", err);
            btn.disabled = false;
            btn.textContent = "Delete";
            showError("Could not reach the server to delete this clip.");
        }
    }

    // ---------------------------------------------------------------
    // API calls -- processing pipeline
    // ---------------------------------------------------------------

    async function loadClips() {
        try {
            const res = await fetch("/api/clips");
            if (!res.ok) {
                throw new Error(`Request failed with status ${res.status}`);
            }
            const data = await res.json();
            renderClips(data.clips || []);
        } catch (err) {
            console.error("Failed to load clips:", err);
            // Non-fatal: leave whatever was already rendered (or empty state).
        }
    }

    async function pollStatus() {
        try {
            const res = await fetch("/api/status");
            const state = await res.json();

            if (state.active) {
                showProcessing(state.step);
                pollTimer = window.setTimeout(pollStatus, POLL_INTERVAL_MS);
                return;
            }

            // Job is no longer active -- stop polling and settle on a result.
            hideProcessing();

            if (state.success === true) {
                hideError();
                showSuccess(state.clips || []);
            } else if (state.success === false) {
                showError(state.error);
            }
        } catch (err) {
            console.error("Failed to poll status:", err);
            hideProcessing();
            showError("Lost connection to the server while processing.");
        }
    }

    function startPolling() {
        window.clearTimeout(pollTimer);
        pollStatus();
    }

    async function processVideo() {
        const url = urlInput.value.trim();

        if (!url) {
            showError("Please paste a video URL first.");
            return;
        }

        hideError();
        showProcessing("Starting...");

        try {
            const res = await fetch("/api/process", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url }),
            });
            const data = await res.json();

            if (!res.ok || !data.success) {
                hideProcessing();
                showError(data.error || "Failed to start processing.");
                return;
            }

            startPolling();
        } catch (err) {
            console.error("Failed to start processing:", err);
            hideProcessing();
            showError("Could not reach the server. Is it running?");
        }
    }

    // ---------------------------------------------------------------
    // Wiring
    // ---------------------------------------------------------------

    processBtn.addEventListener("click", processVideo);

    urlInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            processVideo();
        }
    });

    // On load: show whatever clips already exist on disk, and, in case a
    // job was left running from a previous session (e.g. page refresh
    // mid-process), pick the status polling back up too.
    document.addEventListener("DOMContentLoaded", () => {
        loadClips();
        pollStatus();
    });
})();
