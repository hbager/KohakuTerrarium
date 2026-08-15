import { describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import { nextTick } from "vue"

vi.mock("@/utils/i18n", () => ({
  useI18n: () => ({
    t: (key) => key,
  }),
}))

import PresetEditor from "./PresetEditor.vue"

const passthrough = { template: "<div><slot /></div>" }

function mountEditor(presetOverrides = {}) {
  return mount(PresetEditor, {
    props: {
      mode: "edit",
      backends: [{ name: "openrouter" }],
      preset: {
        name: "mimo-v2-pro",
        model: "minimax/mimo-v2-pro",
        provider: "openrouter",
        max_context: 128000,
        max_output: 16384,
        source: "user",
        is_default: false,
        variation_groups: {
          reasoning: { xhigh: { reasoning_effort: "xhigh" } },
          speed: { fast: { service_tier: "fast" } },
        },
        ...presetOverrides,
      },
    },
    global: {
      stubs: {
        "el-button": { template: "<button @click='$emit(\"click\")'><slot /></button>" },
        "el-tag": passthrough,
        "el-input": { template: "<div />" },
        "el-input-number": { template: "<div />" },
        "el-option": {
          props: ["value", "label"],
          template: "<option :value='value'>{{ label }}</option>",
        },
        "el-select": {
          props: ["modelValue"],
          emits: ["update:modelValue"],
          template:
            "<select :value='modelValue' @change='$emit(\"update:modelValue\", $event.target.value)'><slot /></select>",
        },
      },
    },
  })
}

describe("PresetEditor default selector", () => {
  it("emits selected preview variations when setting the default", async () => {
    const wrapper = mountEditor()
    const selects = wrapper.findAll("select")

    await selects.at(-2).setValue("xhigh")
    await selects.at(-1).setValue("fast")
    expect(wrapper.text()).toContain('"reasoning_effort": "xhigh"')
    expect(wrapper.text()).toContain('"service_tier": "fast"')
  })

  it("shows the default badge without exposing a set-default action", async () => {
    const wrapper = mountEditor({ is_default: true })
    await nextTick()

    expect(wrapper.text()).toContain("settings.models.isDefault")
    expect(wrapper.text()).not.toContain("settings.models.setAsDefault")
  })
})
