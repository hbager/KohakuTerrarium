/**
 * Panel + preset registration. Called once from main.js (synchronous).
 *
 * Presets use a binary split tree:
 *   SplitNode = { type: "split", direction: "horizontal"|"vertical",
 *                 ratio: 0-100, children: [Node, Node] }
 *   LeafNode  = { type: "leaf", panelId: string }
 */

import { defineAsyncComponent } from "vue"

import { useLayoutStore } from "@/stores/layout"

const ChatPanel = defineAsyncComponent(() => import("@/components/chat/ChatPanel.vue"))
const EditorMain = defineAsyncComponent(() => import("@/components/editor/EditorMain.vue"))
const EditorStatus = defineAsyncComponent(() => import("@/components/editor/EditorStatus.vue"))
const FileTree = defineAsyncComponent(() => import("@/components/editor/FileTree.vue"))
const CanvasPanel = defineAsyncComponent(() => import("@/components/panels/CanvasPanel.vue"))
const CreaturesPanel = defineAsyncComponent(() => import("@/components/panels/CreaturesPanel.vue"))
const DebugPanel = defineAsyncComponent(() => import("@/components/panels/DebugPanel.vue"))
const FilesPanel = defineAsyncComponent(() => import("@/components/panels/FilesPanel.vue"))
const ActivityPanel = defineAsyncComponent(() => import("@/components/panels/ActivityPanel.vue"))
const SettingsPanel = defineAsyncComponent(() => import("@/components/panels/SettingsPanel.vue"))
const StatePanel = defineAsyncComponent(() => import("@/components/panels/StatePanel.vue"))
const TerminalPanel = defineAsyncComponent(() => import("@/components/panels/TerminalPanel.vue"))
const ModulesPanel = defineAsyncComponent(
  () => import("@/components/panels/modules/ModulesPanel.vue"),
)
const StatusDashboard = defineAsyncComponent(
  () => import("@/components/status/StatusDashboard.vue"),
)
const StatusDashboardTab = defineAsyncComponent(
  () => import("@/components/status/StatusDashboardTab.vue"),
)

// ─── Helper to build tree nodes concisely ────────────────────────

function leaf(panelId) {
  return { type: "leaf", panelId }
}

function hsplit(ratio, left, right) {
  return {
    type: "split",
    direction: "horizontal",
    ratio,
    children: [left, right],
  }
}

function vsplit(ratio, top, bottom) {
  return {
    type: "split",
    direction: "vertical",
    ratio,
    children: [top, bottom],
  }
}

// ─── Presets ─────────────────────────────────────────────────────

/** Chat focus — default for single-creature instances.
 *  chat | status-dashboard(top) + modules(bottom). Modules replaces
 *  the legacy ``state`` slot — runtime config is the more useful
 *  default than scratchpad inspection. ``state`` panel is still
 *  registered and reachable via the panel picker. */
const CHAT_FOCUS_PRESET = {
  id: "chat-focus",
  label: "Chat Focus",
  shortcut: "Ctrl+1",
  tree: hsplit(70, leaf("chat"), vsplit(65, leaf("status-dashboard"), leaf("modules"))),
}

/** Workspace — files + editor + chat for code-work creatures. */
const WORKSPACE_PRESET = {
  id: "workspace",
  label: "Workspace",
  shortcut: "Ctrl+2",
  tree: hsplit(
    20,
    leaf("files"),
    hsplit(62, leaf("monaco-editor"), vsplit(65, leaf("chat"), leaf("status-tab"))),
  ),
}

/** Chat + Terminal — chat left, terminal top-right, state + status bottom-right. */
const CHAT_TERMINAL_PRESET = {
  id: "chat-terminal",
  label: "Chat + Terminal",
  shortcut: "Ctrl+6",
  tree: hsplit(
    50,
    leaf("chat"),
    vsplit(65, leaf("terminal"), hsplit(50, leaf("state"), leaf("status-tab"))),
  ),
}

/** Multi-creature — default for terrarium instances. */
const MULTI_CREATURE_PRESET = {
  id: "multi-creature",
  label: "Multi-creature",
  shortcut: "Ctrl+3",
  tree: hsplit(
    18,
    leaf("creatures"),
    hsplit(66, leaf("chat"), vsplit(50, leaf("status-dashboard"), leaf("state"))),
  ),
}

/** Canvas — chat on left, canvas + modules on right. ``modules`` here
 *  takes the slot the legacy ``tool-options`` panel used to occupy
 *  (provider-native tool options) — the unified module surface
 *  subsumes that. */
const CANVAS_PRESET = {
  id: "canvas",
  label: "Canvas",
  shortcut: "Ctrl+4",
  tree: hsplit(45, leaf("chat"), vsplit(70, leaf("canvas"), leaf("modules"))),
}

/** Debug — chat + state + debug drawer. */
const DEBUG_PRESET = {
  id: "debug",
  label: "Debug",
  shortcut: "Ctrl+5",
  tree: vsplit(55, hsplit(60, leaf("chat"), leaf("state")), leaf("debug")),
}

const SETTINGS_PRESET = {
  id: "settings",
  label: "Settings",
  tree: hsplit(62, leaf("chat"), vsplit(55, leaf("settings"), leaf("activity"))),
}

/** Legacy instance (old layout compat). */
const LEGACY_INSTANCE_PRESET = {
  id: "legacy-instance",
  label: "Legacy Instance",
  tree: hsplit(65, leaf("chat"), leaf("status-dashboard")),
}

/** Legacy editor (old layout compat). */
const LEGACY_EDITOR_PRESET = {
  id: "legacy-editor",
  label: "Legacy Editor",
  tree: hsplit(
    20,
    leaf("file-tree"),
    hsplit(60, leaf("monaco-editor"), vsplit(70, leaf("chat"), leaf("editor-status"))),
  ),
}

export const DEFAULT_PRESETS = [
  CHAT_FOCUS_PRESET,
  WORKSPACE_PRESET,
  MULTI_CREATURE_PRESET,
  CANVAS_PRESET,
  DEBUG_PRESET,
  SETTINGS_PRESET,
  CHAT_TERMINAL_PRESET,
]

// ─── Registration ────────────────────────────────────────────────

export function registerBuiltinPanels() {
  const layout = useLayoutStore()

  // ── Panels ──
  layout.registerPanel({ id: "chat", label: "Chat", component: ChatPanel })
  layout.registerPanel({
    id: "status-dashboard",
    label: "Status",
    component: StatusDashboard,
  })
  layout.registerPanel({
    id: "file-tree",
    label: "File Tree",
    component: FileTree,
  })
  layout.registerPanel({
    id: "monaco-editor",
    label: "Editor",
    component: EditorMain,
  })
  // Legacy alias — legacy-editor preset references this id.
  layout.registerPanel({
    id: "editor-status",
    label: "Activity",
    component: EditorStatus,
  })
  layout.registerPanel({ id: "files", label: "Files", component: FilesPanel })
  layout.registerPanel({ id: "activity", label: "Activity", component: ActivityPanel })
  layout.registerPanel({ id: "settings", label: "Settings", component: SettingsPanel })
  layout.registerPanel({ id: "state", label: "State", component: StatePanel })
  layout.registerPanel({
    id: "creatures",
    label: "Creatures",
    component: CreaturesPanel,
  })
  layout.registerPanel({
    id: "canvas",
    label: "Canvas",
    component: CanvasPanel,
  })
  layout.registerPanel({ id: "debug", label: "Debug", component: DebugPanel })
  layout.registerPanel({
    id: "status-tab",
    label: "Status",
    component: StatusDashboardTab,
  })
  layout.registerPanel({
    id: "terminal",
    label: "Terminal",
    component: TerminalPanel,
  })
  layout.registerPanel({
    id: "modules",
    label: "Modules",
    component: ModulesPanel,
  })

  // ── Presets ──
  layout.registerBuiltinPreset(LEGACY_INSTANCE_PRESET)
  layout.registerBuiltinPreset(LEGACY_EDITOR_PRESET)
  for (const preset of DEFAULT_PRESETS) {
    layout.registerBuiltinPreset(preset)
  }
}
