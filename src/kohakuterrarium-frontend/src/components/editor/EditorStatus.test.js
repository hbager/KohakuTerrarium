import { mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import { nextTick } from "vue"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/utils/i18n", () => ({
  useI18n: () => ({ t: (key) => key }),
}))

vi.mock("@/utils/api", () => ({
  agentAPI: {},
  terrariumAPI: { stopCreatureTask: vi.fn() },
}))

vi.mock("@/components/common/StatusDot.vue", () => ({
  default: { template: "<span />" },
}))

import EditorStatus from "./EditorStatus.vue"
import { useChatStore } from "@/stores/chat"

describe("EditorStatus", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it("does not borrow the primary context limit for an unpopulated active creature", async () => {
    const chat = useChatStore()
    chat.activeTab = "bob"
    chat.tokenUsage.bob = { prompt: 20, completion: 4, cached: 0, lastPrompt: 900 }
    chat.sessionInfo.maxContext = 1000
    chat.modelByTab.alice = { maxContext: 1000 }

    const wrapper = mount(EditorStatus, { props: { instance: { max_context: 1000 } } })
    await wrapper.findAll("button")[1].trigger("click")

    expect(wrapper.text()).not.toContain("common.context")
    expect(wrapper.text()).not.toContain("90%")
  })

  it("shows context usage for the active creature", async () => {
    const chat = useChatStore()
    chat.activeTab = "alice"
    chat.tokenUsage = {
      alice: { prompt: 10, completion: 2, cached: 0, lastPrompt: 100 },
      bob: { prompt: 20, completion: 4, cached: 0, lastPrompt: 900 },
    }
    chat.modelByTab = {
      alice: { maxContext: 1000 },
      bob: { maxContext: 1000 },
    }

    const wrapper = mount(EditorStatus)
    await wrapper.findAll("button")[1].trigger("click")
    expect(wrapper.text()).toContain("100/1.0K (10%)")

    chat.activeTab = "bob"
    await nextTick()
    expect(wrapper.text()).toContain("900/1.0K (90%)")
  })
})
