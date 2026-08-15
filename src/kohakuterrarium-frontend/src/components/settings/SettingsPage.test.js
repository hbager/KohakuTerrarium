import { describe, expect, it, vi, beforeEach } from "vitest"
import { mount, flushPromises } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import { nextTick, defineComponent } from "vue"

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

vi.mock("@/utils/i18n", () => ({
  useI18n: () => ({
    t: (key, vars) => (vars?.name ? `${key}:${vars.name}` : key),
  }),
}))

vi.mock("@/composables/useDensity", () => ({
  useDensity: () => ({ isCompact: { value: false } }),
}))

vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({ currentUser: null }),
}))

vi.mock("@/stores/cluster", () => ({
  useClusterStore: () => ({ isCluster: false }),
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
    dark: false,
    desktopZoom: 1,
    mobileZoom: 1,
    toggle: vi.fn(),
    setDesktopZoom: vi.fn(),
    setMobileZoom: vi.fn(),
  }),
}))

vi.mock("@/utils/api", () => ({
  configAPI: { getModels: vi.fn() },
  settingsAPI: {
    getKeys: vi.fn(),
    getBackends: vi.fn(),
    getNativeTools: vi.fn(),
    listMCP: vi.fn(),
    setDefaultModel: vi.fn(),
    getCodexUsage: vi.fn(),
  },
}))

vi.mock("@/components/account/AccountSection.vue", () => ({ default: { template: "<div />" } }))
vi.mock("@/components/settings/AboutPanel.vue", () => ({ default: { template: "<div />" } }))
vi.mock("@/components/settings/AdvancedPanel.vue", () => ({ default: { template: "<div />" } }))
vi.mock("@/components/settings/BackendForm.vue", () => ({ default: { template: "<div />" } }))
vi.mock("@/components/settings/CodexLoginModal.vue", () => ({ default: { template: "<div />" } }))
vi.mock("@/components/settings/modals/MCPServerEditModal.vue", () => ({
  default: { template: "<div />" },
}))
vi.mock("@/components/settings/SitesPane.vue", () => ({ default: { template: "<div />" } }))
vi.mock("@/components/settings/UpdatesPanel.vue", () => ({ default: { template: "<div />" } }))
vi.mock("@/components/cluster/SitePicker.vue", () => ({ default: { template: "<div />" } }))
vi.mock("@/components/settings/DriveSettingsPanel.vue", () => ({ default: { template: "<div />" } }))
vi.mock("@/components/settings/PresetEditor.vue", () => ({
  default: defineComponent({
    props: ["preset", "backends", "mode"],
    emits: ["set-default"],
    template:
      "<button class='set-default' @click='$emit(\"set-default\", preset)'>settings.models.setAsDefault</button>",
  }),
}))

import SettingsPage from "./SettingsPage.vue"
import { configAPI, settingsAPI } from "@/utils/api"

const tabsStub = {
  props: ["modelValue"],
  template: "<div><slot /></div>",
}
const tabPaneStub = {
  props: ["label", "name"],
  template: "<section><slot /></section>",
}

function mountSettingsPage() {
  return mount(SettingsPage, {
    global: {
      stubs: {
        "el-tabs": tabsStub,
        "el-tab-pane": tabPaneStub,
        "el-input": { template: "<div />" },
        "el-button": {
          template: "<button v-bind='$attrs' @click='$emit(\"click\")'><slot /></button>",
        },
        "el-tag": { template: "<span><slot /></span>" },
        "el-select": { template: "<select><slot /></select>" },
        "el-option": { template: "<option />" },
        "el-input-number": { template: "<input />" },
        "el-checkbox-group": { template: "<div><slot /></div>" },
        "el-switch": { template: "<button />" },
        "el-popconfirm": { template: "<div><slot name='reference' /></div>" },
      },
    },
  })
}

describe("SettingsPage default model selection", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    settingsAPI.getKeys.mockResolvedValue({ providers: [] })
    settingsAPI.getBackends.mockResolvedValue({
      backends: [{ name: "openrouter", built_in: true }],
    })
    settingsAPI.getNativeTools.mockResolvedValue({ tools: [] })
    settingsAPI.listMCP.mockResolvedValue({ servers: [] })
    configAPI.getModels.mockResolvedValue([
      {
        provider: "openrouter",
        name: "gpt-5.5-custom",
        model: "openrouter/gpt-5.5",
        source: "user",
        available: true,
        variation_groups: {},
        selected_variations: { speed: "fast", reasoning: "xhigh" },
      },
    ])
    settingsAPI.setDefaultModel.mockResolvedValue({
      status: "set",
      default_model: "openrouter/gpt-5.5-custom",
    })
  })

  it("sets the default model using the provider-qualified selector", async () => {
    const wrapper = mountSettingsPage()
    await flushPromises()
    await nextTick()

    const presetRow = wrapper
      .findAll("button")
      .find((button) => button.text().includes("gpt-5.5-custom"))
    expect(presetRow).toBeTruthy()
    await presetRow.trigger("click")
    await nextTick()

    const setDefaultButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("settings.models.setAsDefault"))
    expect(setDefaultButton).toBeTruthy()
    await setDefaultButton.trigger("click")
    await flushPromises()
    await nextTick()

    expect(settingsAPI.setDefaultModel).toHaveBeenCalledWith(
      "openrouter/gpt-5.5-custom@reasoning=xhigh,speed=fast",
    )
  })
})
