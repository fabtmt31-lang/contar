(function () {
  const banner = document.getElementById("nfc-badge-banner");
  const bannerText = document.getElementById("nfc-badge-banner-text");
  const cancelBtn = document.getElementById("nfc-badge-cancel");
  const offButtons = document.querySelectorAll(".nfc-badge-off");

  if (!banner || offButtons.length === 0) {
    return; // page sans aucun badge NFC "non associé" à activer
  }

  // Textes traduits, fournis par la page (voir templates/_nfc_badge.html).
  const T = window.NFC_BADGE_TEXT || {};

  let pollTimer = null;
  let pending = null; // { kind, itemId }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function hideBanner() {
    banner.hidden = true;
    stopPolling();
    pending = null;
  }

  async function post(url, formBody) {
    return fetch(url, {
      method: "POST",
      headers: formBody ? { "Content-Type": "application/x-www-form-urlencoded" } : undefined,
      body: formBody,
    });
  }

  async function pollCaptureState() {
    try {
      const res = await fetch(window.NFC_BADGE_API.state);
      const data = await res.json();

      if (data.uid) {
        stopPolling();
        bannerText.textContent = T.found || "";
        const body = new URLSearchParams();
        body.set("uid_tag", data.uid);
        body.set("target", `${pending.kind}:${pending.itemId}`);
        await post(window.NFC_BADGE_API.associate, body);
        window.location.reload();
        return;
      }

      if (data.capturing === false) {
        // Capture expirée sans tag posé, ou annulée ailleurs.
        hideBanner();
      }
    } catch (err) {
      // Réseau momentanément indisponible : on retentera au prochain cycle.
    }
  }

  offButtons.forEach((btn) => {
    btn.addEventListener("click", async () => {
      pending = { kind: btn.dataset.nfcKind, itemId: btn.dataset.nfcItem };
      bannerText.textContent = T.waiting || "";
      banner.hidden = false;

      await post(window.NFC_BADGE_API.start);
      stopPolling();
      pollTimer = setInterval(pollCaptureState, 500);
    });
  });

  if (cancelBtn) {
    cancelBtn.addEventListener("click", async () => {
      await post(window.NFC_BADGE_API.cancel);
      hideBanner();
    });
  }
})();
