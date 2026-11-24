// Écran Import : l'état du câble USB-C est relu toutes les deux secondes ;
// quand il change (ordinateur branché, rangement du dépôt terminé…), la
// page se recharge pour afficher le nouvel état et le bilan.
(function () {
  const panel = document.getElementById("usb-panel");
  if (!panel) {
    return;
  }
  const url = panel.dataset.url;
  let last = null;

  async function refresh() {
    if (document.hidden) {
      return;
    }
    try {
      const res = await fetch(url, { headers: { "X-Requested-With": "fetch" } });
      if (res.redirected || !res.ok) {
        return;
      }
      const data = await res.json();
      const key = [data.connected, data.busy, data.undervoltage].join("|");
      if (last !== null && key !== last) {
        window.location.reload();
        return;
      }
      last = key;
    } catch (err) {
      // Réseau momentanément indisponible : nouvel essai au prochain tour.
    }
  }

  refresh();
  setInterval(refresh, 2000);
})();
