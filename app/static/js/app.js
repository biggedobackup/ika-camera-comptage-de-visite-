/*
 * IKA COMPTEUR — comportements génériques (aucun JS inline dans les templates).
 *  1. Œil afficher / masquer sur tous les champs mot de passe.
 *  2. Bouton de soumission désactivé + indicateur de chargement pendant l'envoi.
 *  3. Modal de confirmation avant toute suppression (POST + CSRF).
 *  4. Mise en évidence du lien de menu de la page active (complément du rendu serveur).
 *  5. Notifications toast en haut à droite (disparition auto après 5 s).
 *  6. WebSocket temps réel pour les compteurs et passages caméras.
 */
(function () {
  "use strict";

  /* ---------------------------------------------------------------------
   * 1. Afficher / masquer le mot de passe
   * ------------------------------------------------------------------- */
  var compteurChamps = 0;

  function creerBoutonOeil(champ) {
    var bouton = document.createElement("button");
    bouton.type = "button";
    bouton.className = "btn btn-oeil";
    bouton.setAttribute("data-basculer-mot-de-passe", "");
    bouton.setAttribute("aria-controls", champ.id);
    bouton.setAttribute("aria-pressed", "false");
    bouton.setAttribute("aria-label", "Afficher le mot de passe");
    var icone = document.createElement("i");
    icone.className = "bi bi-eye";
    icone.setAttribute("aria-hidden", "true");
    bouton.appendChild(icone);
    return bouton;
  }

  /* Ajoute l'œil aux champs mot de passe qui n'en ont pas (champs écrits sans la macro). */
  function initialiserChampsMotDePasse(racine) {
    racine.querySelectorAll('input[type="password"]').forEach(function (champ) {
      if (!champ.id) {
        compteurChamps += 1;
        champ.id = "mot-de-passe-" + compteurChamps;
      }
      if (document.querySelector('[data-basculer-mot-de-passe][aria-controls="' + champ.id + '"]')) {
        return;
      }
      var groupe = champ.closest(".input-group");
      if (!groupe) {
        groupe = document.createElement("div");
        groupe.className = "input-group";
        champ.parentNode.insertBefore(groupe, champ);
        groupe.appendChild(champ);
      }
      champ.insertAdjacentElement("afterend", creerBoutonOeil(champ));
    });
  }

  function basculerMotDePasse(bouton) {
    var champ = document.getElementById(bouton.getAttribute("aria-controls"));
    if (!champ) {
      return;
    }
    var afficher = champ.type === "password";
    champ.type = afficher ? "text" : "password";
    bouton.setAttribute("aria-pressed", afficher ? "true" : "false");
    bouton.setAttribute("aria-label", afficher ? "Masquer le mot de passe" : "Afficher le mot de passe");
    var icone = bouton.querySelector(".bi");
    if (icone) {
      icone.classList.toggle("bi-eye", !afficher);
      icone.classList.toggle("bi-eye-slash", afficher);
    }
  }

  /* ---------------------------------------------------------------------
   * 2. Soumission : bouton désactivé + indicateur de chargement
   * ------------------------------------------------------------------- */
  function boutonsDuFormulaire(formulaire) {
    var boutons = Array.prototype.slice.call(
      formulaire.querySelectorAll('button[type="submit"], button:not([type]), input[type="submit"]')
    );
    if (formulaire.id) {
      document.querySelectorAll('[form="' + formulaire.id + '"]').forEach(function (bouton) {
        if (bouton.matches('button[type="submit"], button:not([type]), input[type="submit"]')) {
          boutons.push(bouton);
        }
      });
    }
    return boutons;
  }

  function activerChargement(formulaire) {
    boutonsDuFormulaire(formulaire).forEach(function (bouton) {
      if (bouton.disabled) {
        return;
      }
      bouton.disabled = true;
      bouton.setAttribute("aria-busy", "true");
      bouton.setAttribute("data-desactive-pendant-envoi", "");
      if (bouton.tagName === "BUTTON") {
        var indicateur = document.createElement("span");
        indicateur.className = "spinner-border spinner-border-sm";
        indicateur.setAttribute("aria-hidden", "true");
        indicateur.setAttribute("data-indicateur-envoi", "");
        bouton.insertBefore(indicateur, bouton.firstChild);
      }
    });
  }

  function reinitialiserFormulaires() {
    document.querySelectorAll("form[data-envoi-en-cours]").forEach(function (formulaire) {
      formulaire.removeAttribute("data-envoi-en-cours");
    });
    document.querySelectorAll("[data-indicateur-envoi]").forEach(function (indicateur) {
      indicateur.remove();
    });
    document.querySelectorAll("[data-desactive-pendant-envoi]").forEach(function (bouton) {
      bouton.disabled = false;
      bouton.removeAttribute("aria-busy");
      bouton.removeAttribute("data-desactive-pendant-envoi");
    });
  }

  document.addEventListener("submit", function (evenement) {
    var formulaire = evenement.target;
    if (evenement.defaultPrevented || !(formulaire instanceof HTMLFormElement)) {
      return;
    }
    if (formulaire.hasAttribute("data-envoi-en-cours")) {
      evenement.preventDefault(); // double envoi bloqué
      return;
    }
    formulaire.setAttribute("data-envoi-en-cours", "");
    // Désactivation différée : le bouton cliqué reste inclus dans les données envoyées.
    window.setTimeout(function () {
      activerChargement(formulaire);
    }, 0);
  });

  // Retour arrière (cache de navigation) : les boutons redeviennent utilisables.
  window.addEventListener("pageshow", function (evenement) {
    if (evenement.persisted) {
      reinitialiserFormulaires();
    }
  });

  /* ---------------------------------------------------------------------
   * 3. Confirmation avant suppression
   * ------------------------------------------------------------------- */
  function estCheminLocal(url) {
    return typeof url === "string" && url.charAt(0) === "/" && url.charAt(1) !== "/" && url.indexOf("\\") === -1;
  }

  function ouvrirConfirmationSuppression(declencheur) {
    var modal = document.getElementById("modal-suppression");
    var url = declencheur.getAttribute("data-url");
    if (!modal || !estCheminLocal(url) || typeof bootstrap === "undefined") {
      return;
    }
    var formulaire = modal.querySelector("form[data-formulaire-suppression]");
    var message = modal.querySelector("[data-message-suppression]");
    formulaire.setAttribute("action", url);
    message.textContent = declencheur.getAttribute("data-message") || "Voulez-vous vraiment supprimer cet élément ?";
    bootstrap.Modal.getOrCreateInstance(modal).show();
  }

  /* ---------------------------------------------------------------------
   * 4. Lien de menu actif (si le serveur ne l'a pas déjà marqué)
   * ------------------------------------------------------------------- */
  function marquerMenuActif() {
    var menu = document.querySelector("[data-menu-principal]");
    if (!menu || menu.querySelector(".menu-lien.active")) {
      return;
    }
    var chemin = window.location.pathname;
    var meilleur = null;
    menu.querySelectorAll("a.menu-lien[href]").forEach(function (lien) {
      var href = lien.getAttribute("href");
      var prefixe = href.replace(/\/$/, "") + "/";
      if (chemin === href || chemin.indexOf(prefixe) === 0) {
        if (!meilleur || href.length > meilleur.getAttribute("href").length) {
          meilleur = lien;
        }
      }
    });
    if (meilleur) {
      meilleur.classList.add("active");
      meilleur.setAttribute("aria-current", "page");
    }
  }

  /* ---------------------------------------------------------------------
   * Délégation des clics et initialisation
   * ------------------------------------------------------------------- */
  document.addEventListener("click", function (evenement) {
    var oeil = evenement.target.closest("[data-basculer-mot-de-passe]");
    if (oeil) {
      evenement.preventDefault();
      basculerMotDePasse(oeil);
      return;
    }
    var suppression = evenement.target.closest("[data-confirmer-suppression]");
    if (suppression) {
      evenement.preventDefault();
      ouvrirConfirmationSuppression(suppression);
    }
  });

  /* ---------------------------------------------------------------------
   * 5. Notifications toast : affichage en haut à droite + disparition auto
   * ------------------------------------------------------------------- */
  function initialiserNotifications() {
    var notifications = document.querySelectorAll("[data-notification]");
    if (!notifications.length) {
      return;
    }
    notifications.forEach(function (toast) {
      if (typeof bootstrap !== "undefined" && bootstrap.Toast) {
        bootstrap.Toast.getOrCreateInstance(toast, { autohide: true, delay: 5000 }).show();
      } else {
        // Sans Bootstrap : repli, disparaît après 5 s.
        window.setTimeout(function () {
          toast.remove();
        }, 5000);
      }
    });
  }

  /* ---------------------------------------------------------------------
   * 6. WebSocket temps réel pour les compteurs et passages caméras
   * ------------------------------------------------------------------- */
  function initialiserWebSocketComptage() {
    var entreesEl = document.querySelector("[data-comptage-entrees]");
    var tableauPassages = document.querySelector("[data-tableau-passages]");
    var tableauCameras = document.querySelector("[data-tableau-cameras]");

    if (!entreesEl && !tableauPassages && !tableauCameras) {
      return;
    }

    var protocole = window.location.protocol === "https:" ? "wss:" : "ws:";
    var wsUrl = protocole + "//" + window.location.host + "/ws/comptage";
    var ws = null;
    var delaiReconnexion = 2500;

    function animerChiffre(element, nouvelleValeur) {
      if (!element || nouvelleValeur === undefined) return;
      var ancienne = element.textContent.trim();
      if (ancienne !== String(nouvelleValeur)) {
        element.textContent = nouvelleValeur;
        element.classList.add("bg-warning-subtle", "rounded", "px-1");
        setTimeout(function () {
          element.classList.remove("bg-warning-subtle", "rounded", "px-1");
        }, 1200);
      }
    }

    function connecter() {
      try {
        ws = new WebSocket(wsUrl);
      } catch (e) {
        return;
      }

      ws.onopen = function () {
        var badge = document.getElementById("badge-temps-reel");
        if (badge) {
          badge.className = "badge bg-success-subtle text-success border border-success-subtle px-3 py-2 fs-6";
        }
      };

      ws.onmessage = function (event) {
        try {
          var msg = JSON.parse(event.data);
          if (msg.indicateurs) {
            animerChiffre(document.querySelector("[data-comptage-entrees]"), msg.indicateurs.entrees_jour);
            animerChiffre(document.querySelector("[data-comptage-uniques]"), msg.indicateurs.visiteurs_uniques_jour);
            animerChiffre(document.querySelector("[data-comptage-personnel]"), msg.indicateurs.personnel_exclu_jour);
            var activesEl = document.querySelector("[data-comptage-cameras-actives]");
            if (activesEl) {
              animerChiffre(activesEl, msg.indicateurs.cameras_en_ligne + " / " + msg.indicateurs.cameras_total);
            }
          }

          if (msg.type === "nouveau_passage" && tableauPassages) {
            var tr = document.createElement("tr");
            tr.className = "table-success";
            tr.innerHTML =
              '<td class="col-numero">⚡</td>' +
              '<td class="fw-medium">' + (msg.horodatage || "À l'instant") + "</td>" +
              '<td><div class="fw-semibold">' + (msg.camera_nom || msg.camera_sn) + '</div><code class="small text-muted">' + msg.camera_sn + "</code></td>" +
              '<td class="text-center fw-bold text-primary">' + (msg.entrees || 0) + "</td>" +
              '<td class="text-center fw-medium text-secondary">' + (msg.sorties || 0) + "</td>" +
              '<td class="text-center fw-bold text-success">' + (msg.visiteurs_uniques || 0) + "</td>" +
              '<td class="text-center text-warning">' + (msg.visiteurs_recidives || 0) + "</td>" +
              '<td class="text-center text-muted">' + (msg.personnel_exclu || 0) + "</td>" +
              '<td class="text-center">' + (msg.passants || 0) + "</td>";
            tableauPassages.insertBefore(tr, tableauPassages.firstChild);
            setTimeout(function () {
              tr.classList.remove("table-success");
            }, 3000);
          }

          if (msg.type === "heartbeat" && tableauCameras) {
            var camRow = tableauCameras.querySelector('[data-camera-sn="' + msg.camera_sn + '"]');
            if (camRow) {
              var statutCol = camRow.querySelector("[data-colonne-statut]");
              if (statutCol) {
                statutCol.innerHTML = '<span class="badge bg-success-subtle text-success border border-success-subtle"><i class="bi bi-check-circle-fill me-1"></i>En ligne</span>';
              }
              var hbCol = camRow.querySelector("[data-colonne-heartbeat]");
              if (hbCol && msg.dernier_heartbeat) {
                hbCol.textContent = msg.dernier_heartbeat;
              }
            }
          }
        } catch (err) {}
      };

      ws.onclose = function () {
        var badge = document.getElementById("badge-temps-reel");
        if (badge) {
          badge.className = "badge bg-warning-subtle text-warning border border-warning-subtle px-3 py-2 fs-6";
        }
        setTimeout(connecter, delaiReconnexion);
      };
    }

    connecter();
  }

  function initialiser() {
    initialiserChampsMotDePasse(document);
    marquerMenuActif();
    initialiserNotifications();
    initialiserWebSocketComptage();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialiser);
  } else {
    initialiser();
  }
})();

