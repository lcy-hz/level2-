import { inject, onBeforeUnmount, watch } from 'vue'

// A snapshot must not silently omit evidence whose load is still in progress.
export function useEvidencePending(source) {
  const setPending = inject('setEvidencePending', null)
  const token = Symbol('evidence-request')
  watch(source, value => setPending?.(token, Boolean(value)), { immediate: true, flush: 'sync' })
  onBeforeUnmount(() => setPending?.(token, false))
}
