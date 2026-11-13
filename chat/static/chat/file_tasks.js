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

        static ago(iso) {
            const minutes = Math.max(0, Math.floor((Date.now() - new Date(iso)) / 60000));
            if (minutes < 1) {
                return "just now";
            }
            if (minutes < 60) {
                return minutes + " min ago";
            }
            const hours = Math.floor(minutes / 60);
            if (hours < 24) {
                return hours + (hours === 1 ? " hour ago" : " hours ago");
            }
            const days = Math.floor(hours / 24);
            return days + (days === 1 ? " day ago" : " days ago");
        }
    }

    class TaskRow {
        static JOBS = { summary: "Summary", kb: "Knowledge base" };
        static ACTIONS = { summary: "Summarise", add: "Add to KB", start: "Start" };
        static WEIGHTS = { embed_batch: 4, summarize_piece: 4 };
        static CLOSED = { Completed: "done", Running: "running" };

        constructor(task, card) {
            this.card = card;
            this.task = task;
            this.tab = task.tab;
            this.starting = false;
            this.run = null;
            this.socket = null;
            this.root = Html.element("div", "ft-row");
            const name = Html.element("div", "ft-name");
            name.title = task.name;
            const text = Html.element("div", "ft-text");
            const chat = Html.element("a", "ft-chat", task.chat);
            chat.href = "/?chat=" + task.chat_id;
            chat.title = task.chat;
            text.append(Html.element("span", "ft-label", task.name), chat);
            this.badge = Html.element("span", "ft-badge ft-badge-" + task.job, TaskRow.JOBS[task.job]);
            name.append(
                Html.element("span", "material-symbols-outlined ft-icon", "description"),
                text,
                this.badge
            );
            this.info = Html.element("div", "ft-info");
            this.when = Html.element("div", "ft-when");
            this.button = Html.element("button", "rl-btn rl-btn-start");
            this.button.type = "button";
            this.button.addEventListener("click", this.click.bind(this));
            this.actions = Html.element("div", "ft-actions");
            this.actions.appendChild(this.button);
            this.progress = Html.element("div", "ft-progress dp");
            this.progress.addEventListener("click", this.control.bind(this));
            this.root.append(name, this.info, this.when, this.actions, this.progress);
            this.watchIfRunning();
            this.render();
        }

        live() {
            return this.tab === "running" && this.run !== null;
        }

        watchIfRunning() {
            if (this.tab === "running" && this.task.progress_url && !this.socket) {
                this.run = { progress: null, error: "" };
                this.socket = DocProgress.watch(this.task.progress_url, this.run, this.update.bind(this), this.ended.bind(this));
            }
        }

        stop() {
            if (this.socket) {
                this.socket.onclose = null;
                this.socket.close();
                this.socket = null;
            }
        }

        ended() {
            this.socket = null;
        }

        update() {
            const progress = this.run.progress;
            if (progress && progress.status !== "Running") {
                this.tab = TaskRow.CLOSED[progress.status] || "failed";
                this.task.finished_at = new Date().toISOString();
                this.task.reason = this.tab === "failed" ? progress.status.toLowerCase() : "";
            }
            this.render();
        }

        sync(task) {
            if (this.starting || (this.live() && this.socket)) {
                return;
            }
            this.task = task;
            this.tab = task.tab;
            this.watchIfRunning();
            this.render();
        }

        async click() {
            let body = null;
            if (this.task.action === "start") {
                body = new FormData();
                body.append("mode", "process_temporal");
            }
            this.starting = true;
            this.task.reason = "";
            this.render();
            const response = await fetch(this.task.action_url, {
                method: "POST",
                body: body,
                credentials: "same-origin",
                headers: { "X-CSRFToken": DocActions.csrfToken(), Accept: "application/json" },
            }).catch(function () {
                return null;
            });
            const data = response ? await response.json().catch(function () { return {}; }) : {};
            this.starting = false;
            if (response && response.ok && data.level === "success") {
                this.stop();
                this.tab = "running";
                this.card.active = "running";
                this.task.progress_url = data.progress_url || this.task.progress_url || "";
                this.watchIfRunning();
                this.render();
                return;
            }
            if (!response || !response.ok || data.level === "error") {
                this.tab = "failed";
                this.task.reason = data.message || "Could not start" + (response ? " (" + response.status + ")" : "") + ".";
                this.render();
                return;
            }
            this.card.reload();
        }

        control(event) {
            const button = RunControls.target(event);
            if (button && this.run) {
                RunControls.send(this.run, button.dataset.runAction, this.render.bind(this));
            }
        }

        paused() {
            return Boolean(this.live() && this.run.progress && this.run.progress.paused);
        }

        status() {
            if (this.starting) {
                return ["starting", "Starting…"];
            }
            if (this.tab === "running") {
                return this.paused() ? ["paused", "Paused"] : ["running", "Running"];
            }
            if (this.tab === "failed") {
                const reason = this.task.reason || "failed";
                return ["failed", reason.charAt(0).toUpperCase() + reason.slice(1)];
            }
            if (this.tab === "done") {
                return ["done", "Done"];
            }
            return ["todo", "Not started"];
        }

        renderInfo() {
            const status = this.status();
            const finished = this.task.finished_at && (this.tab === "failed" || this.tab === "done");
            this.info.replaceChildren(Html.element("span", "ft-status ft-status-" + status[0], status[1]));
            this.when.textContent = finished ? Html.ago(this.task.finished_at) : "—";
            this.when.title = finished ? new Date(this.task.finished_at).toLocaleString() : "";
            this.badge.hidden = this.tab !== "running";
        }

        render() {
            this.renderInfo();
            const label = this.tab === "failed" ? "Retry" : TaskRow.ACTIONS[this.task.action];
            this.button.textContent = this.starting ? "Starting…" : label;
            this.button.hidden = !this.starting && (this.tab === "running" || this.tab === "done");
            this.button.disabled = this.starting;
            this.progress.innerHTML = this.progressHtml();
            this.card.refresh();
        }

        progressHtml() {
            if (!this.live()) {
                return "";
            }
            const p = this.run.progress;
            if (!p) {
                return '<div class="ft-progress-item"><div class="rl-live-line">' +
                    DocProgress.escape(this.run.error || "Connecting to Temporal…") + "</div></div>";
            }
            const step = p.steps.find(function (s) {
                return s.state === "running" || s.state === "failed";
            });
            const current = step ? step.label + (step.progress ? " " + step.progress : "") : "";
            const line = [p.paused ? "Paused" : current, p.steps_done + "/" + p.steps_total + " steps"].filter(Boolean).join(" · ");
            const error = step && step.last_error ? '<div class="dp-error">' + DocProgress.escape(step.last_error) + "</div>" : "";
            return '<div class="ft-progress-item' + (p.paused ? " dp-paused" : "") + '"><div class="rl-live-line rl-live-head"><span>' +
                DocProgress.escape(line) + "</span>" + RunControls.html(this.run, this.task.key) + "</div>" +
                RunControls.errorHtml(this.run) + TaskRow.segmentsHtml(p.steps) + error + "</div>";
        }

        static segmentsHtml(steps) {
            const segments = steps.map(function (step) {
                let fill = step.state === "done" ? 100 : 0;
                let counter = "";
                if (step.total != null) {
                    if (step.total && step.state !== "done") {
                        fill = (step.done / step.total) * 100;
                    }
                    counter = '<span class="rl-seg-count">' + step.done + "/" + step.total + "</span>";
                }
                return (
                    '<div class="rl-seg rl-seg-' + step.state + '" style="flex-grow:' + (TaskRow.WEIGHTS[step.key] || 1) + '"' +
                    ' title="' + DocProgress.escape(step.label + ": " + step.state) + '">' + counter +
                    '<div class="rl-seg-track"><div class="rl-seg-fill" style="width:' + fill.toFixed(1) + '%"></div></div></div>'
                );
            });
            return '<div class="rl-segs">' + segments.join("") + "</div>";
        }
    }

    class TasksCard {
        static TABS = [
            { key: "running", label: "Running" },
            { key: "failed", label: "Failed" },
            { key: "todo", label: "To do" },
            { key: "done", label: "Done" },
        ];
        static EMPTY = {
            running: "Nothing is running right now.",
            failed: "Nothing has failed.",
            todo: "Nothing is left to do in this chat.",
            done: "Nothing has finished in the last 7 days.",
        };

        static URL = "/api/v1/chat/tasks";

        static draw(bubble, artifact) {
            new TasksCard(bubble, artifact);
        }

        constructor(bubble, artifact) {
            if (!DocProgress.allowed()) {
                const card = Html.element("div", "rl-card ft-card");
                card.appendChild(Html.element("div", "ft-empty", "You don't have access to Temporal tasks."));
                bubble.appendChild(card);
                return;
            }
            this.active = artifact.tab || "running";
            this.chatId = artifact.chat_id || this.openChatId();
            this.rows = [];
            this.groups = {};
            this.tabs = {};
            this.ready = false;
            bubble.classList.add("ft-wide");
            this.root = Html.element("div", "rl-card ft-card ft-show-progress");
            this.root.append(this.buildHead(), this.buildTable());
            bubble.appendChild(this.root);
            const card = this;
            (artifact.tasks || []).forEach(function (task) {
                card.add(task);
            });
            this.ready = true;
            this.refresh();
            this.reload();
        }

        openChatId() {
            const messages = document.querySelector(".rc-messages[data-chat-id]");
            return messages ? messages.dataset.chatId : "";
        }

        add(task) {
            const row = new TaskRow(task, this);
            this.rows.push(row);
            this.groups[task.file_id] = this.groups[task.file_id] || {};
            this.groups[task.file_id][task.job] = row;
            this.table.insertBefore(row.root, this.empty);
        }

        async reload() {
            if (this.loading) {
                return;
            }
            this.loading = true;
            this.reloadButton.disabled = true;
            const response = await fetch(TasksCard.URL + "?chat=" + encodeURIComponent(this.chatId || ""), {
                credentials: "same-origin",
                headers: { Accept: "application/json" },
            }).catch(function () {
                return null;
            });
            this.loading = false;
            this.reloadButton.disabled = false;
            if (!response || !response.ok) {
                return;
            }
            const data = await response.json();
            const fresh = {};
            data.tasks.forEach(function (task) {
                fresh[task.key] = task;
            });
            const card = this;
            this.rows = this.rows.filter(function (row) {
                const task = fresh[row.task.key];
                delete fresh[row.task.key];
                if (!task) {
                    delete card.groups[row.task.file_id][row.task.job];
                    row.stop();
                    row.root.remove();
                    return false;
                }
                row.sync(task);
                return true;
            });
            Object.values(fresh).forEach(function (task) {
                card.add(task);
            });
            this.refresh();
        }

        buildHead() {
            const head = Html.element("div", "rl-head ft-head");
            const bar = Html.element("div", "ft-tabs");
            const card = this;
            TasksCard.TABS.forEach(function (tab) {
                const button = Html.element("button", "ft-tab");
                button.type = "button";
                const count = Html.element("span", "ft-tab-count", "0");
                button.append(Html.element("span", "", tab.label), count);
                button.addEventListener("click", function () {
                    card.active = tab.key;
                    card.refresh();
                });
                card.tabs[tab.key] = { button: button, count: count };
                bar.appendChild(button);
            });
            const tools = Html.element("div", "ft-head-tools");
            this.reloadButton = Html.element("button", "ft-reload");
            this.reloadButton.type = "button";
            this.reloadButton.title = "Refresh";
            this.reloadButton.appendChild(Html.element("span", "material-symbols-outlined", "refresh"));
            this.reloadButton.addEventListener("click", this.reload.bind(this));
            tools.append(this.reloadButton);
            head.append(bar, tools);
            return head;
        }

        buildTable() {
            this.table = Html.element("div", "ft-table");
            const header = Html.element("div", "ft-row ft-header");
            ["Task", "Status", "Finished", "Action"].forEach(function (title) {
                header.appendChild(Html.element("div", "", title));
            });
            this.empty = Html.element("div", "ft-empty");
            this.table.append(header, this.empty);
            return this.table;
        }

        ordered() {
            if (this.active !== "done") {
                return this.rows;
            }
            return this.rows.slice().sort(function (a, b) {
                return (b.task.finished_at || "").localeCompare(a.task.finished_at || "");
            });
        }

        merged(row) {
            const kb = this.groups[row.task.file_id].kb;
            return row.task.job === "summary" && row.tab === "todo" && Boolean(kb) && kb.tab === "todo";
        }

        placeButtons() {
            const card = this;
            Object.values(this.groups).forEach(function (group) {
                if (!group.summary) {
                    return;
                }
                const home = card.merged(group.summary) ? group.kb.actions : group.summary.actions;
                if (group.summary.button.parentNode !== home) {
                    home.appendChild(group.summary.button);
                }
            });
        }

        refresh() {
            if (!this.ready) {
                return;
            }
            const card = this;
            this.placeButtons();
            TasksCard.TABS.forEach(function (tab) {
                const parts = card.tabs[tab.key];
                parts.count.textContent = String(card.rows.filter(function (row) {
                    return row.tab === tab.key && !card.merged(row);
                }).length);
                parts.button.classList.toggle("ft-tab-on", tab.key === card.active);
            });
            let shown = 0;
            this.ordered().forEach(function (row) {
                const visible = row.tab === card.active && !card.merged(row);
                row.root.hidden = !visible;
                shown += visible ? 1 : 0;
                card.table.insertBefore(row.root, card.empty);
            });
            this.empty.hidden = shown > 0;
            this.empty.textContent = TasksCard.EMPTY[this.active];
        }
    }

    window.TasksCard = TasksCard;
})();
