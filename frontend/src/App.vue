<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  applyReviewAction,
  fetchReviewItems,
  type ReviewAction,
  type ReviewItem
} from "./api";

const currentReviewer = "alex";
const items = ref<ReviewItem[]>([]);
const selectedId = ref<string | null>(null);
const isLoading = ref(false);
const errorMessage = ref<string | null>(null);
const noticeMessage = ref<string | null>(null);
const pendingAction = ref<ReviewAction | null>(null);

const ALL_ACTIONS: ReviewAction[] = ["claim", "approve", "reject", "escalate"];
const ACTION_LABELS: Record<ReviewAction, string> = {
  claim: "Claim",
  approve: "Approve",
  reject: "Reject",
  escalate: "Escalate"
};

const selectedItem = computed(
  () => items.value.find((item) => item.id === selectedId.value) ?? items.value[0] ?? null
);

const assigneeLabel = computed(() => {
  const item = selectedItem.value;
  if (!item?.assigned_reviewer) return "None";
  return item.assigned_reviewer === currentReviewer
    ? `${item.assigned_reviewer} (you)`
    : item.assigned_reviewer;
});

const actionHint = computed(() => {
  const item = selectedItem.value;
  if (!item) return "";
  if (item.status === "unassigned") {
    return "Unassigned — claim this item to start reviewing it.";
  }
  if (item.status === "in_review") {
    return item.assigned_reviewer === currentReviewer
      ? "You are reviewing this item. Approve, reject, or escalate to finish it."
      : `In review by ${item.assigned_reviewer}.`;
  }
  return `This item is ${item.status}. No further actions are available.`;
});

// TAKEHOME: The backend owns the workflow rules. Items arrive already
// filtered to the active queue, sorted by urgency, and carrying
// allowed_actions; after a successful action we refetch instead of patching
// local state, so this client can never drift from the server's rules.
async function loadItems(options: { background?: boolean } = {}) {
  if (!options.background) {
    isLoading.value = true;
    errorMessage.value = null;
  }

  try {
    items.value = await fetchReviewItems();
    if (!options.background) {
      selectedId.value = selectedItem.value?.id ?? null;
    }
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : "Something went wrong loading the queue.";
  } finally {
    if (!options.background) {
      isLoading.value = false;
    }
  }
}

async function performAction(action: ReviewAction) {
  if (!selectedItem.value) return;

  pendingAction.value = action;
  errorMessage.value = null;
  noticeMessage.value = null;

  try {
    const updated = await applyReviewAction(selectedItem.value.id, action, currentReviewer);
    await loadItems({ background: true });

    if (items.value.some((item) => item.id === updated.id)) {
      selectedId.value = updated.id;
      if (action === "claim") {
        noticeMessage.value = `${updated.id} is now assigned to you.`;
      }
    } else {
      // The item reached a terminal status and left the active queue.
      selectedId.value = items.value[0]?.id ?? null;
      noticeMessage.value = `${updated.id} ${updated.status}. Showing the next item in the queue.`;
    }
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : "That action could not be completed.";
  } finally {
    pendingAction.value = null;
  }
}

function isActionAllowed(action: ReviewAction) {
  return selectedItem.value?.allowed_actions.includes(action) ?? false;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(value));
}

function relativeAge(value: string) {
  const hours = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 3_600_000));
  if (hours < 1) return "new";
  if (hours < 24) return `${hours}h old`;
  return `${Math.round(hours / 24)}d old`;
}

onMounted(loadItems);
</script>

<template>
  <main class="page-shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">Reviewer workspace</p>
        <h1>Active queue</h1>
      </div>
      <div class="topbar-tools">
        <button class="refresh" type="button" :disabled="isLoading" @click="loadItems()">
          Refresh
        </button>
        <div class="reviewer">Signed in as {{ currentReviewer }}</div>
      </div>
    </header>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
    <p v-if="noticeMessage" class="notice-banner">{{ noticeMessage }}</p>
    <p v-if="isLoading" class="loading">Loading review items...</p>

    <section v-else class="workspace">
      <aside class="queue-list" aria-label="Review queue">
        <p v-if="!items.length" class="queue-empty">No active items — the queue is clear.</p>
        <button
          v-for="item in items"
          :key="item.id"
          class="queue-item"
          :class="{ selected: item.id === selectedItem?.id }"
          type="button"
          @click="selectedId = item.id"
        >
          <span class="queue-title">{{ item.title }}</span>
          <span class="queue-badges">
            <span class="badge" :class="`risk-${item.risk_level}`">{{ item.risk_level }} risk</span>
            <span v-if="item.customer_tier === 'priority'" class="badge tier-priority">priority</span>
            <span class="queue-meta">{{ relativeAge(item.submitted_at) }}</span>
          </span>
          <span class="queue-meta">
            <template v-if="item.status === 'in_review'">
              in review ·
              <strong v-if="item.assigned_reviewer === currentReviewer" class="mine">you</strong>
              <template v-else>{{ item.assigned_reviewer }}</template>
            </template>
            <template v-else>{{ item.status }}</template>
          </span>
        </button>
      </aside>

      <section v-if="selectedItem" class="detail-panel">
        <div class="detail-header">
          <div>
            <p class="eyebrow">{{ selectedItem.id }}</p>
            <h2>{{ selectedItem.title }}</h2>
          </div>
          <span class="status-pill" :class="`status-${selectedItem.status}`">
            {{ selectedItem.status }}
          </span>
        </div>

        <dl class="facts">
          <div>
            <dt>Submitted</dt>
            <dd>{{ formatDate(selectedItem.submitted_at) }} · {{ relativeAge(selectedItem.submitted_at) }}</dd>
          </div>
          <div>
            <dt>Risk</dt>
            <dd>{{ selectedItem.risk_level }}</dd>
          </div>
          <div>
            <dt>Customer</dt>
            <dd>{{ selectedItem.customer_tier }}</dd>
          </div>
          <div>
            <dt>Assignee</dt>
            <dd>{{ assigneeLabel }}</dd>
          </div>
        </dl>

        <p class="summary">{{ selectedItem.summary }}</p>
        <p class="notes">{{ selectedItem.notes_count }} notes on this item</p>

        <p class="action-hint">{{ actionHint }}</p>
        <!-- TAKEHOME: The required rules gate actions on status only, not on
             who claimed the item, so e.g. alex may approve an item sam is
             reviewing. We surface ownership rather than block it; restricting
             decisions to the assignee is a product call (see SUBMISSION.md). -->
        <div class="actions" aria-label="Workflow actions">
          <button
            v-for="action in ALL_ACTIONS"
            :key="action"
            type="button"
            :disabled="Boolean(pendingAction) || !isActionAllowed(action)"
            :title="isActionAllowed(action) ? undefined : actionHint"
            @click="performAction(action)"
          >
            {{ ACTION_LABELS[action] }}
          </button>
        </div>
      </section>

      <section v-else class="detail-panel detail-empty">
        <p>Select an item from the queue to see its details.</p>
      </section>
    </section>
  </main>
</template>
