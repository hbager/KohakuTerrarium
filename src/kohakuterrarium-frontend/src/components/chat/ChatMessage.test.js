import { mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { nextTick } from "vue"

vi.mock("@/stores/instances", () => ({
  useInstancesStore: () => ({ current: null }),
}))

vi.mock("@/utils/i18n", () => ({
  useI18n: () => ({ t: (key) => key }),
}))

vi.mock("@/components/common/MarkdownRenderer.vue", () => ({
  default: { props: ["content"], template: "<div>{{ content }}</div>" },
}))

vi.mock("@/components/chat/ToolCallBlock.vue", () => ({
  default: { template: "<div />" },
}))

vi.mock("@/components/chat/UIEventBlock.vue", () => ({
  default: { template: "<div />" },
}))

vi.mock("@/components/cluster/SiteChip.vue", () => ({
  default: { template: "<span />" },
}))

import ChatMessage from "./ChatMessage.vue"
import { useChatStore } from "@/stores/chat"

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

function pendingPromise() {
  let resolve
  const promise = new Promise((r) => {
    resolve = r
  })
  return { promise, resolve }
}

describe("ChatMessage — edit rerun UX", () => {
  it("closes the inline editor immediately after Save & Rerun starts", async () => {
    const chat = useChatStore()
    const pending = pendingPromise()
    vi.spyOn(chat, "editMessage").mockReturnValue(pending.promise)

    const wrapper = mount(ChatMessage, {
      props: {
        message: {
          id: "u_1_1_2",
          role: "user",
          content: "old text",
          turnIndex: 1,
          userPosition: 0,
          latestBranch: 1,
        },
        messageIdx: 0,
      },
    })

    await wrapper.find('[aria-label="Edit and rerun message"]').trigger("click")
    expect(wrapper.find("textarea").exists()).toBe(true)

    const textarea = wrapper.find("textarea")
    await textarea.setValue("new text")
    await wrapper.findAll("button").find((btn) => btn.text() === "Save & Rerun").trigger("click")
    await nextTick()

    expect(chat.editMessage).toHaveBeenCalledOnce()
    expect(wrapper.find("textarea").exists()).toBe(false)

    pending.resolve(true)
  })
})
