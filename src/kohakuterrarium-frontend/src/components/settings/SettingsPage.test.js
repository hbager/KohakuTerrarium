import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"

const mockSettingsAPI = vi.hoisted(() => ({
  getKeys: vi.fn(),
  getBackends: vi.fn(),
  getNativeTools: vi.fn(),
  setDefaultModel: vi.fn(),
}))

const mockConfigAPI = vi.hoisted(() => ({
  getModels: vi.fn(),
}))

vi.mock("@/utils/api", () => ({
  settingsAPI: mockSettingsAPI,
  configAPI: mockConfigAPI,
}))

vi.mock("@/utils/i18n", () => ({
  useI18n: () => ({
    t: (key, params) => (params?.name ? `${key}:${params.name}` : key),
  }),
}))

vi.mock("@/utils/layoutEvents", () => ({
  fireModelCatalogChanged: vi.fn(),
}))

vi.mock("@/composables/useDensity", () => ({
  useDensity: () => ({ isCompact: { value: false } }),
}))

vi.mock("@/stores/cluster", () => ({
  useClusterStore: () => ({ nodes: [] }),
}))

vi.mock("@/stores/locale", () => ({
  LOCALE_DISPLAY_NAMES: { "zh-TW": "繁體中文" },
  SUPPORTED_LOCALES: ["zh-TW"],
  useLocaleStore: () => ({ locale: "zh-TW", setLocale: vi.fn() }),
}))

vi.mock("@/stores/theme", () => ({
  DEFAULT_DESKTOP_ZOOM: 1,
  DEFAULT_MOBILE_ZOOM: 1,
  MAX_UI_ZOOM: 1.5,
  MIN_UI_ZOOM: 0.75,
  useThemeStore: () => ({
    mode: "light",
    density: "comfortable",
    desktopZoom: 1,
    mobileZoom: 1,
    setMode: vi.fn(),
    setDensity: vi.fn(),
    setDesktopZoom: vi.fn(),
    setMobileZoom: vi.fn(),
  }),
}))

vi.mock("element-plus", () => ({
  ElMessage: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  },
  ElMessageBox: {
    confirm: vi.fn(),
  },
}))

import { ElMessage } from "element-plus"
import SettingsPage from "./SettingsPage.vue"

const passthrough = { template: "<div><slot /></div>" }

function mountSettings() {
  return mount(SettingsPage, {
    global: {
      stubs: {
        "el-tabs": passthrough,
        "el-tab-pane": passthrough,
        "el-button": { template: "<button @click='$emit(\"click\")'><slot /></button>" },
        "el-input": { template: "<div><slot /></div>" },
        "el-switch": { template: "<div />" },
        "el-tag": passthrough,
        "el-popconfirm": passthrough,
        "el-select": passthrough,
        "el-option": passthrough,
        "el-slider": passthrough,
        SitePicker: { template: "<div />" },
        AboutPanel: { template: "<div />" },
        AdvancedPanel: { template: "<div />" },
        BackendForm: { template: "<div />" },
        CodexLoginModal: { template: "<div />" },
        MCPServerEditModal: { template: "<div />" },
        SitesPane: { template: "<div />" },
        UpdatesPanel: { template: "<div />" },
        PresetEditor: {
          props: ["preset", "backends", "mode"],
          emits: ["set-default"],
          template:
            "<div><button class='set-default' @click='$emit(\"set-default\", preset)'>set default</button><button class='set-default-fast' @click='$emit(\"set-default\", { ...preset, selected_variations: { reasoning: \"xhigh\", speed: \"fast\" } })'>set default fast</button></div>",
        },
      },
    },
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  mockSettingsAPI.getKeys.mockResolvedValue({ providers: [] })
  mockSettingsAPI.getBackends.mockResolvedValue({ backends: [] })
  mockSettingsAPI.getNativeTools.mockResolvedValue({ tools: [] })
  mockSettingsAPI.setDefaultModel.mockResolvedValue({ status: "set" })
  mockConfigAPI.getModels.mockResolvedValue([
    {
      provider: "openrouter",
      name: "mimo-v2-pro",
      model: "minimax/mimo-v2-pro",
      available: true,
      source: "preset",
    },
  ])
})

describe("SettingsPage model defaults", () => {
  it("sets the default model with a provider-qualified selector", async () => {
    const wrapper = mountSettings()
    await flushPromises()

    await wrapper.find(".preset-row").trigger("click")
    await flushPromises()
    await wrapper.find(".set-default").trigger("click")
    await flushPromises()

    expect(mockSettingsAPI.setDefaultModel).toHaveBeenCalledWith("openrouter/mimo-v2-pro")
  })

  it("preserves selected variations when setting the default model", async () => {
    const wrapper = mountSettings()
    await flushPromises()

    await wrapper.find(".preset-row").trigger("click")
    await flushPromises()
    await wrapper.find(".set-default-fast").trigger("click")
    await flushPromises()

    expect(mockSettingsAPI.setDefaultModel).toHaveBeenCalledWith(
      "openrouter/mimo-v2-pro@reasoning=xhigh,speed=fast",
    )
  })

  it("does not show an error after successfully setting the default", async () => {
    const wrapper = mountSettings()
    await flushPromises()

    await wrapper.find(".preset-row").trigger("click")
    await flushPromises()
    await wrapper.find(".set-default").trigger("click")
    await flushPromises()

    expect(ElMessage.success).toHaveBeenCalled()
    expect(ElMessage.error).not.toHaveBeenCalled()
  })
})
