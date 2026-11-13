(function () {
    "use strict";

    class SummaryCard {
        static PILLS = { Running: "running", Completed: "completed", Failed: "error", Canceled: "pending" };
        static SEGMENT_WEIGHTS = { summarize_piece: 4 };

        static element(tag, className, text) {
            const node = document.createElement(tag);
            node.className = className;
            if (text != null) {
                node.textContent = text;
            }
            return node;
        }

        static draw(bubble, artifact) {
            new SummaryCard(bubble, artifact);
        }

        constructor(bubble, artifact) {
            this.artifact = artifact;
            this.run = { progress: null, error: "" };
            const card = SummaryCard.element("div", "rl-card");
            const head = SummaryCard.element("div", "rl-head");
            this.pill = SummaryCard.element("span", "rl-pill");
            head.append(SummaryCard.element("span", "rl-title rl-name", artifact.title), this.pill);
            const row = SummaryCard.element("div", "rl-row");
            const meta = SummaryCard.element("div", "rl-meta", artifact.workflow_id + " · run " + artifact.run_id.slice(0, 8) + "…");
            meta.title = "Run ID " + artifact.run_id;
            this.live = SummaryCard.element("div", "dp rl-live");
            this.live.addEventListener("click", this.control.bind(this));
            this.note = SummaryCard.element("div", "rl-note");
            row.append(meta, this.live, this.note);
            card.append(head, row);
            bubble.appendChild(card);
            this.render();
            DocProgress.watch(artifact.progress_url, this.run, this.render.bind(this));
        }

        control(event) {
            const button = RunControls.target(event);
            if (button) {
                RunControls.send(this.run, button.dataset.runAction, this.render.bind(this));
            }
        }

        segmentsHtml(steps) {
            const segments = steps.map(function (step) {
                let fill = step.state === "done" ? 100 : 0;
                let counter = "";
                if (step.key === "summarize_piece" && step.total != null) {
                    if (step.total && step.state !== "done") {
                        fill = (step.done / step.total) * 100;
                    }
                    counter = '<span class="rl-seg-count">' + step.done + "/" + step.total + "</span>";
                }
                return (
                    '<div class="rl-seg rl-seg-' + step.state + '" style="flex-grow:' + (SummaryCard.SEGMENT_WEIGHTS[step.key] || 1) + '"' +
                    ' title="' + DocProgress.escape(step.label + ": " + step.state) + '">' +
                    counter +
                    '<div class="rl-seg-track"><div class="rl-seg-fill" style="width:' + fill.toFixed(1) + '%"></div></div>' +
                    "</div>"
                );
            });
            return '<div class="rl-segs">' + segments.join("") + "</div>";
        }

        liveHtml() {
            const p = this.run.progress;
            if (!p) {
                return '<div class="rl-live-line">' + DocProgress.escape(this.run.error || "Connecting to Temporal…") + "</div>";
            }
            const step = p.steps.find(function (s) {
                return s.state === "running" || s.state === "failed" || s.state === "stopped";
            });
            const current = step ? step.label + (step.progress ? " " + step.progress : "") : "";
            const parts = ["Live: " + DocProgress.statusLabel(p), current, p.steps_done + "/" + p.steps_total + " steps"].filter(Boolean);
            const error = step && step.last_error ? '<div class="dp-error">' + DocProgress.escape(step.last_error) + "</div>" : "";
            return '<div class="rl-live-line rl-live-head"><span>' + DocProgress.escape(parts.join(" · ")) + "</span>" +
                RunControls.html(this.run) + "</div>" + RunControls.errorHtml(this.run) + this.segmentsHtml(p.steps) + error;
        }

        render() {
            const p = this.run.progress;
            const status = p ? p.status : "Running";
            const paused = Boolean(p && p.paused);
            this.pill.textContent = paused ? "paused" : status.toLowerCase();
            this.pill.className = "rl-pill rl-pill-" + (paused ? "pending" : SummaryCard.PILLS[status] || "error");
            this.live.innerHTML = this.liveHtml();
            this.live.classList.toggle("dp-paused", paused);
            const done = status === "Completed";
            this.note.textContent = done ? "Done: the summary is posted in the chat." : "";
            this.note.className = "rl-note" + (done ? " rl-note-success" : "");
        }
    }

    window.SummaryCard = SummaryCard;
})();
