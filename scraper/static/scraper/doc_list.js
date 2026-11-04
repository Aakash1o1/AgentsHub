(function () {
    "use strict";

    class Html {
        static element(tag, className, text) {
            const node = document.createElement(tag);
            if (className) {
                node.className = className;
            }
            if (text != null) {
                node.textContent = text;
            }
            return node;
        }

        static when(iso) {
            return new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
        }

        static async post(url, fields) {
            const entries = Object.entries(fields);
            let body = null;
            if (entries.length) {
                body = new FormData();
                for (const [name, value] of entries) {
                    body.append(name, value);
                }
            }
            const response = await fetch(url, {
                method: "POST",
                body: body,
                credentials: "same-origin",
                headers: { "X-CSRFToken": DocActions.csrfToken(), Accept: "application/json" },
            });
            const data = await response.json().catch(function () {
                return {};
            });
            return { ok: response.ok, status: response.status, data: data };
        }
    }

    class RunRow {
        static LABELS = { start: "Start", starting: "Starting…", cancel: "Cancel", canceling: "Canceling…" };
        static RESTARTABLE = ["Canceled", "Failed", "Terminated", "Timed out"];
        static SEGMENT_WEIGHTS = { embed_batch: 4 };
        static STEP_STATUS = { mark_waiting: "waiting", timer: "waiting", mark_extracting: "extracting", extract_text: "extracting", mark_embedding: "embedding", embed_batch: "embedding" };
        static CLOSED_PILLS = { Completed: ["completed", "completed"], Failed: ["failed", "error"], Canceled: ["canceled", "pending"] };

        constructor(doc) {
            this.doc = doc;
            this.state = doc.startable ? "start" : doc.status === "completed" ? "done" : "cancel";
            this.message = null;
            this.run = null;
            this.socket = null;
            this.build();
            this.render();
        }

        build() {
            const doc = this.doc;
            this.button = Html.element("button", "rl-btn");
            this.button.type = "button";
            this.button.addEventListener("click", this.click.bind(this));
            const top = Html.element("div", "rl-top");
            this.pill = Html.element("span", "rl-pill");
            top.append(Html.element("span", "rl-name", doc.name || "Document " + doc.id), this.pill, this.button);
            this.meta = Html.element("div", "rl-meta");
            if (doc.run_id) {
                this.meta.title = "Run ID " + doc.run_id;
            }
            this.note = Html.element("div", "rl-note");
            this.live = Html.element("div", "dp rl-live");
            this.root = Html.element("li", "rl-row");
            this.root.append(top, this.meta, this.note, this.live);
        }

        click() {
            if (this.state === "start") {
                this.start();
            } else if (this.state === "cancel") {
                this.cancel();
            }
        }

        async start() {
            this.state = "starting";
            this.message = null;
            this.render();
            const reply = await Html.post(this.doc.enqueue_url, { mode: "process_temporal" });
            this.message = { level: reply.data.level || "error", text: reply.data.message || "Could not start (" + reply.status + ")." };
            if (reply.ok && reply.data.level !== "error") {
                this.state = "cancel";
                this.watch();
            } else {
                this.state = "start";
            }
            this.render();
        }

        async cancel() {
            this.state = "canceling";
            this.message = null;
            this.render();
            const reply = await Html.post(this.doc.cancel_url, {});
            if (!reply.ok) {
                this.state = "cancel";
                this.message = { level: "error", text: reply.data.error || "Could not cancel (" + reply.status + ")." };
            } else if (!this.socket) {
                this.state = "start";
                this.message = { level: "success", text: "Cancel requested." };
            }
            this.render();
        }

        watch() {
            this.stopWatching();
            this.run = { progress: null, error: "", cancelUrl: this.doc.cancel_url, canceling: false };
            const row = this;
            this.socket = DocProgress.watch(this.doc.progress_url, this.run, this.update.bind(this), function () {
                row.socket = null;
                if (row.state === "canceling") {
                    row.state = "start";
                }
                row.render();
            });
        }

        stopWatching() {
            if (this.socket) {
                this.socket.onclose = null;
                this.socket.close();
                this.socket = null;
            }
        }

        update() {
            const status = this.run.progress ? this.run.progress.status : "Running";
            if (status === "Completed") {
                this.state = "done";
            } else if (RunRow.RESTARTABLE.includes(status)) {
                this.state = "start";
            }
            this.render();
        }

        liveHtml() {
            if (!this.run) {
                return "";
            }
            if (!this.run.progress) {
                const text = this.run.error || "Connecting to Temporal…";
                return '<div class="rl-live-line">' + DocProgress.escape(text) + "</div>";
            }
            const p = this.run.progress;
            if (p.status !== "Running") {
                const stopped = p.steps.find(function (step) {
                    return step.state === "stopped" || step.state === "failed";
                });
                const where = stopped
                    ? "stopped at " + stopped.label + (stopped.progress ? " " + stopped.progress : "")
                    : p.steps_done + "/" + p.steps_total + " steps";
                const reason = stopped && stopped.last_error ? '<div class="dp-error">' + DocProgress.escape(stopped.last_error) + "</div>" : "";
                return '<div class="rl-live-line">' + DocProgress.escape("Live: " + p.status + " · " + where) + "</div>" + reason;
            }
            const running = p.steps.find(function (step) {
                return step.state === "running";
            });
            const failed = p.steps.find(function (step) {
                return step.state === "failed";
            });
            const step = running || failed;
            const current = step ? step.label + (step.progress ? " " + step.progress : "") : "";
            const parts = ["Live: " + p.status, current, p.steps_done + "/" + p.steps_total + " steps"].filter(Boolean);
            const error = step && step.last_error ? '<div class="dp-error">' + DocProgress.escape(step.last_error) + "</div>" : "";
            return (
                '<div class="rl-live-line">' + DocProgress.escape(parts.join(" · ")) + "</div>" +
                this.segmentsHtml(p.steps) +
                error
            );
        }

        segmentsHtml(steps) {
            const segments = steps.map(function (step) {
                let fill = step.state === "done" ? 100 : 0;
                let counter = "";
                if (step.key === "embed_batch") {
                    if (step.total && step.state !== "done") {
                        fill = (step.done / step.total) * 100;
                    }
                    if (step.total != null) {
                        counter = '<span class="rl-seg-count">' + step.done + "/" + step.total + "</span>";
                    }
                }
                return (
                    '<div class="rl-seg rl-seg-' + step.state + '" style="flex-grow:' + (RunRow.SEGMENT_WEIGHTS[step.key] || 1) + '"' +
                    ' title="' + DocProgress.escape(step.label + ": " + step.state) + '">' +
                    counter +
                    '<div class="rl-seg-track"><div class="rl-seg-fill" style="width:' + fill.toFixed(1) + '%"></div></div>' +
                    "</div>"
                );
            });
            return '<div class="rl-segs">' + segments.join("") + "</div>";
        }

        livePill(progress) {
            if (progress.status === "Running") {
                const step = progress.steps.find(function (s) {
                    return s.state === "running";
                });
                return [(step && RunRow.STEP_STATUS[step.key]) || "running", "running"];
            }
            return RunRow.CLOSED_PILLS[progress.status] || [progress.status.toLowerCase(), "error"];
        }

        render() {
            const doc = this.doc;
            const progress = this.run && this.run.progress;
            const pill = progress ? this.livePill(progress) : [doc.status, doc.status];
            this.pill.textContent = pill[0];
            this.pill.className = "rl-pill rl-pill-" + pill[1];
            const run = doc.run_id ? " (" + doc.run_id.slice(0, 8) + "…)" : "";
            this.meta.textContent = "#" + doc.id + " · " + doc.workflow_id + " · " + doc.source_type +
                " · last run: " + (progress ? progress.status : doc.last_run) + run;
            const done = this.state === "done";
            this.button.hidden = done;
            this.button.textContent = RunRow.LABELS[this.state] || "";
            this.button.disabled = this.state === "starting" || this.state === "canceling";
            this.button.className = "rl-btn rl-btn-" + (this.state.startsWith("cancel") ? "cancel" : "start");
            this.note.textContent = this.message ? this.message.text : "";
            this.note.className = "rl-note" + (this.message ? " rl-note-" + this.message.level : "");
            this.live.innerHTML = this.liveHtml();
        }
    }

    class RunsCard {
        static draw(bubble, artifact) {
            const card = Html.element("div", "rl-card");
            const head = Html.element("div", "rl-head");
            head.append(
                Html.element("span", "rl-title", artifact.title),
                Html.element("span", "rl-count", String(artifact.documents.length))
            );
            const list = Html.element("ul", "rl-rows");
            const rows = artifact.documents.map(function (doc) {
                const row = new RunRow(doc);
                list.appendChild(row.root);
                return row;
            });
            const more = artifact.truncated ? " · only the newest " + artifact.documents.length + " are shown" : "";
            const foot = Html.element(
                "div",
                "rl-foot",
                "Rows are a snapshot as of " + Html.when(artifact.fetched_at) + more + ". Running rows show their current progress; ask again for a fresh list."
            );
            card.append(head, list, foot);
            bubble.appendChild(card);
            rows.forEach(function (row) {
                if (row.state === "cancel") {
                    row.watch();
                }
            });
        }
    }

    class AddDocumentForm {
        constructor(root) {
            this.root = root;
            this.toggle = root.querySelector("[data-link-toggle]");
            this.pop = root.querySelector(".rc-linkpop");
            this.form = root.querySelector(".rc-adddoc-form");
            this.input = this.form.querySelector("[name=url]");
            this.submit = this.form.querySelector("[type=submit]");
            this.result = root.querySelector(".rc-adddoc-result");
            this.bind();
        }

        bind() {
            const self = this;
            this.toggle.addEventListener("click", function () {
                if (self.pop.hidden) {
                    self.open();
                } else {
                    self.close();
                }
            });
            document.addEventListener("click", function (event) {
                if (!self.pop.hidden && !self.pop.contains(event.target) && !self.toggle.contains(event.target)) {
                    self.close();
                }
            });
            this.form.querySelector("[data-close]").addEventListener("click", this.close.bind(this));
            this.input.addEventListener("keydown", function (event) {
                if (event.key === "Escape") {
                    self.close();
                }
            });
            this.form.addEventListener("submit", function (event) {
                event.preventDefault();
                self.send();
            });
        }

        open() {
            this.result.hidden = true;
            this.pop.hidden = false;
            this.toggle.classList.add("rc-on");
            this.input.focus();
        }

        close() {
            this.pop.hidden = true;
            this.toggle.classList.remove("rc-on");
            this.input.value = "";
            this.result.hidden = true;
        }

        show(level, text) {
            this.result.hidden = false;
            this.result.className = "rc-adddoc-result rc-adddoc-" + level;
            this.result.textContent = text;
            this.result.title = text;
        }

        async send() {
            this.submit.disabled = true;
            this.show("info", "Adding…");
            try {
                const reply = await Html.post(this.root.dataset.addUrl, {
                    url: this.input.value,
                    chat_id: this.root.dataset.chatId,
                });
                if (reply.ok) {
                    this.close();
                } else {
                    this.show(reply.data.level || "error", reply.data.message || "Could not add the link (" + reply.status + ").");
                }
            } catch (error) {
                this.show("error", error.message);
            }
            this.submit.disabled = false;
        }

        static bind() {
            const root = document.querySelector(".rc-adddoc");
            if (root) {
                new AddDocumentForm(root);
            }
        }
    }

    window.RunsCard = RunsCard;
    AddDocumentForm.bind();
})();
