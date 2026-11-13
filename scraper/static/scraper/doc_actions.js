(function () {
    "use strict";

    class DocActions {
        static SELECTOR = ".doc-action-btn";

        static csrfToken() {
            const input = document.querySelector("input[name=csrfmiddlewaretoken]");
            if (input) {
                return input.value;
            }
            const match = document.cookie.match(/(^|;)\s*csrftoken=([^;]*)/);
            return match ? decodeURIComponent(match[2]) : "";
        }

        static isDark() {
            return document.documentElement.classList.contains("dark");
        }

        static submit(url, mode) {
            const form = document.createElement("form");
            form.method = "POST";
            form.action = url;

            const fields = { csrfmiddlewaretoken: DocActions.csrfToken(), mode: mode };
            for (const [name, value] of Object.entries(fields)) {
                const input = document.createElement("input");
                input.type = "hidden";
                input.name = name;
                input.value = value;
                form.appendChild(input);
            }

            document.body.appendChild(form);
            form.submit();
        }

        static buttonHtml(m) {
            return (
                '<button type="button" class="doc-mode-btn" ' +
                'data-mode="' + m.mode + '" ' +
                'style="background:' + m.colour + ';">' +
                '<div class="doc-mode-label">' + m.label + "</div>" +
                '<div class="doc-mode-hint">' + m.hint + "</div>" +
                "</button>"
            );
        }

        static optionsHtml(modes) {
            const groups = {};
            let html = "";
            modes.forEach(function (m) {
                if (m.group) {
                    (groups[m.group] = groups[m.group] || []).push(m);
                } else {
                    html += DocActions.buttonHtml(m);
                }
            });
            for (const [name, items] of Object.entries(groups)) {
                html +=
                    '<details class="doc-mode-group">' +
                    "<summary>" + name + "</summary>" +
                    items.map(DocActions.buttonHtml).join("") +
                    "</details>";
            }
            return html;
        }

        static open(button) {
            const url = button.dataset.url;
            const modes = JSON.parse(button.dataset.modes);
            const dark = DocActions.isDark();

            Swal.fire({
                title: "Document #" + button.dataset.doc,
                html: DocActions.optionsHtml(modes),
                showConfirmButton: false,
                showCancelButton: true,
                cancelButtonText: "Cancel",
                background: dark ? "#1a1d29" : "#ffffff",
                color: dark ? "#d1d5db" : "#374151",
                didOpen: function (popup) {
                    popup.querySelectorAll(".doc-mode-btn").forEach(function (el) {
                        el.addEventListener("click", function () {
                            Swal.close();
                            DocActions.submit(url, el.dataset.mode);
                        });
                    });
                },
            });
        }

        static bind() {
            document.addEventListener("click", function (event) {
                const button = event.target.closest(DocActions.SELECTOR);
                if (!button) {
                    return;
                }
                event.preventDefault();
                DocActions.open(button);
            });
        }
    }

    class DocProgress {
        static SELECTOR = ".doc-progress-btn";
        static TICK_MS = 1000;
        static DENIED = "Progress hidden: you don't have access to Temporal tasks.";
        static ICONS = { done: "\u2713", running: "", failed: "\u2715", stopped: "\u25A0", pending: "" };
        static STATUS_TONES = { Running: "blue", Completed: "green", Paused: "amber" };

        static escape(text) {
            const div = document.createElement("div");
            div.textContent = text == null ? "" : String(text);
            return div.innerHTML;
        }

        static seconds(ms) {
            if (ms < 1000) {
                return Math.max(0, Math.round(ms)) + "ms";
            }
            const total = Math.round(ms / 1000);
            const h = Math.floor(total / 3600);
            const m = Math.floor((total % 3600) / 60);
            const s = total % 60;
            if (h) {
                return h + "h " + m + "m";
            }
            return m ? m + "m " + s + "s" : s + "s";
        }

        static duration(step) {
            if (!step.started_at) {
                return "";
            }
            const end = step.ended_at && step.state !== "running" ? new Date(step.ended_at) : Date.now();
            return DocProgress.seconds(end - new Date(step.started_at));
        }

        static bar(percent, tone) {
            const width = Math.min(100, Math.max(0, percent)).toFixed(1);
            return '<div class="dp-bar dp-bar-' + tone + '"><div style="width:' + width + '%"></div></div>';
        }

        static batchHtml(step) {
            if (step.total == null) {
                return "";
            }
            const percent = step.total ? (step.done / step.total) * 100 : 100;
            return DocProgress.bar(percent, "blue");
        }

        static stepHtml(step) {
            const extra = step.key === "embed_batch" ? DocProgress.batchHtml(step) : "";
            const error = step.last_error ? '<div class="dp-error">' + DocProgress.escape(step.last_error) + "</div>" : "";
            return (
                '<li class="dp-step dp-' + step.state + '">' +
                '<span class="dp-dot">' + DocProgress.ICONS[step.state] + "</span>" +
                '<div class="dp-step-body">' +
                '<div class="dp-step-line">' +
                '<span class="dp-step-label">' + DocProgress.escape(step.label) + "</span>" +
                '<span class="dp-step-count">' + DocProgress.escape(step.progress || "") + "</span>" +
                '<span class="dp-step-time">' + DocProgress.duration(step) + "</span>" +
                "</div>" +
                extra +
                error +
                "</div>" +
                "</li>"
            );
        }

        static headHtml(doc, state) {
            const progress = state.progress;
            const status = progress ? DocProgress.statusLabel(progress) : "";
            const tone = DocProgress.STATUS_TONES[status] || (status ? "red" : "gray");
            const meta = progress
                ? DocProgress.escape(progress.document.type) + " \u00B7 " + DocProgress.escape(progress.document.source)
                : "";
            return (
                '<div class="dp-head">' +
                '<div class="dp-head-text">' +
                '<div class="dp-title">Document ' + DocProgress.escape(doc) + "</div>" +
                (meta ? '<div class="dp-meta" title="' + meta + '">' + meta + "</div>" : "") +
                "</div>" +
                '<div class="dp-head-side">' +
                RunControls.html(state) +
                (status ? '<span class="dp-status dp-status-' + tone + '">' + DocProgress.escape(status) + "</span>" : "") +
                "</div>" +
                "</div>"
            );
        }

        static statusLabel(progress) {
            return progress.paused ? "Paused" : progress.status;
        }

        static stepsHtml(progress) {
            const percent = progress.steps_total ? (progress.steps_done / progress.steps_total) * 100 : 0;
            return (
                '<div class="dp-overall">' +
                '<div class="dp-overall-line"><span>Workflow steps</span><span>' +
                progress.steps_done + "/" + progress.steps_total + "</span></div>" +
                DocProgress.bar(percent, "green") +
                "</div>" +
                '<ol class="dp-steps">' + progress.steps.map(DocProgress.stepHtml).join("") + "</ol>"
            );
        }

        static html(doc, state) {
            const error = state.error ? '<div class="dp-error dp-error-box">' + DocProgress.escape(state.error) + "</div>" : "";
            const body = state.progress
                ? DocProgress.stepsHtml(state.progress)
                : state.error ? "" : '<div class="dp-loading">Loading\u2026</div>';
            const paused = state.progress && state.progress.paused ? " dp-paused" : "";
            return (
                '<div class="dp' + paused + '">' +
                DocProgress.headHtml(doc, state) +
                RunControls.errorHtml(state) +
                error +
                body +
                "</div>"
            );
        }

        static allowed() {
            return window.TEMPORAL_TASKS !== false;
        }

        static watch(url, state, render, onEnd) {
            if (!DocProgress.allowed()) {
                state.error = DocProgress.DENIED;
                render();
                return null;
            }
            const scheme = location.protocol === "https:" ? "wss://" : "ws://";
            const socket = new WebSocket(scheme + location.host + url);
            socket.onmessage = function (event) {
                const message = JSON.parse(event.data);
                if (message.error) {
                    state.error = message.error;
                } else {
                    state.progress = message;
                    state.sending = "";
                }
                render();
            };
            socket.onclose = function () {
                if (!state.progress && !state.error) {
                    state.error = "Could not open the progress connection.";
                    render();
                }
                if (onEnd) {
                    onEnd();
                }
            };
            return socket;
        }

        static open(doc, url) {
            const dark = DocActions.isDark();
            const state = { progress: null, error: "" };
            let socket = null;
            let ticking = null;

            const render = function () {
                const box = document.getElementById("doc-progress-box");
                if (box) {
                    box.innerHTML = DocProgress.html(doc, state);
                }
            };

            Swal.fire({
                html: '<div id="doc-progress-box"></div>',
                width: 640,
                showConfirmButton: false,
                showCancelButton: true,
                cancelButtonText: "Close",
                background: dark ? "#1a1d29" : "#ffffff",
                color: dark ? "#d1d5db" : "#374151",
                didOpen: function () {
                    document.getElementById("doc-progress-box").addEventListener("click", function (event) {
                        const button = RunControls.target(event);
                        if (button) {
                            RunControls.send(state, button.dataset.runAction, render);
                        }
                    });
                    render();
                    socket = DocProgress.watch(url, state, render);
                    ticking = setInterval(render, DocProgress.TICK_MS);
                },
                willClose: function () {
                    clearInterval(ticking);
                    socket.onclose = null;
                    socket.close();
                },
            });
        }

        static bind() {
            document.addEventListener("click", function (event) {
                const button = event.target.closest(DocProgress.SELECTOR);
                if (!button) {
                    return;
                }
                event.preventDefault();
                DocProgress.open(button.dataset.doc, button.dataset.url);
            });
        }
    }

    class RunControls {
        static LABELS = { pause: "Pause", resume: "Resume", cancel: "Cancel" };
        static BUSY = { pause: "Pausing\u2026", resume: "Resuming\u2026", cancel: "Canceling\u2026" };

        static html(run, key) {
            const progress = run && run.progress;
            if (!progress || !progress.control_url || progress.status !== "Running") {
                return "";
            }
            const actions = [progress.paused ? "resume" : "pause", "cancel"];
            const buttons = actions.map(function (action) {
                const label = run.sending === action ? RunControls.BUSY[action] : RunControls.LABELS[action];
                return (
                    '<button type="button" class="run-ctl-btn run-ctl-' + action + '" data-run-action="' + action + '"' +
                    (key ? ' data-run-key="' + key + '"' : "") + (run.sending ? " disabled" : "") + ">" + label + "</button>"
                );
            });
            return '<span class="run-ctl">' + buttons.join("") + "</span>";
        }

        static errorHtml(run) {
            return run && run.controlError ? '<div class="dp-error">' + DocProgress.escape(run.controlError) + "</div>" : "";
        }

        static target(event) {
            const button = event.target.closest("[data-run-action]");
            return button && !button.disabled ? button : null;
        }

        static async send(run, action, render) {
            run.sending = action;
            run.controlError = "";
            render();
            const body = new FormData();
            body.append("action", action);
            try {
                const response = await fetch(run.progress.control_url, {
                    method: "POST",
                    body: body,
                    credentials: "same-origin",
                    headers: { "X-CSRFToken": DocActions.csrfToken(), Accept: "application/json" },
                });
                const data = await response.json().catch(function () {
                    return {};
                });
                if (!response.ok) {
                    run.controlError = data.error || "Could not " + action + " (" + response.status + ").";
                    run.sending = "";
                }
            } catch (error) {
                run.controlError = error.message;
                run.sending = "";
            }
            render();
        }
    }

    class DocRowControls {
        static SELECTOR = ".doc-ctl-btn";

        static async send(button) {
            const label = button.textContent;
            button.disabled = true;
            button.textContent = RunControls.BUSY[button.dataset.action];
            const body = new FormData();
            body.append("action", button.dataset.action);
            const response = await fetch(button.dataset.url, {
                method: "POST",
                body: body,
                credentials: "same-origin",
                headers: { "X-CSRFToken": DocActions.csrfToken(), Accept: "application/json" },
            }).catch(function () {
                return null;
            });
            const data = response ? await response.json().catch(function () { return {}; }) : {};
            if (response && response.ok) {
                location.reload();
                return;
            }
            button.disabled = false;
            button.textContent = label;
            Swal.fire({ icon: "error", text: data.error || "Could not " + button.dataset.action + "." });
        }

        static bind() {
            document.addEventListener("click", function (event) {
                const button = event.target.closest(DocRowControls.SELECTOR);
                if (button && !button.disabled) {
                    event.preventDefault();
                    DocRowControls.send(button);
                }
            });
        }
    }

    window.DocActions = DocActions;
    window.DocProgress = DocProgress;
    window.RunControls = RunControls;
    DocActions.bind();
    DocProgress.bind();
    DocRowControls.bind();
})();
