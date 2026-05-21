import { describe, expect, it } from "vitest"

import source from "./MarkdownRenderer.vue?raw"

describe("MarkdownRenderer — bundle hygiene", () => {
  it("does not import the full highlight.js bundle", () => {
    expect(source).not.toContain('from "highlight.js"')
    expect(source).not.toContain("from 'highlight.js'")
    expect(source).toContain('from "highlight.js/lib/core"')
  })
})
