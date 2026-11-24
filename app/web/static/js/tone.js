// Réglages → Volume et sortie audio : la tonalité s'applique à chaque
// déplacement d'un curseur, pour régler à l'oreille pendant une lecture.
(function () {
  const form = document.getElementById("tone-form");
  if (!form) {
    return;
  }
  const sliders = Array.from(form.querySelectorAll('input[type="range"]'));
  let timer = null;

  function label(value) {
    const number = Number(value);
    return (number > 0 ? "+" + number : String(number)) + " dB";
  }

  function show() {
    sliders.forEach((slider) => {
      const output = form.querySelector('output[for="' + slider.id + '"]');
      if (output) {
        output.textContent = label(slider.value);
      }
    });
  }

  async function send() {
    const body = new URLSearchParams();
    sliders.forEach((slider) => body.set(slider.name, slider.value));
    try {
      await fetch(form.action, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "fetch" },
        body: body,
      });
    } catch (err) {
      // Réseau momentanément indisponible : le bouton Enregistrer reste là.
    }
  }

  sliders.forEach((slider) => {
    slider.addEventListener("input", () => {
      show();
      clearTimeout(timer);
      timer = setTimeout(send, 150);
    });
  });
})();
