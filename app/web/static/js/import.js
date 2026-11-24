// Écran Import : le cadre « Clé USB » est relu toutes les deux secondes pour
// suivre la clé branchée et l'avancement d'un import (voir
// templates/_import_usb.html et la route /import/cle).
(function () {
  const panel = document.getElementById("usb-panel");
  if (!panel) {
    return;
  }
  const url = panel.dataset.url;
  let lastHtml = null;
  let busy = false;

  function openFolds() {
    return Array.from(panel.querySelectorAll("details[open][data-keep]")).map((d) => d.dataset.keep);
  }

  async function refresh() {
    if (busy || document.hidden) {
      return;
    }
    busy = true;
    try {
      const res = await fetch(url, { headers: { "X-Requested-With": "fetch" } });
      // Session expirée : la boîte renvoie vers la page de connexion. On
      // recharge la page entière plutôt que d'afficher cette page dans le cadre.
      if (res.redirected) {
        window.location.reload();
        return;
      }
      if (!res.ok) {
        return;
      }
      const html = await res.text();
      if (html !== lastHtml) {
        if (lastHtml !== null) {
          const keep = openFolds();
          panel.innerHTML = html;
          keep.forEach((name) => {
            const fold = panel.querySelector('details[data-keep="' + name + '"]');
            if (fold) {
              fold.open = true;
            }
          });
        }
        lastHtml = html;
      }
    } catch (err) {
      // Réseau momentanément indisponible : nouvel essai au prochain tour.
    } finally {
      busy = false;
    }
  }

  refresh();
  setInterval(refresh, 2000);
})();
