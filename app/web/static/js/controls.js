(function () {
  const banner = document.getElementById("capture-banner");
  const bannerText = document.getElementById("capture-banner-text");
  const cancelBtn = document.getElementById("capture-cancel");

  const assignActionForm = document.getElementById("assign-action-form");
  const assignActionField = document.getElementById("assign-action-field");
  const assignActionCode = document.getElementById("assign-action-code");

  const assignComboForm = document.getElementById("assign-combo-form");
  const assignComboSlot = document.getElementById("assign-combo-slot");
  const assignComboCode = document.getElementById("assign-combo-code");

  // Textes traduits, fournis par la page (voir templates/settings_controls.html).
  const T = window.CONTROLS_TEXT || {};

  let pollTimer = null;
  let pendingTarget = null; // { kind: "action", action } ou { kind: "combo", slot }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function hideBanner() {
    banner.hidden = true;
    stopPolling();
    pendingTarget = null;
  }

  async function post(url) {
    return fetch(url, { method: "POST" });
  }

  async function pollCaptureState() {
    try {
      const res = await fetch(window.CONTROLS_API.state);
      const data = await res.json();

      if (data.code) {
        stopPolling();
        bannerText.textContent = (T.found || "").replace("{label}", data.label || data.code);
        if (pendingTarget && pendingTarget.kind === "action") {
          assignActionField.value = pendingTarget.action;
          assignActionCode.value = data.code;
          assignActionForm.submit();
        } else if (pendingTarget && pendingTarget.kind === "combo") {
          assignComboSlot.value = pendingTarget.slot;
          assignComboCode.value = data.code;
          assignComboForm.submit();
        }
        return;
      }

      if (data.capturing === false) {
        // Capture expirée sans appui détecté, ou annulée ailleurs.
        hideBanner();
      }
    } catch (err) {
      // Réseau momentanément indisponible : on retentera au prochain cycle.
    }
  }

  document.querySelectorAll(".btn-capture-start").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const kind = btn.dataset.captureKind;
      const label = btn.dataset.captureLabel || "";

      pendingTarget =
        kind === "combo"
          ? { kind: "combo", slot: btn.dataset.captureSlot }
          : { kind: "action", action: btn.dataset.captureAction };

      bannerText.textContent = (T.press || "").replace("{label}", label);
      banner.hidden = false;

      await post(window.CONTROLS_API.start);
      stopPolling();
      pollTimer = setInterval(pollCaptureState, 500);
    });
  });

  cancelBtn.addEventListener("click", async () => {
    await post(window.CONTROLS_API.cancel);
    hideBanner();
  });
})();
