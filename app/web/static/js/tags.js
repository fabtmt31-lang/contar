// Page Tags, et étape « Tags maîtres » de l'assistant de bienvenue.
// Trois usages de la même capture (« posez un tag sur le lecteur ») :
// - associer un tag à une histoire ou à un album ;
// - déclarer un tag maître (import par clé USB) ;
// et, sans capture, donner un nom à un tag déjà associé.
// Chaque bloc ne s'active que si ses éléments sont dans la page.
(function () {
  const startBtn = document.getElementById("capture-start");
  const banner = document.getElementById("capture-banner");
  const bannerText = document.getElementById("capture-banner-text");
  const cancelBtn = document.getElementById("capture-cancel");

  const assignSection = document.getElementById("assign-section");
  const assignUidLabel = document.getElementById("assign-uid");
  const assignUidField = document.getElementById("assign-uid-field");
  const assignName = document.getElementById("assign-name");

  // Tags maîtres : le tag posé est enregistré tout de suite comme tag
  // « ajouter » ou « remplacer ».
  const masterButtons = document.querySelectorAll(".master-capture");
  const masterForm = document.getElementById("master-form");
  const masterRole = document.getElementById("master-role");
  const masterUid = document.getElementById("master-uid");
  let pendingRole = null;

  const API = window.TAGS_API || {};
  const TEXT = window.TAGS_TEXT || {};
  let pollTimer = null;

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function hideBanner() {
    if (banner) {
      banner.hidden = true;
    }
    stopPolling();
  }

  async function post(url) {
    return fetch(url, { method: "POST" });
  }

  async function pollCaptureState() {
    try {
      const res = await fetch(API.state);
      const data = await res.json();

      if (data.uid) {
        hideBanner();
        if (pendingRole && masterForm) {
          masterRole.value = pendingRole;
          masterUid.value = data.uid;
          masterForm.submit();
          return;
        }
        if (assignSection) {
          assignUidLabel.textContent = data.uid;
          assignUidField.value = data.uid;
          if (assignName) {
            assignName.value = data.name || "";   // nom déjà donné à ce tag
          }
          assignSection.hidden = false;
        }
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

  async function startCapture(message) {
    if (!banner) {
      return;
    }
    if (assignSection) {
      assignSection.hidden = true;
    }
    bannerText.textContent = message || "";
    banner.hidden = false;
    banner.scrollIntoView({ block: "nearest" });

    await post(API.start);
    stopPolling();
    pollTimer = setInterval(pollCaptureState, 500);
  }

  masterButtons.forEach((button) => {
    button.addEventListener("click", () => {
      pendingRole = button.dataset.role;
      startCapture(TEXT.waitingMaster);
    });
  });

  if (startBtn) {
    startBtn.addEventListener("click", () => {
      pendingRole = null;
      startCapture(TEXT.waiting);
    });
  }

  if (cancelBtn) {
    cancelBtn.addEventListener("click", async () => {
      pendingRole = null;
      await post(API.cancel);
      hideBanner();
    });
  }

  // Nommer ou renommer un tag : une simple question, puis l'envoi.
  document.querySelectorAll("form.tag-rename").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const answer = window.prompt(form.dataset.prompt || "", form.dataset.current || "");
      if (answer === null) {
        event.preventDefault();
        return;
      }
      form.elements.tag_name.value = answer.trim();
    });
  });
})();
