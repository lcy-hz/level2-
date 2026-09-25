export function evidencePanelKey(document, loadSequence) {
  return `${document?.id || `${document?.mode}:${document?.day}`}:${loadSequence}`
}

export function requestGeneration() {
  let generation = 0
  return {
    begin: () => ++generation,
    invalidate: () => ++generation,
    accepts: id => id === generation,
  }
}
