import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"

vi.mock("@element-plus/icons-vue", () => ({
  ArrowDown: { template: "<span />" },
}))

vi.mock("@/utils/api", () => ({
  configAPI: { getModels: vi.fn() },
  agentAPI: {},
  terrariumAPI: { switchCreatureModel: vi.fn() },
}))

vi.mock("@/components/chrome/instanceContext", () => ({
  useInstanceContext: () => ({
    instance: { value: { id: "agent-1", type: "creature", llm_name: "openai/gpt" } },
  }),
}))

vi.mock("vue-router", () => ({
  useRoute: () => ({ params: {} }),
}))

import ModelSwitcher from "./ModelSwitcher.vue"
import { configAPI } from "@/utils/api"
import { LAYOUT_EVENTS } from "@/utils/layoutEvents"

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

async function flushPromises() {
  await Promise.resolve()
  await Promise.resolve()
}

describe("ModelSwitcher — workspace model catalog refresh", () => {
  it("reloads models when settings changes the model catalog", async () => {
    configAPI.getModels
      .mockResolvedValueOnce([{ provider: "openai", name: "gpt", model: "gpt", available: true }])
      .mockResolvedValueOnce([{ provider: "local", name: "llama", model: "llama", available: true }])

    mount(ModelSwitcher, {
      props: { instanceId: "agent-1" },
      global: {
        stubs: {
          "el-select": { template: "<div><slot /></div>" },
          "el-option": { template: "<div />" },
          "el-popover": { template: "<div><slot name='reference' /><slot /></div>" },
          "el-input": { template: "<div />" },
          "el-button": { template: "<button><slot /></button>" },
          "el-icon": { template: "<span><slot /></span>" },
        },
      },
    })
    await flushPromises()
    expect(configAPI.getModels).toHaveBeenCalledTimes(1)

    window.dispatchEvent(new CustomEvent(LAYOUT_EVENTS.MODEL_CATALOG_CHANGED, { detail: {} }))
    await flushPromises()

    expect(configAPI.getModels).toHaveBeenCalledTimes(2)
  })
})
