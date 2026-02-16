# Add this to your /a0/usr/hardening/install_all.sh after the other layer installations

echo ""
echo "========================================"
echo "Layer 5: Translation Layer (BST)"
echo "========================================"
if [[ -d "$HARDENING_DIR/translation-layer" ]]; then
    bash "$HARDENING_DIR/translation-layer/install_translation_layer.sh"
else
    echo "⚠ translation-layer/ not found, skipping"
fi
