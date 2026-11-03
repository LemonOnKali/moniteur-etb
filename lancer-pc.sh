#!/bin/sh
# Moniteur Pokémon 30 ans : lancement direct sur ce PC (Linux, macOS, Raspberry Pi).
# Surveille les grandes enseignes qui bloquent les serveurs GitHub
# (Carrefour, King Jouet, Cultura, Amazon…). « ./lancer-pc.sh tout » surveille
# aussi toutes les boutiques.
cd "$(dirname "$0")" || exit 1
PY=python3
command -v "$PY" >/dev/null 2>&1 || PY=python
OPTION=""
[ "$1" = "tout" ] && OPTION="--tout"
# Mise à jour automatique si le dossier vient de « git clone ».
[ -d .git ] && command -v git >/dev/null 2>&1 && git pull --ff-only --quiet
while true; do
  "$PY" moniteur.py --pc $OPTION
  echo "Le moniteur s'est arrêté. Nouveau départ dans 30 secondes (Ctrl+C deux fois pour quitter)."
  sleep 30
done
