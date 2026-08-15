import { flushPromises, mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import { nextTick } from "vue"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/utils/api", () => ({
  configAPI: { getModels: vi.fn() },
}))

vi.mock("@/components/chrome/ModelSwitcher.vue", () => ({
  default: { template: "<div />" },
}))

import ModelTab from "./ModelTab.vue"
import { useChatStore } from "@/stores/chat"
import { configAPI } from "@/utils/api"
import { fireModelCatalogChanged } from "@/utils/layoutEvents"

describe("ModelTab", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
  })

  it("keeps the newest profile when the active model changes", async () => {
    const chat = useChatStore()
    chat.activeTab = "root"
    chat.modelByTab.root = { llmName: "openai/old" }
    let resolveOld
    let resolveNew
    configAPI.getModels
      .mockReturnValueOnce(new Promise((resolve) => (resolveOld = resolve)))
      .mockReturnValueOnce(new Promise((resolve) => (resolveNew = resolve)))

    const wrapper = mount(ModelTab)
    await nextTick()
    chat.modelByTab.root.llmName = "anthropic/new"
    await nextTick()

    resolveNew([{ provider: "anthropic", name: "new", max_context: 3000 }])
    await flushPromises()
    expect(wrapper.text()).toContain("anthropic")
    expect(wrapper.text()).toContain("3.0k")

    resolveOld([{ provider: "openai", name: "old", max_context: 1000 }])
    await flushPromises()
    expect(wrapper.text()).toContain("anthropic")
    expect(wrapper.text()).not.toContain("openai")
    expect(wrapper.text()).toContain("3.0k")
    wrapper.unmount()
  })

  it("matches the qualified provider and reloads while mounted", async () => {
    const chat = useChatStore()
    chat.activeTab = "root"
    chat.modelByTab.root = { llmName: "openai/shared@reasoning=high" }
    configAPI.getModels
      .mockResolvedValueOnce([
        { provider: "anthropic", name: "shared", max_context: 1000 },
        { provider: "openai", name: "shared", max_context: 2000 },
      ])
      .mockResolvedValueOnce([{ provider: "openai", name: "shared", max_context: 3000 }])

    const wrapper = mount(ModelTab)
    await flushPromises()
    expect(wrapper.text()).toContain("openai")
    expect(wrapper.text()).toContain("2.0k")
    expect(wrapper.text()).not.toContain("anthropic")

    fireModelCatalogChanged()
    await flushPromises()
    expect(configAPI.getModels).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain("3.0k")

    wrapper.unmount()
    fireModelCatalogChanged()
    await flushPromises()
    expect(configAPI.getModels).toHaveBeenCalledTimes(2)
  })
})
