(function () {
  const els = {
    root: document.getElementById("now-playing"),
    cover: document.getElementById("cover"),
    coverImage: document.getElementById("cover-image"),
    iconBook: document.getElementById("cover-icon-book"),
    iconMusic: document.getElementById("cover-icon-music"),
    title: document.getElementById("title"),
    subtitle: document.getElementById("subtitle"),
    progress: document.getElementById("progress"),
    positionLabel: document.getElementById("position-label"),
    durationLabel: document.getElementById("duration-label"),
    toggleBtn: document.getElementById("btn-toggle"),
    backBtn: document.getElementById("btn-back"),
    forwardBtn: document.getElementById("btn-forward"),
    volDown: document.getElementById("vol-down"),
    volUp: document.getElementById("vol-up"),
    volumeFill: document.getElementById("volume-fill"),
    playlistBadge: document.getElementById("playlist-badge"),
    playlistBadgeName: document.getElementById("playlist-badge-name"),
    sleepBadge: document.getElementById("sleep-badge"),
    sleepBadgeText: document.getElementById("sleep-badge-text"),
  };

  // Textes traduits, fournis par la page (voir templates/now_playing.html).
  const T = window.PLAYER_TEXT || {};

  let seeking = false;
  let lastState = null;

  // Les icônes sont déjà dans la page (dessins SVG) : on montre l'une ou
  // l'autre plutôt que de changer un caractère comme avant.
  function showOnly(button, attribute, value) {
    button.querySelectorAll(`[${attribute}]`).forEach((el) => {
      el.hidden = el.getAttribute(attribute) !== value;
    });
  }

  function formatTime(ms) {
    const totalSeconds = Math.max(0, Math.floor((ms || 0) / 1000));
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${minutes}:${seconds.toString().padStart(2, "0")}`;
  }

  function render(state) {
    lastState = state;

    if (!state.kind) {
      els.root.dataset.state = "empty";
      els.title.textContent = T.emptyTitle || "";
      els.subtitle.textContent = T.emptySubtitle || "";
      els.playlistBadge.hidden = true;
      els.sleepBadge.hidden = true;
      return;
    }

    // Minuterie de coucher : temps restant avant la mise en pause.
    const sleepLeft = state.sleep_remaining_s;
    if (typeof sleepLeft === "number") {
      const minutes = Math.ceil(sleepLeft / 60);
      els.sleepBadgeText.textContent = sleepLeft < 60
        ? (T.sleepSoon || "")
        : (T.sleepMinutes || "").replace("{n}", minutes);
      els.sleepBadge.hidden = false;
    } else {
      els.sleepBadge.hidden = true;
    }

    if (state.playlist_name) {
      els.playlistBadgeName.textContent = state.playlist_name;
      els.playlistBadge.hidden = false;
    } else {
      els.playlistBadge.hidden = true;
    }

    els.root.dataset.state = state.loaded ? "loaded" : "preview";
    els.title.textContent = state.title || "";
    els.subtitle.textContent = state.subtitle || "";
    els.cover.style.setProperty("--item-color", state.color_hex || "#8FB6FF");

    const isTrack = state.kind === "track";
    showOnly(els.backBtn, "data-mode", isTrack ? "track" : "book");
    showOnly(els.forwardBtn, "data-mode", isTrack ? "track" : "book");
    els.backBtn.setAttribute("aria-label", isTrack ? T.prevTrack : T.back10);
    els.forwardBtn.setAttribute("aria-label", isTrack ? T.nextTrack : T.forward10);

    if (state.cover_url) {
      if (els.coverImage.getAttribute("src") !== state.cover_url) {
        els.coverImage.src = state.cover_url;
      }
      els.coverImage.hidden = false;
      els.iconBook.hidden = true;
      els.iconMusic.hidden = true;
    } else {
      els.coverImage.hidden = true;
      els.iconBook.hidden = isTrack;
      els.iconMusic.hidden = !isTrack;
    }

    const duration = state.duration_ms || 0;
    const position = state.position_ms || 0;

    if (!seeking) {
      els.progress.max = duration > 0 ? duration : 100;
      els.progress.value = position;
    }
    els.positionLabel.textContent = formatTime(position);
    els.durationLabel.textContent = formatTime(duration);

    showOnly(els.toggleBtn, "data-icon", state.is_playing ? "pause" : "play");
    els.toggleBtn.setAttribute("aria-label", state.is_playing ? T.pause : T.play);
    els.volumeFill.style.width = `${state.volume || 0}%`;
  }

  async function fetchState() {
    try {
      const res = await fetch(window.API.state);
      render(await res.json());
    } catch (err) {
      // Réseau momentanément indisponible : on retentera au prochain cycle.
    }
  }

  async function post(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const data = await res.json();
    if (data.state) render(data.state);
    return data;
  }

  els.toggleBtn.addEventListener("click", () => {
    if (lastState && lastState.kind && !lastState.loaded) {
      // Rien n'est chargé dans le lecteur : on lance la dernière lecture connue.
      post(window.API.play, { kind: lastState.kind, item_id: lastState.item_id });
    } else if (lastState && lastState.kind) {
      post(window.API.toggle);
    }
  });

  els.backBtn.addEventListener("click", () => post(window.API.skipBack));
  els.forwardBtn.addEventListener("click", () => post(window.API.skipForward));

  els.progress.addEventListener("input", () => { seeking = true; });
  els.progress.addEventListener("change", () => {
    post(window.API.seek, { position_ms: parseInt(els.progress.value, 10) });
    seeking = false;
  });

  els.volDown.addEventListener("click", () => post(window.API.volume, { direction: "down" }));
  els.volUp.addEventListener("click", () => post(window.API.volume, { direction: "up" }));

  fetchState();
  setInterval(fetchState, 1000);
})();
