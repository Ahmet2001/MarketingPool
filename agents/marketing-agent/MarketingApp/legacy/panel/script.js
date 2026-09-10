document.addEventListener("DOMContentLoaded", () => {
    const STORAGE_KEY = "mimar.panel.apiBase";
    const DEFAULT_POLL_MS = 12000;

    const state = {
        apiBase: resolveInitialApiBase(),
        activeTab: "dashboard",
        activeMemTab: "persona",
        activeSrcTab: "file",
        activeCustomToolTab: "ai",
        selectedFilePath: null,
        pendingActionId: null,
        hierarchy: null,
        stats: [],
        logs: [],
        skills: [],
        pendingActions: [],
        system: null,
        chart: null,
        lastSyncAt: null,
        expandedDirs: new Set(),
        activityFilter: "all",
        activitySearch: "",
        workspaceNodes: [],
        heartbeatDirty: false,
        heartbeat: {
            config: null,
            status: null,
            jobs: [],
        },
        pendingUploadFile: null,
        workspaceSearch: "",
        currentFileContent: "",
        currentFileMeta: null,
        heartbeatJobFilter: "all",
        social: {
            browser: null,
            queue: { items: [] },
            selectedQueueId: null,
            editorDirty: false,
            filter: "actionable",
            search: "",
        },
        env: {
            target: ".env",
            content: "",
            loaded: false,
        },
        agentStudio: {
            catalog: null,
            selectedAgentName: null,
            selectedCustomToolName: null,
            toolSearch: "",
            packPath: "",
            packPreview: null,
            editorDirty: false,
            customDirty: false,
            aiToolMessages: [],
            selectedToolNames: new Set(),
        },
    };

    const dom = {
        navItems: [...document.querySelectorAll(".nav-item")],
        tabPanels: [...document.querySelectorAll(".tab-panel")],
        memNavItems: [...document.querySelectorAll(".mem-nav-item")],
        memPanes: [...document.querySelectorAll(".memory-pane")],
        srcTabs: [...document.querySelectorAll(".src-tab")],
        customToolTabs: [...document.querySelectorAll(".custom-tool-tab")],
        customToolPanes: [...document.querySelectorAll(".custom-tool-pane")],
        srcPanes: [...document.querySelectorAll(".src-sub-content")],
        currentTabTitle: document.getElementById("current-tab-title"),
        connectionState: document.getElementById("connection-state"),
        apiBaseInput: document.getElementById("api-base-input"),
        saveApiBase: document.getElementById("save-api-base"),
        refreshAll: document.getElementById("refresh-all"),
        openEnvSettings: document.getElementById("open-env-settings"),
        sidebarSystemChip: document.getElementById("sidebar-system-chip"),
        sidebarModel: document.getElementById("sidebar-model"),
        sidebarUptime: document.getElementById("sidebar-uptime"),
        heroSystemPill: document.getElementById("hero-system-pill"),
        lastSyncLabel: document.getElementById("last-sync-label"),
        metricModel: document.getElementById("metric-model"),
        metricUptime: document.getElementById("metric-uptime"),
        metricApprovals: document.getElementById("metric-approvals"),
        activityTypeFilter: document.getElementById("activity-type-filter"),
        activitySearch: document.getElementById("activity-search"),
        summaryGrid: document.getElementById("summary-grid"),
        basemodelTools: document.getElementById("basemodel-tools"),
        submodelsContainer: document.getElementById("submodels-container"),
        liveActivity: document.getElementById("live-activity"),
        pendingActionsList: document.getElementById("pending-actions-list"),
        approvalCountBadge: document.getElementById("approval-count-badge"),
        approvalBadge: document.getElementById("approval-badge"),
        approvalModal: document.getElementById("approval-modal"),
        approvalDesc: document.getElementById("approval-desc"),
        btnApprove: document.getElementById("btn-approve"),
        btnReject: document.getElementById("btn-reject"),
        personaEditor: document.getElementById("persona-editor"),
        savePersona: document.getElementById("save-persona"),
        memListTitle: document.getElementById("mem-list-title"),
        memTableBody: document.getElementById("mem-table-body"),
        newMemKey: document.getElementById("new-mem-key"),
        newMemVal: document.getElementById("new-mem-val"),
        btnAddMem: document.getElementById("btn-add-mem"),
        workspaceSearch: document.getElementById("workspace-search"),
        fileTree: document.getElementById("file-tree"),
        currentFileName: document.getElementById("current-file-name"),
        currentFilePath: document.getElementById("current-file-path"),
        fileViewer: document.getElementById("file-viewer"),
        copyFilePath: document.getElementById("copy-file-path"),
        fileStatExtension: document.getElementById("file-stat-extension"),
        fileStatLines: document.getElementById("file-stat-lines"),
        fileStatChars: document.getElementById("file-stat-chars"),
        fileStatWords: document.getElementById("file-stat-words"),
        fileSearchInput: document.getElementById("file-search-input"),
        fileSearchResults: document.getElementById("file-search-results"),
        clearFileSearch: document.getElementById("clear-file-search"),
        btnAddSource: document.getElementById("btn-add-source"),
        refreshTree: document.getElementById("refresh-tree"),
        sourceModal: document.getElementById("source-modal"),
        closeSourceModal: document.getElementById("close-source-modal"),
        envModal: document.getElementById("env-modal"),
        closeEnvModal: document.getElementById("close-env-modal"),
        envTargetSelect: document.getElementById("env-target-select"),
        envFileMeta: document.getElementById("env-file-meta"),
        envEditor: document.getElementById("env-editor"),
        reloadEnvContent: document.getElementById("reload-env-content"),
        saveEnvContent: document.getElementById("save-env-content"),
        fileInput: document.getElementById("file-input"),
        dropZone: document.getElementById("drop-zone"),
        selectedFileName: document.getElementById("selected-file-name"),
        btnUpload: document.getElementById("btn-upload"),
        btnAddUrl: document.getElementById("btn-add-url"),
        btnAddText: document.getElementById("btn-add-text"),
        srcUrlName: document.getElementById("src-url-name"),
        srcUrlVal: document.getElementById("src-url-val"),
        srcTextName: document.getElementById("src-text-name"),
        srcTextVal: document.getElementById("src-text-val"),
        reloadSkills: document.getElementById("reload-skills"),
        skillsList: document.getElementById("skills-list"),
        heartbeatEditor: document.getElementById("heartbeat-editor"),
        heartbeatEnable: document.getElementById("heartbeat-enable"),
        heartbeatDisable: document.getElementById("heartbeat-disable"),
        heartbeatReload: document.getElementById("heartbeat-reload"),
        heartbeatEnabledState: document.getElementById("heartbeat-enabled-state"),
        heartbeatMeta: document.getElementById("heartbeat-meta"),
        heartbeatRunningState: document.getElementById("heartbeat-running-state"),
        heartbeatRunningMeta: document.getElementById("heartbeat-running-meta"),
        heartbeatConfigState: document.getElementById("heartbeat-config-state"),
        heartbeatConfigMeta: document.getElementById("heartbeat-config-meta"),
        heartbeatSummaryGrid: document.getElementById("heartbeat-summary-grid"),
        heartbeatJobFilter: document.getElementById("heartbeat-job-filter"),
        heartbeatJobList: document.getElementById("heartbeat-job-list"),
        saveHeartbeat: document.getElementById("save-heartbeat"),
        launchBrowserVisible: document.getElementById("launch-browser-visible"),
        refreshSocial: document.getElementById("refresh-social"),
        scanSocial: document.getElementById("scan-social"),
        socialBrowserState: document.getElementById("social-browser-state"),
        socialBrowserUrl: document.getElementById("social-browser-url"),
        socialBrowserMode: document.getElementById("social-browser-mode"),
        socialQueueCount: document.getElementById("social-queue-count"),
        socialQueueUpdated: document.getElementById("social-queue-updated"),
        socialQueueFilter: document.getElementById("social-queue-filter"),
        socialQueueSearch: document.getElementById("social-queue-search"),
        socialSelectedMeta: document.getElementById("social-selected-meta"),
        socialOpenLink: document.getElementById("social-open-link"),
        socialQueueList: document.getElementById("social-queue-list"),
        socialEditorTitle: document.getElementById("social-editor-title"),
        socialCommentPreview: document.getElementById("social-comment-preview"),
        socialToneSelect: document.getElementById("social-tone-select"),
        socialReplyCount: document.getElementById("social-reply-count"),
        socialReplyEditor: document.getElementById("social-reply-editor"),
        socialGenerateDraft: document.getElementById("social-generate-draft"),
        socialSaveDraft: document.getElementById("social-save-draft"),
        socialSkipItem: document.getElementById("social-skip-item"),
        socialSendReply: document.getElementById("social-send-reply"),
        agentStudioRefresh: document.getElementById("agent-studio-refresh"),
        agentStudioReloadRuntime: document.getElementById("agent-studio-reload-runtime"),
        agentStudioNewAgent: document.getElementById("agent-studio-new-agent"),
        agentStudioSaveAgent: document.getElementById("agent-studio-save-agent"),
        agentStudioDeleteAgent: document.getElementById("agent-studio-delete-agent"),
        agentStudioAgentCount: document.getElementById("agent-studio-agent-count"),
        agentStudioActiveCount: document.getElementById("agent-studio-active-count"),
        agentStudioCustomCount: document.getElementById("agent-studio-custom-count"),
        agentStudioErrorCount: document.getElementById("agent-studio-error-count"),
        agentStudioAgentList: document.getElementById("agent-studio-agent-list"),
        agentStudioErrors: document.getElementById("agent-studio-errors"),
        agentStudioPackList: document.getElementById("agent-studio-pack-list"),
        agentStudioPackPath: document.getElementById("agent-studio-pack-path"),
        agentStudioPackOverwrite: document.getElementById("agent-studio-pack-overwrite"),
        agentStudioPackPreviewBtn: document.getElementById("agent-studio-pack-preview-btn"),
        agentStudioPackInstallBtn: document.getElementById("agent-studio-pack-install-btn"),
        agentStudioPackPreview: document.getElementById("agent-studio-pack-preview"),
        agentStudioName: document.getElementById("agent-studio-name"),
        agentStudioType: document.getElementById("agent-studio-type"),
        agentStudioModelMode: document.getElementById("agent-studio-model-mode"),
        agentStudioModel: document.getElementById("agent-studio-model"),
        agentStudioModelHint: document.getElementById("agent-studio-model-hint"),
        agentStudioEnabled: document.getElementById("agent-studio-enabled"),
        agentStudioDescription: document.getElementById("agent-studio-description"),
        agentStudioPrompt: document.getElementById("agent-studio-prompt"),
        agentStudioToolSearch: document.getElementById("agent-studio-tool-search"),
        agentStudioToolList: document.getElementById("agent-studio-tool-list"),
        customToolNew: document.getElementById("custom-tool-new"),
        customToolSave: document.getElementById("custom-tool-save"),
        customToolList: document.getElementById("custom-tool-list"),
        customToolAiBrief: document.getElementById("custom-tool-ai-brief"),
        customToolAiGenerate: document.getElementById("custom-tool-ai-generate"),
        customToolAiConversation: document.getElementById("custom-tool-ai-conversation"),
        customToolName: document.getElementById("custom-tool-name"),
        customToolEnabled: document.getElementById("custom-tool-enabled"),
        customToolDescription: document.getElementById("custom-tool-description"),
        customToolParamsNote: document.getElementById("custom-tool-params-note"),
        customToolEnvVars: document.getElementById("custom-tool-env-vars"),
        customToolCode: document.getElementById("custom-tool-code"),
        customToolTestArgs: document.getElementById("custom-tool-test-args"),
        customToolTest: document.getElementById("custom-tool-test"),
        customToolTestResult: document.getElementById("custom-tool-test-result"),
        statsChart: document.getElementById("stats-chart"),
        toastRegion: document.getElementById("toast-region"),
    };

    bindEvents();
    initializePanel();
    window.addEventListener("unhandledrejection", (event) => {
        const reason = event.reason;
        const message = reason?.message || String(reason || "Bilinmeyen panel hatası");
        toast(`Panel işlemi tamamlanamadı: ${message}`, "error");
        event.preventDefault();
    });

    function resolveInitialApiBase() {
        const stored = localStorage.getItem(STORAGE_KEY);
        if (stored) {
            return stored;
        }
        if (window.location.protocol.startsWith("http")) {
            return `${window.location.origin}/api`;
        }
        return "http://localhost:8001/api";
    }

    function normalizeApiBase(value) {
        let normalized = (value || "").trim();
        if (!normalized) {
            return resolveInitialApiBase();
        }
        if (normalized.startsWith("/")) {
            normalized = `${window.location.origin}${normalized}`;
        }
        normalized = normalized.replace(/\/+$/, "");
        if (!normalized.endsWith("/api")) {
            normalized = `${normalized}/api`;
        }
        return normalized;
    }

    function bindEvents() {
        dom.apiBaseInput.value = state.apiBase;
        dom.activityTypeFilter.value = state.activityFilter;
        dom.heartbeatJobFilter.value = state.heartbeatJobFilter;
        dom.socialQueueFilter.value = state.social.filter;

        dom.navItems.forEach((item) => {
            item.addEventListener("click", () => switchTab(item.dataset.tab));
        });

        dom.memNavItems.forEach((item) => {
            item.addEventListener("click", () => switchMemTab(item.dataset.mem));
        });

        dom.srcTabs.forEach((item) => {
            item.addEventListener("click", () => switchSourceTab(item.dataset.src));
        });

        dom.customToolTabs.forEach((item) => {
            item.addEventListener("click", () => switchCustomToolTab(item.dataset.customTab));
        });

        dom.saveApiBase.addEventListener("click", connectApiBase);
        dom.apiBaseInput.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                connectApiBase();
            }
        });

        dom.refreshAll.addEventListener("click", async () => {
            try {
                await refreshActiveView();
                toast("Panel verileri yenilendi.", "success");
            } catch (error) {
                setConnectionState(`Yenileme başarısız: ${error.message}`, "error");
                toast(`Panel yenilenemedi: ${error.message}`, "error");
            }
        });

        dom.openEnvSettings.addEventListener("click", openEnvModal);
        dom.closeEnvModal.addEventListener("click", closeEnvModal);
        dom.reloadEnvContent.addEventListener("click", () => loadEnvContent(dom.envTargetSelect.value, true));
        dom.saveEnvContent.addEventListener("click", saveEnvContent);
        dom.envTargetSelect.addEventListener("change", () => loadEnvContent(dom.envTargetSelect.value, true));

        dom.approvalBadge.addEventListener("click", () => {
            const current = state.pendingActions.find((item) => item.id === state.pendingActionId) || state.pendingActions[0];
            if (current) {
                openApprovalModal(current);
            }
        });

        dom.btnApprove.addEventListener("click", () => decideAction("approve"));
        dom.btnReject.addEventListener("click", () => decideAction("reject"));

        dom.savePersona.addEventListener("click", savePersona);
        dom.btnAddMem.addEventListener("click", addMemoryEntry);
        dom.activityTypeFilter.addEventListener("change", () => {
            state.activityFilter = dom.activityTypeFilter.value;
            renderLogs(state.logs);
        });
        dom.activitySearch.addEventListener("input", () => {
            state.activitySearch = dom.activitySearch.value.trim().toLowerCase();
            renderLogs(state.logs);
        });

        dom.refreshTree.addEventListener("click", fetchWorkspaceTree);
        dom.workspaceSearch.addEventListener("input", () => {
            state.workspaceSearch = dom.workspaceSearch.value.trim().toLowerCase();
            renderTree(state.workspaceNodes || []);
        });
        dom.copyFilePath.addEventListener("click", copySelectedFilePath);
        dom.fileSearchInput.addEventListener("input", renderFileSearchResults);
        dom.clearFileSearch.addEventListener("click", () => {
            dom.fileSearchInput.value = "";
            renderFileSearchResults();
        });

        dom.btnAddSource.addEventListener("click", () => dom.sourceModal.classList.remove("hidden"));
        dom.closeSourceModal.addEventListener("click", () => dom.sourceModal.classList.add("hidden"));
        dom.sourceModal.addEventListener("click", (event) => {
            if (event.target === dom.sourceModal) {
                dom.sourceModal.classList.add("hidden");
            }
        });
        dom.envModal.addEventListener("click", (event) => {
            if (event.target === dom.envModal) {
                closeEnvModal();
            }
        });
        dom.approvalModal.addEventListener("click", (event) => {
            if (event.target === dom.approvalModal) {
                dom.approvalModal.classList.add("hidden");
            }
        });
        dom.fileInput.addEventListener("change", syncSelectedFile);
        dom.dropZone.addEventListener("click", () => dom.fileInput.click());
        dom.dropZone.addEventListener("dragover", (event) => {
            event.preventDefault();
            dom.dropZone.classList.add("dragover");
        });
        dom.dropZone.addEventListener("dragleave", () => dom.dropZone.classList.remove("dragover"));
        dom.dropZone.addEventListener("drop", (event) => {
            event.preventDefault();
            dom.dropZone.classList.remove("dragover");
            if (event.dataTransfer.files.length > 0) {
                state.pendingUploadFile = event.dataTransfer.files[0];
                syncSelectedFile();
            }
        });

        dom.btnUpload.addEventListener("click", uploadSelectedFile);
        dom.btnAddUrl.addEventListener("click", addUrlTarget);
        dom.btnAddText.addEventListener("click", addTextTarget);

        dom.reloadSkills.addEventListener("click", reloadSkills);
        dom.heartbeatEnable.addEventListener("click", () => toggleHeartbeat(true));
        dom.heartbeatDisable.addEventListener("click", () => toggleHeartbeat(false));
        dom.heartbeatReload.addEventListener("click", reloadHeartbeatScheduler);
        dom.saveHeartbeat.addEventListener("click", saveHeartbeatConfig);
        dom.heartbeatJobFilter.addEventListener("change", () => {
            state.heartbeatJobFilter = dom.heartbeatJobFilter.value;
            renderHeartbeat();
        });
        dom.heartbeatEditor.addEventListener("input", () => {
            state.heartbeatDirty = true;
        });
        dom.heartbeatJobList.addEventListener("click", (event) => {
            const button = event.target.closest("[data-heartbeat-action]");
            if (!button) {
                return;
            }
            handleHeartbeatJobAction(
                button.dataset.heartbeatJobId,
                button.dataset.heartbeatAction
            );
        });
        dom.launchBrowserVisible.addEventListener("click", () => launchSocialBrowser(false));
        dom.refreshSocial.addEventListener("click", async () => {
            await fetchSocialSnapshot();
            toast("Sosyal kuyruk yenilendi.", "success");
        });
        dom.scanSocial.addEventListener("click", scanSocialPage);
        dom.socialQueueFilter.addEventListener("change", () => {
            state.social.filter = dom.socialQueueFilter.value;
            renderSocial({ browser: state.social.browser, queue: state.social.queue });
        });
        dom.socialQueueSearch.addEventListener("input", () => {
            state.social.search = dom.socialQueueSearch.value.trim().toLowerCase();
            renderSocial({ browser: state.social.browser, queue: state.social.queue });
        });
        dom.socialGenerateDraft.addEventListener("click", generateSocialDraft);
        dom.socialSaveDraft.addEventListener("click", saveSocialDraft);
        dom.socialSkipItem.addEventListener("click", skipSocialItem);
        dom.socialSendReply.addEventListener("click", sendSocialReply);
        dom.socialReplyEditor.addEventListener("input", () => {
            state.social.editorDirty = true;
            updateReplyCounter();
        });
        dom.socialQueueList.addEventListener("click", (event) => {
            const item = event.target.closest("[data-social-queue-id]");
            if (!item) {
                return;
            }
            selectSocialItem(item.dataset.socialQueueId);
        });

        dom.agentStudioRefresh.addEventListener("click", async () => {
            await fetchAgentStudioCatalog({ silent: false });
            toast("Agent Studio kataloğu yenilendi.", "success");
        });
        dom.agentStudioReloadRuntime.addEventListener("click", reloadAgentStudioRuntime);
        dom.agentStudioNewAgent.addEventListener("click", () => {
            state.agentStudio.selectedAgentName = "__new__";
            state.agentStudio.editorDirty = false;
            renderAgentStudioEditor(null, true);
            renderAgentStudioToolList(null);
        });
        dom.agentStudioSaveAgent.addEventListener("click", saveAgentStudioAgent);
        dom.agentStudioDeleteAgent.addEventListener("click", deleteAgentStudioAgent);
        dom.agentStudioPackPreviewBtn.addEventListener("click", previewAgentStudioPack);
        dom.agentStudioPackInstallBtn.addEventListener("click", installAgentStudioPack);
        dom.agentStudioPackPath.addEventListener("input", () => {
            state.agentStudio.packPath = dom.agentStudioPackPath.value;
        });
        dom.agentStudioToolSearch.addEventListener("input", () => {
            state.agentStudio.toolSearch = dom.agentStudioToolSearch.value.trim().toLowerCase();
            const agent = getSelectedStudioAgent();
            renderAgentStudioToolList(agent);
        });
        [
            dom.agentStudioName,
            dom.agentStudioType,
            dom.agentStudioModelMode,
            dom.agentStudioModel,
            dom.agentStudioEnabled,
            dom.agentStudioDescription,
            dom.agentStudioPrompt,
        ].forEach((input) => {
            input.addEventListener("input", () => {
                state.agentStudio.editorDirty = true;
                if (input === dom.agentStudioType || input === dom.agentStudioModelMode) {
                    renderAgentStudioToolList(getSelectedStudioAgent());
                    syncAgentStudioModelControls(getSelectedStudioAgent());
                }
            });
            input.addEventListener("change", () => {
                state.agentStudio.editorDirty = true;
                if (input === dom.agentStudioType || input === dom.agentStudioModelMode) {
                    renderAgentStudioToolList(getSelectedStudioAgent());
                    syncAgentStudioModelControls(getSelectedStudioAgent());
                }
            });
        });
        dom.agentStudioAgentList.addEventListener("click", (event) => {
            const item = event.target.closest("[data-agent-studio-select]");
            if (!item) {
                return;
            }
            selectAgentStudioAgent(item.dataset.agentStudioSelect);
        });
        dom.agentStudioPackList.addEventListener("click", (event) => {
            const item = event.target.closest("[data-agent-pack-select]");
            if (!item) {
                return;
            }
            const path = item.dataset.agentPackPath || "";
            state.agentStudio.packPath = path;
            dom.agentStudioPackPath.value = path;
        });
        dom.agentStudioToolList.addEventListener("change", (event) => {
            if (event.target.matches("input[type='checkbox']")) {
                if (event.target.checked) {
                    state.agentStudio.selectedToolNames.add(event.target.value);
                } else {
                    state.agentStudio.selectedToolNames.delete(event.target.value);
                }
                state.agentStudio.editorDirty = true;
            }
        });
        dom.customToolNew.addEventListener("click", () => {
            state.agentStudio.selectedCustomToolName = "__new__";
            state.agentStudio.customDirty = false;
            renderCustomToolEditor(null, true);
        });
        dom.customToolAiGenerate.addEventListener("click", generateCustomToolWithAi);
        dom.customToolSave.addEventListener("click", saveCustomTool);
        dom.customToolTest.addEventListener("click", testCustomTool);
        dom.customToolList.addEventListener("click", (event) => {
            const item = event.target.closest("[data-custom-tool-select]");
            if (!item) {
                return;
            }
            selectCustomTool(item.dataset.customToolSelect);
        });
        [
            dom.customToolName,
            dom.customToolEnabled,
            dom.customToolDescription,
            dom.customToolParamsNote,
            dom.customToolAiBrief,
            dom.customToolEnvVars,
            dom.customToolCode,
            dom.customToolTestArgs,
        ].forEach((input) => {
            input.addEventListener("input", () => {
                state.agentStudio.customDirty = true;
            });
            input.addEventListener("change", () => {
                state.agentStudio.customDirty = true;
            });
        });

        dom.fileTree.addEventListener("click", async (event) => {
            const node = event.target.closest("[data-tree-path]");
            if (!node) {
                return;
            }

            const { treePath, treeType, treeName } = node.dataset;
            if (treeType === "directory") {
                if (state.expandedDirs.has(treePath)) {
                    state.expandedDirs.delete(treePath);
                } else {
                    state.expandedDirs.add(treePath);
                }
                await fetchWorkspaceTree({ silent: true });
                return;
            }

            await loadFile(treePath, treeName);
        });

        dom.submodelsContainer.addEventListener("click", async (event) => {
            const button = event.target.closest("[data-agent-toggle]");
            if (!button) {
                return;
            }

            await apiRequest(`/agents/${encodeURIComponent(button.dataset.agentToggle)}/toggle`, {
                method: "POST",
            });
            toast("Ajan durumu güncellendi.", "success");
            await fetchBootstrap();
        });

        document.addEventListener("click", handleToolToggle);

        dom.pendingActionsList.addEventListener("click", (event) => {
            const button = event.target.closest("[data-open-approval]");
            if (!button) {
                return;
            }
            const action = state.pendingActions.find((item) => item.id === button.dataset.openApproval);
            if (action) {
                openApprovalModal(action);
            }
        });

        dom.skillsList.addEventListener("click", async (event) => {
            const button = event.target.closest("[data-skill-toggle]");
            if (!button) {
                return;
            }
            await toggleSkill(button.dataset.skillToggle);
        });

        document.addEventListener("visibilitychange", async () => {
            if (!document.hidden) {
                await refreshActiveView({ silent: true });
            }
        });
    }

    async function initializePanel() {
        renderFileMeta();
        renderFileSearchResults();
        updateReplyCounter();
        try {
            await refreshActiveView({ silent: true });
        } catch (error) {
            setConnectionState(`İlk senkron başarısız: ${error.message}`, "error");
            toast(`İlk bağlantı kurulamadı: ${error.message}`, "error");
        }
        window.setInterval(async () => {
            if (document.hidden) {
                return;
            }
            try {
                await refreshActiveView({ silent: true });
            } catch (error) {
                setConnectionState(`Arka plan senkronu başarısız: ${error.message}`, "error");
            }
        }, DEFAULT_POLL_MS);
    }

    async function connectApiBase() {
        const previous = state.apiBase;
        const nextBase = normalizeApiBase(dom.apiBaseInput.value);
        state.apiBase = nextBase;
        dom.apiBaseInput.value = nextBase;

        try {
            await fetchBootstrap();
            localStorage.setItem(STORAGE_KEY, nextBase);
            toast("API bağlantısı güncellendi.", "success");
        } catch (error) {
            state.apiBase = previous;
            dom.apiBaseInput.value = previous;
            setConnectionState(`Bağlantı başarısız: ${error.message}`, "error");
            toast(`API bağlantısı kurulamadı: ${error.message}`, "error");
        }
    }

    async function openEnvModal() {
        dom.envModal.classList.remove("hidden");
        if (!state.env.loaded) {
            await loadEnvContent(state.env.target || dom.envTargetSelect.value || ".env", true);
        }
    }

    function closeEnvModal() {
        dom.envModal.classList.add("hidden");
    }

    async function apiRequest(path, options = {}) {
        const controller = new AbortController();
        const timeoutId = window.setTimeout(() => controller.abort(), options.timeout ?? 12000);
        const headers = new Headers(options.headers || {});
        const config = {
            method: options.method || "GET",
            headers,
            signal: controller.signal,
        };

        if (options.body !== undefined) {
            if (options.body instanceof FormData) {
                config.body = options.body;
            } else if (typeof options.body === "string") {
                config.body = options.body;
                if (!headers.has("Content-Type")) {
                    headers.set("Content-Type", "text/plain;charset=UTF-8");
                }
            } else {
                config.body = JSON.stringify(options.body);
                if (!headers.has("Content-Type")) {
                    headers.set("Content-Type", "application/json");
                }
            }
        }

        try {
            const response = await fetch(`${state.apiBase}${path}`, config);
            const contentType = response.headers.get("content-type") || "";
            const payload = contentType.includes("application/json")
                ? await response.json()
                : await response.text();

            if (!response.ok) {
                const rawDetail = typeof payload === "string"
                    ? payload
                    : payload.detail ?? payload.message ?? "Bilinmeyen API hatası";
                const message = typeof rawDetail === "string"
                    ? rawDetail
                    : rawDetail.message
                        || [rawDetail.busy_owner, rawDetail.busy_label].filter(Boolean).join(" • ")
                        || JSON.stringify(rawDetail);
                throw new Error(message);
            }

            return payload;
        } catch (error) {
            if (error.name === "AbortError") {
                throw new Error("İstek zaman aşımına uğradı.");
            }
            throw error;
        } finally {
            window.clearTimeout(timeoutId);
        }
    }

    async function loadEnvContent(target = ".env", showToast = false) {
        try {
            const payload = await apiRequest(`/env?target=${encodeURIComponent(target)}`);
            state.env.target = payload.target || target;
            state.env.content = payload.content || "";
            state.env.loaded = true;
            dom.envTargetSelect.value = state.env.target;
            dom.envEditor.value = state.env.content;
            dom.envFileMeta.textContent = payload.exists
                ? `${payload.path} yüklendi`
                : `${payload.path} henüz yok, kaydedince oluşturulacak`;
            if (showToast) {
                toast(`${state.env.target} yüklendi.`, "success");
            }
        } catch (error) {
            dom.envFileMeta.textContent = `Env dosyası yüklenemedi: ${error.message}`;
            toast(`Env dosyası yüklenemedi: ${error.message}`, "error");
        }
    }

    async function saveEnvContent() {
        try {
            await apiRequest("/env", {
                method: "POST",
                body: JSON.stringify({
                    target: dom.envTargetSelect.value,
                    content: dom.envEditor.value,
                }),
            });
            state.env.target = dom.envTargetSelect.value;
            state.env.content = dom.envEditor.value;
            state.env.loaded = true;
            toast(`${state.env.target} kaydedildi.`, "success");
            await fetchBootstrap({ silent: true });
            await loadEnvContent(state.env.target, false);
        } catch (error) {
            toast(`Env kaydedilemedi: ${error.message}`, "error");
        }
    }

    async function refreshActiveView({ silent = false } = {}) {
        await fetchBootstrap({ silent });
        if (state.activeTab === "memory") {
            await loadMemoryTab({ silent: true });
        }
        if (state.activeTab === "workspace") {
            await fetchWorkspaceTree({ silent: true });
        }
        if (state.activeTab === "automation") {
            await fetchHeartbeatConfig({ silent: true });
            await fetchSocialSnapshot({ silent: true });
        }
        if (state.activeTab === "agent-studio") {
            await fetchAgentStudioCatalog({ silent: true });
        }
    }

    async function fetchBootstrap({ silent = false } = {}) {
        const payload = await apiRequest("/panel/bootstrap");
        state.system = payload.system || null;
        state.hierarchy = payload.hierarchy || { tools: [], submodels: [] };
        state.logs = payload.logs || [];
        state.stats = payload.stats || [];
        state.pendingActions = payload.pending_actions || [];
        state.skills = payload.skills || [];
        state.heartbeat = {
            config: payload.heartbeat || null,
            status: payload.heartbeat_status || null,
            jobs: payload.heartbeat_jobs || [],
        };
        state.social.browser = payload.social?.browser || null;
        state.social.queue = payload.social?.queue || { items: [] };
        state.agentStudio.catalog = payload.agent_studio || state.agentStudio.catalog;

        if (!state.heartbeatDirty && payload.heartbeat && typeof payload.heartbeat.content === "string") {
            dom.heartbeatEditor.value = payload.heartbeat.content;
        }

        renderSystem(payload.system);
        renderHierarchy(payload.hierarchy);
        renderLogs(payload.logs);
        renderPendingActions(payload.pending_actions);
        renderSummary(payload.hierarchy, payload.skills, payload.pending_actions);
        renderStatsChart(payload.stats);
        renderSkills(payload.skills);
        renderHeartbeat();
        renderSocial(payload.social || { browser: null, queue: { items: [] } });
        renderAgentStudio();
        markSync();

        if (!silent) {
            setConnectionState("API senkronize edildi.", "success");
        }
    }

    function renderSystem(system) {
        if (!system) {
            setConnectionState("API cevap vermiyor.", "error");
            updateStatusChip(dom.sidebarSystemChip, "Offline", false);
            updateStatusChip(dom.heroSystemPill, "Offline", false);
            dom.sidebarModel.textContent = "Model bilgisi yok";
            dom.sidebarUptime.textContent = "Uptime bilgisi henüz yok";
            dom.metricModel.textContent = "-";
            dom.metricUptime.textContent = "-";
            return;
        }

        const isOnline = system.status === "Online";
        const uptime = formatUptime(system.uptime || 0);

        updateStatusChip(dom.sidebarSystemChip, system.status, isOnline);
        updateStatusChip(dom.heroSystemPill, system.status, isOnline);
        dom.sidebarModel.textContent = system.model || "Model bilgisi yok";
        dom.sidebarUptime.textContent = `Uptime: ${uptime}`;
        dom.metricModel.textContent = system.model || "-";
        dom.metricUptime.textContent = uptime;

        setConnectionState(
            isOnline ? `Bağlı: ${state.apiBase}` : "Sistem offline görünüyor.",
            isOnline ? "success" : "warning"
        );
    }

    function renderSummary(hierarchy, skills, pendingActions) {
        const agents = hierarchy?.submodels || [];
        const rootTools = hierarchy?.tools || [];
        const allTools = rootTools.concat(...agents.map((agent) => agent.tools || []));
        const activeAgents = agents.filter((agent) => agent.active).length;
        const activeTools = allTools.filter((tool) => tool.active).length;
        const summaryItems = [
            { label: "Ajan", value: `${activeAgents}/${agents.length || 0}`, tone: "teal" },
            { label: "Aktif Tool", value: `${activeTools}/${allTools.length || 0}`, tone: "amber" },
            { label: "Skill", value: `${skills?.length || 0}`, tone: "slate" },
            { label: "Approval", value: `${pendingActions?.length || 0}`, tone: "rose" },
        ];

        dom.metricApprovals.textContent = `${pendingActions?.length || 0}`;
        dom.summaryGrid.innerHTML = "";

        summaryItems.forEach((item) => {
            const card = document.createElement("div");
            card.className = `summary-item tone-${item.tone}`;
            const label = document.createElement("span");
            label.textContent = item.label;
            const value = document.createElement("strong");
            value.textContent = item.value;
            card.append(label, value);
            dom.summaryGrid.appendChild(card);
        });
    }

    function renderHierarchy(hierarchy) {
        dom.basemodelTools.innerHTML = "";
        dom.submodelsContainer.innerHTML = "";

        (hierarchy?.tools || []).forEach((tool) => {
            dom.basemodelTools.appendChild(createToolPill(tool));
        });

        (hierarchy?.submodels || []).forEach((agent) => {
            const card = document.createElement("article");
            card.className = `agent-card ${agent.active ? "" : "is-inactive"}`;

            const head = document.createElement("div");
            head.className = "agent-card-head";

            const icon = document.createElement("span");
            icon.className = "node-mark";
            icon.textContent = resolveAgentIcon(agent.name);

            const textWrap = document.createElement("div");
            const title = document.createElement("h4");
            title.textContent = agent.name;
            const subtitle = document.createElement("p");
            const parts = [agent.active ? "Aktif durumda" : "Şu anda pasif"];
            if (agent.model) {
                parts.push(agent.model);
            }
            if (typeof agent.tool_count === "number") {
                parts.push(`${agent.tool_count} tool`);
            }
            subtitle.textContent = parts.join(" • ");
            textWrap.append(title, subtitle);

            if (agent.desc) {
                textWrap.title = agent.desc;
            }

            const toggle = document.createElement("button");
            toggle.className = `toggle-pill ${agent.active ? "is-active" : ""}`;
            toggle.type = "button";
            toggle.dataset.agentToggle = agent.name;
            toggle.textContent = agent.active ? "Aktif" : "Pasif";

            head.append(icon, textWrap, toggle);

            const tools = document.createElement("div");
            tools.className = "tool-cloud";
            (agent.tools || []).forEach((tool) => {
                tools.appendChild(createToolPill(tool));
            });

            card.append(head, tools);
            dom.submodelsContainer.appendChild(card);
        });
    }

    function createToolPill(tool) {
        const wrapper = document.createElement("div");
        wrapper.className = `tool-pill ${tool.active ? "" : "is-inactive"}`;

        const label = document.createElement("span");
        label.textContent = tool.name;

        const button = document.createElement("button");
        button.className = `toggle-dot ${tool.active ? "is-active" : ""}`;
        button.type = "button";
        button.dataset.toolToggle = tool.name;
        button.setAttribute("aria-label", `${tool.name} durumunu değiştir`);

        wrapper.append(label, button);
        return wrapper;
    }

    async function handleToolToggle(event) {
        const button = event.target.closest("[data-tool-toggle]");
        if (!button) {
            return;
        }
        await apiRequest(`/tools/${encodeURIComponent(button.dataset.toolToggle)}/toggle`, {
            method: "POST",
        });
        toast("Tool durumu güncellendi.", "success");
        await fetchBootstrap({ silent: true });
    }

    function getStudioCatalog() {
        return state.agentStudio.catalog || {
            agents: [],
            tools: [],
            custom_tools: [],
            packs: [],
            errors: [],
            recommended_memory_tools: [],
        };
    }

    function getSelectedStudioAgent() {
        const catalog = getStudioCatalog();
        if (!state.agentStudio.selectedAgentName || state.agentStudio.selectedAgentName === "__new__") {
            return null;
        }
        return (catalog.agents || []).find((agent) => agent.name === state.agentStudio.selectedAgentName) || null;
    }

    function getSelectedCustomTool() {
        const catalog = getStudioCatalog();
        if (!state.agentStudio.selectedCustomToolName || state.agentStudio.selectedCustomToolName === "__new__") {
            return null;
        }
        return (catalog.custom_tools || []).find((tool) => tool.name === state.agentStudio.selectedCustomToolName) || null;
    }

    function getHierarchyAgent(name) {
        if (!name) {
            return null;
        }
        return (state.hierarchy?.submodels || []).find((agent) => agent.name === name) || null;
    }

    async function fetchAgentStudioCatalog({ silent = false } = {}) {
        const payload = await apiRequest("/agent-studio/catalog");
        state.agentStudio.catalog = payload;
        renderAgentStudio();
        if (!silent) {
            setConnectionState("Agent Studio kataloğu senkronize edildi.", "success");
        }
        return payload;
    }

    function renderAgentStudio() {
        const catalog = getStudioCatalog();
        const agents = catalog.agents || [];
        const customTools = catalog.custom_tools || [];

        if (!state.agentStudio.selectedAgentName && !state.agentStudio.editorDirty && agents.length > 0) {
            state.agentStudio.selectedAgentName = agents[0].name;
        }
        if (!state.agentStudio.selectedCustomToolName && !state.agentStudio.customDirty && customTools.length > 0) {
            state.agentStudio.selectedCustomToolName = customTools[0].name;
        }

        renderAgentStudioOverview(catalog);
        renderAgentStudioAgentList(catalog);
        renderAgentStudioErrors(catalog.errors || []);
        renderAgentStudioPackSurface(catalog);

        const selectedAgent = getSelectedStudioAgent();
        if (!state.agentStudio.editorDirty) {
            renderAgentStudioEditor(selectedAgent, false);
        } else {
            renderAgentStudioToolList(selectedAgent);
        }

        renderCustomToolList(catalog);
        const selectedCustomTool = getSelectedCustomTool();
        if (!state.agentStudio.customDirty) {
            renderCustomToolEditor(selectedCustomTool, false);
        }
    }

    function renderAgentStudioOverview(catalog) {
        const agents = catalog.agents || [];
        const customTools = catalog.custom_tools || [];
        const activeAgents = agents.filter((agent) => agent.enabled).length;
        const visibleErrors = (catalog.errors || []).length
            + customTools.filter((tool) => Boolean(tool.error)).length;

        if (dom.agentStudioAgentCount) {
            dom.agentStudioAgentCount.textContent = String(agents.length);
        }
        if (dom.agentStudioActiveCount) {
            dom.agentStudioActiveCount.textContent = String(activeAgents);
        }
        if (dom.agentStudioCustomCount) {
            dom.agentStudioCustomCount.textContent = String(customTools.length);
        }
        if (dom.agentStudioErrorCount) {
            dom.agentStudioErrorCount.textContent = String(visibleErrors);
        }
    }

    function renderAgentStudioAgentList(catalog) {
        const agents = catalog.agents || [];
        dom.agentStudioAgentList.innerHTML = "";
        if (agents.length === 0) {
            dom.agentStudioAgentList.innerHTML = '<div class="empty-copy">Agent config bulunamadı.</div>';
            return;
        }

        agents.forEach((agent) => {
            const row = document.createElement("button");
            row.type = "button";
            row.className = `studio-list-item ${state.agentStudio.selectedAgentName === agent.name ? "is-selected" : ""}`;
            row.dataset.agentStudioSelect = agent.name;

            const content = document.createElement("div");
            const title = document.createElement("strong");
            title.textContent = agent.name;
            const meta = document.createElement("p");
            const runtimeAgent = getHierarchyAgent(agent.name);
            const parts = [agent.type || "config", agent.enabled ? "aktif" : "pasif"];
            if (agent.model) {
                parts.push(`config:${agent.model}`);
            }
            if (runtimeAgent?.model) {
                parts.push(`runtime:${runtimeAgent.model}`);
            }
            parts.push(`${agentSelectedToolNames(agent, catalog).length} tool`);
            meta.textContent = parts.join(" • ");
            content.append(title, meta);

            const badge = document.createElement("span");
            badge.className = `risk-badge ${agent.type === "builtin" ? "risk-medium" : "risk-low"}`;
            badge.textContent = agent.type || "config";
            row.append(content, badge);
            dom.agentStudioAgentList.appendChild(row);
        });
    }

    function renderAgentStudioErrors(errors) {
        dom.agentStudioErrors.innerHTML = "";
        const visibleErrors = (errors || []).slice(0, 8);
        if (visibleErrors.length === 0) {
            return;
        }
        visibleErrors.forEach((error) => {
            const item = document.createElement("div");
            item.className = "studio-error";
            const scope = error.scope || "agent_studio";
            const name = error.name ? `:${error.name}` : "";
            item.textContent = `${scope}${name} • ${error.message || error}`;
            dom.agentStudioErrors.appendChild(item);
        });
    }

    function buildPackPreviewText(preview) {
        if (!preview) {
            return "Pack önizlemesi burada görünecek.";
        }
        const lines = [
            `${preview.name} • ${preview.type} • v${preview.version || "0.1.0"}`,
            preview.description || "Açıklama yok.",
            `Kurulabilir: ${preview.installable ? "evet" : "hayır"}`,
            `Agent: ${(preview.agents || []).length} • Tool: ${(preview.tools || []).length}`,
        ];
        if (preview.warnings?.length) {
            lines.push("", "Uyarılar:");
            preview.warnings.slice(0, 8).forEach((warning) => lines.push(`- ${warning}`));
        }
        if (preview.errors?.length) {
            lines.push("", "Hatalar:");
            preview.errors.slice(0, 8).forEach((error) => lines.push(`- ${error}`));
        }
        const tools = preview.tools || [];
        if (tools.length) {
            lines.push("", "Tool'lar:");
            tools.slice(0, 8).forEach((tool) => {
                lines.push(`- ${tool.name} • ${tool.export_ok ? "ok" : "hata"}${tool.error ? ` • ${tool.error}` : ""}`);
            });
        }
        const agents = preview.agents || [];
        if (agents.length) {
            lines.push("", "Agent'lar:");
            agents.slice(0, 8).forEach((agent) => {
                lines.push(`- ${agent.name} • ${agent.type} • ${agent.model || "default"} • ${Array.isArray(agent.tools) ? agent.tools.length : 0} tool`);
            });
        }
        return lines.join("\n");
    }

    function renderAgentStudioPackSurface(catalog) {
        const packs = catalog.packs || [];
        dom.agentStudioPackList.innerHTML = "";
        if (!state.agentStudio.packPath) {
            const firstPackPath = packs[0]?.source_path || packs[0]?.installed_path || "";
            const samplePackPath = catalog.paths?.agent_packs_dir
                ? `${catalog.paths.agent_packs_dir.replace(/\/+$/, "")}/ornek_haber_bundle`
                : "";
            if (firstPackPath) {
                state.agentStudio.packPath = firstPackPath;
            } else if (samplePackPath) {
                state.agentStudio.packPath = samplePackPath;
            }
        }
        dom.agentStudioPackPath.value = state.agentStudio.packPath || "";

        if (packs.length === 0) {
            dom.agentStudioPackList.innerHTML = '<div class="empty-copy">Henüz yüklü pack yok.</div>';
        } else {
            packs.forEach((pack) => {
                const row = document.createElement("button");
                row.type = "button";
                row.className = "studio-list-item";
                row.dataset.agentPackSelect = pack.name;
                row.dataset.agentPackPath = pack.source_path || pack.installed_path || "";

                const content = document.createElement("div");
                const title = document.createElement("strong");
                title.textContent = pack.name;
                const meta = document.createElement("p");
                meta.textContent = `${pack.type || "agent_bundle"} • v${pack.version || "0.1.0"}`;
                const extra = document.createElement("div");
                extra.className = "pack-list-meta";
                extra.textContent = `${(pack.installed_agents || []).length} agent • ${(pack.installed_tools || []).length} tool`;
                content.append(title, meta, extra);

                const badge = document.createElement("span");
                badge.className = "risk-badge risk-low";
                badge.textContent = "pack";
                row.append(content, badge);
                dom.agentStudioPackList.appendChild(row);
            });
        }

        dom.agentStudioPackPreview.classList.toggle("empty-copy", !state.agentStudio.packPreview);
        dom.agentStudioPackPreview.textContent = buildPackPreviewText(state.agentStudio.packPreview);
    }

    function renderAgentStudioEditor(agent, force = false) {
        if (state.agentStudio.editorDirty && !force) {
            return;
        }
        const isNew = !agent;
        const initialTools = agent
            ? agentSelectedToolNames(agent, getStudioCatalog())
            : getStudioCatalog().recommended_memory_tools || [];
        const promptPlaceholder = agent?.system_prompt_placeholder
            || getStudioCatalog().default_config_system_prompt_placeholder
            || "Agent rolünü ve çalışma kurallarını yaz...";
        state.agentStudio.selectedToolNames = new Set(initialTools);
        dom.agentStudioName.value = agent?.name || "";
        dom.agentStudioName.disabled = !isNew;
        dom.agentStudioType.value = agent?.type || "config";
        dom.agentStudioType.disabled = !isNew;
        dom.agentStudioEnabled.checked = agent?.enabled ?? true;
        dom.agentStudioDescription.value = agent?.description || "";
        dom.agentStudioPrompt.value = agent?.system_prompt || "";
        dom.agentStudioPrompt.placeholder = promptPlaceholder;
        dom.agentStudioDeleteAgent.disabled = isNew || agent?.type === "builtin";
        syncAgentStudioModelControls(agent);
        renderAgentStudioToolList(agent);
    }

    function resolveAgentStudioModelConfig(agent) {
        const configured = (agent?.model || "default").trim() || "default";
        if (configured === "default" || configured === "browser_default") {
            return { mode: configured, customModel: "" };
        }
        return { mode: "custom", customModel: configured };
    }

    function forceValidModelMode(mode, agentType) {
        if (mode === "browser_default" && agentType !== "builtin") {
            return "default";
        }
        if (mode === "custom" || mode === "default" || mode === "browser_default") {
            return mode;
        }
        return "default";
    }

    function syncAgentStudioModelControls(agent = getSelectedStudioAgent()) {
        const typeValue = dom.agentStudioType.value || agent?.type || "config";
        const { mode, customModel } = resolveAgentStudioModelConfig(agent);
        const runtimeAgent = getHierarchyAgent(agent?.name);
        const editorMode = dom.agentStudioModelMode.value || mode;
        const editorCustomModel = dom.agentStudioModel.value.trim();

        Array.from(dom.agentStudioModelMode.options).forEach((option) => {
            option.hidden = false;
            option.disabled = false;
        });

        const browserOption = Array.from(dom.agentStudioModelMode.options).find((option) => option.value === "browser_default");
        if (browserOption) {
            const allowBrowserDefault = typeValue === "builtin" || mode === "browser_default";
            browserOption.hidden = !allowBrowserDefault;
            browserOption.disabled = !allowBrowserDefault;
        }

        const selectedMode = forceValidModelMode(
            state.agentStudio.editorDirty ? editorMode : mode,
            typeValue
        );
        const selectedCustomModel = state.agentStudio.editorDirty ? editorCustomModel : customModel;
        const effectiveModel = runtimeAgent?.model || (
            selectedMode === "custom" ? (selectedCustomModel || agent?.model || "default") : selectedMode
        );
        dom.agentStudioModelMode.value = selectedMode;
        dom.agentStudioModel.value = selectedMode === "custom" ? selectedCustomModel : "";
        dom.agentStudioModel.disabled = selectedMode !== "custom";
        dom.agentStudioModel.placeholder = selectedMode === "custom"
            ? "ornek: gemini-3.1-flash-lite-preview"
            : "Custom Model secildiginde aktif olur";

        const hintParts = [`Efektif runtime modeli: ${effectiveModel}`];
        if (selectedMode === "default") {
            hintParts.push("Subagent varsayilani kullanilir");
        } else if (selectedMode === "browser_default") {
            hintParts.push("Browser varsayilani kullanilir");
        } else {
            hintParts.push("Kaydedilince custom override uygulanir");
        }
        dom.agentStudioModelHint.textContent = hintParts.join(" • ");
    }

    function currentCheckedStudioTools() {
        return new Set(state.agentStudio.selectedToolNames || []);
    }

    function agentSelectedToolNames(agent, catalog = getStudioCatalog()) {
        if (!agent) {
            return [];
        }
        if (agent.type === "builtin") {
            if (agent.tool_mode === "custom") {
                return agent.tools || [];
            }
            return (catalog.tools || [])
                .filter((tool) => (tool.groups || []).includes(agent.name))
                .map((tool) => tool.name);
        }
        return agent.tools || [];
    }

    function renderAgentStudioToolList(agent) {
        const catalog = getStudioCatalog();
        const query = state.agentStudio.toolSearch;
        const recommended = new Set(catalog.recommended_memory_tools || []);
        let selected = currentCheckedStudioTools();
        if (!state.agentStudio.editorDirty && agent) {
            selected = new Set(agentSelectedToolNames(agent, catalog));
            state.agentStudio.selectedToolNames = new Set(selected);
        } else if (!agent && selected.size === 0) {
            selected = new Set(recommended);
            state.agentStudio.selectedToolNames = new Set(selected);
        }

        const tools = (catalog.tools || []).filter((tool) => {
            if (!query) {
                return true;
            }
            return `${tool.name} ${tool.description || ""} ${tool.category || ""}`.toLowerCase().includes(query);
        });

        dom.agentStudioToolList.innerHTML = "";
        if (tools.length === 0) {
            dom.agentStudioToolList.innerHTML = '<div class="empty-copy">Filtreye uygun tool yok.</div>';
            return;
        }

        tools.forEach((tool) => {
            const label = document.createElement("label");
            label.className = `tool-check risk-${tool.risk || "low"} ${tool.active ? "" : "is-inactive"}`;

            const checkbox = document.createElement("input");
            checkbox.type = "checkbox";
            checkbox.value = tool.name;
            checkbox.checked = selected.has(tool.name);
            checkbox.disabled = !tool.active;

            const text = document.createElement("span");
            const name = document.createElement("strong");
            name.textContent = tool.name;
            const meta = document.createElement("small");
            const metaParts = [tool.category || "tool", tool.risk || "low"];
            if (tool.source === "custom") {
                metaParts.push("custom");
            }
            if (tool.recommended) {
                metaParts.push("önerilen hafıza");
            }
            meta.textContent = metaParts.join(" • ");
            text.append(name, meta);

            label.append(checkbox, text);
            if (tool.description) {
                label.title = tool.description;
            }
            dom.agentStudioToolList.appendChild(label);
        });
    }

    function selectAgentStudioAgent(name) {
        state.agentStudio.selectedAgentName = name;
        state.agentStudio.editorDirty = false;
        const agent = getSelectedStudioAgent();
        renderAgentStudioEditor(agent, true);
        renderAgentStudio();
    }

    function collectAgentStudioPayload() {
        const selectedMode = forceValidModelMode(
            dom.agentStudioModelMode.value || "default",
            dom.agentStudioType.value || "config"
        );
        const customModel = dom.agentStudioModel.value.trim();
        const modelValue = selectedMode === "custom"
            ? (customModel || "default")
            : selectedMode;
        return {
            name: dom.agentStudioName.value.trim(),
            type: dom.agentStudioType.value || "config",
            enabled: dom.agentStudioEnabled.checked,
            description: dom.agentStudioDescription.value.trim(),
            model: modelValue,
            tool_mode: "custom",
            system_prompt: dom.agentStudioPrompt.value,
            tools: [...currentCheckedStudioTools()],
        };
    }

    async function saveAgentStudioAgent() {
        const payload = collectAgentStudioPayload();
        if (!payload.name) {
            toast("Agent adı boş olamaz.", "error");
            return;
        }
        const isNew = state.agentStudio.selectedAgentName === "__new__" || !getSelectedStudioAgent();
        const path = isNew && payload.type === "builtin"
            ? "/agent-studio/builtin-agents"
            : isNew
                ? "/agent-studio/agents"
                : `/agent-studio/agents/${encodeURIComponent(state.agentStudio.selectedAgentName)}`;
        const method = isNew ? "POST" : "PUT";
        try {
            const result = await apiRequest(path, { method, body: payload, timeout: 20000 });
            state.agentStudio.catalog = result.catalog || state.agentStudio.catalog;
            if (result.hierarchy) {
                state.hierarchy = result.hierarchy;
                renderHierarchy(result.hierarchy);
            }
            state.agentStudio.selectedAgentName = payload.name;
            state.agentStudio.editorDirty = false;
            renderAgentStudio();
            toast(payload.type === "builtin" && isNew ? "Builtin submodel oluşturuldu ve yüklendi." : "Agent config kaydedildi.", "success");
        } catch (error) {
            toast(`Agent kaydedilemedi: ${error.message}`, "error");
        }
    }

    async function deleteAgentStudioAgent() {
        const agent = getSelectedStudioAgent();
        if (!agent) {
            return;
        }
        if (agent.type === "builtin") {
            toast("Builtin agent silinemez; pasife alabilirsin.", "error");
            return;
        }
        if (!window.confirm(`${agent.name} silinsin mi?`)) {
            return;
        }
        try {
            const result = await apiRequest(`/agent-studio/agents/${encodeURIComponent(agent.name)}`, {
                method: "DELETE",
                timeout: 20000,
            });
            state.agentStudio.catalog = result.catalog || state.agentStudio.catalog;
            state.agentStudio.selectedAgentName = null;
            state.agentStudio.editorDirty = false;
            renderAgentStudio();
            toast("Agent silindi.", "success");
        } catch (error) {
            toast(`Agent silinemedi: ${error.message}`, "error");
        }
    }

    async function reloadAgentStudioRuntime() {
        try {
            const result = await apiRequest("/agent-studio/reload", { method: "POST", timeout: 30000 });
            state.agentStudio.catalog = result.catalog || state.agentStudio.catalog;
            if (result.hierarchy) {
                state.hierarchy = result.hierarchy;
                renderHierarchy(result.hierarchy);
            }
            renderAgentStudio();
            toast(result.restart_required ? "Config kaydedildi; uygulama restart bekliyor." : "Agent runtime yeniden yüklendi.", "success");
        } catch (error) {
            toast(`Agent runtime yenilenemedi: ${error.message}`, "error");
        }
    }

    async function previewAgentStudioPack() {
        const path = dom.agentStudioPackPath.value.trim();
        if (!path) {
            toast("Önce pack klasör yolunu gir.", "error");
            return;
        }
        try {
            dom.agentStudioPackPreviewBtn.disabled = true;
            state.agentStudio.packPath = path;
            state.agentStudio.packPreview = null;
            renderAgentStudioPackSurface(getStudioCatalog());
            const result = await apiRequest("/agent-studio/packs/preview", {
                method: "POST",
                body: { path },
                timeout: 25000,
            });
            state.agentStudio.packPreview = result.preview || null;
            renderAgentStudioPackSurface(getStudioCatalog());
            toast("Pack preview hazır.", "success");
        } catch (error) {
            state.agentStudio.packPreview = {
                name: "preview_failed",
                version: "0.0.0",
                type: "agent_bundle",
                description: "",
                installable: false,
                agents: [],
                tools: [],
                warnings: [],
                errors: [error.message],
            };
            renderAgentStudioPackSurface(getStudioCatalog());
            toast(`Pack preview başarısız: ${error.message}`, "error");
        } finally {
            dom.agentStudioPackPreviewBtn.disabled = false;
        }
    }

    async function installAgentStudioPack() {
        const path = dom.agentStudioPackPath.value.trim();
        if (!path) {
            toast("Önce pack klasör yolunu gir.", "error");
            return;
        }
        try {
            dom.agentStudioPackInstallBtn.disabled = true;
            const result = await apiRequest("/agent-studio/packs/install", {
                method: "POST",
                body: {
                    path,
                    overwrite: dom.agentStudioPackOverwrite.checked,
                },
                timeout: 40000,
            });
            state.agentStudio.catalog = result.catalog || state.agentStudio.catalog;
            if (result.hierarchy) {
                state.hierarchy = result.hierarchy;
                renderHierarchy(result.hierarchy);
            }
            state.agentStudio.packPreview = null;
            renderAgentStudio();
            toast(result.restart_required ? "Pack kuruldu; runtime görmek için restart gerekebilir." : "Pack kuruldu ve runtime'a bağlandı.", "success");
        } catch (error) {
            toast(`Pack kurulamadı: ${error.message}`, "error");
        } finally {
            dom.agentStudioPackInstallBtn.disabled = false;
        }
    }

    function renderCustomToolList(catalog) {
        const tools = catalog.custom_tools || [];
        dom.customToolList.innerHTML = "";
        if (tools.length === 0) {
            dom.customToolList.innerHTML = '<div class="empty-copy">Custom tool yok.</div>';
            return;
        }
        tools.forEach((tool) => {
            const row = document.createElement("button");
            row.type = "button";
            row.className = `studio-list-item ${state.agentStudio.selectedCustomToolName === tool.name ? "is-selected" : ""}`;
            row.dataset.customToolSelect = tool.name;

            const content = document.createElement("div");
            const title = document.createElement("strong");
            title.textContent = tool.name;
            const meta = document.createElement("p");
            meta.textContent = [tool.enabled ? "aktif" : "pasif", tool.error ? "hata" : "hazır"].join(" • ");
            content.append(title, meta);

            const badge = document.createElement("span");
            badge.className = `risk-badge ${tool.error ? "risk-high" : "risk-low"}`;
            badge.textContent = tool.error ? "hata" : "custom";
            row.append(content, badge);
            dom.customToolList.appendChild(row);
        });
    }

    function renderCustomToolEditor(tool, force = false) {
        if (state.agentStudio.customDirty && !force) {
            return;
        }
        dom.customToolAiBrief.value = "";
        state.agentStudio.aiToolMessages = [];
        renderAiToolConversation();
        dom.customToolName.value = tool?.name || "";
        dom.customToolName.disabled = Boolean(tool);
        dom.customToolEnabled.checked = tool?.enabled ?? true;
        dom.customToolDescription.value = tool?.description || "";
        dom.customToolParamsNote.value = tool?.params_note || "";
        const envTemplate = {};
        (tool?.env_vars || []).forEach((name) => {
            envTemplate[name] = "";
        });
        dom.customToolEnvVars.value = Object.keys(envTemplate).length > 0
            ? JSON.stringify(envTemplate, null, 2)
            : "";
        dom.customToolCode.value = tool?.code || "def ornek_tool(text: str) -> str:\n    return text.upper()\n";
        dom.customToolTestArgs.value = tool?.params_note?.trim().startsWith("{") ? tool.params_note : "{}";
        dom.customToolTestResult.textContent = tool?.error ? `Yükleme hatası: ${tool.error}` : "Test çıktısı bekleniyor...";
    }

    function renderAiToolConversation() {
        const messages = state.agentStudio.aiToolMessages || [];
        dom.customToolAiConversation.innerHTML = "";
        if (messages.length === 0) {
            dom.customToolAiConversation.classList.add("empty-copy");
            dom.customToolAiConversation.textContent = "AI brief sohbeti burada görünecek.";
            return;
        }
        dom.customToolAiConversation.classList.remove("empty-copy");
        messages.slice(-8).forEach((message) => {
            const item = document.createElement("div");
            item.className = `ai-message ${message.role === "assistant" ? "assistant" : "user"}`;
            const label = document.createElement("strong");
            label.textContent = message.role === "assistant" ? "AI" : "Sen";
            const body = document.createElement("p");
            body.textContent = message.content || "";
            item.append(label, body);
            dom.customToolAiConversation.appendChild(item);
        });
    }

    function parseJsonField(value, label, fallback = {}) {
        const raw = (value || "").trim();
        if (!raw) {
            return fallback;
        }
        try {
            const parsed = JSON.parse(raw);
            if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
                return parsed;
            }
            throw new Error(`${label} JSON object olmalı.`);
        } catch (error) {
            throw new Error(`${label} JSON değil: ${error.message}`);
        }
    }

    async function generateCustomToolWithAi() {
        const brief = dom.customToolAiBrief.value.trim();
        if (brief.length < 8) {
            toast("AI için biraz daha net bir tool brief'i yaz.", "error");
            return;
        }
        state.agentStudio.aiToolMessages.push({ role: "user", content: brief });
        renderAiToolConversation();

        try {
            dom.customToolAiGenerate.disabled = true;
            dom.customToolAiGenerate.textContent = "Üretiliyor...";
            dom.customToolTestResult.textContent = "AI tool taslağı hazırlanıyor...";
            const result = await apiRequest("/agent-studio/custom-tools/generate", {
                method: "POST",
                body: {
                    brief,
                    current_name: dom.customToolName.value.trim(),
                    current_description: dom.customToolDescription.value.trim(),
                    current_code: dom.customToolCode.value,
                    conversation: state.agentStudio.aiToolMessages,
                },
                timeout: 60000,
            });
            if (result.status === "needs_input") {
                const questions = result.questions || [];
                const message = [result.message || "Birkaç bilgi daha lazım.", ...questions].join("\n");
                state.agentStudio.aiToolMessages.push({ role: "assistant", content: message });
                renderAiToolConversation();
                dom.customToolTestResult.textContent = message;
                dom.customToolAiBrief.value = "";
                toast("AI birkaç soru sordu; brief alanına cevap yazıp tekrar gönder.", "warning");
                return;
            }
            const tool = result.tool || {};
            state.agentStudio.selectedCustomToolName = "__new__";
            dom.customToolName.disabled = false;
            dom.customToolName.value = tool.name || "";
            dom.customToolEnabled.checked = true;
            dom.customToolDescription.value = tool.description || "";
            dom.customToolParamsNote.value = tool.params_note || "";
            dom.customToolEnvVars.value = JSON.stringify(tool.env_vars || {}, null, 2);
            dom.customToolCode.value = tool.code || "";
            dom.customToolTestArgs.value = JSON.stringify(tool.test_args || {}, null, 2);
            dom.customToolTestResult.textContent = tool.warning
                ? `${tool.warning}\n\nHam çıktı önizleme:\n${tool.raw_preview || ""}`
                : "AI taslağı forma aktarıldı. Kaydetmeden önce test edebilirsin.";
            state.agentStudio.aiToolMessages.push({ role: "assistant", content: `Tool taslağı hazır: ${tool.name || "isimsiz"}` });
            renderAiToolConversation();
            state.agentStudio.customDirty = true;
            toast(tool.warning ? "AI çıktısı onarılamadı; güvenli taslak dolduruldu." : "AI custom tool taslağı oluşturdu.", tool.warning ? "warning" : "success");
        } catch (error) {
            dom.customToolTestResult.textContent = error.message;
            toast(`AI tool üretemedi: ${error.message}`, "error");
        } finally {
            dom.customToolAiGenerate.disabled = false;
            dom.customToolAiGenerate.textContent = "AI ile Tool Oluştur";
        }
    }

    function selectCustomTool(name) {
        state.agentStudio.selectedCustomToolName = name;
        state.agentStudio.customDirty = false;
        renderCustomToolEditor(getSelectedCustomTool(), true);
        renderAgentStudio();
    }

    async function saveCustomTool(options = {}) {
        const silent = options?.silent === true;
        const payload = {
            name: dom.customToolName.value.trim(),
            enabled: dom.customToolEnabled.checked,
            description: dom.customToolDescription.value.trim(),
            params_note: dom.customToolParamsNote.value.trim(),
            env_vars: {},
            code: dom.customToolCode.value,
        };
        try {
            payload.env_vars = parseJsonField(dom.customToolEnvVars.value, ".env.model değişkenleri", {});
        } catch (error) {
            if (!silent) {
                toast(error.message, "error");
            }
            return false;
        }
        if (!payload.name) {
            if (!silent) {
                toast("Custom tool adı boş olamaz.", "error");
            }
            return false;
        }
        try {
            const result = await apiRequest("/agent-studio/custom-tools", {
                method: "POST",
                body: payload,
                timeout: 20000,
            });
            state.agentStudio.catalog = result.catalog || state.agentStudio.catalog;
            state.agentStudio.selectedCustomToolName = payload.name;
            state.agentStudio.customDirty = false;
            renderAgentStudio();
            if (!silent) {
                toast("Custom tool kaydedildi.", "success");
            }
            return true;
        } catch (error) {
            if (!silent) {
                toast(`Custom tool kaydedilemedi: ${error.message}`, "error");
            }
            return false;
        }
    }

    async function testCustomTool() {
        const name = dom.customToolName.value.trim();
        if (!name) {
            toast("Önce custom tool adı gir.", "error");
            return;
        }
        let args = {};
        try {
            args = JSON.parse(dom.customToolTestArgs.value || "{}");
        } catch (error) {
            toast(`Test argümanı JSON değil: ${error.message}`, "error");
            return;
        }
        try {
            const existsInCatalog = Boolean((getStudioCatalog().custom_tools || []).find((tool) => tool.name === name));
            if (state.agentStudio.customDirty || !existsInCatalog) {
                dom.customToolTestResult.textContent = "Test öncesi tool kaydediliyor...";
                const saved = await saveCustomTool({ silent: true });
                if (!saved) {
                    dom.customToolTestResult.textContent = "Tool kaydedilemediği için test başlatılamadı.";
                    toast("Test için önce tool kaydı tamamlanmalı.", "error");
                    return;
                }
            }
            dom.customToolTestResult.textContent = "Çalışıyor...";
            const result = await apiRequest(`/agent-studio/custom-tools/${encodeURIComponent(name)}/test`, {
                method: "POST",
                body: { arguments: args },
                timeout: 25000,
            });
            dom.customToolTestResult.textContent = JSON.stringify({
                arguments: result.arguments || args,
                result: result.result,
            }, null, 2);
            toast("Custom tool testi tamamlandı.", "success");
        } catch (error) {
            dom.customToolTestResult.textContent = error.message;
            toast(`Custom tool testi başarısız: ${error.message}`, "error");
        }
    }

    function renderLogs(logs) {
        dom.liveActivity.innerHTML = "";
        const query = state.activitySearch;
        const typeFilter = state.activityFilter;
        const filteredLogs = (logs || []).filter((log) => {
            const matchesType = typeFilter === "all" || (log.type || "sistem") === typeFilter;
            if (!matchesType) {
                return false;
            }
            if (!query) {
                return true;
            }
            return `${log.type || ""} ${log.message || ""}`.toLowerCase().includes(query);
        });

        if (filteredLogs.length === 0) {
            dom.liveActivity.innerHTML = '<div class="empty-copy">Filtreye uyan log bulunamadı.</div>';
            return;
        }

        filteredLogs.slice().reverse().forEach((log) => {
            const entry = document.createElement("div");
            entry.className = `activity-entry ${log.type || "sistem"}`;

            const meta = document.createElement("div");
            meta.className = "activity-meta";
            meta.textContent = `[${log.time || "--:--"}] ${String(log.type || "log").toUpperCase()}`;

            const body = document.createElement("p");
            body.textContent = log.message || "";

            entry.append(meta, body);
            dom.liveActivity.appendChild(entry);
        });
    }

    function renderPendingActions(actions) {
        const items = actions || [];
        state.pendingActions = items;
        state.pendingActionId = items[0]?.id || null;
        dom.approvalCountBadge.textContent = `${items.length}`;
        dom.metricApprovals.textContent = `${items.length}`;

        if (items.length === 0) {
            dom.pendingActionsList.innerHTML = '<div class="empty-copy">Bekleyen aksiyon bulunmuyor.</div>';
            dom.approvalBadge.classList.add("hidden");
            dom.approvalModal.classList.add("hidden");
            return;
        }

        dom.approvalBadge.classList.remove("hidden");
        dom.approvalBadge.textContent = `${items.length} onay bekliyor`;
        dom.pendingActionsList.innerHTML = "";

        items.forEach((action) => {
            const row = document.createElement("div");
            row.className = "stack-item";

            const content = document.createElement("div");
            const title = document.createElement("strong");
            title.textContent = action.id;
            const desc = document.createElement("p");
            desc.textContent = action.description;
            content.append(title, desc);

            const button = document.createElement("button");
            button.className = "btn ghost compact";
            button.type = "button";
            button.dataset.openApproval = action.id;
            button.textContent = "İncele";

            row.append(content, button);
            dom.pendingActionsList.appendChild(row);
        });
    }

    function openApprovalModal(action) {
        state.pendingActionId = action.id;
        dom.approvalDesc.textContent = action.description;
        dom.approvalModal.classList.remove("hidden");
    }

    async function decideAction(decision) {
        if (!state.pendingActionId) {
            return;
        }

        await apiRequest(`/actions/${encodeURIComponent(state.pendingActionId)}/${decision}`, {
            method: "POST",
        });

        dom.approvalModal.classList.add("hidden");
        toast(`İşlem ${decision === "approve" ? "onaylandı" : "reddedildi"}.`, "success");
        await fetchBootstrap({ silent: true });
    }

    function renderStatsChart(metrics) {
        const values = metrics || [];
        const labels = values.map((item) => item.time || "-");
        const durations = values.map((item) => item.duration || 0);
        const names = values.map((item) => item.name || "task");

        if (!state.chart) {
            state.chart = new Chart(dom.statsChart, {
                type: "line",
                data: {
                    labels,
                    datasets: [{
                        label: "Araç / Ajan Süresi",
                        data: durations,
                        borderColor: "#19d3c5",
                        backgroundColor: "rgba(25, 211, 197, 0.12)",
                        tension: 0.35,
                        fill: true,
                        pointRadius: 3,
                        pointHoverRadius: 5,
                    }],
                },
                options: {
                    maintainAspectRatio: false,
                    responsive: true,
                    plugins: {
                        legend: {
                            labels: {
                                color: "#f3efe4",
                                font: { family: "Space Grotesk" },
                            },
                        },
                        tooltip: {
                            callbacks: {
                                title(context) {
                                    return `${names[context[0].dataIndex] || "Görev"} • ${labels[context[0].dataIndex] || "-"}`;
                                },
                                label(context) {
                                    return `${context.parsed.y}s`;
                                },
                            },
                        },
                    },
                    scales: {
                        x: {
                            ticks: { color: "rgba(243, 239, 228, 0.65)" },
                            grid: { color: "rgba(255, 255, 255, 0.05)" },
                        },
                        y: {
                            ticks: {
                                color: "rgba(243, 239, 228, 0.65)",
                                callback(value) {
                                    return `${value}s`;
                                },
                            },
                            grid: { color: "rgba(255, 255, 255, 0.05)" },
                        },
                    },
                },
            });
            return;
        }

        state.chart.data.labels = labels;
        state.chart.data.datasets[0].data = durations;
        state.chart.update();
    }

    async function switchTab(tabId) {
        state.activeTab = tabId;

        dom.navItems.forEach((item) => item.classList.toggle("active", item.dataset.tab === tabId));
        dom.tabPanels.forEach((panel) => panel.classList.toggle("active", panel.id === `tab-${tabId}`));

        const activeNav = dom.navItems.find((item) => item.dataset.tab === tabId);
        dom.currentTabTitle.textContent = activeNav?.dataset.title || "Panel";

        try {
            await refreshActiveView({ silent: true });
        } catch (error) {
            setConnectionState(`Sekme verisi yüklenemedi: ${error.message}`, "error");
            toast(`Sekme yüklenemedi: ${error.message}`, "error");
        }
    }

    async function switchMemTab(memId) {
        state.activeMemTab = memId;
        dom.memNavItems.forEach((item) => item.classList.toggle("active", item.dataset.mem === memId));
        dom.memPanes.forEach((pane) => pane.classList.remove("active"));

        if (memId === "persona") {
            document.getElementById("mem-content-persona").classList.add("active");
        } else {
            document.getElementById("mem-content-list").classList.add("active");
        }

        await loadMemoryTab({ silent: true });
    }

    async function loadMemoryTab() {
        if (state.activeMemTab === "persona") {
            const data = await apiRequest("/persona");
            dom.personaEditor.value = data.content || "";
            return;
        }

        const raw = await apiRequest("/memory/raw");

        renderMemoryCategory(state.activeMemTab, raw);
    }

    function renderMemoryCategory(category, rawData) {
        dom.memListTitle.textContent = category.charAt(0).toUpperCase() + category.slice(1);
        dom.memTableBody.innerHTML = "";
        const items = rawData[category] || (category === "tercihler" || category === "kisiler" ? {} : []);

        if (Array.isArray(items)) {
            if (items.length === 0) {
                renderEmptyMemoryRow();
                return;
            }

            items.forEach((item) => {
                dom.memTableBody.appendChild(createMemoryRow(category, item.anahtar, item.deger));
            });
            return;
        }

        const entries = Object.entries(items);
        if (entries.length === 0) {
            renderEmptyMemoryRow();
            return;
        }

        entries.forEach(([key, value]) => {
            const normalizedValue = typeof value === "object" && value !== null ? value.deger : value;
            dom.memTableBody.appendChild(createMemoryRow(category, key, normalizedValue));
        });
    }

    function createMemoryRow(category, key, value) {
        const tr = document.createElement("tr");
        const keyCell = document.createElement("td");
        keyCell.textContent = key;
        const valueCell = document.createElement("td");
        valueCell.textContent = value;
        const actionCell = document.createElement("td");
        const button = document.createElement("button");
        button.className = "btn ghost compact";
        button.type = "button";
        button.textContent = "Sil";
        button.addEventListener("click", async () => {
            await apiRequest("/memory/delete", {
                method: "POST",
                body: { category, key },
            });
            toast("Kayıt silindi.", "success");
            await loadMemoryTab({ silent: true });
        });
        actionCell.appendChild(button);
        tr.append(keyCell, valueCell, actionCell);
        return tr;
    }

    function renderEmptyMemoryRow() {
        const tr = document.createElement("tr");
        const td = document.createElement("td");
        td.colSpan = 3;
        td.className = "empty-copy";
        td.textContent = "Bu kategoride kayıt bulunmuyor.";
        tr.appendChild(td);
        dom.memTableBody.appendChild(tr);
    }

    async function savePersona() {
        try {
            await apiRequest("/persona", {
                method: "POST",
                body: { content: dom.personaEditor.value },
            });
            toast("Persona kaydedildi.", "success");
        } catch (error) {
            toast(`Persona kaydedilemedi: ${error.message}`, "error");
        }
    }

    async function addMemoryEntry() {
        const key = dom.newMemKey.value.trim();
        const value = dom.newMemVal.value.trim();

        if (!key || !value) {
            toast("Anahtar ve değer zorunlu.", "warning");
            return;
        }

        try {
            await apiRequest("/memory/write", {
                method: "POST",
                body: { category: state.activeMemTab, key, value },
            });

            dom.newMemKey.value = "";
            dom.newMemVal.value = "";
            toast("Bellek kaydı eklendi.", "success");
            await loadMemoryTab({ silent: true });
        } catch (error) {
            toast(`Bellek kaydı eklenemedi: ${error.message}`, "error");
        }
    }

    async function fetchWorkspaceTree({ silent = false } = {}) {
        try {
            const nodes = await apiRequest("/workspace/tree");
            state.workspaceNodes = Array.isArray(nodes) ? nodes : [];
            renderTree(state.workspaceNodes);
            if (!silent) {
                toast("Workspace ağacı yenilendi.", "success");
            }
        } catch (error) {
            if (!silent) {
                toast(`Workspace ağacı yüklenemedi: ${error.message}`, "error");
            }
            throw error;
        }
    }

    function renderTree(nodes) {
        dom.fileTree.innerHTML = "";
        const filteredNodes = filterTreeNodes(nodes || [], state.workspaceSearch);

        if (!filteredNodes || filteredNodes.length === 0) {
            dom.fileTree.innerHTML = `<div class="empty-copy">${
                state.workspaceSearch
                    ? "Arama ile eşleşen dosya ya da klasör bulunamadı."
                    : "Workspace boş görünüyor."
            }</div>`;
            return;
        }

        const fragment = document.createDocumentFragment();
        filteredNodes
            .slice()
            .sort(sortTreeNodes)
            .forEach((node) => fragment.appendChild(renderTreeNode(node, 0)));
        dom.fileTree.appendChild(fragment);
    }

    function renderTreeNode(node, depth) {
        const wrapper = document.createElement("div");
        wrapper.className = "tree-node-wrapper";

        const row = document.createElement("button");
        row.type = "button";
        row.className = `tree-node ${state.selectedFilePath === node.path ? "is-selected" : ""}`;
        row.style.setProperty("--depth", depth);
        row.dataset.treePath = node.path;
        row.dataset.treeType = node.type;
        row.dataset.treeName = node.name;

        const icon = document.createElement("span");
        icon.className = "tree-icon";
        if (node.type === "directory") {
            const expanded = depth === 0 || state.expandedDirs.has(node.path);
            row.dataset.expanded = expanded ? "true" : "false";
            icon.textContent = expanded ? "▾" : "▸";
        } else {
            icon.textContent = "•";
        }

        const label = document.createElement("span");
        label.className = "tree-label";
        label.textContent = node.name;

        row.append(icon, label);
        wrapper.appendChild(row);

        if (node.type === "directory") {
            const expanded = depth === 0 || state.expandedDirs.has(node.path);
            if (expanded) {
                const children = document.createElement("div");
                children.className = "tree-children";
                (node.children || []).slice().sort(sortTreeNodes).forEach((child) => {
                    children.appendChild(renderTreeNode(child, depth + 1));
                });
                wrapper.appendChild(children);
            }
        }

        return wrapper;
    }

    async function loadFile(path, name) {
        const data = await apiRequest(`/workspace/read?path=${encodeURIComponent(path)}`);
        state.selectedFilePath = path;
        state.currentFileContent = data.content || "";
        state.currentFileMeta = buildFileMeta(path, data.content || "");
        dom.currentFileName.textContent = name;
        dom.currentFilePath.textContent = path;
        dom.fileViewer.textContent = data.content || "";
        renderFileMeta();
        renderFileSearchResults();
        await fetchWorkspaceTree({ silent: true });
    }

    function filterTreeNodes(nodes, query) {
        if (!query) {
            return nodes;
        }

        const lowered = query.toLowerCase();
        return (nodes || [])
            .map((node) => {
                if (node.type === "directory") {
                    const children = filterTreeNodes(node.children || [], lowered);
                    if (node.name.toLowerCase().includes(lowered) || children.length > 0) {
                        return { ...node, children };
                    }
                    return null;
                }

                if (`${node.name} ${node.path}`.toLowerCase().includes(lowered)) {
                    return node;
                }
                return null;
            })
            .filter(Boolean);
    }

    function sortTreeNodes(a, b) {
        if (a.type !== b.type) {
            return a.type === "directory" ? -1 : 1;
        }
        return String(a.name || "").localeCompare(String(b.name || ""), "tr");
    }

    function buildFileMeta(path, content) {
        const normalized = String(content || "");
        const lines = normalized ? normalized.split(/\r?\n/).length : 0;
        const words = normalized.trim() ? normalized.trim().split(/\s+/).length : 0;
        const extension = path && path.includes(".") ? path.split(".").pop().toLowerCase() : "-";
        return {
            extension,
            lines,
            chars: normalized.length,
            words,
        };
    }

    function renderFileMeta() {
        const meta = state.currentFileMeta || { extension: "-", lines: 0, chars: 0, words: 0 };
        dom.fileStatExtension.textContent = meta.extension || "-";
        dom.fileStatLines.textContent = `${meta.lines ?? 0}`;
        dom.fileStatChars.textContent = `${meta.chars ?? 0}`;
        dom.fileStatWords.textContent = `${meta.words ?? 0}`;
    }

    function renderFileSearchResults() {
        const content = state.currentFileContent || "";
        const query = dom.fileSearchInput.value.trim().toLowerCase();
        dom.fileSearchResults.innerHTML = "";

        if (!state.selectedFilePath) {
            dom.fileSearchResults.innerHTML = '<div class="empty-copy">Bir dosya seçtiğinizde burada satır bazlı arama sonuçları görünecek.</div>';
            return;
        }

        if (!query) {
            dom.fileSearchResults.innerHTML = '<div class="empty-copy">Dosyada hızlı arama için bir ifade yazın.</div>';
            return;
        }

        const matches = content
            .split(/\r?\n/)
            .map((line, index) => ({ line, index: index + 1 }))
            .filter((entry) => entry.line.toLowerCase().includes(query))
            .slice(0, 12);

        if (matches.length === 0) {
            dom.fileSearchResults.innerHTML = '<div class="empty-copy">Arama ifadesi seçili dosyada bulunamadı.</div>';
            return;
        }

        matches.forEach((match) => {
            const item = document.createElement("div");
            item.className = "insight-result";

            const title = document.createElement("strong");
            title.textContent = `Satır ${match.index}`;

            const body = document.createElement("p");
            body.textContent = match.line.trim() || "(boş satır)";

            item.append(title, body);
            dom.fileSearchResults.appendChild(item);
        });
    }

    async function copySelectedFilePath() {
        if (!state.selectedFilePath) {
            toast("Önce bir dosya seçin.", "warning");
            return;
        }

        try {
            if (navigator.clipboard?.writeText) {
                await navigator.clipboard.writeText(state.selectedFilePath);
            } else {
                const temp = document.createElement("textarea");
                temp.value = state.selectedFilePath;
                document.body.appendChild(temp);
                temp.select();
                document.execCommand("copy");
                temp.remove();
            }
            toast("Dosya yolu panoya kopyalandı.", "success");
        } catch (error) {
            toast(`Dosya yolu kopyalanamadı: ${error.message}`, "error");
        }
    }

    function switchSourceTab(srcId) {
        state.activeSrcTab = srcId;
        dom.srcTabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.src === srcId));
        dom.srcPanes.forEach((pane) => pane.classList.toggle("active", pane.id === `src-content-${srcId}`));
    }

    function switchCustomToolTab(tabId) {
        state.activeCustomToolTab = tabId || "ai";
        dom.customToolTabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.customTab === state.activeCustomToolTab));
        dom.customToolPanes.forEach((pane) => pane.classList.toggle("active", pane.id === `custom-tool-pane-${state.activeCustomToolTab}`));
    }

    function syncSelectedFile() {
        state.pendingUploadFile = dom.fileInput.files?.[0] || state.pendingUploadFile;
        const file = state.pendingUploadFile;
        dom.selectedFileName.textContent = file ? file.name : "Seçili dosya yok";
    }

    async function uploadSelectedFile() {
        const file = state.pendingUploadFile || dom.fileInput.files?.[0];
        if (!file) {
            toast("Önce bir dosya seçin.", "warning");
            return;
        }

        try {
            const formData = new FormData();
            formData.append("file", file);
            await apiRequest("/workspace/targets/upload", {
                method: "POST",
                body: formData,
                timeout: 30000,
            });

            dom.fileInput.value = "";
            state.pendingUploadFile = null;
            syncSelectedFile();
            dom.sourceModal.classList.add("hidden");
            toast("Dosya target klasörüne yüklendi.", "success");
            await fetchWorkspaceTree({ silent: true });
        } catch (error) {
            toast(`Dosya yüklenemedi: ${error.message}`, "error");
        }
    }

    async function addUrlTarget() {
        const name = dom.srcUrlName.value.trim();
        const content = dom.srcUrlVal.value.trim();
        if (!name || !content) {
            toast("URL kaynağı için ad ve içerik zorunlu.", "warning");
            return;
        }

        try {
            await apiRequest("/workspace/targets/add", {
                method: "POST",
                body: { type: "url", name, content },
            });

            dom.srcUrlName.value = "";
            dom.srcUrlVal.value = "";
            dom.sourceModal.classList.add("hidden");
            toast("URL kaynağı eklendi.", "success");
            await fetchWorkspaceTree({ silent: true });
        } catch (error) {
            toast(`URL kaynağı eklenemedi: ${error.message}`, "error");
        }
    }

    async function addTextTarget() {
        const name = dom.srcTextName.value.trim();
        const content = dom.srcTextVal.value.trim();
        if (!name || !content) {
            toast("Metin kaynağı için ad ve içerik zorunlu.", "warning");
            return;
        }

        try {
            await apiRequest("/workspace/targets/add", {
                method: "POST",
                body: { type: "text", name, content },
            });

            dom.srcTextName.value = "";
            dom.srcTextVal.value = "";
            dom.sourceModal.classList.add("hidden");
            toast("Metin kaynağı eklendi.", "success");
            await fetchWorkspaceTree({ silent: true });
        } catch (error) {
            toast(`Metin kaynağı eklenemedi: ${error.message}`, "error");
        }
    }

    function renderSkills(skills) {
        dom.skillsList.innerHTML = "";

        if (!skills || skills.length === 0) {
            dom.skillsList.innerHTML = '<div class="empty-copy">Yüklü skill bulunamadı.</div>';
            return;
        }

        skills.forEach((skill) => {
            const item = document.createElement("div");
            item.className = "stack-item";

            const content = document.createElement("div");
            const name = document.createElement("strong");
            name.textContent = skill.name;
            const desc = document.createElement("p");
            desc.textContent = `${skill.agent || "genel"} • ${skill.description || "Açıklama yok"}`;
            content.append(name, desc);

            const button = document.createElement("button");
            button.className = `btn ${skill.enabled ? "primary" : "ghost"} compact`;
            button.type = "button";
            button.dataset.skillToggle = skill.name;
            button.textContent = skill.enabled ? "Aktif" : "Pasif";

            item.append(content, button);
            dom.skillsList.appendChild(item);
        });
    }

    async function toggleSkill(name) {
        try {
            await apiRequest(`/skills/${encodeURIComponent(name)}/toggle`, { method: "POST" });
            toast(`Skill durumu güncellendi: ${name}`, "success");
            await fetchBootstrap({ silent: true });
        } catch (error) {
            toast(`Skill güncellenemedi: ${error.message}`, "error");
        }
    }

    async function reloadSkills() {
        try {
            await apiRequest("/skills/reload", { method: "POST" });
            toast("Skill listesi yeniden yüklendi.", "success");
            await fetchBootstrap({ silent: true });
        } catch (error) {
            toast(`Skill listesi yenilenemedi: ${error.message}`, "error");
        }
    }

    async function fetchHeartbeatConfig() {
        const [config, status, jobs] = await Promise.all([
            apiRequest("/heartbeat/config"),
            apiRequest("/heartbeat/status"),
            apiRequest("/heartbeat/jobs"),
        ]);

        state.heartbeat = {
            config,
            status,
            jobs: Array.isArray(jobs) ? jobs : [],
        };

        if (!state.heartbeatDirty) {
            dom.heartbeatEditor.value = config.content || "";
        }
        renderHeartbeat();
    }

    async function saveHeartbeatConfig() {
        try {
            await apiRequest("/heartbeat/config", {
                method: "POST",
                body: { content: dom.heartbeatEditor.value },
            });
            state.heartbeatDirty = false;
            await fetchHeartbeatConfig();
            toast("Heartbeat config kaydedildi.", "success");
        } catch (error) {
            toast(`Heartbeat config kaydedilemedi: ${error.message}`, "error");
        }
    }

    async function reloadHeartbeatScheduler() {
        try {
            await apiRequest("/heartbeat/reload", { method: "POST" });
            await fetchHeartbeatConfig();
            toast("Heartbeat scheduler yenilendi.", "success");
        } catch (error) {
            toast(`Heartbeat yenilenemedi: ${error.message}`, "error");
        }
    }

    function renderHeartbeat() {
        const config = state.heartbeat?.config || {};
        const status = state.heartbeat?.status || {};
        const jobs = Array.isArray(state.heartbeat?.jobs) ? state.heartbeat.jobs : [];
        const filteredJobs = jobs.filter(matchesHeartbeatJobFilter);
        const enabled = Boolean(config?.enabled);
        const taskCount = config?.task_count ?? 0;
        const activeJobName = status?.active_job_name || status?.active_job_id || "Yok";
        const configValid = Boolean(config?.valid);
        const runningCount = jobs.filter((job) => job.running).length;
        const pausedCount = jobs.filter((job) => job.paused).length;
        const issueCount = jobs.filter((job) => ["error", "paused", "disabled"].includes(job.last_status) || job.last_error).length;

        dom.heartbeatEnabledState.textContent = enabled ? "Aktif" : "Kapalı";
        dom.heartbeatMeta.textContent = `${taskCount} görev tanımı • ${status?.scheduled_job_count ?? 0} zamanlı job`;
        dom.heartbeatRunningState.textContent = status?.running
            ? `Çalışıyor • ${activeJobName}`
            : (status?.ready ? "Beklemede" : "Hazır değil");
        dom.heartbeatRunningMeta.textContent = status?.last_reload_at
            ? `Son yenileme: ${formatDateTime(status.last_reload_at)}`
            : "Scheduler henüz yüklenmedi";
        dom.heartbeatConfigState.textContent = configValid ? "Geçerli" : "Hatalı";
        dom.heartbeatConfigMeta.textContent = configValid
            ? `${status?.scheduled_job_count ?? 0} zamanlı job • ${jobs.length} toplam`
            : (config?.validation_error || "Config doğrulanamadı");

        dom.heartbeatEnable.classList.toggle("primary", enabled);
        dom.heartbeatEnable.classList.toggle("ghost", !enabled);
        dom.heartbeatDisable.classList.toggle("primary", !enabled);
        dom.heartbeatDisable.classList.toggle("ghost", enabled);
        dom.heartbeatSummaryGrid.innerHTML = "";

        [
            { label: "Çalışan", value: runningCount, tone: "teal" },
            { label: "Durdurulan", value: pausedCount, tone: "amber" },
            { label: "Sorunlu", value: issueCount, tone: "rose" },
            { label: "Toplam", value: jobs.length, tone: "slate" },
        ].forEach((item) => {
            const card = document.createElement("div");
            card.className = `summary-item tone-${item.tone}`;
            const label = document.createElement("span");
            label.textContent = item.label;
            const value = document.createElement("strong");
            value.textContent = `${item.value}`;
            card.append(label, value);
            dom.heartbeatSummaryGrid.appendChild(card);
        });

        dom.heartbeatJobList.innerHTML = "";
        if (filteredJobs.length === 0) {
            dom.heartbeatJobList.innerHTML = `<div class="empty-copy">${
                jobs.length === 0
                    ? "Tanımlı heartbeat görevi yok."
                    : "Seçili filtrede gösterilecek heartbeat görevi yok."
            }</div>`;
            return;
        }

        filteredJobs.forEach((job) => {
            const item = document.createElement("div");
            item.className = `stack-item heartbeat-job-item status-${job.last_status || "idle"}`;

            const top = document.createElement("div");
            top.className = "heartbeat-job-top";

            const head = document.createElement("div");
            const title = document.createElement("strong");
            title.textContent = job.name || job.job_id;
            const meta = document.createElement("p");
            meta.textContent = `${job.job_id} • ${job.cron || "manual"}`;
            head.append(title, meta);

            const badge = document.createElement("span");
            badge.className = `queue-badge status-${job.last_status || "idle"}`;
            badge.textContent = resolveHeartbeatJobStatusLabel(job);
            top.append(head, badge);

            const info = document.createElement("p");
            info.className = "heartbeat-job-copy";
            info.textContent = [
                `Next: ${formatDateTime(job.next_run_at)}`,
                `Last: ${formatDateTime(job.last_run_at)}`,
                `Run count: ${job.run_count ?? 0}`,
            ].join(" • ");

            const error = document.createElement("p");
            error.className = "heartbeat-job-error";
            error.textContent = job.last_error || "Son hata yok";

            const actions = document.createElement("div");
            actions.className = "toolbar-actions heartbeat-job-actions";

            const toggle = document.createElement("button");
            toggle.type = "button";
            toggle.className = "btn ghost";
            toggle.dataset.heartbeatAction = job.paused ? "resume" : "pause";
            toggle.dataset.heartbeatJobId = job.job_id;
            toggle.textContent = job.paused ? "Devam Ettir" : "Duraklat";
            toggle.disabled = !job.enabled && !job.paused;

            const run = document.createElement("button");
            run.type = "button";
            run.className = "btn ghost";
            run.dataset.heartbeatAction = "run";
            run.dataset.heartbeatJobId = job.job_id;
            run.textContent = "Şimdi Çalıştır";
            run.disabled = Boolean(job.running);

            actions.append(toggle, run);
            item.append(top, info, error, actions);
            dom.heartbeatJobList.appendChild(item);
        });
    }

    function matchesHeartbeatJobFilter(job) {
        const filter = state.heartbeatJobFilter;
        if (filter === "active") {
            return Boolean(job.enabled) && !job.paused;
        }
        if (filter === "issues") {
            return Boolean(job.paused || job.last_error || ["error", "disabled", "paused"].includes(job.last_status));
        }
        return true;
    }

    async function toggleHeartbeat(enabled) {
        dom.heartbeatEnable.disabled = true;
        dom.heartbeatDisable.disabled = true;
        dom.heartbeatReload.disabled = true;

        try {
            await apiRequest("/heartbeat/toggle", {
                method: "POST",
                body: { enabled },
            });
            await fetchHeartbeatConfig();
            toast(`Heartbeat ${enabled ? "açıldı" : "kapatıldı"}.`, "success");
        } catch (error) {
            toast(`Heartbeat durumu değiştirilemedi: ${error.message}`, "error");
        } finally {
            dom.heartbeatEnable.disabled = false;
            dom.heartbeatDisable.disabled = false;
            dom.heartbeatReload.disabled = false;
        }
    }

    async function handleHeartbeatJobAction(jobId, action) {
        if (!jobId || !action) {
            return;
        }

        const endpointMap = {
            pause: `/heartbeat/jobs/${encodeURIComponent(jobId)}/pause`,
            resume: `/heartbeat/jobs/${encodeURIComponent(jobId)}/resume`,
            run: `/heartbeat/jobs/${encodeURIComponent(jobId)}/run`,
        };

        const endpoint = endpointMap[action];
        if (!endpoint) {
            return;
        }

        try {
            await apiRequest(endpoint, { method: "POST", timeout: 20000 });
            await fetchHeartbeatConfig();
            if (action === "run") {
                toast(`Job tetiklendi: ${jobId}`, "success");
            } else {
                toast(`Job güncellendi: ${jobId}`, "success");
            }
        } catch (error) {
            toast(`Heartbeat job işlemi başarısız: ${error.message}`, "error");
        }
    }

    async function fetchSocialSnapshot({ silent = false } = {}) {
        try {
            const [browser, queue] = await Promise.all([
                apiRequest("/social/browser/status"),
                apiRequest("/social/x/queue"),
            ]);
            state.social.browser = browser || null;
            state.social.queue = queue || { items: [] };
            renderSocial({ browser, queue });
            if (!silent) {
                setConnectionState("Sosyal inbox senkronize edildi.", "success");
            }
        } catch (error) {
            if (!silent) {
                toast(`Sosyal görünüm yenilenemedi: ${error.message}`, "error");
            }
            throw error;
        }
    }

    function renderSocial(snapshot) {
        const browser = snapshot?.browser || state.social.browser || { ready: false, error: "Tarayıcı bağlı değil." };
        const queue = snapshot?.queue || state.social.queue || { items: [] };
        const items = Array.isArray(queue.items) ? queue.items : [];
        const actionableCount = items.filter(isSocialActionable).length;
        const visibleItems = filterSocialItems(items);

        state.social.browser = browser;
        state.social.queue = queue;

        dom.socialBrowserState.textContent = browser.ready
            ? `Hazır • ${browser.title || "Aktif sekme"}`
            : "Bağlı değil";
        dom.socialBrowserUrl.textContent = browser.ready
            ? (browser.url || "Tarayıcı sekmesi algılandı")
            : (browser.error || "Tarayıcı oturumu başlatılmalı");
        dom.socialBrowserMode.textContent = browser.ready
            ? `Mod: ${browser.visibility_label || (browser.headless ? "Headless" : "Görünür")}`
            : `Son tercih: ${browser.visibility_label || (browser.preferred_headless ? "Headless" : "Görünür")}`;
        dom.socialQueueCount.textContent = `${actionableCount} aksiyonluk • ${visibleItems.length}/${items.length} görünür`;
        dom.socialQueueUpdated.textContent = queue.updated_at
            ? `Son güncelleme: ${formatDateTime(queue.updated_at)}`
            : "Henüz tarama yapılmadı";
        syncSocialBrowserButtons(browser);

        const selectedStillExists = visibleItems.some((item) => item.queue_id === state.social.selectedQueueId);
        if (!selectedStillExists) {
            const nextItem = visibleItems[0] || null;
            state.social.selectedQueueId = nextItem?.queue_id || null;
            state.social.editorDirty = false;
        }

        dom.socialQueueList.innerHTML = "";
        if (visibleItems.length === 0) {
            dom.socialQueueList.innerHTML = `<div class="empty-copy">${
                items.length === 0
                    ? "Tarama sonrası yorumlar burada görünecek."
                    : "Filtreye uyan yorum bulunamadı."
            }</div>`;
        } else {
            visibleItems.forEach((item) => {
                const button = document.createElement("button");
                button.type = "button";
                button.className = `queue-item ${item.queue_id === state.social.selectedQueueId ? "is-active" : ""}`;
                button.dataset.socialQueueId = item.queue_id;

                const top = document.createElement("div");
                top.className = "queue-item-top";

                const author = document.createElement("strong");
                author.textContent = item.author_handle ? `@${item.author_handle}` : (item.author_name || "Bilinmeyen kullanıcı");

                const badge = document.createElement("span");
                badge.className = `queue-badge status-${item.status || "new"}`;
                badge.textContent = resolveQueueStatusLabel(item.status);

                top.append(author, badge);

                const text = document.createElement("p");
                text.className = "queue-item-text";
                text.textContent = item.text || "Yorum metni okunamadı.";

                const meta = document.createElement("div");
                meta.className = "queue-item-meta";
                meta.textContent = [item.author_name, item.time_label].filter(Boolean).join(" • ") || "Yeni yorum";

                button.append(top, text, meta);
                dom.socialQueueList.appendChild(button);
            });
        }

        const selected = getSelectedSocialItem();
        if (!selected) {
            dom.socialSelectedMeta.textContent = "Henüz seçim yok";
            dom.socialOpenLink.classList.add("hidden");
            dom.socialEditorTitle.textContent = "Yorum seçin";
            dom.socialCommentPreview.textContent = "Tarayıcı açıkken ilgili X sayfasını tarayarak yorumları sıraya alabilirsiniz.";
            if (!state.social.editorDirty) {
            dom.socialReplyEditor.value = "";
            }
            dom.socialReplyEditor.dataset.queueId = "";
            updateSocialComposerActions(false);
            updateReplyCounter();
            return;
        }

        dom.socialSelectedMeta.textContent = `${selected.author_handle ? `@${selected.author_handle}` : (selected.author_name || "Yorum")} • ${resolveQueueStatusLabel(selected.status)}`;
        if (selected.tweet_url) {
            dom.socialOpenLink.href = selected.tweet_url;
            dom.socialOpenLink.classList.remove("hidden");
        } else {
            dom.socialOpenLink.classList.add("hidden");
        }

        dom.socialEditorTitle.textContent = selected.author_name || (selected.author_handle ? `@${selected.author_handle}` : "Seçili yorum");
        dom.socialCommentPreview.textContent = selected.text || "Yorum metni bulunamadı.";

        if (!state.social.editorDirty || dom.socialReplyEditor.dataset.queueId !== selected.queue_id) {
            dom.socialReplyEditor.value = selected.draft_reply || "";
            dom.socialReplyEditor.dataset.queueId = selected.queue_id;
            state.social.editorDirty = false;
        }

        updateSocialComposerActions(true);
        updateReplyCounter();
    }

    function getSelectedSocialItem() {
        const items = state.social.queue?.items || [];
        return items.find((item) => item.queue_id === state.social.selectedQueueId) || null;
    }

    function syncSocialBrowserButtons(browser) {
        dom.launchBrowserVisible.classList.toggle("primary", !browser?.ready);
        dom.launchBrowserVisible.classList.toggle("ghost", Boolean(browser?.ready));
    }

    function selectSocialItem(queueId) {
        if (!queueId || queueId === state.social.selectedQueueId) {
            return;
        }
        state.social.selectedQueueId = queueId;
        state.social.editorDirty = false;
        renderSocial({ browser: state.social.browser, queue: state.social.queue });
    }

    function updateSocialComposerActions(enabled) {
        const selected = getSelectedSocialItem();
        const replyText = dom.socialReplyEditor.value.trim();
        const overLimit = replyText.length > 240;
        const sendDisabled = !enabled || !selected || !replyText || ["sent", "skipped"].includes(selected.status) || overLimit;
        [
            dom.socialGenerateDraft,
            dom.socialSaveDraft,
            dom.socialSkipItem,
            dom.socialReplyEditor,
        ].forEach((element) => {
            element.disabled = !enabled;
        });
        dom.socialSendReply.disabled = sendDisabled;
    }

    function isSocialActionable(item) {
        return !["sent", "skipped"].includes(item.status);
    }

    function filterSocialItems(items) {
        const filter = state.social.filter;
        const query = state.social.search;
        return items.filter((item) => {
            if (filter === "actionable" && !isSocialActionable(item)) {
                return false;
            }
            if (filter !== "all" && filter !== "actionable" && item.status !== filter) {
                return false;
            }
            if (!query) {
                return true;
            }
            return [
                item.author_handle,
                item.author_name,
                item.text,
                item.draft_reply,
            ]
                .filter(Boolean)
                .join(" ")
                .toLowerCase()
                .includes(query);
        });
    }

    function updateReplyCounter() {
        const length = dom.socialReplyEditor.value.trim().length;
        dom.socialReplyCount.textContent = `${length} / 240`;
        dom.socialReplyCount.classList.toggle("is-warning", length >= 220 && length <= 240);
        dom.socialReplyCount.classList.toggle("is-danger", length > 240);
        updateSocialComposerActions(Boolean(getSelectedSocialItem()));
    }

    async function scanSocialPage() {
        dom.scanSocial.disabled = true;
        try {
            const payload = await apiRequest("/social/x/scan", {
                method: "POST",
                body: { limit: 25 },
                timeout: 30000,
            });
            state.social.browser = payload.browser || state.social.browser;
            state.social.queue = payload.queue || state.social.queue;
            renderSocial({ browser: state.social.browser, queue: state.social.queue });
            toast(`${payload.new_items || 0} yeni yorum bulundu.`, "success");
        } catch (error) {
            toast(`X sayfası taranamadı: ${error.message}`, "error");
        } finally {
            dom.scanSocial.disabled = false;
        }
    }

    async function launchSocialBrowser() {
        dom.launchBrowserVisible.disabled = true;

        try {
            const payload = await apiRequest("/social/browser/launch", {
                method: "POST",
                body: {
                    headless: false,
                    restart_if_needed: true,
                },
                timeout: 35000,
            });
            state.social.browser = payload.browser || state.social.browser;
            renderSocial({ browser: state.social.browser, queue: state.social.queue });
            toast(payload.message || "Tarayıcı görünür modda hazır.", "success");
        } catch (error) {
            toast(`Tarayıcı başlatılamadı: ${error.message}`, "error");
        } finally {
            dom.launchBrowserVisible.disabled = false;
        }
    }

    async function generateSocialDraft() {
        const selected = getSelectedSocialItem();
        if (!selected) {
            toast("Önce kuyruktan bir yorum seçin.", "warning");
            return;
        }

        dom.socialGenerateDraft.disabled = true;
        try {
            const payload = await apiRequest(`/social/x/queue/${encodeURIComponent(selected.queue_id)}/draft`, {
                method: "POST",
                body: { tone: dom.socialToneSelect.value || "samimi, kısa ve doğal" },
                timeout: 35000,
            });
            dom.socialReplyEditor.value = payload.draft || "";
            state.social.editorDirty = false;
            await fetchSocialSnapshot({ silent: true });
            toast("Taslak üretildi.", "success");
        } catch (error) {
            toast(`Taslak üretilemedi: ${error.message}`, "error");
        } finally {
            dom.socialGenerateDraft.disabled = false;
        }
    }

    async function saveSocialDraft() {
        const selected = getSelectedSocialItem();
        if (!selected) {
            toast("Önce kuyruktan bir yorum seçin.", "warning");
            return;
        }

        try {
            await apiRequest(`/social/x/queue/${encodeURIComponent(selected.queue_id)}/update`, {
                method: "POST",
                body: { text: dom.socialReplyEditor.value },
            });
            state.social.editorDirty = false;
            await fetchSocialSnapshot({ silent: true });
            toast("Taslak kaydedildi.", "success");
        } catch (error) {
            toast(`Taslak kaydedilemedi: ${error.message}`, "error");
        }
    }

    async function skipSocialItem() {
        const selected = getSelectedSocialItem();
        if (!selected) {
            toast("Önce kuyruktan bir yorum seçin.", "warning");
            return;
        }

        try {
            await apiRequest(`/social/x/queue/${encodeURIComponent(selected.queue_id)}/status`, {
                method: "POST",
                body: { status: "skipped", note: "Panelden gecildi" },
            });
            state.social.editorDirty = false;
            await fetchSocialSnapshot({ silent: true });
            toast("Yorum kuyruktan pas geçildi.", "success");
        } catch (error) {
            toast(`Yorum güncellenemedi: ${error.message}`, "error");
        }
    }

    async function sendSocialReply() {
        const selected = getSelectedSocialItem();
        if (!selected) {
            toast("Önce kuyruktan bir yorum seçin.", "warning");
            return;
        }

        const text = dom.socialReplyEditor.value.trim();
        if (!text) {
            toast("Gönderilecek cevap boş olamaz.", "warning");
            return;
        }

        dom.socialSendReply.disabled = true;
        try {
            await apiRequest(`/social/x/queue/${encodeURIComponent(selected.queue_id)}/send`, {
                method: "POST",
                body: { text },
                timeout: 35000,
            });
            state.social.editorDirty = false;
            await fetchSocialSnapshot({ silent: true });
            toast("Yorum cevabı tarayıcı üzerinden gönderildi.", "success");
        } catch (error) {
            toast(`Yorum cevabı gönderilemedi: ${error.message}`, "error");
        } finally {
            dom.socialSendReply.disabled = false;
        }
    }

    function resolveQueueStatusLabel(status) {
        const labels = {
            new: "Yeni",
            drafted: "Taslak",
            approved: "Onaylı",
            pending_verify: "Doğrulanıyor",
            sent: "Gönderildi",
            skipped: "Geçildi",
            error: "Hata",
        };
        return labels[status] || "Yeni";
    }

    function resolveHeartbeatJobStatusLabel(job) {
        if (!job) {
            return "Beklemede";
        }
        if (!job.enabled) {
            return "Devre dışı";
        }
        if (job.running) {
            return "Çalışıyor";
        }
        if (job.paused) {
            return "Duraklatıldı";
        }

        const labels = {
            idle: "Beklemede",
            success: "Başarılı",
            skipped: "Atlandı",
            error: "Hata",
            disabled: "Devre dışı",
            paused: "Duraklatıldı",
            running: "Çalışıyor",
        };
        return labels[job.last_status] || "Beklemede";
    }

    function formatDateTime(value) {
        if (!value) {
            return "-";
        }
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) {
            return value;
        }
        return parsed.toLocaleString("tr-TR");
    }

    function setConnectionState(message, tone = "neutral") {
        dom.connectionState.textContent = message;
        dom.connectionState.dataset.tone = tone;
    }

    function updateStatusChip(element, text, isOnline) {
        element.textContent = text;
        element.classList.toggle("online", isOnline);
        element.classList.toggle("offline", !isOnline);
    }

    function markSync() {
        state.lastSyncAt = new Date();
        dom.lastSyncLabel.textContent = `Son senkron: ${state.lastSyncAt.toLocaleTimeString("tr-TR")}`;
    }

    function formatUptime(totalSeconds) {
        const seconds = Number(totalSeconds || 0);
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        if (hours > 0) {
            return `${hours}sa ${minutes}dk`;
        }
        if (minutes > 0) {
            return `${minutes}dk`;
        }
        return `${Math.max(0, Math.floor(seconds))}sn`;
    }

    function resolveAgentIcon(name) {
        if (name.includes("browser")) {
            return "🌐";
        }
        if (name.includes("content")) {
            return "🎨";
        }
        if (name.includes("vlm")) {
            return "📸";
        }
        if (name.includes("sistem")) {
            return "🛠";
        }
        if (name.includes("arastirma")) {
            return "🔎";
        }
        return "🤖";
    }

    function toast(message, tone = "info") {
        const item = document.createElement("div");
        item.className = `toast ${tone}`;
        item.textContent = message;
        dom.toastRegion.appendChild(item);

        window.setTimeout(() => {
            item.classList.add("is-leaving");
            window.setTimeout(() => item.remove(), 300);
        }, 2800);
    }
});
