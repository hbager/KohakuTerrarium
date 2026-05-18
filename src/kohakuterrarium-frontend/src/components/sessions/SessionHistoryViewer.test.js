import { beforeEach, afterEach, describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"

vi.mock("@/utils/api", () => ({
  sessionAPI: {
    getHistoryIndex: vi.fn(),
    getHistory: vi.fn(),
  },
}))

vi.mock("@/composables/useDensity", () => ({
  useDensity: () => ({ isCompact: { value: false } }),
}))

vi.mock("vue-router", () => ({
  useRoute: () => ({ params: {} }),
  useRouter: () => ({ push: vi.fn() }),
}))

import SessionHistoryViewer from "./SessionHistoryViewer.vue"
import { sessionAPI } from "@/utils/api"
import { useChatStore } from "@/stores/chat"
import { useSessionDetailStore } from "@/stores/sessionDetail"

async function flushPromises() {
  await Promise.resolve()
  await Promise.resolve()
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.useFakeTimers()
  vi.clearAllMocks()
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value: "visible",
  })
})

afterEach(() => {
  vi.useRealTimers()
})

describe("SessionHistoryViewer — workspace refresh", () => {
  it("polls the active target so saved history reflects new backend events", async () => {
    const detail = useSessionDetailStore()
    detail.name = "session-a"
    const chat = useChatStore()
    sessionAPI.getHistoryIndex.mockResolvedValue({
      meta: { session_id: "session-a", agents: ["root"] },
      targets: ["root"],
    })
    sessionAPI.getHistory
      .mockResolvedValueOnce({
        messages: [],
        events: [{ type: "user_input", content: "first", event_id: 1 }],
      })
      .mockResolvedValueOnce({
        messages: [],
        events: [
          { type: "user_input", content: "first", event_id: 1 },
          { type: "text_chunk", content: "second", event_id: 2 },
        ],
      })

    mount(SessionHistoryViewer, {
      props: { embedded: true },
      global: {
        stubs: {
          ChatPanel: { template: "<div />" },
        },
      },
    })

    await flushPromises()
    expect(sessionAPI.getHistory).toHaveBeenCalledTimes(1)
    expect(chat.messagesByTab.root.map((m) => m.content || m.parts?.[0]?.content).join(" ")).toContain(
      "first",
    )

    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()

    expect(sessionAPI.getHistory).toHaveBeenCalledTimes(2)
    expect(JSON.stringify(chat.messagesByTab.root)).toContain("second")
  })
})
