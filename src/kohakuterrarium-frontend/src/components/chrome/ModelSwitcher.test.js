import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"

const mockCurrentInstance = vi.hoisted(() => ({
  value: { id: "agent-1", type: "creature", llm_name: "openai/gpt" },
}))

vi.mock("@element-plus/icons-vue", () => ({
  ArrowDown: { template: "<span />" },
}))

vi.mock("@/utils/api", () => ({
  configAPI: { getModels: vi.fn() },
  agentAPI: {},
  sessionAPI: { getActive: vi.fn(), listActive: vi.fn() },
  terrariumAPI: { switchCreatureModel: vi.fn() },
}))

vi.mock("@/components/chrome/instanceContext", () => ({
  useInstanceContext: () => ({
    instance: mockCurrentInstance,
  }),
}))

vi.mock("vue-router", () => ({
  useRoute: () => ({ params: {} }),
}))

import ModelSwitcher from "./ModelSwitcher.vue"
import { configAPI, sessionAPI, terrariumAPI } from "@/utils/api"
import { useChatStore } from "@/stores/chat"
import { LAYOUT_EVENTS } from "@/utils/layoutEvents"

const mountedWrappers = []

beforeEach(() => {
  setActivePinia(createPinia())
  mockCurrentInstance.value = { id: "agent-1", type: "creature", llm_name: "openai/gpt" }
  vi.clearAllMocks()
})

afterEach(() => {
  mountedWrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  vi.unstubAllGlobals()
})

async function flushPromises() {
  await Promise.resolve()
  await Promise.resolve()
}

describe("ModelSwitcher — workspace model catalog refresh", () => {
  it("prefills default variations when the current selector only has the base model", async () => {
    mockCurrentInstance.value = {
      id: "agent-1",
      type: "creature",
      llm_name: "aaaaa/gpt-5.5-custom",
    }
    configAPI.getModels.mockResolvedValueOnce([
      {
        provider: "aaaaa",
        name: "gpt-5.5-custom",
        model: "gpt-5.5",
        available: true,
        is_default: true,
        selected_variations: { reasoning: "xhigh", speed: "fast" },
        variation_groups: {
          reasoning: { none: {}, low: {}, medium: {}, high: {}, xhigh: {} },
          speed: { normal: {}, fast: {} },
        },
      },
    ])

    const wrapper = mount(ModelSwitcher, {
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
    mountedWrappers.push(wrapper)
    await flushPromises()

    expect(wrapper.text()).toContain("aaaaa/gpt-5.5-custom@reasoning=xhigh,speed=fast")
  })

  it("updates the active session with the resolved selector returned by switch", async () => {
    mockCurrentInstance.value = {
      id: "agent-1",
      graph_id: "graph-1",
      type: "creature",
      llm_name: "aaaaa/gpt-5.5-custom",
      creatures: [{ name: "patient-summit" }],
    }
    configAPI.getModels.mockResolvedValueOnce([
      {
        provider: "aaaaa",
        name: "gpt-5.5-custom",
        model: "gpt-5.5",
        available: true,
        is_default: true,
        selected_variations: { reasoning: "xhigh", speed: "fast" },
        variation_groups: {
          reasoning: { none: {}, low: {}, medium: {}, high: {}, xhigh: {} },
          speed: { normal: {}, fast: {} },
        },
      },
    ])
    terrariumAPI.switchCreatureModel.mockResolvedValueOnce({
      status: "switched",
      model: "aaaaa/gpt-5.5-custom@reasoning=xhigh,speed=fast",
    })
    sessionAPI.getActive.mockResolvedValueOnce({
      session_id: "agent-1",
      name: "patient-summit",
      creatures: [
        {
          name: "patient-summit",
          creature_id: "agent-1",
          running: true,
          model: "gpt-5.5",
          llm_name: "aaaaa/gpt-5.5-custom@reasoning=xhigh,speed=fast",
        },
      ],
    })

    const wrapper = mount(ModelSwitcher, {
      props: { instanceId: "agent-1" },
      global: {
        stubs: {
          "el-select": { template: "<div><slot /></div>" },
          "el-option": { template: "<div />" },
          "el-popover": { template: "<div><slot name='reference' /><slot /></div>" },
          "el-input": { template: "<div />" },
          "el-button": { template: "<button v-bind='$attrs'><slot /></button>" },
          "el-icon": { template: "<span><slot /></span>" },
        },
      },
    })
    mountedWrappers.push(wrapper)
    await flushPromises()

    const switchButton = wrapper
      .findAll("button")
      .find((button) => button.text().trim() === "Switch")
    await switchButton.trigger("click")
    await flushPromises()

    const chat = useChatStore()
    expect(terrariumAPI.switchCreatureModel).toHaveBeenCalledWith(
      "graph-1",
      "patient-summit",
      "aaaaa/gpt-5.5-custom@reasoning=xhigh,speed=fast",
    )
    expect(chat.sessionInfo.llmName).toBe("aaaaa/gpt-5.5-custom@reasoning=xhigh,speed=fast")
  })

  it("reloads models when settings changes the model catalog", async () => {
    configAPI.getModels
      .mockResolvedValueOnce([{ provider: "openai", name: "gpt", model: "gpt", available: true }])
      .mockResolvedValueOnce([
        { provider: "local", name: "llama", model: "llama", available: true },
      ])

    const wrapper = mount(ModelSwitcher, {
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
    mountedWrappers.push(wrapper)
    await flushPromises()
    expect(configAPI.getModels).toHaveBeenCalledTimes(1)

    window.dispatchEvent(new CustomEvent(LAYOUT_EVENTS.MODEL_CATALOG_CHANGED, { detail: {} }))
    await flushPromises()

    expect(configAPI.getModels).toHaveBeenCalledTimes(2)
  })
})
