# Framework Computer's macropad rules.mk, plus one line to build panel_palette.c.
#
# Original: https://github.com/FrameworkComputer/qmk_firmware, branch fl16-2025
# Copyright (C) 2022 Framework Computer
# Modification (the SRC line below): Copyright (C) 2026 Giulio Bramanti
# SPDX-License-Identifier: GPL-2.0-or-later

RGB_MATRIX_ENABLE = yes
RGB_MATRIX_DRIVER = IS31FL3743A

# Per-key panel palette. Ours, not Framework's: see panel_palette.c.
SRC += panel_palette.c
