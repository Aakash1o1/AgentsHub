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

        static escape(text) {
            const box = document.createElement("div");
            box.textContent = text;
            return box.innerHTML;
        }

        static byId(id) {
            return document.getElementById(id);
        }

        static json(id) {
            return JSON.parse(Html.byId(id).textContent);
        }
    }

    class AgentLinks {
        constructor(agents) {
            this.children = new Map(agents.map((agent) => [agent.id, agent.sub_agents]));
            this.parents = new Map();
            for (const agent of agents) {
                for (const sub of agent.sub_agents) {
                    this.parents.set(sub, [...(this.parents.get(sub) || []), agent.id]);
                }
            }
        }

        reaches(start, target) {
            return start === target || (this.children.get(start) || []).some((next) => this.reaches(next, target));
        }

        static length(id, links) {
            const next = links.get(id) || [];
            return 1 + Math.max(0, ...next.map((other) => AgentLinks.length(other, links)));
        }

        below(id) {
            return AgentLinks.length(id, this.children);
        }

        above(id) {
            return AgentLinks.length(id, this.parents);
        }
    }

    class AgentBuilder {
        static ROOT_X = 40;
        static ROOT_Y = 200;
        static COLUMN_SPACE = 80;
        static ROW_GAP = 66;
        static COLUMN_ROWS = 9;
        static STACK_GAP = 14;
        static SAVED_MESSAGE_MS = 3000;

        constructor(root) {
            this.root = root;
            this.agents = Html.json("agents-data");
            this.tools = Html.json("tools-data");
            this.maxLevels = Number(root.dataset.maxLevels);
            this.canvas = Html.byId("canvas");
            this.picker = Html.byId("agentPicker");
            this.msg = Html.byId("msg");
            this.fields = {
                label: Html.byId("fLabel"),
                prompt: Html.byId("fPrompt"),
                description: Html.byId("fDesc"),
                isDefault: Html.byId("fDefault"),
                isActive: Html.byId("fActive"),
            };
            this.drafts = new Map();
            this.baselines = new Map();
            this.rootDraft = null;
            this.state = null;
            this.nodes = new Map();
            this.rootId = null;
            this.savedTimer = null;
            this.saving = null;
            this.pressed = null;
            this.startEditor();
            this.bindEvents();
            this.loadPrompts();
        }

        startEditor() {
            const editor = new Drawflow(this.canvas);
            const removeNode = editor.removeNodeId.bind(editor);
            editor.removeNodeId = (id) => {
                if (id !== `node-${this.rootId}`) {
                    removeNode(id);
                }
            };
            editor.reroute = false;
            editor.zoom_min = 0.3;
            editor.zoom_max = 1.6;
            editor.start();
            editor.on("connectionRemoved", () => window.setTimeout(() => this.reconcile()));
            editor.on("nodeRemoved", () => window.setTimeout(() => this.reconcile()));
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
            Html.byId("btnArrange").addEventListener("click", () => this.arrange());
            Html.byId("search").addEventListener("input", () => this.renderLists());
            for (const field of Object.values(this.fields)) {
                field.addEventListener("input", () => this.readSettings());
            }
            this.canvas.addEventListener("mousedown", (event) => {
                this.pressed = { x: event.clientX, y: event.clientY };
                this.canvas.focus({ preventScroll: true });
            }, true);
            this.canvas.addEventListener("click", (event) => this.clickCanvas(event));
            this.canvas.addEventListener("dblclick", (event) => this.expandTool(event));
            this.canvas.addEventListener("mouseover", (event) => this.hoverPill(event));
            this.canvas.addEventListener("mouseout", () => this.hideTooltip());
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
                    const option = document.createElement("option");
                    option.value = name;
                    list.appendChild(option);
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
                prompt_name: agent ? agent.prompt_name : "",
                description: agent ? agent.description : "",
                is_default: agent ? agent.is_default : false,
                is_active: agent ? agent.is_active : true,
                tools: agent ? agent.tools.filter((name) => this.tool(name)) : [],
                sub_agents: agent ? [...agent.sub_agents] : [],
                graph_json: agent ? agent.graph_json : {},
            };
        }

        load(agent) {
            this.drafts = new Map(this.agents.map((item) => [item.id, this.toDraft(item)]));
            this.rootDraft = agent ? this.drafts.get(agent.id) : this.toDraft(null);
            if (!agent) {
                this.drafts.set(null, this.rootDraft);
            }
            this.state = this.rootDraft;
            this.drawGraph(this.rootDraft.graph_json);
            this.renderPicker();
            this.select(this.rootDraft);
            this.baselines = new Map([...this.drafts.values()].map((draft) => [draft, this.snapshot(draft)]));
            this.refreshDirty();
        }

        select(draft) {
            this.state = draft;
            this.fields.label.value = draft.label;
            this.fields.label.title = draft.slug ? `Slug: ${draft.slug}` : "";
            this.fields.prompt.value = draft.prompt_name;
            this.fields.description.value = draft.description;
            this.fields.isDefault.checked = draft.is_default;
            this.fields.isActive.checked = draft.is_active;
            this.markEditing();
            this.renderLists();
        }

        markEditing() {
            const current = this.nodeOf(this.state);
            this.canvas.querySelectorAll(".drawflow-node").forEach((element) => {
                element.classList.toggle("is-editing", element.id === `node-${current}`);
            });
        }

        tool(name) {
            return this.tools.find((tool) => tool.name === name);
        }

        draft(id) {
            return this.drafts.get(id);
        }

        nodeOf(draft) {
            return draft === this.rootDraft ? this.rootId : this.nodes.get(`agent:${draft.id}`);
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
            this.state.label = this.fields.label.value;
            this.state.prompt_name = this.fields.prompt.value;
            this.state.description = this.fields.description.value;
            this.state.is_active = this.fields.isActive.checked;
            if (this.fields.isDefault.checked && !this.state.is_default) {
                for (const draft of this.drafts.values()) {
                    draft.is_default = false;
                }
            }
            this.state.is_default = this.fields.isDefault.checked;
            this.refreshAgentNodes();
            this.renderLists();
            this.refreshDirty();
        }

        renderPicker() {
            this.picker.replaceChildren();
            if (this.rootDraft.id === null) {
                const option = document.createElement("option");
                option.value = "new";
                option.textContent = "New agent (not saved yet)";
                this.picker.appendChild(option);
            }
            for (const agent of this.agents) {
                const option = document.createElement("option");
                option.value = agent.id;
                const notes = [agent.is_default && "default", !agent.is_active && "inactive"].filter(Boolean);
                option.textContent = `${agent.label} (${agent.slug})${notes.length ? ` - ${notes.join(", ")}` : ""}`;
                this.picker.appendChild(option);
            }
            this.picker.value = this.rootDraft.id === null ? "new" : String(this.rootDraft.id);
        }

        links() {
            return new AgentLinks([...this.drafts.values()]);
        }

        renderLists() {
            const term = Html.byId("search").value.trim().toLowerCase();
            if (term) {
                this.root.querySelectorAll(".ab-group").forEach((group) => { group.open = true; });
            }
            const matches = (...texts) => !term || texts.some((text) => (text || "").toLowerCase().includes(term));

            const toolList = Html.byId("toolList");
            toolList.replaceChildren();
            for (const tool of this.tools.filter((item) => matches(item.name, item.description))) {
                toolList.appendChild(this.row(tool.name, tool.description, this.state.tools.includes(tool.name), this.state !== this.rootDraft, (on) => this.setTool(tool.name, on)));
            }
            if (!toolList.children.length) {
                toolList.appendChild(Html.element("div", "ab-empty", "No tools match."));
            }
            Html.byId("toolCount").textContent = `(${this.state.tools.length} of ${this.tools.length})`;

            const links = this.links();
            const above = links.above(this.state.id);
            const agentList = Html.byId("agentList");
            agentList.replaceChildren();
            const usable = [...this.drafts.values()].filter((draft) => draft !== this.state
                && draft.id !== null
                && !links.reaches(draft.id, this.state.id));
            for (const draft of usable.filter((item) => matches(item.label, item.slug, item.description))) {
                const ticked = this.state.sub_agents.includes(draft.id);
                const tooDeep = !ticked && above + links.below(draft.id) > this.maxLevels;
                const reason = tooDeep ? `Would make a chain longer than ${this.maxLevels} levels.` : null;
                const name = draft.is_active ? draft.label : `${draft.label} (inactive)`;
                agentList.appendChild(this.row(name, reason || draft.description, ticked, Boolean(reason), (on) => this.setSubAgent(draft.id, on)));
            }
            if (!agentList.children.length) {
                agentList.appendChild(Html.element("div", "ab-empty", term ? "No agents match." : "No other agents can be added."));
            }
            Html.byId("agentCount").textContent = `(${this.state.sub_agents.length})`;
        }

        row(name, info, ticked, disabled, onToggle) {
            const row = Html.element("label", "ab-row");
            const box = document.createElement("input");
            box.type = "checkbox";
            box.checked = ticked;
            box.disabled = disabled;
            box.addEventListener("change", () => onToggle(box.checked));
            row.append(box, Html.element("span", "ab-row-name", name));
            row.classList.toggle("is-on", ticked);
            row.classList.toggle("is-disabled", disabled);
            if (info) {
                row.addEventListener("mouseenter", () => this.showTooltip(row, info));
                row.addEventListener("mouseleave", () => this.hideTooltip());
            }
            return row;
        }

        showTooltip(target, text) {
            const tooltip = Html.byId("tooltip");
            tooltip.textContent = text;
            tooltip.hidden = false;
            const box = target.getBoundingClientRect();
            const top = Math.min(box.top, window.innerHeight - tooltip.offsetHeight - 8);
            tooltip.style.top = `${top}px`;
            tooltip.style.left = `${Math.max(8, box.left - tooltip.offsetWidth - 12)}px`;
        }

        hideTooltip() {
            Html.byId("tooltip").hidden = true;
        }

        hoverPill(event) {
            const pill = event.target.closest(".ab-pill");
            if (pill) {
                this.showTooltip(pill, this.tool(pill.dataset.tool).description);
            }
        }

        setTool(name, on) {
            if (on) {
                this.state.tools.push(name);
            } else {
                this.state.tools = this.state.tools.filter((item) => item !== name);
            }
            this.changedConnections();
        }

        setSubAgent(id, on) {
            if (on) {
                this.state.sub_agents.push(id);
            } else {
                this.state.sub_agents = this.state.sub_agents.filter((item) => item !== id);
            }
            this.changedConnections();
        }

        removeFromGraph(key) {
            const [kind, value] = AgentBuilder.splitKey(key);
            if (kind === "tool") {
                this.rootDraft.tools = this.rootDraft.tools.filter((item) => item !== value);
            } else {
                for (const parent of this.graphAgents()) {
                    parent.sub_agents = parent.sub_agents.filter((item) => item !== Number(value));
                }
            }
            this.changedConnections();
        }

        changedConnections() {
            this.syncGraph();
            this.renderLists();
            this.refreshDirty();
        }

        graphData() {
            return this.editor.drawflow.drawflow[this.editor.module].data;
        }

        graphAgents() {
            const found = [this.rootDraft];
            for (const draft of found) {
                for (const id of draft.sub_agents) {
                    if (!found.includes(this.draft(id))) {
                        found.push(this.draft(id));
                    }
                }
            }
            return found;
        }

        drawGraph(layout) {
            this.editor.clear();
            this.nodes.clear();
            const current = Boolean(layout.agents);
            const saved = (current && layout.agent) || { x: AgentBuilder.ROOT_X, y: AgentBuilder.ROOT_Y };
            this.rootId = this.editor.addNode("root", 0, 1, saved.x, saved.y, "ab-root", {}, this.agentHtml(this.rootDraft));
            this.syncGraph(current ? layout : {});
            if (!current) {
                this.placeLeaves();
            }
            this.fit();
        }

        syncGraph(layout = {}) {
            const agents = this.graphAgents();
            const wanted = new Set([
                ...agents.filter((draft) => draft !== this.rootDraft).map((draft) => `agent:${draft.id}`),
                ...this.rootDraft.tools.map((name) => `tool:${name}`),
            ]);
            for (const key of [...this.nodes.keys()]) {
                if (!wanted.has(key)) {
                    this.removeLeaf(key);
                }
            }
            for (const parent of agents) {
                for (const id of parent.sub_agents) {
                    const place = (layout.agents || []).find((item) => item.id === id);
                    this.addLeaf(`agent:${id}`, this.nodeOf(parent), place);
                }
            }
            for (const name of this.rootDraft.tools) {
                const place = (layout.tools || []).find((item) => item.tool === name);
                this.addLeaf(`tool:${name}`, this.rootId, place);
            }
            for (const parent of agents) {
                this.syncLines(parent);
            }
            this.refreshAgentNodes();
            if (!agents.includes(this.state)) {
                this.select(this.rootDraft);
            }
            this.markEditing();
            if ([...this.nodes.values()].some((id) => !this.isVisible(id))) {
                this.fit();
            }
        }

        syncLines(parent) {
            const parentId = this.nodeOf(parent);
            const keys = parent.sub_agents.map((id) => `agent:${id}`);
            if (parent === this.rootDraft) {
                keys.push(...parent.tools.map((name) => `tool:${name}`));
            }
            const wanted = keys.map((key) => String(this.nodes.get(key)));
            const current = this.graphData()[parentId].outputs.output_1.connections.map((link) => String(link.node));
            for (const id of current.filter((item) => !wanted.includes(item))) {
                this.editor.removeSingleConnection(parentId, id, "output_1", "input_1");
            }
            for (const id of wanted.filter((item) => !current.includes(item))) {
                this.editor.addConnection(parentId, id, "output_1", "input_1");
            }
        }

        agentHtml(draft) {
            const notes = ["Agent", draft.is_default && "default", !draft.is_active && "inactive"].filter(Boolean);
            const main = `<div class="ab-node-title">${Html.escape(draft.label || "New agent")}</div>`
                + `<div class="ab-node-sub">${Html.escape(notes.join(" · "))}</div>`;
            if (draft === this.rootDraft) {
                return main;
            }
            const pills = draft.tools.map((name) => `<span class="ab-pill" data-tool="${Html.escape(name)}">${Html.escape(name)}</span>`).join("");
            return main
                + (pills ? `<div class="ab-pills">${pills}</div>` : "")
                + `<button type="button" class="ab-x" data-remove="agent:${draft.id}" aria-label="Remove">&times;</button>`;
        }

        toolHtml(name) {
            const tool = this.tool(name);
            return `<div class="ab-node-title">${Html.escape(name)}</div>`
                + `<div class="ab-node-sub">Tool</div>`
                + `<div class="ab-node-more">${Html.escape(tool.description)}`
                + `<div>Inputs: ${Html.escape(tool.args.length ? tool.args.join(", ") : "none")}</div></div>`
                + `<button type="button" class="ab-x" data-remove="tool:${Html.escape(name)}" aria-label="Remove">&times;</button>`;
        }

        static splitKey(key) {
            const at = key.indexOf(":");
            return [key.slice(0, at), key.slice(at + 1)];
        }

        refreshAgentNodes() {
            for (const draft of this.graphAgents()) {
                const id = this.nodeOf(draft);
                const element = Html.byId(`node-${id}`);
                const before = element.offsetHeight;
                element.querySelector(".drawflow_content_node").innerHTML = this.agentHtml(draft);
                element.classList.toggle("ab-off", !draft.is_active);
                if (element.offsetHeight !== before) {
                    this.editor.updateConnectionNodes(`node-${id}`);
                    this.makeRoom(id);
                }
            }
        }

        addLeaf(key, parentId, place) {
            if (this.nodes.has(key)) {
                return;
            }
            const [kind, value] = AgentBuilder.splitKey(key);
            const isAgent = kind === "agent";
            const draft = isAgent ? this.draft(Number(value)) : null;
            const css = isAgent ? "ab-sub" : "ab-tool";
            const html = isAgent ? this.agentHtml(draft) : this.toolHtml(value);
            const parent = this.graphData()[parentId];
            const id = this.editor.addNode(key, 1, isAgent ? 1 : 0, parent.pos_x, parent.pos_y, css, {}, html);
            this.nodes.set(key, id);
            const free = place && place.x != null && !this.overlaps(id, place.x, place.y);
            const spot = free ? place : this.freeSpot(id, parentId);
            this.moveNode(id, spot.x, spot.y);
        }

        removeLeaf(key) {
            const id = this.nodes.get(key);
            this.nodes.delete(key);
            if (id != null && this.graphData()[id]) {
                this.editor.removeNodeId(`node-${id}`);
            }
        }

        reconcile() {
            const data = this.graphData();
            if (!data[this.rootId]) {
                return;
            }
            const linked = (id) => data[id].outputs.output_1.connections.map((link) => String(link.node));
            const kept = (from, key) => from.includes(String(this.nodes.get(key))) && data[this.nodes.get(key)];
            const before = JSON.stringify(this.graphAgents().map((draft) => [draft.tools, draft.sub_agents]));
            for (const parent of this.graphAgents()) {
                const id = this.nodeOf(parent);
                if (id == null || !data[id]) {
                    continue;
                }
                const from = linked(id);
                parent.sub_agents = parent.sub_agents.filter((sub) => kept(from, `agent:${sub}`));
                if (parent === this.rootDraft) {
                    parent.tools = parent.tools.filter((name) => kept(from, `tool:${name}`));
                }
            }
            if (before !== JSON.stringify(this.graphAgents().map((draft) => [draft.tools, draft.sub_agents]))) {
                this.changedConnections();
            }
        }

        box(id) {
            const node = this.graphData()[id];
            const element = Html.byId(`node-${id}`);
            return { x: node.pos_x, y: node.pos_y, w: element.offsetWidth, h: element.offsetHeight };
        }

        overlaps(id, x, y) {
            const { w, h } = this.box(id);
            return Object.keys(this.graphData()).some((other) => {
                if (String(other) === String(id)) {
                    return false;
                }
                const box = this.box(other);
                return x < box.x + box.w + 10 && box.x < x + w + 10 && y < box.y + box.h + 10 && box.y < y + h + 10;
            });
        }

        freeSpot(id, parentId) {
            const parent = this.box(parentId);
            const own = this.box(id);
            for (let index = 0; ; index += 1) {
                const column = Math.floor(index / AgentBuilder.COLUMN_ROWS);
                const row = index % AgentBuilder.COLUMN_ROWS;
                const away = Math.ceil(row / 2) * (row % 2 ? 1 : -1);
                const spot = {
                    x: parent.x + parent.w + AgentBuilder.COLUMN_SPACE + column * (own.w + AgentBuilder.COLUMN_SPACE),
                    y: parent.y + away * AgentBuilder.ROW_GAP,
                };
                if (!this.overlaps(id, spot.x, spot.y)) {
                    return spot;
                }
            }
        }

        makeRoom(id) {
            const box = this.box(id);
            for (const other of Object.keys(this.graphData())) {
                const next = this.box(other);
                const hit = String(other) !== String(id)
                    && box.x < next.x + next.w && next.x < box.x + box.w
                    && box.y < next.y + next.h && next.y < box.y + box.h;
                if (hit) {
                    this.moveNode(other, next.x, box.y + box.h + AgentBuilder.STACK_GAP);
                    this.makeRoom(other);
                }
            }
        }

        syncPosition(id) {
            const element = Html.byId(`node-${id}`);
            const node = this.graphData()[id];
            node.pos_x = parseFloat(element.style.left);
            node.pos_y = parseFloat(element.style.top);
        }

        moveNode(id, x, y) {
            const node = this.graphData()[id];
            node.pos_x = x;
            node.pos_y = y;
            const element = Html.byId(`node-${id}`);
            element.style.left = `${x}px`;
            element.style.top = `${y}px`;
            this.editor.updateConnectionNodes(`node-${id}`);
        }

        arrange() {
            this.moveNode(this.rootId, AgentBuilder.ROOT_X, AgentBuilder.ROOT_Y);
            this.placeLeaves();
            this.fit();
            this.refreshDirty();
        }

        columns() {
            const links = this.links();
            const byDepth = new Map();
            for (const draft of this.graphAgents()) {
                if (draft !== this.rootDraft) {
                    const depth = this.depth(draft, links);
                    byDepth.set(depth, [...(byDepth.get(depth) || []), this.nodeOf(draft)]);
                }
            }
            const first = [...(byDepth.get(1) || []), ...this.rootDraft.tools.map((name) => this.nodes.get(`tool:${name}`))];
            const columns = [];
            for (let start = 0; start < first.length; start += AgentBuilder.COLUMN_ROWS) {
                columns.push(first.slice(start, start + AgentBuilder.COLUMN_ROWS));
            }
            const deeper = [...byDepth.keys()].filter((depth) => depth > 1).sort();
            return [...columns, ...deeper.map((depth) => byDepth.get(depth))];
        }

        depth(draft, links) {
            const parents = (links.parents.get(draft.id) || []).map((id) => this.draft(id));
            const inGraph = parents.filter((parent) => this.graphAgents().includes(parent));
            if (inGraph.includes(this.rootDraft)) {
                return Math.max(1, ...inGraph.filter((parent) => parent !== this.rootDraft).map((parent) => this.depth(parent, links) + 1));
            }
            return Math.max(...inGraph.map((parent) => this.depth(parent, links) + 1));
        }

        placeLeaves() {
            const root = this.box(this.rootId);
            let x = root.x + root.w + AgentBuilder.COLUMN_SPACE;
            for (const ids of this.columns()) {
                const heights = ids.map((id) => this.box(id).h);
                const total = heights.reduce((sum, height) => sum + height, 0) + (ids.length - 1) * AgentBuilder.STACK_GAP;
                let y = root.y + root.h / 2 - total / 2;
                ids.forEach((id, index) => {
                    this.moveNode(id, x, y);
                    y += heights[index] + AgentBuilder.STACK_GAP;
                });
                x += Math.max(...ids.map((id) => this.box(id).w)) + AgentBuilder.COLUMN_SPACE;
            }
        }

        redraw() {
            if (!this.canvas.clientWidth) {
                return;
            }
            if (!this.rootDraft) {
                this.load(this.agents[0] || null);
                return;
            }
            this.fit();
            for (const id of Object.keys(this.graphData())) {
                this.editor.updateConnectionNodes(`node-${id}`);
            }
        }

        expandTool(event) {
            const element = event.target.closest(".drawflow-node.ab-tool");
            if (!element || event.target.closest("[data-remove]")) {
                return;
            }
            element.classList.toggle("is-expanded");
            this.editor.updateConnectionNodes(element.id);
        }

        isVisible(id) {
            const box = Html.byId(`node-${id}`).getBoundingClientRect();
            const area = this.canvas.getBoundingClientRect();
            return box.left >= area.left && box.right <= area.right && box.top >= area.top && box.bottom <= area.bottom;
        }

        fit() {
            if (!this.canvas.clientWidth || !this.canvas.clientHeight) {
                return;
            }
            const boxes = Object.keys(this.graphData()).map((id) => this.box(id));
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

        clickCanvas(event) {
            const moved = this.pressed && (Math.abs(event.clientX - this.pressed.x) > 4 || Math.abs(event.clientY - this.pressed.y) > 4);
            const remove = event.target.closest("[data-remove]");
            if (remove) {
                this.removeFromGraph(remove.dataset.remove);
                return;
            }
            if (moved || event.target.closest("svg")) {
                return;
            }
            const element = event.target.closest(".drawflow-node");
            if (!element) {
                this.select(this.rootDraft);
                return;
            }
            const id = Number(element.id.replace("node-", ""));
            const key = [...this.nodes].find(([, nodeId]) => nodeId === id)?.[0];
            if (id === this.rootId) {
                this.select(this.rootDraft);
            } else if (key && key.startsWith("agent:")) {
                this.select(this.draft(Number(AgentBuilder.splitKey(key)[1])));
            }
        }

        layout() {
            const data = this.graphData();
            const place = (id) => ({ x: data[id].pos_x, y: data[id].pos_y });
            const agents = this.graphAgents().filter((draft) => draft !== this.rootDraft);
            return {
                agent: place(this.rootId),
                tools: this.rootDraft.tools.map((tool) => ({ tool, ...place(this.nodes.get(`tool:${tool}`)) })),
                agents: agents.map((draft) => ({ id: draft.id, ...place(this.nodeOf(draft)) })),
            };
        }

        collect(draft) {
            return {
                id: draft.id,
                label: draft.label,
                prompt_name: draft.prompt_name,
                description: draft.description,
                is_default: draft.is_default,
                is_active: draft.is_active,
                tools: draft.tools,
                sub_agents: draft.sub_agents,
                graph_json: draft === this.rootDraft ? this.layout() : draft.graph_json,
            };
        }

        snapshot(draft) {
            const payload = this.collect(draft);
            payload.tools = [...payload.tools].sort();
            payload.sub_agents = [...payload.sub_agents].sort();
            if (draft === this.rootDraft) {
                payload.graph_json.tools = [...payload.graph_json.tools].sort((a, b) => a.tool.localeCompare(b.tool));
                payload.graph_json.agents = [...payload.graph_json.agents].sort((a, b) => a.id - b.id);
            }
            return JSON.stringify(payload);
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
            const links = this.links();
            const pending = [...new Set([...this.changedDrafts(), this.rootDraft])];
            pending.sort((a, b) => links.below(a.id) - links.below(b.id));
            for (const draft of pending) {
                if (!await this.saveDraft(draft)) {
                    return false;
                }
            }
            this.renderPicker();
            this.select(this.state);
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
                this.select(draft);
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
            draft.graph_json = saved.graph_json;
            this.baselines.set(draft, this.snapshot(draft));
            return true;
        }
    }

    new AgentBuilder(Html.byId("agentBuilder"));
})();
