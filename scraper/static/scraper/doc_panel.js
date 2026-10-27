(function () {
    "use strict";

    class DocListCard {
        static ACTIVE = "dl-row-active";

        static element(tag, className, text) {
            const node = document.createElement(tag);
            node.className = className;
            if (text != null) {
                node.textContent = text;
            }
            return node;
        }

        static when(iso) {
            return new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
        }

        static row(doc) {
            const button = DocListCard.element("button", "dl-row");
            button.type = "button";
            button.dataset.docId = doc.id;
            button.append(
                DocListCard.element("span", "dl-name", doc.name || "Document " + doc.id),
                DocListCard.element("span", "dl-type", doc.source_type),
                DocListCard.element("span", "dl-pill dl-pill-" + doc.status, doc.status)
            );
            button.addEventListener("click", function () {
                DocListCard.markActive(doc.id);
                DocPanel.open(doc.id);
            });
            const item = DocListCard.element("li", "");
            item.appendChild(button);
            return item;
        }

        static markActive(docId) {
            document.querySelectorAll(".dl-row").forEach(function (row) {
                row.classList.toggle(DocListCard.ACTIVE, docId != null && row.dataset.docId === String(docId));
            });
        }

        static draw(bubble, artifact) {
            const card = DocListCard.element("div", "dl-card");
            const head = DocListCard.element("div", "dl-head");
            head.append(
                DocListCard.element("span", "dl-title", artifact.title),
                DocListCard.element("span", "dl-count", String(artifact.documents.length))
            );
            const rows = DocListCard.element("ul", "dl-rows");
            artifact.documents.forEach(function (doc) {
                rows.appendChild(DocListCard.row(doc));
            });
            const more = artifact.truncated ? " · only the newest " + artifact.documents.length + " are shown" : "";
            const foot = DocListCard.element(
                "div",
                "dl-foot",
                "Snapshot as of " + DocListCard.when(artifact.fetched_at) + more + ". Click a document for its live state."
            );
            card.append(head, rows, foot);
            bubble.appendChild(card);
        }
    }

    class DocPanel {
        static TICK_MS = 1000;
        static STATUS_TONES = { pending: "gray", error: "red", completed: "green" };
        static current = null;

        static root() {
            return document.querySelector(".rc-panel");
        }

        static open(docId) {
            if (DocPanel.current) {
                DocPanel.current.close();
            }
            DocPanel.current = new DocPanel(docId);
            DocPanel.current.load(true);
        }

        static bind() {
            const root = DocPanel.root();
            if (!root) {
                return;
            }
            root.addEventListener("click", function (event) {
                const panel = DocPanel.current;
                if (!panel) {
                    return;
                }
                if (event.target.closest(".dpn-close")) {
                    panel.close();
                    DocListCard.markActive(null);
                } else if (event.target.closest(".dpn-process") && !panel.starting) {
                    panel.process();
                } else {
                    const cancel = event.target.closest(".dp-cancel");
                    if (cancel && !cancel.disabled) {
                        DocProgress.cancel(panel.run, panel.render.bind(panel));
                    }
                }
            });
        }

        constructor(docId) {
            this.docId = docId;
            this.detail = null;
            this.loadError = "";
            this.notice = null;
            this.starting = false;
            this.closed = false;
            this.socket = null;
            this.ticking = null;
            this.run = { progress: null, error: "", cancelUrl: "", canceling: false };
            DocPanel.root().hidden = false;
            this.render();
        }

        detailUrl() {
            return DocPanel.root().dataset.detailUrl.replace("/0/", "/" + this.docId + "/");
        }

        async load(watch) {
            try {
                const response = await fetch(this.detailUrl(), { credentials: "same-origin" });
                const data = await response.json();
                if (this.closed) {
                    return;
                }
                if (!response.ok) {
                    throw new Error(data.error || "Could not load the document.");
                }
                this.detail = data;
                this.loadError = "";
                this.run.cancelUrl = data.cancel_url;
                if (watch && data.has_run) {
                    this.watch();
                }
            } catch (error) {
                if (this.closed) {
                    return;
                }
                this.loadError = error.message;
            }
            this.render();
        }

        watch() {
            this.stopWatching();
            const panel = this;
            this.run = { progress: null, error: "", cancelUrl: this.detail.cancel_url, canceling: false };
            this.socket = DocProgress.watch(this.detail.progress_url, this.run, this.render.bind(this), function () {
                clearInterval(panel.ticking);
                if (!panel.closed) {
                    panel.load(false);
                }
            });
            this.ticking = setInterval(this.render.bind(this), DocPanel.TICK_MS);
        }

        stopWatching() {
            clearInterval(this.ticking);
            if (this.socket) {
                this.socket.onclose = null;
                this.socket.close();
                this.socket = null;
            }
        }

        async process() {
            this.starting = true;
            this.notice = null;
            this.render();
            const body = new FormData();
            body.append("mode", "process_temporal");
            try {
                const response = await fetch(this.detail.enqueue_url, {
                    method: "POST",
                    body: body,
                    credentials: "same-origin",
                    headers: { "X-CSRFToken": DocActions.csrfToken(), Accept: "application/json" },
                });
                const data = await response.json();
                this.notice = { level: data.level || "error", message: data.message || "Could not start processing." };
            } catch (error) {
                this.notice = { level: "error", message: error.message };
            }
            this.starting = false;
            if (!this.closed) {
                await this.load(true);
            }
        }

        close() {
            this.closed = true;
            this.stopWatching();
            DocPanel.root().hidden = true;
            DocPanel.root().replaceChildren();
            if (DocPanel.current === this) {
                DocPanel.current = null;
            }
        }

        field(label, valueHtml) {
            return "<dt>" + label + "</dt><dd>" + valueHtml + "</dd>";
        }

        detailsHtml(d) {
            const tone = DocPanel.STATUS_TONES[d.status] || "blue";
            const added = d.created_at ? DocListCard.when(d.created_at) : "";
            const by = d.created_by ? " by " + DocProgress.escape(d.created_by) : "";
            return (
                '<dl class="dpn-fields">' +
                this.field("Type", DocProgress.escape(d.source_type)) +
                this.field("Source", '<span class="dpn-source" title="' + DocProgress.escape(d.source) + '">' + DocProgress.escape(d.source) + "</span>") +
                this.field("Status", '<span class="dp-status dp-status-' + tone + '">' + DocProgress.escape(d.status_label) + "</span>") +
                this.field("Chunks", String(d.chunks)) +
                this.field("Added", DocProgress.escape(added) + by) +
                "</dl>" +
                (d.error ? '<div class="dp-error dp-error-box">' + DocProgress.escape(d.error) + "</div>" : "")
            );
        }

        actionsHtml(d) {
            let html = "";
            if (d.unprocessed) {
                const label = this.starting ? "Starting…" : "Process with Temporal";
                html += '<button type="button" class="rc-btn rc-btn-primary dpn-process"' + (this.starting ? " disabled" : "") + ">" + label + "</button>";
            }
            if (d.temporal_url) {
                html += '<a class="rc-link dpn-temporal" href="' + DocProgress.escape(d.temporal_url) + '" target="_blank" rel="noopener">Open in Temporal UI ↗</a>';
            }
            return html ? '<div class="dpn-actions">' + html + "</div>" : "";
        }

        noticeHtml() {
            if (!this.notice) {
                return "";
            }
            return '<div class="dpn-notice dpn-notice-' + this.notice.level + '">' + DocProgress.escape(this.notice.message) + "</div>";
        }

        runHtml(d) {
            if (!d.has_run) {
                return "";
            }
            const progress = this.run.progress;
            const status = progress ? progress.status : "";
            const tone = DocProgress.STATUS_TONES[status] || (status ? "red" : "gray");
            const pill = status ? '<span class="dp-status dp-status-' + tone + '">' + DocProgress.escape(status) + "</span>" : "";
            const body = progress
                ? DocProgress.stepsHtml(progress)
                : this.run.error ? "" : '<div class="dp-loading">Loading Temporal run…</div>';
            const error = this.run.error ? '<div class="dp-error dp-error-box">' + DocProgress.escape(this.run.error) + "</div>" : "";
            return (
                '<div class="dp dpn-run">' +
                '<div class="dpn-run-head"><span class="dpn-section">Temporal run</span>' +
                '<span class="dp-head-side">' + DocProgress.cancelHtml(this.run) + pill + "</span></div>" +
                error +
                body +
                "</div>"
            );
        }

        render() {
            if (this.closed) {
                return;
            }
            const d = this.detail;
            const title = d ? d.name || "Document " + d.id : "Document " + this.docId;
            let body;
            if (this.loadError) {
                body = '<div class="dp-error dp-error-box">' + DocProgress.escape(this.loadError) + "</div>";
            } else if (!d) {
                body = '<div class="dp-loading">Loading…</div>';
            } else {
                body = this.detailsHtml(d) + this.noticeHtml() + this.actionsHtml(d) + this.runHtml(d);
            }
            DocPanel.root().innerHTML =
                '<div class="dpn-head">' +
                '<div class="dpn-head-text"><div class="dpn-kicker">Live state · #' + DocProgress.escape(this.docId) + "</div>" +
                '<div class="dpn-title" title="' + DocProgress.escape(title) + '">' + DocProgress.escape(title) + "</div></div>" +
                '<button type="button" class="dpn-close" aria-label="Close panel">✕</button>' +
                "</div>" +
                '<div class="dpn-body">' + body + "</div>";
        }
    }

    window.DocListCard = DocListCard;
    window.DocPanel = DocPanel;
    DocPanel.bind();
})();
