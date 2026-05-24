import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import { createRouter, createMemoryHistory } from "vue-router"
import { isReactive } from "vue"

vi.mock("@/utils/api", () => ({
  attachAPI: { getCreaturePolicies: vi.fn(), getSessionPolicies: vi.fn() },
  configAPI: { listCreatures: vi.fn(), listTerrariums: vi.fn(), getServerInfo: vi.fn() },
  sessionAPI: {
    listActive: vi.fn().mockResolvedValue([]),
    getActive: vi.fn().mockResolvedValue(null),
  },
  settingsAPI: {
    getBackends: vi.fn().mockResolvedValue([]),
    listMCP: vi.fn().mockResolvedValue([]),
  },
  statsAPI: {
    diskUsage: vi.fn().mockResolvedValue({ count: 0, total_bytes: 0 }),
    metrics: vi.fn().mockResolvedValue({ rates: { llm: [], error: [] }, histograms: {} }),
    sessionStats: vi.fn().mockResolvedValue({ by_recency: { "1d": 0 } }),
  },
  terrariumAPI: { list: vi.fn().mockResolvedValue([]) },
  agentAPI: { list: vi.fn().mockResolvedValue([]) },
  nodesAPI: {
    list: vi.fn().mockResolvedValue({ nodes: [] }),
    status: vi.fn(),
    deployCreature: vi.fn(),
  },
}))

import MacroShell from "./MacroShell.vue"
import RailItem from "./RailItem.vue"
import { registerBuiltinTabKinds, _resetBuiltinTabKindsForTests } from "./registerBuiltins"
import { useTabsStore } from "@/stores/tabs"
import { sessionAPI } from "@/utils/api"
import { tabKinds, inspectorInnerTabs, railGroups } from "@/stores/tabKindRegistry"

let storage

beforeEach(() => {
  storage = new Map()
  vi.stubGlobal("localStorage", {
    getItem: (k) => (storage.has(k) ? storage.get(k) : null),
    setItem: (k, v) => storage.set(k, String(v)),
    removeItem: (k) => storage.delete(k),
    clear: () => storage.clear(),
    get length() {
      return storage.size
    },
    key: (i) => Array.from(storage.keys())[i] ?? null,
  })
  setActivePinia(createPinia())
  _resetBuiltinTabKindsForTests()
  tabKinds.clear()
  inspectorInnerTabs.clear()
  railGroups.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/", component: { template: "<div />" } }],
  })
}

function sessionPayload(id, name, creatures = [{ name, running: true }]) {
  return { session_id: id, name, creatures, channels: [] }
}

function mockActiveSessions(sessions) {
  sessionAPI.listActive.mockResolvedValue(sessions)
  sessionAPI.getActive.mockImplementation(async (id) => sessions.find((s) => s.session_id === id) ?? null)
}

describe("MacroShell — tab registration", () => {
  it("registers all built-in tab kinds centrally", () => {
    registerBuiltinTabKinds()

    for (const kind of [
      "dashboard",
      "attach",
      "inspector",
      "session-viewer",
      "saved-sessions",
      "stats",
      "studio-editor",
      "catalog",
      "extensions",
      "settings",
      "code-editor",
      "graph-editor",
    ]) {
      const entry = tabKinds.get(kind)
      expect(entry, `${kind} should be registered`).toBeTruthy()
      expect(entry.component, `${kind} should have a component`).toBeTruthy()
    }
  })
  it("keeps registered tab components raw so Vue does not proxy component definitions", () => {
    registerBuiltinTabKinds()

    for (const kind of ["dashboard", "inspector", "attach", "session-viewer"]) {
      const entry = tabKinds.get(kind)
      expect(entry).toBeTruthy()
      expect(isReactive(entry.component), `${kind} component should stay raw`).toBe(false)
    }

    for (const id of ["overview", "activity", "trace", "log"]) {
      const entry = inspectorInnerTabs.get(id)
      expect(entry).toBeTruthy()
      expect(isReactive(entry.component), `${id} inspector tab should stay raw`).toBe(false)
    }
  })
})

describe("MacroShell — render", () => {
  it("mounts and shows the rail + tab strip + content", async () => {
    const router = makeRouter()
    const wrapper = mount(MacroShell, {
      global: { plugins: [router] },
    })
    await router.isReady()
    // Rail brand
    expect(wrapper.text()).toContain("Kohaku")
    expect(wrapper.text()).toContain("Terrarium")
    // Quick group entries
    expect(wrapper.text()).toContain("Catalog")
    expect(wrapper.text()).toContain("Studio")
    expect(wrapper.text()).toContain("Settings")
    // Pinned group placeholder
    expect(wrapper.text()).toContain("No pinned tabs")
  })

  it("opens a default Dashboard tab on mount when none in URL", async () => {
    const router = makeRouter()
    const wrapper = mount(MacroShell, {
      global: { plugins: [router] },
    })
    await router.isReady()
    await wrapper.vm.$nextTick()
    const tabs = useTabsStore()
    // After onMounted, dashboard tab should exist.
    expect(tabs.tabs.some((t) => t.kind === "dashboard")).toBe(true)
  })

  it("renders one RailItem per running instance", async () => {
    const router = makeRouter()
    mockActiveSessions([
      sessionPayload("agent-1", "alice"),
      sessionPayload("graph-1", "swe-graph", [
        { name: "root", running: true, is_root: true },
        { name: "worker", running: true },
      ]),
    ])
    const wrapper = mount(MacroShell, {
      global: { plugins: [router] },
    })
    await router.isReady()
    await wrapper.vm.$nextTick()
    const items = wrapper.findAllComponents(RailItem)
    expect(items).toHaveLength(2)
    expect(wrapper.text()).toContain("alice")
    expect(wrapper.text()).toContain("swe-graph")
  })
})

describe("MacroShell — density branch", () => {
  it("renders CompactShell (not RailPane) at compact density", async () => {
    // Narrow viewport BEFORE the composable initializes.
    window.innerWidth = 600
    const { _resetDensityForTests } = await import("@/composables/useDensity")
    _resetDensityForTests()

    const router = makeRouter()
    const wrapper = mount(MacroShell, {
      global: { plugins: [router] },
    })
    await router.isReady()
    // CompactShell renders a hamburger + density-override button; the
    // regular shell renders the BrandMark with full "Kohaku Terrarium"
    // text and rail group entries like "No pinned tabs".
    expect(wrapper.text()).not.toContain("No pinned tabs")

    // Restore for downstream tests.
    window.innerWidth = 1024
    _resetDensityForTests()
  })

  it("renders the regular shell at desktop viewport", async () => {
    window.innerWidth = 1024
    const { _resetDensityForTests } = await import("@/composables/useDensity")
    _resetDensityForTests()

    const router = makeRouter()
    const wrapper = mount(MacroShell, {
      global: { plugins: [router] },
    })
    await router.isReady()
    expect(wrapper.text()).toContain("No pinned tabs")
  })
})

describe("MacroShell — surface indicators", () => {
  it("rail [C] click opens an attach tab; second click closes", async () => {
    const router = makeRouter()
    mockActiveSessions([sessionPayload("agent-1", "alice")])
    const wrapper = mount(MacroShell, {
      global: { plugins: [router] },
    })
    await router.isReady()
    await wrapper.vm.$nextTick()
    const tabs = useTabsStore()
    const railItem = wrapper.findComponent(RailItem)
    // Find the [C] button (first surface indicator)
    const buttons = railItem.findAll("button")
    const cBtn = buttons.find((b) => b.text() === "C")
    expect(cBtn).toBeDefined()
    await cBtn.trigger("click")
    expect(tabs.surfaceTabsForTarget("agent-1").chat).toBeDefined()
    await cBtn.trigger("click")
    expect(tabs.surfaceTabsForTarget("agent-1").chat).toBeUndefined()
  })

  it("rail [I] click opens an inspector tab", async () => {
    const router = makeRouter()
    mockActiveSessions([sessionPayload("agent-1", "alice")])
    const wrapper = mount(MacroShell, {
      global: { plugins: [router] },
    })
    await router.isReady()
    await wrapper.vm.$nextTick()
    const tabs = useTabsStore()
    const railItem = wrapper.findComponent(RailItem)
    const iBtn = railItem.findAll("button").find((b) => b.text() === "I")
    expect(iBtn).toBeDefined()
    await iBtn.trigger("click")
    expect(tabs.surfaceTabsForTarget("agent-1").inspector).toBeDefined()
  })
})
