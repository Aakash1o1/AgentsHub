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

        static byId(id) {
            return document.getElementById(id);
        }

        static json(id) {
            return JSON.parse(Html.byId(id).textContent);
        }
    }

    class Workflow {
        static START = "start";
        static STEP = "step";
        static START_ID = "start-1";
        static STEP_ID = "step-1";
        static EDGE_ID = "edge-1";
        static START_POSITION = { x: 40, y: 120 };
        static STEP_POSITION = { x: 320, y: 120 };

        static number(value, fallback) {
            return typeof value === "number" && Number.isFinite(value) ? value : fallback;
        }

        static position(node, fallback) {
            const position = node.position || {};
            return { x: Workflow.number(position.x, fallback.x), y: Workflow.number(position.y, fallback.y) };
        }

        static normalise(json, known) {
            const nodes = json && Array.isArray(json.nodes) ? json.nodes : [];
            const find = (type) => nodes.find((item) => item && item.type === type) || {};
            const start = find(Workflow.START);
            const step = find(Workflow.STEP);
            const data = step.data || {};
            const tools = Array.isArray(data.tools) ? data.tools : [];
            return {
                nodes: [
                    {
                        id: Workflow.START_ID,
                        type: Workflow.START,
                        position: Workflow.position(start, Workflow.START_POSITION),
                        data: {},
                    },
                    {
                        id: Workflow.STEP_ID,
                        type: Workflow.STEP,
                        position: Workflow.position(step, Workflow.STEP_POSITION),
                        data: {
                            name: typeof data.name === "string" ? data.name : "",
                            tools: [...new Set(tools.filter((name) => known.has(name)))],
                            force_tool_call: data.force_tool_call === true,
                        },
                    },
                ],
                edges: [{ id: Workflow.EDGE_ID, source: Workflow.START_ID, target: Workflow.STEP_ID, data: {} }],
            };
        }

        static start(json) {
            return json.nodes[0];
        }

        static step(json) {
            return json.nodes[1];
        }
    }

    class StartNode {
        constructor(content) {
            const head = Html.element("div", "ab-step-head ab-start-head");
            head.append(Html.element("span", "ab-badge ab-badge-start", "START"), Html.element("span", "ab-node-title", "Start"));
            content.append(head, Html.element("div", "ab-node-sub ab-start-note", "Every message begins here"));
        }
    }

    class StepNode {
        constructor(builder, content) {
            this.builder = builder;
            this.title = Html.element("span", "ab-node-title");
            this.notes = Html.element("span", "ab-node-sub");
            const head = Html.element("div", "ab-step-head");
            head.append(Html.element("span", "ab-badge", "STEP"), this.title, this.notes);

            this.description = Html.element("textarea", "ab-step-desc");
            this.description.rows = 5;
            this.description.maxLength = 255;
            this.description.placeholder = "What this agent is for. The router reads this to pick an agent.";
            this.description.addEventListener("input", () => builder.changeDescription(this.description.value));

            this.prompt = Html.element("input", "ab-step-prompt");
            this.prompt.type = "text";
            this.prompt.setAttribute("list", "promptOptions");
            this.prompt.placeholder = "Langfuse prompt name";
            this.prompt.autocomplete = "off";
            this.prompt.addEventListener("input", () => builder.changeStep({ name: this.prompt.value }));

            this.toolsLabel = Html.element("div", "ab-field-label");
            this.chips = Html.element("div", "ab-chips");
            this.chips.addEventListener("click", (event) => {
                const remove = event.target.closest("[data-remove]");
                if (remove) {
                    builder.removeTool(remove.dataset.remove);
                }
            });

            content.append(
                head,
                Html.element("div", "ab-field-label", "Description"),
                this.description,
                Html.element("div", "ab-field-label", "Prompt (Langfuse)"),
                this.prompt,
                this.toolsLabel,
                this.chips,
            );
        }

        render(draft) {
            const data = Workflow.step(draft.workflow_json).data;
            this.title.textContent = draft.label || "New agent";
            this.notes.textContent = [draft.is_default && "default", !draft.is_active && "inactive"].filter(Boolean).join(" · ");
            if (document.activeElement !== this.prompt) {
                this.prompt.value = data.name;
            }
            if (document.activeElement !== this.description) {
                this.description.value = draft.description;
            }
            this.toolsLabel.textContent = `Tools (${data.tools.length})`;
            this.renderChips(data.tools);
        }

        renderChips(chosen) {
            this.chips.replaceChildren();
            for (const name of chosen) {
                const tool = this.builder.tool(name);
                const chip = Html.element("span", "ab-chip");
                chip.title = `${tool.description}\nInputs: ${tool.args.length ? tool.args.join(", ") : "none"}`;
                const remove = Html.element("button", "ab-chip-x", "\u00d7");
                remove.type = "button";
                remove.dataset.remove = name;
                remove.setAttribute("aria-label", `Remove ${name}`);
                chip.append(Html.element("span", "", name), remove);
                this.chips.appendChild(chip);
            }
            if (!chosen.length) {
                this.chips.appendChild(Html.element("span", "ab-empty", "No tools yet. Tick them in the list on the right."));
            }
        }
    }

    class AgentBuilder {
        static SAVED_MESSAGE_MS = 3000;

        constructor(root) {
            this.root = root;
            this.agents = Html.json("agents-data");
            this.tools = Html.json("tools-data");
            this.known = new Set(this.tools.map((tool) => tool.name));
            this.canvas = Html.byId("canvas");
            this.picker = Html.byId("agentPicker");
            this.msg = Html.byId("msg");
            this.search = Html.byId("search");
            this.toolList = Html.byId("toolList");
            this.tooltip = Html.byId("tooltip");
            this.fields = {
                label: Html.byId("fLabel"),
                isDefault: Html.byId("fDefault"),
            };
            this.drafts = new Map();
            this.baselines = new Map();
            this.rootDraft = null;
            this.startId = null;
            this.stepId = null;
            this.stepNode = null;
            this.savedTimer = null;
            this.saving = null;
            this.startEditor();
            this.bindEvents();
            this.loadPrompts();
        }

        startEditor() {
            const editor = new Drawflow(this.canvas);
            editor.removeNodeId = () => {};
            editor.removeConnection = () => {};
            editor.reroute = false;
            editor.draggable_inputs = false;
            editor.zoom_min = 0.3;
            editor.zoom_max = 1.6;
            editor.start();
            editor.on("nodeMoved", (id) => {
                this.syncPosition(id);
                this.refreshDirty();
            });
            this.editor = editor;
        }

        bindEvents() {
            this.picker.addEventListener("change", () => this.pickAgent());
            Html.byId("btnNew").addEventListener("click", () => this.openAgent(null));
            Html.byId("btnSave").addEventListener("click", () => this.save());
            Html.byId("btnZoomIn").addEventListener("click", () => this.editor.zoom_in());
            Html.byId("btnZoomOut").addEventListener("click", () => this.editor.zoom_out());
            Html.byId("btnFit").addEventListener("click", () => this.fit());
            for (const field of Object.values(this.fields)) {
                field.addEventListener("input", () => this.readSettings());
            }
            this.search.addEventListener("input", () => this.renderTools());
            new ResizeObserver(() => this.redraw()).observe(this.canvas);
            window.addEventListener("beforeunload", (event) => {
                if (this.isDirty()) {
                    event.preventDefault();
                    event.returnValue = "";
                }
            });
        }

        async loadPrompts() {
            try {
                const response = await fetch(this.root.dataset.promptsUrl);
                const data = await response.json();
                const list = Html.byId("promptOptions");
                for (const name of data.prompts) {
                    list.appendChild(new Option(name, name));
                }
            } catch (error) {
                console.warn("Could not load Langfuse prompts", error);
            }
        }

        toDraft(agent) {
            return {
                id: agent ? agent.id : null,
                slug: agent ? agent.slug : "",
                label: agent ? agent.label : "",
                description: agent ? agent.description : "",
                is_default: agent ? agent.is_default : false,
                is_active: agent ? agent.is_active : true,
                workflow_json: Workflow.normalise(agent ? agent.workflow_json : null, this.known),
            };
        }

        load(agent) {
            this.drafts = new Map(this.agents.map((item) => [item.id, this.toDraft(item)]));
            this.rootDraft = agent ? this.drafts.get(agent.id) : this.toDraft(null);
            if (!agent) {
                this.drafts.set(null, this.rootDraft);
            }
            this.drawGraph();
            this.renderPicker();
            this.select();
            this.baselines = new Map([...this.drafts.values()].map((draft) => [draft, this.snapshot(draft)]));
            this.refreshDirty();
        }

        select() {
            const draft = this.rootDraft;
            this.fields.label.value = draft.label;
            this.fields.label.title = draft.slug ? `Slug: ${draft.slug}` : "";
            this.fields.isDefault.checked = draft.is_default;
            this.renderStep();
            this.renderTools();
        }

        tool(name) {
            return this.tools.find((tool) => tool.name === name);
        }

        step() {
            return Workflow.step(this.rootDraft.workflow_json);
        }

        openAgent(agent) {
            if (this.isDirty() && !window.confirm("You have unsaved changes. Discard them?")) {
                this.renderPicker();
                return;
            }
            this.load(agent);
        }

        pickAgent() {
            this.openAgent(this.agents.find((agent) => agent.id === Number(this.picker.value)) || null);
        }

        readSettings() {
            const draft = this.rootDraft;
            draft.label = this.fields.label.value;
            if (this.fields.isDefault.checked && !draft.is_default) {
                for (const other of this.drafts.values()) {
                    other.is_default = false;
                }
            }
            draft.is_default = this.fields.isDefault.checked;
            this.renderStep();
            this.refreshDirty();
        }

        changeDescription(text) {
            this.rootDraft.description = text;
            this.refreshDirty();
        }

        changeStep(patch) {
            Object.assign(this.step().data, patch);
            this.renderStep();
            this.renderTools();
            this.refreshDirty();
        }

        setTool(name, on) {
            const tools = this.step().data.tools.filter((item) => item !== name);
            this.changeStep({ tools: on ? [...tools, name] : tools });
        }

        removeTool(name) {
            this.setTool(name, false);
        }

        renderTools() {
            const term = this.search.value.trim().toLowerCase();
            const chosen = this.step().data.tools;
            const matches = (tool) => !term || [tool.name, tool.description].some((text) => (text || "").toLowerCase().includes(term));
            this.toolList.replaceChildren();
            for (const tool of this.tools.filter(matches)) {
                this.toolList.appendChild(this.toolRow(tool, chosen.includes(tool.name)));
            }
            if (!this.toolList.children.length) {
                this.toolList.appendChild(Html.element("div", "ab-empty", "No tools match."));
            }
            Html.byId("toolCount").textContent = `${chosen.length} of ${this.tools.length}`;
        }

        toolRow(tool, ticked) {
            const row = Html.element("label", "ab-row");
            row.classList.toggle("is-on", ticked);
            const box = Html.element("input");
            box.type = "checkbox";
            box.checked = ticked;
            box.addEventListener("change", () => this.setTool(tool.name, box.checked));
            row.append(box, Html.element("span", "ab-row-name", tool.name));
            row.addEventListener("mouseenter", () => this.showTooltip(row, tool));
            row.addEventListener("mouseleave", () => { this.tooltip.hidden = true; });
            return row;
        }

        showTooltip(target, tool) {
            this.tooltip.textContent = `${tool.description}\nInputs: ${tool.args.length ? tool.args.join(", ") : "none"}`;
            this.tooltip.hidden = false;
            const box = target.getBoundingClientRect();
            const top = Math.min(box.top, window.innerHeight - this.tooltip.offsetHeight - 8);
            this.tooltip.style.top = `${top}px`;
            this.tooltip.style.left = `${Math.max(8, box.left - this.tooltip.offsetWidth - 12)}px`;
        }

        renderPicker() {
            this.picker.replaceChildren();
            if (this.rootDraft.id === null) {
                this.picker.appendChild(new Option("New agent (not saved yet)", "new"));
            }
            for (const agent of this.agents) {
                const notes = [agent.is_default && "default", !agent.is_active && "inactive"].filter(Boolean);
                const text = `${agent.label} (${agent.slug})${notes.length ? ` - ${notes.join(", ")}` : ""}`;
                this.picker.appendChild(new Option(text, agent.id));
            }
            this.picker.value = this.rootDraft.id === null ? "new" : String(this.rootDraft.id);
        }

        renderStep() {
            const element = Html.byId(`node-${this.stepId}`);
            element.classList.toggle("ab-off", !this.rootDraft.is_active);
            this.stepNode.render(this.rootDraft);
        }

        graphData() {
            return this.editor.drawflow.drawflow[this.editor.module].data;
        }

        content(id) {
            return Html.byId(`node-${id}`).querySelector(".drawflow_content_node");
        }

        drawGraph() {
            this.editor.clear();
            const start = Workflow.start(this.rootDraft.workflow_json).position;
            const step = this.step().position;
            this.startId = this.editor.addNode(Workflow.START, 0, 1, start.x, start.y, "ab-start", {}, "");
            this.stepId = this.editor.addNode(Workflow.STEP, 1, 0, step.x, step.y, "ab-step", {}, "");
            new StartNode(this.content(this.startId));
            this.stepNode = new StepNode(this, this.content(this.stepId));
            this.editor.addConnection(this.startId, this.stepId, "output_1", "input_1");
            this.renderStep();
            this.fit();
        }

        syncPosition(id) {
            const element = Html.byId(`node-${id}`);
            const node = this.graphData()[id];
            node.pos_x = parseFloat(element.style.left);
            node.pos_y = parseFloat(element.style.top);
        }

        box(id) {
            const node = this.graphData()[id];
            const element = Html.byId(`node-${id}`);
            return { x: node.pos_x, y: node.pos_y, w: element.offsetWidth, h: element.offsetHeight };
        }

        firstAgent() {
            const wanted = Number(new URLSearchParams(window.location.search).get("agent"));
            return this.agents.find((agent) => agent.id === wanted) || this.agents[0] || null;
        }

        redraw() {
            if (!this.canvas.clientWidth) {
                return;
            }
            if (!this.rootDraft) {
                this.load(this.firstAgent());
                return;
            }
            this.fit();
            for (const id of [this.startId, this.stepId]) {
                this.editor.updateConnectionNodes(`node-${id}`);
            }
        }

        fit() {
            if (!this.canvas.clientWidth || !this.canvas.clientHeight || this.stepId === null) {
                return;
            }
            const boxes = [this.box(this.startId), this.box(this.stepId)];
            const left = Math.min(...boxes.map((box) => box.x));
            const top = Math.min(...boxes.map((box) => box.y));
            const right = Math.max(...boxes.map((box) => box.x + box.w));
            const bottom = Math.max(...boxes.map((box) => box.y + box.h));
            const width = this.canvas.clientWidth;
            const height = this.canvas.clientHeight;
            const margin = 60;
            const zoom = Math.max(this.editor.zoom_min, Math.min(
                1,
                (width - margin * 2) / (right - left),
                (height - margin * 2) / (bottom - top),
            ));
            this.editor.zoom = zoom;
            this.editor.zoom_last_value = zoom;
            this.editor.canvas_x = -((left + right) / 2 - width / 2) * zoom;
            this.editor.canvas_y = -((top + bottom) / 2 - height / 2) * zoom;
            this.editor.precanvas.style.transform = `translate(${this.editor.canvas_x}px, ${this.editor.canvas_y}px) scale(${zoom})`;
        }

        currentWorkflow() {
            const workflow = JSON.parse(JSON.stringify(this.rootDraft.workflow_json));
            const data = this.graphData();
            const place = (id, node) => {
                if (data[id]) {
                    node.position = { x: data[id].pos_x, y: data[id].pos_y };
                }
            };
            place(this.startId, Workflow.start(workflow));
            place(this.stepId, Workflow.step(workflow));
            return workflow;
        }

        collect(draft) {
            return {
                id: draft.id,
                label: draft.label,
                description: draft.description,
                is_default: draft.is_default,
                workflow_json: draft === this.rootDraft ? this.currentWorkflow() : draft.workflow_json,
            };
        }

        snapshot(draft) {
            return JSON.stringify(this.collect(draft));
        }

        changedDrafts() {
            return [...this.drafts.values()].filter((draft) => this.snapshot(draft) !== this.baselines.get(draft));
        }

        isDirty() {
            return this.changedDrafts().length > 0;
        }

        refreshDirty() {
            Html.byId("dirty").hidden = !this.isDirty();
        }

        showMessage(text, clearLater) {
            window.clearTimeout(this.savedTimer);
            this.msg.textContent = text;
            if (clearLater) {
                this.savedTimer = window.setTimeout(() => {
                    this.msg.textContent = "";
                }, AgentBuilder.SAVED_MESSAGE_MS);
            }
        }

        save() {
            if (!this.saving) {
                this.saving = this.send().finally(() => {
                    this.saving = null;
                });
            }
            return this.saving;
        }

        async send() {
            this.showMessage("Saving…");
            const pending = [...new Set([...this.changedDrafts(), this.rootDraft])];
            for (const draft of pending) {
                if (!await this.saveDraft(draft)) {
                    return false;
                }
            }
            this.renderPicker();
            this.select();
            this.refreshDirty();
            this.showMessage("Saved ✓", true);
            return true;
        }

        async saveDraft(draft) {
            const response = await fetch(this.root.dataset.saveUrl, {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-CSRFToken": this.root.dataset.csrf },
                body: JSON.stringify(this.collect(draft)),
            });
            const data = await response.json();
            if (!data.ok) {
                this.showMessage(`Error in ${draft.label || "New agent"}: ${data.error}`);
                this.refreshDirty();
                return false;
            }
            const saved = data.agent;
            if (saved.is_default) {
                for (const agent of this.agents) {
                    agent.is_default = false;
                }
            }
            const index = this.agents.findIndex((agent) => agent.id === saved.id);
            if (index >= 0) {
                this.agents[index] = saved;
            } else {
                this.agents.push(saved);
                this.drafts.delete(null);
                this.drafts.set(saved.id, draft);
            }
            draft.id = saved.id;
            draft.slug = saved.slug;
            draft.workflow_json = Workflow.normalise(saved.workflow_json, this.known);
            this.baselines.set(draft, this.snapshot(draft));
            return true;
        }
    }

    new AgentBuilder(Html.byId("agentBuilder"));
})();
