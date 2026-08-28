#!/usr/bin/env bash
# Compile the manuscript to a preview PDF inside a pinned TeX Live container.
#
# The image is pinned by digest and the container runs with no network, so the
# build depends on nothing but the source in this directory. SOURCE_DATE_EPOCH
# is fixed so repeated builds of unchanged source produce identical bytes, and
# so \today does not drift with the wall clock.
set -euo pipefail

IMAGE="texlive/texlive:TL2025-historic@sha256:5912d6a33798957f4cd6ff1673819209f59300c378033d25066feb93270b90ce"
SOURCE_EPOCH="${SOURCE_DATE_EPOCH:-1787788800}"   # 2026-08-27T00:00:00Z
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for pass in 1 2 3; do
  docker run --rm --network none \
    --env "SOURCE_DATE_EPOCH=${SOURCE_EPOCH}" \
    --env FORCE_SOURCE_DATE=1 \
    --env TEXMFVAR=/tmp/texmf-var \
    --env HOME=/tmp \
    --user "$(id -u):$(id -g)" \
    --volume "${HERE}:/work" \
    --workdir /work \
    "${IMAGE}" \
    pdflatex -interaction=nonstopmode -halt-on-error -file-line-error main.tex >/dev/null
done

if grep -qE "LaTeX Warning: (Citation|Reference) .* undefined" "${HERE}/main.log"; then
  echo "unresolved citations or references; see main.log" >&2
  exit 1
fi

echo "built ${HERE}/main.pdf"
