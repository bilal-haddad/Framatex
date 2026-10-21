'use strict';
// Legacy screens load several independent APIs before mounting. Serialize
// top-level screen changes so an older response cannot overwrite a newer page.
// Includes direct dossier links, not only sidebar navigation. Error recovery
// must not poison the queue; per-request timeouts bound every pending screen.
let runtimeNavigationTail = Promise.resolve();
function runtimeNavigateInOrder(action) {
  const result = runtimeNavigationTail.then(action);
  runtimeNavigationTail = result.catch(() => {});
  return result;
}
const runtimeOriginalNavigate = navigate;
navigate = function(...args) { return runtimeNavigateInOrder(() => runtimeOriginalNavigate(...args)); };
const runtimeOriginalOpenLaunch = openLaunch;
openLaunch = function(...args) { return runtimeNavigateInOrder(() => runtimeOriginalOpenLaunch(...args)); };
