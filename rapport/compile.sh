#!/usr/bin/env bash
# Compilation script for the academic report
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Compilation du Rapport Académique (LaTeX) ==="
echo "1. Première passe pdflatex..."
pdflatex -interaction=nonstopmode main.tex > /dev/null 2>&1 || true

echo "2. Deuxième passe pdflatex (indexation et tables)..."
pdflatex -interaction=nonstopmode main.tex > /dev/null 2>&1 || true

echo "3. Troisième passe pdflatex (consolidation finale)..."
pdflatex -interaction=nonstopmode main.tex

echo ""
echo "=== Rapport compilé avec succès ! ==="
echo "Fichier PDF généré : $SCRIPT_DIR/main.pdf"
ls -lh main.pdf
