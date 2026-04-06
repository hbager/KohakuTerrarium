<template>
  <div class="h-full flex flex-col bg-warm-50 dark:bg-warm-900">
    <!-- Header -->
    <div class="flex items-center gap-2 px-3 py-2 border-b border-warm-200 dark:border-warm-700 shrink-0">
      <button
        class="w-6 h-6 flex items-center justify-center rounded text-warm-400 hover:text-warm-600 dark:hover:text-warm-300 transition-colors"
        title="Back to instance"
        @click="$router.push(`/instances/${$route.params.id}`)"
      >
        <div class="i-carbon-arrow-left text-sm" />
      </button>
      <span class="text-xs font-medium text-warm-500 dark:text-warm-400 truncate flex-1">Files</span>
      <button
        class="w-6 h-6 flex items-center justify-center rounded text-warm-400 hover:text-warm-600 dark:hover:text-warm-300 transition-colors"
        title="Refresh"
        @click="refresh"
      >
        <div class="i-carbon-renew text-sm" />
      </button>
    </div>

    <!-- Tree -->
    <div class="flex-1 overflow-y-auto py-1 text-xs">
      <template v-if="tree">
        <FileTreeNode
          v-for="child in tree.children || []"
          :key="child.path"
          :node="child"
          :depth="0"
          @select="onSelect"
        />
      </template>
      <div v-else-if="loading" class="px-3 py-4 text-warm-400 text-center">
        Loading...
      </div>
      <div v-else class="px-3 py-4 text-warm-400 text-center">
        No files
      </div>
    </div>
  </div>
</template>

<script setup>
import FileTreeNode from "@/components/editor/FileTreeNode.vue";
import { useEditorStore } from "@/stores/editor";

const props = defineProps({
  root: { type: String, required: true },
});

const emit = defineEmits(["select"]);
const editor = useEditorStore();

const tree = computed(() => editor.treeData);
const loading = ref(false);

// Poll interval for auto-refresh (3 seconds)
let _pollTimer = null;

watch(
  () => props.root,
  (val) => {
    if (val) {
      editor.setTreeRoot(val);
      _startPolling();
    }
  },
  { immediate: true },
);

onUnmounted(() => {
  _stopPolling();
});

function _startPolling() {
  _stopPolling();
  _pollTimer = setInterval(() => {
    if (editor.treeRoot) {
      editor.refreshTree();
    }
  }, 3000);
}

function _stopPolling() {
  if (_pollTimer) {
    clearInterval(_pollTimer);
    _pollTimer = null;
  }
}

function onSelect(path) {
  emit("select", path);
}

function refresh() {
  editor.refreshTree();
}

defineExpose({ refresh });
</script>
