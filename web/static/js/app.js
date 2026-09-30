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
 *   GET    /api/settings                             -> which API keys are set (secrets masked)
 *   POST   /api/settings                             -> save / remove API keys
 *   POST   /api/settings/youtube/client-secret       -> upload YouTube's client_secret.json
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

    const settingsToggleBtn = document.getElementById("settings-toggle-btn");
    const settingsCloseBtn = document.getElementById("settings-close-btn");
    const settingsSection = document.getElementById("settings-section");
    const settingsErrorBanner = document.getElementById("settings-error");
    const settingsErrorMessage = document.getElementById("settings-error-message");
    const settingsGrid = document.getElementById("settings-grid");

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
    // API keys panel
    // ---------------------------------------------------------------

    const KEY_STATUS_BADGES = {
        ready: { text: "Connected", className: "badge-ready" },
        partial: { text: "Incomplete", className: "badge-partial" },
        missing: { text: "Not set", className: "badge-missing" },
    };

    function showSettingsError(message) {
        settingsErrorMessage.textContent = message || "Something went wrong.";
        settingsErrorBanner.classList.remove("hidden");
    }

    function hideSettingsError() {
        settingsErrorBanner.classList.add("hidden");
        settingsErrorMessage.textContent = "";
    }

    function createSettingsCard(title, status, description, uploaderError) {
        const card = document.createElement("div");
        card.className = "settings-card";

        const head = document.createElement("div");
        head.className = "settings-card-head";

        const heading = document.createElement("div");
        heading.className = "settings-card-title";
        heading.textContent = title;

        const badgeInfo = KEY_STATUS_BADGES[status] || KEY_STATUS_BADGES.missing;
        const badge = document.createElement("span");
        badge.className = `settings-badge ${badgeInfo.className}`;
        badge.textContent = badgeInfo.text;

        head.append(heading, badge);
        card.appendChild(head);

        const desc = document.createElement("p");
        desc.className = "settings-card-desc";
        desc.textContent = description;
        card.appendChild(desc);

        if (uploaderError) {
            const warning = document.createElement("div");
            warning.className = "settings-warning";
            warning.textContent =
                `Uploader unavailable (${uploaderError}). ` +
                "Run pip install -r requirements.txt and restart the server.";
            card.appendChild(warning);
        }

        return card;
    }

    // One "label ... state" line, e.g. "Page ID [FACEBOOK_PAGE_ID]   Saved".
    function createLabelRow(labelText, codeText, stateText, isSet, forId) {
        const row = document.createElement("div");
        row.className = "settings-label-row";

        const label = document.createElement(forId ? "label" : "span");
        label.className = "settings-label";
        label.textContent = labelText;
        if (forId) {
            label.htmlFor = forId;
        }

        const code = document.createElement("code");
        code.className = "settings-env-name";
        code.textContent = codeText;
        label.appendChild(code);

        const state = document.createElement("span");
        state.className = "settings-field-state";
        state.classList.toggle("is-set", isSet);
        state.textContent = stateText;

        row.append(label, state);
        return row;
    }

    function createKeyField(key) {
        const field = document.createElement("div");
        field.className = "settings-field";

        const inputId = `key-${key.name}`;
        let stateText = "Not set";
        if (key.set) {
            stateText = "Saved";
        } else if (key.fallback_active) {
            stateText = `Using ${key.fallback}`;
        }
        field.appendChild(createLabelRow(key.label, key.name, stateText, key.set, inputId));

        const inputRow = document.createElement("div");
        inputRow.className = "settings-input-row";

        const input = document.createElement("input");
        input.id = inputId;
        input.type = key.secret ? "password" : "text";
        input.className = "settings-input";
        input.autocomplete = "off";
        input.spellcheck = false;
        input.dataset.name = key.name;
        // Blank means "keep the saved value", so the placeholder shows what's saved.
        input.placeholder = key.set ? key.display : "Paste value...";
        inputRow.appendChild(input);

        if (key.secret) {
            const toggle = document.createElement("button");
            toggle.type = "button";
            toggle.className = "btn-inline";
            toggle.textContent = "Show";
            toggle.addEventListener("click", () => {
                const reveal = input.type === "password";
                input.type = reveal ? "text" : "password";
                toggle.textContent = reveal ? "Hide" : "Show";
            });
            inputRow.appendChild(toggle);
        }

        if (key.set) {
            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "btn-inline danger";
            remove.textContent = "Remove";
            remove.addEventListener("click", () => removeKey(key, remove));
            inputRow.appendChild(remove);
        }

        field.appendChild(inputRow);
        return { field, input };
    }

    function createKeyGroupCard(group) {
        const card = createSettingsCard(group.title, group.status, group.description, group.uploader_error);

        const inputs = [];
        for (const key of group.keys) {
            const { field, input } = createKeyField(key);
            inputs.push(input);
            card.appendChild(field);
        }

        const saveBtn = document.createElement("button");
        saveBtn.type = "button";
        saveBtn.className = "btn-primary btn-small";
        saveBtn.textContent = "Save";
        saveBtn.disabled = true;
        saveBtn.addEventListener("click", () => saveKeys(group, inputs, saveBtn));

        for (const input of inputs) {
            input.addEventListener("input", () => {
                saveBtn.disabled = !inputs.some((i) => i.value.trim());
            });
            input.addEventListener("keydown", (event) => {
                if (event.key === "Enter" && !saveBtn.disabled) {
                    event.preventDefault();
                    saveBtn.click();
                }
            });
        }

        const footer = document.createElement("div");
        footer.className = "settings-card-footer";
        footer.appendChild(saveBtn);
        card.appendChild(footer);
        return card;
    }

    function createYouTubeCard(youtube) {
        const card = createSettingsCard(
            "YouTube",
            youtube.client_secret ? "ready" : "missing",
            "Uses an OAuth client file instead of a key. In Google Cloud Console, enable " +
                "YouTube Data API v3, create an OAuth client (type: Desktop app) and upload " +
                "its JSON here. The first publish opens a browser window to sign in.",
            youtube.uploader_error
        );

        card.appendChild(createLabelRow(
            "OAuth client file", "client_secret.json",
            youtube.client_secret ? "Uploaded" : "Not uploaded", youtube.client_secret
        ));
        card.appendChild(createLabelRow(
            "Account sign-in", "token.json",
            youtube.token ? "Signed in" : "On first publish", youtube.token
        ));

        const fileInput = document.createElement("input");
        fileInput.type = "file";
        fileInput.accept = ".json,application/json";
        fileInput.className = "hidden";

        const uploadBtn = document.createElement("button");
        uploadBtn.type = "button";
        uploadBtn.className = "btn-primary btn-small";
        uploadBtn.textContent = youtube.client_secret ? "Replace file" : "Upload client_secret.json";
        uploadBtn.addEventListener("click", () => fileInput.click());

        fileInput.addEventListener("change", () => {
            const file = fileInput.files[0];
            fileInput.value = ""; // so picking the same file again still fires "change"
            if (file) {
                uploadClientSecret(file, uploadBtn);
            }
        });

        const footer = document.createElement("div");
        footer.className = "settings-card-footer";
        footer.append(fileInput, uploadBtn);
        card.appendChild(footer);
        return card;
    }

    function renderSettings(settings) {
        settingsGrid.innerHTML = "";

        const groups = settings.groups || [];
        for (const group of groups) {
            settingsGrid.appendChild(createKeyGroupCard(group));
        }
        if (settings.youtube) {
            settingsGrid.appendChild(createYouTubeCard(settings.youtube));
        }

        // Videos can't be processed without Groq, so flag it on the header button.
        const groq = groups.find((g) => g.id === "groq");
        const needsGroq = !groq || groq.status !== "ready";
        settingsToggleBtn.classList.toggle("needs-attention", needsGroq);
        settingsToggleBtn.title = needsGroq ? "Groq API key is missing — processing videos needs it." : "";
    }

    async function loadSettings() {
        try {
            const res = await fetch("/api/settings");
            if (!res.ok) {
                throw new Error(`Request failed with status ${res.status}`);
            }
            renderSettings(await res.json());
        } catch (err) {
            console.error("Failed to load API keys:", err);
            showSettingsError("Could not load API keys from the server.");
        }
    }

    // Shared by save / remove / upload: every settings write returns the
    // fresh settings payload, which re-renders the whole panel.
    async function submitSettings(url, options, successMessage) {
        try {
            const res = await fetch(url, options);
            const data = await res.json();

            if (!res.ok || !data.success) {
                showSettingsError(data.error || "Could not save API keys.");
                return false;
            }

            hideSettingsError();
            renderSettings(data.settings);
            showToast(successMessage);
            return true;
        } catch (err) {
            console.error("Failed to save API keys:", err);
            showSettingsError("Could not reach the server to save API keys.");
            return false;
        }
    }

    function jsonPost(body) {
        return {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        };
    }

    async function saveKeys(group, inputs, saveBtn) {
        const values = {};
        for (const input of inputs) {
            const value = input.value.trim();
            if (value) {
                values[input.dataset.name] = value;
            }
        }

        saveBtn.disabled = true;
        saveBtn.textContent = "Saving...";

        const ok = await submitSettings("/api/settings", jsonPost({ values }), `${group.title} saved.`);
        if (!ok) {
            saveBtn.disabled = false;
            saveBtn.textContent = "Save";
        }
    }

    async function removeKey(key, btn) {
        const confirmed = window.confirm(`Remove ${key.name} from .env?`);
        if (!confirmed) {
            return;
        }

        btn.disabled = true;
        const ok = await submitSettings("/api/settings", jsonPost({ clear: [key.name] }), `${key.name} removed.`);
        if (!ok) {
            btn.disabled = false;
        }
    }

    async function uploadClientSecret(file, btn) {
        const form = new FormData();
        form.append("file", file);

        const originalLabel = btn.textContent;
        btn.disabled = true;
        btn.textContent = "Uploading...";

        const ok = await submitSettings(
            "/api/settings/youtube/client-secret",
            { method: "POST", body: form },
            "YouTube client file saved."
        );
        if (!ok) {
            btn.disabled = false;
            btn.textContent = originalLabel;
        }
    }

    function setSettingsOpen(open) {
        settingsSection.classList.toggle("hidden", !open);
        settingsToggleBtn.classList.toggle("active", open);
        settingsToggleBtn.setAttribute("aria-expanded", String(open));
        if (open) {
            hideSettingsError();
            loadSettings(); // refresh, e.g. token.json appears after the first YouTube publish
        }
    }

    // ---------------------------------------------------------------
    // Wiring
    // ---------------------------------------------------------------

    settingsToggleBtn.addEventListener("click", () => {
        setSettingsOpen(settingsSection.classList.contains("hidden"));
    });
    settingsCloseBtn.addEventListener("click", () => setSettingsOpen(false));

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
        loadSettings(); // so the header button can flag a missing Groq key
    });
})();
