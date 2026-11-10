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
            const progressUrl = button.dataset.progressUrl;
            const dark = DocActions.isDark();
            const progressHtml = progressUrl
                ? '<button type="button" class="doc-run-btn">Last Temporal run</button>'
                : "";

            Swal.fire({
                title: "Document #" + button.dataset.doc,
                html: DocActions.optionsHtml(modes) + progressHtml,
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
                    const run = popup.querySelector(".doc-run-btn");
                    if (run) {
                        run.addEventListener("click", function () {
                            DocProgress.open(button.dataset.doc, progressUrl, button.dataset.cancelUrl);
                        });
                    }
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
        static ICONS = { done: "\u2713", running: "", failed: "\u2715", stopped: "\u25A0", pending: "" };
        static STATUS_TONES = { Running: "blue", Completed: "green" };

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

        static cancelHtml(state) {
            if (!state.cancelUrl || !state.progress) {
                return "";
            }
            const running = state.progress.status === "Running";
            let label = "Cancel";
            if (state.progress.status === "Canceled") {
                label = "Canceled";
            } else if (state.canceling && running) {
                label = "Canceling\u2026";
            }
            const disabled = !running || state.canceling ? " disabled" : "";
            return '<button type="button" class="dp-cancel"' + disabled + ">" + label + "</button>";
        }

        static headHtml(doc, state) {
            const progress = state.progress;
            const status = progress ? progress.status : "";
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
                DocProgress.cancelHtml(state) +
                (status ? '<span class="dp-status dp-status-' + tone + '">' + DocProgress.escape(status) + "</span>" : "") +
                "</div>" +
                "</div>"
            );
        }

        static cancel(state, render) {
            state.canceling = true;
            render();
            fetch(state.cancelUrl, {
                method: "POST",
                headers: { "X-CSRFToken": DocActions.csrfToken() },
                credentials: "same-origin",
            })
                .then(function (response) {
                    return response.json().then(function (body) {
                        if (!response.ok) {
                            throw new Error(body.error || "Could not cancel.");
                        }
                    });
                })
                .catch(function (err) {
                    state.canceling = false;
                    state.error = err.message;
                    render();
                });
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
            return (
                '<div class="dp">' +
                DocProgress.headHtml(doc, state) +
                error +
                body +
                "</div>"
            );
        }

        static watch(url, state, render, onEnd) {
            const scheme = location.protocol === "https:" ? "wss://" : "ws://";
            const socket = new WebSocket(scheme + location.host + url);
            socket.onmessage = function (event) {
                const message = JSON.parse(event.data);
                if (message.error) {
                    state.error = message.error;
                } else {
                    state.progress = message;
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

        static open(doc, url, cancelUrl) {
            const dark = DocActions.isDark();
            const state = { progress: null, error: "", cancelUrl: cancelUrl, canceling: false };
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
                        const button = event.target.closest(".dp-cancel");
                        if (button && !button.disabled) {
                            DocProgress.cancel(state, render);
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
                DocProgress.open(button.dataset.doc, button.dataset.url, button.dataset.cancelUrl);
            });
        }
    }

    window.DocActions = DocActions;
    window.DocProgress = DocProgress;
    DocActions.bind();
    DocProgress.bind();
})();
