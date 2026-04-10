/**
 * useArtifactDetector — watches the chat store for assistant messages
 * and scans them for canvas artifacts. Runs globally (App.vue) so
 * detection works regardless of which preset is active.
 *
 * Rescans when:
 *   - New messages arrive (message count changes)
 *   - Processing ends (streaming complete — final scan of the last message)
 */

import { watch } from "vue";

import { useCanvasStore } from "@/stores/canvas";
import { useChatStore } from "@/stores/chat";

export function useArtifactDetector() {
  const chat = useChatStore();
  const canvas = useCanvasStore();

  function scanAll() {
    const tab = chat.activeTab;
    if (!tab) return;
    const msgs = chat.messagesByTab?.[tab] || [];
    for (const m of msgs) {
      canvas.scanMessage(m);
    }
  }

  // Rescan all messages when processing ends (the last streamed
  // message is now complete with full content).
  watch(
    () => chat.processing,
    (processing, prev) => {
      if (!processing && prev) scanAll();
    },
  );

  // Also scan when new messages arrive.
  watch(
    () => {
      const tab = chat.activeTab;
      if (!tab) return 0;
      return chat.messagesByTab?.[tab]?.length || 0;
    },
    () => scanAll(),
  );

  // Scan when the active tab changes (e.g. switching creatures).
  watch(() => chat.activeTab, () => scanAll());
}
